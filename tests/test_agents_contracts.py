"""Offline contract tests for the agent layer (Phase 1).

Every agent must:
- take exactly ONE pydantic input model in ``execute()``;
- return a validated, schema-conformant pydantic output model;
- route LLM calls through backend.services.llm_client (no raw chat()).

All LLM/transport boundaries are mocked — no GPU, server or network needed.

The scripted payloads below are deliberately *model instances* built from
valid data: they exercise each agent's full execute() path (input contract,
client kwargs, post-processing) while the raw-text -> validate -> repair loop
inside llm_client is covered separately in tests/test_llm_client.py.
"""
from __future__ import annotations

import inspect
import json
import shutil
from typing import Any, Callable

import pytest
from pydantic import BaseModel

from backend.agents.architect import ArchitectAgent
from backend.agents.art_director import ArtDirectorAgent
from backend.agents.coder import CoderAgent
from backend.agents.designer import GameDesignerAgent
from backend.agents.dialogue_writer import DialogueWriterAgent
from backend.agents.level_generator import LevelGeneratorAgent
from backend.agents.localization import LocalizationManagerAgent
from backend.agents.playtester import AIPlaytesterAgent
from backend.agents.prompt_refiner import PromptRefinerAgent
from backend.agents.qa import QAAgent
from backend.agents.quest_designer import QuestDesignerAgent
from backend.schemas.agent_schemas import (
    ArchitecturePlan,
    ArchitectInput,
    ArtDirectorInput,
    AssetPrompt,
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
    LocalizationEntry,
    LocalizationFile,
    LocalizationInput,
    LocalizationOutput,
    PlaytestConfig,
    PlaytestReport,
    PromptRefinerInput,
    PromptUpdate,
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


# --------------------------------------------------------------------- #
# shared sample data
# --------------------------------------------------------------------- #

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

QUEST_LIST = QuestGraphList(
    quests=[
        QuestGraph(
            quest_id="q1",
            title="Find the Lantern",
            description="Retrieve the lost lantern.",
            stages=[
                QuestStage(id="s1", description="Talk to the elder", type="intro"),
                QuestStage(id="s2", description="Enter the cave", type="objective"),
                QuestStage(
                    id="s3", description="Return the lantern", type="outro",
                    rewards=[{"type": "item", "id": "lantern_blessed"}],
                ),
            ],
            dependencies=[],
            npcs_involved=["elder"],
            items_required=["lantern"],
        )
    ]
)

DIALOGUE_LIST = DialogueTreeList(
    dialogues=[
        DialogueTree(
            dialogue_id="d1",
            npc_id="elder",
            trigger="approach",
            nodes=[
                DialogueNode(
                    id="n1",
                    speaker="elder",
                    text_key="d1_n1",
                    choices=[DialogueChoice(text_key="d1_n1_c1", next="n2")],
                ),
                # terminal node: no choices -> "end" (validator treats an empty
                # choice list as a valid leaf; see backend/validators)
                DialogueNode(id="n2", speaker="elder", text_key="d1_n2", choices=[]),
            ],
            conditions={},
        )
    ]
)

# The dialogue validator requires every referenced localization key to exist in
# the input registry, so the happy-path input must supply them.
DIALOGUE_LOC_KEYS = ["d1_n1", "d1_n1_c1", "d1_n2"]

ARCH_WITH_LEVEL_PARAMS = ArchitecturePlan(
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

LEVEL_LAYOUT = LevelLayout(
    algorithm="bsp",
    width=100,
    height=100,
    # NOTE: LevelLayoutValidator matches start_room/end_room against the set of
    # room_type values (a quirk documented in PHASE_NOTES.md), so these must be
    # room types, not ids.
    rooms=[
        Room(x=0, y=0, width=10, height=10, room_type="start"),
        Room(x=50, y=50, width=10, height=10, room_type="end"),
    ],
    corridors=[Corridor(start=(5, 5), end=(50, 50), width=2)],
    points_of_interest=[],
    enemy_spawn_points=[(7, 7)],
    item_spawn_points=[],
    start_room="start",
    end_room="end",
)

LOCALIZATION_OUT = LocalizationOutput(
    entries=[LocalizationEntry(key="d1_n1", value="Hello, traveler.", category="dialogue")],
    localization_files=[LocalizationFile(locale="en", strings={"d1_n1": "Hello, traveler."})],
    missing_keys=[],
)


def gdd_payload() -> dict:
    return GDD.model_dump(mode="json")


def arch_payload() -> dict:
    return ARCH.model_dump(mode="json")


# --------------------------------------------------------------------- #
# happy paths (one per LLM-backed agent)
# --------------------------------------------------------------------- #


async def test_designer_happy_path(install_fake_llm):
    fake = install_fake_llm([gdd_payload()])
    out = await GameDesignerAgent().execute(DesignerInput(wizard_input=WIZARD))
    assert isinstance(out, GameDesignDocument)
    assert out.title == GDD.title
    call = fake.calls[0]
    assert call["response_model"] is GameDesignDocument
    assert call["role"] == "designer"


async def test_architect_happy_path_and_bare_gdd_compat(install_fake_llm):
    fake = install_fake_llm([arch_payload()])
    out = await ArchitectAgent().execute(ArchitectInput(design_document=GDD))
    assert isinstance(out, ArchitecturePlan)
    assert fake.calls[0]["role"] == "architect"

    # convenience: bare GameDesignDocument auto-wrapped
    fake2 = install_fake_llm([arch_payload()])
    out2 = await ArchitectAgent().execute(GDD)
    assert isinstance(out2, ArchitecturePlan)
    assert len(fake2.calls) == 1


async def test_quest_designer_happy_path_uses_wrapper(install_fake_llm):
    fake = install_fake_llm([QUEST_LIST])
    out = await QuestDesignerAgent().execute(
        QuestDesignerInput(design_document=GDD, npc_registry=["elder"], item_registry=["lantern"])
    )
    assert isinstance(out, QuestGraphList)
    assert out.quests[0].quest_id == "q1"
    assert fake.calls[0]["response_model"] is QuestGraphList  # not type(list[...])


async def test_dialogue_writer_happy_path_uses_wrapper(install_fake_llm):
    fake = install_fake_llm([DIALOGUE_LIST])
    out = await DialogueWriterAgent().execute(
        DialogueWriterInput(design_document=GDD, localization_keys=DIALOGUE_LOC_KEYS)
    )
    assert isinstance(out, DialogueTreeList)
    assert out.dialogues[0].npc_id == "elder"
    assert fake.calls[0]["response_model"] is DialogueTreeList


async def test_art_director_happy_path(install_fake_llm):
    payload = {
        "prompts": [
            {
                "slot": "player",
                "prompt": "cute pixel hero sprite",
                "negative_prompt": "blurry",
                "width": 512,
                "height": 512,
                "style": "pixel-art",
            }
        ],
        "assets": [],
    }
    fake = install_fake_llm([payload])
    out = await ArtDirectorAgent().execute(ArtDirectorInput(architecture_plan=ARCH))
    assert isinstance(out, AssetPromptsOutput)
    assert out.prompts[0].slot == "player"
    assert fake.calls[0]["role"] == "art_director"


async def test_prompt_refiner_happy_path_uses_wrapper(install_fake_llm):
    payload = {"updates": [{"agent_name": "coder", "updated_prompt": "Always type your GDScript."}]}
    fake = install_fake_llm([payload])
    out = await PromptRefinerAgent().execute(PromptRefinerInput(generation_history=[]))
    assert isinstance(out, PromptUpdates)
    assert out.updates[0].agent_name == "coder"
    assert fake.calls[0]["response_model"] is PromptUpdates


async def test_level_generator_happy_path(install_fake_llm):
    fake = install_fake_llm([LEVEL_LAYOUT])
    out = await LevelGeneratorAgent().execute(
        LevelGeneratorInput(architecture_plan=ARCH_WITH_LEVEL_PARAMS)
    )
    assert isinstance(out, LevelLayout)
    assert out.algorithm == "bsp"


async def test_localization_happy_path(install_fake_llm):
    fake = install_fake_llm([LOCALIZATION_OUT])
    out = await LocalizationManagerAgent().execute(LocalizationInput())
    assert isinstance(out, LocalizationOutput)
    assert out.entries[0].key == "d1_n1"


async def test_coder_happy_path_code_role_tokens(install_fake_llm):
    payload = CODER_OUT.model_dump(mode="json")
    fake = install_fake_llm([payload])
    out = await CoderAgent().execute(CoderInput(architecture_plan=ARCH))
    assert isinstance(out, CoderOutput)
    assert out.modules_created == ["player_controller"]
    assert fake.calls[0]["role"] == "coder"


# --------------------------------------------------------------------- #
# schema-repair paths (bad first response -> client repairs -> valid out)
#
# Here the *client* itself is faked: it returns a raw invalid string on the
# first generate() call and only validates the corrected second reply —
# exactly what the real LLMClient.generate does internally (covered in
# tests/test_llm_client.py against a mocked transport).
# --------------------------------------------------------------------- #


REPAIR_SAMPLE_PAYLOADS: dict[str, dict[str, Any]] = {
    "GameDesignDocument": GDD.model_dump(mode="json"),
    "ArchitecturePlan": ARCH.model_dump(mode="json"),
    "QuestGraphList": QUEST_LIST.model_dump(mode="json"),
    "DialogueTreeList": DIALOGUE_LIST.model_dump(mode="json"),
    "PromptUpdates": {"updates": [{"agent_name": "coder", "updated_prompt": "Type your GDScript."}]},
    "CoderOutput": CODER_OUT.model_dump(mode="json"),
}


def _repair_payload(model: type[BaseModel]) -> dict[str, Any]:
    """Return a valid raw dict payload for ``model`` (used by the repair test)."""
    sample = REPAIR_SAMPLE_PAYLOADS[model.__name__]
    return model.model_validate(sample).model_dump(mode="json")


REPAIR_CASES = [
    pytest.param(GameDesignerAgent, DesignerInput(wizard_input=WIZARD), GameDesignDocument, id="designer"),
    pytest.param(ArchitectAgent, ArchitectInput(design_document=GDD), ArchitecturePlan, id="architect"),
    pytest.param(
        QuestDesignerAgent,
        QuestDesignerInput(design_document=GDD, npc_registry=["elder"], item_registry=["lantern"]),
        QuestGraphList,
        id="quest_designer",
    ),
    pytest.param(
        DialogueWriterAgent,
        DialogueWriterInput(design_document=GDD, localization_keys=DIALOGUE_LOC_KEYS),
        DialogueTreeList,
        id="dialogue_writer",
    ),
    pytest.param(PromptRefinerAgent, PromptRefinerInput(generation_history=[]), PromptUpdates, id="prompt_refiner"),
    pytest.param(CoderAgent, CoderInput(architecture_plan=ARCH), CoderOutput, id="coder"),
]


@pytest.mark.parametrize("agent_cls,input_model,output_model", REPAIR_CASES)
async def test_schema_repair_second_attempt_succeeds(
    monkeypatch: pytest.MonkeyPatch, agent_cls, input_model, output_model
):
    """First raw LLM reply fails schema validation -> the real LLMClient repair
    loop feeds the validation error back -> second reply validates.

    Only the transport boundary (_complete) is faked here; generate(), the
    validate/repair cycle and the agents' execute() run for real. The repair
    loop itself is also covered against a mocked HTTP transport in
    tests/test_llm_client.py::test_schema_repair_feeds_error_back.
    """
    import backend.services.llm_client as llm_client
    from backend.services.llm_client import LLMClient

    good_text = json.dumps(_repair_payload(output_model))
    scripted = iter(["not json at all {{{", good_text])
    prompts_seen: list[str] = []

    async def fake_complete(self, *, messages, model, temperature, max_tokens, schema, schema_name=""):  # noqa: ANN001
        prompts_seen.append(messages[-1]["content"])
        return next(scripted)

    monkeypatch.setattr(LLMClient, "_complete", fake_complete)
    # the cached shared client is bound to this test's fresh event loop, so it
    # is rebuilt here with _complete already patched — no cache reset needed.

    out = await agent_cls().execute(input_model)
    assert isinstance(out, output_model)
    # the repair request must have carried the validation-error feedback text
    assert len(prompts_seen) == 2
    assert "Validation error" in prompts_seen[1] or "schema" in prompts_seen[1].lower()


# --------------------------------------------------------------------- #
# deterministic agents (no LLM call)
# --------------------------------------------------------------------- #


async def test_qa_agent_deterministic_contract():
    report = await QAAgent().execute(QAInput(coder_output=CODER_OUT))
    assert isinstance(report, QAReport)
    assert report.files_checked == 1


async def test_qa_rejects_non_model_input():
    with pytest.raises(TypeError):
        await QAAgent().execute({"coder_output": {}})  # plain dict not allowed


@pytest.mark.skipif(
    shutil.which("godot") is not None or shutil.which("godot-headless") is not None,
    reason="Godot binary present; offline no-Godot assertion would be flaky",
)
async def test_playtester_offline_no_godot(tmp_path):
    """Without Godot/project on disk the playtester returns a safe failure report."""
    report = await AIPlaytesterAgent(godot_headless_path="godot-headless-missing").execute(
        PlaytestConfig(workspace_path=str(tmp_path / "does-not-exist"))
    )
    assert isinstance(report, PlaytestReport)
    assert report.success is False
    assert report.error_message == "Project path does not exist"


# --------------------------------------------------------------------- #
# contract uniformity: exactly one positional execute() parameter
# --------------------------------------------------------------------- #

ALL_AGENTS = [
    GameDesignerAgent, ArchitectAgent, QuestDesignerAgent, DialogueWriterAgent,
    ArtDirectorAgent, PromptRefinerAgent, LevelGeneratorAgent, LocalizationManagerAgent,
    CoderAgent, QAAgent, AIPlaytesterAgent,
]


@pytest.mark.parametrize("agent_cls", ALL_AGENTS)
def test_execute_takes_exactly_one_input_model(agent_cls):
    sig = inspect.signature(agent_cls.execute)
    params = [p for p in list(sig.parameters.values())[1:]]  # drop self
    assert len(params) == 1
    assert params[0].kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


@pytest.mark.parametrize("agent_cls", ALL_AGENTS)
def test_agents_declare_roles(agent_cls):
    assert isinstance(agent_cls.role, str) and agent_cls.role


async def test_base_call_llm_kwargs(install_fake_llm):
    fake = install_fake_llm([gdd_payload()])
    agent = GameDesignerAgent()
    result = await agent._call_llm("prompt text", GameDesignDocument)
    assert isinstance(result, GameDesignDocument)
    kwargs = fake.calls[0]
    assert kwargs["system_prompt"] == agent.system_prompt
    assert kwargs["model"] == agent.model_name
    assert kwargs["temperature"] == agent.temperature
    assert kwargs["role"] == "designer"
    assert kwargs["prompt"] == "prompt text"
