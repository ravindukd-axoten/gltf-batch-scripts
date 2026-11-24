"""Tower-base pieces TWB_* (P146): the Delta Face tower podium kit as parametric pieces, from the p112 research estimates.

Numbers come from docs/research/delta-face-tower-bases.md (the row descriptions in docs/inventory/buildings_heroes.csv),
+-20 % and confidence M/L, so every piece is a generic block until agent photos exist (Q2-Q8 there). Frame as in
elements.py: x along the front from the piece's left edge, street/front on -y, wall face y = 0, z up from the pavement.
Pieces use the shared frontage trim sheet (MAT_FrontageTrim_A, light/worn swap); LED screen and sign faces take
MAT_SignGlow_A on their own 0-1 UV. Curved plans (porte-cochere, gatehouse roof, oval island) are 8-12 segment
polygons. Planting is a bed with clipped hedge and shrub mounds only: palms and frangipani come from the vegetation lane.
TWB_ConstructionHoarding is not built: the 2020-22 hoarding is superseded for the 2026 slice era (inventory row).
"""
from __future__ import annotations

import math

from classes import _st
from gnlib import S
from parts import TRIM, tag

REFS = ["docs/research/delta-face-tower-bases.md (p112)"]


def box(t, x0, x1, y0, y1, z0, z1, trim="CONCRETE", role="ACCENT", bevel=1.0):
    """Box that never squashes the trim sheet: a face taller (or deeper, for a top) than its trim row is promoted to the
    4 m WALL row, split into storeys (zb_cm/sh_cm, as the CLS buildings) and into strips under 3.6 m along y."""
    row = TRIM[trim][1][1]
    dz, dy = z1 - z0, y1 - y0
    if trim != "WALL" and (dz > row - 0.03 or dy > row - 0.03):
        trim = "WALL"
    if trim != "WALL":
        return tag(t, t.cube(x0, x1, y0, y1, z0, z1), trim, role, bevel)
    ns = max(1, int(math.ceil(dz / 3.9)))
    ny = max(1, int(math.ceil(dy / 3.6)))
    out = []
    for i in range(ns):
        za, zb_ = z0 + dz * i / ns, z0 + dz * (i + 1) / ns
        for j in range(ny):
            ya, yb = y0 + dy * j / ny, y0 + dy * (j + 1) / ny
            gap = 0.004
            out.append(_st(t, tag(t, t.cube(x0, x1, ya + (gap if j else 0), yb, za + (gap if i else 0), zb_), "WALL", role, bevel),
                           za, zb_ - za))
    return t.join(*out) if len(out) > 1 else out[0]


def cols(t, xs, y, z0, z1, r=0.2, trim="CONCRETE", role="ACCENT"):
    n = max(1, int(math.ceil((z1 - z0) / 3.9)))
    out = []
    for i in range(n):
        za, zb_ = z0 + (z1 - z0) * i / n, z0 + (z1 - z0) * (i + 1) / n
        out.append(_st(t, tag(t, t.join(*[t.cyl(r, zb_ - za, (x, y, (za + zb_) / 2), "z", 8) for x in xs]), "WALL", role, 0.0), za, zb_ - za))
    return t.join(*out)


def oval(t, r, at, sx, sy, depth, segs=16):
    return t.cyl(r, depth, at, "z", segs, (sx, sy, 1))


def mullions(t, x0, x1, y, z0, z1, pitch, w=0.08, d=0.1):
    n = max(int(round((x1 - x0) / pitch)), 1)
    step = (x1 - x0) / n
    bar = t.cube(0, w, y - d, y, z0, z1)
    return tag(t, t.array(bar, n + 1, (step, 0, 0), (x0 - w / 2, 0, 0)), "FRAME", "METAL", 0.0)


def glass_wall(t, x0, x1, z0, z1, pitch=2.0, y=0.0, transom=None):
    """Glazing plane with slim mullions (and optional transom rail height); the glass is stacked in rows under the
    1.2 m GLASS trim row so the sheet is never squashed."""
    n = max(1, int(math.ceil((z1 - z0) / 1.1)))
    rows = [tag(t, t.cube(x0, x1, y - 0.04, y, z0 + (z1 - z0) * k / n + (0.004 if k else 0), z0 + (z1 - z0) * (k + 1) / n),
                "GLASS", "NEUTRAL", 0.0) for k in range(n)]
    g = [t.join(*rows), mullions(t, x0, x1, y, z0, z1, pitch)]
    if transom:
        g.append(tag(t, t.cube(x0, x1, y - 0.1, y, transom - 0.04, transom + 0.04), "FRAME", "METAL", 0.0))
    return t.join(*g)


