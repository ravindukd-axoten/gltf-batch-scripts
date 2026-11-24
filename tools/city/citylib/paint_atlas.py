"""Layout of the road-paint atlas T_RoadPaint_A (material MAT_RoadPaint_A): lane legends, arrows, "BUS".

Shared by the city pipeline (UVs, citylib/markings.py) and the texture script (tools/textures/build_textures.py),
so the picture and the geometry cannot drift apart. Pure Python, no dependencies.

The atlas is 1024 x 1920 px: 4 columns x 3 rows of 256 x 640 px cells (aspect 0.4); row 2 (MAT2) holds the road
wear decals (oil, cracks, an older patch), opaque like the rest so they cost no blending and no extra draw. A cell is drawn so that it
looks right on a quad of that aspect: the word legends are baked already stretched (tall thin capitals, what
drivers see on the real road), arrows and BUS are drawn undistorted. u runs across the lane to the driver's right,
v along the direction of travel, so the top of the letters is the far end. Opaque: the cell carries its own
asphalt, like the trim's paint rows.
"""
from __future__ import annotations

ATLAS_W, ATLAS_H = 1024, 1920
CELL_W, CELL_H = 256, 640
TILE_M = (9.6, 18.0)          # metres the whole atlas covers (107 px/m across, 107 px/m along for arrows)

# name -> (column, row), row 0 = bottom of the atlas (v 0..0.5)
CELLS = {
    "CITYHUB": (0, 1), "WELLAWATTA": (1, 1), "A2": (2, 1), "BUS": (3, 1),
    "ARROW_STRAIGHT": (0, 0), "ARROW_LEFT": (1, 0), "ARROW_RIGHT": (2, 0),
    "PATCH": (3, 0),          # phase 2: asphalt patch repair (darker resealed rectangle), placed by citylib/roadside.py
    # MAT2 road wear (citylib/roadside.py rules): oil drips where vehicles wait, a sealed longitudinal crack along a
    # wheel path, crazed (alligator) asphalt, an older pale patch with frayed edges
    "OIL": (0, 2), "CRACK": (1, 2), "ALLIGATOR": (2, 2), "PATCH_B": (3, 2),
}
# quad size in metres (across, along) per cell kind
LEGEND_M = (2.4, 6.0)
ARROW_M = (1.4, 3.5)
BUS_M = (1.2, 3.0)
SIZE_M = {"CITYHUB": LEGEND_M, "WELLAWATTA": LEGEND_M, "A2": LEGEND_M, "BUS": BUS_M,
          "ARROW_STRAIGHT": ARROW_M, "ARROW_LEFT": ARROW_M, "ARROW_RIGHT": ARROW_M, "PATCH": (1.6, 4.0),
          "OIL": (1.2, 3.0), "CRACK": (1.2, 3.0), "ALLIGATOR": (1.4, 3.5), "PATCH_B": (1.8, 4.5)}
INSET_PX = 3


def uv_rect(name: str) -> tuple[float, float, float, float]:
    """(u0, v0, u1, v1) of a cell, inset a few pixels so filtering never bleeds a neighbour in."""
    c, r = CELLS[name]
    return ((c * CELL_W + INSET_PX) / ATLAS_W, (r * CELL_H + INSET_PX) / ATLAS_H,
            ((c + 1) * CELL_W - INSET_PX) / ATLAS_W, ((r + 1) * CELL_H - INSET_PX) / ATLAS_H)
