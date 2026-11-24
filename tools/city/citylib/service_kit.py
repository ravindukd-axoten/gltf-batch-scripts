"""Service-centre KIT (P224, from the P220 research; polish round 1 P229 from the P227 critic): lifts, truss shed,
wash tunnel, hand-wash bay, pylon, workshop wall, reception, tuk-works shed, props.

Source: docs/research/vehicle-service-centres-sri-lanka.md section 6 (ranked kit list, budgets) and the agent photos
`.claude/agent-refs-garage-2026-11-21/ref_01..16` (shapes and proportions only: nothing traced, no real lettering, no
brands). Data: data/places/{KIT,PROP,DEC}_*.json (schema place_kit, extended with the service anchors) and
data/places/service_operators.json (three invented operators, palettes and placeholder wordmarks, doc section 7).

  PROP_Lift_TwoPost_A      photos 3, 5, 6: red two-post lift; node `Carriage` (carriage, arms, pads) raises
  PROP_Lift_SinglePost_A   photo 14: in-ground tuk hoist; node `Frame` raises, node `Ram` scales in height
  PROP_Lift_BikeScissor_A  photo 13: blue platform; node `Deck` raises, node `Legs` scales in height
  KIT_TrussShed_Module_A/B/C photos 3, 5, 6, 9: 4 m bay of a galvanised truss shed, span from data (A/B 10 m one lift
                           row; C 26 m, two rows facing an aisle, wet floor, operator wordmark on the fascia)
  KIT_WashTunnel_A         photos 2, 4, 7: 18 m tunnel, red box portals with lit banner, brush rolls, spray arches,
                           FX_* mist / foam / spray anchors, wet floor, no-entry plate on the exit
  KIT_HandWashBay_A        photos 10, 11: open lean-to shed, tiled dado, drain, hose reel, tool rack, foam buckets
  PROP_Pylon_Service_A     photos 1, 8: plinth and planter, mast, lit head with wordmark, 6 lit slats (text bars are
                           placeholders: people write the real text)
  PROP_WorkshopWall_A      photos 3, 16: roll cab, notice board, parts shelf, oil-can shelf, wall cabinet, air-line reel
  KIT_Reception_A          photo 6: glass office corner, counter, plastic chairs under the eave, AC units
  KIT_TukWorks_Shed_A      photos 14, 15, 16: block-wall lean-to, mono-pitch roof, eave bench, post board
  PROP_ToolCart_A, PROP_OilDrainer_A, PROP_Compressor_A, PROP_TrolleyJack_A, PROP_OilDrum_A, PROP_TyreStack_A,
  PROP_TyreRack_A, DEC_ServiceFloor_A

Moving lift parts are their own glTF child nodes (`<piece>__<Node>` here, exported as children named `<Node>` with
extras pi_move = raise | scale_y, pi_travel_m), pivot at the rest position, so Unity raises them by transform (research
section 6, rank 2). `demo_pieces()` builds raised whole variants for review renders only; they are never exported.

Pure Python (no bpy). Kit frame as in places_kit: x right, Blender y = Unity z forward, z up; pivot on the ground.
Parts wrapped in `detail()` are LOD0 only (`_LOD1` sibling node drops them).
"""
from __future__ import annotations

import json
import math
import os

from . import street_kit as SK
from .fuel_kit import _mark, detail, details, far_sides, to_blender, wordmark
from .street_kit import Piece, array, box, cyl, sweep, tube

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(REPO, "data", "places")
OPERATORS = os.path.join(DATA_DIR, "service_operators.json")
NAMES = ("PROP_Lift_TwoPost_A", "PROP_Lift_SinglePost_A", "PROP_Lift_BikeScissor_A",
         "KIT_TrussShed_Module_A", "KIT_TrussShed_Module_B", "KIT_TrussShed_Module_C", "KIT_WashTunnel_A",
         "KIT_HandWashBay_A", "PROP_Pylon_Service_A", "PROP_WorkshopWall_A", "KIT_Reception_A", "KIT_TukWorks_Shed_A",
         "PROP_FasciaSign_Service_A", "PROP_ToolCart_A", "PROP_OilDrainer_A", "PROP_Compressor_A", "PROP_TrolleyJack_A",
         "PROP_OilDrum_A", "PROP_TyreStack_A", "PROP_TyreRack_A", "DEC_ServiceFloor_A")

RED = "#C2382F"            # lift / equipment red (photos 3, 5, 6: generic workshop equipment, not a brand colour)
RED_D = "#8F2A24"
FLOOR_LINE = "#F2C200"     # yellow bay lines (photos 3, 5, 12, 13)
SCISSOR_BLUE = "#2F6BB0"   # photo 13
SCISSOR_Y = "#E8B923"
STEEL = "#6B6F73"
STEEL_L = "#C9CDCF"
DARK = "#2B2A2C"
RUBBER = "#262628"
TILE = "#E6EBEC"
STONE = "#9A968E"
WHITE = "#F2F2EE"
GALV, GALV_D = SK.GALV, SK.GALV_D
SAFETY_Y, SAFETY_K = "#E3B12C", "#232325"
PAINT_W = "#ECEAE2"
FIRE_RED = "#B23A33"
SKYLIGHT = "#E4EEEC"
FOAM = "#F4F6F6"
FASCIA_K = "#1E1F22"       # black shed fascia band (photo 9)
WET_STEEL = "#8C9396"      # stainless dado inside the tunnel (photos 2, 4)
GLASS_BAND = "#3A4650"     # tunnel side window band (photo 7)
CEILING_LINER = "#C9CECC"  # P268: light PVC liner under the tunnel roof (photos 2, 4: pale ceiling over the brushes)
CARDBOARD = "#B08A5A"
CORK = "#B98E5E"
BLOCK = "#C6C0B2"          # cement-rendered block wall (photos 14, 16)
BLOCK_D = "#A9A396"
PLANT = "#4E7A3C"
CHAIR = ("#2E5E9E", "#ECEAE2", "#C0392B")   # plastic chairs: blue, white, red (generic)
CAN = ("#D9A520", "#B23A33", "#2D5E95", "#3E8E4A")   # unbranded oil cans


