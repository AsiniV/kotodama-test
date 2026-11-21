"""
Game Designer Agent - Converts wizard input + Lore into structured GDD.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import DesignerInput, WizardInput, GameDesignDocument

logger = logging.getLogger("kotodama.agents.designer")


class GameDesignerAgent(BaseAgent[GameDesignDocument]):
    """
    Game Designer Agent responsible for creating structured Game Design Documents.

    Contract (Phase 1): execute() takes exactly ONE pydantic input model.

    Input: DesignerInput(wizard_input: WizardInput, lore_context: Optional[str])
    Output: GameDesignDocument with module dependencies and estimated modules
    """

    role = "designer"

    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.6):
        super().__init__(model_name=model_name, temperature=temperature)

    def _get_system_prompt(self) -> str:
        return """You are an expert Game Designer AI specialized in Godot 4.3 game development.
Your task is to convert user input from a 14-step wizard into a structured Game Design Document (GDD).

CRITICAL RULES:
1. NEVER suggest modifications to the Core Engine - only modules/plugins
2. All module communication must use signals with `module_` prefix
3. Respect the closed vocabulary of 10 asset slots: player, enemy, background, ui_button, tileset, item, npc, projectile, hazard, icon
4. Quest complexity levels: none, simple (1-2 quests), branching (2-3 quests), epic (4-6 quests with dependencies)
5. Dialogue depth levels: none, linear (text only), branching (2-3 choices), full_rpg (conditions, flags, quest triggers)

MODULE ARCHITECTURE:
- Core Engine is immutable (Scene Management, Input System, Global Signal Bus, State Machine, Physics, UI Framework)
- Modules are isolated scenes/scripts (PlayerController, InventorySystem, BossMechanic, QuestManager, DialogueSystem)
- Adding/removing modules never breaks the rest of the game

Generate a comprehensive GDD that includes:
- Clear genre, perspective, art style, setting, scale
- Core mechanics (3-5 key gameplay elements)
- Target audience description
- Unique selling points (what makes this game special)
- Module dependencies (which modules are required)
- Estimated modules to generate
- quest_complexity and dialogue_depth echoed from the wizard input

Output MUST be valid JSON matching the GameDesignDocument schema."""

    async def execute(self, input_data: DesignerInput) -> GameDesignDocument:
        """
        Execute the Game Designer agent.

        Args:
            input_data: DesignerInput wrapping WizardInput (+ optional lore context)

        Returns:
            GameDesignDocument with complete game design

        Raises:
            TypeError: if input_data is not a DesignerInput
            ValueError: if the wrapped wizard input fails validation
        """
        if not isinstance(input_data, DesignerInput):
            raise TypeError(
                f"GameDesignerAgent.execute expects DesignerInput, got {type(input_data).__name__}"
            )
        if not self.validate_input(input_data.wizard_input):
            raise ValueError("Invalid wizard input")

        # Build prompt with wizard input and optional lore context
        prompt = self._build_prompt(input_data)

        # Call LLM and parse response (structured output, validated + repaired by llm_client)
        result = await self._call_llm(prompt, GameDesignDocument)

        logger.info(f"Generated GDD for project: {result.title}")
        return result

    def _build_prompt(self, input_data: DesignerInput) -> str:
        """Build the prompt for the LLM."""
        wizard_input = input_data.wizard_input
        prompt = f"""Create a Game Design Document based on the following wizard input:

PROJECT NAME: {wizard_input.project_name}
GENRE: {wizard_input.genre}
PERSPECTIVE: {wizard_input.perspective}
ART STYLE: {wizard_input.art_style}
SETTING: {wizard_input.setting}
SCALE: {wizard_input.scale}
CONTROLS: {wizard_input.controls}
HAS SAVING: {wizard_input.has_saving}
MONETIZATION: {wizard_input.monetization}
QUEST COMPLEXITY: {wizard_input.quest_complexity}
DIALOGUE DEPTH: {wizard_input.dialogue_depth}
DESCRIPTION: {wizard_input.text_description}
"""

        if wizard_input.lore_collection_id:
            prompt += f"\nLORE COLLECTION ID: {wizard_input.lore_collection_id}\n(Lore context will be injected from PGVector)"

        if input_data.lore_context:
            prompt += f"\nLORE CONTEXT:\n{input_data.lore_context}\n"

        # Phase 11: IR-repair feedback from the ir_assembler node (if any).
        if getattr(input_data, "extra_context", None):
            prompt += f"\nVALIDATION FEEDBACK (fix these in your output):\n{input_data.extra_context}\n"

        prompt += "\n\nThe GDD must echo quest_complexity and dialogue_depth from the wizard input."
        prompt += "\n\nGenerate a comprehensive GDD following the rules in the system prompt."

        return prompt

    def validate_input(self, input_data: WizardInput) -> bool:
        """Validate wizard input."""
        if not input_data.project_name or len(input_data.project_name) < 3:
            return False
        if not input_data.genre or not input_data.perspective:
            return False
        if not input_data.text_description or len(input_data.text_description) < 10:
            return False
        return True


# Singleton instance
_designer_agent = None


def get_designer_agent() -> GameDesignerAgent:
    """Get singleton instance of GameDesignerAgent."""
    global _designer_agent
    if _designer_agent is None:
        _designer_agent = GameDesignerAgent()
    return _designer_agent
