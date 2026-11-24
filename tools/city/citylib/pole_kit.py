"""Roadside electricity poles, lamps and cable runs for the Delta Face circle (P134, rows WS-0110..0127 of the inventory).

Pure Python (no bpy), unit-tested. Every piece is a list of primitive parts; `tools/city/build_poles.py` builds the same
list in Blender and measures the triangles, this module counts them analytically so the budgets are tested without
Blender. Frame: pivot on the ground, +z up, local x ALONG the pole line (crossarms and wires run along y = across the
line; +y points to the road), as the placement markers (`POLE_<name>`) are yawed by citylib/poles.py.

What was taken from where (honest):
- Poly Haven `modular_electricity_poles` and `modular_electric_cables` (CC0, tools/sources/packs/): measured as PROPORTION
  references only. The poles pack is a 5-7 m wooden-pole HV kit (13k-tri poles, 0.34 m insulators, 0.55 x 0.61 x 0.3
  transformer, 1.2 m cross-arm); the cables pack is indoor surface conduit, not overhead spans. Nothing of their geometry
  or textures ships: the pieces below are re-modelled parametrically to the budgets (a 13k-tri pole retopo to 300 tris
  would be a rebuild anyway) with Cityhub LV types: spun concrete, steel angle arms, pin insulators.
- Photos (references/delta-face/streetview_2026-11-16): sv_06 and sv_11 show tall slim grey single-arm lamps on the sea
  side every ~35-40 m and ONE slim grey kerb pole on the land side, no overhead spans along Delta Face Centre Rd; sv_03
  shows the CCTV pole and a striped signal-pole base. Concrete LV poles with crossarms, H-frame transformers, telecom
  bundles and stays are NOT visible in the circle photos: they come from the inventory rows (Delta Face Street Catalogue
  FST-006 / FST-017, videos vid-00066 / 00067) and apply to the inland streets, so placement defaults to the land side
  and to inland districts (config `poles`, data/world/wear_rules.json by district).
"""
from __future__ import annotations

import math

# paint (sRGB hex into COLOR_0 rgb; AO goes to alpha)
CONC, CONC_D = "#A29F97", "#85827B"
GALV, GALV_D = "#A9ADA9", "#8C918F"
BLACK, IRON = "#2B2A2C", "#3B3D40"
PORC = "#B9A88F"
RED, YELLOW = "#C23A30", "#E0BE35"
XFMR = "#66736E"
CABLE = "#1D1D1F"
BULB = "#FFD98A"
PANEL, LENS = "#25354D", "#D9DDD6"
CAN_GREEN = "#4F6B55"


def box(x0, x1, y0, y1, z0, z1, paint=CONC):
    return ("box", (x0, x1, y0, y1, z0, z1), paint)


def prism(cx, cy, z0, z1, r0, r1, n, paint=GALV, top=True, bottom=False, rot=0.0):
    """n-gon frustum about +z (n=4 gives a square tapered pole section; radius is the circumradius)."""
    return ("prism", (cx, cy, z0, z1, r0, r1, n, rot), paint, top, bottom)


def tube(pts, r, n=3, paint=CABLE, caps=False):
    return ("tube", tuple(tuple(p) for p in pts), r, n, paint, caps)


def quad(p0, p1, p2, p3, paint=BULB, double=False):
    return ("quad", (p0, p1, p2, p3), paint, double)


def part_tris(part) -> int:
    t = part[0]
    if t == "box":
        return 12
    if t == "prism":
        n = part[1][6]
        return 2 * n + (n - 2 if part[3] else 0) + (n - 2 if part[4] else 0)
    if t == "tube":
        segs = len(part[1]) - 1
        n = part[3]
        return segs * 2 * n + (2 * (n - 2) if part[5] else 0)
    if t == "quad":
        return 4 if part[3] else 2
    raise ValueError(t)


def tris(parts) -> int:
    return sum(part_tris(p) for p in parts)


def extent_z(parts) -> tuple[float, float]:
    lo, hi = 1e9, -1e9
    for p in parts:
        t = p[0]
        if t == "box":
            lo, hi = min(lo, p[1][4]), max(hi, p[1][5])
        elif t == "prism":
            lo, hi = min(lo, p[1][2]), max(hi, p[1][3])
        elif t == "tube":
            for q in p[1]:
                lo, hi = min(lo, q[2]), max(hi, q[2])
        else:
            for q in p[1]:
                lo, hi = min(lo, q[2]), max(hi, q[2])
    return lo, hi


