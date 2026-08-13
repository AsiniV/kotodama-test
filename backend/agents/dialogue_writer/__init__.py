"""
Dialogue Writer Agent - Generates branching dialogue trees with conditions.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import GameDesignDocument, QuestGraph, DialogueTree

logger = logging.getLogger("kotodama.agents.dialogue_writer")


class DialogueWriterAgent(BaseAgent):
    """
    Dialogue Writer Agent responsible for generating branching dialogue trees.
    
    Input: GDD + QuestGraphs + LoreContext
    Output: DialogueTree list
    
    Validates: All text_keys exist in localization, no orphan nodes, valid actions.
    """
    
    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.6):
        super().__init__(model_name=model_name, temperature=temperature)
    
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

    async def execute(self, gdd: GameDesignDocument, quest_graphs: list[QuestGraph], lore_context: str | None = None) -> list[DialogueTree]:
        """
        Execute the Dialogue Writer agent.
        
        Args:
            gdd: Game Design Document
            quest_graphs: List of quest graphs
            lore_context: Optional lore context
            
        Returns:
            List of DialogueTree objects
        """
        if gdd.dialogue_depth == "none":
            return []
        
        prompt = self._build_prompt(gdd, quest_graphs, lore_context)
        result = await self._call_llm(prompt, type(list[DialogueTree]))
        
        logger.info(f"Generated {len(result)} dialogue trees for {gdd.title}")
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
