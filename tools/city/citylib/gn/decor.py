"""Hero surface pass (research 3.3 and 5): vertex paint + AO in COLOR_0 and a baked decor atlas on UV1.

COLOR_0 (`Col`, byte corner colour): rgb = paint variation (a low-frequency tint of the lime-wash and tiles, so
one material reads as many repaints, Art Bible "Paint variation by vertex colour"; black = glass, which is drawn
by the trim material, build_heroes._merge_glass), a = ambient occlusion
(Cycles, baked first into rgb by build_heroes._bake_ao and moved to alpha here).

Decor atlas (`T_<Hero>_Decor.png`, 2048, linear, UV1 = `UVMap2`): R grime (cavities and corners, from a short
AO), G monsoon streaks (vertical streak noise in the band under every floor line and under ledges), B base dirt
(splash-back up to about 1.4 m), A localised AO (SLICE5: reveals, soffits, cornice undersides, wall feet; 1 = open).
Baked with Cycles from those masks (AO and position driven, no painting, nothing
from the reference photos). SHD_HeroLit (Unity) multiplies the albedo by grime/streak colours with these masks.
LOD1 has no unwrap: its UV1 points at a reserved clean corner of the atlas.
"""
from __future__ import annotations

import math

import bpy

UV1_SCALE = 0.985          # UV1 islands packed into [0, 0.985]; the top-right corner stays clean (LOD1)
CLEAN_UV = (0.995, 0.995)
FLOOR_PERIOD = 4.0         # storey height above the ground floor (hero_hotel.LEVELS)
FLOOR_PHASE = 1.6


def _n(nt, kind, **kw):
    node = nt.nodes.new(kind)
    for k, v in kw.items():
        setattr(node, k, v)
    return node


def _math(nt, op, a, b=None, clamp=False):
    m = _n(nt, "ShaderNodeMath", operation=op, use_clamp=clamp)
    for i, x in enumerate((a, b)):
        if x is None:
            continue
        if isinstance(x, (int, float)):
            m.inputs[i].default_value = x
        else:
            nt.links.new(x, m.inputs[i])
    return m.outputs[0]


