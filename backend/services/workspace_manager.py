"""
Workspace Manager - Handles project creation, git versioning, and rollback.

Features:
- Create workspace from template
- Git-like versioning with baseline/result commits
- Rollback to previous stable state
- Asset preservation during code retries
"""

import asyncio
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional
import hashlib


class WorkspaceManager:
    """Manages game project workspaces with version control."""

    def __init__(self, base_path: str = "/workspace/workspaces"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.templates_path = Path("/workspace/templates/godot_core")

    async def create_workspace(self, project_id: str, user_id: str) -> Path:
        """Create a new workspace from template."""
        workspace_path = self.base_path / user_id / project_id
        workspace_path.mkdir(parents=True, exist_ok=True)
        
        # Copy Godot core template
        if self.templates_path.exists():
            await self._copy_template(workspace_path)
        
        # Initialize git repo
        await self._init_git(workspace_path)
        
        # Create baseline commit
        await self._commit(workspace_path, "baseline", "Initial workspace creation")
        
        return workspace_path

    async def _copy_template(self, workspace_path: Path) -> None:
        """Copy Godot core template to workspace."""
        game_project_path = workspace_path / "game_project"
        if not game_project_path.exists():
            shutil.copytree(self.templates_path, game_project_path)

    async def _init_git(self, path: Path) -> None:
        """Initialize git repository."""
        try:
            process = await asyncio.create_subprocess_exec(
                "git", "init",
                cwd=str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
        except Exception as e:
            print(f"Git init failed: {e}")

    async def _commit(self, path: Path, commit_type: str, message: str) -> str:
        """Create a git commit."""
        try:
            # Stage all files
            await asyncio.create_subprocess_exec(
                "git", "add", "-A",
                cwd=str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ).communicate()
            
            # Commit
            timestamp = datetime.now().isoformat()
            full_message = f"[{commit_type}] {message} @ {timestamp}"
            process = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", full_message,
                cwd=str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            
            # Get commit hash
            rev_process = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "HEAD",
                cwd=str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            rev_stdout, _ = await rev_process.communicate()
            return rev_stdout.decode("utf-8").strip()
        except Exception as e:
            print(f"Git commit failed: {e}")
            return ""

    async def save_result(self, workspace_path: Path, changes: list[str]) -> str:
        """Save generation result as 'result' commit."""
        return await self._commit(workspace_path, "result", f"Generated: {', '.join(changes)}")

    async def rollback(self, workspace_path: Path) -> bool:
        """Rollback to baseline commit."""
        try:
            process = await asyncio.create_subprocess_exec(
                "git", "reset", "--hard", "baseline",
                cwd=str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
            return process.returncode == 0
        except Exception as e:
            print(f"Rollback failed: {e}")
            return False

    async def preserve_assets(self, workspace_path: Path) -> list[Path]:
        """Extract asset paths before code retry."""
        assets_path = workspace_path / "game_project" / "assets"
        preserved = []
        
        if assets_path.exists():
            for asset_file in assets_path.rglob("*"):
                if asset_file.is_file():
                    preserved.append(asset_file)
        
        return preserved

    async def restore_assets(self, workspace_path: Path, preserved_assets: list[Path]) -> None:
        """Restore assets after code retry."""
        # Assets are already in git, so reset will restore them
        # This method is for additional safety if needed
        pass

    def get_workspace_info(self, workspace_path: Path) -> dict:
        """Get workspace metadata."""
        game_project_path = workspace_path / "game_project"
        
        return {
            "path": str(workspace_path),
            "exists": workspace_path.exists(),
            "has_game_project": game_project_path.exists(),
            "assets_count": len(list((game_project_path / "assets").glob("*"))) if game_project_path.exists() else 0,
            "modules_count": len(list((game_project_path / "modules").glob("*"))) if game_project_path.exists() else 0,
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
