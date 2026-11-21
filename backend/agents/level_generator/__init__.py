"""
Level Generator Agent — thin LLM wrapper over deterministic levelgen (Phase 10).

Per the Phase-10 contract, the LLM never imagines room coordinates. It only
*chooses generation parameters* (algorithm, dimensions, densities) for the
architect's ``level_parameters``; the actual geometry — grid, rooms,
corridors, spawns — is produced deterministically by
:func:`backend.services.levelgen.generate_layout`, which guarantees a
well-shaped grid and verifies start->end BFS reachability before returning.

Flow of :meth:`LevelGeneratorAgent.execute`:

1. Require ``architecture_plan.level_parameters`` (orchestration skips the
   node when they are absent).
2. Ask the LLM for a :class:`backend.schemas.levelgen_schemas.LevelGenerationProposal`
   (parameters only). Any LLM failure falls back to a deterministic proposal
   derived from the plan itself — generation never blocks on the model.
3. Merge: architect ``level_parameters`` always win over the proposal; an
   explicit ``seed`` in the params pins reproducibility end-to-end.
4. Validate the resulting layout with ``LevelLayoutValidator`` (density
   thresholds come from the input model).  The deterministic engines stamp
   ``start_room``/``end_room`` as GameIR v2 room *ids* (``room_<i>``), while
   the pre-existing validator compares them against ``room_type`` values —
   a known Phase-10 adjacent bug (see PHASE_NOTES.md).  Until the validator
   is fixed upstream, the wrapper tolerates exactly that id-vs-room_type
   mismatch via :meth:`_validate` and re-asserts start/end existence against
   the real room ids itself, so generation never blocks on the stale check.
"""

import logging
from typing import Any, Dict, List, Optional

from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import (
    ArchitecturePlan,
    LevelGeneratorInput,
    LevelLayout,
)
from backend.schemas.levelgen_schemas import LevelGenerationProposal
from backend.services.levelgen import generate_layout
from backend.validators import create_level_validator, ValidationResult

logger = logging.getLogger("kotodama.agents.level_generator")


