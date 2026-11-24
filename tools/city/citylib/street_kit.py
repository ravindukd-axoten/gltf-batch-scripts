"""Delta Face street kit: the data the Geometry Nodes street generators build from (TDD "Street kit as built").

Pure Python (no bpy), unit-tested. Each piece is a list of parts; `citylib/gn/street.py` turns every part into
Geometry Nodes (lathe = a profile curve's radius swept by Curve to Mesh, tube = a polyline swept by a circle,
box/cyl/cone = GN mesh primitives, array = Instance on Points along a line, sweep = a profile swept along a
path, window = the hero library's PI_GN_WindowGrid). Python only says what and where (dimensions from the
reference photos, listed per piece); the shapes are node groups that open and edit in Blender.

Frame (same as kit.py): x along the wall / road, y outwards is -y, z up, pivot on the ground. Paint is sRGB hex
into COLOR_0 rgb (AO goes to alpha, baked after the generator is applied); `mat` is a material role:
  kit   MAT_StreetKit_A  (SHD_HeroLit over the FacadeTrim_A textures; UV0 on the trim rows, UV1 decor masks)
  sign  MAT_Signage_A    (SHD_HeroLit over T_Signage_A; UV0 = the board's atlas cell)
  glass MAT_StreetKit_A painted black (HeroLit draws black-painted faces as glass)
  lamp  MAT_Lamp_Emissive, rubble MAT_SeawallRubble, concrete MAT_Concrete_Weathered, roof MAT_RoofTerracotta
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

from . import rules

MAT_KIT = "MAT_StreetKit_A"
MAT_SIGN = "MAT_Signage_A"
ROLES = {"kit": MAT_KIT, "glass": MAT_KIT, "sign": MAT_SIGN, "lamp": "MAT_Lamp_Emissive",
         "rubble": "MAT_SeawallRubble", "concrete": "MAT_Concrete_Weathered", "roof": "MAT_RoofTerracotta",
         "cobble": "MAT_GreyCobble"}

SEAWALL_H = 3.6
STEPS_H = 3.0
TERRACE_H = 0.9
SIGNS_JSON = os.path.join(os.path.dirname(__file__), "..", "..", "textures", "signage.json")

# paint (sRGB): street furniture colours from the photos and the style frames
BLACK, IRON = "#2B2A2C", "#3B3D40"
GALV, GALV_D = "#A9ADA9", "#8C918F"
COPPER = "#B8653A"
CREAM, WHITE, STONE = "#EFE6D2", "#F4F1E8", "#D8CFBF"
BIN = {"g": "#2E7D3E", "r": "#B8282E", "o": "#E8862A"}
WALL_FAMILIES = {   # lime-wash families (gf_21, gf_24, gf_25: off-white; a few muted alternatives, no ochre / rose / gold)
    "lime": "#F0EDE5", "cream": "#ECE5D4", "grey": "#DEDDD8", "pastel": "#D8E2DD", "white": "#F3F1EA",
}
TIMBER = {"green": "#2C4636", "brown": "#563B2A"}   # louvred shutters and panelled doors (gf_24)
SHOP_FRAME = "#D3D5D1"                               # light aluminium / painted shop-glass frame
CANVAS = {"red": "#B23A33", "green": "#2F6B48", "blue": "#2D5E95", "cream": "#EFE7D2", "orange": "#D9822E"}


@dataclass
class Piece:
    name: str
    width: float
    height: float
    parts: list
    budget: int                 # LOD0 triangle cap (AGENTS.md budgets: kit 500-3k, prop 100-1.5k)
    bevel: float = 0.0          # Bevel (1 segment, angle-limited) + Weighted Normal width, 0 = none
    upper: bool = False         # UV1 decor band: upper storeys (no base dirt)
    shutter: str = TIMBER["green"]   # paint of the WindowGrid's louvred shutter / awning sources
    refs: list = field(default_factory=list)   # reference photos / style frame the piece is checked against
    decay: str = ""             # wear class ("metal", "timber", "paint", "plastic", "concrete"): writes COLOR_1 (see gn/street.py)
    surface: bool = False       # kit surface layer (P242): trim-row UV0 on flat paint + COLOR_1 wear (gn/street.py)


def lathe(prof, segs=8, paint=GALV, mat="kit", at=(0.0, 0.0, 0.0)):
    """Radius profile [(r, z), ...] bottom to top, revolved about +z at `at`."""
    return {"t": "lathe", "prof": prof, "segs": segs, "paint": paint, "mat": mat, "at": at}


def tube(pts, r, segs=6, paint=GALV, mat="kit"):
    return {"t": "tube", "pts": pts, "r": r, "segs": segs, "paint": paint, "mat": mat}


def box(size, at, paint=GALV, mat="kit", rot=0.0, uv="trim"):
    """Box of `size` (x, y, z) centred at `at`; rot about z; uv 'trim' (flat paint), 'body' (wall plaster rows),
    'world' (real-scale, for world materials), or ('sign', col, row) for an atlas cell on the -y face."""
    return {"t": "box", "size": size, "at": at, "paint": paint, "mat": mat, "rot": rot, "uv": uv}


def cyl(r, depth, at, segs=12, paint=IRON, mat="kit", axis="z", r2=None):
    return {"t": "cyl", "r": r, "r2": r if r2 is None else r2, "depth": depth, "at": at, "segs": segs,
            "paint": paint, "mat": mat, "axis": axis}


def sweep(path, prof, paint=CREAM, mat="kit", uv="trim", closed=True):
    """Profile [(px, py), ...] (px right of travel, py up) swept along the 3D polyline `path`."""
    return {"t": "sweep", "path": path, "prof": prof, "paint": paint, "mat": mat, "uv": uv, "closed": closed}


def array(part, count, step):
    return {"t": "array", "part": part, "count": count, "step": step}


def window(**inputs):
    """One PI_GN_WindowGrid bay at x = Bay Width / 2 (hero library, gn/facade.py); paint by `family`."""
    return {"t": "window", "inputs": inputs}


# --- promenade set (priority 1) ------------------------------------------------------------------

def _seawall(name, bench_h, cap_over, batter, rows=5):
    H = SEAWALL_H
    body = [(-batter, 0.0), (-0.05, H - 0.1), (-0.12, H - 0.1), (-0.12, H + bench_h - 0.1), (0.5, H + bench_h - 0.1),
            (0.5, H), (0.9, H), (0.9, 0.0)]
    # coping with a rolled (half-round) lip on the sea side, where people sit (gf_03, gf_16); flat to the land side
    r, top = 0.09, H + bench_h + 0.04
    lx, lz = -0.12 - cap_over + r, top - r
    lip = [(lx - r * math.sin(a), lz + r * math.cos(a)) for a in (math.pi * k / 6 for k in range(6, 0, -1))]
    cap = [(-0.12 - cap_over + r, H + bench_h - 0.1)] + lip + [(lx, top), (0.5 + cap_over, top), (0.5 + cap_over, H + bench_h - 0.1)]
    toe = [(-batter - 0.25, -0.3), (-batter - 0.25, 0.25), (-batter + 0.2, 0.25), (-batter + 0.2, -0.3)]
    return Piece(name, 4.0, H + bench_h + 0.04, [
        sweep([(0, 0, 0), (4, 0, 0)], body, STONE, "rubble", "world"),
        {"t": "rubble", "face": [(-batter, 0.0), (-0.05, H - 0.1)], "length": 4.0, "rows": rows, "cols": 5,
         "paint": STONE, "mat": "rubble"},
        sweep([(0, 0, 0), (4, 0, 0)], cap, STONE, "concrete", "world"),
        sweep([(0, 0, 0), (4, 0, 0)], toe, STONE, "concrete", "world"),
    ], 2000, refs=["gf_03", "gf_04", "gf_10", "gf_16"])


def _steps(name, n, w, h, run, cheek=0.25):
    rise = h / n
    step = box((w, run, rise), (w / 2, -run / 2, h - rise / 2), STONE, "concrete", uv="world")
    cheek_prof = [(-cheek, 0.0), (0.0, 0.0), (0.0, 0.25), (-cheek, 0.25)]
    return Piece(name, w, h, [
        array(step, n, (0.0, -run, -rise)),
        box((w, n * run, 0.12), (w / 2, -n * run / 2, 0.06), STONE, "concrete", uv="world"),
        sweep([(0, 0, h - 0.05), (0, -n * run, -0.05)], cheek_prof, STONE, "concrete", "world"),
        sweep([(w + cheek, 0, h - 0.05), (w + cheek, -n * run, -0.05)], cheek_prof, STONE, "concrete", "world"),
    ], 3000 if n > 8 else 900, refs=["gf_10"])


def _bin(c, x):
    """P46e: a tapered round bin with a rolled rim and a domed lid (gf_10 painted bins), not a box."""
    # 6 sides, 4 rings, open base (never seen): no more tris than the old 3-box bin; the 8 x 9 first try doubled
    # the set to 992 tris and 6 x 5 still put cell_-1_-1 over 60k
    return [lathe([(0.21, 0.0), (0.26, 0.84), (0.29, 0.9), (0.0, 0.96)],
                  6, BIN[c], at=(x, 0.0, 0.0)),
            box((0.24, 0.03, 0.05), (x, -0.27, 0.78), IRON)]


def _globe(x, z, r=0.2):
    return lathe([(0.05, 0.0), (0.16 * r / 0.2, 0.06), (r, 0.2), (r * 0.8, 0.34), (0.03, 0.4)], 10, CREAM, "lamp",
                 (x, 0.0, z))


def promenade() -> list[Piece]:
    p = [_seawall("KIT_Seawall_Rubble_A", 0.55, 0.05, 0.9), _seawall("KIT_Seawall_Rubble_B", 0.45, 0.08, 0.8, 6),
         _seawall("KIT_Seawall_Rubble_C", 0.62, 0.03, 1.0, 5),
         _steps("KIT_SeawallSteps_A", 14, 3.0, STEPS_H, 0.3), _steps("KIT_Steps_Terrace_A", 5, 6.0, TERRACE_H, 0.42),
         _steps("KIT_Steps_TerraceLong_A", 5, 24.0, TERRACE_H, 0.42)]  # one 24 m run, cheeks only at its ends (gf_10)
    bars = array(cyl(0.012, 0.86, (0.11, 0, 0.55), 5, BLACK), 21, (0.11, 0, 0))
    p.append(Piece("PROP_Railing_Finial_01", 2.5, 1.22, [
        lathe([(0.05, 0.0), (0.05, 1.0), (0.07, 1.04), (0.03, 1.08), (0.075, 1.15), (0.0, 1.22)], 8, BLACK),
        tube([(0.0, 0, 1.0), (2.5, 0, 1.0)], 0.035, 6, COPPER), tube([(0.0, 0, 0.1), (2.5, 0, 0.1)], 0.02, 4, BLACK),
        bars], 1200, refs=["gf_08"]))
    pole = [(0.16, 0.0), (0.16, 0.45), (0.1, 0.55), (0.075, 0.6), (0.06, 4.6), (0.05, 5.0)]
    p.append(Piece("PROP_Lamp_TwinGlobe_01", 1.3, 5.45, [
        lathe(pole, 8, IRON), tube([(-0.55, 0, 4.82), (-0.3, 0, 4.92), (0.3, 0, 4.92), (0.55, 0, 4.82)], 0.03, 6, IRON),
        _globe(-0.55, 4.82), _globe(0.55, 4.82), lathe([(0.04, 0.0), (0.02, 0.35)], 6, IRON, at=(0, 0, 5.0))],
        1500, refs=["gf_10", "gf_16"]))
    arm = lambda s: tube([(0, 0, 9.3), (0.6 * s, 0, 9.65), (1.4 * s, 0, 9.8), (1.9 * s, 0, 9.75)], 0.045, 6, GALV)  # noqa: E731
    head = lambda s: [box((0.7, 0.28, 0.12), (2.05 * s, 0, 9.72), GALV_D), box((0.6, 0.22, 0.03), (2.05 * s, 0, 9.65), CREAM, "lamp")]  # noqa: E731
    p.append(Piece("PROP_StreetLamp_DoubleArm_01", 4.6, 10.0, [
        box((0.5, 0.5, 0.6), (0, 0, 0.3), STONE, "concrete", uv="world"),
        lathe([(0.14, 0.6), (0.12, 3.0), (0.08, 9.4), (0.06, 9.9)], 8, GALV), arm(1), arm(-1), *head(1), *head(-1)],
        1200, refs=["gf_10", "gf_18"]))
    cluster = [_globe(0, 5.15, 0.24)]
    for dx, dy in ((0.55, 0), (-0.55, 0), (0, 0.55), (0, -0.55)):
        cluster.append(tube([(0, 0, 4.7), (dx * 0.6, dy * 0.6, 4.75), (dx, dy, 4.62)], 0.025, 5, IRON))
        g = _globe(0, 4.62, 0.18)
        g["at"] = (dx, dy, 4.62)
        cluster.append(g)
    p.append(Piece("PROP_Lamp_Roundabout_01", 1.4, 5.6, [
        box((0.6, 0.6, 0.5), (0, 0, 0.25), STONE, "concrete", uv="world"),
        lathe([(0.2, 0.5), (0.14, 0.9), (0.09, 1.0), (0.08, 4.4), (0.12, 4.6), (0.06, 4.75)], 10, BLACK), *cluster],
        1500, refs=["gf_17", "gf_18"]))
    p.append(Piece("PROP_Bin_Set_01", 1.8, 0.98, _bin("g", -0.62) + _bin("r", 0.0) + _bin("o", 0.62)
                   + [box((1.9, 0.12, 0.08), (0, 0.3, 0.6), IRON)], 600, bevel=0.012, refs=["gf_10"]))
    p.append(Piece("PROP_Bench_StoneWall_01", 3.0, 0.47, [
        box((3.0, 0.5, 0.4), (1.5, 0, 0.2), STONE, "rubble", uv="world"),
        box((3.06, 0.6, 0.07), (1.5, 0, 0.435), STONE, "concrete", uv="world")], 200, bevel=0.015, refs=["gf_16"]))
    p.append(Piece("PROP_Bollard_01", 0.3, 0.92, [
        lathe([(0.15, 0.0), (0.15, 0.06), (0.12, 0.1), (0.11, 0.78), (0.08, 0.86), (0.0, 0.92)], 10, WHITE),
        lathe([(0.112, 0.5), (0.112, 0.6)], 10, BLACK)], 300, refs=["gf_18"]))
    # the umbrella food carts were replaced by the isso wade carts (citylib/carts.py, tools/city/build_carts.py)
    tin = [(-1.4, -1.05), (1.4, -1.05), (1.4, -0.95), (-1.4, -0.95)]
    p.append(Piece("PROP_Kade_Stall_01", 2.8, 2.7, [
        *[box((0.07, 0.07, 2.35), (x, y, 1.175), "#2F5E8C") for x in (-1.2, 1.2) for y in (-0.7, 0.7)],
        box((2.4, 0.6, 1.0), (0, -0.4, 0.5), "#2F5E8C"), box((2.5, 0.7, 0.05), (0, -0.4, 1.02), CREAM),
        box((2.4, 0.04, 2.3), (0, 0.72, 1.15), "#D9D2BE"),
        sweep([(-1.4, 0.0, 2.36), (1.4, 0.0, 2.36)], [(-1.05, 0.0), (0.95, 0.25), (0.95, 0.29), (-1.05, 0.04)], GALV, uv="trim"),
        box((2.3, 0.04, 0.42), (0, -0.82, 2.2), "#FFFFFF", "sign", uv=("sign", 2, 6)),
        box((2.0, 0.5, 0.06), (0, -0.4, 1.4), "#101010", "glass"),
    ], 600, bevel=0.01, refs=["gf_03"]))
    _ = tin
    return p


# --- Delta Road shopfront kit (priority 2): ground bays 3.0 x 4.0 m, upper modules 3.0 x 3.2 m -----

GF, UF = rules.GROUND_FLOOR_M, rules.UPPER_FLOOR_M
PIER, FASCIA0, FASCIA1 = 0.3, 2.9, 3.7


def _ground_frame(paint):
    """Piers, fascia band (the sign board sits on it), floor band and plinth shared by the ground bays."""
    return [box((PIER, 0.3, GF), (PIER / 2, 0.15, GF / 2), paint, uv="body"),
            box((PIER, 0.3, GF), (3.0 - PIER / 2, 0.15, GF / 2), paint, uv="body"),
            box((3.0 - 2 * PIER, 0.3, GF - FASCIA0), (1.5, 0.15, (GF + FASCIA0) / 2), paint, uv="body"),
            # P46e: shop cornice over the fascia 0.22 m deep (was 0.12 m), same 5-point profile and tris
            sweep([(0, 0, GF - 0.2), (3.0, 0, GF - 0.2)], [(-0.22, 0.0), (-0.22, 0.08), (-0.06, 0.2), (0.0, 0.2), (0.0, 0.0)], WHITE),
            box((3.0, 0.06, 0.3), (1.5, -0.03, 0.15), "#7E7468", uv="trim")]


def _awning(colours, x0=0.15, x1=2.85, top=FASCIA0 - 0.05, reach=1.0, drop=0.5, stripe=0.45):
    """Canvas awning under the fascia (style frame density; gf_24 green awnings): one sloped sheet with its valance
    per stripe of `colours` (one colour = plain). Stripes are separate sweeps, so no texture is needed."""
    r, d, v = reach, drop, 0.24
    prof = [(0.0, 0.03), (-r, -d + 0.03), (-r, -d - v), (-r + 0.02, -d - v), (-r + 0.02, -d - 0.01), (0.0, -0.01)]
    n = max(1, round((x1 - x0) / stripe)) if len(colours) > 1 else 1
    w = (x1 - x0) / n
    return [sweep([(x0 + i * w, 0, top), (x0 + (i + 1) * w, 0, top)], prof, colours[i % len(colours)]) for i in range(n)]


def _shop_window(x0, x1, z0, z1, y=0.28, mullion=False):
    """Shop glass (big panes over a lit interior read in SHD_HeroLit, uv role 'shop') under a light head frame;
    the piers frame the sides."""
    w, cx = x1 - x0, (x0 + x1) / 2
    out = [box((w, 0.04, z1 - z0), (cx, y + 0.02, (z0 + z1) / 2), "#101010", "glass", uv="shop"),
           box((w, 0.08, 0.07), (cx, y - 0.02, z1 + 0.035), SHOP_FRAME)]
    if mullion:
        out.append(box((0.06, 0.08, z1 - z0), (cx, y - 0.02, (z0 + z1) / 2), SHOP_FRAME))
    return out


def _roller(slats, paint="#9BA0A1"):
    """Part-open roller shutter: a curtain `slats` x 0.31 m deep hanging from the drum box under the fascia (one box:
    the bays sit 40+ per Delta Road cell, so slat lines are left to the paint)."""
    zb = FASCIA0 - 0.1 - slats * 0.31
    return [box((2.4, 0.03, slats * 0.31), (1.5, 0.27, zb + slats * 0.155), paint),
            box((2.42, 0.05, 0.05), (1.5, 0.25, zb), "#4A4E50"),
            cyl(0.17, 2.4, (1.5, 0.16, FASCIA0 - 0.05), 6, "#7A8084", axis="x")]


def _doors(x0, x1, z1, paint, y=0.3):
    """Panelled timber double doors filling an arched opening up to its springing line (gf_24): two leaves and
    one raised panel each."""
    half = (x1 - x0) / 2
    out = []
    for i in range(2):
        cx = x0 + i * half + half / 2
        out += [box((half - 0.02, 0.05, z1), (cx, y, z1 / 2), paint),
                box((half - 0.26, 0.03, z1 - 0.5), (cx, y - 0.04, z1 / 2), paint)]
    return out


SHOP_WALLS = {"A": "lime", "B": "cream"}


def shopfronts() -> list[Piece]:
    out = []
    for fam, key in SHOP_WALLS.items():
        paint = WALL_FAMILIES[key]
        # roller shutters part open over a lit shop (A half open under a striped awning, B mostly closed, bare)
        # P46e: B gets a plain green canvas too (bare B bays left the street front flat; style frame awning rhythm)
        slats, aw = (4, [CANVAS["orange"]]) if fam == "A" else (6, [CANVAS["green"]])
        zg = FASCIA0 - 0.1 - slats * 0.31
        parts = (_ground_frame(paint) + _roller(slats) + _shop_window(0.3, 2.7, 0.45, zg - 0.04, y=0.3) +
                 [box((2.4, 0.12, 0.45), (1.5, 0.26, 0.225), "#6E6A62")] + (_awning(aw) if aw else []))
        out.append(Piece(f"KIT_Shopfront_Shutter_{fam}", 3.0, GF, parts, 1600, bevel=0.0, refs=["gf_21", "sf_street"]))
        aw = [CANVAS["green"], CANVAS["cream"]] if fam == "A" else [CANVAS["blue"]]
        out.append(Piece(f"KIT_Shopfront_Glazed_{fam}", 3.0, GF, _ground_frame(paint) + _shop_window(0.3, 2.7, 0.5, 2.75, mullion=True) +
                         [box((2.4, 0.12, 0.5), (1.5, 0.24, 0.25), "#6E6A62")] + _awning(aw),
                         1600, bevel=0.0, refs=["gf_24", "sf_street"]))
        door = TIMBER["green"] if fam == "A" else TIMBER["brown"]
        out.append(Piece(f"KIT_Shopfront_Arched_{fam}", 3.0, GF, [
            window(**{"Bay Width": 3.0, "Storey Height": GF, "Window Width": 1.7, "Window Height": 3.1, "Sill Height": 0.0,
                      "Reveal Depth": 0.35, "Arched": True, "Surround": True, "Keystone": True, "Fanlight": True,
                      "family": paint}),
            *_doors(0.65, 2.35, 2.25, door),
            sweep([(0, 0, GF - 0.18), (3.0, 0, GF - 0.18)], [(-0.12, 0.0), (-0.12, 0.08), (-0.04, 0.18), (0.0, 0.18), (0.0, 0.0)], WHITE),
            box((3.0, 0.06, 0.3), (1.5, -0.03, 0.15), "#7E7468")], 3000, bevel=0.01, refs=["gf_21", "gf_24"], shutter=door))
    out.append(Piece("KIT_Shopfront_Corner_A", 0.9, GF, [
        box((0.9, 0.9, GF), (0.45, 0.45, GF / 2), WALL_FAMILIES["lime"], uv="body"),
        box((1.0, 1.0, 0.35), (0.45, 0.45, 0.175), "#7E7468"),
        sweep([(0, -0.0, GF - 0.18), (0.9, 0, GF - 0.18)], [(-0.12, 0.0), (-0.12, 0.08), (-0.04, 0.18), (0.0, 0.18), (0.0, 0.0)], WHITE)],
        800, bevel=0.02, refs=["gf_25"]))
    return out


UPPER_STYLES = {
    # family -> WindowGrid inputs (gf_21/gf_24 colonial arches and shutters; style frame shophouse awnings)
    "Colonial": {"Window Width": 1.1, "Window Height": 1.9, "Sill Height": 0.75, "Arched": True, "Surround": True,
                 "Keystone": True, "Sill": True, "Shutters": True},
    "Shophouse": {"Window Width": 1.2, "Window Height": 1.6, "Sill Height": 0.85, "Surround": True, "Sill": True,
                  "Hood": True, "Awning": True},
    "Modern": {"Window Width": 1.8, "Window Height": 1.3, "Sill Height": 0.95, "Sill": True, "Hood": True},  # P46e: sunshade
}
UPPER_REVEAL = 0.3   # P46e: 0.22 -> 0.3 m, the opening reads as a hole in a thick lime wall at street distance
UPPER_VARIANTS = {"A": "lime", "B": "cream", "C": "grey", "D": "pastel"}


def upper() -> list[Piece]:
    out = []
    for style, ins in UPPER_STYLES.items():
        for v, fam in UPPER_VARIANTS.items():
            parts = [window(**{"Bay Width": 3.0, "Storey Height": UF, "Reveal Depth": UPPER_REVEAL, **ins,
                               "family": WALL_FAMILIES[fam]}),
                     sweep([(0, 0, UF - 0.16), (3.0, 0, UF - 0.16)], [(-0.1, 0.0), (-0.1, 0.1), (-0.03, 0.16), (0.0, 0.16), (0.0, 0.0)],
                           WHITE)]
            if style == "Modern" and v in ("B", "D"):
                parts.append(box((0.8, 0.3, 0.55), (2.2, -0.15, 0.55), "#D9D9D4"))   # AC unit under the sill
            out.append(Piece(f"KIT_Upper_{style}_{v}", 3.0, UF, parts, 3000, bevel=0.01, upper=True, refs=["gf_21", "gf_24", "sf_street"],
                             shutter=TIMBER["brown"] if v == "C" else TIMBER["green"]))
    return out


def _run(prof, paint, uv="trim"):
    """One open profile (y outwards-negative, z up; bottom to top along the outer face) swept along the 3 m bay."""
    return sweep([(0, 0, 0), (3.0, 0, 0)], prof, paint, uv=uv, closed=False)


def plaster() -> list[Piece]:
    """Plain lime-plaster walls and parapet for every kit / street building below tower height (side and back
    walls, floors above the window modules, the roofline), in the same paint families as the upper modules.
    Open-profile sweeps only, so a bay costs what the V1 FacadeTrim pieces did (the dense whole-block cell_-1_4
    has ~1,800 plain upper bays): wall 2 tris + string course 6; parapet = cornice 4 + wall 2 + coping 6."""
    out = []
    course = lambda z0, z1, o: [(0.0, z0), (-o, z0 + 0.04), (-o, z1 - 0.03), (0.0, z1)]  # noqa: E731
    for v, fam in UPPER_VARIANTS.items():
        paint = WALL_FAMILIES[fam]
        out.append(Piece(f"KIT_WallPlaster_Upper_{v}", 3.0, UF, [
            _run([(0.0, 0.0), (0.0, UF - 0.16)], paint, "body"),
            _run(course(UF - 0.16, UF, 0.08), WHITE)], 40, upper=True, refs=["gf_24", "gf_25"]))
        out.append(Piece(f"KIT_WallPlaster_Ground_{v}", 3.0, GF, [
            _run([(0.0, 0.0), (0.0, GF - 0.18)], paint, "body"),
            _run(course(GF - 0.18, GF, 0.1), WHITE)], 40, refs=["gf_24", "gf_25"]))
        # gf_24 / gf_25: a projecting cornice on the roof line, a short plain parapet and a thin overhanging coping
        H = rules.PARAPET_M
        # P46e: the 0.16 m wedge becomes a 0.28 m deep one at the same 12 tris: its underside throws the dark line
        # under the roofline that gf_24 / gf_25 and the style frame show. (A 7-point moulded profile cost +8 tris a
        # bay and pushed cell_-1_-1 to 60,356, over the 60k LOD0 budget.)
        out.append(Piece(f"KIT_Parapet_Cornice_{v}", 3.0, H, [
            _run([(0.0, 0.0), (-0.28, 0.17), (0.0, 0.29)], WHITE),
            _run([(0.0, 0.29), (0.0, H - 0.06)], paint, "body"),
            _run([(0.0, H - 0.06), (-0.05, H), (0.22, H), (0.22, 0.0)], WHITE)], 40, upper=True, refs=["gf_24", "gf_25"]))
    return out


def sign_atlas() -> dict:
    """T_Signage_A geometry from signage.json: size (px), grid (cols, rows), cell (px); the one source of truth."""
    spec = json.load(open(SIGNS_JSON, encoding="utf-8"))
    return {"size": tuple(spec["size"]), "grid": tuple(spec["grid"]), "cell": tuple(spec["cell"])}


# --- signage (priority 3) ------------------------------------------------------------------------

def signs() -> list[Piece]:
    spec = json.load(open(SIGNS_JSON, encoding="utf-8"))
    out = []
    counts: dict[str, int] = {}
    for s in spec["signs"]:
        use = s["use"]
        if use not in ("fascia", "projecting", "wall"):
            continue
        counts[use] = counts.get(use, 0) + 1
        n = f"PROP_Sign_{use.capitalize()}_{counts[use]:02d}"
        cell = ("sign", s["cell"][0], s["cell"][1])
        if use == "fascia":
            parts = [box((2.8, 0.06, 0.7), (1.5, -0.05, 3.3), "#FFFFFF", "sign", uv=cell)]   # 4:1 cell, ~0.3 m letters
        elif use == "wall":
            parts = [box((2.4, 0.012, 0.6), (1.5, -0.008, 1.6), "#FFFFFF", "sign", uv=cell)]
        else:
            parts = [box((1.5, 0.05, 0.375), (0.0, -0.95, 0.2), "#FFFFFF", "sign", uv=cell, rot=1.5708),   # read at 10-20 m
                     tube([(0, 0, 0.43), (0, -1.75, 0.43)], 0.02, 4, IRON)]
        out.append(Piece(n, 2.4, 3.6, parts, 200, bevel=0.0, refs=["sf_street"]))
    return out


# --- street furniture (priority 4) ---------------------------------------------------------------

def furniture() -> list[Piece]:
    out = []
    out.append(Piece("PROP_StreetLamp_SingleArm_01", 2.8, 10.0, [
        box((0.45, 0.45, 0.5), (0, 0, 0.25), STONE, "concrete", uv="world"),
        lathe([(0.13, 0.5), (0.11, 3.0), (0.07, 9.0)], 8, GALV),
        tube([(0, 0, 8.9), (0.15, 0, 9.6), (0.8, 0, 9.95), (2.2, 0, 10.0)], 0.045, 6, GALV),
        box((0.65, 0.26, 0.12), (2.35, 0, 9.95), GALV_D), box((0.55, 0.2, 0.03), (2.35, 0, 9.88), CREAM, "lamp")],
        800, refs=["gf_21", "gf_24", "gf_25"]))
    post = lambda x, y: box((0.1, 0.1, 2.5), (x, y, 1.25), "#2F5E8C")  # noqa: E731
    out.append(Piece("PROP_BusShelter_01", 4.4, 3.6, [
        *[post(x, y) for x in (-1.9, 1.9) for y in (-0.6, 0.6)],
        box((3.9, 0.06, 1.6), (0, 0.62, 1.5), "#D9D2BE"), box((3.2, 0.4, 0.06), (0, 0.4, 0.46), "#5B4636"),
        *[box((0.08, 0.35, 0.44), (x, 0.4, 0.22), IRON) for x in (-1.4, 1.4)],
        box((4.3, 1.8, 0.12), (0, 0, 2.56), "#7E7468"),
        cyl(3.15, 1.0, (0, 0, 3.12), 4, "#C8693F", "roof", r2=0.05),
        box((1.4, 0.04, 0.35), (0, -0.92, 2.35), "#FFFFFF", "sign", uv=("sign", 0, 5))], 900, bevel=0.01, refs=["sf_street"]))
    out.append(Piece("PROP_TrafficLight_01", 4.2, 6.2, [
        box((0.5, 0.5, 0.3), (0, 0, 0.15), STONE, "concrete", uv="world"),
        lathe([(0.1, 0.3), (0.085, 5.9), (0.06, 6.05)], 8, GALV),
        tube([(0, 0, 5.6), (1.5, 0, 5.75), (3.8, 0, 5.75)], 0.05, 6, GALV),
        *[box((0.32, 0.26, 0.95), (x, 0, z), BLACK) for x, z in ((3.6, 5.2), (0.0, 2.9))],
        *[cyl(0.1, 0.04, (x, -0.14, z + dz), 8, c, "lamp", axis="y") for x, z in ((3.6, 5.2), (0.0, 2.9))
          for dz, c in ((0.3, "#C8282E"), (0.0, "#E8B931"), (-0.3, "#2E9D4E"))]], 900, bevel=0.008, refs=["gf_17", "gf_18"]))
    for i, (col, row) in enumerate(((1, 5), (2, 5), (3, 5), (0, 6), (1, 6)), 1):
        out.append(Piece(f"PROP_SignPost_{i:02d}", 1.1, 3.0, [
            lathe([(0.04, 0.0), (0.04, 3.0)], 6, GALV),
            box((1.1, 0.03, 0.28), (0, -0.06, 2.75), "#FFFFFF", "sign", uv=("sign", col, row))], 200, refs=["gf_25"]))
    # SLICE1 frontage pieces (citylib/frontage.py): feeder pillar cabinets on a plinth (gf_21 orange, gf_25 grey),
    # a galvanised tree guard (gf_24), placed by the frontage rule along named roads
    for i, col in enumerate(("#8E9384", "#C7742F"), 1):
        out.append(Piece(f"PROP_UtilityCabinet_{i:02d}", 1.1, 1.45, [
            box((1.15, 0.5, 0.18), (0, 0, 0.09), STONE, "concrete", uv="world"),
            box((1.0, 0.4, 1.12), (0, 0, 0.74), col),
            box((1.08, 0.48, 0.06), (0, 0, 1.33), col),
            box((0.02, 0.02, 0.95), (0, -0.205, 0.74), BLACK),
            box((0.42, 0.01, 0.12), (-0.22, -0.205, 1.12), "#FFFFFF" if i == 1 else "#E8C83A")], 240, bevel=0.01,
            refs=["gf_21", "gf_25"]))
    bars = [(x, y) for k in range(4) for x, y in (((-0.55 + 0.275 * k), -0.55), (0.55, (-0.55 + 0.275 * k)),
                                                  ((0.55 - 0.275 * k), 0.55), (-0.55, (0.55 - 0.275 * k)))]
    ring = [(-0.55, -0.55), (0.55, -0.55), (0.55, 0.55), (-0.55, 0.55), (-0.55, -0.55)]
    out.append(Piece("PROP_TreeGuard_01", 1.2, 1.3, [
        *[tube([(x, y, 0.0), (x, y, 1.25)], 0.018, 4, GALV_D) for x, y in bars],
        *[tube([(x, y, z) for x, y in ring], 0.02, 4, GALV_D) for z in (0.35, 1.2)]], 400, refs=["gf_24"]))
    # SLICE2: the raised median planter down the middle of Delta Road (agent h10-h14): a 6 m run of terracotta
    # ribbed concrete, 1.2 m wide (the OSM median), a pale coping; the clipped hedge on top is a vegetation
    # instance the median rule adds (VEG_Hedge_Clipped_A), so it shares the vegetation atlas and wind
    rib = "#A4532F"
    out.append(Piece("PROP_MedianPlanter_01", 6.0, 0.62, [
        box((6.0, 1.1, 0.5), (0, 0, 0.25), "#B8653F"),
        box((6.0, 1.2, 0.08), (0, 0, 0.54), "#CDBFA6"),
        array(box((0.08, 0.05, 0.42), (-2.85, -0.57, 0.25), rib), 20, (0.3, 0, 0)),
        array(box((0.08, 0.05, 0.42), (-2.85, 0.57, 0.25), rib), 20, (0.3, 0, 0)),
        box((5.9, 0.95, 0.04), (0, 0, 0.58), "#4A3A2C")], 600, refs=["h10", "h11", "h12", "h14"]))
    return out


# --- P2 traffic and seafront set (Street Catalogue; sv_03, sv_04, sv_05, sv_07, sv_09, sv_11) ------------------

RED_PLASTIC, CONE_RED, SIGN_BLUE, SLAB = "#C23A30", "#D2352B", "#1E4E9C", "#3A3C3F"


def _stripes(r, z0, z1, n=6, segs=6, at=(0.0, 0.0)):
    """Black / white painted bands up a pole's foot (sv_03): n cylinders of alternate paint."""
    step = (z1 - z0) / n
    return [cyl(r, step, (at[0], at[1], z0 + step * (k + 0.5)), segs, BLACK if k % 2 == 0 else WHITE) for k in range(n)]


