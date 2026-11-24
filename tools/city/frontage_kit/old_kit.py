"""Build the A/B baseline: import the old frontage kit glbs (Art/World/Kit) and assemble demo.BAYS (P96).

blender -b --factory-startup -P old_kit.py -- KIT_GLB_DIR OUT.blend
Writes a scratch .blend whose `_demo` frontage matches the new kit's on the same layout and camera.
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo  # noqa: E402

src, out = sys.argv[sys.argv.index("--") + 1:][:2]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
kit = bpy.data.collections.new("FrontageKit")
bpy.context.scene.collection.children.link(kit)
names = {n for bay in demo.BAYS for n in bay} | {demo.CORNER}
got = {}
for n in sorted(names):
    p = os.path.join(src, "KIT_" + n + ".glb")
    if not os.path.exists(p):
        continue
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=p)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH" and not o.name.split(".")[0].upper().endswith(("LOD1", "LOD2", "_COL"))]
    for o in new:
        if o not in meshes and o.type == "MESH":
            bpy.data.objects.remove(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if len(meshes) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = "KIT_" + n
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    kit.objects.link(ob)
    got[n] = ob
    xs = [v[0] for v in ob.bound_box]; ys = [v[1] for v in ob.bound_box]; zs = [v[2] for v in ob.bound_box]
    print("OLD", n, "x %.2f..%.2f y %.2f..%.2f z %.2f..%.2f" % (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)),
          "tris", sum(len(p.vertices) - 2 for p in ob.data.polygons))
for o in [o for o in bpy.data.objects if o.type == "EMPTY"]:
    bpy.data.objects.remove(o)
demo.assemble(get=got.get)
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
