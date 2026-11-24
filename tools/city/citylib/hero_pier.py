"""HERO_DeltaFacePier: the Delta Face pedestrian jetty and the giant flag on its plinth (one land-to-sea axis).

References (looked at only, nothing traced or textured): references/delta-face/pier_and_carts_2026-11-16
(pier_01 top-down axis, pier_02 jetty from above, pier_03 side view at sunset) and gf_07 / gf_08.

Measured, not guessed (all in metres):
- OSM way `man_made=pier` (tools/city/data/delta_face_2026-11-15.osm), projected with geo.CITYHUB: a T outline.
  Root (stem centre on the seawall line) (-140.20, 218.15); head far edge centre (-172.30, 207.75): axis bearing
  197.95 degrees from +x (east), i.e. the jetty points west-south-west, square to the seawall.
  Stem 3.0 m wide (OSM) x 26.66 m from the seawall to the head; head 10.4 m across x 7.08 m deep.
- Aerials: pier_02 head/stem width 3.4, head depth/stem width 2.4, stem length/width ~7.8 (OSM 3.5, 2.4, 8.9):
  OSM kept for lengths, stem widened to 3.2 m (pier_01 reads 3.2-3.6 m against the 10.4 m head).
- pier_01 at 0.18 m/px (head 10.4 m = 58 px): flag plinth 17 x 9 m centred 16 m inland of the seawall, lawn
  rectangles 10 m deep either side of a 5.4 m paved path, a 6 m paved band along the Green's edge, a small
  blue-roofed hut on the promenade 4.7 m left of the axis. The layout puts the Green's edge (terrace) at u = -10.0.
- Heights (citylib/layout.Heights): road 3.8 (z = 0 here), promenade 3.3, Green 3.95, sea 0, beach top 0.4.
  Deck 2.85 m above the sea (3 steps of 0.15 m down from the promenade, pier_02); squat square piers 1.8 m with
  short 5.69 m spans (pier_03: the pier is about a third of the bay, the slab edge reads as a 0.7 m fascia).

Local frame (HeroMesh): u along the axis towards the sea (u = 0 on the seawall line), v to the left of u, z up
from road level (the pivot). Round 3 (2026-11-17): the jetty, its rock shelf and the flag plinth are modelled in
Blender (citylib/pier_model.py: primitives + Bevel / PI_GN_EdgeWear / Weighted Normal, a GN-relief rock shelf,
tiling PBR sets MAT_HeroSurface_PierConcrete and MAT_HeroSurface_PierRock). This module keeps the measured
layout (constants, the column points, the railing run, shelf_z) and the small parts: the steel railing (GN,
citylib/gn/pier.py), mast, flag, hut, paving, lawn edging and the painted rectangle on FacadeTrim_A, plus the
lawn. COLOR_0 rgb carries the paint and weathering (gn/pier.apply_paint), alpha the baked AO.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import hero_bays as HB
from . import hero_geom as G
from . import materials as M

PIVOT = (-140.20, 218.15)
YAW_DEG = 197.95

# heights (local z = world - 3.8)
Z_PROM = -0.5
Z_GREEN = 0.15
Z_SEA = -3.8
Z_BED = -5.6          # column feet, buried in the rocks / sea bed
DECK_Z = -0.95        # deck top: 2.85 m above the sea
SLAB_T = 0.35
LIP = 0.10            # deck lip above the fascia's shadow line
FASCIA = 0.55         # slab + edge beam, the visible slab edge (pier_03: a thin band over tall columns)
XHEAD_D = 0.40        # crosshead depth under the slab
WET_Z = -3.0          # top of the dark wet / algae band on the columns
TIDE = 0.6            # round 4: the columns' tide line, metres above the sea (pier_03: dark wet lower third)

# plan
STEM_W = 3.2
LANDING_U = 2.4
STEP_RISE, STEP_TREAD, STEP_N = 0.15, 0.5, 3
STEM_START = LANDING_U + STEP_TREAD * STEP_N       # 3.9
HEAD_U0 = 26.66
HEAD_D = 7.08
HEAD_W = 10.4
SPANS = 4
SPAN = (HEAD_U0 - STEM_START) / SPANS             # 5.69
COL = 1.5             # pier_03: columns read taller than wide (about 1.3 : 1 above the sea)
HEAD_COL_U = (HEAD_U0 + 1.0, HEAD_U0 + HEAD_D - 1.0)
HEAD_COL_V = (-3.7, 0.0, 3.7)
RAIL_H = 1.05
RAIL_INSET = 0.14
RAIL_POST = 1.5       # round 4: curved post spacing on the head railing (gf_08)
PINK = (HEAD_U0 + 2.6 - 0.65, HEAD_U0 + 2.6 + 0.65, -2.4, 2.4)   # pier_02: 4.8 x 1.3 m, 2.6 m in from the stem

# the flag landmark, inland on the same axis
TERRACE_U = -10.0
BAND = (-16.0, -10.25, 24.0)          # paved band along the Green's edge: u0, u1, half width
PLINTH = (-21.0, -12.0, 8.0)          # base platform: u0, u1, half width
PLINTH_H = 0.60                       # raised slab: four 0.15 m courses, stairs front and back (pier_01 shadow)
PLINTH_RIM = 0.9                      # darker granite frame round the light top (pier_01)
PLINTH_STAIR = (2.5, 0.35)            # stair half width, tread
PEDESTAL = 0.8                        # half size of the low mast base (pier_01: no tall pedestal)
PEDESTAL_TOP = Z_GREEN + PLINTH_H + 0.5
MAST_U = (PLINTH[0] + PLINTH[1]) / 2  # -16.5
MAST_H = 32.0
MAST_R = (0.32, 0.13)
FLAG_W, FLAG_H = 12.0, 6.0            # generic 2:1 flag (Street Catalogue: stays generic until people decide)
PATH = (-46.0, PLINTH[0], 2.7)        # paved path inland of the plinth
LAWN = (-26.5, 2.7, 24.0)             # lawn rectangles: inland edge, inner and outer v
HUT = (-9.4, -6.6, -6.4, -3.0)        # u0, u1, v0, v1 on the promenade
HUT_H = 2.5

# paint (sRGB tints on COLOR_0; SHD_HeroLit multiplies the trim's albedo by rgb * 1.1)
PAINT = {
    "deck": (0.62, 0.47, 0.40),       # dull weathered rust-brown concrete (pier_02 median ~ (130, 88, 66))
    "concrete": (0.86, 0.80, 0.74),   # piers, fascias, crossheads: grey-brown weathered concrete
    "wet": (0.42, 0.44, 0.36),        # wet / algae band at the waterline
    "white": (1.0, 1.0, 1.0),         # rail, mast
    "pink": (0.92, 0.55, 0.55),       # faded red / pink painted rectangle (pier_02)
    "granite": (0.88, 0.90, 0.94),    # flag plinth top (pier_01: light grey ~ (197, 197, 196))
    "flag": (0.97, 0.97, 0.97),       # on the accent block (Pettah yellow): plain generic flag (own key: no AO)
    "paving": (0.95, 0.93, 0.90),     # path and band, light grey slabs
    "kerb": (0.85, 0.84, 0.82),
    "hut": (1.0, 0.98, 0.95),
    "roof": (0.36, 0.55, 0.85),       # blue roof (pier_01)
    "dark": (0.12, 0.12, 0.13),       # door and window openings
    "under": (0.66, 0.62, 0.58),      # slab soffits
    "steel": (0.93, 0.97, 1.0),       # head railing: light grey painted steel (gf_08), on the concrete cornice row
    "rock": (0.30, 0.29, 0.28),       # the flat dark rock shelf under the stem (pier_01, pier_02 ~ (57, 68, 69))
    "algae": (0.27, 0.34, 0.22),      # green weed on the shelf near the waterline (pier_01)
    "granite_dark": (0.62, 0.63, 0.66),   # plinth sides, rim and mast base
}
CONCRETE_BLOCK, CREAM_BLOCK, ACCENT_BLOCK = 1, 0, 2


@dataclass
class PierLayout(HB.FacadeLayout):
    """The facade layout (empty) plus the jetty's GN inputs."""
    pier_points: list = field(default_factory=list)    # (u, v, z, angle, kind): 0 stem bent, 1 span, 2 head column
    pier_rails: list = field(default_factory=list)     # polylines [(u, v, z), ...]: PI_GN_PierRailing runs

    def gn_extra(self, name, yaw, coll, lod, mats) -> list:
        """Extra GN objects for build_heroes._gn_parts (Blender only): spans, bents, columns, the head railing."""
        from .gn import pier
        return pier.objects(name, self, yaw, coll, lod, mats)


