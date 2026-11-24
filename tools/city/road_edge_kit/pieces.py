"""Road edge kit (P92) pieces: every kit piece, its LOD1 and collision, built from kitlib (Blender 5.3).

build_all() makes collection `RoadEdgeKit` with one object per piece and variant (`KIT_*` / `DEC_*`), `<name>_LOD1`
and `<name>_COL` (convex, invisible), all with pivots at the world origin of the piece (see the spec §2) and laid
out on a display grid by object location only (export resets it). Dimensions: ROAD_EDGE_KIT_SPEC.md §1.
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import kitlib as K

SU, SV = K.SHEET_U_M, K.SHEET_V_M
# tile regions (u0, v0) in metres on the trim sheet (spec §3, tiles row 3.0-4.0, decals 4.0-8.0)
TILE = {"manhole": (0.0, 3.0), "chequer": (1.0, 3.0), "gully": (2.05, 3.03), "tray": (2.05, 3.38),
        "tactile": (3.0, 3.0), "slot": (3.825, 3.0)}   # slot is mapped turned 90 degrees (1.0 m along v)
DECAL = {"crack": (0.0, 4.0, 4.0, 0.25), "dust": (0.0, 4.25, 4.0, 0.5), "patch_a": (0.0, 4.75, 1.2, 0.8),
         "patch_b": (1.2, 4.75, 2.0, 1.0), "oil": (3.2, 4.75, 0.8, 0.6), "patch_irr": (0.0, 5.75, 1.5, 1.2),
         "crazing": (1.5, 5.75, 1.0, 1.0), "trench": (0.0, 7.0, 4.0, 0.6)}
CONCRETE_SIDE_V = K.ROW["kerbB"] + 0.30     # side faces of plinths/covers use the precast kerb face texels


# --- mesh helpers ------------------------------------------------------------------------------------------------

def new_obj(name, c, bm=None):
    me = bpy.data.meshes.new(name)
    if bm is not None:
        bm.to_mesh(me)
        bm.free()
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    ob.data.materials.append(K.material())
    return ob


def apply_mods(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, depsgraph=dg)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    me.name = ob.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    if not any(me.materials):                      # the GN sweep leaves one empty slot
        me.materials.clear()
        me.materials.append(K.material())
    for nm in ("uloc", "vlen", "u0", "blen"):      # GN working attributes, not for export
        if nm in me.attributes:
            me.attributes.remove(me.attributes[nm])


def bevel(ob, width, segs=2, angle=40, limit="ANGLE"):
    m = ob.modifiers.new("Bevel", "BEVEL")
    m.width, m.segments, m.limit_method = width, segs, limit
    m.angle_limit = math.radians(angle)
    m.harden_normals = False
    return m


def finish(ob, sharp=35):
    """Smooth by angle + weighted normals (face area, keep sharp), then triangulate (glTF game mesh)."""
    me = ob.data
    for p in me.polygons:
        p.use_smooth = True
    me.set_sharp_from_angle(angle=math.radians(sharp))
    wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.keep_sharp = True
    wn.weight = 50
    tri = ob.modifiers.new("Tri", "TRIANGULATE")
    tri.keep_custom_normals = True
    apply_mods(ob)


def planar_uv(ob, top_uv0, top_origin=(0.0, 0.0), side_v=CONCRETE_SIDE_V, top_rot=0.0):
    """Top faces: planar xy into the sheet region at top_uv0 (metres); side faces: wrap u by xy, v by z into the
    concrete side texels. 1 m on the piece = 1 m on the sheet (256 px/m)."""
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uv = me.uv_layers.active.data
    ox, oy = top_origin
    cr, sr = math.cos(top_rot), math.sin(top_rot)
    for p in me.polygons:
        n = p.normal
        al = [me.vertices[me.loops[li].vertex_index].co.x * abs(n.y) +
              me.vertices[me.loops[li].vertex_index].co.y * abs(n.x) for li in p.loop_indices]
        base = math.floor(min(al) / 4.0) * 4.0          # P92b: wrap once per face (corner-wise % split faces)
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            if n.z > 0.6:
                x, y = co.x - ox, co.y - oy
                x, y = cr * x - sr * y, sr * x + cr * y
                uv[li].uv = ((top_uv0[0] + x) / SU, (top_uv0[1] + y) / SV)
            else:
                along = co.x * abs(n.y) + co.y * abs(n.x)
                uv[li].uv = ((along - base) / SU, (side_v + 0.10 - co.z) / SV)


def cube_bm(sx, sy, sz, cx=0.0, cy=0.0, cz=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=bm.verts)
    return bm


def cyl_bm(r, h, segs, cz=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r, radius2=r, depth=h)
    bmesh.ops.translate(bm, vec=(0, 0, cz), verts=bm.verts)
    return bm


def top_face(bm):
    bm.faces.ensure_lookup_table()
    return max(bm.faces, key=lambda f: f.calc_center_median().z * 10 + f.normal.z)


def recess(bm, inset, depth, face=None):
    """Inset the top face and push the inner face down: a frame with a recessed cover / grate bed."""
    f = face or top_face(bm)
    r = bmesh.ops.inset_region(bm, faces=[f], thickness=inset, depth=0.0, use_even_offset=True)
    bmesh.ops.translate(bm, vec=(0, 0, -depth), verts=f.verts)
    return f


def convex_col(ob, c):
    """Collision <piece>_COL, hidden in renders: convex hull of the LOD1 (welded, outward winding), or for bent runs
    (curves, corners) the LOD1 shape itself as a static non-convex mesh collider."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    if not ob.name.startswith(("KIT_Kerb_Curve", "KIT_Kerb_Corner", "KIT_BorderCourse_R")):
        pts = [v.co.copy() for v in bm.verts]          # hull from the points only, no source faces left over
        bm.free()
        bm = bmesh.new()
        for p in pts:
            bm.verts.new(p)
        res = bmesh.ops.convex_hull(bm, input=bm.verts)
        bmesh.ops.delete(bm, geom=list({*res["geom_interior"], *res["geom_unused"], *res["geom_holes"]}),
                         context="VERTS")
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(1), verts=bm.verts, edges=bm.edges)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    col = new_obj(ob.name.replace("_LOD1", "") + "_COL", c, bm)
    col.display_type = "WIRE"
    col.hide_render = True
    return col


