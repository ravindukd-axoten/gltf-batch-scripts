"""Road edge kit (P92) builder library, run inside Blender 5.3 (MCP execute_python or `blender -b -P build_kit.py`).

Shapes come from Blender-native tools, not vertex placement:
- kerbs, channels, dropped kerbs: a cross-section profile (the measured points of ROAD_EDGE_KIT_SPEC.md §1) swept by
  the Geometry Nodes group `PI_EdgeSweep` along a path: Fillet Curve rounds the nose, the path is resampled into
  blocks (real 5 mm joints), each block is Curve to Mesh with filled caps, jittered a few millimetres by seed, realised;
  UVs are stored by the node tree (u = distance along the path / 4 m, v = trim row + distance along the profile / 8 m).
- slabs, covers, grates, plinths: primitives + Bevel / Inset / Solidify / Array modifiers and Weighted Normal.
Blender axes: +X along the piece (east when placed unrotated), +Y north/back of kerb, +Z up, metres.
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

SHEET_U_M, SHEET_V_M = 4.0, 8.0                 # trim sheet covers 4 m x 8 m (1024 x 2048 px, 256 px/m)
ROW = {"kerbA": 0.0, "kerbB": 0.5, "kerbC": 1.0, "channel": 1.5, "foot": 2.0, "tiles": 3.0, "decal": 4.0,
       "border": 7.498}   # P92b: border sides run down to z 0 (pivot at base); top stays at v 7.65-7.95
MAT_NAME = "MAT_RoadEdgeTrim_A"

# Profiles (y across: road at -y, z up; pivot = kerb face foot on the road surface). r = fillet radius.
# Read from the photos (spec §1): 0.15 upstand, 0.22-0.30 top, battered face, rounded or chamfered nose.
PROFILES = {
    # granite, rounded nose, 0.26 top, 15 mm batter (sv_03, sv_15)
    "kerbA": [(0.000, -0.05, 0), (0.000, 0.000, 0), (0.015, 0.150, 0.035), (0.260, 0.150, 0.008),
              (0.260, 0.080, 0)],
    # precast concrete, 25 mm batter + 25 mm 45-degree chamfer, 0.24 top (land side, gf_21, gf_23)
    "kerbB": [(0.000, -0.05, 0), (0.000, 0.000, 0), (0.022, 0.122, 0.004), (0.050, 0.150, 0.004),
              (0.240, 0.150, 0.006), (0.240, 0.080, 0)],
    # painted junction kerb: half-round 50 mm nose, 0.16 upstand, 0.22 top
    "kerbC": [(0.000, -0.05, 0), (0.000, 0.000, 0), (0.008, 0.160, 0.05), (0.220, 0.160, 0.01),
              (0.220, 0.080, 0)],
    # concrete channel (gutter) 0.35 m, dished 4 mm, sits 6-10 mm proud of the asphalt with a skirt
    "channel": [(-0.360, -0.02, 0), (-0.355, 0.006, 0.004), (-0.180, 0.003, 0), (0.000, 0.010, 0),
                (0.000, -0.02, 0)],
    # grey paver border course behind kerb A: 0.30 m (three 100 mm stretcher rows), flush with the footway (sv_03,
    # sv_05). The back-of-kerb face first (down to z 0, hidden below 0.102), so the top maps onto sheet v 7.65-7.95 (the drawn paver rows).
    # Top 2 mm proud of the 0.15 m footway so the 1.5 mm settle jitter never sinks it into a coplanar footway mesh.
    "border": [(0.255, 0.0, 0), (0.255, 0.152, 0), (0.555, 0.152, 0), (0.555, 0.0, 0)],
}
LOD1_PROFILES = {
    "kerbA": [(0.0, -0.02), (0.012, 0.15), (0.26, 0.15), (0.26, 0.08)],
    "kerbB": [(0.0, -0.02), (0.03, 0.15), (0.24, 0.15), (0.24, 0.08)],
    "kerbC": [(0.0, -0.02), (0.02, 0.16), (0.22, 0.16), (0.22, 0.08)],
    "channel": [(-0.36, 0.006), (0.0, 0.01)],
    "border": [(0.255, 0.0), (0.255, 0.152), (0.555, 0.152), (0.555, 0.0)],
}


# --- scene helpers -------------------------------------------------------------------------------------------------

def coll(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    p = parent or bpy.context.scene.collection
    if c.name not in [x.name for x in p.children]:
        p.children.link(c)
    return c


def material() -> bpy.types.Material:
    m = bpy.data.materials.get(MAT_NAME)
    if m is None:
        m = bpy.data.materials.new(MAT_NAME)
        m.use_nodes = True
    return m


def curve_obj(name: str, pts, cyclic=False, radii=None, c=None) -> bpy.types.Object:
    """A poly curve object (path or profile). Profiles keep the fillet radius on the point radius."""
    cu = bpy.data.curves.get(name) or bpy.data.curves.new(name, "CURVE")
    cu.splines.clear()
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        sp.points[i].co = (p[0], p[1], p[2] if len(p) > 2 else 0.0, 1.0)
        sp.points[i].radius = radii[i] if radii else 1.0
    sp.use_cyclic_u = cyclic
    ob = bpy.data.objects.get(name) or bpy.data.objects.new(name, cu)
    if c is not None and ob.name not in c.objects:
        c.objects.link(ob)
    ob.hide_render = True
    return ob


def profile_obj(key: str, lod: int, c) -> bpy.types.Object:
    if lod == 0:
        pts = PROFILES[key]
        # profile in the curve's XY plane: x = across (y of the piece), y = up (z of the piece)
        return curve_obj(f"PRF_{key}", [(y, z, 0) for y, z, _ in pts], cyclic=key != "channel",
                         radii=[r for _, _, r in pts], c=c)
    pts = LOD1_PROFILES[key]
    return curve_obj(f"PRF_{key}_LOD1", [(y, z, 0) for y, z in pts], cyclic=False, radii=[0.0] * len(pts), c=c)


def path_line(name, length, c):
    return curve_obj(name, [(0, 0, 0), (length, 0, 0)], c=c)


def path_arc(name, radius, degrees, c, turn=1, steps=48):
    """Arc starting at the origin heading +X; turn=+1 bends towards +Y (kerb on the inside: external corner),
    -1 towards -Y."""
    pts = []
    for i in range(steps + 1):
        a = math.radians(degrees) * i / steps
        pts.append((radius * math.sin(a), turn * radius * (1 - math.cos(a)), 0))
    return curve_obj(name, pts, c=c)


# --- the sweep node group -------------------------------------------------------------------------------------------

def _n(t, kind, loc=(0, 0), **props):
    node = t.nodes.new(kind)
    node.location = loc
    for k, v in props.items():
        setattr(node, k, v)
    return node


def _math(t, op, a=None, b=None, loc=(0, 0)):
    n = _n(t, "ShaderNodeMath", loc, operation=op)
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            t.links.new(v, n.inputs[i])
    return n.outputs[0]


def sweep_group() -> bpy.types.NodeTree:
    """PI_EdgeSweep: path + profile -> jointed, capped, jittered blocks with UVs.

    Inputs: Path, Profile (objects), Block (m), Gap (m), Jitter (m), Seed, Fillet Count, Row (m),
    Drop Start / Drop End (upstand scale at the path start / end, 1 = full kerb), Path Length (m).
    """
    name = "PI_EdgeSweep"
    if name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[name])
    t = bpy.data.node_groups.new(name, "GeometryNodeTree")
    t.is_modifier = True
    io = t.interface
    io.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for nm, st, dv in (("Path", "NodeSocketObject", None), ("Profile", "NodeSocketObject", None),
                       ("Block", "NodeSocketFloat", 0.5), ("Gap", "NodeSocketFloat", 0.005),
                       ("Jitter", "NodeSocketFloat", 0.003), ("Seed", "NodeSocketInt", 0),
                       ("Fillet Count", "NodeSocketInt", 3), ("Row", "NodeSocketFloat", 0.0),
                       ("Drop Start", "NodeSocketFloat", 1.0), ("Drop End", "NodeSocketFloat", 1.0),
                       ("Path Length", "NodeSocketFloat", 1.0)):
        s = io.new_socket(nm, in_out="INPUT", socket_type=st)
        if dv is not None:
            s.default_value = dv
    gi = _n(t, "NodeGroupInput", (-1800, 0))
    go = _n(t, "NodeGroupOutput", (1800, 0))
    L = t.links.new

    # path -> resample into n+1 points (n blocks of about Block metres)
    pinfo = _n(t, "GeometryNodeObjectInfo", (-1600, 300), transform_space="RELATIVE")
    L(gi.outputs["Path"], pinfo.inputs["Object"])
    count = _math(t, "DIVIDE", gi.outputs["Path Length"], gi.outputs["Block"], (-1600, 100))
    count = _math(t, "ROUND", count, None, (-1450, 100))
    count = _math(t, "MAXIMUM", count, 1.0, (-1300, 100))
    count = _math(t, "ADD", count, 1.0, (-1150, 100))
    res = _n(t, "GeometryNodeResampleCurve", (-1000, 300))
    L(pinfo.outputs["Geometry"], res.inputs["Curve"])
    L(count, res.inputs["Count"])
    spar = _n(t, "GeometryNodeSplineParameter", (-1000, 0))
    cap = _n(t, "GeometryNodeCaptureAttribute", (-800, 300))
    cap.capture_items.new("FLOAT", "plen")
    L(res.outputs[0], cap.inputs[0])
    L(spar.outputs["Length"], cap.inputs["plen"])
    c2m = _n(t, "GeometryNodeCurveToMesh", (-600, 300))
    L(cap.outputs[0], c2m.inputs["Curve"])
    # edge midpoints, direction and length
    ev = _n(t, "GeometryNodeInputMeshEdgeVertices", (-600, 0))
    d = _n(t, "ShaderNodeVectorMath", (-400, 0), operation="SUBTRACT")
    L(ev.outputs["Position 2"], d.inputs[0])
    L(ev.outputs["Position 1"], d.inputs[1])
    elen = _n(t, "ShaderNodeVectorMath", (-250, -100), operation="LENGTH")
    L(d.outputs[0], elen.inputs[0])
    mid = _n(t, "GeometryNodeFieldOnDomain", (-400, -250), domain="EDGE", data_type="FLOAT")
    L(cap.outputs["plen"], mid.inputs[0])
    m2p = _n(t, "GeometryNodeMeshToPoints", (-200, 300), mode="EDGES")
    L(c2m.outputs[0], m2p.inputs["Mesh"])
    cap2 = _n(t, "GeometryNodeCaptureAttribute", (-50, 300), domain="EDGE")
    for nm, ty in (("dir", "VECTOR"), ("elen", "FLOAT"), ("mid", "FLOAT")):
        cap2.capture_items.new(ty, nm)
    L(c2m.outputs[0], cap2.inputs[0])
    L(d.outputs[0], cap2.inputs["dir"])
    L(elen.outputs["Value"], cap2.inputs["elen"])
    L(mid.outputs[0], cap2.inputs["mid"])
    # points from the captured mesh (capture first, then points, so the fields travel)
    L(cap2.outputs[0], m2p.inputs["Mesh"])

    # block mesh: unit line (-0.5..0.5 in x) swept by the filleted profile, caps filled
    prf = _n(t, "GeometryNodeObjectInfo", (-800, -500), transform_space="ORIGINAL")
    L(gi.outputs["Profile"], prf.inputs["Object"])
    fil = _n(t, "GeometryNodeFilletCurve", (-600, -500))
    if "Mode" in fil.inputs:                      # Blender 5.x: menu socket
        fil.inputs["Mode"].default_value = "Poly"
    else:
        fil.mode = "POLY"
    L(prf.outputs["Geometry"], fil.inputs["Curve"])
    rad = _n(t, "GeometryNodeInputRadius", (-800, -700))
    L(rad.outputs[0], fil.inputs["Radius"])
    if "Count" in fil.inputs:
        L(gi.outputs["Fillet Count"], fil.inputs["Count"])
    # profile curve lies in XY (x across, y up); rotate so it is a YZ section for Curve to Mesh along +X:
    # Curve to Mesh maps profile X -> path normal, profile Y -> path binormal; handled by the line's tilt below.
    spar2 = _n(t, "GeometryNodeSplineParameter", (-450, -700))
    capv = _n(t, "GeometryNodeStoreNamedAttribute", (-400, -500), domain="POINT", data_type="FLOAT")
    capv.inputs["Name"].default_value = "vlen"
    L(fil.outputs[0], capv.inputs["Geometry"])
    L(spar2.outputs["Length"], capv.inputs["Value"])
    line = _n(t, "GeometryNodeCurvePrimitiveLine", (-450, -300))
    line.inputs["Start"].default_value = (-0.5, 0, 0)
    line.inputs["End"].default_value = (0.5, 0, 0)
    spar3 = _n(t, "GeometryNodeSplineParameter", (-300, -300))
    capu = _n(t, "GeometryNodeStoreNamedAttribute", (-250, -300), domain="POINT", data_type="FLOAT")
    capu.inputs["Name"].default_value = "uloc"
    L(line.outputs[0], capu.inputs["Geometry"])
    L(spar3.outputs["Factor"], capu.inputs["Value"])
    blk = _n(t, "GeometryNodeCurveToMesh", (-50, -400))
    L(capu.outputs[0], blk.inputs["Curve"])
    L(capv.outputs[0], blk.inputs["Profile Curve"])
    blk.inputs["Fill Caps"].default_value = True
    # Curve to Mesh along +X puts the profile's (x, y) on (-y, -z): turn it 180 degrees about X so profile x is
    # the piece's +y (back of kerb) and profile y is +z (up)
    flip = _n(t, "GeometryNodeTransform", (100, -400))
    L(blk.outputs[0], flip.inputs["Geometry"])
    flip.inputs["Rotation"].default_value = (math.pi, 0.0, 0.0)

    # instance blocks on the edge midpoints, scaled to edge length minus the joint gap
    rot = _n(t, "FunctionNodeAlignRotationToVector", (150, 100), axis="X", pivot_axis="Z")
    L(cap2.outputs["dir"], rot.inputs["Vector"])
    blen = _math(t, "SUBTRACT", cap2.outputs["elen"], gi.outputs["Gap"], (150, -100))
    scl = _n(t, "ShaderNodeCombineXYZ", (300, -100))
    L(blen, scl.inputs[0])
    scl.inputs[1].default_value = 1.0
    scl.inputs[2].default_value = 1.0
    iop = _n(t, "GeometryNodeInstanceOnPoints", (450, 300))
    L(m2p.outputs[0], iop.inputs["Points"])
    L(flip.outputs[0], iop.inputs["Instance"])
    L(rot.outputs[0], iop.inputs["Rotation"])
    L(scl.outputs[0], iop.inputs["Scale"])
    # per-block u start and length as instance attributes
    u0 = _math(t, "MULTIPLY", blen, 0.5, (300, -250))
    u0 = _math(t, "SUBTRACT", cap2.outputs["mid"], u0, (450, -250))
    sti = _n(t, "GeometryNodeStoreNamedAttribute", (650, 300), domain="INSTANCE", data_type="FLOAT")
    sti.inputs["Name"].default_value = "u0"
    L(iop.outputs[0], sti.inputs["Geometry"])
    L(u0, sti.inputs["Value"])
    sti2 = _n(t, "GeometryNodeStoreNamedAttribute", (800, 300), domain="INSTANCE", data_type="FLOAT")
    sti2.inputs["Name"].default_value = "blen"
    L(sti.outputs[0], sti2.inputs["Geometry"])
    L(blen, sti2.inputs["Value"])
    # settle jitter: a few mm of lift and a fraction of a degree of tilt per block, by seed
    rz = _n(t, "FunctionNodeRandomValue", (650, 0), data_type="FLOAT")
    L(gi.outputs["Seed"], rz.inputs["Seed"])
    rz.inputs["Min"].default_value = -1.0
    rz.inputs["Max"].default_value = 1.0
    jz = _math(t, "MULTIPLY", rz.outputs[0], gi.outputs["Jitter"], (800, 0))
    tr = _n(t, "ShaderNodeCombineXYZ", (950, 0))
    L(jz, tr.inputs[2])
    rr = _n(t, "FunctionNodeRandomValue", (650, -200), data_type="FLOAT_VECTOR")
    L(gi.outputs["Seed"], rr.inputs["Seed"])
    rr.inputs["Min"].default_value = (-1, -1, -1)
    rr.inputs["Max"].default_value = (1, 1, 1)
    jr = _n(t, "ShaderNodeVectorMath", (800, -200), operation="SCALE")
    L(rr.outputs[0], jr.inputs[0])
    jrs = _math(t, "MULTIPLY", gi.outputs["Jitter"], 2.0, (650, -350))   # 3 mm -> about 0.34 degrees
    L(jrs, jr.inputs["Scale"])
    tin = _n(t, "GeometryNodeTranslateInstances", (1000, 300))
    L(sti2.outputs[0], tin.inputs["Instances"])
    L(tr.outputs[0], tin.inputs["Translation"])
    rin = _n(t, "GeometryNodeRotateInstances", (1150, 300))
    L(tin.outputs[0], rin.inputs["Instances"])
    eul = _n(t, "FunctionNodeEulerToRotation", (950, -200))
    L(jr.outputs[0], eul.inputs[0])
    L(eul.outputs[0], rin.inputs["Rotation"])
    real = _n(t, "GeometryNodeRealizeInstances", (1300, 300))
    L(rin.outputs[0], real.inputs[0])

    # dropped kerb: scale the upstand (z > 0) from Drop Start to Drop End along the path
    nu0 = _n(t, "GeometryNodeInputNamedAttribute", (1150, -300), data_type="FLOAT")
    nu0.inputs["Name"].default_value = "u0"
    nbl = _n(t, "GeometryNodeInputNamedAttribute", (1150, -450), data_type="FLOAT")
    nbl.inputs["Name"].default_value = "blen"
    pos = _n(t, "GeometryNodeInputPosition", (1150, -600))
    sep = _n(t, "ShaderNodeSeparateXYZ", (1300, -600))
    L(pos.outputs[0], sep.inputs[0])
    # u along the path in metres = u0 + uloc * blen (uloc from the block line)
    nul = _n(t, "GeometryNodeInputNamedAttribute", (1150, -750), data_type="FLOAT")
    nul.inputs["Name"].default_value = "uloc"
    um = _math(t, "MULTIPLY", nul.outputs[0], nbl.outputs[0], (1300, -750))
    um = _math(t, "ADD", um, nu0.outputs[0], (1450, -750))
    f = _math(t, "DIVIDE", um, gi.outputs["Path Length"], (1600, -750))
    mixf = _n(t, "ShaderNodeMapRange", (1900, -750), clamp=True)
    L(f, mixf.inputs["Value"])
    L(gi.outputs["Drop Start"], mixf.inputs["To Min"])
    L(gi.outputs["Drop End"], mixf.inputs["To Max"])
    zpos = _math(t, "MAXIMUM", sep.outputs[2], 0.0, (1450, -600))
    k1 = _math(t, "SUBTRACT", mixf.outputs[0], 1.0, (2050, -650))
    dz = _math(t, "MULTIPLY", zpos, k1, (2200, -600))
    off = _n(t, "ShaderNodeCombineXYZ", (2350, -600))
    L(dz, off.inputs[2])
    sp = _n(t, "GeometryNodeSetPosition", (1500, 300))
    L(real.outputs[0], sp.inputs["Geometry"])
    L(off.outputs[0], sp.inputs["Offset"])

    # UVs: u = metres along the path / 4, v = (row + metres along the profile) / 8
    nvl = _n(t, "GeometryNodeInputNamedAttribute", (1450, -1000), data_type="FLOAT")
    nvl.inputs["Name"].default_value = "vlen"
    uu = _math(t, "DIVIDE", um, SHEET_U_M, (1600, -900))
    vv = _math(t, "ADD", nvl.outputs[0], gi.outputs["Row"], (1600, -1050))
    vv = _math(t, "DIVIDE", vv, SHEET_V_M, (1750, -1050))
    uvv = _n(t, "ShaderNodeCombineXYZ", (1900, -950))
    L(uu, uvv.inputs[0])
    L(vv, uvv.inputs[1])
    suv = _n(t, "GeometryNodeStoreNamedAttribute", (1650, 300), domain="CORNER", data_type="FLOAT2")
    suv.inputs["Name"].default_value = "UVMap"
    L(sp.outputs[0], suv.inputs["Geometry"])
    L(uvv.outputs[0], suv.inputs["Value"])
    # P92b: the profile winding gave inward faces (negative volume; Unity back-face culls them): flip once here
    flp = _n(t, "GeometryNodeFlipFaces", (1750, 300))
    L(suv.outputs[0], flp.inputs["Mesh"])
    L(flp.outputs[0], go.inputs[0])
    return t


# --- piece builders --------------------------------------------------------------------------------------------------

def set_input(md, name, val):
    for it in md.node_group.interface.items_tree:
        if it.item_type == "SOCKET" and it.in_out == "INPUT" and it.name == name:
            try:
                md[it.identifier] = val
            except TypeError:   # Blender 5.x: modifier inputs live on md.properties.inputs.<identifier>.value
                getattr(md.properties.inputs, it.identifier).value = val
            return
    raise KeyError(name)


def sweep(name, key, path, length, c, src, lod=0, block=0.5, gap=0.005, jitter=0.003, seed=0,
          drop=(1.0, 1.0)) -> bpy.types.Object:
    """A kerb / channel object driven by PI_EdgeSweep (modifier kept live until `bake_piece`)."""
    g = bpy.data.node_groups.get("PI_EdgeSweep") or sweep_group()
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    md = ob.modifiers.new("PI_EdgeSweep", "NODES")
    md.node_group = g
    prf = profile_obj(key, lod, src)
    for k, v in (("Path", path), ("Profile", prf), ("Path Length", float(length)), ("Row", ROW[key]),
                 ("Block", float(block)), ("Gap", float(gap if lod == 0 else 0.0)),
                 ("Jitter", float(jitter if lod == 0 else 0.0)), ("Seed", int(seed)),
                 ("Fillet Count", 2 if lod == 0 else 0), ("Drop Start", float(drop[0])),
                 ("Drop End", float(drop[1]))):
        set_input(md, k, v)
    ob.data.materials.append(material())
    return ob


def stats(ob):
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    m = ev.to_mesh()
    co = np.array([v.co[:] for v in m.vertices]) if len(m.vertices) else np.zeros((1, 3))
    r = dict(v=len(m.vertices), tris=sum(len(p.vertices) - 2 for p in m.polygons),
             lo=co.min(0).round(3).tolist(), hi=co.max(0).round(3).tolist(), uv=[u.name for u in m.uv_layers])
    ev.to_mesh_clear()
    return r
