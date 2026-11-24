"""Frontage kit v2 (P96): evaluate the assembly groups into game meshes.

For every piece: GN generator object (kept in `_src`, editable) -> evaluated mesh -> cleanup -> Bevel (edge
weights from the generator) + Weighted Normal on LOD0 -> trim-sheet UVs from the per-face `trim` row ->
COLOR_0 (rgb = paint by `role`, a = Cycles AO bake) -> `KIT_x`, `KIT_x_LOD1`, `KIT_x_COL` on a layout grid.
"""
from __future__ import annotations

import json
import os

import bmesh
import bpy
import numpy as np

import arcade
import parts
import pieces

HERE = os.path.dirname(os.path.abspath(__file__))
SHEET_W_M, SHEET_H_M = 4.0, 16.0
TEX = os.path.join(HERE, "textures", "T_FrontageTrim_A_BaseMap.png")
MAT = "MAT_FrontageTrim_A"
# decay level "light" (next to the Delta Face Hotel): same UVs, cleaner albedo (textures.py --decay light)
TEX_LIGHT = os.path.join(HERE, "textures", "T_FrontageTrim_A_Light_BaseMap.png")
MAT_LIGHT = "MAT_FrontageTrim_A_Light"
ROW = {tid: rows for tid, rows in parts.TRIM.values()}
ROLE_NAME = {v: k for k, v in parts.ROLE.items()}
ROTATE_TALL = False  # P143 generators set True (genbuild.build); the P96 kit keeps its UVs
STRIPES = {"KIT_Shopfront_Shutter_A": ("orange", "cream"), "KIT_Shopfront_Glazed_A": ("green", "cream"),
           "KIT_Shopfront_Shutter_D": ("green",), "KIT_Shopfront_Arched_B": ("green",)}


def srgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def collection(name, parent=None, hide=False):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in (parent or bpy.context.scene.collection).children:
        (parent or bpy.context.scene.collection).children.link(c)
    c.hide_render = hide
    return c


def material(name=MAT, tex=TEX):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Specular IOR Level"].default_value = 0.0
    img = nt.nodes.new("ShaderNodeTexImage")
    img_name = os.path.splitext(os.path.basename(tex))[0]
    if os.path.exists(tex):
        img.image = bpy.data.images.load(tex, check_existing=True)
    else:
        img.image = bpy.data.images.get(img_name) or bpy.data.images.new(img_name, 1024, 4096)
    col = nt.nodes.new("ShaderNodeVertexColor")
    col.layer_name = "Col"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(img.outputs["Color"], mix.inputs["A"])
    nt.links.new(col.outputs["Color"], mix.inputs["B"])
    ao = nt.nodes.new("ShaderNodeMix")
    ao.data_type, ao.blend_type = "RGBA", "MULTIPLY"
    ao.inputs["Factor"].default_value = 1.0
    nt.links.new(mix.outputs["Result"], ao.inputs["A"])
    nt.links.new(col.outputs["Alpha"], ao.inputs["B"])
    nt.links.new(ao.outputs["Result"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def _socket_id(ng, name):
    return next(i.identifier for i in ng.interface.items_tree if getattr(i, "in_out", "") == "INPUT" and i.name == name)


def generator(name, ng, lod, src):
    me = bpy.data.meshes.new(f"GEN_{name}_{lod}")
    ob = bpy.data.objects.new(f"GEN_{name}_LOD{lod}", me)
    src.objects.link(ob)
    mod = ob.modifiers.new("Frontage", "NODES")
    mod.node_group = ng
    ins, sid = mod.properties.inputs, _socket_id(ng, "LOD")
    cur = getattr(ins, sid)
    if hasattr(cur, "value"):
        cur.value = bool(lod)
    else:
        setattr(ins, sid, bool(lod))
    return ob


def evaluate(ob, name):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    me.name = name
    return me


def cleanup(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    # No vertex welding: parts are separate closed shells that may touch; welding them makes edges with 3+ faces.
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=0.0005)
    straight = [v for v in bm.verts if len(v.link_edges) == 2 and len(v.link_faces) == 2 and
                abs((v.link_edges[0].other_vert(v).co - v.co).normalized().dot(
                    (v.link_edges[1].other_vert(v).co - v.co).normalized()) + 1) < 1e-6]
    bmesh.ops.dissolve_verts(bm, verts=straight)          # boolean leftovers on straight edges -> sliver tris
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4], quad_method="BEAUTY",
                          ngon_method="BEAUTY")
    slivers = [f for f in bm.faces if f.calc_area() < 1e-7]
    bmesh.ops.delete(bm, geom=slivers, context="FACES_ONLY")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()