# --- helpers ------------------------------------------------------------------------------------

def _paint(m, colour, fn, *args, **kw) -> None:
    """Run a hero_geom primitive and paint the faces it added."""
    n0 = len(m.faces)
    fn(m, *args, **kw)
    for i in range(n0, len(m.faces)):
        m.colors[i] = colour


def _slab_top(m, u0, u1, v0, v1, z, block, paint_at, strip=3.2, ubreaks=(), vbreaks=()) -> None:
    """Flat top split into cells that stay within one trim body row (3.2 m) in v; real scale u = metres / 4.
    paint_at(u, v) -> colour of the cell centred there."""
    vs = sorted({v0, v1, *[x for x in vbreaks if v0 < x < v1],
                 *[v0 + strip * k for k in range(1, int((v1 - v0) / strip) + 1) if v0 + strip * k < v1]})
    us = sorted({u0, u1, *[x for x in ubreaks if u0 < x < u1]})
    for a, b in zip(us, us[1:]):
        for c, d in zip(vs, vs[1:]):
            base = v0 + strip * math.floor((c - v0) / strip + 1e-6)
            t0, t1 = (c - base) / strip, (d - base) / strip
            uv = [(a / 4, G.trim_v(block, G.BODY, t0)), (b / 4, G.trim_v(block, G.BODY, t0)),
                  (b / 4, G.trim_v(block, G.BODY, t1)), (a / 4, G.trim_v(block, G.BODY, t1))]
            m.add_face([(a, c, z), (b, c, z), (b, d, z), (a, d, z)], uv, G.TRIM, paint_at((a + b) / 2, (c + d) / 2))


def _sides(m, u0, u1, v0, v1, z0, z1, block, colour, row=G.BODY) -> None:
    _paint(m, colour, G.box, u0, u1, v0, v1, z0, z1, G.TRIM, block, row, top=False)


def _lawn(m, u0, u1, v0, v1, z) -> None:
    t = M.tile(M.LAWN_STRIPE)
    m.add_face([(u0, v0, z), (u1, v0, z), (u1, v1, z), (u0, v1, z)],
               [(u0 / t[0], v0 / t[1]), (u1 / t[0], v0 / t[1]), (u1 / t[0], v1 / t[1]), (u0 / t[0], v1 / t[1])],
               M.LAWN_STRIPE, (1.0, 1.0, 1.0))


# --- the jetty ----------------------------------------------------------------------------------

def jetty(hm: G.HeroMesh, lod: int) -> None:
    """Layout only (round 3): the landing, steps, deck, bents, T-head and columns are modelled in Blender
    (citylib/pier_model.jetty_pieces places them on these points); here: the GN points, the railing run and the
    faded painted rectangle (a paint layer on the head deck)."""
    mp = hm.plain
    hw = STEM_W / 2
    lay = hm.layout
    for k in range(SPANS):
        lay.pier_points.append((STEM_START + SPAN * k, 0.0, DECK_Z, 0.0, 1))
        if k:
            lay.pier_points.append((STEM_START + SPAN * k, 0.0, DECK_Z, 0.0, 0))
    for u in HEAD_COL_U:
        for v in HEAD_COL_V:
            lay.pier_points.append((u, v, DECK_Z, 0.0, 2))
    u0, u1, h2 = HEAD_U0, HEAD_U0 + HEAD_D, HEAD_W / 2
    pu0, pu1, pv0, pv1 = PINK
    # the faded painted rectangle: a paint layer 20 mm proud (clear of the deck's wear waviness; coplanar cells
    # would be dissolved away at LOD1)
    _slab_top(mp, pu0, pu1, pv0, pv1, DECK_Z + 0.02, CONCRETE_BLOCK, lambda u, v: PAINT["pink"])
    # the light grey steel railing round the head, open where the stem joins (pier_02, pier_03, gf_08)
    r = RAIL_INSET
    lay.pier_rails.append([(u0 + r, hw + 0.05, DECK_Z), (u0 + r, h2 - r, DECK_Z), (u1 - r, h2 - r, DECK_Z),
                           (u1 - r, -h2 + r, DECK_Z), (u0 + r, -h2 + r, DECK_Z), (u0 + r, -hw - 0.05, DECK_Z)])
    _ = lod


