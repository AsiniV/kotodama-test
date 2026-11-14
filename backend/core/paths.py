"""Canonical filesystem layout for generated game workspaces (Phase 4).

Single source of truth for every path the backend touches on disk.  The one
and only layout is::

    {workspace_root}/{project_id}/          <- git root (versioned by WorkspaceManager)
        godot_project/                      <- the Godot project (template + generated content)
            assets/                         <- sprites / audio / music (res://assets/...)
            data/                           <- generated JSON data (quests, dialogues, ...)
        assets/                             <- staging area for raw generated assets (MinIO cache, audio gen)

``workspace_root`` comes from ``Settings.workspace_root`` (env:
``WORKSPACE_ROOT``); inside the backend container it is pinned to
``/app/workspace`` by docker-compose, which is the same volume mounted into
the godot-headless worker at ``/godot/workspace`` — so both containers see
identical paths.

The old ``game_project/`` directory name and the scattered hard-coded
``/workspace/*`` roots are removed; use the helpers here instead.
"""
from __future__ import annotations

from pathlib import Path

from backend.core.config import get_settings

# Repo root: backend/core/paths.py -> parents[2] == repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Directory name of the Godot project inside the workspace.  Replaces the old
#: inconsistent ``game_project/`` name.
GODOT_PROJECT_DIR_NAME = "godot_project"
#: Staging directory for raw generated assets (before integration into the
#: Godot project's ``assets/`` folder).
STAGING_ASSETS_DIR_NAME = "assets"


def workspace_root() -> Path:
    """Return the absolute root under which all project workspaces live."""
    return Path(get_settings().workspace_root).expanduser().resolve()


def project_workspace(project_id: str) -> Path:
    """Root of one project's workspace (the git repository root)."""
    return workspace_root() / project_id


def godot_project_path(project_id: str) -> Path:
    """Path to the Godot project directory of a workspace."""
    return project_workspace(project_id) / GODOT_PROJECT_DIR_NAME


def project_assets_path(project_id: str) -> Path:
    """Path to ``godot_project/assets`` (in-project asset folder, res://assets/)."""
    return godot_project_path(project_id) / "assets"


def project_data_path(project_id: str) -> Path:
    """Path to ``godot_project/data`` (generated JSON data files)."""
    return godot_project_path(project_id) / "data"


def staging_assets_path(project_id: str) -> Path:
    """Path to the raw-asset staging dir ``{workspace}/assets``."""
    return project_workspace(project_id) / STAGING_ASSETS_DIR_NAME


def exports_dir() -> Path:
    """Directory where finished export artifacts are written."""
    return workspace_root() / "exports"


def template_path() -> Path:
    """Immutable Godot core template — always the repo-level ``godot_core/``.

    Overridable via the ``GODOT_CORE_PATH`` environment variable (mapped onto
    ``Settings.godot_core_path``) for exotic deployments; defaults to the
    checkout next to the ``backend/`` package, which docker-compose bind-mounts
    read-only into the backend container at ``/app/godot_core``.
    """
    return Path(get_settings().godot_core_path).expanduser().resolve()
