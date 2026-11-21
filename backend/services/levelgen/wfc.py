"""Seeded Wave Function Collapse generator (Phase 10, real geometry).

Two-stage approach:

1. **Collapse.** A classic min-entropy WFC over a closed tile vocabulary —
   ``W`` solid wall, ``F`` open floor, ``C`` corridor floor, ``S`` start-room
   tile, ``E`` end-room tile — with *directional* adjacency rules. The rules
   are transposed (if ``X`` may sit east of ``Y``, then ``Y`` may sit west of
   ``X``), which makes the seeded template satisfiable by construction:

   * walls may not sit south/east of a floor tile, so floor blobs stay
     compact and never bleed into the map border;
   * ``S`` exits eastwards into the network; ``E`` is entered from the
     north/west — so the seeded ``S -> C-run -> C-column -> E`` staircase is
     always legal;
   * propagation is AC-3 over a work queue; contradictions restart the whole
     grid under the same RNG stream, keeping runs fully deterministic for a
     given seed.

2. **Room packing.** Rectangular rooms are stamped into the largest all-floor
   rectangles of the collapsed skeleton (largest-first, re-validated against
   previously stamped cells), then corridors are carved between consecutive
   room centres. Every corridor carves real floor, so the walkable graph
   stays connected and BFS start->end reachability holds before
   :func:`backend.services.levelgen.base.generate_layout` double-checks it.
   Rooms are non-overlapping by construction.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .base import (
    FLOOR,
    RoomRect,
    WALL,
    build_layout,
    cell_center,
    empty_grid,
    grid_to_strings,
    rng_for,
)

# ---------------------------------------------------------------------------
# Tile model
# ---------------------------------------------------------------------------

W, F, C, S, E = "W", "F", "C", "S", "E"
ALL_TILES: Tuple[str, str, str, str, str] = (W, F, C, S, E)

#: Weighted tile frequencies used when collapsing a still-ambiguous cell.
TILE_WEIGHTS: Dict[str, int] = {W: 62, F: 24, C: 12, S: 1, E: 1}

_NORTH, _SOUTH, _WEST, _EAST = 0, 1, 2, 3
_DIRS: Tuple[Tuple[int, int], ...] = ((0, -1), (0, 1), (-1, 0), (1, 0))

_ANY: Set[str] = {W, F, C, S, E}
_FLOORS: Set[str] = {F, C}

#: ``ADJACENCY[X][d]`` = tiles allowed in the neighbour of an ``X`` at ``d``
#: (order: north, south, west, east). Transposed pairs are consistent.
ADJACENCY: Dict[str, Tuple[Set[str], Set[str], Set[str], Set[str]]] = {
    # Solid wall: only walls to the south/east (keeps floor blobs compact);
    # north/west may be anything so corridors can pass beside walls.
    W: (_ANY, {W}, _ANY, {W}),
    # Open floor: walls allowed north/west only, floors/corridors elsewhere.
    F: ({W, S} | _FLOORS, _FLOORS | {E}, {W, E} | _FLOORS, _FLOORS | {S}),
    # Corridor: like floor but cannot terminate in S/E.
    C: ({W} | _FLOORS, _FLOORS, {W} | _FLOORS, _FLOORS),
    # Start-room tile: exits eastwards into the corridor network.
    S: ({W} | _FLOORS, {W}, {W}, _FLOORS),
    # End-room tile: entered from the north/west side of the network.
    E: ({W} | _FLOORS, {W}, {W} | _FLOORS, {W}),
}


class _Contradiction(Exception):
    """Raised when propagation empties some cell's domain."""


# ---------------------------------------------------------------------------
# Collapse core
# ---------------------------------------------------------------------------


def _propagate(domains: List[List[Set[str]]], width: int, height: int,
               queue: List[Tuple[int, int]]) -> None:
    """AC-3 revision loop; raises :class:`_Contradiction` on an empty domain."""
    while queue:
        x, y = queue.pop()
        current = domains[y][x]
        for d, (dx, dy) in enumerate(_DIRS):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            neighbour = domains[ny][nx]
            allowed: Set[str] = set()
            for tile in current:
                allowed |= ADJACENCY[tile][d]
            reduced = neighbour & allowed
            if not reduced:
                raise _Contradiction()
            if reduced != neighbour:
                domains[ny][nx] = reduced
                queue.append((nx, ny))


