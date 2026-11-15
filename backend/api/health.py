"""
Health-check endpoints (Phase 7 — real status + health).

``GET /api/v1/health`` is the endpoint the Docker Compose backend healthcheck
probes (see ``docker-compose.yml``: ``curl -f http://localhost:8000/api/v1/health``).

Design constraints:
- Always answers HTTP 200 while the API process is alive. Infra components
  (database, redis) are probed with short timeouts and reported per-component;
  a degraded component never turns into a crash or a 5xx, so container startup
  ordering can't flap the healthcheck.
- Every probe is defensive: imports happen lazily inside ``try`` blocks so the
  endpoint works even in minimal/offline environments where drivers or servers
  are absent.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("kotodama.api.health")

router = APIRouter()

#: Per-component probe budget. The compose healthcheck allows 10 s total;
#: keep each probe far below that so the endpoint always answers quickly.
PROBE_TIMEOUT_SECONDS = 3.0


class ComponentHealth(BaseModel):
    """Health of one infrastructure dependency."""

    status: str  # "ok" | "degraded"
    detail: str | None = None


class HealthResponse(BaseModel):
    """Payload returned by ``GET /api/v1/health``."""

    status: str  # "healthy" | "degraded" — HTTP code stays 200 either way
    version: str
    services: dict[str, ComponentHealth] = Field(default_factory=dict)


async def _probe_database() -> ComponentHealth:
    """SELECT 1 through the app's async session factory."""
    try:
        from sqlalchemy import text

        # Imported lazily so minimal/offline envs without a working DB
        # engine still answer 200 with "degraded" instead of crashing.
        from backend.db.session import AsyncSessionLocal

        async def _check() -> int:
            async with AsyncSessionLocal() as session:
                return await session.scalar(text("SELECT 1"))

        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            value = await _check()
        if value == 1:
            return ComponentHealth(status="ok")
        return ComponentHealth(status="degraded", detail="unexpected query result")
    except Exception as e:  # noqa: BLE001 - health probes must never raise
        logger.debug("health: database probe failed: %s", e)
        return ComponentHealth(status="degraded", detail=type(e).__name__)


async def _probe_redis() -> ComponentHealth:
    """PING the shared ProgressService Redis client (None when not configured)."""
    try:
        from backend.services.progress_service import get_progress_service

        client = get_progress_service()._get_redis()
        if client is None:
            return ComponentHealth(
                status="degraded", detail="not configured/unreachable; in-memory fallback active"
            )
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            pong = await asyncio.to_thread(client.ping)
        if pong:
            return ComponentHealth(status="ok")
        return ComponentHealth(status="degraded", detail="ping returned falsy value")
    except Exception as e:  # noqa: BLE001 - health probes must never raise
        logger.debug("health: redis probe failed: %s", e)
        return ComponentHealth(status="degraded", detail=type(e).__name__)


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Real liveness/readiness report for the API and its infra dependencies."""
    from backend.core.config import get_settings

    settings = get_settings()

    components: list[Any] = [_probe_database(), _probe_redis()]
    results = await asyncio.gather(*components)
    names = ["database", "redis"]

    services = {name: res for name, res in zip(names, results)}
    overall = "healthy" if all(s.status == "ok" for s in services.values()) else "degraded"

    return HealthResponse(
        status=overall,
        version=settings.app_version,
        services=services,
    )
