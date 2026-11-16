"""Phase 8 — offline verification for billing-off + router prefixes + docker infra.

Everything external is mocked or avoided: no GPU, no Godot binary, no LLM
server, no network, no Docker daemon.  The docker checks are *static*
(valid YAML / text inspection of ``docker-compose.yml`` and
``docker/Dockerfile.backend``), never ``docker compose config``.

Covered invariants:
1. ``Settings.billing_enabled`` defaults to False; with billing off,
   :meth:`BillingService.check_credits_sufficient` returns True without any
   DB access and :meth:`BillingService.deduct_credits` is a no-op (True) —
   generation can never be blocked by credits.
2. The pre-auth placeholder ``user_id="default_user"`` (and other
   non-integer ids) no longer crash billing lookups with
   ``ValueError: invalid literal for int()`` — ``parse_user_id`` coerces
   safely and DB-touching paths return ``None``/``False`` instead.
3. ``backend/main.py`` mounts export/marketplace routers at exactly
   ``/api/v1/export/*`` and ``/api/v1/marketplace/*`` — no doubled prefixes
   like ``/api/v1/export/api/v1/export/request`` (verified via route
   inspection AND the OpenAPI schema).
4. ``docker-compose.yml`` gives backend and the godot-headless worker ONE
   shared workspace bind mount at the same container path, and the backend
   healthcheck probes ``/api/v1/health``; ``docker/Dockerfile.backend``
   bakes the Godot headless binary into the image at GODOT_HEADLESS_PATH's
   default location.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.core.config import Settings
from backend.services.billing_service import BillingService, parse_user_id

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE_BACKEND = REPO_ROOT / "docker" / "Dockerfile.backend"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_settings(**overrides: Any) -> Settings:
    """Deterministic settings that ignore the repo .env file."""
    return Settings(_env_file=None, **overrides)


class _NoDB:
    """Context manager standing in for ``get_db_session`` that fails loudly.

    If any billing code path enters this while billing is disabled, the test
    must fail: the whole point of Phase 8 task 1 is that NO database access
    happens on the disabled path.
    """

    def __call__(self) -> "_NoDB":
        return self

    async def __aenter__(self) -> Any:
        raise AssertionError("billing touched the DB while billing_enabled=False")

    async def __aexit__(self, *exc: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Task 1a: billing_enabled defaults to False
# ---------------------------------------------------------------------------

def test_billing_enabled_defaults_to_false_in_settings() -> None:
    assert Settings.model_fields["billing_enabled"].default is False
    # Fresh instance (repo .env ignored) also defaults off.
    assert make_settings().billing_enabled is False


def test_billing_enabled_env_override_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_ENABLED", "true")
    assert Settings(_env_file=None).billing_enabled is True


def test_dotenv_example_documents_billing_enabled() -> None:
    """`.env.example` must document BILLING_ENABLED=false (this phase, task 1)."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^BILLING_ENABLED=false\s*$", text, re.MULTILINE), (
        ".env.example missing BILLING_ENABLED=false"
    )


# ---------------------------------------------------------------------------
# Task 1b: checks/deduction skipped when billing is off (no DB access)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_credits_sufficient_skipped_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.services.billing_service as bs

    monkeypatch.setattr(bs, "get_db_session", _NoDB())
    service = BillingService.__new__(BillingService)
    service.settings = make_settings(billing_enabled=False)

    # Zero credits on record (free tier default) — still allowed through.
    assert await service.check_credits_sufficient("default_user", 999) is True


@pytest.mark.asyncio
async def test_deduct_credits_is_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.services.billing_service as bs

    monkeypatch.setattr(bs, "get_db_session", _NoDB())
    service = BillingService.__new__(BillingService)
    service.settings = make_settings(billing_enabled=False)

    assert (
        await service.deduct_credits(
            user_id="default_user",
            amount=50,
            project_id="proj-x",
            attempt_number=2,
        )
        is True
    )