# --- the rock shelf ------------------------------------------------------------------------------

SHELF = (0.6, 24.0, 20.0)   # u0, u1, half width: rock armour at the seawall foot running out as a reef into the surf


def shelf_z(u: float, v: float) -> float:
    """Mean shelf top in metres above the sea (round 4, pier_01 / pier_02): rock armour piled against the seawall
    foot (1.1 m, above the 0.4 m beach), a low wet reef just proud of the sea out to about half the stem (the GN
    relief puts roughly half of it above the water there, awash in surf), then it drops under the sea before the
    head. Its sides sink under the beach strip and the sea from |v| 12 m, so the edge is ragged, not a slab."""
    if u < 2.5:
        z = 1.1 - 0.65 * (u - SHELF[0]) / (2.5 - SHELF[0])
    elif u < 6.0:
        z = 0.45 - 0.27 * (u - 2.5) / 3.5
    elif u < 14.0:
        z = 0.18 - 0.14 * (u - 6.0) / 8.0
    else:
        z = max(-1.2, 0.04 - 0.16 * (u - 14.0))
    a = abs(v)
    if a > 12.0:
        z -= 0.075 * (a - 12.0) * (1.0 + 0.5 * math.sin(0.7 * u + 0.4 * v))
    z += 0.05 * math.sin(1.3 * u + 0.5 * v) + 0.04 * math.sin(0.6 * v - 0.9 * u + 2.0)
    return z


# --- the flag landmark ---------------------------------------------------------------------------

def flag_landmark(hm: G.HeroMesh, lod: int) -> None:
    mb, mp = hm.bevel, hm.plain
    zg = Z_GREEN + 0.03
    pave = lambda u, v: PAINT["paving"]   # noqa: E731
    # paved band along the Green's edge and the path inland of the plinth (pier_01), kerbed lawns either side
    b0, b1, bw = BAND
    _slab_top(mp, b0, b1, -bw, bw, zg, CONCRETE_BLOCK, pave)
    p0, p1, pw = PATH
    _slab_top(mp, p0, p1, -pw, pw, zg, CONCRETE_BLOCK, pave)
    l0, lv0, lv1 = LAWN
    pl0, pl1, plw = PLINTH
    for s in (-1.0, 1.0):
        rects = [(l0, pl0, lv0, lv1), (pl0, b0, plw + 0.3, lv1)]
        for a, b, c, d in rects:
            vlo, vhi = (c, d) if s > 0 else (-d, -c)
            _lawn(mp, a, b, vlo, vhi, Z_GREEN + 0.04)
        if lod == 0:   # concrete edging round the lawn rectangles
            k = 0.12
            for a, b, c, d in ((l0 - k, l0, lv0, lv1 + k), (l0, b0, lv1, lv1 + k), (l0 - k, pl0, lv0 - k, lv0)):
                vlo, vhi = (c, d) if s > 0 else (-d, -c)
                _paint(mb, PAINT["kerb"], G.box, a, b, vlo, vhi, Z_GREEN - 0.05, Z_GREEN + 0.1, G.TRIM, CONCRETE_BLOCK,
                       G.REVEAL)
    # the raised plinth, its stairs and the mast base are modelled (pier_model.plinth_pieces)
    mast(hm, lod)
    flag(hm, lod)
    hut(hm, lod)


