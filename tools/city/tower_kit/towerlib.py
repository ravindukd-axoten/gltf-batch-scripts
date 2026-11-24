"""Tower kit library (P103): Geometry Nodes storey stacker, fin generator, trim-sheet UVs, parts, AO bake, LODs.

Blender 5.3. World axes: +X east, +Y north (Blender), +Z up, 1 unit = 1 m; glTF export turns +Z up into +Y up.
Every tower is built around its own base centre (origin on the ground, plan centre), so the pivot needs no fix-up.

How a tower is made:
  plan curve (open poly, starts mid-edge, CCW)  ->  PI_TowerStoreys (GN): fillet, one ring per storey on a Mesh Line,
  per-storey scale (bulge / taper), ring length `ru`, `storey` and a seeded glazing variant `row`  ->  Curve to Mesh
  with a multi-spline storey profile (each spline = one trim row: slab nose, soffit, glass, balustrade ...) ->
  Python reads `ru`, `pp` (profile position), `pseg` and `row` and writes trim-sheet UVs.
  PI_TowerFins (GN) puts vertical fins / pilasters along the plan at a bay spacing, with a seeded skip for bay variation.
"""
import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

# --- trim sheet T_TowerTrim_A: 1024 x 2048 px, 8 m x 16 m at 128 px/m; v rows in metres from the bottom -----------
SHEET_W_M, SHEET_H_M = 8.0, 16.0
ROWS = {"GLASS0": (0.0, 3.2), "GLASS1": (3.2, 3.2), "GLASS2": (6.4, 3.2),
        "SLAB": (9.6, 0.8), "SOFFIT": (10.4, 1.6), "METAL": (12.0, 0.8), "BALUS": (12.8, 1.2),
        "STONE": (14.0, 0.8), "LOUVRE": (14.8, 0.8), "FAR": (15.6, 0.4)}
GLASS_ROWS = ["GLASS0", "GLASS1", "GLASS2"]
BAY_M = 1.6  # painted mullion bay in the glass rows (8 m / 5)
TEX_DIR = None  # set by towers.py
SRC = "_src"


# --- small helpers ---------------------------------------------------------------------------------------------------
def coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def link(obj, cname):
    coll(cname).objects.link(obj)
    return obj


