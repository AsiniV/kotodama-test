"""
Complete LangGraph orchestration for all 11 agents.

Pipeline (Phase 5 — orchestrator wiring):

START → designer → architect → quest_designer → dialogue_writer → level_generator
      → art_director → coder → qa → playtest → localization → commit → END
                    ↑                                            │
                    └──────────── retry (attempt < MAX_ATTEMPTS)─┘
      any node failure → fail → END       critical failure after retries → rollback → END

Wiring rules enforced here:
- Every agent is called with the Phase-3 single-input contract (one pydantic
  input model, see PHASE_NOTES §1); no positional/multi-arg calls remain.
- Explicit error edges: every production node routes through ``_failure_router``;
  a node that recorded ``error_message`` goes to ``fail`` (or ``rollback`` when
  the workspace was already generated), never cascading ``None`` into
  downstream agents.
- Localization runs AFTER playtest and is NON-BLOCKING: its failures (including
  missing keys) are logged as warnings and never route to retry/rollback.
- The graph has NO checkpointer: nodes must not mutate state in place
  (LangGraph merges returned dicts only), so attempt counting happens on local
  copies inside the coder node.
"""

import json
import logging
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from backend.agents.architect import ArchitectAgent
from backend.agents.art_director import ArtDirectorAgent
from backend.agents.coder import CoderAgent
from backend.agents.designer import GameDesignerAgent
from backend.agents.dialogue_writer import DialogueWriterAgent
from backend.agents.level_generator import LevelGeneratorAgent
from backend.agents.localization import LocalizationManagerAgent
from backend.agents.playtester import AIPlaytesterAgent
from backend.agents.qa import QAAgent
from backend.agents.quest_designer import QuestDesignerAgent
from backend.schemas.agent_schemas import (
    ArchitectInput,
    CoderInput,
    CoderOutput,
    DialogueWriterInput,
    DesignerInput,
    GameDesignDocument,
    GameIR,
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
    WizardInput,
)

# NOTE: heavy service modules (workspace_manager -> sqlalchemy stack via
# backend.db, art_pipeline -> minio) are imported LAZILY inside the factory
# functions at the bottom of this module, so ``backend.services.orchestration``
# stays importable in minimal offline environments (tests run without the DB /
# object-storage dependencies installed). Their constructor annotations below
# are therefore plain ``Any``.

logger = logging.getLogger("kotodama.services.orchestration")

# Two-attempt rule: attempt_number is incremented by the coder node; a second
# failure exhausts retries and routes to rollback.
MAX_ATTEMPTS = 2


class GenerationState(TypedDict):
    """State passed through the generation pipeline."""
    messages: Annotated[list, add_messages]
    # Canonical WizardInput (raw dicts are normalized in run_generation).
    wizard_input: WizardInput
    gdd: GameDesignDocument | None
    architecture_plan: Any | None  # ArchitecturePlan (duck-typed for stub agents)
    quest_graphs: list[Any]        # list[QuestGraph]
    dialogue_trees: list[Any]      # list[DialogueTree]
    asset_prompts: list[Any]       # list[AssetPrompt] (from the art pipeline)
    generated_assets: list[GeneratedAsset]
    asset_paths: list[str]
    level_layout: LevelLayout | dict | None
    game_ir: GameIR | dict | None
    generated_files: list[GeneratedFile]
    qa_report: QAReport | None
    playtest_report: PlaytestReport | None
    localization_output: LocalizationOutput | None
    attempt_number: int
    success: bool
    error_message: str | None
    workspace_path: str | None
    skip_agents: list[str]


