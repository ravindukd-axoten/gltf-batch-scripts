"""Frontage kit v2 part node groups (P96): openings, shutters, rollers, canopies, services, balconies, signs.

Every group is a real, parametric Geometry Nodes group (`PI_*`); `pieces.py` assembles them per kit piece with
the values from its variant table. Coordinates: x along the facade from the bay's left edge, street on -y, wall
face at y = 0 (wall body 0..0.3), z up from the pavement. Faces carry `trim` (trim-sheet row, see TRIM) and
`role` (paint role, see ROLE); edges carry `bevel_weight_edge` (1 = bevelled on LOD0).
"""
from __future__ import annotations

from gnlib import T, group

# trim-sheet rows: id -> (v0, height) in metres on the 4 m x 16 m sheet (FRONTAGE_KIT_SPEC.md 4)
TRIM = {"WALL": (0, (0.0, 4.0)), "REVEAL": (1, (4.0, 1.0)), "FRAME": (2, (5.0, 1.0)), "CONCRETE": (3, (6.0, 1.0)),
        "ROLLER": (4, (7.0, 2.4)), "LOUVRE": (5, (9.4, 1.2)), "PANEL": (6, (10.6, 1.0)), "GLASS": (7, (11.6, 1.2)),
        "CANVAS": (8, (12.8, 0.8)), "METAL": (9, (13.6, 0.8)), "SPALL": (10, (14.4, 0.8)),
        "PLINTH": (11, (15.2, 0.4)), "SHEET": (12, (15.6, 0.4))}
TR = {k: v[0] for k, v in TRIM.items()}
ROLE = {"WALL": 0, "ACCENT": 1, "TIMBER": 2, "METAL": 3, "NEUTRAL": 4, "CANVAS": 5, "GREY": 6, "BOARD": 7, "TILE": 8}

G: dict = {}


def tag(t: T, geo, trim, role, bevel=1.0):
    geo = t.tag(geo, TR[trim], bevel)
    return t.store(geo, "role", ROLE[role], "INT", "FACE")


def fswitch(t, cond, a, b, kind="FLOAT"):
    return t.switch(cond, a, b, kind)


def fcmp(t, a, b, op="GREATER_THAN"):
    n = t.node("FunctionNodeCompare", data_type="FLOAT", operation=op)
    t.set(n.inputs[0], a)
    t.set(n.inputs[1], b)
    from gnlib import S
    return S(t, n.outputs[0])


def shape(t, xa, xb, zb, zt, y0, y1, arched, segs):
    """Opening solid: a box, or a box to the springing line plus a half-round head (Mesh Boolean union)."""
    rect = t.cube(xa, xb, y0, y1, zb, zt)
    r = (xb - xa) / 2
    spring = zt - r
    body = t.cube(xa, xb, y0, y1, zb, spring)
    # head 1 mm inset front and back: no coplanar caps in the union (they left the lower half-disc as internal
    # faces, the "black disc" in the Colonial A/C arch glass)
    head = t.cyl(r, (y1 - y0) - 0.002, ((xa + xb) / 2, (y0 + y1) / 2, spring), "y", segs)
    arch = t.boolean(body, [head], "UNION")
    return t.switch(arched, rect, arch)


# --- groups ---------------------------------------------------------------------------------------------------

def _cutter(t, p):
    segs = t.switch(p.LOD, 12, 8, "INT")
    return tag(t, shape(t, p.X, p.X + p.Width, p.Sill, p.Sill + p.Height, -0.3, p.Depth, p.Arched, segs),
               "REVEAL", "WALL", 1.0)