def _signal_head(x, z, y=0.0):
    return [box((0.3, 0.24, 0.9), (x, y, z), BLACK), box((0.5, 0.03, 1.1), (x, y + 0.13, z), BLACK),
            *[cyl(0.09, 0.05, (x, y - 0.13, z + dz), 6, c, "lamp", axis="y")
              for dz, c in ((0.28, "#C8282E"), (0.0, "#E8B931"), (-0.28, "#2E9D4E"))]]


def _plate_post(h, plate, stripes=False):
    """A sign on a galvanised post; `plate` is the sign part (its centre near the top)."""
    return [lathe([(0.04, 0.0), (0.04, h)], 6, GALV), *(_stripes(0.045, 0.0, 1.2, 4) if stripes else []), *plate]


def traffic() -> list[Piece]:
    out = []
    # red water-filled "POLICE" barrier (sv_04, sv_09, sv_14): a swept plastic body, end lugs, the label on -y
    body = [(0.22, 0.0), (0.2, 0.08), (0.1, 0.76), (0.07, 0.84), (-0.07, 0.84), (-0.1, 0.76), (-0.2, 0.08), (-0.22, 0.0)]
    out.append(Piece("PROP_Barrier_Police_01", 1.6, 0.85, [
        sweep([(-0.72, 0, 0), (0.72, 0, 0)], body, RED_PLASTIC),
        *[box((0.12, 0.16, 0.55), (x, 0, 0.36), RED_PLASTIC) for x in (-0.76, 0.76)],
        box((0.36, 0.06, 0.04), (0, 0, 0.86), RED_PLASTIC),
        box((0.9, 0.012, 0.22), (0, -0.152, 0.5), "#FFFFFF", "sign", uv=("sign", 3, 7))], 160, refs=["sv_04", "sv_09", "sv_14"]))
    # centre-line delineator block (catalogue 4, sv_07/sv_09): red plastic block, trapezoid end profile, a stub on top;
    # upright, and knocked onto its side (its own mesh: yaw-only instances)
    out.append(Piece("PROP_Delineator_01", 0.5, 0.7, [
        sweep([(-0.25, 0, 0), (0.25, 0, 0)], [(-0.25, 0.0), (-0.14, 0.6), (0.14, 0.6), (0.25, 0.0)], RED_PLASTIC),
        cyl(0.05, 0.1, (0, 0, 0.65), 6, RED_PLASTIC)], 80, refs=["sv_07", "sv_09"]))
    out.append(Piece("PROP_Delineator_02", 0.8, 0.5, [
        sweep([(0, -0.25, 0), (0, 0.25, 0)], [(0.0, 0.0), (0.0, 0.5), (0.6, 0.39), (0.6, 0.11)], RED_PLASTIC)], 80, refs=["sv_07"]))   # no stub: it broke off
    out.append(Piece("PROP_TrafficCone_01", 0.38, 0.72, [
        box((0.38, 0.38, 0.03), (0, 0, 0.015), CONE_RED),
        lathe([(0.15, 0.03), (0.03, 0.7), (0.0, 0.71)], 8, CONE_RED),
        cyl(0.098, 0.12, (0, 0, 0.36), 8, WHITE, r2=0.077)], 140, refs=["sv_07"]))
    # cantilever signal mast (sv_11): galvanised pole on a striped foot, a 6 m arm with a brace, two heads over
    # the lanes and one at the kerb, the junction name plate on the arm (blue band, no text)
    out.append(Piece("PROP_SignalMast_01", 7.0, 7.0, [
        box((0.55, 0.55, 0.3), (0, 0, 0.15), STONE, "concrete", uv="world"),
        lathe([(0.13, 0.3), (0.11, 6.6), (0.08, 6.75)], 8, GALV), *_stripes(0.135, 0.3, 2.1, 6, 8),
        tube([(0, 0, 6.3), (6.6, 0, 6.3)], 0.07, 6, GALV), tube([(0, 0, 5.2), (2.6, 0, 6.25)], 0.04, 4, GALV),
        *_signal_head(3.4, 5.6), *_signal_head(6.1, 5.6), *_signal_head(0.0, 2.9, -0.25),
        box((1.6, 0.04, 0.4), (4.75, -0.1, 6.65), SIGN_BLUE), box((1.3, 0.045, 0.1), (4.75, -0.1, 6.65), "#5C7FB8")],
        700, refs=["sv_11", "sv_03"]))
    # striped-foot variants of the kerb lamp and the traffic light, near junction corners (sv_03)
    lamp = next(p for p in furniture() if p.name == "PROP_StreetLamp_SingleArm_01")
    out.append(Piece("PROP_StreetLamp_SingleArm_02", lamp.width, lamp.height,
                     lamp.parts + _stripes(0.14, 0.5, 2.3, 6), 950, refs=["sv_03", "gf_21"]))
    tl = next(p for p in furniture() if p.name == "PROP_TrafficLight_01")
    out.append(Piece("PROP_TrafficLight_02", tl.width, tl.height, tl.parts + _stripes(0.105, 0.3, 2.1, 6),
                     1150, bevel=0.008, refs=["sv_03", "gf_17"]))
    # three-plate direction sign on twin posts (sv_03): Sinhala and Tamil plates are blank blue bands
    # (native-speaker review), the English plate from the atlas (place names only)
    plates = []
    for z, eng in ((3.75, False), (3.05, False), (2.35, True)):
        plates.append(box((2.7, 0.03, 0.66), (0, 0.0, z), WHITE))
        if eng:
            plates.append(box((2.6, 0.03, 0.6), (0, -0.02, z), "#FFFFFF", "sign", uv=("sign", 0, 7)))
        else:
            plates += [box((2.6, 0.03, 0.6), (0, -0.02, z), SIGN_BLUE), box((1.9, 0.03, 0.2), (0, -0.03, z), "#4D72B0")]
    out.append(Piece("PROP_Sign_Direction_01", 2.7, 4.1, [
        *[box((0.1, 0.1, 4.1), (x, 0.07, 2.05), GALV) for x in (-1.0, 1.0)], *plates], 260, refs=["sv_03"]))
    out.append(Piece("PROP_Sign_PedCrossing_01", 0.6, 3.0, _plate_post(3.0, [
        box((0.6, 0.02, 0.6), (0, -0.06, 2.65), "#FFFFFF", "sign", uv=("sign", 1, 7, 0))]), 120, refs=["sv_03"]))
    out.append(Piece("PROP_Sign_Parking_01", 0.5, 2.8, _plate_post(2.8, [
        box((0.5, 0.02, 0.5), (0, -0.06, 2.5), "#FFFFFF", "sign", uv=("sign", 1, 7, 1))]), 120, refs=["sv_08"]))
    out.append(Piece("PROP_Sign_NoParking_01", 0.5, 2.8, _plate_post(2.8, [
        box((0.5, 0.02, 0.5), (0, -0.06, 2.5), "#FFFFFF", "sign", uv=("sign", 1, 7, 2))]), 120, refs=["sv_07"]))
    out.append(Piece("PROP_Sign_Chevron_01", 0.6, 2.0, _plate_post(2.0, [
        box((0.6, 0.02, 0.75), (0, -0.06, 1.55), "#FFFFFF", "sign", uv=("sign", 1, 7, 3))], stripes=True), 200,
        refs=["sv_15"]))
    out.append(Piece("PROP_CCTVPole_01", 1.0, 8.0, [
        box((0.4, 0.4, 0.25), (0, 0, 0.125), STONE, "concrete", uv="world"),
        lathe([(0.09, 0.25), (0.07, 8.0)], 6, GALV), box((0.4, 0.22, 0.55), (0, -0.16, 3.0), "#8E9384"),
        tube([(0, 0, 7.6), (0.7, 0, 7.6)], 0.03, 4, GALV), box((0.38, 0.16, 0.16), (0.8, 0, 7.5), WHITE),
        cyl(0.11, 0.12, (0.0, 0, 8.05), 8, WHITE)], 240, refs=["sv_03"]))
    # seafront bus shelter (sv_05): plinth, silver posts, a flat dark roof slab, back-lit fictional ad panels at the
    # ends of the back wall, slatted benches; three bays, its front (-y) to the road
    post = lambda x, y: box((0.1, 0.1, 2.6), (x, y, 1.45), GALV)  # noqa: E731
    bench = lambda x: [array(box((1.7, 0.07, 0.03), (x, 0.25, 0.6), "#B5B9B6"), 3, (0, 0.09, 0)),  # noqa: E731
                       *[box((0.05, 0.3, 0.45), (x + dx, 0.34, 0.37), IRON) for dx in (-0.75, 0.75)]]
    out.append(Piece("PROP_BusShelter_Seafront_01", 7.6, 2.9, [
        box((7.6, 2.2, 0.15), (0, 0.1, 0.075), STONE, "concrete", uv="world"),
        *[post(x, 0.8) for x in (-3.6, -1.2, 1.2, 3.6)], *[post(x, -0.7) for x in (-3.6, 3.6)],
        box((7.9, 2.5, 0.16), (0, 0.05, 2.83), SLAB), box((7.9, 0.06, 0.24), (0, -1.2, 2.75), GALV_D),
        *[box((1.3, 0.12, 1.95), (x, 0.82, 1.3), GALV) for x in (-2.4, 2.4)],
        *[box((1.16, 0.02, 1.74), (x, 0.755, 1.3), "#FFFFFF", "sign", uv=("sign", 2, 7, q))
          for x, q in ((-2.4, 0), (2.4, 1))],
        *[box((1.2, 0.02, 0.03), (x, 0.75, 2.22), CREAM, "lamp") for x in (-2.4, 2.4)],
        box((2.3, 0.03, 1.4), (0, 0.84, 1.15), GALV_D),
        *bench(-1.0), *bench(1.4),
        box((1.4, 0.04, 0.35), (-2.4, -1.25, 2.45), "#FFFFFF", "sign", uv=("sign", 0, 5))], 1200, bevel=0.008,
        refs=["sv_05", "sv_03"]))
    # small land-side booth halt (east kerb): beige box, open front, bench, flat roof
    beige = "#D9CDB2"
    out.append(Piece("PROP_BusShelter_Booth_01", 2.6, 2.7, [
        box((2.5, 0.12, 2.3), (0, 0.65, 1.15), beige, uv="body"),
        *[box((0.12, 1.4, 2.3), (x, 0.0, 1.15), beige, uv="body") for x in (-1.19, 1.19)],
        box((2.8, 1.8, 0.14), (0, 0.0, 2.37), "#8C8478"),
        box((2.1, 0.4, 0.05), (0, 0.4, 0.46), "#5B4636"), box((2.1, 0.06, 0.44), (0, 0.55, 0.22), beige),
        box((1.4, 0.04, 0.35), (0, -0.72, 2.12), "#FFFFFF", "sign", uv=("sign", 0, 5))], 330, bevel=0.01,
        refs=["sv_12"]))
    # white promenade kiosk (sv_07): white cabin on a plinth, sliding service windows, overhanging flat roof,
    # a fictional sponsor poster on the -x side wall
    out.append(Piece("PROP_Kiosk_White_01", 2.6, 2.7, [
        box((2.6, 2.0, 0.12), (0, 0, 0.06), STONE, "concrete", uv="world"),
        box((2.4, 1.8, 2.3), (0, 0, 1.27), WHITE, uv="body"),
        box((1.7, 0.03, 0.85), (0, -0.91, 1.45), "#55646A"),
        *[box((0.04, 0.05, 0.9), (x, -0.93, 1.45), SHOP_FRAME) for x in (-0.87, 0.0, 0.87)],
        box((1.9, 0.35, 0.05), (0, -1.05, 0.98), GALV),
        box((2.9, 2.3, 0.12), (0, 0, 2.48), WHITE),
        box((0.03, 0.8, 1.2), (-1.215, 0, 1.4), "#FFFFFF", "sign", uv=("sign", 2, 7, 3))], 420, bevel=0.01,
        refs=["sv_07"]))
    return out


