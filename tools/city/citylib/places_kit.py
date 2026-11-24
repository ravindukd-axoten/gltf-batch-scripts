"""Place kit pieces (P207 E2): the drive-in bay plus the fuel station kit (citylib/fuel_kit.py), as street-kit data.

Pure Python (no bpy), unit-tested. The pieces use the street kit's part helpers (`street_kit.box`, `cyl`, `tube`,
`sweep`, `array`) and are built by the same Geometry Nodes generator (`citylib/gn/street.py`: applied, Bevel +
Weighted Normal, trim UVs / world UVs, COLOR_0 paint + Cycles vertex AO). Dimensions and anchors come from the
data files in `data/places/` (one per piece, schema `data/schemas/place_kit.schema.json`), so the data is the one
source for the Blender build and for Unity's PlaceSite (E5). `tools/city/build_places_kit.py` builds and exports.

Frames: the data is piece-local in Unity axes (x right, y up, z forward). Blender parts here use the kit frame
(x the same, Blender y = Unity z, Blender z = Unity y); `to_blender()` converts. Materials are shared world
materials only (no new shader, no unique texture): MAT_StreetKit_A (paint by vertex colour over the trim rows),
MAT_Concrete_Weathered (floors and forecourt, real-scale UVs), MAT_Lamp_Emissive (tube light, canopy soffit
lights, LED price rows). That is 3 draws per piece on Low.
"""
from __future__ import annotations

import json
import os

from . import street_kit as SK
from . import fuel_kit as FK
from . import service_kit as SV
from .street_kit import Piece, array, box, cyl, sweep, tube

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(REPO, "data", "places")
SCHEMA = os.path.join(REPO, "data", "schemas", "place_kit.schema.json")
TRIS_JSON = os.path.join(os.path.dirname(__file__), "places_kit_tris.json")
NAMES = ("KIT_BayOpen_A",) + FK.NAMES + SV.NAMES

# paint (sRGB). Yard workshop: lime-wash render over a red-oxide dado, painted green lintel, galvanised sheet.
RENDER = SK.WALL_FAMILIES["cream"]
OXIDE = "#7A3B2E"
LINTEL = "#3E5F55"
GALV, GALV_D = SK.GALV, SK.GALV_D
SAFETY_Y, SAFETY_K = "#E3B12C", "#232325"
PAINT_W = "#ECEAE2"            # road / floor paint white
HARDBOARD = "#B7966A"
TOOL_RED = "#B23A33"
RUBBER = "#262628"
TEAL_D = "#0F5958"                # oil drum


