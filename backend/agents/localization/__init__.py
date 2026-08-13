"""
Localization Manager Agent - Extracts text strings, generates localization files.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import LocalizationOutput, DialogueTree

logger = logging.getLogger("kotodama.agents.localization")


class LocalizationManagerAgent(BaseAgent):
    """
    Localization Manager Agent responsible for extracting and managing text strings.
    
    Input: GeneratedFiles + DialogueTrees
    Output: LocalizationOutput with entries and files
    
    Validates: Every tr() key exists in en.json, no hardcoded strings.
    """
    
    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.1):
        super().__init__(model_name=model_name, temperature=temperature)
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Localization Manager AI specialized in game text extraction.
Your task is to extract all user-facing strings into localization files.

CRITICAL RULES:
1. Every tr() key must exist in en.json
2. No hardcoded user-facing strings in generated code
3. All keys follow naming convention: {category}_{entity}_{field}
4. Maximum key length: 128 characters
5. No duplicate keys

KEY NAMING CONVENTIONS:
- quest_{id}_title: Quest titles
- quest_{id}_desc: Quest descriptions
- quest_{id}_stage_{stage}: Quest stage descriptions
- dl_{npc}_{node}: Dialogue node text
- npc_{id}_name: NPC names
- item_{id}_name: Item names
- item_{id}_desc: Item descriptions
- ui_{action}: UI strings (save_success, load_success, etc.)

OUTPUT FORMAT:
Return LocalizationOutput with:
- entries: list of LocalizationEntry objects
- localization_files: list of LocalizationFile objects (en.json, etc.)
- missing_keys: list of tr() calls without corresponding keys

Output MUST be valid JSON matching LocalizationOutput schema."""

    async def execute(self, dialogue_trees: list[DialogueTree], generated_files: list | None = None) -> LocalizationOutput:
        """
        Execute the Localization Manager agent.
        
        Args:
            dialogue_trees: List of dialogue trees
            generated_files: Optional list of generated files to scan
            
        Returns:
            LocalizationOutput object
        """
        prompt = self._build_prompt(dialogue_trees, generated_files)
        result = await self._call_llm(prompt, LocalizationOutput)
        
        logger.info(f"Extracted {len(result.entries)} localization entries")
        return result
    
    def _build_prompt(self, dialogue_trees: list[DialogueTree], generated_files: list | None) -> str:
        """Build the prompt for the LLM."""
        prompt = f"""Extract localization strings from the following content:

DIALOGUE TREES: {len(dialogue_trees)} trees
GENERATED FILES: {len(generated_files) if generated_files else 0} files

Extract all user-facing strings and generate localization keys.
Follow all rules in the system prompt."""
        
        return prompt


# Singleton instance
_localization_agent = None


def get_localization_agent() -> LocalizationManagerAgent:
    """Get singleton instance of LocalizationManagerAgent."""
    global _localization_agent
    if _localization_agent is None:
        _localization_agent = LocalizationManagerAgent()
    return _localization_agent
