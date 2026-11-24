"""Seafront kit pieces and street props for Delta Face (greybox, real-world dimensions).

Same conventions as kit.py: local x along the wall/road, z up, outward face towards -y, pivot on the
ground. Street props use one shared material (MAT_Prop_Shared_Atlas) and take their colours from
vertex colours (Art Bible "Paint variation by vertex colour"), so every prop in a cell batches into
one material. Dimensions follow the reference photos and common street-furniture sizes.
"""
from __future__ import annotations

import math

from . import materials as M
from .mesh import MeshData, box, box_project, circle, hex_rgb, prism_ring, rect

MAT_PROP = M.PROP
MAT_SEAWALL = M.SEAWALL
MAT_KERB = M.CONCRETE       # bench-wall caps, steps, piles: weathered concrete
MAT_MARKING = M.STREET_TRIM  # zebra stripes use the street trim's zebra row
MAT_LAMP = M.LAMP  # lamp heads: its own slot so night lighting can drive emission later


def _metres(material):
    """rect() UVs at the material's real texture scale (metres / TILE_M) in the face's own frame."""
    tu, tv = M.tile(material)
    return lambda p, loc, ul, vl: (loc[0] / tu, loc[1] / tv)

C_TRUNK = hex_rgb("#8A6A4A")
C_FROND = hex_rgb("#4E9A3F")
C_FROND2 = hex_rgb("#6DB04F")
C_POLE = hex_rgb("#5E6B66")
C_LAMP = hex_rgb("#EFE3C8")
C_CREAM = hex_rgb("#EFE3C8")
C_STONE = hex_rgb("#D8CFBF")
C_WATER = hex_rgb("#3FA9B5")
C_POT = hex_rgb("#B5533C")
C_SHRUB = hex_rgb("#4E9A3F")
C_ROCK = hex_rgb("#8E8C88")
C_WHEEL = hex_rgb("#3A2E3F")
C_CANVAS = {"01": hex_rgb("#C8283C"), "02": hex_rgb("#E8B931"), "03": hex_rgb("#1E6FD9")}

# seawall, steps, lamps, bins, benches, bollards, railing and food carts moved to the street kit
# (citylib/street_kit.py data + citylib/gn/street.py Geometry Nodes); their heights stay importable here
from .street_kit import SEAWALL_H, STEPS_H, TERRACE_H  # noqa: E402,F401


def _ring_between(m: MeshData, a: list, za: float, b: list, zb: float, color, mat=MAT_PROP) -> None:
    """Side faces joining two rings of equal length (counter-clockwise), a below b."""
    n = len(a)
    for i in range(n):
        j = (i + 1) % n
        m.add_face([(a[i][0], a[i][1], za), (a[j][0], a[j][1], za), (b[j][0], b[j][1], zb), (b[i][0], b[i][1], zb)],
                   [(i / n, 0), ((i + 1) / n, 0), ((i + 1) / n, 1), (i / n, 1)], mat, color)


def palm_coconut() -> MeshData:
    """Coconut palm, ~10 m: leaning six-sided trunk in three segments, eight drooping fronds."""
    m = MeshData()
    segs = [(0.0, 0.0, 0.0, 0.24), (0.35, 0.0, 3.5, 0.2), (0.9, 0.0, 7.0, 0.17), (1.3, 0.0, 9.6, 0.15)]
    rings = [(circle(x, y, r, 6), z) for x, y, z, r in segs]
    for (ra, za), (rb, zb) in zip(rings, rings[1:]):
        _ring_between(m, ra, za, rb, zb, C_TRUNK)
    cx, cy, cz = 1.3, 0.0, 9.6
    m.add_face([(x, y, cz) for x, y in rings[-1][0]], [(0.5, 0.5)] * 6, MAT_PROP, C_TRUNK)
    for k in range(8):
        a = 2 * math.pi * k / 8 + 0.2
        ux, uy = math.cos(a), math.sin(a)
        px, py = -uy * 0.35, ux * 0.35  # half frond width
        pts = [(0.0, 0.0), (2.2, 0.35), (4.2, -1.3)]  # (distance out, height) along the frond
        col = C_FROND if k % 2 else C_FROND2
        for (d0, h0), (d1, h1) in zip(pts, pts[1:]):
            w0 = 0.15 if d0 == 0 else 1.0
            a0 = (cx + ux * d0 - px * w0, cy + uy * d0 - py * w0, cz + h0)
            b0 = (cx + ux * d0 + px * w0, cy + uy * d0 + py * w0, cz + h0)
            a1 = (cx + ux * d1 - px * 0.6, cy + uy * d1 - py * 0.6, cz + h1)
            b1 = (cx + ux * d1 + px * 0.6, cy + uy * d1 + py * 0.6, cz + h1)
            m.add_face([a0, a1, b1, b0], [(0, 0), (1, 0), (1, 1), (0, 1)], MAT_PROP, col)  # top
            off = -0.03
            m.add_face([(b0[0], b0[1], b0[2] + off), (b1[0], b1[1], b1[2] + off), (a1[0], a1[1], a1[2] + off),
                        (a0[0], a0[1], a0[2] + off)], [(0, 0), (1, 0), (1, 1), (0, 1)], MAT_PROP, col)  # underside
    return m




