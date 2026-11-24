"""Frontage elements FE_* (P143): every inventory FE_ row as a parametric piece from the P96 part groups.

Each element is the stand-alone version of a part the kit pieces already place (parts.py PI_* groups, pieces.py
helpers), with its own pivot so the city pipeline (or a hand-dressed hero) can drop it onto any wall: x along the
wall from the element's left edge, street on -y, wall face y = 0 (inserts such as doors sit inside the reveal at
y > 0), z up from the element's foot. One material (MAT_FrontageTrim_A, light/worn swap) except the two elements
whose face takes its own picture (lit sign face, painted shutter name: MAT_SignGlow_A, MAT_ShutterName_A).
Numbers are the FRONTAGE_KIT_SPEC.md 1 estimates (gf_21, gf_24, gf_25, sv_04, style frame), +-20 %.
"""
from __future__ import annotations

import pieces
import shopfront
from parts import G, tag
from pieces import _op

REFS_COL = ["gf_21", "gf_24", "sv_04"]
REFS_SHOP = ["style frame dff6fe56", "Cityhub shophouses (agent photos needed)"]


def _use(t, p, kind, **vals):
    return t.use(G[kind], **vals, LOD=p.LOD)


def opening(**o):
    """PI_Opening as a stand-alone insert. LOD1 keeps a plain drip strip under the sill (the part drops it), so both
    LODs share the base line (pivot rule) and the sill shadow does not pop."""
    def body(t, p):
        geo = _use(t, p, "PI_Opening", **o)
        if not o.get("Ledge"):
            return geo
        x, w, s, z0 = o["X"], o["Width"], o["Surround"], o["Sill"]
        drip = tag(t, t.cube(x - s - 0.03, x + w + s + 0.03, -0.075, 0.0, z0 - 0.14, z0 - 0.07), "CONCRETE", "ACCENT", 0.0)
        return t.join(geo, t.when(p.LOD, drip))
    return body


def fanlight(t, p):
    """Arched fanlight alone: the full arched opening clipped at its springing line (no lower half-disc)."""
    geo = _use(t, p, "PI_Opening", X=0.1, Width=1.7, Sill=-0.95, Height=1.87, Depth=0.3, Arched=True, Surround=0.1,
               Ledge=False, Hood=0, Glazing=1, Shutters=0, Grille=False)
    sill = tag(t, t.cube(0.0, 1.9, -0.06, 0.3, 0.0, 0.06), "FRAME", "ACCENT")
    return t.join(t.boolean(geo, [t.cube(-1.0, 3.0, -1.0, 1.0, -2.0, 0.06)]), sill)


def louvre_leaf(t, p, w=0.55, h=1.8):
    """Louvred leaf with a middle rail and two louvre panels (each fits the 1.2 m LOUVRE row unscaled)."""
    ring = t.boolean(t.cube(0, w, 0, 0.035, 0, h), [t.cube(0.055, w - 0.055, -0.1, 0.2, 0.055, h - 0.055)])
    mid = h * 0.5
    rail = t.cube(0.055, w - 0.055, 0.0, 0.035, mid - 0.04, mid + 0.04)
    panels = t.join(t.cube(0.055, w - 0.055, 0.02, 0.03, 0.055, mid - 0.04), t.cube(0.055, w - 0.055, 0.02, 0.03, mid + 0.04, h - 0.055))
    blade = t.move(t.cube(0.055, w - 0.055, -0.016, 0.016, -0.005, 0.005), (0, 0, 0), (0.55, 0, 0))
    n = int((mid - 0.13) / 0.075)
    blades = t.join(t.array(blade, n, (0, 0, 0.075), (0, 0.018, 0.1)), t.array(blade, n, (0, 0, 0.075), (0, 0.018, mid + 0.08)))
    return t.join(tag(t, t.join(ring, rail), "PANEL", "TIMBER", 0.0), tag(t, panels, "LOUVRE", "TIMBER", 0.0),
                  t.when(t.bnot(p.LOD), tag(t, blades, "PANEL", "TIMBER", 0.0)))


