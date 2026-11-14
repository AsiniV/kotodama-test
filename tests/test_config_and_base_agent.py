"""Offline unit tests for Phase 1 LLM-foundation plumbing.

Covers:
- backend/core/config.py alignment with .env / .env.example names
  (STABLE_DIFFUSION_URL, unified LLM_* model names, WORKSPACE_ROOT,
  GODOT_HEADLESS_PATH, Radeon 8060S / 128 GB GPU defaults, code max tokens).
- AGENTS.md common preamble loading into BaseAgent system prompts.
- BaseAgent._call_llm routing through the mocked LLM client.

No GPU, LLM server, or network required.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import backend.agents.base as agents_base
from backend.core.config import Settings


class _Out(BaseModel):
    answer: str


class _EchoAgent(agents_base.BaseAgent[_Out]):
    role = "designer"

    def _get_system_prompt(self) -> str:
        return "ROLE-SPECIFIC-PROMPT"

    async def execute(self, input_data: Any) -> _Out:  # pragma: no cover - unused
        return await self._call_llm("prompt", _Out)


# --------------------------------------------------------------------- #
# config alignment
# --------------------------------------------------------------------- #


def test_sd_webui_url_reads_stable_diffusion_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STABLE_DIFFUSION_URL", "http://gpu-box:7861")
    s = Settings(_env_file=None)
    assert s.sd_webui_url == "http://gpu-box:7861"


def test_unified_llm_model_env_names(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CODE_MODEL", "codellama:34b")
    monkeypatch.setenv("LLM_DESIGN_MODEL", "llama3.1:70b")
    monkeypatch.setenv("LLM_EMBEDDING_MODEL", "mxbai-embed-large")
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-coder:32b")
    s = Settings(_env_file=None)
    assert s.ollama_code_model == "codellama:34b"
    assert s.ollama_design_model == "llama3.1:70b"
    assert s.ollama_embedding_model == "mxbai-embed-large"
    assert s.llm_backend == "openai"
    assert s.openai_base_url == "http://vllm:8000/v1"
    assert s.openai_api_key == "sk-test"
    assert s.openai_model == "qwen2.5-coder:32b"


def test_workspace_root_and_godot_headless_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKSPACE_ROOT", "/data/ws")
    monkeypatch.setenv("GODOT_HEADLESS_PATH", "/opt/godot/godot")
    s = Settings(_env_file=None)
    assert s.workspace_root == "/data/ws"
    assert s.godot_headless_path == "/opt/godot/godot"


def test_gpu_defaults_match_ryzen_ai_max():
    s = Settings(_env_file=None)
    assert s.gpu_vendor == "AMD"
    assert "8060S" in s.gpu_model
    assert s.gpu_vram_gb == 128
    assert s.gpu_backend == "rocm"


def test_token_budget_defaults_and_env_overrides(monkeypatch: pytest.MonkeyPatch):
    s = Settings(_env_file=None)
    assert s.llm_max_tokens == 4096
    assert s.llm_code_max_tokens == 16384  # 16384 for code-generating roles

    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")
    monkeypatch.setenv("LLM_CODE_MAX_TOKENS", "32768")
    s2 = Settings(_env_file=None)
    assert s2.llm_max_tokens == 2048
    assert s2.llm_code_max_tokens == 32768


def test_timeout_and_retry_env_aliases(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "42")
    monkeypatch.setenv("AGENT_RETRY_COUNT", "5")
    s = Settings(_env_file=None)
    assert s.llm_timeout_seconds == 42.0
    assert s.llm_max_repair_retries == 5


def test_dotenv_example_covers_documented_env_names():
    """Every env var name used by Settings aliases must appear in .env.example."""
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    for name in (
        "OLLAMA_BASE_URL", "LLM_CODE_MODEL", "LLM_DESIGN_MODEL", "LLM_EMBEDDING_MODEL",
        "LLM_BACKEND", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
        "LLM_TEMPERATURE_CODE", "LLM_TEMPERATURE_DESIGN", "LLM_MAX_TOKENS",
        "LLM_CODE_MAX_TOKENS", "AGENT_TIMEOUT_SECONDS", "AGENT_RETRY_COUNT",
        "GPU_VENDOR", "GPU_MODEL", "GPU_VRAM_GB", "GPU_BACKEND",
        "STABLE_DIFFUSION_URL", "WORKSPACE_ROOT", "GODOT_HEADLESS_PATH",
    ):
        assert f"{name}=" in text, f"{name} missing from .env.example"


# --------------------------------------------------------------------- #
# AGENTS.md common preamble
# --------------------------------------------------------------------- #


def test_agents_md_exists_at_repo_root():
    assert agents_base.AGENTS_MD_PATH.is_file()
    body = agents_base.load_common_preamble()
    assert "Kotodama" in body
    assert "Godot" in body
    assert "<!--" not in body  # maintainer comments stripped
    assert not body.startswith("# ")  # title line dropped


def test_agent_system_prompt_includes_preamble_and_role():
    agent = _EchoAgent()
    assert "ROLE-SPECIFIC-PROMPT" in agent.system_prompt
    assert agent.system_prompt.index("Kotodama") < agent.system_prompt.index("ROLE-SPECIFIC-PROMPT")


def test_missing_agents_md_degrades_gracefully(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agents_base, "AGENTS_MD_PATH", tmp_path / "nope.md")
    agents_base.load_common_preamble.cache_clear()
    try:
        agent = _EchoAgent()
        assert agent.system_prompt == "ROLE-SPECIFIC-PROMPT"
    finally:
        agents_base.load_common_preamble.cache_clear()


# --------------------------------------------------------------------- #
# BaseAgent._call_llm via mocked client
# --------------------------------------------------------------------- #


async def test_call_llm_returns_validated_model_via_mocked_client(install_fake_llm):
    fake = install_fake_llm([{"answer": "ok"}])
    agent = _EchoAgent(model_name="test-model", temperature=0.2)
    out = await agent._call_llm("give me an answer", _Out)
    assert isinstance(out, _Out) and out.answer == "ok"

    call = fake.calls[0]
    assert call["model"] == "test-model"
    assert call["temperature"] == 0.2
    assert call["role"] == "designer"
    assert "Kotodama" in call["system_prompt"]  # preamble reaches the client


async def test_call_llm_rejects_non_model_response_model(install_fake_llm):
    install_fake_llm([{"answer": "x"}])
    agent = _EchoAgent()
    with pytest.raises(Exception):
        await agent._call_llm("p", dict)  # type: ignore[arg-type]