def poly_curve(name, splines, cname=SRC):
    """Legacy poly curve object from a list of 2D/3D point lists (one spline each)."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    for s in splines:
        sp = cu.splines.new("POLY")
        sp.points.add(len(s) - 1)
        for i, p in enumerate(s):
            sp.points[i].co = (p[0], p[1], p[2] if len(p) > 2 else 0.0, 1.0)
    return link(bpy.data.objects.new(name, cu), cname)


def signed_area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))


def plan_open(pts):
    """Closed polygon -> open CCW polyline that starts and ends at the midpoint of the longest edge.
    The seam then sits on a flat face (no fillet lost, UV `ru` restarts there on split vertices)."""
    pts = [tuple(p) for p in pts]
    if signed_area(pts) < 0:
        pts.reverse()
    n = len(pts)
    k = max(range(n), key=lambda i: (Vector(pts[(i + 1) % n]) - Vector(pts[i])).length)
    a, b = Vector(pts[k]), Vector(pts[(k + 1) % n])
    m = tuple((a + b) / 2)
    ring = [m] + [pts[(k + 1 + i) % n] for i in range(n)] + [m]
    return ring


def rect(w, d):
    return [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]


def notched_rect(w, d, nx, ny, slot=None):
    """Rectangle w (x) by d (y) with re-entrant corner notches nx by ny; optional mid slots (width, depth) on the
    two long (x) faces."""
    hw, hd = w / 2, d / 2
    s = []
    # south face, west to east
    s += [(-hw + nx, -hd)]
    if slot:
        sw, sd = slot
        s += [(-sw / 2, -hd), (-sw / 2, -hd + sd), (sw / 2, -hd + sd), (sw / 2, -hd)]
    s += [(hw - nx, -hd), (hw - nx, -hd + ny), (hw, -hd + ny), (hw, hd - ny), (hw - nx, hd - ny), (hw - nx, hd)]
    if slot:
        s += [(sw / 2, hd), (sw / 2, hd - sd), (-sw / 2, hd - sd), (-sw / 2, hd)]
    s += [(-hw + nx, hd), (-hw + nx, hd - ny), (-hw, hd - ny), (-hw, -hd + ny), (-hw + nx, -hd + ny)]
    return s


def oval(a, b, n, squareness=2.6):
    """Superellipse plan, semi-axes a (x) and b (y), n points; squareness 2 = ellipse, higher = rounder box."""
    out = []
    for i in range(n):
        t = 2 * math.pi * i / n
        c, s = math.cos(t), math.sin(t)
        out.append((a * math.copysign(abs(c) ** (2 / squareness), c), b * math.copysign(abs(s) ** (2 / squareness), s)))
    return out


def scale_pts(pts, sx, sy=None):
    sy = sx if sy is None else sy
    return [(p[0] * sx, p[1] * sy) for p in pts]


# --- profiles ----------------------------------------------------------------------------------------------------------
class Profile:
    """A storey section drawn bottom -> top in (x outward from the plan line, y up). Each segment is its own spline
    (own vertices, own trim row). Curve to Mesh makes a face's normal the profile direction turned 90 degrees
    counter-clockwise, so the splines are written top -> bottom to face outward on a CCW plan."""

    def __init__(self, name, segs, height):
        self.name, self.segs, self.height = name, segs, height  # segs: [((x0,y0),(x1,y1), row)]
        self.obj = None

    def build(self):
        # Curve to Mesh (Z Up normals, CCW ring) maps profile +X outward and profile +Y to world -Z: mirror y.
        splines = [[(p1[0], -p1[1]), (p0[0], -p0[1])] for (p0, p1, _r) in reversed(self.segs)]
        self.obj = poly_curve("PRF_" + self.name, splines)
        self.meta = list(reversed(self.segs))  # spline index -> segment
        return self.obj


def prof_curtain(h, nose=0.15, inset=0.25, band=0.5, band_row="SLAB"):
    """Office curtain wall: slab nose band proud of the glass (band_row METAL: a dark floor line, verticals lead)."""
    return Profile(f"Curtain_{h:.2f}_{band:.2f}_{band_row}", [
        ((-inset, 0.0), (nose, 0.0), "SOFFIT"),
        ((nose, 0.0), (nose, band), band_row),
        ((nose, band), (-inset, band), "SOFFIT"),
        ((-inset, band), (-inset, h), "GLASS"),
    ], h)


def prof_balcony(h, depth=1.4, slab=0.25, rail=1.1, back=0.3):
    """Residential balcony storey: slab projecting `depth` with an upturned glass balustrade, glass `back` behind."""
    x0, x1, t = -back, depth, 0.08
    return Profile(f"Balcony_{h:.2f}_{depth:.2f}", [
        ((x0, 0.0), (x1, 0.0), "SOFFIT"),
        ((x1, 0.0), (x1, slab), "SLAB"),
        ((x1, slab), (x1, slab + rail), "BALUS"),
        ((x1, slab + rail), (x1 - t, slab + rail), "SLAB"),
        ((x1 - t, slab + rail), (x1 - t, slab + 0.02), "BALUS"),
        ((x1 - t, slab + 0.02), (x0, slab + 0.02), "SOFFIT"),
        ((x0, slab + 0.02), (x0, h), "GLASS"),
    ], h)


def prof_balcony_lod1(h, depth=1.4, slab=0.25, rail=1.1, back=0.3):
    """LOD1: balcony as a slab plus a solid balustrade band (4 segments instead of 7)."""
    x0, x1 = -back, depth
    return Profile(f"BalconyL1_{h:.2f}_{depth:.2f}", [
        ((x0, 0.0), (x1, 0.0), "SOFFIT"),
        ((x1, 0.0), (x1, slab), "SLAB"),
        ((x1, slab), (x1, slab + rail), "BALUS"),
        ((x1, slab + rail), (x0, slab + rail), "SOFFIT"),
        ((x0, slab + rail), (x0, h), "GLASS"),
    ], h)


def prof_grid(h, nose=0.5, inset=0.45, band=0.7):
    """Hotel: deep white floor band over recessed dark glass."""
    return Profile(f"Grid_{h:.2f}", [
        ((-inset, 0.0), (nose, 0.0), "SOFFIT"),
        ((nose, 0.0), (nose, band), "SLAB"),
        ((nose, band), (-inset, band), "SLAB"),
        ((-inset, band), (-inset, h), "GLASS"),
    ], h)


def prof_flat(h, row="GLASS", x=0.0):
    return Profile(f"Flat_{row}_{h:.2f}_{x:.2f}", [((x, 0.0), (x, h), row)], h)


def prof_lobby(h, inset=0.6, canopy=0.0):
    """Double-height lobby: stone plinth, deep-set glass, stone head band."""
    segs = [((0.0, 0.0), (0.0, 0.6), "STONE"), ((0.0, 0.6), (-inset, 0.6), "SOFFIT"),
            ((-inset, 0.6), (-inset, h - 1.2), "GLASS2"), ((-inset, h - 1.2), (0.0, h - 1.2), "SOFFIT"),  # busiest row: lit lobby
            ((0.0, h - 1.2), (0.0, h), "STONE")]
    return Profile(f"Lobby_{h:.2f}", segs, h)


# --- Geometry Nodes ---------------------------------------------------------------------------------------------------
def _sock(ng, name, kind, io="INPUT", default=None, minv=None):
    s = ng.interface.new_socket(name, in_out=io, socket_type=kind)
    if default is not None:
        s.default_value = default
    if minv is not None:
        s.min_value = minv
    return s


def storeys_group():
    """PI_TowerStoreys: plan + profile -> stacked storey rings with per-storey scale, ring length and variant."""
    ng = bpy.data.node_groups.get("PI_TowerStoreys")
    if ng:
        return ng
    ng = bpy.data.node_groups.new("PI_TowerStoreys", "GeometryNodeTree")
    _sock(ng, "Geometry", "NodeSocketGeometry")
    for nm, kind, dv in [("Plan", "NodeSocketObject", None), ("Profile", "NodeSocketObject", None),
                         ("Storeys", "NodeSocketInt", 10), ("Storey Height", "NodeSocketFloat", 3.5),
                         ("Base Z", "NodeSocketFloat", 0.0), ("Bulge", "NodeSocketFloat", 0.0),
                         ("Taper", "NodeSocketFloat", 0.0), ("Fillet Radius", "NodeSocketFloat", 0.5),
                         ("Fillet Count", "NodeSocketInt", 1), ("Variants", "NodeSocketInt", 4),
                         ("Seed", "NodeSocketInt", 0)]:
        _sock(ng, nm, kind, default=dv)
    _sock(ng, "Geometry", "NodeSocketGeometry", io="OUTPUT")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    def math_node(op, a=None, b=None, vtype="ShaderNodeMath"):
        n = N.new(vtype)
        n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                L.new(v, n.inputs[i])
        return n.outputs[0]

    plan = N.new("GeometryNodeObjectInfo")
    L.new(gi.outputs["Plan"], plan.inputs["Object"])
    fil = N.new("GeometryNodeFilletCurve")
    fil.inputs["Mode"].default_value = "Poly"
    fil.inputs["Limit Radius"].default_value = True
    L.new(plan.outputs["Geometry"], fil.inputs["Curve"])
    L.new(gi.outputs["Fillet Radius"], fil.inputs["Radius"])
    L.new(gi.outputs["Fillet Count"], fil.inputs["Count"])
    # storey points
    line = N.new("GeometryNodeMeshLine")
    L.new(gi.outputs["Storeys"], line.inputs["Count"])
    comb0 = N.new("ShaderNodeCombineXYZ")
    L.new(gi.outputs["Base Z"], comb0.inputs["Z"])
    L.new(comb0.outputs[0], line.inputs["Start Location"])
    comb1 = N.new("ShaderNodeCombineXYZ")
    L.new(gi.outputs["Storey Height"], comb1.inputs["Z"])
    L.new(comb1.outputs[0], line.inputs["Offset"])
    inst = N.new("GeometryNodeInstanceOnPoints")
    L.new(line.outputs[0], inst.inputs["Points"])
    L.new(fil.outputs[0], inst.inputs["Instance"])
    # per-storey scale: (1 + bulge * sin(pi t)) * (1 - taper * t), t = index / (storeys - 1)
    idx = N.new("GeometryNodeInputIndex")
    nm1 = math_node("MAXIMUM", math_node("SUBTRACT", gi.outputs["Storeys"], 1.0), 1.0)
    t = math_node("DIVIDE", idx.outputs[0], nm1)
    bul = math_node("ADD", math_node("MULTIPLY", gi.outputs["Bulge"], math_node("SINE", math_node("MULTIPLY", t, math.pi))), 1.0)
    tap = math_node("SUBTRACT", 1.0, math_node("MULTIPLY", gi.outputs["Taper"], t))
    s = math_node("MULTIPLY", bul, tap)
    comb2 = N.new("ShaderNodeCombineXYZ")
    L.new(s, comb2.inputs["X"])
    L.new(s, comb2.inputs["Y"])
    comb2.inputs["Z"].default_value = 1.0
    sc = N.new("GeometryNodeScaleInstances")
    L.new(inst.outputs[0], sc.inputs["Instances"])
    L.new(comb2.outputs[0], sc.inputs["Scale"])
    real = N.new("GeometryNodeRealizeInstances")
    L.new(sc.outputs[0], real.inputs["Geometry"])
    # ring attributes: ru (length along the ring), storey (ring index), row (seeded glazing variant)
    sp = N.new("GeometryNodeSplineParameter")
    st_ru = N.new("GeometryNodeStoreNamedAttribute")
    st_ru.data_type = "FLOAT"
    st_ru.inputs["Name"].default_value = "ru"
    L.new(real.outputs[0], st_ru.inputs["Geometry"])
    L.new(sp.outputs["Length"], st_ru.inputs["Value"])
    ev = N.new("GeometryNodeFieldOnDomain")
    ev.domain = "CURVE"
    ev.data_type = "INT"
    idx2 = N.new("GeometryNodeInputIndex")
    L.new(idx2.outputs[0], ev.inputs[0])
    st_s = N.new("GeometryNodeStoreNamedAttribute")
    st_s.data_type = "INT"
    st_s.inputs["Name"].default_value = "storey"
    L.new(st_ru.outputs[0], st_s.inputs["Geometry"])
    L.new(ev.outputs[0], st_s.inputs["Value"])
    rnd = N.new("FunctionNodeRandomValue")
    rnd.data_type = "INT"
    rnd.inputs["Min"].default_value = 0
    L.new(math_node("SUBTRACT", gi.outputs["Variants"], 1.0), rnd.inputs["Max"])
    L.new(ev.outputs[0], rnd.inputs["ID"])
    L.new(gi.outputs["Seed"], rnd.inputs["Seed"])
    st_r = N.new("GeometryNodeStoreNamedAttribute")
    st_r.data_type = "INT"
    st_r.inputs["Name"].default_value = "row"
    L.new(st_s.outputs[0], st_r.inputs["Geometry"])
    L.new(rnd.outputs["Value"], st_r.inputs["Value"])
    nrm = N.new("GeometryNodeSetCurveNormal")
    nrm.inputs["Mode"].default_value = "Z Up"
    L.new(st_r.outputs[0], nrm.inputs["Curve"])
    # profile with its own attributes: pp (profile position), pseg (spline index = trim row segment)
    prof = N.new("GeometryNodeObjectInfo")
    L.new(gi.outputs["Profile"], prof.inputs["Object"])
    pos = N.new("GeometryNodeInputPosition")
    st_pp = N.new("GeometryNodeStoreNamedAttribute")
    st_pp.data_type = "FLOAT_VECTOR"
    st_pp.inputs["Name"].default_value = "pp"
    L.new(prof.outputs["Geometry"], st_pp.inputs["Geometry"])
    L.new(pos.outputs[0], st_pp.inputs["Value"])
    ev2 = N.new("GeometryNodeFieldOnDomain")
    ev2.domain = "CURVE"
    ev2.data_type = "INT"
    idx3 = N.new("GeometryNodeInputIndex")
    L.new(idx3.outputs[0], ev2.inputs[0])
    st_ps = N.new("GeometryNodeStoreNamedAttribute")
    st_ps.data_type = "INT"
    st_ps.inputs["Name"].default_value = "pseg"
    L.new(st_pp.outputs[0], st_ps.inputs["Geometry"])
    L.new(ev2.outputs[0], st_ps.inputs["Value"])
    c2m = N.new("GeometryNodeCurveToMesh")
    c2m.inputs["Miter Scale"].default_value = True
    c2m.inputs["Miter Scale Limit"].default_value = 3.0
    L.new(nrm.outputs[0], c2m.inputs["Curve"])
    L.new(st_ps.outputs[0], c2m.inputs["Profile Curve"])
    L.new(c2m.outputs[0], go.inputs[0])
    return ng


def fins_group():
    """PI_TowerFins: vertical fins / pilasters along the (filleted) plan every `Spacing` m, rotated to the facade,
    from Base Z to Top Z; a seeded `Skip` fraction drops fins for bay rhythm variation."""
    ng = bpy.data.node_groups.get("PI_TowerFins")
    if ng:
        return ng
    ng = bpy.data.node_groups.new("PI_TowerFins", "GeometryNodeTree")
    _sock(ng, "Geometry", "NodeSocketGeometry")
    for nm, kind, dv in [("Plan", "NodeSocketObject", None), ("Fin", "NodeSocketObject", None),
                         ("Spacing", "NodeSocketFloat", 3.0), ("Skip", "NodeSocketFloat", 0.0),
                         ("Seed", "NodeSocketInt", 0), ("Fillet Radius", "NodeSocketFloat", 0.5),
                         ("Fillet Count", "NodeSocketInt", 1)]:
        _sock(ng, nm, kind, default=dv)
    _sock(ng, "Geometry", "NodeSocketGeometry", io="OUTPUT")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    plan = N.new("GeometryNodeObjectInfo")
    L.new(gi.outputs["Plan"], plan.inputs["Object"])
    fil = N.new("GeometryNodeFilletCurve")
    fil.inputs["Mode"].default_value = "Poly"
    fil.inputs["Limit Radius"].default_value = True
    L.new(plan.outputs["Geometry"], fil.inputs["Curve"])
    L.new(gi.outputs["Fillet Radius"], fil.inputs["Radius"])
    L.new(gi.outputs["Fillet Count"], fil.inputs["Count"])
    c2p = N.new("GeometryNodeCurveToPoints")
    c2p.mode = "LENGTH"
    L.new(fil.outputs[0], c2p.inputs["Curve"])
    L.new(gi.outputs["Spacing"], c2p.inputs["Length"])
    fin = N.new("GeometryNodeObjectInfo")
    L.new(gi.outputs["Fin"], fin.inputs["Object"])
    rnd = N.new("FunctionNodeRandomValue")
    rnd.data_type = "BOOLEAN"
    L.new(gi.outputs["Skip"], rnd.inputs["Probability"])
    L.new(gi.outputs["Seed"], rnd.inputs["Seed"])
    notn = N.new("FunctionNodeBooleanMath")
    notn.operation = "NOT"
    L.new(rnd.outputs[3] if len(rnd.outputs) > 3 else rnd.outputs["Value"], notn.inputs[0])
    inst = N.new("GeometryNodeInstanceOnPoints")
    L.new(c2p.outputs["Points"], inst.inputs["Points"])
    L.new(notn.outputs[0], inst.inputs["Selection"])
    L.new(fin.outputs["Geometry"], inst.inputs["Instance"])
    L.new(c2p.outputs["Rotation"], inst.inputs["Rotation"])
    real = N.new("GeometryNodeRealizeInstances")
    L.new(inst.outputs[0], real.inputs["Geometry"])
    L.new(real.outputs[0], go.inputs[0])
    return ng


def gn_object(name, group, values):
    me = bpy.data.meshes.new(name)
    obj = link(bpy.data.objects.new(name, me), SRC)
    # Blender 5.3 modifiers take no ID properties from Python: wrap the generator in a one-node tree whose group
    # node carries this object's input values.
    w = bpy.data.node_groups.new("W_" + name, "GeometryNodeTree")
    _sock(w, "Geometry", "NodeSocketGeometry")
    _sock(w, "Geometry", "NodeSocketGeometry", io="OUTPUT")
    gnode = w.nodes.new("GeometryNodeGroup")
    gnode.node_tree = group
    for k, v in values.items():
        gnode.inputs[k].default_value = v
    w.links.new(gnode.outputs[0], w.nodes.new("NodeGroupOutput").inputs[0])
    md = obj.modifiers.new("gen", "NODES")
    md.node_group = w
    return obj


def evaluated_mesh(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    return bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)


# --- UVs ----------------------------------------------------------------------------------------------------------
def row_uv(row, u_m, t, t_len):
    """u in metres along the facade; t in metres across the row. A segment no taller than the row maps at true
    scale, anchored to the row top (lit lip and rail sit there); a longer one is stretched over the row."""
    v0, rh = ROWS[row]
    t = max(0.0, min(t_len, t))
    if t_len <= rh:
        tt = rh - t_len + t
    else:
        tt = t / t_len * rh
    return (u_m / SHEET_W_M, (v0 + tt) / SHEET_H_M)


def storeys_mesh(name, plan_pts, profile, storeys, h, z0, seed, bulge=0.0, taper=0.0, fr=0.5, fc=1,
                 far=False, far_group=1):
    """Run PI_TowerStoreys and return a bmesh-ready Mesh with trim UVs."""
    plan = poly_curve("PLN_" + name, [plan_open(plan_pts)])
    if profile.obj is None:
        profile.build()
    g = gn_object("GEN_" + name, storeys_group(), {
        "Plan": plan, "Profile": profile.obj, "Storeys": storeys, "Storey Height": h, "Base Z": z0,
        "Bulge": bulge, "Taper": taper, "Fillet Radius": fr, "Fillet Count": fc, "Variants": len(GLASS_ROWS), "Seed": seed})
    me = evaluated_mesh(g)
    me.name = "ME_" + name
    ru = me.attributes["ru"].data
    pp = me.attributes["pp"].data
    ps = me.attributes["pseg"].data
    st = me.attributes["storey"].data
    rw = me.attributes["row"].data
    uvl = me.uv_layers.new(name="UVMap")
    rng = random.Random(seed)
    shifts = [rng.randrange(5) * BAY_M for _ in range(storeys + 1)]
    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            seg = profile.meta[ps[vi].value]
            (x0, y0), (x1, y1), row = seg
            p = (pp[vi].vector[0], -pp[vi].vector[1])  # stored profile is mirrored in y (Profile.build)
            if row == "GLASS":
                row = "FAR" if far else GLASS_ROWS[rw[vi].value]
            u = ru[vi].value + (0.0 if far else shifts[st[vi].value])
            if abs(y1 - y0) >= abs(x1 - x0):
                t, tl = p[1] - min(y0, y1), abs(y1 - y0)
            else:
                t, tl = p[0] - min(x0, x1), abs(x1 - x0)
            uvl.data[li].uv = row_uv(row, u, t, tl)
    for k in ("ru", "pp", "pseg", "storey", "row"):
        me.attributes.remove(me.attributes[k])
    return me


def fins_mesh(name, plan_pts, spacing, width, depth, z0, z1, seed, row="SLAB", skip=0.0, fr=0.5, fc=1, out=0.0):
    """Fins from PI_TowerFins. Curve to Points frame on a CCW plan (measured): local +X = outward normal,
    local -Y = world up, local +Z = tangent. The fin source box is built in that frame."""
    plan = poly_curve("PLN_" + name, [plan_open(plan_pts)])
    bm = bmesh.new()
    res = bmesh.ops.create_cube(bm, size=1.0)
    x0, x1 = out - 0.3, out + depth
    for v in res["verts"]:
        v.co = Vector(((x0 + x1) / 2 + v.co.x * (x1 - x0), -((z0 + z1) / 2 + v.co.y * (z1 - z0)), v.co.z * width))
    fin_me = bpy.data.meshes.new("FINSRC_" + name)
    bm.to_mesh(fin_me)
    bm.free()
    fin = link(bpy.data.objects.new("FIN_" + name, fin_me), SRC)
    g = gn_object("GENF_" + name, fins_group(), {"Plan": plan, "Fin": fin, "Spacing": spacing, "Skip": skip,
                                                   "Seed": seed, "Fillet Radius": fr, "Fillet Count": fc})
    me = evaluated_mesh(g)
    me.name = "ME_" + name
    box_uv(me, row, kill_bottom=True)
    return me


def box_uv(me, row, kill_bottom=False, kill_top=False, u_shift=0.0):
    """World-space trim UVs for box-like parts: per face, the longer in-face axis runs along u, the other is
    stretched across the row. Optionally deletes down/up facing faces (never seen)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    kill = [f for f in bm.faces if (kill_bottom and f.normal.z < -0.9) or (kill_top and f.normal.z > 0.9)]
    if kill:
        bmesh.ops.delete(bm, geom=kill, context="FACES")
    uv = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        n = f.normal
        if abs(n.z) > 0.9:
            ax = [Vector((1, 0, 0)), Vector((0, 1, 0))]
        else:
            ax = [Vector((0, 0, 1)), Vector((-n.y, n.x, 0)).normalized()]
        ext = []
        for a in ax:
            d = [l.vert.co.dot(a) for l in f.loops]
            ext.append((min(d), max(d) - min(d)))
        ia = 0 if ext[0][1] >= ext[1][1] else 1
        a_u, a_t = ax[ia], ax[1 - ia]
        tmin, tl = ext[1 - ia]
        for l in f.loops:
            l[uv].uv = row_uv(row, l.vert.co.dot(a_u) + u_shift, l.vert.co.dot(a_t) - tmin, tl)
    bm.to_mesh(me)
    bm.free()
    return me


