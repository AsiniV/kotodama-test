"""Seeded drunkard's-random-walk generator (Phase 10, real geometry).

Classic cave carving: one or more walkers start near the grid centre and take
``steps`` axis-aligned steps of ``step_length`` tiles each, painting every
visited cell floor. The walk is a single connected trace by construction; any
extra walkers are joined to the first trace with straight L-shaped corridors,
and all remaining disconnected pockets are sealed back to wall so the grid
contains exactly one walkable region.

"Rooms" are maximal rectangles detected inside the carved floor
(:func:`backend.services.levelgen.base.detect_rooms_from_floor`), sorted
top-to-bottom / left-to-right: the first becomes ``room_0`` (start) and the
last the end room. Corridor records describe connectivity along the already
carved floor (endpoints snapped to real floor cells), mirroring the cellular
automata module. BFS start->end reachability therefore holds before
:func:`backend.services.levelgen.base.generate_layout` double-checks it.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    FLOOR,
    RoomRect,
    WALL,
    build_layout,
    detect_rooms_from_floor,
    empty_grid,
    grid_to_strings,
    rng_for,
)

_DIRS: Tuple[Tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _walk(grid: List[List[str]], start: Tuple[int, int], steps: int,
          step_length: int, width: int, height: int, rng: random.Random) -> None:
    """Carve one drunkard's trail from ``start``, clamped to the interior."""
    x, y = start
    grid[y][x] = FLOOR
    for _ in range(steps):
        dx, dy = _DIRS[rng.randrange(4)]
        nx = min(max(1, x + dx * step_length), width - 2)
        ny = min(max(1, y + dy * step_length), height - 2)
        # Paint the whole segment between the two cells (not just the target)
        # so single-tile steps still dig tunnels instead of dotted trails.
        if dx:
            for cx in range(min(x, nx), max(x, nx) + 1):
                grid[y][cx] = FLOOR
        else:
            for cy in range(min(y, ny), max(y, ny) + 1):
                grid[cy][x] = FLOOR
        grid[ny][nx] = FLOOR
        x, y = nx, ny


def _components(grid: List[List[str]]) -> List[List[Tuple[int, int]]]:
    w, h = len(grid[0]), len(grid)
    seen: set = set()
    comps: List[List[Tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            if grid[y][x] != FLOOR or (x, y) in seen:
                continue
            stack = [(x, y)]
            comp: List[Tuple[int, int]] = []
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                comp.append((cx, cy))
                for dx, dy in _DIRS:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and grid[ny][nx] == FLOOR \
                            and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            comps.append(comp)
    return comps


def _seal_except_main(grid: List[List[str]]) -> None:
    """Keep only the largest floor component; wall off every pocket."""
    comps = _components(grid)
    if len(comps) < 2:
        return
    biggest = max(comps, key=len)
    keep = set(biggest)
    for comp in comps:
        if comp is biggest:
            continue
        for (x, y) in comp:
            grid[y][x] = WALL


def _connect(grid: List[List[str]], a: Tuple[int, int], b: Tuple[int, int]) -> None:
    """Carve an L-shaped link between two floor cells (interior-clamped)."""
    height, width = len(grid), len(grid[0])
    ax, ay = a
    bx, by = b
    for x in range(min(ax, bx), max(ax, bx) + 1):
        if 0 < x < width - 1:
            grid[ay][x] = FLOOR
    for y in range(min(ay, by), max(ay, by) + 1):
        if 0 < y < height - 1:
            grid[y][bx] = FLOOR


def generate_random_walk(params: Dict[str, Any], *, seed: Optional[int] = None):
    """Deterministic drunkard's-carver layout with rooms found in the floor."""
    rng = rng_for(params, seed)
    width = int(params["width"])
    height = int(params["height"])

    area = width * height
    total_steps = max(80, int(params.get("walk_steps") or area // 3))
    step_length = max(1, min(4, int(params.get("walk_step_length") or 2)))
    # More walkers on bigger grids so the carve covers the map with several
    # distinct halls instead of one long snaking tunnel.
    walkers = max(1, min(6, int(params.get("walkers") or area // 900 + 1)))

    grid = empty_grid(width, height, fill=WALL)
    starts: List[Tuple[int, int]] = []
    for i in range(walkers):
        sx = rng.randrange(max(2, width // 4), max(3, 3 * width // 4))
        sy = rng.randrange(max(2, height // 4), max(3, 3 * height // 4))
        starts.append((sx, sy))
        _walk(grid, (sx, sy), max(40, total_steps // walkers), step_length,
              width, height, rng)

    # Join all walker traces into one component, then seal leftover pockets.
    for prev, nxt in zip(starts, starts[1:]):
        _connect(grid, prev, nxt)
    _seal_except_main(grid)

    strings = grid_to_strings(grid)
    rects = sorted(detect_rooms_from_floor(strings), key=lambda r: (r[1], r[0]))
    if len(rects) < 2:
        bx, by = max(1, width // 2), max(1, height // 2)
        rects = [
            (min(bx, width - 3), min(by, height - 3), 2, 2),
            (max(1, bx - 1), max(1, by - 1), 2, 2),
        ]

    def centre(r: RoomRect) -> Tuple[int, int]:
        rx, ry, rw, rh = r
        fl = [(x, y) for y in range(ry, ry + rh) for x in range(rx, rx + rw)
              if strings[min(y, height - 1)][min(x, width - 1)] == FLOOR]
        if not fl:
            return rx + rw // 2, ry + rh // 2
        xs = sorted(p[0] for p in fl)
        ys = sorted(p[1] for p in fl)
        cand = (xs[len(xs) // 2], ys[len(ys) // 2])
        if strings[cand[1]][cand[0]] == FLOOR:
            return cand
        return fl[len(fl) // 2]

    corridors = [(centre(a), centre(b), 1) for a, b in zip(rects, rects[1:])]

    return build_layout(
        algorithm="random_walk", params=params, grid=grid,
        rooms=rects, corridors=corridors, rng=rng,
    )
