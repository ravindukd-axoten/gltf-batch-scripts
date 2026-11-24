"""Geometry Nodes for the Delta Face street kit (TDD "Street kit as built"; data in citylib/street_kit.py).

Every piece is one node group `PI_GN_Street_<piece>` built from its parts: lathes (a profile's radius on a curve,
Curve to Mesh with a circle), tubes (Curve to Mesh along a polyline), boxes, cylinders and cones (GN mesh
primitives), arrays (Instance on Points along a Mesh Line, realized) and profile sweeps; facade bays reuse the hero
library's PI_GN_WindowGrid with its mid-poly sources (sills, keystones, shutters, awnings, fanlights). The groups
stay in the saved .blend (tools/city/out) and regenerate from their inputs.

After the generator is applied (TDD workaround rule: before the AO bake) the pipeline adds, per piece:
Bevel (1 segment, 30 degree limit) + Weighted Normal where the data asks for it, UV0 on the FacadeTrim_A rows /
real-scale world UVs / the signage atlas cell, UV1 (`UVMap2`) on the shared decor masks, and COLOR_0 = paint rgb +
Cycles vertex AO in alpha.
"""
from __future__ import annotations

import math

import bmesh
import bpy

from .. import hero_bays as HB
from .. import materials as M
from .. import street_kit as SK
from . import facade, sources, wear
from .nodes import Tree

COLL = "PI_StreetKit_Build"
AO_SAMPLES = 48
AO_DISTANCE_M = 1.2
SIGN_GRID = SK.sign_atlas()["grid"]   # T_Signage_A cells (columns, rows), 512 x 128 px each (signage.json; 4 x 16)
SHOP_U, SHOP_V = (0.5, 0.98), (0.33, 0.98)   # SHD_HeroLit reads u > 0.45 on black faces as shop glass
ROLE_ID = {"trim": 0, "body": 1, "world": 2, "sign": 3, "shop": 4}
BEVEL_GROWTH = 0.12           # surface-layer bevel may add at most 12 % to a piece's triangles (P242 cap fix)
PIECE_CAP = 2900              # AGENTS.md kit building piece cap (3k) less a margin; the bevel never pushes a piece over it
BEVEL_TRIS_PER_EDGE = 3       # a 1-segment bevel strip is 2 triangles plus its share of the corner fills
FLAT_M = 0.012                # parts this thin lying flat are paint on the ground: top face only (surface pieces)
BEVEL_MIN_M = 0.15            # smallest box side that gets a bevel on surface-layer pieces (columns, kerbs, bodies)
# kit surface layer (P242): flat paint maps onto FacadeTrim_A block 1 (cast concrete: neutral grain, formwork panel
# lines and streaks) at world scale, so paint multiplies a real texture instead of one texel strip of the reveal row
SURFACE_BLOCK = 1
SURFACE_M = 4.0               # one trim block is 4 m x 4 m


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)) + (1.0,)


def _poly3(t: Tree, pts):
    sw = t.n("GeometryNodeIndexSwitch", data_type="VECTOR")
    while len([s for s in sw.inputs if s.name not in ("Index", "")]) < len(pts):
        sw.index_switch_items.new()
    items = [s for s in sw.inputs if s.name not in ("Index", "")]
    t.links.new(t.index(), sw.inputs["Index"])
    for s, p in zip(items, pts):
        s.default_value = tuple(float(c) for c in p)
    pts_ = t.o(t.n("GeometryNodePoints", {"Count": len(pts), "Position": t.o(sw)}))
    return t.o(t.n("GeometryNodePointsToCurves", {"Points": pts_}))


def _fswitch(t: Tree, vals):
    sw = t.n("GeometryNodeIndexSwitch", data_type="FLOAT")
    while len([s for s in sw.inputs if s.name not in ("Index", "")]) < len(vals):
        sw.index_switch_items.new()
    items = [s for s in sw.inputs if s.name not in ("Index", "")]
    t.links.new(t.index(), sw.inputs["Index"])
    for s, v in zip(items, vals):
        s.default_value = float(v)
    return t.o(sw)


def _circle(t: Tree, segs):
    return t.o(t.n("GeometryNodeCurvePrimitiveCircle", {"Resolution": int(segs), "Radius": 1.0}, mode="RADIUS"))