# ---- catenary ---------------------------------------------------------------------------------------------------
def catenary(length: float, sag: float, segs: int, x0=0.0, y=0.0, z=0.0, sag_k=1.0):
    """Points of a parabola-like sag (catenary at these slacks) from (x0, y, z) along +x; sag in metres at mid-span."""
    pts = []
    for i in range(segs + 1):
        u = i / segs
        pts.append((x0 + length * u, y, z - 4.0 * sag * sag_k * u * (1.0 - u)))
    return pts


# ---- concrete poles (WS-0115) -------------------------------------------------------------------------------------
def conc_pole(h: float) -> list:
    """Tapered spun-concrete pole, square section 0.24 m at the foot to 0.14 m at the top, a darker base band, a pole
    number plate and a top cap (Catalogue FST-006). Budget <= 300."""
    r0, r1 = 0.17, 0.10
    k = lambda z: r0 + (r1 - r0) * z / h   # noqa: E731
    return [prism(0, 0, 0.0, 1.0, k(0), k(1.0), 4, CONC_D, top=False, rot=math.pi / 4),
            prism(0, 0, 1.0, h * 0.5, k(1.0), k(h * 0.5), 4, CONC, top=False, rot=math.pi / 4),
            prism(0, 0, h * 0.5, h, k(h * 0.5), k(h), 4, CONC, top=True, rot=math.pi / 4),
            box(-0.02, 0.02, -k(h * 0.5) * 0.72, -k(h * 0.5) * 0.72 - 0.012, 2.1, 2.35, "#E8E4D6"),   # number plate
            prism(0, 0, h, h + 0.05, k(h) * 0.8, k(h) * 0.7, 4, GALV_D, top=True, rot=math.pi / 4)]


def _insulator(y, z):
    return prism(0, y, z, z + 0.13, 0.04, 0.025, 4, PORC, top=True, rot=math.pi / 4)


def crossarm(drop: float, wires=4, span=0.38, dead=False) -> list:
    """One 1.5 m steel-angle arm `drop` m below the pole top with two braces and `wires` pin (or strain) insulators."""
    z = -drop
    out = [box(-0.045, 0.045, -0.75, 0.75, z - 0.03, z + 0.03, GALV_D),
           box(-0.012, 0.012, -0.30, -0.02, z - 0.35, z - 0.33, GALV),
           box(-0.012, 0.012, 0.02, 0.30, z - 0.35, z - 0.33, GALV)]
    ys = [(i - (wires - 1) / 2) * span for i in range(wires)]
    for y in ys:
        out.append(_insulator(y, z + 0.03) if not dead else
                   prism(0.0, y, z + 0.03, z + 0.16, 0.04, 0.03, 4, PORC, top=True, rot=math.pi / 4))
    return out


def conc_arms(n: int, dead: bool = False) -> list:
    """`n` stacked arms hung from a marker at the pole top; 1 = top arm 0.25 m down, each next 0.6 m below."""
    parts = []
    for i in range(n):
        for p in crossarm(0.25 + 0.6 * i, dead=dead):
            parts.append(_shift(p, 0.0))
    return parts


def _shift(p, dz):
    return p   # arms are authored relative to the marker already (z negative = below)


# ---- H-frame transformer platform (WS-0116) -------------------------------------------------------------------------
def xfmr_h() -> list:
    """Two concrete poles 2.2 m apart along the line, steel platform, 100 kVA tank with fins, 3 HV + 4 LV bushings, 3
    fuse cutouts, earth wire, danger plate. Tank proportions from the Poly Haven transformer (0.55 x 0.61 x 0.3 beside
    a 0.14 pole = about 4 pole widths wide) scaled to a 100 kVA unit (0.85 x 0.55 x 0.95). Budget <= 1200."""
    h = 10.0
    parts = []
    for x in (-1.1, 1.1):
        parts += [_mv(p, x) for p in conc_pole(h)]
    pz = 5.2
    parts += [box(-1.3, 1.3, -0.55, 0.55, pz - 0.05, pz + 0.05, GALV_D),              # platform deck
              box(-1.3, 1.3, -0.45, -0.38, pz - 0.35, pz - 0.05, GALV),              # channel girders
              box(-1.3, 1.3, 0.38, 0.45, pz - 0.35, pz - 0.05, GALV),
              box(-0.425, 0.425, -0.275, 0.275, pz + 0.05, pz + 1.0, XFMR),          # tank
              box(-0.47, 0.47, -0.30, 0.30, pz + 1.0, pz + 1.06, XFMR),              # lid
              box(-0.12, 0.12, -0.30, -0.327, pz + 0.55, pz + 0.85, RED)]            # danger / rating plate
    for i in range(7):                                                             # cooling fins on both ends
        z = pz + 0.2 + i * 0.1
        parts += [box(-0.50, -0.425, -0.22, 0.22, z, z + 0.05, XFMR),
                  box(0.425, 0.50, -0.22, 0.22, z, z + 0.05, XFMR)]
    for i, x in enumerate((-0.28, 0.0, 0.28)):                                     # HV bushings (porcelain, tall)
        parts.append(prism(x, 0.0, pz + 1.06, pz + 1.40, 0.05, 0.03, 6, PORC, top=True))
    for i, x in enumerate((-0.36, -0.12, 0.12, 0.36)):                             # LV bushings, front
        parts.append(prism(x, -0.15, pz + 1.06, pz + 1.22, 0.035, 0.025, 4, PORC, top=True, rot=math.pi / 4))
    for x in (-0.55, 0.0, 0.55):                                                   # drop-out fuse cutouts on an arm
        parts += [box(x - 0.015, x + 0.015, -0.04, 0.04, h - 0.9, h - 0.4, "#7A6D5C"),
                  prism(x, 0.0, h - 0.4, h - 0.28, 0.045, 0.03, 4, PORC, top=True, rot=math.pi / 4)]
    parts += [box(-0.75, 0.75, -0.05, 0.05, h - 0.5, h - 0.44, GALV_D),
              tube([(1.12, 0.12, 0.0), (1.12, 0.12, h - 0.3)], 0.006, 3, GALV)]    # earth wire down the right pole
    return parts


def _mv(p, dx):
    """Shift one part along x."""
    t = p[0]
    if t == "box":
        a = p[1]
        return ("box", (a[0] + dx, a[1] + dx, *a[2:]), p[2])
    if t == "prism":
        a = p[1]
        return ("prism", (a[0] + dx, *a[1:]), *p[2:])
    raise ValueError(t)


# ---- telecom poles (WS-0117) ---------------------------------------------------------------------------------------
def telecom_pole(variant: str) -> list:
    """A: thin concrete 7 m. B: galvanised 7 m tube. Both carry two messenger clamps, a splice box and one cable coil
    loop (Catalogue FST-006, vid-00066/67). Budget <= 200."""
    if variant == "A":
        shaft = [prism(0, 0, 0.0, 3.5, 0.11, 0.085, 4, CONC_D, top=False, rot=math.pi / 4),
                 prism(0, 0, 3.5, 7.0, 0.085, 0.065, 4, CONC, top=True, rot=math.pi / 4)]
    else:
        shaft = [prism(0, 0, 0.0, 3.5, 0.075, 0.065, 8, GALV_D, top=False),
                 prism(0, 0, 3.5, 7.0, 0.065, 0.045, 8, GALV, top=True)]
    z = 6.3
    ring = [(0.20 * math.cos(a), 0.16 + 0.20 * math.sin(a) * 0.0 + 0.0, z - 0.8 + 0.20 * math.sin(a)) for a in
            [i * math.pi / 4 for i in range(9)]]
    coil = tube([(x, 0.18 + 0.0, zz) for x, _, zz in ring], 0.012, 3, CABLE)       # one loop hanging on the pole
    return shaft + [box(-0.04, 0.04, 0.0, 0.40, z - 0.03, z + 0.03, GALV_D),           # messenger bracket
                    box(-0.04, 0.04, 0.0, 0.40, z - 1.0, z - 0.94, GALV_D),
                    box(-0.12, 0.12, 0.10, 0.20, z - 1.9, z - 1.55, "#6B6F72"),          # splice box
                    coil]


