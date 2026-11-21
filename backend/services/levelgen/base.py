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


def grid_shape_ok(grid: Grid, width: int, height: int) -> bool:
    """True when ``grid`` has exactly ``height`` rows of exactly ``width`` chars."""
    return len(grid) == height and all(len(row) == width for row in grid)


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
        # Maximal width along the row, then grow downwards while full rows fit.
        w = 1
        while (ax + w, ay) in cells and ax + w < width:
            w += 1
        h = 1
        while ay + h < height and all((ax + dx, ay + h) in cells for dx in range(w)):
            h += 1
        rooms.append((ax, ay, w, h))
        cells.difference_update(
            (ax + dx, ay + dy) for dx in range(w) for dy in range(h)
        )
    return rooms


# ---------------------------------------------------------------------------
# Layout assembly (shared by every algorithm module)
# ---------------------------------------------------------------------------

#: Room types recognised by ``backend.schemas.api_schemas.LevelLayoutCreate``'s
#: vocabulary and by quest-stage location references; anything else maps to
#: "generic".
KNOWN_ROOM_TYPES = ("start", "end", "boss", "treasure", "shop", "hub", "arena", "puzzle")


def assign_room_types(count: int, rng: random.Random) -> List[str]:
    """Deterministic room_type assignment: slot 0 is 'start', last is 'end'.

    Middle rooms cycle through a small thematic vocabulary so layouts stay
    readable and every room_type is unique per position (the level validator
    matches start/end against the *set* of room types).
    """
    if count <= 0:
        return []
    if count == 1:
        return ["start"]
    types = ["start"]
    specials = ["treasure", "hub", "arena", "puzzle", "shop", "boss"]
    for i in range(1, count - 1):
        types.append(specials[i % len(specials)])
    types.append("end")
    return types


def build_layout(
    *,
    algorithm: str,
    params: Dict[str, Any],
    grid: List[List[str]],
    rooms: List[RoomRect],
    corridors: List[Tuple[Tuple[int, int], Tuple[int, int], int]],
    rng: random.Random,
) -> Any:
    """Carve spawns/POIs into a real grid and assemble a LevelLayout.

    Spawn points and POI coordinates are chosen from *floor* cells inside the
    given room rectangles, so everything in the returned model refers to the
    actual carved geometry (never LLM-imagined coordinates).
    """
    from backend.schemas.agent_schemas import Corridor, LevelLayout, Room

    strings = grid_to_strings(grid)
    height = len(strings)
    width = len(strings[0]) if height else 0

    types = assign_room_types(len(rooms), rng)
    room_models = [
        Room(x=rx, y=ry, width=rw, height=rh, room_type=types[i], id=f"room_{i}")
        for i, (rx, ry, rw, rh) in enumerate(rooms)
    ]
    corridor_models = [Corridor(start=a, end=b, width=w) for a, b, w in corridors]

    floors_by_room: List[List[Tuple[int, int]]] = []
    for rx, ry, rw, rh in rooms:
        floors_by_room.append([
            (x, y)
            for y in range(max(0, ry), min(height, ry + rh))
            for x in range(max(0, rx), min(width, rx + rw))
            if strings[y][x] == FLOOR
        ])
    all_floors = [c for fl in floors_by_room for c in fl]

    def _scatter(density: float, cap: int) -> List[Tuple[int, int]]:
        if not all_floors or density <= 0.0:
            return []
        total_area = sum(rw * rh for _, _, rw, rh in rooms) or 1
        n = min(cap, max(1, int(round(density * total_area))) if density > 0 else 0)
        picked: List[Tuple[int, int]] = []
        seen: set = set()
        pool = list(all_floors)
        rng.shuffle(pool)
        it = iter(pool)
        for _ in range(n):
            try:
                cell = next(it)
            except StopIteration:
                break
            if cell not in seen:
                seen.add(cell)
                picked.append(cell)
        return sorted(picked)

    enemy_spawns = _scatter(float(params.get("enemy_density") or 0.0), cap=max(1, len(rooms) * 4))
    item_spawns = _scatter(float(params.get("item_density") or 0.0), cap=max(1, len(rooms) * 3))

    poi_names = params.get("points_of_interest") or []
    pois: List[Dict[str, Any]] = []
    if isinstance(poi_names, (list, tuple)) and poi_names and len(rooms) > 2:
        candidates = list(range(1, len(rooms) - 1))
        rng.shuffle(candidates)
        wanted = min(
            len(candidates),
            max(1, int(round(float(params.get("poi_density") or 0.2) * len(rooms)))),
            len(poi_names),
        )
        for k in range(wanted):
            idx = candidates[k]
            fl = floors_by_room[idx]
            x, y = rng.choice(fl) if fl else (rooms[idx][0], rooms[idx][1])
            name = str(poi_names[k % len(poi_names)])
            pois.append({"name": name, "x": x, "y": y, "room": types[idx]})

    start_id = room_models[0].id or "room_0"
    end_id = room_models[-1].id or f"room_{len(room_models) - 1}"
    return LevelLayout(
        algorithm=algorithm,
        width=width,
        height=height,
        rooms=room_models,
        corridors=corridor_models,
        points_of_interest=pois,
        enemy_spawn_points=enemy_spawns,
        item_spawn_points=item_spawns,
        start_room=start_id,
        end_room=end_id,
        validation_passed=False,
        grid=strings,
    )