def pieces() -> dict[str, Piece]:
    out = {}
    from . import street_kit_life   # P140: bus halts, vendor stalls, traffic control (imports this module's helpers)
    for p in (promenade() + shopfronts() + upper() + plaster() + signs() + furniture() + traffic()
              + street_kit_life.pieces()):
        out[p.name] = p
    return out


TRIS_JSON = os.path.join(os.path.dirname(__file__), "street_kit_tris.json")


def measured_tris() -> dict[str, int]:
    """LOD0 triangles per piece as the last Blender build measured them (written by gn/street.build)."""
    if not os.path.exists(TRIS_JSON):
        return {n: p.budget for n, p in pieces().items()}
    return json.load(open(TRIS_JSON, encoding="utf-8"))


def max_extent(piece: Piece) -> tuple[float, float]:
    """(min z, max z) of the boxes, lathes and tubes, for the unit tests' height checks."""
    lo, hi = 1e9, -1e9

    def visit(part, oz=0.0):
        nonlocal lo, hi
        t = part["t"]
        if t == "box":
            z, h = part["at"][2] + oz, part["size"][2] / 2
            lo, hi = min(lo, z - h), max(hi, z + h)
        elif t == "cyl" and part.get("axis", "z") == "z":
            z = part["at"][2] + oz   # `at` is the base
            lo, hi = min(lo, z), max(hi, z + part["depth"])
        elif t == "lathe":
            for _, z in part["prof"]:
                lo, hi = min(lo, z + part["at"][2] + oz), max(hi, z + part["at"][2] + oz)
        elif t == "tube":
            for p in part["pts"]:
                lo, hi = min(lo, p[2] + oz), max(hi, p[2] + oz)
        elif t == "sweep":
            zs = [z for _, z in part["prof"]]
            for p in part["path"]:
                lo, hi = min(lo, p[2] + oz + min(zs)), max(hi, p[2] + oz + max(zs))
        elif t == "array":
            visit(part["part"], oz)
            visit(part["part"], oz + part["step"][2] * (part["count"] - 1))
    for p in piece.parts:
        visit(p)
    return lo, hi
