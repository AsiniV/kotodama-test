"""Services for Kotodama backend.

Submodules are imported lazily (PEP 562 ``__getattr__``) so that importing a
lightweight module such as ``backend.services.llm_client`` never drags in the
database stack (sqlalchemy/asyncpg). This keeps the agent pipeline runnable in
offline/test environments where DB dependencies are not installed. Explicit
submodule imports (``from backend.services import llm_client`` or
``from backend.services.billing_service import ...``) keep working unchanged.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BillingService",
    "get_billing_service",
]


def __getattr__(name: str) -> Any:
    if name in ("BillingService", "get_billing_service"):
        module = import_module("backend.services.billing_service")
        return getattr(module, name)
    try:
        # Allow lazy access to submodules, e.g. ``backend.services.llm_client``.
        return import_module(f"backend.services.{name}")
    except ImportError as exc:
        raise AttributeError(f"module 'backend.services' has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    return sorted(__all__)