def _wizard_input_from_dict(wizard_input) -> WizardInput:
    """Coerce a raw wizard dict (API layer) into the validated WizardInput model.

    Maps API field names onto the agent schema; project_name falls back to the
    orchestrator's project id. Unknown keys are dropped.
    """
    if isinstance(wizard_input, WizardInput):
        return wizard_input

    data = dict(wizard_input or {})
    # Canonical model: only remap API-specific field names.
    data.setdefault("project_name", data.get("project_id") or "kotodama-project")
    if not data.get("text_description"):
        data["text_description"] = data.get("description", "")
    try:
        return WizardInput.model_validate(data)
    except Exception:
        pass

    mapped = {
        "project_name": data.get("project_name") or data.get("project_id") or "kotodama-project",
        "genre": data.get("genre", ""),
        "perspective": data.get("perspective", ""),
        "art_style": data.get("art_style", "pixel-art"),
        "setting": data.get("setting", ""),
        "scale": data.get("scale", "small"),
        "controls": data.get("controls", {}),
        "has_saving": bool(data.get("has_saving", False)),
        "monetization": data.get("monetization") or "none",
        "quest_complexity": data.get("quest_complexity", "none"),
        "dialogue_depth": data.get("dialogue_depth", "none"),
        "lore_collection_id": data.get("lore_collection_id"),
        "text_description": data.get("description") or data.get("text_description", ""),
    }
    return WizardInput.model_validate(mapped)


def _module_names(plan: Any) -> list[str]:
    """Best-effort module id/name list from an ArchitecturePlan (or stub)."""
    names: list[str] = []
    for module in getattr(plan, "required_modules", []) or []:
        if isinstance(module, dict):
            names.append(str(module.get("id") or module.get("name") or "module"))
        else:
            names.append(str(getattr(module, "id", None) or getattr(module, "name", None) or "module"))
    return names or ["unknown"]


def _level_parameters(plan: Any) -> dict | None:
    """Extract level_parameters from an ArchitecturePlan (or stub), if present."""
    params = getattr(plan, "level_parameters", None)
    if isinstance(params, dict) and params:
        return params
    if isinstance(plan, dict):
        params = plan.get("level_parameters")
        if isinstance(params, dict) and params:
            return params
    return None


