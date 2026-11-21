"""Seeded Binary Space Partitioning generator (Phase 10, real geometry).

Classic dungeon BSP: recursively split the grid into leaf partitions, place
one non-overlapping room inside each leaf, connect sibling partitions with L-
shaped corridors carved into the *same* grid. Because every corridor is
carved between two rooms of the two sub-partitions it joins, the resulting
floor graph is connected by construction; ``generate_layout`` in ``base``
still double-checks start->end reachability with BFS before returning.

Room order is deterministic: leaves are sorted top-to-bottom, left-to-right,
so ``room_0`` is the top-left-most room (start) and the last one is the
bottom-right-most (end).
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    FLOOR,
    RoomRect,
    build_layout,
    carve_rect,
    cell_center,
    empty_grid,
    rng_for,
)

Node = Tuple[Tuple[int, int, int, int], Optional["Node"], Optional["Node"]]


def _split(rect: RoomRect, rng: random.Random, min_size: Tuple[int, int]) -> Optional[Tuple[RoomRect, RoomRect]]:
    """Split a partition horizontally or vertically when there is room for it."""
    x, y, w, h = rect
    can_split_v = w >= 2 * (min_size[0] + 1)
    can_split_h = h >= 2 * (min_size[1] + 1)
    if not (can_split_v or can_split_h):
        return None
    if can_split_v and can_split_h:
        horizontal = rng.random() < (h / (w + h))
    else:
        horizontal = can_split_h
    if horizontal:
        lo = min_size[1]
        hi = h - min_size[1]
        cut = rng.randrange(lo, hi)
        return (x, y, w, cut), (x, y + cut, w, h - cut)
    lo = min_size[0]
    hi = w - min_size[0]
    cut = rng.randrange(lo, hi)
    return (x, y, cut, h), (x + cut, y, w - cut, h)


def _bsp_tree(rect: RoomRect, depth: int, max_depth: int, rng: random.Random,
              min_size: Tuple[int, int]) -> Node:
    if depth >= max_depth:
        return (rect, None, None)
    split = _split(rect, rng, min_size)
    if split is None:
        return (rect, None, None)
    a, b = split
    return (
        rect,
        _bsp_tree(a, depth + 1, max_depth, rng, min_size),
        _bsp_tree(b, depth + 1, max_depth, rng, min_size),
    )


def _leaves(node: Node) -> List[RoomRect]:
    _, left, right = node
    if left is None and right is None:
        return [node[0]]
    out: List[RoomRect] = []
    for child in (left, right):
        if child is not None:
            out.extend(_leaves(child))
    return out


def _rooms_of(node: Node, room_map: Dict[RoomRect, RoomRect]) -> List[RoomRect]:
    _, left, right = node
    if left is None and right is None:
        r = room_map.get(node[0])
        return [r] if r else []
    out: List[RoomRect] = []
    for child in (left, right):
        if child is not None:
            out.extend(_rooms_of(child, room_map))
    return out


def _carve_corridor(grid: List[List[str]], a: Tuple[int, int], b: Tuple[int, int],
                    width: int, rng: random.Random) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Carve an L-shaped corridor (H-then-V or V-then-H) between cells a and b.

    The bend is jittered along the first axis so parallel corridors between
    neighbouring partitions do not perfectly overlap into one wide blob.
    """
    height = len(grid)
    gw = len(grid[0]) if height else 0
    half = max(0, (width - 1) // 2)

    def h_line(y: int, x0: int, x1: int) -> None:
        for gy in range(max(1, y - half), min(height - 1, y + half + 1)):
            for gx in range(max(1, min(x0, x1)), min(gw - 1, max(x0, x1) + 1)):
                grid[gy][gx] = FLOOR

    def v_line(x: int, y0: int, y1: int) -> None:
        for gx in range(max(1, x - half), min(gw - 1, x + half + 1)):
            for gy in range(max(1, min(y0, y1)), min(height - 1, max(y0, y1) + 1)):
                grid[gy][gx] = FLOOR

    ax, ay = a
    bx, by = b
    bend_x = rng.randint(min(ax, bx), max(ax, bx))
    bend_y = rng.randint(min(ay, by), max(ay, by))
    if rng.random() < 0.5:
        h_line(ay, ax, bend_x)
        v_line(bend_x, ay, by)
        h_line(by, bend_x, bx)
    else:
        v_line(ax, ay, bend_y)
        h_line(bend_y, ax, bx)
        v_line(bx, bend_y, by)
    return a, b


def generate_bsp(params: Dict[str, Any], *, seed: Optional[int] = None):
    """Deterministic BSP layout: non-overlapping rooms joined by carved corridors."""
    rng = rng_for(params, seed)
    width = int(params["width"])
    height = int(params["height"])
    min_room_w, min_room_h = params.get("min_room_size", (4, 4))
    max_room_w, max_room_h = params.get("max_room_size") or (None, None)
    max_room_w = min(max_room_w or max(6, width // 4), max(width - 4, min_room_w))
    max_room_h = min(max_room_h or max(6, height // 4), max(height - 4, min_room_h))
    corridor_width = int(params.get("corridor_width", 1))
    target_rooms = int(params.get("max_rooms", 8))

    # Depth chosen so the partition count brackets the requested room count.
    lo_depth = max(1.0, math.log2(max(2, int(params.get("min_rooms", 4)))))
    hi_depth = max(lo_depth, math.log2(max(2, target_rooms)))
    max_depth = max(1, min(7, int(round(rng.uniform(lo_depth, hi_depth)))))

    root: Node = _bsp_tree((0, 0, width, height), 0, max_depth, rng, (min_room_w, min_room_h))
    leaves = sorted(_leaves(root), key=lambda r: (r[1], r[0]))

    grid = empty_grid(width, height)
    rects: List[RoomRect] = []
    room_map: Dict[RoomRect, RoomRect] = {}
    for lx, ly, lw, lh in leaves:
        rw = rng.randint(min_room_w, max(min_room_w, min(lw - 2, max_room_w)))
        rh = rng.randint(min_room_h, max(min_room_h, min(lh - 2, max_room_h)))
        if rw < 2 or rh < 2:
            continue
        rx = lx + rng.randint(1, max(1, lw - rw - 1))
        ry = ly + rng.randint(1, max(1, lh - rh - 1))
        room = (rx, ry, rw, rh)
        carve_rect(grid, room)
        rects.append(room)
        room_map[(lx, ly, lw, lh)] = room

    # Connect sibling partitions bottom-up; guarantees a connected floor graph.
    corridors: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []

    def connect(node: Node) -> None:
        _, left, right = node
        if left is None or right is None:
            return
        connect(left)
        connect(right)
        la = _rooms_of(left, room_map)
        ra = _rooms_of(right, room_map)
        if not la or not ra:
            return
        a = cell_center(rng.choice(la))
        b = cell_center(rng.choice(ra))
        corridors.append(_carve_corridor(grid, a, b, corridor_width, rng))

    connect(root)

    if len(rects) < 2:  # degenerate tiny grids: fall back to two stacked rooms
        grid = empty_grid(width, height)
        rects = [(2, 2, max(3, width // 4), max(3, height // 4)),
                 (width - 2 - max(3, width // 4), height - 2 - max(3, height // 4),
                  max(3, width // 4), max(3, height // 4))]
        for r in rects:
            carve_rect(grid, r)
        a, b = cell_center(rects[0]), cell_center(rects[-1])
        corridors = [_carve_corridor(grid, a, b, corridor_width, rng)]

    layout = build_layout(
        algorithm="bsp", params=params, grid=grid, rooms=rects,
        corridors=[(a, b, corridor_width) for a, b in corridors], rng=rng,
    )
    return layout