def _bake_material(img) -> bpy.types.Material:
    mat = bpy.data.materials.new("_PI_DecorBake")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = _n(nt, "ShaderNodeOutputMaterial")
    emit = _n(nt, "ShaderNodeEmission")
    nt.links.new(emit.outputs[0], out.inputs["Surface"])
    tex = _n(nt, "ShaderNodeTexImage")
    tex.image = img
    nt.nodes.active = tex
    geo = _n(nt, "ShaderNodeNewGeometry")
    sep_p = _n(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep_p.inputs[0])
    sep_n = _n(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], sep_n.inputs[0])
    z = sep_p.outputs[2]
    side = _math(nt, "SUBTRACT", 1.0, _math(nt, "ABSOLUTE", sep_n.outputs[2]), clamp=True)  # 1 on walls
    ao_short = _n(nt, "ShaderNodeAmbientOcclusion", samples=16)
    ao_short.inputs["Distance"].default_value = 0.8
    ao_long = _n(nt, "ShaderNodeAmbientOcclusion", samples=16)
    ao_long.inputs["Distance"].default_value = 2.5
    # R grime: cavities and inside corners, broken by a soft noise
    noise = _n(nt, "ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.35
    noise.inputs["Detail"].default_value = 4.0
    nt.links.new(geo.outputs["Position"], noise.inputs["Vector"])
    cav = _math(nt, "SUBTRACT", 1.0, ao_short.outputs["AO"], clamp=True)
    grime = _math(nt, "MULTIPLY", _math(nt, "POWER", cav, 0.8), _math(nt, "MULTIPLY_ADD" if False else "ADD", _math(nt, "MULTIPLY", noise.outputs["Fac"], 0.9), 0.35), clamp=True)
    # G monsoon streaks: vertical streak noise, strongest just under each floor line and under ledges
    mapping = _n(nt, "ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (5.0, 5.0, 0.22)
    nt.links.new(geo.outputs["Position"], mapping.inputs["Vector"])
    snoise = _n(nt, "ShaderNodeTexNoise")
    snoise.inputs["Scale"].default_value = 3.0
    snoise.inputs["Detail"].default_value = 2.0
    nt.links.new(mapping.outputs[0], snoise.inputs["Vector"])
    streaks = _n(nt, "ShaderNodeMapRange")
    streaks.inputs["From Min"].default_value = 0.48
    streaks.inputs["From Max"].default_value = 0.72
    nt.links.new(snoise.outputs["Fac"], streaks.inputs["Value"])
    phase = _math(nt, "FRACT", _math(nt, "DIVIDE", _math(nt, "SUBTRACT", z, FLOOR_PHASE), FLOOR_PERIOD))
    band = _n(nt, "ShaderNodeMapRange")
    band.inputs["From Min"].default_value = 0.35
    band.inputs["From Max"].default_value = 0.97
    nt.links.new(phase, band.inputs["Value"])
    ledge = _math(nt, "SUBTRACT", 1.0, ao_long.outputs["AO"], clamp=True)
    zone = _math(nt, "MAXIMUM", _math(nt, "MULTIPLY", band.outputs[0], 0.8), _math(nt, "MULTIPLY", ledge, 1.6), clamp=True)
    streak = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", streaks.outputs[0], zone), side, clamp=True)
    # B base dirt: splash-back up to ~1.4 m on walls, broken by the grime noise
    base = _n(nt, "ShaderNodeMapRange")
    base.inputs["From Min"].default_value = 1.5
    base.inputs["From Max"].default_value = 0.1
    nt.links.new(z, base.inputs["Value"])
    dirt = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", base.outputs[0], side), _math(nt, "ADD", _math(nt, "MULTIPLY", noise.outputs["Fac"], 0.8), 0.4), clamp=True)
    comb = _n(nt, "ShaderNodeCombineColor")
    nt.links.new(grime, comb.inputs[0])
    nt.links.new(streak, comb.inputs[1])
    nt.links.new(dirt, comb.inputs[2])
    nt.links.new(comb.outputs[0], emit.inputs["Color"])
    return mat


def _ao_material(img) -> bpy.types.Material:
    """SLICE5 alpha: localised ambient occlusion (1 open, 0 occluded), so window and door reveals, the
    eave soffits, the undersides of cornices and the wall feet darken while big open faces stay white (earlier
    rounds: wide AO greyed the lime-wash). AO at 0.7 m; AO >= 0.85 maps to 1 (open), floor 0.3."""
    mat = bpy.data.materials.new("_PI_DecorAOBake")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = _n(nt, "ShaderNodeOutputMaterial")
    emit = _n(nt, "ShaderNodeEmission")
    nt.links.new(emit.outputs[0], out.inputs["Surface"])
    tex = _n(nt, "ShaderNodeTexImage")
    tex.image = img
    nt.nodes.active = tex
    ao = _n(nt, "ShaderNodeAmbientOcclusion", samples=24)
    ao.inputs["Distance"].default_value = 0.7
    open_ = _math(nt, "DIVIDE", _math(nt, "SUBTRACT", ao.outputs["AO"], 0.15), 0.7, clamp=True)   # AO >= 0.85 reads open
    curve = _math(nt, "POWER", open_, 1.3)
    lifted = _math(nt, "ADD", _math(nt, "MULTIPLY", curve, 0.7), 0.3, clamp=True)
    nt.links.new(lifted, emit.inputs["Color"])
    return mat


def _bake_pass(ob, img, mat) -> list:
    """EMIT-bake `mat` on UVMap2 of `ob` (other meshes hidden) into `img`; returns its pixels."""
    me = ob.data
    old_mats = [m for m in me.materials]
    old_idx = [p.material_index for p in me.polygons]
    me.materials.clear()
    me.materials.append(mat)
    uv_active = me.uv_layers.active.name
    me.uv_layers.active = me.uv_layers["UVMap2"]
    hidden = [o for o in bpy.data.objects if o.type == "MESH" and o is not ob and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    try:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        bpy.context.scene.render.bake.margin = 4
        bpy.context.scene.render.bake.target = "IMAGE_TEXTURES"
        bpy.ops.object.bake(type="EMIT")
    finally:
        for o in hidden:
            o.hide_render = False
        me.materials.clear()
        for m in old_mats:
            me.materials.append(m)
        me.polygons.foreach_set("material_index", old_idx)
        me.uv_layers.active = me.uv_layers[uv_active]
        me.uv_layers[uv_active].active_render = True
        bpy.data.materials.remove(mat)
    return list(img.pixels)


def bake_decor(ob, path: str, size: int = 2048, samples: int = 16) -> str:
    """Bake the decor masks of `ob` (needs UVMap2) into a PNG at `path` (alone: other meshes hidden)."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    img = bpy.data.images.new("T_Decor", size, size, alpha=True, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"
    img.alpha_mode = "CHANNEL_PACKED"   # A is data, not coverage: no premultiply on save
    px = _bake_pass(ob, img, _bake_material(img))
    aimg = bpy.data.images.new("T_DecorAO", size, size, alpha=False, float_buffer=False)
    aimg.colorspace_settings.name = "Non-Color"
    apx = _bake_pass(ob, aimg, _ao_material(aimg))
    bpy.data.images.remove(aimg)
    px[3::4] = apx[0::4]   # SLICE5: A = localised AO (gutter pixels outside the islands bake as 0: harmless)
    # keep the reserved corner clean (LOD1 samples it): no decor, no AO
    c0 = int(size * UV1_SCALE) + 2
    for y in range(c0, size):
        for x in range(c0, size):
            i = (y * size + x) * 4
            px[i:i + 4] = (0.0, 0.0, 0.0, 1.0)
    img.pixels = px
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return path


def lod1_uv1(ob) -> None:
    """LOD1 UV1: every corner on the atlas's clean corner (no decor; COLOR_0 still carries paint and AO)."""
    me = ob.data
    uv = me.uv_layers.get("UVMap2") or me.uv_layers.new(name="UVMap2")
    uv.data.foreach_set("uv", list(CLEAN_UV) * len(uv.data))
    me.uv_layers.active = me.uv_layers["UVMap"]
    me.uv_layers["UVMap"].active_render = True


def _hash_noise(x, y, s):
    """Smooth value noise in [0, 1] (no bpy/mathutils noise: deterministic everywhere)."""
    def h(i, j):
        n = math.sin(i * 127.1 + j * 311.7 + s * 74.7) * 43758.5453
        return n - math.floor(n)
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    u, v = xf * xf * (3 - 2 * xf), yf * yf * (3 - 2 * yf)
    a, b, c, d = h(xi, yi), h(xi + 1, yi), h(xi, yi + 1), h(xi + 1, yi + 1)
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v


def paint(ob, seed: int = 11) -> None:
    """COLOR_0: move the baked AO (rgb) to alpha and write a low-frequency paint tint into rgb: the lime-wash
    drifts between slightly warmer and cooler cream over ~12 m, tiles between fresh and weathered over ~6 m."""
    me = ob.data
    ca = me.color_attributes.get("Col")
    if ca is None:
        ca = me.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
        for d in ca.data:
            d.color = (1.0, 1.0, 1.0, 1.0)
    names = [m.name if m else "" for m in me.materials]
    loops = me.loops
    verts = me.vertices
    out = [0.0] * (len(ca.data) * 4)
    srgb = [0.0] * (len(ca.data) * 4)
    ca.data.foreach_get("color_srgb", srgb)
    for p in me.polygons:
        mat = names[p.material_index] if names else ""
        for li in p.loop_indices:
            co = verts[loops[li].vertex_index].co
            ao = srgb[li * 4]
            if "Roof" in mat:
                n = _hash_noise(co.x / 6.0, co.y / 6.0, seed) * 0.6 + _hash_noise(co.x / 1.7, co.y / 1.7, seed + 3) * 0.4
                rgb = (0.86 + 0.2 * n, 0.84 + 0.2 * n, 0.82 + 0.22 * n)
            elif "Glass" in mat:
                rgb = (0.0, 0.0, 0.0)   # glass flag: SHD_HeroLit draws black-painted faces of the trim material as glass
            elif "Lawn" in mat:
                rgb = (1.0, 1.0, 1.0)
            else:
                n = _hash_noise(co.x / 12.0, co.y / 12.0 + co.z / 20.0, seed)
                m = _hash_noise(co.x / 4.0, co.z / 3.0, seed + 7)
                k = 0.93 + 0.07 * m
                rgb = (k * (0.99 + 0.02 * n), k * (0.97 + 0.03 * n), k * (0.93 + 0.06 * (1 - n)))
            out[li * 4:li * 4 + 4] = (*rgb, ao)
    ca.data.foreach_set("color_srgb", out)
