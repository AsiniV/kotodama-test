"""Phase 11 — offline tests for the GameIR assembler + error attribution.

Everything runs WITHOUT GPU, Godot binary, LLM server or network: agents are
recording stubs and the workspace/art services are fakes (same pattern as
``tests/test_orchestration_dryrun.py``).

Covered contract (``backend/services/ir_assembler.py`` + the ``ir_assembler``
node in ``backend/services/orchestration.py``):

1. ``tests/fixtures/golden_ir.json`` passes the Phase-9 ``ir_validator`` with
   ``valid=True`` and zero errors (golden-fixture guard).
2. ``assemble_game_ir`` happy path: stub agent outputs assemble into a valid
   GameIR v2 (entities/components, rooms, manifest, audio map, l10n table).
3. ``attribute_ir_errors`` maps broken references / quest problems / l10n
   misses to the responsible agent node with actionable feedback text.
4. Graph-level bounded IR-retry routing: invalid IR loops back through the
   attributed agent with its feedback injected into the retry input
   (``extra_context``), and the run stops (fails/rolls back) once
   ``MAX_IR_RETRIES`` is exhausted.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import backend.services.orchestration as orchestration
from backend.schemas.agent_schemas import (
    AssetPrompt,
    AssetPromptsOutput,
    CoderOutput,
    DialogueChoice,
    DialogueNode,
    DialogueTree,
    DialogueTreeList,
    EntityRequest,
    GameDesignDocument,
    GeneratedAsset,
    GeneratedFile,
    LevelLayout,
    LocalizationEntry,
    LocalizationFile,
    LocalizationOutput,
    PlaytestReport,
    QAReport,
    QuestGraph,
    QuestGraphList,
    QuestStage,
    Room,
    WizardInput,
)
from backend.services.ir_assembler import (
    AGENT_NODE_FOR_SECTION,
    MAX_IR_RETRIES,
    assemble_game_ir,
    attribute_ir_errors,
    format_agent_feedback,
)
from backend.services.ir_validator import IRError, ValidationReport, validate_game_ir

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "golden_ir.json"

AGENT_ATTRS = (
    "designer",
    "architect",
    "quest_designer",
    "dialogue_writer",
    "level_generator",
    "coder",
    "qa",
    "playtester",
    "localization_manager",
)

_AGENT_CLASS_NAMES = {
    "designer": "GameDesignerAgent",
    "architect": "ArchitectAgent",
    "quest_designer": "QuestDesignerAgent",
    "dialogue_writer": "DialogueWriterAgent",
    "level_generator": "LevelGeneratorAgent",
    "coder": "CoderAgent",
    "qa": "QAAgent",
    "playtester": "AIPlaytesterAgent",
    "localization_manager": "LocalizationManagerAgent",
}


# ---------------------------------------------------------------------------
# Stub infrastructure (mirrors tests/test_orchestration_dryrun.py)
# ---------------------------------------------------------------------------

class RecordingAgent:
    """Stub agent that records every input it receives; optional scripted outputs."""

    def __init__(self, output: Any = None, raises: Exception | None = None):
        self.output = output
        self.raises = raises
        self.calls: list[Any] = []

    async def execute(self, input_data: Any) -> Any:
        self.calls.append(input_data)
        if self.raises is not None:
            raise self.raises
        return self.output() if callable(self.output) else self.output


class FakeWorkspaceManager:
    """In-memory stand-in for WorkspaceManager (no git, no template copy)."""

    def __init__(self, root: Path):
        self.root = root
        self.events: list[str] = []

    async def create_workspace(self, project_id: str, user_id: str) -> Path:
        path = self.root / project_id
        (path / "godot_project" / "assets").mkdir(parents=True, exist_ok=True)
        self.events.append(f"create:{project_id}")
        return path

    async def save_result(self, workspace_path: Path, changes: list[str]) -> str:
        self.events.append("commit")
        return "a" * 40

    async def rollback(self, workspace_path: Path) -> bool:
        self.events.append("rollback")
        return True

    async def preserve_assets(self, workspace_path: Path) -> list[Path]:
        self.events.append("preserve")
        return []

    async def restore_assets(self, workspace_path: Path, preserved: list[Path]) -> None:
        self.events.append("restore")

    async def clear_preserved(self, workspace_path: Path) -> None:
        self.events.append("clear_preserved")


class FakeArtPipeline:
    """Deterministic sprite-only art pipeline stand-in."""

    async def generate_project_assets(self, **kwargs: Any) -> AssetPromptsOutput:
        prompt = AssetPrompt(slot="npc", prompt="village elder sprite", style="pixel-art")
        asset = GeneratedAsset(
            path="res://assets/sprites/npc.png",
            slot="npc",
            asset_type="sprite",
            tags=["npc"],
            used_in=["module_npc"],
            prompt_used=prompt.prompt,
            provider="local",
            generated_at=datetime.now(timezone.utc),
        )
        return AssetPromptsOutput(prompts=[prompt], assets=[asset])


def make_wizard(**overrides: Any) -> WizardInput:
    base: dict[str, Any] = dict(
        genre="adventure",
        perspective="top-down",
        art_style="pixel-art",
        setting="cursed forest",
        scale="small",
        text_description="a tiny exploration game",
        project_name="ir-assembler-project",
    )
    base.update(overrides)
    return WizardInput(**base)


def make_gdd(**overrides: Any) -> GameDesignDocument:
    base: dict[str, Any] = dict(
        title="IR Assembly",
        genre="adventure",
        perspective="top-down",
        art_style="pixel-art",
        setting="cursed forest",
        scale="small",
        core_mechanics=["explore"],
        target_audience="everyone",
        unique_selling_points=["tiny"],
        module_dependencies=["module_player"],
        estimated_modules=["module_player"],
        quest_complexity="simple",
        dialogue_depth="linear",
    )
    base.update(overrides)
    return GameDesignDocument(**base)


def make_plan(level_parameters: dict | None = None) -> Any:
    from backend.schemas.agent_schemas import ArchitecturePlan

    return ArchitecturePlan(
        scene_tree={"Main": ["Player"]},
        required_modules=[{"id": "module_player"}],
        signal_contracts=[{"signal": "module_player_died", "emitter": "module_player"}],
        asset_slots_needed=["player"],
        level_parameters=level_parameters,
    )


def make_coder_output() -> CoderOutput:
    return CoderOutput(
        files=[
            GeneratedFile(
                path="godot_project/module_player.gd",
                content="extends Node\nsignal module_player_died\n",
                file_type="gdscript",
                module_id="module_player",
            )
        ],
        modules_created=["module_player"],
        signals_registered=["module_player_died"],
    )


def make_playtest_report(score: float = 95.0, success: bool = True, crashed: bool = False) -> PlaytestReport:
    return PlaytestReport(success=success, stability_score=score, crashed=crashed)


def make_qa_report(passed: bool = True) -> QAReport:
    return QAReport(passed=passed, errors=[], warnings=[], files_checked=1, signals_verified=1)


def make_localization_output() -> LocalizationOutput:
    return LocalizationOutput(
        entries=[LocalizationEntry(key="dlg_elder_intro_n0", value="Hello", category="dialogue")],
        localization_files=[LocalizationFile(locale="en", strings={"dlg_elder_intro_n0": "Hello"})],
        missing_keys=[],
    )


def make_quest(npcs: list[str] | None = None) -> QuestGraph:
    return QuestGraph(
        quest_id="q1",
        title="Find the lantern",
        description="Recover the lost lantern from the hollow.",
        stages=[QuestStage(id="s1", description="Search the hollow", type="objective", location="room_1")],
        dependencies=[],
        npcs_involved=list(npcs or ["npc_elder"]),
        items_required=[],
    )


def make_dialogue() -> DialogueTree:
    return DialogueTree(
        dialogue_id="dlg_elder",
        npc_id="npc_elder",
        trigger="interact",
        nodes=[
            DialogueNode(
                id="n0",
                speaker="npc_elder",
                text_key="dlg_elder_n0",
                choices=[DialogueChoice(text_key="dlg_elder_n0_yes", next="END")],
            )
        ],
        conditions={},
    )


def make_layout(start_room: str = "room_0", end_room: str = "room_1") -> LevelLayout:
    return LevelLayout(
        algorithm="bsp",
        width=64,
        height=64,
        rooms=[
            Room(x=0, y=0, width=10, height=10, room_type="start"),
            Room(x=40, y=40, width=10, height=10, room_type="end"),
        ],
        corridors=[],
        points_of_interest=[],
        enemy_spawn_points=[],
        item_spawn_points=[],
        start_room=start_room,
        end_room=end_room,
        validation_passed=True,
    )


def happy_state(**overrides: Any) -> dict[str, Any]:
    """A GenerationState-shaped mapping with internally consistent stub outputs."""
    state: dict[str, Any] = {
        "wizard_input": make_wizard(),
        "gdd": make_gdd(),
        "architecture_plan": make_plan(),
        "quest_graphs": [make_quest()],
        "dialogue_trees": [make_dialogue()],
        "level_layout": make_layout(),
        "generated_assets": [],
        "asset_paths": [],
        "audio_requests": [
            {"id": "bgm_main_theme", "type": "bgm", "description": "calm forest theme"},
            {"id": "sfx_ui_select", "type": "sfx", "description": "UI blip"},
        ],
        "localization_output": None,
        "entities": [],
    }
    state.update(overrides)
    return state


def _build_orchestrator(tmp_path: Path, stub_agents: dict[str, RecordingAgent]) -> orchestration.OrchestratorService:
    orch = orchestration.OrchestratorService.__new__(orchestration.OrchestratorService)
    for attr in AGENT_ATTRS:
        setattr(orch, attr, getattr(orchestration, _AGENT_CLASS_NAMES[attr])())
    for attr, stub in stub_agents.items():
        setattr(orch, attr, stub)
    orch.workspace_manager = FakeWorkspaceManager(tmp_path / "workspaces")
    orch.analyzer = None
    orch.lore_rag = None
    orch.art_pipeline = FakeArtPipeline()
    orch.graph = orch._build_graph()
    return orch


@pytest.fixture
def stub_agents() -> dict[str, RecordingAgent]:
    layout = make_layout()
    return {
        "designer": RecordingAgent(make_gdd()),
        "architect": RecordingAgent(make_plan(level_parameters={"algorithm": "bsp"})),
        "quest_designer": RecordingAgent(QuestGraphList(quests=[make_quest()])),
        "dialogue_writer": RecordingAgent(DialogueTreeList(dialogues=[make_dialogue()])),
        "level_generator": RecordingAgent(layout),
        "coder": RecordingAgent(make_coder_output()),
        "qa": RecordingAgent(make_qa_report()),
        "playtester": RecordingAgent(make_playtest_report()),
        "localization_manager": RecordingAgent(make_localization_output()),
    }


@pytest.fixture
def orchestrator(tmp_path: Path, stub_agents: dict[str, RecordingAgent]) -> orchestration.OrchestratorService:
    return _build_orchestrator(tmp_path, stub_agents)


async def run(orch: orchestration.OrchestratorService) -> dict[str, Any]:
    return await orch.run_generation(make_wizard(), user_id="u-ir", project_id="proj-ir")


def contents(messages: list[Any]) -> list[str]:
    return [getattr(m, "content", str(m)) for m in messages]


def codes(report: ValidationReport) -> set[str]:
    return {e.code for e in report.errors}


# ---------------------------------------------------------------------------
# 1. Golden fixture: tests/fixtures/golden_ir.json passes ir_validator
# ---------------------------------------------------------------------------

def test_golden_fixture_json_loads_and_validates() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    report = validate_game_ir(payload)
    assert report.ok, report.render()
    assert report.errors == []  # zero errors, not merely "few"


def test_golden_fixture_roundtrips_through_game_ir_model() -> None:
    """Model load + validator agree the golden IR is valid (valid=True)."""
    from backend.schemas.agent_schemas import GameIR

    model = GameIR.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    report = validate_game_ir(model)
    assert report.ok
    assert report.error_codes == set()
    assert model.schema_version == 2


def test_golden_fixture_survives_validation_after_deepcopy() -> None:
    """Guard against accidental shared-state mutation in the validator."""
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    first = validate_game_ir(copy.deepcopy(payload))
    second = validate_game_ir(copy.deepcopy(payload))
    assert first.ok and second.ok
    assert first.errors == second.errors == []


# ---------------------------------------------------------------------------
# 2. assemble_game_ir happy path from stub agent outputs
# ---------------------------------------------------------------------------

def test_assemble_happy_path_produces_valid_ir() -> None:
    result = assemble_game_ir(happy_state())
    assert result.ok, result.error_summary
    assert result.report.errors == []
    ir = result.ir
    assert ir is not None
    assert ir.schema_version == 2
    assert ir.design_document is not None and ir.design_document.title == "IR Assembly"
    assert [q.quest_id for q in ir.quests] == ["q1"]
    assert [d.dialogue_id for d in ir.dialogues] == ["dlg_elder"]
    assert ir.level_layout is not None
    assert [r.id for r in ir.level_layout.rooms] == ["room_0", "room_1"]
    # Assembled IR re-validates cleanly on its own.
    assert validate_game_ir(ir).ok


def test_assemble_merges_npc_entities_with_components() -> None:
    result = assemble_game_ir(happy_state())
    ir = result.ir
    assert ir is not None
    npc = next(e for e in ir.entities if e.id == "npc_elder")
    assert npc.type == "npc"
    assert npc.dialogue_id == "dlg_elder"
    assert npc.components.interactable is not None
    assert npc.components.interactable.dialogue_id == "dlg_elder"
    assert npc.components.interactable.prompt_key == "dlg_elder_prompt"
    assert npc.components.quest_giver is not None
    assert npc.components.quest_giver.quest_ids == ["q1"]
    # Deterministic placement inside a room of the layout.
    assert npc.position_x is not None and npc.position_y is not None


def test_assemble_seeds_localization_table_for_every_tr_key() -> None:
    result = assemble_game_ir(happy_state())
    ir = result.ir
    assert ir is not None
    en = ir.localization_table.entries["en"]
    # quest title, dialogue node + choice keys, interact prompt all seeded.
    assert "Find the lantern" in en
    assert en["dlg_elder_n0"] == "Dlg Elder N0"  # humanised placeholder
    assert "dlg_elder_n0_yes" in en
    assert en["dlg_elder_prompt"] == "Interact with Npc Elder"


def test_assemble_derives_audio_requests_and_audio_map() -> None:
    state = happy_state(audio_requests=None)
    result = assemble_game_ir(state)
    assert result.ok, result.error_summary
    ir = result.ir
    assert ir is not None
    # No agent emits AudioRequests today → baseline BGM + SFX budget is seeded.
    ids = [a.id for a in ir.audio_requests]
    assert ids == ["bgm_main_theme", "sfx_ui_select"]
    assert [z.id for z in ir.audio_map.zones] == ["zone_room_0", "zone_room_1"]
    assert ir.audio_map.zones[0].bgm_id == "bgm_main_theme"
    assert ir.audio_map.ambient == ["bgm_main_theme"]


def test_assemble_maps_art_slots_to_entities_and_manifest() -> None:
    asset = GeneratedAsset(
        path="res://assets/sprites/npc.png",
        slot="npc",
        asset_type="sprite",
        tags=["npc"],
        used_in=["module_npc"],
        prompt_used="village elder",
        provider="local",
        generated_at=datetime.now(timezone.utc),
    )
    result = assemble_game_ir(happy_state(generated_assets=[asset]))
    assert result.ok, result.error_summary
    ir = result.ir
    assert ir is not None
    manifest_ids = {entry.id for entry in ir.asset_manifest}
    assert "sprite_npc" in manifest_ids
    npc = next(e for e in ir.entities if e.id == "npc")
    assert npc.components.sprite is not None
    assert npc.components.sprite.asset_id == "sprite_npc"


def test_assemble_accepts_attribute_style_state_object() -> None:
    """The function takes a Mapping OR any object exposing the keys as attributes."""

    class StateShim:
        def __init__(self, data: dict[str, Any]) -> None:
            self.__dict__.update(data)

    result = assemble_game_ir(StateShim(happy_state()))
    assert result.ok, result.error_summary


def test_assemble_never_raises_on_garbage_sections() -> None:
    """Invalid optional sections degrade to ``None`` instead of raising."""
    result = assemble_game_ir(happy_state(gdd={"title": 123}, level_layout="not-a-layout"))
    assert result.ok  # strict=False coercion → broken optional sections dropped
    assert result.ir is not None and result.ir.design_document is None


def test_assemble_drops_structurally_invalid_quest_payloads() -> None:
    bad_quest = {"quest_id": "q1"}  # missing required fields
    result = assemble_game_ir(happy_state(quest_graphs=[bad_quest]))
    # The broken quest is dropped by the strict coercion; assembly stays valid.
    assert result.ok
    assert result.ir is not None and result.ir.quests == []


# ---------------------------------------------------------------------------
# 3. attribute_ir_errors: broken refs / quests / l10n → responsible agent
# ---------------------------------------------------------------------------

def _report(*errors: IRError) -> ValidationReport:
    return ValidationReport(errors=list(errors), warnings=[])


def test_attribute_reference_errors_to_owning_agents() -> None:
    report = _report(
        IRError("refs.missing_dialogue", "entities[3].dialogue_id", "unknown dialogue"),
        IRError("refs.missing_dialogue", "entities[1].components.interactable.dialogue_id", "unknown dialogue"),
        IRError("refs.missing_asset", "entities[0].components.sprite.asset_id", "unknown asset"),
        IRError("refs.missing_npc", "dialogues[0].npc_id", "unknown npc"),
        IRError("refs.missing_audio", "audio_map.zones[0].bgm_id", "unknown bgm"),
        IRError("level.unknown_start_room", "level_layout.start_room", "unknown room"),
    )
    grouped = attribute_ir_errors(report)
    assert [e.path for e in grouped["dialogue_writer"]] == ["dialogues[0].npc_id"]
    assert [e.path for e in grouped["quest_designer"]] == [
        "entities[1].components.interactable.dialogue_id"
    ]
    assert [e.path for e in grouped["coder"]] == ["entities[3].dialogue_id", "entities[0].components.sprite.asset_id"]
    assert [e.path for e in grouped["level_generator"]] == [
        "audio_map.zones[0].bgm_id",
        "level_layout.start_room",
    ]


def test_attribute_quest_errors_to_quest_designer() -> None:
    report = _report(
        IRError("quests.cycle", "quests", "cycle detected"),
        IRError("refs.missing_quest_dependency", "quests[1].dependencies", "unknown dep"),
        IRError("refs.missing_quest", "entities[2].components.quest_giver.quest_ids[0]", "unknown quest"),
    )
    grouped = attribute_ir_errors(report)
    assert len(grouped["quest_designer"]) == 3
    assert "coder" not in grouped  # quest_giver component refs mirror quest data


def test_attribute_localization_errors_win_over_path_section() -> None:
    report = _report(
        IRError("l10n.missing_key", "dialogues[0].nodes[1].text_key", "key missing"),
        IRError("l10n.missing_key", "quests[0].title", "key missing"),
        IRError("schema.invalid", "localization_table.default_locale", "bad locale"),
    )
    grouped = attribute_ir_errors(report)
    assert len(grouped["localization"]) == 3
    assert set(grouped) == {"localization"}


def test_attribute_unknown_sections_fall_back_to_coder() -> None:
    report = _report(IRError("ids.duplicate", "brand_new_section[0].id", "dupe"))
    grouped = attribute_ir_errors(report)
    assert [e.code for e in grouped["coder"]] == ["ids.duplicate"]


def test_attribute_design_and_camera_sections() -> None:
    report = _report(
        IRError("schema.invalid", "design_document.title", "required"),
        IRError("schema.invalid", "camera.zoom", "must be positive"),
        IRError("manifest.bad_path", "asset_manifest[0].path", "not res://"),
        IRError("schema.invalid", "$", "GameIR is missing (None)"),
    )
    grouped = attribute_ir_errors(report)
    assert grouped["designer"][0].path.startswith("design_document")
    assert grouped["architect"][0].path.startswith("camera")
    assert grouped["art_director"][0].path.startswith("asset_manifest")
    assert grouped["coder"][0].path == "$"  # root-section fallback


def test_feedback_text_is_actionable_per_agent() -> None:
    broken = happy_state()
    broken["dialogue_trees"] = [make_dialogue()]
    broken["quests"] = [
        QuestGraph(
            quest_id="q1",
            title="Nonexistent Title Key",
            description="d",
            stages=[QuestStage(id="s1", description="go", type="objective")],
            dependencies=["q_ghost"],
            npcs_involved=["npc_who"],
            items_required=[],
        )
    ]
    result = assemble_game_ir(broken)
    assert not result.ok
    assert "quest_designer" in result.agent_feedback
    feedback = result.agent_feedback["quest_designer"]
    assert feedback.startswith("GameIR validation failed. Fix these quest_designer issues")
    assert "[refs.missing_quest_dependency]" in feedback
    assert "q_ghost" in feedback
    # Grouping view matches the feedback keys.
    grouped = attribute_ir_errors(result.report)
    assert set(grouped) == set(result.agent_feedback)


def test_format_agent_feedback_lists_each_error_once() -> None:
    errs = [
        IRError("quests.cycle", "quests", "a -> b -> a"),
        IRError("refs.missing_quest_dependency", "quests[1].dependencies", "unknown dep 'x'"),
    ]
    text = format_agent_feedback("quest_designer", errs)
    lines = text.splitlines()
    assert lines[0] == "GameIR validation failed. Fix these quest_designer issues and re-run:"
    assert lines[1] == "- [quests.cycle] quests: a -> b -> a"
    assert lines[2] == "- [refs.missing_quest_dependency] quests[1].dependencies: unknown dep 'x'"


def test_attribution_table_covers_all_ir_sections() -> None:
    assert set(AGENT_NODE_FOR_SECTION) >= {
        "design_document",
        "entities",
        "quests",
        "dialogues",
        "level_layout",
        "asset_manifest",
        "audio_map",
        "localization_table",
        "camera",
    }


# ---------------------------------------------------------------------------
# 4. Graph bounded-retry routing around the ir_assembler node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ir_assembler_node_present_between_persist_and_qa(orchestrator) -> None:
    graph = orchestrator.graph.get_graph()
    successors: dict[str, set[str]] = {}
    for edge in graph.edges:
        successors.setdefault(edge.source, set()).add(edge.target)
    assert "ir_assembler" in successors.get("persist_files", set())
    assert "qa" in successors.get("ir_assembler", set())
    assert "fail" in successors.get("ir_assembler", set())
    assert "rollback" in successors.get("ir_assembler", set())
    # Repair routes loop back through the owning agents' pipeline segments.
    for route in orchestration.IR_REPAIR_ROUTES:
        assert route in successors.get("ir_assembler", set()), f"missing repair route to {route}"


@pytest.mark.asyncio
async def test_invalid_ir_routes_repair_with_feedback_then_exhausts(orchestrator, stub_agents) -> None:
    """Unfixable IR → exactly MAX_IR_RETRIES repairs, feedback injected, then stop."""
    # Quest references an NPC/dialogue that no repair can conjure: the stub
    # always returns the same broken quest graph.
    broken_quest = QuestGraph(
        quest_id="q1",
        title="Find the lantern",
        description="d",
        stages=[QuestStage(id="s1", description="go", type="objective")],
        dependencies=[],
        npcs_involved=["npc_ghost"],
        items_required=[],
    )
    stub_agents["quest_designer"].output = QuestGraphList(quests=[broken_quest])

    result = await run(orchestrator)

    assert result["success"] is False
    validation = result["game_ir_validation"]
    assert validation["ok"] is False
    assert "refs.missing_npc" in {e["code"] for e in validation["errors"]}
    assert "npc_ghost" in validation["attributed_to"]["quest_designer"][0]["message"]

    # Bounded retries: initial pass + MAX_IR_RETRIES repair attempts.
    assert result["ir_repair_attempts"] == MAX_IR_RETRIES
    assert result["ir_repair_target"] is None
    assert len(stub_agents["quest_designer"].calls) == 1 + MAX_IR_RETRIES
    # Downstream never saw the broken IR: QA/playtest/localization/commit skipped.
    assert stub_agents["qa"].calls == []
    assert stub_agents["playtester"].calls == []
    assert stub_agents["localization_manager"].calls == []
    events = orchestrator.workspace_manager.events
    assert "commit" not in events
    assert "rollback" in events  # coder already produced files → rollback path

    msgs = contents(result["messages"])
    assert sum("routing repair to quest_designer" in m for m in msgs) == MAX_IR_RETRIES - 1
    assert any("repairs exhausted" in m for m in msgs)
    assert "GameIR validation failed" in (result["error_message"] or "")
    assert "refs.missing_npc" in (result["error_message"] or "")


@pytest.mark.asyncio
async def test_repair_retry_injects_feedback_into_agent_input(orchestrator, stub_agents) -> None:
    """First failure carries no context; the routed retry gets actionable text."""
    calls = stub_agents["quest_designer"]
    original_execute = calls.execute

    async def flaky_execute(input_data: Any) -> Any:
        if not calls.calls:  # first pass: produce an IR-breaking quest
            return QuestGraphList(
                quests=[
                    QuestGraph(
                        quest_id="q1",
                        title="Find the lantern",
                        description="d",
                        stages=[QuestStage(id="s1", description="go", type="objective")],
                        dependencies=[],
                        npcs_involved=["npc_ghost"],
                        items_required=[],
                    )
                ]
            )
        return original_execute(input_data)  # repaired: healthy quest

    calls.execute = flaky_execute

    result = await run(orchestrator)

    assert result["success"] is True, result.get("error_message")
    assert result["ir_repair_attempts"] == 1
    assert result["ir_repair_target"] is None
    assert len(calls.calls) == 2
    # Retry input carried the attributed, actionable feedback...
    retry_input = calls.calls[1]
    assert retry_input.extra_context is not None
    assert "Fix these quest_designer issues" in retry_input.extra_context
    assert "refs.missing_npc" in retry_input.extra_context
    assert "npc_ghost" in retry_input.extra_context
    # ...and only the retry (the first pass had nothing to fix yet).
    assert calls.calls[0].extra_context in (None, "")
    # Feedback was consumed: later agents did not receive quest-designer text.
    assert stub_agents["coder"].calls[-1].extra_context in (None, "")


@pytest.mark.asyncio
async def test_unroutable_l10n_error_fails_immediately_without_retry(orchestrator, stub_agents) -> None:
    """l10n.missing_key attributes to `localization`, which is NOT a repair route."""
    broken_dialogue = DialogueTree(
        dialogue_id="dlg_elder",
        npc_id="npc_elder",
        trigger="interact",
        nodes=[
            DialogueNode(
                id="n0",
                speaker="npc_elder",
                text_key="\u0442\u043e\u043b\u044c\u043a\u043e \u0447\u0442\u043e \u043f\u043e-\u0440\u0443\u0441\u0441\u043a\u0438",
                choices=[DialogueChoice(text_key="dlg_elder_n0_yes", next="END")],
            )
        ],
        conditions={},
    )
    stub_agents["dialogue_writer"].output = DialogueTreeList(dialogues=[broken_dialogue])

    result = await run(orchestrator)

    assert result["success"] is False
    assert result["ir_repair_attempts"] == 1
    assert result["ir_repair_target"] is None
    assert "l10n.missing_key" in {e["code"] for e in result["game_ir_validation"]["errors"]}
    assert "localization" in result["game_ir_validation"]["attributed_to"]
    # No repair loop happened at all: single pass through the authors.
    assert len(stub_agents["dialogue_writer"].calls) == 1
    assert len(stub_agents["quest_designer"].calls) == 1
    assert stub_agents["qa"].calls == []
    assert "rollback" in orchestrator.workspace_manager.events


@pytest.mark.asyncio
async def test_valid_ir_flows_straight_to_qa(orchestrator, stub_agents) -> None:
    result = await run(orchestrator)

    assert result["success"] is True, result.get("error_message")
    assert result["ir_repair_attempts"] == 0
    assert result["ir_repair_target"] is None
    assert result["game_ir_validation"]["ok"] is True
    assert result["game_ir_validation"]["errors"] == []
    assert isinstance(result["game_ir"], dict)
    json.dumps(result["game_ir"])  # checkpoint-safe
    assert result["game_ir"]["files"] == ["godot_project/module_player.gd"]
    assert len(stub_agents["quest_designer"].calls) == 1
    assert len(stub_agents["qa"].calls) == 1
    assert "commit" in orchestrator.workspace_manager.events
    assert any("IR assembled" in m for m in contents(result["messages"]))
