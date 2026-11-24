"""PI_GN_HipRoof: hipped tile roofs with Dutch gablets, fascia and soffit (TDD "Blender asset methods").

Replaces the old vertex-by-vertex `hero_geom.hip_roof`. Python only lays out the eave rectangles
(`hero_bays.RoofRect`, overhang included); the node group builds every roof of a hero in one pass:

1. each input quad (the eave rectangle, at eave height) drops by the fascia depth and is extruded back up by it
   (the fascia band); a flipped copy at the bottom is the soffit;
2. the eave face is extruded up to the gablet foot and scaled about its centre: across the ridge to the gablet
   width (0 for a plain hip), along it to the ridge length (the hip slopes);
3. faces with a gablet are extruded up to the ridge and scaled to zero across it: the long sides continue the
   slopes, the short ends are the vertical gablet triangles;
4. zero-area tops are deleted and coincident ridge vertices merged.

Per-vertex attributes on the input quads (written by `roofs_object`): `pt` tan(pitch), `gf` gablet fraction,
`fa` fascia depth, `wd`/`ln` short/long side, `ze` eave height, `la`/`sa` long/short axis (unit vectors).
Faces are sorted by normal: slopes get the roof material (tiles along the eave, up the slope, real scale),
vertical faces at the eave the trim cornice row (fascia), vertical faces above it plaster (gablets), and
downward faces the trim reveal row (soffit).
"""
from __future__ import annotations

import math

import bpy

from .. import hero_bays as HB
from .. import materials as M
from .facade import PLASTER_TILE, _to_world, finish_mesh, store_uv
from .nodes import Tree

ROOF_TILE_M = M.tile(M.ROOF_TILE)


def _extrude(t: Tree, geo, sel, offset):
    node = t.n("GeometryNodeExtrudeMesh", {"Mesh": geo, "Selection": sel, "Offset": offset, "Individual": True}, mode="FACES")
    return node.outputs["Mesh"], node.outputs["Top"], node.outputs["Side"]


def _scale(t: Tree, geo, sel, factor, axis):
    node = t.n("GeometryNodeScaleElements", {"Geometry": geo, "Selection": sel, "Scale": factor, "Axis": axis}, domain="FACE")
    node.inputs["Scale Mode"].default_value = "Single Axis"
    return t.o(node)


