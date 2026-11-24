"""HERO_DeltaFacePier, the modelled parts (Blender only): jetty, rock shelf and flag plinth (research 3.1-3.5).

Round 3 (2026-11-17, agent: the round-2 jetty read as "lego blocks placed"). These parts are no longer face
lists. Each concrete element is a Blender cube primitive scaled to the measured size (hero_pier constants,
local frame u along the axis, v left, z up from road level). It gets loop cuts for paint and wear density and
the research 3.1 modifier stack:

  Bevel (2 segments, profile 0.5, 30 degree angle limit, arc outer mitres)
  -> PI_GN_EdgeWear (Geometry Nodes: the bevelled edges are eroded and chipped inward by 3D noise, flat faces
     get a few millimetres of waviness so no face is a perfect plane)
  -> Weighted Normal (face area, keep sharp).

The modifiers are evaluated, not hand-edited, then the part is turned to the hero's yaw. LOD1 uses a 1-segment
bevel, light wear and coarse cuts. The rock shelf is a 0.25 m grid laid on hero_pier.shelf_z (the measured
shelf profile). Three Displace modifiers add the relief: Voronoi F2-F1 plates with cracks between them, a
2.5 m swell and 0.4 m grain. Decimate (Collapse) then brings it down to budget, which research 3.4 allows for
rock.

UV0 is box-projected in the hero frame at the world sets' own scale: the concrete is T_ConcreteWeathered at
3.0 m per tile (1024 px, 341 px/m on High, 171 on Low), the rock is T_RockArmour at 1.8 m per tile (569 px/m).
These are the same texel densities as the city cells. The deck's U runs along the stem, so the texture follows
the walkway. COLOR_0 holds the weathering (gn/pier.apply_paint, from the face key `pi_pk` written here plus
position, normal and vertex convexity) and the baked AO in alpha. Materials are MAT_HeroSurface_PierConcrete
and MAT_HeroSurface_PierRock (WorldMaterials.json, SHD_HeroLit with vertex paint and AO on).
"""
from __future__ import annotations

import math

import bmesh
import bpy
import numpy as np

from . import hero_pier as P
from .gn.nodes import Tree

CONCRETE = "MAT_HeroSurface_PierConcrete"
ROCK = "MAT_HeroSurface_PierRock"
FOAM = "MAT_HeroSurface_PierFoam"          # round 4: SHD_PierFoam, the transparent surf sheet (WorldMaterials.json)
PREVIEW = {CONCRETE: (0.55, 0.42, 0.35, 1.0), ROCK: (0.10, 0.11, 0.11, 1.0), FOAM: (0.95, 0.95, 0.92, 1.0)}
TILE = {CONCRETE: 3.0, ROCK: 1.8}          # metres per UV unit = the world sets' size_m (tools/textures)
FOOT_Z = P.Z_SEA - 1.2                     # column feet: 1.2 m under the sea, buried in the shelf or the sea bed
TIDE_Z = P.Z_SEA + P.TIDE                  # the columns' tide line (pier_03): a cut row on each side of it
# column rows (LOD0): dense through the splash zone so the tide line, algae and salt crust read at 3-5 m
COL_ZCUTS = sorted({round(P.Z_SEA + z, 3) for z in
                    (-0.3, -0.1, 0.1, 0.25, 0.4, P.TIDE - 0.025, P.TIDE + 0.025, 0.75, 0.88, 1.0, 1.15, 1.3, 1.5, 1.75)})

# wear per level of detail: bevel width (m), segments, chip depth (m), cut spacing (m)
WEAR = {0: dict(segments=2, depth=0.028, chip=0.07, waviness=0.004, step=0.30),
        1: dict(segments=1, depth=0.0, chip=0.0, waviness=0.0, step=1.2)}


# --- materials and the wear node group ------------------------------------------------------------

def material(name: str) -> bpy.types.Material:
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.diffuse_color = PREVIEW[name]
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = PREVIEW[name]
            bsdf.inputs["Roughness"].default_value = 0.85
    return m