def _leaf(t, p):
    """Louvred timber shutter leaf, origin bottom-left-front: stiles and rails, louvre panel, blades on LOD0."""
    w, h = p.Width, p.Height
    ring = t.boolean(t.cube(0, w, 0, 0.035, 0, h), [t.cube(0.055, w - 0.055, -0.1, 0.2, 0.055, h - 0.055)])
    rail = t.cube(0.055, w - 0.055, 0.0, 0.035, h * 0.45, h * 0.45 + 0.05)
    frame = tag(t, t.join(ring, rail), "PANEL", "TIMBER", 0.0)
    panel = tag(t, t.cube(0.055, w - 0.055, 0.02, 0.03, 0.055, h - 0.055), "LOUVRE", "TIMBER", 0.0)
    blade = t.move(t.cube(0.055, w - 0.055, -0.016, 0.016, -0.005, 0.005), (0, 0.0, 0), (0.55, 0, 0))
    blades = tag(t, t.array(blade, (h - 0.14) / 0.12, (0, 0, 0.12), (0, 0.018, 0.12)), "PANEL", "TIMBER", 0.0)
    full = t.join(frame, panel, t.when(t.bnot(p.LOD), blades))
    box = tag(t, t.cube(0, w, 0, 0.035, 0, h), "LOUVRE", "TIMBER", 0.0)     # LOD1: louvres and stiles in the trim
    return t.switch(p.Simple, full, box)