class OrchestratorService:
    """Orchestrates the multi-agent generation pipeline."""

    def __init__(
        self,
        *,
        workspace_manager: Any | None = None,
        analyzer: Any | None = None,
        lore_rag: Any | None = None,
        art_pipeline: Any | None = None,
    ):
        self.designer = GameDesignerAgent()
        self.architect = ArchitectAgent()
        self.quest_designer = QuestDesignerAgent()
        self.dialogue_writer = DialogueWriterAgent()
        self.art_director = ArtDirectorAgent()
        self.level_generator = LevelGeneratorAgent()
        self.coder = CoderAgent()
        self.qa = QAAgent()
        self.playtester = AIPlaytesterAgent()
        self.localization_manager = LocalizationManagerAgent()
        # Injectable for offline tests; default to the process-wide services.
        self.workspace_manager = workspace_manager or _default_workspace_manager()
        self.analyzer = analyzer if analyzer is not None else _default_analyzer()
        self.lore_rag = lore_rag if lore_rag is not None else _default_lore_rag()
        self.art_pipeline = art_pipeline if art_pipeline is not None else _default_art_pipeline()

        self.graph = self._build_graph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow with explicit error edges."""
        builder = StateGraph(GenerationState)

        # Production nodes.
        builder.add_node("designer", self._run_designer)
        builder.add_node("architect", self._run_architect)
        builder.add_node("quest_designer", self._run_quest_designer)
        builder.add_node("dialogue_writer", self._run_dialogue_writer)
        builder.add_node("level_generator", self._run_level_generator)
        builder.add_node("art_director", self._run_art_director)
        builder.add_node("coder", self._run_coder)
        builder.add_node("qa", self._run_qa)
        builder.add_node("playtest", self._run_playtest)
        builder.add_node("localization", self._run_localization)
        # Terminal / control nodes.
        builder.add_node("commit", self._run_commit)
        builder.add_node("rollback", self._run_rollback)
        builder.add_node("fail", self._run_fail)

        builder.add_edge(START, "designer")

        # Every production node gets an explicit error edge via the router:
        # error_message set -> fail/rollback, otherwise continue the pipeline.
        for node, nxt in (
            ("designer", "architect"),
            ("architect", "quest_designer"),
            ("quest_designer", "dialogue_writer"),
            ("dialogue_writer", "level_generator"),
            ("level_generator", "art_director"),
            ("art_director", "coder"),
            ("coder", "qa"),
            ("qa", "playtest"),
        ):
            builder.add_conditional_edges(
                node,
                self._failure_router,
                {"continue": nxt, "fail": "fail", "rollback": "rollback"},
            )

        # Playtest decides retry vs. proceed. Localization runs AFTER it and
        # is non-blocking (its result never changes routing).
        builder.add_conditional_edges(
            "playtest",
            self._after_playtest_router,
            {
                "retry": "coder",
                "continue": "localization",
                "rollback": "rollback",
            },
        )

        builder.add_edge("localization", "commit")
        builder.add_edge("commit", END)
        builder.add_edge("rollback", END)
        builder.add_edge("fail", END)

        # No checkpointer: nodes must not mutate state in place (see module
        # docstring); attempt counting uses local copies inside _run_coder.
        return builder.compile()

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    def _failure_router(self, state: GenerationState) -> Literal["continue", "fail", "rollback"]:
        """Route a node to ``fail``/``rollback`` when it recorded an error.

        Errors raised before any code was generated go to ``fail`` (cheap
        abort); errors after the coder produced files roll the workspace back
        to the baseline tag.
        """
        if state.get("error_message"):
            if state.get("generated_files"):
                return "rollback"
            return "fail"
        return "continue"

    def _after_playtest_router(self, state: GenerationState) -> Literal["retry", "continue", "rollback"]:
        """Route based on playtest results (QA failures retry together with playtest)."""
        if state.get("error_message"):
            return "rollback"

        report = state.get("playtest_report")
        if report is None:
            return "rollback"

        qa_failed = bool(state.get("qa_report")) and not state["qa_report"].passed
        attempts_left = state.get("attempt_number", 0) < MAX_ATTEMPTS

        # Critical failures: retry once while attempts remain, then rollback.
        if report.crashed or report.stability_score < 40:
            return "retry" if attempts_left else "rollback"

        # Success threshold (non-critical): commit-ready unless QA objects.
        if report.success and report.stability_score >= 60:
            if qa_failed and attempts_left:
                return "retry"
            return "continue"

        if attempts_left:
            return "retry"
        return "rollback"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    async def run_generation(self, wizard_input: dict | WizardInput, user_id: str, project_id: str) -> GenerationState:
        """Run the full generation pipeline."""
        # Create workspace
        workspace_path = await self.workspace_manager.create_workspace(project_id, user_id)

        initial_state: GenerationState = {
            "messages": [],
            # Normalize once so every node sees the canonical validated model.
            "wizard_input": _wizard_input_from_dict(wizard_input),
            "gdd": None,
            "architecture_plan": None,
            "quest_graphs": [],
            "dialogue_trees": [],
            "asset_prompts": [],
            "generated_assets": [],
            "asset_paths": [],
            "level_layout": None,
            "game_ir": None,
            "generated_files": [],
            "qa_report": None,
            "playtest_report": None,
            "localization_output": None,
            "attempt_number": 0,
            "success": False,
            "error_message": None,
            "workspace_path": str(workspace_path),
            "skip_agents": [],
        }

        config = {"configurable": {"thread_id": f"{user_id}_{project_id}"}}
        result = await self.graph.ainvoke(initial_state, config)

        return result

    # ------------------------------------------------------------------
    # Production nodes (each calls exactly one agent with its Phase-3
    # single-input model; failures record error_message for _failure_router)
    # ------------------------------------------------------------------
    async def _run_designer(self, state: GenerationState) -> dict:
        """Run Game Designer agent."""
        try:
            wizard = _wizard_input_from_dict(state["wizard_input"])
            gdd = await self.designer.execute(DesignerInput(wizard_input=wizard))
            return {"gdd": gdd, "messages": [f"✓ GDD created: {gdd.title}"]}
        except Exception as e:
            logger.exception("Designer failed")
            return {"error_message": f"Designer failed: {e}"}

    async def _run_architect(self, state: GenerationState) -> dict:
        """Run Architect agent."""
        try:
            plan = await self.architect.execute(ArchitectInput(design_document=state["gdd"]))
            return {
                "architecture_plan": plan,
                "messages": [f"✓ Architecture planned: {len(_module_names(plan))} modules"],
            }
        except Exception as e:
            logger.exception("Architect failed")
            return {"error_message": f"Architect failed: {e}"}

    async def _run_quest_designer(self, state: GenerationState) -> dict:
        """Run Quest Designer agent (skipped when complexity == none)."""
        try:
            if state["gdd"].quest_complexity == "none":
                return {"quest_graphs": [], "messages": ["⏳ Quest Designer: Skipped (complexity=none)"]}

            quests_output = await self.quest_designer.execute(QuestDesignerInput(
                design_document=state["gdd"],
                architecture_plan=state["architecture_plan"],
            ))
            quest_graphs = list(quests_output.quests)
            return {"quest_graphs": quest_graphs, "messages": [f"✓ Generated {len(quest_graphs)} quests"]}
        except Exception as e:
            logger.exception("Quest Designer failed")
            return {"error_message": f"Quest Designer failed: {e}"}

    async def _run_dialogue_writer(self, state: GenerationState) -> dict:
        """Run Dialogue Writer agent (skipped when depth == none)."""
        try:
            if state["gdd"].dialogue_depth == "none":
                return {"dialogue_trees": [], "messages": ["⏳ Dialogue Writer: Skipped (depth=none)"]}

            dialogues_output = await self.dialogue_writer.execute(DialogueWriterInput(
                design_document=state["gdd"],
                quest_graphs=list(state.get("quest_graphs") or []),
            ))
            dialogue_trees = list(dialogues_output.dialogues)
            return {"dialogue_trees": dialogue_trees, "messages": [f"✓ Generated {len(dialogue_trees)} dialogue trees"]}
        except Exception as e:
            logger.exception("Dialogue Writer failed")
            return {"error_message": f"Dialogue Writer failed: {e}"}

    async def _run_level_generator(self, state: GenerationState) -> dict:
        """Run Level Generator agent (only when the plan declares level_parameters)."""
        try:
            params = _level_parameters(state["architecture_plan"])
            if params is None:
                return {"level_layout": None, "messages": ["⏳ Level Generator: Skipped (no level_parameters)"]}

            layout = await self.level_generator.execute(LevelGeneratorInput(
                architecture_plan=state["architecture_plan"],
            ))
            return {"level_layout": layout, "messages": [f"✓ Level layout: {layout.algorithm} {layout.width}x{layout.height}"]}
        except Exception as e:
            logger.exception("Level Generator failed")
            return {"error_message": f"Level Generator failed: {e}"}

    async def _run_art_director(self, state: GenerationState) -> dict:
        """Run Art Director + image pipeline. Non-blocking: failures yield no assets."""
        if "art_director" in (state.get("skip_agents") or []):
            return {
                "asset_prompts": [],
                "generated_assets": [],
                "asset_paths": [],
                "messages": ["⏳ Art Director: Skipped (skip_agents)"],
            }
        try:
            output = await self.art_pipeline.generate_project_assets(
                architecture_plan=state["architecture_plan"],
                art_style=state["wizard_input"].art_style,
                project_id=state["wizard_input"].project_name,
            )
            prompts = list(output.prompts)
            assets = list(output.assets)
            asset_paths = [asset.path for asset in assets]
            return {
                "asset_prompts": prompts,
                "generated_assets": assets,
                "asset_paths": asset_paths,
                "messages": [f"✓ Art: {len(prompts)} prompts, {len(assets)} assets"],
            }
        except Exception as e:
            logger.warning("Art pipeline failed; continuing without assets: %s", e)
            return {
                "asset_prompts": [],
                "generated_assets": [],
                "asset_paths": [],
                "messages": [f"⚠ Art generation skipped: {e}"],
            }

    async def _run_coder(self, state: GenerationState) -> dict:
        """Run Coder agent; increments the attempt counter (two-attempt rule)."""
        try:
            attempt = state.get("attempt_number", 0) + 1

            # Preserve generated assets across a regeneration; they are
            # restored right after the new files land (Phase 4 note #1).
            preserved: list[Path] = []
            workspace_path = state.get("workspace_path")
            if attempt > 1 and workspace_path:
                preserved = await self.workspace_manager.preserve_assets(Path(workspace_path))

            coder_output = await self.coder.execute(CoderInput(
                architecture_plan=state["architecture_plan"],
                quest_graphs=list(state.get("quest_graphs") or []),
                dialogue_trees=list(state.get("dialogue_trees") or []),
                asset_paths=list(state.get("asset_paths") or []),
                level_layout=(
                    state["level_layout"].model_dump()
                    if isinstance(state.get("level_layout"), LevelLayout)
                    else state.get("level_layout")
                ),
            ))
            files = list(coder_output.files)

            if preserved and workspace_path:
                await self.workspace_manager.restore_assets(Path(workspace_path), preserved)
                await self.workspace_manager.clear_preserved(Path(workspace_path))

            game_ir = self._build_game_ir(state, files)
            return {
                "generated_files": files,
                "game_ir": game_ir,
                "attempt_number": attempt,
                "messages": [f"✓ Generated {len(files)} files (Attempt {attempt})"],
            }
        except Exception as e:
            logger.exception("Coder failed")
            return {"error_message": f"Coder failed: {e}"}

    def _build_game_ir(self, state: GenerationState, files: list[GeneratedFile]) -> dict:
        """Assemble the Game IR snapshot persisted alongside the generated code.

        Returned as a plain dict so it stays JSON-serializable for future
        checkpointers; built leniently so stub/partial upstream outputs never
        crash the coder node.
        """
        entities: list[dict] = []
        used_slots = {asset.slot for asset in state.get("generated_assets", [])}
        for slot in sorted(used_slots):
            entities.append({"id": slot, "type": "npc" if slot == "npc" else "decoration", "sprite": slot})
        for quest in state.get("quest_graphs", []):
            for npc in getattr(quest, "npcs_involved", []) or []:
                entities.append({"id": str(npc), "type": "npc"})

        ir = GameIR(
            design_document=state.get("gdd") if isinstance(state.get("gdd"), GameDesignDocument) else None,
            quests=list(state.get("quest_graphs") or []),
            dialogues=list(state.get("dialogue_trees") or []),
            level_layout=state.get("level_layout") if isinstance(state.get("level_layout"), LevelLayout) else None,
            entities=entities,
        )
        payload = ir.model_dump(mode="json")
        payload["files"] = [f.path for f in files]
        return payload

    async def _run_qa(self, state: GenerationState) -> dict:
        """Run QA agent (deterministic validation of the coder output)."""
        try:
            files = list(state.get("generated_files") or [])
            report = await self.qa.execute(QAInput(
                coder_output=CoderOutput(
                    files=files,
                    modules_created=_module_names(state["architecture_plan"]),
                    signals_registered=[],
                ),
                asset_paths=list(state.get("asset_paths") or []),
                signal_contracts=list(getattr(state["architecture_plan"], "signal_contracts", []) or []),
            ))
            return {"qa_report": report, "messages": [f"✓ QA: {'PASSED' if report.passed else 'FAILED'} ({len(report.errors)} errors)"]}
        except Exception as e:
            logger.exception("QA failed")
            return {"error_message": f"QA failed: {e}"}

    async def _run_playtest(self, state: GenerationState) -> dict:
        """Run AI Playtester agent (Godot headless; deterministic failure offline)."""
        try:
            config = PlaytestConfig(
                workspace_path=state["workspace_path"],
                max_frames=900,
                timeout_seconds=60,
            )
            report = await self.playtester.execute(config)
            return {"playtest_report": report, "messages": [f"✓ Playtest: Score {report.stability_score}/100"]}
        except Exception as e:
            logger.exception("Playtest failed")
            return {"error_message": f"Playtest failed: {e}"}

    async def _run_localization(self, state: GenerationState) -> dict:
        """Run Localization Manager. NON-BLOCKING: never sets error_message."""
        try:
            loc_output = await self.localization_manager.execute(LocalizationInput(
                dialogue_trees=list(state.get("dialogue_trees") or []),
                quest_graphs=list(state.get("quest_graphs") or []),
                generated_file_paths=[f.path for f in state.get("generated_files", [])],
            ))

            # Write localization files to the workspace (best effort).
            written = 0
            workspace_path = state.get("workspace_path")
            if workspace_path and loc_output.localization_files:
                loc_dir = Path(workspace_path) / "godot_project" / "assets" / "localization"
                loc_dir.mkdir(parents=True, exist_ok=True)
                for loc_file in loc_output.localization_files:
                    file_path = loc_dir / f"{loc_file.locale}.json"
                    file_path.write_text(
                        json.dumps({"locale": loc_file.locale, "strings": loc_file.strings}, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    written += 1

            warning = f" ⚠ {len(loc_output.missing_keys)} missing keys" if loc_output.missing_keys else ""
            return {
                "localization_output": loc_output,
                "messages": [
                    f"✓ Localization: {len(loc_output.entries)} entries, {written} files{warning}"
                ],
            }
        except Exception as e:
            # Non-blocking: log and continue to commit without localization.
            logger.warning("Localization failed (non-blocking): %s", e)
            return {
                "localization_output": None,
                "messages": [f"⚠ Localization skipped: {e}"],
            }

    # ------------------------------------------------------------------
    # Terminal nodes
    # ------------------------------------------------------------------
    async def _run_commit(self, state: GenerationState) -> dict:
        """Commit successful generation."""
        try:
            changes = _module_names(state["architecture_plan"]) if state.get("architecture_plan") else ["unknown"]
            commit_hash = await self.workspace_manager.save_result(
                Path(state["workspace_path"]),
                changes,
            )
            return {"success": True, "messages": [f"✓ Committed: {str(commit_hash)[:8]}"]}
        except Exception as e:
            logger.exception("Commit failed")
            return {"success": False, "error_message": f"Commit failed: {e}"}

    async def _run_rollback(self, state: GenerationState) -> dict:
        """Rollback to the baseline tag after exhausted retries."""
        try:
            rolled_back = await self.workspace_manager.rollback(Path(state["workspace_path"]))
            await self.workspace_manager.clear_preserved(Path(state["workspace_path"]))
        except Exception as e:
            logger.exception("Rollback execution failed")
            return {
                "success": False,
                "error_message": f"Generation failed after {state.get('attempt_number', 0)} attempts. Rollback failed: {e}",
                "messages": [f"✗ Rollback failed (Attempt {state.get('attempt_number', 0)})"],
            }

        attempts = state.get("attempt_number", 0)
        credit_charged = attempts >= MAX_ATTEMPTS
        detail = state.get("error_message") or (
            f"playtest score {state['playtest_report'].stability_score}"
            if state.get("playtest_report") else "quality gate failed"
        )
        return {
            "success": False,
            "error_message": (
                f"Generation failed after {attempts} attempts. Rollback "
                f"{'successful' if rolled_back else 'failed'}. Credit "
                f"{'charged' if credit_charged else 'NOT charged'}. Last error: {detail}"
            ),
            "messages": [f"✗ Rolled back to baseline (Attempt {attempts})"],
        }

    async def _run_fail(self, state: GenerationState) -> dict:
        """Abort cleanly before anything was generated (no workspace mutation)."""
        return {
            "success": False,
            "messages": [f"✗ Aborted: {state.get('error_message') or 'unknown error'}"],
        }


# ----------------------------------------------------------------------
# Lazy service defaults (keep this module importable without sqlalchemy/minio)
# ----------------------------------------------------------------------
def _default_workspace_manager() -> Any:
    from backend.services.workspace_manager import get_workspace_manager

    return get_workspace_manager()


def _default_analyzer() -> Any:
    from backend.services.incremental_analyzer import get_incremental_analyzer

    return get_incremental_analyzer()


def _default_lore_rag() -> Any:
    from backend.services.lore_rag_service import get_lore_rag_service

    return get_lore_rag_service()


def _default_art_pipeline() -> Any:
    from backend.services.art_pipeline import get_art_pipeline_service

    return get_art_pipeline_service()


# Singleton instance
_orchestrator: OrchestratorService | None = None


def get_orchestrator() -> OrchestratorService:
    """Get or create orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorService()
    return _orchestrator
