"""
Prompt Refiner Agent - Meta-agent that analyzes generations and updates system prompts.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import PromptRefinerInput, PromptUpdates

logger = logging.getLogger("kotodama.agents.prompt_refiner")


class PromptRefinerAgent(BaseAgent):
    """
    Prompt Refiner Agent (Meta-agent) responsible for improving system prompts.
    
    Input: GenerationHistory (successful and failed generations)
    Output: UpdatedPrompts for each agent type
    
    Analyzes patterns in successful vs failed generations to optimize prompts.
    """
    
    role = "prompt_refiner"

    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.3):
        super().__init__(model_name=model_name, temperature=temperature)
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Prompt Engineering AI specialized in optimizing LLM prompts.
Your task is to analyze generation history and improve system prompts for all agents.

ANALYSIS PROCESS:
1. Identify patterns in successful generations (what worked well)
2. Identify patterns in failed generations (common errors, missing information)
3. Determine which prompt elements need clarification or strengthening
4. Generate updated prompts that address identified issues

PROMPT IMPROVEMENT STRATEGIES:
- Add explicit examples for complex outputs
- Clarify ambiguous instructions
- Strengthen critical rules with consequences
- Add edge case handling
- Improve formatting requirements

OUTPUT FORMAT:
Return a dictionary mapping agent names to their updated system prompts.
Only include agents that need prompt updates.

Focus on incremental improvements, not complete rewrites."""

    async def execute(self, input_data: PromptRefinerInput) -> PromptUpdates:
        """
        Execute the Prompt Refiner agent.

        Args:
            input_data: PromptRefinerInput with the generation history records.

        Returns:
            PromptUpdates with one PromptUpdate per agent that needs changes

        Raises:
            TypeError: if input_data is not a PromptRefinerInput
        """
        if not isinstance(input_data, PromptRefinerInput):
            raise TypeError(
                f"PromptRefinerAgent.execute expects PromptRefinerInput, got {type(input_data).__name__}"
            )

        prompt = self._build_prompt(input_data.generation_history)
        result = await self._call_llm(prompt, PromptUpdates)

        logger.info(f"Generated updates for {len(result.updates)} agent prompts")
        return result

    def _build_prompt(self, history: list) -> str:
        """Build the prompt for the LLM (history items are GenerationRecord models or dicts)."""
        def _is_success(h) -> bool:
            return getattr(h, "success", None) if not isinstance(h, dict) else h.get("success", False)

        successes = [h for h in history if _is_success(h)]
        failures = [h for h in history if not _is_success(h)]
        
        prompt = f"""Analyze the following generation history and suggest prompt improvements:

SUCCESSFUL GENERATIONS: {len(successes)}
FAILED GENERATIONS: {len(failures)}

Success rate: {len(successes) / max(len(history), 1) * 100:.1f}%

Identify patterns and suggest improvements for each agent's system prompt.
Focus on the most common failure modes."""
        
        return prompt


# Singleton instance
_prompt_refiner_agent = None


def get_prompt_refiner_agent() -> PromptRefinerAgent:
    """Get singleton instance of PromptRefinerAgent."""
    global _prompt_refiner_agent
    if _prompt_refiner_agent is None:
        _prompt_refiner_agent = PromptRefinerAgent()
    return _prompt_refiner_agent
