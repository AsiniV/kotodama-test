"""
Level Generator Agent - Procedural level generation using BSP, Cellular Automata, WFC.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import ArchitecturePlan, LevelLayout
from backend.validators import create_level_validator, ValidationResult

logger = logging.getLogger("kotodama.agents.level_generator")


class LevelGeneratorAgent(BaseAgent):
    """
    Level Generator Agent responsible for procedural level generation.
    
    Input: ArchitecturePlan with level_parameters
    Output: LevelLayout with rooms, corridors, spawn points (validated)
    
    Algorithms: BSP, Cellular Automata, Wave Function Collapse, Random Walk
    """
    
    def __init__(self, model_name: str = "qwen2.5-coder:32b", temperature: float = 0.15):
        super().__init__(model_name=model_name, temperature=temperature)
        self.validator = None
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Level Design AI specialized in procedural generation algorithms.
Your task is to generate level layouts using algorithmic approaches with LLM-defined parameters.

SUPPORTED ALGORITHMS:
1. BSP (Binary Space Partitioning) - Dungeons, buildings, space stations
2. Cellular Automata - Caves, organic terrain, forests
3. Wave Function Collapse - Tile-based levels, cities, puzzles
4. Random Walk - Simple mazes, paths

VALIDATION RULES:
1. Start and End points must exist in valid rooms
2. All points of interest must be reachable from start (A* verifiable)
3. No overlapping rooms (BSP guarantees this)
4. Enemy density does not exceed threshold in any single room
5. At least one path exists from start to end

OUTPUT FORMAT:
Return a LevelLayout with:
- algorithm: which algorithm was used
- width, height: grid dimensions
- rooms: list of Room objects with x, y, width, height, type
- corridors: list of Corridor objects connecting rooms
- points_of_interest: dict of important locations
- enemy_spawn_points: list of (x, y) tuples
- item_spawn_points: list of (x, y) tuples
- start_room, end_room: room identifiers
- validation_passed: true if all checks pass

Output MUST be valid JSON matching LevelLayout schema."""

    async def execute(self, arch_plan: ArchitecturePlan, 
                     max_enemy_density: float = 0.5,
                     max_item_density: float = 0.5) -> LevelLayout:
        """
        Execute the Level Generator agent.
        
        Args:
            arch_plan: Architecture Plan with level_parameters
            max_enemy_density: Maximum enemy density per unit area
            max_item_density: Maximum item density per unit area
            
        Returns:
            Validated LevelLayout object
            
        Raises:
            ValueError: If validation fails or no level_parameters
        """
        if not arch_plan.level_parameters:
            raise ValueError("No level_parameters in architecture plan")
        
        prompt = self._build_prompt(arch_plan)
        result = await self._call_llm(prompt, LevelLayout)
        
        # Validate generated level
        validator = create_level_validator(
            max_enemy_density=max_enemy_density,
            max_item_density=max_item_density
        )
        
        validation_result = validator.validate_level(result)
        
        if not validation_result.passed:
            error_msg = f"Level validation failed: {'; '.join(validation_result.errors)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        if validation_result.warnings:
            for warning in validation_result.warnings:
                logger.warning(f"Level warning: {warning}")
        
        # Mark as validated
        result.validation_passed = True
        
        logger.info(f"Generated and validated {len(result.rooms)} rooms using {result.algorithm}")
        return result
    
    def _build_prompt(self, arch_plan: ArchitecturePlan) -> str:
        """Build the prompt for the LLM."""
        params = arch_plan.level_parameters
        prompt = f"""Generate a procedural level layout with the following parameters:

ALGORITHM: {params.get('algorithm', 'bsp')}
DIMENSIONS: {params.get('width', 64)}x{params.get('height', 64)}
THEME: {params.get('theme', 'generic')}
POINTS OF INTEREST: {params.get('points_of_interest', [])}
ENEMY DENSITY: {params.get('enemy_density', 0.3)}
ITEM DENSITY: {params.get('item_density', 0.2)}
START ROOM: {params.get('start_room', 'entrance')}
END ROOM: {params.get('end_room', 'exit')}

Follow all rules in the system prompt."""
        
        return prompt


# Singleton instance
_level_generator_agent = None


def get_level_generator_agent() -> LevelGeneratorAgent:
    """Get singleton instance of LevelGeneratorAgent."""
    global _level_generator_agent
    if _level_generator_agent is None:
        _level_generator_agent = LevelGeneratorAgent()
    return _level_generator_agent
