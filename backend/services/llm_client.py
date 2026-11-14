"""
Unified async LLM client with structured (schema-conformant) output.

Supports two backends:
- ``ollama``  — native Ollama server (``ollama.AsyncClient``, ``format=<json schema>``)
- ``openai``  — any OpenAI-compatible endpoint (raw HTTP via ``httpx``,
  ``response_format={"type": "json_schema", ...}``)

The backend is selected automatically: if ``OPENAI_API_KEY`` / ``LLM_API_KEY``
is configured the OpenAI-compatible path is used, otherwise Ollama.

Structured-output enforcement and repair:
1. The Pydantic model's JSON schema is sent with the request so the server
   constrains generation.
2. The response text is parsed as JSON and validated against the model.
3. On parse/validation failure the error text is fed back to the model in a
   repair message and the request is retried (up to ``max_repair_retries``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.core.config import Settings, get_settings

logger = logging.getLogger("kotodama.llm")

T = TypeVar("T", bound=BaseModel)

# Roles that generate code get a much larger output budget by default.
CODE_ROLES = frozenset({"coder", "architect", "qa"})
DEFAULT_CODE_MAX_TOKENS = 16384

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(RuntimeError):
    """Raised when the LLM backend fails (transport/server error)."""


class LLMSchemaValidationError(LLMError):
    """Raised when the model output could not be validated after all retries."""

    def __init__(self, message: str, last_error: Optional[Exception] = None):
        super().__init__(message)
        self.last_error = last_error


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences some models wrap around JSON output."""
    stripped = text.strip()
    return _FENCE_RE.sub("", stripped).strip()


def _schema_for_model(response_model: type[BaseModel]) -> dict[str, Any]:
    """Return a JSON schema suitable for constrained decoding.

    Some providers reject ``$ref``/``$defs`` in structured-output schemas, so we
    inline references (best-effort; falls back to the raw schema on failure).
    """
    schema = response_model.model_json_schema()
    defs = schema.pop("$defs", None)
    if not defs:
        return schema

    def _inline(node: Any, depth: int = 0) -> Any:
        if depth > 50:  # recursion guard
            return node
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.rsplit("/", 1)[-1]
                target = defs.get(name)
                if isinstance(target, dict):
                    merged = {k: v for k, v in node.items() if k != "$ref"}
                    merged.update(_inline(target, depth + 1))
                    return merged
            return {k: _inline(v, depth + 1) for k, v in node.items()}
        if isinstance(node, list):
            return [_inline(v, depth + 1) for v in node]
        return node

    try:
        return _inline(schema)
    except Exception:  # pragma: no cover - defensive
        schema["$defs"] = defs
        return schema