def wear_group() -> bpy.types.NodeTree:
    """PI_GN_EdgeWear: erode and chip bevelled edges inward with 3D noise; a little waviness on flat faces.
    Edge-ness = how far the point normal is from the piece's own axes (the pieces are axis-aligned in the
    hero frame), so only bevel rows move and flat faces stay flat but for the waviness."""
    t = Tree("PI_GN_EdgeWear")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Depth", "NodeSocketFloat", 0.02)
    t.input("Chip", "NodeSocketFloat", 0.04)
    t.input("Waviness", "NodeSocketFloat", 0.004)
    t.input("Seed", "NodeSocketFloat", 0.0)
    n = t.normal()
    ax = t.xyz(n)
    a = t.math("MAXIMUM", t.math("ABSOLUTE", ax[0]), t.math("ABSOLUTE", ax[1]))
    a = t.math("MAXIMUM", a, t.math("ABSOLUTE", ax[2]))
    edge = t.math("MINIMUM", t.mul(t.sub(1.0, a), 3.4), 1.0)
    pos = t.vmath("ADD", t.position(), t.vec(t.gi("Seed"), t.mul(t.gi("Seed"), 0.37), 0.0))
    chipn = t.o(t.n("ShaderNodeTexNoise", {"Vector": pos, "Scale": 4.0, "Detail": 4.0, "Roughness": 0.65}), "Factor")
    chip = t.o(t.n("ShaderNodeMapRange", {"Value": chipn, "From Min": 0.47, "From Max": 0.60, "To Min": 0.0,
                                         "To Max": 1.0}, clamp=True), "Result")
    erode = t.o(t.n("ShaderNodeTexNoise", {"Vector": pos, "Scale": 9.0, "Detail": 2.0}), "Factor")
    inward = t.mul(edge, t.add(t.mul(t.gi("Depth"), t.add(0.4, erode)), t.mul(t.gi("Chip"), chip)))
    wav = t.o(t.n("ShaderNodeTexNoise", {"Vector": pos, "Scale": 1.3, "Detail": 2.0}), "Factor")
    out = t.sub(t.mul(t.sub(wav, 0.5), t.mul(t.gi("Waviness"), 2.0)), inward)
    geo = t.o(t.n("GeometryNodeSetPosition", {"Geometry": t.gi("Geometry"),
                                              "Offset": t.vmath("SCALE", n, scale=out)}))
    t.result(geo)
    return t.ng


def _wear_ng():
    return bpy.data.node_groups.get("PI_GN_EdgeWear") or wear_group()


# --- concrete pieces -------------------------------------------------------------------------------

class Piece:
    """One concrete element: a cube scaled to (u0, u1, v0, v1, z0, z1) with loop cuts, a paint key per face."""

    def __init__(self, key, u0, u1, v0, v1, z0, z1, bevel=0.04, open_top=False, open_bottom=False, step=None,
                 zcuts=None):
        self.key, self.box, self.bevel = key, (u0, u1, v0, v1, z0, z1), bevel
        self.open_top, self.open_bottom, self.step = open_top, open_bottom, step
        self.zcuts = zcuts   # explicit horizontal cuts (LOD0): the columns' tide line and splash-zone rows


def _cube(p: Piece, lod: int) -> bmesh.types.BMesh:
    u0, u1, v0, v1, z0, z1 = p.box
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    lo, hi = (u0, v0, z0), (u1, v1, z1)
    for v in bm.verts:
        v.co = [lo[i] if v.co[i] < 0 else hi[i] for i in range(3)]
    step = p.step or WEAR[lod]["step"]
    steps = step if isinstance(step, tuple) else (step, step, step)
    steps = tuple(max(x, WEAR[lod]["step"]) for x in steps)   # LOD1: coarse cuts everywhere
    for axis in range(3):
        a, b = lo[axis], hi[axis]
        n = max(1, round((b - a) / steps[axis]))
        cuts = [a + (b - a) * i / n for i in range(1, n)]
        if axis == 2 and p.zcuts is not None:
            cuts = [z for z in p.zcuts if a + 0.02 < z < b - 0.02] if lod == 0 else \
                [z for z in (TIDE_Z,) if a + 0.02 < z < b - 0.02]
        for c in cuts:
            co, no = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            co[axis], no[axis] = c, 1.0
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=co, plane_no=no)
    drop = [f for f in bm.faces if (p.open_top and f.normal.z > 0.9 and abs(f.calc_center_median().z - z1) < 1e-4)
            or (p.open_bottom and f.normal.z < -0.9 and abs(f.calc_center_median().z - z0) < 1e-4)]
    if drop:
        bmesh.ops.delete(bm, geom=drop, context="FACES_ONLY")
    return bm


