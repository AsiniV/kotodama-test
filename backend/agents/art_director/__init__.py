"""
Art Director Agent - Generates image prompts for Stable Diffusion, manages asset metadata.
"""

import logging
from typing import List, Tuple
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import ArchitecturePlan, GeneratedAsset, AssetPromptsOutput

logger = logging.getLogger("kotodama.agents.art_director")


class ArtDirectorAgent(BaseAgent):
    """
    Art Director Agent responsible for generating asset prompts and managing art pipeline.
    
    Input: ArchitecturePlan + LoreContext + ArtStyle
    Output: AssetPromptsOutput with prompts and assets
    
    CRITICAL: Uses closed vocabulary of 10 asset slots only.
    """
    
    # Closed vocabulary of 10 asset slots (per spec Section 3.4)
    VALID_SLOTS = ["player", "enemy", "background", "ui_button", "tileset", "item", "npc", "projectile", "hazard", "icon"]
    
    def __init__(self, model_name: str = "qwen2.5:32b", temperature: float = 0.6):
        super().__init__(model_name=model_name, temperature=temperature)
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Art Director AI specialized in game asset creation for Godot 4.3.
Your task is to generate precise image generation prompts for Stable Diffusion.

CRITICAL RULES:
1. Use ONLY the closed vocabulary of 10 asset slots: player, enemy, background, ui_button, tileset, item, npc, projectile, hazard, icon
2. Each slot can be used ONCE per project
3. Prompts must be specific and include: style, colors, mood, resolution hints
4. Match the art_style from the Architecture Plan (pixel-art, hand-drawn, low-poly, etc.)
5. Include lore context when available for thematic consistency

PROMPT FORMAT:
Each prompt should be detailed and include:
- Subject description (what it is)
- Art style (pixel-art, vector, painted, etc.)
- Color palette (specific colors)
- Mood/atmosphere
- Technical hints (e.g., "sprite sheet", "transparent background", "512x512")

ASSET METADATA:
For each asset, generate complete metadata including:
- path: "assets/{slot}.png"
- slot: one of the 10 valid slots
- type: "sprite", "texture", "ui", etc.
- tags: relevant tags for searchability
- dimensions: expected size (e.g., [512, 512])
- prompt_used: the exact SD prompt

Output MUST be valid JSON matching AssetPromptsOutput schema."""

    async def execute(self, architecture_plan: ArchitecturePlan, lore_context: str | None = None, art_style: str = "pixel-art") -> AssetPromptsOutput:
        """
        Execute the Art Director agent.
        
        Args:
            architecture_plan: Architecture plan with required asset slots
            lore_context: Optional lore context from PGVector
            art_style: Art style from wizard input
            
        Returns:
            AssetPromptsOutput with prompts and assets
        """
        prompt = self._build_prompt(architecture_plan, lore_context, art_style)
        
        # Call LLM to generate prompts
        result = await self._call_llm(prompt, AssetPromptsOutput)
        
        logger.info(f"Generated {len(result.prompts)} asset prompts")
        return result
    
    def _build_prompt(self, arch_plan: ArchitecturePlan, lore_context: str | None, art_style: str) -> str:
        """Build the prompt for the LLM."""
        prompt = f"""Generate asset generation prompts based on the following Architecture Plan:

ART STYLE: {art_style}
REQUIRED SLOTS: {arch_plan.asset_slots_needed}
SETTING: {getattr(arch_plan, 'setting', 'generic')}
"""
        
        if lore_context:
            prompt += f"\nLORE CONTEXT:\n{lore_context}\n"
        
        prompt += """
Generate detailed Stable Diffusion prompts for each required asset slot.
Each prompt should be specific enough for consistent art generation.
Follow all rules in the system prompt."""
        
        return prompt


# Singleton instance
_art_director_agent = None


def get_art_director_agent() -> ArtDirectorAgent:
    """Get singleton instance of ArtDirectorAgent."""
    global _art_director_agent
    if _art_director_agent is None:
        _art_director_agent = ArtDirectorAgent()
    return _art_director_agent
