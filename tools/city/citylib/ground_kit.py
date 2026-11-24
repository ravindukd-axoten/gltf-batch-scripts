"""B1 ground kit: kerbs, junction corners, crossings, road decals, humps, studs, covers, drains, decks (P292).

Pure Python (no bpy), unit-tested (tests/test_ground_kit.py). Same contract as the street kit (citylib/street_kit.py,
TDD "Street kit as built"): a piece is a list of parts that `citylib/ground_build.py` turns into Geometry Nodes
(street-kit part types plus `fill`, `quad`, `shelf`) and a piece-level `drop` field (dropped-kerb ramps). Python
only says what and where; the shapes are node groups that stay editable in the saved .blend.

Frame: x east/along, y north, z up, pivot on the road surface (z = 0). Road decals: the far end of the legend (top
of the letters, travel direction) is +y; the driver's right is +x (glTF: facing +Z, like the rest of the kit).
Sweeps: the street-kit convention, profile (y, z) for a path along +x with y < 0 to the right of travel. `side()`
writes profiles as r = metres to the right of travel, so a path walked with the footway on its right keeps the
road on the left.

Materials and UVs (`mat` role -> material, `uv`):
  kit      MAT_StreetKit_A  painted parts (HeroLit: COLOR_0 paint x the trim's flat strip)   uv "trim"
  street   MAT_StreetTrim_A kerb faces, gutter, manhole                                    uv ("row", <name>)
  paintb   MAT_RoadPaint_B  B1 road-paint glyph atlas (citylib/ground_paint.py)              uv ("cell", <glyph>)
  painta   MAT_RoadPaint_A  existing atlas cells (patch, wear; citylib/paint_atlas.py)        uv ("cella", <cell>)
  concrete / plaza / brick / asphalt / rock  world materials at real scale                  uv "world"
Textured faces carry white paint (the shader ignores COLOR_0 rgb there; AO still goes to alpha).

References (references/delta-face, streetview NOTES): sv_03 (NW plaza at the south roundabout: brick plaza, grey
kerb, striped pole foot, give-way sign), sv_04 (flared plaza, red channelling barriers), sv_11 (ITC zebra and signal
masts), sv_14 (dashed lanes, red barriers), gf_18 (zebra, yellow box, splitter gores, red pavers), agent aerial b3
(signal crossing). Sizes: Sri Lankan RDA kerb 150 mm upstand, dropped kerb 25 mm, tactile 0.8 m deep, guard rail
1.0 m, hump 3.7 m x 75 mm (row WS-0017), studs 100 mm (WS-0018).
"""
from __future__ import annotations

import json
import math
import os

from . import street_kit as SK
from .street_kit import Piece, box, cyl, lathe, sweep, tube

ROLES = {"street": "MAT_StreetTrim_A", "paintb": "MAT_RoadPaint_B", "painta": "MAT_RoadPaint_A",
         "plaza": "MAT_PlazaPaver", "brick": "MAT_HerringbonePaver", "asphalt": "MAT_Asphalt",
         "rock": "MAT_RockArmour", "cobble": "MAT_GreyCobble"}
# StreetTrim_A rows in UV v (tools/textures/build_textures.build_street_trim): kerb, white, yellow, zebra, gutter;
# "manhole" is the square cover cell in the gutter row (u 3.1-3.9 m of the 4 m sheet)
TRIM_ROWS = {"kerb": (0.0, 0.25), "white": (0.25, 0.375), "yellow": (0.375, 0.5), "zebra": (0.5, 0.75),
             "gutter": (0.75, 1.0)}
MANHOLE_UV = (0.775, 0.775, 0.975, 0.975)
TRIM_SHEET_M = 4.0

WHITE, BLACK, GALV, IRON = "#FFFFFF", SK.BLACK, SK.GALV, SK.IRON
KERB_YELLOW = "#D2A73C"            # Art Bible lane yellow (chipped, faded)
KERB_WHITE = "#E6E1D6"             # painted kerb white, a little dusty
TACTILE = "#C9A646"                # buff-yellow blister / corduroy tiles on new Cityhub footways
GRANITE = "#8E8C88"
STUD_BODY, STUD_WHITE, STUD_AMBER = "#9B9EA0", "#F2F0E8", "#E39A1E"

