"""Phase 7 — real generation progress events (Redis primary, in-memory fallback).

The orchestrator emits a structured :class:`ProgressEvent` on every node
transition; this service persists them so ``GET /api/v1/generation/status/{id}``
can report *real* progress instead of the old mock payload.

Storage contract (one key per project):

- Redis:    ``generation:progress:{project_id}`` → JSON blob
            (:class:`GenerationProgress.model_dump_json`), TTL
            ``PROGRESS_TTL_SECONDS`` (default 24 h).
- Fallback: process-local dict (used automatically when Redis is unreachable
            or ``redis_url`` is empty — offline tests/dev runs land here).

Deliberately avoids importing ``backend.db.session`` at module level: engine
creation there would try to connect during import and break offline test
environments.  The DB-fallback hook receives injected async callables instead.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger("kotodama.services.progress")

#: Redis key prefix for the per-project progress blob.
REDIS_KEY_PREFIX = "generation:progress:"

#: Status values surfaced through ProjectStatusResponse.status.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def utcnow_iso() -> str:
    """UTC timestamp as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


#: Default per-run wall-clock budget used to interpolate *live* progress
#: between node completions (the pipeline takes minutes; the last recorded
#: event alone would keep /status frozen until the next stage finishes).
DEFAULT_STAGE_TIMEOUT_SECONDS = 180


class ProgressEvent(BaseModel):
    """One structured progress event emitted during a generation run."""

    stage: str  # pipeline node name: designer, architect, coder, ...
    progress_pct: int = Field(ge=0, le=100)
    message: str = ""
    status: str = STATUS_RUNNING  # pending | running | completed | failed
    timestamp: str = Field(default_factory=utcnow_iso)
    attempt_number: int = 1
    error_message: str | None = None


class GenerationProgress(BaseModel):
    """Aggregated progress state for one project (the persisted blob)."""

    project_id: str
    user_id: str | None = None
    status: str = STATUS_PENDING
    progress_pct: int = Field(default=0, ge=0, le=100)
    current_stage: str | None = None
    attempt_number: int = 1
    started_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    finished_at: str | None = None
    error_message: str | None = None
    events: list[ProgressEvent] = Field(default_factory=list)
    #: Compact terminal outcome snapshot (success, attempt_number, scores...),
    #: filled by the orchestrator when the run finishes; surfaced as
    #: ProjectStatusResponse.result.
    result_snapshot: dict[str, Any] | None = None


