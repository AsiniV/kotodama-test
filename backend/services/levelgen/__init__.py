"""
Phase 10: deterministic procedural level generation.

This package replaces LLM-imagined room coordinates with real, seeded
geometry algorithms. Every generator is a pure function of its parameters
plus an integer ``seed`` (Python's Mersenne Twister via ``random.Random``),
so the same seed always yields byte-identical layouts.

Algorithms:
    * ``bsp``            — Binary Space Partitioning dungeon (rooms + corridors)
    * ``cellular_automata`` — cave carved by CA smoothing, rooms detected from floors
    * ``wfc``            — Wave Function Collapse on a simple tile set
    * ``random_walk``    — drunkard's-carver, rooms detected from floors

All four return a validated :class:`backend.schemas.agent_schemas.LevelLayout`
whose grid (``grid`` field, row-major strings of '#' wall / '.' floor) is
guaranteed start->end reachable; reachability is verified with BFS before the
layout is returned and ``ValueError`` is raised if it fails.

Public API:
    generate_layout(params, seed=None) -> LevelLayout   # dispatch by params['algorithm']
    ALGORITHMS: mapping name -> generator callable
"""
from __future__ import annotations

from .base import (
    ALGORITHMS,
    Grid,
    generate_layout,
    normalize_level_parameters,
    resolve_seed,
)
from .bsp import generate_bsp
from .cellular_automata import generate_cellular_automata
from .wfc import generate_wfc
from .random_walk import generate_random_walk

__all__ = [
    "ALGORITHMS",
    "Grid",
    "generate_layout",
    "normalize_level_parameters",
    "resolve_seed",
    "generate_bsp",
    "generate_cellular_automata",
    "generate_wfc",
    "generate_random_walk",
]
