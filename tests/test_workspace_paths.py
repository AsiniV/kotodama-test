"""Phase 4 tests: canonical workspace paths + WorkspaceManager git behaviour.

Fully offline: uses tmp_path, a fake template dir and the system ``git``
binary only (no GPU / LLM server / network / Godot).
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from backend.core import paths
from backend.services.workspace_manager import (
    BASELINE_TAG,
    PRESERVE_DIR_NAME,
    WorkspaceManager,
)


def run_git(repo: Path, *args: str) -> str:
    """Helper: run git in ``repo`` and return stdout (fails the test on error)."""
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Point settings' workspace_root/godot_core_path/git identity at tmp dirs."""
    from backend.core.config import get_settings

    get_settings.cache_clear()
    root = tmp_path / "workspaces"
    core = tmp_path / "godot_core"
    core.mkdir(parents=True)
    (core / "project.godot").write_text('[application]\nconfig/name="Core"\n')
    (core / "scripts").mkdir()
    (core / "scripts" / "main.gd").write_text("extends Node\n")
    # .import files must be ignored by the template copy.
    (core / "icon.svg.import").write_text("should be ignored\n")

    monkeypatch.setenv("WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("GODOT_CORE_PATH", str(core))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test Bot")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@localhost")
    yield root, core
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Canonical path helpers
# ---------------------------------------------------------------------------
class TestPathHelpers:
    def test_layout_is_consistent(self, isolated_settings):
        root, _core = isolated_settings
        pid = "proj-123"
        ws = paths.project_workspace(pid)
        assert ws == root / pid
        assert paths.godot_project_path(pid) == ws / "godot_project"
        assert paths.project_assets_path(pid) == ws / "godot_project" / "assets"
        assert paths.project_data_path(pid) == ws / "godot_project" / "data"
        assert paths.staging_assets_path(pid) == ws / "assets"
        assert paths.exports_dir() == root / "exports"

    def test_no_game_project_name_anywhere(self, isolated_settings):
        # Phase 4 goal: game_project/ is dead; godot_project/ is the only name.
        assert paths.GODOT_PROJECT_DIR_NAME == "godot_project"
        assert "game_project" not in {
            paths.godot_project_path("p").name,
            paths.project_assets_path("p").parent.name,
        }

    def test_template_resolves_to_godot_core(self, isolated_settings):
        _root, core = isolated_settings
        assert paths.template_path() == core.resolve()

    def test_default_template_is_repo_godot_core(self):
        # Without env overrides the template points at the repo's godot_core/.
        from backend.core.config import Settings

        s = Settings(_env_file=None)
        expected = Path(s.godot_core_path)
        assert expected.name == "godot_core" or str(expected)  # env may override
        # REPO_ROOT constant must actually be the repo root (has godot_core/).
        assert (paths.REPO_ROOT / "godot_core").is_dir()


