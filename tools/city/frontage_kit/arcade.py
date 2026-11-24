"""Walk-under arcade (colonnade) kit pieces for the colonial Delta Road ground storey (P186).

Agent, 2026-11-20: a REAL walk-under arcade, not a flat arched front. Reference: references/delta-road-shophouses
tile 6 (Cargills, Fort: deep arched arcade, white archivolts and keystones on painted piers, impost band, plinth) and
tile 5 (domed colonial block by the Delta Face roundabout: arcade under the upper floors). How the real one is built:
a load-bearing front wall of piers carries arches; the upper storeys stand on that front wall and on
a back wall (the shop fronts) 2.5 m behind it; the arcade ceiling is the first floor slab, carried across the
walk by beams from each pier to a pilaster on the back wall. The walk is one paved floor a step above the kerb.

Numbers from the Delta Road Street View survey (P188, docs/references/p188/DELTA_ROAD_STREETVIEW_SURVEY.md): no
colonial verandah arcade survives on Delta Road; the walk-under type that does (Kollupitiya, west side) has square
piers about 0.7 m wide, 4-4.5 m apart, a 2-3 m deep walk, a flat soffit at about 4 m and a 1-1.2 m sign band. The
agent asked for arched colonial styling, so the arches and mouldings are colonial and the dimensions are the survey's.

Pieces (same conventions as the frontage kit: facade along +X from the pivot, street on -Y, up +Z, pivot at the
bottom-left front corner on the pavement; storey 4.5 m like the other colonial ground pieces):
- `KIT_Arcade_Colonial_A`: straight bay, 4.5 m wide, 3.5 m deep (0.7 m square piers, 2.5 m clear walk, 0.3 back
  wall with a roller-shutter shop and its signboard). Half piers at both ends: two bays make a 0.7 m pier. Upper
  3 m kit pieces line up with it every 9 m (two bays).
- `KIT_Arcade_Colonial_Corner_A`: convex corner turn, 3.5 x 3.5 m: the street run along +X ends in a 0.7 m corner
  pier, the side run leaves along +Y with its arcade facing +X (a straight bay rotated +90 deg about Z and placed at
  (3.5, 3.5) continues it). One piece serves every convex corner (rotate it).
Every shape comes from Geometry Nodes primitives, booleans and transforms (gnlib); kitbuild finishes, UVs, paints
and bakes them like every other kit piece.
"""
from __future__ import annotations

import math

import bmesh
import bpy

from parts import G, tag

W, H = 4.5, 4.5            # bay width (survey: piers 4-4.5 m apart), colonial ground storey (pieces.GF_COL)
PT = 0.7                   # square pier, 0.7 x 0.7 m (survey); also the front wall (spandrel) thickness
WALK = 2.5                 # clear walk depth, inner pier face to back wall face (survey: 2-3 m)
BACK = PT + WALK           # back wall face (y)
DEPTH = BACK + 0.3         # whole footprint depth
FLOOR = 0.12               # walk floor top: one low step above the pavement
SPRING, RISE = 2.5, 0.8    # springing line and rise of the flattened (elliptical) colonial arch: crown 3.3 m
CROWN = SPRING + RISE      # the 1.2 m band from the crown to the storey line is the sign band (survey 1-1.2 m)
CEIL = 4.0                 # flat soffit of the first-floor slab (survey ~4 m)
BEAM = 3.7                 # underside of the cross beams
STRAIGHT_ARCHES = [(PT / 2, W - PT / 2)]           # 3.8 m clear between half piers
CORNER = DEPTH             # corner piece is DEPTH x DEPTH
CORNER_ARCHES_FRONT = [(PT / 2, CORNER - PT)]      # opens onto the side run's walk
CORNER_ARCHES_SIDE = [(PT, CORNER - PT / 2)]       # opens onto the front run's walk


def _arch(t, a, b, r_add, depth, y, segs):
    """Elliptical arch solid over (a, b): half-span (b - a) / 2 + r_add, rise RISE + r_add, axis along Y."""
    half = (b - a) / 2 + r_add
    return t.cyl(half, depth, ((a + b) / 2, y, SPRING), "y", segs, (1.0, (RISE + r_add) / half, 1.0))