KERB_UP = 0.15                     # kerb upstand above the road (m)
KERB_DROP = 0.125                  # dropped kerb: 25 mm upstand left
GROUND_JSON = os.path.join(os.path.dirname(__file__), "..", "data", "ground_kit_tris.json")


# --- helpers (data only) ----------------------------------------------------------------------------

def side(prof_r):
    """Profile written as (r right of travel, z) -> the street-kit sweep convention (y = -r)."""
    return [(-r, z) for r, z in prof_r]


def kerb_prof(lod=0):
    """Concrete/granite kerb (sv_03, sv_11): batter face to the road (left), 20 mm chamfer, 180 mm top, 100 mm
    below the road so a dropped run never shows a gap."""
    if lod:
        return side([(-0.10, -0.10), (-0.10, KERB_UP), (0.09, KERB_UP), (0.09, -0.10)])
    return side([(-0.10, -0.10), (-0.10, 0.0), (-0.085, KERB_UP - 0.02), (-0.065, KERB_UP), (0.09, KERB_UP),
                 (0.09, -0.10)])


def arc(cx, cy, r, a0, a1, n, z=0.0):
    """Points on a circular arc (degrees, counter-clockwise from +x), n segments."""
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * k / n)), z) for k in range(n + 1)]


def fill(path2d, z0, z1, paint=WHITE, mat="plaza", uv="world"):
    """Closed outline filled (GN Fill Curve) and extruded from z0 to z1 (an island or a slab)."""
    return {"t": "fill", "path": [tuple(p[:2]) for p in path2d], "z0": z0, "z1": z1, "paint": paint, "mat": mat,
            "uv": uv}


def quad(w, l, at=(0.0, 0.0, 0.004), paint=WHITE, mat="paintb", uv=None, rot=0.0):
    """One flat quad (2 tris), w across (x) by l along (y): a road decal."""
    return {"t": "quad", "size": (w, l), "at": at, "paint": paint, "mat": mat, "uv": uv, "rot": rot}


def drop(cx, cy, axis, half, flare, depth, amount=KERB_DROP):
    """Piece-level field: lower everything above z = 0.1 by `amount` over |s - c| < half (linear flares of `flare`),
    fading to nothing `depth` metres behind the kerb. axis 'x': crossing on a kerb running along x at y = cy, the
    footway at y > cy; axis 'y': kerb along y at x = cx, footway at x > cx."""
    return {"axis": axis, "c": (cx, cy), "half": half, "flare": flare, "depth": depth, "amount": amount}


class GPiece(Piece):
    """A street-kit Piece plus the ground extras: piece-level drop fields, sockets (name -> (x, y, z)), the
    inventory row it answers, its manifest kind and LOD1 (None = no LOD1: decals, studs)."""

    def __init__(self, name, width, height, parts, budget, row, kind, sockets=None, drops=None, lod1=None,
                 refs=None, bevel=0.0, note=""):
        super().__init__(name, width, height, parts, budget, bevel=bevel, refs=refs or [])
        self.row, self.kind, self.note = row, kind, note
        self.sockets = sockets or {}
        self.drops = drops or []
        self.lod1 = lod1


# --- kerbs (WS-0055, Art Bible street furniture: kerbs painted black and white) -------------------------

def _kerb_run(x0, x1, paints, lod, seg=0.5, mat="kit", uv="trim"):
    """A straight kerb from x0 to x1 in blocks of `seg`, painted in turn (one block per paint when only one)."""
    n = max(1, round((x1 - x0) / seg)) if len(paints) > 1 else 1
    step = (x1 - x0) / n
    # walked towards -x so the footway (right of travel) is +y and the road face looks -y (glTF +Z, the kit front)
    return [sweep([(x0 + (k + 1) * step, 0, 0), (x0 + k * step, 0, 0)], kerb_prof(lod), paints[k % len(paints)],
                  mat, uv=uv) for k in range(n)]


