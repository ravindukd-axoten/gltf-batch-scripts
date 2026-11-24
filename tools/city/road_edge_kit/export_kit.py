"""Export every road edge kit piece to its own .glb (LOD0 + LOD1 + _COL, pivot at the origin, Y-up).

Output goes to a scratch folder, never into Unity Assets (P92 brief; the Unity import is a later task):
    blender -b tools/city/road_edge_kit/KIT_RoadEdge_A.blend -P tools/city/road_edge_kit/export_kit.py -- <out dir>
"""
import os
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "/tmp/road_edge_kit_glb"
os.makedirs(out, exist_ok=True)
kit = bpy.data.collections["RoadEdgeKit"]
scene = bpy.context.scene
vl = bpy.context.view_layer
pieces = sorted((o for o in kit.objects if o.type == "MESH" and not o.name.endswith(("_LOD1", "_COL"))),
                key=lambda o: o.name)
total = 0
for ob in pieces:
    group = [bpy.data.objects.get(n) for n in (ob.name, ob.name + "_LOD1", ob.name + "_COL")]
    group = [g for g in group if g is not None]
    keep = [(g, g.location.copy()) for g in group]
    for o in vl.objects:
        o.select_set(False)
    for g in group:
        g.location = (0.0, 0.0, 0.0)
        g.hide_set(False)
        g.select_set(True)
    fp = os.path.join(out, ob.name + ".glb")
    bpy.ops.export_scene.gltf(filepath=fp, use_selection=True, export_format="GLB", export_apply=True,
                              export_yup=True, export_image_format="NONE")
    for g, loc in keep:
        g.location = loc
    total += os.path.getsize(fp)
print(f"EXPORTED {len(pieces)} pieces, {total // 1024} KB -> {out}")
