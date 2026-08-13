"""
Complete LangGraph orchestration for all 11 agents.

Pipeline:
START → designer → architect → quest_designer → dialogue_writer → art_director → coder → qa → playtest → commit → END
                                    ↑                                                    │
                                    └──────────────── retry (attempt 1) ──────────────────┘
                                                                                         │
                                                                                         └─→ rollback (attempt 2) → END
"""

import asyncio
from typing import Annotated, TypedDict, Literal
from datetime import datetime

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from backend.agents.designer import GameDesignerAgent
from backend.agents.architect import ArchitectAgent
from backend.agents.quest_designer import QuestDesignerAgent
from backend.agents.dialogue_writer import DialogueWriterAgent
from backend.agents.art_director import ArtDirectorAgent
from backend.agents.coder import CoderAgent
from backend.agents.qa import QAAgent
from backend.agents.playtester import AIPlaytesterAgent
from backend.schemas.agent_schemas import (
    GameDesignDocument, ArchitecturePlan, GeneratedFile,
    QAReport, PlaytestReport, PlaytestConfig, QuestGraph, DialogueTree
)
from backend.services.workspace_manager import get_workspace_manager
from backend.services.incremental_analyzer import get_incremental_analyzer
from backend.services.lore_rag_service import get_lore_rag_service


class GenerationState(TypedDict):
    """State passed through the generation pipeline."""
    messages: Annotated[list, add_messages]
    wizard_input: dict
    gdd: GameDesignDocument | None
    architecture_plan: ArchitecturePlan | None
    generated_files: list[GeneratedFile]
    qa_report: QAReport | None
    playtest_report: PlaytestReport | None
    attempt_number: int
    success: bool
    error_message: str | None
    workspace_path: str | None
    skip_agents: list[str]