# ---- stay (WS-0118) --------------------------------------------------------------------------------------------------
def stay(h_attach=8.4, reach=3.6) -> list:
    """Stay wire from `h_attach` on the pole (at -x, the line end) to a ground anchor block; guard sleeve to 2.2 m."""
    d = (-reach, 0.0, 0.0)
    top = (-0.12, 0.0, h_attach)
    foot = (d[0], 0.0, 0.25)
    sleeve_len = 2.2
    f = sleeve_len / math.dist(top, foot)
    sl = (foot[0] + (top[0] - foot[0]) * f, 0.0, foot[2] + (top[2] - foot[2]) * f)
    return [tube([top, foot], 0.007, 3, GALV_D),
            tube([foot, sl], 0.035, 4, YELLOW),                                       # yellow guard sleeve (FST-006)
            box(d[0] - 0.3, d[0] + 0.3, -0.25, 0.25, 0.0, 0.25, CONC_D)]


# ---- decorative and special lamps (WS-0110..0113) ----------------------------------------------------------------
def lamp_ring() -> list:
    """Black cast pole ~4.5 m, flared foot, ring-top crown and lantern (Green edge, hotel frontage; vid-00039, GFG-012).
    Budget <= 600."""
    p = [prism(0, 0, 0.0, 0.25, 0.17, 0.12, 8, BLACK, top=False),
         prism(0, 0, 0.25, 0.45, 0.12, 0.085, 8, BLACK, top=False),
         prism(0, 0, 0.45, 3.5, 0.085, 0.065, 8, BLACK, top=False),
         prism(0, 0, 3.5, 3.62, 0.11, 0.11, 8, BLACK, top=False),                   # collar
         prism(0, 0, 3.62, 3.9, 0.065, 0.065, 8, BLACK, top=False),
         prism(0, 0, 3.9, 4.0, 0.15, 0.20, 8, BLACK, top=False),                    # lantern seat
         prism(0, 0, 4.0, 4.38, 0.20, 0.20, 6, "#E9E3D0", top=False),               # glass
         prism(0, 0, 4.38, 4.52, 0.26, 0.10, 6, BLACK, top=True)]                   # roof
    for i in range(6):                                                              # ring-top: 6 spokes of a crown ring
        a = i * math.pi / 3
        p.append(tube([(0.13 * math.cos(a), 0.13 * math.sin(a), 4.52), (0.13 * math.cos(a + math.pi / 3),
                                                                        0.13 * math.sin(a + math.pi / 3), 4.52)],
                      0.02, 4, BLACK))
    p.append(prism(0, 0, 4.52, 4.66, 0.03, 0.02, 8, BLACK, top=True))
    for i in range(4):                                                              # fluting rings on the shaft
        z = 0.9 + i * 0.7
        p.append(prism(0, 0, z, z + 0.05, 0.095 - 0.003 * i, 0.095 - 0.003 * i, 8, BLACK, top=False))
    return p


def lamp_solar() -> list:
    """Slim galvanised 5 m pole, 20 degree solar panel on top, LED head on a short arm, battery box (vid-00051). <= 400."""
    tilt = math.radians(20)
    cx, cz, w, d = 0.0, 5.12, 0.45, 0.30
    c, s = math.cos(tilt), math.sin(tilt)
    pts = [(cx - w * c, -d, cz - w * s), (cx + w * c, -d, cz + w * s), (cx + w * c, d, cz + w * s),
           (cx - w * c, d, cz - w * s)]
    top = [(x, y, z + 0.04) for x, y, z in pts]
    return [prism(0, 0, 0.0, 2.5, 0.06, 0.05, 8, GALV, top=False),
            prism(0, 0, 2.5, 5.0, 0.05, 0.04, 8, GALV, top=True),
            box(-0.18, 0.18, 0.04, 0.22, 2.4, 3.0, "#566067"),                      # battery box
            box(-0.05, 0.05, -0.02, 0.02, 4.9, 5.1, GALV_D),                        # head of the pole
            quad(*top, paint=PANEL),
            quad(pts[3], pts[2], pts[1], pts[0], paint=GALV_D),
            box(-0.18, 0.18, -0.9, -0.04, 4.78, 4.88, GALV_D),                      # arm
            box(-0.14, 0.14, -0.95, -0.55, 4.66, 4.78, LENS)]                       # LED head