def plant_pot() -> MeshData:
    """Concrete planter with a clipped shrub (promenade edge), 0.7 m pot."""
    m = MeshData()
    _ring_between(m, circle(0, 0, 0.42, 8), 0.0, circle(0, 0, 0.55, 8), 0.7, C_POT)
    m.add_face([(x, y, 0.7) for x, y in circle(0, 0, 0.55, 8)], [(0.5, 0.5)] * 8, MAT_PROP, C_POT)
    prism_ring(m, circle(0, 0, 0.5, 6), 0.7, 1.35, MAT_PROP, C_SHRUB, taper=0.45)
    return m



def fountain_roundabout() -> MeshData:
    """Ornamental roundabout fountain, 10 m radius (scaled to the island): basin, two tiers,
    four guardian statue blocks (placeholders for hand-made statues)."""
    m = MeshData()
    outer, inner = circle(0, 0, 10.0, 24), circle(0, 0, 9.6, 24)
    prism_ring(m, outer, 0.0, 0.8, MAT_PROP, C_CREAM, cap=False)
    for i in range(24):  # rim between outer and inner rings
        j = (i + 1) % 24
        m.add_face([(outer[i][0], outer[i][1], 0.8), (outer[j][0], outer[j][1], 0.8),
                    (inner[j][0], inner[j][1], 0.8), (inner[i][0], inner[i][1], 0.8)],
                   [(0, 0), (1, 0), (1, 1), (0, 1)], MAT_PROP, C_CREAM)
        m.add_face([(inner[j][0], inner[j][1], 0.55), (inner[i][0], inner[i][1], 0.55),
                    (inner[i][0], inner[i][1], 0.8), (inner[j][0], inner[j][1], 0.8)],
                   [(0, 0), (1, 0), (1, 1), (0, 1)], MAT_PROP, C_CREAM)  # inner wall faces the water
    m.add_face([(x, y, 0.55) for x, y in inner], [(0.5 + x / 20, 0.5 + y / 20) for x, y in inner], MAT_PROP, C_WATER)
    _ring_between(m, circle(0, 0, 1.6, 8), 0.55, circle(0, 0, 1.1, 8), 1.8, C_CREAM)
    _ring_between(m, circle(0, 0, 1.1, 8), 1.8, circle(0, 0, 3.2, 8), 2.2, C_CREAM)
    m.add_face([(x, y, 2.2) for x, y in circle(0, 0, 3.2, 8)], [(0.5, 0.5)] * 8, MAT_PROP, C_WATER)
    _ring_between(m, circle(0, 0, 0.6, 8), 2.2, circle(0, 0, 0.4, 8), 3.6, C_CREAM)
    _ring_between(m, circle(0, 0, 0.4, 8), 3.6, circle(0, 0, 1.5, 8), 3.9, C_CREAM)
    m.add_face([(x, y, 3.9) for x, y in circle(0, 0, 1.5, 8)], [(0.5, 0.5)] * 8, MAT_PROP, C_WATER)
    prism_ring(m, circle(0, 0, 0.25, 6), 3.9, 5.2, MAT_PROP, C_CREAM, taper=0.2)
    for k in range(4):
        a = math.pi / 4 + k * math.pi / 2
        cx, cy = 6.5 * math.cos(a), 6.5 * math.sin(a)
        box(m, cx - 0.8, cy - 0.8, 0.55, cx + 0.8, cy + 0.8, 1.4, MAT_PROP, C_STONE)
        box(m, cx - 0.4, cy - 0.6, 1.4, cx + 0.4, cy + 0.6, 2.6, MAT_PROP, C_STONE)
    return m