def slab(t, x0, x1, y0, y1, z0=0.0, z1=0.12, trim="PLINTH", role="GREY"):
    return box(t, x0, x1, y0, y1, z0, z1, "WALL", role, 0.0)


def checker(t, x0, y0, nx, ny, s, z, trim="PLINTH", role="WALL"):
    """Light/dark paving: dark tiles on every second cell of an nx x ny grid (2 m cells)."""
    tile = t.cube(0, s, 0, s, z, z + 0.01)
    row = t.array(tile, nx, (2 * s, 0, 0), (x0, y0, 0))
    r2 = t.array(row, ny, (0, 2 * s, 0), (0, 0, 0))
    r3 = t.move(t.array(row, ny, (0, 2 * s, 0), (0, 0, 0)), (s, s, 0))
    return tag(t, t.join(r2, r3), trim, role, 0.0)


def cone(t, r, h, at, segs=8):
    c = t.node("GeometryNodeMeshCone")
    t.set(c.inputs["Vertices"], segs)
    t.set(c.inputs["Radius Bottom"], r)
    t.set(c.inputs["Depth"], h)
    return t.move(S(t, c.outputs["Mesh"]), at)


def rail(t, x0, x1, y, z, h=1.1):
    posts = t.array(t.cube(0, 0.05, y - 0.05, y, z, z + h), max(int((x1 - x0) / 1.2), 2), (1.2, 0, 0), (x0, 0, 0))
    top = t.cube(x0, x1, y - 0.06, y, z + h - 0.05, z + h)
    return tag(t, t.join(posts, top), "METAL", "METAL", 0.0)


# --- pieces ---------------------------------------------------------------------------------------------------------
def porte_cochere(t, p):
    """Mall drive-through apron: 26 x 24 m pale paving, one lane + kerbside bay, kerbed landscaped island, kerb edge."""
    out = [slab(t, 0, 26, -24, 0, 0.0, 0.1, "PLINTH", "GREY")]
    ring = t.boolean(oval(t, 1.0, (13, -12, 0.12), 6.0, 3.0, 0.24, 14), [oval(t, 1.0, (13, -12, 0.12), 5.6, 2.6, 0.5, 14)])
    out.append(tag(t, ring, "CONCRETE", "ACCENT", 0.0))
    out.append(tag(t, oval(t, 1.0, (13, -12, 0.1), 5.6, 2.6, 0.18, 14), "PLINTH", "WALL", 0.0))   # planted island fill
    out.append(box(t, 0, 26, -24.3, -24.0, 0.0, 0.18, "CONCRETE", "ACCENT"))   # road-edge kerb
    bay = t.array(t.cube(0, 0.15, 0, 5.0, 0.1, 0.11), 3, (3.0, 0, 0), (2.0, -20, 0))   # kerbside bay lines
    out.append(tag(t, bay, "CONCRETE", "NEUTRAL", 0.0))
    return t.join(*out)


def atrium(t, p):
    """Glazed atrium entrance 20 x 12 m: a glass wall on a 2 m grid with transoms, a stone frame and a glyph disc."""
    out = [glass_wall(t, 1.0, 19.0, 0.0, 12.0, 2.0, 0.0, 6.0)]
    out.append(tag(t, t.join(t.cube(0.0, 1.0, -0.4, 0.2, 0.0, 12.4), t.cube(19.0, 20.0, -0.4, 0.2, 0.0, 12.4),
                             t.cube(0.0, 20.0, -0.4, 0.2, 12.0, 12.4)), "WALL", "WALL"))
    out.append(tag(t, t.cyl(1.0, 0.06, (10, -0.45, 10.4), "y", 6), "PANEL", "BOARD", 0.0))   # fictional glyph (Q8)
    out.append(tag(t, t.array(t.cube(0, 0.5, -0.08, 0, 0, 0.03), 4, (2.0, 0, 0), (7.5, 0, 0)), "METAL", "METAL", 0.0))
    return t.join(*out)


def fascia(t, p):
    """Dark fascia 24 x 7 m projecting over the apron, soffit at 5.5 m, on slim columns."""
    out = [box(t, 0, 24, -7.0, 0.0, 5.5, 5.6, "PANEL", "GREY"),
           box(t, 0, 24, -7.2, -6.9, 5.5, 6.9, "PANEL", "GREY"),
           box(t, 0, 24, -7.0, 0.0, 6.8, 6.9, "CONCRETE", "ACCENT"),
           cols(t, (2.0, 8.0, 16.0, 22.0), -6.3, 0.0, 5.5, 0.22)]
    return t.join(*out)