# --- sweeps: kerbs, channels ---------------------------------------------------------------------------------------

def path_poly(name, pts, src):
    return K.curve_obj(name, [(x, y, 0) for x, y in pts], c=src)


def poly_len(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def kerb_piece(name, key, path, length, c, src, block, seed, drop=(1.0, 1.0), lod1_block=1.0, jitter=0.003,
               gap=0.005):
    ob = K.sweep(name, key, path, length, c, src, lod=0, block=block, seed=seed, drop=drop, jitter=jitter, gap=gap)
    apply_mods(ob)
    _drop_uv(ob, key, length, drop)
    finish(ob)
    lo = K.sweep(name + "_LOD1", key, path, length, c, src, lod=1, block=lod1_block, drop=drop)
    apply_mods(lo)
    _drop_uv(lo, key, length, drop)
    bm = bmesh.new()                                   # LOD1 blocks have no gap: weld the shared block ends
    bm.from_mesh(lo.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bm.to_mesh(lo.data)
    bm.free()
    finish(lo, sharp=60)
    return ob, lo


def _drop_uv(ob, key, length, drop):
    """A dropped upstand is the profile squashed in z, but its v kept the full profile length (texels squashed 5x,
    352 px/m). Slide each face/back corner's v towards the top arris by what the drop removed, so the short face
    shows the stone just under the arris at true scale. Profiles run front-bottom -> top -> back (v increases)."""
    if tuple(drop) == (1.0, 1.0):
        return
    pts = K.PROFILES[key]
    ztop = max(p[1] for p in pts)
    ymid = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
    me = ob.data
    uv = me.uv_layers[0].data
    for poly in me.polygons:
        if abs(poly.normal.x) > 0.9:                   # end caps keep their own mapping
            continue
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            k = min(max(drop[0] + (drop[1] - drop[0]) * co.x / length, min(drop)), max(drop))
            zo = max(co.z / k if co.z > 0 else 0.0, 0.0)
            dv = (1.0 - k) * max(ztop - zo, 0.0) * (1.0 if co.y < ymid else -1.0)
            uv[li].uv = (uv[li].uv[0], uv[li].uv[1] + dv / SV)


def _weld_segments(ob, length):
    """Merge the coincident segment ends of a straight run and delete the internal end caps (faces facing along X
    inside the run), so the run is one closed stone."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    caps = [f for f in bm.faces if abs(f.normal.x) > 0.99 and 1e-3 < f.calc_center_median().x < length - 1e-3]
    bmesh.ops.delete(bm, geom=caps, context="FACES_ONLY")
    bm.to_mesh(ob.data)
    bm.free()


def _bend(ob, length, deg, turn):
    """Simple Deform Bend about the piece origin (Z axis): a straight run 0..length along +X becomes an arc of radius
    length / angle starting at the origin heading +X, bending towards +Y for turn=+1 (as kitlib.path_arc)."""
    m = ob.modifiers.new("Bend", "SIMPLE_DEFORM")
    m.deform_method, m.deform_axis = "BEND", "Z"
    m.angle = turn * math.radians(deg)
    apply_mods(ob)


def bent_piece(name, key, r, deg, turn, segs, lod1_segs, c, src):
    """A curved stone: the profile swept straight in `segs` welded segments (no joints), then bent to radius r."""
    ln = r * math.radians(deg)
    path = K.path_line(f"PTH_S_{name}", ln, src)
    ob = K.sweep(name, key, path, ln, c, src, lod=0, block=ln / segs, gap=0.0, jitter=0.0)
    apply_mods(ob)
    _weld_segments(ob, ln)
    _bend(ob, ln, deg, turn)
    finish(ob)
    lo = K.sweep(name + "_LOD1", key, path, ln, c, src, lod=1, block=ln / lod1_segs)
    apply_mods(lo)
    _weld_segments(lo, ln)
    _bend(lo, ln, deg, turn)
    finish(lo, sharp=60)
    return ob, lo


def build_sweeps(c, src):
    out = []
    L1 = K.path_line("PTH_L1", 1.0, src)
    out.append(kerb_piece("KIT_Kerb_Straight_A", "kerbA", L1, 1.0, c, src, 0.5, 11))
    out.append(kerb_piece("KIT_Kerb_Straight_B", "kerbB", L1, 1.0, c, src, 1.0, 12))
    out.append(kerb_piece("KIT_Kerb_Straight_C", "kerbC", L1, 1.0, c, src, 0.5, 13))
    # curves and corner units: one curved stone each (P92b). Granite / precast radius kerbs are cut curved; straight
    # blocks along an arc left wedge gaps at the back and faceted noses. The joints of the 0.5 / 1.0 m units are in
    # the trim texture. turn=+1: footway inside the bend (external corner); R6 is precast B.
    for nm, key, r, deg, segs, lsegs in (("R3", "kerbA", 3.0, 90, 14, 6), ("R6", "kerbB", 6.0, 45, 9, 4),
                                         ("R12", "kerbA", 12.0, 22.5, 6, 3)):
        out.append(bent_piece(f"KIT_Kerb_Curve_{nm}", key, r, deg, 1, segs, lsegs, c, src))
    out.append(bent_piece("KIT_Kerb_Corner_Ext90", "kerbA", 0.5, 90, 1, 5, 3, c, src))
    out.append(bent_piece("KIT_Kerb_Corner_Int90", "kerbB", 0.5, 90, -1, 4, 3, c, src))
    sp = [(0, 0), (0.6, 0), (0.6 + 0.6 * math.cos(math.radians(45)), 0.6 * math.sin(math.radians(45)))]
    p = path_poly("PTH_Splay45", sp, src)
    out.append(kerb_piece("KIT_Kerb_Corner_Splay45", "kerbA", p, poly_len(sp), c, src, 0.6, 33, lod1_block=0.6))
    # dropped kerbs (precast B): 150 mm -> 25 mm ramp, 25 mm flat (drive), 6 mm flush (crossing)
    out.append(kerb_piece("KIT_Kerb_Dropped_Ramp", "kerbB", L1, 1.0, c, src, 1.0, 41, drop=(1.0, 0.17),
                          lod1_block=0.25))
    out.append(kerb_piece("KIT_Kerb_Dropped_Flat", "kerbB", L1, 1.0, c, src, 1.0, 42, drop=(0.17, 0.17)))
    out.append(kerb_piece("KIT_Kerb_Dropped_RampUp", "kerbB", L1, 1.0, c, src, 1.0, 44, drop=(0.17, 1.0),
                          lod1_block=0.25))
    out.append(kerb_piece("KIT_Kerb_Dropped_Flush", "kerbB", L1, 1.0, c, src, 1.0, 43, drop=(0.04, 0.04)))
    # channel 1 m units
    out.append(kerb_piece("KIT_Gutter_Plain", "channel", L1, 1.0, c, src, 1.0, 51, jitter=0.0015))
    # grey paver border course between kerb A and the red footway (sea side, sv_03 / sv_05): straight 2 m and the
    # three kerb curves; 0.5 m settle blocks with no gap (joints are the drawn paver joints), 1.5 mm settle jitter
    L2 = K.path_line("PTH_L2", 2.0, src)
    out.append(kerb_piece("KIT_BorderCourse_Straight", "border", L2, 2.0, c, src, 0.5, 91, jitter=0.0015, gap=0.0,
                          lod1_block=2.0))
    for nm, r, deg, segs in (("R3", 3.0, 90, 14), ("R6", 6.0, 45, 9), ("R12", 12.0, 22.5, 6)):
        out.append(bent_piece(f"KIT_BorderCourse_{nm}", "border", r, deg, 1, segs, max(2, segs // 2), c, src))
    return out


# --- covers, grates, plinths ----------------------------------------------------------------------------------------

def _cover(name, c, sx, sy, frame, depth, tile, centre=(0.0, 0.0), proud=0.004, thick=0.06, rot=0.0):
    """Rectangular frame + recessed bed, flush with the surface (a few mm proud), top mapped onto a tile."""
    bm = cube_bm(sx, sy, thick, centre[0], centre[1], proud - thick / 2)
    recess(bm, frame, depth)
    ob = new_obj(name, c, bm)
    bevel(ob, 0.004, 1, 30)
    apply_mods(ob)
    planar_uv(ob, tile, (centre[0] - sx / 2, centre[1] - sy / 2), top_rot=rot)
    finish(ob)
    return ob


def _lod_plate(name, c, sx, sy, tile, centre=(0.0, 0.0), proud=0.004, rot=0.0):
    bm = cube_bm(sx, sy, 0.02, centre[0], centre[1], proud - 0.01)
    ob = new_obj(name, c, bm)
    planar_uv(ob, tile, (centre[0] - sx / 2, centre[1] - sy / 2), top_rot=rot)
    finish(ob, 60)
    return ob


def build_covers(c):
    out = []
    # gully grates in the channel (pivot at the kerb face foot: grate centre 0.17 m out on the road side)
    g = _cover("KIT_DrainGrate_Gully", c, 0.60, 0.30, 0.04, 0.012, TILE["gully"], (0.0, -0.17), proud=0.009)
    out.append((g, _lod_plate("KIT_DrainGrate_Gully_LOD1", c, 0.6, 0.3, TILE["gully"], (0, -0.17), 0.009)))
    slot_uv = (TILE["slot"][0] + 0.15, TILE["slot"][1])
    s = _cover("KIT_DrainGrate_Slot", c, 1.00, 0.15, 0.025, 0.008, slot_uv, (0.0, 0.0), rot=math.pi / 2)
    out.append((s, _lod_plate("KIT_DrainGrate_Slot_LOD1", c, 1.0, 0.15, slot_uv, rot=math.pi / 2)))
    ch = _cover("KIT_DrainGrate_Chamber", c, 0.60, 0.45, 0.035, 0.006, TILE["tray"], (0.0, 0.0))
    out.append((ch, _lod_plate("KIT_DrainGrate_Chamber_LOD1", c, 0.6, 0.45, TILE["tray"])))
    # manholes
    out.append(_manhole_round(c))
    sq = _cover("KIT_Manhole_SquareChequer", c, 0.70, 0.70, 0.05, 0.004, (TILE["chequer"][0] + 0.15,
                TILE["chequer"][1] + 0.15), (0.0, 0.0), proud=0.006)
    out.append((sq, _lod_plate("KIT_Manhole_SquareChequer_LOD1", c, 0.7, 0.7,
                               (TILE["chequer"][0] + 0.15, TILE["chequer"][1] + 0.15), proud=0.006)))
    tr = _cover("KIT_Manhole_ConcreteTray", c, 0.60, 0.60, 0.03, 0.008, TILE["tray"], (0.0, 0.0), proud=0.005)
    out.append((tr, _lod_plate("KIT_Manhole_ConcreteTray_LOD1", c, 0.6, 0.6, TILE["tray"], proud=0.005)))
    return out


def _manhole_round(c):
    """0.70 m round cast cover in a 0.95 m square concrete surround (gf_23)."""
    bm = cube_bm(0.95, 0.95, 0.08, 0, 0, 0.005 - 0.04)
    f = top_face(bm)
    ob = new_obj("KIT_Manhole_Round", c, bm)
    cut = new_obj("_cut_manhole", c, cyl_bm(0.36, 0.2, 16, 0.0))
    b = ob.modifiers.new("Hole", "BOOLEAN")
    b.object, b.operation, b.solver = cut, "DIFFERENCE", "EXACT"
    apply_mods(ob)
    bpy.data.objects.remove(cut)
    cov = cyl_bm(0.35, 0.05, 16, 0.002 - 0.025)    # P92b: flat cover, the raised rim and pattern are in the normal
    cov_ob = new_obj("_cov", c, cov)
    j = ob.modifiers.new("Join", "BOOLEAN")
    j.object, j.operation, j.solver = cov_ob, "UNION", "EXACT"
    apply_mods(ob)
    bpy.data.objects.remove(cov_ob)
    planar_uv(ob, (TILE["manhole"][0] + 0.5, TILE["manhole"][1] + 0.5))
    finish(ob)
    lo = new_obj("KIT_Manhole_Round_LOD1", c, cube_bm(0.95, 0.95, 0.02, 0, 0, 0.004 - 0.01))
    planar_uv(lo, (TILE["manhole"][0] + 0.5, TILE["manhole"][1] + 0.5))
    finish(lo, 60)
    return ob, lo


def build_plinths(c, src):
    out = []
    # square bollard plinth 0.40 m, 0.12 proud, chamfered, with a steel collar socket (sv_03, gf_25)
    bm = cube_bm(0.40, 0.40, 0.20, 0, 0, 0.12 - 0.10)
    f = top_face(bm)
    bmesh.ops.inset_region(bm, faces=[f], thickness=0.03, depth=0.0, use_even_offset=True)
    bmesh.ops.translate(bm, vec=(0, 0, 0.012), verts=f.verts)          # weathered crown, sheds water
    ob = new_obj("KIT_BollardBase_Square", c, bm)
    bevel(ob, 0.012, 1, 40)                                             # plinth arrises first, collar stays crisp
    apply_mods(ob)
    col = new_obj("_collar", c, cyl_bm(0.065, 0.05, 8, 0.12 + 0.012 + 0.015))
    u = ob.modifiers.new("Collar", "BOOLEAN")
    u.object, u.operation, u.solver = col, "UNION", "EXACT"
    apply_mods(ob)
    bpy.data.objects.remove(col)
    _drop_bottom(ob)
    planar_uv(ob, (0.3, K.ROW["foot"] + 0.25))
    finish(ob)
    lo = new_obj("KIT_BollardBase_Square_LOD1", c, cube_bm(0.40, 0.40, 0.20, 0, 0, 0.02))
    planar_uv(lo, (0.3, K.ROW["foot"] + 0.25))
    finish(lo, 60)
    out.append((ob, lo))
    # round plinth 0.35 m, 16 sides
    bm = cyl_bm(0.175, 0.20, 12, 0.02)
    ob = new_obj("KIT_BollardBase_Round", c, bm)
    bevel(ob, 0.015, 1, 40)
    apply_mods(ob)
    _drop_bottom(ob)
    planar_uv(ob, (1.3, K.ROW["foot"] + 0.25))
    finish(ob)
    lo = new_obj("KIT_BollardBase_Round_LOD1", c, cyl_bm(0.175, 0.20, 8, 0.02))
    planar_uv(lo, (1.3, K.ROW["foot"] + 0.25))
    finish(lo, 60)
    out.append((ob, lo))
    # loose precast kerb stone used as a wheel stop (car park, tuk rank; sv_08)
    p = K.path_line("PTH_L09", 0.9, src)
    ob, lo = kerb_piece("KIT_BollardBase_WheelStop", "kerbB", p, 0.9, c, src, 0.9, 61, jitter=0.006)
    out.append((ob, lo))
    return out


# --- slabs, tactile, decals -----------------------------------------------------------------------------------------

FOOT_Y0, FOOT_Z = 0.255, 0.15   # footway starts behind a 0.26 m kerb top, flush with it


def _slab_field(name, c, nx, ny, sx, sy, seed, sunk=None, gap=0.006, tilt=0.004, bevel_w=0.0):
    """nx x ny slabs (Array modifiers), each settled by a few mm (loose-part transforms, seeded). P92b: no mesh bevel
    on the 0.5 m slabs (336 -> 80 tris for 2 m x 1 m); the arris chamfer is in the baked normal of the slab row."""
    import random
    rnd = random.Random(seed)
    bm = cube_bm(sx - gap, sy - gap, FOOT_Z, (sx) / 2, FOOT_Y0 + sy / 2, FOOT_Z / 2)   # P92b: down to z 0 (pivot)
    ob = new_obj(name, c, bm)
    if bevel_w:
        bevel(ob, bevel_w, 1, 30)
    ax = ob.modifiers.new("ArrX", "ARRAY")
    ax.count, ax.use_relative_offset, ax.use_constant_offset = nx, False, True
    ax.constant_offset_displace = (sx, 0, 0)
    ay = ob.modifiers.new("ArrY", "ARRAY")
    ay.count, ay.use_relative_offset, ay.use_constant_offset = ny, False, True
    ay.constant_offset_displace = (0, sy, 0)
    apply_mods(ob)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    parts = _loose_parts(bm)
    for i, verts in enumerate(parts):
        cen = sum((v.co for v in verts), Vector()) / len(verts)
        dz = rnd.uniform(-0.002, 0.002)
        ang = (rnd.uniform(-tilt, tilt), rnd.uniform(-tilt, tilt))
        if sunk is not None and i == sunk:
            dz, ang = -0.018, (0.025, -0.012)       # settled slab over a soft spot / roots
        m = (Matrix.Translation(cen + Vector((0, 0, dz))) @ Matrix.Rotation(ang[0], 4, "X") @
             Matrix.Rotation(ang[1], 4, "Y") @ Matrix.Translation(-cen))
        bmesh.ops.transform(bm, matrix=m, verts=verts)
    bm.to_mesh(ob.data)
    bm.free()
    _drop_bottom(ob)
    return ob


def _drop_bottom(ob, z=None):
    """Delete faces facing down (never seen; the piece sits on or in the ground)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z < -0.9], context="FACES")
    bm.to_mesh(ob.data)
    bm.free()