def _modifiers(ob, p: Piece, lod: int, seed: float) -> None:
    w = WEAR[lod]
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.width = p.bevel
    bev.segments = w["segments"]
    bev.profile = 0.5
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(30)
    bev.miter_outer = "MITER_ARC"
    bev.face_strength_mode = "FSTR_ALL"
    if w["depth"] > 0.0:
        from .gn.nodes import set_inputs
        gn = ob.modifiers.new("EdgeWear", "NODES")
        gn.node_group = _wear_ng()
        set_inputs(gn, {"Depth": w["depth"] * p.bevel / 0.04, "Chip": w["chip"] * p.bevel / 0.04,
                        "Waviness": w["waviness"], "Seed": seed})
    wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.mode = "FACE_AREA"
    wn.use_face_influence = True
    wn.keep_sharp = True
    wn.weight = 50


def _evaluated(ob, coll) -> bpy.types.Mesh:
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    return me


def _box_uv(me: bpy.types.Mesh, tile: float, seed: float = 0.0) -> None:
    """UV0 box-projected in the hero frame (before the yaw turn): tops (u, v), u-facing (v, z), v-facing (u, z)."""
    nl = len(me.loops)
    if not nl:
        return
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    vi = np.empty(nl, dtype=np.int64)
    me.loops.foreach_get("vertex_index", vi)
    fn = np.empty(len(me.polygons) * 3)
    me.polygons.foreach_get("normal", fn)
    fn = np.abs(fn.reshape(-1, 3))
    ls = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_total", lt)
    face_of = np.repeat(np.arange(len(me.polygons)), lt)
    dom = np.argmax(fn, axis=1)[face_of]
    p = co[vi]
    uv = np.where(dom[:, None] == 2, p[:, [0, 1]], np.where(dom[:, None] == 0, p[:, [1, 2]], p[:, [0, 2]]))
    uv = uv / tile + seed
    layer = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", uv.ravel())


def _keys(me: bpy.types.Mesh, keys) -> None:
    """Face attribute pi_pk (gn/pier.KEYS): one paint key per face (a list) or for all faces (a string)."""
    from .gn.pier import KEYS
    a = me.attributes.get("pi_pk") or me.attributes.new("pi_pk", "INT", "FACE")
    vals = [KEYS[keys]] * len(me.polygons) if isinstance(keys, str) else [KEYS[k] for k in keys]
    a.data.foreach_set("value", vals)


def _finish(name, me, mat, coll, yaw, keys, seed=0.0) -> bpy.types.Object:
    while len(me.materials):
        me.materials.pop()
    me.materials.append(material(mat))
    me.polygons.foreach_set("material_index", [0] * len(me.polygons))
    for k in [a.name for a in me.attributes if a.name.startswith("bevel") or a.name == "face_strength"]:
        me.attributes.remove(me.attributes[k])
    _box_uv(me, TILE[mat], seed)
    _keys(me, keys)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    me.transform(_yaw_matrix(yaw))
    return ob


def _yaw_matrix(yaw):
    from mathutils import Matrix
    return Matrix.Rotation(math.radians(yaw), 4, "Z")


def concrete(name: str, pieces: list[Piece], lod: int, coll, yaw: float) -> bpy.types.Object:
    """Build each piece with its modifier stack, evaluate, join into one object turned to the hero's yaw."""
    tmp = []
    for k, p in enumerate(pieces):
        bm = _cube(p, lod)
        me = bpy.data.meshes.new(f"_{name}_{k}")
        bm.to_mesh(me)
        bm.free()
        me.shade_smooth()
        ob = bpy.data.objects.new(me.name, me)
        coll.objects.link(ob)
        _modifiers(ob, p, lod, seed=k * 3.7)
        tmp.append((ob, p))
    out = bmesh.new()
    keys = []
    for ob, p in tmp:
        me = _evaluated(ob, coll)
        n0 = len(out.faces)
        out.from_mesh(me)
        keys += [p.key] * (len(out.faces) - n0)
        bpy.data.meshes.remove(me)
        old = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(old)
    me = bpy.data.meshes.new(name)
    out.to_mesh(me)
    out.free()
    return _finish(name, me, CONCRETE, coll, yaw, keys)


# --- the jetty --------------------------------------------------------------------------------------