def kerbs(lod=0) -> list[GPiece]:
    out = []
    for name, paints, note in (
            ("KIT_Kerb_Straight_D_Yellow_A", [KERB_YELLOW], "no-stopping kerb, inland and at bus halts"),
            ("KIT_Kerb_Straight_D_YellowBlack_A", [KERB_YELLOW, BLACK], "yellow-black no-stopping kerb, 0.5 m blocks"),
            ("KIT_Kerb_Straight_D_BlackWhite_A", [KERB_WHITE, BLACK], "black-and-white kerb at roundabouts and islands")):
        out.append(GPiece(name, 1.0, KERB_UP, _kerb_run(-0.5, 0.5, paints, lod), 64, "WS-0055", "kit_small",
                          refs=["sv_03", "gf_18", "Art Bible street furniture"], note=note))
    # a plain StreetTrim kerb 1 m block: the textured kerb row (the cells' own kerb), for kit corners and islands
    out.append(GPiece("KIT_Kerb_Straight_D_Grey_A", 1.0, KERB_UP,
                      _kerb_run(-0.5, 0.5, [WHITE], lod, mat="street", uv=("row", "kerb")), 64, "WS-0055",
                      "kit_small", refs=["sv_03", "sv_11"], note="unpainted kerb on the StreetTrim kerb row"))
    # dropped kerb crossover, 3 m: 1.8 m at 25 mm, 0.6 m flares (sv_11 crossing; tactile in the corner pieces)
    out.append(GPiece("KIT_Kerb_Dropped_A", 3.0, KERB_UP,
                      [sweep([(x, 0, 0) for x in (1.5, 0.9, -0.9, -1.5)], kerb_prof(lod), WHITE, "street",
                             uv=("row", "kerb"))], 120, "WS-0086", "kit_small",
                      drops=[drop(0.0, 0.0, "x", 0.9, 0.6, 1.2)], refs=["sv_11", "agent aerial b3"],
                      note="kerb only; the ramp and tactile come with the corner pieces"))
    return out


# --- junction corners (WS-0086 signalised corner, WS-0095 flared plaza corner) ---------------------------

