"""Blender side of the B1 ground kit (data in citylib/ground_kit.py; P292).

Reuses the street kit's Geometry Nodes path (citylib/gn/street.py): every piece is one node group
`PI_GN_Ground_<piece>` built from street-kit parts plus three ground part types (fill: Fill Curve + Extrude Mesh;
quad: a 2 x 2 Mesh Grid decal; shelf: a Mesh Grid displaced by Noise with paint from height) and the piece-level
`drop` fields (Set Position on the tops, linear ramps). After the generator is applied: shell winding, the street
kit's UVs, then ground UVs (StreetTrim_A rows, the RoadPaint_B / RoadPaint_A cells and the manhole cell), COLOR_0
= paint + Cycles AO (street._paint_ao). LOD1 is the same data with fewer segments (ground_kit.pieces(lod=1)).
Export: one glb per piece holding <name>_LOD0 and <name>_LOD1 (B2 convention), base-centre pivot.
"""
from __future__ import annotations

import json
import math
import os

import bmesh
import bpy

from . import blender_scene as BS
from . import ground_kit as GK
from . import ground_paint as GP
from . import paint_atlas as PA
from . import street_kit as SK
from .gn import facade
from .gn import street as ST
from .gn.nodes import Tree

SK.ROLES.update(GK.ROLES)
KIND = {"row": 1, "cell": 2, "cella": 3, "manhole": 4}
ROW_NAMES = list(GK.TRIM_ROWS)
B_CELLS = list(GP.CELLS)
A_CELLS = list(PA.CELLS)


def ensure_materials():
    mats = BS.ensure_materials()
    if "MAT_RoadPaint_B" not in mats:
        m = mats["MAT_RoadPaint_A"].copy()
        m.name = "MAT_RoadPaint_B"
        mats["MAT_RoadPaint_B"] = m
    return mats


def _encode(part):
    """Ground uv tuples -> the street kit's ('sign', col, row) face code (scell = kind * 16 + index)."""
    part = dict(part)
    uv = part.get("uv")
    if isinstance(uv, (tuple, list)) and uv and uv[0] in KIND:
        kind = KIND[uv[0]]
        idx = {1: lambda: ROW_NAMES.index(uv[1]), 2: lambda: B_CELLS.index(uv[1]),
               3: lambda: A_CELLS.index(uv[1]), 4: lambda: 0}[kind]()
        part["uv"] = ("sign", kind, idx)
    if part.get("t") == "array":
        part["part"] = _encode(part["part"])
    return part


def _clamp01(t, v):
    return t.math("MINIMUM", t.math("MAXIMUM", v, 0.0), 1.0)


def _gpart(t: Tree, part, mats, piece):
    k = part["t"]
    if k == "quad":
        w, l = part["size"]
        geo = t.o(t.n("GeometryNodeMeshGrid", {"Size X": w, "Size Y": l, "Vertices X": 2, "Vertices Y": 2}))
        geo = t.transform(geo, translation=t.vec(*part["at"]), rotation=(0.0, 0.0, part.get("rot", 0.0)))
        return ST._tag(t, geo, part, mats)
    if k == "fill":
        crv = facade.polyline(t, part["path"], cyclic=True)
        geo = t.o(t.n("GeometryNodeFillCurve", {"Curve": crv, "Mode": "N-gons"}))
        geo = t.transform(geo, translation=t.vec(0.0, 0.0, part["z0"]))
        geo = t.o(t.n("GeometryNodeExtrudeMesh", {"Mesh": geo, "Offset": t.vec(0.0, 0.0, part["z1"] - part["z0"]),
                                                   "Offset Scale": 1.0}, mode="FACES"), "Mesh")
        return ST._tag(t, geo, part, mats)
    if k == "shelf":
        sx, sy = part["size"]
        nx, ny = part["verts"]
        geo = t.o(t.n("GeometryNodeMeshGrid", {"Size X": sx, "Size Y": sy, "Vertices X": nx, "Vertices Y": ny}))
        pos = t.position()
        x, y, _ = t.xyz(pos)
        noise = t.o(t.n("ShaderNodeTexNoise", {"Vector": t.vmath("SCALE", pos, scale=0.3), "Scale": 1.0,
                                                "Detail": 3.0, "Roughness": 0.55}), "Factor")
        # ragged outline: the edge falloff distance is pushed in by a second, coarser noise so the shelf is not a
        # rectangle; tops get a stepped (quantised) worn-platform look from the fine noise
        rag = t.o(t.n("ShaderNodeTexNoise", {"Vector": t.vmath("ADD", t.vmath("SCALE", pos, scale=0.11),
                                                                t.vec(7.3, 2.1, 0.0)),
                                              "Scale": 1.0, "Detail": 2.0}), "Factor")
        cut = t.mul(t.sub(rag, 0.4), 2.5)
        e = t.math("MINIMUM", _clamp01(t, t.div(t.sub(t.sub(sx / 2, t.math("ABSOLUTE", x)), cut), 1.2)),
                   _clamp01(t, t.div(t.sub(t.sub(sy / 2, t.math("ABSOLUTE", y)), t.mul(cut, 0.45)), 0.9)))
        step = t.div(t.math("FLOOR", t.mul(t.sub(noise, 0.2), 6.0)), 6.0)
        top = t.add(0.05, t.mul(part["h"], t.add(t.mul(step, 1.3), t.mul(t.sub(noise, 0.5), 0.6))))
        z = t.sub(t.mul(top, e), t.mul(part["rim"], t.sub(1.0, e)))
        geo = t.o(t.n("GeometryNodeSetPosition", {"Geometry": geo, "Position": t.vec(x, y, z)}))
        geo = ST._tag(t, geo, part, mats)
        # paint from height (face centre): algae green low, wet dark band, dry grey-brown rock on the high flats
        _, _, zf = t.xyz(t.position())
        f1 = _clamp01(t, t.div(t.sub(zf, -0.45), 0.3))
        f2 = _clamp01(t, t.div(t.sub(zf, 0.04), 0.16))
        c1 = t.o(t.n("ShaderNodeMix", {("Factor", "VALUE"): f1, ("A", "RGBA"): ST._hex(part["low"]),
                                       ("B", "RGBA"): ST._hex(part["wet"])}, data_type="RGBA"), "Result")
        c2 = t.o(t.n("ShaderNodeMix", {("Factor", "VALUE"): f2, ("A", "RGBA"): c1, ("B", "RGBA"): ST._hex(part["dry"])},
                     data_type="RGBA"), "Result")
        return t.store(geo, "paint", c2, "FLOAT_COLOR", "FACE")
    if k == "array":
        return ST._part(t, part, mats, piece)
    return ST._part(t, part, mats, piece)


def piece_group(piece: GK.GPiece, mats, lod: int):
    t = Tree(f"PI_GN_Ground_{piece.name}_L{lod}")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    geo = t.join(*[_gpart(t, _encode(p), mats, piece) for p in piece.parts])
    geo = t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": geo}))
    if piece.drops:
        x, y, z = t.xyz(t.position())
        total = None
        for dr in piece.drops:
            s, dd = (x, y) if dr["axis"] == "x" else (y, x)
            cs, cd = (dr["c"][0], dr["c"][1]) if dr["axis"] == "x" else (dr["c"][1], dr["c"][0])
            a = _clamp01(t, t.div(t.sub(dr["half"] + dr["flare"], t.math("ABSOLUTE", t.sub(s, cs))), dr["flare"]))
            b = _clamp01(t, t.sub(1.0, t.div(t.math("MAXIMUM", t.sub(dd, cd), 0.0), dr["depth"])))
            f = t.mul(t.mul(a, b), dr["amount"])
            total = f if total is None else t.add(total, f)
        sel = t.cmp(z, 0.1)
        geo = t.o(t.n("GeometryNodeSetPosition", {"Geometry": geo, "Selection": sel,
                                                   "Offset": t.vec(0.0, 0.0, t.mul(total, -1.0))}))
    geo = t.o(t.n("GeometryNodeMergeByDistance", {"Geometry": geo, "Distance": 0.0005}))
    t.result(geo)
    t.ng.use_fake_user = True
    return t.ng


def _ground_uvs(ob) -> None:
    """UV0 for the ground face codes; everything else keeps street._uvs."""
    me = ob.data
    roles = ST._attr_face(me, "uvrole") or [0] * len(me.polygons)
    cells = ST._attr_face(me, "scell") or [0] * len(me.polygons)
    uv0 = me.uv_layers["UVMap"]
    a0 = [0.0] * (2 * len(me.loops))
    uv0.data.foreach_get("uv", a0)
    groups: dict[int, list] = {}
    for p in me.polygons:
        if roles[p.index] == 3 and cells[p.index] // 16 in (2, 3, 4):
            groups.setdefault(cells[p.index], []).append(p)
    bbox = {}
    for code, faces in groups.items():
        xs = [me.vertices[v].co.x for f in faces for v in f.vertices]
        ys = [me.vertices[v].co.y for f in faces for v in f.vertices]
        bbox[code] = (min(xs), min(ys), max(max(xs) - min(xs), 1e-4), max(max(ys) - min(ys), 1e-4))
    for p in me.polygons:
        if roles[p.index] != 3:
            continue
        kind, idx = divmod(cells[p.index], 16)
        n = p.normal
        if kind == 1:
            v0, v1 = GK.TRIM_ROWS[ROW_NAMES[idx]]
            ext = [me.vertices[v].co for v in p.vertices]
            if abs(n.z) >= max(abs(n.x), abs(n.y)):
                # tops: u along the run (dominant horizontal axis), v across the face
                along_x = (max(c.x for c in ext) - min(c.x for c in ext)) >= (max(c.y for c in ext) - min(c.y for c in ext))
                ka, kb = ("x", "y") if along_x else ("y", "x")
            else:
                ka, kb = ("x" if abs(n.y) >= abs(n.x) else "y"), "z"
            bmin = min(getattr(c, kb) for c in ext)
            bspan = max(max(getattr(c, kb) for c in ext) - bmin, 1e-4)
            for li in p.loop_indices:
                co = me.vertices[me.loops[li].vertex_index].co
                a0[2 * li] = getattr(co, ka) / GK.TRIM_SHEET_M
                a0[2 * li + 1] = v0 + 0.02 * (v1 - v0) + 0.96 * (v1 - v0) * (getattr(co, kb) - bmin) / bspan
            continue
        x0, y0, w, h = bbox[cells[p.index]]
        if kind == 2:
            r = GP.uv_rect(B_CELLS[idx])
        elif kind == 3:
            r = PA.uv_rect(A_CELLS[idx])
        else:
            r = GK.MANHOLE_UV
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            fu = (co.x - x0) / w
            fv = (co.y - y0) / h
            if kind == 4 and abs(n.z) < 0.5:
                fu, fv = 0.02, 0.5                       # cover rim: the frame's edge
            a0[2 * li] = r[0] + (r[2] - r[0]) * fu
            a0[2 * li + 1] = r[1] + (r[3] - r[1]) * fv
    uv0.data.foreach_set("uv", a0)


def build_piece(piece: GK.GPiece, mats, lod: int, coll):
    name = f"{piece.name}_LOD{lod}"
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old)
    me = bpy.data.meshes.new(f"_{name}_src")
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    mod = ob.modifiers.new("Ground", "NODES")
    mod.node_group = piece_group(piece, mats, lod)
    bpy.context.view_layer.objects.active = ob
    facade.apply_gn(ob)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    ST._recalc_shells(bm)
    bm.to_mesh(ob.data)
    bm.free()
    if piece.bevel > 0:
        ST._bevel(ob, piece.bevel)
    ST._uvs(ob, piece)
    _ground_uvs(ob)
    ST._paint_ao(ob, piece)
    ST._to_kit_material(ob, mats)
    ob.data.name = name
    for k, (x, y, z) in piece.sockets.items() if lod == 0 else ():
        e = bpy.data.objects.new(f"SOCKET_{k}", None)
        e.empty_display_size = 0.2
        e.location = (x, y, z)
        e.parent = ob
        coll.objects.link(e)
    return ob


def wants_lod1(piece: GK.GPiece, lod0_tris: int) -> bool:
    return lod0_tris > 40 and piece.kind != "marking" or piece.name == "KIT_SpeedHump_Painted_A"


def export(objs, path) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
        for c in o.children:
            c.select_set(True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=True,
                              export_apply=True, export_vertex_color="ACTIVE", export_materials="EXPORT",
                              export_image_format="NONE", export_texcoords=True, export_normals=True,
                              export_extras=False)


def build(out_dir, only=None, tris_json=GK.GROUND_JSON):
    mats = ensure_materials()
    coll = bpy.data.collections.get("PI_Ground_Build") or bpy.data.collections.new("PI_Ground_Build")
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    p0, p1 = GK.pieces(0), GK.pieces(1)
    report = GK.measured_tris()
    built = {}
    for name, piece in p0.items():
        if only and name not in only:
            continue
        l0 = build_piece(piece, mats, 0, coll)
        t0 = ST.tris(l0)
        objs = [l0]
        t1 = None
        if wants_lod1(piece, t0):
            l1 = build_piece(p1[name], mats, 1, coll)
            t1 = ST.tris(l1)
            l1.location.x = 0.0
            objs.append(l1)
        export(objs, os.path.join(out_dir, f"{name}.glb"))
        lo = [min(v.co[i] for v in l0.data.vertices) for i in range(3)]
        hi = [max(v.co[i] for v in l0.data.vertices) for i in range(3)]
        report[name] = {"lod0": t0, "lod1": t1, "budget": piece.budget, "row": piece.row, "kind": piece.kind,
                        "size_m": [round(hi[i] - lo[i], 3) for i in range(3)],
                        "materials": sorted({l0.data.materials[p.material_index].name for p in l0.data.polygons}),
                        "sockets": {k: list(v) for k, v in piece.sockets.items()}}
        built[name] = objs
        print(f"BUILT {name} lod0 {t0} lod1 {t1} budget {piece.budget}" + ("  OVER" if t0 > piece.budget else ""))
    with open(tris_json, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(report.items())), fh, indent=1)
    return built


# --- review renders (textured preview; the glbs are already written) ------------------------------------

TEX = {"MAT_StreetTrim_A": "Textures/T_StreetTrim_A", "MAT_RoadPaint_A": "Textures/T_RoadPaint_A",
       "MAT_RoadPaint_B": "Ground/T_RoadPaint_B", "MAT_PlazaPaver": "Textures/T_PlazaPaver",
       "MAT_HerringbonePaver": "Textures/T_HerringbonePaver", "MAT_Asphalt": "Textures/T_Asphalt",
       "MAT_Concrete_Weathered": "Textures/T_ConcreteWeathered", "MAT_RockArmour": "Textures/T_RockArmour"}


def preview_materials(art_world: str) -> None:
    """Base colour = texture (UV0) x COLOR_0 for textured materials; COLOR_0 rgb x AO alpha for painted ones."""
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        nt = m.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        col = nt.nodes.get("Col")
        if bsdf is None or col is None:
            continue
        ao = nt.nodes.new("ShaderNodeMix")
        ao.data_type = "RGBA"
        ao.blend_type = "MULTIPLY"
        ao.inputs["Factor"].default_value = 1.0
        nt.links.new(col.outputs["Alpha"], ao.inputs[6])
        nt.links.new(col.outputs["Alpha"], ao.inputs[7])
        src = col.outputs["Color"]
        key = TEX.get(m.name)
        if key:
            path = os.path.join(art_world, key + "_BaseMap.png")
            if os.path.exists(path):
                img = nt.nodes.new("ShaderNodeTexImage")
                img.image = bpy.data.images.load(path, check_existing=True)
                src = img.outputs["Color"]
                if m.name == "MAT_RockArmour":       # algae tint lives in COLOR_0 for the rock shelf
                    mix = nt.nodes.new("ShaderNodeMix")
                    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
                    mix.inputs["Factor"].default_value = 1.0
                    nt.links.new(img.outputs["Color"], mix.inputs[6])
                    nt.links.new(col.outputs["Color"], mix.inputs[7])
                    src = mix.outputs[2]
        nt.links.new(src, ao.inputs[6])
        ao_val = nt.nodes.new("ShaderNodeMath")
        ao_val.operation = "MULTIPLY_ADD"
        nt.links.new(col.outputs["Alpha"], ao_val.inputs[0])
        ao_val.inputs[1].default_value = 0.6
        ao_val.inputs[2].default_value = 0.4
        nt.links.new(ao_val.outputs[0], ao.inputs[7])
        nt.links.new(ao.outputs[2], bsdf.inputs["Base Color"])


def render(objs, path, top=False) -> None:
    sc = bpy.context.scene
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o not in objs
    lo = [min((o.matrix_world @ v.co)[i] for o in objs for v in o.data.vertices) for i in range(3)]
    hi = [max((o.matrix_world @ v.co)[i] for o in objs for v in o.data.vertices) for i in range(3)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    rad = max(math.dist(lo, hi) / 2, 0.08)
    cam = bpy.data.objects.get("REVIEW_Cam")
    if cam is None:
        cam = bpy.data.objects.new("REVIEW_Cam", bpy.data.cameras.new("REVIEW_Cam"))
        sc.collection.objects.link(cam)
        sun = bpy.data.objects.new("REVIEW_Sun", bpy.data.lights.new("REVIEW_Sun", "SUN"))
        sun.data.energy = 3.5
        sun.rotation_euler = (math.radians(50), 0.0, math.radians(-35))
        sc.collection.objects.link(sun)
        world = sc.world or bpy.data.worlds.new("W")
        sc.world = world
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.6, 0.68, 1.0)
        world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    cam.data.lens = 50
    el, az = (math.radians(62), math.radians(-25)) if top else (math.radians(30), math.radians(-38))
    d = rad / math.sin(math.radians(17)) * 1.05
    cam.location = (c[0] + d * math.cos(el) * math.sin(az), c[1] - d * math.cos(el) * math.cos(az), c[2] + d * math.sin(el))
    cam.rotation_euler = (math.radians(90) - el, 0.0, az)
    cam.data.clip_end = d * 4
    sc.camera = cam
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 480, 340
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