def box_mesh(name, center, size, row, rot_z=0.0, top=True, bottom=False):
    """Axis box (optionally turned about Z) with trim-row UVs."""
    bm = bmesh.new()
    res = bmesh.ops.create_cube(bm, size=1.0)
    for v in res["verts"]:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    if rot_z:
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(rot_z, 3, "Z"))
    bmesh.ops.translate(bm, verts=bm.verts, vec=Vector(center))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return box_uv(me, row, kill_bottom=not bottom, kill_top=not top)


def quad_mesh(name, center, w, h, yaw, out_offset=0.0):
    """Vertical ad face, w x h, facing along `yaw` (radians from +X), UV 0-1 (own quad, sponsor slot)."""
    bm = bmesh.new()
    d = Vector((math.cos(yaw), math.sin(yaw), 0))
    t = Vector((-d.y, d.x, 0))
    c = Vector(center) + d * out_offset
    vs = [bm.verts.new(c - t * w / 2 + Vector((0, 0, -h / 2))), bm.verts.new(c + t * w / 2 + Vector((0, 0, -h / 2))),
          bm.verts.new(c + t * w / 2 + Vector((0, 0, h / 2))), bm.verts.new(c - t * w / 2 + Vector((0, 0, h / 2)))]
    f = bm.faces.new(vs)
    if f.normal.dot(d) < 0:
        f.normal_flip()
    uv = bm.loops.layers.uv.new("UVMap")
    for l in f.loops:
        p = l.vert.co - c
        l[uv].uv = (p.dot(t) / w + 0.5, p.z / h + 0.5)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