def _solid_spans(length, arches):
    spans, x = [], 0.0
    for a, b in arches:
        spans.append((x, a))
        x = b
    spans.append((x, length))
    return [s for s in spans if s[1] - s[0] > 1e-4]


def _cornice(t, x0, x1, z, p, ext=False):
    """The colonial ground cornice (pieces._string big profile) from x0 to x1; `ext` runs each band on past x1 by
    its own projection so it covers the outside corner (the side run then starts flush at 0). LOD1 keeps the
    deepest band."""
    steps = [(-0.08, 0.0, 0.08), (-0.16, 0.08, 0.16), (-0.24, 0.16, 0.24), (-0.3, 0.24, 0.3), (-0.2, 0.3, 0.36)]
    full = t.join(*[t.cube(x0, x1 + (-y if ext else 0.0), y, 0.01, z + a, z + b) for y, a, b in steps])
    simple = t.cube(x0, x1 + (0.24 if ext else 0.0), -0.24, 0.01, z, z + 0.36)
    return tag(t, t.switch(p.LOD, full, simple), "FRAME", "ACCENT")


def _front(t, p, length, arches, segs, ext=False):
    """Front pier wall (box, not yet cut), arch cutters (their faces become the white intrados) and the applied
    details along local +X. `ext`: the run ends at an outside corner on its right (bands wrap the corner)."""
    grid = tuple(t.switch(p.LOD, g, 2, "INT") for g in (int(length) + 2, 2, 5))
    wall = tag(t, t.cube(0, length, 0, PT, 0, H, grid), "WALL", "WALL", 0.0)
    # jambs keep the wall paint, the intrados (head) takes the white of the archivolt (tile 6)
    cutters = [c for a, b in arches for c in (
        tag(t, t.cube(a, b, -0.4, PT + 0.4, -0.3, SPRING), "WALL", "WALL", 0.0),
        tag(t, _arch(t, a, b, 0.0, PT + 0.8, PT / 2, segs), "FRAME", "ACCENT", 0.0))]
    lod0 = t.bnot(p.LOD)
    det = []
    for a, b in arches:
        # archivolt: a 0.16 m moulded ring proud of the spandrel, keystone at the crown (tile 6: white voussoirs)
        ring = t.boolean(_arch(t, a, b, 0.16, 0.046, -0.022, segs),
                         [_arch(t, a, b, 0.0, 0.3, 0.0, segs),
                          t.cube(a - 0.5, b + 0.5, -0.3, 0.3, SPRING - 2.0, SPRING)])
        cx = (a + b) / 2
        key = t.cube(cx - 0.13, cx + 0.13, -0.085, 0.02, CROWN - 0.12, CROWN + 0.26)
        det += [tag(t, ring, "FRAME", "ACCENT"), t.when(lod0, tag(t, key, "FRAME", "ACCENT"))]
    for s0, s1 in _solid_spans(length, arches):
        end = ext and abs(s1 - length) < 1e-6
        # impost band at the springing, plinth at the foot, flat pilaster on the pier face between them
        det.append(tag(t, t.cube(s0, s1 + (0.07 if end else 0.0), -0.07, 0.01, SPRING - 0.18, SPRING),
                       "FRAME", "ACCENT"))
        det.append(tag(t, t.cube(s0, s1 + (0.06 if end else 0.0), -0.06, 0.01, 0.0, 0.5), "PLINTH", "GREY"))
        if s1 - s0 > 0.6:
            pa, pb = s0 + 0.15, s1 - 0.15
        else:
            pa, pb = (s0, s0 + 0.2) if s0 < 1e-6 else (s1 - 0.2, s1)
        det.append(t.when(lod0, tag(t, t.cube(pa, pb, -0.045, 0.01, 0.5, SPRING - 0.18), "WALL", "WALL")))
    det.append(_cornice(t, 0.0, length, H - 0.36, p, ext=ext))
    return wall, cutters, det


