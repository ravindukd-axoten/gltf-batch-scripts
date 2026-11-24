"""Street-furniture generators (P147): sign kit (SG), ground and furniture kit (SF), road-marking modules (MK).

Same pattern as elements.py / towerbase.py: `catalogue(set)` returns entries for genbuild.build, each tagged with the
inventory row NAME (looked up by row id in docs/inventory/row_manifest.csv, so the spelling is never typed twice).
Frame: x along the piece, sign faces and facades toward -y, z up, ground pieces lie on z = 0 with the road run along +x.
Numbers come from the row descriptions and the Art Bible street-prop budget (100-1,500 tris); proportions follow Sri
Lankan road practice (blue-ground plates, red-ringed regulatory discs) and are +-20 %: no photo measured.
Sign faces carry shape and flat colour only (vertex colour per role via the entry's `paint`); numerals, glyphs and
trilingual text come from the T_Signage_A atlas later, and text is for people to decide (AGENTS.md).
"""
from __future__ import annotations

import csv
import math
import os

from parts import tag
from gnlib import S
from classes import _st
from towerbase import box, cols, cone

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "..", "..", "..", "docs", "inventory", "row_manifest.csv")
_NAMES: dict = {}
PI = math.pi

RED, WHITE, BLACK, BLUE, BROWN = "#C8282E", "#F4F4F0", "#1E1E24", "#1E4E9C", "#6B4226"
YELLOW, GREEN, STEEL, CONC = "#F2C230", "#1E6B3A", "#8C918F", "#A8A59C"


