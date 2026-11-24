"""Geometry Nodes generators for repeated facade elements (TDD "Blender asset methods"; research 3.2).

One authoritative node group per element, built from Python so the pipeline can rebuild it headless, but a
normal node group in the .blend (open it, tweak the inputs, it regenerates):

| Group | Element | Input geometry |
| --- | --- | --- |
| PI_GN_ArcadeBay | one arcade bay: arched opening with reveal/soffit, archivolt, imposts, keystone, the back face of the pier wall, the veranda's floor, ceiling and back wall with a glazed door | bay points |
| PI_GN_WindowGrid | one window bay: wall panel with the opening, reveal, glass, architrave, sill, hood or keystone, shutters, awning, fanlight | bay points |
| PI_GN_Balustrade | turned balusters on a plinth under a moulded rail, posts at run ends | run edges |
| PI_GN_CorniceRun | a moulding profile swept (mitred) along a polyline | polylines |
| PI_GN_EaveBrackets | brackets under an eave every n metres | polylines |
| PI_GN_HipRoof | hipped tile roofs with Dutch gablets, fascia and soffit (`roof.py`) | eave quads |
| PI_GN_BoundaryWall | boundary wall: body, dark base, coping, piers, gate piers with lanterns, railings (`wall.py`) | run edges |
| PI_GN_UV1 | UV1 (`UVMap2`): one non-overlapping 0-1 unwrap, seams at edges over 30 degrees or `uv_seam` | the joined LOD0 |

Bay points are mesh vertices in the hero frame with point attributes `rot` (wall direction, radians about Z),
`s0` (bay centre's distance along its wall) and `z0` (floor line). A bay is built once per object in "shape
space" (x across the wall, y up from the floor line, z towards the viewer: Fill Curve works in XY), turned
into the bay frame (x along the wall, y into the building, z up), instanced on the points, realized, and its
UVs finished per bay: plaster (`uvk` 2) shifts by (s0, z0) / 4 so the real-scale render runs on across bays,
trim (`uvk` 1) shifts along u only, glass (`uvk` 0) stays on its vision pane. Then Merge by Distance.

UV0 rows follow the FacadeTrim_A contract (hero_bays.trim_map): mouldings and sills on the cornice row, soffits,
floors and dark recesses on the reveal row (block 2 = the dark accent block), walls in real-scale plaster.
"""
from __future__ import annotations

import math

import bmesh
import bpy

from .. import hero_bays as HB
from .. import materials as M
from .nodes import Tree, set_inputs

GLASS_U = (0.03, 0.22)
GLASS_V = M.GLASS_VISION
PLASTER_TILE = 4.0  # MAT_PlasterSmooth_Cream metres per UV unit (materials.TILE_M)

# moulding profiles: (outward offset d, height z) listed bottom to top, as hero_blocks used them
PROFILES = {
    "cornice": [(0.0, -0.6), (0.14, -0.6), (0.14, -0.46), (0.24, -0.46), (0.24, -0.28), (0.5, -0.1), (0.5, 0.0), (0.0, 0.0)],
    "string": [(0.0, -0.42), (0.14, -0.42), (0.14, -0.3), (0.26, -0.16), (0.26, 0.0), (0.0, 0.0)],
    "plinth": [(0.12, 0.0), (0.12, 0.75), (0.03, 0.79), (0.0, 0.79)],
    "cornice_lod1": [(0.0, -0.4), (0.35, -0.1), (0.35, 0.0), (0.0, 0.0)],
    "string_lod1": [(0.0, -0.4), (0.14, -0.1), (0.14, 0.0), (0.0, 0.0)],
    "coping": [(0.0, 0.0), (0.07, 0.0), (0.07, 0.17), (0.0, 0.17)],
    "ridge": [(-0.17, -0.02), (-0.13, 0.1), (0.0, 0.16), (0.13, 0.1), (0.17, -0.02)],   # SLICE5: 6 -> 4 facets (smooth shaded)
    "pipe": [(0.07, 0.0), (0.035, 0.0606), (-0.035, 0.0606), (-0.07, 0.0), (-0.035, -0.0606), (0.035, -0.0606), (0.07, -0.0)],
    "rail": [(-0.13, 0.0), (0.13, 0.0), (0.13, 0.05), (0.09, 0.1), (0.0, 0.12), (-0.09, 0.1), (-0.13, 0.05), (-0.13, 0.0)],
    "bal_plinth": [(-0.16, 0.0), (0.16, 0.0), (0.16, 0.12), (0.12, 0.15), (-0.12, 0.15), (-0.16, 0.12), (-0.16, 0.0)],
}


# --- shared field helpers ------------------------------------------------------------------------

def opt(t: Tree, geo, cond):
    """Geometry when cond (bool socket/value) is true, else nothing."""
    return t.switch(cond, None, geo, "GEOMETRY")


def is_detail0(t: Tree):
    return t.cmp(t.gi("Detail"), 0, "EQUAL", "INT")