def _opening(t, p):
    x, w, z0, h, d, s = p.X, p.Width, p.Sill, p.Height, p.Depth, p.Surround
    top = z0 + h
    cx = x + w / 2
    segs = t.switch(p.LOD, 12, 8, "INT")
    spring = fswitch(t, p.Arched, top, top - w / 2)
    lod0 = t.bnot(p.LOD)
    out = []
    # architrave surround, sitting on the sill
    ring = t.boolean(shape(t, x - s, x + w + s, z0, top + s, -0.045, 0.02, p.Arched, segs),
                     [shape(t, x, x + w, z0 - 0.2, top, -0.2, 0.2, p.Arched, segs)])
    # LOD1: the surround becomes a flat painted frame (4 boxes, no boolean ring; arches keep the cheap ring)
    flat = t.join(t.cube(x - s, x, -0.03, 0.0, z0, spring), t.cube(x + w, x + w + s, -0.03, 0.0, z0, spring),
                  t.cube(x - s, x + w + s, -0.03, 0.0, top, top + s))
    lod_ring = t.switch(p.Arched, flat, ring)
    out.append(t.when(fcmp(t, s, 0.001), tag(t, t.switch(p.LOD, ring, lod_ring), "FRAME", "ACCENT")))
    # sill ledge with a drip course under it
    ledge = t.join(t.cube(x - s - 0.08, x + w + s + 0.08, -0.11, 0.02, z0 - 0.07, z0),
                   t.when(lod0, t.cube(x - s - 0.03, x + w + s + 0.03, -0.075, 0.0, z0 - 0.14, z0 - 0.07)))
    out.append(t.when(p.Ledge, tag(t, ledge, "CONCRETE", "ACCENT")))
    # head: 1 keystone, 2 concrete sunshade with side fins, 3 moulded hood
    key = t.cube(cx - 0.11, cx + 0.11, -0.075, 0.01, top - 0.12, top + s + 0.12)
    sun = t.join(t.cube(x - s - 0.3, x + w + s + 0.3, -0.6, 0.0, top + s + 0.1, top + s + 0.18),
                 t.cube(x - s - 0.3, x + w + s + 0.3, -0.6, -0.54, top + s + 0.03, top + s + 0.18),
                 t.cube(x - s - 0.3, x - s - 0.24, -0.6, 0.0, top + s - 0.3, top + s + 0.1),
                 t.cube(x + w + s + 0.24, x + w + s + 0.3, -0.6, 0.0, top + s - 0.3, top + s + 0.1))
    hood = t.join(t.when(lod0, t.cube(x - s - 0.05, x + w + s + 0.05, -0.07, 0.01, top + s, top + s + 0.08)),
                  t.cube(x - s - 0.14, x + w + s + 0.14, -0.14, 0.01, top + s + 0.08, top + s + 0.17),
                  t.when(lod0, t.cube(x - s - 0.1, x + w + s + 0.1, -0.1, 0.01, top + s + 0.17, top + s + 0.22)))
    out += [t.when(t.cmp(p.Hood, 1), tag(t, key, "FRAME", "ACCENT")),
            t.when(t.cmp(p.Hood, 2), tag(t, sun, "CONCRETE", "WALL")),
            t.when(t.cmp(p.Hood, 3), tag(t, hood, "FRAME", "ACCENT"))]
    # glass at the back of the reveal
    out.append(tag(t, shape(t, x, x + w, z0, top, d - 0.03, d - 0.005, p.Arched, segs), "GLASS", "NEUTRAL", 0.0))
    # glazing: 1 casement with mullion and transom (fanlight bars when arched), 2 shop frame, 3 panelled doors
    fr = 0.06
    case_ring = t.boolean(shape(t, x, x + w, z0, top, d - 0.09, d - 0.03, p.Arched, segs),
                          [shape(t, x + fr, x + w - fr, z0 + fr, top - fr, d - 0.3, d + 0.1, p.Arched, segs)])
    tz = fswitch(t, p.Arched, z0 + (top - z0) * 0.72, spring)
    transom = t.cube(x, x + w, d - 0.09, d - 0.03, tz - 0.03, tz + 0.03)
    r = w / 2
    bars = t.join(*[t.move(t.cube(-0.014, 0.014, d - 0.085, d - 0.04, 0.0, r - 0.02), t.vec(cx, 0, spring),
                           (0, a, 0)) for a in (-0.785, 0.0, 0.785)])
    fan = t.when(t.band(p.Arched, lod0), bars)
    mull = t.cube(cx - 0.025, cx + 0.025, d - 0.09, d - 0.03, z0, tz)
    casement = t.join(case_ring, transom, mull, fan)
    shop_mulls = t.join(case_ring, t.cube(x, x + w, d - 0.09, d - 0.03, top - 0.55, top - 0.49),
                        t.cube(x + w / 3 - 0.03, x + w / 3 + 0.03, d - 0.09, d - 0.03, z0, top),
                        t.cube(x + 2 * w / 3 - 0.03, x + 2 * w / 3 + 0.03, d - 0.09, d - 0.03, z0, top))
    leaves = []
    for i in range(2):
        lx = x + 0.02 + i * (w / 2 - 0.015)
        lw = w / 2 - 0.025
        leaf = t.cube(lx, lx + lw, d - 0.1, d - 0.04, z0, spring - 0.02)
        panels = t.join(t.cube(lx + 0.09, lx + lw - 0.09, d - 0.12, d - 0.1, z0 + 0.15, z0 + (spring - z0) * 0.42),
                        t.cube(lx + 0.09, lx + lw - 0.09, d - 0.12, d - 0.1, z0 + (spring - z0) * 0.5, spring - 0.15))
        leaves += [leaf, t.when(lod0, panels)]
    doors = t.join(tag(t, t.join(*leaves), "PANEL", "TIMBER", 0.0), tag(t, t.join(transom, fan), "FRAME", "ACCENT", 0.0))
    out += [t.when(t.cmp(p.Glazing, 1), tag(t, casement, "FRAME", "ACCENT", 0.0)),
            t.when(t.cmp(p.Glazing, 2), tag(t, shop_mulls, "METAL", "METAL")),
            t.when(t.cmp(p.Glazing, 3), doors)]
    # shutters: 1 both open on the wall face, 2 closed in the reveal, 3 one open and one hanging off a hinge
    lw, lh = w / 2, spring - z0
    leaf = t.use(G["PI_ShutterLeaf"], Width=lw, Height=lh, LOD=p.LOD, Simple=p.LOD)
    left_open = t.move(leaf, t.vec(x - s - lw, -0.08, z0))     # back face on the surround's face (y -0.045)
    right_open = t.move(leaf, t.vec(x + w + s, -0.08, z0))
    flat = t.use(G["PI_ShutterLeaf"], Width=lw, Height=lh, LOD=True, Simple=p.LOD)   # closed: louvres in the trim
    closed = t.join(t.move(flat, t.vec(x, d - 0.14, z0)), t.move(flat, t.vec(cx, d - 0.14, z0)))
    # hanging: the bottom hinge has gone, the leaf hangs from its top hinge (pivot = its top-left corner, flush
    # with the surround), the foot sagging 0.08 rad toward the window and swung 0.3 rad off the wall
    ay, az = 0.08, -0.3
    import math
    ca, sa, cz, sz = math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    hanging = t.move(leaf, t.vec(x + w + s - lh * sa * cz, -0.08 - lh * sa * sz, z0 + lh - lh * ca), (0.0, ay, az))
    out += [t.when(t.cmp(p.Shutters, 1), t.join(left_open, right_open)),
            t.when(t.cmp(p.Shutters, 2), closed),
            t.when(t.cmp(p.Shutters, 3), t.join(left_open, hanging))]
    # security grille: square bars and two flats in front of the glass
    bar = t.cube(-0.009, 0.009, -0.045, -0.027, z0, spring)
    pitch = fswitch(t, p.LOD, 0.2, 0.3)                 # 0.125 read as a jail grille (critic, v3)
    grille = t.join(t.array(bar, w / pitch, t.vec(pitch, 0, 0), t.vec(x + pitch / 2, 0, 0)),
                    t.cube(x, x + w, -0.05, -0.022, z0 + 0.3, z0 + 0.34),
                    t.cube(x, x + w, -0.05, -0.022, spring - 0.34, spring - 0.3))
    out.append(t.when(p.Grille, tag(t, grille, "METAL", "METAL", 0.0)))
    return t.join(*out)