def _loose_parts(bm):
    bm.verts.ensure_lookup_table()
    seen, parts = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, part = [v], []
        seen.add(v.index)
        while stack:
            x = stack.pop()
            part.append(x)
            for e in x.link_edges:
                o = e.other_vert(x)
                if o.index not in seen:
                    seen.add(o.index)
                    stack.append(o)
        parts.append(part)
    return parts


def build_footway(c):
    out = []
    # A: 0.5 m precast slabs, 4 x 2 over 2 m x 1 m (gf_21, gf_23)
    a = _slab_field("KIT_PavementEdge_Slabs", c, 4, 2, 0.5, 0.5, 71)
    # B: cast bays 1.0 x 1.0 with a sawn 12 mm expansion joint between them (land-side footway)
    b = _slab_field("KIT_PavementEdge_CastBays", c, 2, 1, 1.0, 1.0, 72, gap=0.012, tilt=0.002, bevel_w=0.006)
    # C: 0.5 m slabs, one sunk and tilted (roots / soft fill)
    cc = _slab_field("KIT_PavementEdge_Sunk", c, 4, 2, 0.5, 0.5, 73, sunk=5)
    for ob in (a, b, cc):
        planar_uv(ob, (0.0, K.ROW["foot"] - FOOT_Y0), (0.0, 0.0), side_v=K.ROW["kerbB"] + 0.30)
        finish(ob)
        lo = new_obj(ob.name + "_LOD1", c, cube_bm(2.0, 1.0, FOOT_Z, 1.0, FOOT_Y0 + 0.5, FOOT_Z / 2))
        _drop_bottom(lo)
        planar_uv(lo, (0.0, K.ROW["foot"] - FOOT_Y0))
        finish(lo, 60)
        out.append((ob, lo))
    return out


def build_tactile(c):
    out = []
    for nm, sx in (("KIT_TactilePad_1200", 1.2), ("KIT_TactilePad_2400", 2.4)):
        bm = cube_bm(sx, 0.8, FOOT_Z + 0.004, sx / 2, FOOT_Y0 + 0.4, (FOOT_Z + 0.004) / 2)   # P92b: base at z 0
        ob = new_obj(nm, c, bm)
        bevel(ob, 0.003, 1, 30)
        apply_mods(ob)
        # 0.4 m tiles repeat inside the 1 m tactile tile: map the pad in 1.2 m chunks wrapping on 0.8 m (2 tiles)
        planar_uv(ob, (TILE["tactile"][0], TILE["tactile"][1]), (0.0, FOOT_Y0))
        _wrap_u(ob, TILE["tactile"][0], 0.8)
        finish(ob)
        lo = new_obj(nm + "_LOD1", c, cube_bm(sx, 0.8, FOOT_Z + 0.004, sx / 2, FOOT_Y0 + 0.4, (FOOT_Z + 0.004) / 2))
        _drop_bottom(lo)
        planar_uv(lo, (TILE["tactile"][0], TILE["tactile"][1]), (0.0, FOOT_Y0))
        out.append((ob, lo))
    return out


def _wrap_u(ob, u0, period):
    """Keep top UVs inside one tile by splitting the pad into faces of whole tiles is overkill: the pad's top is
    subdivided at every `period` metres along x so each face maps to the same tile range."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    xs = [v.co.x for v in bm.verts]
    x = min(xs) + period
    while x < max(xs) - 1e-4:
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(x, 0, 0),
                               plane_no=(1, 0, 0))
        x += period
    bm.to_mesh(me)
    bm.free()
    uv = me.uv_layers.active.data
    for p in me.polygons:
        if p.normal.z < 0.6:
            continue
        cx = p.center.x
        k = math.floor((cx - min(xs)) / period)
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv[li].uv = ((u0 + (co.x - min(xs)) - k * period) / SU, uv[li].uv[1])


def build_decals(c):
    """Opaque mesh decals 4 mm above the asphalt (their edges fade to the sheet asphalt, no alpha)."""
    out = []
    for key, (u0, v0, w, h) in DECAL.items():
        name = "DEC_RoadEdge_" + "".join(s.capitalize() for s in key.split("_"))
        nx = max(1, round(w / 1.0))
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=nx, y_segments=1, size=0.5)
        bmesh.ops.scale(bm, vec=(w, h, 1), verts=bm.verts)
        # road-edge decals run along the kerb: the strip's back edge sits on the channel edge (y = -0.36)
        bmesh.ops.translate(bm, vec=(w / 2, -0.36 - h / 2, 0.004), verts=bm.verts)
        ob = new_obj(name, c, bm)
        me = ob.data
        me.uv_layers.new(name="UVMap")
        uv = me.uv_layers.active.data
        for p in me.polygons:
            for li in p.loop_indices:
                co = me.vertices[me.loops[li].vertex_index].co
                uv[li].uv = ((u0 + co.x) / SU, (v0 + (co.y + 0.36 + h)) / SV)
        finish(ob, 60)
        out.append((ob, None))
    return out


# crossover ramps behind the dropped kerbs (P92b): the footway falls from 0.15 m to the dropped kerb top over 1.0 m,
# so no 0.13 m step is left behind a dropped kerb. Front edge on the kerb B back (y 0.235, 5 mm under the kerb top),
# back edge flush with the footway. Front height per kerb: Flat 0.0255 (0.17 x 0.15), Flush 0.006, and the two
# transition units follow Dropped_Ramp (0.15 -> 0.0255) and Dropped_RampUp. Surfaces: Paver = grey 200 x 100 mm
# stretcher pavers (sea side, framed like the border course), Conc = footway concrete row (land side).
XO_Y0, XO_D = 0.235, 1.0
XO_FRONT = {"Flat": (0.0255, 0.0255), "Flush": (0.006, 0.006), "SideDown": (FOOT_Z, 0.0255),
            "SideUp": (0.0255, FOOT_Z)}
XO_UV = {"Paver": (2.5, 5.80), "Conc": (0.0, K.ROW["foot"])}


def _crossover(name, c, front, uv0, lod=0):
    """Grid (1 or 2 x 2) whose height is the linear ramp from the front edge to the footway; LOD0 gets 0.06 m Solidify
    skirts (skirts hide placement gaps), the bottom left open (it sits on the cell ground)."""
    z0, z1 = front
    xs = 1 if z0 == z1 else 2
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=xs, y_segments=1 if lod else 2, size=0.5)
    bmesh.ops.scale(bm, vec=(1.0, XO_D, 1.0), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0.5, XO_Y0 + XO_D / 2, 0.0), verts=bm.verts)
    for v in bm.verts:
        zf = z0 + (z1 - z0) * v.co.x
        v.co.z = zf + (FOOT_Z - zf) * (v.co.y - XO_Y0) / XO_D
    if lod:                                            # P92b: a front skirt to z 0 (pivot at base, hides the seam)
        fe = [e for e in bm.edges if all(abs(v.co.y - XO_Y0) < 1e-6 for v in e.verts)]
        ret = bmesh.ops.extrude_edge_only(bm, edges=fe)
        for v in [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]:
            v.co.z = 0.0
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        if max(bm.faces, key=lambda f: f.calc_center_median().z).normal.z < 0:
            bmesh.ops.reverse_faces(bm, faces=bm.faces)
    ob = new_obj(name, c, bm)
    if not lod:
        so = ob.modifiers.new("Skirt", "SOLIDIFY")
        so.thickness, so.offset, so.use_even_offset = 0.06, -1.0, True
        apply_mods(ob)
        _drop_bottom(ob)
    planar_uv(ob, uv0, (0.0, XO_Y0), side_v=K.ROW["kerbB"] + 0.30)
    finish(ob, 60 if lod else 35)
    return ob


def build_crossovers(c):
    out = []
    for kind, front in XO_FRONT.items():
        for surf, uv0 in XO_UV.items():
            nm = f"KIT_Crossover_{kind}_{surf}"
            out.append((_crossover(nm, c, front, uv0), _crossover(nm + "_LOD1", c, front, uv0, lod=1)))
    return out


def gutter_variants(c, src):
    """Channel with a gully grate, and a kerb inlet unit (kerb B with a 0.6 x 0.08 m mouth over the gully)."""
    out = []
    L1 = bpy.data.objects["PTH_L1"]
    ob, lo = kerb_piece("KIT_Gutter_Gully", "channel", L1, 1.0, c, src, 1.0, 52, jitter=0.0015)
    g = _cover("_gully_tmp", c, 0.60, 0.30, 0.04, 0.012, TILE["gully"], (0.5, -0.17), proud=0.012)
    _join(ob, g)
    out.append((ob, lo))
    kb = K.sweep("KIT_Gutter_KerbInlet", "kerbB", L1, 1.0, c, src, lod=0, block=1.0, seed=53)
    apply_mods(kb)
    cut = new_obj("_mouth", c, cube_bm(0.60, 0.14, 0.08, 0.5, 0.02, 0.045))
    b = kb.modifiers.new("Mouth", "BOOLEAN")
    b.object, b.operation, b.solver = cut, "DIFFERENCE", "EXACT"
    apply_mods(kb)
    bpy.data.objects.remove(cut)
    ch = K.sweep("_ch_tmp", "channel", L1, 1.0, c, src, lod=0, block=1.0, seed=54, jitter=0.0015)
    apply_mods(ch)
    _join(kb, ch)
    finish(kb)
    lo2 = K.sweep("KIT_Gutter_KerbInlet_LOD1", "kerbB", L1, 1.0, c, src, lod=1, block=1.0)
    apply_mods(lo2)
    finish(lo2, 60)
    out.append((kb, lo2))
    return out


def _join(a, b):
    bm = bmesh.new()
    bm.from_mesh(a.data)
    bm.from_mesh(b.data)
    bm.to_mesh(a.data)
    bm.free()
    bpy.data.objects.remove(b)


# --- all ------------------------------------------------------------------------------------------------------------

def build_all():
    old = bpy.data.collections.get("RoadEdgeKit")      # rebuild only the kit; other scenes keep their objects
    if old:
        for o in list(old.all_objects):
            bpy.data.objects.remove(o)
    for m in list(bpy.data.meshes):
        if m.users == 0:
            bpy.data.meshes.remove(m)
    c = K.coll("RoadEdgeKit")
    src = K.coll("_src", c)
    K.sweep_group()
    pairs = []
    pairs += build_sweeps(c, src)
    pairs += gutter_variants(c, src)
    pairs += build_covers(c)
    pairs += build_plinths(c, src)
    pairs += build_footway(c)
    pairs += build_tactile(c)
    pairs += build_crossovers(c)
    pairs += build_decals(c)
    for ob, lo in pairs:
        if ob.name.startswith("KIT_Crossover"):          # the top sheet's hull is flat: hull the closed LOD0
            convex_col(ob, c)
            continue
        if lo is not None and not ob.name.startswith(("KIT_Manhole", "KIT_DrainGrate", "KIT_Tactile", "KIT_Gutter_P",
                                                      "KIT_Gutter_G")):
            convex_col(lo, c)
    layout(pairs)
    return pairs


def layout(pairs, cols=6, dx=4.5, dy=3.5):
    """Display grid by object location only (pivots stay at each piece's origin)."""
    for i, (ob, lo) in enumerate(pairs):
        x, y = (i % cols) * dx, -(i // cols) * dy
        ob.location = (x, y, 0)
        if lo is not None:
            lo.location = (x, y - 1.6, 0)
            lo.hide_render = True
        col = bpy.data.objects.get(ob.name + "_COL")
        if col:
            col.location = lo.location if lo is not None else ob.location