def polyline(t: Tree, pts, cyclic=False):
    """Poly curve through fixed points [(x, y), ...] (profile space) as a curve."""
    sw = t.n("GeometryNodeIndexSwitch", data_type="VECTOR")
    while len([s for s in sw.inputs if s.name not in ("Index", "")]) < len(pts):
        sw.index_switch_items.new()
    items = [s for s in sw.inputs if s.name not in ("Index", "")]
    t.links.new(t.index(), sw.inputs["Index"])
    for s, p in zip(items, pts):
        s.default_value = (p[0], p[1], 0.0)
    pts_ = t.o(t.n("GeometryNodePoints", {"Count": len(pts), "Position": t.o(sw)}))
    crv = t.o(t.n("GeometryNodePointsToCurves", {"Points": pts_}))
    if cyclic:
        crv = t.o(t.n("GeometryNodeSetSplineCyclic", {"Curve": crv, "Cyclic": True}))
    return crv


def opening_curve(t: Tree, hw, zb, spring, rise, segs, closed=False, arc_only=False):
    """Opening outline in shape space, counter-clockwise: (hw, zb), the head from (hw, spring) over the top to
    (-hw, spring) in `segs` steps (x = hw cos, y = spring + rise sin: semicircle when rise = hw, flat head when
    rise = 0 and segs = 1), then (-hw, zb). Open (jambs and head), closed (with the sill line) or the head only."""
    i = t.index()
    if arc_only:
        k = i
        count = t.add(segs, 1)
    else:
        k = t.sub(i, 1)
        count = t.add(segs, 3)
    th = t.mul(k, t.div(math.pi, segs))
    arc = t.vec(t.mul(t.math("COSINE", th), hw), t.add(spring, t.mul(t.math("SINE", th), rise)), 0.0)
    if arc_only:
        pos = arc
    else:
        foot = t.switch(t.cmp(i, 0, "EQUAL", "INT"), t.vec(t.mul(hw, -1.0), zb, 0.0), t.vec(hw, zb, 0.0), "VECTOR")
        head = t.bool("AND", t.cmp(i, 1, "GREATER_EQUAL", "INT"), t.cmp(i, t.add(segs, 1), "LESS_EQUAL", "INT"))
        pos = t.switch(head, foot, arc, "VECTOR")
    pts = t.o(t.n("GeometryNodePoints", {"Count": count, "Position": pos}))
    crv = t.o(t.n("GeometryNodePointsToCurves", {"Points": pts}))
    if closed:
        crv = t.o(t.n("GeometryNodeSetSplineCyclic", {"Curve": crv, "Cyclic": True}))
    return crv


def rect_curve(t: Tree, w, h, y0=0.0):
    r = t.o(t.n("GeometryNodeCurvePrimitiveQuadrilateral", {"Width": w, "Height": h}))
    return t.transform(r, translation=t.vec(0.0, t.add(y0, t.mul(h, 0.5)), 0.0))


def fill(t: Tree, *curves):
    return t.o(t.n("GeometryNodeFillCurve", {"Curve": t.join(*curves)}))


def store_uv(t: Tree, geo, uv):
    return t.store(geo, "UVMap", uv, "FLOAT_VECTOR" if False else "FLOAT2", "CORNER")


def mark(t: Tree, geo, mat, uvk: int):
    geo = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": geo, "Material": mat}))
    return t.store(geo, "uvk", uvk, "INT", "FACE")


def box_uv(t: Tree, tile=PLASTER_TILE):
    """Real-scale box projection in shape space (faces towards z: x, y; towards x: z, y; towards y: x, z)."""
    pos = t.position()
    fn = t.on_domain(t.normal(), "FACE", "FLOAT_VECTOR")
    nx, ny, nz = (t.math("ABSOLUTE", c) for c in t.xyz(fn))
    x, y, z = t.xyz(pos)
    by_z = t.cmp(nz, t.math("MAXIMUM", nx, ny), "GREATER_EQUAL")
    by_x = t.cmp(nx, ny, "GREATER_EQUAL")
    uv = t.switch(by_z, t.switch(by_x, t.vec(x, z), t.vec(z, y), "VECTOR"), t.vec(x, y), "VECTOR")
    return t.vmath("SCALE", uv, scale=1.0 / tile)


def sweep(t: Tree, curve, profile_pts, mat, block=0, row=HB.CORNICE, uvk=1, closed_profile=False):
    """Profile [(px, py), ...] swept along curve (px: right of travel, py: into the wall / down); UVs u =
    length / 4 along the curve, v across the trim row by the profile's length fraction."""
    curve = t.store(curve, "pu", t.o(t.n("GeometryNodeSplineParameter"), "Length"), "FLOAT", "POINT")
    prof = polyline(t, profile_pts, closed_profile)
    prof = t.store(prof, "pv", t.o(t.n("GeometryNodeSplineParameter"), "Factor"), "FLOAT", "POINT")
    m = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": curve, "Profile Curve": prof, "Miter Scale": True}))
    s, o = HB.trim_map(block, row)
    uv = t.vec(t.div(t.named("pu"), 4.0), t.madd(t.named("pv"), s, o))
    m = store_uv(t, m, uv)
    return mark(t, m, mat, uvk)


def shape_to_bay(t: Tree, geo):
    """Shape space (x, up, towards viewer) -> bay frame (x, into building, up): +90 degrees about x."""
    return t.transform(geo, rotation=(math.pi / 2, 0.0, 0.0))


def place(t: Tree, src_obj_socket, translation, scale=None):
    geo = t.o(t.n("GeometryNodeObjectInfo", {"Object": src_obj_socket}), "Geometry")
    return t.transform(geo, translation=translation, scale=scale)


def finish_bays(t: Tree, proto):
    """Instance the bay prototype on the input points, realize, per-bay UV shifts, smooth by angle, merge."""
    rot = t.o(t.n("FunctionNodeEulerToRotation", {"Euler": t.vec(0.0, 0.0, t.named("rot"))}))
    inst = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": t.gi("Geometry"), "Instance": proto, "Rotation": rot}))
    geo = t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": inst}))
    uvk = t.named("uvk", "INT")
    du = t.mul(t.div(t.named("s0"), 4.0), t.cmp(uvk, 0, "GREATER_THAN", "INT"))
    dv = t.mul(t.div(t.named("z0"), PLASTER_TILE), t.cmp(uvk, 2, "EQUAL", "INT"))
    geo = store_uv(t, geo, t.vmath("ADD", t.named("UVMap", "FLOAT_VECTOR"), t.vec(du, dv)))
    return finish_mesh(t, geo)


def finish_mesh(t: Tree, geo, merge=0.0008):
    for name in ("uvk", "s0", "z0", "rot", "pu", "pv"):
        geo = t.o(t.n("GeometryNodeRemoveAttribute", {"Geometry": geo, "Name": name}))
    geo = t.o(t.n("GeometryNodeMergeByDistance", {"Geometry": geo, "Distance": merge}))
    geo = t.o(t.n("GeometryNodeSetShadeSmooth", {"Mesh": geo, "Shade Smooth": True}, domain="FACE"))
    ang = t.o(t.n("GeometryNodeInputMeshEdgeAngle"), "Unsigned Angle")
    smooth = t.cmp(ang, math.radians(31.0), "LESS_THAN")
    return t.o(t.n("GeometryNodeSetShadeSmooth", {"Mesh": geo, "Shade Smooth": smooth}, domain="EDGE"))


def _common_inputs(t: Tree):
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Detail", "NodeSocketInt", 0, min_value=0, max_value=1)
    t.input("Wall Material", "NodeSocketMaterial")
    t.input("Trim Material", "NodeSocketMaterial")
    t.input("Glass Material", "NodeSocketMaterial")


# --- PI_GN_WindowGrid ------------------------------------------------------------------------------