def load(name: str) -> dict:
    with open(os.path.join(DATA_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def operators() -> dict:
    with open(OPERATORS, encoding="utf-8") as fh:
        return json.load(fh)["operators"]


def _seg(p0, p1, w, h, z, paint):
    """Flat bar from p0 to p1 (x, y) at height z: width w, thickness h (box rotated about z)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    return box((w, math.hypot(dx, dy), h), ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, z), paint,
               rot=math.atan2(-dx, dy))


def _tyre(x, y, z, r=0.3, w=0.2, axis="z", rim=GALV):
    return [cyl(r, w, (x, y, z), segs=8, paint=RUBBER, axis=axis),
            detail(cyl(r * 0.62, w + 0.012, (x, y, z), segs=8, paint=rim, axis=axis))]    # P268: rim LOD0 only


def _budget(doc: dict) -> int:
    return doc["budget_low"]["tris_lod0"]


def _lit(parts: list) -> list:
    """Parts drawn with the emissive lamp role (MAT_Lamp_Emissive: glows at dusk, SHD_Lamp _PI_LampGlow)."""
    for q in parts:
        (q["part"] if q["t"] == "array" else q)["mat"] = "lamp"
    return parts


def _word(op: dict, cx, face_y, ny, z0, cell, paint, word=None) -> list:
    """Operator placeholder wordmark (fuel_kit block letters; people decide the real name)."""
    return wordmark(word or op["wordmark"], cx, face_y, ny, z0, cell, paint)


# --- moving nodes ------------------------------------------------------------------------------------

def node(parts: list, name: str) -> list:
    """Tag parts as a moving child node of the piece (split off by split_nodes)."""
    for q in parts:
        q["node"] = name
    return parts


def _shift(part: dict, d) -> dict:
    q = dict(part)
    add = lambda pt: tuple(a + b for a, b in zip(pt, d))  # noqa: E731
    t = part["t"]
    if t == "array":
        q["part"] = _shift(part["part"], d)
    elif t in ("box", "cyl", "grid", "lathe"):
        q["at"] = add(part["at"])
    elif t == "tube":
        q["pts"] = [add(pt) for pt in part["pts"]]
    elif t == "sweep":
        q["path"] = [add(pt) for pt in part["path"]]
    return q


def split_nodes(piece: Piece) -> list[Piece]:
    """[static piece, node pieces ...]: node pieces are named `<piece>__<Node>`, parts moved so the node's pivot is
    the origin; `.meta` = {pivot (kit frame), move, travel_m}. A piece without nodes comes back alone."""
    nodes = getattr(piece, "nodes", None)
    if not nodes:
        return [piece]
    base = Piece(piece.name, piece.width, piece.height, [q for q in piece.parts if not q.get("node")],
                 budget=piece.budget, bevel=piece.bevel, refs=piece.refs, surface=piece.surface)
    base.nodes = nodes
    out = [base]
    for nn, meta in nodes.items():
        px, py, pz = meta["pivot"]
        part = Piece(f"{piece.name}__{nn}", piece.width, piece.height,
                     [_shift(q, (-px, -py, -pz)) for q in piece.parts if q.get("node") == nn],
                     budget=piece.budget, bevel=piece.bevel, refs=piece.refs, surface=piece.surface)
        part.node_of, part.node, part.meta = piece.name, nn, meta
        out.append(part)
    return out


# --- lifts -------------------------------------------------------------------------------------------

def lift_two_post(name: str, raise_m: float | None = None) -> Piece:
    """Two-post lift (photos 3, 5, 6): red posts on floor plates, steel cap, floor cover plate, power unit and hose on
    one post, yellow/black base stripe and a capacity plate on each post face. Node `Carriage`: the two carriages,
    4 telescopic arms (front short, rear long) and rubber pads; it raises by `raise_m` (data dims.raise_m)."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc["operator"]]
    col = RED if doc.get("params", {}).get("colour", "red") == "red" else op["lift"]
    H, px = d["height"], d["post_x"]
    c0 = 0.16
    ch = c0 + (raise_m or 0.0)
    p = [box((2 * px - 0.2, 0.62, 0.03), (0.0, 0.0, 0.015), STEEL)]
    for s in (-1, 1):
        x = s * px
        p += [box((0.52, 0.72, 0.04), (x, 0.0, 0.02), col),
              box((0.22, 0.44, H), (x, 0.0, H / 2), col),
              box((0.30, 0.50, 0.12), (x, 0.0, H + 0.06), STEEL)]
        p += node([box((0.34, 0.52, 0.42), (x, 0.0, ch + 0.21), RED_D if col == RED else col)], "Carriage")
        pivot = (x - s * 0.22, 0.0)
        for pad_y, pad_x in ((0.95, 0.80), (-1.25, 0.80)):                       # front arm short, rear arm long
            tip = (s * pad_x, pad_y)
            mid = ((pivot[0] * 0.4 + tip[0] * 0.6), (pivot[1] * 0.4 + tip[1] * 0.6))
            p += node([_seg(pivot, mid, 0.11, 0.07, ch + 0.07, col), _seg(mid, tip, 0.075, 0.06, ch + 0.12, STEEL)],
                      "Carriage")
            p += node([detail(cyl(0.075, 0.06, (tip[0], tip[1], ch + 0.18), segs=8, paint=RUBBER))], "Carriage")
        p.append(detail(box((0.225, 0.445, 0.3), (x, 0.0, 0.25), SAFETY_Y)))
        p.append(detail(array(box((0.226, 0.06, 0.3), (x, -0.16, 0.25), SAFETY_K, rot=0.0), 3, (0.0, 0.14, 0.0))))
        p.append(detail(box((0.14, 0.02, 0.1), (x - s * 0.111, 0.0, 1.55), WHITE, rot=math.pi / 2)))  # capacity plate
    p += [box((0.3, 0.24, 0.95), (-px - 0.45, 0.1, 0.475), STEEL),
          detail(tube([(-px - 0.38, 0.1, 0.95), (-px - 0.3, 0.1, 1.9), (-px - 0.2, 0.0, c0 + 0.2)], 0.025, segs=4,
                      paint=RUBBER))]
    piece = Piece(name, 2 * px + 1.2, H + 0.12, p, budget=_budget(doc), refs=doc["refs"])
    piece.nodes = {"Carriage": {"pivot": (0.0, 0.0, c0), "move": "raise", "travel_m": d["raise_m"]}}
    return piece


def lift_single_post(name: str, raise_m: float | None = None) -> Piece:
    """In-ground single-post hoist for tuks (photo 14): hatch plate flush with the floor and a collar (static), node
    `Ram` (chrome ram, pivot on the collar: Unity scales it in height) and node `Frame` (H-frame of two long bars and
    a cross bar with four pads: raises), feed hose and a drain trench."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc["operator"]]
    c0 = 0.1
    ch = c0 + (raise_m or 0.0)
    L, gap = d["frame_len"], d["frame_w"] / 2
    p = [box((1.1, 1.1, 0.03), (0.0, 0.0, 0.015), STEEL),
         cyl(0.2, 0.06, (0.0, 0.0, 0.06), segs=8, paint=STEEL_L)]
    p += node([cyl(0.085, ch + 0.05, (0.0, 0.0, (ch + 0.05) / 2 + 0.02), segs=8, paint=STEEL_L)], "Ram")
    frame = [box((0.2, 0.2, 0.1), (0.0, 0.0, ch), STEEL)]
    for s in (-1, 1):
        frame.append(box((0.12, L, 0.08), (s * gap, 0.0, ch + 0.07), op["frame"]))
    frame.append(box((2 * gap + 0.12, 0.14, 0.08), (0.0, 0.0, ch + 0.07), op["frame"]))
    for s in (-1, 1):
        for yy in (-L / 2 + 0.1, L / 2 - 0.1):
            frame.append(detail(cyl(0.07, 0.06, (s * gap, yy, ch + 0.14), segs=8, paint=RUBBER)))
    p += node(frame, "Frame")
    p += details([box((0.3, 2.6, 0.012), (0.0, 0.0, 0.006), DARK),
                  tube([(0.5, 0.2, 0.03), (0.9, 0.4, 0.03), (1.3, 1.0, 0.03)], 0.025, segs=4, paint=RUBBER)])
    piece = Piece(name, gap * 2 + 0.6, ch + 0.2, p, budget=_budget(doc), refs=doc["refs"])
    travel = d.get("raise_m", 1.1)
    piece.nodes = {"Frame": {"pivot": (0.0, 0.0, c0), "move": "raise", "travel_m": travel},
                   "Ram": {"pivot": (0.0, 0.0, 0.02), "move": "scale_y", "travel_m": travel, "rest_len_m": c0 + 0.05}}
    return piece


def lift_bike_scissor(name: str, raise_m: float | None = None) -> Piece:
    """Bike scissor lift (photo 13): iron base frame and approach ramp (static), node `Deck` (blue platform, wheel
    stop, side rails: raises) and node `Legs` (yellow scissor legs and the ram: Unity scales them in height)."""
    doc = load(name)
    d = doc["dims"]
    r = raise_m or 0.0
    t0 = 0.22
    top = t0 + r
    W, L = d["platform_w"], d["platform_l"]
    p = [box((W + 0.1, L - 0.1, 0.05), (0.0, 0.0, 0.025), DARK),
         sweep([(-W / 2 + 0.05, 0.0, 0.0), (W / 2 - 0.05, 0.0, 0.0)],
               [(-L / 2 - 0.9, 0.0), (-L / 2, 0.0), (-L / 2, t0)], SCISSOR_BLUE)]
    p += node([box((W, L, 0.08), (0.0, 0.0, top - 0.04), SCISSOR_BLUE),
               box((W, 0.08, 0.14), (0.0, L / 2 - 0.1, top + 0.07), SAFETY_Y),
               detail(box((0.07, L, 0.05), (-W / 2 - 0.02, 0.0, top + 0.01), SCISSOR_BLUE)),     # P268: rails LOD0
               detail(box((0.07, L, 0.05), (W / 2 + 0.02, 0.0, top + 0.01), SCISSOR_BLUE)),
               detail(box((0.12, 0.3, 0.16), (0.0, L / 2 - 0.3, top + 0.08), DARK))], "Deck")     # wheel clamp
    y0, y1 = -L / 2 + 0.2, L / 2 - 0.2
    legs = []
    for s in (-1, 1):
        x = s * (W / 2 - 0.12)
        legs.append(far_sides(tube([(x, y0, 0.07), (x, y1, top - 0.1)], 0.035, segs=6, paint=SCISSOR_Y), 3))
        legs.append(far_sides(tube([(x, y1, 0.07), (x, y0, top - 0.1)], 0.035, segs=6, paint=SCISSOR_Y), 3))
    legs.append(detail(tube([(0.0, y0, 0.08), (0.0, y1 - 0.2, top - 0.12)], 0.045, segs=6, paint=STEEL_L)))
    p += node(legs, "Legs")
    piece = Piece(name, W + 0.5, top + 0.2, p, budget=_budget(doc), refs=doc["refs"])
    travel = d.get("raise_m", 0.65)
    piece.nodes = {"Deck": {"pivot": (0.0, 0.0, t0), "move": "raise", "travel_m": travel},
                   "Legs": {"pivot": (0.0, 0.0, 0.07), "move": "scale_y", "travel_m": travel, "rest_len_m": t0 - 0.17}}
    return piece


def _fascia_frame(d: dict) -> tuple[float, float]:
    """(y of the fascia front face, z of its centre) of a truss shed with dims `d`, as truss_shed builds them
    (eave overhang 0.45 m, fascia band 0.08 m deep and 0.7 m tall hung 0.22 m below the eave line)."""
    hs, ov = d["span"] / 2, 0.45
    return -(hs + ov) - 0.11, d["eave"] - ov * d["rise"] / hs - 0.22


def fascia_sign(name: str) -> Piece:
    """Operator wordmark for a truss-shed hall fascia (photo 9; critic fix 9): lit block letters and the mark on a
    black backing board proud of the fascia band. Shares the origin of the module in params.module: place it once
    per hall at one module's transform (lettering is a placeholder; people write the real name)."""
    doc = load(name)
    op = operators()[doc["operator"]]
    fy, zc = _fascia_frame(load(doc["params"]["module"])["dims"])
    cell = 0.09
    word = op["wordmark"]
    width = len(word) * 4 * cell - cell
    w = width + 1.5
    p = [box((w, 0.04, 0.62), (0.2, fy - 0.02, zc), FASCIA_K)]
    p += _lit(_word(op, 0.35, fy - 0.05, -1, zc - 2.5 * cell, cell, WHITE))
    p += _mark(op, (0.35 - width / 2 - 0.45, fy - 0.06, zc), 0.26, -1)
    return Piece(name, w, 0.7, p, budget=_budget(doc), refs=doc["refs"])


# --- floors (baked into COLOR_0 by build_places_kit.paint_service) ----------------------------------

def floor_grid(sx, sy, at, step=1.0, mat="concrete"):
    """Top-only subdivided floor slab (fuel_kit grid, GN Mesh Grid): vertices for the baked AO, the Low night light
    pool, grime, oil and the wet state."""
    nx, ny = max(2, round(sx / step) + 1), max(2, round(sy / step) + 1)
    return {"t": "grid", "size": (sx, sy), "at": at, "verts": (nx, ny), "paint": PAINT_W, "mat": mat, "uv": "world"}


def _puddle(x, y) -> float:
    """0..1 puddle mask from a few low-frequency waves (deterministic, no texture)."""
    n = math.sin(0.83 * x + 0.61 * y + 0.3) * math.sin(0.47 * y - 0.9 * x + 1.1) + 0.45 * math.sin(1.3 * x - 0.7 * y + 2.0)
    return min(max((n - 0.35) / 0.4, 0.0), 1.0)


def floor_tint(name: str, x: float, y: float) -> tuple[float, float, float]:
    """RGB multiplier of a service floor at (x, y), Blender kit frame of piece `name`. The night light pool under the
    LIGHT_* anchors is baked in (Low: no realtime lights); grime toward walls and the open eave; oil under the lift
    bays; wet floors (params.floor wet) add puddles and tyre tracks. Medium/High add the LIGHT_* realtime lights."""
    doc = load(name)
    d, prm = doc["dims"], doc.get("params", {})
    pool = 0.0
    for a in doc["anchors"]:
        if a["kind"] != "light":
            continue
        lx, ly, lz = to_blender(a["pos"])
        s = max(1.6, 0.5 * lz)
        pool = max(pool, math.exp(-((x - lx) ** 2 / (2 * (1.6 * s) ** 2) + (y - ly) ** 2 / (2 * s ** 2))))
    k = 1.0
    if "span" in d:                                         # truss shed: edges, oil under each bay
        hs = d["span"] / 2
        k *= 0.84 + 0.16 * min((hs - abs(y)) / 1.6, 1.0)
        for by in _bay_ys(d, prm):
            k *= 1.0 - 0.38 * math.exp(-(x * x / (2 * 0.6 ** 2) + (y - by) ** 2 / (2 * 0.9 ** 2)))     # oil drip patch
    if "half_w" in d:                                       # tunnel: wet track down the middle, darker at the walls
        k *= 0.88 + 0.12 * min((d["half_w"] - abs(x)) / 0.6, 1.0)
    if "depth" in d and "hoist_at" in d:                    # tuk works: oil round the hoist, dust at the open front
        hx, hy = d["hoist_x"], d["hoist_at"]
        k *= 1.0 - 0.25 * math.exp(-((x - hx) ** 2 + (y - hy) ** 2) / (2 * 1.1 ** 2))
        k *= 0.9 + 0.1 * min(y / 2.0, 1.0)
    wet = prm.get("floor") == "wet"
    rgb = [k, k, k]
    if wet:
        w = _puddle(x, y)
        tracks = 0.0
        if "length" in d:
            tracks = max(math.exp(-((abs(x) - 0.78) ** 2) / (2 * 0.16 ** 2)), 0.0)
        base = 0.86                                         # damp slab reads darker than dry concrete (photos 5, 9)
        rgb = [base * rgb[0] * (1 - 0.45 * w - 0.15 * tracks), base * rgb[1] * (1 - 0.42 * w - 0.15 * tracks),
               base * rgb[2] * (1 - 0.34 * w - 0.12 * tracks)]
    gain = (1 + 0.28 * pool, 1 + 0.22 * pool, 1 + 0.12 * pool)
    return tuple(round(c * g, 4) for c, g in zip(rgb, gain))


JOINT = "#4F4C47"           # sealed saw-cut joint (as the fuel forecourt)
SCUFF = "#7E7A73"           # tyre scuff on the workshop slab
OIL_POOL = "#34302B"


def _bay_ys(d: dict, prm: dict) -> list[float]:
    hs = d["span"] / 2
    return [-hs + 3.4, hs - 3.4] if prm.get("lift_rows", 1) == 2 else [-0.6]


# --- truss shed --------------------------------------------------------------------------------------

RIB_PITCH, RIB_H = 0.33, 0.035     # box-rib wall sheet (garage refs 3, 7, 9, 10, 11): rib every 33 cm, 35 mm deep


def clad(x0, x1, yw, z0, z1, ny, turn=False, pitch=RIB_PITCH, h=RIB_H, paint=GALV) -> list:
    """Box-rib sheet wall from x0 to x1 in the plane y = yw, z0..z1, ribs standing out towards ny (+1/-1): two open
    vertical sweeps over the same profile (outer and inner face, ribs read from both sides; 8 triangles a rib per
    face) as LOD0 detail, with a flat 1 cm sheet as the LOD1/LOD2 proxy. turn=True turns the wall 90 degrees about
    the kit origin, so it lies in x = -yw, from y = x0 to x1, ribs towards -ny * x (end walls)."""
    n = max(1, round((x1 - x0) / pitch))
    pw = (x1 - x0) / n
    pts = []
    for i in range(n):
        a = x0 + i * pw
        pts += [(a, 0.0), (a + 0.6 * pw, 0.0), (a + 0.68 * pw, h), (a + 0.92 * pw, h)]
    pts.append((x1, 0.0))
    # vertical sweep frame (checked in Blender): world x = -px, world y = yw - py; px rising faces -y
    prof = [(-x, -ny * off) for x, off in pts]
    out = sorted(prof) if ny < 0 else sorted(prof, reverse=True)
    rz = math.pi / 2 if turn else 0.0
    path = [(0.0, yw, z0), (0.0, yw, z1)]
    sheets = [dict(sweep(path, out, paint, closed=False), rotz=rz),
              dict(sweep(path, list(reversed(out)), paint, closed=False), rotz=rz)]
    cx, cy, L = (x0 + x1) / 2, yw + ny * h / 2, x1 - x0
    flat = box((0.012, L, z1 - z0), (-cy, cx, (z0 + z1) / 2), paint) if turn else \
        box((L, 0.012, z1 - z0), (cx, cy, (z0 + z1) / 2), paint)
    return [detail(sheets[0], proxy=flat), detail(sheets[1])]


def truss_shed(name: str) -> Piece:
    """One 4 m bay of a galvanised steel truss shed (photos 3, 5, 6, 9). Tiled along x; the module owns its west
    column and truss. Span from data (A/B 10 m, one lift row; C 26 m, two rows facing a middle aisle): truss panels,
    purlins, skylight strips and tube-light rows scale with it. Gable roof, gutters, black fascia band on the open
    front (-y; C carries the operator wordmark, lit), floor slab grid (dry / wet with a drain channel), yellow bay
    lines. params.walls: back = clad back wall on the +y side (A, C), end = gable end wall on the +x side, back_end =
    both (B, the hall's closing module; P259).
    Kit frame +y = Unity +z (checked by glTF round trip: build_places_kit exports turned 180 degrees about up and the
    Unity glTF importer mirrors x, test_service_kit.test_shed_wall_side_in_glb)."""
    doc = load(name)
    d = doc["dims"]
    prm = doc["params"]
    walls = prm["walls"]
    op = operators()[doc["operator"]]
    P, S, E, R = d["pitch"], d["span"], d["eave"], d["rise"]
    hs, x0 = S / 2, -P / 2
    t = 0.06
    ov = 0.45
    slope = R / hs
    zr = lambda y: E + R * (1 - abs(y) / hs)                            # roof underside height at y  # noqa: E731
    Ye = hs + ov
    ze = E - ov * slope
    p = []
    for sg in (-1, 1):
        p.append(box((0.3, 0.3, E), (x0, sg * (hs - 0.15), E / 2), STEEL))
    p.append(box((0.22, 0.22, 0.22), (x0, -hs + 0.15, 0.11), STEEL))     # base plate stub (reads as a footing)
    n = max(6, 2 * round(S / 3.4))
    ys = [-hs + i * S / n for i in range(n + 1)]
    zb = E - 0.2
    top = [(x0, y, zr(y) - 0.12) for y in ys]
    web = [(x0, ys[i], zb if i % 2 == 0 else zr(ys[i]) - 0.12) for i in range(n + 1)]
    p += [far_sides(tube(top, 0.04, segs=4, paint=GALV_D), 3), far_sides(tube(web, 0.03, segs=4, paint=GALV_D), 3),
          far_sides(tube([(x0, ys[0], zb), (x0, ys[-1], zb)], 0.04, segs=4, paint=GALV_D), 3)]   # P268: 3 sides far
    n_sky = 1 if S <= 12 else 2
    n_pur = max(5, round((hs - 0.9) / 1.25))
    for sg in (-1, 1):                                                   # roof slopes (sweeps along x)
        pr = [(sg * Ye, ze), (0.0, zr(0)), (0.0, zr(0) + t), (sg * Ye, ze + t)] if sg < 0 else \
            [(0.0, zr(0)), (Ye, ze), (Ye, ze + t), (0.0, zr(0) + t)]
        p.append(sweep([(x0, 0.0, 0.0), (x0 + P, 0.0, 0.0)], pr, GALV))
        for k in range(n_sky):                                           # translucent skylight strips
            a0 = 0.35 + k * (Ye - 0.35) / n_sky
            a1 = a0 + (Ye - 0.35) / n_sky - (0.7 if k == n_sky - 1 else 0.9)
            za, zb_ = zr(a0), ze + (Ye - a1) * slope
            sk = [(sg * a1, zb_), (sg * a0, za), (sg * a0, za + t + 0.02), (sg * a1, zb_ + t + 0.02)]
            sk = sk if sg < 0 else [sk[1], sk[0], sk[3], sk[2]]
            p.append(sweep([(-0.55, 0.0, 0.0), (0.55, 0.0, 0.0)], sk, SKYLIGHT))
        p.append(box((P, 0.18, 0.14), (0.0, sg * (Ye - 0.05), ze - 0.02), GALV_D))            # gutter
        for k in range(1, n_pur + 1):
            y = sg * (0.9 + k * (hs - 0.9) / n_pur)
            p.append(detail(box((P, 0.08, 0.1), (0.0, y, zr(y) - 0.07), GALV_D)))              # purlins
    p.append(box((P, 0.5, 0.08), (0.0, 0.0, zr(0) + t + 0.04), GALV_D))                        # ridge cap
    rows = _light_rows(S)
    p += _lit([box((1.4, 0.1, 0.06), (0.0, y, E - 0.55), WHITE) for y in rows])               # tube-light rows
    p += details([tube([(-0.5, y, E - 0.52), (-0.5, y, zr(y) - 0.1)], 0.008, segs=3, paint=GALV_D) for y in rows])
    # black fascia band across the open front (photo 9); the operator wordmark is PROP_FasciaSign_Service_A, placed
    # once per hall at one module's transform (a word in every tiled module would repeat)
    p.append(box((P, 0.08, 0.7), (0.0, -Ye - 0.07, ze - 0.22), FASCIA_K))
    # floor slab and bay lines: the static `Ground` node (P242 workshop floor: saw-cut joints on the module line,
    # oil pools and tyre scuffs per bay, drain grate; refs garage 5, 6, 9, 10)
    g = []
    if prm.get("floor", "dry") != "none":
        g.append(floor_grid(P, S, (0.0, 0.0, 0.004)))
        g.append(box((0.02, S - 0.1, 0.004), (x0 + 0.01, 0.0, 0.0065), JOINT))          # module-line saw cut
        g.append(box((P, 0.02, 0.004), (0.0, 0.0, 0.0065), JOINT))                     # mid-span saw cut
        for k, yb in enumerate(_bay_ys(d, prm)):
            yo = 0.9 if yb < 0 else -0.9                                             # engine end of the bay
            g += details([cyl(0.38 + 0.08 * k, 0.004, (0.15, yb + yo, 0.008), segs=7, paint=OIL_POOL),
                          box((0.5, 0.22, 0.003), (0.45, yb + yo + 0.2, 0.009), OIL_POOL, rot=0.6)])
            g += details([box((0.2, 4.2, 0.003), (w, yb, 0.0075), SCUFF) for w in (-0.8, 0.8)])
    if prm.get("lift_rows", 1) == 2:
        for sg in (-1, 1):
            yb = sg * (hs - 6.4)
            g.append(box((P - 0.1, 0.1, 0.006), (0.0, yb, 0.011), FLOOR_LINE))
            g.append(box((0.1, 6.0, 0.006), (x0 + 0.06, sg * (hs - 3.4), 0.011), FLOOR_LINE))
    else:
        g += [box((0.1, S - 1.0, 0.006), (x0 + 0.06, 0.0, 0.011), FLOOR_LINE),
              box((P - 0.1, 0.1, 0.006), (0.0, -hs + 1.2, 0.011), FLOOR_LINE)]
    if prm.get("floor") == "wet":                                        # drain channel inside the open front
        g += [box((P, 0.3, 0.012), (0.0, -hs + 0.5, 0.008), DARK)]
        g.append(detail(array(box((0.04, 0.3, 0.014), (x0 + 0.2, -hs + 0.5, 0.012), STEEL_L), 10, (0.4, 0.0, 0.0))))
    p += g                       # workshop floor in the module mesh (under 1k with it; a node would add draws on Low)
    # P259 cladding (garage refs 7, 9, 10, 11): rendered block dado to 1.2 m, box-rib sheet above it to a top girt
    # under the eave; a downpipe from the gutter on the column line of every back-wall module (ref 10)
    zd = 1.2
    if walls in ("back", "back_end"):
        p += [box((P, 0.2, zd), (0.0, hs, zd / 2), BLOCK), box((P, 0.24, 0.05), (0.0, hs, zd + 0.025), BLOCK_D),
              box((P, 0.1, 0.12), (0.0, hs, E - 0.06), GALV_D)]
        p += clad(x0, x0 + P, hs, zd + 0.05, E - 0.12, 1)
        p.append(far_sides(tube([(x0 + 0.3, hs + 0.16, 0.12), (x0 + 0.3, hs + 0.16, ze - 0.45),
                                 (x0 + 0.3, Ye - 0.08, ze - 0.12)], 0.045, segs=6, paint=GALV_D), 4))
    if walls in ("end", "back_end"):
        xe = x0 + P
        p += [sweep([(xe - 0.06, 0.0, 0.0), (xe + 0.02, 0.0, 0.0)],
                    [(-hs + 0.3, E - 0.12), (hs - 0.3, E - 0.12), (hs, E), (0.0, E + R - 0.12), (-hs, E)], GALV),
              box((0.3, 0.3, E), (xe, -hs + 0.15, E / 2), STEEL), box((0.3, 0.3, E), (xe, hs - 0.15, E / 2), STEEL),
              box((0.2, S - 0.6, zd), (xe, 0.0, zd / 2), BLOCK), box((0.24, S - 0.6, 0.05), (xe, 0.0, zd + 0.025), BLOCK_D),
              box((0.1, S - 0.6, 0.12), (xe, 0.0, E - 0.06), GALV_D)]
        p += clad(-hs + 0.3, hs - 0.3, -xe, zd + 0.05, E - 0.12, -1, turn=True)
        p.append(box((0.1, S - 1.0, 0.006), (xe - 0.16, 0.0, 0.011), FLOOR_LINE))
    return Piece(name, P, E + R, p, budget=_budget(doc), refs=doc["refs"])


def _light_rows(S: float) -> list[float]:
    """Tube-light rows across the span: 2 rows for a 10 m shed, 4 (over each bay row and the aisle) when wide."""
    hs = S / 2
    return [-2.6, 2.6] if S <= 12 else [-(hs - 3.4), -2.6, 2.6, hs - 3.4]


# --- wash tunnel -------------------------------------------------------------------------------------

BRUSH_LOBES = 14        # cloth strips round the top roll (P259; garage ref 2: blue wash rolls read as fins of cloth)
WRAP_LOBES = 16         # narrow cloth strips round a vertical wrap roll (P268; P259 had 2 tiers of 8)
STRIP_LEAN = 0.55       # P268: strip tips trail by this share of half a strip pitch, so strips lean like cloth


def _strips(r_out, r_in, lobes=BRUSH_LOBES, turn=0.0, lean=0.0) -> list:
    """Closed star profile: `lobes` cloth strips (narrow wedges out to r_out) round a hub of r_in, counter-clockwise
    (faces outwards on both vertical and horizontal sweeps; checked in Blender). `lean` (< 1) turns each tip
    towards the next hub point, so a strip trails like cloth instead of standing out as a rigid radial fin."""
    pts = []
    for k in range(2 * lobes):
        tip = k % 2 == 0
        a = turn + k * math.pi / lobes + (lean * math.pi / lobes if tip else 0.0)
        r = r_out if tip else r_in
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


WRAP_SWAY = 0.05        # P268: how far (m) the free bottom of a wrap roll's strips swings off the mount


def _brush_v(x, y, h, z0, col, fore=1.0) -> list:
    """Vertical wrap-around brush roll (garage ref 2): steel core and one full-height column of 16 narrow leaning
    cloth strips (open sweep, no caps: the ends are never seen from a car) hung from the top mount and swept along a
    two-segment path whose free bottom sways WRAP_SWAY off the core (outwards from the tunnel centre, turned per
    roll), so the strips read as hanging cloth with a bellied bottom instead of rigid fins or stacked tiers (P268
    review of the P259 inside view: flat panels); 128 triangles. LOD1/LOD2 keep a 6-sided roll."""
    side = 1.0 if x >= 0 else -1.0
    dx, dy = side * WRAP_SWAY, 0.6 * WRAP_SWAY * fore                 # fore: +1 / -1 along the tunnel per pair
    path = [(x + dx, y + dy, z0), (x + 0.45 * dx, y + 0.45 * dy, z0 + 0.5 * h), (x, y, z0 + h)]
    prof = _strips(0.41, 0.10, lobes=WRAP_LOBES, turn=(side + 1.0) * math.pi / (4 * WRAP_LOBES), lean=STRIP_LEAN)
    return [cyl(0.08, h + 0.25, (x, y, z0 + h / 2 + 0.12), segs=6, paint=STEEL_L),
            detail(dict(sweep(path, prof, col), caps=False), proxy=cyl(0.36, h, (x, y, z0 + h / 2), segs=6, paint=col))]


def _brush_h(y, z, length, col) -> list:
    """Horizontal top roll (garage ref 2): steel core along x and a 14-strip leaning star swept along it."""
    return [cyl(0.07, length + 0.3, (0.0, y, z), segs=6, paint=STEEL_L, axis="x"),
            detail(sweep([(-length / 2, y, z), (length / 2, y, z)],
                         _strips(0.42, 0.11, turn=math.pi / 24, lean=STRIP_LEAN), col),
                   proxy=cyl(0.35, length, (0.0, y, z), segs=6, paint=col, axis="x"))]


def _spray_arch(y, hw, H, col) -> list:
    """Inverted-U spray bar with nozzle studs on the top and both legs (pre-soak, rinse; photos 2, 4)."""
    xs = hw - 0.32
    p = [tube([(-xs, y, 0.25), (-xs, y, H - 0.75), (xs, y, H - 0.75), (xs, y, 0.25)], 0.035, segs=4, paint=col)]
    p.append(detail(array(box((0.05, 0.07, 0.05), (-xs + 0.35, y, H - 0.81), STEEL_L), 6, (2 * (xs - 0.35) / 5, 0.0, 0.0))))
    for s in (-1, 1):
        p.append(detail(array(box((0.07, 0.05, 0.05), (s * (xs - 0.06), y, 0.55), STEEL_L), 5, (0.0, 0.0, 0.45))))
    return p


def wash_tunnel(name: str) -> Piece:
    """Automatic wash tunnel (photos 2, 4, 7): sheet-clad shell with a window band, two red box portals with a lit
    banner (placeholder wordmark), stage arches (pre-soak spray, foam, brushes, rinse spray, dryer) at the research
    distances: 2 pairs of vertical wrap brushes and a top roll at the brush stage, spray bars with nozzle studs,
    stainless wet dado on both walls, lit strip lights, wet floor slab, drive rollers, guide rails, stop light and
    barrier at the gate and a no-entry plate on the exit. FX_* anchors place mist / foam / spray / air (data)."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc["operator"]]
    L, hw, H = d["length"], d["half_w"], d["height"]
    sx = hw + 0.06
    p = [box((0.12, L, H), (-sx, L / 2, H / 2), GALV), box((0.12, L, H), (sx, L / 2, H / 2), GALV),
         box((2 * sx + 0.3, L, 0.14), (0.0, L / 2, H + 0.07), GALV_D),
         # P268: light PVC ceiling liner under the dark roof sheet (the review saw a black ceiling from inside;
         # normals were right, the underside was GALV_D in deep AO); its top face is hidden by the roof (dropped)
         box((2 * hw, L - 0.4, 0.02), (0.0, L / 2, H - 0.01), CEILING_LINER),
         box((0.5, L, 0.1), (-sx, L / 2, 0.05), "#8E8A82"), box((0.5, L, 0.1), (sx, L / 2, 0.05), "#8E8A82")]
    for s in (-1, 1):                                                   # outside window band, inside wet dado
        p.append(box((0.03, L - 1.6, 1.0), (s * (sx + 0.075), L / 2, 1.9), GLASS_BAND))
        p.append(box((0.03, L - 0.4, 1.15), (s * (sx - 0.075), L / 2, 0.68), WET_STEEL))
    p.append(floor_grid(2 * hw, L, (0.0, L / 2, 0.004), step=1.0))
    for xx in (-0.85, 0.85):                                           # drive rollers
        p.append(box((0.42, L - 1.0, 0.06), (xx, L / 2, 0.03), DARK))
    p += [box((0.5, L - 1.0, 0.012), (0.0, L / 2, 0.006), STEEL),
          box((0.1, L - 1.0, 0.16), (-1.3, L / 2, 0.08), SAFETY_Y), box((0.1, L - 1.0, 0.16), (1.3, L / 2, 0.08), SAFETY_Y)]
    for yy, face in ((0.0, -1), (L, 1)):                                # portals: red box frames with a lit banner
        for s in (-1, 1):
            p.append(box((0.55, 0.9, H + 0.4), (s * (sx + 0.22), yy, (H + 0.4) / 2), op["portal"]))
        p += [box((2 * sx + 1.3, 0.9, 0.55), (0.0, yy, H + 0.12), op["portal"]),
              box((2 * sx, 0.7, 0.1), (0.0, yy, H - 0.2), op["portal_d"])]
        board = _lit([box((2 * sx - 0.3, 0.04, 0.42), (0.0, yy + face * 0.46, H + 0.12), WHITE)])
        cell = 0.06
        c1, c2 = -0.62, 0.78                                            # reads left to right from outside
        words = _word(op, c1, yy + face * 0.48, face, H + 0.12 - 2.5 * cell, cell, op["portal_d"])
        words += _word(op, c2, yy + face * 0.48, face, H + 0.12 - 2.5 * cell, cell, op["portal_d"], word="WASH")
        p += board + details(words) if face < 0 else board   # entry: words on LOD0 only; exit: the lit board alone
    arches = [("aqua", op["neon"]), ("foam", op["portal"]), ("brush", op["blue"]), ("rinse", op["neon"]), ("dry", op["white"])]
    for (kind, col), at in zip(arches, doc["params"]["arch_at"]):
        for s in (-1, 1):
            p.append(box((0.14, 0.24, H - 0.5), (s * (hw - 0.25), at, (H - 0.5) / 2 + 0.1), col))
        p.append(box((2 * hw - 0.2, 0.24, 0.16), (0.0, at, H - 0.45), col))
        if kind == "brush":                                            # 2 pairs of wrap brushes and a top roll
            for dy in (-1.1, 0.9):
                for s in (-1, 1):
                    p += _brush_v(s * (hw - 0.62), at + dy, 1.75, 0.2, op["blue"] if dy < 0 else FOAM,
                                  fore=-1.0 if dy < 0 else 1.0)
            p += _brush_h(at + 0.2, H - 1.05, 2 * hw - 0.9, op["blue"])
        elif kind in ("aqua", "rinse"):
            p += _spray_arch(at + 0.35, hw, H, STEEL_L)
        elif kind == "foam":
            p += _spray_arch(at + 0.35, hw, H, op["portal_d"])
        else:                                                           # dryer: blower boxes on the arch
            p += [box((0.5, 0.4, 0.3), (xx, at + 0.3, H - 0.7), op["white"]) for xx in (-0.7, 0.7)]
            p += [box((0.3, 0.35, 0.6), (s * (hw - 0.45), at + 0.3, 1.4), op["white"]) for s in (-1, 1)]
    # sheet laps every 2.6 m (P259: was 0.95 m; the 264 triangles pay for the brush strips)
    p.append(detail(array(box((0.05, 0.03, H - 0.5), (-sx - 0.08, 1.0, H / 2 + 0.1), GALV_D), 7, (0.0, 2.6, 0.0))))
    p.append(detail(array(box((0.05, 0.03, H - 0.5), (sx + 0.08, 1.0, H / 2 + 0.1), GALV_D), 7, (0.0, 2.6, 0.0))))
    p += _lit([box((1.2, 0.1, 0.05), (0.0, yy, H - 0.1), WHITE) for yy in (2.0, 8.0, 14.0)])
    p += details(_lit([box((1.2, 0.1, 0.05), (0.0, yy, H - 0.1), WHITE) for yy in (5.0, 11.0, 17.0)]))
    gx = sx + 0.9                                                       # gate: stop light + barrier, stop line
    p += [box((0.14, 0.14, 2.2), (gx, -1.4, 1.1), DARK), box((0.32, 0.2, 0.8), (gx, -1.4, 2.3), DARK),
          cyl(0.07, 0.05, (gx, -1.52, 2.5), segs=8, paint="#C33A32", axis="y"),
          cyl(0.07, 0.05, (gx, -1.52, 2.25), segs=8, paint="#3E9B5A", axis="y"),
          box((0.2, 0.2, 1.0), (-gx, -1.0, 0.5), DARK), box((2 * gx + 0.2, 0.08, 0.1), (0.0, -1.0, 1.0), WHITE),
          box((3.2, 0.3, 0.008), (0.0, -1.8, 0.012), PAINT_W)]
    p += details([box((0.4, 0.09, 0.1), (-gx + 0.25 + i * 0.8, -1.0, 1.0), "#C33A32") for i in range(5)])
    # no-entry plate on the exit portal, facing out (photo 7): red disc, white bar (a symbol, no text)
    nx = sx + 0.22
    p += [cyl(0.3, 0.04, (nx, L + 0.47, 2.2), segs=12, paint="#C33A32", axis="y"),
          box((0.4, 0.02, 0.09), (nx, L + 0.5, 2.2), WHITE)]
    return Piece(name, 2 * sx + 1.6, H + 0.7, p, budget=_budget(doc), refs=doc["refs"])


# --- pylon -------------------------------------------------------------------------------------------

def _slat_face(w, sh, y, ny, z, op) -> list:
    """Lit slat face (lamp) with a dark icon square and a text bar: placeholder lettering, people write the text."""
    return _lit([box((w - 0.06, 0.012, sh - 0.08), (0.0, y, z), WHITE)]) + \
        [box((sh - 0.16, 0.012, sh - 0.16), (-w / 2 + 0.2, y + ny * 0.008, z), op["accent"]),
         box((w * 0.55, 0.012, 0.12), (0.08 * w, y + ny * 0.008, z), op["fascia"])]


def pylon(name: str) -> Piece:
    """Service pylon (photos 1, 8): stone plinth in a planter, mast, a big lit head box (lamp face, operator
    wordmark and mark on the front, mark on the back) and 6 stacked lit slats with placeholder icon + text bars on
    both faces (lamp role: the pylon glows at dusk, photos 9, 12). Two draws: kit + lamp; no atlas cell."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc["operator"]]
    H, n = d["height"], int(d["slats"])
    w, hh = d["width"], d["head_h"]
    sh, gap = d["slat_h"], 0.07
    p = [box((2.4, 1.2, 0.3), (0.0, 0.0, 0.15), STONE), box((2.2, 1.0, 0.04), (0.0, 0.0, 0.31), PLANT),
         box((0.7, 0.7, 0.45), (0.0, 0.0, 0.22), STONE),
         box((0.3, 0.3, H - 0.3 - hh), (0.0, 0.0, 0.3 + (H - 0.3 - hh) / 2), op["mast"]),
         box((w, 0.5, hh), (0.0, 0.0, H - hh / 2), op["fascia"]),
         box((w + 0.05, 0.54, 0.12), (0.0, 0.0, H - hh + 0.06), op["accent"])]
    p += details([box((0.5, 0.4, 0.3), (x, y, 0.45), PLANT, rot=0.4 * x) for x, y in ((-0.8, -0.2), (0.75, 0.15), (-0.5, 0.3))])
    for fy in (-1, 1):                                                  # lit head faces
        p += _lit([box((w - 0.16, 0.012, hh - 0.36), (0.0, fy * 0.256, H - hh / 2 + 0.04), WHITE)])
    cell = 0.075
    word = op["wordmark"]
    width = len(word) * 4 * cell - cell
    p += _word(op, 0.28, -0.26, -1, H - hh / 2 - 2.5 * cell + 0.04, cell, op["fascia"])
    p += _mark(op, (0.28 - width / 2 - 0.36, -0.27, H - hh / 2 + 0.04), 0.24, -1)
    p += details(_mark(op, (0.0, 0.27, H - hh / 2 + 0.04), 0.3, 1))
    z = H - hh - 0.3 - sh / 2
    for i in range(n):
        p.append(box((w - 0.3, 0.1, sh), (0.0, 0.0, z), op["cream"]))
        p += _slat_face(w - 0.3, sh, -0.056, -1, z, op)
        p += details(_slat_face(w - 0.3, sh, 0.056, 1, z, op))
        z -= sh + gap
    return Piece(name, w + 0.2, H, p, budget=_budget(doc), refs=doc["refs"])


# --- workshop wall set -------------------------------------------------------------------------------

def workshop_wall(name: str) -> Piece:
    """Workshop back-wall set for one 4 m shed bay (photos 3, 16; critic fix 7, 15): red roll cab with a top chest
    and drawer lines, notice board, steel parts shelving with boxes, oil-can shelf (unbranded cans), wall cabinet,
    air-line reel with a hanging hose, jack stands and a creeper. Back face on y = +0.3 (sits against a wall)."""
    doc = load(name)
    yb = 0.3
    p = []
    rx = -1.45                                                          # roll cab + top chest
    p += [box((0.72, 0.46, 0.9), (rx, yb - 0.25, 0.5), FIRE_RED), box((0.7, 0.44, 0.38), (rx, yb - 0.25, 1.15), FIRE_RED),
          box((0.74, 0.48, 0.03), (rx, yb - 0.25, 0.96), DARK), box((0.6, 0.4, 0.08), (rx, yb - 0.25, 0.04), RUBBER)]
    p += details([box((0.66, 0.012, 0.012), (rx, yb - 0.485, 0.28 + 0.15 * i), STEEL_L) for i in range(5)])
    p.append(detail(box((1.0, 0.03, 0.7), (rx + 0.1, yb - 0.02, 1.85), CORK)))                    # notice board
    p += details([box((0.2, 0.012, 0.27), (rx - 0.2 + 0.26 * i, yb - 0.04, 1.85 + (0.1 if i % 2 else -0.1)), WHITE)
                  for i in range(3)])
    sx = -0.1                                                           # parts shelving
    for x in (sx - 0.6, sx + 0.6):
        for y in (yb - 0.45, yb - 0.04):
            p.append(box((0.04, 0.04, 2.0), (x, y, 1.0), STEEL))
    for z in (0.15, 0.7, 1.25, 1.8):
        p.append(box((1.24, 0.45, 0.03), (sx, yb - 0.245, z), GALV))
    boxes = [(-0.35, 0.15, 0.3, 0.28), (0.1, 0.15, 0.4, 0.22), (0.42, 0.15, 0.25, 0.3), (-0.3, 0.7, 0.45, 0.3),
             (0.25, 0.7, 0.35, 0.2), (-0.38, 1.25, 0.3, 0.22), (0.05, 1.25, 0.3, 0.3), (0.4, 1.25, 0.25, 0.18),
             (-0.2, 1.8, 0.5, 0.25)]
    p += details([box((bw, 0.36, bh), (sx + bx, yb - 0.25, bz + 0.015 + bh / 2), CARDBOARD) for bx, bz, bw, bh in boxes])
    ox = 1.4                                                            # oil-can shelf
    for x in (ox - 0.5, ox + 0.5):
        p.append(box((0.04, 0.32, 1.5), (x, yb - 0.17, 0.75), STEEL))
    for z in (0.3, 0.8, 1.3):
        p.append(box((1.04, 0.32, 0.03), (ox, yb - 0.17, z), GALV))
        p += details([box((0.14, 0.1, 0.24), (ox - 0.38 + 0.19 * k, yb - 0.17, z + 0.135), CAN[(k + int(z * 3)) % 4])
                      for k in range(5)])
    p += [box((1.0, 0.36, 0.6), (ox, yb - 0.18, 2.05), STEEL_L), box((0.98, 0.01, 0.56), (ox, yb - 0.365, 2.05), GALV_D)]
    ax = -0.85                                                          # air-line reel + hose
    p += [cyl(0.24, 0.16, (ax, yb - 0.12, 2.35), segs=10, paint=SAFETY_Y, axis="y"),
          cyl(0.15, 0.17, (ax, yb - 0.12, 2.35), segs=8, paint=RUBBER, axis="y")]
    p.append(detail(tube([(ax + 0.1, yb - 0.2, 2.15), (ax + 0.25, yb - 0.5, 1.2), (ax + 0.1, yb - 0.7, 0.4),
                          (ax - 0.3, yb - 0.8, 0.03)], 0.012, segs=3, paint=RUBBER)))
    for jx in (0.95, 1.35):                                             # jack stands pair (floor, detail)
        p += details([cyl(0.13, 0.04, (jx, yb - 0.85, 0.02), segs=4, paint=FIRE_RED),
                      cyl(0.04, 0.5, (jx, yb - 0.85, 0.27), segs=4, paint=FIRE_RED)])
    p += details([box((0.45, 1.0, 0.06), (-0.35, yb - 1.1, 0.1), RED_D), box((0.4, 0.95, 0.02), (-0.35, yb - 1.1, 0.14), DARK)])
    return Piece(name, 4.0, 2.6, p, budget=_budget(doc), refs=doc["refs"])


# --- reception ---------------------------------------------------------------------------------------

def _chair(x, y, yaw, col) -> list:
    """Stackable plastic chair (photo 6, research section 3): seat, back and two leg frames."""
    c, s = math.cos(yaw), math.sin(yaw)
    at = lambda dx, dy, z: (x + dx * c - dy * s, y + dx * s + dy * c, z)  # noqa: E731
    return [box((0.44, 0.42, 0.04), at(0.0, 0.0, 0.45), col, rot=yaw),
            box((0.44, 0.04, 0.42), at(0.0, 0.22, 0.68), col, rot=yaw),
            box((0.04, 0.4, 0.43), at(-0.19, 0.0, 0.215), col, rot=yaw),
            box((0.04, 0.4, 0.43), at(0.19, 0.0, 0.215), col, rot=yaw)]


def reception(name: str) -> Piece:
    """Reception / waiting office (photo 6, research `KIT_Reception_A`): 8 x 5 m block, glass front and side (lit
    interior read, uv shop), rendered back and side wall, flat roof with an eave over the front, operator fascia band
    with the mark, counter with a till, waiting chairs inside and under the eave (SEAT_* anchors), two outdoor AC
    units on the side wall and a split unit inside, eave downlights and ceiling panels (lamp)."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc["operator"]]
    W, D, H = d["width"], d["depth"], d["height"]
    hw = W / 2
    p = [box((W + 0.4, D + 1.6, 0.12), (0.0, D / 2 - 0.6, 0.06), TILE),
         box((W, 0.2, H), (0.0, D - 0.1, H / 2), op["cream"]), box((0.2, D, H), (hw - 0.1, D / 2, H / 2), op["cream"]),
         box((W, 0.21, 0.5), (0.0, D - 0.1, 0.25), op["fascia"]), box((0.21, D, 0.5), (hw - 0.1, D / 2, 0.25), op["fascia"]),
         box((W - 2.0, 0.06, 2.5), (-1.0, 0.0, 1.37), mat="glass", uv="shop"),
         box((1.1, 0.08, 2.2), (hw - 1.4, 0.0, 1.22), mat="glass", uv="shop"),
         box((0.06, D - 0.4, 2.5), (-hw, D / 2, 1.37), mat="glass"),
         box((W + 0.8, D + 1.6, 0.22), (0.0, D / 2 - 0.6, H + 0.11), WHITE),
         box((W + 0.8, 0.12, 0.6), (0.0, -1.46, H + 0.05), op["fascia"]),
         box((W + 0.82, 0.13, 0.1), (0.0, -1.46, H - 0.2), op["accent"])]
    p.append(detail(array(box((0.08, 0.1, 2.5), (-hw, 0.0, 1.37), GALV_D), 6, ((W - 2.0) / 5, 0.0, 0.0))))  # P268
    p += [box((0.08, 0.1, 2.5), (-hw, D - 0.3, 1.37), GALV_D), box((W - 0.4, 0.1, 0.08), (-0.2, 0.0, 2.62), GALV_D)]
    p += _mark(op, (-hw + 0.8, -1.53, H + 0.05), 0.24, -1)
    p += [box((2.4, 0.6, 1.0), (1.2, D - 1.6, 0.6), op["cream"]), box((2.5, 0.7, 0.05), (1.2, D - 1.6, 1.12), DARK)]
    p.append(detail(box((0.4, 0.06, 0.3), (1.6, D - 1.6, 1.32), DARK, rot=0.2)))                     # till screen
    for i in range(4):                                                  # waiting chairs under the eave
        p += details(_chair(-3.0 + 0.6 * i, -0.75, math.pi, CHAIR[i % 2]))
    # P268 far proxy: the chair row reads as one seat, one back and two leg ends (16 cm gaps are 4 px at 25 m)
    p[-1]["proxy"] = [box((2.24, 0.42, 0.04), (-2.1, -0.75, 0.45), CHAIR[0]),
                      box((2.24, 0.04, 0.42), (-2.1, -0.97, 0.68), CHAIR[0]),
                      box((0.04, 0.4, 0.43), (-3.19, -0.75, 0.215), CHAIR[0]),
                      box((0.04, 0.4, 0.43), (-1.01, -0.75, 0.215), CHAIR[0])]
    for i in range(3):
        p += details(_chair(-2.8 + 0.6 * i, D - 0.7, 0.0, CHAIR[0]))
    for ay in (1.2, 2.6):                                               # outdoor AC units + split unit
        p += [box((0.32, 0.8, 0.56), (hw + 0.2, ay, 2.1), WHITE),
              detail(cyl(0.2, 0.02, (hw + 0.37, ay - 0.08, 2.1), segs=10, paint=DARK, axis="x"))]   # P268: fan LOD0
        p.append(detail(box((0.36, 0.06, 0.04), (hw + 0.2, ay, 1.8), STEEL)))
    p.append(detail(box((0.9, 0.24, 0.3), (-1.5, D - 0.32, 2.55), WHITE)))
    p.append(detail(tube([(hw + 0.1, 3.0, 2.3), (hw + 0.1, 3.0, 2.8)], 0.02, segs=3, paint=WHITE)))
    p += _lit([box((0.5, 0.5, 0.03), (x, -0.8, H - 0.015), WHITE) for x in (-2.4, 0.0, 2.4)])        # eave downlights
    p += _lit([box((1.2, 0.6, 0.03), (x, D / 2, H - 0.015), WHITE) for x in (-1.8, 1.8)])            # ceiling panels
    return Piece(name, W + 0.8, H + 0.3, p, budget=_budget(doc), refs=doc["refs"])


# --- tuk works shed ----------------------------------------------------------------------------------

def tukworks_shed(name: str) -> Piece:
    """Tuk-works block-wall lean-to (photos 14, 15, 16; critic fix 13): rendered block back wall with a painted
    dado, low block side walls with steel posts above, mono-pitch galvanised roof (high at the open front) on
    rafters, concrete floor grid (oil round the hoist position, dust at the front), drain trench, workbench, eave
    bench, tube lights, post board on two posts at the roadside (placeholder wordmark and text bars; people write the
    text). The single-post hoist (PROP_Lift_SinglePost_A) sits at dims.hoist_x / hoist_at."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc["operator"]]
    W, D, Hf, Hb, Hw = d["width"], d["depth"], d["front_h"], d["back_h"], d["wall_h"]
    hw = W / 2
    zr = lambda y: Hf + (Hb - Hf) * y / D  # noqa: E731
    p = [floor_grid(W, D, (0.0, D / 2, 0.004), step=1.4),
         box((W, 0.2, Hb), (0.0, D - 0.1, Hb / 2), BLOCK), box((W, 0.21, 1.2), (0.0, D - 0.1, 0.6), op["blue"])]
    for s in (-1, 1):
        p += [box((0.2, D, Hw), (s * (hw - 0.1), D / 2, Hw / 2), BLOCK), box((0.22, D, 0.08), (s * (hw - 0.1), D / 2, Hw + 0.04), BLOCK_D)]
        p.append(detail(array(box((0.212, D - 0.1, 0.012), (s * (hw - 0.1), D / 2, 0.2), BLOCK_D), 5, (0.0, 0.0, 0.2))))
        for y in (0.2, D / 2, D - 0.3):
            p.append(box((0.12, 0.12, zr(y) - Hw), (s * (hw - 0.1), y, Hw + (zr(y) - Hw) / 2), STEEL))
    p.append(box((0.14, 0.14, Hf), (0.0, 0.2, Hf / 2), STEEL))
    p.append(box((W, 0.16, 0.2), (0.0, 0.2, Hf - 0.1), STEEL))                                       # front beam
    p.append(sweep([(-hw - 0.3, 0.0, 0.0), (hw + 0.3, 0.0, 0.0)],
                   [(-0.6, Hf + 0.12), (D + 0.3, Hb + 0.12 - 0.03), (D + 0.3, Hb + 0.17), (-0.6, Hf + 0.17)], GALV))
    p.append(detail(array(tube([(-hw + 0.2, 0.0, Hf + 0.05), (-hw + 0.2, D, Hb + 0.05)], 0.04, segs=4, paint=STEEL),
                          6, ((W - 0.4) / 5, 0.0, 0.0))))
    p += _lit([box((0.1, 1.4, 0.06), (x, D * 0.45, zr(D * 0.45) - 0.35), WHITE) for x in (-2.5, 2.5)])
    p.append(detail(box((W - 1.0, 0.3, 0.01), (0.0, 0.7, 0.012), DARK)))                             # drain trench
    p += [box((2.4, 0.7, 0.06), (3.0, D - 0.6, 0.9), "#7A5A3A"), box((2.3, 0.6, 0.86), (3.0, D - 0.6, 0.43), GALV_D)]
    p += [box((2.2, 0.4, 0.08), (-3.4, -0.35, 0.45), STONE), box((0.3, 0.36, 0.41), (-4.3, -0.35, 0.205), STONE),
          box((0.3, 0.36, 0.41), (-2.5, -0.35, 0.205), STONE)]                                       # eave bench
    bx, by = hw + 1.4, -1.2                                             # post board (photo 15)
    p += [box((0.08, 0.08, 3.0), (bx - 0.7, by, 1.5), STEEL), box((0.08, 0.08, 3.0), (bx + 0.7, by, 1.5), STEEL),
          box((1.6, 0.05, 1.2), (bx, by, 2.3), WHITE), box((1.6, 0.06, 0.26), (bx, by, 2.77), op["blue"])]
    cell = 0.04
    p += _word(op, bx, by - 0.03, -1, 2.77 - 2.5 * cell, cell, WHITE)
    p += details([box((1.0 - 0.2 * (i % 2), 0.012, 0.07), (bx - 0.2 + 0.1 * (i % 2), by - 0.03, 2.5 - 0.17 * i), DARK)
                  for i in range(5)] + [box((0.3, 0.012, 0.3), (bx + 0.5, by - 0.03, 2.2), op["portal"])])
    return Piece(name, W + 0.6, Hf + 0.2, p, budget=_budget(doc), refs=doc["refs"])


# --- hand-wash bay -----------------------------------------------------------------------------------

def handwash_bay(name: str) -> Piece:
    """Open hand-wash bay (photos 10, 11): 4 x 8 m lean-to on steel posts, galvanised back and side wall over a tiled
    dado, concrete floor with a drain channel, hose reel, tool rack (lance, bucket, mitt, chamois), two foam buckets."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc["operator"]]
    W, L, H, Hb = d["width"], d["length"], d["roof_front"], d["roof_back"]
    t = 0.07
    hx = W / 2
    p = [box((W, L, 0.06), (0.0, L / 2, 0.03), mat="concrete", uv="world", paint="#B9B4AA"),
         box((0.34, L - 0.6, 0.02), (0.0, L / 2, 0.065), DARK)]
    p.append(sweep([(-hx - 0.25, 0.0, 0.0), (hx + 0.25, 0.0, 0.0)],
                   [(-0.5, H), (L + 0.4, Hb), (L + 0.4, Hb + t), (-0.5, H + t)], GALV))
    for s in (-1, 1):
        for y in (0.2, L / 2, L - 0.3):
            h = H + (Hb - H) * (y + 0.5) / (L + 0.9)
            p.append(box((0.14, 0.14, h), (s * (hx - 0.1), y, h / 2), STEEL))
        p.append(tube([(s * (hx - 0.1), -0.5, H - 0.07), (s * (hx - 0.1), L + 0.4, Hb - 0.07)], 0.05, segs=4, paint=STEEL))
    p += [box((W, 0.08, Hb - 0.1), (0.0, L, (Hb - 0.1) / 2), GALV), box((W - 0.02, 0.12, 1.2), (0.0, L - 0.02, 0.66), TILE),
          box((W, 0.14, 0.05), (0.0, L - 0.02, 1.27), op["neon"]),
          box((0.08, L, Hb - 0.4), (-hx, L / 2, (Hb - 0.4) / 2 + 0.1), GALV),
          box((0.1, L, 1.0), (-hx + 0.01, L / 2, 0.56), TILE)]
    p.append(detail(array(box((0.05, 0.03, Hb - 1.6), (-hx + 0.4, L - 0.06, 1.2 + (Hb - 1.6) / 2), GALV_D), 7, (0.5, 0.0, 0.0))))
    # hose reel (blue drum with a coil) and drop hose, lance on the wall
    p += [cyl(0.3, 0.2, (hx - 0.9, L - 0.2, 1.4), segs=10, paint=op["blue"], axis="y"),
          cyl(0.2, 0.22, (hx - 0.9, L - 0.2, 1.4), segs=8, paint=RUBBER, axis="y")]
    p.append(detail(tube([(hx - 0.7, L - 0.3, 1.2), (hx - 0.5, L - 0.8, 0.5), (hx - 0.2, L - 1.6, 0.06)], 0.03, segs=4, paint=RUBBER)))
    # tool rack on the back wall
    rx = -hx + 1.0
    p += [box((1.3, 0.05, 1.1), (rx, L - 0.1, 1.45), "#B7966A"), box((1.3, 0.3, 0.04), (rx, L - 0.25, 1.0), "#B7966A"),
          box((1.3, 0.3, 0.04), (rx, L - 0.25, 0.4), "#B7966A")]
    p += details([tube([(rx - 0.4, L - 0.15, 1.9), (rx - 0.4, L - 0.15, 1.0)], 0.025, segs=4, paint=op["neon"]),     # lance
                  cyl(0.15, 0.3, (rx + 0.1, L - 0.25, 1.17), segs=8, paint=op["blue"], r2=0.2),                     # bucket
                  box((0.18, 0.1, 0.07), (rx + 0.45, L - 0.25, 1.05), SAFETY_Y),                                      # mitt
                  box((0.3, 0.04, 0.4), (rx + 0.45, L - 0.12, 1.6), "#D9B25A")])                                   # chamois
    for x, y in ((-1.2, L - 1.3), (1.4, 2.5)):                          # foam buckets with a foam head
        p += details([cyl(0.15, 0.32, (x, y, 0.22), segs=8, paint=op["blue"], r2=0.19),
                      cyl(0.17, 0.12, (x, y, 0.42), segs=8, paint=FOAM, r2=0.09)])
    p.append(detail(box((0.09, 0.09, 1.2), (hx - 0.12, L - 0.15, 0.6), STEEL)))                                      # standpipe
    p.append(detail(array(box((0.04, 0.32, 0.012), (0.0, 1.5, 0.078), STEEL_L), 6, (0.0, 1.0, 0.0))))                 # grate bars
    return Piece(name, W + 0.5, H + 0.1, p, budget=_budget(doc), refs=doc["refs"])


# --- props -------------------------------------------------------------------------------------------

def tool_cart(name: str) -> Piece:
    doc = load(name)
    p = [box((0.72, 0.46, 0.6), (0.0, 0.0, 0.5), FIRE_RED), box((0.78, 0.52, 0.06), (0.0, 0.0, 0.83), DARK)]
    p += details([box((0.7, 0.04, 0.05), (0.0, -0.26, 0.9), STEEL), box((0.06, 0.06, 0.1), (-0.3, -0.24, 0.86), STEEL),
                  box((0.06, 0.06, 0.1), (0.3, -0.24, 0.86), STEEL)])        # P268: handle and drawer fronts LOD0 only
    for i in range(3):
        p.append(detail(box((0.66, 0.02, 0.14), (0.0, -0.235, 0.3 + i * 0.18), RED_D if i % 2 else FIRE_RED)))
    p.append(box((0.6, 0.4, 0.1), (0.0, 0.0, 0.05), RUBBER))
    return Piece(name, 0.8, 0.95, p, budget=_budget(doc), refs=doc["refs"])


def oil_drainer(name: str) -> Piece:
    doc = load(name)
    # P268 LOD1: tank and funnel at 5 sides; the 5 cm wheel base and the 4 cm handle posts are LOD0 only
    p = [detail(box((0.6, 0.6, 0.05), (0.0, 0.0, 0.1), STEEL)),
         far_sides(cyl(0.2, 0.75, (0.0, 0.0, 0.52), segs=8, paint="#2E7D3E"), 5),
         far_sides(cyl(0.3, 0.14, (0.0, 0.0, 0.97), segs=8, paint=STEEL_L, r2=0.1), 5),
         detail(box((0.04, 0.04, 0.8), (-0.26, 0.0, 0.5), STEEL)), detail(box((0.04, 0.04, 0.8), (0.26, 0.0, 0.5), STEEL))]
    return Piece(name, 0.9, 1.1, p, budget=_budget(doc), refs=doc["refs"])


def compressor(name: str) -> Piece:
    doc = load(name)
    # P268 LOD1: tank at 5 sides, pump at 3, the two feet as one cradle block on the ground
    p = [far_sides(cyl(0.19, 0.85, (0.0, 0.0, 0.5), segs=8, paint=RED, axis="x"), 5),
         detail(dict(box((0.3, 0.26, 0.26), (-0.25, 0.0, 0.78), STEEL), bevel_lod0=True),   # far: seated motor
                proxy=box((0.3, 0.22, 0.3), (-0.25, 0.0, 0.76), STEEL)),
         far_sides(cyl(0.09, 0.28, (0.25, 0.0, 0.8), segs=8, paint=STEEL_L), 3),
         detail(box((0.06, 0.5, 0.2), (-0.35, 0.0, 0.22), DARK), proxy=box((0.76, 0.42, 0.32), (0.0, 0.0, 0.16), DARK)),
         detail(box((0.06, 0.5, 0.2), (0.35, 0.0, 0.22), DARK))]
    return Piece(name, 1.0, 0.95, p, budget=_budget(doc), refs=doc["refs"])


def trolley_jack(name: str) -> Piece:
    doc = load(name)
    p = [box((0.34, 0.8, 0.1), (0.0, 0.0, 0.1), RED), box((0.16, 0.2, 0.1), (0.0, 0.3, 0.2), STEEL),
         cyl(0.06, 0.04, (0.0, 0.3, 0.27), segs=8, paint=RUBBER),
         detail(tube([(0.0, -0.3, 0.12), (0.0, -0.7, 0.5)], 0.02, segs=4, paint=STEEL))]      # P268: handle LOD0 only
    return Piece(name, 0.45, 0.6, p, budget=_budget(doc), refs=doc["refs"])


def oil_drum(name: str) -> Piece:
    doc = load(name)
    p = [cyl(0.29, 0.88, (0.0, 0.0, 0.44), segs=8, paint="#0F5958")]
    p += details([cyl(0.3, 0.05, (0.0, 0.0, z), segs=8, paint="#0C4846") for z in (0.25, 0.63)])
    return Piece(name, 0.62, 0.9, p, budget=_budget(doc), refs=doc["refs"])


def tyre_stack(name: str) -> Piece:
    doc = load(name)
    p = []
    for i in range(3):
        p += details(_tyre(0.02 * (i % 2), 0.0, 0.1 + 0.2 * i, 0.3, 0.2))
    # P268 far proxy: the stack is one rubber drum (same outline: the tyres sit flush, 2 cm offsets)
    p[0]["proxy"] = cyl(0.3, 0.6, (0.01, 0.0, 0.3), segs=6, paint=RUBBER)
    return Piece(name, 0.66, 0.62, p, budget=_budget(doc), refs=doc["refs"])


def tyre_rack(name: str) -> Piece:
    """Wall rack with two shelves of three upright tyres (plan B tyre shed; photos 12, 16 dressing)."""
    doc = load(name)
    d = doc["dims"]
    W, D, H = d["width"], d["depth"], d["height"]
    op = operators()[doc["operator"]]
    p = []
    for x in (-W / 2 + 0.05, W / 2 - 0.05):
        for y in (-D / 2 + 0.04, D / 2 - 0.04):
            p.append(box((0.07, 0.07, H), (x, y, H / 2), op["frame"]))
    for z in (0.15, 0.97):
        p.append(box((W, D, 0.04), (0.0, 0.0, z), op["frame"]))
        for i in range(3):
            p += _tyre(-0.78 + i * 0.78, 0.0, z + 0.02 + 0.31, 0.31, 0.2, axis="y")
    p.append(detail(box((W, 0.07, 0.07), (0.0, D / 2 - 0.04, H - 0.03), op["frame"])))   # P268: LOD0 only
    return Piece(name, W, H, p, budget=_budget(doc), refs=doc["refs"])


def service_floor(name: str) -> Piece:
    """Bay floor decals (research rank 5; critic fix 17): U of yellow bay lines, a hatched stop zone, a direction
    arrow, two oil stains (each a disc and an offset smear, so not a hard round dot) and four tyre-track smears along
    the wheel lines (the wet-floor read, photos 5, 9, 10). Flat quads about 1 cm over the floor (kit paint only)."""
    doc = load(name)
    d = doc["dims"]
    W, L = d["width"], d["length"]
    z = 0.012
    p = [box((0.12, L, 0.006), (-W / 2, 0.0, z), FLOOR_LINE), box((0.12, L, 0.006), (W / 2, 0.0, z), FLOOR_LINE),
         box((W, 0.12, 0.006), (0.0, L / 2, z), FLOOR_LINE)]
    p += [box((0.14, 1.5, 0.006), (0.0, -L / 2 + 1.2, z), PAINT_W),
          box((0.14, 0.7, 0.006), (-0.22, -L / 2 + 1.75, z), PAINT_W, rot=math.radians(-35)),
          box((0.14, 0.7, 0.006), (0.22, -L / 2 + 1.75, z), PAINT_W, rot=math.radians(35))]
    p.append(array(box((0.1, 0.6, 0.006), (-0.9, L / 2 - 0.9, z), SAFETY_K, rot=math.radians(35)), 4, (0.6, 0.0, 0.0)))
    for (x, y, r), k in zip(((-0.5, 0.4, 0.5), (0.9, -0.8, 0.35)), (1, 3)):
        a = 2 * math.pi * k / 5
        p += [cyl(r, 0.006, (x, y, z), segs=7, paint="#3A3631"),
              box((r * 1.2, r * 0.55, 0.004), (x + r * 0.75 * math.cos(a), y + r * 0.75 * math.sin(a), z + 0.002), "#4A4640", rot=a)]
    p += details([box((0.22, L * 0.8, 0.003), (s * 0.78 + 0.05 * k, -0.2 * k, z - 0.002), "#8F8B84" if k else "#86827B")
                  for s in (-1, 1) for k in (0, 1)])
    return Piece(name, W + 0.2, 0.03, p, budget=_budget(doc), refs=doc["refs"])


BUILDERS = {"Lift_TwoPost": lift_two_post, "Lift_SinglePost": lift_single_post, "Lift_BikeScissor": lift_bike_scissor,
            "TrussShed": truss_shed, "WashTunnel": wash_tunnel, "HandWashBay": handwash_bay, "Pylon": pylon,
            "WorkshopWall": workshop_wall, "Reception": reception, "TukWorks_Shed": tukworks_shed, "FasciaSign_Service": fascia_sign,
            "ToolCart": tool_cart, "OilDrainer": oil_drainer, "Compressor": compressor, "TrolleyJack": trolley_jack,
            "OilDrum": oil_drum, "TyreStack": tyre_stack, "TyreRack": tyre_rack, "ServiceFloor": service_floor}


def build_piece(n: str) -> Piece:
    """The whole piece (moving nodes still inside), as the builders make it."""
    key = n.split("_", 1)[1].rsplit("_", 1)[0]
    if key.startswith("Pylon"):
        key = "Pylon"
    if key == "TrussShed_Module":
        key = "TrussShed"
    return BUILDERS[key](n)


def pieces() -> dict[str, Piece]:
    """Every exported piece, lifts split into the static piece and `<piece>__<Node>` moving nodes."""
    out = {}
    for n in NAMES:
        for pc in split_nodes(build_piece(n)):
            out[pc.name] = pc
    return out


def demo_pieces() -> dict[str, Piece]:
    """Raised variants for review renders only (never exported): the lifts as they look in use."""
    out = {}
    for key, piece in (("DEMO_TwoPost_Up", lift_two_post("PROP_Lift_TwoPost_A", raise_m=1.35)),
                       ("DEMO_SinglePost_Up", lift_single_post("PROP_Lift_SinglePost_A", raise_m=1.1)),
                       ("DEMO_Scissor_Up", lift_bike_scissor("PROP_Lift_BikeScissor_A", raise_m=0.65))):
        piece.name = key
        out[key] = piece
    return out