@pytest.mark.asyncio
async def test_generation_api_estimate_zero_when_billing_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The api/generation.py gating logic: estimate 0 + check passes when off.

    Mirrors lines in ``start_generation`` without booting the full app.
    """
    import backend.api.generation as gen_api

    settings = make_settings(billing_enabled=False)
    service = BillingService.__new__(BillingService)
    service.settings = settings
    monkeypatch.setattr(gen_api, "get_settings", lambda: settings)
    monkeypatch.setattr(gen_api, "get_billing_service", lambda: service)

    wizard = {
        "project_name": "p",
        "genre": "rpg",
        "scale": "large",
        "quest_complexity": "epic",
        "dialogue_depth": "full_rpg",
        "has_saving": True,
    }
    estimated_credits = (
        service.calculate_generation_cost(wizard) if settings.billing_enabled else 0
    )
    assert estimated_credits == 0
    # Non-integer placeholder user id must not raise (int(user_id) bug).
    assert await service.check_credits_sufficient("default_user", estimated_credits)


# ---------------------------------------------------------------------------
# Task 1c: int(user_id) crash fix — non-numeric ids handled gracefully
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7", 7),
        (42, 42),
        ("default_user", None),
        ("", None),
        (None, None),
        ("user-abc-123", None),
        ("3.5", None),
    ],
)
def test_parse_user_id_coerces_or_returns_none(raw: Any, expected: int | None) -> None:
    assert parse_user_id(raw) == expected


@pytest.mark.asyncio
async def test_get_user_subscription_non_numeric_id_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-auth placeholder id used to crash with ValueError: invalid literal."""
    import backend.services.billing_service as bs

    monkeypatch.setattr(bs, "get_db_session", _NoDB())
    service = BillingService.__new__(BillingService)
    service.settings = make_settings(billing_enabled=True)

    # Billing ON but id not numeric: safe None, no DB touch, no exception.
    assert await service.get_user_subscription("default_user") is None
    assert await service.get_user_credits("default_user") == 0


@pytest.mark.asyncio
async def test_deduct_credits_non_numeric_id_fails_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.services.billing_service as bs

    monkeypatch.setattr(bs, "get_db_session", _NoDB())
    service = BillingService.__new__(BillingService)
    service.settings = make_settings(billing_enabled=True)

    assert (
        await service.deduct_credits(
            user_id="default_user", amount=10, project_id="p", attempt_number=1
        )
        is False
    )


# ---------------------------------------------------------------------------
# Task 2: no double prefixes on export/marketplace routers
# ---------------------------------------------------------------------------

EXPECTED_EXPORT = {
    "/api/v1/export/request",
    "/api/v1/export/status/{job_id}",
}
EXPECTED_MARKETPLACE = {
    "/api/v1/marketplace/submit",
    "/api/v1/marketplace/search",
    "/api/v1/marketplace/{module_id}",
}


@pytest.fixture(scope="module")
def main_app_routes() -> tuple[list[str], dict[str, Any]]:
    """(route paths, openapi paths) from backend.main — no TestClient needed.

    Importing ``backend.main`` builds the app object only; lifespan (DB init)
    runs exclusively under a TestClient/uvicorn context, which we avoid so the
    suite stays fully offline.
    """
    from backend.main import app

    paths = sorted(getattr(r, "path", "") for r in app.routes)
    schema = app.openapi()
    return paths, schema


def test_export_routes_have_single_prefix(main_app_routes: tuple[list[str], dict]) -> None:
    paths, _ = main_app_routes
    export_paths = [p for p in paths if "/export" in p]
    assert EXPECTED_EXPORT <= set(export_paths), export_paths
    for p in export_paths:
        assert p.startswith("/api/v1/export/"), f"doubled prefix: {p}"
        # e.g. "/api/v1/export/api/v1/export/request" would contain it twice.
        assert p.count("/api/v1/export") == 1, f"doubled prefix: {p}"


def test_marketplace_routes_have_single_prefix(main_app_routes: tuple[list[str], dict]) -> None:
    paths, _ = main_app_routes
    mp_paths = [p for p in paths if "/marketplace" in p]
    assert EXPECTED_MARKETPLACE <= set(mp_paths), mp_paths
    for p in mp_paths:
        assert p.startswith("/api/v1/marketplace"), f"doubled prefix: {p}"
        assert p.count("/api/v1/marketplace") == 1, f"doubled prefix: {p}"


def test_openapi_schema_free_of_double_prefixes(main_app_routes: tuple[list[str], dict]) -> None:
    _, schema = main_app_routes
    openapi_paths = set(schema["paths"])
    assert EXPECTED_EXPORT <= openapi_paths
    assert EXPECTED_MARKETPLACE <= openapi_paths
    for p in openapi_paths:
        assert not re.search(r"/api/v1/(export|marketplace)/api/v1/", p), p


def test_router_modules_declare_no_own_prefix() -> None:
    """Root cause guard: the APIRouter objects must not repeat the mount prefix."""
    from backend.api import export, marketplace

    assert export.router.prefix == ""
    assert marketplace.router.prefix == ""