def _corner(name, R, W, tail, lod, row, refs, plaza_mat="plaza", rail=True, kerb_paints=None, note="",
            crossings=True, budget=1500):
    """A kerbed corner: arc of radius R between two straight tails, the footway band W wide behind it, dropped
    kerbs with a tactile pad at each crossing (one per arm), a pedestrian guard rail along the arc between the
    crossings, sockets for the signal posts, push buttons, zebras and striped pole feet.
    Roads lie at y < 0 (arm A along x) and x < 0 (arm B along y); the footway is the block at x, y > 0.
    The path runs tail A (towards -x) -> arc -> tail B (towards +y): the footway is on its right."""
    n = 6 if lod else 14
    xc = R + tail / 2                                   # crossing centres on each tail
    tA = [(R + tail, 0, 0), (xc + 1.6, 0, 0), (xc + 0.9, 0, 0), (xc - 0.9, 0, 0), (xc - 1.6, 0, 0), (R, 0, 0)]
    tB = [(0, xc - 1.6, 0), (0, xc - 0.9, 0), (0, xc + 0.9, 0), (0, xc + 1.6, 0), (0, R + tail, 0)]
    if not crossings:
        tA, tB = [(R + tail, 0, 0), (R, 0, 0)], [(0, R + tail, 0)]
    path = tA + arc(R, R, R, 270, 180, n)[1:] + tB
    parts = []
    kmat, kuv = ("street", ("row", "kerb")) if not kerb_paints else ("kit", "trim")
    if kerb_paints:   # painted kerb blocks along the whole path, ~1 m each
        for a, b in zip(path, path[1:]):
            L = math.dist(a[:2], b[:2])
            k = max(1, round(L))
            for j in range(k):
                p0 = tuple(a[i] + (b[i] - a[i]) * j / k for i in range(3))
                p1 = tuple(a[i] + (b[i] - a[i]) * (j + 1) / k for i in range(3))
                parts.append(sweep([p0, p1], kerb_prof(lod), kerb_paints[len(parts) % len(kerb_paints)], kmat, uv=kuv))
    else:
        parts.append(sweep(path, kerb_prof(lod), WHITE, kmat, uv=kuv))
    # footway band: one slab profile swept along the same path (conforms to the arc), a vertex at the ramp depth
    parts.append(sweep(path, side([(0.09, -0.05), (0.09, KERB_UP), (1.2, KERB_UP), (W, KERB_UP), (W, -0.05)]),
                       WHITE, plaza_mat, uv="world"))
    drops, sockets = [], {}
    if crossings:
        drops = [drop(xc, 0.0, "x", 0.9, 0.7, 1.2), drop(0.0, xc, "y", 0.9, 0.7, 1.2)]
        # tactile blister pads: 0.8 m deep behind the dropped kerb, the drop field tilts them with the ramp
        parts += [box((1.8, 0.8, 0.014), (xc, 0.09 + 0.4, KERB_UP + 0.007), TACTILE, "kit"),
                  box((0.8, 1.8, 0.014), (0.09 + 0.4, xc, KERB_UP + 0.007), TACTILE, "kit")]
        sockets = {"Signal_A": (xc + 1.9, 0.6, KERB_UP), "Signal_B": (0.6, xc + 1.9, KERB_UP),
                   "PushButton_A": (xc + 1.9, 0.6, 1.05), "PushButton_B": (0.6, xc + 1.9, 1.05),
                   "Zebra_A": (xc, -3.0, 0.0), "Zebra_B": (-3.0, xc, 0.0)}
    if rail:
        # pedestrian guard rail (galvanised, 1.0 m) 0.45 m behind the kerb along the arc, posts ~2 m apart
        ra = arc(R, R, R - 0.45, 270, 180, 6 if lod else 10)
        run = [(xc - 1.9, 0.45, 0)] + [p for p in ra] + [(0.45, xc - 1.9, 0)]
        for z in ((1.0, 0.55) if lod else (1.0, 0.55, 0.15)):
            parts.append(tube([(x, y, KERB_UP + z) for x, y, _ in run], 0.024, 4 if lod else 6, GALV))
        posts = run[::2] + ([run[-1]] if len(run) % 2 == 0 else [])
        parts += [cyl(0.028, 1.02, (x, y, KERB_UP + 0.51), 4 if lod else 6, GALV) for x, y, _ in posts]
    sockets["StripedBase"] = (R * (1 - math.sqrt(0.5)) + 0.6, R * (1 - math.sqrt(0.5)) + 0.6, KERB_UP)
    return GPiece(name, R + tail, KERB_UP, parts, budget, row, "kit_large", sockets=sockets, drops=drops,
                  refs=refs, note=note)


def corners(lod=0) -> list[GPiece]:
    return [
        _corner("KIT_JunctionCorner_Signal_A", 6.0, 3.5, 6.0, lod, "WS-0086", ["sv_11", "sv_03", "agent aerial b3"],
                note="signalised corner: R6 kerb, two dropped crossings with tactile, guard rail, sockets"),
        _corner("KIT_RoundaboutPlaza_Corner_A", 13.0, 8.0, 4.0, lod, "WS-0095", ["sv_03", "sv_04", "gf_18"],
                rail=False, crossings=False, plaza_mat="brick",
                note="flared roundabout plaza corner (sv_03): R13 grey kerb, 8 m brick plaza, no rail"),
    ]


# --- roundabout splitter island (WS-0095, gf_18 splitter gores) ------------------------------------------