C_TERRACOTTA = hex_rgb("#C98A62")


def lamp_monument() -> MeshData:
    """Stylised placeholder for the south roundabout's ornamental lamp monument (sv_01, sv_02, gf_19): a flared
    terracotta "tulip" plinth, four leaf-blade struts, a slim grey column and a crown of five lanterns, about 12.5 m (pale blades, terracotta base: sv_01).
    A stand-in until the hero is modelled by hand; no real-world design is copied."""
    m = MeshData()
    _ring_between(m, circle(0, 0, 1.5, 12), 0.0, circle(0, 0, 1.25, 12), 0.35, C_TERRACOTTA)   # foot
    _ring_between(m, circle(0, 0, 1.25, 12), 0.35, circle(0, 0, 0.45, 12), 1.9, C_TERRACOTTA)  # tulip flare
    m.add_face([(x, y, 1.9) for x, y in circle(0, 0, 0.45, 12)], [(0.5, 0.5)] * 12, MAT_PROP, C_TERRACOTTA)
    for k in range(4):                                                   # leaf-blade struts, both faces
        a = math.pi / 4 + k * math.pi / 2
        ca, sa = math.cos(a), math.sin(a)
        ta, tb = -sa, ca                                                 # across the blade
        r0, z0, r1, z1 = 0.4, 1.9, 1.35, 5.6
        quad = [(r0 * ca + ta * 0.28, r0 * sa + tb * 0.28, z0), (r0 * ca - ta * 0.28, r0 * sa - tb * 0.28, z0),
                (r1 * ca - ta * 0.06, r1 * sa - tb * 0.06, z1), (r1 * ca + ta * 0.06, r1 * sa + tb * 0.06, z1)]
        uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
        th = 0.035                                                       # a thin slab, not two coincident faces
        front = [(x + ca * th, y + sa * th, z) for x, y, z in quad]
        back = [(x - ca * th, y - sa * th, z) for x, y, z in quad]
        m.add_face(front, uv, MAT_PROP, C_STONE)                      # pale blades on the terracotta base (sv_01)
        m.add_face(list(reversed(back)), uv, MAT_PROP, C_STONE)
        for i in range(4):
            j = (i + 1) % 4
            m.add_face([back[i], back[j], front[j], front[i]], uv, MAT_PROP, C_STONE)
    prism_ring(m, circle(0, 0, 0.16, 8), 1.9, 11.4, MAT_PROP, C_POLE, taper=0.25)              # column
    _ring_between(m, circle(0, 0, 0.12, 8), 11.4, circle(0, 0, 0.5, 8), 11.6, C_POLE)        # crown cap
    for k in range(5):                                                   # five lanterns on short arms
        a = 2 * math.pi * k / 5
        cx, cy = 0.75 * math.cos(a), 0.75 * math.sin(a)
        box(m, cx - 0.2, cy - 0.2, 11.6, cx + 0.2, cy + 0.2, 12.2, MAT_PROP, C_LAMP)
        box(m, cx - 0.25, cy - 0.25, 12.2, cx + 0.25, cy + 0.25, 12.3, MAT_PROP, C_POLE)
    box(m, -0.22, -0.22, 11.6, 0.22, 0.22, 12.5, MAT_PROP, C_LAMP)
    return m