def _back_shop(t, p):
    """Back wall (shop front) with a roller shutter half up over a glazed shop and a signboard: the Delta Road
    default (agent, 2026-11-20) moved under the arcade. Built at y=0 like a ground bay, then moved to BACK."""
    cut = t.use(G["PI_OpeningCutter"], X=0.6, Width=W - 1.2, Sill=0.0, Height=2.9, Depth=0.26, Arched=False, LOD=p.LOD)
    wall = t.boolean(tag(t, t.cube(0, W, 0, 0.3, 0, CEIL, (6, 2, 5)), "WALL", "WALL", 0.0), [cut])
    shop = [t.use(G["PI_Roller"], X0=0.6, X1=W - 0.6, ZTop=2.9, Curtain=1.05, LOD=p.LOD),
            t.use(G["PI_Opening"], X=0.6, Width=W - 1.2, Sill=0.32, Height=2.2, Depth=0.26, Arched=False, Surround=0.0,
                  Ledge=False, Hood=0, Glazing=2, Shutters=0, Grille=False, LOD=p.LOD),
            t.use(G["PI_Sign"], X0=0.4, X1=W - 0.4, Z0=3.05, Z1=3.7),
            tag(t, t.cube(0, W, -0.035, 0.01, 0, 0.3), "PLINTH", "GREY")]
    return t.move(t.join(wall, *shop), (0, BACK, 0))


def _beam(t, x0, x1, y0, y1):
    return tag(t, t.cube(x0, x1, y0, y1, BEAM, CEIL + 0.001), "WALL", "WALL")


def straight(t, p):
    segs = t.switch(p.LOD, 16, 8, "INT")
    wall, cutters, det = _front(t, p, W, STRAIGHT_ARCHES, segs)
    front = t.boolean(wall, cutters)
    floor = tag(t, t.cube(0, W, -0.0, BACK, 0.0, FLOOR), "PLINTH", "GREY")
    ceil = tag(t, t.cube(0, W, PT, BACK, CEIL, H), "REVEAL", "WALL", 0.0)
    beams = t.join(_beam(t, 0.0, 0.15, PT, BACK), _beam(t, W - 0.15, W, PT, BACK))
    pil = tag(t, t.join(t.cube(0, 0.15, BACK - 0.12, BACK, FLOOR, BEAM), t.cube(W - 0.15, W, BACK - 0.12, BACK, FLOOR,
                                                                                    BEAM)), "WALL", "WALL")
    return t.join(front, *det, floor, ceil, beams, pil, _back_shop(t, p))


def corner(t, p):
    segs = t.switch(p.LOD, 16, 8, "INT")
    rot = (0.0, 0.0, math.pi / 2)
    fw, fc, fdet = _front(t, p, CORNER, CORNER_ARCHES_FRONT, segs, ext=True)
    sw, sc, sdet = _front(t, p, CORNER, CORNER_ARCHES_SIDE, segs)
    side = [t.move(g, (CORNER, 0, 0), rot) for g in [sw]]
    walls = t.boolean(fw, side, "UNION")
    cut = fc + [t.move(c, (CORNER, 0, 0), rot) for c in sc]
    front = t.boolean(walls, cut)
    det = fdet + [t.move(g, (CORNER, 0, 0), rot) for g in sdet if g is not None]
    floor = tag(t, t.cube(0, CORNER, 0, CORNER, 0.0, FLOOR), "PLINTH", "GREY")
    ceil = tag(t, t.cube(0, CORNER - PT, PT, CORNER, CEIL, H), "REVEAL", "WALL", 0.0)
    post = tag(t, t.cube(0, 0.3, BACK, CORNER, FLOOR, CEIL), "WALL", "WALL")
    beams = t.join(_beam(t, 0.0, 0.15, PT, BACK), _beam(t, 0.3, CORNER - PT, CORNER - 0.15, CORNER))
    # diagonal beam from the corner pier to the inner post: the groin line where the two walks meet
    half = math.hypot(CORNER - PT - 0.3, BACK - PT) / 2 + 0.2
    diag = t.move(t.cube(-half, half, -0.15, 0.15, BEAM, CEIL + 0.001), ((CORNER - PT + 0.3) / 2, (PT + BACK) / 2, 0),
                  (0, 0, -math.pi / 4))
    return t.join(front, *det, floor, ceil, post, beams, tag(t, diag, "WALL", "WALL"))