def mast(hm: G.HeroMesh, lod: int) -> None:
    mb = hm.bevel
    n = 16 if lod == 0 else 8
    z0, z1 = PEDESTAL_TOP, PEDESTAL_TOP + MAST_H
    r0, r1 = MAST_R
    cu = MAST_U

    def ring(r, z):
        return [(cu + r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), z) for i in range(n)]
    sections = [(r0 + 0.12, z0), (r0 + 0.12, z0 + 0.6), (r0, z0 + 0.7), (r1, z1)]
    for (ra, za), (rb, zb) in zip(sections, sections[1:]):
        a, b = ring(ra, za), ring(rb, zb)
        for i in range(n):
            j = (i + 1) % n
            u0, u1 = i / n * 2 * math.pi * 0.25 / 4, (i + 1) / n * 2 * math.pi * 0.25 / 4
            mb.add_face([a[i], a[j], b[j], b[i]], [(u0, G.trim_v(CREAM_BLOCK, G.BODY, 0.1)), (u1, G.trim_v(CREAM_BLOCK, G.BODY, 0.1)),
                         (u1, G.trim_v(CREAM_BLOCK, G.BODY, 0.6)), (u0, G.trim_v(CREAM_BLOCK, G.BODY, 0.6))],
                        G.TRIM, PAINT["white"])
    top = ring(r1, z1)
    mb.add_face(top, [(0.0, G.trim_v(CREAM_BLOCK, G.REVEAL, 0.5))] * n, G.TRIM, PAINT["white"])
    # truck (finial) on top
    _paint(mb, PAINT["white"], G.box, cu - 0.2, cu + 0.2, -0.2, 0.2, z1, z1 + 0.35, G.TRIM, CREAM_BLOCK, G.CORNICE)


FLAG_FLY_DEG = 35.0   # the onshore south-westerly carries the flag inland and to the north of the axis


def _fly(u, v, z):
    """Turn a flag point about the mast so the flag flies FLAG_FLY_DEG off the axis (readable from the jetty)."""
    a = math.radians(FLAG_FLY_DEG)
    du = u - MAST_U
    return (MAST_U + du * math.cos(a) + v * math.sin(a), -du * math.sin(a) + v * math.cos(a), z)


def flag(hm: G.HeroMesh, lod: int) -> None:
    """A plain generic flag flying inland (onshore sea breeze, pier_01): a waved sheet, two-sided, smooth."""
    mb = hm.bevel
    nu, nz = (18, 8) if lod == 0 else (8, 4)
    zt = PEDESTAL_TOP + MAST_H - 0.4
    x0 = MAST_U - MAST_R[1] - 0.05

    def p(i, k, side):
        s = i / nu                            # 0 at the hoist, 1 at the fly
        t = k / nz                            # 0 bottom, 1 top
        u = x0 - s * FLAG_W * (0.97 + 0.03 * math.cos(math.pi * t))
        amp = 0.08 + 0.42 * s
        v = amp * math.sin(2 * math.pi * (1.6 * s - 0.15 * t)) + side * 0.012
        z = zt - FLAG_H + t * FLAG_H - 0.35 * s * s * (1.0 - 0.5 * t)
        return _fly(u, v, z)
    for side in (1.0, -1.0):
        for i in range(nu):
            for k in range(nz):
                a, b, c, d = p(i, k, side), p(i + 1, k, side), p(i + 1, k + 1, side), p(i, k + 1, side)
                uv = [(x / 4 * 0.4, G.trim_v(ACCENT_BLOCK, G.BODY, 0.1 + 0.8 * y)) for x, y in
                      ((i / nu, k / nz), ((i + 1) / nu, k / nz), ((i + 1) / nu, (k + 1) / nz), (i / nu, (k + 1) / nz))]
                pts = [a, b, c, d] if side > 0 else [d, c, b, a]
                uvs = uv if side > 0 else uv[::-1]
                mb.add_face(pts, uvs, G.TRIM, PAINT["flag"])