def downpipe(t, p, z1=3.2):
    """Downpipe in 0.75 m lengths with socket collars (each length fits the METAL row unscaled), hopper, clips, shoe."""
    x = 0.11
    seg = t.cyl(0.05, 0.75, (x, -0.09, 0.375), "z", t.switch(p.LOD, 8, 5, "INT"))
    n = int((z1 - 0.45) / 0.75) + 1
    pipe = t.array(seg, n, (0, 0, 0.75), (0, 0, 0.1))
    collars = t.array(t.cyl(0.058, 0.07, (x, -0.09, 0.0), "z", 8), n - 1, (0, 0, 0.75), (0, 0, 0.85))
    hopper = t.cube(x - 0.11, x + 0.11, -0.22, 0.0, z1 - 0.25, z1)
    shoe = t.move(t.cube(-0.05, 0.05, -0.2, 0.0, 0.0, 0.1), (x, -0.05, 0.02), (-0.5, 0, 0))
    clips = t.array(t.cube(x - 0.07, x + 0.07, -0.15, 0.0, -0.02, 0.02), 2, (0, 0, 1.5), (0, 0, 0.9))
    return tag(t, t.join(pipe, hopper, shoe, t.when(t.bnot(p.LOD), t.join(collars, clips))), "METAL", "GREY", 0.0)


def lean_to(t, p):
    return shopfront.lean_to(t, p)


def ac_unit(t, p):
    """PI_AC on its brackets; LOD1 keeps a 4-sided condensate pipe so both LODs share the base line."""
    ac = _use(t, p, "PI_AC", X=0.0, Z=0.7)
    return t.join(ac, t.when(p.LOD, tag(t, t.cyl(0.012, 0.7, (0.15, -0.1, 0.35), "z", 4), "METAL", "GREY", 0.0)))


def roller(curtain, x1=2.4, **kw):
    """shopfront.roller_shutter: slatted curtain, sheet-metal hood, guides, bottom bar, handles, padlocks."""
    def body(t, p):
        return shopfront.roller_shutter(t, p, x1=x1, zt=2.9, curtain=curtain, **kw)
    return body


def wicket(t, p):
    """Shut roller shutter with a hinged wicket door cut into the curtain (frame, leaf, hinge straps, padlock hasp)."""
    out = [roller(2.5, locks="none", handles=1)(t, p)]
    frame = t.boolean(t.cube(0.78, 1.62, -0.012, 0.016, 0.06, 1.95), [t.cube(0.83, 1.57, -0.1, 0.1, 0.11, 1.9)])
    leaf = t.cube(0.84, 1.56, -0.004, 0.014, 0.12, 1.89)
    straps = t.join(*[t.cube(0.84, 1.14, -0.012, -0.004, z, z + 0.05) for z in (0.35, 1.6)])
    hasp = t.join(t.cube(1.44, 1.52, -0.03, -0.004, 1.0, 1.14), t.cube(1.47, 1.49, -0.05, -0.03, 0.95, 1.02))
    out += [tag(t, frame, "METAL", "METAL"), tag(t, leaf, "ROLLER", "NEUTRAL", 0.0),
            tag(t, t.join(straps, t.when(t.bnot(p.LOD), hasp)), "METAL", "GREY", 0.0)]
    return t.join(*out)


def glazed_door(t, p):
    """Glazed shop double door with transom light, kick plates and pull bars, in a slim metal frame."""
    door = _use(t, p, "PI_Opening", X=0.05, Width=1.5, Sill=0.0, Height=2.6, Depth=0.12, Arched=False, Surround=0.05,
                Ledge=False, Hood=0, Glazing=1, Shutters=0, Grille=False)
    kick = t.join(*[t.cube(x, x + 0.7, 0.02, 0.035, 0.02, 0.28) for x in (0.08, 0.82)])
    bars = t.join(*[t.cube(x, x + 0.03, -0.05, 0.02, 0.8, 1.5) for x in (0.7, 0.87)])
    return t.join(door, tag(t, kick, "METAL", "METAL", 0.0), t.when(t.bnot(p.LOD), tag(t, bars, "METAL", "METAL", 0.0)))


