"""
Architect Agent - Analyzes GDD and plans Godot scene structure, modules, and signal contracts.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import GameDesignDocument, ArchitecturePlan

logger = logging.getLogger("kotodama.agents.architect")


class ArchitectAgent(BaseAgent[ArchitecturePlan]):
    """
    Architect Agent responsible for creating architecture plans from GDDs.
    
    Input: GameDesignDocument
    Output: ArchitecturePlan with scene tree, modules, signal contracts, and level parameters
    """
    
    def __init__(self, model_name: str = "qwen2.5-coder:32b", temperature: float = 0.15):
        super().__init__(model_name=model_name, temperature=temperature)
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Godot 4.3 Architect AI specialized in modular game architecture.
Your task is to analyze a Game Design Document and create a detailed Architecture Plan.

CRITICAL RULES:
1. Core Engine is IMMUTABLE - never suggest changes to: Scene Management, Input System, Global Signal Bus, State Machine, Physics, UI Framework
2. All module communication MUST use signals with `module_` prefix (e.g., module_enemy_defeated, module_quest_completed)
3. Every signal channel must be registered via register_channel()
4. Every channel must have at least one publisher and one subscriber (QA will verify)
5. Respect the closed vocabulary of 10 asset slots: player, enemy, background, ui_button, tileset, item, npc, projectile, hazard, icon
6. If has_saving is true, include save_system_required: true

SCENE STRUCTURE:
- Use Godot 4.3 node hierarchy (Node2D/Node3D, CharacterBody2D/3D, Area2D/3D, etc.)
- Modules are isolated scenes that can be added/removed without breaking the game
- Main scene should reference modules through the Global Signal Bus

SIGNAL CONTRACT FORMAT:
Each signal contract must include:
- name: string with module_ prefix
- publisher: module name that emits the signal
- subscribers: list of modules that listen to the signal
- parameters: list of parameter names and types

LEVEL PARAMETERS (for procedural generation):
If the game requires levels, include level_parameters with:
- algorithm: "bsp", "cellular_automata", "wfc", or "random_walk"
- width, height: grid dimensions
- theme: setting theme
- points_of_interest: list of important locations
- enemy_density: 0.0-1.0
- item_density: 0.0-1.0
- start_room, end_room: room identifiers

Output MUST be valid JSON matching the ArchitecturePlan schema."""

    async def execute(self, input_data: GameDesignDocument) -> ArchitecturePlan:
        """
        Execute the Architect agent.
        
        Args:
            input_data: GameDesignDocument from Game Designer
            
        Returns:
            ArchitecturePlan with complete architecture specification
        """
        prompt = self._build_prompt(input_data)
        result = await self._call_llm(prompt, ArchitecturePlan)
        
        logger.info(f"Generated Architecture Plan for: {input_data.title}")
        return result
    
    def _build_prompt(self, gdd: GameDesignDocument) -> str:
        """Build the prompt for the LLM."""
        prompt = f"""Create an Architecture Plan based on the following Game Design Document:

TITLE: {gdd.title}
GENRE: {gdd.genre}
PERSPECTIVE: {gdd.perspective}
ART STYLE: {gdd.art_style}
SETTING: {gdd.setting}
SCALE: {gdd.scale}
CORE MECHANICS: {', '.join(gdd.core_mechanics)}
MODULE DEPENDENCIES: {', '.join(gdd.module_dependencies)}
ESTIMATED MODULES: {', '.join(gdd.estimated_modules)}
LORE CONTEXT: {gdd.lore_context or 'None'}

Generate a comprehensive Architecture Plan including:
1. Scene tree structure (hierarchical Godot node layout)
2. Required modules with specifications
3. Signal contracts (all inter-module communications)
4. Asset slots needed (from the 10-slot vocabulary)
5. Level parameters if applicable (for procedural generation)
6. Save system requirement flag

Follow all rules in the system prompt."""
        
        return prompt


# Singleton instance
_architect_agent = None


def get_architect_agent() -> ArchitectAgent:
    """Get singleton instance of ArchitectAgent."""
    global _architect_agent
    if _architect_agent is None:
        _architect_agent = ArchitectAgent()
    return _architect_agent