def _tag(t: Tree, geo, part, mats, uv=None):
    mat = mats[SK.ROLES[part["mat"]]]
    geo = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": geo, "Material": mat}))
    paint = (0.0, 0.0, 0.0, 1.0) if part["mat"] == "glass" else _hex(part["paint"])
    geo = t.store(geo, "paint", paint, "FLOAT_COLOR", "FACE")
    uv = uv or part.get("uv", "trim")
    role = ROLE_ID["sign"] if isinstance(uv, (tuple, list)) else ROLE_ID[uv]
    geo = t.store(geo, "uvrole", role, "INT", "FACE")
    # bevel eligibility (P242): boxes whose smallest side is at least BEVEL_MIN_M; small trims, glass, cylinders and
    # floor paint stay sharp so the bevel's triangles go where they catch light (research 3.1 mid-poly kits)
    bev = int(part["t"] == "box" and part["mat"] != "glass" and (not part.get("detail") or bool(part.get("bevel_lod0")))
              and min(part["size"]) >= BEVEL_MIN_M)
    geo = t.store(geo, "bev", bev, "INT", "FACE")
    # lying paint (P242): stains, scuffs, joints and bay lines a few mm thick keep only their top face on surface pieces
    hz = part["size"][2] if part["t"] == "box" else (part["depth"] if part["t"] == "cyl" and part["axis"] == "z" else 1.0)
    geo = t.store(geo, "flat", int(hz <= FLAT_M), "INT", "FACE")
    geo = t.store(geo, "plate", int(bool(part.get("plate"))), "INT", "FACE")      # P268 far LODs (fuel_kit.lod1)
    if isinstance(uv, (tuple, list)):
        # ("sign", col, row, q): q = 0..3 picks a square quarter of the 4:1 cell (icons, posters; P2 traffic set)
        q = int(uv[3]) + 1 if len(uv) > 3 else 0
        geo = t.store(geo, "scell", int(uv[1]) * 16 + int(uv[2]) + 256 * q, "INT", "FACE")
    return geo