def window_group(src: dict) -> bpy.types.NodeTree:
    t = Tree("PI_GN_WindowGrid")
    _common_inputs(t)
    for name, d in (("Bay Width", 3.6), ("Storey Height", 4.0), ("Window Width", 1.25), ("Window Height", 2.2),
                    ("Sill Height", 0.85), ("Reveal Depth", 0.3)):
        t.input(name, "NodeSocketFloat", d, min_value=0.0)
    t.input("Segments", "NodeSocketInt", 6, min_value=1, max_value=16)
    # SLICE6: Closed = louvred door leaves shut inside the opening (gf_24), Dark = open doorway, a dark interior card
    for name in ("Arched", "Surround", "Sill", "Hood", "Keystone", "Shutters", "Awning", "Fanlight", "Closed", "Dark"):
        t.input(name, "NodeSocketBool", False)
    for name in ("Sill Object", "Hood Object", "Keystone Object", "Shutter Object", "Awning Object", "Fanlight Object"):
        t.input(name, "NodeSocketObject")
    W, H, ww, wh, sh, D = (t.gi(n) for n in ("Bay Width", "Storey Height", "Window Width", "Window Height",
                                              "Sill Height", "Reveal Depth"))
    arched = t.gi("Arched")
    hw = t.mul(ww, 0.5)
    rise = t.switch(arched, 0.0, hw)
    top = t.add(sh, wh)
    spring = t.sub(top, rise)
    segs = t.switch(arched, 1, t.gi("Segments"), "INT")
    wall, trim, glass = t.gi("Wall Material"), t.gi("Trim Material"), t.gi("Glass Material")
    d0 = is_detail0(t)

    closed = opening_curve(t, hw, sh, spring, rise, segs, closed=True)
    path = opening_curve(t, hw, sh, spring, rise, segs)
    proud = t.mul(t.gi("Surround"), -0.06)
    panel0 = fill(t, rect_curve(t, W, H), closed)
    panel1 = fill(t, rect_curve(t, W, H))
    panel = t.switch(d0, panel1, panel0, "GEOMETRY")
    panel = mark(t, store_uv(t, panel, box_uv(t)), wall, 2)
    reveal = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": closed, "Profile Curve": t.o(t.n(
        "GeometryNodeCurvePrimitiveLine", {"Start": t.vec(0.0, D), "End": t.vec(0.0, proud)}))}))
    reveal = opt(t, mark(t, store_uv(t, reveal, box_uv(t)), wall, 2), d0)
    gl = t.transform(fill(t, closed), translation=t.vec(0.0, 0.0, t.switch(d0, 0.02, t.mul(D, -1.0))))
    x, y, _ = t.xyz(t.position())
    gu = t.add(GLASS_U[0], t.mul(t.div(t.add(x, hw), ww), GLASS_U[1] - GLASS_U[0]))
    gv = t.add(GLASS_V[0], t.mul(t.div(t.sub(y, sh), wh), GLASS_V[1] - GLASS_V[0]))
    glz = mark(t, store_uv(t, gl, t.vec(gu, gv)), glass, 0)
    dark = mark(t, store_uv(t, gl, t.vec(0.1, HB.trim_v(2, HB.REVEAL, 0.5))), trim, 0)   # block 2 dark paint row
    gl = t.switch(t.gi("Dark"), glz, dark, "GEOMETRY")
    # architrave round jambs and head (0.13 m wide, 0.06 m proud); the reveal closes its inner side
    surround = sweep(t, path, [(0.0, -0.06), (0.13, -0.06), (0.13, 0.0)], trim)
    surround = opt(t, surround, t.bool("AND", d0, t.gi("Surround")))
    shape = t.join(panel, reveal, gl, surround)
    parts = [shape_to_bay(t, shape)]

    def ob_part(obj_in, flag, translation, scale=None):
        geo = place(t, t.gi(obj_in), translation, scale)
        parts.append(opt(t, geo, t.bool("AND", d0, t.gi(flag))))

    ob_part("Sill Object", "Sill", t.vec(0.0, 0.0, sh), t.vec(t.add(ww, 0.44), 1.0, 1.0))
    ob_part("Hood Object", "Hood", t.vec(0.0, 0.0, t.add(top, 0.13)), t.vec(t.add(ww, 0.5), 1.0, 1.0))
    ob_part("Keystone Object", "Keystone", t.vec(0.0, -0.04, t.sub(top, 0.1)), (0.7, 1.0, 0.6))
    leaf_h = t.sub(spring, sh)
    sw = hw  # each leaf half the window width
    ob_part("Shutter Object", "Shutters", t.vec(t.sub(t.mul(hw, -1.0), t.add(0.14, sw)), 0.0, sh), t.vec(sw, 1.0, leaf_h))
    ob_part("Shutter Object", "Shutters", t.vec(t.add(hw, 0.14), 0.0, sh), t.vec(sw, 1.0, leaf_h))
    # closed leaves: two shutter leaves filling the opening below the springing, just behind the reveal's front
    shut = t.bool("AND", d0, t.gi("Closed"))
    for x0 in (t.mul(hw, -1.0), 0.0):
        geo = place(t, t.gi("Shutter Object"), t.vec(x0, t.sub(D, 0.12), sh), t.vec(hw, 1.0, leaf_h))
        parts.append(opt(t, geo, shut))
    ob_part("Awning Object", "Awning", t.vec(0.0, 0.0, t.add(top, 0.32)), t.vec(t.add(ww, 0.24), 1.0, 1.0))
    ob_part("Fanlight Object", "Fanlight", t.vec(0.0, t.sub(D, 0.04), spring), t.vec(hw, 1.0, hw))
    # French doors: a central glazing bar and a meeting rail below the fanlight
    bar = t.o(t.n("GeometryNodeMeshGrid", {"Size X": 0.07, "Size Y": t.sub(spring, sh), "Vertices X": 2, "Vertices Y": 2}))
    bar = t.transform(bar, translation=t.vec(0.0, t.sub(D, 0.04), t.mul(t.add(spring, sh), 0.5)), rotation=(math.pi / 2, 0.0, 0.0))
    bar = mark(t, store_uv(t, bar, t.vec(0.0, HB.trim_v(0, HB.REVEAL, 0.5))), trim, 0)
    plain = t.bool("NOT", t.bool("OR", t.gi("Closed"), t.gi("Dark")))
    parts.append(opt(t, bar, t.bool("AND", t.bool("AND", d0, t.gi("Fanlight")), plain)))
    t.result(finish_bays(t, t.join(*parts)))
    return t.ng


# --- PI_GN_ArcadeBay -------------------------------------------------------------------------------

