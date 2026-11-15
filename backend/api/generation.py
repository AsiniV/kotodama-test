"""
API routes for game generation endpoints.

Phase 7: ``/status/{id}`` reports *real* agent progress (Redis event stream +
Postgres fallback via :mod:`backend.services.progress_service`). The old mock
payloads are gone; every endpoint either does real workspace work or fails
honestly (404 / 501) instead of pretending.
"""
import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List
from urllib.parse import quote

from backend.services.orchestration import get_orchestrator
from backend.services.workspace_manager import get_workspace_manager
from backend.services.billing_service import get_billing_service
from backend.services.progress_service import get_progress_service
from backend.core import paths
from backend.schemas.api_schemas import (
    GenerationResponse, ProjectStatusResponse,
)
# Canonical WizardInput lives in backend.schemas.agent_schemas (single source).
from backend.schemas.agent_schemas import AudioRequest, WizardInput

router = APIRouter()
logger = logging.getLogger("kotodama.api.generation")


class DownloadMeta(BaseModel):
    """Metadata returned by ``GET /{project_id}/download?...&meta=true``."""

    project_id: str
    filename: str
    format: str
    size_bytes: int


@router.post("/start", response_model=GenerationResponse)
async def start_generation(
    request: WizardInput,
    background_tasks: BackgroundTasks
):
    """
    Start game generation from wizard input.

    This endpoint:
    1. Creates a new project/workspace
    2. Starts the multi-agent generation pipeline
    3. Returns immediately with project ID for status tracking
    """
    try:
        project_id = str(uuid.uuid4())
        user_id = "default_user"  # TODO: Get from auth (auth phase)

        # Stamp the generated project id onto the canonical model
        wizard_input = request.model_copy(update={"project_name": project_id})

        # Calculate credit cost BEFORE starting generation
        billing_service = get_billing_service()
        estimated_credits = billing_service.calculate_generation_cost(wizard_input)

        # Check if user has sufficient credits
        has_credits = await billing_service.check_credits_sufficient(user_id, estimated_credits)
        if not has_credits:
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient credits. Required: {estimated_credits}, Your balance: Please check your subscription."
            )

        orchestrator = get_orchestrator()

        # Open the durable progress record synchronously so an immediate
        # GET /status/{project_id} after this response already finds a real
        # ("running", 0%) entry instead of racing the background task.
        await get_progress_service().start_run(project_id, user_id=user_id)

        # Start generation in background
        async def run_generation():
            try:
                result = await orchestrator.run_generation(
                    wizard_input=wizard_input,
                    user_id=user_id,
                    project_id=project_id
                )

                # Handle credit charging based on Two-Attempt Rule
                attempt_number = result.get("attempt_number", 1)
                success = result.get("success", False)

                # Charge credits on success OR second attempt failure
                should_charge = success or (attempt_number >= 2)

                if should_charge:
                    await billing_service.deduct_credits(
                        user_id=user_id,
                        amount=estimated_credits,
                        project_id=project_id,
                        attempt_number=attempt_number,
                    )

                logger.info(
                    "Generation completed for %s: success=%s, attempt=%s, credits_charged=%s",
                    project_id, success, attempt_number, should_charge,
                )
            except Exception as e:
                logger.exception("Generation failed for %s: %s", project_id, e)
                # The orchestrator's finally-block normally finalizes the
                # progress record; this covers exceptions raised outside it.
                try:
                    await get_progress_service().finalize(
                        project_id, success=False, error_message=str(e)
                    )
                except Exception:  # pragma: no cover - defensive cleanup
                    logger.warning("Could not finalize failed progress for %s", project_id)

        background_tasks.add_task(run_generation)

        return GenerationResponse(
            success=True,
            project_id=project_id,
            message="Generation started successfully",
            estimated_time_seconds=180,  # 3 minutes
            estimated_credits=estimated_credits
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start generation: {str(e)}")


@router.post("/generate-audio")
async def trigger_audio_generation(
    game_id: str,
    audio_requests: List[AudioRequest],
    background_tasks: BackgroundTasks,
):
    """ЭТАП 2.4: запуск локальной генерации звука (MusicGen / AudioLDM 2).

    Генерация занимает 10-40 секунд на трек, поэтому HTTP-ответ не блокируется:
    задачи ставятся в BackgroundTasks и выполняются после возврата ответа.
    """
    # Canonical layout (backend/core/paths.py): staging dir
    # {workspace_root}/{game_id}/assets/audio — the same directory
    # GodotIntegrator copies from during integration.
    workspace_path = str(
        paths.staging_assets_path(game_id) / "audio"
    )
    os.makedirs(workspace_path, exist_ok=True)

    try:
        from backend.services.audio_generator import get_audio_engine

        engine = get_audio_engine()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    for req in audio_requests:
        background_tasks.add_task(
            _process_audio_task,
            req=req,
            engine=engine,
            workspace_path=workspace_path,
            game_id=game_id,
        )

    return {
        "status": "queued",
        "message": "Audio generation started",
        "queued": len(audio_requests),
        "workspace_path": workspace_path,
    }


async def _process_audio_task(req: AudioRequest, engine, workspace_path: str, game_id: str):
    """Обёртка над backend.services.audio_generator.process_audio_task."""
    from backend.services.audio_generator import process_audio_task

    return await process_audio_task(req, engine, workspace_path, game_id)


@router.get("/status/{project_id}", response_model=ProjectStatusResponse)
async def get_generation_status(project_id: str):
    """
    Real generation status for a project (Phase 7 — no mocks).

    Data sources, merged by the orchestrator:
    - Redis progress event stream written on every node transition
      (``generation:progress:{id}``, TTL'd), mirrored to Postgres at the end
      of each run — survives restarts and multi-worker deployments;
    - the live LangGraph checkpoint when reachable (freshest state + logs).

    Returns:
    - status: "pending" | "running" | "completed" | "failed"
    - progress: 0-100 percentage (interpolated between stage boundaries
      while running; exact stage-completion values otherwise)
    - current_agent: which pipeline stage is currently running
    - logs: real messages produced by the agents so far
    - result: final outcome snapshot once the run finished
    - 404 when the project id is unknown to both stores
    """
    orchestrator = get_orchestrator()

    view = None
    try:
        view = await orchestrator.get_status(project_id)
    except Exception as e:
        logger.exception("get_status failed for %s: %s", project_id, e)
        # Fall back to the raw durable record if the merge layer breaks.
        progress = await get_progress_service().get_progress_with_fallback(project_id)
        if progress is not None:
            view = {
                "status": progress.status,
                "progress": progress.progress_pct,
                "current_stage": progress.current_stage,
                "attempt_number": progress.attempt_number,
                "logs": [ev.message for ev in progress.events[-50:] if ev.message],
                "error_message": progress.error_message,
                "result": progress.result_snapshot,
            }

    if view is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return ProjectStatusResponse(
        project_id=project_id,
        status=view["status"],
        progress=int(view["progress"]),
        current_agent=view["current_stage"],
        logs=list(view["logs"]),
        attempt_number=int(view["attempt_number"]),
        error_message=view.get("error_message"),
        result=view.get("result"),
    )


@router.get("/{project_id}/download")
async def download_project(
    project_id: str,
    format: str = Query(default="source", pattern="^(web|apk|source)$"),
    meta: bool = Query(default=False),
) -> Response:
    """
    Download the generated project.

    Formats:
    - source: zipped Godot project (``godot_project/`` of the workspace)
    - web / apk: exported build from ``exports/{project_id}/`` (produced by
      the export pipeline, Phase 9)

    With ``?meta=true`` the endpoint only reports whether the artifact exists
    and its size (used by the frontend before triggering a big download).
    Unknown project → 404; known project whose artifact was never built → 501.
    """
    ws_root = paths.workspace_root().resolve()
    safe_id = _validate_project_id(project_id, ws_root)
    workspace = ws_root / safe_id

    if format == "source":
        source_dir = workspace / paths.GODOT_PROJECT_DIR_NAME
        if not source_dir.is_dir():
            _raise_artifact_or_unknown(project_id, workspace, "source")
        zip_path = await asyncio.to_thread(_zip_godot_project, safe_id, source_dir)
    else:
        export_dir = paths.exports_dir() / safe_id
        if not export_dir.is_dir():
            _raise_artifact_or_unknown(project_id, workspace, format)
        artifact = _pick_export_artifact(export_dir, format)
        if artifact is None:
            _raise_artifact_or_unknown(project_id, workspace, format)
        zip_path = None

    file_path = zip_path or artifact
    assert file_path is not None
    filename = file_path.name

    if meta:
        meta_model = DownloadMeta(
            project_id=project_id,
            filename=filename,
            format=format,
            size_bytes=file_path.stat().st_size,
        )
        return JSONResponse(content=meta_model.model_dump())

    return FileResponse(
        path=str(file_path),
        media_type="application/zip" if format == "source" else "application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"'},
    )


def _validate_project_id(project_id: str, ws_root: Path) -> str:
    """Reject traversal/absolute ids before touching the filesystem."""
    candidate = Path(project_id)
    if (
        not project_id
        or candidate.is_absolute()
        or ".." in candidate.parts
        or "/" in project_id
        or "\\" in project_id
    ):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    resolved = (ws_root / candidate).resolve()
    if resolved != ws_root and ws_root not in resolved.parents:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project_id


def _raise_artifact_or_unknown(project_id: str, workspace: Path, format: str) -> None:
    """404 when the project never existed, 501 when the artifact isn't built."""
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    raise HTTPException(
        status_code=501,
        detail=(
            f"{format} artifact for {project_id} has not been generated yet; "
            "run generation (or the export pipeline) first"
        ),
    )


def _zip_godot_project(project_id: str, source_dir: Path) -> Path:
    """Zip ``godot_project/`` into {workspace}/builds/<id>_source.zip (cached)."""
    builds_dir = source_dir.parent / "builds"
    builds_dir.mkdir(parents=True, exist_ok=True)
    zip_path = builds_dir / f"{project_id}_source.zip"
    if zip_path.exists():
        zip_path.unlink()  # always serve a fresh archive
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=str(source_dir))
    return zip_path