def shopfront_bay(t, p):
    """One 2.4 m podium bay: glass between slim pale mullions, 1.2 m dark fascia, cool-white 0.9 m letters."""
    out = [tag(t, t.cube(0.06, 2.34, -0.05, 0.0, 0.2, 3.3), "GLASS", "NEUTRAL", 0.0),
           box(t, 0.0, 0.08, -0.12, 0.0, 0.0, 3.3, "CONCRETE", "ACCENT"), box(t, 2.32, 2.4, -0.12, 0.0, 0.0, 3.3, "CONCRETE", "ACCENT"),
           box(t, 0.0, 2.4, -0.1, 0.0, 0.0, 0.2, "PLINTH", "GREY", 0.0),
           box(t, 0.0, 2.4, -0.2, 0.0, 3.3, 4.5, "PANEL", "GREY")]
    letters = t.array(t.cube(0, 0.18, -0.24, -0.2, 3.5, 4.4), 7, (0.27, 0.0, 0), (0.28, 0, 0))
    out.append(t.when(t.bnot(p.LOD), tag(t, letters, "PANEL", "BOARD", 0.0)))
    return t.join(*out)


def cladding(t, p):
    """Podium front 7.2 x 8 m: pale limestone-look panels 3.6 m wide with joints, dark fascia bands at the top and base."""
    out = [box(t, 0, 7.2, 0, 0.25, 1.0, 7.0, "WALL", "WALL"),
           box(t, 0, 7.2, -0.04, 0.25, 0.0, 1.0, "PANEL", "GREY"), box(t, 0, 7.2, -0.04, 0.25, 7.0, 8.0, "PANEL", "GREY")]
    joints = t.array(t.cube(0, 0.03, -0.015, 0.0, 1.0, 7.0), 3, (3.6, 0, 0), (-0.015, 0, 0))
    hjoints = t.array(t.cube(0, 7.2, -0.015, 0.0, 0, 0.03), 3, (0, 0, 2.0), (0, 0, 2.99))
    out.append(t.when(t.bnot(p.LOD), tag(t, t.join(joints, hjoints), "REVEAL", "ACCENT", 0.0)))
    return t.join(*out)


def led_screen(t, p):
    """Podium LED screen 12 x 6 m (2:1 sponsor slot): steel frame, glowing face on its own 0-1 UV, catwalk lip."""
    frame = t.boolean(t.cube(0, 12, -0.5, 0.0, 0, 6), [t.cube(0.2, 11.8, -0.6, -0.4, 0.2, 5.8)])
    face = t.store(tag(t, t.cube(0.2, 11.8, -0.45, -0.4, 0.2, 5.8), "PANEL", "BOARD", 0.0), "mat2", 1, "INT", "FACE")
    lip = t.cube(0, 12, -0.9, -0.5, 0, 0.12)
    return t.join(tag(t, t.join(frame, lip), "METAL", "METAL"), face)


def north_entrance(t, p):
    """North entrance: 12 m glazing, dark box canopy 12 x 4.5 m at 4.2 m, planting bed 3 m deep with shrub mounds."""
    out = [glass_wall(t, 0.0, 12.0, 0.0, 4.2, 2.0, 0.0, 2.6),
           box(t, -0.3, 12.3, -4.5, 0.0, 4.2, 5.2, "PANEL", "GREY"),
           cols(t, (0.4, 11.6), -4.1, 0.0, 4.2, 0.12, "METAL", "METAL"),
           box(t, -3.0, -0.3, -4.5, -1.5, 0.0, 0.4, "CONCRETE", "ACCENT"),
           tag(t, t.join(*[cone(t, 0.7, 0.9, (x, -3.0, 0.85), 8) for x in (-2.4, -1.6, -0.9)]), "SPALL", "WALL", 0.0)]
    return t.join(*out)


def parking_wing(t, p):
    """Open-deck car park, 6 levels at 3.0 m x 30 m wide: white slab edges, dark louvre infill, end columns, stepped ramp face."""
    out = []
    for i in range(6):
        z = i * 3.0
        out.append(box(t, 0, 30, -18, 0, z, z + 0.25, "CONCRETE", "ACCENT"))
        out.append(box(t, 0, 30, -18.2, -18.0, z + 0.25, z + 1.0, "WALL", "WALL"))   # white slab edge beam
        out.append(box(t, 0, 30, -17.8, -17.7, z + 1.0, z + 2.75, "LOUVRE", "NEUTRAL", 0.0))   # dark louvre infill
        slats = t.array(t.cube(0, 30, -18.0, -17.6, 0, 0.04), 3, (0, 0, 0.6), (0, 0, z + 1.2))
        out.append(tag(t, slats, "LOUVRE", "NEUTRAL", 0.0))
    out.append(cols(t, [x * 7.5 for x in range(5)], -17.0, 0.0, 18.0, 0.3))
    ramp = t.move(t.cube(0, 6.0, -0.15, 0.0, 0.0, 3.0), (30, -17.9, 0), (0, 0, 0))
    for i in range(6):   # the stepped diagonal ramp face: one tilted 3 m plate per level
        out.append(tag(t, t.move(t.cube(30.0, 33.0, -1.8, 1.8, -0.1, 0.1), (0, -9.0 if i % 2 == 0 else -9.0, i * 3.0 + 1.5), ((-1) ** i * 0.5, 0, 0)), "WALL", "WALL", 0.0))
    return t.join(*out)


def pool_deck(t, p):
    """Podium roof garden 30 x 18 m: deck, 12 x 5 m pool cut, glass balustrade, planters, loungers, play area."""
    deck = t.join(slab(t, 0, 30, -18, -11, 0, 0.3), slab(t, 0, 30, -6, 0, 0, 0.3), slab(t, 0, 4, -11, -6, 0, 0.3),
                  slab(t, 16, 30, -11, -6, 0, 0.3))
    water = box(t, 4, 16, -11, -6, 0.1, 0.2, "GLASS", "NEUTRAL", 0.0)
    bal = tag(t, t.cube(0, 30, -18.0, -17.95, 0.3, 1.4), "GLASS", "NEUTRAL", 0.0)
    posts = tag(t, t.array(t.cube(0, 0.06, -18.05, -17.95, 0.3, 1.4), 11, (3.0, 0, 0), (0, 0, 0)), "METAL", "METAL", 0.0)
    planters = t.join(box(t, 0.5, 3.5, -3.0, -0.5, 0.3, 0.8, "CONCRETE", "ACCENT"), box(t, 18, 28, -3.0, -0.5, 0.3, 0.8, "CONCRETE", "ACCENT"))
    hedge = tag(t, t.join(t.cube(18.2, 27.8, -2.8, -0.7, 0.8, 1.3), t.cube(0.7, 3.3, -2.8, -0.7, 0.8, 1.3)), "SPALL", "WALL", 0.0)
    lounger = t.array(t.cube(0, 0.7, 0, 1.9, 0.3, 0.55), 4, (1.3, 0, 0), (5.0, -4.7, 0))
    play = t.join(tag(t, t.cube(20, 28, -14, -8, 0.3, 0.34), "PANEL", "ACCENT", 0.0), tag(t, t.cube(23.6, 24.4, -11.4, -10.6, 0.34, 1.9), "METAL", "METAL", 0.0))
    return t.join(deck, water, bal, posts, planters, hedge, tag(t, lounger, "CANVAS", "CANVAS", 0.0), play)


def residents_porte_cochere(t, p):
    """Residents' side-street porte-cochere, 8 m wide, one drop-off lane: flat canopy on four columns over a paved lane."""
    out = [box(t, 0, 8, -9, 0, 3.9, 4.4, "CONCRETE", "ACCENT"), box(t, -0.1, 8.1, -9.1, -8.9, 3.9, 4.8, "WALL", "WALL"),
           cols(t, (0.5, 7.5), -8.3, 0.0, 3.9, 0.18), cols(t, (0.5, 7.5), -1.0, 0.0, 3.9, 0.18),
           slab(t, 0, 8, -14, 0, 0.0, 0.1), box(t, 0, 0.2, -14, 0, 0.0, 0.18, "CONCRETE", "ACCENT"),
           glass_wall(t, 1.0, 7.0, 0.0, 3.0, 2.0, 0.0)]
    return t.join(*out)


def office_stone_block(t, p):
    """Office tower base 24 x 16 m, 3 levels: champagne stone block, three recessed panels, white piers rising into the fins."""
    block = t.boolean(t.cube(0, 24, -0.8, 0.8, 0, 16), [t.cube(x, x + 5.0, -1.0, -0.4, 2.0, 14.0) for x in (2.5, 9.5, 16.5)])
    out = [tag(t, block, "WALL", "WALL"),
           *[tag(t, t.cube(x + 0.1, x + 4.9, -0.4, -0.38, 2.1, 13.9), "PANEL", "WALL", 0.0) for x in (2.5, 9.5, 16.5)],
           box(t, 0.0, 1.0, -1.1, -0.7, 0, 16, "CONCRETE", "ACCENT"), box(t, 23.0, 24.0, -1.1, -0.7, 0, 16, "CONCRETE", "ACCENT"),
           box(t, 7.2, 8.2, -1.1, -0.7, 0, 16, "CONCRETE", "ACCENT"), box(t, 15.2, 16.2, -1.1, -0.7, 0, 16, "CONCRETE", "ACCENT"),
           box(t, 0, 24, -1.0, 0.8, 15.7, 16.0, "CONCRETE", "ACCENT")]
    return t.join(*out)


def office_canopy(t, p):
    """Office entrance canopy 28 x 4.5 m at 5 m on 4 slim columns 7.5 m apart, with three glass door bays below."""
    out = [box(t, 0, 28, -4.5, 0.0, 5.0, 5.4, "CONCRETE", "ACCENT"), box(t, 0, 28, -4.6, -4.4, 5.4, 5.7, "WALL", "WALL"),
           cols(t, (2.5, 10.0, 17.5, 25.0), -4.0, 0.0, 5.0, 0.14, "METAL", "METAL")]
    for x in (2.5, 10.0, 17.5):   # three glass door bays in the base wall
        out.append(glass_wall(t, x + 0.5, x + 6.5, 0.0, 3.6, 3.0, 0.0, 2.4))
    return t.join(*out)


def office_apron(t, p):
    """Office forecourt apron 28 x 9 m: dark/light 2 m slab pattern, low planter wall with a 0.6 m clipped hedge."""
    out = [slab(t, 0, 28, -9, 0, 0.0, 0.1, "PLINTH", "WALL"), checker(t, 0.0, -9.0, 7, 2, 2.0, 0.1),
           box(t, 0, 28, -9.4, -9.0, 0.0, 0.5, "CONCRETE", "ACCENT"),
           tag(t, t.cube(0.1, 27.9, -9.3, -9.1, 0.5, 1.1), "SPALL", "WALL", 0.0)]
    return t.join(*out)


def hotel_pilotis(t, p):
    """Hotel podium 24 m wide, about 20 m, 4 levels: ground on slim columns (4.5 m clear), upper block in white concrete with a maroon louvre panel, grey panel and glazed bay."""
    out = [cols(t, [x * 4.0 + 1.0 for x in range(6)], -1.5, 0.0, 4.5, 0.25), box(t, 0, 24, -3.0, 0.5, 0, 0.15, "PLINTH", "GREY", 0.0),
           box(t, 0, 24, -3.0, 0.5, 4.5, 20.0, "WALL", "WALL")]
    out.append(tag(t, t.cube(2.0, 8.0, -3.05, -3.0, 6.5, 18.0), "LOUVRE", "ACCENT", 0.0))   # maroon louvre panel
    out.append(tag(t, t.array(t.cube(2.0, 8.0, -3.15, -3.05, 0, 0.1), 12, (0, 0, 1.0), (0, 0, 6.5)), "LOUVRE", "ACCENT", 0.0))
    out.append(tag(t, t.cube(10.0, 15.0, -3.05, -3.0, 6.5, 18.0), "PANEL", "GREY", 0.0))   # grey panel
    out.append(glass_wall(t, 17.0, 23.0, 6.5, 18.0, 2.0, -3.0, 12.0))   # glazed bay
    out += [box(t, 0, 24, -3.3, -2.9, 8.0 + 4.0 * i, 8.25 + 4.0 * i, "CONCRETE", "ACCENT") for i in range(3)]   # slab bands
    return t.join(*out)


def oval_island(t, p):
    """Hotel forecourt turning apron 25 x 25 m: oval island 14 x 8 m with a low green kerb wall and a pale fountain bowl."""
    ring = t.boolean(oval(t, 1.0, (12.5, -12.5, 0.2), 7.0, 4.0, 0.4, 16), [oval(t, 1.0, (12.5, -12.5, 0.2), 6.7, 3.7, 0.8, 16)])
    bowl = t.boolean(t.cyl(1.4, 0.7, (12.5, -12.5, 0.45), "z", 12), [t.cyl(1.2, 0.5, (12.5, -12.5, 0.65), "z", 12)])
    return t.join(slab(t, 0, 25, -25, 0, 0.0, 0.1), tag(t, ring, "PANEL", "TIMBER", 0.0),
                  tag(t, oval(t, 1.0, (12.5, -12.5, 0.1), 6.7, 3.7, 0.18, 16), "SPALL", "WALL", 0.0),
                  tag(t, bowl, "CONCRETE", "ACCENT", 0.0), tag(t, t.cyl(0.18, 1.2, (12.5, -12.5, 1.0), "z", 8), "CONCRETE", "ACCENT", 0.0))