def splitter(lod=0) -> list[GPiece]:
    """Teardrop splitter island at a roundabout arm: 9 m long, 2.6 m at the give-way end, a 0.6 m nose; black and
    white kerb blocks (Art Bible), a brick top (gf_18 shows paved islands). Path walked clockwise (top view) so the
    island is on the right of travel."""
    L, hw, rn = 9.0, 1.3, 0.6
    n = 4 if lod else 8
    nose = arc(0.0, L - rn, rn, 0, 180, n)                     # far end (+y), counter-clockwise from +x
    cw = [(hw, 0.0, 0.0), (-hw, 0.0, 0.0), *reversed(nose), (hw, 0.0, 0.0)]   # clockwise: island on the right
    parts = []
    for a, b in zip(cw, cw[1:]):
        k = max(1, round(math.dist(a[:2], b[:2])))
        for j in range(k):
            p0 = tuple(a[i] + (b[i] - a[i]) * j / k for i in range(3))
            p1 = tuple(a[i] + (b[i] - a[i]) * (j + 1) / k for i in range(3))
            parts.append(sweep([p0, p1], kerb_prof(lod), (KERB_WHITE, BLACK)[len(parts) % 2], "kit"))
    inner = [(hw - 0.09, 0.09)] + [(x * (rn - 0.09) / rn, (L - rn) + (y - (L - rn)) * (rn - 0.09) / rn)
                                    for x, y, _ in nose] + [(-hw + 0.09, 0.09)]
    parts.append(fill(inner, -0.05, KERB_UP - 0.01, WHITE, "brick"))
    return [GPiece("KIT_SplitterIsland_Nose_A", 2 * hw, KERB_UP, parts, 900, "WS-0095", "kit_small",
                   sockets={"Sign_KeepLeft": (0.0, L - 1.0, KERB_UP), "Bollard": (0.0, 1.0, KERB_UP)},
                   refs=["gf_18", "sv_04"], note="splitter island nose; the hatched gore paint is a decal")]


# --- surface pieces: hump, studs, covers, drains, footpath ----------------------------------------------

def surface(lod=0) -> list[GPiece]:
    out = []
    # WS-0017 speed hump: 3.7 m along travel x 75 mm, full 3.5 m lane, chevrons from the B atlas on top
    hump = [(-1.85, 0.0), (-1.25, 0.03), (-0.6, 0.065), (0.0, 0.075), (0.6, 0.065), (1.25, 0.03), (1.85, 0.0)]
    if lod:
        hump = [(-1.85, 0.0), (-0.7, 0.06), (0.7, 0.06), (1.85, 0.0)]
    # path across the lane (+x), profile along travel: r = -y (the chevrons point +y)
    out.append(GPiece("KIT_SpeedHump_Painted_A", 3.5, 0.075,
                      [sweep([(-1.75, 0, 0), (1.75, 0, 0)], [(y, z) for y, z in hump] + [(1.85, -0.02), (-1.85, -0.02)],
                             WHITE, "paintb", uv=("cell", "HUMP_CHEVRON"))], 40, "WS-0017", "marking",
                      refs=["row WS-0017"], note="asphalt hump with white chevrons; placement waits on a Delta Face ref"))
    # WS-0018 road studs: a 100 mm wedge (two reflective slopes), 8 tris; white (centre) and amber (edge)
    for nm, c in (("PROP_RoadStud_White_A", STUD_WHITE), ("PROP_RoadStud_Amber_A", STUD_AMBER)):
        out.append(GPiece(nm, 0.1, 0.02, [sweep([(-0.05, 0, 0), (0.05, 0, 0)],
                                                [(-0.05, 0.0), (0.0, 0.02), (0.05, 0.0)], c, "kit")],
                          8, "WS-0018", "prop_small", refs=["row WS-0018"], note="culled beyond 40 m on Low"))
    # WS-0019 utility covers in the carriageway: a pale older patch (RoadPaint_A PATCH_B cell), the square-framed
    # manhole from the StreetTrim gutter row, a cast-iron valve box and a small round cover
    out.append(GPiece("KIT_UtilityCoverCluster_Road_A", 1.8, 0.03, [
        quad(1.8, 4.5, (0.0, 0.0, 0.003), WHITE, "painta", ("cella", "PATCH_B")),
        box((0.8, 0.8, 0.03), (0.0, 0.6, 0.0), WHITE, "street", uv=("manhole",)),
        box((0.32, 0.46, 0.02), (0.15, -0.6, 0.004), IRON, "kit"),
        cyl(0.2, 0.02, (-0.35, -1.4, 0.004), 8 if lod else 12, IRON),
    ], 120, "WS-0019", "marking", refs=["row WS-0019", "StreetTrim_A manhole cell (agent h16)"],
        note="covers 4-10 mm proud of the patch; patch quad 1.8 x 4.5 m"))
    # drains: the gutter channel with its grate (StreetTrim gutter row, 2 m) and a run of loose concrete drain
    # cover slabs over a roadside channel (Cityhub inland roads)
    out.append(GPiece("KIT_Drain_GutterGrate_A", 2.0, 0.02, [
        sweep([(-1.0, 0, 0), (1.0, 0, 0)], [(-0.25, 0.0), (-0.1, -0.02), (0.1, -0.02), (0.25, 0.0), (0.25, -0.08), (-0.25, -0.08)],
              WHITE, "street", uv=("row", "gutter"))], 60, "WS-0019", "kit_small",
        refs=["StreetTrim_A gutter row"], note="dished gutter at the kerb foot, grate in the middle"))
    slabs = []
    for k, (dx, rot, dz) in enumerate(((0.0, 0.0, 0.0), (0.02, 0.025, 0.006), (-0.01, -0.02, 0.0), (0.03, 0.01, 0.012))):
        x = -0.95 + k * 0.63 + dx
        slabs.append(box((0.6, 0.9, 0.08), (x, 0.0, 0.04 + dz), "#B7B0A4", "concrete", rot=rot, uv="world"))
        if not lod:
            slabs += [box((0.06, 0.03, 0.01), (x, sgn * 0.3, 0.081 + dz), "#3A3632", "kit", rot=rot) for sgn in (-1, 1)]
    slabs.append(box((2.7, 1.2, 0.06), (0.0, 0.0, -0.02), "#8F877C", "concrete", uv="world"))
    out.append(GPiece("KIT_Drain_CoverSlabs_A", 2.7, 0.1, slabs, 200, "WS-0019", "kit_small",
                      refs=["Art Bible street furniture: drains"],
                      note="four lifted slabs over a channel edge, slightly uneven (inland roads)"))
    # WS-0071 Delta Road footpath: 2 m run, 3.2 m wide: kerb, 0.3 m granite edge band, red-brown brick pavers, a
    # 0.3 m corduroy guidance band 1.0 m in (ridges across the walk direction)
    fp = [*_kerb_run(-1.0, 1.0, [WHITE], lod, mat="street", uv=("row", "kerb")),
          box((2.0, 0.3, 0.2), (0.0, 0.24, KERB_UP - 0.1), GRANITE, "cobble", uv="world"),
          box((2.0, 2.81, 0.2), (0.0, 0.09 + 0.3 + 1.405, KERB_UP - 0.1), WHITE, "brick", uv="world"),
          box((2.0, 0.3, 0.012), (0.0, 1.15, KERB_UP + 0.006), TACTILE, "kit")]
    if not lod:
        fp.append({"t": "array", "part": box((2.0, 0.025, 0.008), (0.0, 1.03, KERB_UP + 0.016), TACTILE, "kit"),
                   "count": 4, "step": (0.0, 0.08, 0.0)})
    out.append(GPiece("KIT_Footpath_BrickTactile_A", 2.0, KERB_UP + 0.02, fp, 260, "WS-0071", "kit_small",
                      refs=["gf_24", "gf_21", "agent h08/h16 herringbone"],
                      note="brick (hotel herringbone material) with granite edge and corduroy band"))
    return out


