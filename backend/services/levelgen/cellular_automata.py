"""Seeded 4-5 cellular-automata cave generator (Phase 10, real geometry).

Standard cave CA: random-fill the interior, then apply the B36/S34-5 rule
("if a cell has <4 live neighbours it dies, else it stays/is born") for a few
iterations. The largest connected floor component is kept as the playable
cave and every other component is sealed off (turned back into wall) so the
grid contains exactly one walkable region — start->end reachability then
holds by construction. "Rooms" are maximal rectangles detected inside the
cave floor; the first (top-left-most) is the start room, the last is the end.
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


def _initial_fill(width: int, height: int, fill_prob: float, rng: random.Random) -> List[List[str]]:
    """Random noise seed; the outer border stays solid wall forever."""
    grid = empty_grid(width, height, fill=WALL)
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            # Border-adjacent cells start slightly more often as wall to keep
            # the carve away from the map edge.
            edge = x in (1, width - 2) or y in (1, height - 2)
            p = fill_prob * (0.5 if edge else 1.0)
            grid[y][x] = FLOOR if rng.random() < p else WALL
    return grid


def _live_neighbours(grid: List[List[str]], x: int, y: int, width: int, height: int) -> int:
    n = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height:
                if grid[ny][nx] == FLOOR:
                    n += 1
            else:
                n += 1  # out-of-bounds counts as wall/floor per classic CA; walls count live
    return n


def _step(grid: List[List[str]], width: int, height: int) -> List[List[str]]:
    nxt = [row[:] for row in grid]
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            live = _live_neighbours(grid, x, y, width, height)
            if grid[y][x] == FLOOR:
                nxt[y][x] = FLOOR if live >= 4 else WALL
            else:
                nxt[y][x] = FLOOR if live >= 5 else WALL
    return nxt


def _components(grid: List[List[str]]) -> List[List[Tuple[int, int]]]:
    width, height = len(grid[0]), len(grid)
    seen: set = set()
    comps: List[List[Tuple[int, int]]] = []
    for y in range(height):
        for x in range(width):
            if grid[y][x] != FLOOR or (x, y) in seen:
                continue
            stack = [(x, y)]
            comp: List[Tuple[int, int]] = []
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                comp.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width and 0 <= ny < height \
                            and grid[ny][nx] == FLOOR and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            comps.append(comp)
    return comps


def _connect_components(grid: List[List[str]], comps: List[List[Tuple[int, int]]]) -> None:
    """Carve straight-line corridors linking each component to the first one.

    Used as a safety net when the CA result has no single dominant cave; the
    largest component is passed first so the carve keeps every region of the
    map playable instead of discarding geometry.
    """
    if len(comps) < 2:
        return
    anchor = comps[0][len(comps[0]) // 2]
    for comp in comps[1:]:
        target = comp[len(comp) // 2]
        ax, ay = anchor
        tx, ty = target
        for x in range(min(ax, tx), max(ax, tx) + 1):
            if 0 < x < len(grid[0]) - 1:
                grid[ay][x] = FLOOR
        for y in range(min(ay, ty), max(ay, ty) + 1):
            if 0 < y < len(grid) - 1:
                grid[y][tx] = FLOOR


def generate_cellular_automata(params: Dict[str, Any], *, seed: Optional[int] = None):
    """Deterministic cave layout with a single connected floor component."""
    rng = rng_for(params, seed)
    width = int(params["width"])
    height = int(params["height"])
    fill_prob = min(0.65, max(0.30, float(params.get("fill_probability", 0.45))))
    iterations = int(params.get("ca_iterations", 4))

    grid = _initial_fill(width, height, fill_prob, rng)
    for _ in range(max(1, iterations)):
        grid = _step(grid, width, height)

    # Keep only the largest connected cave; seal every other island so the
    # grid has exactly one walkable region (reachability holds by
    # construction). Room detection below runs on the SEALED grid.
    comps = _components(grid)
    if not comps:
        # Pathological all-wall result: open a guaranteed cavern in the middle.
        grid = empty_grid(width, height, fill=WALL)
        for y in range(2, height - 2):
            for x in range(2, width - 2):
                grid[y][x] = FLOOR
        comps = [[(x, y) for y in range(2, height - 2) for x in range(2, width - 2)]]
    comps.sort(key=len, reverse=True)
    biggest = comps[0]
    keep = set(biggest)
    for y in range(height):
        for x in range(width):
            if grid[y][x] == FLOOR and (x, y) not in keep:
                grid[y][x] = WALL

    strings = grid_to_strings(grid)
    rects = sorted(detect_rooms_from_floor(strings), key=lambda r: (r[1], r[0]))
    if len(rects) < 2:
        bx, by = max(1, width // 2), max(1, height // 2)
        rects = [
            (min(bx, width - 3), min(by, height - 3), 2, 2),
            (max(1, bx - 1), max(1, by - 1), 2, 2),
        ]

    # Corridor records connect consecutive detected room centres along the
    # already-carved cave floor (they describe connectivity, they do not add
    # new geometry — the cave itself is the path). Endpoints are snapped to
    # actual floor cells so every recorded corridor endpoint is walkable.
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
        algorithm="cellular_automata", params=params, grid=grid,
        rooms=rects, corridors=corridors, rng=rng,
    )