def grilled_gate(t, p):
    """Collapsible steel shop gate: square bars at 0.2 m (LOD1 0.3), two lattice rails, top and floor tracks, lock box."""
    # separate bar and rail boxes (not the PI_Opening grille, which welds into one 2.4 x 2.5 m UV island)
    # dark shop-interior card in two lifts (fits the 1.2 m glass row) and steel channel jambs
    void = t.join(t.cube(0.06, 2.46, 0.3, 0.32, 0.0, 1.25), t.cube(0.06, 2.46, 0.3, 0.32, 1.25, 2.5))
    jambs = t.join(t.cube(0.0, 0.06, -0.08, 0.3, 0.0, 2.5), t.cube(2.46, 2.52, -0.08, 0.3, 0.0, 2.5))
    g = t.join(tag(t, void, "GLASS", "NEUTRAL", 0.0), tag(t, jambs, "METAL", "GREY", 0.0))
    pitch = t.switch(p.LOD, 0.2, 0.3, "FLOAT")
    bar = t.cube(-0.01, 0.01, -0.06, -0.04, 0.03, 2.5)
    bars = t.array(bar, 2.4 / pitch, t.vec(pitch, 0, 0), t.vec(0.06 + pitch / 2, 0, 0))
    rails = t.join(*[t.cube(0.06, 2.46, -0.075, -0.06, z, z + 0.05) for z in (0.8, 1.7)])
    tracks = t.join(t.cube(0.0, 2.52, -0.08, 0.0, 2.5, 2.58), t.cube(0.0, 2.52, -0.08, 0.0, 0.0, 0.03))
    lock = t.cube(1.18, 1.34, -0.1, -0.075, 1.0, 1.2)
    return t.join(g, tag(t, t.join(bars, rails, tracks, lock), "METAL", "METAL", 0.0))


def leaf(pair):
    def body(t, p):
        lf = louvre_leaf(t, p)
        hinges = tag(t, t.join(*[t.cube(-0.03, 0.0, 0.0, 0.03, z, z + 0.06) for z in (0.25, 1.5)]), "METAL", "GREY", 0.0)
        one = t.join(t.move(lf, (0.03, 0, 0)), hinges)
        return t.join(one, t.move(one, (1.17, 0, 0), (0, 0, 0), (-1, 1, 1))) if pair else one
    return body


def sill_hood(t, p):
    """Window head and sill set (no glass): moulded hood with a drip, projecting sill ledge with its drip course."""
    w, s, h = 1.2, 0.1, 1.8
    x0, z0, top = 0.15, 0.14, 0.14 + 1.8
    ledge = t.join(t.cube(x0 - s - 0.08, x0 + w + s + 0.08, -0.11, 0.02, z0 - 0.07, z0),
                   t.cube(x0 - s - 0.03, x0 + w + s + 0.03, -0.075, 0.0, z0 - 0.14, z0 - 0.07))
    hood = t.join(t.when(t.bnot(p.LOD), t.cube(x0 - s - 0.05, x0 + w + s + 0.05, -0.07, 0.01, top + s, top + s + 0.08)),
                  t.cube(x0 - s - 0.14, x0 + w + s + 0.14, -0.14, 0.01, top + s + 0.08, top + s + 0.17),
                  t.when(t.bnot(p.LOD), t.cube(x0 - s - 0.1, x0 + w + s + 0.1, -0.1, 0.01, top + s + 0.17, top + s + 0.22)))
    jambs = t.join(t.cube(x0 - s, x0, -0.045, 0.02, z0, top), t.cube(x0 + w, x0 + w + s, -0.045, 0.02, z0, top),
                   t.cube(x0 - s, x0 + w + s, -0.045, 0.02, top, top + s))
    return t.join(tag(t, ledge, "CONCRETE", "ACCENT"), tag(t, hood, "FRAME", "ACCENT"), tag(t, jambs, "FRAME", "ACCENT"))


def sunshade(t, p):
    """Concrete window sunshade (chajja) 0.6 m deep with side fins and a drip lip; same paint as the wall."""
    w = 2.0
    return tag(t, t.join(t.cube(0.0, w, -0.6, 0.0, 0.3, 0.38), t.cube(0.0, w, -0.6, -0.54, 0.23, 0.38),
                         t.cube(0.0, 0.06, -0.6, 0.0, 0.0, 0.3), t.cube(w - 0.06, w, -0.6, 0.0, 0.0, 0.3),
                         t.when(t.bnot(p.LOD), t.cube(0.06, w - 0.06, -0.62, -0.6, 0.2, 0.24))), "CONCRETE", "WALL")


def strip_window(t, p):
    win = _use(t, p, "PI_Opening", X=0.15, Width=2.5, Sill=0.18, Height=1.25, Depth=0.22, Arched=False, Surround=0.0,
               Ledge=False, Hood=0, Glazing=2, Shutters=0, Grille=False)
    ring = t.boolean(t.cube(0.0, 2.8, -0.32, 0.02, 0.0, 1.6), [t.cube(0.15, 2.65, -0.5, 0.1, 0.18, 1.43)])
    return t.join(win, tag(t, ring, "CONCRETE", "WALL"))