def jetty_pieces(lay) -> list[Piece]:
    """Landing, steps, stem deck (lip slab over a fascia body), bents, the T-head and its columns (layout:
    hero_pier constants and lay.pier_points)."""
    hw, h2 = P.STEM_W / 2, P.HEAD_W / 2
    lip, o = 0.13, 0.05
    zb = P.DECK_Z - P.FASCIA                     # soffit
    ps = [Piece("deck", -0.05, P.LANDING_U, -hw, hw, P.Z_SEA - 0.1, P.Z_PROM, bevel=0.03)]
    for k in range(P.STEP_N):
        u0 = P.LANDING_U + P.STEP_TREAD * k
        ps.append(Piece("deck", u0 - 0.02, u0 + P.STEP_TREAD, -hw, hw, P.Z_SEA - 0.1, P.Z_PROM - P.STEP_RISE * (k + 1),
                        bevel=0.025))
    # stem: a lip slab 50 mm proud of the 0.57 m fascia body (the shadow line in pier_03), deck top at DECK_Z
    ps.append(Piece("deck", P.STEM_START - 0.02, P.HEAD_U0 + 0.4, -hw - o, hw + o, P.DECK_Z - lip, P.DECK_Z, bevel=0.035,
                    step=(0.3, 0.4, 0.2)))
    ps.append(Piece("concrete", P.STEM_START - 0.02, P.HEAD_U0 + 0.3, -hw, hw, zb, P.DECK_Z - lip, bevel=0.03,
                    open_top=True, step=(0.3, 0.4, 0.3)))
    # bents and head columns on the layout points: squat 1.8 m piers, crossheads under the soffit
    for u, v, _z, _a, kind in lay.pier_points:
        c = P.COL / 2
        if kind == 0:
            ps.append(Piece("concrete", u - 0.55, u + 0.55, -hw - 0.25, hw + 0.25, zb - P.XHEAD_D, zb + 0.02, bevel=0.04,
                            step=(0.22, 0.25, 0.13)))
            ps.append(Piece("concrete", u - c, u + c, -c, c, FOOT_Z, zb - P.XHEAD_D + 0.02, bevel=0.05,
                            open_top=True, open_bottom=True, step=(0.25, 0.25, 0.36), zcuts=COL_ZCUTS))
        elif kind == 2:
            ps.append(Piece("concrete", u - c, u + c, v - c, v + c, FOOT_Z, zb - P.XHEAD_D + 0.22, bevel=0.05,
                            open_top=True, open_bottom=True, step=(0.25, 0.25, 0.36), zcuts=COL_ZCUTS))
    # T-head: lip slab, fascia body, a cross beam over each column row
    u0, u1 = P.HEAD_U0, P.HEAD_U0 + P.HEAD_D
    ps.append(Piece("deck", u0 - o, u1 + o, -h2 - o, h2 + o, P.DECK_Z - lip, P.DECK_Z, bevel=0.035, step=(0.4, 0.4, 0.2)))
    # the head fascia: fine rows so rust streaks from the railing posts read as streaks (pier_03, gf_08)
    ps.append(Piece("concrete", u0, u1, -h2, h2, zb, P.DECK_Z - lip, bevel=0.03, open_top=True, step=(0.16, 0.16, 0.1)))
    for cu in P.HEAD_COL_U:
        ps.append(Piece("concrete", cu - 0.85, cu + 0.85, -h2 + 0.3, h2 - 0.3, zb - P.XHEAD_D + 0.2, zb + 0.02,
                        bevel=0.04, open_top=True, step=(0.25, 0.3, 0.12)))
    return ps


def plinth_pieces() -> list[Piece]:
    """The flag plinth (pier_01): a raised slab with a coping course, stairs seaward and inland, a low mast base."""
    pl0, pl1, plw = P.PLINTH
    zt = P.Z_GREEN + P.PLINTH_H
    o = 0.06
    ps = [Piece("granite_dark", pl0, pl1, -plw, plw, P.Z_GREEN - 0.1, zt - 0.12, bevel=0.03, open_top=True,
                step=(0.6, 0.6, 0.25)),
          Piece("granite", pl0 - o, pl1 + o, -plw - o, plw + o, zt - 0.12, zt, bevel=0.03, step=(0.9, 0.9, 0.2))]
    sw, st = P.PLINTH_STAIR
    n = round(P.PLINTH_H / P.STEP_RISE)
    for k in range(n - 1):
        z = P.Z_GREEN + P.STEP_RISE * (k + 1)
        d = st * (n - 1 - k)
        for a, b in ((pl1 + o - 0.02, pl1 + o + d), (pl0 - o - d, pl0 - o + 0.02)):
            ps.append(Piece("granite", a, b, -sw, sw, P.Z_GREEN - 0.05, z, bevel=0.025, step=(0.35, 0.4, 0.2)))
    cu, pe = P.MAST_U, P.PEDESTAL
    ps.append(Piece("granite_dark", cu - pe, cu + pe, -pe, pe, zt - 0.02, P.PEDESTAL_TOP - 0.1, bevel=0.03,
                    step=(0.4, 0.4, 0.2)))
    c = pe + 0.06
    ps.append(Piece("granite", cu - c, cu + c, -c, c, P.PEDESTAL_TOP - 0.1, P.PEDESTAL_TOP, bevel=0.025,
                    step=(0.4, 0.4, 0.2)))
    return ps


