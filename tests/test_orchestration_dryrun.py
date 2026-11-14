"""Phase 5 — offline dry-run tests for the LangGraph orchestrator wiring.

The whole graph must traverse WITHOUT GPU, Godot binary, LLM server or network:
every agent is replaced by a recording stub and the workspace/art services are
fakes. These tests assert the Phase-5 invariants:

1. ``GenerationState`` carries the new fields (asset_paths, generated_assets,
   level_layout, game_ir).
2. Every agent is called with its Phase-3 single pydantic input model.
3. Explicit error edges: a failing node routes to ``fail``/``rollback`` and no
   downstream agent receives cascaded ``None`` inputs.
4. Localization runs AFTER playtest and is non-blocking (its failure never
   aborts the pipeline); retry loops respect the two-attempt rule.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import backend.services.orchestration as orchestration
from backend.schemas.agent_schemas import (
    ArchitectInput,
    AssetPrompt,
    AssetPromptsOutput,
    CoderInput,
    CoderOutput,
    DialogueTreeList,
    DialogueWriterInput,
    DesignerInput,
    GameDesignDocument,
    GeneratedAsset,
    GeneratedFile,
    LevelGeneratorInput,
    LevelLayout,
    LocalizationInput,
    LocalizationOutput,
    PlaytestConfig,
    PlaytestReport,
    QAInput,
    QAReport,
    QuestDesignerInput,
    QuestGraphList,
    Room,
    WizardInput,
)

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


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class RecordingAgent:
    """Stub agent that records its single input and returns/raises canned data."""

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
        return [workspace_path / ".kotodama_preserved" / "player.png"]

    async def restore_assets(self, workspace_path: Path, preserved: list[Path]) -> None:
        self.events.append("restore")

    async def clear_preserved(self, workspace_path: Path) -> None:
        self.events.append("clear_preserved")


class FakeArtPipeline:
    """Stand-in for ArtPipelineService.generate_project_assets."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def generate_project_assets(self, **kwargs: Any) -> AssetPromptsOutput:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("SD unreachable")
        prompt = AssetPrompt(
            slot="player", prompt="hero sprite", style=kwargs.get("art_style", "pixel-art")
        )
        asset = GeneratedAsset(
            path="res://assets/sprites/player.png",
            slot="player",
            asset_type="sprite",
            tags=["player"],
            used_in=["module_player"],
            prompt_used=prompt.prompt,
            provider="local",
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
        project_name="dryrun-project",
    )
    base.update(overrides)
    return WizardInput(**base)