def hut(hm: G.HeroMesh, lod: int) -> None:
    """Small blue-roofed hut on the promenade, seaward of the plinth (pier_01)."""
    mb = hm.bevel
    u0, u1, v0, v1 = HUT
    z0, z1 = Z_PROM, Z_PROM + HUT_H
    _paint(mb, PAINT["hut"], G.box, u0, u1, v0, v1, z0, z1, G.TRIM, CREAM_BLOCK, G.BODY, top=False)
    if lod == 0:   # door on the landward face, a window each side, a dark base band
        uc = (u0 + u1) / 2
        _paint(mb, PAINT["dark"], G.box, u0 - 0.02, u0, (v0 + v1) / 2 - 0.45, (v0 + v1) / 2 + 0.45, z0, z0 + 2.0,
               G.TRIM, CREAM_BLOCK, G.REVEAL, top=False)
        for v, d in ((v0, -0.02), (v1, 0.02)):
            a, b = (v + d, v) if d < 0 else (v, v + d)
            _paint(mb, PAINT["dark"], G.box, uc - 0.5, uc + 0.5, a, b, z0 + 1.0, z0 + 1.8, G.TRIM, CREAM_BLOCK,
                   G.REVEAL, top=False)
        _paint(mb, PAINT["granite"], G.box, u0 - 0.03, u1 + 0.03, v0 - 0.03, v1 + 0.03, z0, z0 + 0.3, G.TRIM,
               CONCRETE_BLOCK, G.REVEAL, top=False)
    # hipped roof, 0.35 m overhang, blue sheet
    o, rise = 0.35, 0.9
    a0, a1, b0, b1 = u0 - o, u1 + o, v0 - o, v1 + o
    ridge_h = (a1 - a0) / 2
    r0, r1 = (a0 + ridge_h, a1 - ridge_h) if (b1 - b0) > (a1 - a0) else (a0, a1)
    rv0, rv1 = (b0 + ridge_h, b1 - ridge_h)
    zr = z1 + rise
    zc = z1 - 0.05
    um = (a0 + a1) / 2
    ring = [(a0, b0, zc), (a1, b0, zc), (a1, b1, zc), (a0, b1, zc)]
    ridge = [(um, rv0, zr), (um, rv1, zr)]
    rv = lambda t: G.trim_v(CREAM_BLOCK, G.BODY, t)   # noqa: E731
    faces = [([ring[0], ring[1], ridge[0]], 3), ([ring[1], ring[2], ridge[1], ridge[0]], 4),
             ([ring[2], ring[3], ridge[1]], 3), ([ring[3], ring[0], ridge[0], ridge[1]], 4)]
    for pts, n in faces:
        uvs = [(p[0] / 4 + p[1] / 4, rv(min(1.0, max(0.0, (p[2] - zc) / rise)))) for p in pts]
        mb.add_face(pts, uvs, G.TRIM, PAINT["roof"])
    # fascia + soffit
    _paint(mb, PAINT["roof"], G.box, a0, a1, b0, b1, zc - 0.12, zc, G.TRIM, CREAM_BLOCK, G.REVEAL, top=False, bottom=True)
    _ = r0, r1


# --- far proxy -----------------------------------------------------------------------------------