def _part(t: Tree, part, mats, piece):
    k = part["t"]
    if k == "lathe":
        prof = part["prof"]
        crv = _poly3(t, [(0.0, 0.0, z) for _, z in prof])
        geo = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": crv, "Profile Curve": _circle(t, part["segs"]), "Fill Caps": True,
                                                    "Scale": _fswitch(t, [max(r, 1e-4) for r, _ in prof])}))
        geo = t.transform(geo, translation=t.vec(*part["at"]))
        return _tag(t, geo, part, mats)
    if k == "tube":
        crv = _poly3(t, part["pts"])
        geo = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": crv, "Profile Curve": _circle(t, part["segs"]), "Fill Caps": True,
                                                    "Scale": part["r"]}))
        return _tag(t, geo, part, mats)
    if k == "box":
        geo = t.o(t.n("GeometryNodeMeshCube", {"Size": t.vec(*part["size"])}))
        geo = t.transform(geo, translation=t.vec(*part["at"]), rotation=(0.0, 0.0, part.get("rot", 0.0)))
        return _tag(t, geo, part, mats)
    if k == "grid":
        # top-only subdivided ground (P207 fuel forecourt): vertices for the baked AO, light pool and grime
        sx, sy = part["size"]
        nx, ny = part["verts"]
        geo = t.o(t.n("GeometryNodeMeshGrid", {"Size X": sx, "Size Y": sy, "Vertices X": int(nx), "Vertices Y": int(ny)}))
        geo = t.transform(geo, translation=t.vec(*part["at"]))
        return _tag(t, geo, part, mats)
    if k == "cyl":
        geo = t.o(t.n("GeometryNodeMeshCone", {"Vertices": int(part["segs"]), "Radius Top": part["r2"],
                                                 "Radius Bottom": part["r"], "Depth": part["depth"]}, fill_type="NGON"))
        rot = {"z": (0.0, 0.0, 0.0), "x": (0.0, math.pi / 2, 0.0), "y": (math.pi / 2, 0.0, 0.0)}[part["axis"]]
        if part["segs"] == 4:
            rot = (rot[0], rot[1], math.pi / 4)   # a 4-sided cone is a hip/pyramid roof: square to the axes
        geo = t.transform(geo, translation=t.vec(*part["at"]), rotation=rot)
        return _tag(t, geo, part, mats, "world" if part["mat"] == "roof" else None)
    if k == "sweep":
        path = _poly3(t, part["path"])
        # data profiles are (y outwards-negative, z up) for a path along +x; Curve to Mesh profile is (right, down)
        prof = facade.polyline(t, [(-y, -z) for y, z in reversed(part["prof"])], cyclic=part.get("closed", True))
        geo = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": path, "Profile Curve": prof,
                                                           "Fill Caps": part.get("caps", True)}))
        if part.get("rotz"):            # P259: turn a vertical sweep about the kit origin (walls along y)
            geo = t.transform(geo, rotation=(0.0, 0.0, part["rotz"]))
        return _tag(t, geo, part, mats)
    if k == "array":
        sub = _part(t, part["part"], mats, piece)
        pts = t.o(t.n("GeometryNodeMeshLine", {"Count": int(part["count"]), "Offset": t.vec(*part["step"])},
                      mode="OFFSET"))
        inst = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": pts, "Instance": sub}))
        return t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": inst}))
    if k == "rubble":
        # random-rubble face: a grid of points on the battered face, each a bevel-free stone block of jittered
        # size and tilt (fixed seed), standing a few cm proud of the swept body (gf_03, gf_04)
        (y0, z0), (y1, z1) = part["face"]
        L, rows, cols = part["length"], part["rows"], part["cols"]
        grid = t.o(t.n("GeometryNodeMeshGrid", {"Size X": L - 0.3, "Size Y": 1.0, "Vertices X": cols, "Vertices Y": rows}))
        x, f, _ = t.xyz(t.position())
        f = t.add(f, 0.5)                                       # 0 at the foot, 1 at the top
        rnd = lambda seed, lo, hi: t.o(t.n("FunctionNodeRandomValue", {("Min", "VALUE"): lo, ("Max", "VALUE"): hi,  # noqa: E731
                                                                   ("Seed", "INT"): seed}, data_type="FLOAT"))
        stag = t.mul(t.math("FLOORED_MODULO", t.math("ROUND", t.mul(f, rows - 1)), 2.0), (L - 0.3) / (cols - 1) / 2)
        pos = t.vec(t.add(t.add(x, L / 2), stag), t.add(y0 + 0.04, t.mul(f, y1 - y0)), t.add(z0 + 0.15, t.mul(f, z1 - z0 - 0.3)))
        grid = t.o(t.n("GeometryNodeSetPosition", {"Geometry": grid, "Position": pos}))
        pts = t.o(t.n("GeometryNodeMeshToPoints", {"Mesh": grid}))
        stone = t.o(t.n("GeometryNodeMeshCube", {"Size": t.vec(1.0, 1.0, 1.0)}))
        stone = _tag(t, stone, part, mats, "world")
        sx = (L - 0.3) / (cols - 1)
        sz = (z1 - z0) / rows
        scale = t.vec(rnd(3, sx * 0.75, sx * 1.05), rnd(4, 0.12, 0.22), rnd(5, sz * 0.7, sz * 1.0))
        slope = math.atan2(y1 - y0, z1 - z0)
        rot = t.vec(t.add(-slope, rnd(6, -0.08, 0.08)), rnd(7, -0.06, 0.06), rnd(8, -0.1, 0.1))
        rot = t.o(t.n("FunctionNodeEulerToRotation", {"Euler": rot}))
        inst = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": pts, "Instance": stone, "Rotation": rot, "Scale": scale}))
        return t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": inst}))
    if k == "window":
        ins = dict(part["inputs"])
        fam = ins.pop("family")
        W = ins.get("Bay Width", 3.0)
        pts = t.o(t.n("GeometryNodePoints", {"Count": 1, "Position": t.vec(W / 2, 0.0, 0.0)}))
        for a in ("rot", "s0", "z0"):
            pts = t.store(pts, a, 0.0, "FLOAT", "POINT")
        src = _sources()
        objs = {"Sill Object": "SRC_Sill", "Hood Object": "SRC_Hood", "Keystone Object": "SRC_Keystone",
                "Shutter Object": "SRC_Shutter", "Awning Object": "SRC_Awning", "Fanlight Object": "SRC_Fanlight"}
        node = t.group(_window_group(), {"Geometry": pts, "Detail": 0, "Wall Material": mats[M.PLASTER],
                                         "Trim Material": mats[M.FACADE_TRIM], "Glass Material": mats[M.TOWER_GLASS],
                                         **{k_: src[v] for k_, v in objs.items()}, **ins})
        geo = t.o(node)
        # walls (MAT_PlasterColonial here) the family's paint; the shutter / awning sources keep PlasterSmooth and take
        # the piece's timber paint; trim white; glass black (read back by material in _paint_ao())
        geo = t.store(geo, "paint", _hex(fam), "FLOAT_COLOR", "FACE")
        return t.store(geo, "uvrole", -1, "INT", "FACE")
    raise ValueError(k)


_WINDOW = None
_SRC = None


def _sources():
    """The hero library's mid-poly instance sources, built once per run (rebuilding removes the old objects)."""
    global _SRC
    if _SRC is None or any(o.name not in bpy.data.objects for o in _SRC.values()):
        _SRC = sources.build_all()
        # Object Info only sees objects the depsgraph evaluates: keep the sources out of renders, not the viewport
        bpy.data.collections[sources.COLLECTION].hide_viewport = False
    return _SRC


def _window_group():
    global _WINDOW
    if _WINDOW is None or _WINDOW.name not in bpy.data.node_groups:
        _WINDOW = facade.window_group(_sources())
    return _WINDOW


