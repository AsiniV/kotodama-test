"""
Marketplace API Routes

Endpoints for module marketplace operations:
- Submit module
- Search modules
- Download module
- Publish module
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from pathlib import Path
from typing import Optional

from backend.services.marketplace_service import (
    get_marketplace_service,
    MarketplaceService,
    ModuleMetadata,
)

router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])


class SubmitModuleRequest(BaseModel):
    """Request to submit a module."""
    module_id: str
    name: str
    description: str
    category: str
    price_credits: int = 0
    tags: list[str] = None
    dependencies: list[str] = None


class SubmitModuleResponse(BaseModel):
    """Response from module submission."""
    success: bool
    message: str
    module_id: str | None = None


class SearchModulesResponse(BaseModel):
    """Response from module search."""
    modules: list[dict]
    total: int


@router.post("/submit", response_model=SubmitModuleResponse)
async def submit_module(
    request: SubmitModuleRequest,
    user_id: str = Query(..., description="Author ID"),
    service: MarketplaceService = Depends(get_marketplace_service),
):
    """Submit a module to the marketplace."""
    # In production, module_path would come from file upload
    # For now, we simulate with a test module path
    module_path = Path(f"/workspace/test_modules/{request.module_id}")
    
    if not module_path.exists():
        raise HTTPException(status_code=400, detail="Module path does not exist")
    
    metadata = ModuleMetadata(
        module_id=request.module_id,
        name=request.name,
        description=request.description,
        author_id=user_id,
        category=request.category,  # type: ignore
        price_credits=request.price_credits,
        tags=request.tags or [],
        dependencies=request.dependencies or [],
    )
    
    success, message = await service.submit_module(module_path, metadata, user_id)
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return SubmitModuleResponse(
        success=True,
        message=message,
        module_id=request.module_id,
    )


@router.get("/search", response_model=SearchModulesResponse)
async def search_modules(
    query: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None, description="Filter by category"),
    min_rating: float = Query(0.0, ge=0.0, le=5.0),
    max_price: Optional[int] = Query(None, ge=0),
    free_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    service: MarketplaceService = Depends(get_marketplace_service),
):
    """Search marketplace modules."""
    results = service.search_modules(
        query=query,
        category=category,
        min_rating=min_rating,
        max_price=max_price,
        free_only=free_only,
    )
    
    # Convert to dict and limit
    modules = [
        {
            "module_id": m.metadata.module_id,
            "name": m.metadata.name,
            "description": m.metadata.description,
            "category": m.metadata.category,
            "price_credits": m.metadata.price_credits,
            "rating": m.metadata.rating,
            "downloads": m.metadata.downloads,
            "tags": m.metadata.tags,
        }
        for m in results[:limit]
    ]
    
    return SearchModulesResponse(
        modules=modules,
        total=len(results),
    )


@router.get("/{module_id}")
async def get_module(
    module_id: str,
    service: MarketplaceService = Depends(get_marketplace_service),
):
    """Get module details."""
    module = service.get_module(module_id)
    
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    return {
        "metadata": module.metadata.model_dump(),
        "files": module.files,
        "assets": [a.model_dump() for a in module.assets],
        "security_scan": {
            "passed": module.security_scan.passed,
            "violations_count": len(module.security_scan.violations),
            "warnings": module.security_scan.warnings,
        },
        "plagiarism_checks": [p.model_dump() for p in module.plagiarism_checks],
    }


@router.post("/{module_id}/publish")
async def publish_module(
    module_id: str,
    user_id: str = Query(..., description="Author ID"),
    service: MarketplaceService = Depends(get_marketplace_service),
):
    """Publish a module to the marketplace."""
    success, message = await service.publish_module(module_id, user_id)
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message}


@router.post("/{module_id}/download")
async def download_module(
    module_id: str,
    user_id: str = Query(..., description="User ID"),
    service: MarketplaceService = Depends(get_marketplace_service),
):
    """Download a module."""
    success, message = await service.download_module(module_id, user_id)
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message}
