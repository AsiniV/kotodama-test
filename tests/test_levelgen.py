"""Phase 10 closing: deterministic level generation + LevelGeneratorAgent wrapper.

Covers (fully offline — no GPU / Godot / LLM server / network):

* every algorithm in ``backend.services.levelgen`` (bsp, cellular_automata,
  wfc, random_walk) produces a schema-valid :class:`LevelLayout` whose grid
  is well-shaped and whose start->end rooms are BFS-reachable;
* seeding is deterministic: same params+seed -> identical layouts, different
  seeds -> different layouts (and an explicit seed overrides the derived one);
* ``LevelGeneratorAgent`` is a thin parameter-choosing wrapper: with a mocked
  LLM it proposes parameters (plan params win), delegates geometry to
  ``generate_layout``, tolerates the known ``LevelLayoutValidator``
  id-vs-room_type mismatch (PHASE_NOTES.md), and falls back deterministically
  when the LLM fails or returns garbage.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import pytest

from backend.agents.level_generator import LevelGeneratorAgent
from backend.schemas.agent_schemas import (
    ArchitecturePlan,
    LevelGeneratorInput,
    LevelLayout,
)
from backend.schemas.levelgen_schemas import LevelGenerationProposal
from backend.services.levelgen import generate_layout
from backend.services.levelgen.base import bfs_reachable, cell_center

ALGORITHMS: Tuple[str, ...] = ("bsp", "cellular_automata", "wfc", "random_walk")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _params(algorithm: str, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "algorithm": algorithm,
        "width": 48,
        "height": 48,
        "min_rooms": 3,
        "max_rooms": 8,
        "enemy_density": 0.1,
        "item_density": 0.05,
        "points_of_interest": ["shrine", "forge"],
        "seed": 1234,
    }
    base.update(overrides)
    return base


def _bfs_start_to_end(layout: LevelLayout) -> bool:
    """Independent BFS check: room-centre of start_room reaches end_room."""
    assert layout.grid is not None, "deterministic layouts must ship a real grid"
    grid: List[str] = list(layout.grid)
    assert len(grid) == layout.height
    assert all(len(row) == layout.width for row in grid)
    rooms = {r.id or f"room_{i}": r for i, r in enumerate(layout.rooms)}
    start = rooms[layout.start_room]
    end = rooms[layout.end_room]
    s = cell_center((start.x, start.y, start.width, start.height))
    e = cell_center((end.x, end.y, end.width, end.height))
    return bfs_reachable(grid, s, e)


def _make_plan(level_parameters: Dict[str, Any]) -> ArchitecturePlan:
    return ArchitecturePlan(
        scene_tree={"root": "Main"},
        required_modules=[{"id": "level_generator", "purpose": "procedural levels"}],
        signal_contracts=[],
        asset_slots_needed=["tileset"],
        level_parameters=level_parameters,
    )


# ---------------------------------------------------------------------------
# Deterministic engines: schema validity + reachability for all 4 algorithms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_generate_layout_returns_valid_level_layout(algorithm: str) -> None:
    layout = generate_layout(_params(algorithm))
    assert isinstance(layout, LevelLayout)
    assert layout.algorithm == algorithm
    assert layout.width == 48 and layout.height == 48
    assert len(layout.rooms) >= 1
    assert layout.start_room and layout.end_room
    room_ids = {r.id for r in layout.rooms}
    assert layout.start_room in room_ids and layout.end_room in room_ids
    # Pydantic v2 round-trip: the model serialises and revalidates cleanly.
    reparsed = LevelLayout.model_validate(json.loads(layout.model_dump_json()))
    assert reparsed == layout


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_grid_is_well_shaped_and_spawns_on_floor(algorithm: str) -> None:
    layout = generate_layout(_params(algorithm))
    assert layout.grid is not None
    for row in layout.grid:
        assert set(row) <= {"#", "."}
    for x, y in list(layout.enemy_spawn_points) + list(layout.item_spawn_points):
        assert layout.grid[y][x] == ".", f"spawn ({x},{y}) sits on a wall"


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_bfs_start_to_end_reachable(algorithm: str) -> None:
    layout = generate_layout(_params(algorithm))
    assert _bfs_start_to_end(layout), f"{algorithm}: end room unreachable from start"


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_reachable_across_many_seeds(algorithm: str) -> None:
    """The WFC staircase/ADJACENCY contradiction used to fail *every* seed;
    guard all four engines across a seed sweep instead of a single lucky run."""
    for seed in range(20):
        layout = generate_layout(_params(algorithm, seed=seed))
        assert _bfs_start_to_end(layout), f"{algorithm} seed={seed} unreachable"


# ---------------------------------------------------------------------------
# Seeding determinism
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_same_seed_is_deterministic(algorithm: str) -> None:
    first = generate_layout(_params(algorithm, seed=99))
    second = generate_layout(_params(algorithm, seed=99))
    assert first.model_dump() == second.model_dump()


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_different_seeds_diverge(algorithm: str) -> None:
    a = generate_layout(_params(algorithm, seed=1))
    b = generate_layout(_params(algorithm, seed=2))
    assert a.grid != b.grid, f"{algorithm}: seed has no effect on geometry"


def test_explicit_seed_kwarg_overrides_params_seed() -> None:
    via_kwarg = generate_layout(_params("bsp", seed=5), seed=77)
    pinned = generate_layout(_params("bsp", seed=77))
    assert via_kwarg.model_dump() == pinned.model_dump()


def test_unknown_algorithm_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown level generation algorithm"):
        generate_layout(_params("not_a_real_algorithm"))


# ---------------------------------------------------------------------------
# LevelGeneratorAgent: thin LLM parameter-choosing wrapper (mocked LLM)
# ---------------------------------------------------------------------------

async def test_agent_with_mocked_llm_delegates_geometry(install_fake_llm) -> None:
    """The LLM only chooses parameters; the plan's level_parameters win and
    the deterministic engine carves the geometry."""
    proposal = LevelGenerationProposal(
        algorithm="wfc", width=64, height=64, theme="crypt", max_rooms=6
    )
    fake = install_fake_llm([proposal])

    plan_params = _params("bsp", seed=42)  # plan must override the proposal
    agent = LevelGeneratorAgent()
    layout = await agent.execute(
        LevelGeneratorInput(architecture_plan=_make_plan(plan_params))
    )

    assert len(fake.calls) == 1
    assert fake.calls[0]["response_model"] is LevelGenerationProposal
    assert isinstance(layout, LevelLayout)
    assert layout.algorithm == "bsp"          # plan wins over proposal
    assert layout.width == 48                 # plan wins over proposal's 64
    assert layout.validation_passed is True
    assert _bfs_start_to_end(layout)
    # Same plan (same seed) through the agent -> byte-identical layout.
    again = await LevelGeneratorAgent().execute(
        LevelGeneratorInput(architecture_plan=_make_plan(dict(plan_params)))
    )
    assert again.model_dump() == layout.model_dump()


async def test_agent_fills_gaps_the_plan_left_open(install_fake_llm) -> None:
    """Keys absent from level_parameters come from the LLM proposal."""
    proposal = LevelGenerationProposal(
        algorithm="random_walk", points_of_interest=["altar"], seed=7
    )
    install_fake_llm([proposal])
    layout = await LevelGeneratorAgent().execute(
        LevelGeneratorInput(architecture_plan=_make_plan({"theme": "ruins"}))
    )
    assert layout.algorithm == "random_walk"  # proposal fills the gap
    assert _bfs_start_to_end(layout)


async def test_agent_deterministic_fallback_when_llm_fails(install_fake_llm) -> None:
    install_fake_llm([RuntimeError("LLM unavailable")])
    agent = LevelGeneratorAgent()
    layout = await agent.execute(
        LevelGeneratorInput(
            architecture_plan=_make_plan(_params("cellular_automata", seed=5))
        )
    )
    assert isinstance(layout, LevelLayout)
    assert layout.algorithm == "cellular_automata"
    assert layout.validation_passed is True
    assert _bfs_start_to_end(layout)


async def test_agent_recovers_from_garbage_llm_output(install_fake_llm) -> None:
    """Invalid proposals fall back; the pipeline never blocks on the model."""
    install_fake_llm(["not json at all"])
    layout = await LevelGeneratorAgent().execute(
        LevelGeneratorInput(architecture_plan=_make_plan(_params("wfc", seed=11)))
    )
    assert layout.algorithm == "wfc"
    assert _bfs_start_to_end(layout)


async def test_agent_requires_level_parameters(install_fake_llm) -> None:
    install_fake_llm([LevelGenerationProposal()])
    with pytest.raises(ValueError, match="level_parameters"):
        await LevelGeneratorAgent().execute(
            LevelGeneratorInput(architecture_plan=_make_plan({}))
        )


async def test_agent_rejects_wrong_input_type() -> None:
    with pytest.raises(TypeError):
        await LevelGeneratorAgent().execute("not-an-input-model")  # type: ignore[arg-type]


async def test_agent_tolerates_validator_id_vs_room_type_mismatch(install_fake_llm) -> None:
    """Adjacent Phase-10 bug (see PHASE_NOTES.md): LevelLayoutValidator
    compares start_room/end_room (room_<i> ids) against room_type values.
    The wrapper must not fail on that stale check but must still enforce
    genuine errors (e.g. overlapping rooms)."""
    install_fake_llm([LevelGenerationProposal()])
    agent = LevelGeneratorAgent()
    layout = generate_layout(_params("bsp", seed=3))

    result = agent._validate(layout, max_enemy_density=0.5, max_item_density=0.5)
    assert bool(result)  # tolerated -> passes despite validator's stale errors

    broken = layout.model_copy(deep=True)
    broken.rooms[1].x = broken.rooms[0].x  # force an overlap
    broken.rooms[1].y = broken.rooms[0].y
    with pytest.raises(ValueError, match="Overlapping rooms"):
        agent._validate(broken, max_enemy_density=0.5, max_item_density=0.5)
