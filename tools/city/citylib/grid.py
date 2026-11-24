"""Streaming-cell maths, a line-for-line mirror of BatchIsland.WorldGrid (Runtime/WorldGrid.cs).

Positions here are in the world frame: east = Unity X, north = Unity Z (metres from the origin).
Cell id = cell_<floor(east / 128)>_<floor(north / 128)>; tests check this file against WorldGrid.cs.
"""
from __future__ import annotations

import math

CELL_SIZE = 128.0  # WorldGrid.CellSize


def cell_of(east: float, north: float) -> tuple[int, int]:
    """WorldGrid.CellOf: floor (not truncation), so -0.5 m is cell -1."""
    return math.floor(east / CELL_SIZE), math.floor(north / CELL_SIZE)


def cell_id(cell: tuple[int, int]) -> str:
    """WorldGrid.CellId: cell_<east>_<north>."""
    return f"cell_{cell[0]}_{cell[1]}"


def cell_id_at(east: float, north: float) -> str:
    return cell_id(cell_of(east, north))


def cell_origin(cell: tuple[int, int]) -> tuple[float, float]:
    """WorldGrid.CellOrigin: south-west corner (east, north)."""
    return cell[0] * CELL_SIZE, cell[1] * CELL_SIZE


def cell_bounds(cell: tuple[int, int]) -> tuple[float, float, float, float]:
    """(min_east, min_north, max_east, max_north)."""
    x0, y0 = cell_origin(cell)
    return x0, y0, x0 + CELL_SIZE, y0 + CELL_SIZE


def cells_in_bounds(min_e: float, min_n: float, max_e: float, max_n: float) -> list[tuple[int, int]]:
    """Every cell touching the box, sorted north-then-east for stable output order."""
    cx0, cy0 = cell_of(min_e, min_n)
    cx1, cy1 = cell_of(max_e, max_n)
    return [(cx, cy) for cy in range(cy0, cy1 + 1) for cx in range(cx0, cx1 + 1)]


def split_segment(p0: tuple[float, float], p1: tuple[float, float]) -> list[tuple[tuple[int, int], tuple[float, float], tuple[float, float]]]:
    """Cut a 2D segment at cell borders. Returns [(cell, a, b)] pieces in order from p0 to p1;
    each piece's midpoint decides its cell, so pieces lying on a border go to the east/north cell."""
    (x0, y0), (x1, y1) = p0, p1
    ts = {0.0, 1.0}
    dx, dy = x1 - x0, y1 - y0
    for a0, d in ((x0, dx), (y0, dy)):
        if abs(d) < 1e-12:
            continue
        lo, hi = sorted((a0, a0 + d))
        k = math.floor(lo / CELL_SIZE) + 1
        while k * CELL_SIZE < hi:
            ts.add((k * CELL_SIZE - a0) / d)
            k += 1
    ts_sorted = sorted(t for t in ts if 0.0 <= t <= 1.0)
    out = []
    for ta, tb in zip(ts_sorted, ts_sorted[1:]):
        if tb - ta < 1e-9:
            continue
        a = (x0 + dx * ta, y0 + dy * ta)
        b = (x0 + dx * tb, y0 + dy * tb)
        out.append((cell_of((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), a, b))
    return out