def piece_group(piece: SK.Piece, mats) -> bpy.types.NodeTree:
    t = Tree(f"PI_GN_Street_{piece.name}")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    geo = t.join(*[_part(t, p, mats, piece) for p in piece.parts])
    geo = t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": geo}))
    geo = t.o(t.n("GeometryNodeMergeByDistance", {"Geometry": geo, "Distance": 0.0005}))
    t.result(geo)
    t.ng.use_fake_user = True   # keep the generator in the saved .blend after it is applied
    return t.ng


# --- after the generator: bevel, UVs, paint + AO ---------------------------------------------------

def _coll():
    c = bpy.data.collections.get(COLL)
    if c is None:
        c = bpy.data.collections.new(COLL)
        bpy.context.scene.collection.children.link(c)
    return c


def _attr_face(me, name, kind="INT"):
    a = me.attributes.get(name)
    if a is None:
        return None
    n = len(me.polygons)
    if kind == "INT":
        vals = [0] * n
        a.data.foreach_get("value", vals)
    else:
        vals = [0.0] * (4 * n)
        a.data.foreach_get("color", vals)
        vals = [tuple(vals[4 * i:4 * i + 4]) for i in range(n)]
    return vals


def _mark_bevel_edges(ob) -> int:
    """Bevel weight 1 on sharp (> 30 degree) edges whose faces are all bevel-eligible (`bev` face attribute)."""
    me = ob.data
    flags = _attr_face(me, "bev") or [1] * len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    lay = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge")
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    budget = int(min(BEVEL_GROWTH * tris, max(0, PIECE_CAP - tris)) / BEVEL_TRIS_PER_EDGE)
    cand = []
    for e in bm.edges:
        e[lay] = 0.0
        fs = e.link_faces
        if len(fs) == 2 and all(flags[f.index] for f in fs) and e.calc_face_angle(0.0) > math.radians(30):
            cand.append(e)
    cand.sort(key=lambda e: -e.calc_length())          # the longest (silhouette) edges catch the light first
    n = 0
    for e in cand[:budget]:
        e[lay] = 1.0
        n += 1
    bm.to_mesh(me)
    bm.free()
    return n


def _drop_flat_sides(ob) -> int:
    """Deletes the sides and bottoms of lying paint parts (`flat` face attribute): a 4 mm stain or bay line is seen
    from above only, so a box costs 2 triangles instead of 12 and a 6-sided disc 4 instead of 20 (P242 Low cost)."""
    me = ob.data
    flags = _attr_face(me, "flat")
    if flags is None:
        return 0
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    drop = [f for f in bm.faces if flags[f.index] and f.normal.z < 0.9]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    bm.to_mesh(me)
    bm.free()
    if me.attributes.get("flat"):
        me.attributes.remove(me.attributes["flat"])
    return len(drop)


HIDDEN_EPS = 0.002            # P268 hidden-face test: how far a face is nudged out along its normal (2 mm)
GROUND_Z = 0.003              # place-kit pieces stand on z = 0: a down face at or below this is ground contact
_RAY = (0.5773, 0.5774, 0.5775)   # odd parity-ray direction (never along a box edge or face)


def _shells(bm) -> list:
    """Connected face shells of a bmesh, in face order (deterministic)."""
    seen, out = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        shell, stack = [], [f]
        seen.add(f.index)
        while stack:
            g = stack.pop()
            shell.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        out.append(sorted(shell, key=lambda g: g.index))
    return out


def _inside(tree, p) -> bool:
    """Ray-parity point-in-closed-shell test (BVH over that one shell)."""
    from mathutils import Vector
    d = Vector(_RAY).normalized()
    o, hits = Vector(p), 0
    for _ in range(64):
        loc = tree.ray_cast(o, d)[0]
        if loc is None:
            break
        hits += 1
        o = loc + d * 1e-5
    return hits % 2 == 1


