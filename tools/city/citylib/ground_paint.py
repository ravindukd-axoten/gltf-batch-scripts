"""Layout of the B1 road-paint glyph atlas T_RoadPaint_B (material MAT_RoadPaint_B), row WS-0025 (P292).

The glyphs T_RoadPaint_A lacks: combo arrows, give-way triangle, SLOW, BALADAKSHA, BUS LANE, hump chevrons, a
yellow box-junction hatch and bay-end (wheel-stop) paint. Same grid, size, asphalt and paint treatment as
T_RoadPaint_A (citylib/paint_atlas.py): 1024 x 1920 px, 4 x 3 cells of 256 x 640 px, opaque (each cell carries its
own asphalt), u across the lane to the driver's right, v along travel. Kept as its own sheet so the existing cells'
UVs do not move; merging it into RoadPaint_A (one material per cell) needs a city + texture rebuild together
(GROUND_HANDOFF.md). Pure Python, shared by the geometry (citylib/ground_build.py) and tools/city/build_ground_paint.py.
"""
from __future__ import annotations

from . import paint_atlas as pa

ATLAS_W, ATLAS_H = pa.ATLAS_W, pa.ATLAS_H
CELL_W, CELL_H = pa.CELL_W, pa.CELL_H
INSET_PX = pa.INSET_PX

# name -> (column, row), row 0 = bottom of the atlas (UV v 0..1/3)
CELLS = {
    "ARROW_STRAIGHT_LEFT": (0, 0), "ARROW_STRAIGHT_RIGHT": (1, 0), "GIVE_WAY": (2, 0), "SLOW": (3, 0),
    "BALADAKSHA": (0, 1), "BUS_LANE": (1, 1), "HUMP_CHEVRON": (2, 1), "BOX_HATCH": (3, 1),
    "WHEEL_STOP": (0, 2), "SPARE_1": (1, 2), "SPARE_2": (2, 2), "SPARE_3": (3, 2),   # spares: plain asphalt
}
YELLOW = {"BOX_HATCH", "WHEEL_STOP"}
PAINT_WHITE, PAINT_YELLOW = "#DCD6C8", "#D2A73C"     # Art Bible: chipped and faded lane paint
# metres the cell is drawn for (across, along); geometry may differ (the hump stretches its cell over 3.5 x 3.7 m)
DRAWN_M = {"ARROW_STRAIGHT_LEFT": (1.4, 3.5), "ARROW_STRAIGHT_RIGHT": (1.4, 3.5), "GIVE_WAY": (1.4, 3.5),
           "SLOW": (2.0, 5.0), "BALADAKSHA": (2.4, 6.0), "BUS_LANE": (2.4, 6.0), "HUMP_CHEVRON": (3.5, 3.7),
           "BOX_HATCH": (3.2, 8.0), "WHEEL_STOP": (1.0, 2.5)}


def uv_rect(name: str) -> tuple[float, float, float, float]:
    """(u0, v0, u1, v1) of a cell, inset a few pixels so filtering never bleeds a neighbour in."""
    c, r = CELLS[name]
    return ((c * CELL_W + INSET_PX) / ATLAS_W, (r * CELL_H + INSET_PX) / ATLAS_H,
            ((c + 1) * CELL_W - INSET_PX) / ATLAS_W, ((r + 1) * CELL_H - INSET_PX) / ATLAS_H)


def paint_hex(name: str) -> str:
    return PAINT_YELLOW if name in YELLOW else PAINT_WHITE