def arcade_group(src: dict) -> bpy.types.NodeTree:
    t = Tree("PI_GN_ArcadeBay")
    _common_inputs(t)
    for name, d in (("Bay Width", 3.7), ("Storey Height", 4.85), ("Arch Width", 2.5), ("Crown Gap", 0.55),
                    ("Pier Depth", 0.6), ("Veranda Depth", 3.0), ("Ceiling Drop", 0.35), ("Door Width", 1.2),
                    ("Door Height", 2.9), ("Recess Depth", 0.0)):
        t.input(name, "NodeSocketFloat", d, min_value=0.0)
    t.input("Segments", "NodeSocketInt", 8, min_value=2, max_value=24)
    t.input("Keystone Object", "NodeSocketObject")
    t.input("Impost Object", "NodeSocketObject")
    W, H, aw, cg, D, V = (t.gi(n) for n in ("Bay Width", "Storey Height", "Arch Width", "Crown Gap", "Pier Depth",
                                             "Veranda Depth"))
    wall, trim, glass = t.gi("Wall Material"), t.gi("Trim Material"), t.gi("Glass Material")
    d0 = is_detail0(t)
    hw = t.mul(aw, 0.5)
    crown = t.sub(H, cg)
    spring = t.sub(crown, hw)
    segs = t.gi("Segments")
    closed = opening_curve(t, hw, 0.0, spring, hw, segs, closed=True)
    path = opening_curve(t, hw, 0.0, spring, hw, segs)
    head = opening_curve(t, hw, 0.0, spring, hw, segs, arc_only=True)
    front = fill(t, rect_curve(t, W, H), closed)
    front = mark(t, store_uv(t, front, box_uv(t)), wall, 2)
    back = t.transform(t.o(t.n("GeometryNodeFlipFaces", {"Mesh": front})), translation=t.vec(0.0, 0.0, t.mul(D, -1.0)))
    has_ver = t.bool("AND", d0, t.cmp(V, 0.01, "GREATER_THAN"))
    back = opt(t, back, d0)
    # P46e: LOD1 gets "Recess Depth" (the veranda depth, set by hero_bays.arcade_params): the reveal runs on to the
    # veranda's back wall, so the arch reads as a deep shaded opening, not a dark face on a flat wall (same triangles)
    DR = t.add(D, t.gi("Recess Depth"))
    reveal = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": path, "Profile Curve": t.o(t.n(
        "GeometryNodeCurvePrimitiveLine", {"Start": t.vec(0.0, DR), "End": (0.0, 0.0, 0.0)}))}))
    reveal = mark(t, store_uv(t, reveal, box_uv(t)), wall, 2)
    # LOD1: a dark recess closes the arch at the back of the pier (plus Recess Depth)
    s2, o2 = HB.trim_map(2, HB.REVEAL)
    dark = t.transform(fill(t, closed), translation=t.vec(0.0, 0.0, t.mul(DR, -1.0)))
    dark = opt(t, mark(t, store_uv(t, dark, t.vec(0.1, o2 + 0.5 * s2)), trim, 0), t.bool("NOT", d0))
    archivolt = sweep(t, head, [(0.0, -0.07), (0.24, -0.07), (0.24, 0.0)], trim)
    archivolt = opt(t, archivolt, d0)
    # veranda: floor, ceiling (shape space: y up, z towards the arch, so depth is -z)
    ceil_y = t.sub(H, t.gi("Ceiling Drop"))
    sr, orv = HB.trim_map(0, HB.REVEAL)

    def slab(y, flip):
        g = t.o(t.n("GeometryNodeMeshGrid", {"Size X": W, "Size Y": t.sub(V, D), "Vertices X": 2, "Vertices Y": 2}))
        g = t.transform(g, translation=t.vec(0.0, 0.0, 0.0), rotation=(-math.pi / 2, 0.0, 0.0))  # XY grid -> XZ, faces +y
        g = t.transform(g, translation=t.vec(0.0, y, t.mul(t.add(V, D), -0.5)))
        if flip:
            g = t.o(t.n("GeometryNodeFlipFaces", {"Mesh": g}))
        x_, _, z_ = t.xyz(t.position())
        return mark(t, store_uv(t, g, t.vec(t.div(x_, 4.0), t.madd(t.div(z_, t.mul(V, -1.0)), sr, orv))), trim, 1)
    floor = slab(0.0, False)
    ceiling = slab(ceil_y, True)
    dw, dh = t.gi("Door Width"), t.math("MINIMUM", t.gi("Door Height"), t.sub(ceil_y, 0.4))
    door = opening_curve(t, t.mul(dw, 0.5), 0.0, dh, 0.0, 1, closed=True)
    bwall = fill(t, rect_curve(t, W, ceil_y))
    bwall = mark(t, store_uv(t, bwall, box_uv(t)), wall, 2)
    x, y, _ = t.xyz(t.position())
    dglass = t.transform(fill(t, door), translation=(0.0, 0.0, 0.03))
    gu = t.add(GLASS_U[0], t.mul(t.div(t.add(x, t.mul(dw, 0.5)), dw), GLASS_U[1] - GLASS_U[0]))
    gv = t.add(GLASS_V[0], t.mul(t.div(y, dh), GLASS_V[1] - GLASS_V[0]))
    dglass = mark(t, store_uv(t, dglass, t.vec(gu, gv)), glass, 0)
    dreveal = None
    backwall = t.transform(t.join(bwall, dglass), translation=t.vec(0.0, 0.0, t.mul(V, -1.0)))
    veranda = opt(t, t.join(floor, ceiling, backwall), has_ver)
    shape = t.join(front, back, reveal, dark, archivolt, veranda)
    parts = [shape_to_bay(t, shape)]
    ks = place(t, t.gi("Keystone Object"), t.vec(0.0, -0.07, t.sub(crown, 0.16)))
    parts.append(opt(t, ks, d0))
    for sgn in (-1.0, 1.0):
        im = place(t, t.gi("Impost Object"), t.vec(t.mul(t.add(hw, 0.2), sgn), 0.0, spring))
        parts.append(opt(t, im, d0))
    t.result(finish_bays(t, t.join(*parts)))
    return t.ng