# --- the rock shelf ---------------------------------------------------------------------------------

def rock_group() -> bpy.types.NodeTree:
    """PI_GN_RockShelf (round 4): relief on the shelf grid (z only, hero frame so x = u). Near the seawall the
    shelf is rock armour: rounded ~1.3 m blocks (Voronoi F1 domes) with an amplitude of `Relief`; from u 2-6 m it
    eases to a flatter reef (`Reef`) of ~2 m plates split by Voronoi cracks, all roughened by a 0.3 m grain. The
    relief is centred on the shelf_z profile, so about half of the reef breaks the surface (pier_01, pier_02)."""
    t = Tree("PI_GN_RockShelf")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Relief", "NodeSocketFloat", 0.34)
    t.input("Reef", "NodeSocketFloat", 0.14)
    t.input("Crack", "NodeSocketFloat", 0.12)
    t.input("Grain", "NodeSocketFloat", 0.05)
    t.input("Seed", "NodeSocketFloat", 3.0)
    x = t.xyz(t.position())[0]
    pos = t.vmath("ADD", t.position(), t.vec(t.gi("Seed"), 0.0, 0.0))
    armour = t.o(t.n("ShaderNodeMapRange", {"Value": x, "From Min": 2.0, "From Max": 6.0, "To Min": 1.0, "To Max": 0.0},
                     interpolation_type="SMOOTHSTEP", clamp=True), "Result")
    amp = t.add(t.gi("Reef"), t.mul(t.sub(t.gi("Relief"), t.gi("Reef")), armour))
    blk = t.n("ShaderNodeTexVoronoi", {"Vector": pos, "Scale": 0.75, "Randomness": 0.85})
    lump = t.o(t.n("ShaderNodeMapRange", {"Value": t.o(blk, "Distance"), "From Min": 0.08, "From Max": 0.8,
                                          "To Min": 1.0, "To Max": 0.0}, interpolation_type="SMOOTHSTEP", clamp=True), "Result")
    swell = t.o(t.n("ShaderNodeTexNoise", {"Vector": pos, "Scale": 0.3, "Detail": 3.0, "Roughness": 0.55}), "Factor")
    h = t.mul(t.add(t.mul(t.sub(lump, 0.35), 1.1), t.mul(t.sub(swell, 0.5), 0.9)), amp)   # low mass, few pits
    vor = t.n("ShaderNodeTexVoronoi", {"Vector": pos, "Scale": 0.5, "Randomness": 0.9}, feature="DISTANCE_TO_EDGE")
    crack = t.o(t.n("ShaderNodeMapRange", {"Value": t.o(vor, "Distance"), "From Min": 0.0, "From Max": 0.06,
                                          "To Min": 1.0, "To Max": 0.0}, clamp=True), "Result")
    grain = t.o(t.n("ShaderNodeTexNoise", {"Vector": pos, "Scale": 3.2, "Detail": 4.0, "Roughness": 0.6}), "Factor")
    dz = t.add(t.sub(h, t.mul(crack, t.gi("Crack"))), t.mul(t.sub(grain, 0.5), t.mul(t.gi("Grain"), 2.0)))
    t.result(t.o(t.n("GeometryNodeSetPosition", {"Geometry": t.gi("Geometry"), "Offset": t.vec(0.0, 0.0, dz)})))
    return t.ng