def balcony(x1, reach):
    def body(t, p):
        return _use(t, p, "PI_Balcony", X0=0.0, X1=x1, Z=0.45, Reach=reach)
    return body


def awning(kind, stripes, ztop, reach, drop, x1=2.7, profile="lean", valance="straight", xw=0.0):
    """Canvas awning (kind 1: shopfront.canvas_awning, profile lean | dutch | box, valance straight | scallop) or
    the P96 PI_Awning (2 concrete canopy). `xw` is where the piece lands in its building (stripe columns)."""
    def body(t, p):
        if kind != 1:
            return _use(t, p, "PI_Awning", X0=0.0, X1=x1, ZTop=ztop, Reach=reach, Drop=drop, Kind=kind, Stripes=stripes)
        return shopfront.canvas_awning(t, p, x1, ztop, reach, drop, profile, valance, xw)
    return body


def pilasters(t, p):
    top = 3.04
    out = []
    for x in (0.04, 2.61):
        out.append(tag(t, t.cube(x, x + 0.35, -0.08, 0.01, 0, top, (2, 2, 4)), "WALL", "ACCENT", 0.0))   # plastered shaft
        out.append(tag(t, t.join(t.cube(x - 0.04, x + 0.39, -0.12, 0.01, 0, 0.3),
                          t.when(t.bnot(p.LOD), t.cube(x - 0.02, x + 0.37, -0.1, 0.01, 0.3, 0.38)),
                          t.cube(x - 0.04, x + 0.39, -0.13, 0.01, top - 0.22, top),
                          t.when(t.bnot(p.LOD), t.cube(x - 0.07, x + 0.42, -0.16, 0.01, top - 0.08, top))), "FRAME", "ACCENT"))
    return t.join(*out)


def string_course(big):
    return lambda t, p: pieces._string(t, 0.0, big=big, p=p)


def roof_stubs(t, p):
    """Plain parapet (P96 Parapet D) plus a column stub with rebar starters: the waiting-for-the-next-floor roof."""
    base = pieces._parapet("D")(t, p)
    stub = tag(t, t.cube(1.35, 1.65, 0.0, 0.3, 0.92, 1.3), "CONCRETE", "WALL")
    bars = tag(t, t.join(*[t.cyl(0.008, 0.7, (x, y, 1.65), "z", 4) for x in (1.4, 1.6) for y in (0.05, 0.25)]),
               "METAL", "GREY", 0.0)
    return t.join(base, stub, t.when(t.bnot(p.LOD), bars))


def spall_patch(t, p):
    """Patched render skin (32 mm proud) with a spalled pocket to the brick: placed over any plain wall."""
    skin = tag(t, t.cube(0.0, 1.4, -0.032, 0.0, 0.0, 1.1, (3, 2, 3)), "WALL", "WALL", 0.0)
    cut = [t.move(c, (0, -0.034, 0)) for c in pieces.spall_cut(t, p, X=0.7, Z=0.55, W=0.85, H=0.62)]
    edge = tag(t, t.join(t.cube(0.0, 1.4, -0.036, -0.03, 1.08, 1.1), t.cube(0.0, 1.4, -0.036, -0.03, 0.0, 0.02)),
               "FRAME", "ACCENT", 0.0)
    return t.join(t.boolean(skin, cut), edge)


def vent(breeze):
    def body(t, p):
        if not breeze:   # louvred steel wall vent 0.45 x 0.3: frame and four blades
            frame = t.boolean(t.cube(0, 0.45, -0.04, 0.0, 0, 0.3), [t.cube(0.04, 0.41, -0.2, 0.1, 0.04, 0.26)])
            blade = t.move(t.cube(0.04, 0.41, -0.012, 0.012, -0.004, 0.004), (0, -0.02, 0), (0.6, 0, 0))
            blades = t.array(blade, 4, (0, 0, 0.055), (0, 0, 0.065))
            back = t.cube(0.04, 0.41, 0.0, 0.01, 0.04, 0.26)
            return t.join(tag(t, t.join(frame, blades), "METAL", "METAL", 0.0), tag(t, back, "REVEAL", "WALL", 0.0))
        # concrete breeze-block vent panel 0.9 x 0.6 (3 x 2 blocks, each with a square-in-diamond pierce)
        panel = t.cube(0, 0.9, -0.03, 0.12, 0, 0.6)
        hole = t.cube(-0.075, 0.075, -0.2, 0.3, -0.075, 0.075)
        holes = t.array(t.array(t.move(hole, (0, 0, 0), (0, 0.785, 0)), 3, (0.3, 0, 0), (0.15, 0, 0.15)), 2,
                        (0, 0, 0.3))
        return tag(t, t.boolean(panel, [holes]), "CONCRETE", "WALL", 0.0)
    return body


