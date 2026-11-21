"""Shared helpers for the Phase-10 deterministic level generators.

Conventions used by every algorithm in this package:

* A layout grid is a list of ``height`` strings of length ``width``;
  ``'#'`` = wall (impassable), ``'.'`` = floor (walkable).
* Rooms are stored as ``(x, y, w, h)`` tuples of *inclusive-free* rectangle
  bounds (x..x+w-1, y..y+h-1) matching :class:`backend.schemas.agent_schemas.Room`.
* Room identifiers follow the GameIR v2 convention implemented by
  ``backend.services.ir_validator._rooms``: ``room_<index>`` into
  ``LevelLayout.rooms``. ``LevelLayout.start_room`` / ``end_room`` hold these ids.
* All randomness flows through an explicit ``random.Random(seed)`` instance —
  never the global module state — so generation is reproducible.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

RoomRect = Tuple[int, int, int, int]  # x, y, w, h
Grid = List[str]

WALL = "#"
FLOOR = "."

#: Default grid size when level_parameters omit width/height.
DEFAULT_WIDTH = 64
DEFAULT_HEIGHT = 64
MAX_GRID_DIM = 512


def resolve_seed(params: Dict[str, Any]) -> int:
    """Deterministically derive an integer seed from level parameters.

    ``params['seed']`` wins when present (int or numeric string). Otherwise a
    stable hash of the sorted parameter mapping is used, so two runs with the
    same plan produce identical geometry even without an explicit seed.
    """
    raw = params.get("seed")
    if raw is not None:
        try:
            return int(raw) & 0xFFFFFFFF
        except (TypeError, ValueError):
            pass
    digest = hashlib.sha256(
        repr(sorted((str(k), str(v)) for k, v in params.items())).encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16)


def rng_for(params: Dict[str, Any], seed: Optional[int] = None) -> random.Random:
    """Build a private RNG for one generation run."""
    return random.Random(resolve_seed(params) if seed is None else seed)


def grid_dims(params: Dict[str, Any]) -> Tuple[int, int]:
    """Extract clamped (width, height) from level parameters."""
    width = _clamp_int(params.get("width") or params.get("grid_width"), DEFAULT_WIDTH, 16, MAX_GRID_DIM)
    height = _clamp_int(params.get("height") or params.get("grid_height"), DEFAULT_HEIGHT, 16, MAX_GRID_DIM)
    return width, height


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def empty_grid(width: int, height: int, fill: str = WALL) -> List[List[str]]:
    return [[fill] * width for _ in range(height)]


def grid_to_strings(grid: List[List[str]]) -> Grid:
    return ["".join(row) for row in grid]


def carve_rect(grid: List[List[str]], rect: RoomRect) -> None:
    x, y, w, h = rect
    height = len(grid)
    width = len(grid[0]) if height else 0
    for gy in range(max(1, y), min(height - 1, y + h)):
        for gx in range(max(1, x), min(width - 1, x + w)):
            grid[gy][gx] = FLOOR


def cell_center(rect: RoomRect) -> Tuple[int, int]:
    x, y, w, h = rect
    return x + w // 2, y + h // 2


def bfs_reachable(grid: Grid, start: Tuple[int, int], goal: Tuple[int, int]) -> bool:
    """4-neighbour BFS over floor cells; True when ``goal`` is reachable from ``start``."""
    if not grid:
        return False
    height, width = len(grid), len(grid[0])

    def walkable(p: Tuple[int, int]) -> bool:
        x, y = p
        return 0 <= x < width and 0 <= y < height and grid[y][x] == FLOOR

    if not (walkable(start) and walkable(goal)):
        return False
    if start == goal:
        return True
    seen = {start}
    frontier = [start]
    while frontier:
        nxt: List[Tuple[int, int]] = []
        for cx, cy in frontier:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p = (cx + dx, cy + dy)
                if p in seen or not walkable(p):
                    continue
                if p == goal:
                    return True
                seen.add(p)
                nxt.append(p)
        frontier = nxt
    return False


def floor_cells(grid: Grid) -> List[Tuple[int, int]]:
    return [(x, y) for y, row in enumerate(grid) for x, ch in enumerate(row) if ch == FLOOR]


def detect_rooms_from_floor(grid: Grid, min_size: int = 3) -> List[RoomRect]:
    """Greedy maximal-rectangle scan used by the cave/walk generators.

    Repeatedly takes the largest all-floor rectangle anchored at the topmost,
    leftmost remaining floor cell. The result is non-overlapping and each room
    contains its anchor cell, which keeps downstream spawn placement valid.
    """
    cells = set(floor_cells(grid))
    rooms: List[RoomRect] = []
    height = len(grid)
    width = len(grid[0]) if height else 0
    while cells:
        ax, ay = min(cells, key=lambda c: (c[1], c[0]))
        # Maximal width along the row, then grow downwards.
        w = 1
        while (ax + w, ay) in cells and ax + w < width:
            w += 1
        h = 1
        while ay + h < height and all((ax + dx, ay + h) in cells for dx in range(w)):
            h += 1
        while w * h < min_size * min_size and h > 1:
            h -= 1
            w = min(w, *[dx + 1 for dx in range(w) if (ax + dx, ay + h - 1) in cells] or [w])
        rooms.append((ax, ay, w, h))
        cells.difference_update(
            (ax + dx, ay + dy) for dx in range(w) for dy in range(h)
        )
    return rooms


def normalize_level_parameters(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fill defaults and coerce types for architect-supplied level_parameters."""
    out: Dict[str, Any] = dict(params or {})
    width, height = grid_dims(out)
    out["width"], out["height"] = width, height
    out["algorithm"] = str(out.get("algorithm") or "bsp").strip().lower()
    out["min_rooms"] = _clamp_int(out.get("min_rooms"), 4, 2, 32)
    out["max_rooms"] = max(out["min_rooms"], _clamp_int(out.get("max_rooms"), 10, 2, 64))
    out["corridor_width"] = _clamp_int(out.get("corridor_width"), 1, 1, 5)
    out["enemy_density"] = _clamp_float(out.get("enemy_density"), 0.15, 0.0, 1.0)
    out["item_density"] = _clamp_float(out.get("item_density"), 0.10, 0.0, 1.0)
    out["poi_density"] = _clamp_float(out.get("poi_density"), 0.2, 0.0, 1.0)
    return out