def gatehouse(t, p):
    """Curved galvanised-roof shelter 5 x 3 m (guard post or shuttle stop): half-barrel roof on posts over a back wall and bench."""
    shell = t.boolean(t.cyl(2.7, 3.2, (2.5, -1.5, 2.4), "y", 12, (1, 1, 0.45)),
                      [t.cyl(2.6, 3.4, (2.5, -1.5, 2.4), "y", 12, (1, 1, 0.45)), t.cube(-1, 7, -4, 1, 0, 2.4)])
    out = [tag(t, shell, "SHEET", "NEUTRAL"), box(t, 0, 5, -0.3, 0, 0, 2.4, "WALL", "WALL"),
           cols(t, (0.1, 4.9), -2.9, 0.0, 2.4, 0.07, "METAL", "METAL"), slab(t, 0, 5, -3, 0, 0.0, 0.12),
           box(t, 0.4, 4.6, -0.9, -0.3, 0.12, 0.55, "PANEL", "TIMBER", 0.0)]
    return t.join(*out)


def tensile_terrace(t, p):
    """Event terrace 18 x 10 m on the hotel podium: pale deck, parapet, four masts holding two white tensile peaks, roof planters."""
    out = [slab(t, 0, 18, -10, 0, 0.0, 0.3), rail(t, 0, 18, -10.0, 0.3, 1.1),
           tag(t, t.join(*[t.cyl(0.08, 6.5, (x, -5.0, 3.55), "z", 6) for x in (4.0, 14.0)]), "METAL", "METAL", 0.0),
           tag(t, t.join(cone(t, 5.0, 2.5, (4.0, -5.0, 5.8), 8), cone(t, 5.0, 2.5, (14.0, -5.0, 5.8), 8)), "CANVAS", "CANVAS", 0.0),
           box(t, 0.3, 17.7, -0.9, -0.3, 0.3, 0.8, "CONCRETE", "ACCENT"),
           tag(t, t.cube(0.4, 17.6, -0.85, -0.35, 0.8, 1.2), "SPALL", "WALL", 0.0)]
    return t.join(*out)


def itc_podium(t, p):
    """Curve towers shared podium 38 x 28 m, 4 storeys of 4.5 m: stepped ground storey, stone piers, glass bands, palms side left to vegetation."""
    out = [box(t, 0, 38, -1.0, 0.0, 0.0, 18.0, "WALL", "WALL")]
    out.append(box(t, 0, 38, -6.0, -1.0, 0.0, 4.5, "WALL", "WALL"))   # stepped ground storey
    out.append(glass_wall(t, 2.0, 36.0, 0.3, 4.2, 3.0, -6.0, 2.5))
    for i in range(1, 4):
        z = 4.5 * i + 0.3
        out.append(glass_wall(t, 1.0, 37.0, z, z + 3.6, 3.0, -1.0, None))
        out.append(box(t, 0, 38, -1.4, -0.9, 4.5 * i - 0.15, 4.5 * i + 0.3, "CONCRETE", "ACCENT"))
    out.append(tag(t, t.array(t.cube(0, 0.8, -1.3, -0.9, 4.5, 18.0), 6, (7.4, 0, 0), (0.0, 0, 0)), "WALL", "WALL"))
    out.append(box(t, -0.2, 38.2, -1.5, 0.0, 17.8, 18.4, "CONCRETE", "ACCENT"))
    return t.join(*out)


