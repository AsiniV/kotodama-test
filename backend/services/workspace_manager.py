"""
Workspace Manager - Handles project creation, git versioning, and rollback.

Canonical layout (see backend/core/paths.py — single source of truth):

    {workspace_root}/{project_id}/          <- git root
        godot_project/                      <- copy of the immutable godot_core template
            assets/                         <- sprites / audio / music (res://assets/...)
            data/                           <- generated JSON data files
        assets/                             <- raw-asset staging (audio gen, MinIO cache)

Features:
- Create workspace from the repo-level ``godot_core/`` template
- Git versioning with a real ``baseline`` tag plus ``[result]`` commits
- Rollback that actually restores the baseline (tag reset + working-tree clean)
- Asset preservation across code retries: files are copied out to a snapshot
  dir before the hard reset and re-copied afterwards (git alone does not
  protect untracked/generated assets).
"""

import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.core import paths
from backend.core.config import get_settings

#: Tag created on the initial workspace commit; rollback resets to this ref.
BASELINE_TAG = "baseline"
#: Directory (inside the workspace, git-ignored) holding preserved assets.
PRESERVE_DIR_NAME = ".kotodama_preserved"


class WorkspaceManager:
    """Manages game project workspaces with version control."""

    def __init__(self, base_path: Optional[str] = None) -> None:
        settings = get_settings()
        self.base_path = (
            Path(base_path).expanduser().resolve()
            if base_path is not None
            else paths.workspace_root()
        )
        self.templates_path = paths.template_path()
        self.git_author_name = settings.git_author_name
        self.git_author_email = settings.git_author_email
        self.base_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Workspace lifecycle
    # ------------------------------------------------------------------
    async def create_workspace(self, project_id: str, user_id: str) -> Path:
        """Create a new workspace from the godot_core template.

        ``user_id`` is accepted for API compatibility with the orchestrator;
        ownership is tracked in the database, while the on-disk layout is the
        flat canonical ``{workspace_root}/{project_id}`` (Phase 4 goal: one
        layout everywhere).
        """
        workspace_path = self.base_path / project_id
        workspace_path.mkdir(parents=True, exist_ok=True)

        # Deterministic subdirectories of the canonical layout.
        (workspace_path / paths.STAGING_ASSETS_DIR_NAME).mkdir(parents=True, exist_ok=True)

        # Copy Godot core template into godot_project/
        if self.templates_path.is_dir():
            await self._copy_template(workspace_path)
        godot_project = workspace_path / paths.GODOT_PROJECT_DIR_NAME
        (godot_project / "assets").mkdir(parents=True, exist_ok=True)
        (godot_project / "data").mkdir(parents=True, exist_ok=True)

        # Initialize git repo and create the tagged baseline commit.
        await self._init_git(workspace_path)
        await self._commit(workspace_path, "baseline", "Initial workspace creation")
        await self._tag_baseline(workspace_path)

        return workspace_path

    async def _copy_template(self, workspace_path: Path) -> None:
        """Copy the immutable godot_core template into godot_project/."""
        godot_project_path = workspace_path / paths.GODOT_PROJECT_DIR_NAME
        if not godot_project_path.exists():
            shutil.copytree(
                self.templates_path,
                godot_project_path,
                ignore=shutil.ignore_patterns("*.import", "__pycache__"),
            )

    # ------------------------------------------------------------------
    # Git plumbing
    # ------------------------------------------------------------------
    async def _run_git(self, path: Path, *args: str) -> tuple[int, str, str]:
        """Run a git command in ``path``; return (returncode, stdout, stderr)."""
        process = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return (
            process.returncode or 0,
            stdout.decode("utf-8", "replace"),
            stderr.decode("utf-8", "replace"),
        )

    async def _init_git(self, path: Path) -> None:
        """Initialize git repository with a local identity and default branch."""
        try:
            returncode, _, stderr = await self._run_git(path, "init", "-b", "main")
            if returncode != 0:
                # Older git (< 2.28) has no -b flag; fall back to plain init.
                returncode, _, stderr = await self._run_git(path, "init")
            if returncode != 0:
                print(f"Git init failed: {stderr}")
                return

            # Local identity so commits work even on hosts without global
            # git config (containers, CI).
            await self._run_git(path, "config", "user.name", self.git_author_name)
            await self._run_git(path, "config", "user.email", self.git_author_email)

            # Keep generated caches and asset-preservation snapshots out of git.
            gitignore = path / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(
                    "\n".join(
                        [
                            "**/*.import",
                            "__pycache__/",
                            f"{PRESERVE_DIR_NAME}/",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
        except Exception as e:
            print(f"Git init failed: {e}")

    async def _has_commits(self, path: Path) -> bool:
        returncode, _, _ = await self._run_git(path, "rev-parse", "HEAD")
        return returncode == 0

    async def _commit(self, path: Path, commit_type: str, message: str) -> str:
        """Create a git commit; return its hash ('' when there is nothing to commit)."""
        try:
            # Stage all files
            await self._run_git(path, "add", "-A")

            if await self._has_commits(path):
                # Nothing staged? Skip the (failing) empty commit, keep HEAD.
                dirty_rc, _, _ = await self._run_git(path, "diff", "--quiet", "HEAD")
                if dirty_rc == 0:
                    _, head_out, _ = await self._run_git(path, "rev-parse", "HEAD")
                    return head_out.strip()

            # Commit (identity passed explicitly — robust even if config is absent)
            timestamp = datetime.now().isoformat()
            full_message = f"[{commit_type}] {message} @ {timestamp}"
            identity_args = [
                "-c", f"user.name={self.git_author_name}",
                "-c", f"user.email={self.git_author_email}",
            ]
            returncode, _, stderr = await self._run_git(
                path, *identity_args, "commit", "-m", full_message
            )
            if returncode != 0:
                print(f"Git commit failed: {stderr}")
                return ""

            # Get commit hash
            _, rev_stdout, _ = await self._run_git(path, "rev-parse", "HEAD")
            return rev_stdout.strip()
        except Exception as e:
            print(f"Git commit failed: {e}")
            return ""

    async def _tag_baseline(self, path: Path) -> bool:
        """Create the real ``baseline`` tag that rollback resets to."""
        returncode, _, stderr = await self._run_git(path, "tag", "-f", BASELINE_TAG)
        if returncode != 0:
            print(f"Baseline tag failed: {stderr}")
        return returncode == 0

    async def save_result(self, workspace_path: Path, changes: list[str]) -> str:
        """Save generation result as 'result' commit."""
        return await self._commit(workspace_path, "result", f"Generated: {', '.join(changes)}")

    async def rollback(self, workspace_path: Path) -> bool:
        """Rollback to the baseline tag.

        Resets the branch pointer to ``baseline`` and cleans the working tree
        (including untracked files), so the workspace really returns to the
        state captured at creation time.  The ``baseline`` tag is created by
        :meth:`create_workspace` — previously rollback reset to a nonexistent
        ref and silently failed.
        """
        try:
            returncode, _, stderr = await self._run_git(
                workspace_path, "reset", "--hard", BASELINE_TAG
            )
            if returncode != 0:
                print(f"Rollback failed: {stderr}")
                return False
            # Drop untracked leftovers (generated files never committed).
            await self._run_git(workspace_path, "clean", "-fd")
            return True
        except Exception as e:
            print(f"Rollback failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Asset preservation across code retries
    # ------------------------------------------------------------------
    def _preserve_root(self, workspace_path: Path) -> Path:
        return workspace_path / PRESERVE_DIR_NAME

    async def preserve_assets(self, workspace_path: Path) -> list[Path]:
        """Snapshot current asset files before a code retry / rollback.

        Copies every file under ``godot_project/assets`` and the workspace
        staging ``assets`` dir into a git-ignored snapshot directory inside
        the workspace, preserving relative paths.  Returns the snapshot file
        paths (pass them to :meth:`restore_assets`).
        """
        snapshot_root = self._preserve_root(workspace_path)
        preserved: list[Path] = []

        sources = [
            workspace_path / paths.GODOT_PROJECT_DIR_NAME / "assets",
            workspace_path / paths.STAGING_ASSETS_DIR_NAME,
        ]
        for src_root in sources:
            if not src_root.is_dir():
                continue
            rel_base = src_root.relative_to(workspace_path)
            for asset_file in sorted(src_root.rglob("*")):
                if not asset_file.is_file():
                    continue
                dest = snapshot_root / rel_base / asset_file.relative_to(src_root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(asset_file, dest)
                preserved.append(dest)

        return preserved

    async def restore_assets(
        self, workspace_path: Path, preserved_assets: list[Path]
    ) -> None:
        """Restore assets saved by :meth:`preserve_assets` after a rollback.

        Each snapshot path is mirrored back to its original location inside
        the workspace (snapshot root removed).  Missing/foreign paths are
        skipped.
        """
        snapshot_root = self._preserve_root(workspace_path)
        for snapshot_path in preserved_assets:
            try:
                rel = Path(snapshot_path).relative_to(snapshot_root)
            except ValueError:
                # Foreign path: nothing sane to restore; skip.
                continue
            source = Path(snapshot_path)
            if not source.is_file():
                continue
            target = workspace_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    async def clear_preserved(self, workspace_path: Path) -> None:
        """Remove the snapshot directory (call once the retry cycle is done)."""
        shutil.rmtree(self._preserve_root(workspace_path), ignore_errors=True)

    # ------------------------------------------------------------------
    # Introspection / cleanup
    # ------------------------------------------------------------------
    def get_workspace_info(self, workspace_path: Path) -> dict:
        """Get workspace metadata."""
        godot_project_path = workspace_path / paths.GODOT_PROJECT_DIR_NAME

        return {
            "path": str(workspace_path),
            "exists": workspace_path.exists(),
            "has_godot_project": godot_project_path.exists(),
            "assets_count": len(list((godot_project_path / "assets").glob("*"))) if godot_project_path.exists() else 0,
            "modules_count": len(list((godot_project_path / "modules").glob("*"))) if godot_project_path.exists() else 0,
        }

    async def cleanup_workspace(self, workspace_path: Path) -> bool:
        """Remove workspace entirely."""
        try:
            if workspace_path.exists():
                shutil.rmtree(workspace_path)
                return True
            return False
        except Exception as e:
            print(f"Cleanup failed: {e}")
            return False


# Singleton instance
_workspace_manager: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    """Get or create workspace manager singleton."""
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager
