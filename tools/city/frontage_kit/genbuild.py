"""Generated-row builder (P143): one generic Geometry Nodes pipeline for every catalogue of parametric pieces.

A catalogue (elements.py for FE_*, classes.py for CLS_*, towerbase.py for TWB_*) lists entries; each entry names a
body function `fn(t, p)` written with gnlib/parts (GN primitives, booleans, arrays, group instances; never vertex by
vertex). This module turns every entry into game meshes the same way the P96 kit does (kitbuild.py: evaluate ->
cleanup -> bevel + weighted normals -> trim UVs -> COLOR_0 paint x AO), then adds the wear layer from
docs/research/wear-and-decay-system.md: COLOR_0 rgb also carries the citylib/decay.py grime multiply (foot splash,
edges, occlusion; `vertex_rgba` formula), and a second colour set `Wear` (COLOR_1: R dirt, G edge wear, B rust on
metal / damp on walls, A age seed from decay.stable_hash). Decay level stays the P96 material swap
(MAT_FrontageTrim_A worn, MAT_FrontageTrim_A_Light near the Delta Face Hotel); COLOR_1 is authored at worn strength.

Entry keys: name, body, h (storey or piece height for the wall row), variant (paint family A-D), refs (list),
row (inventory row name it builds), lod2 (optional body for a third LOD), mat2 (optional second material name for
faces tagged `mat2`), stripes (canvas colours), kind (validator kind), worn_only (bool).
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys

import bmesh
import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import kitbuild  # noqa: E402
import parts  # noqa: E402
import slivers  # noqa: E402
from gnlib import group  # noqa: E402

_spec = importlib.util.spec_from_file_location("decay", os.path.join(HERE, "..", "citylib", "decay.py"))
decay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decay)

PROV = os.path.join(REPO, "docs", "provenance", "provenance.csv")
WORLD = "unity/BatchIsland/Assets/BatchIsland/Art/World"


def merge_slivers(bm, name, passes=3):
    """Merge the short edge of every zero-area triangle (bevel beside a boolean cut; see slivers.py)."""
    for _ in range(passes):
        bm.verts.ensure_lookup_table()
        tris = [(tuple(l.vert.index for l in t), tuple(tuple(l.vert.co) for l in t)) for t in bm.calc_loop_triangles()]
        pairs, bad = slivers.sliver_merges(tris)
        if not pairs:
            break
        verts = [(bm.verts[a], bm.verts[b]) for a, b in pairs]
        for va, vb in verts:
            bmesh.ops.pointmerge(bm, verts=[va, vb], merge_co=(va.co + vb.co) / 2)
        bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-5)
        print("SLIVERS_MERGED", name, len(pairs))
    if bad:
        print("SLIVERS_LEFT", name, bad)


def mat2_material(name):
    """Second slot for faces that take their own 0-1 texture (sign faces, painted names): neutral base, vertex paint."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    col = nt.nodes.new("ShaderNodeVertexColor")
    col.layer_name = "Col"
    nt.links.new(col.outputs["Color"], bsdf.inputs["Base Color"])
    if "Glow" in name:   # emissive sign face: the colour is the vertex paint, strength set in Unity
        nt.links.new(col.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 2.0
    return m


def _face_int(me, name):
    return kitbuild.face_attr(me, name)


def apply_mat2(ob, mat2):
    """Faces tagged mat2 -> slot 1 with planar 0-1 UVs over their bounding box (one texture per face set)."""
    me = ob.data
    flag = _face_int(me, "mat2") > 0
    if not flag.any() or not mat2:
        return
    me.materials.append(bpy.data.materials[mat2])
    idx = np.zeros(len(me.polygons), np.int32)
    idx[flag] = 1
    me.polygons.foreach_set("material_index", idx)
    uv = me.uv_layers["UVMap"]
    co = np.array([v.co[:] for v in me.vertices])
    loops = [li for p in me.polygons if flag[p.index] for li in p.loop_indices]
    vi = np.array([me.loops[li].vertex_index for li in loops])
    pts = co[vi]
    lo, hi = pts.min(0), pts.max(0)
    ext = np.maximum(hi - lo, 1e-6)
    for li, pt in zip(loops, pts):
        uv.data[li].uv = ((pt[0] - lo[0]) / ext[0], (pt[2] - lo[2]) / ext[2])


def _edge_verts(me):
    """Convexity per vertex (1 on sharp convex edges): exposed edges lose paint and catch dust."""
    bm = bmesh.new()
    bm.from_mesh(me)
    edge = np.zeros(len(bm.verts))
    for e in bm.edges:
        if len(e.link_faces) == 2 and e.calc_face_angle_signed(0.0) > 0.5:
            for v in e.verts:
                edge[v.index] = 1.0
    bm.free()
    return edge


def write_wear(ob, name, worn=True):
    """COLOR_0 rgb x decay grime (vertex_rgba), COLOR_1 `Wear` (R dirt, G edge, B rust/damp, A seed)."""
    me = ob.data
    n_l = len(me.loops)
    vidx = np.zeros(n_l, np.int64)
    me.loops.foreach_get("vertex_index", vidx)
    co = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    z = co[:, 2]
    h01 = np.clip((z - z.min()) / max(z.max() - z.min(), 0.05), 0, 1)[vidx]
    edge = _edge_verts(me)[vidx]
    total = np.zeros(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_total", total)
    role = np.repeat(_face_int(me, "role"), total)
    trim = np.repeat(_face_int(me, "trim"), total)
    nrm = np.zeros(len(me.polygons) * 3)
    me.polygons.foreach_get("normal", nrm)
    down = np.repeat(nrm.reshape(-1, 3)[:, 2] < -0.7, total)
    col = me.color_attributes["Col"]
    rgba = np.zeros(n_l * 4)
    col.data.foreach_get("color_srgb", rgba)
    rgba = rgba.reshape(-1, 4)
    ao = rgba[:, 3]
    wear = 1 if worn else 0
    # citylib/decay.vertex_rgba, vectorised (same constants)
    g = decay.WEAR_GRIME[wear] * (0.55 * (1.0 - h01) ** 2 + 0.25 * edge + 0.2 * (1.0 - ao))
    g = np.clip(g, 0, 1)
    glass = trim == parts.TR["GLASS"]
    for c in range(3):
        mul = 1.0 - (1.0 - decay.GRIME[c]) * g
        rgba[:, c] = np.where(glass, rgba[:, c], rgba[:, c] * mul)
    col.data.foreach_set("color_srgb", rgba.ravel())
    dirt = np.clip(0.6 * (1.0 - h01) ** 3 + np.where(down, 0.35, 0.0) + 0.3 * (1.0 - ao), 0, 1)
    metal = role == parts.ROLE["METAL"]
    wall = role == parts.ROLE["WALL"]
    rust = np.where(metal, 0.25 + 0.55 * (1.0 - h01), 0.0)
    damp = np.where(wall, 0.6 * (1.0 - h01) ** 2, 0.0)
    seed = (decay.stable_hash("building:" + name) % 1000) / 999.0
    w = me.color_attributes.get("Wear") or me.color_attributes.new("Wear", "BYTE_COLOR", "CORNER")
    out = np.stack([dirt, np.clip(edge * 0.7, 0, 1), np.maximum(rust, damp), np.full(n_l, seed)], 1)
    w.data.foreach_set("color", out.ravel())
    me.color_attributes.active_color = col
    me.color_attributes.render_color_index = me.color_attributes.find("Col")


def collision_bbox(name, ob, at, coll):
    co = np.array([v.co[:] for v in ob.data.vertices])
    lo, hi = co.min(0), co.max(0)
    me = bpy.data.meshes.new(f"{name}_COL")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        for i in range(3):
            v.co[i] = lo[i] + (v.co[i] + 0.5) * max(hi[i] - lo[i], 0.02)
    bm.to_mesh(me)
    bm.free()
    c = bpy.data.objects.new(f"{name}_COL", me)
    c.location = at
    c.hide_render = True
    coll.objects.link(c)


def build(entries, kit_name, bake=True, need_asm=False):
    kitbuild.ROTATE_TALL = True
    kitbuild.setup_scene()
    parts.build_groups()
    if need_asm:
        import pieces
        pieces.build_assemblies()
    src = kitbuild.collection("_src", hide=True)
    kit = kitbuild.collection(kit_name)
    mat = kitbuild.material()
    kitbuild.material(kitbuild.MAT_LIGHT, kitbuild.TEX_LIGHT)
    for e in entries:
        if e.get("mat2"):
            mat2_material(e["mat2"])
    tris = {}
    for i, e in enumerate(entries):
        name = e["name"]
        at = ((i % 8) * 6.0, (i // 8) * 8.0, 0.0)
        if e.get("paint"):
            kitbuild.PAINT_OVERRIDE[name] = e["paint"]
        if e.get("stripes"):
            kitbuild.STRIPES[name] = e["stripes"]
            kitbuild.STRIPES[name + "_LOD1"] = e["stripes"]
            kitbuild.STRIPES[name + "_LOD2"] = e["stripes"]
        ng = group(f"ASM_{name}", [("LOD", bool, False)], e["body"])
        lods = [(0, ng, 0), (1, ng, 1)]
        if e.get("lod2"):
            lods.append((2, group(f"ASM_{name}_LOD2", [("LOD", bool, False)], e["lod2"]), 1))
        for lod, g, flag in lods:
            gen = kitbuild.generator(f"{name}_{lod}", g, flag, src)
            gen.location = at
            oname = name if lod == 0 else f"{name}_LOD{lod}"
            me = kitbuild.evaluate(gen, oname)
            kitbuild.cleanup(me)
            ob = bpy.data.objects.new(oname, me)
            ob.location = at
            kit.objects.link(ob)
            bpy.context.view_layer.update()
            kitbuild.apply_mods(ob, bevel=(lod == 0))
            bm = bmesh.new(); bm.from_mesh(ob.data)   # boolean slivers (gable cuts) leave zero-area faces
            bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-5)
            merge_slivers(bm, oname)
            bm.to_mesh(ob.data); bm.free()
            ob.data.materials.clear()
            ob.data.materials.append(mat)
            kitbuild.uv_and_paint(ob.data, e.get("h", 3.2), e.get("variant", "A"), oname)
            apply_mat2(ob, e.get("mat2"))
            if bake:
                kitbuild.bake_ao(ob)
            write_wear(ob, name)
            ob["refs"] = ",".join(e.get("refs", []))
            ob["row"] = e.get("row", "")
            ob["storey_h"] = round(e.get("h", 3.2), 3)
            ob["decay_levels"] = "worn" if e.get("worn_only") else "light,worn"
            ob["decay_default"] = "worn"
            if lod:
                ob.hide_render = True
            tris.setdefault(name, {})[f"lod{lod}"] = sum(len(p.vertices) - 2 for p in ob.data.polygons)
            if lod == 0:
                collision_bbox(name, ob, at, kit)
    for o in src.objects:
        o.hide_set(True)
    return tris


def export(kit_name, out_dir):
    """One glb per piece (LODs + COL) at the origin; both colour sets; no embedded images (Unity maps materials)."""
    os.makedirs(out_dir, exist_ok=True)
    kit = bpy.data.collections[kit_name]
    names = sorted(o.name for o in kit.objects if o.type == "MESH" and "_LOD" not in o.name and not o.name.endswith("_COL"))
    for nm in names:
        grp = [o for o in kit.objects if o.name == nm or o.name.startswith(nm + "_LOD") or o.name == nm + "_COL"]
        keep = [(o.location.copy(), o.hide_render) for o in grp]
        bpy.ops.object.select_all(action="DESELECT")
        for o in grp:
            o.location = (0, 0, 0)
            o.hide_set(False)
            o.select_set(True)
        kw = dict(filepath=os.path.join(out_dir, nm + ".glb"), use_selection=True, export_format="GLB",
                  export_apply=True, export_yup=True, export_image_format="NONE")
        try:
            bpy.ops.export_scene.gltf(**kw, export_vertex_color="ACTIVE", export_all_vertex_colors=True)
        except TypeError:
            bpy.ops.export_scene.gltf(**kw, export_vertex_color="ACTIVE")
        for o, (loc, h) in zip(grp, keep):
            o.location, o.hide_render = loc, h
    return names


def add_provenance(paths, generator, note):
    """Additive: one row per new asset path (re-reads the log right before appending)."""
    with open(PROV, newline="", encoding="utf-8") as f:
        have = {r["asset_path"] for r in csv.DictReader(f)}
    new = [p for p in paths if p not in have]
    if not new:
        return 0
    with open(PROV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        for p in new:
            kind = "model/building" if "/Buildings/" in p else ("source/blend" if p.endswith(".blend") else "model/kit-piece")
            w.writerow([p, kind, "script", f"{generator} (Blender 5.3.0, Geometry Nodes)", generator,
                        "LicenseRef-Axoten-Proprietary", "IP assignment in Axoten contracts (Safety doc > Contracts)",
                        "2026-11-20", note])
    return len(new)


def write_rowmap(path, generator, args, kind, out_rel, entries, tris):
    rows = {}
    for e in entries:
        rows.setdefault(e["row"], []).append(e["name"])
    data = {"_comment": "Spec-to-piece name map (P143): inventory row name -> generated pieces. Read by "
                        "tools/inventory/build_row_manifest.py; rewritten by the generator, do not edit.",
            "generator": generator, "args": args, "validator": f"blender_qa:{kind}:low", "outputs_dir": out_rel,
            "rows": rows, "tris": tris}
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
