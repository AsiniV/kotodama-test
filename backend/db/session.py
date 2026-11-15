"""
Database session management and connection pooling.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from backend.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("kotodama.db")


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


def _build_engine():
    """Create the async engine.

    Phase 7: wrapped in a guard so importing this module NEVER crashes in
    environments where the DB driver (asyncpg/psycopg) or the server itself
    is absent — e.g. the offline pytest suite and the docker healthcheck
    during startup.  A failed build is retried on next access; callers that
    actually use the DB receive the original error at that point.
    """
    try:
        return create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    except Exception:  # pragma: no cover - depends on installed drivers
        return None


#: Module-level handle kept for backwards compatibility with code that does
#: ``from backend.db.session import engine`` AFTER a successful first session
#: creation; None until the engine can be built.
engine = None

#: Lazily-built session factory (see ``_get_session_factory``).
_session_factory: async_sessionmaker | None = None


def _get_session_factory() -> async_sessionmaker:
    global engine, _session_factory
    if _session_factory is None:
        built = _build_engine()
        if built is None:
            raise RuntimeError(
                "Database engine unavailable: install the async driver "
                "(asyncpg) and/or start Postgres infra"
            )
        engine = built
        _session_factory = async_sessionmaker(
            built,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


class _LazyAsyncSessionFactory:
    """Drop-in replacement for the old module-level ``AsyncSessionLocal``.

    Resolves the engine at call time instead of import time so offline
    environments (no asyncpg driver / no Postgres) can still import every
    backend module; usage attempts raise a clear RuntimeError.
    """

    def __call__(self, *args, **kwargs) -> AsyncSession:
        return _get_session_factory()(*args, **kwargs)

    def __getattr__(self, name):  # pragma: no cover - passthrough
        return getattr(_get_session_factory(), name)


AsyncSessionLocal = _LazyAsyncSessionFactory()


async def get_db() -> AsyncSession:
    """Dependency for getting async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_session() -> AsyncSession:
    """Context manager for getting async database session (for services)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables.

    Phase 7: tolerates an unreachable/offline Postgres — the app still boots
    (degraded) and ``/api/v1/health`` reports the real component status
    instead of the container crash-looping on startup.
    """
    try:
        factory = _get_session_factory()
    except Exception as e:  # driver missing / engine unbuildable
        logger.warning("init_db skipped: database engine unavailable (%s)", e)
        return
    try:
        async with factory.bind.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:  # server down at boot: keep serving, report degraded
        logger.warning("init_db skipped: could not reach Postgres (%s)", e)


async def close_db() -> None:
    """Close database connections (no-op when the engine was never built)."""
    if engine is not None:
        await engine.dispose()