def far(hm: G.HeroMesh) -> None:
    m = hm.plain
    u0, u1, hw = SHELF
    for a, b in ((u0, 12.0), (12.0, u1)):
        za, zb = shelf_z(a + 0.2, 0.0) + Z_SEA, shelf_z(b, 0.0) + Z_SEA
        m.add_face([(a, -hw + 4, za), (b, -hw + 4, zb), (b, hw - 4, zb), (a, hw - 4, za)],
                   [(0.0, G.trim_v(CONCRETE_BLOCK, G.BODY, 0.1))] * 4, G.TRIM, PAINT["rock"])
    hw, h2 = STEM_W / 2, HEAD_W / 2
    _paint(m, PAINT["deck"], G.box, 0.0, HEAD_U0, -hw, hw, DECK_Z - FASCIA, DECK_Z, G.TRIM, CONCRETE_BLOCK, G.BODY)
    _paint(m, PAINT["deck"], G.box, HEAD_U0, HEAD_U0 + HEAD_D, -h2, h2, DECK_Z - FASCIA, DECK_Z, G.TRIM,
           CONCRETE_BLOCK, G.BODY)
    for k in range(1, SPANS):
        u = STEM_START + SPAN * k
        _paint(m, PAINT["concrete"], G.box, u - COL / 2, u + COL / 2, -COL / 2, COL / 2, Z_SEA - 0.3, DECK_Z - FASCIA,
               G.TRIM, CONCRETE_BLOCK, G.BODY, top=False)
    for u in HEAD_COL_U:
        _paint(m, PAINT["concrete"], G.box, u - COL / 2, u + COL / 2, -h2 + 0.6, h2 - 0.6, Z_SEA - 0.3, DECK_Z - FASCIA,
               G.TRIM, CONCRETE_BLOCK, G.BODY, top=False)
    pl0, pl1, plw = PLINTH
    _paint(m, PAINT["granite"], G.box, pl0, pl1, -plw, plw, Z_GREEN - 0.1, Z_GREEN + PLINTH_H, G.TRIM, CONCRETE_BLOCK,
           G.CORNICE)
    cu = MAST_U
    _paint(m, PAINT["granite"], G.box, cu - PEDESTAL, cu + PEDESTAL, -PEDESTAL, PEDESTAL, Z_GREEN + PLINTH_H,
           PEDESTAL_TOP, G.TRIM, CONCRETE_BLOCK, G.BODY)
    _paint(m, PAINT["white"], G.box, cu - 0.2, cu + 0.2, -0.2, 0.2, PEDESTAL_TOP, PEDESTAL_TOP + MAST_H, G.TRIM,
           CREAM_BLOCK, G.BODY)
    zt = PEDESTAL_TOP + MAST_H - 0.4
    x0 = cu - 0.2
    pts = [_fly(x0, 0.0, zt - FLAG_H), _fly(x0 - FLAG_W, 0.0, zt - FLAG_H - 0.3), _fly(x0 - FLAG_W, 0.0, zt - 0.2),
           _fly(x0, 0.0, zt)]
    uv = [(0.0, G.trim_v(ACCENT_BLOCK, G.BODY, 0.1)), (0.5, G.trim_v(ACCENT_BLOCK, G.BODY, 0.1)),
          (0.5, G.trim_v(ACCENT_BLOCK, G.BODY, 0.9)), (0.0, G.trim_v(ACCENT_BLOCK, G.BODY, 0.9))]
    m.add_face(pts, uv, G.TRIM, PAINT["flag"])
    m.add_face(pts[::-1], uv[::-1], G.TRIM, PAINT["flag"])


def build(lod: int) -> G.HeroMesh:
    hm = G.HeroMesh(yaw_deg=YAW_DEG)
    if lod == 2:
        far(hm)
        return hm
    hm.layout = PierLayout()
    jetty(hm, lod)
    flag_landmark(hm, lod)
    return hm


def blender_parts(name: str, lay, lod: int, coll, yaw: float) -> list:
    """build_heroes hook (Blender only): the modelled jetty, plinth and rock shelf (citylib/pier_model)."""
    from . import pier_model
    return pier_model.parts(name, lay, lod, coll, yaw)


# --- hooks for build_heroes (Blender only) -------------------------------------------------------

def ao_grounds() -> list[tuple[float, float, float, float, float]]:
    """AO occluder planes in the local frame (u0, u1, v0, v1, z): the Green, the promenade, the sea bed."""
    return [(-120.0, TERRACE_U, -80.0, 80.0, Z_GREEN), (TERRACE_U, 0.0, -80.0, 80.0, Z_PROM),
            (0.0, 80.0, -80.0, 80.0, Z_SEA + 0.2)]


def pre_join(parts) -> None:
    """Per-face paint keys from the MeshData colours, before the AO bake clears the colour attributes."""
    from .gn import pier
    for ob in parts:
        pier.col_to_paint(ob)


def paint(ob) -> None:
    """Weathering paint, then the surf sheet (after the AO bake, so the foam never occludes the rock)."""
    from . import pier_model
    from .gn import pier
    pier.apply_paint(ob)
    pier_model.foam(ob)