def _drop_hidden(ob, ground: bool = True) -> int:
    """P268 hidden-face removal (the 'remove hidden geometry' step of offline LOD tools) on a kit piece: deletes
    faces no camera can see, so the silhouette and every visible surface stay as built. A face is hidden when
    (a) `ground` and it faces down at z <= GROUND_Z (ground contact; moving lift nodes pass ground=False), or (b) its
    centre and corners (pulled 1 % in), nudged HIDDEN_EPS out along its normal, all lie inside one other closed
    shell (a box base on a slab, a band's back pressed into the wall, a post foot in a plinth). Runs before the
    bevel, so ground and buried edges are never bevelled (and the bevel never meets those degenerate corners)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    shells = _shells(bm)
    closed = []
    for k, sh in enumerate(shells):
        if all(len(e.link_faces) == 2 for g in sh for e in g.edges):
            vs = sorted({v.index for g in sh for v in g.verts})
            remap = {vi: j for j, vi in enumerate(vs)}
            cos = [bm.verts[vi].co.copy() for vi in vs]
            tree = BVHTree.FromPolygons(cos, [[remap[v.index] for v in g.verts] for g in sh])
            lo = [min(c[i] for c in cos) for i in range(3)]
            hi = [max(c[i] for c in cos) for i in range(3)]
            closed.append((k, tree, lo, hi))
    agent = {g.index: k for k, sh in enumerate(shells) for g in sh}
    drop = []
    for f in bm.faces:
        n = f.normal
        if ground and n.z < -0.99 and all(v.co.z <= GROUND_Z for v in f.verts):
            drop.append(f)
            continue
        c = f.calc_center_median()
        pts = [c + n * HIDDEN_EPS] + [c + (v.co - c) * 0.99 + n * HIDDEN_EPS for v in f.verts]
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        for k, tree, blo, bhi in closed:
            if k == agent[f.index] or any(lo[i] < blo[i] or hi[i] > bhi[i] for i in range(3)):
                continue
            if all(_inside(tree, Vector(p)) for p in pts):
                drop.append(f)
                break
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    bm.to_mesh(me)
    bm.free()
    return len(drop)


def _stray(src_cos, out_cos, tol) -> int:
    """Bevel output vertices farther than `tol` from every input vertex. Blender's weight bevel can leave one
    uninitialised vertex at a degenerate corner, a value that changes every run (KIT_TukWorks_Shed_A, P259/P268):
    sometimes far away, sometimes near the origin, so a bounding-box test alone let it through."""
    from mathutils.kdtree import KDTree
    kd = KDTree(len(src_cos))
    for i, co in enumerate(src_cos):
        kd.insert(co, i)
    kd.balance()
    return sum(1 for co in out_cos if kd.find(co)[2] > tol)


def _drop_plate_sides(ob) -> int:
    """P268 far LODs: upright plates (`plate` face attribute: sign faces, text bars a few mm thick and wordmark
    glyph blocks; fuel_kit.lod1 tags them) keep only the faces parallel to their biggest face, so a plate costs 4
    triangles instead of 12 and the back one usually goes in _drop_hidden. The sides (5 cm relief at most) are about
    a pixel beyond the LOD1 distance."""
    me = ob.data
    flags = _attr_face(me, "plate")
    if flags is None:
        return 0
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    drop = []
    for sh in _shells(bm):
        if not all(flags[f.index] for f in sh):
            continue
        big = max(sh, key=lambda f: f.calc_area()).normal
        drop += [f for f in sh if abs(f.normal.dot(big)) < 0.9]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    bm.to_mesh(me)
    bm.free()
    me.attributes.remove(me.attributes["plate"])
    return len(drop)


def _bevel(ob, width, by_weight=False):
    marked = by_weight and _mark_bevel_edges(ob)
    if marked or not by_weight:       # a surface piece with no box edges big enough keeps its edges sharp (no blanket bevel)
        bev = ob.modifiers.new("Bevel", "BEVEL")
        bev.width = width
        bev.segments = 1
        bev.limit_method = "WEIGHT" if marked else "ANGLE"
        bev.angle_limit = math.radians(30)
        bev.harden_normals = True
        bev.face_strength_mode = "FSTR_ALL"
        bev.miter_outer = "MITER_ARC"
    wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.mode = "FACE_AREA"
    wn.use_face_influence = True
    wn.keep_sharp = True
    wn.weight = 50
    keep = ob.data.copy()
    src = [v.co.copy() for v in ob.data.vertices]
    lim = max(max(abs(c) for c in v.co) for v in ob.data.vertices) + 1.0 if ob.data.vertices else 0.0
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
        for mod in list(ob.modifiers):
            bpy.ops.object.modifier_apply(modifier=mod.name)
    far = any(max(abs(c) for c in v.co) > lim for v in ob.data.vertices)
    if far or (marked and _stray(src, [v.co for v in ob.data.vertices], 4.0 * width + 1e-4)):
        # a degenerate weight-bevel corner can leave a garbage vertex (seen on KIT_TukWorks_Shed_A): keep the
        # unbevelled mesh, weighted normals only (the same result every run)
        bad, ob.data = ob.data, keep
        bpy.data.meshes.remove(bad)
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.mode, wn.keep_sharp = "FACE_AREA", True
        with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
            bpy.ops.object.modifier_apply(modifier=wn.name)
        print(f"[street] {ob.name}: bevel produced a stray vertex, kept the sharp mesh")
    else:
        bpy.data.meshes.remove(keep)


def _uvs(ob, piece: SK.Piece) -> None:
    """UV0 by role and UV1 (UVMap2) on the decor masks. Pure mapping of the generated surface (no shapes)."""
    me = ob.data
    uv0 = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    uv1 = me.uv_layers.get("UVMap2") or me.uv_layers.new(name="UVMap2")
    roles = _attr_face(me, "uvrole") or [0] * len(me.polygons)
    cells = _attr_face(me, "scell") or [0] * len(me.polygons)
    names = [m.name if m else "" for m in me.materials]
    storey = SK.UF if piece.upper else SK.GF
    b1 = HB.trim_map(0, HB.REVEAL)
    bs = HB.trim_map(SURFACE_BLOCK, HB.BODY)
    paint = _attr_face(me, "paint", "COLOR") if piece.surface else None
    fit = _surface_fit(me) if piece.surface else None
    a0 = [0.0] * (2 * len(me.loops))
    a1 = [0.0] * (2 * len(me.loops))
    uv0.data.foreach_get("uv", a0)
    xs = [v.co.x for v in me.vertices] or [0.0]
    x0, wid = min(xs), max(max(xs) - min(xs), 4.0)
    for p in me.polygons:
        n = p.normal
        mat = names[p.material_index] if names else ""
        role = roles[p.index]
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            # planar coordinates on the face's dominant axis
            if abs(n.z) >= max(abs(n.x), abs(n.y)):
                a, b = co.x, co.y
            elif abs(n.x) >= abs(n.y):
                a, b = co.y, co.z
            else:
                a, b = co.x, co.z
            if role == 2:                                   # world materials at real scale
                tu, tv = M.tile(mat)
                u, v = a / tu, b / tv
            elif role == 3:                                 # signage atlas cell on the board's face
                quarter, cc = divmod(cells[p.index], 256)
                col, row = divmod(cc, 16)
                if n.y < -0.5 or abs(n.x) > 0.5 and abs(n.y) < 0.5 and n.x < -0.5:
                    fu = (co.x - p.center.x) if n.y < -0.5 else -(co.y - p.center.y)
                    fv = co.z - p.center.z
                    hw = max(abs(me.vertices[me.loops[q].vertex_index].co.x - p.center.x) for q in p.loop_indices) \
                        if n.y < -0.5 else max(abs(me.vertices[me.loops[q].vertex_index].co.y - p.center.y) for q in p.loop_indices)
                    hh = max(abs(me.vertices[me.loops[q].vertex_index].co.z - p.center.z) for q in p.loop_indices)
                    fu, fv = 0.5 + 0.5 * fu / max(hw, 1e-4), 0.5 + 0.5 * fv / max(hh, 1e-4)
                else:
                    fu, fv = 0.02, 0.5                     # edges and backs: the board's painted border
                u = (col + 0.01 + 0.98 * fu) / SIGN_GRID[0] if not quarter else \
                    (col + (quarter - 1 + 0.03 + 0.94 * fu) / 4.0) / SIGN_GRID[0]
                v = 1.0 - (row + 0.99 - 0.98 * fv) / SIGN_GRID[1]
            elif role == 4:                                 # shop glass: the face's extent on the shop pane rows
                ext = [me.vertices[me.loops[q].vertex_index].co for q in p.loop_indices]
                ea = [(c.x if abs(n.y) >= abs(n.x) else c.y) for c in ext]
                eb = [c.z for c in ext]
                fa = (a - min(ea)) / max(max(ea) - min(ea), 1e-4) if abs(n.z) < 0.5 else 0.5
                fb = (co.z - min(eb)) / max(max(eb) - min(eb), 1e-4) if abs(n.z) < 0.5 else 0.5
                u, v = SHOP_U[0] + fa * (SHOP_U[1] - SHOP_U[0]), SHOP_V[0] + fb * (SHOP_V[1] - SHOP_V[0])
            elif role == -1 and "PlasterSmooth" in mat:      # shutter / awning sources: flat timber paint
                u, v = (a + b) / 40.0, 0.5 * b1[0] + b1[1]
            elif role == 1 or (role == -1 and "Plaster" in mat):  # wall plaster: the smooth reveal row (gf_21/24/25 lime
                u, v = a / 40.0, 0.5 * b1[0] + b1[1]              # render is smooth); ageing = decor masks + grime detail
            elif role == -1:                                # WindowGrid trim / glass keep the library's UVs
                u, v = a0[2 * li], a0[2 * li + 1]
            elif piece.surface and paint and sum(paint[p.index][:3]) > 0.0:
                # surface layer: world-scale trim block, v fitted to the face inside the block's body row
                lo, span = fit[p.index]
                u, v = a / SURFACE_M, bs[1] + bs[0] * (b - lo) / span
            else:                                           # flat paint: a narrow strip of the cream reveal row
                u, v = (a + b) / 40.0, 0.5 * b1[0] + b1[1]
            a0[2 * li], a0[2 * li + 1] = u, v
            # UV1: decor masks; u band 0-0.5 ground (base dirt), 0.5-1 upper; v = height in the 4 m band
            uu = 0.02 + 0.46 * min(max((co.x - x0) / wid, 0.0), 1.0) + (0.5 if piece.upper else 0.0)
            vv = min(max(co.z / (storey if piece.upper else 4.0), 0.0), 0.99)
            a1[2 * li], a1[2 * li + 1] = uu, vv
    uv0.data.foreach_set("uv", a0)
    uv1.data.foreach_set("uv", a1)
    me.uv_layers.active = uv0
    uv0.active_render = True


def _plane_ab(n, co):
    if abs(n.z) >= max(abs(n.x), abs(n.y)):
        return co.x, co.y
    if abs(n.x) >= abs(n.y):
        return co.y, co.z
    return co.x, co.z


def _surface_fit(me) -> list:
    """Per face (low, span) of its planar v coordinate so the face sits inside one trim block's body row: the block
    starts at the 4 m line below the face; a face taller than 4 m from there is fitted (squeezed) into the row."""
    out = []
    for p in me.polygons:
        bs = [_plane_ab(p.normal, me.vertices[v].co)[1] for v in p.vertices]
        lo = math.floor(min(bs) / SURFACE_M) * SURFACE_M
        out.append((lo, max(SURFACE_M, max(bs) - lo)))
    return out


def _paint_ao(ob, piece: SK.Piece) -> None:
    """COLOR_0 (`Col`): rgb = the part's paint (sRGB), a = Cycles AO baked alone with a ground plane."""
    me = ob.data
    paint = _attr_face(me, "paint", "COLOR") or [(1.0, 1.0, 1.0, 1.0)] * len(me.polygons)
    names = [m.name if m else "" for m in me.materials]
    for ca in list(me.color_attributes):
        if ca.name != "paint":
            me.color_attributes.remove(ca)
    ca = me.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
    me.color_attributes.active_color = ca
    me.color_attributes.render_color_index = me.color_attributes.active_color_index
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = AO_SAMPLES
    scene.cycles.device = "CPU"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("AO_World")
    scene.world.light_settings.distance = AO_DISTANCE_M
    hidden = [o for o in bpy.data.objects if o.type == "MESH" and o is not ob and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0, 0, -0.01))
    ground = bpy.context.active_object
    try:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        scene.render.bake.target = "VERTEX_COLORS"
        bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
    finally:
        bpy.data.objects.remove(ground)
        for o in hidden:
            o.hide_render = False
    ca = me.color_attributes["Col"]
    ao = [0.0] * (4 * len(ca.data))
    ca.data.foreach_get("color_srgb", ao)
    out = [0.0] * len(ao)
    trim_white = _hex(SK.WHITE)
    timber = _hex(piece.shutter)
    for p in me.polygons:
        mat = names[p.material_index] if names else ""
        rgb = paint[p.index][:3]
        if "Glass" in mat:
            rgb = (0.0, 0.0, 0.0)
        elif "FacadeTrim" in mat:
            rgb = trim_white[:3]
        elif "PlasterSmooth" in mat:
            rgb = timber[:3]
        for li in p.loop_indices:
            out[4 * li:4 * li + 4] = (*rgb, ao[4 * li])
    ca.data.foreach_set("color_srgb", out)
    for name in ("paint", "uvrole", "scell", "bev", "flat", "plate"):
        if name in me.attributes:
            me.attributes.remove(me.attributes[name])