def make_gdd(**overrides: Any) -> GameDesignDocument:
    base: dict[str, Any] = dict(
        title="Dry Run",
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


def make_level_layout() -> LevelLayout:
    return LevelLayout(
        algorithm="bsp",
        width=64,
        height=64,
        rooms=[Room(x=0, y=0, width=10, height=10, room_type="start"),
               Room(x=40, y=40, width=10, height=10, room_type="end")],
        corridors=[],
        points_of_interest=[],
        enemy_spawn_points=[],
        item_spawn_points=[],
        start_room="r0",
        end_room="r1",
        validation_passed=True,
    )


def make_localization_output(missing: list[str] | None = None) -> LocalizationOutput:
    from backend.schemas.agent_schemas import LocalizationEntry, LocalizationFile

    return LocalizationOutput(
        entries=[LocalizationEntry(key="dlg_hello", value="Hello", category="dialogue")],
        localization_files=[LocalizationFile(locale="en", strings={"dlg_hello": "Hello"})],
        missing_keys=missing or [],
    )


@pytest.fixture
def fake_wm(tmp_path: Path) -> FakeWorkspaceManager:
    return FakeWorkspaceManager(tmp_path / "workspaces")


@pytest.fixture
def stub_agents() -> dict[str, RecordingAgent]:
    """Happy-path stub agents for every LLM/deterministic agent in the graph."""
    return {
        "designer": RecordingAgent(make_gdd()),
        "architect": RecordingAgent(make_plan()),
        "quest_designer": RecordingAgent(QuestGraphList(quests=[])),
        "dialogue_writer": RecordingAgent(DialogueTreeList(dialogues=[])),
        # No level_parameters in the plan => node skips; stub returns a layout anyway.
        "level_generator": RecordingAgent(make_level_layout()),
        "coder": RecordingAgent(make_coder_output()),
        "qa": RecordingAgent(make_qa_report()),
        "playtester": RecordingAgent(make_playtest_report()),
        "localization_manager": RecordingAgent(make_localization_output()),
    }


@pytest.fixture
def orchestrator(
    tmp_path: Path,
    fake_wm: FakeWorkspaceManager,
    stub_agents: dict[str, RecordingAgent],
    monkeypatch: pytest.MonkeyPatch,
) -> orchestration.OrchestratorService:
    """Orchestrator with all external boundaries faked (no DB/minio/git/network)."""
    # Real agent constructors load AGENTS.md etc.; replace the class-level
    # defaults after construction with recording stubs instead.
    monkeypatch.setattr(orchestration, "get_orchestrator", lambda: None, raising=False)
    orch = orchestration.OrchestratorService.__new__(orchestration.OrchestratorService)
    # Instantiate real agents once so attribute names/types match production...
    for attr in AGENT_ATTRS:
        real_cls = getattr(orchestration, {
            "designer": "GameDesignerAgent",
            "architect": "ArchitectAgent",
            "quest_designer": "QuestDesignerAgent",
            "dialogue_writer": "DialogueWriterAgent",
            "level_generator": "LevelGeneratorAgent",
            "coder": "CoderAgent",
            "qa": "QAAgent",
            "playtester": "AIPlaytesterAgent",
            "localization_manager": "LocalizationManagerAgent",
        }[attr])
        setattr(orch, attr, real_cls())
    # ...then swap in the stubs (the graph nodes read self.<attr> at runtime).
    for attr, stub in stub_agents.items():
        setattr(orch, attr, stub)
    orch.workspace_manager = fake_wm
    orch.analyzer = None
    orch.lore_rag = None
    orch.art_pipeline = FakeArtPipeline()
    orch.graph = orch._build_graph()
    return orch


async def run(orch: orchestration.OrchestratorService, wizard: WizardInput | dict | None = None):
    return await orch.run_generation(
        wizard if wizard is not None else make_wizard(),
        user_id="u-test",
        project_id="proj-test",
    )


def contents(messages: list[Any]) -> list[str]:
    return [getattr(m, "content", str(m)) for m in messages]


# ---------------------------------------------------------------------------
# Task 1: state schema fields
# ---------------------------------------------------------------------------

def test_generation_state_has_phase5_fields():
    annotations = orchestration.GenerationState.__annotations__
    for field in ("asset_paths", "generated_assets", "level_layout", "game_ir"):
        assert field in annotations, f"GenerationState missing field: {field}"


# ---------------------------------------------------------------------------
# Task 2 + DONE criterion: full happy-path traversal, single-input contracts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_traverses_and_commits(orchestrator, stub_agents, fake_wm, tmp_path):
    result = await run(orchestrator)

    assert result["success"] is True
    assert result["error_message"] is None
    assert result["attempt_number"] == 1
    assert "commit" in fake_wm.events

    # New Phase-5 state fields populated.
    assert result["asset_paths"] == ["res://assets/sprites/player.png"]
    assert [a.slot for a in result["generated_assets"]] == ["player"]
    assert result["level_layout"] is None  # skipped: plan has no level_parameters
    assert isinstance(result["game_ir"], dict)
    assert result["game_ir"]["files"] == ["godot_project/module_player.gd"]
    assert json_roundtrips(result["game_ir"])

    # Localization ran AFTER playtest and before commit.
    msgs = contents(result["messages"])
    idx_playtest = next(i for i, m in enumerate(msgs) if "Playtest" in m)
    idx_loc = next(i for i, m in enumerate(msgs) if "Localization" in m)
    assert idx_playtest < idx_loc
    assert any("Committed" in m for m in msgs)

    # Phase-3 contract: each agent got EXACTLY ONE pydantic input model.
    expected_input = {
        "designer": DesignerInput,
        "architect": ArchitectInput,
        "quest_designer": QuestDesignerInput,
        "dialogue_writer": DialogueWriterInput,
        "coder": CoderInput,
        "qa": QAInput,
        "localization_manager": LocalizationInput,
    }
    for attr, model in expected_input.items():
        calls = stub_agents[attr].calls
        assert len(calls) == 1, f"{attr} called {len(calls)} times"
        assert isinstance(calls[0], model), f"{attr} got {type(calls[0]).__name__}, want {model.__name__}"

    # Playtester receives PlaytestConfig; art pipeline saw the architecture plan.
    assert isinstance(stub_agents["playtester"].calls[0], PlaytestConfig)
    assert orchestrator.art_pipeline.calls[0]["art_style"] == "pixel-art"


@pytest.mark.asyncio
async def test_quest_dialogue_and_level_nodes_run_when_enabled(orchestrator, stub_agents):
    stub_agents["designer"].output = make_gdd(quest_complexity="simple", dialogue_depth="linear")
    stub_agents["architect"].output = make_plan(level_parameters={"algorithm": "bsp"})

    result = await run(orchestrator)

    assert result["success"] is True
    assert isinstance(stub_agents["quest_designer"].calls[0], QuestDesignerInput)
    assert isinstance(stub_agents["dialogue_writer"].calls[0], DialogueWriterInput)
    assert isinstance(stub_agents["level_generator"].calls[0], LevelGeneratorInput)
    assert isinstance(result["level_layout"], LevelLayout)
    # Coder received the level layout as a plain dict (CoderInput.level_layout).
    coder_input = stub_agents["coder"].calls[0]
    assert isinstance(coder_input.level_layout, dict)
    assert coder_input.level_layout["algorithm"] == "bsp"
    # Game IR picked up the layout too.
    assert result["game_ir"]["level_layout"]["algorithm"] == "bsp"


# ---------------------------------------------------------------------------
# Task 3: explicit error edges (no cascading None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_early_failure_routes_to_fail_without_cascade(orchestrator, stub_agents):
    stub_agents["architect"].raises = RuntimeError("LLM down")

    result = await run(orchestrator)

    assert result["success"] is False
    assert "Architect failed" in (result["error_message"] or "")
    # Downstream agents were NEVER invoked with None inputs.
    for attr in ("quest_designer", "dialogue_writer", "level_generator", "coder",
                 "qa", "playtester", "localization_manager"):
        assert stub_agents[attr].calls == [], f"{attr} ran after architect failure"
    # Cheap abort: no rollback needed (nothing was written to the workspace).
    assert "rollback" not in fake_events(orchestrator)
    assert "commit" not in fake_events(orchestrator)
    assert any("Aborted" in m for m in contents(result["messages"]))


@pytest.mark.asyncio
async def test_post_generation_failure_routes_to_rollback(orchestrator, stub_agents):
    stub_agents["playtester"].raises = RuntimeError("godot exploded")

    result = await run(orchestrator)

    assert result["success"] is False
    assert "rollback" in fake_events(orchestrator)
    assert "commit" not in fake_events(orchestrator)
    # Localization is after playtest: it must not have run on the error path.
    assert stub_agents["localization_manager"].calls == []
    assert "Rollback" in (result["error_message"] or "")


# ---------------------------------------------------------------------------
# Task 3: localization moved after playtest and non-blocking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_localization_failure_is_non_blocking(orchestrator, stub_agents):
    stub_agents["localization_manager"].raises = RuntimeError("loc model missing")

    result = await run(orchestrator)

    assert result["success"] is True  # generation still commits
    assert result["localization_output"] is None
    assert "commit" in fake_events(orchestrator)
    assert any("Localization skipped" in m for m in contents(result["messages"]))
    assert result["error_message"] is None


@pytest.mark.asyncio
async def test_localization_missing_keys_do_not_trigger_retry(orchestrator, stub_agents):
    stub_agents["localization_manager"].output = make_localization_output(missing=["dlg_missing"])

    result = await run(orchestrator)

    assert result["success"] is True
    assert result["attempt_number"] == 1  # no extra coder attempt
    assert len(stub_agents["coder"].calls) == 1
    assert len(stub_agents["localization_manager"].calls) == 1
    assert any("missing keys" in m for m in contents(result["messages"]))


# ---------------------------------------------------------------------------
# Retry loop (two-attempt rule) + asset preservation round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_playtest_failure_retries_then_succeeds_with_asset_restore(orchestrator, stub_agents):
    scores = iter([10.0, 95.0])
    stub_agents["playtester"].output = lambda: make_playtest_report(score=next(scores), success=False)

    result = await run(orchestrator)

    assert result["success"] is True
    assert result["attempt_number"] == 2
    assert len(stub_agents["coder"].calls) == 2
    events = fake_events(orchestrator)
    assert "preserve" in events and "restore" in events and "clear_preserved" in events
    assert events.index("restore") < events.index("clear_preserved")
    assert "rollback" not in events


@pytest.mark.asyncio
async def test_two_playtest_failures_rollback_and_stop(orchestrator, stub_agents):
    stub_agents["playtester"].output = make_playtest_report(score=0.0, success=False, crashed=True)

    result = await run(orchestrator)

    assert result["success"] is False
    assert len(stub_agents["coder"].calls) == orchestration.MAX_ATTEMPTS  # bounded retry
    assert len(stub_agents["playtester"].calls) == orchestration.MAX_ATTEMPTS
    assert "rollback" in fake_events(orchestrator)
    assert stub_agents["localization_manager"].calls == []


# ---------------------------------------------------------------------------
# Graph shape: explicit error edges present for every production node
# ---------------------------------------------------------------------------

def test_every_production_node_has_error_edges(orchestrator):
    graph = orchestrator.graph.get_graph()
    successors = {node: set() for node in graph.nodes}
    for edge in graph.edges:
        successors.setdefault(edge.source, set()).add(edge.target)

    production_nodes = ["designer", "architect", "quest_designer", "dialogue_writer",
                        "level_generator", "art_director", "coder", "qa"]
    for node in production_nodes:
        targets = successors.get(node, set())
        assert "fail" in targets, f"{node} lacks an explicit error edge to fail"

    # Localization sits between playtest and commit and flows straight to commit.
    assert "localization" in successors.get("playtest", set())
    assert successors.get("localization") == {"__end__"} | {"commit"} - {"__end__"} or \
        "commit" in successors.get("localization", set())


# ---------------------------------------------------------------------------
# Contract guard: no multi-positional agent calls remain in the module source
# ---------------------------------------------------------------------------

def test_no_legacy_multi_arg_agent_calls():
    source = inspect.getsource(orchestration)
    for forbidden in (".modules}", 'state["gdd"].modules', "execute(state["):
        assert forbidden not in source


def json_roundtrips(payload: dict) -> bool:
    import json

    json.dumps(payload)
    return True


def fake_events(orch: orchestration.OrchestratorService) -> list[str]:
    return orch.workspace_manager.events