def _roller(t, p):
    """Roller shutter: drum box under the fascia, guide channels, slatted curtain `Open` m long, bottom bar."""
    x0, x1, zt, c = p.X0, p.X1, p.ZTop, p.Curtain
    drum = tag(t, t.cube(x0 - 0.02, x1 + 0.02, -0.06, 0.2, zt - 0.34, zt), "METAL", "METAL")
    guides = tag(t, t.join(t.cube(x0, x0 + 0.06, -0.02, 0.07, 0, zt - 0.34),
                           t.cube(x1 - 0.06, x1, -0.02, 0.07, 0, zt - 0.34)), "METAL", "METAL", 0.0)
    zb = zt - 0.34 - c
    curtain = tag(t, t.cube(x0 + 0.03, x1 - 0.03, 0.015, 0.035, zb, zt - 0.34), "ROLLER", "NEUTRAL", 0.0)
    bar = tag(t, t.cube(x0 + 0.03, x1 - 0.03, 0.0, 0.05, zb - 0.05, zb), "METAL", "METAL", 0.0)
    show = fcmp(t, c, 0.02)
    return t.join(drum, guides, t.when(show, t.join(curtain, bar)))


def _euler_x(t, a):
    n = t.node("FunctionNodeEulerToRotation")
    t.set(n.inputs[0], t.vec(a, 0.0, 0.0))
    from gnlib import S
    return S(t, n.outputs[0])


