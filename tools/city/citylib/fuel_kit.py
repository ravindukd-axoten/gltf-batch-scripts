"""Fuel station KIT (P207 E2, part 2): canopy variants and shared site parts, as street-kit data.

Agent photos (.claude/agent-refs-fuel-2026-11-21, 16 shots of Sri Lankan forecourts) show that stations change from
operator to operator and fit whatever plot they get, so the station is a kit, not one canopy:

  canopy variants   one `canopy()` driven by data/places/KIT_FuelCanopy_<A|B|C>.json `dims` + `params`:
                    A long flat canopy with a deep fascia band (photos 2, 9), B curved / chamfered fascia with swept
                    corners (3, 5, 6), C small L-plan canopy with an open purlin underside for a tight site beside an
                    old building (12). Params: fascia flat|curved|purlin, column square_banded|slim_round|angled,
                    plan rect|L, hood none|box|angled (separate dispenser hoods, 8, 10, 13, 14, 16).
  shared parts      `island()` (kerb plinth, 2 double-sided dispensers, yellow-black bollards, sand-bucket stand),
                    used by every canopy; site parts as their own pieces so a site places them where the plot allows:
                    price pylon S/M/L (1, 7, 15), shop / food-mart block, forecourt paver patch, cone + barrier set.
  operators         data/places/fuel_operators.json: three fictional operators (palette + mark shape). No real brand
                    name, logo or trade-dress copy; lettering is a placeholder panel plus a SIGN_* slot anchor until
                    the signage atlas gets fuel cells (people decide the text).
  queue             a `queue_lane` anchor (head, chain of points along the frontage, slot spacing per vehicle kind,
                    max slots, the pump stops it feeds); `queue_positions()` is the reference spawner maths.

Pure Python (no bpy). Frames as in places_kit: data in Unity piece-local axes, parts in the Blender kit frame
(x the same, Blender y = Unity z forward, z up); the approach side is -y. Parts wrapped in `detail()` are LOD0 only:
the build makes `<name>_LOD1` without them (Low tier uses LOD1 beyond its LOD distance).
"""
from __future__ import annotations

import json
import math
import os

from . import street_kit as SK
from .street_kit import Piece, array, box, cyl, sweep, tube

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(REPO, "data", "places")
OPERATORS = os.path.join(DATA_DIR, "fuel_operators.json")
CANOPIES = ("KIT_FuelCanopy_A", "KIT_FuelCanopy_B", "KIT_FuelCanopy_C")
PARTS = ("KIT_FuelPylon_S", "KIT_FuelPylon_M", "KIT_FuelPylon_L", "KIT_FuelPylon_P", "KIT_FuelShop_A", "KIT_FuelPavers_A",
         "KIT_FuelCones_A", "KIT_FuelProps_A", "KIT_FuelProps_B", "KIT_FuelWall_A")
NAMES = CANOPIES + PARTS

G = 0.08                         # forecourt top (paver patch thickness)
SAFETY_Y, SAFETY_K = "#E3B12C", "#232325"
PAINT_W = "#ECEAE2"
ISLAND = "#55575A"               # dark grey island plinth (photos 4, 14, 16)
HEAD = "#34373B"
LED_DARK = "#1E1E24"
RUBBER = "#262628"
CONE = "#E8682A"
FIRE_RED = "#B23A33"
KICK_Y = "#E2B321"                # column kick sleeve, yellow with a black ring (photos 4, 12)
KICK_H = 0.32
FASCIA_D = 0.7                    # fascia box depth
GRADES = ("#2F6B48", "#C9A227", SK.BLACK, "#2D5E95", "#7A3B6E")   # fictional grade chips (petrol 92/95, diesel...)