def revetment_rock() -> MeshData:
    """One armour-stone boulder (about 2.4 x 2.0 x 1.2 m), irregular, for groynes and revetments."""
    m = MeshData()
    jit = [1.0, 0.82, 1.1, 0.9, 1.05, 0.78, 0.95, 1.12]
    base = [(1.2 * j * math.cos(2 * math.pi * i / 8), 1.0 * j * math.sin(2 * math.pi * i / 8)) for i, j in enumerate(jit)]
    mid = [(0.85 * j * math.cos(2 * math.pi * i / 8 + 0.3), 0.7 * j * math.sin(2 * math.pi * i / 8 + 0.3))
           for i, j in enumerate(reversed(jit))]
    _ring_between(m, base, -0.2, mid, 0.75, None, M.ROCK)
    top = [(x * 0.45, y * 0.45) for x, y in mid]
    _ring_between(m, mid, 0.75, top, 1.15, None, M.ROCK)
    m.add_face([(x, y, 1.15) for x, y in top], [(0.5, 0.5)] * 8, M.ROCK)
    box_project(m, M.ROCK)
    return m


def zebra_crossing() -> MeshData:
    """Zebra crossing decal: eight 0.5 m stripes across 7.5 m (local x, scaled to the carriageway),
    3.0 m long (local y, along the road), 1 cm above the asphalt."""
    m = MeshData()
    for k in range(8):
        x0 = k * 1.0
        z0, z1 = M.TRIM_ZEBRA
        rect(m, (x0, 0.0, 0.01), (0.5, 0.0, 0.0), (0.0, 3.0, 0.0), MAT_MARKING,
             lambda p, loc, ul, vl: (loc[1] / 4.0, z0 + (z1 - z0) * loc[0] / 0.5))
    return m


def pier_pile() -> MeshData:
    """Square concrete pile, 0.6 m, unit height (scaled in z to reach the deck)."""
    m = MeshData()
    box(m, -0.3, -0.3, 0.0, 0.3, 0.3, 1.0, MAT_KERB)
    box_project(m, MAT_KERB)
    return m


C_BLACK = hex_rgb("#2B2630")
C_COPPER = hex_rgb("#B8653A")
C_PIER_BLUE = hex_rgb("#9CCFE0")
C_DECK = hex_rgb("#D8D3C8")
C_RED = hex_rgb("#C8283C")
C_GREEN = hex_rgb("#3F8F4A")
C_ORANGE = hex_rgb("#E8862A")
C_FLAG = hex_rgb("#E8B931")







def pier_pedestrian() -> MeshData:
    """Pedestrian pier module, 4.0 m long (x) x 3.0 m wide: light deck slab on a concrete leg, light-blue
    curved railings both sides. Pivot on the deck top; the leg reaches 3.8 m down into the surf."""
    m = MeshData()
    box(m, 0.0, -1.5, -0.4, 4.0, 1.5, 0.0, MAT_PROP, C_DECK, bottom=True)
    box(m, 1.4, -0.6, -3.8, 2.6, 0.6, -0.4, MAT_PROP, hex_rgb("#8C7B6B"))
    for side in (-1.0, 1.0):
        y0 = 1.45 * side
        for x in (0.0, 2.0):
            # curved post: two segments leaning outwards
            pts = [(x, y0, 0.0), (x, y0 + 0.12 * side, 0.6), (x, y0 + 0.02 * side, 1.15)]
            for (ax, ay, az), (bx, by, bz) in zip(pts, pts[1:]):
                box(m, ax - 0.04, min(ay, by) - 0.03, az, ax + 0.04, max(ay, by) + 0.03, bz, MAT_PROP, C_PIER_BLUE)
        box(m, 0.0, y0 - 0.04, 1.1, 4.0, y0 + 0.04 + 0.04 * side, 1.18, MAT_PROP, C_PIER_BLUE)
        box(m, 0.0, y0 + 0.06 * side - 0.02, 0.55, 4.0, y0 + 0.06 * side + 0.02, 0.6, MAT_PROP, C_PIER_BLUE)
    return m


def flagpole() -> MeshData:
    """Tall flagpole, 25 m, with a plain generic flag (people choose the real flag later)."""
    m = MeshData()
    box(m, -0.4, -0.4, 0.0, 0.4, 0.4, 0.5, MAT_PROP, C_STONE)
    _ring_between(m, circle(0, 0, 0.14, 6), 0.5, circle(0, 0, 0.06, 6), 25.0, C_LAMP)
    rect(m, (0.06, 0.0, 21.0), (4.5, 0.0, 0.0), (0.0, 0.0, 3.0), MAT_PROP, None, C_FLAG)
    rect(m, (4.56, 0.02, 21.0), (-4.5, 0.0, 0.0), (0.0, 0.0, 3.0), MAT_PROP, None, C_FLAG)
    return m


