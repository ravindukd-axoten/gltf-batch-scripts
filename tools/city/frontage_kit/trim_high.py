"""High-poly source for the frontage trim sheet T_FrontageTrim_A (P96), baked by Cycles onto a 4 x 16 m plane.

blender -b --factory-startup -P trim_high.py -- [--res 256] [--out bakes] [--save trim_high.blend]

Each trim row (FRONTAGE_KIT_SPEC.md "Trim sheet") gets real relief built from primitives and modifiers (Array,
Bevel), never vertex by vertex: roller-shutter slats, louvre blades, raised door panels, frame mouldings, canvas
folds, running-bond brick for spalls and corrugated sheet. Every pattern repeats on a period that divides 4 m, so
the rows tile along U. Three bakes come out at `res` px per metre (256 = game density, 1024 x 4096):
  trim_ao.png  ambient occlusion (selected-to-active, 0.06 m distance)
  trim_nrm.png tangent-space normal (+X = U, +Y = V); used only to paint light into the albedo, never shipped
  trim_h.png   height, 1.0 = 0.05 m above the plane
textures.py paints the shipped albedo from these. Bakes are build outputs (gitignored), not assets.
"""
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RES = int(argv[argv.index("--res") + 1]) if "--res" in argv else 256
OUT = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(HERE, "bakes")
SAVE = argv[argv.index("--save") + 1] if "--save" in argv else ""
W, H = 4.0, 16.0
os.makedirs(OUT, exist_ok=True)


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


def box(name, x0, x1, y0, y1, z0, z1, bevel=0.0, segs=2, rot=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    o = bpy.context.object
    o.name = name
    o.scale = (x1 - x0, y1 - y0, z1 - z0)
    bpy.ops.object.transform_apply(scale=True)
    if rot:
        o.rotation_euler = rot
    if bevel:
        b = o.modifiers.new("Bevel", "BEVEL")
        b.width, b.segments, b.limit_method = bevel, segs, "NONE"
    return o


def rod(name, axis, length, r, at, zscale, segs=16):
    """Cylinder along `axis` ('x' or 'y'), squashed in Z: a slat or corrugation profile."""
    rot = (0, math.pi / 2, 0) if axis == "x" else (math.pi / 2, 0, 0)
    bpy.ops.mesh.primitive_cylinder_add(vertices=segs, radius=r, depth=length, location=at, rotation=rot)
    o = bpy.context.object
    o.name = name
    bpy.ops.object.transform_apply(rotation=True)
    o.scale = (1, 1, zscale)
    bpy.ops.object.transform_apply(scale=True)
    return o


def array(o, count, offset, name="Array"):
    a = o.modifiers.new(name, "ARRAY")
    a.count = count
    a.use_relative_offset, a.use_constant_offset = False, True
    a.constant_offset_displace = offset
    return o


def build_high():
    hi = []
    L0, L1 = -0.3, W + 0.3          # overhang U so the bake sees no ends: rows tile
    hi.append(box("backing", L0, L1, -0.3, H + 0.3, -0.02, 0.0))
    # FRAME 5-6: three moulded rails with sunk grooves between (paint-filled joints read at frame scale)
    for y0, y1 in ((5.03, 5.30), (5.34, 5.66), (5.70, 5.97)):
        hi.append(box("frame", L0, L1, y0, y1, 0.0, 0.016, 0.006))
    # CONCRETE 6-7: slab edge chamfers every 1 m (formwork joints)
    hi.append(array(box("formwork", -0.01, 0.01, 6.02, 6.98, -0.01, 0.002, 0.004), 5, (1.0, 0, 0)))
    # ROLLER 7-9.4: curved slats, 0.08 m pitch (30 slats)
    hi.append(array(rod("slat", "x", L1 - L0, 0.042, (W / 2, 7.04, 0.0), 0.22), 30, (0, 0.08, 0)))
    # LOUVRE 9.4-10.6: blades tilted 40 degrees, 0.1 m pitch, in a stiled panel every 0.5 m
    hi.append(array(box("blade", L0, L1, -0.06, 0.06, -0.004, 0.004, 0.003, 1, (math.radians(40), 0, 0)),
                    12, (0, 0.1, 0)))
    hi[-1].location = (W / 2, 9.45, 0.03)
    hi.append(array(box("stile", -0.025, 0.025, 9.4, 10.6, 0.0, 0.05, 0.008), 9, (0.5, 0, 0)))
    # PANEL 10.6-11.6: raised-and-fielded panels, 0.5 m pitch, two tiers
    for y0, y1 in ((10.66, 11.08), (11.14, 11.56)):
        hi.append(array(box("panel", 0.06, 0.44, y0, y1, 0.0, 0.02, 0.03, 3), 8, (0.5, 0, 0)))
    # GLASS 11.6-12.8: flat (putty beads at the top and bottom)
    hi.append(box("bead", L0, L1, 11.6, 11.64, 0.0, 0.01, 0.004))
    hi.append(box("bead", L0, L1, 12.76, 12.8, 0.0, 0.01, 0.004))
    # CANVAS 12.8-13.6: soft vertical folds, 0.2 m pitch (stripes are 0.45 m in vertex colour)
    hi.append(array(rod("fold", "y", 0.8, 0.1, (0.0, 13.2, -0.013), 0.25, 24), 21, (0.2, 0, 0)))
    # METAL 13.6-14.4: pressed panel seams every 0.4 m and rivet heads
    hi.append(array(box("seam", -0.012, 0.012, 13.6, 14.4, 0.0, 0.006, 0.004), 11, (0.4, 0, 0)))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=0.008, location=(0.2, 13.66, 0))
    rv = bpy.context.object
    array(array(rv, 10, (0.4, 0, 0)), 2, (0, 0.68, 0), "Array2")
    hi.append(rv)
    # SPALL 14.4-15.2: running-bond brick 0.19 x 0.065, 10 mm joints (period 0.2 m)
    for k, (dx, y) in enumerate(((0.0, 14.42), (0.1, 14.495))):
        b = box("brick", dx + 0.005, dx + 0.195, y, y + 0.065, 0.0, 0.022, 0.005)
        hi.append(array(array(b, 21, (0.2, 0, 0)), 5, (0, 0.15, 0), "Array2"))
        b.location.x -= 0.2
    # PLINTH 15.2-15.6: flat
    # SHEET 15.6-16.0: corrugations, 0.08 m pitch (50 across 4 m)
    hi.append(array(rod("corr", "y", 0.4, 0.04, (0.0, 15.8, -0.012), 0.6, 16), 51, (0.08, 0, 0)))
    return hi