# --- assembly ---------------------------------------------------------------------------------------------------------
def join_meshes(name, parts, cname):
    """parts: list of (Mesh, material_index). Returns one object; pieces keep their own vertices (hard edges between
    trim rows), then vertices closer than 0.1 mm are merged so the welded shell is what the validator sees."""
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    for me, mi in parts:
        tmp = bmesh.new()
        tmp.from_mesh(me)
        src_uv = tmp.loops.layers.uv.get("UVMap") or tmp.loops.layers.uv.active
        vmap = {v: bm.verts.new(v.co) for v in tmp.verts}
        for f in tmp.faces:
            try:
                nf = bm.faces.new([vmap[v] for v in f.verts])
            except ValueError:
                continue
            nf.material_index = mi
            for la, lb in zip(f.loops, nf.loops):
                lb[uvl].uv = la[src_uv].uv if src_uv else (0, 0)
        tmp.free()
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    zero = [f for f in bm.faces if f.calc_area() < 1e-6]
    if zero:
        bmesh.ops.delete(bm, geom=zero, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me), cname)
    return obj


def shade(obj, angle=35.0):
    for p in obj.data.polygons:
        p.use_smooth = True
    obj.data.set_sharp_from_angle(angle=math.radians(angle)) if hasattr(obj.data, "set_sharp_from_angle") else None


def tri_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def bake_ao_vertex(objs, samples=24, distance=6.0):
    """Cycles AO into a byte colour attribute (exported as COLOR_0; AO in RGB, A = 1)."""
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.world = sc.world or bpy.data.worlds.new("W")
    sc.world.light_settings.distance = distance
    for o in objs:
        ca = o.data.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
        o.data.color_attributes.active_color = ca
        o.data.color_attributes.render_color_index = o.data.color_attributes.active_color_index
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
