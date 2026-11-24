"""Export each frontage kit piece (LOD0, LOD1, collision) to its own glb in a scratch folder (P96).

blender -b KIT_Frontage_A.blend -P export_kit.py -- OUT_DIR
Run in background Blender only. Each piece is moved to the origin for its export so the pivot is the bay's
street-side bottom-left corner on world axes (+X east along the street, +Y north into the building in Blender =
+Z in Unity, +Z up). Vertex colour COLOR_0 (paint x AO) is exported; the output is a build product, not committed.
"""
import os
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1]
os.makedirs(out, exist_ok=True)
kit = bpy.data.collections["FrontageKit"]
names = sorted(o.name for o in kit.objects if o.type == "MESH" and not o.name.endswith(("_LOD1", "_COL")))
for nm in names:
    group = [bpy.data.objects[n] for n in (nm, nm + "_LOD1", nm + "_COL") if n in bpy.data.objects]
    keep = [o.location.copy() for o in group]
    hidden = [o.hide_render for o in group]
    for o in group:
        o.location = (0, 0, 0)
        o.hide_render = False
    bpy.ops.object.select_all(action="DESELECT")
    for o in group:
        o.hide_set(False)
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(out, nm + ".glb"), use_selection=True, export_format="GLB",
                              export_vertex_color="ACTIVE", export_apply=True, export_yup=True)
    for o, loc, h in zip(group, keep, hidden):
        o.location, o.hide_render = loc, h
print("EXPORTED", len(names), out)