class ProgressService:
    """Write/read progress events to Redis with an in-memory DB-style fallback.

    All public methods are safe to call without a running Redis server (or even
    without the ``redis`` package installed): every backend failure degrades to
    the local store, so API callers never crash when infra is offline.
    """

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        redis_url: str | None = None,
        ttl_seconds: int = 24 * 3600,
        db_persist_hook: Callable[[GenerationProgress], Awaitable[None]] | None = None,
        db_load_hook: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None,
        live_stage_timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS,
    ):
        self._redis = redis_client
        self._redis_url = redis_url
        self._ttl = max(int(ttl_seconds), 60)
        self._db_persist_hook = db_persist_hook
        self._db_load_hook = db_load_hook
        # In-memory fallback ("DB fallback"): survives Redis outages and keeps
        # offline tests hermetic.  Bounded to avoid unbounded growth.
        self._store: dict[str, GenerationProgress] = {}
        self._max_projects = 512
        #: Wall-clock budget per stage used by :func:`live_progress_pct`
        #: (tests shrink it; production default matches the 3-min estimate).
        self.live_stage_timeout_seconds = max(int(live_stage_timeout_seconds), 1)

    # ------------------------------------------------------------------
    # Backend plumbing
    # ------------------------------------------------------------------
    def _get_redis(self) -> Any | None:
        """Return a connected sync redis client, or None when unavailable."""
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:  # lazy import: redis may be absent in minimal/offline envs
            import redis

            client = redis.Redis.from_url(
                self._redis_url, socket_connect_timeout=1.0, socket_timeout=1.0
            )
            client.ping()
        except Exception as e:  # pragma: no cover - depends on infra state
            logger.warning("ProgressService: Redis unavailable (%s); using in-memory store", e)
            self._redis_url = None  # don't retry the connection storm per event
            return None
        self._redis = client
        return client

    @staticmethod
    def redis_key(project_id: str) -> str:
        return f"{REDIS_KEY_PREFIX}{project_id}"

    async def _write_backend(self, progress: GenerationProgress) -> None:
        """Persist one snapshot: Redis first, then the injected DB hook.

        Failures in either backend are logged, never raised — the in-memory
        copy always holds the authoritative latest state for this process.
        """
        payload = progress.model_dump_json()
        self._store[progress.project_id] = progress
        if len(self._store) > self._max_projects:  # prune oldest by update time
            oldest = sorted(self._store.values(), key=lambda p: p.updated_at)[: -self._max_projects // 2]
            for stale in oldest:
                self._store.pop(stale.project_id, None)

        client = self._get_redis()
        if client is not None:
            try:
                await asyncio.to_thread(
                    client.set, self.redis_key(progress.project_id), payload, ex=self._ttl
                )
            except Exception as e:
                logger.warning("ProgressService: Redis write failed for %s: %s", progress.project_id, e)

        # DB mirror: only terminal snapshots hit Postgres by default (one row
        # per run, not one write per node event).  An injected hook keeps the
        # legacy per-event behaviour available for callers that want it.
        if self._db_persist_hook is not None:
            try:
                await self._db_persist_hook(progress)
            except Exception as e:
                logger.warning("ProgressService: DB persist hook failed for %s: %s", progress.project_id, e)
        elif progress.status in (STATUS_COMPLETED, STATUS_FAILED):
            await self.save_to_db(progress)

    async def _read_backend(self, project_id: str) -> GenerationProgress | None:
        """Read one snapshot: Redis first, then the injected DB hook."""
        client = self._get_redis()
        if client is not None:
            try:
                raw = await asyncio.to_thread(client.get, self.redis_key(project_id))
                if raw is not None:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    return GenerationProgress.model_validate(json.loads(raw))
            except Exception as e:
                logger.warning("ProgressService: Redis read failed for %s: %s", project_id, e)

        if self._db_load_hook is not None:
            try:
                data = await self._db_load_hook(project_id)
                if data is not None:
                    return GenerationProgress.model_validate(data)
            except Exception as e:
                logger.warning("ProgressService: DB load hook failed for %s: %s", project_id, e)
        else:
            record = await self.load_from_db(project_id)
            if record is not None:
                return record
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_progress(self, project_id: str) -> GenerationProgress | None:
        """Latest progress snapshot for a project; None when unknown.

        The in-process copy wins when present (freshest, no round trip);
        otherwise Redis / the DB hook are consulted so a status query served by
        another worker still sees real progress.
        """
        local = self._store.get(project_id)
        remote = await self._read_backend(project_id)
        if remote is not None:
            # A record written by another worker/process wins over a stale
            # local stub as long as this process has no live run for it.
            if local is None or (
                local.status == STATUS_PENDING and remote.status != STATUS_PENDING
            ):
                return remote
            return local
        return local

    async def record_event(self, project_id: str, event: ProgressEvent, *, user_id: str | None = None) -> GenerationProgress:
        """Append one event, recomputing aggregate fields, and persist it."""
        progress = self._store.get(project_id) or await self._read_backend(project_id)
        if progress is None:
            progress = GenerationProgress(project_id=project_id, user_id=user_id)
        if user_id and not progress.user_id:
            progress.user_id = user_id

        progress.events.append(event)
        progress.status = event.status
        progress.current_stage = event.stage
        progress.progress_pct = max(progress.progress_pct, event.progress_pct)
        progress.attempt_number = max(progress.attempt_number, event.attempt_number)
        progress.updated_at = event.timestamp
        if event.error_message:
            progress.error_message = event.error_message
        if event.status in (STATUS_COMPLETED, STATUS_FAILED):
            progress.finished_at = event.timestamp

        await self._write_backend(progress)
        return progress

    async def start_run(self, project_id: str, *, user_id: str | None = None) -> GenerationProgress:
        """Initialize (or reset) progress at the beginning of a generation run."""
        progress = GenerationProgress(
            project_id=project_id,
            user_id=user_id,
            status=STATUS_RUNNING,
            progress_pct=0,
            started_at=utcnow_iso(),
        )
        await self._write_backend(progress)
        return progress

    async def finalize(
        self,
        project_id: str,
        *,
        success: bool,
        error_message: str | None = None,
        stage: str = "commit",
        message: str | None = None,
    ) -> GenerationProgress:
        """Record the terminal event (completed at 100% or failed as-is)."""
        existing = self._store.get(project_id)
        event = ProgressEvent(
            stage=stage,
            progress_pct=100 if success else (existing.progress_pct if existing else 0),
            message=message
            or ("Generation completed successfully" if success else (error_message or "Generation failed")),
            status=STATUS_COMPLETED if success else STATUS_FAILED,
            attempt_number=max(1, existing.attempt_number if existing else 1),
            error_message=None if success else error_message,
        )
        return await self.record_event(project_id, event)

    async def clear(self, project_id: str) -> None:
        """Drop all stored progress for a project (used by tests/cleanup)."""
        self._store.pop(project_id, None)
        client = self._get_redis()
        if client is not None:
            try:
                await asyncio.to_thread(client.delete, self.redis_key(project_id))
            except Exception as e:  # pragma: no cover - infra-dependent
                logger.warning("ProgressService: Redis delete failed for %s: %s", project_id, e)

    # ------------------------------------------------------------------
    # DB-backed persistence (Phase 7: survives Redis loss / TTL expiry)
    # ------------------------------------------------------------------
    async def save_to_db(self, progress: GenerationProgress) -> None:
        """Upsert one snapshot into the Postgres ``generation_progress`` table.

        Best-effort: any failure (DB offline, driver missing) is logged and
        swallowed so callers inside the hot event path never break.
        """
        try:
            from sqlalchemy import select

            # Imported lazily: pulling in backend.db.session builds the DB
            # engine, which explodes in minimal envs without a PG driver —
            # exactly what save_to_db must tolerate offline.
            from backend.db.session import AsyncSessionLocal
            from backend.models.schemas import GenerationProgressRecord

            payload = progress.model_dump(mode="json")
            async with AsyncSessionLocal() as session:
                existing = await session.get(GenerationProgressRecord, progress.project_id)
                if existing is None:
                    session.add(GenerationProgressRecord(progress_json=payload))
                else:
                    # Reassign a fresh dict so SQLAlchemy detects JSON mutation.
                    existing.progress_json = payload
                existing.status = progress.status
                existing.progress_pct = progress.progress_pct
                existing.current_stage = progress.current_stage
                existing.attempt_number = progress.attempt_number
                existing.error_message = progress.error_message
                await session.commit()
        except Exception as e:  # noqa: BLE001 - persistence must never raise
            logger.warning("ProgressService: DB save failed for %s: %s", progress.project_id, e)

    async def load_from_db(self, project_id: str) -> GenerationProgress | None:
        """Load one snapshot from Postgres; None when absent or DB offline."""
        try:
            from backend.db.session import AsyncSessionLocal
            from backend.models.schemas import GenerationProgressRecord

            async with AsyncSessionLocal() as session:
                record = await session.get(GenerationProgressRecord, project_id)
            if record is None or not record.progress_json:
                return None
            return GenerationProgress.model_validate(record.progress_json)
        except Exception as e:  # noqa: BLE001 - read fallback must never raise
            logger.warning("ProgressService: DB load failed for %s: %s", project_id, e)
            return None

    async def list_project_ids_from_db(self) -> list[str]:
        """All project ids that have persisted progress (empty when DB offline)."""
        try:
            from sqlalchemy import select

            from backend.db.session import AsyncSessionLocal
            from backend.models.schemas import GenerationProgressRecord

            async with AsyncSessionLocal() as session:
                result = await session.execute(select(GenerationProgressRecord.project_id))
            return [row[0] for row in result.all()]
        except Exception as e:  # noqa: BLE001
            logger.warning("ProgressService: DB id listing failed: %s", e)
            return []

    async def get_progress_with_fallback(self, project_id: str) -> GenerationProgress | None:
        """Full read chain: memory → Redis → Postgres. None when truly unknown."""
        found = await self.get_progress(project_id)
        if found is not None:
            return found
        return await self.load_from_db(project_id)


def live_progress_pct(
    progress: GenerationProgress, *, stage_timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS
) -> int:
    """Interpolated progress percentage including work in flight.

    Terminal states report their recorded value verbatim. While running, the
    fraction of the current stage's budget elapsed since the last event is
    credited toward the next stage boundary — strictly capped below it, so the
    number only ever reaches a boundary when the stage really completed.
    """
    if progress.status in (STATUS_COMPLETED, STATUS_FAILED):
        return progress.progress_pct

    base = progress.progress_pct
    if base >= 100:
        return base

    try:
        updated = datetime.fromisoformat(progress.updated_at)
    except ValueError:  # pragma: no cover - defensive
        return base
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    elapsed = max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())

    timeout = max(int(stage_timeout_seconds), 1)
    window = 100 - base
    increment = min(int(elapsed / timeout * window), max(window - 1, 0))
    return base + increment


# ----------------------------------------------------------------------
# Factory / singleton
# ----------------------------------------------------------------------
_progress_service: ProgressService | None = None


def get_progress_service() -> ProgressService:
    """Get or create the process-wide ProgressService singleton."""
    global _progress_service
    if _progress_service is None:
        redis_url = ""
        try:  # settings import must never break offline environments
            from backend.core.config import get_settings

            redis_url = get_settings().redis_url
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("ProgressService: settings unavailable (%s); in-memory only", e)
        _progress_service = ProgressService(redis_url=redis_url)
    return _progress_service


def set_progress_service(service: ProgressService | None) -> None:
    """Override the singleton (dependency injection for tests)."""
    global _progress_service
    _progress_service = service