# --- PI_GN_Balustrade ------------------------------------------------------------------------------

def balustrade_group(src: dict) -> bpy.types.NodeTree:
    """Runs are mesh edges (start -> end at the base height), vertex attribute `post` marks the ends that get a
    pedestal. Rail and plinth are moulded profiles swept along the run (UV u = metres / 4 on the cornice row);
    balusters are instanced every `Spacing` metres between `Margin` from each end; heights scale to `Height`."""
    t = Tree("PI_GN_Balustrade")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Height", "NodeSocketFloat", 0.95, min_value=0.4)
    t.input("Spacing", "NodeSocketFloat", 0.36, min_value=0.12)
    t.input("Margin", "NodeSocketFloat", 0.2, min_value=0.0)
    t.input("Baluster Object", "NodeSocketObject")
    t.input("Post Object", "NodeSocketObject")
    t.input("Material", "NodeSocketMaterial")
    H, sp, mg = t.gi("Height"), t.gi("Spacing"), t.gi("Margin")
    mat = t.gi("Material")
    crv = t.o(t.n("GeometryNodeMeshToCurve", {"Mesh": t.gi("Geometry")}))
    plinth_h, rail_h = 0.15, 0.12
    plinth = sweep(t, crv, _profile_xy("bal_plinth"), mat, closed_profile=False)
    rail = sweep(t, crv, _profile_xy("rail"), mat)
    rail = t.transform(rail, translation=t.vec(0.0, 0.0, t.sub(H, rail_h)))
    trimmed = t.o(t.n("GeometryNodeTrimCurve", {"Curve": crv, ("Start", "VALUE"): mg, ("End", "VALUE"): mg}, mode="LENGTH"))
    # Trim's end is a length from the start in LENGTH mode: end = length - margin
    trim_node = trimmed.node
    length = t.o(t.n("GeometryNodeCurveLength", {"Curve": crv}))
    t.set([s for s in trim_node.inputs if s.name == "End" and s.type == "VALUE" and s.enabled][0], t.sub(length, mg))
    pts = t.o(t.n("GeometryNodeCurveToPoints", {"Curve": trimmed, "Length": sp}, mode="LENGTH"))
    zs = t.div(t.sub(H, plinth_h + rail_h), 0.66)
    bal = t.o(t.n("GeometryNodeObjectInfo", {"Object": t.gi("Baluster Object")}), "Geometry")
    inst = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": pts, "Instance": bal, "Scale": t.vec(1.0, 1.0, zs)}))
    inst = t.transform(inst, translation=(0.0, 0.0, plinth_h))
    # posts on flagged run ends
    post_pts = t.o(t.n("GeometryNodeMeshToPoints", {"Mesh": t.gi("Geometry"), "Selection": t.named("post", "BOOLEAN")}))
    post_pts = t.o(t.n("GeometryNodeMergeByDistance", {"Geometry": post_pts, "Distance": 0.05}))
    post = t.o(t.n("GeometryNodeObjectInfo", {"Object": t.gi("Post Object")}), "Geometry")
    posts = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": post_pts, "Instance": post, "Scale": t.vec(1.0, 1.0, t.add(H, 0.08))}))
    geo = t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": t.join(plinth, rail, inst, posts)}))
    t.result(finish_mesh(t, geo))
    return t.ng


def _profile_xy(name):
    """Balustrade profiles are (across, up) pairs: px = across (right of travel), py = -up."""
    return [(a, -b) for a, b in PROFILES[name]]


# --- PI_GN_CorniceRun and PI_GN_EaveBrackets -------------------------------------------------------

def cornice_group() -> bpy.types.NodeTree:
    """A moulding profile (an object whose vertices are the profile in X = outward, Y = up) swept along each
    polyline of the input mesh with mitred corners; UV u = metres / 4, v across `V Scale`/`V Offset`."""
    t = Tree("PI_GN_CorniceRun")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Profile Object", "NodeSocketObject")
    t.input("Material", "NodeSocketMaterial")
    t.input("V Scale", "NodeSocketFloat", 0.025)
    t.input("V Offset", "NodeSocketFloat", 0.2)
    crv = t.o(t.n("GeometryNodeMeshToCurve", {"Mesh": t.gi("Geometry")}))
    crv = t.store(crv, "pu", t.o(t.n("GeometryNodeSplineParameter"), "Length"), "FLOAT", "POINT")
    prof = t.o(t.n("GeometryNodeObjectInfo", {"Object": t.gi("Profile Object")}), "Geometry")
    prof = t.o(t.n("GeometryNodeMeshToCurve", {"Mesh": prof}))
    prof = t.store(prof, "pv", t.o(t.n("GeometryNodeSplineParameter"), "Factor"), "FLOAT", "POINT")
    m = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": crv, "Profile Curve": prof, "Miter Scale": True}))
    m = store_uv(t, m, t.vec(t.div(t.named("pu"), 4.0), t.madd(t.named("pv"), t.gi("V Scale"), t.gi("V Offset"))))
    m = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": m, "Material": t.gi("Material")}))
    t.result(finish_mesh(t, m))
    return t.ng


