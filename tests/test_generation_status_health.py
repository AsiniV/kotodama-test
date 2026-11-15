"""Phase 7 offline tests: real /status + /api/v1/health, no mock bodies.

Fully offline: FastAPI TestClient against a minimal app that mounts only the
generation and health routers; Redis/DB/orchestrator/billing are mocked or
degraded to the in-memory fallback. No GPU, Godot, LLM server, or network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.api import generation as gen_api
from backend.api import health as health_api
from backend.services import progress_service as ps_module
from backend.services.progress_service import (
    REDIS_KEY_PREFIX,
    ProgressEvent,
    ProgressService,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

WIZARD_PAYLOAD: dict[str, Any] = {
    "genre": "rpg",
    "perspective": "top_down",
    "art_style": "pixel_art",
    "setting": "fantasy",
    "scale": "small",
    "controls": {"move": "arrows"},
    "text_description": "a tiny test quest",
    "project_name": "phase7-test",
}


class _FakeRedis:
    """Minimal sync redis stub implementing only what ProgressService uses."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.set_keys: list[str] = []

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.set_keys.append(key)
        self.data[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0

    def ping(self) -> bool:
        return True


class _BrokenRedis:
    """Redis stub whose every operation raises — infra-offline simulation."""

    def set(self, *a: Any, **k: Any) -> None:
        raise ConnectionError("redis down")

    def get(self, *a: Any, **k: Any) -> None:
        raise ConnectionError("redis down")

    def delete(self, *a: Any, **k: Any) -> None:
        raise ConnectionError("redis down")

    def ping(self) -> bool:
        raise ConnectionError("redis down")


@pytest.fixture()
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture()
def progress(fake_redis: _FakeRedis) -> ProgressService:
    """In-process ProgressService backed by the fake Redis (no real infra)."""
    return ProgressService(redis_client=fake_redis)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
           progress: ProgressService, fake_redis: _FakeRedis):
    """TestClient on a minimal app with generation+health routers only.

    All external systems are neutralized: WORKSPACE_ROOT points at tmp_path,
    the orchestrator/billing singletons are fakes, and every DB touch is
    stubbed so nothing ever opens a socket.
    """
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    # No real Redis: the health probe must see the injected fake service, and
    # no code path may ever attempt a socket connection.
    monkeypatch.setenv("REDIS_URL", "")
    from backend.core.config import get_settings

    get_settings.cache_clear()

    # --- Fake orchestrator (mirrors the production merge contract) --------
    class FakeOrchestrator:
        def __init__(self) -> None:
            self.run_calls: list[dict[str, Any]] = []

        async def run_generation(self, *, wizard_input, user_id, project_id):
            self.run_calls.append(
                {"wizard_input": wizard_input, "user_id": user_id, "project_id": project_id}
            )
            await progress.record_event(
                project_id,
                ProgressEvent(stage="designer", progress_pct=15,
                              message="designer done", status=STATUS_RUNNING),
            )
            await progress.finalize(project_id, success=True)
            return {"success": True, "attempt_number": 1}

        async def get_status(self, project_id: str):
            p = await progress.get_progress_with_fallback(project_id)
            if p is None:
                return None
            return {
                "status": p.status,
                "progress": p.progress_pct,
                "current_stage": p.current_stage,
                "attempt_number": p.attempt_number,
                "logs": [e.message for e in p.events if e.message],
                "error_message": p.error_message,
                "result": p.result_snapshot,
            }

    fake_orch = FakeOrchestrator()
    monkeypatch.setattr(gen_api, "get_orchestrator", lambda: fake_orch)

    # --- Fake billing (no DB) ----------------------------------------------
    class FakeBilling:
        deducted: list[dict[str, Any]] = []

        def calculate_generation_cost(self, wizard_input):
            return 42

        async def check_credits_sufficient(self, user_id, required_credits):
            return True

        async def deduct_credits(self, **kwargs):
            FakeBilling.deducted.append(kwargs)

    monkeypatch.setattr(gen_api, "get_billing_service", lambda: FakeBilling())

    # --- Redirect the module-level singleton used inside generation.py -----
    # (start_run on /start, raw fallback on /status, clear on DELETE)
    monkeypatch.setattr(ps_module, "_progress_service", progress)

    # Keep the *real* Postgres mirror out of every path: route terminal
    # snapshots through an injectable hook instead (offline-safe test double
    # for the DB fallback; None values = "row absent").
    rows: dict[str, dict] = {}

    async def _hook_persist(p) -> None:
        rows[p.project_id] = json.loads(p.model_dump_json())

    async def _hook_load(pid: str):
        return rows.get(pid)

    progress._db_persist_hook = _hook_persist
    progress._db_load_hook = _hook_load

    # --- Health probes: DB unreachable, Redis served by the fake -----------
    async def broken_db_probe():
        # Mimic the production probe contract: it never raises, it reports.
        return health_api.ComponentHealth(status="degraded", detail="ConnectionError")

    monkeypatch.setattr(health_api, "_probe_database", broken_db_probe)

    # DELETE must really clear progress (no no-op stubs): wrap the real
    # ProgressService.clear so the fake-DB hook row is dropped too — /status
    # can only answer 404 afterwards if the endpoint performs a genuine
    # durable clear across every backend.
    _real_clear = progress.clear

    async def _clear_everywhere(pid: str) -> None:
        await _real_clear(pid)
        rows.pop(pid, None)

    monkeypatch.setattr(progress, "clear", _clear_everywhere)

    app = FastAPI()
    app.include_router(health_api.router, prefix="/api/v1")
    app.include_router(gen_api.router, prefix="/api/v1/generation")
    with TestClient(app) as tc:
        yield tc