def shop_glass(t, p):
    """Shop window with depth: glass pane, two shelves with goods blocks and the painted interior card 0.6 m behind."""
    w, h = 2.4, 2.2
    # pane and card in two 1.1 m lifts with a transom bar: each fits the 1.2 m glass row unscaled
    pane = tag(t, t.join(t.cube(0, w, 0.0, 0.01, 0.0, 1.08), t.cube(0, w, 0.0, 0.01, 1.12, h)), "GLASS", "NEUTRAL", 0.0)
    card = tag(t, t.join(t.cube(0, w, 0.6, 0.62, 0.0, 1.1), t.cube(0, w, 0.6, 0.62, 1.1, h)), "GLASS", "NEUTRAL", 0.0)
    pane = t.join(pane, tag(t, t.cube(0, w, -0.02, 0.03, 1.07, 1.13), "METAL", "METAL", 0.0))
    shelves = t.join(*[t.cube(0.05, w - 0.05, 0.1, 0.55, z, z + 0.03) for z in (0.6, 1.3)])
    goods = t.join(*[t.cube(x, x + 0.22, 0.3, 0.5, z + 0.03, z + 0.03 + hh) for z in (0.6, 1.3)
                     for x, hh in ((0.2, 0.3), (0.6, 0.22), (1.05, 0.34), (1.5, 0.18), (1.9, 0.28))])
    return t.join(pane, card, tag(t, shelves, "METAL", "METAL", 0.0), t.when(t.bnot(p.LOD), tag(t, goods, "PANEL", "BOARD", 0.0)))


def security_grille(t, p):
    w, h = 1.4, 1.6
    bar = t.cube(-0.009, 0.009, -0.045, -0.027, 0.0, h)
    pitch = t.switch(p.LOD, 0.2, 0.3, "FLOAT")
    bars = t.array(bar, w / pitch, t.vec(pitch, 0, 0), t.vec(pitch / 2, 0, 0))
    flats = t.join(t.cube(0, w, -0.05, -0.022, 0.3, 0.34), t.cube(0, w, -0.05, -0.022, h - 0.34, h - 0.3),
                   t.cube(0, w, -0.05, -0.022, 0.0, 0.04), t.cube(0, w, -0.05, -0.022, h - 0.04, h))
    lugs = t.join(*[t.cube(x, x + 0.06, -0.03, 0.0, z, z + 0.04) for x in (0.0, w - 0.06) for z in (0.3, h - 0.34)])
    return tag(t, t.join(bars, flats, t.when(t.bnot(p.LOD), lugs)), "METAL", "METAL", 0.0)


def threshold(t, p):
    """Shop threshold: two terrazzo steps with nosings and a cheek wall (shop floors sit 0.3 m above the pavement)."""
    steps = t.join(t.cube(0, 2.4, -0.6, 0.0, 0.0, 0.15), t.cube(0, 2.4, -0.3, 0.0, 0.15, 0.3))
    nos = t.join(t.cube(0, 2.4, -0.62, -0.58, 0.13, 0.15), t.cube(0, 2.4, -0.32, -0.28, 0.28, 0.3))
    cheek = t.cube(2.4, 2.55, -0.6, 0.0, 0.0, 0.34)
    return t.join(tag(t, steps, "PLINTH", "GREY", 0.0), tag(t, t.join(t.when(t.bnot(p.LOD), nos), cheek), "CONCRETE", "WALL"))


def curtain(t, p):
    """Window curtain behind the glass: two drapes of pleats (alternating set-back boxes) on a rod with tie-backs."""
    pleat = t.cube(0.0, 0.09, 0.0, 0.025, 0.0, 1.7)
    front = t.array(pleat, 5, (0.16, 0, 0))
    back = t.array(t.move(pleat, (0.08, 0.05, 0.03)), 5, (0.16, 0, 0))
    drape = t.join(front, t.when(t.bnot(p.LOD), back))
    drapes = t.join(drape, t.move(drape, (0.62, 0, 0)))
    rod = t.cyl(0.012, 1.5, (0.75, 0.0, 1.78), "x", 6)
    return t.join(tag(t, drapes, "CANVAS", "CANVAS", 0.0), tag(t, rod, "METAL", "GREY", 0.0))


