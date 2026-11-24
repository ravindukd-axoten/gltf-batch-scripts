"""Profile-driven sheets, rods and ribs for the shopfront elements (P148), on top of gnlib.

A `sheet` is a Mesh Grid whose vertices are placed by a Python function of (X, s) that builds Math nodes: X runs
along the wall, s from 0 to 1 across the sheet (down the awning slope, down a shutter curtain). That gives curved
awning skins with sag, scalloped valance hems, corrugated sheet and slatted shutter curtains from one grid node
each, never vertex by vertex. Column breaks can be pinned to the canvas stripe bands (kitbuild paints stripes by
face centre in 0.45 m bands starting at x = 0.1 of the finished mesh), so a stripe never splits a face.
"""
from __future__ import annotations

import math

from gnlib import S

STRIPE_W = 0.45
STRIPE_X0 = 0.1   # kitbuild.uv_and_paint: k = floor((cx - 0.1) / 0.45)


def _n(t, kind, **props):
    return t.node(kind, **props)


def m(t, op, a, b=0.0):
    return t.math(op, a, b)


def sin(t, a):
    return m(t, "SINE", a)


def cos(t, a):
    return m(t, "COSINE", a)


def clamp(t, a, lo, hi):
    return m(t, "MINIMUM", m(t, "MAXIMUM", a, lo), hi)


def stripe_cols(x0, x1, xw=0.0, col=STRIPE_W / 2):
    """Grid start, column width and count so column breaks fall on the stripe bands of the finished mesh (the
    piece is placed at x offset `xw`); the first and last columns are clipped to [x0, x1] by `xmap`."""
    phase = (STRIPE_X0 - xw - x0) % col
    xa = x0 + phase - col if phase > 1e-4 else x0
    n = max(1, int(math.ceil((x1 - xa) / col - 1e-6)))
    return xa, col, n


def xmap(t, px, xa, col, x0, x1):
    """Grid x -> wall X: uniform columns from xa, each clipped to [x0, x1] by its two ends (continuous, so the
    sub-columns of a clipped column shrink with it and nothing collapses to zero width)."""
    f = (px - xa) / col
    c = m(t, "FLOOR", f + 1e-5)
    a = clamp(t, xa + c * col, x0, x1)
    b = clamp(t, xa + (c + 1.0) * col, x0, x1)
    return a + (b - a) * (f - c), f - c


def _pos(t):
    sep = _n(t, "ShaderNodeSeparateXYZ")
    t.ng.links.new(_n(t, "GeometryNodeInputPosition").outputs[0], sep.inputs[0])
    return S(t, sep.outputs[0]), S(t, sep.outputs[1]), S(t, sep.outputs[2])


def set_pos(t, geo, x, y, z):
    sp = _n(t, "GeometryNodeSetPosition")
    t.set(sp.inputs["Geometry"], geo)
    t.set(sp.inputs["Position"], t.vec(x, y, z))
    return S(t, sp.outputs["Geometry"])


def sheet(t, xa, col, ncol, nrow, fpos, x0=None, x1=None, sub=1):
    """Grid of `ncol * sub` columns from xa (width col / sub) and `nrow` rows; fpos(X, s, f) -> (x, y, z) where X is
    the clipped wall position, s 0..1 across and f 0..1 inside the stripe column (for scallops)."""
    g = _n(t, "GeometryNodeMeshGrid")
    w = ncol * col
    t.set(g.inputs["Size X"], w)
    t.set(g.inputs["Size Y"], 1.0)
    t.set(g.inputs["Vertices X"], ncol * sub + 1)
    t.set(g.inputs["Vertices Y"], nrow + 1)
    geo = t.move(S(t, g.outputs["Mesh"]), (xa + w / 2, 0.5, 0.0))
    px, py, _ = _pos(t)
    lo = xa if x0 is None else x0
    hi = xa + w if x1 is None else x1
    X, f = xmap(t, px, xa, col, lo, hi)
    return set_pos(t, geo, *fpos(X, py, f))


def solid(t, geo, th):
    """Close a sheet into a thin shell: the sheet flipped plus its extrusion `th` along the face normals."""
    fl = _n(t, "GeometryNodeFlipFaces")
    t.set(fl.inputs["Mesh"], geo)
    ex = _n(t, "GeometryNodeExtrudeMesh", mode="FACES")
    t.set(ex.inputs["Mesh"], geo)
    t.set(ex.inputs["Offset Scale"], th)
    t.set(ex.inputs["Individual"], False)
    return t.join(S(t, fl.outputs["Mesh"]), S(t, ex.outputs["Mesh"]))


def two_sided(t, geo, th):
    """A sheet and its flipped copy `th` below (no edge walls): corrugated sheet that is seen from both sides."""
    fl = _n(t, "GeometryNodeFlipFaces")
    t.set(fl.inputs["Mesh"], t.move(geo, (0.0, 0.0, -th)))
    return t.join(geo, S(t, fl.outputs["Mesh"]))


def _circle(t, r, res):
    c = _n(t, "GeometryNodeCurvePrimitiveCircle")
    t.set(c.inputs["Resolution"], res)
    t.set(c.inputs["Radius"], r)
    return S(t, c.outputs["Curve"])


def _tube(t, curve, r, res):
    c2m = _n(t, "GeometryNodeCurveToMesh")
    t.set(c2m.inputs["Curve"], curve)
    t.set(c2m.inputs["Profile Curve"], _circle(t, r, res))
    c2m.inputs["Fill Caps"].default_value = True
    return S(t, c2m.outputs["Mesh"])


def rod(t, p0, p1, r=0.013, res=6):
    """Round tube from p0 to p1 (frame rails, arms, shackles)."""
    ln = _n(t, "GeometryNodeCurvePrimitiveLine")
    t.set(ln.inputs["Start"], t.vec(*p0))
    t.set(ln.inputs["End"], t.vec(*p1))
    return _tube(t, S(t, ln.outputs["Curve"]), r, res)


def bent_rod(t, fpos, n, r=0.013, res=6):
    """Tube along fpos(s) -> (x, y, z) for s in 0..1, in n segments (an awning arm following its skin)."""
    ln = _n(t, "GeometryNodeCurvePrimitiveLine")
    t.set(ln.inputs["Start"], (0.0, 0.0, 0.0))
    t.set(ln.inputs["End"], (1.0, 0.0, 0.0))
    rs = _n(t, "GeometryNodeResampleCurve")
    t.ng.links.new(ln.outputs["Curve"], rs.inputs["Curve"])
    t.set(rs.inputs["Count"], n + 1)
    px, _, _ = _pos(t)
    return _tube(t, set_pos(t, S(t, rs.outputs["Curve"]), *fpos(px)), r, res)


def wave(t, a, half):
    """0/1 alternating per `half` step of a (corrugation and slat ridges at grid rows or columns on that step)."""
    return m(t, "FLOORED_MODULO", m(t, "ROUND", a / half), 2.0)