def shelf(name: str, lod: int, coll, yaw: float, tris: int | None = None) -> bpy.types.Object:
    """The dark rock shelf: shelf_z profile + PI_GN_RockShelf relief (ledges, cracks, grain), decimated, the
    ledge risers shaded sharp."""
    from .gn.nodes import set_inputs
    u0, u1, hw = P.SHELF
    step = 0.2
    nu, nv = math.ceil((u1 - u0) / step), math.ceil(2 * hw / step)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=nu, y_segments=nv, size=0.5)
    for v in bm.verts:
        u = u0 + (v.co.x + 0.5) * (u1 - u0)
        w = -hw + (v.co.y + 0.5) * 2 * hw
        v.co = (u, w, P.shelf_z(u, w) + P.Z_SEA)
    me = bpy.data.meshes.new(f"_{name}_high")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(me.name, me)
    coll.objects.link(ob)
    gn = ob.modifiers.new("RockShelf", "NODES")
    gn.node_group = bpy.data.node_groups.get("PI_GN_RockShelf") or rock_group()
    set_inputs(gn, {"Seed": 3.0})
    dec = ob.modifiers.new("Decimate", "DECIMATE")
    dec.decimate_type = "COLLAPSE"
    target = tris or (12000 if lod == 0 else 2800)
    dec.ratio = min(1.0, target / (2 * nu * nv))
    me2 = _evaluated(ob, coll)
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    bm = bmesh.new()
    bm.from_mesh(me2)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(48):
            e.smooth = False
    bm.to_mesh(me2)
    bm.free()
    return _finish(name, me2, ROCK, coll, yaw, "rock")


# --- entry point for build_heroes --------------------------------------------------------------------

def parts(name: str, lay, lod: int, coll, yaw: float) -> list:
    """The modelled LOD0 / LOD1 parts (unparented, at the hero's yaw, origin at the pivot)."""
    if lod >= 2:
        return []
    return [concrete(f"{name}_jetty", jetty_pieces(lay), lod, coll, yaw),
            concrete(f"{name}_plinth", plinth_pieces(), lod, coll, yaw),
            shelf(f"{name}_shelf", lod, coll, yaw)]


# --- surf foam (round 4) -------------------------------------------------------------------------------