def load(name: str) -> dict:
    with open(os.path.join(DATA_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def to_blender(p):
    """Unity piece-local (x, y up, z forward) -> Blender kit frame (x, y forward, z up)."""
    return (p[0], p[2], p[1])


def anchors(name: str) -> list[dict]:
    return load(name)["anchors"]


def _stripes(length, n, at, size, paint=SAFETY_K, axis="x"):
    """n dark bands evenly over a painted run (kerb stop, island kerbs)."""
    step = length / n
    x0, y0, z0 = at
    if axis == "x":
        return array(box(size, (x0 - length / 2 + step / 2, y0, z0), paint), n, (step, 0.0, 0.0))
    return array(box(size, (x0, y0 - length / 2 + step / 2, z0), paint), n, (0.0, step, 0.0))


# --- 1. open-front drive-in bay ---------------------------------------------------------------------

def bay() -> Piece:
    d = load("KIT_BayOpen_A")["dims"]
    W, D, t, H = d["inner_w"], d["inner_d"], d["wall_t"], d["clear_h"]
    rf, rb, sh, ap = d["roof_front"], d["roof_back"], d["slab_h"], d["apron_d"]
    X = W + 2 * t                    # outer width, x 0..X
    cx = X / 2
    wall_top = rb - 0.05             # walls stop under the low (back) eave; a gable wedge fills the slope
    dado = 1.0
    p = []
    # floor slab and the ramp lip at the opening (concrete, real-scale UVs)
    p.append(box((W, D, sh), (cx, D / 2, sh / 2), mat="concrete", uv="world"))
    p.append(sweep([(t, 0.0, 0.0), (t + W, 0.0, 0.0)], [(0.0, 0.0), (0.0, sh), (-ap, 0.0)], mat="concrete", uv="world"))
    # walls: render box + a red-oxide dado box 2 cm proud on every face
    for x in (t / 2, X - t / 2):
        p.append(box((t, D + t, wall_top), (x, (D + t) / 2, wall_top / 2), RENDER, uv="body"))
        p.append(box((t + 0.04, D + t + 0.02, dado), (x, (D + t) / 2, dado / 2), OXIDE))
        # gable wedge from the back eave up to the front lintel
        p.append(sweep([(x - t / 2, 0.0, 0.0), (x + t / 2, 0.0, 0.0)],
                       [(0.0, wall_top), (D + t, wall_top), (0.0, rf - 0.06)], RENDER, uv="body"))
        # breeze-block vent band high on each side wall (dark openings through the wall, seen from both faces)
        p.append(array(box((t + 0.02, 0.2, 0.2), (x, 1.2, wall_top - 0.45), "#3A3530"), 9, (0.0, 0.6, 0.0)))
    p.append(box((X, t, wall_top), (cx, D + t / 2, wall_top / 2), RENDER, uv="body"))
    p.append(box((X - 0.02, t + 0.04, dado), (cx, D + t / 2, dado / 2), OXIDE))
    # front piers and the painted lintel beam
    for x in (0.16, X - 0.16):
        p.append(box((0.34, 0.34, H), (x, 0.05, H / 2), RENDER, uv="body"))
        p.append(box((0.38, 0.38, dado), (x, 0.05, dado / 2), OXIDE))
    p.append(box((X + 0.1, 0.36, rf - H), (cx, 0.05, (H + rf) / 2), LINTEL))
    # rolled-up roller shutter: drum housing behind the lintel, guide channels on both jambs
    p.append(cyl(0.2, W - 0.1, (t + 0.05, 0.42, H - 0.2), segs=10, paint=GALV_D, axis="x"))
    for x in (t + 0.05, X - t - 0.05):
        p.append(box((0.07, 0.09, H - 0.3), (x, 0.26, (H - 0.3) / 2 + sh), GALV_D))
    # lean-to corrugated sheet roof: one sheet + raised ribs down the fall, three steel purlins under it
    y0, y1 = -0.35, D + t + 0.3
    slope = (rb - rf) / (y1 - y0)
    p.append(sweep([(-0.1, 0.0, 0.0), (X + 0.1, 0.0, 0.0)],
                   [(y0, rf), (y1, rb), (y1, rb + 0.025), (y0, rf + 0.025)], GALV))
    p.append(array(tube([(-0.05, y0, rf + 0.03), (-0.05, y1, rb + 0.03)], 0.022, segs=4, paint=GALV), 20,
                   ((X + 0.1) / 19, 0.0, 0.0)))
    for y in (1.6, 3.6, 5.6):
        z = rf + slope * (y - y0) - 0.07
        p.append(box((X, 0.08, 0.12), (cx, y, z), SK.IRON))
    # floor paint: bay edge lines; striped kerb stop
    for x in (cx - 1.25, cx + 1.25):
        p.append(box((0.08, D - 0.6, 0.006), (x, D / 2 - 0.1, sh + 0.003), SAFETY_Y))
    ks = next(a for a in anchors("KIT_BayOpen_A") if a["kind"] == "kerb_stop")
    kx, ky, kz = to_blender(ks["pos"])
    sx, sy, sz = ks["size"]
    p.append(box((sx, sz, sy), (kx, ky, kz + sy / 2), SAFETY_Y, mat="kit"))
    p.append(_stripes(sx, 4, (kx, ky, kz + sy / 2), (0.2, sz + 0.004, sy + 0.004)))
    # tool wall (left), cabinet, bench (right), oil drum and tyres (back corner)
    p.append(box((0.03, 2.6, 1.2), (t + 0.02, 3.6, 1.75), HARDBOARD))
    p.append(array(box((0.03, 0.035, 0.26), (t + 0.05, 2.6, 1.85), SK.IRON), 9, (0.0, 0.22, 0.0)))
    p.append(array(box((0.05, 0.3, 0.22), (t + 0.06, 2.75, 1.4), TOOL_RED), 3, (0.0, 0.7, 0.0)))
    p.append(box((0.55, 0.9, 1.0), (t + 0.3, 5.5, sh + 0.5), TOOL_RED))
    p.append(array(box((0.56, 0.8, 0.02), (t + 0.3, 5.5, sh + 0.25), SK.BLACK), 4, (0.0, 0.0, 0.2)))
    p.append(box((0.65, 2.4, 0.06), (X - t - 0.33, 4.8, sh + 0.9), SK.STONE))
    for y in (3.7, 5.9):
        p.append(box((0.06, 0.06, 0.88), (X - t - 0.1, y, sh + 0.44), SK.IRON))
        p.append(box((0.06, 0.06, 0.88), (X - t - 0.6, y, sh + 0.44), SK.IRON))
    p.append(box((0.6, 2.2, 0.04), (X - t - 0.33, 4.8, sh + 0.25), SK.IRON))
    p.append(cyl(0.29, 0.88, (t + 0.38, D - 0.4, sh), segs=12, paint=TEAL_D))
    p.append(array(cyl(0.3, 0.19, (t + 1.15, D - 0.4, sh), segs=12, paint=RUBBER), 3, (0.0, 0.0, 0.2)))
    # oil stains on the floor where engines stand (kit paint, 3 mm proud)
    for (ox, oy, w, l, r) in ((cx - 0.15, 4.5, 0.9, 0.6, 0.3), (cx + 0.2, 2.2, 0.6, 0.45, -0.5)):
        p.append(box((w, l, 0.004), (ox, oy, sh + 0.002), "#6E6A62", rot=r))
    # back gutter and front barge board on the roof
    p.append(box((X + 0.2, 0.14, 0.12), (cx, y1 + 0.02, rb - 0.04), GALV_D))
    p.append(box((X + 0.24, 0.04, 0.18), (cx, y0 - 0.02, rf + 0.02), LINTEL))
    # tube light under the middle purlin
    zl = rf + slope * (3.6 - y0) - 0.2
    p.append(box((1.25, 0.08, 0.05), (cx, 3.6, zl + 0.04), SK.GALV))
    p.append(box((1.2, 0.04, 0.04), (cx, 3.6, zl), mat="lamp"))
    return Piece("KIT_BayOpen_A", X, rf + 0.05, p, budget=load("KIT_BayOpen_A")["budget_low"]["tris_lod0"],
                 bevel=0.012, refs=load("KIT_BayOpen_A")["refs"])


ROLE_PAINT = {"concrete": "#B9B4AA", "lamp": "#FFF4D6", "cobble": "#8A8780"}   # preview / COLOR_0 tint of the non-paint materials


def _role_paint(part: dict) -> None:
    if part["t"] == "array":
        _role_paint(part["part"])
    elif part.get("mat") in ROLE_PAINT:
        part["paint"] = ROLE_PAINT[part["mat"]]


BEVEL_M = 0.015          # P242: Bevel (1 segment, harden) + Weighted Normal on canopy, shed and building pieces
BEVEL_PROP_M = 0.01      # props, pylons, lifts


def surface(piece: Piece) -> Piece:
    """Kit surface layer (P242) on a fuel / service piece: trim-row UV0, COLOR_1 wear and (LOD0 only) the bevel."""
    piece.surface = True
    if piece.bevel == 0.0 and not piece.name.endswith(("_LOD1", "_LOD2")):
        piece.bevel = BEVEL_M if piece.name.startswith("KIT_") else BEVEL_PROP_M
    return piece


def has_lod2(name: str) -> bool:
    """LOD2 for every fuel piece and the service buildings (KIT_*); small service props stop at LOD1."""
    base = name.split("__")[0]
    return base in FK.NAMES or (base in SV.NAMES and base.startswith("KIT_"))


def pieces(lods: bool = False) -> dict[str, Piece]:
    """Every place-kit piece by name; `lods` adds `<name>_LOD1` (the piece without its fuel_kit.detail() parts, round
    parts at 8 sides, no bevel) and, where has_lod2(), `<name>_LOD2` (fuel_kit.lod2). Nodes `<piece>__<Node>` (moving
    lift parts; static Ground / Islands of the canopies and sheds) get their own LODs."""
    out = {}
    fuel = [pc for piece in FK.pieces().values() for pc in SV.split_nodes(piece)]
    for piece in [bay()] + fuel + list(SV.pieces().values()):
        for part in piece.parts:
            _role_paint(part)
        out[piece.name] = piece
        if piece.name.split("__")[0] in FK.NAMES + SV.NAMES:
            surface(piece)
            if lods:
                low = FK.lod1(piece)
                out[low.name] = low
                if has_lod2(piece.name):
                    far = FK.lod2(piece)
                    out[far.name] = far
    return out


def measured() -> dict[str, dict]:
    """Per piece {tris, draws, materials} as the last Blender build measured them (build_places_kit.py)."""
    if not os.path.exists(TRIS_JSON):
        return {}
    with open(TRIS_JSON, encoding="utf-8") as fh:
        return json.load(fh)