def row_name(rid):
    if not _NAMES:
        with open(MANIFEST, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                _NAMES[r["row_id"]] = r["name"]
    return _NAMES[rid]


def E(rid, name, body, pre, h=2.5, paint=None, refs=None, **kw):
    return dict(row=row_name(rid), name=f"KIT_{pre}_{name}", body=body, h=h, variant="A", refs=refs or [], paint=paint or {}, **kw)


# ---- helpers -------------------------------------------------------------------------------------------------
def post(t, x, z0, z1, y=0.05, r=0.035, segs=8, role="METAL"):
    return tag(t, t.cyl(r, z1 - z0, (x, y, (z0 + z1) / 2), "z", segs), "METAL", role, 0.0)


def rect(t, x0, x1, z0, z1, y0=-0.03, y1=0.0, role="BOARD", trim="PANEL"):
    return tag(t, t.cube(x0, x1, y0, y1, z0, z1), trim, role, 0.0)


def disc(t, r, cx, cz, y0, y1, role, segs=20, rot=0.0, trim="PANEL"):
    c = t.move(t.cyl(r, y1 - y0, (0, 0, 0), "y", segs), (cx, (y0 + y1) / 2, cz), (0, rot, 0))
    return tag(t, c, trim, role, 0.0)


def tri(t, r, cx, cz, y0, y1, role, up=True):
    return disc(t, r, cx, cz, y0, y1, role, 3, -PI / 2 if up else PI / 2)


def bary(t, cx, cz, L, w, ang, role, y0=-0.04, y1=-0.03):
    """Bar on a sign face (xz plane), `ang` counter-clockwise as the viewer sees it."""
    c = t.move(t.cube(-L / 2, L / 2, y0, y1, -w / 2, w / 2), (cx, 0, cz), (0, -ang, 0))
    return tag(t, c, "PANEL", role, 0.0)


def barz(t, cx, cy, L, w, ang, z1=0.012, z0=0.0, role="NEUTRAL"):
    """Flat bar on the ground (xy plane) rotated about z."""
    c = t.move(t.cube(-L / 2, L / 2, -w / 2, w / 2, z0, z1), (cx, cy, 0), (0, 0, ang))
    return tag(t, c, "WALL", role, 0.0)


def trz(t, r, cx, cy, ang, z1=0.012, role="NEUTRAL"):
    c = t.move(t.cyl(r, z1, (0, 0, z1 / 2), "z", 3), (cx, cy, 0), (0, 0, ang))
    return tag(t, c, "WALL", role, 0.0)


def lens(t, cx, cz, r, role, y0=-0.12, y1=-0.06):
    return disc(t, r, cx, cz, y0, y1, role, 12, 0.0, "GLASS")


def face(t, x0, x1, y0, y1, z0, z1, role="BOARD"):
    """Big sign face: box() promotes it to the 4 m wall row in strips, so the sheet is never squashed."""
    return box(t, x0, x1, y0, y1, z0, z1, "PANEL", role, 0.0)


def glow(t, geo):
    return t.store(geo, "mat2", 1, "INT", "FACE")


def J(t, *g):
    return t.join(*g)


# ---- signs (SG) -----------------------------------------------------------------------------------------------
# Footway clearance (P153, critic fix 3): plate bottoms at least 2.1 m over the footway so a 1.8 m person walks under
# with 0.3 m to spare (gate: tests/test_street_scale_gate.py on the built glbs). Plate centre 2.5 m, post to 2.95 m.
SIGN_CENTRE, SIGN_POST = 2.5, 2.95


def pole_sign(face_fn, centre=SIGN_CENTRE, post_z=SIGN_POST):
    def body(t, p):
        return J(t, post(t, 0, 0, post_z), face_fn(t, 0.0, centre))
    return body


def f_no_entry(t, cx, cz):
    return J(t, disc(t, 0.3, cx, cz, -0.03, 0.0, "ACCENT"), bary(t, cx, cz, 0.44, 0.1, 0, "NEUTRAL"))


def f_speed(t, cx, cz):
    return J(t, disc(t, 0.3, cx, cz, -0.03, 0.0, "ACCENT"), disc(t, 0.23, cx, cz, -0.04, -0.03, "NEUTRAL"),
             rect(t, cx - 0.13, cx + 0.13, cz - 0.09, cz + 0.09, -0.05, -0.04, "GREY"))


def f_no_stop(t, cx, cz, cross=True):
    g = [disc(t, 0.3, cx, cz, -0.03, 0.0, "ACCENT"), disc(t, 0.24, cx, cz, -0.04, -0.03, "NEUTRAL")]
    g.append(bary(t, cx, cz, 0.44, 0.07, PI / 4, "ACCENT", -0.05, -0.04))
    if cross:
        g.append(bary(t, cx, cz, 0.44, 0.07, -PI / 4, "ACCENT", -0.05, -0.04))
    return J(t, *g)


def f_arrow(t, cx, cz, ang, role="GREY", L=0.36, y0=-0.05, y1=-0.04):
    dx, dz = math.cos(ang), math.sin(ang)
    stem = bary(t, cx - dx * 0.04, cz - dz * 0.04, L, 0.07, ang, role, y0, y1)
    head = disc(t, 0.1, cx + dx * L / 2, cz + dz * L / 2, y0, y1, role, 3, -ang)
    return J(t, stem, head)


def f_no_turn(t, cx, cz):
    return J(t, disc(t, 0.3, cx, cz, -0.03, 0.0, "ACCENT"), disc(t, 0.23, cx, cz, -0.04, -0.03, "NEUTRAL"),
             f_arrow(t, cx - 0.02, cz, 0.0), bary(t, cx, cz, 0.5, 0.06, -PI / 4, "ACCENT", -0.06, -0.05))


def f_uturn(t, cx, cz):
    return J(t, disc(t, 0.3, cx, cz, -0.03, 0.0, "ACCENT"), disc(t, 0.23, cx, cz, -0.04, -0.03, "NEUTRAL"),
             bary(t, cx - 0.07, cz - 0.02, 0.07, 0.24, 0, "GREY"), bary(t, cx + 0.07, cz + 0.08, 0.07, 0.2, 0, "GREY"),
             bary(t, cx, cz + 0.14, 0.21, 0.07, 0, "GREY"), tri(t, 0.08, cx + 0.07, cz - 0.1, -0.05, -0.04, "GREY", False),
             bary(t, cx, cz, 0.5, 0.06, -PI / 4, "ACCENT", -0.06, -0.05))


def f_keep_left(t, cx, cz):
    return J(t, disc(t, 0.3, cx, cz, -0.03, 0.0, "ACCENT"), f_arrow(t, cx + 0.12, cz + 0.12, PI * 1.25, "NEUTRAL", 0.38))


def f_one_way(t, cx, cz):
    return J(t, rect(t, cx - 0.5, cx + 0.5, cz - 0.17, cz + 0.17, -0.03, 0.0, "ACCENT"),
             f_arrow(t, cx - 0.1, cz, 0.0, "NEUTRAL", 0.7))


def f_giveway(t, cx, cz):
    return J(t, tri(t, 0.47, cx, cz + 0.08, -0.03, 0.0, "ACCENT", False), tri(t, 0.33, cx, cz + 0.08, -0.04, -0.03, "NEUTRAL", False))


def f_warn(t, cx, cz, inner):
    return J(t, tri(t, 0.5, cx, cz - 0.04, -0.03, 0.0, "ACCENT"), tri(t, 0.35, cx, cz - 0.04, -0.04, -0.03, "NEUTRAL"), *inner(t, cx, cz))


def i_ped(t, cx, cz, dx=0.0, s=1.0):
    return [disc(t, 0.04 * s, cx + dx, cz + 0.13 * s, -0.06, -0.04, "GREY", 8), bary(t, cx + dx, cz, 0.04 * s, 0.2 * s, 0, "GREY", -0.06, -0.04)]


def i_two(t, cx, cz):
    return i_ped(t, cx, cz, -0.07, 0.8) + i_ped(t, cx, cz, 0.07, 0.8)


def i_slow(t, cx, cz):
    return [bary(t, cx, cz - 0.02, 0.3, 0.07, 0, "GREY", -0.06, -0.04), bary(t, cx, cz + 0.1, 0.18, 0.06, 0, "GREY", -0.06, -0.04)]


def f_roundabout_ahead(t, cx, cz):
    arcs = [disc(t, 0.05, cx + 0.12 * math.cos(a), cz - 0.04 + 0.12 * math.sin(a), -0.06, -0.04, "GREY", 8) for a in (0.5, 2.1, 3.7)]
    return J(t, tri(t, 0.5, cx, cz - 0.04, -0.03, 0.0, "ACCENT"), tri(t, 0.35, cx, cz - 0.04, -0.04, -0.03, "NEUTRAL"), *arcs)


def f_mandatory_round(t, cx, cz):
    arcs = [f_arrow(t, cx + 0.14 * math.cos(a), cz + 0.14 * math.sin(a), a + PI / 2, "NEUTRAL", 0.12) for a in (0.4, 2.5, 4.6)]
    return J(t, disc(t, 0.3, cx, cz, -0.03, 0.0, "ACCENT"), *arcs)


def f_height(t, cx, cz):
    return J(t, disc(t, 0.3, cx, cz, -0.03, 0.0, "ACCENT"), disc(t, 0.23, cx, cz, -0.04, -0.03, "NEUTRAL"),
             bary(t, cx, cz, 0.3, 0.05, 0, "GREY", -0.06, -0.04), tri(t, 0.07, cx, cz + 0.1, -0.06, -0.04, "GREY"),
             tri(t, 0.07, cx, cz - 0.1, -0.06, -0.04, "GREY", False))


def f_tourist(t, cx, cz):
    return J(t, rect(t, cx - 0.47, cx + 0.47, cz - 0.32, cz + 0.32, -0.03, 0.0, "NEUTRAL"),
             rect(t, cx - 0.43, cx + 0.43, cz - 0.28, cz + 0.28, -0.04, -0.03, "ACCENT"),
             rect(t, cx - 0.25, cx + 0.25, cz - 0.05, cz + 0.05, -0.05, -0.04, "NEUTRAL"))


def f_cctv(t, cx, cz):
    return J(t, rect(t, cx - 0.25, cx + 0.25, cz - 0.17, cz + 0.17, -0.03, 0.0, "ACCENT"),
             rect(t, cx - 0.2, cx + 0.2, cz - 0.12, cz + 0.12, -0.04, -0.03, "NEUTRAL"),
             rect(t, cx - 0.12, cx + 0.06, cz - 0.04, cz + 0.06, -0.06, -0.04, "GREY"),
             disc(t, 0.035, cx + 0.1, cz + 0.01, -0.06, -0.04, "GREY", 8))


def f_name_plate(t, cx, cz):
    return J(t, rect(t, cx - 0.45, cx + 0.45, cz - 0.14, cz + 0.14, -0.03, 0.0, "NEUTRAL"),
             rect(t, cx - 0.43, cx + 0.43, cz - 0.12, cz + 0.12, -0.04, -0.03, "ACCENT"),
             *[rect(t, cx - 0.38, cx + 0.38, cz + dz - 0.012, cz + dz + 0.012, -0.05, -0.04, "NEUTRAL") for dz in (-0.07, 0.0, 0.07)])


def f_bus_stop(t, cx, cz):
    return J(t, disc(t, 0.2, cx, cz, -0.03, 0.0, "ACCENT"), disc(t, 0.14, cx, cz, -0.04, -0.03, "GREY"),
             rect(t, cx - 0.2, cx + 0.2, cz - 0.42, cz - 0.24, -0.03, 0.0, "NEUTRAL"))


def plate_inset(t, cx, cz, w, h, outer, inner, rim=0.04):
    return J(t, rect(t, cx - w / 2, cx + w / 2, cz - h / 2, cz + h / 2, -0.03, 0.0, outer),
             rect(t, cx - w / 2 + rim, cx + w / 2 - rim, cz - h / 2 + rim, cz + h / 2 - rim, -0.04, -0.03, inner))


def board2(face, w, h, leg=0.9, top=2.3):
    """Board on two posts."""
    def body(t, p):
        return J(t, post(t, 0.1, 0, top), post(t, w - 0.1, 0, top), face(t, w, h, top))
    return body


def f_police(t, w, h, top):
    cx, cz = w / 2, top - h / 2
    return J(t, plate_inset(t, cx, cz, w, h, "ACCENT", "NEUTRAL", 0.05), rect(t, 0.1, w - 0.1, cz + h / 2 - 0.3, cz + h / 2 - 0.08, -0.05, -0.04, "ACCENT"),
             *[rect(t, 0.15, w - 0.15, cz - 0.05 - 0.14 * k, cz - 0.01 - 0.14 * k, -0.05, -0.04, "GREY") for k in range(3)])


def f_bathing(t, w, h, top):
    cx, cz = w / 2, top - h / 2
    bands = [("ACCENT", 0), ("TIMBER", 1), ("BOARD", 2)]
    g = [rect(t, 0, w, top - h, top, -0.03, 0.0, "NEUTRAL")]
    for role, k in bands:
        z0 = top - 0.06 - (k + 1) * (h - 0.12) / 3
        g.append(rect(t, 0.06, w * 0.35, z0 + 0.04, z0 + (h - 0.12) / 3 - 0.04, -0.04, -0.03, role))
        g.append(rect(t, w * 0.42, w - 0.08, z0 + 0.1, z0 + (h - 0.12) / 3 - 0.1, -0.04, -0.03, "GREY"))
    return J(t, *g)


def hanging_round(t, p):
    arm = tag(t, t.cube(0, 0.9, 0.0, 0.05, 0.9, 0.94), "METAL", "METAL", 0.0)
    chain = tag(t, t.join(t.cube(0.4, 0.42, 0.0, 0.02, 0.6, 0.9), t.cube(0.74, 0.76, 0.0, 0.02, 0.6, 0.9)), "METAL", "METAL", 0.0)
    return J(t, arm, chain, post(t, 0.02, 0.0, 1.0, 0.03, 0.03), disc(t, 0.3, 0.58, 0.3, -0.03, 0.05, "ACCENT", 20),
             disc(t, 0.25, 0.58, 0.3, -0.05, -0.03, "NEUTRAL", 20))


def lightbox(t, p):
    shell = box(t, 0, 1.6, -0.22, 0.0, 0, 0.7, "PANEL", "GREY")
    face = glow(t, tag(t, t.cube(0.05, 1.55, -0.24, -0.22, 0.05, 0.65), "PANEL", "BOARD", 0.0))
    return J(t, shell, face, tag(t, t.cube(0.2, 0.3, 0.0, 0.1, 0.1, 0.6), "METAL", "METAL", 0.0))


def signboard_frame(w, h):
    def body(t, p):
        d = 0.08
        fr = [tag(t, t.cube(0, w, -d, 0, 0, 0.06), "FRAME", "GREY", 0.5), tag(t, t.cube(0, w, -d, 0, h - 0.06, h), "FRAME", "GREY", 0.5),
              tag(t, t.cube(0, 0.06, -d, 0, 0.06, h - 0.06), "FRAME", "GREY", 0.5), tag(t, t.cube(w - 0.06, w, -d, 0, 0.06, h - 0.06), "FRAME", "GREY", 0.5)]
        fc = face(t, 0.06, w - 0.06, -0.05, -0.04, 0.06, h - 0.06)
        br = [tag(t, t.cube(x, x + 0.05, 0, 0.3, 0.02, 0.07), "METAL", "METAL", 0.0) for x in (0.1, w - 0.15)]
        return J(t, *fr, fc, *br)
    return body


def flex_billboard(w, h, legs_h):
    def body(t, p):
        g = [box(t, 0.3, 0.45, 0.0, 0.15, 0, legs_h + h, "METAL", "METAL", 0.0), box(t, w - 0.45, w - 0.3, 0.0, 0.15, 0, legs_h + h, "METAL", "METAL", 0.0),
             tag(t, t.cube(0.3, w - 0.3, 0.0, 0.1, legs_h - 0.1, legs_h), "METAL", "METAL", 0.0),
             tag(t, t.cube(0.3, w - 0.3, 0.0, 0.1, legs_h + h, legs_h + h + 0.1), "METAL", "METAL", 0.0),
             face(t, 0.45, w - 0.45, -0.06, -0.02, legs_h, legs_h + h),
             tag(t, t.cube(0.3, w - 0.3, -0.5, 0.0, legs_h - 0.12, legs_h - 0.08), "METAL", "GREY", 0.0),
             tag(t, t.cube(0.3, w - 0.3, -0.5, -0.46, legs_h - 0.08, legs_h + 0.9), "METAL", "GREY", 0.0)]
        n = 3 if w > 6 else 2
        for k in range(n):
            x = w * (k + 0.5) / n
            g += [tag(t, t.cube(x - 0.1, x + 0.1, -0.5, -0.2, legs_h + h + 0.1, legs_h + h + 0.25), "METAL", "GREY", 0.0)]
        return J(t, *g)
    return body


def unipole(t, p):
    col = cols(t, [6], 0.0, 0, 9.0, 0.3, "METAL", "METAL")
    boards = [face(t, 0, 12, y0, y1, 9.0, 12.0) for y0, y1 in ((-0.45, -0.4), (0.4, 0.45))]
    body = tag(t, t.cube(0, 12, -0.4, 0.4, 8.9, 9.0), "METAL", "GREY", 0.0)
    walk = tag(t, t.cube(0, 12, -1.0, -0.45, 8.8, 8.85), "METAL", "GREY", 0.0)
    rail_ = tag(t, t.cube(0, 12, -1.0, -0.98, 8.85, 9.8), "METAL", "GREY", 0.0)
    return J(t, col, *boards, body, walk, rail_, tag(t, t.cyl(0.55, 0.4, (6, 0, 0.2), "z", 10), "CONCRETE", "ACCENT", 0.0))


def hoarding(t, p):
    ridges = tag(t, t.array(t.cube(0, 0.12, -0.05, 0.0, 0, 2.4), 33, (0.125, 0, 0), (0, 0, 0)), "METAL", "GREY", 0.0)
    posts = tag(t, t.array(t.cube(0, 0.08, 0.0, 0.1, 0, 2.5), 3, (2.0, 0, 0), (0, 0, 0)), "METAL", "METAL", 0.0)
    rail_ = tag(t, t.cube(0, 4.1, -0.07, 0.1, 2.4, 2.5), "METAL", "METAL", 0.0)
    panels = [face(t, 0.2 + 2.0 * k, 1.8 + 2.0 * k, -0.08, -0.06, 0.4, 2.2) for k in range(2)]
    return J(t, ridges, posts, rail_, *panels)


def poster_box(t, p):
    fr = box(t, 0, 1.2, -0.12, 0.0, 0, 1.8, "PANEL", "METAL")
    return J(t, fr, glow(t, tag(t, t.cube(0.08, 1.12, -0.14, -0.12, 0.08, 1.72), "PANEL", "BOARD", 0.0)),
             tag(t, t.cube(0.0, 1.2, 0.0, 0.12, 0, 0.1), "METAL", "GREY", 0.0))


def ad_slot(w, h, z0):
    def body(t, p):
        fr = tag(t, t.boolean(t.cube(0, w, -0.4, 0, z0, z0 + h), [t.cube(0.15, w - 0.15, -0.5, -0.3, z0 + 0.15, z0 + h - 0.15)]), "METAL", "METAL")
        fc = face(t, 0.15, w - 0.15, -0.33, -0.3, z0 + 0.15, z0 + h - 0.15)
        ribs = tag(t, t.array(t.cube(0, 0.1, 0.0, 0.3, z0 + 0.15, z0 + h - 0.15), 4, ((w - 0.1) / 3, 0, 0)), "METAL", "GREY", 0.0)
        return J(t, fr, fc, ribs)
    return body


def ad_face(w, h):
    def body(t, p):
        return J(t, rect(t, 0, w, 0, h, -0.06, -0.02, "METAL", "FRAME"), face(t, 0.05, w - 0.05, -0.08, -0.06, 0.05, h - 0.05))
    return body


def led_screen(t, p):
    fr = box(t, 0, 6.2, -0.35, 0.0, 2.4, 6.0, "PANEL", "GREY")
    fc = glow(t, tag(t, t.cube(0.1, 6.1, -0.37, -0.35, 2.5, 5.9), "PANEL", "BOARD", 0.0))
    legs = J(t, box(t, 0.4, 0.55, 0.0, 0.3, 0, 2.4, "METAL", "METAL", 0.0), box(t, 5.6, 5.75, 0.0, 0.3, 0, 2.4, "METAL", "METAL", 0.0))
    return J(t, fr, fc, legs)


def lamp_banner_pair(t, p):
    pol = post(t, 0, 0, 7.0, 0.0, 0.07, 10)
    arms = [tag(t, t.cube(0, 0.5, -0.02, 0.02, 5.5 + dz, 5.55 + dz), "METAL", "METAL", 0.0) for dz in (0, 0.9)]
    bn = [rect(t, 0.12 + 0.5 * k, 0.52 + 0.5 * k, 3.7, 5.5, -0.05, -0.02, "ACCENT") for k in (0,)] + [rect(t, -0.52, -0.12, 3.7, 5.5, -0.05, -0.02, "ACCENT")]
    return J(t, pol, *arms, *bn)


def ad_flag(t, p):
    base = tag(t, t.cyl(0.25, 0.04, (0, 0, 0.02), "z", 10), "CONCRETE", "GREY", 0.0)
    return J(t, base, post(t, 0, 0.0, 2.6, 0.0, 0.025, 8), rect(t, 0.02, 0.82, 0.5, 2.5, -0.01, 0.01, "ACCENT", "CANVAS"))


def ad_aframe(t, p):
    a = [tag(t, t.move(t.cube(0, 0.7, -0.03, 0.03, 0, 1.0), (0, 0.3 * s, 0.009), (0.28 * -s, 0, 0)), "PANEL", "BOARD", 0.0) for s in (1, -1)]  # lean keeps min z >= 0
    return J(t, *a, tag(t, t.cube(0, 0.7, -0.05, 0.05, 0.98, 1.0), "METAL", "METAL", 0.0))


def ad_wall_zone(t, p):
    return J(t, face(t, 0, 6, -0.02, 0.0, 0.0, 3.0), rect(t, 0, 6, 0.0, 0.06, -0.03, -0.02, "ACCENT"))


def gantry(t, p):
    cols = [box(t, x, x + 0.5, -0.25, 0.25, 0, 6.5, "METAL", "METAL") for x in (-0.5, 17.5)]
    ch = [tag(t, t.cube(-0.5, 18.0, -0.3, 0.3, z, z + 0.14), "METAL", "METAL", 0.0) for z in (5.6, 6.5)]
    dia = [tag(t, t.move(t.cube(-0.6, 0.6, -0.04, 0.04, -0.04, 0.04), (0.5 + i * 1.2, 0, 6.05), (0, -1.0 if i % 2 else 1.0, 0)), "METAL", "GREY", 0.0)
           for i in range(14)]
    panels = []
    for k, w in enumerate((4.2, 4.2, 4.6)):
        x0 = 1.0 + k * 5.6
        panels += [rect(t, x0, x0 + w, 4.0, 6.0, -0.32, -0.3, "NEUTRAL"), rect(t, x0 + 0.06, x0 + w - 0.06, 4.06, 5.94, -0.34, -0.32, "ACCENT")]
    hang = tag(t, t.array(t.cube(0, 0.06, -0.3, -0.05, 5.95, 6.5), 8, (2.4, 0, 0), (1.0, 0, 0)), "METAL", "GREY", 0.0)
    return J(t, *cols, *ch, *dia, *panels, hang)


def sg_catalogue():
    S = "SG"
    cat = [
        E("WS-0130", "SignPost_Blue_A", lambda t, p: J(t, post(t, 0, 0, 2.4, 0.0, 0.04, 6), tag(t, t.cyl(0.05, 0.05, (0, 0, 2.425), "z", 6), "METAL", "METAL", 0.0)), S, paint={"METAL": BLUE}),
        E("WS-0132", "StreetNamePlate_A", lambda t, p: J(t, post(t, 0, 0, 2.6), post(t, 0.9, 0, 2.6), f_name_plate(t, 0.45, 2.3)), S, paint={"ACCENT": BLUE}),
        E("WS-0136", "Chevron_A", lambda t, p: J(t, post(t, 0.05, 0, 2.0), post(t, 0.65, 0, 2.0), rect(t, 0, 0.7, 1.0, 1.8, -0.03, 0.0, "GREY"),
                                              *[bary(t, 0.35 + dx, 1.4, 0.4, 0.07, a, "NEUTRAL") for dx, a in ((-0.12, 0.9), (0.12, -0.9))]), S, paint={"GREY": BLACK}),
        E("WS-0137", "GiveWay_A", pole_sign(f_giveway), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0138", "RoundaboutAhead_A", pole_sign(f_roundabout_ahead), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0138", "RoundaboutMandatory_A", pole_sign(f_mandatory_round), S, h=3.0, paint={"ACCENT": BLUE}),
        E("WS-0139", "NoEntry_A", pole_sign(f_no_entry), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0140", "OneWay_A", pole_sign(f_one_way), S, h=3.0, paint={"ACCENT": BLUE}),
        E("WS-0141", "SpeedLimit_A", pole_sign(f_speed), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0142", "NoStopping_A", pole_sign(lambda t, cx, cz: f_no_stop(t, cx, cz, True)), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0142", "NoWaiting_B", pole_sign(lambda t, cx, cz: f_no_stop(t, cx, cz, False)), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0143", "KeepLeft_A", pole_sign(f_keep_left), S, h=3.0, paint={"ACCENT": BLUE}),
        E("WS-0144", "NoUTurn_A", pole_sign(f_uturn), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0144", "NoRightTurn_B", pole_sign(f_no_turn), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0145", "BusStopPlate_A", pole_sign(f_bus_stop, 2.6, 3.0), S, h=3.0, paint={"ACCENT": YELLOW}),
        E("WS-0146", "WarnPedestrians_A", pole_sign(lambda t, cx, cz: f_warn(t, cx, cz, i_ped)), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0146", "WarnSchool_B", pole_sign(lambda t, cx, cz: f_warn(t, cx, cz, i_two)), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0146", "WarnSlow_C", pole_sign(lambda t, cx, cz: f_warn(t, cx, cz, i_slow)), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0147", "HeightLimit_A", pole_sign(f_height), S, h=3.0, paint={"ACCENT": RED}),
        E("WS-0148", "TouristBrown_A", pole_sign(f_tourist), S, h=3.0, paint={"ACCENT": BROWN}),
        E("WS-0149", "CCTVPlate_A", pole_sign(f_cctv), S, h=3.0, paint={"ACCENT": BLUE}),
        E("WS-0150", "PoliceNotice_A", board2(f_police, 1.4, 0.9), S, paint={"ACCENT": BLUE}),
        E("WS-0151", "BathingFlags_A", board2(f_bathing, 1.1, 1.3), S, paint={"ACCENT": RED, "TIMBER": YELLOW, "BOARD": GREEN}),
        E("WS-0155", "HangingRound_A", hanging_round, S, paint={"ACCENT": RED}),
        E("WS-0156", "Lightbox_A", lightbox, S, mat2="MAT_SignGlow_A"),
        E("WS-0157", "SignboardFrame_2x06", signboard_frame(2.0, 0.6), S),
        E("WS-0157", "SignboardFrame_3x08", signboard_frame(3.0, 0.8), S),
        E("WS-0157", "SignboardFrame_4x10", signboard_frame(4.0, 1.0), S),
        E("WS-0161", "FlexBillboard_6x3", flex_billboard(7.0, 3.0, 3.0), S, h=6.0),
        E("WS-0161", "FlexBillboard_9x4", flex_billboard(10.0, 4.0, 3.5), S, h=8.0),
        E("WS-0162", "Unipole_A", unipole, S, h=12.0),
        E("WS-0163", "CorrugatedHoarding_A", hoarding, S),
        E("WS-0164", "ShelterPosterBox_A", poster_box, S, mat2="MAT_SignGlow_A"),
        E("WS-0165", "AdSlot_Crown_A", ad_slot(12.0, 3.0, 0.0), S),
        E("WS-0165", "AdSlot_Podium_B", ad_slot(6.0, 2.0, 0.0), S),
        E("WS-0166", "AdFace_3x1", ad_face(3.0, 1.0), S),
        E("WS-0166", "AdFace_2x1", ad_face(2.0, 1.0), S),
        E("WS-0166", "AdFace_1x1", ad_face(1.0, 1.0), S),
        E("WS-0167", "LEDScreen_A", led_screen, S, h=6.0, mat2="MAT_SignGlow_A"),
        E("WS-0168", "LampBannerPair_A", lamp_banner_pair, S, h=7.0, paint={"ACCENT": RED}),
        E("BH-0082", "AdFlag_A", ad_flag, S, paint={"ACCENT": RED}),
        E("BH-0082", "AdAFrame_A", ad_aframe, S),
        E("BH-0082", "AdWallZone_A", ad_wall_zone, S),
        E("WS-0094", "DirectionGantry_A", gantry, S, h=7.0, paint={"ACCENT": BLUE}),
    ]
    return cat


# ---- ground and furniture (SF) ----------------------------------------------------------------------------------
def sq_cover(t, p):
    frame = box(t, -0.45, 0.45, -0.45, 0.45, 0, 0.03, "METAL", "GREY", 0.0)
    plate = tag(t, t.cube(-0.38, 0.38, -0.38, 0.38, 0.03, 0.045), "METAL", "METAL", 0.0)
    ribs = tag(t, t.array(t.cube(-0.34, 0.34, -0.012, 0.012, 0.045, 0.055), 7, (0, 0.11, 0), (0, -0.33, 0)), "METAL", "GREY", 0.0)
    return J(t, frame, plate, ribs)


def telecom_cover(t, p):
    fr = box(t, -0.5, 0.5, -0.3, 0.3, 0, 0.03, "METAL", "GREY", 0.0)
    return J(t, fr, tag(t, t.cube(-0.46, -0.01, -0.26, 0.26, 0.03, 0.045), "METAL", "METAL", 0.0), tag(t, t.cube(0.01, 0.46, -0.26, 0.26, 0.03, 0.045), "METAL", "METAL", 0.0),
             tag(t, t.array(t.cube(-0.4, -0.08, -0.01, 0.01, 0.045, 0.052), 5, (0, 0.1, 0), (0, -0.2, 0)), "METAL", "GREY", 0.0))


def valve_box(t, p):
    return J(t, tag(t, t.cyl(0.13, 0.03, (0, 0, 0.015), "z", 10), "METAL", "GREY", 0.0), tag(t, t.cyl(0.1, 0.025, (0, 0, 0.04), "z", 10), "METAL", "METAL", 0.0),
             tag(t, t.cube(-0.06, 0.06, -0.01, 0.01, 0.052, 0.06), "METAL", "GREY", 0.0))


def power_pit(t, p):
    fr = box(t, -0.3, 0.3, -0.3, 0.3, 0, 0.04, "CONCRETE", "GREY", 0.0)
    return J(t, fr, tag(t, t.cube(-0.26, 0.26, -0.26, 0.26, 0.04, 0.05), "METAL", "METAL", 0.0),
             tag(t, t.array(t.cube(-0.2, -0.12, -0.03, 0.03, 0.05, 0.055), 2, (0.32, 0, 0)), "METAL", "GREY", 0.0),
             tag(t, t.array(t.cube(-0.2, 0.2, -0.012, 0.012, 0.05, 0.057), 4, (0, 0.12, 0), (0, -0.18, 0)), "METAL", "GREY", 0.0))


def u_drain(missing=(), length=2.0, end=False):
    def body(t, p):
        g = [box(t, 0, length, -0.28, 0.28, 0, 0.1, "CONCRETE", "ACCENT", 0.0)]
        for y0, y1 in ((-0.28, -0.225), (0.225, 0.28)):
            g.append(box(t, 0, length, y0, y1, 0, 0.42, "CONCRETE", "ACCENT"))
        if end:
            g.append(box(t, length - 0.06, length, -0.28, 0.28, 0, 0.42, "CONCRETE", "ACCENT"))
        n = int(round(length / 0.5))
        for i in range(n):
            if i in missing:
                g.append(tag(t, t.cube(i * 0.5 + 0.02, i * 0.5 + 0.48, -0.2, 0.2, 0.1, 0.13), "SPALL", "GREY", 0.0))
                continue
            g.append(tag(t, t.cube(i * 0.5 + 0.01, i * 0.5 + 0.49, -0.27, 0.27, 0.36, 0.42), "CONCRETE", "ACCENT", 0.0))
            g.append(tag(t, t.cube(i * 0.5 + 0.2, i * 0.5 + 0.3, -0.04, 0.04, 0.42, 0.435), "METAL", "GREY", 0.0))
        return J(t, *g)
    return body


def outfall(t, p):
    pipe = t.boolean(t.cyl(0.5, 3.0, (1.5, 0, 0.55), "x", 14), [t.cyl(0.4, 3.2, (1.5, 0, 0.55), "x", 14)])
    head = t.boolean(t.cube(-0.1, 0.3, -1.1, 1.1, 0, 1.4), [t.cyl(0.4, 0.8, (0.1, 0, 0.55), "x", 14)])
    apron = t.cube(2.4, 4.4, -1.0, 1.0, 0, 0.12)
    wing = [t.cube(2.4, 3.6, s * 0.95 - 0.1, s * 0.95 + 0.1, 0, 0.5) for s in (-1, 1)]
    return J(t, tag(t, pipe, "CONCRETE", "ACCENT"), tag(t, head, "WALL", "GREY"), tag(t, apron, "CONCRETE", "GREY", 0.0), *[tag(t, w, "CONCRETE", "ACCENT", 0.0) for w in wing])


def push_button(t, p):
    return J(t, post(t, 0, 0, 2.6, 0.0, 0.05, 8), box(t, -0.07, 0.07, -0.13, -0.05, 1.0, 1.25, "METAL", "GREY", 0.0),
             disc(t, 0.03, 0, 1.12, -0.14, -0.13, "ACCENT", 8, 0.0, "METAL"), rect(t, -0.06, 0.06, 1.17, 1.22, -0.15, -0.13, "NEUTRAL", "PANEL"))


def ped_head(t, p):
    hs = box(t, -0.16, 0.16, -0.16, 0, 2.0, 2.8, "METAL", "GREY", 0.0)
    return J(t, post(t, 0, 0, 2.0, -0.08, 0.05, 8), hs, lens(t, 0, 2.6, 0.1, "ACCENT", -0.18, -0.16), lens(t, 0, 2.25, 0.1, "TIMBER", -0.18, -0.16),
             rect(t, -0.15, 0.15, 2.7, 2.74, -0.22, -0.16, "GREY", "METAL"), rect(t, -0.15, 0.15, 2.35, 2.39, -0.22, -0.16, "GREY", "METAL"))


def countdown(t, p):
    return J(t, post(t, 0, 0, 2.2, -0.08, 0.05, 8), box(t, -0.2, 0.2, -0.16, 0, 2.2, 2.6, "METAL", "GREY", 0.0),
             glow(t, tag(t, t.cube(-0.17, 0.17, -0.18, -0.16, 2.24, 2.56), "PANEL", "BOARD", 0.0)))


def controller_cabinet(t, p):
    b = box(t, 0, 0.7, 0, 0.45, 0.1, 1.4, "METAL", "GREY")
    door = tag(t, t.cube(0.05, 0.65, -0.015, 0.0, 0.2, 1.3), "METAL", "METAL", 0.0)
    roof = tag(t, t.cube(-0.03, 0.73, -0.03, 0.48, 1.4, 1.45), "METAL", "GREY", 0.0)
    base = box(t, -0.05, 0.75, -0.05, 0.5, 0, 0.1, "CONCRETE", "ACCENT", 0.0)
    vent = tag(t, t.array(t.cube(0.1, 0.6, -0.03, 0.0, 1.1, 1.13), 4, (0, 0, -0.07)), "LOUVRE", "GREY", 0.0)
    return J(t, b, door, roof, base, vent, tag(t, t.cube(0.55, 0.6, -0.04, -0.015, 0.7, 0.9), "METAL", "GREY", 0.0))


def guard_rail(t, p):
    posts = tag(t, t.array(t.cyl(0.03, 1.1, (0, 0, 0.55), "z", 8), 3, (1.5, 0, 0), (0, 0, 0)), "METAL", "METAL", 0.0)
    rails = [tag(t, t.cyl(0.025, 3.0, (1.5, 0, z), "x", 8), "METAL", "METAL", 0.0) for z in (0.45, 1.05)]
    bars = tag(t, t.array(t.cyl(0.012, 0.6, (0, 0, 0.75), "z", 6), 10, (0.3, 0, 0), (0.15, 0, 0)), "METAL", "GREY", 0.0)
    return J(t, posts, *rails, bars)


def stairs(width, n, rise, tread, cheek=True, cheek_w=0.25, rail_=False):
    def body(t, p):
        g = []
        for i in range(n):
            g.append(box(t, 0.003, width - 0.003, -(n - i) * tread + 0.003, -(n - i - 1) * tread - 0.003, 0, (i + 1) * rise, "CONCRETE", "ACCENT", 0.5))
        if cheek:
            for x0, x1 in ((-cheek_w, 0), (width, width + cheek_w)):
                g.append(box(t, x0, x1, -n * tread, 0.0, 0, n * rise + 0.15, "CONCRETE", "ACCENT"))
        return J(t, *g)
    return body


def kerb_ramp(t, p):
    ramp = tag(t, t.move(t.cube(0, 2.0, -1.2, 0.0, 0.0, 0.15), (0, 0, 0), (0, -0.0, 0)), "CONCRETE", "ACCENT", 0.5)
    wings = [tag(t, t.cube(x0, x1, -1.2, 0.0, 0, 0.15), "CONCRETE", "GREY", 0.5) for x0, x1 in ((-0.4, 0), (2.0, 2.4))]
    lip = tag(t, t.cube(0, 2.0, -1.3, -1.2, 0, 0.02), "CONCRETE", "GREY", 0.0)
    return J(t, ramp, *wings, lip, tag(t, t.array(t.cube(0.1, 0.18, -1.0, -0.2, 0.15, 0.165), 6, (0.32, 0, 0)), "CONCRETE", "GREY", 0.0))


def balustrade(t, p):
    base = box(t, 0, 2.0, -0.15, 0.15, 0, 0.12, "CONCRETE", "ACCENT")
    cap = box(t, 0, 2.0, -0.12, 0.12, 0.5, 0.58, "CONCRETE", "ACCENT")
    posts = tag(t, t.array(t.cube(0, 0.16, -0.1, 0.1, 0.12, 0.5), 2, (1.84, 0, 0)), "CONCRETE", "ACCENT", 0.5)
    bal = tag(t, t.array(t.cyl(0.035, 0.38, (0, 0, 0.31), "z", 8), 8, (0.2, 0, 0), (0.2, 0, 0)), "CONCRETE", "ACCENT", 0.0)
    return J(t, base, cap, posts, bal)


def seawall(t, p):
    body = box(t, 0, 4.0, -0.6, 0.6, 0, 2.7, "WALL", "WALL")
    cap = tag(t, t.cube(0, 4.0, -0.75, 0.75, 2.7, 3.3), "CONCRETE", "ACCENT", 1.0)
    round_ = tag(t, t.cyl(0.3, 4.0, (2.0, -0.75, 3.3), "x", 8), "CONCRETE", "ACCENT", 0.0)
    return J(t, body, cap, round_)


# ---- roundabout landmarks (P153, critic fix 2) ---------------------------------------------------------------
def lathe(t, prof, segs=16):
    """Solid of revolution about z from (r, z) pairs, low to high: Mesh Cone frustums (1 mm overlaps) in one union."""
    out = []
    for (r0, z0), (r1, z1) in zip(prof, prof[1:]):
        c = t.node("GeometryNodeMeshCone")
        t.set(c.inputs["Vertices"], segs)
        t.set(c.inputs["Radius Bottom"], r0)
        t.set(c.inputs["Radius Top"], r1)
        t.set(c.inputs["Depth"], z1 - z0 + 0.001)
        out.append(t.move(S(t, c.outputs["Mesh"]), (0, 0, z0)))   # GN Mesh Cone spans z 0..depth
    return out[0] if len(out) == 1 else t.boolean(out[0], out[1:], "UNION")


def _c2m(t, curve, profile, scale=None):
    c2m = t.node("GeometryNodeCurveToMesh")
    t.ng.links.new(curve, c2m.inputs["Curve"])
    t.ng.links.new(profile, c2m.inputs["Profile Curve"])
    c2m.inputs["Fill Caps"].default_value = True
    if scale is not None:
        t.set(c2m.inputs["Scale"], scale)
    return S(t, c2m.outputs["Mesh"])


def _factor(t):
    return S(t, t.node("GeometryNodeSplineParameter").outputs["Factor"])


def fluted(t, r0, r1, z0, z1, flutes=12, depth=0.025):
    """Fluted shaft: a star profile (flutes) swept up a vertical line, tapering r0 -> r1."""
    line = t.node("GeometryNodeCurvePrimitiveLine")
    t.set(line.inputs["Start"], (0.0, 0.0, z0))
    t.set(line.inputs["End"], (0.0, 0.0, z1))
    star = t.node("GeometryNodeCurveStar")
    t.set(star.inputs["Points"], flutes)
    t.set(star.inputs["Inner Radius"], 1.0 - depth / r0)
    t.set(star.inputs["Outer Radius"], 1.0)
    f = _factor(t)
    return _c2m(t, line.outputs["Curve"], star.outputs["Curve"], r0 + (r1 - r0) * f)


def _bezier(t, a, b, c, res):
    bz = t.node("GeometryNodeCurveQuadraticBezier")
    t.set(bz.inputs["Resolution"], res)
    for k, v in (("Start", a), ("Middle", b), ("End", c)):
        t.set(bz.inputs[k], v)
    return bz.outputs["Curve"]


def leaf(t, a, b, c, w, th, res=10):
    """Tulip blade: a rectangle profile swept along a bezier in the xz plane, normal +y so the width runs across
    the blade, scaled by a sine so it tapers at both ends (stem and tip)."""
    cur = _bezier(t, a, b, c, res)
    sn = t.node("GeometryNodeSetCurveNormal")
    try:
        sn.mode = "FREE"
    except (AttributeError, TypeError):
        sn.inputs["Mode"].default_value = "Free"
    t.ng.links.new(cur, sn.inputs["Curve"])
    t.set(sn.inputs["Normal"], (0.0, 1.0, 0.0))
    q = t.node("GeometryNodeCurvePrimitiveQuadrilateral")
    t.set(q.inputs["Width"], th)
    t.set(q.inputs["Height"], w)
    sine = t.math("SINE", _factor(t) * PI, 0.0)
    return _c2m(t, sn.outputs["Curve"], q.outputs["Curve"], 0.25 + 0.75 * sine)


def tube(t, a, b, c, r, res=8, segs=6):
    circ = t.node("GeometryNodeCurvePrimitiveCircle")
    t.set(circ.inputs["Resolution"], segs)
    t.set(circ.inputs["Radius"], r)
    return _c2m(t, _bezier(t, a, b, c, res), circ.outputs["Curve"])


def spin(t, geo, n, a0=0.0):
    """n copies of geo rotated about z."""
    return J(t, *[t.move(geo, (0, 0, 0), (0, 0, a0 + 2 * PI * k / n)) for k in range(n)])


def lantern(t, x, y, zb):
    """Hexagonal bronze lantern 0.9 m: cup, glass, hood, finial (catalogue s6 dark bronze #4A3F35)."""
    g = [tag(t, lathe(t, [(0.06, 0.0), (0.15, 0.1), (0.17, 0.13)], 6), "METAL", "METAL", 0.0),
         tag(t, lathe(t, [(0.16, 0.13), (0.19, 0.52)], 6), "GLASS", "NEUTRAL", 0.0),
         tag(t, lathe(t, [(0.25, 0.52), (0.23, 0.57), (0.05, 0.78), (0.0, 0.9)], 6), "METAL", "METAL", 0.0)]
    return t.move(J(t, *g), (x, y, zb))


def lamp_monument(t, p):
    """South-roundabout lamp monument (catalogue s6, sv_01/sv_02), fictional: a peach flared bell plinth 3.4 m across
    and 2 m high, six pale tulip blades leaning out to 7 m, a fluted column to 12 m with collars, a capital and a crown
    of four lanterns on curled arms around a fifth on top (13.4 m). Blades paler than the plinth as sv_01 shows."""
    segs = t.switch(p.LOD, 24, 12, "INT")
    step = _st(t, tag(t, lathe(t, [(1.7, 0.0), (1.7, 0.25)], segs), "WALL", "WALL", 0.5), 0.0, 0.25)
    bell = _st(t, tag(t, lathe(t, [(1.5, 0.25), (1.45, 0.45), (1.2, 0.8), (0.92, 1.2), (0.72, 1.6), (0.64, 1.85), (0.74, 1.9),
                                   (0.74, 2.05), (0.5, 2.12)], segs), "WALL", "WALL", 0.0), 0.0, 2.12)
    blade = _st(t, tag(t, leaf(t, (0.42, 0.0, 2.0), (1.75, 0.0, 3.5), (1.8, 0.0, 7.0), 0.55, 0.07, t.switch(p.LOD, 12, 6, "INT")),
                       "WALL", "GREY", 0.0), 2.0, 5.0)
    blades = spin(t, blade, 6, PI / 6)
    shaft = [_st(t, tag(t, fluted(t, 0.22 - 0.021 * k, 0.22 - 0.021 * (k + 1), z0, z0 + 3.3), "WALL", "ACCENT", 0.0), z0, 3.3)
             for k, z0 in enumerate((2.05, 5.35, 8.65))]
    collars = [tag(t, lathe(t, [(0.27 - 0.02 * k, z - 0.06), (0.27 - 0.02 * k, z + 0.06)], 16), "CONCRETE", "GREY", 0.0)
               for k, z in enumerate((5.35, 7.0, 8.65))]
    cap = tag(t, lathe(t, [(0.17, 11.92), (0.34, 12.06), (0.34, 12.14), (0.08, 12.2)], 16), "METAL", "METAL", 0.0)
    arm = tag(t, tube(t, (0.12, 0.0, 12.08), (1.0, 0.0, 11.9), (0.95, 0.0, 12.36), 0.035), "METAL", "METAL", 0.0)
    arms = spin(t, arm, 4, PI / 4)
    lamps = [lantern(t, 0.95 * math.cos(PI / 4 + k * PI / 2), 0.95 * math.sin(PI / 4 + k * PI / 2), 12.36) for k in range(4)]
    post_ = tag(t, lathe(t, [(0.06, 12.18), (0.05, 12.5)], 8), "METAL", "METAL", 0.0)
    return J(t, step, bell, blades, *shaft, *collars, cap, arms, *lamps, post_, lantern(t, 0.0, 0.0, 12.5))


def ring(t, r_out, r_in, z0, z1, at, segs=24):
    return t.boolean(t.cyl(r_out, z1 - z0, (at[0], at[1], (z0 + z1) / 2), "z", segs), [t.cyl(r_in, z1 - z0 + 0.2, (at[0], at[1], (z0 + z1) / 2), "z", segs)])


def ystrips(t, geo, r, step=3.6, gap=0.003):
    """Cut a wide round piece into y slabs (3 mm apart) so no trim-sheet island is taller than the 4 m row; one
    18 m disc would squash its UVs ~5x (the kerb measured 18 px/m that way)."""
    n = int(math.ceil(2 * r / step))
    ys = [-r + 2 * r * i / n for i in range(n + 1)]
    return J(t, *[intersect(t, geo, t.cube(-r - 1, r + 1, ya + (gap / 2 if i else -0.5), yb - (gap / 2 if i < n - 1 else -0.5), -1.0, 20.0))
                  for i, (ya, yb) in enumerate(zip(ys, ys[1:]))])


def fountain(t, p):
    """Lotus-roundabout fountain at gf_18 / gf_17 scale, fictional: an 18.3 m outer pool with a cream coping, a raised
    10 m inner pool, eight urn statues on pedestals in the outer ring (placeholders for the hand-made statues) and a
    white tiered centrepiece of three basins and eight ribs to 7.3 m. Jets are a separate FX row (WS-0296)."""
    segs = t.switch(p.LOD, 32, 16, "INT")
    ring_ = lambda ro, ri, z0, z1: arc_blocks(t, ro, ri, z0, z1, 0.0, 2 * PI, 32, 64)  # noqa: E731
    pools = J(t, _st(t, tag(t, ring_(9.0, 8.6, 0.0, 0.55), "WALL", "WALL", 0.0), 0.0, 1.1),
              tag(t, ring_(9.15, 8.5, 0.55, 0.65), "CONCRETE", "ACCENT", 0.0),
              _st(t, tag(t, ring_(4.9, 4.5, 0.0, 1.0), "WALL", "WALL", 0.0), 0.0, 1.1),
              tag(t, ring_(5.0, 4.4, 1.0, 1.08), "CONCRETE", "ACCENT", 0.0),
              ystrips(t, J(t, tag(t, t.cyl(8.62, 0.04, (0, 0, 0.4), "z", 64), "GLASS", "NEUTRAL", 0.0),
                          tag(t, t.cyl(4.52, 0.04, (0, 0, 0.86), "z", 64), "GLASS", "NEUTRAL", 0.0)), 8.62, 1.15))   # GLASS row is 1.2 m
    statue = J(t, box(t, 6.25, 7.15, -0.45, 0.45, 0.3, 0.95, "CONCRETE", "GREY", 0.0),
               tag(t, t.move(lathe(t, [(0.18, 0.95), (0.3, 1.15), (0.42, 1.45), (0.34, 1.75), (0.2, 1.85), (0.28, 1.97)], 12), (6.7, 0, 0)),
                   "CONCRETE", "ACCENT", 0.0))
    shaft = [_st(t, tag(t, fluted(t, 0.45 - 0.05 * k, 0.4 - 0.05 * k, z0, z0 + 1.7, 16, 0.04), "WALL", "WALL", 0.0), z0, 1.7)
             for k, z0 in enumerate((0.86, 2.56, 4.26))]
    tiers = [tag(t, lathe(t, [(0.4, z), (r, z + 0.32), (r, z + 0.44), (r - 0.12, z + 0.44), (0.0, z + 0.3)], segs), "CONCRETE", "ACCENT", 0.0)
             for r, z in ((2.3, 1.8), (1.55, 3.3), (0.95, 4.6))]
    rib = tag(t, tube(t, (2.1, 0.0, 2.2), (1.7, 0.0, 3.9), (0.35, 0.0, 5.9), 0.06), "CONCRETE", "ACCENT", 0.0)
    top = tag(t, lathe(t, [(0.4, 5.95), (0.55, 6.1), (0.3, 6.35), (0.4, 6.6), (0.12, 6.95), (0.0, 7.3)], 12), "CONCRETE", "ACCENT", 0.0)
    return J(t, pools, spin(t, statue, 8, PI / 8), *shaft, *tiers, spin(t, rib, 8), top)


def cannon_plinth(t, p):
    base = box(t, -1.4, 1.4, -0.9, 0.9, 0, 0.5, "CONCRETE", "ACCENT")
    plinth = box(t, -1.1, 1.1, -0.6, 0.6, 0.5, 1.0, "WALL", "WALL")
    barrel = tag(t, t.move(t.cyl(0.2, 2.2, (0, 0, 0), "x", 12), (0.0, 0, 1.55), (0, -0.2, 0)), "METAL", "GREY", 0.0)
    muzzle = tag(t, t.move(t.cyl(0.26, 0.2, (0, 0, 0), "x", 12), (-1.1, 0, 1.2), (0, -0.2, 0)), "METAL", "GREY", 0.0)
    wheels = [tag(t, t.cyl(0.4, 0.12, (0.2, y, 1.4), "y", 12), "METAL", "GREY", 0.0) for y in (-0.5, 0.5)]
    carriage = tag(t, t.cube(-0.5, 0.9, -0.45, 0.45, 1.0, 1.25), "METAL", "GREY", 0.5)
    return J(t, base, plinth, barrel, muzzle, carriage, *wheels)


def rock_pile(t, p):
    g = []
    seeds = [(0.0, 0.0, 0.5, 1.6, 1.1, 1.0, 0.1, 0.2, 0.3), (1.4, 0.3, 0.4, 1.3, 1.0, 0.8, 0.3, 0.1, 0.9), (-1.3, 0.5, 0.45, 1.4, 1.2, 0.9, 0.2, 0.4, 1.4),
             (0.5, 1.2, 0.9, 1.2, 1.0, 0.9, 0.5, 0.2, 2.1), (-0.7, -1.2, 0.4, 1.5, 1.0, 0.8, 0.1, 0.3, 2.9), (1.6, -1.1, 0.35, 1.1, 0.9, 0.7, 0.2, 0.2, 0.5),
             (-2.3, -0.3, 0.3, 1.2, 0.9, 0.7, 0.3, 0.1, 1.7), (0.0, 0.4, 1.1, 1.0, 0.9, 0.8, 0.4, 0.3, 0.8)]
    for x, y, z, lx, ly, lz, a, b, c in seeds:
        g.append(tag(t, t.move(t.cube(-lx / 2, lx / 2, -ly / 2, ly / 2, -lz / 2, lz / 2), (x, y, z + 0.34), (a, b, c)), "CONCRETE", "GREY", 0.5))
    return J(t, *g)


def oruwa(t, p):
    hull = tag(t, t.cyl(0.4, 6.0, (3.0, 0, 0.55), "x", 12, (1, 0.55, 1.0)), "CANVAS", "CANVAS", 0.0)
    keel = tag(t, t.cube(0.2, 5.8, -0.04, 0.04, 0.0, 0.3), "METAL", "GREY", 0.0)
    prow = [tag(t, t.move(t.cube(0, 0.5, -0.05, 0.05, 0, 0.5), (x, 0, 0.7), (0, s * 0.5, 0)), "METAL", "GREY", 0.0) for x, s in ((-0.1, 1), (6.0, -1))]
    booms = tag(t, t.array(t.cube(-0.04, 0.04, 0.3, 2.3, 0.75, 0.82), 2, (2.4, 0, 0), (1.8, 0, 0)), "METAL", "METAL", 0.0)
    flo = tag(t, t.cyl(0.12, 4.6, (3.0, 2.3, 0.55), "x", 8), "CONCRETE", "ACCENT", 0.0)
    mast = tag(t, t.cyl(0.04, 3.5, (3.0, 0, 2.4), "z", 6), "METAL", "METAL", 0.0)
    seats = tag(t, t.array(t.cube(-0.2, 0.2, -0.3, 0.3, 0.7, 0.75), 3, (1.4, 0, 0), (1.0, 0, 0)), "METAL", "GREY", 0.0)
    return J(t, hull, keel, *prow, booms, flo, mast, seats)


def watch_tower(t, p):
    # legs 2.2 m from the ground into the deck; centre lifted 2 cm so the 0.05 rad lean keeps min z >= 0 (critic: -0.15 m)
    legs = [tag(t, t.move(t.cyl(0.07, 2.2, (0, 0, 0), "z", 8), (sx * 0.95, sy * 0.95, 1.12), (sy * 0.05, -sx * 0.05, 0)), "METAL", "METAL", 0.0) for sx in (-1, 1) for sy in (-1, 1)]
    braces = [bary(t, 0, 1.2, 2.5, 0.05, a, "METAL", -0.97, -0.92) for a in (0.7, -0.7)]
    deck = box(t, -1.2, 1.2, -1.2, 1.2, 2.2, 2.3, "CONCRETE", "ACCENT")
    cabin = box(t, -0.9, 0.9, -0.9, 0.9, 2.3, 4.2, "WALL", "WALL")
    win = tag(t, t.cube(-0.7, 0.7, -0.92, -0.9, 3.0, 3.8), "GLASS", "NEUTRAL", 0.0)
    roof = tag(t, t.cube(-1.3, 1.3, -1.3, 1.3, 4.2, 4.35), "CONCRETE", "ACCENT", 0.5)
    ladder = tag(t, t.array(t.cube(1.0, 1.2, 1.2, 1.3, 0.2, 0.26), 8, (0, 0, 0.28)), "METAL", "GREY", 0.0)
    return J(t, *legs, *braces, deck, cabin, win, roof, ladder)


def event_tent(t, p):
    poles = tag(t, t.join(*[t.cyl(0.04, 2.4, (x, y, 1.2), "z", 8) for x in (0.1, 5.9) for y in (0.1, 5.9)]), "METAL", "METAL", 0.0)
    roof = tag(t, t.move(cone(t, 4.5, 1.3, (0, 0, 0), 4), (3.0, 3.0, 3.05), (0, 0, PI / 4)), "WALL", "CANVAS", 0.0)
    val = tag(t, t.join(*[t.cube(0, 6, y0, y1, 2.2, 2.4) for y0, y1 in ((-0.1, 0.0), (6.0, 6.1))] + [t.cube(x0, x1, -0.1, 6.1, 2.2, 2.4) for x0, x1 in ((-0.1, 0.0), (6.0, 6.1))]), "CANVAS", "CANVAS", 0.0)
    return J(t, poles, roof, val)


def tree_band(t, p):
    trunk = tag(t, t.cyl(0.14, 1.4, (0, 0, 0.7), "z", 10), "CONCRETE", "GREY", 0.0)
    band = tag(t, t.cyl(0.155, 0.9, (0, 0, 0.55), "z", 10), "CONCRETE", "NEUTRAL", 0.0)
    lime = tag(t, t.cyl(0.158, 0.1, (0, 0, 0.05), "z", 10), "CONCRETE", "ACCENT", 0.0)
    return J(t, trunk, band, lime)


def tactile(t, p):
    base = box(t, 0, 4.0, -0.3, 0.3, 0, 0.012, "SHEET", "ACCENT", 0.0)
    rid = tag(t, t.array(t.cube(0.05, 0.1, -0.25, 0.25, 0.012, 0.03), 40, (0.1, 0, 0), (0, 0, 0)), "SHEET", "ACCENT", 0.0)
    return J(t, base, rid)


ARC_SEGS_Q = 24   # chords per quarter for kerb and ring arcs (critic fix 3: 6 chords showed kinks; gate >= 24)


def quarter_ring(t, r_out, r_in, z0, z1, segs_q=ARC_SEGS_Q, gap=0.003):
    """Smooth quarter annulus (0..90 deg, centre at the origin) as segs_q chord blocks (see arc_blocks)."""
    return arc_blocks(t, r_out, r_in, z0, z1, 0.0, PI / 2, segs_q, 4 * segs_q, gap)


def arc_blocks(t, r_out, r_in, z0, z1, a_start, a_end, blocks, poly, gap=0.003):
    """Annulus arc as `blocks` separate blocks, 3 mm apart: a `poly`-gon ring (vertices on every block end) cut by
    two half-space boxes per block. Separate blocks keep each trim-sheet island under ~2 m (one 14 m kerb island
    squashed its UVs to 18 px/m) and never share coplanar faces."""
    zc, d = (z0 + z1) / 2, z1 - z0
    ann = t.boolean(t.cyl(r_out, d, (0, 0, zc), "z", poly), [t.cyl(r_in, d + 0.2, (0, 0, zc), "z", poly)])
    big = r_out + 2.0
    da = (a_end - a_start) / blocks
    out = []
    for i in range(blocks):
        a0, a1 = a_start + da * i, a_start + da * (i + 1)
        left = t.move(t.cube(-big, big, gap / 2, big, z0 - 0.1, z1 + 0.1), (0, 0, 0), (0, 0, a0))     # above ray a0
        right = t.move(t.cube(-big, big, -big, -gap / 2, z0 - 0.1, z1 + 0.1), (0, 0, 0), (0, 0, a1))  # below ray a1
        out.append(intersect(t, ann, left, right))
    return J(t, *out)


def intersect(t, *geos):
    """Mesh boolean INTERSECT (gnlib.boolean wires Mesh 1, which INTERSECT does not have)."""
    n = t.node("GeometryNodeMeshBoolean", operation="INTERSECT")
    try:
        n.solver = "MANIFOLD"
    except TypeError:
        n.solver = "EXACT"
    for g in geos:
        t.ng.links.new(g.s, n.inputs["Mesh 2"])
    return S(t, n.outputs["Mesh"])


def island_kerb(r=14.0, deg=90, w=0.25, z=0.25):
    def body(t, p):
        return tag(t, quarter_ring(t, r + w / 2, r - w / 2, 0.0, z), "CONCRETE", "ACCENT", 0.5)
    return body


def splitter(t, p):
    """Elliptic splitter island 6 x 2 m, a 0.15 m kerb and a 1 cm raised paved infill (critic: the 0.35 m nose post
    stood 0.495 m tall, 2.5x a kerb; gate 0.15-0.25 m)."""
    d = tag(t, t.cyl(1.0, 0.15, (3.0, 0, 0.075), "z", 24, (3.0, 1.0, 1.0)), "CONCRETE", "ACCENT", 0.5)
    top = tag(t, t.cyl(0.85, 0.02, (3.0, 0, 0.16), "z", 24, (3.0, 0.8, 1.0)), "CONCRETE", "GREY", 0.0)
    return J(t, d, top)


def sponsor_boards(t, p):
    return J(t, *[J(t, post(t, x + 0.1, 0, 1.4), post(t, x + 1.9, 0, 1.4), face(t, x, x + 2.0, -0.04, 0.0, 0.6, 1.5)) for x in (0.0, 3.0)])


# ---- Baladaksha lake edge (P162) -------------------------------------------------------------------------------
# Agent 2026-11-20 shots os_10, os_13, os_14, os_20 (Street View 2021-22; proportions +-20 %, no site measure).
# Frame for these pieces: x along the edge, +y toward the lake, the road at y < 0, z up, pivot at the start of the run.
# Modular lengths (2 m rails, 4 m runs) so the placement code can tile them end to end.
GREEN_BAR, GREY_TUBE, RUST, PAVER_RED, KERB_GREY = "#2F6B3A", "#8E9492", "#8A3B22", "#8A4B3A", "#B9B7B0"


def EN(row, name, body, h, **kw):
    """Entry with an explicit inventory row name (no WS row exists yet for the lake-edge pieces)."""
    return dict(row=row, name=f"KIT_SF_{name}", body=body, h=h, variant="A", refs=kw.pop("refs", []), paint=kw.pop("paint", {}), **kw)


def block_seat(L, d, h):
    def body(t, p):
        return box(t, 0, L, -d / 2, d / 2, 0, h, "CONCRETE", "ACCENT", 1.0)
    return body


def slab_marker(t, p):
    """Upright rust-red perforated slab, 0.7 m wide, 1.1 m tall on a low plinth (os_13: a row of them in the verge); 2 x 3 square holes."""
    plinth = box(t, 0.0, 0.7, -0.2, 0.2, 0, 0.12, "CONCRETE", "ACCENT", 0.5)
    slab = t.cube(0.05, 0.65, -0.05, 0.05, 0.12, 1.1)
    holes = [t.cube(0.15 + 0.2 * i, 0.27 + 0.2 * i, -0.1, 0.1, 0.35 + 0.22 * j, 0.50 + 0.22 * j) for i in range(2) for j in range(3)]
    return J(t, plinth, tag(t, t.boolean(slab, holes), "PANEL", "NEUTRAL", 0.5))


def green_rail(role="METAL", bars=15):
    def body(t, p):
        posts = tag(t, t.array(t.cube(-0.035, 0.035, -0.035, 0.035, 0, 1.05), 2, (1.93, 0, 0), (0.035, 0, 0)), "METAL", role, 0.5)
        top = tag(t, t.cube(0, 2.0, -0.03, 0.03, 0.97, 1.03), "METAL", role, 0.5)
        low = tag(t, t.cube(0, 2.0, -0.025, 0.025, 0.10, 0.14), "METAL", role, 0.5)
        pitch = 1.86 / (bars - 1)
        vb = tag(t, t.array(t.cyl(0.011, 0.84, (0, 0, 0.55), "z", 6), bars, (pitch, 0, 0), (0.07, 0, 0)), "METAL", role, 0.0)
        return J(t, posts, top, low, vb)
    return body


def tube_rail(t, p):
    """Grey 3-rail tube railing at the water (os_13): 2 m module, posts at both ends."""
    posts = tag(t, t.array(t.cyl(0.04, 1.05, (0, 0, 0.525), "z", 8), 2, (2.0, 0, 0), (0, 0, 0)), "METAL", "GREY", 0.0)
    rails = [tag(t, t.cyl(0.022, 2.0, (1.0, 0, z), "x", 8), "METAL", "GREY", 0.0) for z in (0.40, 0.72, 1.02)]
    return J(t, posts, *rails)


def paver_strip(t, p):
    """Footway strip 4 m x 2.5 m beside the kerb (os_13, os_20): red-brown pavers level with a light-grey kerb whose top
    and road face carry the yellow line. Paver joints are texture, not geometry."""
    slab = box(t, 0, 4.0, 0.0, 2.5, 0, 0.14, "CONCRETE", "TILE", 0.0)
    kerb = box(t, 0, 4.0, -0.15, 0.0, 0, 0.15, "CONCRETE", "GREY", 0.5)
    top = tag(t, t.cube(0, 4.0, -0.12, -0.03, 0.15, 0.158), "WALL", "NEUTRAL", 0.0)
    face = tag(t, t.cube(0, 4.0, -0.158, -0.15, 0.04, 0.13), "WALL", "NEUTRAL", 0.0)
    return J(t, slab, kerb, top, face)


def walk_path(t, p):
    """Low stone walking path 4 m x 4 m (os_14): grey stone pavers, a 0.3 m yellow guiding strip with five ribs down the middle."""
    slab = box(t, 0, 4.0, 0.0, 4.0, 0, 0.06, "CONCRETE", "GREY", 0.0)
    strip = tag(t, t.cube(0, 4.0, 1.85, 2.15, 0.06, 0.072), "SHEET", "NEUTRAL", 0.0)
    ribs = tag(t, t.array(t.cube(0, 4.0, 0.0, 0.03, 0.072, 0.085), 5, (0, 0.06, 0), (0, 1.89, 0)), "SHEET", "NEUTRAL", 0.0)
    return J(t, slab, strip, ribs)


def lake_wall(R=None, L=4.0, n=6):
    """Lake wall, rounded coping, no railing (os_14): stem from the waterline (pivot, z = 0) to 0.35 m above the path, a half-round coping; the path surface is at z = 0.9,
    so the placement code sets the piece 0.9 m below the path level.
    R=None is straight; R set is a plan curve of arc length L bending toward +y (the lake); the same piece turned 180 deg about
    its far end is the opposite hand."""
    def body(t, p):
        parts = []
        if R is None:
            parts.append(tag(t, t.cube(0, L, 0.0, 0.3, 0.0, 1.25), "CONCRETE", "ACCENT", 0.5))
            parts.append(tag(t, t.cyl(0.19, L, (L / 2, 0.15, 1.26), "x", 12), "CONCRETE", "ACCENT", 0.0))
            return J(t, *parts)
        th = L / R
        for i in range(n):
            a = th * (i + 0.5) / n
            cx, cy = R * math.sin(a), R * (1 - math.cos(a))
            ch = 2 * R * math.sin(th / 2 / n) + 0.03
            blk = t.move(t.cube(-ch / 2, ch / 2, 0.0, 0.3, 0.0, 1.25), (cx, cy, 0), (0, 0, a))
            cop = t.move(t.cyl(0.19, ch, (0, 0.15, 1.26), "x", 12), (cx, cy, 0), (0, 0, a))
            parts += [tag(t, blk, "CONCRETE", "ACCENT", 0.5), tag(t, cop, "CONCRETE", "ACCENT", 0.0)]
        return J(t, *parts)
    return body


LAKE_ROW = "Baladaksha lake edge (agent shots 2026-11-20)"
LAKE_CATALOGUE = [
    EN(LAKE_ROW, "BlockSeat_Concrete_A", block_seat(1.6, 0.55, 0.45), 0.45, refs=["os_13"], paint={"ACCENT": "#A9A69E"}),
    EN(LAKE_ROW, "BlockSeat_Cube_B", block_seat(0.6, 0.6, 0.55), 0.55, refs=["os_14", "os_15"], paint={"ACCENT": "#A9A69E"}),
    EN(LAKE_ROW, "SlabMarker_Rust_A", slab_marker, 1.1, refs=["os_13"], paint={"NEUTRAL": RUST, "ACCENT": "#A9A69E"}),
    EN(LAKE_ROW, "Railing_GreenBar_A", green_rail(), 1.05, refs=["os_10"], paint={"METAL": GREEN_BAR}),
    EN(LAKE_ROW, "Railing_Tube3_A", tube_rail, 1.05, refs=["os_13"], paint={"GREY": GREY_TUBE}),
    EN("Baladaksha footways: red paver east, wide concrete west (ITC podium)", "PaverStrip_YellowKerb_A", paver_strip, 0.16,
       refs=["os_13", "os_20"], paint={"TILE": PAVER_RED, "GREY": KERB_GREY, "NEUTRAL": YELLOW}),
    EN(LAKE_ROW, "WalkPath_Stone_A", walk_path, 0.09, refs=["os_14", "os_15"], paint={"GREY": "#9A9A96", "NEUTRAL": YELLOW}),
    EN(LAKE_ROW, "LakeWall_Straight_A", lake_wall(), 1.25, refs=["os_14"], paint={"ACCENT": "#B3B0A8"}),
    EN(LAKE_ROW, "LakeWall_Curve_R24_A", lake_wall(24.0), 1.25, refs=["os_14"], paint={"ACCENT": "#B3B0A8"}),
]


def sf_catalogue():
    S = "SF"
    cat = [
        E("WS-0079", "ServiceCover_Framed_A", sq_cover, S, h=0.1, paint={"METAL": "#6C6F70", "GREY": "#4E5254"}),
        E("WS-0080", "TelecomCover_A", telecom_cover, S, h=0.1, paint={"METAL": "#6C6F70", "GREY": "#4E5254"}),
        E("WS-0081", "ValveBox_A", valve_box, S, h=0.1, paint={"METAL": "#6C6F70", "GREY": "#4E5254"}),
        E("WS-0082", "PowerPitCover_A", power_pit, S, h=0.1, paint={"METAL": "#6C6F70", "GREY": "#8A877F"}),
        E("WS-0083", "UDrain_Straight_A", u_drain(), S, h=0.5),
        E("WS-0083", "UDrain_End_B", u_drain(length=1.0, end=True), S, h=0.5),
        E("WS-0083", "UDrain_MissingSlab_C", u_drain(missing=(1, 2)), S, h=0.5),
        E("WS-0084", "StormOutfall_A", outfall, S, h=1.4),
        E("WS-0091", "PushButtonBox_A", push_button, S, h=2.6, paint={"ACCENT": RED, "GREY": "#4E5254"}),
        E("WS-0089", "PedSignalHead_A", ped_head, S, h=2.8, paint={"ACCENT": RED, "TIMBER": "#3FBF6A", "GREY": "#2A2C2E"}),
        E("WS-0090", "CountdownDisplay_A", countdown, S, h=2.6, mat2="MAT_SignGlow_A", paint={"GREY": "#2A2C2E"}),
        E("WS-0092", "ControllerCabinet_A", controller_cabinet, S, h=1.5, paint={"GREY": "#7E8A86", "METAL": "#6E7A76"}),
        E("WS-0093", "PedGuardRail_A", guard_rail, S, h=1.1, paint={"METAL": "#C9CBC8", "GREY": "#D9DBD8"}),
        E("WS-0225", "PromenadeStep_4m", stairs(4.0, 5, 0.15, 0.32), S, h=0.8),
        E("WS-0226", "RoadsideFlight_A", stairs(3.0, 8, 0.17, 0.3), S, h=1.5),
        E("WS-0228", "NorthWideFlight_A", stairs(12.0, 3, 0.17, 0.35), S, h=0.6),
        E("WS-0230", "KerbRamp_Green_A", kerb_ramp, S, h=0.3),
        E("WS-0231", "SeawallBalustrade_A", balustrade, S, h=0.6),
        E("WS-0237", "SeawallBody_Cap_A", seawall, S, h=3.3),
        E("WS-0240", "BeachStairs_A", stairs(4.0, 14, 0.2, 0.32), S, h=3.0),
        E("WS-0101", "LampMonument_A", lamp_monument, S, h=13.4, refs=["sv_01", "sv_02", "catalogue-6"],
          paint={"WALL": "#D89A72", "ACCENT": "#D98E5E", "GREY": "#D2CCC2", "METAL": "#4A3F35", "NEUTRAL": "#F2E3B8"}),
        E("WS-0102", "FountainRoundabout_A", fountain, S, h=7.3, refs=["gf_18", "gf_17"],
          paint={"WALL": "#E9E2D2", "ACCENT": "#F3EEE3", "GREY": "#D8D0BE", "NEUTRAL": "#3E9FAE"}),
        E("WS-0233", "CannonPlinth_A", cannon_plinth, S, h=2.0, paint={"METAL": "#3B3E40", "GREY": "#3B3E40"}),
        E("WS-0241", "RevetmentRock_A", rock_pile, S, h=1.7, paint={"GREY": "#6B6A66"}),
        E("WS-0246", "BeachedOruwa_A", oruwa, S, h=5.0, stripes=("blue", "cream")),
        E("WS-0247", "WatchTower_A", watch_tower, S, h=4.4),
        E("WS-0236", "EventTent_A", event_tent, S, h=4.0, stripes=("cream", "red")),
        E("WS-0076", "TreeBand_A", tree_band, S, h=1.4, paint={"ACCENT": "#A9D45A"}),
        E("WS-0064", "TactileBand_A", tactile, S, h=0.05, paint={"ACCENT": YELLOW}),
        E("WS-0099", "IslandKerb_R14_Q", island_kerb(14.0, 90), S, h=0.3),
        E("WS-0105", "SplitterIsland_A", splitter, S, h=0.2),
        E("WS-0104", "SponsorBoards_A", sponsor_boards, S, h=1.5),
    ]
    cat += LAKE_CATALOGUE
    return cat


# ---- road markings (MK) -----------------------------------------------------------------------------------------
MK_PAINT = {r: WHITE for r in ("WALL", "ACCENT", "TIMBER", "METAL", "NEUTRAL", "GREY", "BOARD")}
MK_YEL = {r: YELLOW for r in MK_PAINT}


def strip(t, x0, x1, y0, y1, role="NEUTRAL"):
    return tag(t, t.cube(x0, x1, y0, y1, 0, 0.012), "WALL", role, 0.0)


def mk_dash(t, p):
    return J(t, *[strip(t, 9 * i, 9 * i + 3, -0.075, 0.075) for i in range(3)])


def mk_solid(w=0.15, off=0.0):
    return lambda t, p: strip(t, 0, 4, off - w / 2, off + w / 2)


def mk_double(t, p):
    return J(t, strip(t, 0, 4, -0.125, -0.025), strip(t, 0, 4, 0.025, 0.125))


def mk_stop(t, p):
    return strip(t, -0.15, 0.15, 0, 3.5)


def mk_giveway(t, p):
    return J(t, *[strip(t, -0.2, 0.2, 0.9 * i, 0.9 * i + 0.6) for i in range(4)])


def mk_yield(t, p):
    return J(t, *[trz(t, 0.45, 1.0 * i + 0.4, 0, PI / 2) for i in range(4)])


def arrow_geo(t, branch):
    g = [strip(t, 0, 2.4, -0.15, 0.15), trz(t, 0.52, 2.66, 0, 0.0)]
    if branch:
        s = branch
        g += [barz(t, 1.7, s * 0.5, 1.4, 0.3, s * PI / 4), trz(t, 0.4, 2.2, s * 1.0, s * PI / 4)]
    return J(t, *g)


def mk_merge(t, p):
    return J(t, strip(t, 0, 1.0, -0.15, 0.15), barz(t, 1.7, 0.4, 1.7, 0.3, 0.46), strip(t, 2.4, 3.2, 0.45, 0.75), trz(t, 0.52, 3.4, 0.6, 0.0))


def outline(t, x0, x1, y0, y1, w=0.1):
    return [strip(t, x0, x1, y0, y0 + w), strip(t, x0, x1, y1 - w, y1), strip(t, x0, x0 + w, y0, y1), strip(t, x1 - w, x1, y0, y1)]


def hatch(t, w, h, pitch, bw=0.12):
    out = []
    c = -h
    while c < w:
        xa, xb = max(c, 0.0), min(c + h, w)
        if xb - xa > 0.15:
            ya, yb = xa - c, xb - c
            out.append(barz(t, (xa + xb) / 2, (ya + yb) / 2, math.hypot(xb - xa, yb - ya), bw, PI / 4))
        c += pitch
    return out


def mk_busbay(t, p):
    return J(t, *outline(t, 0, 12, 0, 2.5))


def mk_gore(t, p):
    return J(t, *outline(t, 0, 8, 0, 2.0, 0.15), *hatch(t, 8, 2.0, 0.9, 0.3))


def mk_boxhatch(t, p):
    return J(t, *outline(t, 0, 6, 0, 6), *hatch(t, 6, 6, 1.0))


def mk_ring(r=15.0):
    def body(t, p):
        return tag(t, quarter_ring(t, r + 0.075, r - 0.075, 0.0, 0.012), "WALL", "NEUTRAL", 0.0)
    return body


def mk_angled(t, p):
    return J(t, *[barz(t, 2.5 * i, 0, 5.0, 0.1, math.radians(60)) for i in range(5)])


def mk_parallel(t, p):
    return J(t, strip(t, 0, 18, 1.9, 2.0), *[strip(t, 6 * i - 0.05, 6 * i + 0.05, 0.0, 2.0) for i in range(4)])


def mk_catalogue():
    S = "MK"
    W, Y = MK_PAINT, MK_YEL
    return [
        E("WS-0026", "LaneDash_3m6m_A", mk_dash, S, h=0.1, paint=W),
        E("WS-0027", "CentreSolid_A", mk_solid(), S, h=0.1, paint=W),
        E("WS-0028", "CentreDouble_A", mk_double, S, h=0.1, paint=W),
        E("WS-0029", "EdgeSolid_A", mk_solid(), S, h=0.1, paint=W),
        E("WS-0030", "NoStopEdge_Yellow_A", mk_solid(0.1, -0.3), S, h=0.1, paint=Y),
        E("WS-0032", "StopLine_A", mk_stop, S, h=0.1, paint=W),
        E("WS-0033", "GiveWayLine_A", mk_giveway, S, h=0.1, paint=W),
        E("WS-0034", "YieldTriangles_A", mk_yield, S, h=0.1, paint=W),
        E("WS-0038", "ArrowAheadLeft_A", lambda t, p: arrow_geo(t, 1), S, h=0.1, paint=W),
        E("WS-0038", "ArrowAheadRight_B", lambda t, p: arrow_geo(t, -1), S, h=0.1, paint=W),
        E("WS-0039", "ArrowMerge_A", mk_merge, S, h=0.1, paint=W),
        E("WS-0045", "BusBayBox_Yellow_A", mk_busbay, S, h=0.1, paint=Y),
        E("WS-0048", "HatchedGore_A", mk_gore, S, h=0.1, paint=W),
        E("WS-0049", "RoundaboutRing_R15_Q", mk_ring(15.0), S, h=0.1, paint=W),
        E("WS-0050", "AngledStrokes_60_A", mk_angled, S, h=0.1, paint=W),
        E("WS-0051", "ParallelBays_A", mk_parallel, S, h=0.1, paint=W),
        E("WS-0052", "BoxJunctionHatch_Yellow_A", mk_boxhatch, S, h=0.1, paint=Y),
    ]


SETS = {"sg": sg_catalogue, "sf": sf_catalogue, "mk": mk_catalogue}


def catalogue(which="sg"):
    return SETS[which]()
