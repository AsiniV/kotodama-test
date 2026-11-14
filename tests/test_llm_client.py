"""Offline unit tests for backend/services/llm_client.py.

No GPU / LLM server / network required: transports are mocked either with
httpx.MockTransport (OpenAI-compatible path) or by patching the ollama
AsyncClient boundary (_complete_ollama).
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field, ValidationError

from backend.core.config import Settings
from backend.services import llm_client as lc
from backend.services.llm_client import (
    CODE_ROLES,
    LLMClient,
    LLMError,
    LLMSchemaValidationError,
    _schema_for_model,
    _strip_code_fences,
)


class SmallModel(BaseModel):
    name: str
    count: int = 0


class WrappedList(BaseModel):
    items: list[str] = Field(default_factory=list)


def make_settings(**overrides: Any) -> Settings:
    base = dict(
        llm_backend="openai",
        openai_base_url="http://fake.local/v1",
        openai_api_key="test-key",
        llm_timeout_seconds=5.0,
    )
    base.update(overrides)
    return Settings._base_cls(**base) if hasattr(Settings, "_base_cls") else Settings.model_construct(**base)


def make_openai_client(responses: list[dict], captured: list[dict]) -> LLMClient:
    """LLMClient whose httpx transport returns scripted JSON responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "json": json.loads(request.content.decode()),
            }
        )
        payload = responses[min(len(captured) - 1, len(responses) - 1)]
        return httpx.Response(200, json=payload)

    client = LLMClient(settings=make_settings())
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    lc.httpx.AsyncClient = patched_async_client  # type: ignore[attr-defined]
    return client


@pytest.fixture(autouse=True)
def _restore_httpx(monkeypatch: pytest.MonkeyPatch):
    real = httpx.AsyncClient
    yield
    lc.httpx.AsyncClient = real  # type: ignore[attr-defined]


# --------------------------------------------------------------------- #
# helpers / configuration
# --------------------------------------------------------------------- #


def test_strip_code_fences():
    assert _strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_code_fences("  plain text  ") == "plain text"


def test_schema_for_model_inlines_refs():
    class Inner(BaseModel):
        x: int

    class Outer(BaseModel):
        inners: list[Inner]

    schema = _schema_for_model(Outer)
    assert "$defs" not in schema
    assert "$ref" not in json.dumps(schema)
    assert schema["properties"]["inners"]["items"]["properties"]["x"]["type"] == "integer"


def test_role_token_budgets():
    client = LLMClient(settings=make_settings(llm_backend="ollama"))
    assert client.max_tokens_for_role("coder") == 16384
    assert client.max_tokens_for_role("architect") == 16384
    assert client.max_tokens_for_role("qa") == 16384
    assert client.max_tokens_for_role("designer") == 4096
    assert client.max_tokens_for_role(None) == 4096
    assert CODE_ROLES == frozenset({"coder", "architect", "qa"})


def test_auto_backend_selection():
    assert LLMClient(settings=make_settings(llm_backend="auto")).backend == "openai"
    assert (
        LLMClient(
            settings=make_settings(llm_backend="auto", openai_api_key="")
        ).backend
        == "ollama"
    )


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        LLMClient(settings=make_settings(llm_backend="mistral"))


# --------------------------------------------------------------------- #
# OpenAI-compatible structured output
# --------------------------------------------------------------------- #


async def test_openai_happy_path_and_request_shape():
    captured: list[dict] = []
    client = make_openai_client(
        [{"choices": [{"message": {"content": '{"name": "ok", "count": 2}'}}]}],
        captured,
    )
    out = await client.generate(
        prompt="hi", response_model=SmallModel, model="m", temperature=0.3, role="designer"
    )
    assert isinstance(out, SmallModel) and out.name == "ok" and out.count == 2

    req = captured[0]["json"]
    body = json.dumps(req["response_format"])
    assert req["response_format"]["type"] == "json_schema"
    assert '"name"' in body and '"count"' in body  # Pydantic schema enforced
    assert req["max_tokens"] == 4096
    assert captured[0]["headers"]["authorization"] == "Bearer test-key"
    assert captured[0]["url"].endswith("/chat/completions")


async def test_openai_strips_markdown_fences():
    captured: list[dict] = []
    client = make_openai_client(
        [{"choices": [{"message": {"content": "```json\n{\"name\": \"fenced\"}\n```"}}]}],
        captured,
    )
    out = await client.generate(prompt="p", response_model=SmallModel, model="m")
    assert out.name == "fenced"


async def test_openai_code_role_gets_large_budget():
    captured: list[dict] = []
    client = make_openai_client(
        [{"choices": [{"message": {"content": '{"name": "c"}'}}]}], captured
    )
    await client.generate(prompt="p", response_model=SmallModel, model="m", role="coder")
    assert captured[0]["json"]["max_tokens"] == 16384