def _awning(t, p):
    """1 canvas awning (stripes split for paint, struts), 2 concrete canopy with brackets, 3 sheet-metal lean-to."""
    x0, x1, zt, rch, drop = p.X0, p.X1, p.ZTop, p.Reach, p.Drop
    length = t.math("POWER", rch * rch + drop * drop, 0.5)
    ang = _euler_x(t, t.math("ARCTAN2", drop, rch))
    mid = t.vec((x0 + x1) / 2, -rch / 2, zt - drop / 2)
    slab = t.node("GeometryNodeMeshCube")
    t.set(slab.inputs["Size"], t.vec(x1 - x0, length, 0.018))
    t.set(slab.inputs["Vertices X"], p.Stripes + 1)
    from gnlib import S
    canvas = t.move(S(t, slab.outputs["Mesh"]), mid, ang)
    val = t.node("GeometryNodeMeshCube")
    t.set(val.inputs["Size"], t.vec(x1 - x0, 0.015, 0.24))
    t.set(val.inputs["Vertices X"], p.Stripes + 1)
    valance = t.move(S(t, val.outputs["Mesh"]), t.vec((x0 + x1) / 2, -rch - 0.005, zt - drop - 0.12))
    strut = t.node("GeometryNodeMeshCube")
    t.set(strut.inputs["Size"], t.vec(0.025, length, 0.025))
    struts = t.join(*[t.move(S(t, strut.outputs["Mesh"]), t.vec(xs, -rch / 2, zt - drop / 2 - 0.03), ang)
                      for xs in (x0 + 0.06, x1 - 0.06)])
    cloth = t.join(tag(t, t.join(canvas, valance), "CANVAS", "CANVAS", 0.0), tag(t, struts, "METAL", "METAL", 0.0))
    canopy = t.join(tag(t, t.join(t.cube(x0, x1, -rch, 0.0, zt - 0.12, zt),
                                  t.cube(x0, x1, -rch, -rch + 0.07, zt, zt + 0.1)), "CONCRETE", "WALL"),
                    tag(t, t.join(*[t.cube(xb, xb + 0.14, -rch * 0.55, 0.0, zt - 0.42, zt - 0.12)
                                    for xb in (x0 + 0.08, x1 - 0.22)]), "CONCRETE", "WALL"))
    sheet = t.move(t.cube(-(x1 - x0) / 2, (x1 - x0) / 2, -length / 2, length / 2, -0.006, 0.006), mid, ang)
    lean = t.join(tag(t, sheet, "SHEET", "NEUTRAL", 0.0),
                  tag(t, t.join(struts, t.cube(x0, x1, -rch - 0.03, -rch + 0.01, zt - drop - 0.06, zt - drop)),
                      "METAL", "METAL", 0.0))
    return t.join(t.when(t.cmp(p.Kind, 1), cloth), t.when(t.cmp(p.Kind, 2), canopy), t.when(t.cmp(p.Kind, 3), lean))


def _ac(t, p):
    """Split AC outdoor unit on wall brackets with its fan grille and a condensate pipe."""
    x, z = p.X, p.Z
    case = tag(t, t.cube(x, x + 0.8, -0.34, -0.04, z, z + 0.55), "METAL", "NEUTRAL")
    fan = tag(t, t.cyl(0.19, 0.02, (x + 0.48, -0.345, z + 0.28), "y", t.switch(p.LOD, 12, 8, "INT")), "METAL", "METAL", 0.0)
    brk = tag(t, t.join(*[t.join(t.cube(bx, bx + 0.04, -0.38, 0.0, z - 0.05, z),
                                 t.cube(bx, bx + 0.04, -0.04, 0.0, z - 0.35, z)) for bx in (x + 0.08, x + 0.68)]),
              "METAL", "METAL", 0.0)
    pipe = tag(t, t.cyl(0.012, 0.7, (x + 0.15, -0.1, z - 0.35), "z", 6), "METAL", "GREY", 0.0)
    return t.join(case, fan, brk, t.when(t.bnot(p.LOD), pipe))


def _pipe(t, p):
    """Rainwater downpipe with hopper head, wall clips every 1.5 m and a shoe at the foot."""
    x, z0, z1 = p.X, p.Z0, p.Z1
    pipe = t.cyl(0.05, z1 - z0 - 0.35, (x, -0.09, (z0 + z1) / 2 - 0.05), "z", t.switch(p.LOD, 8, 5, "INT"))
    hopper = t.cube(x - 0.11, x + 0.11, -0.22, 0.0, z1 - 0.25, z1)
    shoe = t.move(t.cube(-0.05, 0.05, -0.2, 0.0, 0.0, 0.1), t.vec(x, -0.05, z0 + 0.12), (-0.5, 0, 0))
    clip = t.cube(x - 0.07, x + 0.07, -0.15, 0.0, -0.02, 0.02)
    clips = t.array(clip, (z1 - z0) / 1.5, (0, 0, 1.5), t.vec(0, 0, z0 + 0.6))
    return tag(t, t.join(pipe, hopper, shoe, t.when(t.bnot(p.LOD), clips)), "METAL", "GREY", 0.0)


