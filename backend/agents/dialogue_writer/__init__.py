"""
Dialogue Writer Agent - Generates branching dialogue trees with conditions.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import (
    GameDesignDocument,
    QuestGraph,
    DialogueTree,
    DialogueTreeList,
    DialogueWriterInput,
)
from backend.validators import create_dialogue_validator, ValidationResult

logger = logging.getLogger("kotodama.agents.dialogue_writer")


class DialogueWriterAgent(BaseAgent[DialogueTreeList]):
    """
    Dialogue Writer Agent responsible for generating branching dialogue trees.
    
    Input: GDD + QuestGraphs + LoreContext
    Output: DialogueTree list (validated)
    
    Validates: All text_keys exist in localization, no orphan nodes, valid actions.
    """
    
    role = "dialogue_writer"

    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.6):
        super().__init__(model_name=model_name, temperature=temperature)
        self.validator = None
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Dialogue Writer AI specialized in creating engaging NPC conversations.
Your task is to generate branching dialogue trees based on the GDD and quests.

CRITICAL RULES:
1. Every text_key must exist in the localization file (format: dl_{npc}_{node})
2. Every 'next' node must exist in the dialogue tree
3. No orphan nodes (all nodes reachable from trigger)
4. Every 'requires' condition must be satisfiable
5. Every 'action' must be valid (give_item, set_flag, start_quest)

DIALOGUE DEPTH LEVELS:
- none: No dialogues
- linear: Simple NPC interactions, no choices
- branching: Player choices affect dialogue flow (2-3 choices per node)
- full_rpg: Complex dialogues with conditions, flags, quest triggers

NODE STRUCTURE:
- id: Unique node identifier
- speaker: NPC ID
- text_key: Localization key
- choices: List of player choices with next node references

Output MUST be valid JSON matching DialogueTree schema."""

    async def execute(self, input_data: DialogueWriterInput) -> DialogueTreeList:
        """
        Execute the Dialogue Writer agent.

        Args:
            input_data: DialogueWriterInput with GDD, quest graphs, optional lore
                context and localization/item/flag/quest registries.

        Returns:
            DialogueTreeList of validated DialogueTree objects (empty when
            dialogue_depth == "none")

        Raises:
            TypeError: if input_data is not a DialogueWriterInput
            ValueError: if dialogue validation fails
        """
        if not isinstance(input_data, DialogueWriterInput):
            raise TypeError(
                f"DialogueWriterAgent.execute expects DialogueWriterInput, got {type(input_data).__name__}"
            )

        gdd = input_data.design_document
        if gdd.dialogue_depth == "none":
            return DialogueTreeList(dialogues=[])

        prompt = self._build_prompt(gdd, input_data.quest_graphs, input_data.lore_context)

        # Phase 11: IR-repair feedback from the ir_assembler node (if any).
        if getattr(input_data, "extra_context", None):
            prompt += f"\nVALIDATION FEEDBACK (fix these in your output):\n{input_data.extra_context}\n"
        result = await self._call_llm(prompt, DialogueTreeList)

        # Validate generated dialogues
        validator = create_dialogue_validator(
            localization_keys=set(input_data.localization_keys),
            item_registry=set(input_data.item_registry),
            flag_registry=set(input_data.flag_registry),
            quest_registry=set(input_data.quest_registry),
        )

        validation_result = validator.validate_multiple_dialogues(result.dialogues)

        if not validation_result.passed:
            error_msg = f"Dialogue validation failed: {'; '.join(validation_result.errors)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        if validation_result.warnings:
            for warning in validation_result.warnings:
                logger.warning(f"Dialogue warning: {warning}")

        logger.info(f"Generated and validated {len(result.dialogues)} dialogue trees for {gdd.title}")
        return result

    def _build_prompt(self, gdd: GameDesignDocument, quest_graphs: list[QuestGraph], lore_context: str | None) -> str:
        """Build the prompt for the LLM."""
        prompt = f"""Generate dialogue trees based on the following GDD:

TITLE: {gdd.title}
DIALOGUE DEPTH: {gdd.dialogue_depth}
SETTING: {gdd.setting}
LORE CONTEXT: {lore_context or 'None'}
QUESTS: {len(quest_graphs)} quests available

Generate dialogues appropriate for the depth level.
Follow all rules in the system prompt."""
        
        return prompt


# Singleton instance
_dialogue_writer_agent = None


def get_dialogue_writer_agent() -> DialogueWriterAgent:
    """Get singleton instance of DialogueWriterAgent."""
    global _dialogue_writer_agent
    if _dialogue_writer_agent is None:
        _dialogue_writer_agent = DialogueWriterAgent()
    return _dialogue_writer_agent