def lamp_blue() -> list:
    """Promenade twin-globe lamp with a vertical blue LED strip on the shaft (vid-00061, FLT-002). Base twin-globe is
    the street kit's PROP_Lamp_TwinGlobe_01 (348 tris); this self-contained variant is base + 20. Budget <= 370."""
    p = [prism(0, 0, 0.0, 0.3, 0.16, 0.10, 12, GALV_D, top=False),
         prism(0, 0, 0.3, 4.2, 0.085, 0.06, 12, GALV, top=False),
         box(-0.7, 0.7, -0.03, 0.03, 4.15, 4.2, GALV_D)]
    for x in (-0.7, 0.7):
        p += [prism(x, 0, 4.2, 4.28, 0.07, 0.07, 8, GALV_D, top=False),
              prism(x, 0, 4.28, 4.56, 0.18, 0.18, 12, "#F0EBDD", top=True, bottom=False)]
    p += [box(-0.012, 0.012, -0.09, -0.096, 0.8, 3.4, "#4FA3FF"), box(-0.012, 0.012, 0.09, 0.096, 0.8, 3.4, "#4FA3FF")]
    return p


def flood_mast() -> list:
    """13.5 m tapered galvanised mast, a head ring with 5 flood heads, step bolts and a base plate (GFG-012, FLT-001)."""
    p = [prism(0, 0, 0.0, 0.35, 0.28, 0.2, 8, GALV_D, top=False),
         prism(0, 0, 0.35, 6.5, 0.2, 0.15, 8, GALV, top=False),
         prism(0, 0, 6.5, 13.0, 0.15, 0.08, 8, GALV, top=False),
         prism(0, 0, 13.0, 13.15, 0.45, 0.45, 8, GALV_D, top=True)]
    for i in range(5):
        a = i * 2 * math.pi / 5
        x, y = 0.55 * math.cos(a), 0.55 * math.sin(a)
        p += [box(x - 0.17, x + 0.17, y - 0.09, y + 0.09, 13.15, 13.55, "#4D5256"),
              box(x - 0.15, x + 0.15, y + math.copysign(0.09, y or 1) * 0.0 - 0.005, y + 0.005, 13.2, 13.5, LENS)]
    return p


def lamp_tall() -> list:
    """Slim grey single-arm road lamp, 9 m tapered tube, 1.8 m upswept arm over the carriageway (+y), LED head: the
    Delta Face Centre Rd lamp of sv_06 / sv_11 (one every ~35-40 m, sea side). Budget <= 300."""
    return [prism(0, 0, 0.0, 0.4, 0.11, 0.085, 8, GALV_D, top=False),
            prism(0, 0, 0.4, 4.5, 0.085, 0.07, 8, "#9EA2A3", top=False),
            prism(0, 0, 4.5, 9.0, 0.07, 0.05, 8, "#9EA2A3", top=True),
            tube([(0, 0, 8.7), (0, 0.5, 9.05), (0, 1.3, 9.45), (0, 1.8, 9.55)], 0.04, 4, "#9EA2A3"),
            box(-0.17, 0.17, 1.55, 2.25, 9.45, 9.57, "#B8BBB8"), box(-0.13, 0.13, 1.62, 2.18, 9.40, 9.45, LENS)]


def banner_pole() -> list:
    """6 m pole with two vertical banner arms in a cast concrete block (vid-00065, GFG-019)."""
    return [box(-0.45, 0.45, -0.45, 0.45, 0.0, 0.5, CONC_D),
            prism(0, 0, 0.5, 6.0, 0.06, 0.045, 8, GALV, top=True),
            box(-0.02, 0.02, 0.0, 0.9, 5.2, 5.25, GALV_D), box(-0.02, 0.02, 0.0, 0.9, 1.9, 1.95, GALV_D),
            box(-0.02, 0.02, 0.86, 0.9, 1.9, 5.25, GALV_D)]


def lamp_arm() -> list:
    """Street-lamp bracket for a concrete pole: 1.5 m upswept arm and an LED head, hung from the top marker."""
    return [box(-0.04, 0.04, 0.0, 1.45, -0.62, -0.57, GALV), box(-0.04, 0.04, 0.06, 0.3, -0.84, -0.62, GALV),
            box(-0.16, 0.16, 1.05, 1.62, -0.60, -0.50, "#C9CCC8"), box(-0.12, 0.12, 1.12, 1.52, -0.65, -0.60, LENS)]