def _wiring(t, p):
    """Meter / wiring box with a hinged door edge and cables running up the wall."""
    x, z = p.X, p.Z
    box = t.join(t.cube(x, x + 0.32, -0.15, 0.0, z, z + 0.45), t.cube(x + 0.02, x + 0.3, -0.16, -0.14, z + 0.02, z + 0.43))
    cables = t.join(*[t.cyl(0.011, 2.2, (x + cx, -0.04, z + 0.45 + 1.1), "z", 5) for cx in (0.08, 0.24)],
                    t.when(t.bnot(p.LOD), t.cyl(0.011, 2.2, (x + 0.16, -0.04, z + 0.45 + 1.1), "z", 5)))
    return t.join(tag(t, box, "METAL", "METAL"), tag(t, cables, "METAL", "GREY", 0.0))


def _balcony(t, p):
    """Cantilever balcony: slab with nosing, corbels, square balusters (LOD0) or a grille panel (LOD1), rails."""
    x0, x1, z, r = p.X0, p.X1, p.Z, p.Reach
    slab = tag(t, t.join(t.cube(x0, x1, -r, 0.0, z - 0.15, z),
                         t.cube(x0 - 0.03, x1 + 0.03, -r - 0.03, -r + 0.06, z - 0.18, z - 0.1),
                         *[t.cube(xb, xb + 0.16, -r * 0.6, 0.0, z - 0.45, z - 0.15) for xb in (x0 + 0.1, x1 - 0.26)]),
               "CONCRETE", "WALL")
    rails = tag(t, t.join(t.cube(x0, x1, -r + 0.02, -r + 0.1, z + 0.88, z + 0.95),
                          t.cube(x0, x0 + 0.06, -r + 0.02, 0.0, z + 0.88, z + 0.95),
                          t.cube(x1 - 0.06, x1, -r + 0.02, 0.0, z + 0.88, z + 0.95),
                          t.cube(x0, x1, -r + 0.03, -r + 0.09, z, z + 0.08)), "METAL", "METAL")
    bal = t.cube(-0.018, 0.018, -0.018, 0.018, z + 0.08, z + 0.88)
    balusters = tag(t, t.array(bal, (x1 - x0 - 0.1) / 0.12 + 1, (0.12, 0, 0), t.vec(x0 + 0.05, -r + 0.06, 0)),
                    "METAL", "METAL", 0.0)
    panel = tag(t, t.cube(x0, x1, -r + 0.05, -r + 0.07, z + 0.08, z + 0.88), "METAL", "METAL", 0.0)
    return t.join(slab, rails, t.switch(p.LOD, balusters, panel))


def _sign(t, p):
    """Shop signboard: board on stand-offs inside a painted steel angle frame (sign art goes on the board face)."""
    x0, x1, z0, z1 = p.X0, p.X1, p.Z0, p.Z1
    board = tag(t, t.cube(x0 + 0.04, x1 - 0.04, -0.13, -0.1, z0 + 0.04, z1 - 0.04), "PANEL", "BOARD", 0.0)
    frame = t.boolean(t.cube(x0, x1, -0.15, -0.08, z0, z1), [t.cube(x0 + 0.05, x1 - 0.05, -0.3, 0.1, z0 + 0.05, z1 - 0.05)])
    stand = t.join(*[t.cube(xs, xs + 0.05, -0.08, 0.0, (z0 + z1) / 2 - 0.1, (z0 + z1) / 2 + 0.1) for xs in (x0 + 0.2, x1 - 0.25)])
    return t.join(board, tag(t, t.join(frame, stand), "METAL", "METAL"))