def _decay_color1(ob, piece: SK.Piece) -> None:
    """COLOR_1 (`Col1`), decay-ready channels (docs/research/wear-and-decay-system.md 3.1): R dirt (foot splash from
    the ground up to 0.45 m, plus cavities from the AO in Col.a), G edge wear (how far the vertex's faces bend away
    from each other, so bevelled corners chip first), B rust (metal: the lowest 0.3 m, galvanised and iron paints
    only) or damp (other classes: the lowest 0.15 m), A per-piece age seed (hash of the name, 0..1)."""
    me = ob.data
    col = me.color_attributes["Col"]
    ao = [0.0] * (4 * len(col.data))
    col.data.foreach_get("color_srgb", ao)
    nv = len(me.vertices)
    nrm = [[] for _ in range(nv)]
    for p in me.polygons:
        for vi in p.vertices:
            nrm[vi].append(p.normal.copy())
    spread = []
    for ns in nrm:
        lo = 1.0
        for a in ns:
            for b in ns:
                lo = min(lo, a.dot(b))
        spread.append(min(max((1.0 - lo) / 1.0, 0.0), 1.0))
    seed = (sum(ord(c) * (i + 3) for i, c in enumerate(piece.name)) % 997) / 997.0
    metal = piece.decay == "metal"
    out = [0.0] * (4 * len(me.loops))
    for li, lp in enumerate(me.loops):
        z = me.vertices[lp.vertex_index].co.z
        dirt = min(1.0, max(0.0, 1.0 - z / 0.45) * 0.8 + (1.0 - ao[4 * li + 3]) * 0.5)
        wear = spread[lp.vertex_index] * 0.9
        rust = max(0.0, 1.0 - z / 0.3) if metal else max(0.0, 1.0 - z / 0.15) * 0.6
        out[4 * li:4 * li + 4] = (dirt, wear, rust, seed)
    ca = me.color_attributes.new(name="Col1", type="BYTE_COLOR", domain="CORNER")
    ca.data.foreach_set("color", out)   # linear: the exporter writes these values unchanged (data, not paint)
    me.color_attributes.active_color = me.color_attributes["Col"]
    me.color_attributes.render_color_index = me.color_attributes.active_color_index