def _pick_export_artifact(export_dir: Path, format: str) -> Path | None:
    """Find the newest exported build matching the requested format."""
    patterns = {"web": ("*.zip", "*.html"), "apk": ("*.apk",)}[format]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(p for p in export_dir.rglob(pattern) if p.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


@router.post("/{project_id}/preview")
async def generate_preview(project_id: str):
    """
    Generate a web preview for a project.

    Requires the Web export build produced by the export pipeline
    (``POST /api/v1/export/{id}``, Phase 9) — this endpoint intentionally does
    NOT fake a preview URL: without a real build it answers 404 (unknown
    project) or 501 (export missing) so clients can tell the difference.
    """
    ws_root = paths.workspace_root().resolve()
    safe_id = _validate_project_id(project_id, ws_root)
    workspace = ws_root / safe_id
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    export_dir = paths.exports_dir() / safe_id
    artifact = _pick_export_artifact(export_dir, "web") if export_dir.is_dir() else None
    if artifact is None:
        raise HTTPException(
            status_code=501,
            detail=(
                f"No web export found for {project_id}; run generation to completion "
                "and trigger the export pipeline (POST /api/v1/export/{project_id}) first"
            ),
        )

    return {
        "success": True,
        "preview_url": f"/preview/{project_id}",
        "artifact": artifact.name,
        "message": (
            "⚠️ Building and loading the web version takes about 30 seconds. "
            "Enjoy the process of creating magic!"
        ),
        "estimated_time_seconds": 30,
    }


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """Delete a project workspace and all its progress records."""
    ws_root = paths.workspace_root().resolve()
    safe_id = _validate_project_id(project_id, ws_root)
    workspace = ws_root / safe_id
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    # Defense-in-depth: never delete outside the canonical workspace root.
    resolved = workspace.resolve()
    if resolved == ws_root or ws_root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Refusing to delete protected path")

    # Real deletion through the workspace manager (git metadata included);
    # fall back to plain rmtree if the manager fails on a broken repo.
    removed = False
    try:
        workspace_manager = get_workspace_manager()
        removed = await workspace_manager.cleanup_workspace(resolved)
    except Exception as e:
        logger.warning("WorkspaceManager cleanup failed for %s: %s", project_id, e)
    if not removed:
        try:
            await asyncio.to_thread(shutil.rmtree, str(resolved))
            removed = True
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete project: {e}")

    # Drop durable progress so /status/{id} returns 404 afterwards.
    try:
        await get_progress_service().clear(project_id)
    except Exception as e:  # pragma: no cover - defensive cleanup
        logger.warning("Progress clear failed for %s: %s", project_id, e)

    return {"success": True, "message": f"Project {project_id} deleted"}
