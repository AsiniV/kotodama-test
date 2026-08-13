"""
Art Pipeline Service - Coordinates asset generation, storage, and integration.
Orchestrates Art Director agent, Image Generation service, and MinIO storage.
"""

import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from backend.schemas.agent_schemas import ArchitecturePlan, AssetPromptsOutput, GeneratedAsset
from backend.agents.art_director import get_art_director_agent
from backend.services.image_generation import get_image_gen_service
from backend.services.minio_service import get_minio_service

logger = logging.getLogger("kotodama.services.art_pipeline")


class ArtPipelineService:
    """
    Service for managing the complete art generation pipeline.
    
    Workflow:
    1. Art Director generates prompts for required asset slots
    2. Image Generation creates images from prompts
    3. MinIO stores assets with proper metadata
    4. Coder receives asset paths for integration
    """
    
    def __init__(self):
        self.art_director = get_art_director_agent()
        self.image_gen = get_image_gen_service()
        self.minio = get_minio_service()
    
    async def generate_project_assets(
        self,
        architecture_plan: ArchitecturePlan,
        lore_context: Optional[str] = None,
        art_style: str = "pixel-art",
        project_id: Optional[str] = None
    ) -> AssetPromptsOutput:
        """
        Generate all assets for a project.
        
        Args:
            architecture_plan: Plan with required asset slots
            lore_context: Optional lore from PGVector
            art_style: Art style from wizard
            project_id: Project identifier for storage paths
            
        Returns:
            AssetPromptsOutput with prompts and generated assets
        """
        logger.info(f"Starting art pipeline for project {project_id}")
        logger.info(f"Required slots: {architecture_plan.asset_slots_needed}")
        
        # Step 1: Art Director generates prompts
        prompts_output = await self.art_director.execute(
            architecture_plan=architecture_plan,
            lore_context=lore_context,
            art_style=art_style
        )
        
        logger.info(f"Generated {len(prompts_output.prompts)} asset prompts")
        
        # Step 2: Generate images from prompts
        if prompts_output.prompts:
            # Create slot mapping for batch generation
            slot_mapping = {}
            for i, prompt_config in enumerate(prompts_output.prompts):
                # Determine slot from architecture plan or use index
                if i < len(architecture_plan.asset_slots_needed):
                    slot = architecture_plan.asset_slots_needed[i]
                else:
                    slot = "icon"  # Fallback
                slot_mapping[f"prompt_{i}"] = slot
            
            # Generate images
            generated_assets = await self.image_gen.generate_asset_batch(
                prompts=prompts_output.prompts,
                slot_mapping=slot_mapping
            )
            
            # Step 3: Upload to MinIO
            for asset in generated_assets:
                try:
                    # Find the corresponding generated image path
                    # (In real implementation, this would come from image_gen)
                    temp_path = Path(f"/tmp/kotodama_assets/{asset.slot}.png")
                    
                    if temp_path.exists():
                        # Upload to MinIO
                        object_name = f"assets/{asset.slot}.png"
                        await self.minio.upload_asset(temp_path, object_name)
                        
                        # Update asset path to MinIO reference
                        asset.path = f"minio://{self.minio.assets_bucket}/{object_name}"
                        
                        logger.info(f"Uploaded asset {asset.slot} to MinIO")
                    else:
                        logger.warning(f"Temporary asset file not found: {temp_path}")
                        
                except Exception as e:
                    logger.error(f"Failed to upload asset {asset.slot}: {e}")
                    # Continue with other assets even if one fails
            
            prompts_output.assets = generated_assets
        
        logger.info(f"Art pipeline completed: {len(prompts_output.assets)} assets generated")
        return prompts_output
    
    async def download_assets_for_project(
        self,
        assets: list[GeneratedAsset],
        workspace_path: Path
    ) -> list[Path]:
        """
        Download assets from MinIO to workspace.
        
        Args:
            assets: List of GeneratedAsset metadata
            workspace_path: Path to project workspace
            
        Returns:
            List of downloaded asset paths
        """
        assets_dir = workspace_path / "game_project" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        
        downloaded_paths = []
        
        for asset in assets:
            try:
                # Extract object name from MinIO path
                if asset.path.startswith("minio://"):
                    # Parse minio://bucket/path format
                    parts = asset.path.replace("minio://", "").split("/", 1)
                    if len(parts) == 2:
                        object_name = parts[1]
                    else:
                        object_name = asset.path.replace("minio://", "")
                else:
                    object_name = asset.path
                
                # Download to workspace
                dest_path = assets_dir / f"{asset.slot}.png"
                await self.minio.download_asset(object_name, dest_path)
                
                downloaded_paths.append(dest_path)
                logger.info(f"Downloaded asset {asset.slot} to {dest_path}")
                
            except Exception as e:
                logger.error(f"Failed to download asset {asset.slot}: {e}")
                # Continue with other assets
        
        return downloaded_paths
    
    async def get_asset_paths_for_coder(
        self,
        assets: list[GeneratedAsset],
        workspace_path: Path
    ) -> list[str]:
        """
        Get list of asset paths for the Coder agent.
        
        The Coder needs local paths to integrate assets into GDScript.
        
        Args:
            assets: List of GeneratedAsset metadata
            workspace_path: Path to project workspace
            
        Returns:
            List of local asset paths relative to game_project
        """
        # First ensure assets are downloaded
        downloaded = await self.download_assets_for_project(assets, workspace_path)
        
        # Return paths relative to game_project/assets/
        relative_paths = [f"assets/{path.name}" for path in downloaded]
        
        logger.info(f"Prepared {len(relative_paths)} asset paths for Coder")
        return relative_paths
    
    async def validate_asset_slots(self, asset_slots: list[str]) -> tuple[bool, list[str]]:
        """
        Validate that requested asset slots are from the closed vocabulary.
        
        Args:
            asset_slots: List of requested slot names
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        valid_slots = self.art_director.VALID_SLOTS
        errors = []
        
        for slot in asset_slots:
            if slot not in valid_slots:
                errors.append(f"Invalid asset slot '{slot}'. Must be one of: {valid_slots}")
        
        # Check for duplicates
        if len(asset_slots) != len(set(asset_slots)):
            duplicates = [slot for slot in asset_slots if asset_slots.count(slot) > 1]
            errors.append(f"Duplicate asset slots not allowed: {set(duplicates)}")
        
        is_valid = len(errors) == 0
        return is_valid, errors


# Singleton instance
_art_pipeline_service: Optional[ArtPipelineService] = None


def get_art_pipeline_service() -> ArtPipelineService:
    """Get or create ArtPipelineService singleton."""
    global _art_pipeline_service
    if _art_pipeline_service is None:
        _art_pipeline_service = ArtPipelineService()
    return _art_pipeline_service