class LevelGeneratorAgent(BaseAgent):
    """
    Level Generator Agent: picks procedural-generation parameters via the LLM
    and delegates all geometry to the seeded engines in
    ``backend.services.levelgen``.

    Input: LevelGeneratorInput (ArchitecturePlan with level_parameters +
           density thresholds)
    Output: LevelLayout with real carved grid/rooms/corridors/spawns,
            BFS start->end reachable, validated

    Algorithms: BSP, Cellular Automata, Wave Function Collapse, Random Walk
    """

    role = "level_generator"

    def __init__(self, model_name: str = "qwen2.5-coder:32b", temperature: float = 0.15):
        super().__init__(model_name=model_name, temperature=temperature)
        self.validator = None

    def _get_system_prompt(self) -> str:
        return """You are an expert Level Design AI specialized in procedural generation algorithms.

Your ONLY task is to CHOOSE GENERATION PARAMETERS for a deterministic level
generator. You must NOT invent room coordinates, grids or spawn points — the
backend engine carves the real geometry from your parameters and guarantees
start->end reachability.

SUPPORTED ALGORITHMS:
1. bsp - Binary Space Partitioning: dungeons, buildings, space stations
2. cellular_automata - caves, organic terrain, forests
3. wfc - Wave Function Collapse: tile-based levels, cities, puzzles
4. random_walk - simple mazes, paths

CHOOSE SENSIBLE VALUES FOR THE THEME:
- width/height: grid size in tiles (16..512)
- min_rooms/max_rooms: room count range (bigger castles => more rooms)
- corridor_width: 1..5 (wider => easier navigation)
- enemy_density/item_density/poi_density: 0.0..1.0 fractions of floor area
- theme: one word describing the level flavour
- points_of_interest: short names of landmarks the generator should place

Output MUST be valid JSON matching the given parameter schema. No extra keys."""

    async def execute(self, input_data: LevelGeneratorInput) -> LevelLayout:
        """
        Execute the Level Generator agent.

        Args:
            input_data: LevelGeneratorInput with the architecture plan (must
                contain level_parameters) and density thresholds

        Returns:
            Validated, deterministically generated LevelLayout

        Raises:
            TypeError: if input_data is not a LevelGeneratorInput
            ValueError: If there are no level_parameters or the generated
                layout fails validation / cannot be made reachable
        """
        if not isinstance(input_data, LevelGeneratorInput):
            raise TypeError(
                f"LevelGeneratorAgent.execute expects LevelGeneratorInput, got {type(input_data).__name__}"
            )

        arch_plan = input_data.architecture_plan
        if not arch_plan.level_parameters:
            raise ValueError("No level_parameters in architecture plan")

        params = dict(arch_plan.level_parameters)
        proposal = await self._propose_parameters(params)
        merged = self._merge_params(proposal, params)

        # Deterministic geometry: same merged params (incl. optional 'seed')
        # always yield byte-identical layouts.
        result = generate_layout(merged)

        self._validate(
            result,
            max_enemy_density=input_data.max_enemy_density,
            max_item_density=input_data.max_item_density,
        )

        # Mark as validated
        result.validation_passed = True

        logger.info(f"Generated and validated {len(result.rooms)} rooms using {result.algorithm}")
        return result

    def _validate(
        self,
        layout: LevelLayout,
        *,
        max_enemy_density: float,
        max_item_density: float,
    ) -> ValidationResult:
        """Run ``LevelLayoutValidator`` while tolerating its known id-vs-type bug.

        The deterministic engines set ``start_room``/``end_room`` to GameIR v2
        room *ids* (``room_<i>``), but the pre-existing validator compares
        them against the set of ``room_type`` values (see PHASE_NOTES.md,
        Phase 10 adjacent bugs).  We therefore drop exactly those two stale
        "does not exist" errors from the validator's report — after asserting
        ourselves that the ids really resolve to rooms — and fail hard on any
        other error (overlap, connectivity, POI integrity).
        """
        validator = create_level_validator(
            max_enemy_density=max_enemy_density,
            max_item_density=max_item_density,
        )
        validation_result = validator.validate_level(layout)

        room_ids = {r.id or f"room_{i}" for i, r in enumerate(layout.rooms)}
        for endpoint in (layout.start_room, layout.end_room):
            if endpoint not in room_ids:
                error_msg = f"Level validation failed: room id '{endpoint}' does not exist"
                logger.error(error_msg)
                raise ValueError(error_msg)

        stale_prefixes = (
            f"Start room '{layout.start_room}' does not exist",
            f"End room '{layout.end_room}' does not exist",
        )
        remaining_errors: List[str] = [
            err for err in validation_result.errors if err not in stale_prefixes
        ]
        if remaining_errors:
            error_msg = f"Level validation failed: {'; '.join(remaining_errors)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Rebuild the report so it reflects the tolerated check: the raw
        # validator's ``passed`` flag is False purely because of its stale
        # id-vs-room_type comparison, which we have re-asserted above.
        result = ValidationResult(passed=True, errors=[], warnings=list(validation_result.warnings))

        for warning in result.warnings:
            logger.warning(f"Level warning: {warning}")
        return result

    async def _propose_parameters(
        self, plan_params: Dict[str, Any]
    ) -> LevelGenerationProposal:
        """Ask the LLM for generation parameters; fall back deterministically.

        The fallback keeps the pipeline fully offline-safe: when no LLM is
        reachable (or it returns garbage), the plan's own level_parameters
        already describe a complete, valid request.
        """
        try:
            prompt = self._build_prompt(plan_params)
            return await self._call_llm(prompt, LevelGenerationProposal)
        except Exception as exc:  # noqa: BLE001 - any LLM failure -> fallback
            logger.warning(
                "LevelGeneratorAgent: LLM parameter proposal failed (%s); "
                "using deterministic fallback from level_parameters",
                exc,
            )
            return self._fallback_proposal(plan_params)

    @staticmethod
    def _fallback_proposal(plan_params: Dict[str, Any]) -> LevelGenerationProposal:
        """Derive a valid proposal straight from the architect's parameters."""
        data: Dict[str, Any] = {}
        for field in LevelGenerationProposal.model_fields:
            if field in plan_params and plan_params[field] is not None:
                data[field] = plan_params[field]
        if "grid_width" in plan_params and "width" not in data:
            data["width"] = plan_params["grid_width"]
        if "grid_height" in plan_params and "height" not in data:
            data["height"] = plan_params["grid_height"]
        try:
            return LevelGenerationProposal(**data)
        except Exception:  # invalid hints (e.g. unknown algorithm) -> defaults
            return LevelGenerationProposal()

    @staticmethod
    def _merge_params(
        proposal: LevelGenerationProposal, plan_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Proposal first, then the architect's level_parameters override it.

        The plan is the source of truth (the wizard/designer chose it); the
        LLM only fills gaps (e.g. points_of_interest the plan omitted).
        Legacy aliases (grid_width/grid_height, dungeon_rooms) are normalised
        downstream by ``normalize_level_parameters``.
        """
        merged: Dict[str, Any] = proposal.model_dump()
        for key, value in plan_params.items():
            if value is not None:
                merged[key] = value
        return merged

    def _build_prompt(self, plan_params: Dict[str, Any]) -> str:
        """Build the prompt for the LLM (parameter choice only)."""
        prompt = f"""Choose procedural level generation parameters for this level brief:

ALGORITHM HINT: {plan_params.get('algorithm', 'bsp')}
DIMENSIONS: {plan_params.get('width') or plan_params.get('grid_width') or 64}x{plan_params.get('height') or plan_params.get('grid_height') or 64}
THEME: {plan_params.get('theme', 'generic')}
POINTS OF INTEREST: {plan_params.get('points_of_interest', [])}
ENEMY DENSITY: {plan_params.get('enemy_density', 0.3)}
ITEM DENSITY: {plan_params.get('item_density', 0.2)}
START ROOM: {plan_params.get('start_room', 'entrance')}
END ROOM: {plan_params.get('end_room', 'exit')}

Return ONLY the parameter JSON (no coordinates, no grid)."""

        return prompt


# Singleton instance
_level_generator_agent: Optional[LevelGeneratorAgent] = None


def get_level_generator_agent() -> LevelGeneratorAgent:
    """Get singleton instance of LevelGeneratorAgent."""
    global _level_generator_agent
    if _level_generator_agent is None:
        _level_generator_agent = LevelGeneratorAgent()
    return _level_generator_agent