def cannon_plinth() -> MeshData:
    """Old black cannon on a stone plinth (a row lines the Green's seaward edge). Barrel points +x."""
    m = MeshData()
    box(m, -1.0, -0.6, 0.0, 1.0, 0.6, 0.6, MAT_PROP, hex_rgb("#B9A68C"))
    box(m, -0.75, -0.35, 0.6, 0.55, 0.35, 0.95, MAT_PROP, C_BLACK)       # carriage
    for x in (-0.55, 0.35):
        box(m, x - 0.22, -0.42, 0.6, x + 0.22, -0.35, 1.04, MAT_PROP, C_BLACK)
        box(m, x - 0.22, 0.35, 0.6, x + 0.22, 0.42, 1.04, MAT_PROP, C_BLACK)
    # barrel: eight-sided, tapering, raised towards the muzzle
    ring_a = [(0.0, 0.22 * math.cos(a), 0.22 * math.sin(a)) for a in [2 * math.pi * i / 8 for i in range(8)]]
    start, end = (-0.9, 0.0, 1.05), (1.5, 0.0, 1.45)
    for i in range(8):
        j = (i + 1) % 8
        a0 = (start[0], start[1] + ring_a[i][1], start[2] + ring_a[i][2])
        a1 = (start[0], start[1] + ring_a[j][1], start[2] + ring_a[j][2])
        b0 = (end[0], end[1] + ring_a[i][1] * 0.65, end[2] + ring_a[i][2] * 0.65)
        b1 = (end[0], end[1] + ring_a[j][1] * 0.65, end[2] + ring_a[j][2] * 0.65)
        m.add_face([a0, a1, b1, b0], [(0, 0), (1, 0), (1, 1), (0, 1)], MAT_PROP, C_BLACK)
    m.add_face([(end[0], end[1] + r[1] * 0.65, end[2] + r[2] * 0.65) for r in ring_a], [(0.5, 0.5)] * 8, MAT_PROP, C_BLACK)
    m.add_face([(start[0], start[1] + r[1], start[2] + r[2]) for r in reversed(ring_a)], [(0.5, 0.5)] * 8, MAT_PROP, C_BLACK)
    return m


def kiosk() -> MeshData:
    """Unbranded promenade kiosk, 2.4 x 1.4 x 2.3 m, plain red and white."""
    m = MeshData()
    box(m, -1.2, -0.7, 0.0, 1.2, 0.7, 1.0, MAT_PROP, C_RED)
    box(m, -1.2, -0.7, 1.0, 1.2, 0.7, 2.0, MAT_PROP, C_CREAM)
    box(m, -1.3, -0.85, 2.0, 1.3, 0.85, 2.3, MAT_PROP, C_RED)
    return m


def vendor_balloons() -> MeshData:
    """Balloon and toy vendor (placeholder): a pole with a cluster of coloured balloon blocks and a basket."""
    m = MeshData()
    box(m, -0.3, -0.3, 0.0, 0.3, 0.3, 0.5, MAT_PROP, C_TRUNK)
    _ring_between(m, circle(0, 0, 0.03, 4), 0.5, circle(0, 0, 0.03, 4), 2.2, C_POLE)
    colours = [C_RED, C_FLAG, hex_rgb("#FF3FA4"), hex_rgb("#1E6FD9"), C_GREEN, C_ORANGE]
    for k, c in enumerate(colours):
        a = 2 * math.pi * k / len(colours)
        cx, cy, cz = 0.35 * math.cos(a), 0.35 * math.sin(a), 2.3 + 0.25 * (k % 2)
        prism_ring(m, circle(cx, cy, 0.18, 6), cz, cz + 0.4, MAT_PROP, c, taper=0.5, cx=cx, cy=cy)
    return m


def fin_vertical() -> MeshData:
    """White vertical facade fin, 0.35 m wide, 0.8 m deep (outwards, -y), unit height (scaled in z)."""
    m = MeshData()
    box(m, -0.175, -0.8, 0.0, 0.175, 0.0, 1.0, MAT_PROP, hex_rgb("#EFE9DA"))
    return m
