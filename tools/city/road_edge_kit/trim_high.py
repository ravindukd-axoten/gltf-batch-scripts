"""Road edge trim sheet high-poly (P92): the bake source for T_RoadEdgeTrim_A rows v 0-4 m (kerbs, channel, footway,
covers, grates, tactile). Laid flat at true scale (X = u metres, Y = v metres, Z up), built from primitives with
Bevel / Subdivision / Displace / Array / Boolean modifiers, then baked onto TRIM_Low (a 4 x 4 m plane, UV 0..1) with
the MCP bake_maps tool (normal, ao, curvature). Row layout: ROAD_EDGE_KIT_SPEC.md §3 and pieces.TILE.
"""
from __future__ import annotations

import math

import bmesh
import bpy

import kitlib as K
import pieces as P

TOP = 0.0      # every surface's top at z = 0; recesses go below


def _obj(name, bm, c):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    return ob


def _noise_tex(name, size, kind="CLOUDS", depth=2):
    t = bpy.data.textures.get(name) or bpy.data.textures.new(name, kind)
    t.noise_scale = size
    if hasattr(t, "noise_depth"):
        t.noise_depth = depth
    return t


def block(name, c, sx, sy, cx, cy, gap, bev=0.004, rough=0.0012, sub=5, seed=0.0, h=0.08):
    """One stone / slab: bevelled box, subdivided and displaced by a fine noise (aggregate, worn top)."""
    bm = P.cube_bm(sx - gap, sy - gap, h, cx, cy, TOP - h / 2)
    ob = _obj(name, bm, c)
    b = ob.modifiers.new("Bevel", "BEVEL")
    b.width, b.segments, b.limit_method = bev, 3, "ANGLE"
    s = ob.modifiers.new("Sub", "SUBSURF")
    s.subdivision_type, s.levels, s.render_levels = "SIMPLE", sub, sub
    d = ob.modifiers.new("Grain", "DISPLACE")
    d.texture = _noise_tex("TX_Grain", 0.012, depth=3)
    d.texture_coords, d.strength, d.mid_level = "GLOBAL", rough, 0.5
    d2 = ob.modifiers.new("Undulate", "DISPLACE")
    d2.texture = _noise_tex("TX_Undulate", 0.25, depth=1)
    d2.texture_coords, d2.strength = "GLOBAL", rough * 1.5
    # chipped arrises: a coarse noise only where the bevel turns down (vertex group would be per vertex; instead a
    # strong low-frequency displace masked by the bevel through the texture's contrast)
    return ob


def bed(c, x0, y0, sx, sy, z=-0.012, name="bed"):
    """Mortar / sand bed seen in the joints."""
    return _obj(name, P.cube_bm(sx, sy, 0.01, x0 + sx / 2, y0 + sy / 2, z), c)


def row_blocks(c, v0, height, unit, gap, seed, bev=0.004, rough=0.0012):
    n = int(round(4.0 / unit))
    for i in range(n):
        block(f"HP_r{v0}_{i}", c, unit, height + 0.02, unit * i + unit / 2, v0 + height / 2, gap, bev, rough,
              seed=seed + i)
    bed(c, 0, v0, 4.0, height, name=f"HP_bed{v0}")


def arr(ob, count, off, name="Arr"):
    a = ob.modifiers.new(name, "ARRAY")
    a.count, a.use_relative_offset, a.use_constant_offset = count, False, True
    a.constant_offset_displace = off
    return a


def boolean(ob, cutter, op="DIFFERENCE"):
    b = ob.modifiers.new("Bool", "BOOLEAN")
    b.object, b.operation, b.solver = cutter, op, "EXACT"
    cutter.hide_render = cutter.hide_viewport = True
    return b


def build(c=None):
    sc = bpy.data.scenes.get("TrimHigh") or bpy.data.scenes.new("TrimHigh")
    for o in list(sc.objects):
        bpy.data.objects.remove(o)
    c = sc.collection
    R = K.ROW
    # kerbs: granite 0.5 m, precast 1.0 m, painted 0.5 m (joints 5-8 mm, chips on the arrises)
    row_blocks(c, R["kerbA"], 0.5, 0.5, 0.008, 100, bev=0.006, rough=0.0015)
    row_blocks(c, R["kerbB"], 0.5, 1.0, 0.006, 200, bev=0.004, rough=0.0008)
    row_blocks(c, R["kerbC"], 0.5, 0.5, 0.008, 300, bev=0.008, rough=0.0012)
    # channel units 1 m, 0.36 m wide, then asphalt fade band (flat, fine grain only)
    row_blocks(c, R["channel"], 0.38, 1.0, 0.006, 400, bev=0.003, rough=0.0008)
    asp = block("HP_asphalt_fade", c, 4.0, 0.12, 2.0, R["channel"] + 0.44, 0.0, bev=0.0005, rough=0.002)
    # footway: 0.5 m slabs, sawn expansion joint (12 mm) at u = 2 m and 4 m
    for j in range(2):
        for i in range(8):
            gap = 0.012 if i in (3, 7) else 0.006
            block(f"HP_slab_{j}_{i}", c, 0.5, 0.5, 0.25 + 0.5 * i, R["foot"] + 0.25 + 0.5 * j, gap,
                  bev=0.004, rough=0.001)
    bed(c, 0, R["foot"], 4.0, 1.0, name="HP_bed_foot")
    _tiles(c)
    return sc


def _tiles(c):
    T = P.TILE
    v0 = K.ROW["tiles"]
    # concrete ground for the whole tiles row (surrounds), recesses cut by the covers sitting 1-3 mm proud
    ground = block("HP_tiles_ground", c, 4.0, 1.0, 2.0, v0 + 0.5, 0.0, bev=0.0005, rough=0.001)
    # round manhole: 0.70 m cover, 35 mm rim, field of raised square bosses (cast pattern), two key slots
    cx, cy = T["manhole"][0] + 0.5, T["manhole"][1] + 0.5
    rim = _obj("HP_mh_rim", P.cyl_bm(0.35, 0.02, 64, 0.002 - 0.01), c)
    rim.location = (cx, cy, 0)
    bev = rim.modifiers.new("Bevel", "BEVEL")
    bev.width, bev.segments = 0.004, 2
    field_cut = _obj("HP_mh_fieldcut", P.cyl_bm(0.315, 0.02, 64, 0.0), c)
    field_cut.location = (cx, cy, 0.0045)
    boolean(rim, field_cut)
    boss = _obj("HP_mh_boss", P.cube_bm(0.022, 0.022, 0.006, cx - 0.30, cy - 0.30, -0.003), c)
    arr(boss, 14, (0.045, 0, 0), "ArrX")
    arr(boss, 14, (0, 0.045, 0), "ArrY")
    clip = _obj("HP_mh_clip", P.cyl_bm(0.30, 0.1, 48, 0.0), c)
    clip.location = (cx, cy, 0)
    boolean(boss, clip, "INTERSECT")
    for k, dx in enumerate((-0.12, 0.12)):
        key = _obj(f"HP_mh_key{k}", P.cube_bm(0.06, 0.018, 0.03, cx + dx, cy, 0.0), c)
        boolean(rim, key)
    # gap ring between surround and cover
    ring = _obj("HP_mh_gap", P.cyl_bm(0.358, 0.03, 64, 0.0), c)
    ring.location = (cx, cy, 0)
    boolean(ground, ring)
    # square chequer cover 0.70: 50 mm frame, raised diagonal bars in two directions
    qx, qy = T["chequer"][0] + 0.5, T["chequer"][1] + 0.5
    frame = _obj("HP_cq_frame", P.cube_bm(0.70, 0.70, 0.02, qx, qy, 0.002 - 0.01), c)
    hole = _obj("HP_cq_hole", P.cube_bm(0.60, 0.60, 0.03, qx, qy, 0.0), c)
    boolean(frame, hole)
    plate = _obj("HP_cq_plate", P.cube_bm(0.595, 0.595, 0.01, qx, qy, -0.004 - 0.005), c)
    for k, ang in enumerate((45, -45)):
        bar = _obj(f"HP_cq_bar{k}", P.cube_bm(0.012, 0.045, 0.004, 0, 0, -0.004 + 0.002), c)
        bar.rotation_euler = (0, 0, math.radians(ang))
        # rotated grids start at the diamond's corner so 18 x 18 bars cover the whole 0.6 m plate
        bar.location = (qx, qy - 0.75, 0) if k == 0 else (qx - 0.75 + 0.03, qy, 0)
        arr(bar, 18, (0.06, 0.0, 0), "ArrA")
        arr(bar, 18, (0.0, 0.06, 0), "ArrB")
        clipq = _obj(f"HP_cq_clip{k}", P.cube_bm(0.59, 0.59, 0.1, qx, qy, 0.0), c)
        # arrays run in the bar's local axes; keep them axis-aligned by applying the rotation to the cutter only
        boolean(bar, clipq, "INTERSECT")
    gapq = _obj("HP_cq_gap", P.cube_bm(0.71, 0.71, 0.03, qx, qy, 0.0), c)
    boolean(ground, gapq)
    # gully grate 0.60 x 0.30: 40 mm frame, 13 bars across the flow over a dark bed 60 mm down
    gx, gy = T["gully"][0] + 0.30, T["gully"][1] + 0.15
    _grate(c, ground, "gully", gx, gy, 0.60, 0.30, 0.04, bars_along_v=True, pitch=0.042)
    # concrete-filled tray / chamber 0.60 x 0.60: 30 mm steel frame, concrete infill 8 mm down
    tx, ty = T["tray"][0] + 0.30, T["tray"][1] + 0.30
    fr = _obj("HP_tr_frame", P.cube_bm(0.60, 0.60, 0.02, tx, ty, 0.001 - 0.01), c)
    fh = _obj("HP_tr_hole", P.cube_bm(0.54, 0.54, 0.03, tx, ty, 0.0), c)
    boolean(fr, fh)
    block("HP_tr_infill", c, 0.535, 0.535, tx, ty, 0.0, bev=0.002, rough=0.0015, h=0.02).location.z = -0.008
    gapt = _obj("HP_tr_gap", P.cube_bm(0.61, 0.61, 0.03, tx, ty, 0.0), c)
    boolean(ground, gapt)
    # linear slot grate (mapped turned: 0.15 wide in u, 1.0 long in v)
    sx, sy = T["slot"][0] + 0.075, T["slot"][1] + 0.5
    _grate(c, ground, "slot", sx, sy, 0.15, 1.0, 0.025, bars_along_v=False, pitch=0.05)
    # tactile: 0.8 x 0.8 of 0.4 m tiles, 25 mm blisters 5 mm high on a 50 mm grid (aligned)
    ax, ay = T["tactile"]
    for i in range(2):
        for j in range(2):
            block(f"HP_tac_{i}{j}", c, 0.4, 0.4, ax + 0.2 + 0.4 * i, ay + 0.2 + 0.4 * j, 0.004, bev=0.003,
                  rough=0.0006, sub=3)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=6, radius=0.0125)
    bmesh.ops.scale(bm, vec=(1, 1, 0.4), verts=bm.verts)
    bl = _obj("HP_tac_blister", bm, c)
    bl.location = (ax + 0.025, ay + 0.025, 0.0)
    arr(bl, 16, (0.05, 0, 0), "ArrX")
    arr(bl, 16, (0, 0.05, 0), "ArrY")


def _grate(c, ground, nm, cx, cy, sx, sy, frame, bars_along_v, pitch):
    fr = _obj(f"HP_{nm}_frame", P.cube_bm(sx, sy, 0.02, cx, cy, 0.002 - 0.01), c)
    hole = _obj(f"HP_{nm}_hole", P.cube_bm(sx - 2 * frame, sy - 2 * frame, 0.03, cx, cy, 0.0), c)
    boolean(fr, hole)
    floor = _obj(f"HP_{nm}_floor", P.cube_bm(sx - 2 * frame, sy - 2 * frame, 0.01, cx, cy, -0.065), c)
    inner_u, inner_v = sx - 2 * frame, sy - 2 * frame
    if bars_along_v:      # bars parallel to v, repeated along u
        n = int(inner_u / pitch)
        bar = _obj(f"HP_{nm}_bar", P.cube_bm(0.016, inner_v, 0.04, cx - inner_u / 2 + pitch / 2, cy, -0.02 + 0.001), c)
        arr(bar, n, (pitch, 0, 0))
    else:
        n = int(inner_v / pitch)
        bar = _obj(f"HP_{nm}_bar", P.cube_bm(inner_u, 0.012, 0.04, cx, cy - inner_v / 2 + pitch / 2, -0.02 + 0.001), c)
        arr(bar, n, (0, pitch, 0))
    b = bar.modifiers.new("Bevel", "BEVEL")
    b.width, b.segments = 0.002, 2
    cut = _obj(f"HP_{nm}_gcut", P.cube_bm(sx + 0.01, sy + 0.01, 0.1, cx, cy, -0.04), c)
    boolean(ground, cut)


def low_plane():
    """TRIM_Low: 4 x 4 m plane covering sheet rows v 0-4 m, UV 0..1, in the TrimHigh scene."""
    sc = bpy.data.scenes["TrimHigh"]
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=2.0)
    bmesh.ops.translate(bm, vec=(2.0, 2.0, 0.01), verts=bm.verts)
    me = bpy.data.meshes.new("TRIM_Low")
    bm.to_mesh(me)
    bm.free()
    uv = me.uv_layers.new(name="UVMap")
    for p in me.polygons:
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = (co.x / 4.0, co.y / 4.0)
    ob = bpy.data.objects.get("TRIM_Low") or bpy.data.objects.new("TRIM_Low", me)
    ob.data = me
    if ob.name not in sc.collection.objects:
        sc.collection.objects.link(ob)
    return ob


def join_high():
    """Apply all modifiers and join the high-poly into TRIM_High (one bake source)."""
    sc = bpy.data.scenes["TrimHigh"]
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    for ob in list(sc.objects):
        if ob.type != "MESH" or not ob.name.startswith("HP_") or ob.hide_render:
            continue
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        me.transform(ob.matrix_world)
        bm.from_mesh(me)
        ev.to_mesh_clear()
    me = bpy.data.meshes.new("TRIM_High")
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    hi = bpy.data.objects.new("TRIM_High", me)
    sc.collection.objects.link(hi)
    for ob in list(sc.objects):
        if ob.name.startswith("HP_"):
            bpy.data.objects.remove(ob)
    return hi
