#!/usr/bin/env python3
"""Offline agent smoke test (Phase 1).

Runs EVERY agent against a mocked LLM transport — no GPU, no Ollama/OpenAI
server, no network, no Godot — and prints each agent's validated Pydantic
output. Exits non-zero if any agent fails to produce a schema-conformant
result.

Usage:
    python scripts/agent_smoke.py            # run all agents
    python scripts/agent_smoke.py designer   # run one agent by key
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

# Make `backend` importable when run from the repo root or elsewhere.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Deterministic offline environment before any settings are read.
import os  # noqa: E402

os.environ.setdefault("LLM_BACKEND", "ollama")

from pydantic import BaseModel  # noqa: E402

from backend.agents.architect import ArchitectAgent  # noqa: E402
from backend.agents.art_director import ArtDirectorAgent  # noqa: E402
from backend.agents.coder import CoderAgent  # noqa: E402
from backend.agents.designer import GameDesignerAgent  # noqa: E402
from backend.agents.dialogue_writer import DialogueWriterAgent  # noqa: E402
from backend.agents.level_generator import LevelGeneratorAgent  # noqa: E402
from backend.agents.localization import LocalizationManagerAgent  # noqa: E402
from backend.agents.playtester import AIPlaytesterAgent  # noqa: E402
from backend.agents.prompt_refiner import PromptRefinerAgent  # noqa: E402
from backend.agents.qa import QAAgent  # noqa: E402
from backend.agents.quest_designer import QuestDesignerAgent  # noqa: E402
from backend.schemas.agent_schemas import (  # noqa: E402
    ArchitectInput,
    ArchitecturePlan,
    ArtDirectorInput,
    AssetPromptsOutput,
    Corridor,
    CoderInput,
    CoderOutput,
    DialogueChoice,
    DialogueNode,
    DialogueTree,
    DialogueTreeList,
    DialogueWriterInput,
    DesignerInput,
    GameDesignDocument,
    GeneratedFile,
    LevelGeneratorInput,
    LevelLayout,
    LocalizationInput,
    LocalizationOutput,
    PlaytestConfig,
    PlaytestReport,
    PromptRefinerInput,
    PromptUpdates,
    QAInput,
    QAReport,
    QuestDesignerInput,
    QuestGraph,
    QuestGraphList,
    QuestStage,
    Room,
    WizardInput,
)

# --------------------------------------------------------------------------- #
# Mocked transport: replaces LLMClient._complete so the REAL validate/repair
# loop in llm_client.generate runs, but no server is ever contacted.
# --------------------------------------------------------------------------- #


class ScriptedTransport:
    """Queue of raw JSON texts returned by the faked _complete() transport."""

    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.requests: list[dict[str, Any]] = []

    async def _complete(self, *, messages, model, temperature, max_tokens, schema, schema_name=""):  # noqa: ANN001
        self.requests.append({"model": model, "max_tokens": max_tokens, "schema_name": schema_name})
        return self.texts[min(len(self.requests) - 1, len(self.texts) - 1)]


def install_transport(texts: list[str]) -> ScriptedTransport:
    import backend.services.llm_client as llm_client

    transport = ScriptedTransport(texts)
    llm_client.LLMClient._complete = ScriptedTransport._complete.__get__(transport)  # type: ignore[attr-defined]
    return transport


# --------------------------------------------------------------------------- #
# Sample data (mirrors tests/test_agents_contracts.py)
# --------------------------------------------------------------------------- #

WIZARD = WizardInput(
    genre="action-adventure",
    perspective="top-down",
    art_style="pixel-art",
    setting="haunted forest",
    scale="small",
    controls={"move": "wasd", "interact": "e"},
    text_description="A tiny haunted-forest adventure.",
    project_name="smoke-proj",
    quest_complexity="simple",
    dialogue_depth="linear",
)

GDD = GameDesignDocument(
    title="Whispering Woods",
    genre="action-adventure",
    perspective="top-down",
    art_style="pixel-art",
    setting="haunted forest",
    scale="small",
    core_mechanics=["exploration", "light puzzles"],
    target_audience="casual",
    unique_selling_points=["atmosphere"],
    module_dependencies=["player_controller"],
    estimated_modules=["player_controller", "interaction_system"],
    quest_complexity="simple",
    dialogue_depth="linear",
)

ARCH = ArchitecturePlan(
    scene_tree={"root": "Main"},
    required_modules=[{"id": "player_controller", "purpose": "movement"}],
    signal_contracts=[{"name": "module_player_died", "publisher": "player_controller", "subscribers": ["hud"]}],
    asset_slots_needed=["player", "background"],
)

ARCH_WITH_LEVELS = ArchitecturePlan(
    scene_tree={"root": "Main"},
    required_modules=[{"id": "level_generator", "purpose": "procedural levels"}],
    signal_contracts=[],
    asset_slots_needed=["tileset"],
    level_parameters={
        "algorithm": "bsp",
        "grid_width": 100,
        "grid_height": 100,
        "min_rooms": 4,
        "max_rooms": 8,
        "min_room_size": [5, 5],
        "max_room_size": [15, 15],
        "corridor_width": 3,
        "poi_density": 0.2,
        "enemy_density": 0.3,
        "item_density": 0.2,
    },
)

CODER_OUT = CoderOutput(
    files=[
        GeneratedFile(
            path="modules/player_controller/player.gd",
            content="extends CharacterBody2D\n\nfunc _ready() -> void:\n\tpass\n",
            file_type="gdscript",
            module_id="player_controller",
        )
    ],
    modules_created=["player_controller"],
    signals_registered=["module_player_died"],
)

QUEST_LIST_TEXT = json.dumps(
    {
        "quests": [
            {
                "quest_id": "q1",
                "title": "Find the Lantern",
                "description": "Retrieve the lost lantern.",
                "stages": [
                    {"id": "s1", "description": "Talk to the elder", "type": "intro"},
                    {"id": "s2", "description": "Enter the cave", "type": "objective"},
                    {"id": "s3", "description": "Return the lantern", "type": "outro",
                     "rewards": [{"type": "item", "id": "lantern_blessed"}]},
                ],
                "dependencies": [],
                "npcs_involved": ["elder"],
                "items_required": ["lantern"],
            }
        ]
    }
)

DIALOGUE_LIST_TEXT = json.dumps(
    {
        "dialogues": [
            {
                "dialogue_id": "d1",
                "npc_id": "elder",
                "trigger": "approach",
                "nodes": [
                    {"id": "n1", "speaker": "elder", "text_key": "d1_n1",
                     "choices": [{"text_key": "d1_n1_c1", "next": "n2"}]},
                    {"id": "n2", "speaker": "elder", "text_key": "d1_n2", "choices": []},
                ],
                "conditions": {},
            }
        ]
    }
)

LEVEL_LAYOUT_TEXT = json.dumps(
    {
        "algorithm": "bsp",
        "width": 100,
        "height": 100,
        "rooms": [
            {"x": 0, "y": 0, "width": 10, "height": 10, "room_type": "start"},
            {"x": 50, "y": 50, "width": 10, "height": 10, "room_type": "end"},
        ],
        "corridors": [{"start": [5, 5], "end": [50, 50], "width": 2}],
        "points_of_interest": [],
        "enemy_spawn_points": [[7, 7]],
        "item_spawn_points": [],
        "start_room": "start",
        "end_room": "end",
    }
)

LOCALIZATION_TEXT = json.dumps(
    {
        "entries": [{"key": "d1_n1", "value": "Hello, traveler.", "category": "dialogue"}],
        "localization_files": [{"locale": "en", "strings": {"d1_n1": "Hello, traveler."}}],
        "missing_keys": [],
    }
)

ART_PROMPTS_TEXT = json.dumps(
    {
        "prompts": [
            {"slot": "player", "prompt": "cute pixel hero sprite", "negative_prompt": "blurry",
             "width": 512, "height": 512, "style": "pixel-art"}
        ],
        "assets": [],
    }
)

PROMPT_UPDATES_TEXT = json.dumps(
    {"updates": [{"agent_name": "coder", "updated_prompt": "Always type your GDScript."}]}
)

CODER_TEXT = json.dumps(CODER_OUT.model_dump(mode="json"))


# --------------------------------------------------------------------------- #
# One smoke case per agent
# --------------------------------------------------------------------------- #


async def smoke_designer() -> BaseModel:
    install_transport([json.dumps(GDD.model_dump(mode="json"))])
    return await GameDesignerAgent().execute(DesignerInput(wizard_input=WIZARD))


async def smoke_architect() -> BaseModel:
    install_transport([json.dumps(ARCH.model_dump(mode="json"))])
    return await ArchitectAgent().execute(ArchitectInput(design_document=GDD))


async def smoke_quest_designer() -> BaseModel:
    install_transport([QUEST_LIST_TEXT])
    return await QuestDesignerAgent().execute(
        QuestDesignerInput(design_document=GDD, npc_registry=["elder"], item_registry=["lantern"])
    )


async def smoke_dialogue_writer() -> BaseModel:
    install_transport([DIALOGUE_LIST_TEXT])
    return await DialogueWriterAgent().execute(
        DialogueWriterInput(design_document=GDD, localization_keys=["d1_n1", "d1_n1_c1", "d1_n2"])
    )


async def smoke_art_director() -> BaseModel:
    install_transport([ART_PROMPTS_TEXT])
    return await ArtDirectorAgent().execute(ArtDirectorInput(architecture_plan=ARCH))


async def smoke_prompt_refiner() -> BaseModel:
    install_transport([PROMPT_UPDATES_TEXT])
    return await PromptRefinerAgent().execute(PromptRefinerInput(generation_history=[]))


async def smoke_level_generator() -> BaseModel:
    install_transport([LEVEL_LAYOUT_TEXT])
    return await LevelGeneratorAgent().execute(LevelGeneratorInput(architecture_plan=ARCH_WITH_LEVELS))


async def smoke_localization() -> BaseModel:
    install_transport([LOCALIZATION_TEXT])
    return await LocalizationManagerAgent().execute(LocalizationInput())


async def smoke_coder() -> BaseModel:
    install_transport([CODER_TEXT])
    return await CoderAgent().execute(CoderInput(architecture_plan=ARCH))


async def smoke_qa() -> BaseModel:
    # deterministic: no LLM call at all
    return await QAAgent().execute(QAInput(coder_output=CODER_OUT))


async def smoke_playtester() -> BaseModel:
    # deterministic/offline-safe: without Godot it returns a failure report
    with tempfile.TemporaryDirectory() as tmp:
        return await AIPlaytesterAgent(godot_headless_path="godot-headless-missing").execute(
            PlaytestConfig(workspace_path=str(Path(tmp) / "no-project"))
        )


SMOKE_CASES: dict[str, tuple[type[BaseModel], Callable[[], Awaitable[BaseModel]]]] = {
    "designer": (GameDesignDocument, smoke_designer),
    "architect": (ArchitecturePlan, smoke_architect),
    "quest_designer": (QuestGraphList, smoke_quest_designer),
    "dialogue_writer": (DialogueTreeList, smoke_dialogue_writer),
    "art_director": (AssetPromptsOutput, smoke_art_director),
    "prompt_refiner": (PromptUpdates, smoke_prompt_refiner),
    "level_generator": (LevelLayout, smoke_level_generator),
    "localization": (LocalizationOutput, smoke_localization),
    "coder": (CoderOutput, smoke_coder),
    "qa": (QAReport, smoke_qa),
    "playtester": (PlaytestReport, smoke_playtester),
}


def _brief(model: BaseModel) -> str:
    """Short human-readable summary line for a validated output model."""
    dumped = model.model_dump(mode="json")
    text = json.dumps(dumped, ensure_ascii=False)
    return text if len(text) <= 400 else text[:397] + "..."


async def main(argv: list[str]) -> int:
    keys = [a for a in argv if a != "-v" and not a.startswith("-")] or list(SMOKE_CASES)
    unknown = [k for k in keys if k not in SMOKE_CASES]
    if unknown:
        print(f"unknown agent(s): {unknown}; available: {sorted(SMOKE_CASES)}", file=sys.stderr)
        return 2

    failures = 0
    for key in keys:
        expected, runner = SMOKE_CASES[key]
        try:
            out = await runner()
            ok = isinstance(out, expected)
            status = "OK " if ok else "BAD"
            print(f"[{status}] {key:<16} -> {type(out).__name__}")
            print(f"       {_brief(out)}")
            if not ok:
                failures += 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[FAIL] {key:<16} -> {type(exc).__name__}: {exc}")

    total = len(keys)
    print(f"\n{total - failures}/{total} agents produced validated outputs.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