def jbox() -> list:
    """Roadside distribution pillar (CEB service pillar / telecom cabinet) 0.8 x 0.4 x 1.2 on a plinth."""
    return [box(-0.45, 0.45, -0.25, 0.25, 0.0, 0.15, CONC_D), box(-0.4, 0.4, -0.2, 0.2, 0.15, 1.35, CAN_GREEN),
            box(-0.43, 0.43, -0.23, 0.23, 1.35, 1.41, GALV_D), box(-0.3, 0.3, -0.205, -0.21, 0.3, 1.2, "#44604B")]


# ---- wire runs (WS-0123..0127) --------------------------------------------------------------------------------------
SPAN_LENGTHS = (12.0, 18.0, 25.0, 32.0, 40.0)
ARM_Y = (-0.57, -0.19, 0.19, 0.57)        # the four conductors of the 1.5 m arm
SAG_FRAC = 0.025                           # mid-span sag / length for LV runs (short spans, tensioned)


def wire_lv(length: float, wires=4, segs=3) -> list:
    """LV conductors, 3 segments per wire as a 3-sided tube (6 tris): <= 24 per wire per span (WS-0123). Starts and ends
    at the insulator tops of a crossarm (marker at the pole top, arm 0.25 m down: wire at z = -0.25 + 0.03 + 0.13)."""
    z0 = -0.25 + 0.03 + 0.13
    ys = ARM_Y if wires == 4 else (-0.38, 0.0, 0.38)
    out = []
    for k, y in enumerate(ys):
        out.append(tube(catenary(length, length * SAG_FRAC * (1.0 + 0.12 * (k % 2)), segs, 0.0, y, z0), 0.008, 3, CABLE))
    return out


def wire_bundle(length: float) -> list:
    """Telecom / fibre spaghetti: three cables of 5-8 shown as triangular tubes with uneven sag and a slack loop
    (WS-0124). <= 60 per span: 3 cables x 3 segments x 6 = 54."""
    z0 = -1.0
    out = []
    for k, (y, sk, dr) in enumerate(((0.12, 1.0, 0.0), (0.17, 1.35, -0.04), (0.08, 0.8, -0.07))):
        pts = catenary(length, length * 0.03, 3, 0.0, y, z0 + dr, sag_k=sk)
        out.append(tube(pts, 0.014 if k == 0 else 0.010, 3, CABLE))
    return out


def wire_drop(length: float) -> list:
    """Service drop from the pole arm to a facade bracket: two 3-sided segments, <= 12 tris (WS-0125); dips 3 %."""
    z0 = -0.25 + 0.16
    return [tube(catenary(length, length * 0.03, 2, 0.0, 0.0, z0), 0.009, 3, CABLE)]


def wire_signal(length: float) -> list:
    """Signal cable strapped along a mast arm and across a junction (WS-0126): 2 segments x 2 cables x 6 = 24."""
    return [tube(catenary(length, length * 0.01, 2, 0.0, 0.0, 0.0), 0.012, 3, CABLE),
            tube(catenary(length, length * 0.01, 2, 0.0, 0.05, 0.03), 0.012, 3, CABLE)]


def wire_festoon(length: float) -> list:
    """Festoon: catenary string with a bulb card every 1.5 m, 4 tris per bulb (two crossed quads) (WS-0127)."""
    segs = max(2, int(length / 1.5))
    string = tube(catenary(length, length * 0.07, 4, 0.0, 0.0, 0.0), 0.006, 3, CABLE)
    out = [string]
    for i in range(1, segs):
        u = i / segs
        x, z = length * u, -4.0 * length * 0.07 * u * (1.0 - u)
        r = 0.045
        out += [quad((x - r, 0, z - 2 * r), (x + r, 0, z - 2 * r), (x + r, 0, z), (x - r, 0, z), BULB),
                quad((x, -r, z - 2 * r), (x, r, z - 2 * r), (x, r, z), (x, -r, z), BULB)]
    return out


# ---- the catalogue ----------------------------------------------------------------------------------------------------
class Piece:
    def __init__(self, name, parts, budget, row, low, refs=()):
        self.name, self.parts, self.budget, self.row, self.low, self.refs = name, parts, budget, row, low, tuple(refs)

    @property
    def tris(self):
        return tris(self.parts)


