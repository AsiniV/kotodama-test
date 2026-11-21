import asyncio, json, sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import test_orchestration_dryrun as t  # noqa: E402
from backend.schemas.agent_schemas import QuestGraphList, DialogueTreeList  # noqa: E402
import backend.services.orchestration as orch_mod  # noqa: E402


def build(level_params):
    tmp = Path(tempfile.mkdtemp())
    wm = t.FakeWorkspaceManager(tmp / "workspaces")
    stub_agents = {
        "designer": t.RecordingAgent(t.make_gdd(quest_complexity="simple", dialogue_depth="linear")),
        "architect": t.RecordingAgent(t.make_plan(level_parameters=level_params)),
        "quest_designer": t.RecordingAgent(QuestGraphList(quests=[])),
        "dialogue_writer": t.RecordingAgent(DialogueTreeList(dialogues=[])),
        "level_generator": t.RecordingAgent(t.make_level_layout()),
        "coder": t.RecordingAgent(t.make_coder_output()),
        "qa": t.RecordingAgent(t.make_qa_report()),
        "playtester": t.RecordingAgent(t.make_playtest_report()),
        "localization_manager": t.RecordingAgent(t.make_localization_output()),
    }
    orch = orch_mod.OrchestratorService.__new__(orchid := orch_mod.OrchestratorService)
    for attr in t.AGENT_ATTRS:
        real_cls = getattr(orch_mod, {
            "designer": "GameDesignerAgent", "architect": "ArchitectAgent", "quest_designer": "QuestDesignerAgent",
            "dialogue_writer": "DialogueWriterAgent", "level_generator": "LevelGeneratorAgent", "coder": "CoderAgent",
            "qa": "QAAgent", "playtester": "AIPlaytesterAgent", "localization_manager": "LocalizationManagerAgent"}[attr])
        setattr(orch, attr, real_cls())
    for attr, stub in stub_agents.items():
        setattr(orch, attr, stub)
    orch.workspace_manager = wm
    orch.analyzer = None
    orch.lore_rag = None
    orch.art_pipeline = t.FakeArtPipeline()
    orch.graph = orch._build_graph()
    return orch, stub_agents


async def main():
    orch, stubs = build({"algorithm": "bsp"})
    res = await orch.run_generation(t.make_wizard(), user_id="u", project_id="p")
    print("success:", res["success"])
    print("error:", (res.get("error_message") or "")[:500])
    for m in res["messages"]:
        print("MSG:", m)
    v = res.get("game_ir_validation") or {}
    print(json.dumps(v.get("errors"), indent=1)[:3000])
    print("attributed:", list((v.get("attributed_to") or {}).keys()))
    print("ir_repair_attempts:", res.get("ir_repair_attempts"), "target:", res.get("ir_repair_target"))

asyncio.run(main())
