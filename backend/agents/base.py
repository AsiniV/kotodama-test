"""
Base class for all Kotodama agents.
Provides common functionality for LLM interaction, prompt management, and output validation.
"""

from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Any, Generic, Optional, TypeVar
import logging

from pydantic import BaseModel

logger = logging.getLogger("kotodama.agents")

T = TypeVar('T', bound=BaseModel)

# Repo root: backend/agents/base.py -> parents[2] == /workspace (repo root)
REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD_PATH = REPO_ROOT / "AGENTS.md"


def _strip_html_comments(text: str) -> str:
    """Remove HTML comments (maintainer notes) from a markdown document."""
    out: list[str] = []
    rest = text
    while True:
        start = rest.find("<!--")
        if start == -1:
            out.append(rest)
            break
        out.append(rest[:start])
        end = rest.find("-->", start + 4)
        if end == -1:  # unterminated comment: drop the remainder
            break
        rest = rest[end + 3:]
    return "".join(out)


@lru_cache(maxsize=None)
def load_common_preamble(path: Optional[Path] = None) -> str:
    """Load the common system-prompt preamble stored in AGENTS.md (repo root).

    The file is read once per path and cached; maintainer-only HTML comments are
    stripped. If the file is missing the pipeline still works — an empty
    preamble is returned and a warning is logged.
    """
    md_path = path or AGENTS_MD_PATH
    try:
        raw = md_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read agent preamble %s: %s", md_path, e)
        return ""
    body = _strip_html_comments(raw).strip()
    # Drop the leading markdown title line; it adds no instruction value.
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        body = "\n".join(lines[1:]).strip()
    return body


class BaseAgent(ABC, Generic[T]):
    """
    Abstract base class for all agents in the Kotodama system.

    Each agent is responsible for a specific task in the game generation pipeline.
    Agents communicate through structured Pydantic models and follow the LangGraph
    pattern: ``execute()`` takes exactly ONE pydantic input model and returns one
    validated pydantic output model.
    """

    # Agent role used for per-role LLM settings (e.g. max output tokens).
    # Subclasses override with 'designer', 'architect', 'coder', ...
    role: str = "generic"

    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.6):
        """
        Initialize the agent.

        Args:
            model_name: Name of the LLM model to use (via Ollama or OpenAI-compatible server)
            temperature: Sampling temperature for generation
        """
        self.model_name = model_name
        self.temperature = temperature
        # Common preamble (AGENTS.md, repo root) + role-specific system prompt.
        preamble = load_common_preamble()
        role_prompt = self._get_system_prompt().strip()
        self.system_prompt = f"{preamble}\n\n{role_prompt}" if preamble else role_prompt

    @abstractmethod
    def _get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        pass

    @abstractmethod
    async def execute(self, input_data: Any) -> T:
        """
        Execute the agent's task.

        Args:
            input_data: A single pydantic input model for this agent.

        Returns:
            Structured output matching the agent's output schema.
        """
        pass

    async def _call_llm(self, prompt: str, response_model: type[T]) -> T:
        """
        Call the LLM through the unified structured-output client.

        The Pydantic model's JSON schema is sent to the backend (Ollama
        ``format=schema`` / OpenAI ``response_format=json_schema``). On
        validation failure the client retries up to 3 times, feeding the
        validation error text back to the model.

        Args:
            prompt: The user prompt to send to the LLM
            response_model: Pydantic model class to validate the response into

        Returns:
            Validated response instance

        Raises:
            TypeError: if ``response_model`` is not a Pydantic model class
            LLMSchemaValidationError: if output stays invalid after all retries
            LLMError: on transport/backend failures
        """
        from backend.services.llm_client import get_llm_client

        client = await get_llm_client()
        return await client.generate(
            prompt=prompt,
            response_model=response_model,
            system_prompt=self.system_prompt,
            model=self.model_name,
            temperature=self.temperature,
            role=self.role,
        )

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
            "role": self.role,
            "model": self.model_name,
            "temperature": str(self.temperature),
        }
