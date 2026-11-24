"""PI_GN_BoundaryWall: a rendered boundary wall with a dark base, moulded coping, piers and optional railings,
and gate piers with lanterns (TDD "Blender asset methods"; gf_22, gf_23, gf_25).

Replaces the old `hero_hotel._wall_run` boxes. Input: run edges (as PI_GN_Balustrade's), start -> end with the
street on the right of travel; the wall stands on the left of the line (`Thickness` into the site). Run ends
flagged `post` get a gate pier (SRC_GatePier, centred on the wall); intermediate piers (SRC_WallPier) every
`Pier Spacing` metres. Railings (`Railing Height` > 0) are square bars on the coping under a top rail. Detail 1
(LOD1): body, base and coping only.
"""
from __future__ import annotations

import bpy

from .. import hero_bays as HB
from .facade import PLASTER_TILE, finish_mesh, is_detail0, opt, polyline, store_uv
from .nodes import Tree

THICKNESS = 0.36


def _sweep(t: Tree, curve, prof, mat, uv_v):
    """Closed profile (px right of travel, py down) swept along curve; UV u = metres / 4, v = uv_v(factor)."""
    curve = t.store(curve, "pu", t.o(t.n("GeometryNodeSplineParameter"), "Length"), "FLOAT", "POINT")
    p = polyline(t, list(reversed(prof[:-1])), cyclic=True)   # this winding faces the swept walls outwards
    p = t.store(p, "pv", t.o(t.n("GeometryNodeSplineParameter"), "Factor"), "FLOAT", "POINT")
    m = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": curve, "Profile Curve": p, "Miter Scale": True, "Fill Caps": True}))
    m = store_uv(t, m, t.vec(t.div(t.named("pu"), 4.0), uv_v(t.named("pv"))))
    return t.o(t.n("GeometryNodeSetMaterial", {"Geometry": m, "Material": mat}))


def _trimmed_points(t: Tree, crv, margin, spacing):
    length = t.o(t.n("GeometryNodeCurveLength", {"Curve": crv}))
    node = t.n("GeometryNodeTrimCurve", {"Curve": crv}, mode="LENGTH")
    ins = [s for s in node.inputs if s.type == "VALUE" and s.enabled]
    t.set(ins[0], margin)
    t.set(ins[1], t.sub(length, margin))
    return t.n("GeometryNodeCurveToPoints", {"Curve": t.o(node), "Length": spacing}, mode="LENGTH")


def _rot_from(t: Tree, pts_node):
    tx, ty, _ = t.xyz(t.o(pts_node, "Tangent"))
    return t.o(t.n("FunctionNodeEulerToRotation", {"Euler": t.vec(0.0, 0.0, t.math("ARCTAN2", ty, tx))}))