def load(name: str) -> dict:
    with open(os.path.join(DATA_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def operators() -> dict:
    with open(OPERATORS, encoding="utf-8") as fh:
        return json.load(fh)["operators"]


def detail(part: dict, proxy: dict | list | None = None) -> dict:
    """Mark a part LOD0-only (hoses, holsters, paint arrows, slats ...); LOD1 drops it. `proxy` (P259): the cheap
    part LOD1 / LOD2 use in its place (a flat sheet for a ribbed one), never built on LOD0; P268: a list of parts is a
    hand-made far proxy for a whole group (one lit strip for a price row's digits, a block for a small prop)."""
    part["detail"] = True
    if proxy is not None:
        part["proxy"] = proxy
    return part


def _far(parts: list) -> list:
    """LOD1/LOD2 part list: detail() parts swapped for their proxy, if any."""
    out = []
    for p in parts:
        if p.get("detail") and p.get("proxy"):
            out += p["proxy"] if isinstance(p["proxy"], list) else [p["proxy"]]
        else:
            out.append(p)
    return out


def far_sides(part: dict, segs: int) -> dict:
    """P268: a round part's side count on LOD1 / LOD2 (thin posts and poles read as 4 sides beyond 25 m; caps the
    LOD1_SEGS / LOD2_SEGS default, never LOD0)."""
    part["far_segs"] = int(segs)
    return part


def details(parts: list) -> list:
    return [detail(p) for p in parts]


LOD1_SEGS = 6          # LOD1 round parts (columns, hoses, drums): at most 6 sides, no bevel
LOD1_MIN_M = 0.15      # LOD1 drops parts whose longest side is under this (bolts, buttons, nozzles: sub-pixel at 25 m)
LOD2_SEGS = 5
LOD2_MIN_M = 0.3       # LOD2 drops parts whose longest side is under this (lettering, trims, small props)


PLATE_M = 0.04         # P268: a box this thin on one side only (sign face, text bar, shelf, board) is a plate on
#                        LOD1 / LOD2: its 4 cm edges are about a pixel at 25 m on Low (0.7 scale, 720p)


def _segs(part: dict, cap: int) -> dict:
    """Far copy of a part: round parts capped at `cap` sides (or far_sides), thin upright boxes tagged `plate`
    (gn/street._drop_plate_sides keeps their two big faces)."""
    q = dict(part)
    if q["t"] == "box":
        s0, s1, _ = sorted(q["size"])
        if q.get("relief") or (s0 <= PLATE_M and s1 >= 4 * s0 and s1 >= LOD1_MIN_M):
            q["plate"] = True
    if q["t"] == "array":
        q["part"] = _segs(q["part"], cap)
    elif "segs" in q and q["t"] in ("cyl", "tube", "lathe"):
        q["segs"] = min(int(q["segs"]), max(min(cap, int(q.get("far_segs", cap))), 3))
    return q


def extent(part: dict) -> float:
    """Longest side of a part's box (m), for the LOD2 cull."""
    t = part["t"]
    if t == "array":
        step = max(abs(c) for c in part["step"])
        return max(extent(part["part"]), step * (int(part["count"]) - 1))
    if t in ("box", "grid"):
        return max(part["size"])
    if t == "cyl":
        return max(2 * max(part["r"], part["r2"]), part["depth"])
    if t == "lathe":
        zs = [z for _, z in part["prof"]]
        return max(2 * max(r for r, _ in part["prof"]), max(zs) - min(zs))
    pts = part.get("pts") or part.get("path") or []
    if len(pts) < 2:
        return 0.0
    return max(max(c[i] for c in pts) - min(c[i] for c in pts) for i in range(3))


def lod1(piece: Piece) -> Piece:
    """LOD0 minus detail() parts and parts under LOD1_MIN_M, round parts at LOD1_SEGS sides, no bevel
    (P242: 35-45 % of LOD0 on pieces over 1k triangles)."""
    low = Piece(f"{piece.name}_LOD1", piece.width, piece.height,
                [_half_grid(_segs(p, LOD1_SEGS)) for p in _far(piece.parts)
                 if not p.get("detail") and extent(p) >= LOD1_MIN_M],
                budget=piece.budget, bevel=0.0, refs=piece.refs, surface=piece.surface)
    return low


def _half_grid(part: dict) -> dict:
    """LOD1 floor grids at half the vertex rows (the baked light pool and grime stay smooth at 25 m+)."""
    if part["t"] == "grid":
        part = dict(part, verts=tuple(max(2, (n + 1) // 2) for n in part["verts"]))
    return part


def lod2(piece: Piece) -> Piece:
    """Far LOD (P242): LOD1 without parts under LOD2_MIN_M, round parts at LOD2_SEGS sides, floor grids at 2 x 2."""
    parts = []
    for p in _far(piece.parts):
        if p.get("detail") or extent(p) < LOD2_MIN_M:
            continue
        q = _segs(p, LOD2_SEGS)
        if q["t"] == "grid":
            q["verts"] = (2, 2)
        parts.append(q)
    return Piece(f"{piece.name}_LOD2", piece.width, piece.height, parts, budget=piece.budget, bevel=0.0,
                 refs=piece.refs, surface=piece.surface)


def node(parts: list, name: str) -> list:
    """Tag parts as a static child node (`<piece>__<name>`, split off by service_kit.split_nodes)."""
    for q in parts:
        q["node"] = name
    return parts


STATIC = {"pivot": (0.0, 0.0, 0.0), "move": "static", "travel_m": 0.0}   # a static child node at the piece origin


# --- queue maths (the reference the city / game spawner mirrors) ---------------------------------------

def lane_length(points) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def queue_positions(lane: dict, kinds: list[str]) -> list[tuple[float, float, float]]:
    """Unity piece-local (x, z, yaw_deg) of each queued vehicle, first in `kinds` at the head. The lane's
    `points` run head -> tail along the frontage; each vehicle takes `slot_spacing_m[kind]` of the chain (body
    plus gap) and faces the head. Stops at the tail: past it the spawner continues along the road kerb when
    `overflow` is "road_kerb"."""
    pts, sp = lane["points"], lane["slot_spacing_m"]
    out, s = [], 0.0
    total = lane_length(pts)
    for k in kinds:
        mid = s + sp[k] / 2
        if s + sp[k] > total + 1e-6:
            break
        acc = 0.0
        for a, b in zip(pts, pts[1:]):
            seg = math.dist(a, b)
            if acc + seg >= mid:
                t = (mid - acc) / seg
                x, z = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                yaw = math.degrees(math.atan2(a[0] - b[0], a[1] - b[1]))     # faces back towards the head
                out.append((round(x, 3), round(z, 3), round(yaw, 2)))
                break
            acc += seg
        s += sp[k]
    return out


# --- shared parts ------------------------------------------------------------------------------------

def _mark(op: dict, at, r: float, face_y: float) -> list:
    """The operator's mark on a fascia / pylon face (shapes only: disc, diamond, wedge; no real logo)."""
    x, y, z = at
    if op["mark"] == "disc":
        return [cyl(r, 0.08, (x, y + (0.08 if face_y > 0 else 0.0), z), segs=16, paint=op["mark_paint"], axis="y")]
    if op["mark"] == "diamond":
        shape = [(0.0, -r), (r, 0.0), (0.0, r), (-r, 0.0)]
    else:
        shape = [(-r, -0.55 * r), (0.0, 0.1 * r), (r, -0.55 * r), (r, -0.1 * r), (0.0, 0.55 * r), (-r, -0.1 * r)]
    yy = y + face_y * 0.04
    return [sweep([(x, yy - 0.035, 0.0), (x, yy + 0.035, 0.0)], [(px, z + pz) for px, pz in shape],
                  op["mark_paint"])]


def _outward(prof):
    """Sweep profiles put +px on the left of travel; round a CCW outline that is inwards, so mirror it."""
    return [(-px, pz) for px, pz in reversed(prof)]


def dispenser(x: float, y: float, z0: float, op: dict) -> list:
    """Double-sided dispenser facing +-x (the lanes), about 0.46 x 0.94 x 2.45 m (research: 0.5-0.6 wide, 2.0-2.3
    tall plus crown; photos 4, 10, 14): one chamfered body outline swept across its width, operator skirt, dark
    display head with three lit windows (amount, litres, unit price; the boxes run through, so both faces show),
    crown panel with a lit strip. Detail (LOD0 only): amount digit dividers, nozzle boot with three grade nozzles a side,
    two hoses a side hanging from the crown in a loop, a no-smoking sticker."""
    prof = [(-0.42, 0.0), (0.42, 0.0), (0.42, 1.25), (0.47, 1.32), (0.47, 2.05), (0.4, 2.12), (-0.4, 2.12),
            (-0.47, 2.05), (-0.47, 1.32), (-0.42, 1.25)]
    p = [box((0.6, 1.04, 0.1), (x, y, z0 + 0.05), SK.STONE),
         sweep([(x - 0.23, 0.0, 0.0), (x + 0.23, 0.0, 0.0)], [(y + py, z0 + 0.1 + pz) for py, pz in prof], op["body"]),
         box((0.48, 0.88, 0.5), (x, y, z0 + 0.38), op["skirt"]),
         box((0.5, 0.8, 0.62), (x, y, z0 + 1.78), HEAD),
         box((0.505, 0.56, 0.1), (x, y + 0.06, z0 + 1.98), mat="lamp"),
         box((0.505, 0.56, 0.1), (x, y + 0.06, z0 + 1.8), mat="lamp"),
         box((0.505, 0.26, 0.08), (x, y - 0.18, z0 + 1.6), mat="lamp"),
         box((0.36, 1.0, 0.34), (x, y, z0 + 2.39), op["skirt"]),
         box((0.38, 1.02, 0.05), (x, y, z0 + 2.24), op["stripe"]),
         box((0.37, 0.8, 0.08), (x, y, z0 + 2.43), mat="lamp")]
    p += details([array(box((0.51, 0.014, 0.1), (x, y - 0.16, z0 + 1.98), HEAD), 4, (0.0, 0.11, 0.0)),
                  box((0.5, 0.2, 0.2), (x, y + 0.26, z0 + 0.62), PAINT_W),
                  box((0.505, 0.12, 0.03), (x, y + 0.26, z0 + 0.62), FIRE_RED, rot=0.0)])
    for side in (-1, 1):
        fx = x + side * 0.23
        p.append(detail(box((0.07, 0.72, 0.34), (fx + side * 0.035, y - 0.02, z0 + 1.2), op["skirt"])))
        for i, c in enumerate((SK.BLACK, "#2F6B48", "#C9A227")):
            ny_ = y - 0.24 + 0.22 * i
            p.append(detail(tube([(fx + side * 0.08, ny_, z0 + 1.32), (fx + side * 0.1, ny_, z0 + 1.08),
                                  (fx + side * 0.2, ny_, z0 + 1.0)], 0.028, segs=4, paint=c)))
        for k, hy in enumerate((-0.24, 0.2)):
            p.append(detail(tube([(fx, y + hy, z0 + 2.15), (fx + side * 0.2, y + hy * 1.3, z0 + 1.7),
                                  (fx + side * 0.26, y + hy * 1.2, z0 + 0.55), (fx + side * 0.12, y + hy, z0 + 1.08)],
                                 0.016, segs=4, paint=RUBBER)))
    return p


def _hood(x: float, y: float, z0: float, op: dict, style: str) -> list:
    """Separate dispenser hood: 'box' = posts + a lit-edge crown over the dispenser (photos 8, 10); 'angled' =
    a frame with leaning legs and a top beam round the dispenser (photos 13, 14, 16)."""
    top = z0 + 2.75
    if style == "box":
        p = [box((0.08, 0.08, top - z0), (x, y + s * 0.6, z0 + (top - z0) / 2), SK.GALV_D) for s in (-1, 1)]
        p += [box((0.8, 1.5, 0.34), (x, y, top + 0.17), op["skirt"]),
              box((0.82, 1.52, 0.07), (x, y, top + 0.02), op["stripe"]),
              box((0.6, 1.3, 0.02), (x, y, top - 0.02), mat="lamp")]
        return p
    p = []
    for s in (-1, 1):            # tapered leaning legs (Unity z = Blender y), thickness along x, white inner face
        y0 = y + s * 0.72
        lean = s * 0.28
        prof = [(y0 - 0.08, z0), (y0 + 0.08, z0), (y0 + 0.17 + lean, top), (y0 - 0.17 + lean, top)]
        p.append(sweep([(x - 0.13, 0.0, 0.0), (x + 0.13, 0.0, 0.0)], prof, op["skirt"]))
        yi = y0 - s * 0.08
        inner = [(yi - 0.025, z0 + 0.02), (yi + 0.025, z0 + 0.02), (yi - s * 0.09 + lean + 0.025, top),
                 (yi - s * 0.09 + lean - 0.025, top)]
        p.append(sweep([(x - 0.135, 0.0, 0.0), (x + 0.135, 0.0, 0.0)], inner, PAINT_W))
    wedge = [(y - 1.08, top - 0.02), (y + 1.08, top - 0.02), (y + 1.2, top + 0.24), (y + 0.9, top + 0.5),
             (y - 1.2, top + 0.34)]                       # wedge top, taller at the back (photos 13, 14, 16)
    p += [sweep([(x - 0.17, 0.0, 0.0), (x + 0.17, 0.0, 0.0)], wedge, op["skirt"]),
          box((0.36, 2.2, 0.06), (x, y, top - 0.02), op["stripe"]),
          box((0.3, 1.9, 0.02), (x, y, top - 0.06), mat="lamp")]
    return p


def _bollard(x, y, z0, h=1.0) -> list:
    """Yellow crash bollard with two black bands (photos 4, 14)."""
    # 6 sides (P242 island cap): a 15 cm post reads round at 6 sides beyond arm's length
    return [cyl(0.075, h, (x, y, z0), segs=6, paint=SAFETY_Y),       # GN cones stand on `at` (base, not centre)
            cyl(0.079, 0.14, (x, y, z0 + h * 0.48), segs=6, paint=SAFETY_K),
            cyl(0.079, 0.14, (x, y, z0 + h * 0.78), segs=6, paint=SAFETY_K)]


def island(xi: float, d: dict, op: dict, hood: str) -> list:
    """Kerb island along +y at x = xi with `dispensers` double-sided dispensers (research: 2 per island in town),
    striped noses, four bollards and a sand-bucket stand (a Cityhub fixture) between the dispensers."""
    il, iw, ih = d["island_l"], d["island_w"], d["island_h"]
    n, pitch = int(d["dispensers"]), d["dispenser_pitch"]
    z1 = G + ih
    p = [box((iw, il, ih), (xi, 0.0, G + ih / 2), ISLAND),
         box((iw - 0.04, il - 0.04, 0.02), (xi, 0.0, z1 + 0.01), SK.STONE)]
    for s in (-1, 1):            # yellow-black striped noses
        yn = s * (il / 2 - 0.35)
        p.append(box((iw + 0.02, 0.7, ih + 0.006), (xi, yn, G + ih / 2), SAFETY_Y))
        p.append(array(box((0.12, 0.72, ih + 0.012), (xi - iw / 2 + 0.2, yn, G + ih / 2), SAFETY_K), 3,
                       ((iw - 0.4) / 2, 0.0, 0.0)))
        for bx in (-1, 1):
            p += _bollard(xi + bx * (iw / 2 - 0.15), s * (il / 2 - 0.2), z1)
    for k in range(n):
        y = (k - (n - 1) / 2) * pitch
        p += dispenser(xi, y, z1, op)
        if hood != "none":
            p += _hood(xi, y, z1, op, hood)
    # sand buckets on a frame between the dispensers (detail)
    fy = 0.0 if n % 2 == 0 else (pitch / 2)
    p += details([box((0.06, 0.8, 0.05), (xi, fy, z1 + 0.9), SK.IRON),
                  box((0.05, 0.05, 0.9), (xi, fy - 0.38, z1 + 0.45), SK.IRON),
                  box((0.05, 0.05, 0.9), (xi, fy + 0.38, z1 + 0.45), SK.IRON),
                  array(cyl(0.11, 0.24, (xi, fy - 0.24, z1 + 0.48), segs=8, paint=FIRE_RED, r2=0.13), 3,
                        (0.0, 0.24, 0.0))])
    return p


def column(x: float, y: float, h: float, size: float, op: dict, style: str, lean_dir: float = 1.0,
           base: float = G) -> list:
    """square_banded: fat square pillar, two-tone base band + top band (photos 4, 12); slim_round: slim round
    post with two bands (2, 3, 9); angled: flared pillar leaning towards the fascia (5, 6). Every style stands on a
    yellow kick sleeve with a black ring (detail) where it meets the island or slab (`base`, photos 4, 12; P259:
    bare posts read as scaffold poles). Round parts are 10-sided to pay for the sleeves inside the fuel-site cap."""
    z0 = G
    kb = base + KICK_H                            # top of the kick sleeve
    if style == "slim_round":
        r = size / 2
        k = 2 * r + 0.2                           # square concrete-cased foot round the post
        p = [cyl(r, h, (x, y, z0), segs=10, paint=op["column"]),
             cyl(r + 0.07, 1.4 - (kb - z0), (x, y, kb), segs=10, paint=op["band"]),  # brand cladding (3, 4, 11)
             cyl(r + 0.075, 0.14, (x, y, z0 + 1.4), segs=10, paint=op["band2"]),
             box((k, k, KICK_H), (x, y, base + KICK_H / 2), KICK_Y),
             detail(box((k + 0.01, k + 0.01, 0.07), (x, y, base + KICK_H * 0.5), LED_DARK))]
    elif style == "angled":                       # wide tapered blade leaning to the fascia (5, 6)
        lean = lean_dir * 0.55
        t = size * 0.72
        prof = [(y - size * 0.6, z0), (y + size * 0.6, z0), (y + size * 1.2 + lean, z0 + h),
                (y - size * 1.2 + lean, z0 + h)]
        f = 1.4 / h
        band = [(y - size * 0.6 - 0.03, z0), (y + size * 0.6 + 0.03, z0),
                (y + size * (0.6 + 0.6 * f) + 0.03 + lean * f, z0 + 1.4), (y - size * (0.6 + 0.6 * f) - 0.03 + lean * f, z0 + 1.4)]
        kick = [(y - size * 0.6 - 0.05, base), (y + size * 0.6 + 0.05, base),
                (y + size * 0.6 + 0.05, kb), (y - size * 0.6 - 0.05, kb)]
        p = [sweep([(x - t / 2, 0.0, 0.0), (x + t / 2, 0.0, 0.0)], prof, op["column"]),
             sweep([(x - t / 2 - 0.03, 0.0, 0.0), (x + t / 2 + 0.03, 0.0, 0.0)], band, op["band"]),
             sweep([(x - t / 2 - 0.05, 0.0, 0.0), (x + t / 2 + 0.05, 0.0, 0.0)], kick, KICK_Y)]
    else:
        p = [box((size, size, h), (x, y, z0 + h / 2), op["column"]),
             box((size + 0.03, size + 0.03, 1.2), (x, y, z0 + 0.6), op["band"]),
             box((size + 0.03, size + 0.03, 0.12), (x, y, z0 + 1.26), op["band2"]),
             box((size + 0.03, size + 0.03, 0.45), (x, y, z0 + h - 0.6), op["band"]),
             box((size + 0.07, size + 0.07, KICK_H), (x, y, base + KICK_H / 2), KICK_Y),
             detail(box((size + 0.075, size + 0.075, 0.07), (x, y, base + KICK_H * 0.5), LED_DARK))]
    # sign box (no smoking / 24 hours, signs pass later) on the lane side and a CCTV dome (3, 7, 11, 12)
    half = size * 0.36 if style == "angled" else size / 2
    sx = x - half - 0.05
    p += details([box((0.08, 0.42, 0.56), (sx, y, z0 + 2.3), PAINT_W),
                  box((0.085, 0.3, 0.1), (sx, y, z0 + 2.48), FIRE_RED),
                  box((0.12, 0.12, 0.1), (sx, y, z0 + h - 0.9), "#D8D8D2"),
                  box((0.08, 0.08, 0.06), (sx, y, z0 + h - 0.98), LED_DARK)])
    return p


# --- canopy plans --------------------------------------------------------------------------------------

def plan_polygon(d: dict, plan: str) -> list[tuple[float, float]]:
    """Canopy outline, counter-clockwise, Blender kit frame. rect: canopy_w x canopy_l centred; L: plus a wing of
    wing_w x wing_l on +x at the back (+y), leaving the front-right corner to a neighbour building."""
    hw, hl = d["canopy_w"] / 2, d["canopy_l"] / 2
    if plan != "L":
        return [(-hw, -hl), (hw, -hl), (hw, hl), (-hw, hl)]
    ww, wl = d["wing_w"], d["wing_l"]
    return [(-hw, -hl), (hw, -hl), (hw, hl - wl), (hw + ww, hl - wl), (hw + ww, hl), (-hw, hl)]


def _rounded(poly, r, segs=5):
    """Rounded-corner closed path (convex polygon, CCW), first point repeated at the end."""
    out = []
    n = len(poly)
    for i in range(n):
        p0, p1, p2 = poly[i - 1], poly[i], poly[(i + 1) % n]
        a0 = math.atan2(p1[1] - p0[1], p1[0] - p0[0]) - math.pi / 2     # outward normal of the incoming edge
        a1 = math.atan2(p2[1] - p1[1], p2[0] - p1[0]) - math.pi / 2
        while a1 < a0:
            a1 += 2 * math.pi
        cx = p1[0] - r * (math.cos(a0) + math.cos(a1))
        cy = p1[1] - r * (math.sin(a0) + math.sin(a1))
        for k in range(segs + 1):
            a = a0 + (a1 - a0) * k / segs
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    out.append(out[0])
    return out


def _edges(poly):
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ln = math.dist(a, b)
        nx, ny = (b[1] - a[1]) / ln, -(b[0] - a[0]) / ln                # outward (right of travel, CCW)
        yield a, b, ln, (nx, ny)


def _band_edges(poly, z0, h, t, paint, out=0.0, mat="kit"):
    """Axis-aligned band boxes round the outline: thickness t, standing `out` outside the edge."""
    p = []
    for a, b, ln, (nx, ny) in _edges(poly):
        cx, cy = (a[0] + b[0]) / 2 + nx * (out + t / 2), (a[1] + b[1]) / 2 + ny * (out + t / 2)
        L = ln + 2 * (out + t)
        size = (L, t, h) if abs(nx) < 0.5 else (t, L, h)
        p.append(box(size, (cx, cy, z0 + h / 2), paint, mat=mat))
    return p


def _fascia_box(poly, z0, fh, paint, depth=FASCIA_D):
    """Fascia as a solid box section (P259; photos 2, 9, 12: the band is a 0.6-0.8 m deep box, not a 0.1 m plate).
    Same outer face and the same 12 triangles per edge as the old plate; the deck runs into it."""
    return _band_edges(poly, z0, fh, depth, paint, out=0.1 - depth)


def _inset(rects, poly, dd):
    """Pull each deck rect side that lies on the outline in by dd, so the slab ends at the fascia box's inner face:
    a slab corner buried inside the box bakes to zero vertex AO and darkens the whole soffit face (P259)."""
    def on_outline(axis, c, lo, hi):
        for a, b, _, _ in _edges(poly):
            if abs(a[axis] - c) < 1e-6 and abs(b[axis] - c) < 1e-6:
                o = 1 - axis
                if min(a[o], b[o]) < hi - 1e-6 and max(a[o], b[o]) > lo + 1e-6:
                    return True
        return False
    def side(axis, c, lo, hi, sign):                # outline side: in by dd; a side shared with the next rect: out
        return c + sign * dd if on_outline(axis, c, lo, hi) else c - sign * dd   # by dd so the L wing still joins
    out = []
    for (rx0, rx1, ry0, ry1) in rects:
        out.append((side(0, rx0, ry0, ry1, 1), side(0, rx1, ry0, ry1, -1),
                    side(1, ry0, rx0, rx1, 1), side(1, ry1, rx0, rx1, -1)))
    return out


def _rect_cover(poly_plan: str, d: dict):
    """Rectangles that tile the plan (deck / roof sheet): [(x0, x1, y0, y1)]."""
    hw, hl = d["canopy_w"] / 2, d["canopy_l"] / 2
    rects = [(-hw, hw, -hl, hl)]
    if poly_plan == "L":
        rects.append((hw, hw + d["wing_w"], hl - d["wing_l"], hl))
    return rects


# 3 x 5 block letters, top row first: a placeholder wordmark in kit paint (no atlas cell, so no extra draw on the
# 3-draw canopy). Only the letters of the invented operator wordmarks (fuel_operators.json `wordmark`).
FONT = {"A": ("###", "#.#", "###", "#.#", "#.#"), "C": ("###", "#..", "#..", "#..", "###"),
        "E": ("###", "#..", "##.", "#..", "###"), "G": ("###", "#..", "#.#", "#.#", "###"),
        "L": ("#..", "#..", "#..", "#..", "###"), "N": ("##.", "#.#", "#.#", "#.#", "#.#"),
        "O": ("###", "#.#", "#.#", "#.#", "###"), "P": ("###", "#.#", "###", "#..", "#.."),
        "R": ("###", "#.#", "##.", "#.#", "#.#"),
        # service operators (P229, service_operators.json `wordmark`): MUTHU, PENA, KUMARA, WASH
        "H": ("#.#", "#.#", "###", "#.#", "#.#"), "K": ("#.#", "#.#", "##.", "#.#", "#.#"),
        "M": ("#.#", "###", "#.#", "#.#", "#.#"), "S": ("###", "#..", "###", "..#", "###"),
        "T": ("###", ".#.", ".#.", ".#.", ".#."), "U": ("#.#", "#.#", "#.#", "#.#", "###"),
        "W": ("#.#", "#.#", "#.#", "###", "#.#")}


def glyph_rects(ch: str) -> list[tuple[int, int, int, int]]:
    """Cells of a FONT glyph as rectangles (c0, r0, c1, r1), row 0 = bottom: vertical runs first, then the
    leftover cells in horizontal runs (4-5 boxes a letter)."""
    rows = FONT[ch]
    on = {(c, 4 - r) for r, line in enumerate(rows) for c, v in enumerate(line) if v == "#"}
    used, out = set(), []
    for c in range(3):
        r = 0
        while r < 5:
            if (c, r) in on:
                r1 = r
                while (c, r1 + 1) in on:
                    r1 += 1
                if r1 > r:
                    out.append((c, r, c, r1))
                    used |= {(c, k) for k in range(r, r1 + 1)}
                r = r1 + 1
            else:
                r += 1
    for r in range(5):
        c = 0
        while c < 3:
            if (c, r) in on and (c, r) not in used:
                c1 = c
                while (c1 + 1, r) in on and (c1 + 1, r) not in used:
                    c1 += 1
                out.append((c, r, c1, r))
                c = c1 + 1
            else:
                c += 1
    return out


def wordmark(word: str, cx: float, face_y: float, ny: float, z0: float, cell: float, paint: str) -> list:
    """Block-letter word centred at x = cx on a face at y = face_y whose outward normal is ny (+-1), bottom at z0.
    Reads left to right from outside (the +y face is mirrored)."""
    sgn = -ny                                        # viewer's right = +x on the -y face, -x on the +y face
    width = len(word) * 4 * cell - cell
    p = []
    for i, ch in enumerate(word):
        u0 = -width / 2 + i * 4 * cell
        for c0, r0, c1, r1 in glyph_rects(ch):
            u = u0 + (c0 + c1 + 1) * cell / 2
            p.append(dict(box(((c1 - c0 + 1) * cell, 0.05, (r1 - r0 + 1) * cell),
                              (cx + sgn * u, face_y + ny * 0.025, z0 + (r0 + r1 + 1) * cell / 2), paint),
                          relief=True))           # P268: a flat glyph face on LOD1 / LOD2 (_segs tags it a plate)
    return p


SIGN_TEXT = os.path.join(REPO, "data", "signage", "sign_text.json")


def script_words(op: dict) -> dict:
    """P268: the Sinhala and Tamil lines the sign-text proposal (P230, data/signage/sign_text.json) drafts for this
    operator's canopy fascia, as {lang: [word lengths]}. Only `fascia` rows whose use is a fuel canopy fascia and
    whose English text starts with the operator wordmark qualify; the words are still needs-native-review, so the
    kit draws them as placeholder strips (one blob per word, width by length), never as glyphs."""
    if not os.path.exists(SIGN_TEXT):
        return {}
    with open(SIGN_TEXT, encoding="utf-8") as fh:
        doc = json.load(fh)
    word = op.get("wordmark", "")
    for s in doc.get("signs", []):
        en = s.get("text", {}).get("en", "")
        if s.get("layout") == "fascia" and s.get("use", "").startswith("Fuel canopy fascia") and word \
                and en.split()[:1] == [word]:
            return {lang: [len(w) for w in s["text"][lang].split() if w.strip("·")] for lang in ("si", "ta")
                    if s.get("text", {}).get(lang)}
    return {}


STRIP_T = 0.07                   # proud of the fascia face, past the 0.04 stripe / accent bands that cross the strip zone


def script_strips(words: dict, cx, face_y, ny, z_top, z_floor, width, cell, paint) -> list:
    """Two placeholder script lines under an English wordmark (proposal layout rule: English on top, Sinhala then
    Tamil below): per word a thin relief blob, line widths 0.85 / 0.8 of the English word, sized to the space left
    on the fascia. LOD0 only (details); empty when the proposal has no lines or the fascia has no room."""
    h = min(0.9 * cell, (z_top - z_floor - 0.04) / 2.8)
    if h < 0.03:
        return []
    sgn = -ny
    p = []
    for k, (lang, share) in enumerate((("si", 0.85), ("ta", 0.8))):
        lens = words.get(lang) or []
        if not lens:
            continue
        line, space = share * width, 0.8 * cell
        unit = (line - space * (len(lens) - 1)) / sum(lens)
        z = z_top - (0.6 + 1.35 * k) * h * 1.25
        u = -line / 2
        for n in lens:
            w = n * unit
            p.append(dict(box((w, STRIP_T, h), (cx + sgn * (u + w / 2), face_y + ny * STRIP_T / 2, z), paint), relief=True))
            u += w + space
    return details(p)


def _lettering(poly, zc, op, out, fh=1.1, h_frac=0.55, z_floor=None) -> list:
    """Operator wordmark (block letters `h_frac` of the fascia height) + mark on the front (-y) and back (+y)
    fascia faces (SIGN_* anchors in data). The back face is LOD0 only. With `z_floor` (the fascia's bottom), the
    front face also gets the proposal's si / ta placeholder strips under the word (script_strips, LOD0 only)."""
    p = []
    cell = round(h_frac * fh / 5, 3)
    word = op.get("wordmark", "BATCH")
    for a, b, ln, (nx, ny) in _edges(poly):
        if abs(ny) < 0.5 or ln < 5.0:
            continue
        cx, fy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + ny * out
        width = len(word) * 4 * cell - cell
        r = 2.5 * cell
        group = width + 2 * r + 0.3
        wx = cx + (-ny) * (group / 2 - width / 2)               # word on the viewer's right, mark on the left
        part = wordmark(word, wx, fy, ny, zc - 2.5 * cell, cell, op["letter"])
        part += _mark(op, (cx - (-ny) * (group / 2 - r), fy + ny * 0.03, zc), r, ny)
        p += details(part) if ny > 0 else part
        if ny < 0 and z_floor is not None:
            p += script_strips(script_words(op), wx, fy, ny, zc - 2.5 * cell, z_floor, width, cell, op["letter"])
    return p


GRID_STEP = 1.6                  # forecourt grid under the canopy: vertex spacing for the baked AO, pool and grime
JOINT = "#4F4C47"                # sealed saw-cut joint
SCUFF = "#8E8A83"                # tyre scuff on the concrete
SLAB_M = 4.5                     # forecourt slab bay
OIL = "#3E3A35"


def grid(size, at, verts, mat="concrete"):
    """Top-only subdivided ground quad (GN Mesh Grid, gn/street.py `grid`): size (x, y), at = centre."""
    return {"t": "grid", "size": size, "at": at, "verts": verts, "paint": PAINT_W, "mat": mat, "uv": "world"}


def grid_rect(d: dict) -> tuple[float, float, float, float]:
    hw, hl = d["canopy_w"] / 2, d["canopy_l"] / 2
    return (max(d["slab_x0"], -hw - 1.0), min(d["slab_x1"], hw + 1.0),
            max(d["slab_z0"], -hl - 1.0), min(d["slab_z1"], hl + 1.0))


def _stain(x, y, r, k) -> list:
    """Oil-drip stain: an opaque 7-sided disc plus a smaller offset one (an irregular blob), a few mm proud of the
    concrete; Low-safe (no decal blending, Art Bible / critic Low note)."""
    a = 2 * math.pi * k / 5
    return [cyl(r, 0.004, (x, y, G), segs=6, paint=OIL),
            box((r * 1.1, r * 0.5, 0.006), (x + r * 0.7 * math.cos(a), y + r * 0.7 * math.sin(a), G + 0.003), OIL, rot=a)]


def forecourt(d: dict, stops: list) -> list:
    """Concrete forecourt (photos 11, 13, 16): a subdivided grid under and round the canopy (vertex AO, the baked
    night light pool and grime: build_places_kit.paint_ground), plain slab strips round it, panel joints every
    6 m, a drain grate across the entry and the exit, painted kerb noses at the road corners, oil stains at the
    pump stops (detail)."""
    x0, x1, y0, y1 = d["slab_x0"], d["slab_x1"], d["slab_z0"], d["slab_z1"]
    gx0, gx1, gy0, gy1 = grid_rect(d)
    nx, ny = max(2, round((gx1 - gx0) / GRID_STEP) + 1), max(2, round((gy1 - gy0) / GRID_STEP) + 1)
    p = [grid((gx1 - gx0, gy1 - gy0), ((gx0 + gx1) / 2, (gy0 + gy1) / 2, G), (nx, ny))]
    for (ax0, ax1, ay0, ay1) in ((x0, x1, y0, gy0), (x0, x1, gy1, y1), (x0, gx0, gy0, gy1), (gx1, x1, gy0, gy1)):
        if ax1 - ax0 > 0.05 and ay1 - ay0 > 0.05:
            p.append(box((ax1 - ax0, ay1 - ay0, G), ((ax0 + ax1) / 2, (ay0 + ay1) / 2, G / 2), mat="concrete", uv="world"))
    # saw-cut slab joints on a SLAB_M grid (P242: photos 11, 13, 16 show 4-5 m bays; kept on LOD1, the grid is the
    # main ground read from the road)
    for k in range(1, int((x1 - x0) / SLAB_M) + 1):
        p.append(box((0.02, y1 - y0, 0.004), (x0 + k * SLAB_M, (y0 + y1) / 2, G + 0.002), JOINT))
    for k in range(1, int((y1 - y0) / SLAB_M) + 1):
        p.append(box((x1 - x0, 0.02, 0.004), ((x0 + x1) / 2, y0 + k * SLAB_M, G + 0.002), JOINT))
    for yg in (d["canopy_l"] / 2 + 2.6, -d["canopy_l"] / 2 - 2.6):
        if y0 + 0.5 < yg < y1 - 0.5:
            ln = x1 - x0 - 1.0
            p.append(box((ln, 0.32, 0.006), ((x0 + x1) / 2, yg, G + 0.003), "#2E2E30"))
            p += [box((ln, 0.04, 0.01), ((x0 + x1) / 2, yg + s * 0.17, G + 0.004), SK.GALV_D) for s in (-1, 1)]
            # grate bars every 0.5 m (LOD0 only): the trench drain reads as a grate, not a black strip
            p.append(detail(array(box((0.035, 0.3, 0.008), (x0 + 0.75, yg, G + 0.006), SK.GALV_D), int(ln / 0.5),
                                  (0.5, 0.0, 0.0))))
    for s in (-1, 1):                              # painted kerb noses at the road corners (11, 13)
        xc = (x0 + 1.25) if s < 0 else (x1 - 1.25)
        p.append(box((2.5, 0.3, 0.16), (xc, y0 + 0.15, 0.08), SAFETY_Y))
        p.append(array(box((0.3, 0.31, 0.164), (xc - 0.9, y0 + 0.15, 0.08), SAFETY_K), 3, (0.9, 0.0, 0.0)))
    for k, a in enumerate(stops):                  # oil drips under the engine bays (detail)
        sx, sy, _ = to_blender(a["pos"])
        p += details(_stain(sx + (0.25 if k % 2 else -0.2), sy + (0.6 if k % 3 else -0.5), 0.45 + 0.1 * (k % 3), k))
        p += details(_stain(sx - 0.3, sy - 1.6 + 0.3 * (k % 2), 0.22, k + 2))
        # tyre scuffs along the wheel lines through the stop (P242; darker rubber smear, opaque, Low-safe)
        p += details([box((0.2, 5.5, 0.003), (sx + w, sy, G + 0.0015), SCUFF) for w in (-0.55, 0.55)])
    return p


def ground_tint(d: dict, stops: list, x: float, y: float) -> tuple[float, float, float]:
    """RGB multiplier of the forecourt concrete at (x, y), Blender kit frame. The night light pool is baked in
    (Low: no realtime lights, no decals): warm and bright under the canopy, fading out over about 3 m past the
    fascia, a little brighter on the lanes under the soffit lamps; grime off the canopy; darker oil round each
    pump stop. High adds the LIGHT_* anchors as realtime lights on top."""
    hw, hl = d["canopy_w"] / 2, d["canopy_l"] / 2
    dx, dy = max(abs(x) - hw, 0.0), max(abs(y) - hl, 0.0)
    out = math.hypot(dx, dy)
    pool = math.exp(-(out * out) / (2 * 2.2 ** 2))
    lanes = _lane_xs(d)
    lane = max((math.exp(-((x - xl) ** 2) / (2 * 1.6 ** 2)) for xl in lanes), default=0.0)
    pool *= 0.82 + 0.18 * lane
    grime = 0.9 + 0.1 * pool
    oil = 1.0
    for a in stops:
        sx, sy, _ = to_blender(a["pos"])
        oil *= 1.0 - 0.22 * math.exp(-((x - sx) ** 2 + (y - sy) ** 2) / (2 * 0.9 ** 2))
    k = grime * oil
    return (round(k * (1 + 0.24 * pool), 4), round(k * (1 + 0.2 * pool), 4), round(k * (1 + 0.12 * pool), 4))


def canopy(name: str) -> Piece:
    doc = load(name)
    d, prm = doc["dims"], doc["params"]
    op = dict(operators()[doc["operator"]])
    ch, fh = d["clear_h"], d["fascia_h"]
    zs = G + ch                                   # soffit
    poly = plan_polygon(d, prm["plan"])
    x0, x1, y0, y1 = d["slab_x0"], d["slab_x1"], d["slab_z0"], d["slab_z1"]
    stops = [a for a in doc["anchors"] if a["kind"] == "pump_stop"]
    ground = forecourt(d, stops)
    if prm["plan"] == "L":                        # the wing's floor (the notch stays the neighbour's)
        wx0, wx1, wy0 = x1, d["canopy_w"] / 2 + d["wing_w"] + 0.2, d["canopy_l"] / 2 - d["wing_l"]
        ground.append(box((wx1 - wx0, y1 - wy0, G), ((wx0 + wx1) / 2, (wy0 + y1) / 2, G / 2), mat="concrete", uv="world"))
    p = []
    # islands, dispensers, hoods
    n_isl, pitch = int(d["islands"]), d["island_pitch"]
    xs = [(i - (n_isl - 1) / 2) * pitch for i in range(n_isl)]
    for k, xi in enumerate(xs):
        p += node(island(xi, d, op, prm["hood"]), f"Island{k + 1}")
    # columns: on the island ends (rect plans) or at the given grid (C: outside the lanes, plus the wing)
    h_col = ch + 0.05
    if prm["columns_on"] == "islands":
        cols = [(xi, s * d["column_z"]) for xi in xs for s in (-1, 1)]
    else:
        cols = [(s * d["column_x"], t * d["column_z"]) for s in (-1, 1) for t in (-1, 1)]
        if prm["plan"] == "L":
            wx = d["canopy_w"] / 2 + d["wing_w"] - 0.5
            cols += [(wx, d["canopy_l"] / 2 - d["wing_l"] + 0.5), (wx, d["canopy_l"] / 2 - 0.5)]
    base = G + d["island_h"] if prm["columns_on"] == "islands" else G
    for (cx, cy) in cols:
        p += column(cx, cy, h_col, d["column"], op, prm["column"], lean_dir=1.0 if cy > 0 else -1.0, base=base)
    # deck / roof and fascia
    if prm["fascia"] == "curved":
        p += _curved_deck(poly, d, op, zs, fh, prm.get("soffit", "panel"))
    elif prm["fascia"] == "purlin":
        p += _purlin_deck(poly, prm["plan"], d, op, zs, fh)
    else:
        p += _flat_deck(poly, prm["plan"], d, op, zs, fh, prm.get("soffit", "panel"))
    # lane paint: exit arrows (detail)
    for xl in sorted({round(to_blender(a["pos"])[0], 3) for a in stops}):
        ground += details(_arrow(xl, d["canopy_l"] / 2 + 1.6, G + 0.003))
        ground.append(box((2.2, 0.12, 0.004), (xl, -d["island_l"] / 2 - 0.4, G + 0.002), PAINT_W))   # stop bar
    # queue lane: yellow edge lines along the chain (kept on LOD1, the queue reads from far)
    for a in doc["anchors"]:
        if a["kind"] == "queue_lane":
            w = a["width_m"]
            for (ax, az), (bx, bz) in zip(a["points"], a["points"][1:]):
                ln = math.hypot(bx - ax, bz - az)
                ux, uz = (bx - ax) / ln, (bz - az) / ln
                for s in (-1, 1):
                    cx, cz = (ax + bx) / 2 - uz * s * w / 2, (az + bz) / 2 + ux * s * w / 2
                    size = (0.12, ln, 0.006) if abs(uz) > 0.5 else (ln, 0.12, 0.006)
                    ground.append(box(size, (cx, cz, G + 0.003), SAFETY_Y))
    budget = doc["budget_low"]["tris_lod0"]
    # the forecourt stays in the core mesh: core + ground fit the 3k piece cap (A 2.3k, B 2.6k, C 2.4k) and a Ground
    # node would cost 2 more draws on Low (no static batching in CellBuilder); the islands go to static nodes so each
    # bevels under the 3k cap, then build_places_kit merges them back into one mesh by material (P259: 3 draws)
    piece = Piece(name, x1 - x0, zs + fh, p + ground, budget=budget, bevel=0.0, refs=doc["refs"])
    piece.nodes = {f"Island{k + 1}": dict(STATIC) for k in range(len(xs))}
    return piece


def _soffit_lamps(rects, xs_lanes, zs, style="panel") -> list:
    """Soffit lights over each lane: `panel` (1 x 0.5 m boxes every 3 m), `line` (one continuous strip per lane,
    photo 8) or `round` (5-sided downlight discs every 3 m, photo 10; 5 sides keep B under its 6k cap).
    `params.soffit` picks it per canopy."""
    p = []
    for (rx0, rx1, ry0, ry1) in rects:
        for xl in xs_lanes:
            if not rx0 + 0.6 < xl < rx1 - 0.6:
                continue
            if style == "line":
                p.append(box((0.16, ry1 - ry0 - 1.2, 0.03), (xl, (ry0 + ry1) / 2, zs - 0.015), mat="lamp"))
                continue
            n = max(1, int((ry1 - ry0 - 1.0) // 3.0))
            y0 = ry0 + (ry1 - ry0 - (n - 1) * 3.0) / 2
            lamp = (cyl(0.2, 0.03, (xl, y0, zs - 0.03), segs=5, mat="lamp") if style == "round"
                    else box((1.0, 0.5, 0.03), (xl, y0, zs - 0.015), mat="lamp"))
            p.append(array(lamp, n, (0.0, 3.0, 0.0)))
    return p


def _lane_xs(d) -> list[float]:
    n, pitch = int(d["islands"]), d["island_pitch"]
    off = d["island_w"] / 2 + 1.25
    return sorted({round((i - (n - 1) / 2) * pitch + s * off, 3) for i in range(n) for s in (-1, 1)})


def _flat_deck(poly, plan, d, op, zs, fh, soffit="panel") -> list:
    """Long flat canopy: deck slab, deep fascia band with a coloured stripe and an accent line (photos 2, 9)."""
    rects = _rect_cover(plan, d)
    p = [box((rx1 - rx0, ry1 - ry0, 0.3), ((rx0 + rx1) / 2, (ry0 + ry1) / 2, zs + 0.15), op["soffit"])
         for (rx0, rx1, ry0, ry1) in _inset(rects, poly, FASCIA_D - 0.1)]
    z0 = zs - 0.15
    p += _fascia_box(poly, z0, fh, op["fascia"])
    p += _band_edges(poly, z0 + fh * 0.06, fh * 0.2, 0.04, op["stripe"], out=0.1)
    p += _band_edges(poly, z0 + fh * 0.29, 0.05, 0.03, op["accent"], out=0.1)
    p += _band_edges(poly, z0 - 0.06, 0.07, 0.04, "#FFFFFF", out=0.06, mat="lamp")     # lit lip under the fascia (8)
    p += _lettering(poly, z0 + fh * 0.64, op, 0.1, fh, 0.56, z_floor=z0)
    p += _soffit_lamps(rects, _lane_xs(d), zs, soffit)
    return p


def _curved_deck(poly, d, op, zs, fh, soffit="panel") -> list:
    """Swept corners in plan and a chamfered fascia section: the lower lip slopes up and out to a vertical face
    (photos 3, 5, 6). Deck = cross of two boxes + four corner discs."""
    r = d["corner_r"]
    hw, hl = d["canopy_w"] / 2, d["canopy_l"] / 2
    zc = zs + 0.15
    p = [box((2 * hw - 2 * r, 2 * hl, 0.3), (0.0, 0.0, zc), op["soffit"]),
         box((2 * hw, 2 * hl - 2 * r, 0.3), (0.0, 0.0, zc), op["soffit"])]
    for sx in (-1, 1):
        for sy in (-1, 1):
            p.append(cyl(r, 0.3, (sx * (hw - r), sy * (hl - r), zs), segs=8, paint=op["soffit"]))
    path = [(x, y, zs - 0.25) for x, y in _rounded(poly, r)]
    p.append(sweep(path, _outward([(-0.55, 0.0), (0.14, 0.42), (0.14, fh), (-0.3, fh)]), op["fascia"]))
    p.append(sweep(path, _outward([(0.13, 0.44), (0.18, 0.44), (0.18, 0.44 + fh * 0.1), (0.13, 0.44 + fh * 0.1)]),
                   op["stripe"]))
    p.append(sweep(path, _outward([(-0.5, -0.02), (0.13, 0.36), (0.13, 0.4), (-0.5, 0.01)]), mat="lamp"))  # lit lip
    p += _lettering([(-hw, -hl), (hw, -hl), (hw, hl), (-hw, hl)], zs - 0.25 + fh * 0.76, op, 0.17, fh, 0.46,
                    z_floor=zs - 0.25)
    p += _soffit_lamps([(-hw, hw, -hl, hl)], _lane_xs(d), zs, soffit)
    return p


def _purlin_deck(poly, plan, d, op, zs, fh) -> list:
    """Small site canopy: thin sheet roof on steel purlins and beams left open underneath, thick fascia with a
    coloured top and bottom band (photo 12)."""
    rects = _rect_cover(plan, d)
    p = []
    zb = zs + 0.12                               # beam centre; purlins on top; sheet on the purlins
    for k, (rx0, rx1, ry0, ry1) in enumerate(_inset(rects, poly, FASCIA_D - 0.1)):
        cx, cy, w, ln = (rx0 + rx1) / 2, (ry0 + ry1) / 2, rx1 - rx0, ry1 - ry0
        p.append(box((w, ln, 0.04), (cx, cy, zs + 0.5 + 0.006 * k), op["soffit"]))     # k: no coplanar overlap
        n = max(2, int(w / 0.9))
        p.append(array(box((0.07, ln - 0.1, 0.16), (rx0 + w / (2 * n), cy, zs + 0.4), SK.GALV), n,
                       (w / n, 0.0, 0.0)))
    for yb in (-d["column_z"], d["column_z"]):
        p.append(box((d["canopy_w"] - 2 * (FASCIA_D - 0.1), 0.24, 0.34), (0.0, yb, zb + 0.05), op["column"]))
    if plan == "L":
        wx = d["canopy_w"] / 2 + d["wing_w"] - 0.5
        p.append(box((0.24, d["wing_l"], 0.34), (wx, d["canopy_l"] / 2 - d["wing_l"] / 2, zb + 0.05), op["column"]))
    z0 = zs - 0.1
    p += _fascia_box(poly, z0, fh, op["fascia"])
    p += _band_edges(poly, z0 + fh - 0.22, 0.16, 0.03, op["stripe"], out=0.1)
    p += _band_edges(poly, z0, 0.1, 0.03, op["stripe"], out=0.1)
    p += _band_edges(poly, z0 - 0.06, 0.07, 0.04, "#FFFFFF", out=0.06, mat="lamp")     # lit lip under the fascia (8)
    p += _lettering(poly, z0 + fh * 0.47, op, 0.1, fh, 0.5, z_floor=z0)
    for (rx0, rx1, ry0, ry1) in rects:                # tube lights hung from the purlins
        for xl in _lane_xs(d) + ([] if plan != "L" else [rx0 + 1.8]):
            if rx0 + 0.5 < xl < rx1 - 0.5:
                p.append(array(box((0.06, 1.2, 0.05), (xl, ry0 + 1.5, zs + 0.29), mat="lamp"),
                               max(1, int((ry1 - ry0 - 1.5) // 3.0)), (0.0, 3.0, 0.0)))
    return p


def _arrow(x: float, y: float, z: float, paint=PAINT_W) -> list:
    return [box((0.14, 1.6, 0.006), (x, y - 0.4, z), paint),
            box((0.14, 0.75, 0.006), (x - 0.22, y + 0.25, z), paint, rot=math.radians(-35)),
            box((0.14, 0.75, 0.006), (x + 0.22, y + 0.25, z), paint, rot=math.radians(35))]


def to_blender(p):
    return (p[0], p[2], p[1])


# --- site parts --------------------------------------------------------------------------------------

def _price_rows(w, dep, rh, z, rows) -> list:
    """Stacked price rows: dark LED field, grade chip, four lit digit cells and a decimal point (the digit boxes run
    through the panel, so both faces read; live prices are a later data feature)."""
    p = []
    for i in range(rows):
        p.append(box((w - 0.14, dep + 0.02, rh), (0.0, 0.0, z), LED_DARK))
        p.append(box((w * 0.26, dep + 0.03, rh * 0.7), (-w * 0.3, 0.0, z), GRADES[i % len(GRADES)]))
        dw = w * 0.1
        # P268 far proxy: the four digit cells read as one lit strip beyond the LOD1 distance (6 x 20 px at 25 m)
        strip = box((dw * 4.9, dep + 0.04, rh * 0.62), (dw * 1.95, 0.0, z), mat="lamp")
        p.append(detail(array(box((dw, dep + 0.04, rh * 0.62), (w * 0.0, 0.0, z), mat="lamp"), 4, (dw * 1.3, 0.0, 0.0)),
                        proxy=strip))
        p.append(detail(box((0.04, dep + 0.045, 0.05), (w * 0.0 + dw * 2.6 - dw * 0.65, 0.0, z - rh * 0.25), mat="lamp")))
        z -= rh * 1.25
    return p


def pylon(name: str) -> Piece:
    """Roadside price pylon (photos 1, 7, 15): monolith (S / M / L: operator body, mark panel on top, stacked
    price rows, name slot at the foot) or `dims.pole = 1` (a price head on twin poles, head top at 6-8 m, photos
    1, 15). Sizes and style are data."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc["operator"]]
    h, w, dep, rows = d["height"], d["width"], d["depth"], int(d["rows"])
    rh = d["row_h"]
    if d.get("pole", 0) >= 1:
        hh = d["head_h"]
        zb = h - hh
        p = [detail(dict(box((0.5, 0.5, 0.25), (s * w * 0.32, 0.0, 0.125), SK.STONE), bevel_lod0=True))
             for s in (-1, 1)]                                          # P268: plinths LOD0 only (still bevelled)
        p += [box((0.2, 0.2, zb + 0.2), (s * w * 0.32, 0.0, (zb + 0.2) / 2), SK.GALV_D) for s in (-1, 1)]
        p += [box((w, dep, hh), (0.0, 0.0, zb + hh / 2), op["fascia"]),
              box((w + 0.06, dep + 0.06, 0.1), (0.0, 0.0, zb + 0.05), op["stripe"]),
              box((w + 0.04, dep + 0.04, w * 0.62), (0.0, 0.0, h - w * 0.31), op["soffit"]),
              box((w + 0.06, dep + 0.06, 0.1), (0.0, 0.0, h - w * 0.62 - 0.05), op["stripe"])]
        for fy in (-1, 1):
            p += _mark(op, (0.0, fy * dep / 2, h - w * 0.31), w * 0.24, fy)
        p += _price_rows(w, dep, rh, h - w * 0.62 - 0.2 - rh / 2, rows)
        p.append(box((w - 0.14, dep + 0.02, 0.3), (0.0, 0.0, zb + 0.3), op["letter"]))
        return Piece(name, w + 0.3, h, p, budget=doc["budget_low"]["tris_lod0"], refs=doc["refs"])
    base = 0.3
    top = w * 0.9                                  # a bigger mark panel than v1 (critic fix 7)
    p = [box((w + 0.3, dep + 0.3, base), (0.0, 0.0, base / 2), SK.STONE),
         box((w, dep, h - base), (0.0, 0.0, base + (h - base) / 2), op["fascia"]),
         box((w + 0.04, dep + 0.04, top), (0.0, 0.0, h - top / 2), op["soffit"]),
         box((w + 0.06, dep + 0.06, 0.12), (0.0, 0.0, h - top - 0.06), op["stripe"])]
    for fy in (-1, 1):
        p += _mark(op, (0.0, fy * dep / 2, h - top / 2), w * 0.36, fy)
    p += _price_rows(w, dep, rh, h - top - 0.25 - rh / 2, rows)
    p.append(box((w - 0.14, dep + 0.02, 0.32), (0.0, 0.0, base + 0.45), op["letter"]))     # name slot (SIGN anchor)
    return Piece(name, w + 0.3, h, p, budget=doc["budget_low"]["tris_lod0"], refs=doc["refs"])


def shop(name: str) -> Piece:
    """Single-storey shop / food-mart + lube bay behind the canopy (research: office, shop, roller shutter, long
    fascia board, extinguishers; photos 9, 13 background). Front faces -y. Sign board = signage atlas placeholder."""
    doc = load(name)
    d = doc["dims"]
    W, D, H = d["width"], d["depth"], d["height"]
    hw = W / 2
    wall = SK.WALL_FAMILIES["cream"]
    op = operators()[doc.get("operator", "batch")]
    p = [box((W, D, H), (0.0, D / 2, H / 2), wall, uv="body"),
         box((W + 0.04, D + 0.04, 0.6), (0.0, D / 2, 0.3), "#8E8A82"),
         box((W + 0.2, D + 0.2, 0.55), (0.0, D / 2, H + 0.27), wall, uv="body"),
         box((W + 0.24, D + 0.24, 0.08), (0.0, D / 2, H + 0.58), SK.STONE),
         # front canopy overhang with downlights
         box((W + 0.4, 1.5, 0.16), (0.0, -0.75, H - 0.35), SK.WHITE),
         box((W + 0.44, 0.06, 0.3), (0.0, -1.5, H - 0.35), SK.GALV_D),
         # full-width operator fascia on the parapet, lit lip under it, sign board (T_Signage_A cell placeholder;
         # fuel text needs its own cell) (photo 9)
         box((W + 0.26, 0.06, 0.5), (0.0, -0.13, H + 0.27), op["fascia"]),
         box((W + 0.26, 0.07, 0.06), (0.0, -0.14, H + 0.02), mat="lamp"),
         box((5.6, 0.12, 0.7), (-hw + 3.4, -0.2, H + 0.27), mat="sign", uv=("sign", 3, 1)),
         # shop glass (uv "shop": SHD_HeroLit draws a warm lit interior behind black glass) with frame and door
         # (P259) a stall riser, a transom and a deep surround so the glazing sits in a framed opening (refs 5,
         # 6, 9: kiosk glass on a low riser, transom light, aluminium box surround), not a black panel on the wall
         box((5.8, 0.06, 2.2), (-hw + 3.4, -0.02, 1.55), mat="glass", uv="shop"),
         array(box((0.08, 0.1, 2.2), (-hw + 0.5, -0.05, 1.55), SK.SHOP_FRAME), 6, (1.16, 0.0, 0.0)),
         box((5.84, 0.12, 0.45), (-hw + 3.4, -0.06, 0.45 / 2 + 0.01), SK.SHOP_FRAME),          # stall riser
         box((5.9, 0.13, 0.07), (-hw + 3.4, -0.07, 2.12), SK.SHOP_FRAME),                      # transom
         box((6.3, 0.28, 0.2), (-hw + 3.4, -0.14, 2.71), SK.GALV),                             # surround head
         box((0.16, 0.28, 2.81), (-hw + 0.37, -0.14, 1.4), SK.GALV),                           # jambs
         box((0.16, 0.28, 2.81), (-hw + 6.43, -0.14, 1.4), SK.GALV),
         box((1.1, 0.14, 2.2), (-hw + 3.9, -0.07, 1.1), SK.SHOP_FRAME),
         box((0.9, 0.16, 2.0), (-hw + 3.9, -0.08, 1.05), mat="glass", uv="shop"),
         # lube / tyre bay: roller shutter half up, dark bay behind
         box((3.0, 0.05, 1.4), (hw - 2.0, -0.02, 0.7), "#2B2826"),
         box((3.0, 0.1, 1.5), (hw - 2.0, -0.05, 2.15), "#9BA0A1"),
         box((3.2, 0.3, 0.32), (hw - 2.0, -0.15, 3.05), SK.GALV_D),
         box((0.4, 0.2, 2.9), (hw - 0.3, -0.05, 1.45), wall, uv="body"),
         # chest freezer (white, blue lid band) beside the door (ref_09 shop fronts)
         box((1.3, 0.7, 0.85), (-hw + 1.2, -0.95, 0.43), PAINT_W),
         box((1.32, 0.72, 0.1), (-hw + 1.2, -0.95, 0.8), "#2D5E95"),
         # gas-cylinder cage at the side: frame, roof, cylinders
         box((1.5, 0.8, 0.06), (-hw - 0.9, 2.2, 1.55), SK.GALV_D)]
    p += [box((0.05, 0.05, 1.55), (-hw - 0.9 + sx * 0.72, 2.2 + sy * 0.37, 0.78), SK.GALV_D)
          for sx in (-1, 1) for sy in (-1, 1)]
    p += [array(cyl(0.16, 0.62, (-hw - 1.5, 2.2, 0.0), segs=8, paint=FIRE_RED, r2=0.14), 4, (0.4, 0.0, 0.0))]
    # roof: water tank on a stand, two AC condensers; back wall: door, two high windows, downpipes (the shop is
    # seen from the road and the queue on every side)
    p += [box((1.4, 1.4, 0.08), (hw - 1.6, D - 1.4, H + 1.1), SK.GALV_D),
          cyl(0.62, 1.15, (hw - 1.6, D - 1.4, H + 1.14), segs=10, paint="#2A2B2D"),
          array(box((0.9, 0.4, 0.65), (-hw + 1.5, D - 1.0, H + 0.95), SK.GALV), 2, (1.3, 0.0, 0.0)),
          box((1.0, 0.08, 2.1), (hw - 2.5, D + 0.02, 1.05), "#6B6E70"),
          array(box((1.1, 0.06, 0.6), (-hw + 1.8, D + 0.01, 2.2), mat="glass"), 2, (3.0, 0.0, 0.0)),
          array(cyl(0.05, H + 0.6, (-hw + 0.2, D + 0.08, 0.0), segs=6, paint=SK.GALV_D), 2, (W - 0.4, 0.0, 0.0)),
          box((0.06, 1.0, 0.7), (-hw - 0.01, D * 0.62, 2.1), mat="glass")]
    p.append(detail(array(box((0.03, 0.08, 0.6), (-hw + 1.35, D + 0.05, 2.2), SK.IRON), 9, (0.11, 0.0, 0.0))))
    p.append(detail(array(box((0.03, 0.08, 0.6), (-hw + 4.35, D + 0.05, 2.2), SK.IRON), 9, (0.11, 0.0, 0.0))))
    p.append(detail(array(box((1.5, 0.03, 0.03), (-hw - 0.9, 1.81, 0.3), SK.GALV_D), 4, (0.0, 0.0, 0.35))))
    p.append(detail(array(cyl(0.3, 0.1, (-hw + 1.5, D - 0.79, H + 0.95), segs=8, paint=SK.IRON, axis="y"), 2,
                          (1.3, 0.0, 0.0))))
    p.append(detail(array(box((3.0, 0.11, 0.025), (hw - 2.0, -0.05, 1.5), SK.GALV_D), 10, (0.0, 0.0, 0.15))))
    p.append(detail(array(box((0.6, 0.35, 0.05), (-hw + 1.4, -0.75, H - 0.44), mat="lamp"), 4, (2.4, 0.0, 0.0))))
    # extinguishers, AC units on the side wall, a bin (detail); the air / water post stands at the forecourt edge,
    # seen from the road (critic 18), so it stays on LOD1
    p += details([array(cyl(0.09, 0.55, (-hw + 0.35, -0.12, 0.72), segs=8, paint=FIRE_RED), 2, (6.6, 0.0, 0.0)),
                  array(box((0.3, 0.8, 0.55), (hw + 0.16, 1.2, 1.8), SK.GALV), 2, (0.0, 1.4, 0.0)),
                  cyl(0.25, 0.85, (-hw - 0.4, 0.6, 0.0), segs=8, paint="#2E7D3E"),
                  cyl(0.18, 0.08, (hw - 0.3, -2.74, 0.95), segs=10, paint=RUBBER, axis="y")])
    p += [box((0.25, 0.25, 1.3), (hw - 0.3, -2.6, 0.65), "#2D5E95"),
          box((0.5, 0.5, 0.1), (hw - 0.3, -2.6, 0.05), SK.STONE)]
    return Piece(name, W, H + 0.62, p, budget=doc["budget_low"]["tris_lod0"], bevel=0.0, refs=doc["refs"])


def pavers(name: str) -> Piece:
    """Interlocking paver patch (photos 3, 5, 6, 15) with a painted kerb on the road edge and a drain strip."""
    doc = load(name)
    d = doc["dims"]
    W, L = d["width"], d["length"]
    p = [box((W, L, G), (0.0, L / 2, G / 2), mat="cobble", uv="world"),
         box((W, 0.25, 0.16), (0.0, 0.125, 0.08), SAFETY_Y),
         array(box((0.5, 0.26, 0.164), (-W / 2 + 0.5, 0.125, 0.08), SAFETY_K), int(W / 1.0), (1.0, 0.0, 0.0)),
         box((W - 0.4, 0.3, 0.012), (0.0, L * 0.55, G + 0.004), "#3A3A3C")]
    p.append(detail(array(box((0.03, 0.3, 0.016), (-W / 2 + 0.3, L * 0.55, G + 0.006), SK.GALV_D),
                          int((W - 0.4) / 0.3), (0.3, 0.0, 0.0))))
    return Piece(name, W, 0.2, p, budget=doc["budget_low"]["tris_lod0"], refs=doc["refs"])


def cones(name: str) -> Piece:
    """Six traffic cones, two red-and-white pipe barriers round a dispenser end (photo 16) and a striped
    A-frame board (photos 5, 6, 10)."""
    doc = load(name)
    p = []
    for i in range(6):
        y = i * 1.2
        p += [box((0.38, 0.38, 0.04), (0.0, y, 0.02), SK.BLACK),
              far_sides(cyl(0.16, 0.66, (0.0, y, 0.04), segs=8, paint=CONE, r2=0.03), 4),    # P268: 13 px at 25 m
              far_sides(cyl(0.105, 0.12, (0.0, y, 0.36), segs=8, paint=SK.WHITE, r2=0.085), 4)]
    for k, x in enumerate((1.2, 2.6)):
        p.append(far_sides(tube([(x, 0.0, 0.0), (x, 0.0, 0.9), (x, 1.0, 0.9), (x, 1.0, 0.0)], 0.04, segs=6,
                                paint=SK.WHITE), 3))
        p.append(detail(array(cyl(0.045, 0.2, (x, 0.0, 0.15), segs=6, paint=FIRE_RED), 2, (0.0, 0.0, 0.4))))
        p.append(detail(array(cyl(0.045, 0.2, (x, 1.0, 0.15), segs=6, paint=FIRE_RED), 2, (0.0, 0.0, 0.4))))
        p.append(detail(cyl(0.045, 0.24, (x, 0.62, 0.9), segs=6, paint=FIRE_RED, axis="y")))
    for prof in ([(-0.3, 0.0), (-0.22, 0.0), (0.04, 1.0), (-0.04, 1.0)],
                 [(0.22, 0.0), (0.3, 0.0), (0.04, 1.0), (-0.04, 1.0)]):     # A-frame barrier: two leaning boards
        p.append(sweep([(1.4, 0.0, 0.0), (2.6, 0.0, 0.0)], [(3.5 + px, pz) for px, pz in prof], SAFETY_Y))
    p.append(array(box((0.12, 0.3, 0.45), (1.55, 3.5, 0.62), SAFETY_K), 4, (0.3, 0.0, 0.0)))
    return Piece(name, 3.0, 1.0, p, budget=doc["budget_low"]["tris_lod0"], refs=doc["refs"])


def _pictogram(x, y, z, ny, kind) -> list:
    """Prohibition sign with no text (no smoking / no phone): white plate, red ring, red bar, black symbol; faces
    -y when ny < 0."""
    f = y + ny * 0.02
    p = [box((0.42, 0.03, 0.42), (x, y, z), SK.WHITE),
         cyl(0.18, 0.012, (x, f, z), segs=10, paint=FIRE_RED, axis="y"),
         cyl(0.145, 0.016, (x, f + ny * 0.004, z), segs=10, paint=SK.WHITE, axis="y")]
    if kind == "smoke":
        p.append(box((0.2, 0.02, 0.04), (x, f + ny * 0.012, z), SK.BLACK))
    else:
        p.append(box((0.08, 0.02, 0.16), (x, f + ny * 0.012, z), SK.BLACK))
    yb = f + ny * 0.022
    p.append(tube([(x - 0.105, yb, z + 0.105), (x + 0.105, yb, z - 0.105)], 0.018, segs=4, paint=FIRE_RED))
    return p


def props(name: str) -> Piece:
    """Small forecourt props, one draw (critic 11, 13, 15; photos 4, 6, 10, 16). `_A` island-end set laid along
    the island axis (+y), at most 1.1 m wide so it fits between two lanes: lube rack with bottles, squeegee bucket,
    bin, extinguisher stand with sand bucket, no-smoking / no-phone signs on a post. `_B` queue set: jerry cans,
    plastic stool, chain-post barrier."""
    doc = load(name)
    op = operators()[doc.get("operator", "batch")]
    p = []
    if name.endswith("_A"):
        # lube rack: two posts, three shelves, bottles in grade colours (front faces -y)
        p += [box((0.05, 0.4, 1.35), (s * 0.45, 0.4, 0.675), op["fascia"]) for s in (-1, 1)]
        p.append(array(box((0.9, 0.38, 0.03), (0.0, 0.4, 0.3), SK.GALV), 3, (0.0, 0.0, 0.42)))
        p.append(box((0.96, 0.42, 0.2), (0.0, 0.4, 1.45), op["fascia"]))
        p.append(box((0.9, 0.02, 0.12), (0.0, 0.18, 1.45), op["letter"]))
        for k in range(3):
            p.append(detail(array(box((0.1, 0.08, 0.2), (-0.36, 0.3, 0.42 + k * 0.42), GRADES[(k + 1) % len(GRADES)]),
                                  7, (0.12, 0.0, 0.0))))
        p.append(array(box((0.24, 0.16, 0.3), (-0.3, 0.42, 0.33 + 0.84 + 0.15), GRADES[1]), 3, (0.3, 0.0, 0.0)))
        # squeegee bucket and bin
        p += [cyl(0.16, 0.32, (-0.3, 1.0, 0.0), segs=8, paint=GRADES[3], r2=0.19),
              detail(box((0.03, 0.03, 0.9), (-0.3, 1.02, 0.6), SK.BLACK, rot=0.2)),
              cyl(0.22, 0.75, (0.25, 1.05, 0.0), segs=8, paint=SK.BIN["g"]),
              cyl(0.24, 0.06, (0.25, 1.05, 0.75), segs=8, paint=SK.BLACK)]
        # extinguisher stand + sand bucket
        p += [box((0.5, 0.25, 0.9), (0.0, 1.65, 0.45), FIRE_RED),
              array(cyl(0.08, 0.5, (-0.12, 1.5, 0.35), segs=6, paint=FIRE_RED), 2, (0.24, 0.0, 0.0)),
              cyl(0.15, 0.3, (0.0, 2.05, 0.0), segs=8, paint=FIRE_RED, r2=0.18),
              detail(cyl(0.16, 0.01, (0.0, 2.05, 0.28), segs=8, paint="#C9B48A"))]
        # signs on a post: no smoking over no phone, both faces
        p.append(box((0.06, 0.06, 2.0), (0.0, 2.45, 1.0), SK.GALV_D))
        for ny in (-1, 1):
            part = _pictogram(0.0, 2.45 + ny * 0.05, 1.75, ny, "smoke") + _pictogram(0.0, 2.45 + ny * 0.05, 1.27, ny,
                                                                                       "phone")
            p += details(part) if ny > 0 else part
        return Piece(name, 1.1, 2.0, p, budget=doc["budget_low"]["tris_lod0"], refs=doc["refs"])
    # _B queue set: three jerry cans, a plastic stool, a chain-post barrier (3 posts, 2 sagging chains)
    for k, (x, c) in enumerate(((0.0, FIRE_RED), (0.4, SAFETY_Y), (0.8, GRADES[0]))):
        p += [box((0.33, 0.17, 0.42), (x, 0.0, 0.21), c, rot=0.1 * k),
              detail(box((0.16, 0.05, 0.08), (x, 0.0, 0.46), c, rot=0.1 * k)),
              detail(cyl(0.025, 0.06, (x + 0.12, 0.0, 0.42), segs=6, paint=c))]
    p += [far_sides(cyl(0.17, 0.42, (1.6, 0.1, 0.0), segs=8, paint=GRADES[3], r2=0.14), 5),     # P268 far sides
          far_sides(cyl(0.2, 0.03, (1.6, 0.1, 0.42), segs=8, paint=GRADES[3]), 5)]
    for i in range(3):
        y = 1.0 + i * 1.5
        p += [far_sides(cyl(0.17, 0.05, (2.4, y, 0.0), segs=8, paint=SK.BLACK), 5),
              far_sides(cyl(0.03, 0.9, (2.4, y, 0.05), segs=6, paint=SAFETY_Y), 4),
              cyl(0.045, 0.05, (2.4, y, 0.95), segs=6, paint=SK.BLACK)]
    for i in range(2):
        y0 = 1.0 + i * 1.5
        p.append(far_sides(tube([(2.4, y0, 0.88), (2.4, y0 + 0.5, 0.72), (2.4, y0 + 1.0, 0.72), (2.4, y0 + 1.5, 0.88)],
                                0.012, segs=4, paint=FIRE_RED), 3))
    return Piece(name, 2.6, 1.0, p, budget=doc["budget_low"]["tris_lod0"], refs=doc["refs"])


def wall(name: str) -> Piece:
    """Low boundary wall, one tileable 6 m segment along +x (critic 16; photo 9): plastered block wall on a stone
    plinth, operator-colour band and white coping, end pillars with caps, a planter box with a clipped shrub in
    front; SLOT_Palm anchors mark palm / tree slots for the vegetation pass."""
    doc = load(name)
    d = doc["dims"]
    op = operators()[doc.get("operator", "batch")]
    L, H = d["length"], d["height"]
    wallc = SK.WALL_FAMILIES["white"]
    p = [box((L, 0.24, 0.2), (L / 2, 0.0, 0.1), SK.STONE),
         box((L, 0.2, H - 0.3), (L / 2, 0.0, 0.2 + (H - 0.3) / 2), wallc, uv="body"),
         box((L, 0.22, 0.14), (L / 2, 0.0, H - 0.17), op["fascia"]),
         box((L + 0.02, 0.28, 0.06), (L / 2, 0.0, H - 0.07), SK.WHITE)]
    for x in (0.0, L):                                      # pillars (shared with the next segment when tiled)
        p += [box((0.36, 0.36, H + 0.2), (x, 0.0, (H + 0.2) / 2), wallc),
              detail(box((0.44, 0.44, 0.08), (x, 0.0, H + 0.24), SK.WHITE)),       # P268: cap is LOD0 only
              detail(box((0.37, 0.37, 0.12), (x, 0.0, H - 0.1), op["stripe"]))]
    # planter box in front (-y) with a clipped shrub; dark soil
    px = L * 0.5
    p += [box((1.6, 0.55, 0.5), (px, -0.42, 0.25), SK.STONE),
          box((1.5, 0.45, 0.04), (px, -0.42, 0.49), "#3A3027"),
          # P268 far proxy: the two clipped shrubs read as one hedge block on LOD1 / LOD2
          detail(cyl(0.32, 0.45, (px - 0.4, -0.42, 0.45), segs=7, paint="#3F6B34", r2=0.22),
                 proxy=box((1.3, 0.45, 0.38), (px, -0.42, 0.66), "#44723A")),
          detail(cyl(0.3, 0.42, (px + 0.4, -0.42, 0.45), segs=7, paint="#4A7A3A", r2=0.2))]
    return Piece(name, L, H, p, budget=doc["budget_low"]["tris_lod0"], refs=doc["refs"])


def pieces() -> dict[str, Piece]:
    out = {n: canopy(n) for n in CANOPIES}
    for n in PARTS:
        kind = n.split("_")[1]
        out[n] = {"FuelPylon": pylon, "FuelShop": shop, "FuelPavers": pavers, "FuelCones": cones, "FuelProps": props,
                  "FuelWall": wall}[kind](n)
    return out