def ramp_mouth(t, p):
    """Basement ramp mouth 6.5 m wide: opening cut into a 4 m wall with a sloped ramp, boom arm, height bar and sign board."""
    wall = tag(t, t.boolean(t.cube(-2, 8.5, 0, 1.0, 0, 4.0), [t.cube(0, 6.5, -0.1, 1.1, 0.0, 3.0)]), "WALL", "WALL")
    ramp = t.join(*[t.move(t.cube(0, 6.5, -3.2, 0.0, -0.1, 0.0), (0, -3.2 * k + 0.5, 0.8 - 0.29 * k), (0.09, 0, 0)) for k in range(3)])
    out = [wall, tag(t, ramp, "WALL", "GREY", 0.0),
           tag(t, t.cube(-0.2, 6.7, -0.3, 0.0, 2.7, 3.0), "CONCRETE", "ACCENT", 0.0),
           tag(t, t.join(t.cube(0, 0.1, -3.2, -3.1, 0.0, 2.6), t.cube(6.4, 6.5, -3.2, -3.1, 0.0, 2.6), t.cube(0, 6.5, -3.2, -3.1, 2.5, 2.6)), "METAL", "METAL", 0.0),
           tag(t, t.cube(1.0, 5.5, -0.35, -0.3, 3.1, 3.8), "PANEL", "BOARD", 0.0),
           tag(t, t.cube(-0.1, 0.4, -3.0, -2.6, 0.0, 1.0), "METAL", "GREY", 0.0)]
    arm = tag(t, t.cube(0.4, 5.4, -3.0, -2.94, 1.0, 1.1), "CANVAS", "CANVAS", 0.0)
    return t.join(*out, arm)


def boom_kiosk(t, p):
    """Guard kiosk 2 x 2.4 m with an overhanging roof, glazed front, and a 5 m banded boom arm on its post."""
    out = [box(t, 0, 2.4, 0, 2.0, 0, 2.5, "WALL", "WALL"), box(t, -0.2, 2.6, -0.2, 2.2, 2.5, 2.65, "CONCRETE", "ACCENT"),
           tag(t, t.cube(0.2, 2.2, -0.03, 0.0, 0.9, 2.2), "GLASS", "NEUTRAL", 0.0),
           box(t, 3.2, 3.5, -0.2, 0.1, 0.0, 1.0, "METAL", "METAL")]
    arm = t.array(t.cube(0, 0.5, -0.04, 0.04, 1.0, 1.1), 10, (0.5, 0, 0), (3.5, 0, 0))
    odd = t.array(t.cube(0, 0.5, -0.04, 0.04, 1.0, 1.1), 5, (1.0, 0, 0), (4.0, 0, 0))
    out += [tag(t, arm, "WALL", "WALL", 0.0), tag(t, odd, "CANVAS", "CANVAS", 0.0)]
    return t.join(*out)


def bollard(t, p):
    """Dark entrance bollard 0.8 m: round shaft, domed cap, reflective band, foot ring."""
    out = [tag(t, t.cyl(0.075, 0.8, (0, 0, 0.4), "z", t.switch(p.LOD, 12, 6, "INT")), "METAL", "GREY", 0.0),
           tag(t, t.cyl(0.095, 0.05, (0, 0, 0.82), "z", 8), "METAL", "METAL", 0.0),
           tag(t, t.cyl(0.082, 0.07, (0, 0, 0.6), "z", 8), "CANVAS", "CANVAS", 0.0),
           tag(t, t.cyl(0.11, 0.04, (0, 0, 0.02), "z", 8), "CONCRETE", "ACCENT", 0.0)]
    return t.join(*out)


def name_board(t, p):
    """Tower crown name board 11 x 3 m: steel frame and rear stiffeners, glowing face (fictional name or glyph, Q8)."""
    frame = t.boolean(t.cube(0, 11, -0.5, 0.0, 0, 3), [t.cube(0.2, 10.8, -0.6, -0.4, 0.2, 2.8)])
    face = t.store(tag(t, t.cube(0.2, 10.8, -0.45, -0.4, 0.2, 2.8), "PANEL", "BOARD", 0.0), "mat2", 1, "INT", "FACE")
    ribs = tag(t, t.array(t.cube(0, 0.1, 0.0, 0.4, 0.2, 2.8), 4, (3.6, 0, 0), (0.1, 0, 0)), "METAL", "GREY", 0.0)
    return t.join(tag(t, frame, "METAL", "METAL"), face, ribs)


def planter_bed(t, p):
    """Podium planter bed 3 x 1.5 m: kerbed concrete bed, clipped hedge, shrub mounds (palms and frangipani come from vegetation)."""
    bed = t.join(box(t, 0, 3, -1.5, -1.35, 0, 0.5), box(t, 0, 3, -0.15, 0, 0, 0.5), box(t, 0, 0.15, -1.35, -0.15, 0, 0.5),
                 box(t, 2.85, 3, -1.35, -0.15, 0, 0.5), box(t, 0.15, 2.85, -1.35, -0.15, 0, 0.2))
    return t.join(bed, tag(t, t.cube(0.15, 2.85, -1.35, -0.8, 0.2, 0.4), "SPALL", "WALL", 0.0),
                  tag(t, t.cube(0.3, 2.7, -0.55, -0.15, 0.4, 0.95), "SPALL", "WALL", 0.0),
                  tag(t, t.join(*[cone(t, 0.3, 0.6, (x, -1.0, 0.7), 8) for x in (0.7, 1.5, 2.3)]), "SPALL", "WALL", 0.0))