def _to_kit_material(ob, mats) -> None:
    """Wall plaster, trim and glass of the WindowGrid bays all draw with MAT_StreetKit_A (one draw)."""
    me = ob.data
    kitm = mats[SK.MAT_KIT]
    names = [m.name if m else SK.MAT_KIT for m in me.materials]
    final, remap = [], []
    for n in names:
        m = SK.MAT_KIT if n in (M.PLASTER, M.PLASTER_SMOOTH, M.FACADE_TRIM, M.TOWER_GLASS) else n
        if m not in final:
            final.append(m)
        remap.append(final.index(m))
    idx = [0] * len(me.polygons)
    me.polygons.foreach_get("material_index", idx)
    me.materials.clear()
    for n in final:
        me.materials.append(kitm if n == SK.MAT_KIT else mats[n])
    me.polygons.foreach_set("material_index", [remap[i] for i in idx])


def tris(ob) -> int:
    me = ob.data
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def _recalc_shells(bm) -> None:
    """Consistent winding per connected shell. Closed shells (boxes, capped sweeps, lathes) face outwards. An open
    shell has no inside, so recalculating it guesses: on the WindowGrid bays the wall panel (merged to its reveal
    and architrave) came out facing into the building, and the culled wall showed the towers behind as blue and
    white bands (SK2 shop block: Colonial / Shophouse uppers, Arched shopfronts). Open shells keep the side the
    generator wound most of their area to (the panel's Fill Curve), made consistent."""
    seen = set()
    for f in bm.faces:
        if f in seen:
            continue
        island, stack = [], [f]
        seen.add(f)
        while stack:
            g = stack.pop()
            island.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        before = [g.normal.copy() for g in island]
        bmesh.ops.recalc_face_normals(bm, faces=island)
        if all(len(e.link_faces) == 2 for g in island for e in g.edges):
            continue
        for g in island:
            g.normal_update()
        vote = sum(g.calc_area() * (1.0 if g.normal.dot(n0) >= 0.0 else -1.0) for g, n0 in zip(island, before))
        if vote < 0.0:
            bmesh.ops.reverse_faces(bm, faces=island)


