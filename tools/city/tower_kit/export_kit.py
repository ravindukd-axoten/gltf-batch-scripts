"""Export each tower (LOD0-2) from TOWER_KIT_A.blend to tools/city/tower_kit/export/<name>.glb (gitignored scratch).

    blender -b -q tools/city/tower_kit/TOWER_KIT_A.blend -P tools/city/tower_kit/export_kit.py

Each piece is exported at its own origin (base centre, world axes); glTF converts Blender Z-up to Y-up. Custom
properties (name_id, height_m, ad_slots, mount_z_m, span_m) go out as glTF extras; the AO bake goes out as COLOR_0.
"""
import pathlib
import sys

import bpy

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from towers import TOWERS  # noqa: E402

out = HERE / "export"
out.mkdir(exist_ok=True)
for name in TOWERS:
    objs = [bpy.data.objects[n] for n in (name, f"{name}_LOD1", f"{name}_LOD2")]
    saved = [o.location.copy() for o in objs]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.location = (0.0, 0.0, 0.0)
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    path = out / f"{name}.glb"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_apply=True,
                              export_extras=True, export_vertex_color="ACTIVE", export_yup=True)
    for o, loc in zip(objs, saved):
        o.location = loc
    print(f"{path.name}: {path.stat().st_size // 1024} KB")