def _clamp_float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


# ---------------------------------------------------------------------------
# Dispatch registry (populated lazily to avoid import cycles at module load)
# ---------------------------------------------------------------------------

_ALGORITHM_MODULES: Dict[str, str] = {
    "bsp": "backend.services.levelgen.bsp:generate_bsp",
    "cellular_automata": "backend.services.levelgen.cellular_automata:generate_cellular_automata",
    "caves": "backend.services.levelgen.cellular_automata:generate_cellular_automata",
    "wfc": "backend.services.levelgen.wfc:generate_wfc",
    "wave_function_collapse": "backend.services.levelgen.wfc:generate_wfc",
    "random_walk": "backend.services.levelgen.random_walk:generate_random_walk",
    "drunkards_walk": "backend.services.levelgen.random_walk:generate_random_walk",
}


class _AlgorithmRegistry(Dict[str, Callable[..., Any]]):
    """Lazy mapping name -> generator; imports the concrete module on first use."""

    def __missing__(self, key: str) -> Callable[..., Any]:
        target = _ALGORITHM_MODULES.get(key.lower())
        if target is None:
            raise KeyError(key)
        mod_name, func_name = target.split(":")
        import importlib

        func = getattr(importlib.import_module(mod_name), func_name)
        self[key.lower()] = func
        return func

    def known(self) -> List[str]:
        return sorted(set(_ALGORITHM_MODULES))


ALGORITHMS: _AlgorithmRegistry = _AlgorithmRegistry()


def generate_layout(params: Optional[Dict[str, Any]] = None, *, seed: Optional[int] = None):
    """Generate a validated, reachable LevelLayout from level_parameters.

    Raises:
        ValueError: unknown algorithm, or a generated grid that fails the
            internal start->end reachability check after retries.
    """
    from backend.schemas.agent_schemas import LevelLayout  # local import: schema-only dep

    normalized = normalize_level_parameters(params)
    algorithm = normalized["algorithm"]
    try:
        generator = ALGORITHMS[algorithm]
    except KeyError:
        raise ValueError(
            f"Unknown level generation algorithm {algorithm!r}; "
            f"supported: {', '.join(ALGORITHMS.known())}"
        ) from None

    last_error: Optional[Exception] = None
    base_seed = normalized_seed = resolve_seed({**normalized, **({"seed": seed} if seed is not None else {})})
    for attempt in range(5):
        try:
            layout: LevelLayout = generator(normalized, seed=base_seed + attempt * 7919)
        except Exception as exc:  # pragma: no cover - defensive against bad geometry
            last_error = exc
            continue
        if layout.start_room == layout.end_room:
            return layout
        if _layout_reachable(layout):
            return layout
        last_error = ValueError("generated layout is not start->end reachable")
    raise ValueError(f"level generation failed after retries ({algorithm}): {last_error}")


def _layout_reachable(layout) -> bool:
    grid = getattr(layout, "grid", None)
    if not grid:
        return True  # validators below still enforce corridor connectivity
    rooms = {r.id or f"room_{i}": r for i, r in enumerate(layout.rooms)}
    start = rooms.get(layout.start_room)
    end = rooms.get(layout.end_room)
    if start is None or end is None:
        return False
    s = cell_center((start.x, start.y, start.width, start.height))
    e = cell_center((end.x, end.y, end.width, end.height))
    return bfs_reachable(list(grid), s, e)
