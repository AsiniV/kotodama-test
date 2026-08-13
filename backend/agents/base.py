"""
Base class for all Kotodama agents.
Provides common functionality for LLM interaction, prompt management, and output validation.
"""

from abc import ABC, abstractmethod
from typing import Any, TypeVar, Generic
import logging
from pydantic import BaseModel

logger = logging.getLogger("kotodama.agents")

T = TypeVar('T', bound=BaseModel)


class BaseAgent(ABC, Generic[T]):
    """
    Abstract base class for all agents in the Kotodama system.
    
    Each agent is responsible for a specific task in the game generation pipeline.
    Agents communicate through structured Pydantic models and follow the LangGraph pattern.
    """
    
    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.6):
        """
        Initialize the agent.
        
        Args:
            model_name: Name of the LLM model to use (via Ollama)
            temperature: Sampling temperature for generation
        """
        self.model_name = model_name
        self.temperature = temperature
        self.system_prompt = self._get_system_prompt()
        
    @abstractmethod
    def _get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        pass
    
    @abstractmethod
    async def execute(self, input_data: Any) -> T:
        """
        Execute the agent's task.
        
        Args:
            input_data: Input data for the agent
            
        Returns:
            Structured output matching the agent's output schema
        """
        pass
    
    async def _call_llm(self, prompt: str, response_model: type[T]) -> T:
        """
        Call the LLM with the given prompt and parse the response.
        
        Args:
            prompt: The prompt to send to the LLM
            response_model: Pydantic model to parse the response into
            
        Returns:
            Parsed response
        """
        try:
            # Import here to avoid circular dependencies
            from ollama import chat
            from pydantic import ValidationError
            
            response = await chat(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                format="json",
                options={
                    "temperature": self.temperature,
                }
            )
            
            message_content = response.message.content
            
            # Parse JSON response into Pydantic model
            import json
            data = json.loads(message_content)
            return response_model(**data)
            
        except ValidationError as e:
            logger.error(f"Validation error parsing LLM response: {e}")
            raise
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            raise
    
    def validate_input(self, input_data: Any) -> bool:
        """
        Validate input data before processing.
        
        Override in subclasses for custom validation.
        """
        return True
    
    def get_agent_info(self) -> dict[str, str]:
        """Return information about this agent."""
        return {
            "name": self.__class__.__name__,
            "model": self.model_name,
            "temperature": str(self.temperature),
        }
