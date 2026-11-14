"""Shared pytest fixtures for the Kotodama backend test suite.

Everything external (LLM servers, DB, MinIO, Godot) is mocked — the suite
runs fully offline with no GPU / network / hardware requirements.
"""
from __future__ import annotations

import json
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force deterministic offline settings for every test."""
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)


class ScriptedLLMClient:
    """Fake LLMClient whose ``generate`` returns pre-scripted payloads.

    Each payload may be a JSON string or an already-built object. The raw
    text is validated against the requested response model exactly like the
    real client does, so schema-repair behaviour can be exercised by
    patching the underlying transport instead.
    """

    def __init__(self, payloads: list[Any]):
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any):
        from pydantic import BaseModel

        self.calls.append(kwargs)
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        if isinstance(payload, BaseModel):
            return payload
        model = kwargs["response_model"]
        return model.model_validate(json.loads(payload) if isinstance(payload, str) else payload)


@pytest.fixture
def install_fake_llm(monkeypatch: pytest.MonkeyPatch):
    """Install a ScriptedLLMClient as the process-wide LLM client factory."""
    import backend.services.llm_client as llm_client

    def _install(payloads: list[Any]) -> ScriptedLLMClient:
        fake = ScriptedLLMClient(payloads)

        async def _get_llm_client(settings=None):
            return fake

        monkeypatch.setattr(llm_client, "get_llm_client", _get_llm_client)
        # Agents import get_llm_client lazily inside BaseAgent._call_llm via the
        # module attribute, so patching the module is sufficient.
        return fake

    return _install