async def test_schema_repair_feeds_error_back():
    bad = {"choices": [{"message": {"content": "not json at all"}}]}
    good = {"choices": [{"message": {"content": '{"name": "fixed", "count": 1}'}}]}
    captured: list[dict] = []
    client = make_openai_client([bad, good], captured)

    out = await client.generate(prompt="p", response_model=SmallModel, model="m")
    assert out.name == "fixed"
    assert len(captured) == 2
    repair_msgs = captured[1]["json"]["messages"]
    assert any("not valid" in m["content"] for m in repair_msgs)
    assert any("Validation error" in m["content"] for m in repair_msgs)


async def test_validation_error_then_success_counts_attempts():
    calls: list[dict] = []

    async def fake_complete(self, **kw):
        calls.append(kw)
        if len(calls) < 3:
            return '{"name": 123}'  # wrong type -> ValidationError
        return '{"name": "finally"}'

    monkey = pytest.MonkeyPatch()
    monkey.setattr(LLMClient, "_complete", fake_complete)
    try:
        client = LLMClient(settings=make_settings(llm_backend="ollama"))
        out = await client.generate(prompt="p", response_model=SmallModel, model="m")
        assert out.name == "finally"
        assert len(calls) == 3  # 2 failures + success, within max_repair_retries=3
    finally:
        monkey.undo()


async def test_exhausted_repairs_raise_schema_validation_error():
    captured: list[dict] = []
    client = make_openai_client(
        [{"choices": [{"message": {"content": "garbage"}}]}], captured
    )
    with pytest.raises(LLMSchemaValidationError) as exc:
        await client.generate(prompt="p", response_model=SmallModel, model="m")
    assert len(captured) == 4  # initial + 3 retries
    assert isinstance(exc.value.last_error, (json.JSONDecodeError, ValidationError))


async def test_bare_list_response_model_rejected():
    client = LLMClient(settings=make_settings(llm_backend="ollama"))
    with pytest.raises(TypeError):
        await client.generate(prompt="p", response_model=list[SmallModel], model="m")  # type: ignore[arg-type]


async def test_wrapper_model_accepts_list_payload():
    captured: list[dict] = []
    client = make_openai_client(
        [{"choices": [{"message": {"content": '{"items": ["a", "b"]}'}}]}], captured
    )
    out = await client.generate(prompt="p", response_model=WrappedList, model="m")
    assert out.items == ["a", "b"]


async def test_transport_error_wrapped_in_llmerror():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({})
        raise httpx.ConnectError("boom", request=request)

    client = LLMClient(settings=make_settings())
    real_async_client = httpx.AsyncClient
    monkey = pytest.MonkeyPatch()

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkey.setattr(lc.httpx, "AsyncClient", patched)
    try:
        with pytest.raises(LLMError):
            await client.generate(prompt="p", response_model=SmallModel, model="m")
    finally:
        monkey.undo()


# --------------------------------------------------------------------- #
# Ollama backend
# --------------------------------------------------------------------- #


async def test_ollama_uses_format_schema_and_num_predict(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, Any] = {}

    async def fake_ollama(self, *, messages, model, temperature, max_tokens, schema):
        seen.update(messages=messages, model=model, schema=schema, max_tokens=max_tokens)
        return '{"name": "ollama-ok"}'

    monkeypatch.setattr(LLMClient, "_complete_ollama", fake_ollama)
    client = LLMClient(settings=make_settings(llm_backend="ollama", openai_api_key=""))
    out = await client.generate(
        prompt="p", response_model=SmallModel, system_prompt="sys", model="qwen", role="designer"
    )
    assert out.name == "ollama-ok"
    assert seen["schema"]["properties"]["name"]["type"] == "string"
    assert seen["max_tokens"] == 4096
    assert seen["messages"][0] == {"role": "system", "content": "sys"}


async def test_ollama_client_missing_content_raises(monkeypatch: pytest.MonkeyPatch):
    class FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def chat(self, **kw):
            return {"message": {}}  # no content

    monkeypatch.setitem(__import__("sys").modules, "ollama", type("m", (), {"AsyncClient": FakeAsyncClient}))
    client = LLMClient(settings=make_settings(llm_backend="ollama", openai_api_key=""))
    with pytest.raises(LLMError):
        await client.generate(prompt="p", response_model=SmallModel, model="m")


# --------------------------------------------------------------------- #
# module-level cached client
# --------------------------------------------------------------------- #


async def test_get_llm_client_cached_per_loop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(lc, "_cached_client", None)
    monkeypatch.setattr(lc, "_client_loop_id", None)
    c1 = await lc.get_llm_client(settings=make_settings())
    c2 = await lc.get_llm_client(settings=make_settings())
    assert c1 is c2