def _ss(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def foam_values(u, v, hr, seed: int = 41):
    """Per-vertex foam (R), shallow-rock darkening (G) and phase (B) of the surf sheet at hero-frame (u, v), with
    hr = the rock top under it in metres above the sea (-9 where there is none). Surf works the shelf's waterline
    (rock crowns awash), the shallow rock just under it and the armour at the seawall foot (pier_01, pier_02);
    a noise breaks it into patches. Numpy arrays in, arrays out."""
    from .gn.pier import _vnoise
    n = _vnoise(u / 3.1, v / 3.1, seed)
    m = _vnoise(u / 1.2 + 4.0, v / 1.2, seed + 3)
    zone = (1 - _ss(15.0, 22.0, u)) * (1 - _ss(13.0, 19.5, np.abs(v)))
    awash = 1 - _ss(0.0, 0.3, np.abs(hr - 0.03))
    sub = (hr < 0.0) * (1 - _ss(0.05, 0.75, -hr))
    root = (1 - _ss(1.5, 5.0, u)) * (1 - _ss(14.0, 19.0, np.abs(v)))
    # breakers: bands rolling in across the shelf's seaward half and either side of the stem (pier_02)
    surf = _ss(0.2, 0.7, 0.5 + 0.5 * np.sin(u * 2 * np.pi / 5.5 + 2.4 * n + 0.15 * v)) * (hr < 0.05)
    surf = surf * _ss(3.0, 7.0, u) * (1 - _ss(17.0, 22.0, u)) * (1 - _ss(13.0, 19.5, np.abs(v)))
    r = zone * (0.8 * awash + 0.5 * sub) * (0.45 + 0.8 * n) + 0.75 * root * (0.6 + 0.6 * m) + surf * (0.6 + 0.7 * m)
    g = zone * sub * (0.4 + 0.15 * m)   # a hint of the rock under the water, never a black hole
    return np.clip(r, 0, 1), np.clip(g, 0, 1), m


def foam(ob) -> None:
    """Append the pier-local surf sheet to a joined LOD mesh (after the AO bake and paint): a grid draped just over
    the sea and the awash rock of the shelf, plus a ring round each column foot, on MAT_HeroSurface_PierFoam with
    COLOR_0 = (foam, shallow darkening, phase, 1). Grid quads with neither foam nor darkening are dropped."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    lod = 0 if "_LOD0" in ob.name else 1
    me = ob.data
    if ROCK not in [m.name for m in me.materials if m]:
        return
    ri = [m.name if m else "" for m in me.materials].index(ROCK)
    verts = [v.co.copy() for v in me.vertices]
    polys = [list(p.vertices) for p in me.polygons if p.material_index == ri]
    bvh = BVHTree.FromPolygons(verts, polys)
    ya = math.radians(P.YAW_DEG)
    c_, s_ = math.cos(ya), math.sin(ya)
    to_w = lambda u, v: (u * c_ - v * s_, u * s_ + v * c_)   # noqa: E731
    step = 0.8 if lod == 0 else 1.6
    us = np.arange(P.SHELF[0] - 0.2, 22.0 + 1e-6, step)
    vs = np.arange(-20.0, 20.0 + 1e-6, step)
    U, V = np.meshgrid(us, vs, indexing="ij")
    hr = np.full(U.shape, -9.0)
    for i in range(U.shape[0]):
        for j in range(U.shape[1]):
            x, y = to_w(U[i, j], V[i, j])
            hit = bvh.ray_cast(Vector((x, y, P.Z_SEA + 3.0)), Vector((0.0, 0.0, -1.0)), 6.0)
            if hit[0] is not None:
                hr[i, j] = hit[0].z - P.Z_SEA
    R, G, B = foam_values(U, V, hr)
    Z = np.where(hr <= 0.0, 0.03 + 0.14 * _ss(8.0, 20.0, U), np.minimum(hr + 0.025, 0.2)) + P.Z_SEA  # rides the swell
    bm = bmesh.new()
    bm.from_mesh(me)
    nl0 = len(me.loops)
    cols = []
    fi = len(me.materials)
    me.materials.append(material(FOAM))
    vid = {}

    def vert(i, j):
        if (i, j) not in vid:
            vid[(i, j)] = bm.verts.new((*to_w(U[i, j], V[i, j]), Z[i, j]))
        return vid[(i, j)]

    for i in range(U.shape[0] - 1):
        for j in range(U.shape[1] - 1):
            q = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
            if max(max(R[k], G[k]) for k in q) < 0.03:
                continue
            f = bm.faces.new([vert(*k) for k in q])
            f.material_index = fi
            f.smooth = True
            cols += [(R[k], G[k], B[k], 1.0) for k in q]
    # No collars round the column feet: lifted clear of the swell they floated up to 0.28 m off the water, and the
    # dark algae band showed through their gaps as black cracked plates (round-4 review). The sheet's own surf
    # bands carry the foam near the stem columns.
    nrm_old = np.empty(nl0 * 3)
    me.corner_normals.foreach_get("vector", nrm_old)
    bm.to_mesh(me)
    bm.free()
    nl = len(me.loops)
    ca = me.color_attributes.get("Col")
    data = np.empty(nl * 4)
    ca.data.foreach_get("color", data)
    data = data.reshape(-1, 4)
    data[nl0:] = np.asarray(cols)
    ca.data.foreach_set("color", data.ravel())
    nrm = np.vstack([nrm_old.reshape(-1, 3), np.tile((0.0, 0.0, 1.0), (nl - nl0, 1))])
    me.normals_split_custom_set(nrm.tolist())


def convexity(me: bpy.types.Mesh) -> np.ndarray:
    """Per-vertex convexity (> 0 on outer edges and rock crowns, < 0 in crevices): the mean of
    -dot(normal, edge direction) over the vertex's edges."""
    nv = len(me.vertices)
    co = np.empty(nv * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    nrm = np.empty(nv * 3)
    me.vertex_normals.foreach_get("vector", nrm)
    nrm = nrm.reshape(-1, 3)
    ev = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    d = co[ev[:, 1]] - co[ev[:, 0]]
    d /= np.maximum(np.linalg.norm(d, axis=1), 1e-6)[:, None]
    acc = np.zeros(nv)
    cnt = np.zeros(nv)
    np.add.at(acc, ev[:, 0], -np.einsum("ij,ij->i", nrm[ev[:, 0]], d))
    np.add.at(acc, ev[:, 1], np.einsum("ij,ij->i", nrm[ev[:, 1]], d))
    np.add.at(cnt, ev[:, 0], 1)
    np.add.at(cnt, ev[:, 1], 1)
    return acc / np.maximum(cnt, 1)