def wall_group() -> bpy.types.NodeTree:
    t = Tree("PI_GN_BoundaryWall")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Detail", "NodeSocketInt", 0, min_value=0, max_value=1)
    t.input("Height", "NodeSocketFloat", 1.75, min_value=0.3)
    t.input("Pier Spacing", "NodeSocketFloat", 3.6, min_value=1.0)
    t.input("Railing Height", "NodeSocketFloat", 0.0, min_value=0.0)
    t.input("Pier Object", "NodeSocketObject")
    t.input("Gate Pier Object", "NodeSocketObject")
    t.input("Wall Material", "NodeSocketMaterial")
    t.input("Trim Material", "NodeSocketMaterial")
    H, T = t.gi("Height"), THICKNESS
    d0 = is_detail0(t)
    wall, trim = t.gi("Wall Material"), t.gi("Trim Material")
    crv = t.o(t.n("GeometryNodeMeshToCurve", {"Mesh": t.gi("Geometry")}))
    crv = t.store(crv, "endp", t.o(t.n("GeometryNodeCurveEndpointSelection", {"Start Size": 1, "End Size": 1})), "BOOLEAN", "POINT")
    # body (plaster, real scale), dark base, moulded coping; profiles as (right of travel, down)
    body_prof = [(-T, 0.0), (0.0, 0.0), (0.0, -1.0), (-T, -1.0), (-T, 0.0)]
    body = _sweep(t, crv, body_prof, wall, lambda f: t.mul(f, (2 * T + 2.0) / PLASTER_TILE))
    body = t.o(t.n("GeometryNodeSetPosition", {"Geometry": body, "Selection": t.cmp(t.xyz(t.position())[2], 0.5, "GREATER_THAN"),
                                               "Offset": t.vec(0.0, 0.0, t.sub(H, 1.0))}))
    s2, o2 = HB.trim_map(2, HB.REVEAL)
    base = _sweep(t, crv, [(-T - 0.02, 0.0), (0.02, 0.0), (0.02, -0.32), (-T - 0.02, -0.32), (-T - 0.02, 0.0)], trim,
                  lambda f: t.madd(f, s2, o2))
    s0, o0 = HB.trim_map(0, HB.CORNICE)
    cop = [(-T - 0.06, 0.0), (0.06, 0.0), (0.06, -0.1), (0.0, -0.17), (-T, -0.17), (-T - 0.06, -0.1), (-T - 0.06, 0.0)]
    coping = _sweep(t, crv, cop, trim, lambda f: t.madd(f, s0, o0))
    coping = t.transform(coping, translation=t.vec(0.0, 0.0, H))
    parts = [body, base, coping]
    # piers along the run (not within 1.2 m of an end), centred on the wall
    pn = _trimmed_points(t, crv, 1.2, t.gi("Pier Spacing"))
    pier = t.o(t.n("GeometryNodeObjectInfo", {"Object": t.gi("Pier Object")}), "Geometry")
    pier = t.transform(pier, scale=t.vec(1.0, 1.0, t.div(H, 1.75)))
    piers = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": t.o(pn, "Points"), "Instance": pier, "Rotation": _rot_from(t, pn)}))
    parts.append(opt(t, piers, d0))
    # gate piers on flagged run ends
    gn = t.n("GeometryNodeCurveToPoints", {"Curve": crv}, mode="EVALUATED")
    gpts = t.store(t.o(gn, "Points"), "gtan", t.o(gn, "Tangent"), "FLOAT_VECTOR", "POINT")
    gpts = t.o(t.n("GeometryNodeDeleteGeometry", {"Geometry": gpts, "Selection": t.bool(
        "NAND", t.named("endp", "BOOLEAN"), t.named("post", "BOOLEAN"))}, domain="POINT"))
    gate = t.o(t.n("GeometryNodeObjectInfo", {"Object": t.gi("Gate Pier Object")}), "Geometry")
    tx, ty, _ = t.xyz(t.named("gtan", "FLOAT_VECTOR"))
    gpts_rot = t.o(t.n("FunctionNodeEulerToRotation", {"Euler": t.vec(0.0, 0.0, t.math("ARCTAN2", ty, tx))}))
    gates = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": gpts, "Instance": gate, "Rotation": gpts_rot}))
    parts.append(opt(t, gates, d0))
    # railings: square bars every 0.13 m on the coping, a flat top rail
    rh = t.gi("Railing Height")
    rn = _trimmed_points(t, crv, 0.3, 0.13)
    bar = t.o(t.n("GeometryNodeMeshCube", {"Size": t.vec(0.022, 0.022, rh)}))
    bar = t.transform(bar, translation=t.vec(0.0, T / 2, t.add(t.add(H, 0.17), t.mul(rh, 0.5))))
    bar = store_uv(t, bar, t.vec(0.0, HB.trim_v(2, HB.REVEAL, 0.5)))
    bar = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": bar, "Material": trim}))
    bars = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": t.o(rn, "Points"), "Instance": bar, "Rotation": _rot_from(t, rn)}))
    rail = _sweep(t, crv, [(-T / 2 - 0.03, 0.0), (-T / 2 + 0.03, 0.0), (-T / 2 + 0.03, -0.04), (-T / 2 - 0.03, -0.04),
                           (-T / 2 - 0.03, 0.0)], trim, lambda f: t.madd(f, s2, o2))
    rail = t.transform(rail, translation=t.vec(0.0, 0.0, t.add(t.add(H, 0.17), rh)))
    parts.append(opt(t, t.join(bars, rail), t.bool("AND", d0, t.cmp(rh, 0.05, "GREATER_THAN"))))
    geo = t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": t.join(*parts)}))
    for name in ("endp", "post", "gtan", "pu", "pv"):
        geo = t.o(t.n("GeometryNodeRemoveAttribute", {"Geometry": geo, "Name": name}))
    t.result(finish_mesh(t, geo))
    return t.ng
