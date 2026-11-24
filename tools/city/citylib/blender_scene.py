"""Blender side: materials, kit meshes, per-cell object hierarchy and glTF export.

Scene layout (Blender, Z-up, metres, X = east, Y = north):
  PI_Kit/                       one object per KIT_* piece at the origin (source of the shared meshes)
  PI_City/<cell id>/            one collection per cell
    cell_<e>_<n>                root empty at the cell's south-west corner
      cell_<e>_<n>_LOD0         empty: Road, Pavement, Ground, Water meshes and bld_<osm id> buildings
        bld_<osm id>            empty at the footprint centroid; children are kit instances, the roof
                                and rooftop props (instances share the KIT_* mesh, so glTF reuses it)
      cell_<e>_<n>_LOD1         one merged low-detail mesh for the whole cell
      cell_<e>_<n>_COL          empty: *_Ground_COL and *_Buildings_COL meshes (no materials)

Export frame: glTFast negates X on import (TDD "Open-world streaming"). So before writing glTF
every object and mesh is turned 180 degrees about up (x, y -> -x, -y). Blender's exporter then maps
(x, y, z) -> glTF (x, z, -y), and glTFast maps glTF x -> -x, which lands Blender east on Unity +X
and Blender north on Unity +Z. The turn is applied by conjugation (each local transform T -> R T R^-1,
each mesh -> R mesh), so transforms stay translation + yaw and nothing gets a stray root rotation.
"""
from __future__ import annotations

import os

import bmesh
import bpy
from mathutils import Matrix

from . import kit
from . import street2_kit  # HEIGHTS/placement: the round-5 street kit pieces are markers too
from . import materials as M
from .cells import NO_MAT, CellGeom
from .mesh import MeshData

# name -> (sRGB hex, roughness, metallic): the world materials (citylib/materials.py). Preview colours only:
# Unity maps each name to an authored URP material with the CC0-derived textures.
MATERIALS: dict[str, tuple[str, float, float]] = M.MATERIALS

R180 = Matrix.Diagonal((-1.0, -1.0, 1.0, 1.0))


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_linear(h: str) -> tuple[float, float, float, float]:
    h = h.lstrip("#")
    return tuple(_srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4)) + (1.0,)


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0


def ensure_materials() -> dict[str, bpy.types.Material]:
    out = {}
    for name, (hx, rough, metal) in MATERIALS.items():
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        col = hex_linear(hx)
        bsdf.inputs["Base Color"].default_value = col
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        mat.diffuse_color = col
        mat.roughness = rough
        if name in (M.PROP, M.STREET_KIT, M.SIGNAGE) or True:
            # base colour from the "Col" vertex colours; glTF exports it as COLOR_0 wherever a mesh has "Col"
            # (prop palette colours; the street kit's paint + AO). Meshes without "Col" export no colours.
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            attr = nodes.get("Col") or nodes.new("ShaderNodeVertexColor")
            attr.name = "Col"
            attr.layer_name = "Col"
            links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
        out[name] = mat
    return out


def make_mesh(name: str, md: MeshData, mats: dict[str, bpy.types.Material]) -> bpy.types.Mesh:
    me = bpy.data.meshes.new(name)
    me.from_pydata(md.verts, [], md.faces)
    uv = me.uv_layers.new(name="UVMap")
    flat_uv = [c for face in md.uvs for corner in face for c in corner]
    uv.data.foreach_set("uv", flat_uv)
    if md.has_uv2:
        # second UV set (glTF TEXCOORD_1): per-surface data for later shaders, e.g. water's distance offshore
        uv2 = me.uv_layers.new(name="UVMap2")
        flat2 = [c for face, u2 in zip(md.faces, md._uv2_list()) for corner in (u2 or [(0.0, 0.0)] * len(face))
                 for c in corner]
        uv2.data.foreach_set("uv", flat2)
        me.uv_layers.active = uv
    if md.has_colors or md.has_alpha:
        # alpha: P87 baked contact shade per corner (citylib/level_edges.py), 1.0 elsewhere
        ca = me.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
        cols = []
        for i, (face, c) in enumerate(zip(md.faces, md.colors)):
            if c and isinstance(c[0], (tuple, list)):  # per-corner colours (road_writing)
                for cc in c:
                    cols.extend((*cc, 1.0))
                continue
            rgb = c or (1.0, 1.0, 1.0)
            for a in md.corner_alpha(i):
                cols.extend((*rgb, a))
        ca.data.foreach_set("color_srgb", cols)
    real = [m for m in md.materials if m != NO_MAT]
    for m in real:
        me.materials.append(mats[m])
    if real:
        remap = [real.index(m) if m != NO_MAT else 0 for m in md.materials]
        me.polygons.foreach_set("material_index", [remap[i] for i in md.mats])
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bm.to_mesh(me)
    bm.free()
    me.shade_flat()
    me.validate(clean_customdata=False)
    me.update()
    return me


def _obj(name: str, data, coll: bpy.types.Collection, parent=None, loc=(0.0, 0.0, 0.0)) -> bpy.types.Object:
    ob = bpy.data.objects.new(name, data)
    coll.objects.link(ob)
    if parent is not None:
        ob.parent = parent  # parent inverse stays identity: locals are true parent-space offsets
    ob.location = loc
    if data is None:
        ob.empty_display_type = "PLAIN_AXES"
        ob.empty_display_size = 2.0
    return ob


def _cart_meshes(mats) -> dict:
    """The baked isso wade carts and props (tools/city/build_carts.py writes the asset .blend)."""
    from . import cart_model, carts
    if not os.path.exists(carts.BLEND):
        print(f"[city] WARN no {carts.BLEND}: run tools/city/build_carts.py; carts are left out")
        return {}
    return cart_model.load_meshes(carts.BLEND, mats)


def _road_edge_meshes(mats=None) -> dict:
    """P117 WS-0339: the P92b road edge kit pieces from their asset .blend, on the kit's own trim material
    (MAT_RoadEdgeTrim_A and its textures come with them; texture paths are made absolute)."""
    from . import road_edge
    path = os.path.abspath(road_edge.BLEND)
    if not os.path.exists(path):
        print(f"[city] WARN no {path}: the road edge kit is left out")
        return {}
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n in road_edge.PIECES]
    base = os.path.dirname(path)
    out = {}
    for ob in dst.objects:
        if ob is None or ob.type != "MESH":
            continue
        out[ob.name.split(".")[0]] = ob.data
        ob.data.name = ob.name.split(".")[0]
        if mats is not None:
            for m in ob.data.materials:
                if m is not None and m.name.split(".")[0] == road_edge.MATERIAL:
                    mats[road_edge.MATERIAL] = m   # cells draw the kerb faces on it (citylib/cells.wall_quads)
    for im in bpy.data.images:
        if im.filepath.startswith("//") and not os.path.exists(bpy.path.abspath(im.filepath)):
            cand = os.path.join(base, im.filepath[2:])
            if os.path.exists(cand):
                im.filepath = cand
    return out


def build_kit(mats, street_only=None) -> dict[str, bpy.types.Mesh]:
    """Kit meshes by name: V1 Python MeshData pieces, and the street kit built by Geometry Nodes
    (citylib/gn/street.py) under the same names, so cells pick them up through the name swap."""
    from .gn import street
    coll = bpy.data.collections.new("PI_Kit")
    bpy.context.scene.collection.children.link(coll)
    meshes = {}
    built = street.build(mats, street_only)
    built.update(_cart_meshes(mats))
    built.update(_road_edge_meshes(mats))
    for name, piece in kit.PIECES.items():
        me = built.get(name) if piece.build is None else make_mesh(name, piece.build(), mats)
        if me is None:
            continue
        ob = _obj(name, me, coll)
        ob["kit_width_m"] = piece.width
        ob["kit_height_m"] = piece.height
        meshes[name] = me
    coll.hide_render = True
    return meshes


def _street_furniture_mesh(piece: str, cache: dict):
    """A KIT_SF_* piece is built by the frontage kit (Art/World/Kit/StreetFurniture/<piece>.glb), not by `build_kit`:
    import its mesh once so a cell build carries the props (P165: seats and slab stubs beside the lake edge)."""
    import os
    glb = os.path.join(os.path.dirname(__file__), "..", "..", "..", "unity", "BatchIsland", "Assets", "BatchIsland", "Art",
                       "World", "Kit", "StreetFurniture", piece + ".glb")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(glb))
    new = [o for o in bpy.data.objects if o not in before]
    me = next(o.data for o in new if o.type == "MESH")
    for o in new:
        bpy.data.objects.remove(o)
    cache[piece] = me
    return me


def build_cell(cg: CellGeom, mats, kit_meshes, extras: dict) -> bpy.types.Collection:
    city = bpy.data.collections.get("PI_City")
    if city is None:
        city = bpy.data.collections.new("PI_City")
        bpy.context.scene.collection.children.link(city)
    coll = bpy.data.collections.new(cg.id)
    city.children.link(coll)
    root = _obj(cg.id, None, coll, loc=(cg.origin[0], cg.origin[1], 0.0))
    for k, v in extras.items():
        root[k] = v
    root["cell"] = [cg.cell[0], cg.cell[1]]
    lod0 = _obj(f"{cg.id}_LOD0", None, coll, root)
    for name, md in cg.lod0.items():
        _obj(name, make_mesh(name, md, mats), coll, lod0)
    for b in cg.buildings:
        be = _obj(b.name, None, coll, lod0, b.pos)
        for k, v in b.props.items():
            be[k] = v
        if b.landmark_mesh is not None:
            _obj(b.landmark_name, make_mesh(b.landmark_name, b.landmark_mesh, mats), coll, be)
        if b.roof is not None and not b.roof.is_empty():
            _obj(f"{b.name}_Roof", make_mesh(f"{b.name}_Roof", b.roof, mats), coll, be)
        for i, inst in enumerate(b.instances):
            short = inst.piece[4:] if inst.piece.startswith("KIT_") else inst.piece
            ob = _obj(f"{b.name}_{short}_{i:03d}", kit_meshes[inst.piece], coll, be, (inst.x, inst.y, inst.z))
            ob.rotation_euler = (0.0, 0.0, inst.rot)
            if (inst.sx, inst.sy, inst.sz) != (1.0, 1.0, 1.0):
                ob.scale = (inst.sx, inst.sy, inst.sz)
    for name, pos, props in cg.heroes:
        # empty marker: Unity's CellBuilder nests the hero prefab (Art/World/Heroes/<name>.glb) here
        mk = _obj(name, None, coll, lod0, pos)
        for k, v in props.items():
            mk[k] = v
    for group, insts in sorted(cg.groups.items()):
        ge = _obj(f"{cg.id}_{group}", None, coll, lod0)
        for i, inst in enumerate(insts):
            if inst.piece.startswith(("VEG_", "POLE_", "WIRE_", "SIGN_", "POST_")) or street2_kit.is_piece(inst.piece):
                # vegetation marker (citylib/vegetation.py): Unity's CellBuilder places the VEG_*.glb LODs here;
                # P123 sign markers likewise (citylib/signs.py, Art/World/Signs/*.glb; posts scale z to their height)
                ob = _obj(f"{inst.piece}__{cg.id}_{i:04d}", None, coll, ge, (inst.x, inst.y, inst.z))
                ob.empty_display_size = 1.0
                ob.rotation_euler = (inst.rx, inst.ry, inst.rot)   # rx / ry: decay lean (signs), 0 elsewhere
                ob.scale = (inst.sx, inst.sy, inst.sz)
                continue
            short = inst.piece.split("_", 1)[1]
            me = kit_meshes.get(inst.piece) or _street_furniture_mesh(inst.piece, kit_meshes)
            ob = _obj(f"{cg.id}_{group}_{short}_{i:04d}", me, coll, ge, (inst.x, inst.y, inst.z))
            ob.rotation_euler = (0.0, 0.0, inst.rot)
            if (inst.sx, inst.sy, inst.sz) != (1.0, 1.0, 1.0):
                ob.scale = (inst.sx, inst.sy, inst.sz)
    if not cg.lod1.is_empty():
        _obj(f"{cg.id}_LOD1", make_mesh(f"{cg.id}_LOD1", cg.lod1, mats), coll, root)
    if cg.col:
        col = _obj(f"{cg.id}_COL", None, coll, root)
        for name, md in cg.col.items():
            ob = _obj(name, make_mesh(name, md, mats), coll, col)
            ob.display_type = "WIRE"
            ob.hide_render = True
    return coll


def build_env(name: str, md: MeshData, mats, extras: dict) -> bpy.types.Collection:
    """A world-placed environment piece (the open-sea band): its own collection, root at the world origin."""
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    root = _obj(name, None, coll)
    for k, v in extras.items():
        root[k] = v
    _obj(f"{name}_Mesh", make_mesh(f"{name}_Mesh", md, mats), coll, root)
    return coll


def to_export_frame() -> None:
    """Turn the whole scene 180 degrees about up (self-inverse: call again to undo)."""
    for ob in bpy.data.objects:
        ob.location.x, ob.location.y = -ob.location.x, -ob.location.y
    for me in bpy.data.meshes:
        me.transform(R180)
        me.update()


GLTF_SETTINGS = dict(
    export_format="GLB",
    export_yup=True,                 # glTF 2.0 is +Y up
    export_apply=True,               # apply modifiers (none are used)
    export_extras=True,              # custom properties -> node extras (osm_id, levels, cell)
    export_materials="EXPORT",
    export_texcoords=True,
    export_normals=True,
    export_tangents=False,           # no normal maps yet; Unity computes tangents if needed
    # vertex colours from the active "Col" attribute: prop palette rgb, kit paint, and (LOOK2, light_bake) Cycles AO in
    # alpha. "MATERIAL" exported only the rgb the material reads (COLOR_0 VEC3), which dropped the AO.
    export_vertex_color="ACTIVE",
    export_all_vertex_colors=False,
    export_active_vertex_color_when_no_material=True,
    export_cameras=False,
    export_lights=False,
    export_animations=False,
    export_skins=False,
    export_morph=False,
    export_gpu_instances=False,      # glTFast makes one GameObject per instance either way
    export_draco_mesh_compression_enable=False,  # needs the Draco package in Unity; the importer re-encodes anyway
    export_copyright="Geometry derived from OpenStreetMap data (c) OpenStreetMap contributors, ODbL 1.0",
)


def _layer_collection(name: str, lc=None):
    lc = lc or bpy.context.view_layer.layer_collection
    if lc.collection.name == name:
        return lc
    for child in lc.children:
        found = _layer_collection(name, child)
        if found:
            return found
    return None


def export_collection(coll_name: str, path: str, **overrides) -> None:
    """`overrides` replace GLTF_SETTINGS keys (place kits: export_all_vertex_colors=True for COLOR_1 wear)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.context.view_layer.active_layer_collection = _layer_collection(coll_name)
    bpy.ops.export_scene.gltf(filepath=path, use_active_collection=True,
                              use_active_collection_with_nested=True, use_selection=False, **{**GLTF_SETTINGS, **overrides})


def export_kit(out_dir: str) -> list[str]:
    paths = []
    kit_coll = bpy.data.collections["PI_Kit"]
    for name in kit.PIECES:
        tmp = bpy.data.collections.new(f"_export_{name}")
        bpy.context.scene.collection.children.link(tmp)
        tmp.objects.link(bpy.data.objects[name])
        path = os.path.join(out_dir, f"{name}.glb")
        export_collection(tmp.name, path)
        tmp.objects.unlink(bpy.data.objects[name])
        bpy.data.collections.remove(tmp)
        paths.append(path)
    assert kit_coll.objects
    return paths