def _spall(t, p):
    """Spall cutter: three overlapping ellipses (an irregular outline) that the piece subtracts from its wall, so
    the brick shows 16 mm deep inside a broken plaster edge (the old proud plate read as a sticker). The pocket
    floor and sides keep this tag: brick in the SPALL row, unpainted (NEUTRAL)."""
    def ell(dx, dz, sx, sz, segs):
        return t.cyl(0.5, 0.066, t.vec(p.X + dx * p.W, -0.017, p.Z + dz * p.H), "y", segs, t.vec(p.W * sx, p.H * sz, 1.0))
    # One closed ellipse per instance (Part 0 main, Part 1 the side lobe, LOD0 only): two overlapping ellipses
    # joined into one cutter self-intersect, and the MANIFOLD boolean then left inverted lids over the pocket.
    main = t.switch(p.LOD, ell(0, 0, 1.0, 1.0, 8), ell(0, 0, 1.05, 1.0, 6))
    cut = t.switch(t.cmp(p.Part, 1), main, t.when(t.bnot(p.LOD), ell(0.3, 0.2, 0.6, 0.65, 6)))
    return tag(t, cut, "SPALL", "NEUTRAL", 0.0)


SPECS = {
    "PI_OpeningCutter": ([("X", float, 0.9), ("Width", float, 1.2), ("Sill", float, 0.85), ("Height", float, 1.8),
                          ("Depth", float, 0.2), ("Arched", bool, False), ("LOD", bool, False)], _cutter),
    "PI_ShutterLeaf": ([("Width", float, 0.6), ("Height", float, 1.8), ("LOD", bool, False), ("Simple", bool, False)],
                       _leaf),
    "PI_Opening": ([("X", float, 0.9), ("Width", float, 1.2), ("Sill", float, 0.85), ("Height", float, 1.8),
                    ("Depth", float, 0.2), ("Arched", bool, False), ("Surround", float, 0.12), ("Ledge", bool, True),
                    ("Hood", int, 0), ("Glazing", int, 1), ("Shutters", int, 0), ("Grille", bool, False),
                    ("LOD", bool, False)], _opening),
    "PI_Roller": ([("X0", float, 0.3), ("X1", float, 2.7), ("ZTop", float, 2.9), ("Curtain", float, 1.2),
                   ("LOD", bool, False)], _roller),
    "PI_Awning": ([("X0", float, 0.15), ("X1", float, 2.85), ("ZTop", float, 2.85), ("Reach", float, 1.0),
                   ("Drop", float, 0.5), ("Kind", int, 1), ("Stripes", int, 6), ("LOD", bool, False)], _awning),
    "PI_AC": ([("X", float, 0.3), ("Z", float, 0.2), ("LOD", bool, False)], _ac),
    "PI_Pipe": ([("X", float, 2.85), ("Z0", float, 0.0), ("Z1", float, 3.2), ("LOD", bool, False)], _pipe),
    "PI_Wiring": ([("X", float, 2.4), ("Z", float, 0.6), ("LOD", bool, False)], _wiring),
    "PI_Balcony": ([("X0", float, 0.15), ("X1", float, 2.85), ("Z", float, 0.15), ("Reach", float, 0.9),
                    ("LOD", bool, False)], _balcony),
    "PI_Sign": ([("X0", float, 0.2), ("X1", float, 2.8), ("Z0", float, 3.0), ("Z1", float, 3.6)], _sign),
    "PI_Spall": ([("X", float, 1.0), ("Z", float, 1.0), ("W", float, 0.6), ("H", float, 0.4), ("LOD", bool, False),
                  ("Part", int, 0)],
                 _spall),
}


def build_groups() -> dict:
    """(Re)create every part group; leaf first (the opening uses it)."""
    for name in ("PI_ShutterLeaf", *[n for n in SPECS if n != "PI_ShutterLeaf"]):
        inputs, fn = SPECS[name]
        G[name] = group(name, inputs, fn)
    return G