class LLMClient:
    """Async structured-output LLM client (Ollama or OpenAI-compatible)."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        backend: Optional[str] = None,
        ollama_base_url: Optional[str] = None,
        openai_base_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_repair_retries: int = 3,
        default_max_tokens: Optional[int] = None,
        code_max_tokens: Optional[int] = None,
    ):
        s = settings or get_settings()
        self._settings = s

        self.backend = (backend or s.llm_backend or "").lower()
        if self.backend == "auto":
            self.backend = "openai" if (s.openai_api_key) else "ollama"
        if self.backend not in ("ollama", "openai"):
            raise ValueError(f"Unknown LLM backend: {self.backend!r} (expected 'ollama', 'openai' or 'auto')")

        self.ollama_base_url = ollama_base_url or s.ollama_base_url
        self.openai_base_url = (openai_base_url or s.openai_base_url or "").rstrip("/")
        self.openai_api_key = openai_api_key or s.openai_api_key or ""

        self.timeout_seconds = float(timeout_seconds if timeout_seconds is not None else s.llm_timeout_seconds)
        self.max_repair_retries = max(0, int(max_repair_retries))
        self.default_max_tokens = int(default_max_tokens if default_max_tokens is not None else s.llm_max_tokens)
        self.code_max_tokens = int(code_max_tokens if code_max_tokens is not None else s.llm_code_max_tokens)

        self._ollama_client: Any = None  # lazily created ollama.AsyncClient

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    def max_tokens_for_role(self, role: Optional[str]) -> int:
        """Configured max output tokens for an agent role ('coder', 'designer', ...)."""
        if role and role.lower() in CODE_ROLES:
            return self.code_max_tokens
        return self.default_max_tokens

    async def generate(
        self,
        *,
        prompt: str,
        response_model: type[T],
        system_prompt: str = "",
        model: str,
        temperature: float = 0.6,
        max_tokens: Optional[int] = None,
        role: Optional[str] = None,
    ) -> T:
        """Generate a validated instance of ``response_model`` from the LLM.

        Retries up to ``max_repair_retries`` times on invalid JSON / schema
        violations, feeding the validation error text back to the model.
        """
        if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
            raise TypeError(
                f"response_model must be a Pydantic model class, got {response_model!r}. "
                "For lists use a wrapper model (e.g. QuestGraphList)."
            )

        budget = int(max_tokens) if max_tokens is not None else self.max_tokens_for_role(role)
        schema = _schema_for_model(response_model)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        last_error: Optional[Exception] = None
        attempts = self.max_repair_retries + 1
        for attempt in range(1, attempts + 1):
            raw = await self._complete(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=budget,
                schema=schema,
                schema_name=response_model.__name__,
            )
            try:
                data = json.loads(_strip_code_fences(raw))
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = e
                logger.warning(
                    "LLM output failed validation (%s, attempt %d/%d): %s",
                    response_model.__name__, attempt, attempts, str(e)[:500],
                )
                if attempt < attempts:
                    messages = messages + [
                        {"role": "assistant", "content": _truncate(raw)},
                        {
                            "role": "user",
                            "content": (
                                "Your previous reply was not valid for the required JSON schema.\n"
                                f"Validation error:\n{str(e)[:2000]}\n\n"
                                "Respond again with ONLY a corrected JSON object that matches the "
                                "schema exactly. No prose, no markdown fences."
                            ),
                        },
                    ]

        raise LLMSchemaValidationError(
            f"LLM output failed {response_model.__name__} validation after {attempts} attempt(s): {last_error}",
            last_error=last_error,
        )

    async def close(self) -> None:
        if self._ollama_client is not None:
            try:
                await self._ollama_client._client.aclose()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - best effort cleanup
                pass
            self._ollama_client = None

    # ------------------------------------------------------------------ #
    # backends
    # ------------------------------------------------------------------ #

    def _get_ollama_client(self):
        if self._ollama_client is None:
            from ollama import AsyncClient

            self._ollama_client = AsyncClient(host=self.ollama_base_url, timeout=self.timeout_seconds)
        return self._ollama_client

    async def _complete(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        schema: dict[str, Any],
        schema_name: str,
    ) -> str:
        if self.backend == "ollama":
            return await self._complete_ollama(
                messages=messages, model=model, temperature=temperature,
                max_tokens=max_tokens, schema=schema,
            )
        return await self._complete_openai(
            messages=messages, model=model, temperature=temperature,
            max_tokens=max_tokens, schema=schema, schema_name=schema_name,
        )

    async def _complete_ollama(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        schema: dict[str, Any],
    ) -> str:
        client = self._get_ollama_client()
        try:
            response = await client.chat(
                model=model,
                messages=messages,
                format=schema,
                options={
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            )
        except Exception as e:  # ollama library raises many transport errors
            raise LLMError(f"Ollama request failed ({self.ollama_base_url}, model={model}): {e}") from e
        content = getattr(getattr(response, "message", None), "content", None)
        if content is None and isinstance(response, dict):  # tolerate dict-shaped responses (mocks)
            content = response.get("message", {}).get("content")
        if content is None:
            raise LLMError("Ollama returned no message content")
        return str(content)

    async def _complete_openai(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        schema: dict[str, Any],
        schema_name: str,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": re.sub(r"[^A-Za-z0-9_-]", "_", schema_name)[:64] or "response",
                    "schema": schema,
                    "strict": False,  # strict mode requires additionalProperties:false everywhere
                },
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.openai_api_key:
            headers["Authorization"] = f"Bearer {self.openai_api_key}"

        url = f"{self.openai_base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise LLMError(f"OpenAI-compatible request failed ({url}, model={model}): {e}") from e

        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Malformed OpenAI-compatible response: {data}") from e


# ---------------------------------------------------------------------- #
# module-level cached client (per event loop)
# ---------------------------------------------------------------------- #

_cached_client: Optional[LLMClient] = None
_client_loop_id: Optional[int] = None


async def get_llm_client(settings: Optional[Settings] = None) -> LLMClient:
    """Return a process-wide LLMClient bound to the running event loop."""
    global _cached_client, _client_loop_id

    loop_id = id(asyncio.get_running_loop())
    if _cached_client is not None and _client_loop_id == loop_id:
        return _cached_client

    if _cached_client is not None:
        await _cached_client.close()

    _cached_client = LLMClient(settings=settings)
    _client_loop_id = loop_id
    return _cached_client


def truncate_text(text: str, limit: int = 4000) -> str:
    """Truncate long text for embedding into repair messages."""
    return _truncate(text, limit)


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"