def build(mats, only=None, pieces=None) -> dict[str, bpy.types.Mesh]:
    """Build every street-kit piece; returns name -> finished mesh (applied, bevelled, UVs, COLOR_0).
    `pieces` (name -> SK.Piece) builds another set with the same generator (place kit, P207); it never writes
    street_kit_tris.json."""
    out = {}
    coll = _coll()
    for name, piece in (pieces or SK.pieces()).items():
        if only and name not in only:
            continue
        me = bpy.data.meshes.new(f"_{name}_src")
        ob = bpy.data.objects.new(f"_{name}_build", me)
        coll.objects.link(ob)
        mod = ob.modifiers.new("Street", "NODES")
        mod.node_group = piece_group(piece, mats)
        bpy.context.view_layer.objects.active = ob
        facade.apply_gn(ob)
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        _recalc_shells(bm)
        bm.to_mesh(ob.data)
        bm.free()
        if piece.surface:
            _drop_flat_sides(ob)
            _drop_plate_sides(ob)
            moving = getattr(piece, "meta", {}).get("move", "static") != "static"
            print(f"[street] {name}: {_drop_hidden(ob, ground=not moving)} hidden faces dropped")
        if piece.bevel > 0:
            _bevel(ob, piece.bevel, by_weight=piece.surface)
        _uvs(ob, piece)
        _paint_ao(ob, piece)
        if piece.decay:
            _decay_color1(ob, piece)
        if piece.surface:
            wear.write_color1(ob, piece.name)
        _to_kit_material(ob, mats)
        ob.data.name = name
        out[name] = ob.data
        ob["tris"] = tris(ob)
    if not only and pieces is None:
        import json
        with open(SK.TRIS_JSON, "w", encoding="utf-8") as fh:
            json.dump({n: _mesh_tris(m) for n, m in sorted(out.items())}, fh, indent=1)
    return out


def _mesh_tris(me) -> int:
    me.calc_loop_triangles()
    return len(me.loop_triangles)