def apply_mods(ob, bevel):
    if bevel:
        b = ob.modifiers.new("Bevel", "BEVEL")
        b.limit_method, b.width, b.segments, b.use_clamp_overlap = "WEIGHT", 0.012, 1, True
        b.miter_outer = "MITER_ARC"
        _bake_mods(ob)
    finish(ob.data)
    w = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    w.keep_sharp = True
    _bake_mods(ob)


def _bake_mods(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    bpy.data.meshes.remove(old)
    me.name = ob.name


def _key(co, eps=1e-4):
    return (round(co.x / eps), round(co.y / eps), round(co.z / eps))


def finish(me):
    """Ship-ready topology: triangles (beauty), no zero-area slivers, and no edge of one part lying exactly on an
    edge of another (engines and the P95 validator weld by position, which would make 3+ face edges): a touching
    part is nudged 0.3 mm toward the street and up, which no camera can see."""
    bm = bmesh.new()
    bm.from_mesh(me)
    straight = [v for v in bm.verts if len(v.link_edges) == 2 and len(v.link_faces) == 2 and
                abs((v.link_edges[0].other_vert(v).co - v.co).normalized().dot(
                    (v.link_edges[1].other_vert(v).co - v.co).normalized()) + 1) < 1e-6]
    bmesh.ops.dissolve_verts(bm, verts=straight)
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method="BEAUTY", ngon_method="BEAUTY")
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.calc_area() < 1e-8], context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    seen, todo = set(), set(bm.faces)
    while todo:
        f0 = todo.pop()
        isl, stack = {f0}, [f0]
        while stack:
            for e in stack.pop().edges:
                for g in e.link_faces:
                    if g in todo:
                        todo.discard(g)
                        isl.add(g)
                        stack.append(g)
        verts = {v for f in isl for v in f.verts}
        edges = {e for f in isl for e in f.edges}
        for k in range(1, 6):
            keys = {tuple(sorted((_key(e.verts[0].co), _key(e.verts[1].co)))) for e in edges}
            if not keys & seen:
                break
            for v in verts:
                v.co.y -= 0.0003
                v.co.z += 0.0002
        seen |= keys
    bm.to_mesh(me)
    bm.free()


def face_attr(me, name, default=0):
    a = me.attributes.get(name)
    vals = np.full(len(me.polygons), default, dtype=np.int64)
    if a is not None and a.domain == "FACE":
        buf = np.zeros(len(me.polygons), dtype=np.int32)
        a.data.foreach_get("value", buf)
        vals = buf.astype(np.int64)
    return vals


PAINT_OVERRIDE = {}   # P147: piece name -> {role name: "#hex"}, set by genbuild from an entry's `paint` (signs, markings)


def uv_and_paint(me, piece_h, variant, name):
    """Trim-sheet UVs (metre projection, 256 px/m) and COLOR_0 paint per role."""
    n_p, n_l = len(me.polygons), len(me.loops)
    start = np.zeros(n_p, np.int64); me.polygons.foreach_get("loop_start", start)
    total = np.zeros(n_p, np.int64); me.polygons.foreach_get("loop_total", total)
    nrm = np.zeros(n_p * 3); me.polygons.foreach_get("normal", nrm); nrm = nrm.reshape(-1, 3)
    cen = np.zeros(n_p * 3); me.polygons.foreach_get("center", cen); cen = cen.reshape(-1, 3)
    vidx = np.zeros(n_l, np.int64); me.loops.foreach_get("vertex_index", vidx)
    co = np.zeros(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)[vidx]
    trim = face_attr(me, "trim")
    role = face_attr(me, "role")
    pidx = np.repeat(np.arange(n_p), total)
    axis = np.argmax(np.abs(nrm), axis=1)
    ax = axis[pidx]
    sgn = np.sign(nrm[pidx, ax])
    u = np.where(ax == 1, co[:, 0] * -sgn, np.where(ax == 0, co[:, 1] * sgn, co[:, 0]))
    w = np.where(ax == 2, co[:, 1], co[:, 2])
    v0 = np.array([ROW[t][0] for t in range(len(ROW))])[trim]
    vh = np.array([ROW[t][1] for t in range(len(ROW))])[trim]
    # v range per island (faces of one row and one projection that share a vertex), not per triangle: fan
    # triangles of an arch pane or a spall floor each took their own range, which broke the row into blotches
    isl = _islands(me, np.stack([trim, axis, np.sign(nrm[np.arange(n_p), axis]).astype(np.int64)], 1))
    sp = trim == parts.TR["SPALL"]      # a piece has one spall: all its faces per projection share one range
    for g, k in enumerate(np.unique(axis[sp] * 2 + (nrm[np.arange(n_p), axis][sp] > 0))):
        isl[sp & (axis * 2 + (nrm[np.arange(n_p), axis] > 0) == k)] = isl.max() + 1 + g
    if ROTATE_TALL:   # P143: an island taller than its row but narrower than tall turns 90 deg (U tiles, V does not)
        n_i = isl.max() + 1
        rng = []
        for arr in (u, w):
            lo = np.full(n_i, np.inf); np.minimum.at(lo, isl[pidx], arr)
            hi = np.full(n_i, -np.inf); np.maximum.at(hi, isl[pidx], arr)
            rng.append(hi - lo)
        row_h = np.full(n_i, np.inf); np.minimum.at(row_h, isl, vh)
        nowall = np.ones(n_i, bool); nowall[isl[trim == parts.TR["WALL"]]] = False
        rot = nowall & (rng[1] > row_h - 0.024) & (rng[0] < rng[1])
        rl = rot[isl[pidx]]
        u, w = np.where(rl, w, u), np.where(rl, -u, w)
    fmin = np.minimum.reduceat(w, start)
    fmax = np.maximum.reduceat(w, start)
    imin = np.full(isl.max() + 1, np.inf); np.minimum.at(imin, isl, fmin)
    imax = np.full(isl.max() + 1, -np.inf); np.maximum.at(imax, isl, fmax)
    wmin, wmax = imin[isl], imax[isl]
    ext = np.maximum(wmax - wmin, 1e-6)
    margin = 0.012
    scale = np.minimum(1.0, (vh - 2 * margin) / ext)
    wall_side = (trim == parts.TR["WALL"]) & (np.abs(nrm[:, 2]) < 0.7)
    off = {"A": 0.0, "B": 1.37, "C": 2.71, "D": 0.53}[variant]
    s_l = scale[pidx]
    v_local = v0[pidx] + margin + (w - wmin[pidx]) * s_l
    # the wall row is one 4 m storey (streaks hang from its top, splash at its foot); a taller (4.5 m colonial)
    # storey maps onto it 11 % compressed so both ends stay, a shorter one takes its top part
    z = co[:, 2]
    # P143 building classes store each storey's base and height (cm) on their wall faces, so every storey maps
    # onto the 4 m wall row by itself; faces without them use the piece height as before
    zb = face_attr(me, "zb_cm")[pidx] / 100.0
    sh = face_attr(me, "sh_cm")[pidx] / 100.0
    ph = np.where(sh > 0, sh, piece_h)
    zl = z - zb
    v_wall = np.clip(np.where(ph > 4.0, zl * 4.0 / ph, zl + (4.0 - ph)), margin, 4.0 - margin)
    v = np.where(wall_side[pidx], v_wall, v_local)
    uu = np.where(wall_side[pidx], u + off, u * s_l)
    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    uv.data.foreach_set("uv", np.stack([uu / SHEET_W_M, v / SHEET_H_M], 1).ravel())
    # paint
    pal = {**pieces.COMMON, **pieces.PAINT[variant], **PAINT_OVERRIDE.get(name.replace("_LOD1", "").replace("_LOD2", ""), {})}
    rgb = np.array([srgb(pal.get(ROLE_NAME[r], "#FFFFFF")) if ROLE_NAME[r] != "CANVAS" else [1, 1, 1]
                    for r in range(len(ROLE_NAME))])[role]
    if name.split("_LOD")[0] in arcade.PROPS:     # P186: arcade shop-opening metal reads as slate at grazing angles
        rgb[role == parts.ROLE["METAL"]] = srgb(arcade.REVEAL_PAINT)
    stripes = STRIPES.get(name.replace("_LOD1", ""), ("red", "cream"))
    canvas = role == parts.ROLE["CANVAS"]
    if canvas.any():
        k = np.floor((cen[:, 0] - 0.1) / 0.45).astype(int) % len(stripes)
        cols = np.array([srgb(pieces.CANVAS[c]) for c in stripes])
        rgb[canvas] = cols[k[canvas]]
    tile = role == parts.ROLE.get("TILE", -1)
    if tile.any():   # P148 clay tile: each course patch (1.2 m x one course) a little lighter, darker or bragent,
        # as old Calicut roofs are re-laid piecemeal; a stable hash of the face centre, so rebuilds do not shimmer
        h = np.modf(np.abs(np.sin(cen[tile] @ np.array([12.9898, 78.233, 37.719])) * 43758.5453))[0]
        rgb[tile] = rgb[tile] * (0.82 + 0.26 * h)[:, None] * np.where(h[:, None] < 0.3, [0.92, 0.95, 1.0], 1.0)
    a = me.color_attributes.get("Col") or me.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
    rgba = np.concatenate([rgb[pidx], np.ones((n_l, 1))], 1)
    a.data.foreach_set("color_srgb", rgba.ravel())
    me.color_attributes.active_color = a
    me.color_attributes.render_color_index = me.color_attributes.find("Col")


def _islands(me, key):
    """Island id per face: faces with equal `key` rows that share a vertex (union-find)."""
    n_p = len(me.polygons)
    parent = list(range(n_p))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    first = {}
    keys = [tuple(k) for k in key.tolist()]
    # by vertex position, not index: boolean and bevel output can leave a pocket floor split along seams
    pos = [_key(v.co, 1e-4) for v in me.vertices]
    for f in me.polygons:
        k = keys[f.index]
        for vi in f.vertices:
            j = first.setdefault((pos[vi], k), f.index)
            if j != f.index:
                a, b = find(j), find(f.index)
                if a != b:
                    parent[a] = b
    roots = np.array([find(i) for i in range(n_p)])
    _, ids = np.unique(roots, return_inverse=True)
    return ids


def bake_ao(ob):
    """Cycles AO bake into a temporary colour attribute, copied into COLOR_0 alpha (Painted Cityhub A rule)."""
    me = ob.data
    tmp = me.color_attributes.new("AO", "FLOAT_COLOR", "CORNER")
    me.color_attributes.active_color = tmp
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    others = [o for o in bpy.context.scene.objects if o.type == "MESH" and o is not ob and not o.hide_render]
    for o in others:      # bake each piece alone: LOD0 and LOD1 share a location and would occlude each other
        o.hide_render = True
    bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
    for o in others:
        o.hide_render = False
    ao = np.zeros(len(me.loops) * 4); tmp.data.foreach_get("color", ao)
    col = me.color_attributes["Col"]
    rgba = np.zeros(len(me.loops) * 4); col.data.foreach_get("color_srgb", rgba)
    rgba = rgba.reshape(-1, 4)
    rgba[:, 3] = np.clip(0.35 + 0.65 * ao.reshape(-1, 4)[:, 0], 0.0, 1.0)   # never black (violet AO in shader)
    # Glass panes are long fan triangles: vertex AO smears into blotches across them, so glass keeps full alpha.
    trim = face_attr(me, "trim")
    counts = np.zeros(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_total", counts)
    rgba[np.repeat(trim == parts.TR["GLASS"], counts), 3] = 1.0
    col.data.foreach_set("color_srgb", rgba.ravel())
    me.color_attributes.remove(me.color_attributes["AO"])
    me.color_attributes.active_color = me.color_attributes["Col"]


def collision(name, w, h, depth, at, coll):
    me = bpy.data.meshes.new(f"{name}_COL")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    y0 = -0.08
    for v in bm.verts:
        v.co.x = (v.co.x + 0.5) * w
        v.co.y = y0 + (v.co.y + 0.5) * (depth - y0)
        v.co.z = (v.co.z + 0.5) * h
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(f"{name}_COL", me)
    ob.location = at
    ob.hide_render = True
    coll.objects.link(ob)
    return ob


def setup_scene():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 24
    sc.cycles.device = "CPU"
    if not sc.world:
        sc.world = bpy.data.worlds.new("World")
    sc.world.light_settings.distance = 0.6
    sc.unit_settings.system, sc.unit_settings.scale_length = "METRIC", 1.0


def build(only=None, bake=True):
    setup_scene()
    parts.build_groups()
    asm = pieces.build_assemblies()
    src = collection("_src", hide=True)
    kit = collection("FrontageKit")
    mat = material()
    material(MAT_LIGHT, TEX_LIGHT)     # decay level "light": swapped in per placement (object-level slot)
    tris = {}
    rows = {"Upper": 0, "Shopfront": 1, "WallPlaster": 2, "Parapet": 3}
    col_i = {}
    for name, (ng, w, h, v, refs) in asm.items():
        if only and only not in name:
            continue
        fam = name.split("_")[1]
        r = rows.get(fam, 4)
        col_i[r] = col_i.get(r, -1) + 1
        at = (col_i[r] * 4.5, r * 8.0, 0.0)
        for lod in (0, 1):
            gen = generator(name, ng, lod, src)
            gen.location = at
            oname = name if lod == 0 else f"{name}_LOD1"
            me = evaluate(gen, oname)
            cleanup(me)
            ob = bpy.data.objects.new(oname, me)
            ob.location = at
            kit.objects.link(ob)
            bpy.context.view_layer.update()
            apply_mods(ob, bevel=(lod == 0))
            ob.data.materials.clear()      # GN output carries one empty slot
            ob.data.materials.append(mat)
            uv_and_paint(ob.data, h, v, oname)
            if bake:
                bake_ao(ob)
            ob["refs"] = ",".join(refs)
            ob["storey_h"] = round(h, 3)
            ob["decay_levels"] = "worn" if name in pieces.WORN_ONLY else "light,worn"
            ob["decay_default"] = "worn"
            if lod:
                ob.hide_render = True
            tris.setdefault(name, {})[f"lod{lod}"] = sum(len(p.vertices) - 2 for p in ob.data.polygons)
        if name in arcade.PROPS:      # walk-under arcade (P186): corridor collision and walk metadata
            arcade.collision(name, at, kit)
            for o in (bpy.data.objects[name], bpy.data.objects[f"{name}_LOD1"]):
                for k, val in arcade.PROPS[name].items():
                    o[k] = val
            continue
        collision(name, w, h, 0.9 if "Corner" in name else 0.3, at, kit)
    for o in src.objects:
        o.hide_set(True)
    return tris


def write_tris(tris, path):
    with open(path, "w") as f:
        json.dump(tris, f, indent=1, sort_keys=True)
