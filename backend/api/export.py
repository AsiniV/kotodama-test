"""
Export API Routes

Endpoints for game export operations:
- Export to Web
- Export to Android (APK)
- Export to iOS (IPA)
- Export job status
"""

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, Literal
import uuid
from datetime import datetime

from backend.services.export_service import (
    get_export_service,
    get_fastlane_service,
    GodotExportService,
    FastlaneExportService,
    ExportConfig,
    ExportJob,
    ExportResult,
)

router = APIRouter(prefix="/api/v1/export", tags=["export"])


class ExportRequest(BaseModel):
    """Request to export a project."""
    project_id: str
    user_id: str
    platform: Literal["web", "android", "ios", "windows", "macos", "linux"]
    preset_name: str = "Web"
    debug: bool = False
    timeout_seconds: int = 300


class ExportResponse(BaseModel):
    """Response from export request."""
    job_id: str
    status: str
    message: str


class ExportStatusResponse(BaseModel):
    """Response with export job status."""
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    progress_percent: float = 0.0
    result: dict | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


@router.post("/request", response_model=ExportResponse)
async def request_export(
    request: ExportRequest,
    background_tasks: BackgroundTasks,
    service: GodotExportService = Depends(get_export_service),
):
    """Request a game export."""
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    
    # Create output path
    output_dir = Path(f"/workspace/exports/{request.user_id}/{request.project_id}")
    output_file = output_dir / f"{request.project_id}_{request.platform}"
    
    if request.platform == "web":
        output_file = output_file.with_suffix(".html")
    elif request.platform == "android":
        output_file = output_file.with_suffix(".apk")
    elif request.platform == "ios":
        output_file = output_file.with_suffix(".ipa")
    elif request.platform == "windows":
        output_file = output_file.with_suffix(".exe")
    elif request.platform == "macos":
        output_file = output_file.with_suffix(".app")
    elif request.platform == "linux":
        output_file = output_file.with_suffix(".x86_64")
    
    # Create export config
    config = ExportConfig(
        project_path=Path(f"/workspace/workspace_instances/{request.project_id}"),
        output_path=output_file,
        preset_name=request.preset_name,
        platform=request.platform,  # type: ignore
        debug=request.debug,
        timeout_seconds=request.timeout_seconds,
    )
    
    # Create export job
    job = ExportJob(
        job_id=job_id,
        user_id=request.user_id,
        project_id=request.project_id,
        config=config,
    )
    
    # Queue the job
    await service.queue_export(job)
    
    # Start processing in background
    background_tasks.add_task(service.process_queue, max_concurrent=2)
    
    return ExportResponse(
        job_id=job_id,
        status="pending",
        message=f"Export job queued for {request.platform} platform",
    )


@router.get("/status/{job_id}", response_model=ExportStatusResponse)
async def get_export_status(
    job_id: str,
    service: GodotExportService = Depends(get_export_service),
):
    """Get status of an export job."""
    job = service.get_job_status(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    
    result_dict = None
    if job.result:
        result_dict = {
            "success": job.result.success,
            "platform": job.result.platform,
            "output_file": str(job.result.output_file) if job.result.output_file else None,
            "file_size_bytes": job.result.file_size_bytes,
            "duration_seconds": job.result.duration_seconds,
            "godot_version": job.result.godot_version,
        }
    
    # Calculate progress
    progress = 0.0
    if job.status == "pending":
        progress = 0.0
    elif job.status == "running":
        progress = 50.0  # Estimate
    elif job.status == "completed":
        progress = 100.0
    elif job.status == "failed":
        progress = 0.0
    
    return ExportStatusResponse(
        job_id=job_id,
        status=job.status,  # type: ignore
        progress_percent=progress,
        result=result_dict,
        error_message=job.result.error_message if job.result and not job.result.success else None,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.post("/android/build")
async def build_android_apk(
    project_id: str,
    user_id: str = Query(...),
    version_code: int = 1,
    version_name: str = "1.0.0",
    service: FastlaneExportService = Depends(get_fastlane_service),
):
    """Build signed Android APK using Fastlane."""
    project_path = Path(f"/workspace/workspace_instances/{project_id}")
    output_path = Path(f"/workspace/exports/{user_id}/{project_id}.apk")
    
    success, message = await service.build_android_apk(
        project_path=project_path,
        output_path=output_path,
        version_code=version_code,
        version_name=version_name,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message, "apk_path": str(output_path)}


@router.post("/ios/build")
async def build_ios_ipa(
    project_id: str,
    user_id: str = Query(...),
    scheme: str = "Game",
    workspace: Optional[str] = None,
    service: FastlaneExportService = Depends(get_fastlane_service),
):
    """Build signed iOS IPA using Fastlane."""
    project_path = Path(f"/workspace/workspace_instances/{project_id}")
    output_path = Path(f"/workspace/exports/{user_id}/{project_id}.ipa")
    
    success, message = await service.build_ios_ipa(
        project_path=project_path,
        output_path=output_path,
        scheme=scheme,
        workspace=workspace,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message, "ipa_path": str(output_path)}


@router.post("/android/upload")
async def upload_to_play_store(
    apk_path: str,
    package_name: str,
    track: Literal["internal", "alpha", "beta", "production"] = "internal",
    service: FastlaneExportService = Depends(get_fastlane_service),
):
    """Upload APK to Google Play Store."""
    success, message = await service.upload_to_play_store(
        apk_path=Path(apk_path),
        package_name=package_name,
        track=track,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message}


@router.post("/ios/upload")
async def upload_to_app_store(
    ipa_path: str,
    bundle_id: str,
    service: FastlaneExportService = Depends(get_fastlane_service),
):
    """Upload IPA to Apple App Store."""
    success, message = await service.upload_to_app_store(
        ipa_path=Path(ipa_path),
        bundle_id=bundle_id,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message}


@router.post("/configure/android")
async def configure_android_export(
    keystore_path: str,
    keystore_password: str,
    key_alias: str,
    key_password: str,
    service: FastlaneExportService = Depends(get_fastlane_service),
):
    """Configure Android signing credentials."""
    service.configure_android(
        keystore_path=Path(keystore_path),
        keystore_password=keystore_password,
        key_alias=key_alias,
        key_password=key_password,
    )
    
    return {"success": True, "message": "Android credentials configured"}


@router.post("/configure/ios")
async def configure_ios_export(
    apple_id: str,
    apple_password: str,
    app_store_connect_api_key: Optional[str] = None,
    service: FastlaneExportService = Depends(get_fastlane_service),
):
    """Configure iOS signing credentials."""
    service.configure_ios(
        apple_id=apple_id,
        apple_password=apple_password,
        app_store_connect_api_key=app_store_connect_api_key,
    )
    
    return {"success": True, "message": "iOS credentials configured"}