def wayfinding(t, p):
    """Wayfinding set: tenant board on two posts (1.8 x 0.6 m), a 0.5 x 1.5 m blade sign on a bracket, and a parking P sign."""
    board = [tag(t, t.cube(0, 1.8, -0.06, 0.0, 1.9, 2.5), "PANEL", "BOARD", 0.0),
             tag(t, t.join(t.cube(0.1, 0.16, -0.06, 0.0, 0.0, 1.9), t.cube(1.64, 1.7, -0.06, 0.0, 0.0, 1.9)), "METAL", "METAL", 0.0)]
    blade = [tag(t, t.cube(2.4, 2.9, -0.04, 0.0, 1.0, 2.5), "PANEL", "BOARD", 0.0),
             tag(t, t.join(t.cube(2.4, 3.0, -0.05, 0.0, 2.5, 2.56), t.cube(2.4, 2.46, -0.05, 0.0, 0.0, 1.0)), "METAL", "GREY", 0.0)]
    park = [tag(t, t.cube(3.6, 4.2, -0.04, 0.0, 1.8, 2.4), "PANEL", "BOARD", 0.0),
            tag(t, t.cube(3.87, 3.93, -0.05, 0.0, 0.0, 1.8), "METAL", "GREY", 0.0)]
    return t.join(*board, *blade, *park)


def E(row, name, body, h=4.0, v="A", **kw):
    return dict(row=row, name=f"KIT_TWB_{name}", body=body, h=h, variant=v, refs=REFS, **kw)


def catalogue():
    return [
        E("TWB_GreenCourt_DriveThroughPorteCochere", "GreenCourt_PorteCochere_A", porte_cochere),
        E("TWB_GreenCourt_AtriumGlazing", "GreenCourt_AtriumGlazing_A", atrium, h=4.0),
        E("TWB_GreenCourt_FasciaOverhang", "GreenCourt_FasciaOverhang_A", fascia),
        E("TWB_GreenCourt_ShopfrontBays", "GreenCourt_ShopfrontBay_A", shopfront_bay),
        E("TWB_GreenCourt_Cladding", "GreenCourt_Cladding_A", cladding),
        E("TWB_GreenCourt_LEDScreen", "GreenCourt_LEDScreen_A", led_screen, mat2="MAT_SignGlow_A"),
        E("TWB_GreenCourt_NorthEntrance", "GreenCourt_NorthEntrance_A", north_entrance),
        E("TWB_ParkingWing_OpenDecks", "ParkingWing_OpenDecks_A", parking_wing, h=3.0),
        E("TWB_PodiumRoof_PoolDeck", "PodiumRoof_PoolDeck_A", pool_deck),
        E("TWB_Residences_SideStreetPorteCochere", "Residences_PorteCochere_A", residents_porte_cochere),
        E("TWB_OfficeBase_StoneBlock", "OfficeBase_StoneBlock_A", office_stone_block),
        E("TWB_OfficeCanopy", "OfficeCanopy_A", office_canopy),
        E("TWB_OfficeForecourt_Apron", "OfficeForecourt_Apron_A", office_apron),
        E("TWB_HotelPodium_Pilotis", "HotelPodium_Pilotis_A", hotel_pilotis, h=4.5),
        E("TWB_HotelForecourt_OvalIsland", "HotelForecourt_OvalIsland_A", oval_island),
        E("TWB_HotelGatehouse", "HotelGatehouse_A", gatehouse),
        E("TWB_HotelPodium_TensileTerrace", "HotelPodium_TensileTerrace_A", tensile_terrace),
        E("TWB_ITC_SharedPodium", "ITC_SharedPodium_A", itc_podium, h=4.5),
        E("TWB_BasementRampMouth", "BasementRampMouth_A", ramp_mouth),
        E("TWB_BoomBarrierKiosk", "BoomBarrierKiosk_A", boom_kiosk),
        E("TWB_Bollards_Entrance", "Bollard_A", bollard, h=0.8),
        E("TWB_NameBoard_Crown", "NameBoard_Crown_A", name_board, mat2="MAT_SignGlow_A"),
        E("TWB_PlanterBeds_Palms", "PlanterBed_A", planter_bed, h=1.0),
        E("TWB_Wayfinding_Tenant", "Wayfinding_A", wayfinding),
    ]