REVEAL_PAINT = "#D8CFB8"      # lighter plaster tone for the back-wall opening reveals (was kit METAL grey #8C918F)


def catalogue():
    refs = ["tile06_cargills_arcade", "tile05_delta_face_domed_block", "gf_21"]
    return [("KIT_Arcade_Colonial_A", W, H, "A", straight, refs),
            ("KIT_Arcade_Colonial_Corner_A", CORNER, H, "A", corner, refs)]


PROPS = {
    "KIT_Arcade_Colonial_A": {"arcade_depth": WALK, "footprint_depth": DEPTH, "walk_clear_w": W - PT,
                              "walk_clear_h": round(SPRING - FLOOR, 3), "walk_crown_h": round(CROWN - FLOOR, 3),
                              "walk_floor_z": FLOOR,
                              "collision": "walkable_corridor"},
    "KIT_Arcade_Colonial_Corner_A": {"arcade_depth": WALK, "footprint_depth": CORNER, "walk_clear_w": CORNER - 1.5 * PT,
                                     "walk_clear_h": round(SPRING - FLOOR, 3),
                                     "walk_crown_h": round(CROWN - FLOOR, 3), "walk_floor_z": FLOOR,
                                     "collision": "walkable_corridor", "turn": "convex",
                                     "side_run_origin": f"{CORNER},{CORNER},rotZ+90"},
}


def _col_boxes(name):
    """Collision as a walkable corridor: pier boxes, spandrel lintel, back wall, ceiling and a floor slab; the
    walk between them stays open (3.8 m between piers, 2.5 m deep, 2.38 m clear at the springing, 3.18 m at the
    crown, 3.58 m under the beams inside)."""
    boxes = []
    if name == "KIT_Arcade_Colonial_A":
        for s0, s1 in _solid_spans(W, STRAIGHT_ARCHES):
            boxes.append((s0, s1, -0.05, PT, 0, H))
        boxes += [(0, W, -0.05, PT, CROWN - 0.3, H), (0, W, BACK, DEPTH, 0, H), (0, W, PT, BACK, CEIL, H),
                  (0, W, -0.05, BACK, -0.3, FLOOR)]
    else:
        for s0, s1 in _solid_spans(CORNER, CORNER_ARCHES_FRONT):
            boxes.append((s0, s1, -0.05, PT, 0, H))
        for s0, s1 in _solid_spans(CORNER, CORNER_ARCHES_SIDE):
            boxes.append((CORNER - PT, CORNER + 0.05, s0, s1, 0, H))
        boxes += [(0, CORNER, -0.05, PT, CROWN - 0.3, H), (CORNER - PT, CORNER + 0.05, 0, CORNER, CROWN - 0.3, H),
                  (0, CORNER - PT, PT, CORNER, CEIL, H), (0, 0.3, BACK, CORNER, 0, CEIL),
                  (0, CORNER + 0.05, -0.05, CORNER, -0.3, FLOOR)]
    return boxes


def collision(name, at, coll):
    me = bpy.data.meshes.new(f"{name}_COL")
    bm = bmesh.new()
    for x0, x1, y0, y1, z0, z1 in _col_boxes(name):
        r = bmesh.ops.create_cube(bm, size=1.0)
        for v in r["verts"]:
            v.co.x = x0 + (v.co.x + 0.5) * (x1 - x0)
            v.co.y = y0 + (v.co.y + 0.5) * (y1 - y0)
            v.co.z = z0 + (v.co.z + 0.5) * (z1 - z0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(f"{name}_COL", me)
    ob.location = at
    ob.hide_render = True
    ob["collision"] = "walkable_corridor"
    coll.objects.link(ob)
    return ob
