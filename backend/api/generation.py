"""
API routes for game generation endpoints.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import uuid

from backend.services.orchestration import get_orchestrator
from backend.services.workspace_manager import get_workspace_manager
from backend.services.billing_service import get_billing_service
from backend.schemas.api_schemas import (
    GenerationResponse, ProjectStatusResponse,
)

router = APIRouter()


class WizardInput(BaseModel):
    """Wizard input from frontend."""
    genre: str
    perspective: str
    art_style: str
    setting: str
    scale: str
    controls: str
    saving_enabled: bool
    monetization: str
    quest_complexity: str
    dialogue_depth: str
    lore_id: Optional[str] = None
    description: str


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
        user_id = "default_user"  # TODO: Get from auth
        
        # Convert wizard input to orchestrator format
        wizard_input = {
            "genre": request.genre,
            "perspective": request.perspective,
            "art_style": request.art_style,
            "setting": request.setting,
            "scale": request.scale,
            "controls": request.controls,
            "has_saving": request.saving_enabled,
            "monetization": request.monetization,
            "quest_complexity": request.quest_complexity,
            "dialogue_depth": request.dialogue_depth,
            "lore_collection_id": request.lore_id,
            "description": request.description,
            "project_name": project_id,
        }
        
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
                
                print(f"Generation completed for {project_id}: success={success}, attempt={attempt_number}, credits_charged={should_charge}")
            except Exception as e:
                print(f"Generation failed for {project_id}: {e}")
        
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


@router.get("/status/{project_id}", response_model=ProjectStatusResponse)
async def get_generation_status(project_id: str):
    """
    Get current generation status for a project.
    
    Returns:
    - status: "pending" | "running" | "completed" | "failed"
    - progress: 0-100 percentage
    - current_agent: which agent is currently running
    - logs: array of log messages
    - result: final result if completed
    """
    # TODO: Implement status tracking with Redis/DB
    # For now, return mock data
    return ProjectStatusResponse(
        project_id=project_id,
        status="running",
        progress=45,
        current_agent="coder",
        logs=[
            "✓ GDD created",
            "✓ Architecture planned: 5 modules",
            "✓ Generated 2 quests",
            "✓ Generated 1 dialogue trees",
            "✓ Generated 8 asset prompts",
            "→ Generating code..."
        ],
        attempt_number=1
    )


@router.get("/{project_id}/download")
async def download_project(project_id: str, format: str = "web"):
    """
    Download generated project.
    
    Formats:
    - web: HTML5/WebAssembly export
    - apk: Android export (Pro tier+)
    - source: Godot source code only
    """
    workspace_manager = get_workspace_manager()
    
    # TODO: Implement actual export logic
    # For now, return mock response
    return {
        "success": True,
        "download_url": f"/api/v1/generation/{project_id}/download/{format}",
        "format": format,
        "size_mb": 15.2
    }


@router.post("/{project_id}/preview")
async def generate_preview(project_id: str):
    """
    Generate web preview for a project.
    
    Triggers Godot web export and returns preview URL.
    Warning: Takes ~30 seconds as shown in PreviewWarningStep.
    """
    # TODO: Implement web export with Godot headless
    return {
        "success": True,
        "preview_url": f"/preview/{project_id}",
        "message": "⚠️ Building and loading the web version takes about 30 seconds. Enjoy the process of creating magic!",
        "estimated_time_seconds": 30
    }


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """Delete a project and all associated files."""
    workspace_manager = get_workspace_manager()
    
    # TODO: Implement deletion
    return {"success": True, "message": f"Project {project_id} deleted"}