# ---------------------------------------------------------------------------
# 1. GET /api/v1/health — HTTP 200 even when infra is offline
# ---------------------------------------------------------------------------


def test_health_returns_200_with_components_when_db_offline(client: TestClient):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("healthy", "degraded")
    assert set(body["services"]) == {"database", "redis"}
    # DB probe was forced to fail → degraded, but the endpoint never crashes.
    assert body["services"]["database"]["status"] == "degraded"
    assert body["services"]["database"]["detail"] == "ConnectionError"
    # Overall status must reflect the degraded component.
    assert body["status"] == "degraded"
    assert isinstance(body["version"], str) and body["version"]


def test_health_reports_redis_ok_via_injected_fake(client: TestClient):
    body = client.get("/api/v1/health").json()
    # The fake Redis pings fine → its component is ok while DB stays degraded.
    assert body["services"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_coroutine_all_ok(monkeypatch: pytest.MonkeyPatch):
    """Direct call of the handler: all components ok → overall 'healthy'."""
    good = health_api.ComponentHealth(status="ok")

    async def ok_db_probe():
        return good

    svc = ProgressService(redis_client=_FakeRedis())
    monkeypatch.setattr(health_api, "_probe_database", ok_db_probe)
    monkeypatch.setattr(ps_module, "get_progress_service", lambda: svc)

    result = await health_api.health_check()
    assert result.status == "healthy"
    assert result.services["database"].status == "ok"
    assert result.services["redis"].status == "ok"


def test_health_survives_broken_redis_and_no_db(monkeypatch: pytest.MonkeyPatch):
    """No Redis, no Postgres, no drivers: /health must still answer 200."""
    dead = ProgressService(redis_client=_BrokenRedis())
    monkeypatch.setattr(ps_module, "get_progress_service", lambda: dead)
    monkeypatch.setenv("REDIS_URL", "")
    from backend.core.config import get_settings

    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(health_api.router, prefix="/api/v1")
    with TestClient(app) as tc:
        resp = tc.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    # The real DB probe swallows its own failure and reports degraded — the
    # endpoint never crashes nor returns 5xx when infra is offline.
    assert body["status"] == "degraded"
    assert body["services"]["database"]["status"] == "degraded"
    assert body["services"]["redis"]["status"] == "degraded"


def test_main_app_mounts_api_v1_health():
    """backend/main.py exposes exactly the route docker-compose probes."""
    from backend.main import create_app

    app = create_app()
    paths = {getattr(r, "path", "") for r in app.routes if isinstance(r, APIRoute)}
    assert "/api/v1/health" in paths


# ---------------------------------------------------------------------------
# 2. GET /status/{id} — real progress from the event store, 404 unknown
# ---------------------------------------------------------------------------


def test_status_unknown_project_returns_404(client: TestClient):
    resp = client.get("/api/v1/generation/status/no-such-project")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_status_reflects_real_progress_updates(client: TestClient, fake_redis: _FakeRedis):
    # Start a real run; TestClient executes BackgroundTasks before returning.
    start = client.post("/api/v1/generation/start", json=WIZARD_PAYLOAD)
    assert start.status_code == 200, start.text
    project_id = start.json()["project_id"]

    body = client.get(f"/api/v1/generation/status/{project_id}").json()
    assert body["project_id"] == project_id
    assert body["status"] == STATUS_COMPLETED          # real terminal state
    assert body["progress"] == 100                     # real percentage
    assert body["current_agent"] == "commit"           # real last stage
    assert "designer done" in body["logs"]             # real agent messages
    assert body["attempt_number"] == 1
    assert body["error_message"] is None

    # The events really went through the Redis stream (not a canned payload).
    assert f"{REDIS_KEY_PREFIX}{project_id}" in fake_redis.set_keys


def test_status_running_mid_pipeline_reports_partial(client: TestClient):
    pid = "mid-run-project"
    progress = ps_module._progress_service  # injected fixture service
    import anyio

    async def _seed() -> None:
        await progress.start_run(pid, user_id="u1")
        await progress.record_event(
            pid,
            ProgressEvent(stage="architect", progress_pct=30,
                          message="architecture ready", status=STATUS_RUNNING),
        )

    anyio.run(_seed)

    view = client.get(f"/api/v1/generation/status/{pid}").json()
    assert view["status"] == STATUS_RUNNING
    assert view["progress"] == 30
    assert view["current_agent"] == "architect"
    assert view["logs"] == ["architecture ready"]


def test_status_failed_includes_error_message(client: TestClient):
    import anyio

    pid = "failed-project"
    progress = ps_module._progress_service

    async def _seed() -> None:
        await progress.start_run(pid)
        await progress.finalize(pid, success=False, error_message="coder crashed")

    anyio.run(_seed)

    view = client.get(f"/api/v1/generation/status/{pid}").json()
    assert view["status"] == STATUS_FAILED
    assert view["error_message"] == "coder crashed"
    assert view["progress"] == 0  # failure keeps the last real percentage


def test_status_reads_record_written_by_another_worker(fake_redis: _FakeRedis):
    """Cross-worker case: record written elsewhere lives only in Redis."""
    import anyio

    writer = ProgressService(redis_client=fake_redis)
    reader = ProgressService(redis_client=fake_redis)  # empty in-memory store

    async def _flow() -> Any:
        await writer.start_run("remote-pid", user_id="u")
        await writer.finalize("remote-pid", success=True)
        return await reader.get_progress_with_fallback("remote-pid")

    found = anyio.run(_flow)
    assert found is not None
    assert found.status == STATUS_COMPLETED
    assert f"{REDIS_KEY_PREFIX}remote-pid" in fake_redis.set_keys


def test_status_db_fallback_when_redis_down():
    """Terminal snapshot persisted via the DB hook survives a restart."""
    import anyio

    rows: dict[str, dict] = {}

    async def persist(p):
        rows[p.project_id] = json.loads(p.model_dump_json())

    async def load(pid):
        return rows.get(pid)

    svc = ProgressService(redis_client=None, db_persist_hook=persist, db_load_hook=load)

    async def _flow() -> Any:
        await svc.start_run("db-only")
        await svc.finalize("db-only", success=True)
        # Fresh service (simulated restart): memory + redis empty, DB wins.
        svc2 = ProgressService(redis_client=None, db_persist_hook=persist, db_load_hook=load)
        return await svc2.get_progress_with_fallback("db-only")

    found = anyio.run(_flow)
    assert "db-only" in rows
    assert found is not None
    assert found.status == STATUS_COMPLETED


# ---------------------------------------------------------------------------
# 3. Mock/stub bodies are gone from generation.py
# ---------------------------------------------------------------------------


def test_download_streams_real_zip(client: TestClient, tmp_path: Path):
    pid = "dl-proj"
    src = tmp_path / pid / "godot_project"
    src.mkdir(parents=True)
    (src / "project.godot").write_text(f"[application]\nname={pid}\n", encoding="utf-8")

    resp = client.get(f"/api/v1/generation/{pid}/download")
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"  # genuine zip bytes, not a canned payload
    assert len(resp.content) > 0

    meta = client.get(f"/api/v1/generation/{pid}/download?meta=true")
    assert meta.status_code == 200
    meta_body = meta.json()
    assert meta_body["format"] == "source"
    assert meta_body["size_bytes"] == len(resp.content)


def test_download_honest_errors(client: TestClient, tmp_path: Path):
    assert client.get("/api/v1/generation/ghost/download").status_code == 404
    # Known project, artifact never built → 501, not a fake zip/URL.
    pid2 = "no-artifact"
    (tmp_path / pid2).mkdir(parents=True, exist_ok=True)
    resp = client.get(f"/api/v1/generation/{pid2}/download?format=web")
    assert resp.status_code == 501
    assert "not been generated" in resp.json()["detail"]


def test_preview_no_fake_url(client: TestClient, tmp_path: Path):
    assert client.post("/api/v1/generation/ghost/preview").status_code == 404
    pid2 = "no-export"
    (tmp_path / pid2).mkdir(parents=True, exist_ok=True)
    resp = client.post(f"/api/v1/generation/{pid2}/preview")
    assert resp.status_code == 501  # honest: export pipeline produced nothing


def test_delete_removes_workspace_and_progress(client: TestClient, tmp_path: Path):
    import anyio

    pid = "del-proj"
    ws = tmp_path / pid
    ws.mkdir()
    (ws / "marker.txt").write_text("x", encoding="utf-8")
    progress = ps_module._progress_service
    anyio.run(progress.start_run, pid)  # seed a durable record first

    resp = client.delete(f"/api/v1/generation/{pid}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert not ws.exists()  # real deletion, not a canned {"success": true}
    assert client.get(f"/api/v1/generation/status/{pid}").status_code == 404


def test_source_contains_no_mock_markers():
    """Static guard: generation.py has no mock/fake/canned-response leftovers."""
    source = Path(gen_api.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    forbidden = [
        "mock response", "mock_response", "fake_",
        "hardcoded", "dummy", "sample_response", "stub_",
    ]
    hits = [token for token in forbidden if token in lowered]
    assert not hits, f"mock leftovers in generation.py: {hits}"
    # The old hardcoded mock status payload must be gone.
    assert '"progress": 50' not in source
    assert "'progress': 50" not in source
    assert '"current_agent": "asset_generator"' not in source
    # And the endpoints genuinely delegate to the Phase-7 services.
    assert "get_progress_service()" in source
    assert "orchestrator.get_status(" in source