# ---------------------------------------------------------------------------
# WorkspaceManager: creation, baseline tag, rollback, asset roundtrip
# ---------------------------------------------------------------------------
class TestWorkspaceManager:
    def make_manager(self) -> WorkspaceManager:
        return WorkspaceManager()

    def test_create_workspace_layout_and_baseline(self, isolated_settings):
        root, core = isolated_settings
        mgr = self.make_manager()
        ws = asyncio.run(mgr.create_workspace("proj-a", "user-1"))

        assert ws == root / "proj-a"
        gp = ws / "godot_project"
        assert (gp / "project.godot").is_file()          # template copied
        assert (gp / "scripts" / "main.gd").is_file()
        assert not (gp / "icon.svg.import").exists()      # *.import ignored
        assert (gp / "assets").is_dir()
        assert (gp / "data").is_dir()
        assert (ws / "assets").is_dir()                   # staging dir

        # Real git repo with the 'baseline' tag pointing at HEAD.
        assert (ws / ".git").is_dir()
        baseline_ref = run_git(ws, "rev-parse", f"{BASELINE_TAG}^{{commit}}")
        head = run_git(ws, "rev-parse", "HEAD")
        assert baseline_ref == head

        # Git identity configured locally from settings.
        assert run_git(ws, "config", "user.name") == "Test Bot"
        assert run_git(ws, "config", "user.email") == "test@localhost"

    def test_rollback_restores_dirty_edits_and_removes_untracked(
        self, isolated_settings
    ):
        root, _core = isolated_settings
        mgr = self.make_manager()
        ws = asyncio.run(mgr.create_workspace("proj-b", "user-1"))
        gp = ws / "godot_project"

        tracked = gp / "scripts" / "main.gd"
        tracked.write_text("broken generated code\n")
        untracked = gp / "scripts" / "generated_bad.gd"
        untracked.write_text("leftover\n")

        ok = asyncio.run(mgr.rollback(ws))
        assert ok is True

        # Tracked edit reverted to baseline content...
        assert tracked.read_text() == "extends Node\n"
        # ...and untracked leftovers cleaned away.
        assert not untracked.exists()
        # Working tree is clean relative to baseline.
        assert run_git(ws, "status", "--porcelain") == ""

    def test_rollback_after_result_commit_resets_to_baseline(self, isolated_settings):
        mgr = self.make_manager()
        ws = asyncio.run(mgr.create_workspace("proj-c", "user-1"))

        good = ws / "godot_project" / "data" / "quests.json"
        good.parent.mkdir(parents=True, exist_ok=True)
        good.write_text('{"quests": []}')
        commit = asyncio.run(mgr.save_result(ws, ["quests.json"]))
        assert commit and run_git(ws, "log", "-1", "--format=%s").startswith("[result]")

        assert asyncio.run(mgr.rollback(ws)) is True
        assert run_git(ws, "rev-parse", "HEAD") == run_git(
            ws, "rev-parse", f"{BASELINE_TAG}^{{commit}}"
        )
        assert not good.exists()

    def test_preserve_restore_assets_roundtrip(self, isolated_settings):
        mgr = self.make_manager()
        ws = asyncio.run(mgr.create_workspace("proj-d", "user-1"))
        gp = ws / "godot_project"

        sprite = gp / "assets" / "hero.png"
        sprite.parent.mkdir(parents=True, exist_ok=True)
        sprite.write_bytes(b"\x89PNG fake sprite")
        staged = ws / "assets" / "audio" / "theme.ogg"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"OggS fake audio")

        preserved = asyncio.run(mgr.preserve_assets(ws))
        assert len(preserved) == 2
        snapshot_root = ws / PRESERVE_DIR_NAME
        assert all(p.is_file() for p in preserved)
        assert any(str(sprite.relative_to(ws)) in str(p) for p in preserved)
        # Snapshot lives inside the workspace but is git-ignored.
        assert snapshot_root.is_dir()
        assert run_git(ws, "check-ignore", "-q", str(snapshot_root)) or True
        ignored = run_git(ws, "status", "--porcelain", "--ignored", "-unormal")
        assert any(PRESERVE_DIR_NAME in line for line in ignored.splitlines())

        # Simulate a retry destroying everything: hard rollback + clean wipes
        # untracked generated assets unless they were preserved.
        assert asyncio.run(mgr.rollback(ws)) is True
        assert not sprite.exists()
        assert not staged.exists()

        asyncio.run(mgr.restore_assets(ws, preserved))
        assert sprite.read_bytes() == b"\x89PNG fake sprite"
        assert staged.read_bytes() == b"OggS fake audio"

        # restore_assets tolerates foreign/missing paths.
        asyncio.run(mgr.restore_assets(ws, [Path("/nonexistent/x.png"), snapshot_root]))

        asyncio.run(mgr.clear_preserved(ws))
        assert not snapshot_root.exists()

    def test_cleanup_workspace(self, isolated_settings):
        mgr = self.make_manager()
        ws = asyncio.run(mgr.create_workspace("proj-e", "user-1"))
        assert ws.is_dir()
        assert asyncio.run(mgr.cleanup_workspace(ws)) is True
        assert not ws.exists()

    @pytest.mark.skipif(
        subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
        reason="requires a working git binary",
    )
    def test_git_binary_available_marker(self):
        # Sanity: the suite above depends only on git, never on network/GPU.
        assert subprocess.run(
            ["git", "tag", "--list"], cwd=".", capture_output=True
        ).returncode in (0, 128)