class OrchestratorService:
    """Orchestrates the multi-agent generation pipeline."""

    def __init__(self):
        self.designer = GameDesignerAgent()
        self.architect = ArchitectAgent()
        self.quest_designer = QuestDesignerAgent()
        self.dialogue_writer = DialogueWriterAgent()
        self.art_director = ArtDirectorAgent()
        self.coder = CoderAgent()
        self.qa = QAAgent()
        self.playtester = AIPlaytesterAgent()
        self.workspace_manager = get_workspace_manager()
        self.analyzer = get_incremental_analyzer()
        self.lore_rag = get_lore_rag_service()
        
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        builder = StateGraph(GenerationState)
        
        # Add nodes
        builder.add_node("designer", self._run_designer)
        builder.add_node("architect", self._run_architect)
        builder.add_node("quest_designer", self._run_quest_designer)
        builder.add_node("dialogue_writer", self._run_dialogue_writer)
        builder.add_node("art_director", self._run_art_director)
        builder.add_node("coder", self._run_coder)
        builder.add_node("qa", self._run_qa)
        builder.add_node("playtest", self._run_playtest)
        builder.add_node("commit", self._run_commit)
        builder.add_node("rollback", self._run_rollback)
        
        # Define edges
        builder.add_edge(START, "designer")
        builder.add_edge("designer", "architect")
        builder.add_edge("architect", "quest_designer")
        builder.add_edge("quest_designer", "dialogue_writer")
        builder.add_edge("dialogue_writer", "art_director")
        builder.add_edge("art_director", "coder")
        builder.add_edge("coder", "qa")
        
        # Conditional routing after QA
        builder.add_conditional_edges(
            "qa",
            self._after_qa_router,
            {
                "retry": "coder",
                "continue": "playtest",
                "rollback": "rollback",
            }
        )
        
        builder.add_conditional_edges(
            "playtest",
            self._after_playtest_router,
            {
                "retry": "coder",
                "success": "commit",
                "rollback": "rollback",
            }
        )
        
        builder.add_edge("commit", END)
        builder.add_edge("rollback", END)
        
        return builder.compile(checkpointer=MemorySaver())

    def _after_qa_router(self, state: GenerationState) -> Literal["retry", "continue", "rollback"]:
        """Route based on QA results."""
        if state["qa_report"] is None:
            return "rollback"
        
        if not state["qa_report"].passed:
            if state["attempt_number"] < 2:
                return "retry"
            else:
                return "rollback"
        
        return "continue"

    def _after_playtest_router(self, state: GenerationState) -> Literal["retry", "success", "rollback"]:
        """Route based on playtest results."""
        if state["playtest_report"] is None:
            return "rollback"
        
        report = state["playtest_report"]
        
        # Critical failures always rollback
        if report.crashed or report.stability_score < 40:
            if state["attempt_number"] < 2:
                return "retry"
            else:
                return "rollback"
        
        # Success threshold
        if report.success and report.stability_score >= 60:
            return "success"
        
        # Retry if under threshold and attempts remaining
        if state["attempt_number"] < 2:
            return "retry"
        
        return "rollback"

    async def run_generation(self, wizard_input: dict, user_id: str, project_id: str) -> GenerationState:
        """Run the full generation pipeline."""
        # Create workspace
        workspace_path = await self.workspace_manager.create_workspace(project_id, user_id)
        
        initial_state: GenerationState = {
            "messages": [],
            "wizard_input": wizard_input,
            "gdd": None,
            "architecture_plan": None,
            "generated_files": [],
            "qa_report": None,
            "playtest_report": None,
            "attempt_number": 0,
            "success": False,
            "error_message": None,
            "workspace_path": str(workspace_path),
            "skip_agents": [],
        }
        
        config = {"configurable": {"thread_id": f"{user_id}_{project_id}"}}
        result = await self.graph.ainvoke(initial_state, config)
        
        return result

    async def _run_designer(self, state: GenerationState) -> dict:
        """Run Game Designer agent."""
        try:
            gdd = await self.designer.execute(state["wizard_input"])
            return {"gdd": gdd, "messages": [f"✓ GDD created: {gdd.title}"]}
        except Exception as e:
            return {"error_message": f"Designer failed: {str(e)}"}

    async def _run_architect(self, state: GenerationState) -> dict:
        """Run Architect agent."""
        try:
            plan = await self.architect.execute(state["gdd"])
            return {"architecture_plan": plan, "messages": [f"✓ Architecture planned: {len(plan.modules)} modules"]}
        except Exception as e:
            return {"error_message": f"Architect failed: {str(e)}"}

    async def _run_quest_designer(self, state: GenerationState) -> dict:
        """Run Quest Designer agent."""
        try:
            if state["gdd"].quest_complexity == "none":
                return {"quest_graphs": [], "messages": ["⏳ Quest Designer: Skipped (complexity=none)"]}
            
            quest_graphs = await self.quest_designer.execute(state["gdd"], state["architecture_plan"])
            return {"quest_graphs": quest_graphs, "messages": [f"✓ Generated {len(quest_graphs)} quests"]}
        except Exception as e:
            return {"error_message": f"Quest Designer failed: {str(e)}"}

    async def _run_dialogue_writer(self, state: GenerationState) -> dict:
        """Run Dialogue Writer agent."""
        try:
            if state["gdd"].dialogue_depth == "none":
                return {"dialogue_trees": [], "messages": ["⏳ Dialogue Writer: Skipped (depth=none)"]}
            
            # Get lore context if available
            lore_context = None
            if state["wizard_input"].get("lore_collection_id"):
                lore_context = await self.lore_rag.get_collection_context(
                    state["wizard_input"]["lore_collection_id"],
                    "dialogue characters NPCs"
                )
            
            dialogue_trees = await self.dialogue_writer.execute(
                state["gdd"],
                state.get("quest_graphs", []),
                lore_context
            )
            return {"dialogue_trees": dialogue_trees, "messages": [f"✓ Generated {len(dialogue_trees)} dialogue trees"]}
        except Exception as e:
            return {"error_message": f"Dialogue Writer failed: {str(e)}"}

    async def _run_art_director(self, state: GenerationState) -> dict:
        """Run Art Director agent."""
        try:
            # Get lore context if available
            lore_context = None
            if state["wizard_input"].get("lore_collection_id"):
                lore_context = await self.lore_rag.get_collection_context(
                    state["wizard_input"]["lore_collection_id"],
                    "art style visual aesthetic"
                )
            
            art_style = state["wizard_input"].get("art_style", "pixel-art")
            asset_output = await self.art_director.execute(
                state["architecture_plan"],
                lore_context,
                art_style
            )
            
            # Store asset paths for Coder
            asset_paths = [asset.path for asset in asset_output.assets]
            
            return {
                "asset_prompts": asset_output.prompts,
                "generated_assets": asset_output.assets,
                "asset_paths": asset_paths,
                "messages": [f"✓ Generated {len(asset_output.prompts)} asset prompts"]
            }
        except Exception as e:
            return {"error_message": f"Art Director failed: {str(e)}"}

    async def _run_coder(self, state: GenerationState) -> dict:
        """Run Coder agent."""
        try:
            state["attempt_number"] += 1
            
            # Preserve assets before code regeneration
            if state["attempt_number"] > 1 and state["workspace_path"]:
                from pathlib import Path
                preserved = await self.workspace_manager.preserve_assets(Path(state["workspace_path"]))
            
            files = await self.coder.execute(
                state["architecture_plan"],
                state.get("quest_graphs", []),
                state.get("dialogue_trees", []),
                state.get("asset_paths", []),
            )
            
            return {"generated_files": files, "messages": [f"✓ Generated {len(files)} files (Attempt {state['attempt_number']})"]}
        except Exception as e:
            return {"error_message": f"Coder failed: {str(e)}"}

    async def _run_qa(self, state: GenerationState) -> dict:
        """Run QA agent."""
        try:
            report = await self.qa.execute(
                state["generated_files"],
                state["architecture_plan"],
            )
            return {"qa_report": report, "messages": [f"✓ QA: {'PASSED' if report.passed else 'FAILED'} ({report.errors_found} errors)"]}
        except Exception as e:
            return {"error_message": f"QA failed: {str(e)}"}

    async def _run_playtest(self, state: GenerationState) -> dict:
        """Run AI Playtester agent."""
        try:
            if not state["workspace_path"]:
                return {"error_message": "No workspace path for playtest"}
            
            from pathlib import Path
            config = PlaytestConfig(
                workspace_path=state["workspace_path"],
                max_frames=900,
                timeout_seconds=60,
            )
            
            report = await self.playtester.execute(config)
            return {"playtest_report": report, "messages": [f"✓ Playtest: Score {report.stability_score}/100"]}
        except Exception as e:
            return {"error_message": f"Playtest failed: {str(e)}"}

    async def _run_commit(self, state: GenerationState) -> dict:
        """Commit successful generation."""
        try:
            if not state["workspace_path"]:
                return {"error_message": "No workspace to commit"}
            
            from pathlib import Path
            changes = [f.module_id for f in state["architecture_plan"].modules] if state["architecture_plan"] else ["unknown"]
            commit_hash = await self.workspace_manager.save_result(
                Path(state["workspace_path"]),
                changes
            )
            
            return {
                "success": True,
                "messages": [f"✓ Committed: {commit_hash[:8]}"],
            }
        except Exception as e:
            return {"error_message": f"Commit failed: {str(e)}"}

    async def _run_rollback(self, state: GenerationState) -> dict:
        """Rollback to baseline."""
        try:
            if not state["workspace_path"]:
                return {"error_message": "No workspace to rollback"}
            
            from pathlib import Path
            success = await self.workspace_manager.rollback(Path(state["workspace_path"]))
            
            credit_charged = state["attempt_number"] >= 2
            
            return {
                "success": False,
                "error_message": f"Generation failed after {state['attempt_number']} attempts. Rollback {'successful' if success else 'failed'}. Credit {'charged' if credit_charged else 'NOT charged'}.",
                "messages": [f"✗ Rollback executed (Attempt {state['attempt_number']})"],
            }
        except Exception as e:
            return {"error_message": f"Rollback failed: {str(e)}"}


# Singleton instance
_orchestrator: OrchestratorService | None = None


def get_orchestrator() -> OrchestratorService:
    """Get or create orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorService()
    return _orchestrator