def material_height():
    m = bpy.data.materials.new("M_Height")
    nt = m.node_tree
    nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation, mul.inputs[1].default_value, mul.use_clamp = "MULTIPLY", 20.0, True
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], mul.inputs[0])
    nt.links.new(mul.outputs[0], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def target():
    bpy.ops.mesh.primitive_plane_add(size=1, location=(W / 2, H / 2, 0))
    o = bpy.context.object
    o.name = "TrimTarget"
    o.scale = (W, H, 1)
    bpy.ops.object.transform_apply(scale=True)
    m = bpy.data.materials.new("M_Target")
    o.data.materials.append(m)
    return o


def bake(tgt, hi, kind, name, samples):
    img = bpy.data.images.new(name, int(W * RES), int(H * RES), float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    nt = tgt.active_material.node_tree
    for n in [n for n in nt.nodes if n.type == "TEX_IMAGE"]:
        nt.nodes.remove(n)
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = img
    nt.nodes.active = node
    bpy.context.scene.cycles.samples = samples
    bpy.ops.object.select_all(action="DESELECT")
    for o in hi:
        o.select_set(True)
    tgt.select_set(True)
    bpy.context.view_layer.objects.active = tgt
    bpy.ops.object.bake(type=kind, use_selected_to_active=True, cage_extrusion=0.12, max_ray_distance=0.2,
                        margin=0, normal_space="TANGENT")
    sc = bpy.context.scene
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "16"
    sc.render.image_settings.color_mode = "RGB"
    path = os.path.join(OUT, name + ".png")
    img.save_render(path, scene=sc)
    print("BAKED", kind, path)


def main():
    clear()
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.view_settings.view_transform = "Standard"
    sc.world = sc.world or bpy.data.worlds.new("World")
    sc.world.light_settings.distance = 0.06
    hi = build_high()
    mh = material_height()
    for o in hi:
        o.data.materials.clear()
        o.data.materials.append(mh)
    tgt = target()
    bake(tgt, hi, "NORMAL", "trim_nrm", 1)
    bake(tgt, hi, "EMIT", "trim_h", 1)
    bake(tgt, hi, "AO", "trim_ao", 16)
    if SAVE:
        bpy.ops.wm.save_as_mainfile(filepath=SAVE, compress=True)


main()