def normalize_level_parameters(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fill defaults and coerce types for architect-supplied level_parameters.

    Accepts both naming families used across the codebase today:
    ``width``/``height`` (agent system prompt) and ``grid_width``/
    ``grid_height`` (architect fixtures); explicit ``min_room_size`` /
    ``max_room_size`` pairs are honoured as [w, h] lists or scalars.
    """
    out: Dict[str, Any] = dict(params or {})
    width, height = grid_dims(out)
    out["width"], out["height"] = width, height
    out["algorithm"] = str(out.get("algorithm") or "bsp").strip().lower()
    if out["algorithm"] == "dungeon_rooms":  # legacy alias from older IR fixtures
        out["algorithm"] = "bsp"
    out["theme"] = str(out.get("theme") or "generic")
    out["min_rooms"] = _clamp_int(out.get("min_rooms"), 4, 2, 32)
    out["max_rooms"] = max(out["min_rooms"], _clamp_int(out.get("max_rooms"), 10, 2, 64))
    out["corridor_width"] = _clamp_int(out.get("corridor_width"), 1, 1, 5)
    out["min_room_size"] = _pair(out.get("min_room_size"), default=(4, 4), lo=2)
    out["max_room_size"] = _pair(out.get("max_room_size"), default=(None, None), lo=2)
    # Keep the max at least as large as the min on each axis.
    mx, my = out["max_room_size"]
    nx, ny = out["min_room_size"]
    out["max_room_size"] = (max(mx, nx), max(my, ny))
    out["enemy_density"] = _clamp_float(out.get("enemy_density"), 0.15, 0.0, 1.0)
    out["item_density"] = _clamp_float(out.get("item_density"), 0.10, 0.0, 1.0)
    out["poi_density"] = _clamp_float(out.get("poi_density"), 0.2, 0.0, 1.0)
    pois = out.get("points_of_interest")
    out["points_of_interest"] = list(pois) if isinstance(pois, (list, tuple)) else []
    return out


def _pair(value: Any, default: Tuple[Any, Any], lo: int) -> Tuple[int, int]:
    """Coerce a scalar, [w, h] list/tuple, or {'x','y'} dict into an (int, int) pair."""
    d0, d1 = default
    if value is None:
        a, b = d0, d1
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        a, b = value[0], value[1]
    elif isinstance(value, dict):
        a, b = value.get("x", d0), value.get("y", d1)
    else:
        a = b = value
    return (_clamp_int(a, d0 if d0 is not None else lo, lo, MAX_GRID_DIM),
            _clamp_int(b, d1 if d1 is not None else lo, lo, MAX_GRID_DIM))


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


def layout_from_parameters(layout, params: Optional[Dict[str, Any]] = None, *, seed: Optional[int] = None):
    """Coerce a raw (typically LLM-proposed) LevelLayout into real geometry.

    The LLM only *chooses parameters*; the actual grid/rooms/corridors/spawns
    are regenerated deterministically by :func:`generate_layout` using the
    proposed algorithm/dimensions plus ``params['seed']`` (or an explicit
    ``seed`` argument). Room types, corridor endpoints and spawn coordinates
    in the input are treated as hints and replaced by carved geometry.

    Raises whatever :func:`generate_layout` raises when the requested
    algorithm is unknown or no reachable layout can be produced.
    """
    merged: Dict[str, Any] = {}
    if params:
        merged.update(params)
    merged["algorithm"] = getattr(layout, "algorithm", None) or merged.get("algorithm") or "bsp"
    merged.setdefault("width", getattr(layout, "width", DEFAULT_WIDTH))
    merged.setdefault("height", getattr(layout, "height", DEFAULT_HEIGHT))
    merged.setdefault(
        "points_of_interest",
        [poi.get("name", str(poi)) for poi in getattr(layout, "points_of_interest", []) or []],
    )
    if seed is not None:
        merged["seed"] = seed
    return generate_layout(merged, seed=seed)


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
    base_seed = resolve_seed({**normalized, **({"seed": seed} if seed is not None else {})})
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
    if not grid or not grid_shape_ok(list(grid), layout.width, layout.height):
        return False  # a real layout must ship a well-shaped grid
    rooms = {r.id or f"room_{i}": r for i, r in enumerate(layout.rooms)}
    start = rooms.get(layout.start_room)
    end = rooms.get(layout.end_room)
    if start is None or end is None:
        return False
    s = cell_center((start.x, start.y, start.width, start.height))
    e = cell_center((end.x, end.y, end.width, end.height))
    return bfs_reachable(list(grid), s, e)