def pieces() -> dict[str, Piece]:
    out = {}

    def add(name, parts, budget, row, low, refs=()):
        out[name] = Piece(name, parts, budget, row, low, refs)

    for h in (9, 10, 11):
        add(f"POLE_Conc_{h}", conc_pole(float(h)), 300, "WS-0115",
            f"{tris(conc_pole(float(h)))} tris, 0 extra draws (MAT_StreetKit_A, merged per cell), 0 realtime lights", ("FST-006",))
    for n in (1, 2, 3):
        add(f"POLE_Arm_{n}", conc_arms(n), 80 * n, "WS-0115", f"{tris(conc_arms(n))} tris, same material", ("FST-006",))
    add("POLE_Arm_Dead", conc_arms(1, dead=True) + [_mirror_arm()], 160, "WS-0115",
        f"{tris(conc_arms(1, dead=True) + [_mirror_arm()])} tris (end-of-line / corner strain arm)", ("FST-006",))
    add("POLE_Xfmr_H", xfmr_h(), 1200, "WS-0116", f"{tris(xfmr_h())} tris, 1 per ~250 m of line", ("FST-006", "FST-017"))
    add("POLE_Telecom_A", telecom_pole("A"), 200, "WS-0117", f"{tris(telecom_pole('A'))} tris", ("vid-00066", "vid-00067"))
    add("POLE_Telecom_B", telecom_pole("B"), 200, "WS-0117", f"{tris(telecom_pole('B'))} tris", ("vid-00066", "vid-00067"))
    add("POLE_Stay", stay(), 40, "WS-0118", f"{tris(stay())} tris", ("FST-006",))
    add("POLE_LampArm", lamp_arm(), 120, "", f"{tris(lamp_arm())} tris", ("sv_06",))
    add("POLE_Lamp_Ring", lamp_ring(), 600, "WS-0110", f"{tris(lamp_ring())} tris", ("vid-00039", "GFG-012"))
    add("POLE_Lamp_Solar", lamp_solar(), 400, "WS-0111", f"{tris(lamp_solar())} tris", ("vid-00051",))
    add("POLE_Lamp_Tall", lamp_tall(), 300, "WS-0111", f"{tris(lamp_tall())} tris", ("sv_06", "sv_11"))
    add("POLE_Lamp_Blue", lamp_blue(), 370, "WS-0112", f"{tris(lamp_blue())} tris (base twin-globe 348 + 20)", ("vid-00061", "FLT-002"))
    add("POLE_Flood_Mast", flood_mast(), 500, "WS-0113", f"{tris(flood_mast())} tris", ("GFG-012", "FLT-001"))
    add("POLE_Banner", banner_pole(), 200, "WS-0122", f"{tris(banner_pole())} tris", ("vid-00065", "GFG-019"))
    add("POLE_JBox", jbox(), 120, "", f"{tris(jbox())} tris", ("sv_03",))
    for L in SPAN_LENGTHS:
        i = int(L)
        add(f"WIRE_LV4_L{i}", wire_lv(L), 96, "WS-0123", f"{tris(wire_lv(L))} tris per span (24 per wire), 0 draws", ("FST-006",))
        add(f"WIRE_LV3_L{i}", wire_lv(L, 3), 72, "WS-0123", f"{tris(wire_lv(L, 3))} tris per span", ("FST-006",))
        add(f"WIRE_Bundle_L{i}", wire_bundle(L), 60, "WS-0124", f"{tris(wire_bundle(L))} tris per span", ("vid-00053",))
    for L in (6.0, 10.0, 14.0):
        add(f"WIRE_Drop_L{int(L)}", wire_drop(L), 12, "WS-0125", f"{tris(wire_drop(L))} tris", ("FST-006",))
    for L in (12.0, 25.0):
        add(f"WIRE_Signal_L{int(L)}", wire_signal(L), 24, "WS-0126", f"{tris(wire_signal(L))} tris", ("vid-00053", "sv_11"))
    for L in (6.0, 10.0):
        add(f"WIRE_Festoon_L{int(L)}", wire_festoon(L), 24 + 4 * int(L / 1.5), "WS-0127",
            f"{tris(wire_festoon(L))} tris incl. 4 per bulb card, emissive in atlas", ("vid-00060", "FLT-003"))
    return out


def _mirror_arm():
    return box(-0.02, 0.02, -0.75, 0.75, -0.62, -0.58, GALV)   # back strut of the dead-end arm


def span_length_class(length: float) -> float:
    """The nearest built span piece for a real length (marker x scale = length / class, within about +-20 %)."""
    return min(SPAN_LENGTHS, key=lambda c: abs(c - length))