def roof_group() -> bpy.types.NodeTree:
    t = Tree("PI_GN_HipRoof")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Roof Material", "NodeSocketMaterial")
    t.input("Trim Material", "NodeSocketMaterial")
    t.input("Wall Material", "NodeSocketMaterial")
    pt, gf, fa = t.named("pt"), t.named("gf"), t.named("fa")
    wd, ln = t.named("wd"), t.named("ln")
    la, sa = t.named("la", "FLOAT_VECTOR"), t.named("sa", "FLOAT_VECTOR")
    src = t.store(t.gi("Geometry"), "part", 0, "INT", "FACE")
    # soffit: the eave quad flipped, dropped by the fascia (only where there is a fascia)
    soffit = t.o(t.n("GeometryNodeFlipFaces", {"Mesh": src}))
    soffit = t.o(t.n("GeometryNodeSetPosition", {"Geometry": soffit, "Offset": t.vec(0.0, 0.0, t.mul(fa, -1.0))}))
    soffit = t.store(soffit, "part", 3, "INT", "FACE")
    soffit = t.o(t.n("GeometryNodeDeleteGeometry", {"Geometry": soffit, "Selection": t.cmp(fa, 0.001, "LESS_THAN")},
                     domain="FACE", mode="ALL"))
    # fascia band
    geo = t.o(t.n("GeometryNodeSetPosition", {"Geometry": src, "Offset": t.vec(0.0, 0.0, t.mul(fa, -1.0))}))
    geo, _top, side = _extrude(t, geo, t.cmp(fa, 0.001, "GREATER_THAN"), t.vec(0.0, 0.0, fa))
    geo = t.store(geo, "part", 1, "INT", "FACE", selection=side)
    # hip slopes up to the gablet foot
    up = t.cmp(t.named("part", "INT"), 0, "EQUAL", "INT")
    h1 = t.mul(t.mul(t.sub(1.0, gf), t.mul(wd, 0.5)), pt)
    geo, top, side = _extrude(t, geo, up, t.vec(0.0, 0.0, h1))
    geo = t.store(geo, "top", top, "BOOLEAN", "FACE")
    geo = _scale(t, geo, t.named("top", "BOOLEAN"), gf, sa)
    long_k = t.math("MAXIMUM", t.div(t.sub(ln, t.mul(t.sub(1.0, gf), wd)), ln), 0.0)
    geo = _scale(t, geo, t.named("top", "BOOLEAN"), long_k, la)
    # gablets: up to the ridge, closing across it
    has_g = t.bool("AND", t.named("top", "BOOLEAN"), t.cmp(gf, 0.001, "GREATER_THAN"))
    h2 = t.mul(t.mul(gf, t.mul(wd, 0.5)), pt)
    geo, top2, _side = _extrude(t, geo, has_g, t.vec(0.0, 0.0, h2))
    geo = _scale(t, geo, top2, 0.0, sa)
    # remove the degenerate tops, weld the ridge
    area = t.o(t.n("GeometryNodeInputMeshFaceArea"))
    geo = t.o(t.n("GeometryNodeDeleteGeometry", {"Geometry": geo, "Selection": t.cmp(area, 1e-5, "LESS_THAN")},
                  domain="FACE", mode="ONLY_FACE"))
    geo = t.join(geo, soffit)
    geo = t.o(t.n("GeometryNodeMergeByDistance", {"Geometry": geo, "Distance": 0.001}))
    # classify faces, materials and UVs
    fn = t.on_domain(t.normal(), "FACE", "FLOAT_VECTOR")
    nx, ny, nz = t.xyz(fn)
    part = t.named("part", "INT")
    is_fascia = t.cmp(part, 1, "EQUAL", "INT")
    is_soffit = t.cmp(nz, -0.5, "LESS_THAN")
    is_slope = t.cmp(nz, 0.05, "GREATER_THAN")
    is_gable = t.bool("NIMPLY", t.bool("NOT", t.bool("OR", is_slope, is_soffit)), is_fascia)
    tang = t.vmath("NORMALIZE", t.vec(t.mul(ny, -1.0), nx, 0.0))
    pos = t.position()
    along = t.vmath("DOT_PRODUCT", pos, tang)
    z = t.xyz(pos)[2]
    sin_p = t.div(pt, t.math("SQRT", t.add(1.0, t.mul(pt, pt))))
    roof_uv = t.vec(t.div(along, ROOF_TILE_M[0]), t.div(t.div(z, t.math("MAXIMUM", sin_p, 0.05)), ROOF_TILE_M[1]))
    s, o = HB.trim_map(0, HB.CORNICE)
    ft = t.div(t.add(t.sub(z, t.named("ze")), fa), t.math("MAXIMUM", fa, 0.001))
    fascia_uv = t.vec(t.div(along, 4.0), t.madd(t.math("MINIMUM", t.math("MAXIMUM", ft, 0.0), 1.0), s, o))
    gable_uv = t.vec(t.div(along, PLASTER_TILE), t.div(z, PLASTER_TILE))
    px, py, _ = t.xyz(pos)
    soffit_uv = t.vec(t.div(t.add(px, py), 4.0), HB.trim_v(0, HB.REVEAL, 0.5))
    uv = t.switch(is_slope, t.switch(is_fascia, t.switch(is_soffit, gable_uv, soffit_uv, "VECTOR"), fascia_uv, "VECTOR"),
                  roof_uv, "VECTOR")
    geo = store_uv(t, geo, uv)
    geo = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": geo, "Material": t.gi("Roof Material"), "Selection": is_slope}))
    geo = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": geo, "Material": t.gi("Trim Material"),
                                               "Selection": t.bool("OR", is_fascia, is_soffit)}))
    geo = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": geo, "Material": t.gi("Wall Material"), "Selection": is_gable}))
    for name in ("pt", "gf", "fa", "wd", "ln", "ze", "la", "sa", "part", "top"):
        geo = t.o(t.n("GeometryNodeRemoveAttribute", {"Geometry": geo, "Name": name}))
    geo = finish_mesh(t, geo)
    # roofs read flat-shaded (tiles carry the relief in the normal map)
    t.result(t.o(t.n("GeometryNodeSetShadeSmooth", {"Mesh": geo, "Shade Smooth": False}, domain="FACE")))
    return t.ng


def roofs_object(name: str, roofs, yaw: float, coll) -> bpy.types.Object:
    """One quad per hero_bays.RoofRect (eave rectangle at eave height, counter-clockwise from above) with the
    PI_GN_HipRoof point attributes, in pivot-relative world metres."""
    verts, faces = [], []
    attrs = {k: [] for k in ("pt", "gf", "fa", "wd", "ln", "ze")}
    vec = {"la": [], "sa": []}
    a = math.radians(yaw)
    eu, ev = (math.cos(a), math.sin(a), 0.0), (-math.sin(a), math.cos(a), 0.0)
    for r in roofs:
        base = len(verts)
        for u, v in ((r.u0, r.v0), (r.u1, r.v0), (r.u1, r.v1), (r.u0, r.v1)):
            x, y = _to_world(u, v, yaw)
            verts.append((x, y, r.z))
        faces.append((base, base + 1, base + 2, base + 3))
        la, sa = (eu, ev) if r.long_is_u else (ev, eu)
        for _ in range(4):
            for k, val in (("pt", math.tan(math.radians(r.pitch))), ("gf", r.gablet), ("fa", r.fascia), ("wd", r.width),
                           ("ln", r.length), ("ze", r.z)):
                attrs[k].append(val)
            vec["la"] += la
            vec["sa"] += sa
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    for k, vals in attrs.items():
        me.attributes.new(k, "FLOAT", "POINT").data.foreach_set("value", vals)
    for k, vals in vec.items():
        me.attributes.new(k, "FLOAT_VECTOR", "POINT").data.foreach_set("vector", vals)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob
