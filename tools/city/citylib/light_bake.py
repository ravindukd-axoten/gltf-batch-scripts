"""Baked occlusion for the cells (Blender side; research "Lighting and Look" work list 2 and 3).

Runs after every cell is built and before export, with the whole city in the scene, so every bake sees the
neighbouring cells and the result crosses cell edges with no seam.

1. Vertex AO. Every building piece (kit instances under `bld_*`, roofs, landmark masses) gets its own mesh copy
   (instances shared one kit mesh, so they could not hold per-instance AO) and Cycles AO is baked per face corner
   into COLOR_0.A (`Col` alpha; rgb, the street kit's paint, is kept; an existing per-piece AO is kept where darker).
   The plaster and facade-trim corners of each `bld_*` also take that building's paint tint into rgb
   (`paint_variation`, MAT2).
   Ground, road and pavement meshes get it too, but only on their non-horizontal faces (kerb faces, steps,
   edging): their big flat polygons are triangulated with few vertices, so their AO comes from the light map (2).
   All targets are baked in one Cycles call from one combined world-space copy (one scene sync, not one per object).
2. Ground light map (citylib/lightmap.py): a 256 x 256 RGBA texture per cell, baked from a ground-hugging grid
   (1 m quads) laid out as tiles of one atlas: R = AO, G / B / A = sun visibility for the three lighting keys.
"""
from __future__ import annotations

import math
import os
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import lightmap as LM
from . import paint_variation

VERTEX_AO_DISTANCE_M = 6.0     # street canyon scale: wall bases, recesses, under awnings and balconies
VERTEX_AO_SAMPLES = 64
MAP_AO_DISTANCE_M = 10.0       # ground sky visibility: a 15 m street between 4-storey fronts reads darker
MAP_AO_SAMPLES = 48
SHADOW_SAMPLES = 12
SUN_ANGLE_DEG = 1.2            # a little softer than the real sun (0.53): the map is 0.5 m a texel
GRID = 128                     # quads per side of a cell's bake grid (about 1 m)
GRID_LIFT_M = 0.10             # the grid floats this far above the highest ground within a metre
GROUND_PARTS = ("_Road", "_Pavement", "_Ground")
HEIGHT_PARTS = GROUND_PARTS + ("_Water",)
FLAT_NZ = 0.7                  # ground faces flatter than this take AO from the light map, not COLOR_0


def _log(msg: str) -> None:
    print(f"[bake] {msg}", flush=True)


def _setup_cycles(samples: int, distance: float) -> str:
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    device = "CPU"
    # PI_BAKE_DEVICE=CPU: Metal can crash on the full fort_loop bake (55k meshes, NSInvalidArgumentException in
    # MetalDeviceQueue::synchronize, 2026-11-17); the CPU bake gives the same result, only slower.
    force_cpu = os.environ.get("PI_BAKE_DEVICE", "").upper() == "CPU"
    try:
        if force_cpu:
            raise RuntimeError("PI_BAKE_DEVICE=CPU")
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == "METAL"]
        for d in prefs.devices:
            d.use = d.type == "METAL"
        if gpus:
            device = "GPU"
    except Exception:  # noqa: BLE001 - no GPU backend: CPU bake, same result
        pass
    sc.cycles.device = device
    sc.cycles.samples = samples
    if sc.world is None:
        sc.world = bpy.data.worlds.new("PI_BakeWorld")
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        bg.inputs["Strength"].default_value = 1.0
    sc.world.light_settings.distance = distance
    sc.render.bake.margin = 0
    sc.render.bake.use_clear = True
    return device


def _descendants(ob):
    stack = list(ob.children)
    while stack:
        o = stack.pop()
        yield o
        stack.extend(o.children)


def _building_name(ob, stop) -> str | None:
    p = ob.parent
    while p is not None and p is not stop:
        if p.name.startswith("bld_"):
            return p.name.split(".")[0]
        p = p.parent
    return None


def _under_building(ob, stop) -> bool:
    return _building_name(ob, stop) is not None


_BUILDING_OF: dict[int, str] = {}  # id(mesh object) -> bld_<osm id>, filled by collect_targets for the paint tint


def collect_targets(cell_ids: list[str]) -> tuple[list, list]:
    """(building objects, ground objects) of the built cells; building kit instances get their own mesh copy."""
    t0 = time.perf_counter()
    buildings, ground = [], []
    copied = 0
    for cid in cell_ids:
        lod0 = bpy.data.objects.get(f"{cid}_LOD0")
        if lod0 is None:
            continue
        for ob in _descendants(lod0):
            if ob.type != "MESH" or not ob.data.polygons:
                continue
            if any(ob.name == cid + part for part in GROUND_PARTS):
                ground.append(ob)
            elif _under_building(ob, lod0):
                if ob.data.users > 1:
                    ob.data = ob.data.copy()
                    copied += 1
                buildings.append(ob)
                _BUILDING_OF[id(ob)] = _building_name(ob, lod0)
    _log(f"targets: {len(buildings)} building meshes ({copied} instance copies), {len(ground)} ground meshes, "
         f"{time.perf_counter() - t0:.1f} s")
    return buildings, ground


def _gather(obs: list) -> tuple[bpy.types.Mesh, list]:
    """One world-space mesh holding every object's faces in order; spans = (object, first corner, corners)."""
    cos, vis, lss, spans = [], [], [], []
    nv = nl = 0
    for ob in obs:
        me = ob.data
        v, l, p = len(me.vertices), len(me.loops), len(me.polygons)
        co = np.empty(v * 3, np.float32)
        me.vertices.foreach_get("co", co)
        m = np.array(ob.matrix_world, dtype=np.float64)
        co = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        vi = np.empty(l, np.int32)
        me.loops.foreach_get("vertex_index", vi)
        ls = np.empty(p, np.int32)
        me.polygons.foreach_get("loop_start", ls)
        if np.linalg.det(m[:3, :3]) < 0:
            # mirrored instance: reverse each face's corners so the baked normal faces out; corner i of a
            # face of size n at start s maps to s + (n - i) % n, the same corner either way round
            lt = np.empty(p, np.int32)
            me.polygons.foreach_get("loop_total", lt)
            for s, n in zip(ls, lt):
                vi[s:s + n] = np.concatenate((vi[s:s + 1], vi[s + 1:s + n][::-1]))
        cos.append(co.astype(np.float32))
        vis.append(vi + nv)
        lss.append(ls + nl)
        spans.append((ob, nl, l))
        nv += v
        nl += l
    me = bpy.data.meshes.new("_PI_AOBake")
    me.vertices.add(nv)
    me.vertices.foreach_set("co", np.concatenate(cos).ravel())
    me.loops.add(nl)
    me.loops.foreach_set("vertex_index", np.concatenate(vis))
    lsa = np.concatenate(lss)
    me.polygons.add(len(lsa))
    me.polygons.foreach_set("loop_start", lsa)
    me.update(calc_edges=True)
    me.shade_flat()
    return me, spans


def _mirror_corner_order(ob, start: int, n_loops: int) -> np.ndarray | None:
    """Corner permutation for a mirrored object (see _gather), else None."""
    m = np.array(ob.matrix_world, dtype=np.float64)
    if np.linalg.det(m[:3, :3]) >= 0:
        return None
    me = ob.data
    p = len(me.polygons)
    ls = np.empty(p, np.int32)
    lt = np.empty(p, np.int32)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    perm = np.arange(n_loops)
    for s, n in zip(ls, lt):
        perm[s + 1:s + n] = perm[s + 1:s + n][::-1]
    return perm


def _apply_tint(me, rgba: np.ndarray, tint) -> None:
    """MAT2 per-building paint: multiply COLOR_0.rgb of the plaster / facade-trim corners by the building's tint,
    and (MAT3) the street kit's wall-paint corners by the tint over NEUTRAL at half strength
    (paint_variation.street_kit_factor_from_tint)."""
    names = [m.name.split(".")[0] if m is not None else "" for m in me.materials]
    slots = [n in paint_variation.TINT_MATERIALS for n in names]
    kit = [n == paint_variation.STREET_KIT_MATERIAL for n in names]
    if not any(slots) and not any(kit):
        return
    p = len(me.polygons)
    mi = np.empty(p, np.int32)
    me.polygons.foreach_get("material_index", mi)
    lt = np.empty(p, np.int32)
    me.polygons.foreach_get("loop_total", lt)
    idx = np.repeat(np.clip(mi, 0, len(names) - 1), lt)
    on = np.array(slots, bool)[idx]
    rgba[on, :3] *= np.asarray(tint, np.float32)
    if any(kit):
        # MAT3: the street kit's wall-paint corners (paint_variation.street_kit_walls_linear) take the same
        # building tint relative to NEUTRAL; trim, shutters, glass and awnings keep their own paint
        walls = np.asarray(paint_variation.street_kit_walls_linear(), np.float32)
        d = np.abs(rgba[:, None, :3] - walls[None, :, :]).max(axis=2).min(axis=1)
        wall = np.array(kit, bool)[idx] & (d < paint_variation.WALL_MATCH_TOL)
        rgba[wall, :3] *= np.asarray(paint_variation.street_kit_factor_from_tint(tint), np.float32)


def _write_alpha(ob, ao: np.ndarray, flat_one: bool, tint=None) -> None:
    me = ob.data
    n = len(me.loops)
    rgba = np.ones((n, 4), np.float32)
    old = me.color_attributes.get("Col")
    if old is not None:
        buf = np.empty(len(old.data) * 4, np.float32)
        old.data.foreach_get("color", buf)
        buf = buf.reshape(-1, 4)
        if old.domain == "POINT":
            vi = np.empty(n, np.int32)
            me.loops.foreach_get("vertex_index", vi)
            buf = buf[vi]
        rgba = buf
        me.color_attributes.remove(old)
    if flat_one:
        p = len(me.polygons)
        nz = np.empty(p * 3, np.float32)
        me.polygons.foreach_get("normal", nz)
        lt = np.empty(p, np.int32)
        me.polygons.foreach_get("loop_total", lt)
        flat = np.repeat(np.abs(nz.reshape(-1, 3)[:, 2]) > FLAT_NZ, lt)
        ao = np.where(flat, 1.0, ao)
    rgba[:, 3] = np.minimum(rgba[:, 3], ao) if old is not None else ao
    if tint is not None:
        _apply_tint(me, rgba, tint)
    ca = me.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
    ca.data.foreach_set("color", rgba.ravel())
    me.color_attributes.active_color = ca
    me.color_attributes.render_color_index = me.color_attributes.active_color_index


def _bake_selected(ob, bake_type: str, target: str) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.context.scene.render.bake.target = target
    bpy.ops.object.bake(type=bake_type, target=target)


def _lod1_objects(cell_ids):
    return [o for cid in cell_ids for o in [bpy.data.objects.get(f"{cid}_LOD1")] if o is not None]


def bake_vertex_ao(buildings: list, ground: list, hide_extra: list) -> dict:
    t0 = time.perf_counter()
    targets = buildings + ground
    bpy.context.view_layer.update()
    me, spans = _gather(targets)
    ob = bpy.data.objects.new("_PI_AOBake", me)
    bpy.context.scene.collection.objects.link(ob)
    attr = me.color_attributes.new("AO", "FLOAT_COLOR", "CORNER")
    me.color_attributes.active_color = attr
    hidden = [o for o in targets + hide_extra if not o.hide_render]
    for o in hidden:
        o.hide_render = True
    t1 = time.perf_counter()
    device = _setup_cycles(VERTEX_AO_SAMPLES, VERTEX_AO_DISTANCE_M)
    try:
        _bake_selected(ob, "AO", "VERTEX_COLORS")
    finally:
        for o in hidden:
            o.hide_render = False
    t2 = time.perf_counter()
    buf = np.empty(len(me.loops) * 4, np.float32)
    me.color_attributes["AO"].data.foreach_get("color", buf)
    ao_all = buf.reshape(-1, 4)[:, 0].copy()
    ground_set = set(id(o) for o in ground)
    for target, start, n in spans:
        ao = ao_all[start:start + n]
        perm = _mirror_corner_order(target, start, n)
        if perm is not None:
            ao = ao[perm]
        bld = _BUILDING_OF.get(id(target))
        _write_alpha(target, ao, flat_one=id(target) in ground_set,
                     tint=paint_variation.building_tint_linear(bld) if bld else None)
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    t3 = time.perf_counter()
    vis = ao_all[ao_all > 0.02]
    stats = {"corners": int(len(ao_all)), "device": device, "share_black": round(float((ao_all <= 0.02).mean()), 3),
             "visible_p5_p50": [round(float(np.percentile(vis, q)), 3) for q in (5, 50)] if len(vis) else [], "mean_ao": round(float(ao_all.mean()), 3),
             "p5_ao": round(float(np.percentile(ao_all, 5)), 3),
             "seconds": {"gather": round(t1 - t0, 1), "bake": round(t2 - t1, 1), "write": round(t3 - t2, 1)}}
    _log(f"vertex AO: {stats}")
    return stats


def _ground_bvh(cell_ids: list[str]) -> BVHTree:
    verts, polys = [], []
    for cid in cell_ids:
        for part in HEIGHT_PARTS:
            ob = bpy.data.objects.get(cid + part)
            if ob is None:
                continue
            me = ob.data
            co = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", co)
            m = np.array(ob.matrix_world, dtype=np.float64)
            co = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
            base = len(verts)
            verts.extend(map(tuple, co.tolist()))
            polys.extend([base + v for v in p.vertices] for p in me.polygons)
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


def _heights(bvh: BVHTree, xs: np.ndarray, ys: np.ndarray, fallback: float) -> tuple[np.ndarray, np.ndarray]:
    """Ground height under each (x, y) grid point (ray from above) and whether ground was found there."""
    z = np.full(xs.shape, np.nan, np.float64)
    down = Vector((0.0, 0.0, -1.0))
    for idx in np.ndindex(xs.shape):
        hit = bvh.ray_cast(Vector((float(xs[idx]), float(ys[idx]), 400.0)), down, 1000.0)
        if hit[0] is not None:
            z[idx] = hit[0].z
    found = ~np.isnan(z)
    if found.any():
        zz = np.where(found, z, -1e9)
        # fill holes (building footprints) from neighbours, then lift over kerbs: max over 3 x 3
        for _ in range(GRID):
            if (zz > -1e8).all():
                break
            nb = np.max(np.stack([np.roll(zz, s, axis=a) for a in (0, 1) for s in (1, -1)]), axis=0)
            zz = np.where(zz > -1e8, zz, nb)
        zz = np.where(zz > -1e8, zz, fallback)
        pad = np.pad(zz, 1, mode="edge")
        lifted = np.max(np.stack([pad[1 + dy:1 + dy + zz.shape[0], 1 + dx:1 + dx + zz.shape[1]]
                                  for dy in (-1, 0, 1) for dx in (-1, 0, 1)]), axis=0)
        return lifted + GRID_LIFT_M, found
    return np.full(xs.shape, fallback + GRID_LIFT_M), found


def _bake_grid(cell_ids: list[str], origins: dict, fallback_z: float):
    """One mesh with a GRID x GRID quad grid per cell, UVs laid out as atlas tiles."""
    side = LM.atlas_side(len(cell_ids))
    bvh = _ground_bvh(cell_ids)
    n = GRID + 1
    k = np.arange(n, dtype=np.float64)
    span = LM.CELL + LM.SPACING
    verts, uvs, faces, found_all = [], [], [], {}
    q = np.arange(GRID)
    a = (q[:, None] * n + q[None, :]).ravel()
    quad = np.stack([a, a + 1, a + n + 1, a + n], axis=1)          # (row j, col i): j north, i east
    for t, cid in enumerate(cell_ids):
        x0, y0 = origins[cid]
        xs1 = x0 - LM.SPACING / 2 + k * span / GRID
        ys1 = y0 - LM.SPACING / 2 + k * span / GRID
        ys, xs = np.meshgrid(ys1, xs1, indexing="ij")
        z, found = _heights(bvh, xs, ys, fallback_z)
        found_all[cid] = found
        tx, ty = t % side, t // side
        u = (tx + xs * 0 + k[None, :] / GRID) / side
        v = (ty + k[:, None] / GRID + ys * 0) / side
        base = sum(len(vv) for vv in verts)
        verts.append(np.stack([xs, ys, z], axis=-1).reshape(-1, 3))
        uvs.append(np.stack([u, v], axis=-1).reshape(-1, 2))
        faces.append(quad + base)
    co = np.concatenate(verts).astype(np.float32)
    fa = np.concatenate(faces).astype(np.int32)
    uv = np.concatenate(uvs).astype(np.float32)
    me = bpy.data.meshes.new("_PI_GroundBake")
    me.vertices.add(len(co))
    me.vertices.foreach_set("co", co.ravel())
    me.loops.add(fa.size)
    me.loops.foreach_set("vertex_index", fa.ravel())
    me.polygons.add(len(fa))
    me.polygons.foreach_set("loop_start", np.arange(0, fa.size, 4, dtype=np.int32))
    me.update(calc_edges=True)
    layer = me.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", uv[fa.ravel()].ravel())
    me.shade_flat()
    return me, side, found_all


def bake_ground_maps(cell_ids: list[str], origins: dict, out_dir: str, fallback_z: float, repo: str,
                     hide_extra: list, prune: bool) -> dict:
    t0 = time.perf_counter()
    me, side, found = _bake_grid(cell_ids, origins, fallback_z)
    ob = bpy.data.objects.new("_PI_GroundBake", me)
    bpy.context.scene.collection.objects.link(ob)
    for flag in ("visible_camera", "visible_diffuse", "visible_glossy", "visible_transmission",
                 "visible_volume_scatter", "visible_shadow"):
        if hasattr(ob, flag):
            setattr(ob, flag, flag == "visible_camera")
    res = side * LM.MAP_RES
    img = bpy.data.images.new("_PI_GroundBake", res, res, alpha=True, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    mat = bpy.data.materials.new("_PI_GroundBake")
    mat.use_nodes = True
    nt = mat.node_tree
    for nd in list(nt.nodes):
        if nd.type == "BSDF_PRINCIPLED":
            nt.nodes.remove(nd)
    lambert = nt.nodes.new("ShaderNodeBsdfDiffuse")
    nt.links.new(lambert.outputs["BSDF"], nt.nodes["Material Output"].inputs["Surface"])
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = img
    mat.node_tree.nodes.active = node
    me.materials.append(mat)
    hidden = [o for o in hide_extra if not o.hide_render]
    for o in hidden:
        o.hide_render = True
    t1 = time.perf_counter()
    atlas = np.zeros((res, res, 4), np.float32)
    buf = np.empty(res * res * 4, np.float32)
    keys = LM.read_sun_keys(repo)
    sun = None
    try:
        device = _setup_cycles(MAP_AO_SAMPLES, MAP_AO_DISTANCE_M)
        _bake_selected(ob, "AO", "IMAGE_TEXTURES")
        img.pixels.foreach_get(buf)
        atlas[..., 0] = buf.reshape(res, res, 4)[..., 0]
        light = bpy.data.lights.new("_PI_BakeSun", "SUN")
        light.angle = math.radians(SUN_ANGLE_DEG)
        light.energy = 1.0
        sun = bpy.data.objects.new("_PI_BakeSun", light)
        bpy.context.scene.collection.objects.link(sun)
        bpy.context.scene.cycles.samples = SHADOW_SAMPLES
        # sun only: with the sky lit the shadow pass also counts sky occlusion (all three keys then read ~0.6)
        bg = bpy.context.scene.world.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs["Strength"].default_value = 0.0
        for ch, (name, el, az) in enumerate(keys, start=1):
            to_sun = Vector(LM.sun_vector(max(el, 1.0), az))
            sun.rotation_euler = to_sun.to_track_quat("Z", "Y").to_euler()
            # direct diffuse light on the (up-facing) grid with a sun of pi / sin(elevation): 1 = fully lit.
            # (Cycles' SHADOW bake is a ratio that blows up at grazing angles, so it is not used.)
            light.energy = math.pi / max(to_sun.z, 0.02)   # Cycles' diffuse pass carries 1/pi
            bk = bpy.context.scene.render.bake
            bk.use_pass_direct, bk.use_pass_indirect, bk.use_pass_color = True, False, False
            _bake_selected(ob, "DIFFUSE", "IMAGE_TEXTURES")
            img.pixels.foreach_get(buf)
            atlas[..., ch] = np.clip(buf.reshape(res, res, 4)[..., 0], 0.0, 1.0)
    finally:
        for o in hidden:
            o.hide_render = False
        if sun is not None:
            bpy.data.objects.remove(sun)
    t2 = time.perf_counter()
    os.makedirs(out_dir, exist_ok=True)
    tiles, written = {}, []
    filled = 0
    for t, cid in enumerate(cell_ids):
        tx, ty = t % side, t // side
        tile = atlas[ty * LM.MAP_RES:(ty + 1) * LM.MAP_RES, tx * LM.MAP_RES:(tx + 1) * LM.MAP_RES].copy()
        # texels with no ground under them (building footprints) or fully enclosed: fill from the ground around
        f = found[cid]
        hit = np.repeat(np.repeat(f[:-1, :-1] | f[1:, 1:], 2, axis=0), 2, axis=1)[:LM.MAP_RES, :LM.MAP_RES]
        valid = hit & (tile[..., 0] > 0.03)
        filled_tile, _ = LM.fill_masked(tile, valid, passes=6)
        inv = ~valid
        filled_tile[..., 0] = np.where(inv, filled_tile[..., 0] * 0.7, filled_tile[..., 0])
        filled += int(inv.sum())
        tiles[cid] = filled_tile
        path = os.path.join(out_dir, LM.file_name(cid))
        LM.png_rgba(path, LM.tile_rows(filled_tile), LM.MAP_RES, LM.MAP_RES)
        written.append(path)
    if prune:
        keep = {os.path.basename(p) for p in written}
        for fname in os.listdir(out_dir):
            if fname.startswith("TEX_GroundLight_") and fname.endswith(".png") and fname not in keep:
                os.remove(os.path.join(out_dir, fname))
                if os.path.exists(os.path.join(out_dir, fname + ".meta")):
                    os.remove(os.path.join(out_dir, fname + ".meta"))
    seam = seam_error(tiles)
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    bpy.data.images.remove(img)
    bpy.data.materials.remove(mat)
    t3 = time.perf_counter()
    all_px = np.stack(list(tiles.values()))
    stats = {"cells": len(written), "atlas_px": res, "device": device, "keys": keys,
             "mean": [round(float(all_px[..., c].mean()), 3) for c in range(4)],
             "filled_texels": filled, "seam_mean_abs": seam,
             "seconds": {"grid": round(t1 - t0, 1), "bake": round(t2 - t1, 1), "write": round(t3 - t2, 1)}}
    _log(f"ground maps: {stats}")
    return {"stats": stats, "files": written}


def seam_error(tiles: dict) -> dict:
    """Mean absolute 8-bit difference per channel between touching edge texels of neighbouring cells."""
    by_cell = {tuple(int(v) for v in cid.split("_")[1:3]): t for cid, t in tiles.items()}
    diffs, open_diffs = [], []
    for (e, n), t in by_cell.items():
        for other, a_edge, b_edge in ((by_cell.get((e + 1, n)), lambda x: x[:, -1], lambda x: x[:, 0]),
                                      (by_cell.get((e, n + 1)), lambda x: x[-1, :], lambda x: x[0, :])):
            if other is None:
                continue
            a, b = a_edge(t), b_edge(other)
            diffs.append(np.abs(a - b))
            # open ground on both sides (R > 0.78): edges that run under buildings or over the sea are never seen
            both = (a[:, 0] > 0.78) & (b[:, 0] > 0.78)
            open_diffs.append(np.abs(a - b)[both])
    if not diffs:
        return {}
    d = np.concatenate(diffs) * 255.0
    o = np.concatenate(open_diffs) * 255.0
    return {"pairs": len(diffs), "mean": [round(float(d[:, c].mean()), 2) for c in range(4)],
            "p99": [round(float(np.percentile(d[:, c], 99)), 1) for c in range(4)],
            "open_ground_texels": int(o.shape[0]),
            "open_ground_mean": [round(float(o[:, c].mean()), 2) for c in range(4)] if o.size else None,
            "open_ground_p99": [round(float(np.percentile(o[:, c], 99)), 1) for c in range(4)] if o.size else None}


def bake_city(cell_ids: list[str], origins: dict, maps_dir: str, fallback_z: float, repo: str, prune: bool) -> dict:
    t0 = time.perf_counter()
    lod1 = _lod1_objects(cell_ids)
    buildings, ground = collect_targets(cell_ids)
    vtx = bake_vertex_ao(buildings, ground, lod1)
    maps = bake_ground_maps(cell_ids, origins, maps_dir, fallback_z, repo, lod1, prune)
    return {"vertex_ao": vtx, "ground_maps": maps["stats"], "files": maps["files"],
            "seconds": round(time.perf_counter() - t0, 1)}