def boundary(gate):
    def body(t, p):
        if not gate:   # 3 m compound wall 2.1 m with coping, an end pier and a row of steel spikes
            wall = tag(t, t.cube(0, 3.0, 0.0, 0.23, 0.0, 2.1, (4, 2, 3)), "WALL", "WALL", 0.0)
            cope = tag(t, t.cube(-0.02, 3.0, -0.04, 0.27, 2.1, 2.18), "CONCRETE", "ACCENT")
            pier = tag(t, t.join(t.cube(2.6, 3.0, -0.08, 0.31, 0.0, 2.35), t.cube(2.56, 3.04, -0.12, 0.35, 2.35, 2.43)),
                       "WALL", "WALL")
            plinth = tag(t, t.cube(0, 2.6, -0.03, 0.0, 0.0, 0.3), "PLINTH", "GREY", 0.0)
            spike = t.node("GeometryNodeMeshCone")
            t.set(spike.inputs["Vertices"], 4)
            t.set(spike.inputs["Radius Bottom"], 0.018)
            t.set(spike.inputs["Depth"], 0.24)
            from gnlib import S
            sp = t.move(S(t, spike.outputs["Mesh"]), (0, 0.115, 2.3))
            spikes = t.array(sp, t.switch(p.LOD, 13, 6, "INT"), t.vec(t.switch(p.LOD, 0.2, 0.42, "FLOAT"), 0, 0),
                             (0.1, 0, 0))
            rail = t.cube(0.0, 2.6, 0.1, 0.13, 2.18, 2.21)
            return t.join(wall, cope, pier, plinth, tag(t, t.join(spikes, rail), "METAL", "METAL", 0.0))
        # sliding steel gate 3.0 x 2.0 on a floor track: frame, vertical bars, a sheet panel at the foot
        frame = t.boolean(t.cube(0, 3.0, -0.05, 0.0, 0.05, 2.0), [t.cube(0.06, 2.94, -0.2, 0.1, 0.11, 1.94)])
        bars = t.array(t.cube(-0.01, 0.01, -0.04, -0.01, 0.11, 1.94), t.switch(p.LOD, 19, 10, "INT"),
                       t.vec(t.switch(p.LOD, 0.15, 0.3, "FLOAT"), 0, 0), (0.15, 0, 0))
        sheet = t.cube(0.06, 2.94, -0.035, -0.025, 0.11, 0.7)
        track = t.join(t.cube(-0.5, 3.0, -0.06, 0.01, 0.0, 0.03), *[t.cyl(0.04, 0.03, (x, -0.025, 0.06), "y", 8)
                                                                    for x in (0.3, 2.7)])
        return t.join(tag(t, t.join(frame, bars, track), "METAL", "METAL", 0.0), tag(t, sheet, "SHEET", "NEUTRAL", 0.0))
    return body


def neon_sign(flex):
    def body(t, p):
        if not flex:   # lit box sign 2.4 x 0.6: steel box, glowing face (MAT_SignGlow_A), LED rim on LOD0
            box = tag(t, t.cube(0, 2.4, -0.18, -0.02, 0, 0.6), "METAL", "METAL")
            face = t.store(tag(t, t.cube(0.05, 2.35, -0.19, -0.18, 0.05, 0.55), "PANEL", "BOARD", 0.0), "mat2", 1, "INT", "FACE")
            rim = t.store(tag(t, t.join(t.cube(0.0, 2.4, -0.2, -0.18, 0.0, 0.03), t.cube(0.0, 2.4, -0.2, -0.18, 0.57, 0.6)),
                              "METAL", "BOARD", 0.0), "mat2", 1, "INT", "FACE")
            arms = tag(t, t.join(*[t.cube(x, x + 0.04, -0.02, 0.0, 0.2, 0.4) for x in (0.3, 2.06)]), "METAL", "GREY", 0.0)
            return t.join(box, face, t.when(t.bnot(p.LOD), rim), arms)
        # flex banner 3.0 x 0.9 on a pipe frame with tie points (the banner face takes the sign picture)
        pipes = t.join(t.cyl(0.02, 3.1, (1.5, -0.12, 0.92), "x", 6), t.cyl(0.02, 3.1, (1.5, -0.12, 0.0), "x", 6),
                       *[t.cube(x, x + 0.04, -0.12, 0.0, 0.42, 0.5) for x in (0.1, 2.86)])
        flexs = tag(t, t.cube(0.02, 2.98, -0.125, -0.115, 0.02, 0.9, (5, 2, 2)), "PANEL", "BOARD", 0.0)   # art via signage decals
        return t.join(tag(t, pipes, "METAL", "GREY", 0.0), flexs)
    return body