# --- road-paint decals on the B atlas (WS-0025 glyphs; WS-0043, WS-0044) -----------------------------------

DECALS = {   # piece -> (glyph cell, width x, length y, row)
    "KIT_RoadMarking_Baladaksha_A": ("BALADAKSHA", 2.4, 6.0, "WS-0043"),
    "KIT_RoadMarking_Slow_A": ("SLOW", 2.0, 5.0, "WS-0044"),
    "KIT_RoadMarking_ArrowStraightLeft_A": ("ARROW_STRAIGHT_LEFT", 1.4, 3.5, "WS-0025"),
    "KIT_RoadMarking_ArrowStraightRight_A": ("ARROW_STRAIGHT_RIGHT", 1.4, 3.5, "WS-0025"),
    "KIT_RoadMarking_GiveWay_A": ("GIVE_WAY", 1.4, 3.5, "WS-0025"),
    "KIT_RoadMarking_BoxHatch_A": ("BOX_HATCH", 3.2, 8.0, "WS-0025"),
    "KIT_RoadMarking_BayEnd_A": ("WHEEL_STOP", 1.0, 2.5, "WS-0025"),
}


def decals(lod=0) -> list[GPiece]:
    return [GPiece(n, w, 0.004, [quad(w, l, uv=("cell", g))], 2, row, "marking",
                   refs=["paint_atlas.py conventions", "sv_06 legends"],
                   note="opaque decal quad on the B atlas (own asphalt), no LOD1, culled like road paint")
            for n, (g, w, l, row) in DECALS.items()]