def brackets_group() -> bpy.types.NodeTree:
    t = Tree("PI_GN_EaveBrackets")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Spacing", "NodeSocketFloat", 1.7, min_value=0.3)
    t.input("Margin", "NodeSocketFloat", 0.6, min_value=0.0)
    t.input("Bracket Object", "NodeSocketObject")
    crv = t.o(t.n("GeometryNodeMeshToCurve", {"Mesh": t.gi("Geometry")}))
    crv = t.o(t.n("GeometryNodeSetCurveNormal", {"Curve": crv, "Mode": "Z Up"}))
    length = t.o(t.n("GeometryNodeCurveLength", {"Curve": crv}))
    node = t.n("GeometryNodeTrimCurve", {"Curve": crv}, mode="LENGTH")
    ins = [s for s in node.inputs if s.type == "VALUE" and s.enabled]
    t.set(ins[0], t.gi("Margin"))
    t.set(ins[1], t.sub(length, t.gi("Margin")))
    pts = t.n("GeometryNodeCurveToPoints", {"Curve": t.o(node), "Length": t.gi("Spacing")}, mode="LENGTH")
    br = t.o(t.n("GeometryNodeObjectInfo", {"Object": t.gi("Bracket Object")}), "Geometry")
    tx, ty, _ = t.xyz(t.o(pts, "Tangent"))
    rot = t.o(t.n("FunctionNodeEulerToRotation", {"Euler": t.vec(0.0, 0.0, t.math("ARCTAN2", ty, tx))}))
    inst = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": t.o(pts, "Points"), "Instance": br, "Rotation": rot}))
    t.result(finish_mesh(t, t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": inst}))))
    return t.ng


def uv1_group() -> bpy.types.NodeTree:
    """UV1 (`UVMap2`): one non-overlapping 0-1 unwrap for the decor atlas / lighting role (research 3.5), seams at
    edges sharper than 30 degrees OR the instance sources' `uv_seam` (TDD workaround 2)."""
    t = Tree("PI_GN_UV1")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    ang = t.o(t.n("GeometryNodeInputMeshEdgeAngle"), "Unsigned Angle")
    seam = t.bool("OR", t.cmp(ang, math.radians(30.0), "GREATER_THAN"), t.named("uv_seam", "BOOLEAN"))
    uv = t.o(t.n("GeometryNodeUVUnwrap", {"Seam": seam, "Margin": 0.002}))
    geo = t.store(t.gi("Geometry"), "UVMap2", uv, "FLOAT2", "CORNER")
    t.result(geo)
    return t.ng


# --- objects from the layout -----------------------------------------------------------------------

def _to_world(u, v, yaw):
    a = math.radians(yaw)
    return u * math.cos(a) - v * math.sin(a), u * math.sin(a) + v * math.cos(a)


def bay_points_object(name: str, points, yaw: float, coll) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    verts = []
    for p in points:
        x, y = _to_world(p.u, p.v, yaw)
        verts.append((x, y, p.z))
    me.from_pydata(verts, [], [])
    for attr, vals in (("rot", [p.angle + math.radians(yaw) for p in points]), ("s0", [p.s0 for p in points]),
                       ("z0", [p.z for p in points])):
        a = me.attributes.new(attr, "FLOAT", "POINT")
        a.data.foreach_set("value", vals)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def runs_object(name: str, runs, yaw: float, coll) -> bpy.types.Object:
    verts, edges, post = [], [], []
    for r in runs:
        for p, flag in ((r.a, r.post_a), (r.b, r.post_b)):
            x, y = _to_world(p[0], p[1], yaw)
            verts.append((x, y, p[2]))
            post.append(flag)
        edges.append((len(verts) - 2, len(verts) - 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    a = me.attributes.new("post", "BOOLEAN", "POINT")
    a.data.foreach_set("value", post)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def polylines_object(name: str, lines, yaw: float, coll) -> bpy.types.Object:
    """lines: [[(u, v, z), ...], ...] open polylines."""
    verts, edges = [], []
    for line in lines:
        base = len(verts)
        for u, v, z in line:
            x, y = _to_world(u, v, yaw)
            verts.append((x, y, z))
        edges += [(base + i, base + i + 1) for i in range(len(line) - 1)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def profile_object(name: str, prof) -> bpy.types.Object:
    """Profile curve source: vertices in profile space (X right of travel = outward, Y = -up), listed so the
    swept faces look outwards (the hero profiles are bottom to top, so they are reversed here)."""
    pts = [(d, -z, 0.0) for d, z in reversed(prof)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(pts, [(i, i + 1) for i in range(len(pts) - 1)], [])
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old)
    ob = bpy.data.objects.new(name, me)
    from .sources import _coll
    _coll().objects.link(ob)
    return ob


class Generators:
    """Node groups and sources for one Blender session (rebuilt per hero after the scene reset)."""

    def __init__(self, mats: dict):
        from . import sources
        self.mats = mats
        self.src = sources.build_all()
        self.window = window_group(self.src)
        self.arcade = arcade_group(self.src)
        self.balustrade = balustrade_group(self.src)
        self.cornice = cornice_group()
        self.brackets = brackets_group()
        self.uv1 = uv1_group()
        from . import roof, wall
        self.roof = roof.roof_group()
        self.wall = wall.wall_group()
        self.profiles = {k: profile_object(f"PRF_{k}", v) for k, v in PROFILES.items()}

    def _mod(self, ob, ng, values):
        mod = ob.modifiers.new("GN", "NODES")
        mod.node_group = ng
        set_inputs(mod, values)
        return mod

    def bay_object(self, name, bayset: HB.BaySet, yaw, coll) -> bpy.types.Object:
        ob = bay_points_object(name, bayset.points, yaw, coll)
        vals = dict(bayset.params)
        vals.update({"Wall Material": self.mats[M.PLASTER_SMOOTH], "Trim Material": self.mats[M.FACADE_TRIM],
                     "Glass Material": self.mats[M.TOWER_GLASS]})
        if bayset.generator == "PI_GN_WindowGrid":
            vals.update({"Sill Object": self.src["SRC_Sill"], "Hood Object": self.src["SRC_Hood"],
                         "Keystone Object": self.src["SRC_Keystone"], "Shutter Object": self.src["SRC_Shutter"],
                         "Awning Object": self.src["SRC_Awning"], "Fanlight Object": self.src["SRC_Fanlight"]})
            self._mod(ob, self.window, vals)
        else:
            vals.update({"Keystone Object": self.src["SRC_Keystone"], "Impost Object": self.src["SRC_Impost"]})
            self._mod(ob, self.arcade, vals)
        return ob

    def balustrade_object(self, name, runs, yaw, coll, height=0.95, spacing=0.36) -> bpy.types.Object:
        ob = runs_object(name, runs, yaw, coll)
        self._mod(ob, self.balustrade, {"Height": height, "Spacing": spacing, "Baluster Object": self.src["SRC_Baluster"],
                                        "Post Object": self.src["SRC_BalPost"], "Material": self.mats[M.FACADE_TRIM]})
        return ob

    def moulding_object(self, name, lines, yaw, coll, profile, block, row, material="") -> bpy.types.Object:
        ob = polylines_object(name, lines, yaw, coll)
        if material and material != M.FACADE_TRIM:
            s, o = 0.12, 0.0   # tiling material (roof tiles): a narrow band across the texture
        else:
            s, o = HB.trim_map(block, row)
        self._mod(ob, self.cornice, {"Profile Object": self.profiles[profile], "Material": self.mats[material or M.FACADE_TRIM],
                                     "V Scale": s, "V Offset": o})
        return ob

    def brackets_object(self, name, lines, yaw, coll, spacing=2.1) -> bpy.types.Object:
        ob = polylines_object(name, lines, yaw, coll)
        self._mod(ob, self.brackets, {"Spacing": spacing, "Bracket Object": self.src["SRC_Bracket"]})
        return ob


    def roof_object(self, name, roofs, yaw, coll) -> bpy.types.Object:
        from .roof import roofs_object
        ob = roofs_object(name, roofs, yaw, coll)
        self._mod(ob, self.roof, {"Roof Material": self.mats[M.ROOF_TILE], "Trim Material": self.mats[M.FACADE_TRIM],
                                  "Wall Material": self.mats[M.PLASTER_SMOOTH]})
        return ob

    def wall_object(self, name, runs, yaw, coll, lod, height=1.75) -> bpy.types.Object:
        ob = runs_object(name, runs, yaw, coll)
        self._mod(ob, self.wall, {"Detail": lod, "Height": height, "Pier Spacing": 4.2, "Pier Object": self.src["SRC_WallPier"],
                                  "Gate Pier Object": self.src["SRC_GatePier"], "Wall Material": self.mats[M.PLASTER_SMOOTH],
                                  "Trim Material": self.mats[M.FACADE_TRIM]})
        return ob


def apply_gn(ob, keep_coll=None) -> None:
    """Apply the GN modifier (TDD rule: before the AO bake). With keep_coll, an unapplied copy stays there for
    regeneration in the saved .blend."""
    if keep_coll is not None:
        cp = ob.copy()
        cp.data = ob.data.copy()
        cp.name = ob.name + "_GN"
        keep_coll.objects.link(cp)
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
        for mod in list(ob.modifiers):
            bpy.ops.object.modifier_apply(modifier=mod.name)
