"""
Quest Designer Agent - Generates quests as state machine graphs.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import GameDesignDocument, ArchitecturePlan, QuestGraph
from backend.validators import create_quest_validator, ValidationResult

logger = logging.getLogger("kotodama.agents.quest_designer")


class QuestDesignerAgent(BaseAgent):
    """
    Quest Designer Agent responsible for generating quest state machines.
    
    Input: GDD + ArchitecturePlan
    Output: QuestGraph list (validated)
    
    Validates: No circular dependencies, all stages reachable, no impossible conditions.
    """
    
    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.6):
        super().__init__(model_name=model_name, temperature=temperature)
        self.validator = None
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Quest Designer AI specialized in creating engaging quest structures.
Your task is to generate quest state machine graphs based on the GDD.

CRITICAL RULES:
1. Quests must be structured as state machines with clear stages (intro → objectives → outro)
2. No circular dependencies between quests
3. All stages must be reachable from start (BFS/DFS verifiable)
4. No impossible conditions (all required items/NPCs/locations must exist)
5. Every quest must have at least one reward
6. No dead-end stages

QUEST COMPLEXITY LEVELS:
- none: 0 quests
- simple: 1-2 linear quests
- branching: 2-3 quests with choices
- epic: 4-6 quests with dependencies, side quests, multiple endings

STAGE TYPES:
- intro: Sets up the quest context
- objective: Player must complete a task
- outro: Quest completion with rewards

Output MUST be valid JSON matching QuestGraph schema."""

    async def execute(self, gdd: GameDesignDocument, arch_plan: ArchitecturePlan, 
                     item_registry: set[str] = None, npc_registry: set[str] = None,
                     location_registry: set[str] = None) -> list[QuestGraph]:
        """
        Execute the Quest Designer agent.
        
        Args:
            gdd: Game Design Document
            arch_plan: Architecture Plan
            item_registry: Set of valid item IDs
            npc_registry: Set of valid NPC IDs
            location_registry: Set of valid location IDs
            
        Returns:
            List of validated QuestGraph objects
            
        Raises:
            ValueError: If validation fails
        """
        if gdd.quest_complexity == "none":
            return []
        
        prompt = self._build_prompt(gdd, arch_plan)
        result = await self._call_llm(prompt, type(list[QuestGraph]))
        
        # Validate generated quests
        validator = create_quest_validator(
            item_registry=item_registry,
            npc_registry=npc_registry,
            location_registry=location_registry
        )
        
        validation_result = validator.validate_multiple_quests(result)
        
        if not validation_result.passed:
            error_msg = f"Quest validation failed: {'; '.join(validation_result.errors)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        if validation_result.warnings:
            for warning in validation_result.warnings:
                logger.warning(f"Quest warning: {warning}")
        
        logger.info(f"Generated and validated {len(result)} quests for {gdd.title}")
        return result
    
    def _build_prompt(self, gdd: GameDesignDocument, arch_plan: ArchitecturePlan) -> str:
        """Build the prompt for the LLM."""
        prompt = f"""Generate quest state machines based on the following GDD:

TITLE: {gdd.title}
GENRE: {gdd.genre}
SETTING: {gdd.setting}
QUEST COMPLEXITY: {gdd.quest_complexity}
CORE MECHANICS: {', '.join(gdd.core_mechanics)}
LORE CONTEXT: {gdd.lore_context or 'None'}

Generate quests appropriate for the complexity level.
Follow all rules in the system prompt."""
        
        return prompt


# Singleton instance
_quest_designer_agent = None


def get_quest_designer_agent() -> QuestDesignerAgent:
    """Get singleton instance of QuestDesignerAgent."""
    global _quest_designer_agent
    if _quest_designer_agent is None:
        _quest_designer_agent = QuestDesignerAgent()
    return _quest_designer_agent