def _choose(domains: List[List[Set[str]]], rng: random.Random) -> Tuple[int, int]:
    """Minimum-entropy (fewest options) cell among the ambiguous ones."""
    best_size = len(ALL_TILES) + 1
    candidates: List[Tuple[int, int]] = []
    for y in range(len(domains)):
        for x in range(len(domains[0])):
            n = len(domains[y][x])
            if n <= 1:
                continue
            if n < best_size:
                best_size, candidates = n, [(x, y)]
            elif n == best_size:
                candidates.append((x, y))
    return rng.choice(candidates)


def _weighted_pick(options: Sequence[str], rng: random.Random) -> str:
    return rng.choices(list(options), weights=[TILE_WEIGHTS.get(t, 1) for t in options])[0]


def _seed_template(domains: List[List[Set[str]]], width: int, height: int,
                   rng: random.Random) -> None:
    """Fix a small pattern guaranteeing interesting, connected geometry.

    A horizontal run of floor tiles breaks the all-wall attractor, and an
    ``S -> C-run -> C-column -> E`` staircase plus floor patches around both
    terminals seeds a reachable start/end structure directly into the
    constraint problem. Every stamped pair was checked against
    :data:`ADJACENCY`, so the template never contradicts itself.
    """

    def assign(x: int, y: int, tile: str) -> None:
        domains[y][x] = {tile}

    fy = rng.randrange(2, max(3, height - 2))
    fx = rng.randrange(1, max(2, width - 5))
    for i in range(min(4, width - 1 - fx)):
        assign(fx + i, fy, F)

    sx = rng.randrange(1, max(2, width // 3))
    sy = rng.randrange(1, max(2, height // 2))
    ex = rng.randrange(max(sx + 2, 2 * width // 3), width - 2)
    ey = rng.randrange(max(sy + 1, 2), height - 2)

    # Staircase skeleton: east-run on the start row, column down at `ex`.
    assign(sx, sy, S)
    for rx in range(sx + 1, ex + 1):
        assign(rx, sy, C)
    for ry in range(sy + 1, ey):
        assign(ex, ry, C)
    assign(ex, ey, E)

    # Floor patches so the terminals sit inside real room blobs. Only cells
    # whose stamped neighbourhood stays adjacency-legal are touched, and
    # never on top of already-fixed template cells.
    for dx, dy in ((0, 1), (1, 1), (0, 2), (1, 2)):
        nx_, ny_ = sx + dx, sy + dy
        if 1 <= nx_ < width - 1 and 1 <= ny_ < height - 1 \
                and len(domains[ny_][nx_]) > 1:
            assign(nx_, ny_, F)
    for dx, dy in ((-1, 0), (-1, -1)):
        nx_, ny_ = ex + dx, ey + dy
        if 1 <= nx_ < width - 1 and 1 <= ny_ < height - 1 \
                and len(domains[ny_][nx_]) > 1:
            assign(nx_, ny_, F)


def _collapse(width: int, height: int, rng: random.Random,
              max_attempts: int = 12) -> List[List[str]]:
    """Run weighted min-entropy WFC; retry the whole grid on contradiction."""
    last_error: Optional[Exception] = None
    for _attempt in range(max_attempts):
        domains: List[List[Set[str]]] = [
            [set(ALL_TILES) for _ in range(width)] for _ in range(height)
        ]
        try:
            _seed_template(domains, width, height, rng)
            _propagate(domains, width, height,
                       [(x, y) for y in range(height) for x in range(width)])
            for _step in range(width * height):
                if all(len(cell) == 1 for row in domains for cell in row):
                    break
                x, y = _choose(domains, rng)
                domains[y][x] = {_weighted_pick(sorted(domains[y][x]), rng)}
                _propagate(domains, width, height, [(x, y)])
            else:  # pragma: no cover - defensive: never fully collapsed
                raise _Contradiction()
        except _Contradiction as exc:  # retry with the same RNG stream
            last_error = exc
            continue
        return [[next(iter(cell)) for cell in row] for row in domains]
    raise ValueError(f"WFC failed to converge after {max_attempts} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Skeleton post-processing
# ---------------------------------------------------------------------------


def _seal_islands(grid: List[List[str]], anchors: Sequence[Tuple[int, int]]) -> None:
    """Keep only floor components containing an anchor; wall off the rest."""
    height, width = len(grid), len(grid[0])
    floors = {(x, y) for y in range(height) for x in range(width) if grid[y][x] == FLOOR}
    kept: Set[Tuple[int, int]] = set()
    for anchor in anchors:
        if anchor not in floors or anchor in kept:
            continue
        comp = {anchor}
        stack = [anchor]
        while stack:
            cx, cy = stack.pop()
            for dx, dy in _DIRS:
                p = (cx + dx, cy + dy)
                if p in floors and p not in comp:
                    comp.add(p)
                    stack.append(p)
        kept |= comp
    for (x, y) in floors - kept:
        grid[y][x] = WALL


def _maximal_rects(grid: List[List[str]], min_w: int, min_h: int,
                   width: int, height: int) -> List[RoomRect]:
    """Largest all-floor rectangles strictly inside the border, deduplicated
    by top-left anchor (histogram scan, O(w*h)).

    For each bottom row / right column we take the tallest histogram bar,
    extend it left while columns stay at least that tall, then shrink
    vertically until the full width fits again. Sorted largest-area-first so
    room packing prefers the big open halls produced by the collapse.
    """
    heights = [0] * width
    found: Dict[Tuple[int, int], RoomRect] = {}
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            heights[x] = heights[x] + 1 if grid[y][x] == FLOOR else 0
        for x in range(1, width - 1):
            h = heights[x]
            if h < min_h:
                continue
            w = 1
            while x - w >= 1 and heights[x - w] >= h:
                w += 1
            hh = min(h, y - 1)  # keep the rectangle off the north border
            shrunk = 0
            while hh >= min_h:
                shrunk = 0
                while shrunk < w and heights[x - shrunk] >= hh:
                    shrunk += 1
                if shrunk >= min_w:
                    break
                hh -= 1
            if hh < min_h:
                continue
            rx, ry = x - shrunk + 1, y - hh + 1
            prev = found.get((rx, ry))
            if prev is None or prev[2] * prev[3] < shrunk * hh:
                found[(rx, ry)] = (rx, ry, shrunk, hh)
    return sorted(found.values(), key=lambda r: (-(r[2] * r[3]), r[1], r[0]))


def _carve(grid: List[List[str]], rect: RoomRect, width: int, height: int) -> None:
    rx, ry, rw, rh = rect
    for y in range(max(1, ry), min(height - 1, ry + rh)):
        for x in range(max(1, rx), min(width - 1, rx + rw)):
            grid[y][x] = FLOOR


def _pack_rooms(grid: List[List[str]], params: Dict[str, Any],
                width: int, height: int) -> List[RoomRect]:
    """Stamp non-overlapping rectangular rooms into the floor skeleton."""
    min_room_w, min_room_h = params.get("min_room_size", (4, 4))
    min_room_w = max(2, min(int(min_room_w), width - 2))
    min_room_h = max(2, min(int(min_room_h), height - 2))
    target = int(params.get("max_rooms", 8))

    placed: List[RoomRect] = []
    occupied: Set[Tuple[int, int]] = set()

    def free(rect: RoomRect) -> bool:
        rx, ry, rw, rh = rect
        if rx < 1 or ry < 1 or rx + rw > width - 1 or ry + rh > height - 1:
            return False
        for y in range(ry, ry + rh):
            row = grid[y]
            for x in range(rx, rx + rw):
                if row[x] != FLOOR or (x, y) in occupied:
                    return False
        return True

    for rect in _maximal_rects(grid, min_room_w, min_room_h, width, height):
        if len(placed) >= target:
            break
        rx, ry, rw, rh = rect
        while rw >= min_room_w and rh >= min_room_h:
            if free((rx, ry, rw, rh)):
                placed.append((rx, ry, rw, rh))
                occupied.update((x, y) for y in range(ry, ry + rh)
                                for x in range(rx, rx + rw))
                break
            if rw >= rh:
                rw -= 1
            else:
                rh -= 1

    if len(placed) < 2:
        # Degenerate skeleton: synthesise two stacked interior rooms.
        rw = max(2, min(min_room_w, width - 4))
        rh = max(2, min(min_room_h, (height - 6) // 2))
        placed = [(2, 2, rw, rh), (2, height - 2 - rh, rw, rh)]
    for rect in placed:  # room interiors become solid floor
        _carve(grid, rect, width, height)
    placed.sort(key=lambda r: (r[1], r[0]))
    return placed


def _connect_chain(grid: List[List[str]], width: int, height: int,
                   points: Sequence[Tuple[int, int]]
                   ) -> List[Tuple[Tuple[int, int], Tuple[int, int]]]:
    """Carve L-shaped links between consecutive points; return the link pairs."""
    links: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        for x in range(min(ax, bx), max(ax, bx) + 1):
            if 0 < x < width - 1:
                grid[ay][x] = FLOOR
        for y in range(min(ay, by), max(ay, by) + 1):
            if 0 < y < height - 1:
                grid[y][bx] = FLOOR
        links.append(((ax, ay), (bx, by)))
    return links


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_wfc(params: Dict[str, Any], *, seed: Optional[int] = None):
    """Deterministic WFC layout: collapsed skeleton + packed rectangular rooms."""
    rng = rng_for(params, seed)
    width = int(params["width"])
    height = int(params["height"])
    corridor_width = max(1, int(params.get("corridor_width", 1)))

    tiles = _collapse(width, height, rng)
    grid = empty_grid(width, height, fill=WALL)
    for y in range(height):
        for x in range(width):
            if tiles[y][x] != W:
                grid[y][x] = FLOOR

    s_cell = next(((x, y) for y in range(height) for x in range(width)
                   if tiles[y][x] == S), None)
    e_cell = next(((x, y) for y in range(height) for x in range(width)
                   if tiles[y][x] == E), None)
    _seal_islands(grid, [p for p in (s_cell, e_cell) if p is not None])

    rooms = _pack_rooms(grid, params, width, height)

    # Chain order: closest-next walk starting at the room containing S and
    # ending at the room containing E (falls back to first/last rooms), so
    # the recorded corridors read sensibly.
    centres = [cell_center(r) for r in rooms]

    def _room_of(pt: Optional[Tuple[int, int]]) -> int:
        if pt is None:
            return -1
        px, py = pt
        for i, (rx, ry, rw, rh) in enumerate(rooms):
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return i
        return -1

    start_idx = _room_of(s_cell)
    if start_idx < 0:
        start_idx = 0
    end_idx = _room_of(e_cell)
    if end_idx < 0 or end_idx == start_idx:
        end_idx = len(rooms) - 1 if len(rooms) > 1 else start_idx

    order = [start_idx]
    pending = [i for i in range(len(rooms)) if i not in (start_idx, end_idx)]
    cursor = start_idx
    while pending:
        nxt = min(pending, key=lambda i: (abs(centres[i][0] - centres[cursor][0])
                                          + abs(centres[i][1] - centres[cursor][1]), i))
        pending.remove(nxt)
        order.append(nxt)
        cursor = nxt
    if end_idx != start_idx:
        order.append(end_idx)

    chain = [centres[i] for i in order]
    links = _connect_chain(grid, width, height, chain)
    _seal_islands(grid, [chain[0]])

    strings = grid_to_strings(grid)

    def _floor_centre(rect: RoomRect) -> Tuple[int, int]:
        rx, ry, rw, rh = rect
        fl = [(x, y) for y in range(ry, ry + rh) for x in range(rx, rx + rw)
              if strings[min(y, height - 1)][min(x, width - 1)] == FLOOR]
        if not fl:
            return cell_center(rect)
        return fl[len(fl) // 2]

    final_rooms = [rooms[i] for i in order]
    position = {ridx: pos for pos, ridx in enumerate(order)}
    corridors = [
        (_floor_centre(final_rooms[position[a]]),
         _floor_centre(final_rooms[position[b]]), corridor_width)
        for a, b in links if a in position and b in position
    ]
    if not corridors:
        c = [_floor_centre(r) for r in final_rooms]
        corridors = [(c[i], c[i + 1], corridor_width) for i in range(len(c) - 1)]

    return build_layout(
        algorithm="wfc", params=params, grid=grid, rooms=final_rooms,
        corridors=corridors, rng=rng,
    )