def painted_shutter(t, p):
    """Shut roller shutter with the painted shop-name panel (own 0-1 UV, MAT_ShutterName_A; the lettering is a
    texture from names.json written by native writers, not drawn here)."""
    sh = roller(2.5, role="BOARD", locks="shut")(t, p)
    name = t.store(tag(t, t.cube(0.15, 2.25, -0.004, 0.004, 1.15, 2.05), "ROLLER", "BOARD", 0.0), "mat2", 1, "INT", "FACE")
    return t.join(sh, name)


def window_twin(shut):
    def body(t, p):
        ops = [_op(0.18, 0.9, 0.14, 1.5, s=0.1, hood=3, shutters=2 if shut else 1),
               _op(1.75, 0.9, 0.14, 1.5, s=0.1, hood=3, shutters=2 if shut else 1)]
        return t.join(*[opening(**o)(t, p) for o in ops])
    return body


def E(row, name, body, h=3.2, v="A", refs=REFS_COL, **kw):
    return dict(row=row, name=f"KIT_FE_{name}", body=body, h=h, variant=v, refs=refs, **kw)


def catalogue():
    a = REFS_COL
    s = REFS_SHOP
    return [
        E("FE_Door_ArchedTimberPanelled", "Door_ArchedTimberPanelled_A",
          opening(**_op(0.24, 1.7, 0.0, 3.45, d=0.3, arched=True, s=0.16, ledge=False, hood=1, glazing=3)), h=4.5),
        E("FE_Door_ArchedTimberPanelled", "Door_ArchedTimberPanelled_B",
          opening(**_op(0.24, 1.7, 0.0, 3.3, d=0.3, arched=True, s=0.16, ledge=False, hood=0, glazing=3)), h=4.5, v="B"),
        E("FE_Fanlight_Arched", "Fanlight_Arched_A", fanlight),
        E("FE_Door_Wicket", "Door_Wicket_A", wicket, h=4.0, refs=s),
        E("FE_Door_GlazedShop", "Door_GlazedShop_A", glazed_door, h=4.0, v="C", refs=s),
        E("FE_RollerShutter", "RollerShutter_A", roller(1.2, locks="open"), h=4.0, refs=s),
        E("FE_RollerShutter", "RollerShutter_B", roller(2.5, x1=3.0, hood="round", role="BOARD"), h=4.0, v="D",
          refs=s),
        E("FE_RollerShutter", "RollerShutter_C", roller(0.15, role="BOARD", locks="open", handles=1), h=4.0, v="C",
          refs=s),
        E("FE_GrilledGate", "GrilledGate_A", grilled_gate, h=4.0, refs=s),
        E("FE_Window_TallArched", "Window_TallArched_A", opening(**_op(0.2, 1.2, 0.14, 2.05, arched=True, hood=1,
                                                                        shutters=1))),
        E("FE_Window_TallArched", "Window_TallArched_B", opening(**_op(0.2, 1.2, 0.14, 2.05, arched=True, hood=0,
                                                                        shutters=2)), v="B"),
        E("FE_Window_TwinFlatHead", "Window_TwinFlatHead_A", window_twin(True), v="B"),
        E("FE_Window_TwinFlatHead", "Window_TwinFlatHead_B", window_twin(False)),
        E("FE_Window_Strip", "Window_Strip_A", strip_window, v="C", refs=s),
        E("FE_Window_Grilled", "Window_Grilled_A", opening(**_op(0.14, 1.6, 0.14, 1.4, s=0.06, grille=True)), v="D", refs=s),
        E("FE_ShutterLeaf_Louvred", "ShutterLeaf_Louvred_A", leaf(False)),
        E("FE_ShutterLeaf_Louvred", "ShutterLeaf_Louvred_B", leaf(True), v="B"),
        E("FE_Sill_Lintel_Hood", "Sill_Lintel_Hood_A", sill_hood),
        E("FE_Sunshade_Concrete", "Sunshade_Concrete_A", sunshade, v="C", refs=s),
        E("FE_Balconette_Rail", "Balconette_Rail_A", balcony(1.9, 0.38)),
        E("FE_Balcony_SlabRail", "Balcony_SlabRail_A", balcony(2.76, 0.9), refs=s),
        E("FE_Awning_CanvasStriped", "Awning_CanvasStriped_A", awning(1, 6, 0.95, 0.7, 0.85, profile="dutch", valance="scallop"),
          refs=s, stripes=("orange", "cream")),
        E("FE_Awning_CanvasStriped", "Awning_CanvasStriped_B", awning(1, 6, 0.75, 0.85, 0.5, profile="box", valance="scallop"),
          refs=s, stripes=("green", "cream")),
        E("FE_Awning_CanvasPlain", "Awning_CanvasPlain_A", awning(1, 1, 0.8, 0.9, 0.55, profile="lean"), refs=["gf_24"] + s,
          stripes=("green",)),
        E("FE_Awning_SheetMetalLeanTo", "Awning_SheetMetalLeanTo_A", lean_to, refs=s),
        E("FE_Canopy_Concrete", "Canopy_Concrete_A", awning(2, 1, 0.42, 0.9, 0.0, x1=3.0), refs=s),
        E("FE_ACUnit_Bracket", "ACUnit_Bracket_A", ac_unit, refs=s),
        E("FE_Drainpipe", "Drainpipe_A", downpipe, refs=["gf_24"]),
        E("FE_WiringMeterBox", "WiringMeterBox_A", lambda t, p: _use(t, p, "PI_Wiring", X=0.0, Z=0.0), refs=s),
        E("FE_Signboard_Frame", "Signboard_Frame_A", lambda t, p: t.use(G["PI_Sign"], X0=0.0, X1=2.4, Z0=0.0, Z1=0.7),
          refs=s),
        E("FE_Pilaster_Pair", "Pilaster_Pair_A", pilasters, refs=["gf_24", "sv_04"]),
        E("FE_RusticatedPier_Plinth", "RusticatedPier_Plinth_A", pieces._corner(4.5), h=4.5, refs=["gf_25"]),
        E("FE_StringCourse_Cornice", "StringCourse_Cornice_A", string_course(False), refs=["gf_24", "sv_04"]),
        E("FE_StringCourse_Cornice", "StringCourse_Cornice_B", string_course(True), refs=["sv_04", "gf_25"]),
        E("FE_Parapet_Balustrade", "Parapet_Balustrade_A", pieces._parapet("C"), h=0.9, refs=["sv_04", "gf_25"]),
        E("FE_Parapet_DatePlaque", "Parapet_DatePlaque_A", pieces._parapet("B"), h=0.9, refs=["sv_04"]),
        E("FE_RoofStubs_Rebar", "RoofStubs_Rebar_A", roof_stubs, h=0.9, refs=s, worn_only=True),
        E("FE_SpallPatch_Brick", "SpallPatch_Brick_A", spall_patch, h=1.1, refs=["gf_21", "sv_04"], worn_only=True),
        E("FE_WallVent", "WallVent_A", vent(False), h=0.3, refs=s),
        E("FE_WallVent", "WallVent_B", vent(True), h=0.6, v="C", refs=s),
        E("FE_ShopGlass_InteriorCard", "ShopGlass_InteriorCard_A", shop_glass, refs=s),
        E("FE_SecurityGrille_Window", "SecurityGrille_Window_A", security_grille, refs=s),
        E("FE_ShopThreshold_Step", "ShopThreshold_Step_A", threshold, h=0.34, v="C", refs=s),
        E("FE_Curtain_Window", "Curtain_Window_A", curtain, refs=s, stripes=("cream",)),
        E("FE_BoundaryWall_Spikes", "BoundaryWall_Spikes_A", boundary(False), h=2.4, refs=["gf_23", "gf_25"]),
        E("FE_BoundaryWall_Spikes", "BoundaryWall_Gate_B", boundary(True), h=2.0, refs=["gf_23"]),
        E("FE_ShopSign_NeonLED", "ShopSign_LightBox_A", neon_sign(False), h=0.6, refs=s, mat2="MAT_SignGlow_A"),
        E("FE_ShopSign_NeonLED", "ShopSign_FlexBanner_B", neon_sign(True), h=0.9, refs=s),
        E("FE_HandPaintedShutterName", "HandPaintedShutterName_A", painted_shutter, h=4.0, refs=s,
          mat2="MAT_ShutterName_A"),
    ]