# --- concrete road deck (WS-0005 flyover / rail bridge) -------------------------------------------------

def deck(lod=0) -> list[GPiece]:
    """10 m of one-carriageway deck (7.5 m kerb to kerb + two 0.5 m parapet strips): broom-finished concrete
    slab, a tapered box girder below, F-shape (New Jersey) concrete parapets both sides."""
    Wd = 8.5
    jersey = [(0.0, 0.0), (0.0, 0.075), (0.18, 0.33), (0.23, 0.81), (0.4, 0.81), (0.4, 0.0)]
    if lod:
        jersey = [(0.0, 0.0), (0.2, 0.33), (0.23, 0.81), (0.4, 0.81), (0.4, 0.0)]
    parts = [box((10.0, Wd, 0.25), (0.0, 0.0, -0.125), WHITE, "concrete", uv="world"),
             sweep([(-5.0, 0, -0.25), (5.0, 0, -0.25)], [(2.6, 0.0), (1.8, -1.3), (-1.8, -1.3), (-2.6, 0.0)],
                   WHITE, "concrete", uv="world")]
    for sgn in (-1, 1):   # r = 0 at the road toe, 0.4 at the vertical back on the deck edge
        edge = sgn * Wd / 2
        prof = [(edge - sgn * (0.4 - r), z) for r, z in jersey]
        parts.append(sweep([(-5.0, 0, 0), (5.0, 0, 0)], prof, WHITE, "concrete", uv="world"))
    out = [GPiece("KIT_RoadDeck_Concrete_A", 10.0, 0.81, parts, 400, "WS-0005", "kit_large",
                  refs=["row WS-0005 (Baladaksha flyover 2026, Justice Akbar rail bridge)"],
                  note="10 m deck segment; joints every ~30 m are KIT_RoadDeck_Joint_A")]
    # expansion joint: steel cover plate across the carriageway and two edge angles, 40 tris
    out.append(GPiece("KIT_RoadDeck_Joint_A", 7.5, 0.012, [
        box((0.3, 7.5, 0.012), (0.0, 0.0, 0.006), "#6F7070", "kit"),
        box((0.06, 7.5, 0.008), (-0.2, 0.0, 0.004), "#4A4B4C", "kit"),
        box((0.06, 7.5, 0.008), (0.2, 0.0, 0.004), "#4A4B4C", "kit")], 40, "WS-0005", "marking",
        refs=["row WS-0005"], note="steel joint plate, flush with the deck, runs across x"))
    return out


# --- rock shelf below the seawall (WS-0242) ---------------------------------------------------------------

def shelf(lod=0) -> list[GPiece]:
    """Flat, worn rock platform 20 x 6 m with algae: a GN grid displaced by noise, the rim pulled down under the
    sand / water, paint from height (green algae low and wet, grey-brown dry rock high) (gf_03, gf_04)."""
    return [GPiece("KIT_RockShelfBelowThe_01", 20.0, 1.5, [
        {"t": "shelf", "size": (20.0, 6.0), "verts": (11, 5) if lod else (21, 9), "h": 0.7, "rim": 1.1,
         "low": "#40503A", "wet": "#5A554B", "dry": "#8C8476", "mat": "rock", "uv": "world", "paint": "#8A8172"}],
        400, "WS-0242", "kit_small", refs=["gf_03", "gf_04"], note="flat rock platform; algae by height in COLOR_0")]


def pieces(lod=0) -> dict[str, GPiece]:
    out = {}
    for p in kerbs(lod) + corners(lod) + splitter(lod) + surface(lod) + decals(lod) + deck(lod) + shelf(lod):
        out[p.name] = p
    return out


def measured_tris() -> dict:
    """{piece: {"lod0": n, "lod1": n|None}} as the last Blender build measured them (written by ground_build)."""
    if not os.path.exists(GROUND_JSON):
        return {}
    with open(GROUND_JSON, encoding="utf-8") as fh:
        return json.load(fh)
