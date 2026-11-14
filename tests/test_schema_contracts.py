"""Offline schema-contract tests (Phase 2 — Schema fixes).

Verifies that the pydantic schemas match what the agents and the orchestrator
actually read:

1. ``GameDesignDocument`` exposes ``quest_complexity`` / ``dialogue_depth``
   (the orchestrator's skip logic reads them straight off the GDD — no
   AttributeError allowed).
2. ``WizardInput`` has a single source of truth (``agent_schemas``);
   ``api_schemas`` re-exports the *same class*; ``controls`` is a dict and the
   free-text field is named ``text_description`` everywhere.
3. List outputs are wrapped in object models (``QuestGraphList``,
   ``DialogueTreeList``, ``PromptUpdates``) with JSON-schema roots of type
   ``object``; quest_designer / dialogue_writer / prompt_refiner pass those
   wrapper classes to the LLM client as ``response_model`` — never
   ``type(list[...])`` — and their list outputs parse from raw JSON.

Everything external (LLM servers, DB, Godot, network) is mocked; the suite
runs fully offline.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

import backend.schemas.agent_schemas as agent_schemas
import backend.schemas.api_schemas as api_schemas
from backend.agents.dialogue_writer import DialogueWriterAgent
from backend.agents.prompt_refiner import PromptRefinerAgent
from backend.agents.quest_designer import QuestDesignerAgent
from backend.core.config import Settings
from backend.services.llm_client import LLMClient
from backend.schemas.agent_schemas import (
    DialogueChoice,
    DialogueNode,
    DialogueTree,
    DialogueTreeList,
    DialogueWriterInput,
    GameDesignDocument,
    GenerationRecord,
    PromptRefinerInput,
    PromptUpdate,
    PromptUpdates,
    QuestDesignerInput,
    QuestGraph,
    QuestGraphList,
    QuestStage,
    WizardInput,
)

SCHEMAS_DIR = Path(agent_schemas.__file__).parent


# --------------------------------------------------------------------- #
# sample data
# --------------------------------------------------------------------- #

def make_gdd(**overrides) -> GameDesignDocument:
    base = dict(
        title="Whispering Woods",
        genre="action-adventure",
        perspective="top-down",
        art_style="pixel-art",
        setting="haunted forest",
        scale="small",
        core_mechanics=["exploration"],
        target_audience="casual",
        unique_selling_points=["atmosphere"],
        module_dependencies=["player_controller"],
        estimated_modules=["player_controller"],
        quest_complexity="simple",
        dialogue_depth="linear",
    )
    base.update(overrides)
    return GameDesignDocument(**base)


def make_wizard(**overrides) -> WizardInput:
    base = dict(
        genre="action-adventure",
        perspective="top-down",
        art_style="pixel-art",
        setting="haunted forest",
        scale="small",
        controls={"move": "wasd", "interact": "e"},
        text_description="A tiny haunted-forest adventure.",
        project_name="schema-proj",
    )
    base.update(overrides)
    return WizardInput(**base)


QUEST_RAW = {
    "quests": [
        {
            "quest_id": "q1",
            "title": "Find the Lantern",
            "description": "Retrieve the lost lantern.",
            "stages": [
                {"id": "s1", "description": "Talk to the elder", "type": "intro"},
                {"id": "s2", "description": "Enter the cave", "type": "objective"},
                {
                    "id": "s3",
                    "description": "Return the lantern",
                    "type": "outro",
                    "rewards": [{"type": "item", "id": "lantern_blessed"}],
                },
            ],
            "dependencies": [],
            "npcs_involved": ["elder"],
            "items_required": ["lantern"],
        }
    ]
}

DIALOGUE_RAW = {
    "dialogues": [
        {
            "dialogue_id": "d1",
            "npc_id": "elder",
            "trigger": "approach",
            "nodes": [
                {
                    "id": "n1",
                    "speaker": "elder",
                    "text_key": "d1_n1",
                    "choices": [{"text_key": "d1_n1_c1", "next": "n2"}],
                },
                {"id": "n2", "speaker": "elder", "text_key": "d1_n2", "choices": []},
            ],
            "conditions": {},
        }
    ]
}

UPDATES_RAW = {"updates": [{"agent_name": "coder", "updated_prompt": "Type your GDScript."}]}


# --------------------------------------------------------------------- #
# 1. GameDesignDocument fields
# --------------------------------------------------------------------- #


def test_gdd_has_complexity_and_depth_fields():
    for field in ("quest_complexity", "dialogue_depth"):
        assert field in GameDesignDocument.model_fields, f"GameDesignDocument missing {field}"


def test_gdd_reads_fields_without_attribute_error():
    gdd = make_gdd()
    # exactly the attribute access pattern used by orchestration._run_quest_designer
    # and _run_dialogue_writer:
    assert gdd.quest_complexity == "simple"
    assert gdd.dialogue_depth == "linear"


def test_gdd_complexity_defaults_are_none():
    gdd = make_gdd(quest_complexity=None, dialogue_depth=None) if False else None  # noqa: F841 - keep explicit below
    payload = make_gdd().model_dump(mode="json")
    del payload["quest_complexity"]
    del payload["dialogue_depth"]
    parsed = GameDesignDocument.model_validate(payload)
    assert parsed.quest_complexity == "none"
    assert parsed.dialogue_depth == "none"


@pytest.mark.parametrize("value", ["none", "simple", "branching", "epic"])
def test_gdd_quest_complexity_accepts_literal_values(value: str):
    assert make_gdd(quest_complexity=value).quest_complexity == value


@pytest.mark.parametrize("value", ["none", "linear", "branching", "full_rpg"])
def test_gdd_dialogue_depth_accepts_literal_values(value: str):
    assert make_gdd(dialogue_depth=value).dialogue_depth == value


def test_gdd_rejects_unknown_complexity_values():
    with pytest.raises(ValidationError):
        make_gdd(quest_complexity="mega")
    with pytest.raises(ValidationError):
        make_gdd(dialogue_depth="deep")


# --------------------------------------------------------------------- #
# 2. WizardInput unification
# --------------------------------------------------------------------- #


def test_wizard_input_single_source_of_truth():
    assert api_schemas.WizardInput is agent_schemas.WizardInput


def test_only_one_wizard_input_class_defined_in_backend():
    """No file under backend/schemas may define a second WizardInput class."""
    found = []
    for path in sorted(SCHEMAS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "WizardInput":
                found.append(path.name)
    assert found == ["agent_schemas.py"], f"WizardInput defined in multiple modules: {found}"


def test_wizard_controls_is_dict_typed():
    field = WizardInput.model_fields["controls"]
    assert field.default_factory is dict
    # legacy list-shaped controls must be rejected cleanly (not coerced)
    with pytest.raises(ValidationError):
        make_wizard(controls=["up", "down", "left", "right"])


def test_wizard_uses_text_description_everywhere():
    assert "text_description" in WizardInput.model_fields
    assert "description" not in WizardInput.model_fields
    assert "user_description" not in WizardInput.model_fields


def test_wizard_optional_fields_have_safe_defaults():
    wi = make_wizard()
    assert wi.controls == {"move": "wasd", "interact": "e"}
    assert wi.has_saving is False
    assert wi.monetization == "none"
    assert wi.quest_complexity == "none"
    assert wi.dialogue_depth == "none"
    assert wi.lore_collection_id is None


def test_api_generation_request_embeds_canonical_wizard_input():
    req = api_schemas.GenerationRequest(
        project_id=1, request_type="create", wizard_input=make_wizard()
    )
    assert isinstance(req.wizard_input, agent_schemas.WizardInput)


# --------------------------------------------------------------------- #
# 3. List wrapper models + response_model wiring
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "wrapper,attr,item_cls",
    [
        (QuestGraphList, "quests", QuestGraph),
        (DialogueTreeList, "dialogues", DialogueTree),
        (PromptUpdates, "updates", PromptUpdate),
    ],
)
def test_wrapper_models_are_object_rooted_list_wrappers(wrapper, attr, item_cls):
    assert attr in wrapper.model_fields
    schema = wrapper.model_json_schema()
    assert schema.get("type") == "object", f"{wrapper.__name__} schema root must be an object"
    assert schema["properties"][attr]["type"] == "array"
    # default construction yields an empty list (agents return these on 'none' levels)
    assert getattr(wrapper(), attr) == []


def test_quest_graph_list_parses_raw_llm_json():
    parsed = QuestGraphList.model_validate(json.loads(json.dumps(QUEST_RAW)))
    assert len(parsed.quests) == 1
    q = parsed.quests[0]
    assert isinstance(q, QuestGraph)
    assert isinstance(q.stages[0], QuestStage)
    assert q.stages[-1].rewards == [{"type": "item", "id": "lantern_blessed"}]


def test_dialogue_tree_list_parses_raw_llm_json():
    parsed = DialogueTreeList.model_validate(json.loads(json.dumps(DIALOGUE_RAW)))
    assert len(parsed.dialogues) == 1
    d = parsed.dialogues[0]
    assert isinstance(d, DialogueTree)
    assert isinstance(d.nodes[0], DialogueNode)
    assert isinstance(d.nodes[0].choices[0], DialogueChoice)


def test_prompt_updates_parses_raw_llm_json():
    parsed = PromptUpdates.model_validate(json.loads(json.dumps(UPDATES_RAW)))
    assert parsed.updates == [PromptUpdate(agent_name="coder", updated_prompt="Type your GDScript.")]


def test_llm_client_rejects_non_model_response_types():
    """The historical bug: passing type(list[...]) instead of a wrapper model."""
    settings = Settings(llm_backend="ollama")
    client = LLMClient(settings=settings, default_max_tokens=10, code_max_tokens=10, max_repair_retries=0)
    broken: object = list[QuestGraph]  # what `type(list[...])` produced
    with pytest.raises(TypeError, match="wrapper model"):
        import asyncio

        asyncio.run(client.generate(prompt="x", response_model=broken, model="m", temperature=0.0))  # type: ignore[arg-type]


AGENT_MODULES = {
    "quest_designer": SCHEMAS_DIR.parent / "agents" / "quest_designer" / "__init__.py",
    "dialogue_writer": SCHEMAS_DIR.parent / "agents" / "dialogue_writer" / "__init__.py",
    "prompt_refiner": SCHEMAS_DIR.parent / "agents" / "prompt_refiner" / "__init__.py",
}


@pytest.mark.parametrize("agent_name", sorted(AGENT_MODULES))
def test_agents_pass_wrapper_classes_not_type_list(agent_name: str):
    """AST guard: `_call_llm(..., <Model>)` must use a plain name, never type(list[...])."""
    source = AGENT_MODULES[agent_name].read_text(encoding="utf-8")
    assert "type(list[" not in source
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_call_llm"
            and len(node.args) >= 2
        ):
            model_arg = node.args[1]
            assert isinstance(model_arg, ast.Name), (
                f"{agent_name}: _call_llm response_model arg must be a plain model class name"
            )


async def test_quest_designer_uses_quest_graph_list_response_model(install_fake_llm):
    fake = install_fake_llm([QUEST_RAW])  # raw JSON dict -> exercises real validation path
    gdd = make_gdd(quest_complexity="simple")
    out = await QuestDesignerAgent().execute(
        QuestDesignerInput(
            design_document=gdd,
            npc_registry=["elder"],
            item_registry=["lantern"],
            location_registry=[],
        )
    )
    assert isinstance(out, QuestGraphList)
    assert [q.quest_id for q in out.quests] == ["q1"]
    call = fake.calls[0]
    assert call["response_model"] is QuestGraphList
    assert call["role"] == "quest_designer"


async def test_quest_designer_skips_on_none_complexity(install_fake_llm):
    fake = install_fake_llm([QUEST_RAW])
    out = await QuestDesignerAgent().execute(
        QuestDesignerInput(design_document=make_gdd(quest_complexity="none"))
    )
    assert isinstance(out, QuestGraphList)
    assert out.quests == []
    assert fake.calls == []  # LLM never called


async def test_dialogue_writer_uses_dialogue_tree_list_response_model(install_fake_llm):
    fake = install_fake_llm([DIALOGUE_RAW])
    gdd = make_gdd(dialogue_depth="linear")
    out = await DialogueWriterAgent().execute(
        DialogueWriterInput(
            design_document=gdd,
            localization_keys=["d1_n1", "d1_n1_c1", "d1_n2"],
        )
    )
    assert isinstance(out, DialogueTreeList)
    assert [d.dialogue_id for d in out.dialogues] == ["d1"]
    call = fake.calls[0]
    assert call["response_model"] is DialogueTreeList
    assert call["role"] == "dialogue_writer"


async def test_dialogue_writer_skips_on_none_depth(install_fake_llm):
    fake = install_fake_llm([DIALOGUE_RAW])
    out = await DialogueWriterAgent().execute(
        DialogueWriterInput(design_document=make_gdd(dialogue_depth="none"))
    )
    assert isinstance(out, DialogueTreeList)
    assert out.dialogues == []
    assert fake.calls == []


async def test_prompt_refiner_uses_prompt_updates_response_model(install_fake_llm):
    fake = install_fake_llm([UPDATES_RAW])
    history = [GenerationRecord(agent="coder", success=False, error_type="syntax")]
    out = await PromptRefinerAgent().execute(PromptRefinerInput(generation_history=history))
    assert isinstance(out, PromptUpdates)
    assert out.updates[0].agent_name == "coder"
    call = fake.calls[0]
    assert call["response_model"] is PromptUpdates
    assert call["role"] == "refiner" or call["role"] == "prompt_refiner"


# --------------------------------------------------------------------- #
# 4. Orchestrator consumption contract (no AttributeError on GDD fields)
# --------------------------------------------------------------------- #


def test_orchestrator_reads_gdd_complexity_attributes():
    """Mirror of orchestration._run_quest_designer/_run_dialogue_writer checks."""
    state_gdd = make_gdd(quest_complexity="none", dialogue_depth="none")
    # these expressions must not raise AttributeError:
    skip_quests = state_gdd.quest_complexity == "none"
    skip_dialogues = state_gdd.dialogue_depth == "none"
    assert skip_quests and skip_dialogues


def test_orchestrator_unwraps_list_outputs_like_production():
    quests_out = QuestGraphList.model_validate(QUEST_RAW)
    dialogues_out = DialogueTreeList.model_validate(DIALOGUE_RAW)
    # orchestration nodes store the unwrapped lists in the graph state:
    quest_graphs = quests_out.quests
    dialogue_trees = dialogues_out.dialogues
    assert all(isinstance(q, QuestGraph) for q in quest_graphs)
    assert all(isinstance(d, DialogueTree) for d in dialogue_trees)


def test_downstream_input_models_accept_unwrapped_lists():
    """CoderInput / DialogueWriterInput / LocalizationInput take bare lists."""
    quests = QuestGraphList.model_validate(QUEST_RAW).quests
    dialogues = DialogueTreeList.model_validate(DIALOGUE_RAW).dialogues
    gdd = make_gdd()

    di = DialogueWriterInput(design_document=gdd, quest_graphs=quests)
    assert di.quest_graphs == quests

    from backend.schemas.agent_schemas import CoderInput, LocalizationInput
    from backend.schemas.agent_schemas import ArchitecturePlan

    arch = ArchitecturePlan(
        scene_tree={"root": "Main"}, required_modules=[], signal_contracts=[], asset_slots_needed=[]
    )
    ci = CoderInput(architecture_plan=arch, quest_graphs=quests, dialogue_trees=dialogues)
    assert ci.quest_graphs == quests and ci.dialogue_trees == dialogues

    li = LocalizationInput(dialogue_trees=dialogues, quest_graphs=quests)
    assert li.dialogue_trees == dialogues and li.quest_graphs == quests


def test_wrapper_models_roundtrip_through_json_schema_validation():
    """model_validate(model_dump()) keeps nested items as typed models."""
    original = QuestGraphList.model_validate(QUEST_RAW)
    again = QuestGraphList.model_validate(original.model_dump(mode="json"))
    assert again == original
    assert isinstance(again.quests[0], QuestGraph)

    original_d = DialogueTreeList.model_validate(DIALOGUE_RAW)
    again_d = DialogueTreeList.model_validate(original_d.model_dump(mode="json"))
    assert again_d == original_d
