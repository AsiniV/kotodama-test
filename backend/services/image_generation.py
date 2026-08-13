"""
Image Generation Service - Interfaces with Stable Diffusion and cloud providers.
Supports local SD WebUI (A1111) and cloud fallbacks (Fal.ai, Replicate).
"""

import logging
from pathlib import Path
from typing import Optional, Literal
import httpx
from backend.core.config import get_settings
from backend.schemas.agent_schemas import AssetPrompt, GeneratedAsset
from datetime import datetime

settings = get_settings()
logger = logging.getLogger("kotodama.services.image_gen")


class ImageGenerationService:
    """
    Service for generating images via Stable Diffusion or cloud providers.
    
    Priority:
    1. Local Stable Diffusion WebUI (A1111) - default
    2. Fal.ai (Flux.1) - cloud fallback
    3. Replicate - secondary fallback
    """
    
    def __init__(self):
        self.sd_webui_url = settings.sd_webui_url
        self.fal_api_key = settings.fal_api_key
        self.replicate_api_key = settings.replicate_api_key
        self.default_provider = settings.image_gen_provider
    
    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 512,
        height: int = 512,
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: int = -1,
        provider: Optional[Literal["local", "fal", "replicate"]] = None
    ) -> tuple[Path, dict]:
        """
        Generate an image from a prompt.
        
        Args:
            prompt: Positive prompt describing the image
            negative_prompt: Negative prompt for things to avoid
            width: Image width in pixels
            height: Image height in pixels
            steps: Number of diffusion steps
            cfg_scale: CFG scale for guidance
            seed: Random seed (-1 for random)
            provider: Provider to use (auto-select if None)
            
        Returns:
            Tuple of (saved_file_path, metadata_dict)
        """
        provider = provider or self.default_provider
        
        try:
            if provider == "local":
                return await self._generate_local(prompt, negative_prompt, width, height, steps, cfg_scale, seed)
            elif provider == "fal":
                return await self._generate_fal(prompt, negative_prompt, width, height)
            elif provider == "replicate":
                return await self._generate_replicate(prompt, negative_prompt, width, height)
            else:
                raise ValueError(f"Unknown provider: {provider}")
                
        except Exception as e:
            # Try fallback providers if primary fails
            logger.warning(f"Primary provider {provider} failed: {e}. Trying fallback...")
            
            if provider != "local":
                try:
                    return await self._generate_local(prompt, negative_prompt, width, height, steps, cfg_scale, seed)
                except Exception as local_err:
                    logger.error(f"Local fallback also failed: {local_err}")
            
            if provider not in ["fal", "local"]:
                try:
                    return await self._generate_fal(prompt, negative_prompt, width, height)
                except Exception as fal_err:
                    logger.error(f"Fal fallback also failed: {fal_err}")
            
            # Re-raise original error if all fallbacks fail
            raise
    
    async def _generate_local(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        seed: int
    ) -> tuple[Path, dict]:
        """Generate image using local Stable Diffusion WebUI."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "width": width,
                "height": height,
                "steps": steps,
                "cfg_scale": cfg_scale,
                "seed": seed if seed >= 0 else -1,
                "sampler_name": "Euler a",
                "batch_size": 1,
                "n_iter": 1,
            }
            
            response = await client.post(
                f"{self.sd_webui_url}/sdapi/v1/txt2img",
                json=payload
            )
            
            if response.status_code != 200:
                raise Exception(f"SD WebUI error: {response.text}")
            
            result = response.json()
            
            # Decode base64 image
            import base64
            image_data = base64.b64decode(result["images"][0])
            
            # Save to temporary file
            output_dir = Path("/tmp/kotodama_assets")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"generated_{timestamp}.png"
            
            with open(output_path, "wb") as f:
                f.write(image_data)
            
            metadata = {
                "provider": "local",
                "prompt_used": prompt,
                "negative_prompt": negative_prompt,
                "dimensions": (width, height),
                "steps": steps,
                "cfg_scale": cfg_scale,
            }
            
            logger.info(f"Generated image locally: {output_path}")
            return output_path, metadata
    
    async def _generate_fal(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int
    ) -> tuple[Path, dict]:
        """Generate image using Fal.ai (Flux.1)."""
        if not self.fal_api_key:
            raise Exception("Fal.ai API key not configured")
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            headers = {
                "Authorization": f"Key {self.fal_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "prompt": prompt,
                "image_size": {"width": width, "height": height},
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
            }
            
            response = await client.post(
                "https://fal.network/api/fal_ai/flux/dev",
                headers=headers,
                json=payload
            )
            
            if response.status_code != 200:
                raise Exception(f"Fal.ai error: {response.text}")
            
            result = response.json()
            image_url = result.get("image", {}).get("url")
            
            if not image_url:
                raise Exception("No image URL in Fal.ai response")
            
            # Download image
            img_response = await client.get(image_url)
            if img_response.status_code != 200:
                raise Exception("Failed to download image from Fal.ai")
            
            # Save to file
            output_dir = Path("/tmp/kotodama_assets")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"generated_{timestamp}.png"
            
            with open(output_path, "wb") as f:
                f.write(img_response.content)
            
            metadata = {
                "provider": "fal",
                "prompt_used": prompt,
                "dimensions": (width, height),
            }
            
            logger.info(f"Generated image via Fal.ai: {output_path}")
            return output_path, metadata
    
    async def _generate_replicate(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int
    ) -> tuple[Path, dict]:
        """Generate image using Replicate."""
        if not self.replicate_api_key:
            raise Exception("Replicate API key not configured")
        
        import asyncio
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            headers = {
                "Authorization": f"Token {self.replicate_api_key}",
                "Content-Type": "application/json"
            }
            
            # Create prediction
            payload = {
                "version": "ac7321b1d4e6f0c8b6e8e8f3e6f3e6f3e6f3e6f3e6f3e6f3",  # Example version
                "input": {
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "width": width,
                    "height": height,
                    "num_outputs": 1,
                    "num_inference_steps": 25,
                }
            }
            
            response = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers=headers,
                json=payload
            )
            
            if response.status_code not in [200, 201]:
                raise Exception(f"Replicate error: {response.text}")
            
            prediction = response.json()
            
            # Poll for completion
            while prediction["status"] not in ["succeeded", "failed", "canceled"]:
                await asyncio.sleep(2)
                pred_response = await client.get(prediction["urls"]["get"], headers=headers)
                prediction = pred_response.json()
            
            if prediction["status"] != "succeeded":
                raise Exception(f"Replicate prediction failed: {prediction.get('error', 'Unknown error')}")
            
            image_url = prediction["output"][0] if prediction.get("output") else None
            
            if not image_url:
                raise Exception("No image URL in Replicate response")
            
            # Download image
            img_response = await client.get(image_url)
            if img_response.status_code != 200:
                raise Exception("Failed to download image from Replicate")
            
            # Save to file
            output_dir = Path("/tmp/kotodama_assets")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"generated_{timestamp}.png"
            
            with open(output_path, "wb") as f:
                f.write(img_response.content)
            
            metadata = {
                "provider": "replicate",
                "prompt_used": prompt,
                "dimensions": (width, height),
            }
            
            logger.info(f"Generated image via Replicate: {output_path}")
            return output_path, metadata
    
    async def generate_asset_batch(
        self,
        prompts: list[AssetPrompt],
        slot_mapping: dict[str, str]
    ) -> list[GeneratedAsset]:
        """
        Generate multiple assets from a list of prompts.
        
        Args:
            prompts: List of AssetPrompt objects
            slot_mapping: Mapping of slot names to file paths
            
        Returns:
            List of GeneratedAsset metadata objects
        """
        generated_assets = []
        
        for prompt_config in prompts:
            try:
                # Generate image
                image_path, metadata = await self.generate_image(
                    prompt=prompt_config.prompt,
                    negative_prompt=prompt_config.negative_prompt,
                    width=prompt_config.width,
                    height=prompt_config.height,
                )
                
                # Determine slot from mapping
                slot = slot_mapping.get(str(image_path), "icon")
                
                # Create asset metadata
                asset = GeneratedAsset(
                    path=f"assets/{slot}.png",
                    slot=slot,
                    asset_type="sprite" if slot in ["player", "enemy", "npc", "item"] else "texture",
                    tags=prompt_config.tags,
                    dimensions=(prompt_config.width, prompt_config.height),
                    used_in=[],
                    prompt_used=prompt_config.prompt,
                    provider=metadata["provider"],
                    generated_at=datetime.now()
                )
                
                generated_assets.append(asset)
                
            except Exception as e:
                logger.error(f"Failed to generate asset for slot {prompt_config.style}: {e}")
                # Continue with other assets even if one fails
        
        return generated_assets


# Singleton instance
_image_gen_service: Optional["ImageGenerationService"] = None


def get_image_gen_service() -> ImageGenerationService:
    """Get or create ImageGenerationService singleton."""
    global _image_gen_service
    if _image_gen_service is None:
        _image_gen_service = ImageGenerationService()
    return _image_gen_service