# ---------------------------------------------------------------------------
# Task 3: static docker-compose validation
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _split_mount(mount: str) -> tuple[str, str]:
    """Split ``source:target[:flags]`` handling ``${VAR:-default}`` sources.

    ``str.partition(":")`` is wrong here because the ``${...}`` default value
    itself contains no colon but the expression starts with ``$``; we locate
    the LAST structural colon sequence instead by scanning outside braces.
    """
    depth = 0
    for i, ch in enumerate(mount):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ":" and depth == 0:
            src = mount[:i]
            rest = mount[i + 1:]
            target = rest.split(":")[0]
            return src, target
    return mount, ""


def _workspace_mounts(service: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (source, target) pairs for bind mounts targeting /app/workspace."""
    out: list[tuple[str, str]] = []
    for v in service.get("volumes") or []:
        if isinstance(v, str):
            out.append(_split_mount(v))
    return [(s, t) for s, t in out if t == "/app/workspace"]


def test_compose_is_valid_yaml_with_expected_services(compose: dict[str, Any]) -> None:
    services = compose["services"]
    assert {"postgres", "minio", "redis", "backend", "godot-headless"} <= set(services)


def test_backend_and_godot_worker_share_one_workspace_bind_mount(
    compose: dict[str, Any],
) -> None:
    backend_mounts = _workspace_mounts(compose["services"]["backend"])
    worker_mounts = _workspace_mounts(compose["services"]["godot-headless"])
    # Exactly one shared-workspace mount per container...
    assert len(backend_mounts) == 1, backend_mounts
    assert len(worker_mounts) == 1, worker_mounts
    # ...same host source and same container path (no path translation)...
    assert backend_mounts == worker_mounts, (backend_mounts, worker_mounts)
    src, target = backend_mounts[0]
    assert target == "/app/workspace"
    assert "workspace" in src  # ./workspace bind (WORKSPACE_BIND-overridable)
    # ...and it is a bind mount, not a named volume.
    named_volumes = set(compose.get("volumes") or {})
    assert src.split(":")[0] not in named_volumes
    assert not any(name.endswith("workspace_data") for name in named_volumes), named_volumes


def _resolve_default(value: str) -> str:
    """Expand compose-style ``${VAR:-default}`` to its default (offline check)."""
    m = re.fullmatch(r"\$\{[^:}]+:?-([^}]*)\}", value)
    return m.group(1) if m else value


def test_workspace_root_matches_shared_mount_target(compose: dict[str, Any]) -> None:
    for svc in ("backend", "godot-headless"):
        env = compose["services"][svc].get("environment") or {}
        root = _resolve_default(str(env.get("WORKSPACE_ROOT", "")))
        assert root == "/app/workspace", (svc, root)


def test_backend_healthcheck_uses_api_v1_health(compose: dict[str, Any]) -> None:
    hc = compose["services"]["backend"]["healthcheck"]
    test_cmd = " ".join(hc["test"]) if isinstance(hc["test"], list) else str(hc["test"])
    assert "/api/v1/health" in test_cmd
    # Aligned with the Dockerfile HEALTHCHECK (same endpoint).
    dockerfile = DOCKERFILE_BACKEND.read_text(encoding="utf-8")
    assert "HEALTHCHECK" in dockerfile and "/api/v1/health" in dockerfile


def test_billing_env_flag_plumbed_through_compose(compose: dict[str, Any]) -> None:
    env = compose["services"]["backend"].get("environment") or {}
    assert env.get("BILLING_ENABLED", "").startswith("${BILLING_ENABLED:-false}")


# ---------------------------------------------------------------------------
# Task 3: static Dockerfile.backend validation (Godot binary baked in)
# ---------------------------------------------------------------------------

def test_dockerfile_backend_installs_godot_headless_binary() -> None:
    text = DOCKERFILE_BACKEND.read_text(encoding="utf-8")
    assert "godotengine/godot/releases" in text, "Godot download step missing"
    assert "/usr/local/bin/godot" in text, "Godot not installed at GODOT_HEADLESS_PATH default"
    assert "chmod +x /usr/local/bin/godot" in text
    # Version sanity check actually runs during the build.
    assert re.search(r"godot\s+--version", text)
    # Default GODOT_HEADLESS_PATH in settings resolves inside the image.
    assert make_settings().godot_headless_path == "/usr/local/bin/godot"
