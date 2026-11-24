"""Isso wade carts and small props, modelled in Blender (citylib/carts.py has the names, sizes and budgets).

Methods (research section 3, agent: no "lego blocks"):
- Every part is a Blender primitive (cube, cylinder, grid, circle, curve) scaled to the size read off the
  reference photos, with Bevel (angle-limited, 2 segments) + Weighted Normal on hard parts. Turned parts (gas
  cylinder, wok, bowls, tyres) are a short radius profile on a Screw modifier; frame tubes are curves with a
  bevel radius. Panel insets are bmesh inset / extrude operations on the primitive's faces.
- Repeats are Geometry Nodes (PI_GN_CartSpokes, PI_GN_Corrugated, PI_GN_VadaiStacks): wheel spokes laced
  to alternate hub flanges, corrugated canopy sheets (sine profile, flipped underside), stacked vadai with
  seeded heights.
- Each part carries a procedural "look" material (painted steel with Bevel-node edge wear, cavity rust and
  grime; rusty or white corrugated tin; galvanised and stainless steel; timber; rubber; plastics; stylised
  fried crabs and prawn vadai painted from food_01's layout, never traced). Parts are unwrapped (Smart UV
  Project), scaled to one texel density (food tops x2, LED strips x4) and packed together into one 2048
  atlas; Cycles then bakes base colour, roughness, metallic, emission and ambient occlusion (with a ground
  plane) into T_CartIssoWade_*. After the bake every face uses MAT_Cart_IssoWade_A.
- Vertex colour "Col" is white with alpha 1 (SHD_HeroLit's vertex AO stays neutral; the AO is in the atlas).
"""
from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import carts as C

ATLAS_PX = 2048
TEXEL_BIAS = {"food": 3.0, "led": 4.0}        # extra UV area factor per look group (texel density x sqrt)
LOOKS: dict[str, dict] = {}                   # look name -> {"mat", "sockets": {pass: socket}, "out", "group"}


# ----------------------------------------------------------------------------------------------- looks
def _n(nt, kind, loc=None, **props):
    node = nt.nodes.new(kind)
    for k, v in props.items():
        setattr(node, k, v)
    return node


def _val(nt, v):
    node = nt.nodes.new("ShaderNodeValue")
    node.outputs[0].default_value = v
    return node.outputs[0]


def _rgb(nt, hexstr):
    h = hexstr.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    node = nt.nodes.new("ShaderNodeRGB")
    node.outputs[0].default_value = (*lin, 1.0)
    return node.outputs[0]


def _mix(nt, fac, a, b):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = "RGBA"
    m.clamp_factor = True
    _link(nt, fac, m.inputs[0])
    _link(nt, a, m.inputs[6])
    _link(nt, b, m.inputs[7])
    return m.outputs[2]


def _mixf(nt, fac, a, b):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = "FLOAT"
    m.clamp_factor = True
    _link(nt, fac, m.inputs[0])
    _link(nt, a, m.inputs[2])
    _link(nt, b, m.inputs[3])
    return m.outputs[0]


def _link(nt, a, b):
    if isinstance(a, (int, float)):
        b.default_value = a
    elif isinstance(a, tuple):
        b.default_value = a
    else:
        nt.links.new(a, b)


def _math(nt, op, a, b=None, c=None, clamp=False):
    m = nt.nodes.new("ShaderNodeMath")
    m.operation = op
    m.use_clamp = clamp
    _link(nt, a, m.inputs[0])
    if b is not None:
        _link(nt, b, m.inputs[1])
    if c is not None:
        _link(nt, c, m.inputs[2])
    return m.outputs[0]


def _ramp(nt, x, lo, hi):
    """smoothstep-ish 0..1 of x between lo and hi"""
    m = nt.nodes.new("ShaderNodeMapRange")
    m.interpolation_type = "SMOOTHSTEP"
    _link(nt, x, m.inputs["Value"])
    m.inputs["From Min"].default_value = lo
    m.inputs["From Max"].default_value = hi
    return m.outputs["Result"]


def _coord(nt):
    return _n(nt, "ShaderNodeTexCoord").outputs["Object"]


def _noise(nt, scale, detail=4.0, rough=0.55, vec=None, dims="3D", w=0.0, stretch=None):
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.noise_dimensions = dims
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = detail
    tex.inputs["Roughness"].default_value = rough
    v = vec or _coord(nt)
    if stretch:
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = stretch
        nt.links.new(v, mp.inputs["Vector"])
        v = mp.outputs[0]
    nt.links.new(v, tex.inputs["Vector"])
    return tex.outputs["Fac"]


def _edge(nt, radius=0.012, lo=0.02, hi=0.12):
    """Convex / concave edge mask from the Bevel node (rounded normal vs true normal)."""
    bev = nt.nodes.new("ShaderNodeBevel")
    bev.samples = 8
    bev.inputs["Radius"].default_value = radius
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    nt.links.new(bev.outputs[0], dot.inputs[0])
    nt.links.new(geo.outputs["Normal"], dot.inputs[1])
    return _ramp(nt, _math(nt, "SUBTRACT", 1.0, dot.outputs["Value"]), lo, hi)


def _ao(nt, dist=0.2):
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao.samples = 8
    ao.inputs["Distance"].default_value = dist
    return ao.outputs["AO"]


def _zpos(nt):
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(_n(nt, "ShaderNodeNewGeometry").outputs["Position"], sep.inputs[0])
    return sep


def look_painted(nt, paint, bare="#5A5650", rust="#7A3F1E", wear=0.55, rust_amt=0.6, rough=0.42):
    """Painted steel: chipped convex edges show bare steel, rust creeps from cavities and the lower body."""
    edge = _edge(nt)
    n1 = _noise(nt, 22.0, 6.0, 0.6)
    chip = _ramp(nt, _math(nt, "ADD", _math(nt, "MULTIPLY", edge, 1.4), _math(nt, "MULTIPLY", n1, wear)), 0.62, 0.72)
    cav = _math(nt, "SUBTRACT", 1.0, _ao(nt, 0.12))
    z = _zpos(nt).outputs["Z"]
    low = _ramp(nt, z, 0.75, 0.25)
    n2 = _noise(nt, 9.0, 5.0, 0.65)
    rmask = _ramp(nt, _math(nt, "ADD", _math(nt, "MULTIPLY", cav, 1.2),
                            _math(nt, "MULTIPLY", _math(nt, "ADD", low, n2), rust_amt * 0.6)), 0.55, 0.85)
    mott = _noise(nt, 4.0, 3.0, 0.5)
    base = _mix(nt, _math(nt, "MULTIPLY", mott, 0.25), _rgb(nt, paint), _rgb(nt, "#202020"))
    col = _mix(nt, chip, base, _rgb(nt, bare))
    col = _mix(nt, _math(nt, "MULTIPLY", rmask, 0.85), col, _rgb(nt, rust))
    streak = _noise(nt, 6.0, 4.0, 0.6, stretch=(9.0, 9.0, 0.6))
    col = _mix(nt, _math(nt, "MULTIPLY", _ramp(nt, streak, 0.55, 0.8), 0.25), col, _rgb(nt, "#3A3128"))
    r = _mixf(nt, _math(nt, "MAXIMUM", chip, rmask), rough, 0.75)
    m = _mixf(nt, chip, 0.0, 0.6)
    return col, r, m


def look_tin(nt, rusty=True):
    """Corrugated tin: rusty galvanised (cart_03) or white-painted with grime and edge rust (cart_01/02)."""
    n1 = _noise(nt, 3.0, 6.0, 0.62)
    n2 = _noise(nt, 14.0, 8.0, 0.7)
    streak = _noise(nt, 5.0, 5.0, 0.6, stretch=(1.0, 14.0, 1.0))   # runs down the slope (y)
    cav = _math(nt, "SUBTRACT", 1.0, _ao(nt, 0.05))
    edge = _edge(nt, 0.01)
    if rusty:
        rm = _ramp(nt, _math(nt, "ADD", _math(nt, "ADD", n1, _math(nt, "MULTIPLY", n2, 0.5)),
                             _math(nt, "MULTIPLY", streak, 0.4)), 0.5, 0.9)
        col = _mix(nt, rm, _rgb(nt, "#8C8A82"), _rgb(nt, "#8A4A22"))
        col = _mix(nt, _ramp(nt, n2, 0.45, 0.75), col, _rgb(nt, "#5E2E15"))
        col = _mix(nt, _math(nt, "MULTIPLY", cav, 1.5), col, _rgb(nt, "#3D2214"))
        r = _mixf(nt, rm, 0.45, 0.85)
        m = _mixf(nt, rm, 0.7, 0.05)
    else:
        rm = _ramp(nt, _math(nt, "ADD", _math(nt, "MULTIPLY", edge, 1.2), _math(nt, "MULTIPLY", n2, 0.5)), 0.7, 0.9)
        col = _mix(nt, _math(nt, "MULTIPLY", _ramp(nt, streak, 0.5, 0.8), 0.35), _rgb(nt, "#ECEBE4"), _rgb(nt, "#A39C8E"))
        col = _mix(nt, _math(nt, "MULTIPLY", cav, 0.8), col, _rgb(nt, "#8D857A"))
        col = _mix(nt, rm, col, _rgb(nt, "#8A4A22"))
        r = _mixf(nt, rm, 0.38, 0.8)
        m = _val(nt, 0.0)
    return col, r, m


def look_metal(nt, colour, rough, metal=1.0, dirt=0.3):
    n = _noise(nt, 18.0, 5.0, 0.6)
    cav = _math(nt, "SUBTRACT", 1.0, _ao(nt, 0.06))
    col = _mix(nt, _math(nt, "MULTIPLY", _math(nt, "ADD", cav, _math(nt, "MULTIPLY", n, 0.4)), dirt),
               _rgb(nt, colour), _rgb(nt, "#4A4238"))
    r = _math(nt, "ADD", rough, _math(nt, "MULTIPLY", n, 0.15))
    return col, r, _val(nt, metal)


def look_wood(nt, colour="#8A5B36"):
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "Y"
    wave.inputs["Scale"].default_value = 6.0
    wave.inputs["Distortion"].default_value = 6.0
    wave.inputs["Detail"].default_value = 4.0
    nt.links.new(_coord(nt), wave.inputs["Vector"])
    n = _noise(nt, 30.0, 4.0, 0.6)
    col = _mix(nt, _math(nt, "MULTIPLY", wave.outputs["Fac"], 0.45), _rgb(nt, colour), _rgb(nt, "#4E3220"))
    col = _mix(nt, _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", 1.0, _ao(nt, 0.08)), 1.2), col, _rgb(nt, "#2E2018"))
    col = _mix(nt, _math(nt, "MULTIPLY", n, 0.2), col, _rgb(nt, "#B98A5A"))
    return col, _val(nt, 0.7), _val(nt, 0.0)


def look_plain(nt, colour, rough, grime=0.25):
    n = _noise(nt, 8.0, 4.0, 0.55)
    cav = _math(nt, "SUBTRACT", 1.0, _ao(nt, 0.08))
    col = _mix(nt, _math(nt, "MULTIPLY", _math(nt, "ADD", cav, _math(nt, "MULTIPLY", n, 0.5)), grime),
               _rgb(nt, colour), _rgb(nt, "#3A342C"))
    return col, _val(nt, rough), _val(nt, 0.0)


def _cell(nt, size, seed_w=0.0):
    """Voronoi cells of about `size` metres on the object's xy: (distance F1, cell-local xy vector)."""
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.voronoi_dimensions = "2D"
    vor.inputs["Scale"].default_value = 1.0 / size
    vor.inputs["Randomness"].default_value = 0.45
    co = _coord(nt)
    nt.links.new(co, vor.inputs["Vector"])
    # Voronoi's Position output is in the input (object) space, so subtract first, then scale to cell units
    sub = nt.nodes.new("ShaderNodeVectorMath")
    sub.operation = "SUBTRACT"
    nt.links.new(co, sub.inputs[0])
    nt.links.new(vor.outputs["Position"], sub.inputs[1])
    sc = nt.nodes.new("ShaderNodeVectorMath")
    sc.operation = "SCALE"
    sc.inputs["Scale"].default_value = 1.0 / size
    nt.links.new(sub.outputs[0], sc.inputs[0])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(sc.outputs[0], sep.inputs[0])
    return vor.outputs["Distance"], sep.outputs["X"], sep.outputs["Y"], vor.outputs["Color"]


def look_prawn_vadai(nt):
    """Top view of prawn vadai (food_01, stylised): round orange lentil patties, each with two curled prawns."""
    d, x, y, rnd = _cell(nt, 0.075)
    patty = _ramp(nt, d, 0.6, 0.52)              # food_01: patties packed edge to edge
    crisp = _noise(nt, 140.0, 6.0, 0.7)
    col = _mix(nt, _ramp(nt, crisp, 0.45, 0.7), _rgb(nt, "#D8662A"), _rgb(nt, "#9A3A14"))
    col = _mix(nt, _ramp(nt, d, 0.25, 0.42), col, _rgb(nt, "#B4471A"))
    # two prawns: thin ellipses either side of the cell's centre line, segmented
    def prawn(off):
        yy = _math(nt, "SUBTRACT", y, off)
        e = _math(nt, "ADD", _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", x, x), 1.0),
                  _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", yy, yy), 18.0))
        return _ramp(nt, e, 0.11, 0.07)
    pr = _math(nt, "MAXIMUM", prawn(0.09), prawn(-0.09))
    seg = _ramp(nt, _math(nt, "SINE", _math(nt, "MULTIPLY", x, 38.0)), 0.3, 0.9)
    pcol = _mix(nt, _math(nt, "MULTIPLY", seg, 0.6), _rgb(nt, "#F09A5C"), _rgb(nt, "#FBD3A8"))
    col = _mix(nt, pr, col, pcol)
    col = _mix(nt, _math(nt, "SUBTRACT", 1.0, patty), col, _rgb(nt, "#7E3816"))   # fried crumbs between
    return col, _val(nt, 0.4), _val(nt, 0.0)


def look_crabs(nt):
    """Top view of fried crabs on vadai (food_01, stylised): cream shells, orange rims, splayed pale legs."""
    d, x, y, rnd = _cell(nt, 0.10)
    ang = nt.nodes.new("ShaderNodeMath")
    ang.operation = "ARCTAN2"
    nt.links.new(y, ang.inputs[0])
    nt.links.new(x, ang.inputs[1])
    legs = _ramp(nt, _math(nt, "SINE", _math(nt, "MULTIPLY", ang.outputs[0], 10.0)), 0.55, 0.85)
    ring = _math(nt, "MULTIPLY", _ramp(nt, d, 0.18, 0.26), _ramp(nt, d, 0.52, 0.44))
    shell = _ramp(nt, _math(nt, "ADD", _math(nt, "MULTIPLY", x, x), _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", y, y), 2.2)), 0.07, 0.04)
    crisp = _noise(nt, 120.0, 6.0, 0.7)
    col = _mix(nt, _ramp(nt, crisp, 0.4, 0.7), _rgb(nt, "#C9581F"), _rgb(nt, "#8E3412"))   # vadai bed
    col = _mix(nt, _math(nt, "MULTIPLY", legs, ring), col, _rgb(nt, "#F1C7A0"))
    col = _mix(nt, _ramp(nt, d, 0.30, 0.22), col, _rgb(nt, "#E58A4C"))
    col = _mix(nt, shell, col, _rgb(nt, "#F4E7D2"))
    col = _mix(nt, _math(nt, "MULTIPLY", _ramp(nt, crisp, 0.55, 0.8), shell), col, _rgb(nt, "#D99A66"))
    return col, _val(nt, 0.4), _val(nt, 0.0)


def look_vadai_stack(nt):
    """Stacked vadai: crisp brown-orange layers on the sides, a patty with a prawn on top."""
    sep = _zpos(nt)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    nz = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], nz.inputs[0])
    top = _ramp(nt, nz.outputs["Z"], 0.5, 0.8)
    layers = _ramp(nt, _math(nt, "SINE", _math(nt, "MULTIPLY", sep.outputs["Z"], 2 * math.pi / 0.016)), 0.2, 0.9)
    crisp = _noise(nt, 120.0, 6.0, 0.7)
    side = _mix(nt, _math(nt, "MULTIPLY", layers, 0.75), _rgb(nt, "#C8601F"), _rgb(nt, "#6E2A0E"))
    side = _mix(nt, _math(nt, "MULTIPLY", _ramp(nt, crisp, 0.5, 0.75), 0.6), side, _rgb(nt, "#E08A3E"))
    d, x, y, _ = _cell(nt, 0.09)
    pr = _ramp(nt, _math(nt, "ADD", _math(nt, "MULTIPLY", x, x), _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", y, y), 14.0)), 0.12, 0.08)
    tcol = _mix(nt, _ramp(nt, crisp, 0.45, 0.7), _rgb(nt, "#D8662A"), _rgb(nt, "#9A3A14"))
    tcol = _mix(nt, pr, tcol, _rgb(nt, "#F3A468"))
    return _mix(nt, top, side, tcol), _val(nt, 0.45), _val(nt, 0.0)


def look_emissive(nt, colour, albedo="#F2F4F5"):
    return _rgb(nt, albedo), _val(nt, 0.3), _val(nt, 0.0), _rgb(nt, colour)


# --- modelled food (round 2): patterns in each instance's own frame ("lp", stored by PI_GN_FoodScatter) ------
def _lp(nt):
    """Instance-local position (metres) of a scattered food piece: (x, y, z, length of xy)."""
    at = nt.nodes.new("ShaderNodeAttribute")
    at.attribute_name = "lp"
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(at.outputs["Vector"], sep.inputs[0])
    ln = nt.nodes.new("ShaderNodeVectorMath")
    ln.operation = "LENGTH"
    cz = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sep.outputs["X"], cz.inputs["X"])
    nt.links.new(sep.outputs["Y"], cz.inputs["Y"])
    nt.links.new(cz.outputs[0], ln.inputs[0])
    return sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"], ln.outputs["Value"]


def _normal_z(nt):
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(_n(nt, "ShaderNodeNewGeometry").outputs["Normal"], sep.inputs[0])
    return sep.outputs["Z"]


def look_patty(nt):
    """Prawn vadai / crab bed patty (food_01): deep orange lentil dough, crisp darker bumps, browned rim."""
    crisp = _noise(nt, 160.0, 6.0, 0.72)
    blot = _noise(nt, 40.0, 3.0, 0.5)
    col = _mix(nt, _ramp(nt, crisp, 0.42, 0.72), _rgb(nt, "#E8722B"), _rgb(nt, "#A2400F"))
    col = _mix(nt, _math(nt, "MULTIPLY", _ramp(nt, blot, 0.55, 0.75), 0.5), col, _rgb(nt, "#F39A45"))
    side = _ramp(nt, _normal_z(nt), 0.75, 0.35)
    col = _mix(nt, _math(nt, "MULTIPLY", side, 0.55), col, _rgb(nt, "#8A3510"))
    return col, _val(nt, 0.68), _val(nt, 0.0)


def look_prawn_pair(nt):
    """Two whole fried prawns side by side along x on top of a patty (food_01): pink-orange shell segments with
    pale joints, darker head end, fanned tail; dough shows between them."""
    x, y, z, _ = _lp(nt)
    # bands at ~4 texels per period and a dough gap down the middle: finer detail is lost at the atlas density
    seg = _ramp(nt, _math(nt, "SINE", _math(nt, "MULTIPLY", x, 2 * math.pi / 0.016)), 0.1, 0.7)
    lane = _ramp(nt, _math(nt, "ABSOLUTE", _math(nt, "SUBTRACT", _math(nt, "ABSOLUTE", y), 0.0135)), 0.0115, 0.008)
    body = _mix(nt, _math(nt, "MULTIPLY", seg, 0.85), _rgb(nt, "#FBE0C8"), _rgb(nt, "#EE7A3E"))
    head = _ramp(nt, x, -0.022, -0.036)
    body = _mix(nt, _math(nt, "MULTIPLY", head, 0.8), body, _rgb(nt, "#D2502A"))
    tail = _ramp(nt, x, 0.028, 0.038)
    body = _mix(nt, _math(nt, "MULTIPLY", tail, 0.7), body, _rgb(nt, "#E8582A"))
    dough = _mix(nt, _ramp(nt, _noise(nt, 150.0, 5.0, 0.7), 0.45, 0.7), _rgb(nt, "#E06A26"), _rgb(nt, "#9E3E10"))
    return _mix(nt, lane, dough, body), _val(nt, 0.5), _val(nt, 0.0)


def look_crab_shell(nt):
    """Fried crab carapace (food_01): cream-white middle, orange-red rim and spots, dark grooves."""
    x, y, z, r = _lp(nt)
    rim = _ramp(nt, _math(nt, "ADD", _math(nt, "MULTIPLY", _math(nt, "ABSOLUTE", x), 1.0),
                          _math(nt, "MULTIPLY", _math(nt, "ABSOLUTE", y), 1.4)), 0.03, 0.05)
    spots = _ramp(nt, _noise(nt, 90.0, 3.0, 0.5), 0.6, 0.72)
    col = _mix(nt, _math(nt, "MULTIPLY", spots, 0.8), _rgb(nt, "#F4E2C8"), _rgb(nt, "#E8864A"))
    rim = _ramp(nt, _math(nt, "ADD", _math(nt, "ABSOLUTE", x), _math(nt, "MULTIPLY", _math(nt, "ABSOLUTE", y), 1.4)), 0.022, 0.04)
    col = _mix(nt, rim, col, _rgb(nt, "#DA5A24"))
    groove = _ramp(nt, _math(nt, "ABSOLUTE", x), 0.003, 0.0)
    col = _mix(nt, _math(nt, "MULTIPLY", groove, _ramp(nt, y, 0.01, -0.01)), col, _rgb(nt, "#B4562A"))
    return col, _val(nt, 0.45), _val(nt, 0.0)


def look_crab_leg(nt):
    """Crab legs and claws: pale cream with orange joints, dark claw tips."""
    x, y, z, r = _lp(nt)
    joint = _ramp(nt, _math(nt, "SINE", _math(nt, "MULTIPLY", r, 2 * math.pi / 0.03)), 0.6, 0.95)
    col = _mix(nt, _math(nt, "MULTIPLY", joint, 0.9), _rgb(nt, "#F1D6B6"), _rgb(nt, "#DE6A2E"))
    tip = _ramp(nt, r, 0.095, 0.115)
    col = _mix(nt, tip, col, _rgb(nt, "#7A2A12"))
    return col, _val(nt, 0.35), _val(nt, 0.0)


def look_lentil_stack(nt):
    """Paripu (lentil) vadai stacks (cart_01 corners, food_01 edge): golden-brown discs, darker crisp layer
    lines on the sides, lentils and curry-leaf flecks on the top."""
    sep = _zpos(nt)
    top = _ramp(nt, _normal_z(nt), 0.5, 0.8)
    layers = _ramp(nt, _math(nt, "SINE", _math(nt, "MULTIPLY", sep.outputs["Z"], 2 * math.pi / 0.014)), 0.3, 0.95)
    crisp = _noise(nt, 130.0, 6.0, 0.7)
    side = _mix(nt, _math(nt, "MULTIPLY", layers, 0.85), _rgb(nt, "#C49558"), _rgb(nt, "#6A3E18"))
    side = _mix(nt, _math(nt, "MULTIPLY", _ramp(nt, crisp, 0.5, 0.75), 0.5), side, _rgb(nt, "#DDB879"))
    tcol = _mix(nt, _ramp(nt, crisp, 0.4, 0.7), _rgb(nt, "#D4A464"), _rgb(nt, "#93592A"))
    fleck = _ramp(nt, _noise(nt, 260.0, 2.0, 0.4), 0.68, 0.74)
    tcol = _mix(nt, _math(nt, "MULTIPLY", fleck, 0.8), tcol, _rgb(nt, "#3E3014"))
    return _mix(nt, top, side, tcol), _val(nt, 0.7), _val(nt, 0.0)


def look_jar(nt, content):
    """Clear plastic sweet jar seen with its contents: content colour, a pale rim band and highlight streak."""
    z = _zpos(nt).outputs["Z"]
    n = _noise(nt, 60.0, 4.0, 0.6)
    col = _mix(nt, _math(nt, "MULTIPLY", n, 0.35), _rgb(nt, content), _rgb(nt, "#2E2416"))
    streak = _ramp(nt, _noise(nt, 4.0, 2.0, 0.4, stretch=(30.0, 30.0, 1.0)), 0.62, 0.7)
    col = _mix(nt, _math(nt, "MULTIPLY", streak, 0.5), col, _rgb(nt, "#F4F6F2"))
    return col, _val(nt, 0.12), _val(nt, 0.0)


# --- LED light without lights: emission texels that stand in for the light the LED tubes throw (round 2) ----
LED_SPILL = 0.42          # emission = albedo x this x mask (linear) at the brightest; x _EmissionColor 2.2 in Unity
CANOPY_LEDS_Y = (-0.36, -0.02)   # cart B canopy tubes (cart frame y), along x within |x| < 0.75
CANOPY_A_LED_Y = -0.18            # cart A: one batten under the rusty sheet, along x within |x| < 0.6


def _scale_col(nt, col, k):
    s = nt.nodes.new("ShaderNodeVectorMath")
    s.operation = "SCALE"
    _link(nt, col, s.inputs[0])
    _link(nt, k, s.inputs["Scale"])
    return s.outputs[0]


def _canopy_spill(nt, leds=CANOPY_LEDS_Y, half=0.75):
    """Underside of a canopy near its LED tubes (cart_01/02: the sheet glows round the tubes)."""
    co = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(_coord(nt), co.inputs[0])
    under = _ramp(nt, _normal_z(nt), -0.3, -0.7)
    along = _ramp(nt, _math(nt, "ABSOLUTE", co.outputs["X"]), half + 0.35, half - 0.2)
    near = None
    for yy in leds:
        d = _ramp(nt, _math(nt, "ABSOLUTE", _math(nt, "SUBTRACT", co.outputs["Y"], yy)), 0.42, 0.0)
        near = d if near is None else _math(nt, "MAXIMUM", near, d)
    return _math(nt, "MULTIPLY", under, _math(nt, "MULTIPLY", along, near))


def _display_spill(nt):
    """Cart B counter inside the glass box (lit by the box's own LED strips): top faces, x within the box."""
    co = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(_coord(nt), co.inputs[0])
    up = _ramp(nt, _normal_z(nt), 0.5, 0.9)
    inside = _math(nt, "MULTIPLY", _ramp(nt, co.outputs["X"], -0.9, -0.8),
                   _math(nt, "MULTIPLY", _ramp(nt, co.outputs["X"], 0.46, 0.36),
                         _ramp(nt, _math(nt, "ABSOLUTE", co.outputs["Y"]), 0.36, 0.28)))
    return _math(nt, "MULTIPLY", up, inside)


def _lit(builder, k=LED_SPILL, mask=None):
    """Wrap a look so its emission is its own albedo x k (x mask): surfaces lit by the cart's LED tubes."""
    def build(nt):
        col, rough, metal = builder(nt)[:3]
        e = _scale_col(nt, col, k if mask is None else _math(nt, "MULTIPLY", mask(nt), k))
        return col, rough, metal, e
    return build


LOOK_DEFS = {
    # name: (builder, group)
    "paint_green": (lambda nt: look_painted(nt, "#1E9B3C"), "body"),
    "paint_maroon": (lambda nt: look_painted(nt, "#5B1F27", rust_amt=0.4), "body"),
    "tin_rust": (lambda nt: look_tin(nt, True), "body"),
    "tin_white": (lambda nt: look_tin(nt, False), "body"),
    "galv": (lambda nt: look_metal(nt, "#B9BDBB", 0.42, 0.85, 0.45), "body"),
    "steel": (lambda nt: look_metal(nt, "#CED2D4", 0.22, 1.0, 0.25), "body"),
    "iron": (lambda nt: look_metal(nt, "#2C2A28", 0.5, 0.7, 0.2), "body"),
    "wood": (look_wood, "body"),
    "rubber": (lambda nt: look_plain(nt, "#1E1D1C", 0.85, 0.3), "body"),
    "plastic_white": (lambda nt: look_plain(nt, "#E6E3D8", 0.45, 0.35), "body"),
    "plastic_blue": (lambda nt: look_plain(nt, "#2D6FD2", 0.35, 0.15), "body"),
    "stool_red": (lambda nt: look_plain(nt, "#C7352C", 0.42, 0.3), "body"),
    "cyl_red": (lambda nt: look_painted(nt, "#C42620", wear=0.45, rust_amt=0.35, rough=0.35), "body"),
    "cyl_blue": (lambda nt: look_painted(nt, "#2C5CB6", wear=0.45, rust_amt=0.35, rough=0.35), "body"),
    "glass": (lambda nt: look_metal(nt, "#9DB3B6", 0.05, 0.0, 0.1), "body"),
    "prawn_vadai": (look_prawn_vadai, "food"),
    "crabs": (look_crabs, "food"),
    "vadai_tray": (look_prawn_vadai, "body"),     # shelf heaps: same look at body texel density
    "vadai": (look_vadai_stack, "food"),
    # round 2: modelled food (instanced pieces), LED-lit variants for cart B's display and canopy
    "patty": (look_patty, "food"),
    "prawn_pair": (look_prawn_pair, "food"),
    "crab_shell": (look_crab_shell, "food"),
    "crab_leg": (look_crab_leg, "food"),
    "lentil": (look_lentil_stack, "food"),
    "patty_lit": (_lit(look_patty), "food"),
    "prawn_pair_lit": (_lit(look_prawn_pair), "food"),
    "crab_shell_lit": (_lit(look_crab_shell), "food"),
    "crab_leg_lit": (_lit(look_crab_leg), "food"),
    "lentil_lit": (_lit(look_lentil_stack), "food"),
    "steel_tray_lit": (_lit(lambda nt: look_metal(nt, "#CED2D4", 0.25, 1.0, 0.3), 0.3), "body"),
    "tin_white_lit": (_lit(lambda nt: look_tin(nt, False), 0.55, _canopy_spill), "body"),
    "tin_rust_lit": (_lit(lambda nt: look_tin(nt, True), 0.6,
                          lambda nt: _canopy_spill(nt, (CANOPY_A_LED_Y,), 0.6)), "body"),
    "steel_counter_lit": (_lit(lambda nt: look_metal(nt, "#CED2D4", 0.22, 1.0, 0.25), 0.35, _display_spill), "body"),
    "glass_lit": (_lit(lambda nt: look_metal(nt, "#A9C2C4", 0.05, 0.0, 0.1), 0.3), "body"),
    "jar_chilli": (lambda nt: look_jar(nt, "#B8321C"), "body"),
    "jar_onion": (lambda nt: look_jar(nt, "#D9B98A"), "body"),
    "led": (lambda nt: look_emissive(nt, "#F4F9FF", "#FFFFFF"), "led"),
    "bulb_red": (lambda nt: look_emissive(nt, "#FF3B30", "#FF6A5C"), "led"),
    "bulb_green": (lambda nt: look_emissive(nt, "#33E36B", "#7CF09E"), "led"),
    "bulb_blue": (lambda nt: look_emissive(nt, "#3F7BFF", "#86A9FF"), "led"),
    "bulb_amber": (lambda nt: look_emissive(nt, "#FFB238", "#FFD08A"), "led"),
}


def make_looks() -> None:
    for name, (builder, group) in LOOK_DEFS.items():
        mat = bpy.data.materials.get(f"LOOK_Cart_{name}") or bpy.data.materials.new(f"LOOK_Cart_{name}")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        res = builder(nt)
        col, rough, metal = res[:3]
        emit = res[3] if len(res) > 3 else _rgb(nt, "#000000")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        nt.links.new(col, bsdf.inputs["Base Color"])
        nt.links.new(rough, bsdf.inputs["Roughness"])
        nt.links.new(metal, bsdf.inputs["Metallic"])
        em = nt.nodes.new("ShaderNodeEmission")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        img = nt.nodes.new("ShaderNodeTexImage")
        img.name = "BAKE"
        LOOKS[name] = {"mat": mat, "group": group, "bsdf": bsdf, "emit_node": em, "out": out, "img": img,
                       "sockets": {"color": col, "rough": rough, "metal": metal, "emit": emit}}
        nt.links.new(bsdf.outputs[0], out.inputs["Surface"])


def set_pass(kind: str, image) -> None:
    """Route every look to the bake pass: 'color' / 'rough' / 'metal' / 'emit' as emission, 'ao' via the BSDF."""
    for lk in LOOKS.values():
        nt = lk["mat"].node_tree
        for l in list(lk["out"].inputs["Surface"].links):
            nt.links.remove(l)
        if kind in lk["sockets"]:
            nt.links.new(lk["sockets"][kind], lk["emit_node"].inputs["Color"])
            nt.links.new(lk["emit_node"].outputs[0], lk["out"].inputs["Surface"])
        else:
            nt.links.new(lk["bsdf"].outputs[0], lk["out"].inputs["Surface"])
        lk["img"].image = image
        nt.nodes.active = lk["img"]


# ------------------------------------------------------------------------------------------ geometry nodes
def _gn(name):
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")   # one group per use (own settings), Blender suffixes
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    ng.nodes.new("NodeGroupInput")
    return ng, ng.nodes.new("NodeGroupOutput")


def _gm(ng, op, a, b=None):
    m = ng.nodes.new("ShaderNodeMath")
    m.operation = op
    _link(ng, a, m.inputs[0])
    if b is not None:
        _link(ng, b, m.inputs[1])
    return m.outputs[0]


def gn_spokes(n=16, r_rim=0.29, r_hub=0.025, flange=0.032, wire=0.0035):
    """PI_GN_CartSpokes: n spokes from the rim to alternate hub flanges (wheel in xy, axle along z)."""
    ng, out = _gn("PI_GN_CartSpokes")
    circ = ng.nodes.new("GeometryNodeMeshCircle")
    circ.inputs["Vertices"].default_value = n
    circ.inputs["Radius"].default_value = r_rim
    length = math.hypot(r_rim - r_hub, flange)
    cyl = ng.nodes.new("GeometryNodeMeshCylinder")
    cyl.fill_type = "NONE"
    cyl.inputs["Vertices"].default_value = 3
    cyl.inputs["Radius"].default_value = wire
    cyl.inputs["Depth"].default_value = length
    tr = ng.nodes.new("GeometryNodeTransform")
    tr.inputs["Translation"].default_value = (0.0, 0.0, length / 2)
    ng.links.new(cyl.outputs["Mesh"], tr.inputs["Geometry"])
    idx = ng.nodes.new("GeometryNodeInputIndex").outputs[0]
    sign = _gm(ng, "SUBTRACT", _gm(ng, "MULTIPLY", _gm(ng, "MODULO", idx, 2.0), 2.0), 1.0)
    pos = ng.nodes.new("GeometryNodeInputPosition").outputs[0]
    neg = ng.nodes.new("ShaderNodeVectorMath")
    neg.operation = "SCALE"
    neg.inputs["Scale"].default_value = -(r_rim - r_hub) / r_rim
    ng.links.new(pos, neg.inputs[0])
    cz = ng.nodes.new("ShaderNodeCombineXYZ")
    ng.links.new(_gm(ng, "MULTIPLY", sign, flange), cz.inputs["Z"])
    add = ng.nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    ng.links.new(neg.outputs[0], add.inputs[0])
    ng.links.new(cz.outputs[0], add.inputs[1])
    al = ng.nodes.new("FunctionNodeAlignRotationToVector")
    al.axis = "Z"
    ng.links.new(add.outputs[0], al.inputs["Vector"])
    iop = ng.nodes.new("GeometryNodeInstanceOnPoints")
    ng.links.new(circ.outputs["Mesh"], iop.inputs["Points"])
    ng.links.new(tr.outputs[0], iop.inputs["Instance"])
    ng.links.new(al.outputs[0], iop.inputs["Rotation"])
    real = ng.nodes.new("GeometryNodeRealizeInstances")
    ng.links.new(iop.outputs[0], real.inputs[0])
    ng.links.new(real.outputs[0], out.inputs[0])
    return ng


def gn_corrugated(sx, sy, pitch=0.11, amp=0.012, per_wave=4, gap=0.0025):
    """PI_GN_Corrugated: a sx x sy sheet with sine corrugation along x (ridges run along y), plus its flipped
    underside `gap` below, so the sheet reads from above and from under the canopy."""
    ng, out = _gn("PI_GN_Corrugated")
    waves = max(2, round(sx / pitch))
    grid = ng.nodes.new("GeometryNodeMeshGrid")
    grid.inputs["Size X"].default_value = sx
    grid.inputs["Size Y"].default_value = sy
    grid.inputs["Vertices X"].default_value = waves * per_wave + 1
    grid.inputs["Vertices Y"].default_value = 2
    pos = ng.nodes.new("GeometryNodeInputPosition").outputs[0]
    sep = ng.nodes.new("ShaderNodeSeparateXYZ")
    ng.links.new(pos, sep.inputs[0])
    z = _gm(ng, "MULTIPLY", _gm(ng, "SINE", _gm(ng, "MULTIPLY", sep.outputs["X"], 2 * math.pi * waves / sx)), amp)
    off = ng.nodes.new("ShaderNodeCombineXYZ")
    ng.links.new(z, off.inputs["Z"])
    sp = ng.nodes.new("GeometryNodeSetPosition")
    ng.links.new(grid.outputs["Mesh"], sp.inputs["Geometry"])
    ng.links.new(off.outputs[0], sp.inputs["Offset"])
    under = ng.nodes.new("GeometryNodeTransform")
    under.inputs["Translation"].default_value = (0.0, 0.0, -gap)
    ng.links.new(sp.outputs[0], under.inputs["Geometry"])
    flip = ng.nodes.new("GeometryNodeFlipFaces")
    ng.links.new(under.outputs[0], flip.inputs["Mesh"])
    join = ng.nodes.new("GeometryNodeJoinGeometry")
    ng.links.new(flip.outputs[0], join.inputs[0])
    ng.links.new(sp.outputs[0], join.inputs[0])
    ng.links.new(join.outputs[0], out.inputs[0])
    return ng


def gn_stacks(count, length, r=0.045, h=(0.05, 0.11), seed=1, verts=7):
    """PI_GN_VadaiStacks: `count` stacks of vadai along x over `length`, seeded heights."""
    ng, out = _gn("PI_GN_VadaiStacks")
    line = ng.nodes.new("GeometryNodeMeshLine")
    line.mode = "END_POINTS"
    line.inputs["Count"].default_value = count
    line.inputs["Start Location"].default_value = (-length / 2, 0.0, 0.0)
    line.inputs["Offset"].default_value = (length / 2, 0.0, 0.0)
    cyl = ng.nodes.new("GeometryNodeMeshCylinder")
    cyl.inputs["Vertices"].default_value = verts
    cyl.inputs["Radius"].default_value = r
    cyl.inputs["Depth"].default_value = 1.0
    tr = ng.nodes.new("GeometryNodeTransform")
    tr.inputs["Translation"].default_value = (0.0, 0.0, 0.5)
    ng.links.new(cyl.outputs["Mesh"], tr.inputs["Geometry"])
    rnd = ng.nodes.new("FunctionNodeRandomValue")
    rnd.data_type = "FLOAT"
    rnd.inputs["Min"].default_value = h[0]
    rnd.inputs["Max"].default_value = h[1]
    rnd.inputs["Seed"].default_value = seed
    sc = ng.nodes.new("ShaderNodeCombineXYZ")
    sc.inputs["X"].default_value = 1.0
    sc.inputs["Y"].default_value = 1.0
    ng.links.new([o for o in rnd.outputs if o.enabled][0], sc.inputs["Z"])
    rot = ng.nodes.new("FunctionNodeRandomValue")
    rot.data_type = "FLOAT"
    rot.inputs["Max"].default_value = 6.28
    rot.inputs["Seed"].default_value = seed + 7
    eul = ng.nodes.new("ShaderNodeCombineXYZ")
    ng.links.new([o for o in rot.outputs if o.enabled][0], eul.inputs["Z"])
    iop = ng.nodes.new("GeometryNodeInstanceOnPoints")
    ng.links.new(line.outputs[0], iop.inputs["Points"])
    ng.links.new(tr.outputs[0], iop.inputs["Instance"])
    ng.links.new(sc.outputs[0], iop.inputs["Scale"])
    ng.links.new(eul.outputs[0], iop.inputs["Rotation"])
    real = ng.nodes.new("GeometryNodeRealizeInstances")
    ng.links.new(iop.outputs[0], real.inputs[0])
    ng.links.new(real.outputs[0], out.inputs[0])
    return ng


def gn_scatter(src, nx, ny, sx, sy, seed=1, jitter=0.0, tilt=0.0, lift=0.0, scale=(0.92, 1.08), spin=2 * math.pi):
    """PI_GN_FoodScatter: instances of the template object `src` on an nx x ny grid of cell centres over
    sx x sy, jittered, spun about z (+-spin/2), tilted (+-tilt rad) and lifted (0..lift) by seeded random values,
    then realised. Each instance stores its own local position as the point attribute "lp" so the bake can paint
    per-piece patterns (prawn segments, crab rims). Layers built with the same grid and seed line up exactly,
    which is how a piece with two looks (patty + prawns, crab body + legs) is scattered."""
    ng, out = _gn("PI_GN_FoodScatter")
    grid = ng.nodes.new("GeometryNodeMeshGrid")
    grid.inputs["Size X"].default_value = sx * (nx - 1) / nx
    grid.inputs["Size Y"].default_value = sy * (ny - 1) / ny
    grid.inputs["Vertices X"].default_value = nx
    grid.inputs["Vertices Y"].default_value = ny

    def rnd(lo, hi, s, vec=True):
        r = ng.nodes.new("FunctionNodeRandomValue")
        r.data_type = "FLOAT_VECTOR" if vec else "FLOAT"
        outs = [o for o in r.outputs if o.enabled]
        ins = [i for i in r.inputs if i.enabled]
        ins[0].default_value = lo
        ins[1].default_value = hi
        r.inputs["Seed"].default_value = s
        return outs[0]
    sp = ng.nodes.new("GeometryNodeSetPosition")
    ng.links.new(grid.outputs["Mesh"], sp.inputs["Geometry"])
    ng.links.new(rnd((-jitter, -jitter, 0.0), (jitter, jitter, lift), seed), sp.inputs["Offset"])
    info = ng.nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "ORIGINAL"
    info.inputs["Object"].default_value = src
    store = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type = "FLOAT_VECTOR"
    store.domain = "POINT"
    store.inputs["Name"].default_value = "lp"
    ng.links.new(info.outputs["Geometry"], store.inputs["Geometry"])
    ng.links.new(ng.nodes.new("GeometryNodeInputPosition").outputs[0], store.inputs["Value"])
    iop = ng.nodes.new("GeometryNodeInstanceOnPoints")
    ng.links.new(sp.outputs[0], iop.inputs["Points"])
    ng.links.new(store.outputs[0], iop.inputs["Instance"])
    ng.links.new(rnd((-tilt, -tilt, -spin / 2), (tilt, tilt, spin / 2), seed + 3), iop.inputs["Rotation"])
    ng.links.new(rnd(scale[0], scale[1], seed + 5, vec=False), iop.inputs["Scale"])
    real = ng.nodes.new("GeometryNodeRealizeInstances")
    ng.links.new(iop.outputs[0], real.inputs[0])
    ng.links.new(real.outputs[0], out.inputs[0])
    return ng


# ------------------------------------------------------------------------------------------ part helpers
class Builder:
    """Collects the parts of one asset; `finish()` applies modifiers, unwraps and joins them."""

    def __init__(self, name: str, coll):
        self.name = name
        self.coll = coll
        self.parts: list[bpy.types.Object] = []

    def _obj(self, me, look, loc=(0, 0, 0), rot=(0, 0, 0)):
        ob = bpy.data.objects.new(f"{self.name}_p{len(self.parts):02d}", me)
        self.coll.objects.link(ob)
        ob.location = loc
        ob.rotation_euler = rot
        me.materials.append(LOOKS[look]["mat"])
        ob["look"] = look
        self.parts.append(ob)
        return ob

    def _hard(self, ob, width, segs=2, angle=40):
        if width <= 0:
            for p in ob.data.polygons:
                p.use_smooth = False
            return ob
        if width > 0:
            b = ob.modifiers.new("Bevel", "BEVEL")
            b.width = width
            b.segments = segs
            b.limit_method = "ANGLE"
            b.angle_limit = math.radians(angle)
            b.harden_normals = False
        ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL").keep_sharp = True
        return ob

    def box(self, size, loc, look, bevel=0.006, segs=1, rot=(0, 0, 0), inset=None):
        """Cube primitive scaled to `size`; `inset` = (face axis '-y' etc, border, depth) panel recess."""
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=size, verts=bm.verts)
        if inset:
            for axis, border, depth in inset:
                ax = "xyz".index(axis[1])
                sgn = -1 if axis[0] == "-" else 1
                faces = [f for f in bm.faces if f.normal[ax] * sgn > 0.9]
                r = bmesh.ops.inset_individual(bm, faces=faces, thickness=border, depth=-depth)
        me = bpy.data.meshes.new(f"{self.name}_m")
        bm.to_mesh(me)
        bm.free()
        return self._hard(self._obj(me, look, loc, rot), bevel, segs)

    def cyl(self, r, depth, loc, look, verts=8, rot=(0, 0, 0), bevel=0.0, r2=None, cap=True):
        """Cylinder / cone primitive; cap True (both ends), False (open) or "top" (no hidden bottom face)."""
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=bool(cap), cap_tris=False, segments=verts, radius1=r,
                              radius2=r if r2 is None else r2, depth=depth)
        if cap == "top":
            bm.normal_update()
            bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z < -0.9], context="FACES_ONLY")
        me = bpy.data.meshes.new(f"{self.name}_m")
        bm.to_mesh(me)
        bm.free()
        return self._hard(self._obj(me, look, loc, rot), bevel, 1, 50)

    def tube(self, pts, r, look, sides=1):
        """A frame tube along a polyline (curve with a bevel radius); sides 0 -> 4-sided, 1 -> 6."""
        cu = bpy.data.curves.new(f"{self.name}_c", "CURVE")
        cu.dimensions = "3D"
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for p, c in zip(sp.points, pts):
            p.co = (*c, 1.0)
        cu.bevel_depth = r
        cu.bevel_resolution = sides
        cu.use_fill_caps = True
        ob = bpy.data.objects.new(f"{self.name}_p{len(self.parts):02d}", cu)
        self.coll.objects.link(ob)
        ob["look"] = look
        cu.materials.append(LOOKS[look]["mat"])
        self.parts.append(ob)
        return ob

    def lathe(self, prof, look, loc, segs=10, rot=(0, 0, 0), smooth=True):
        """Radius profile [(r, z), ...] on a Screw modifier about local z."""
        bm = bmesh.new()
        vs = [bm.verts.new((r, 0.0, z)) for r, z in prof]
        for a, b in zip(vs, vs[1:]):
            bm.edges.new((a, b))
        me = bpy.data.meshes.new(f"{self.name}_m")
        bm.to_mesh(me)
        bm.free()
        ob = self._obj(me, look, loc, rot)
        s = ob.modifiers.new("Screw", "SCREW")
        s.steps = segs
        s.render_steps = segs
        s.use_merge_vertices = True
        s.merge_threshold = 1e-4
        s.use_smooth_shade = smooth
        s.use_normal_calculate = True
        ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL").keep_sharp = True
        return ob

    def torus(self, R, r, loc, look, major=16, minor=4, rot=(0, 0, 0)):
        bm = bmesh.new()
        bmesh.ops.create_circle(bm, cap_ends=False, segments=minor, radius=r,
                                matrix=Matrix.Translation((R, 0, 0)) @ Matrix.Rotation(math.pi / 2, 4, "X"))
        me = bpy.data.meshes.new(f"{self.name}_m")
        bm.to_mesh(me)
        bm.free()
        ob = self._obj(me, look, loc, rot)
        s = ob.modifiers.new("Screw", "SCREW")
        s.steps = major
        s.render_steps = major
        s.use_merge_vertices = True
        s.use_smooth_shade = True
        s.use_normal_calculate = True
        return ob

    def gn(self, group, loc, look, rot=(0, 0, 0)):
        me = bpy.data.meshes.new(f"{self.name}_m")
        ob = self._obj(me, look, loc, rot)
        mod = ob.modifiers.new("GN", "NODES")
        mod.node_group = group
        return ob

    def grid(self, sx, sy, loc, look, nx=6, ny=4, displace=None, rot=(0, 0, 0)):
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=nx, y_segments=ny, size=0.5)
        bmesh.ops.scale(bm, vec=(sx, sy, 1.0), verts=bm.verts)
        me = bpy.data.meshes.new(f"{self.name}_m")
        bm.to_mesh(me)
        bm.free()
        ob = self._obj(me, look, loc, rot)
        if displace:
            tex = bpy.data.textures.new(f"{self.name}_disp", "VORONOI")
            tex.noise_scale = displace[0]
            d = ob.modifiers.new("Displace", "DISPLACE")
            d.texture = tex
            d.texture_coords = "LOCAL"
            d.strength = displace[1]
            d.mid_level = 0.0
            d.direction = "Z"
        return ob

    def strip(self, length, width, knee, drop, loc, look, rot=(0, 0, 0)):
        """A two-quad grid strip along x, its middle edge lifted by `knee` and its outer end moved by `drop`
        (a crab leg: root at -x, knee up, tip down)."""
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=2, y_segments=1, size=0.5)
        bmesh.ops.scale(bm, vec=(length, width, 1.0), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(0.0, 0.0, knee), verts=[vt for vt in bm.verts if abs(vt.co.x) < 1e-6])
        bmesh.ops.translate(bm, vec=(0.0, 0.0, drop), verts=[vt for vt in bm.verts if vt.co.x > 1e-6])
        bmesh.ops.scale(bm, vec=(1.0, 0.45, 1.0), verts=[vt for vt in bm.verts if vt.co.x > 1e-6])   # taper
        me = bpy.data.meshes.new(f"{self.name}_m")
        bm.to_mesh(me)
        bm.free()
        return self._hard(self._obj(me, look, loc, rot), 0.0)

    def blob(self, size, loc, look, rot=(0, 0, 0), taper=0.0, u=5, v=4, half=False):
        """UV sphere scaled to `size`; `half` keeps the upper half only (open at the equator: domes that sit on
        something, like a crab shell or the prawns on a vadai)."""
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=0.5)
        if half:
            bmesh.ops.delete(bm, geom=[vt for vt in bm.verts if vt.co.z < -1e-4], context="VERTS")
        bmesh.ops.scale(bm, vec=size, verts=bm.verts)
        me = bpy.data.meshes.new(f"{self.name}_m")
        bm.to_mesh(me)
        bm.free()
        ob = self._obj(me, look, loc, rot)
        if taper:
            sd = ob.modifiers.new("Taper", "SIMPLE_DEFORM")
            sd.deform_method = "TAPER"
            sd.factor = taper
            sd.deform_axis = "Z"
        for p in me.polygons:
            p.use_smooth = True
        return ob

    # --- finishing -------------------------------------------------------------------------------------------
    def finish(self) -> bpy.types.Object:
        """Apply every part's modifiers / curve, Smart-UV it at one texel density, join into one object."""
        dg = bpy.context.evaluated_depsgraph_get()
        meshes = []
        for ob in self.parts:
            ev = ob.evaluated_get(dg)
            me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
            me.transform(ob.matrix_world)
            me.materials.clear()                       # GN output carries an empty slot: one look per part
            me.materials.append(LOOKS[ob["look"]]["mat"])
            for p in me.polygons:
                p.material_index = 0
            if ob.type == "CURVE":
                for p in me.polygons:
                    p.use_smooth = True
            me["look"] = ob["look"]
            me.calc_loop_triangles()
            meshes.append(me)
        for ob in self.parts:
            bpy.data.objects.remove(ob)
        joined = []
        for me in meshes:
            ob = bpy.data.objects.new(f"_{self.name}_uv", me)
            self.coll.objects.link(ob)
            joined.append(ob)
            _smart_uv(ob, TEXEL_BIAS.get(LOOKS[me["look"]]["group"], 1.0))
        # join with the operator: it keeps the Weighted Normal custom normals and maps material slots
        for o in bpy.context.scene.objects:
            if o is not None:
                o.select_set(False)
        for ob in joined:
            ob.select_set(True)
        bpy.context.view_layer.objects.active = joined[0]
        bpy.ops.object.join()
        final = joined[0]
        final.name = self.name
        final.data.name = self.name
        return final


def _smart_uv(ob, bias: float) -> None:
    """Smart UV Project, then scale the UVs so the part's UV area / 3D area is the shared density x bias."""
    me = ob.data
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name="UVMap")
    if not me.polygons:
        print("[carts] empty part", ob.name)
        return
    for o in bpy.context.scene.objects:
        if o is not None:
            o.select_set(False)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(55), island_margin=0.02, scale_to_bounds=False,
                             correct_aspect=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    a3 = sum(p.area for p in me.polygons)
    uv = me.uv_layers.active.data
    auv = 0.0
    for p in me.polygons:
        pts = [uv[i].uv for i in p.loop_indices]
        s = 0.0
        for k in range(1, len(pts) - 1):
            e1, e2 = pts[k] - pts[0], pts[k + 1] - pts[0]
            s += abs(e1.x * e2.y - e1.y * e2.x) / 2
        auv += s
    if auv <= 0 or a3 <= 0:
        return
    k = math.sqrt(bias * a3 / auv)
    for d in uv:
        d.uv = d.uv * k


# ------------------------------------------------------------------------------------------ the assets
def _wheel(b: Builder, x, y, R=0.335, look_rim="galv"):
    """Bicycle-type wheel in the xz plane at (x, y, R): tyre, rim, laced spokes (GN), hub."""
    rx = (math.pi / 2, 0, 0)
    b.torus(R - 0.022, 0.024, (x, y, R), "rubber", 14, 4, rot=rx)
    b.torus(R - 0.05, 0.009, (x, y, R), look_rim, 14, 3, rot=rx)
    b.gn(gn_spokes(10, R - 0.055, 0.025, 0.03), (x, y, R), look_rim, rot=rx)   # spokes meet at the axle tube


def cart_a(coll) -> bpy.types.Object:
    """PROP_Cart_IssoWade_A (cart_03): green body, spoked wheels, wooden shelves, rusty tin canopy."""
    b = Builder(C.CART_A, coll)
    # chassis: two big wheels on one axle, a stand at the leg end, push handles at +x
    for y in (-0.43, 0.43):
        _wheel(b, 0.12, y)
    b.tube([(0.12, -0.47, 0.335), (0.12, 0.47, 0.335)], 0.012, "iron", 0)
    for y in (-0.3, 0.3):
        b.tube([(-0.74, y, 0.0), (-0.72, y, 0.34)], 0.016, "iron", 0)
        b.tube([(0.8, y, 0.62), (1.14, y, 0.8), (1.14, y, 0.86)], 0.013, "galv", 0)
    b.tube([(1.14, -0.32, 0.86), (1.14, 0.32, 0.86)], 0.016, "galv", 0)
    # green steel body with a recessed door panel on the front and back
    b.box((1.6, 0.72, 0.62), (0.0, 0.0, 0.65), "paint_green", 0.012, 2,
          inset=[("-y", 0.07, 0.012), ("+y", 0.07, 0.012)])
    b.box((1.66, 0.78, 0.035), (0.0, 0.0, 0.34), "iron", 0.0)                   # chassis channel
    b.box((1.74, 0.84, 0.03), (0.0, 0.0, 0.975), "galv", 0.006)                 # steel counter sheet
    b.box((1.74, 0.16, 0.02), (0.0, -0.5, 0.95), "galv", 0.0)                   # serving ledge (cart_03)
    # open shelving: 4 posts, 3 timber shelves with galvanised lips, stacked vadai (GN)
    for x in (-0.8, 0.8):
        for y in (-0.33, 0.33):
            b.tube([(x, y, 0.99), (x, y, 2.06 if y < 0 else 2.0)], 0.014, "galv", 0)
    for i, z in enumerate((1.26, 1.52, 1.78)):
        d = 0.56 - 0.08 * i
        b.box((1.58, d, 0.024), (0.0, 0.33 - d / 2, z), "wood", 0.0)
        b.box((1.58, 0.018, 0.04), (0.0, 0.33 - d, z + 0.012), "galv", 0.0)
    # the shelf stock and the counter tray are their own piece (PROP_CartFood_IssoWade_A, food_a below)
    # rusty corrugated tin canopy on a light angle frame, sloping to the back
    slope = math.atan2(0.06, 1.1)
    b.gn(gn_corrugated(1.98, 1.16, 0.13, 0.012, 3), (0.0, 0.0, 2.07), "tin_rust_lit", rot=(-slope, 0, 0))
    b.box((1.9, 0.03, 0.03), (0.0, -0.33, 2.055), "galv", 0.0)
    b.box((1.9, 0.03, 0.03), (0.0, 0.33, 1.995), "galv", 0.0)
    # one cool-white LED batten under the sheet for night trade; the rust round it glows (tin_rust_lit)
    b.box((1.2, 0.04, 0.016), (0.0, CANOPY_A_LED_Y, 2.07 - CANOPY_A_LED_Y * math.tan(slope) - 0.024), "led", 0.004)
    # white plastic water can on the ground at the leg end, blue bag hung from the canopy's front corner
    b.box((0.2, 0.26, 0.3), (-1.02, -0.18, 0.15), "plastic_white", 0.03, 1)
    b.cyl(0.024, 0.04, (-1.02, -0.26, 0.315), "plastic_blue", 6)
    b.tube([(-0.92, -0.52, 2.05), (-0.92, -0.52, 1.97)], 0.004, "plastic_blue", 0)
    b.blob((0.13, 0.08, 0.17), (-0.92, -0.52, 1.89), "plastic_blue", taper=-0.4)
    return b.finish()


def cart_b(coll) -> bpy.types.Object:
    """PROP_Cart_IssoWade_B (cart_01/02): maroon cabinet, glass display box with LED, white canopy, pole lights."""
    b = Builder(C.CART_B, coll)
    for y in (-0.46, 0.46):
        _wheel(b, 0.05, y, 0.33)
    b.tube([(0.05, -0.5, 0.33), (0.05, 0.5, 0.33)], 0.012, "iron", 0)
    for y in (-0.32, 0.32):
        b.tube([(-0.78, y, 0.0), (-0.76, y, 0.42)], 0.016, "iron", 0)
        b.tube([(0.84, y, 0.7), (1.1, y, 0.86)], 0.013, "iron", 0)
    b.tube([(1.1, -0.34, 0.86), (1.1, 0.34, 0.86)], 0.016, "iron", 0)
    b.box((1.7, 0.76, 0.55), (0.0, 0.0, 0.675), "paint_maroon", 0.012, 2,
          inset=[("-y", 0.06, 0.012), ("+y", 0.06, 0.012)])
    b.box((1.76, 0.82, 0.04), (0.0, 0.0, 0.40), "iron", 0.0)
    b.box((1.84, 0.9, 0.03), (0.0, 0.0, 0.965), "steel_counter_lit", 0.006)
    # glass display box over the left 2/3 of the counter (cart_01/02): aluminium frame (Wireframe) with a slanted
    # front (the top front edge set back, as on the real showcases) and a centre mullion, glass top the trays
    # stand on, glass end panes, two LED strips under the top. The front stays open (the shared material is
    # opaque on Low, a pane would hide the food); the frame, the end panes and the lit inside carry the read.
    gx0, gx1, gy, gz0, gz1, slant = -0.86, 0.42, 0.34, 0.98, 1.30, 0.1
    gxm = (gx0 + gx1) / 2
    frame = b.box((gx1 - gx0, 2 * gy, gz1 - gz0), (gxm, 0.0, (gz0 + gz1) / 2), "galv", 0.0)
    frame.modifiers.clear()
    for vt in frame.data.vertices:                     # shear the front top edge back (a slanted front pane)
        if vt.co.z > 0 and vt.co.y < 0:
            vt.co.y += slant
    w = frame.modifiers.new("Frame", "WIREFRAME")
    w.thickness = 0.018
    w.use_even_offset = True
    w.use_relative_offset = False
    w.use_replace = True
    b.tube([(gxm, -gy, gz0), (gxm, -gy + slant, gz1)], 0.008, "galv", 0)          # centre mullion
    b.box((gx1 - gx0 + 0.01, 2 * gy - slant + 0.01, 0.008), (gxm, slant / 2, gz1 + 0.006), "glass", 0.0)
    for x in (gx0 + 0.006, gx1 - 0.006):                                          # end panes
        b.box((0.006, 2 * gy - slant / 2 - 0.02, gz1 - gz0 - 0.02), (x, slant / 4, (gz0 + gz1) / 2), "glass_lit", 0.0)
    for y in (-gy + slant + 0.03, gy - 0.04):
        b.box((gx1 - gx0 - 0.06, 0.03, 0.012), (gxm, y, gz1 - 0.012), "led", 0.0)
    # the food (trays of crabs and prawn vadai on the glass top, lentil vadai stacks) is PROP_CartFood_IssoWade_B
    # the open end: a dark iron wok and a steel bowl
    b.lathe([(0.0, 0.0), (0.12, 0.006), (0.22, 0.07), (0.25, 0.11), (0.2, 0.06), (0.0, 0.012)],
            "iron", (0.66, -0.06, 0.98), 8)
    b.lathe([(0.0, 0.0), (0.07, 0.0), (0.12, 0.07), (0.1, 0.045), (0.0, 0.008)], "steel", (0.7, 0.26, 0.98), 8)
    # canopy: 4 posts, white corrugated sheet, cool-white LED tube along the front, coloured pole lights
    for x in (-0.9, 0.9):
        for y in (-0.4, 0.4):
            b.tube([(x, y, 0.98), (x, y, 2.12 if y < 0 else 2.06)], 0.015, "galv", 0)
    slope = math.atan2(0.06, 1.3)
    b.gn(gn_corrugated(2.22, 1.44, 0.14, 0.011, 3), (0.0, 0.0, 2.13), "tin_white_lit", rot=(-slope, 0, 0))
    b.box((2.0, 0.035, 0.035), (0.0, -0.4, 2.105), "galv", 0.0)
    # two LED battens under the sheet (cart_01 shows a row of bright bars, cart_02 one long tube at the front):
    # a flat diffuser bar reads wider than a thin tube at distance; the sheet round them glows (tin_white_lit)
    for y in CANOPY_LEDS_Y:
        z = 2.13 - y * math.tan(slope) - 0.026          # just under the sheet's lowest corrugation
        b.box((1.5, 0.045, 0.018), (0.0, y, z), "led", 0.004)
    k = 0
    for x in (-0.9, 0.9):
        for z in (1.7, 1.95):
            b.cyl(0.026, 0.07, (x, -0.43, z), ("bulb_red", "bulb_green", "bulb_blue", "bulb_amber")[k], 5)
            k += 1
    return b.finish()


def gas_cylinder(coll, name, look) -> bpy.types.Object:
    """12.5 kg LPG cylinder: foot ring, body, shoulder, valve under a protective collar (cart_01/02/03)."""
    b = Builder(name, coll)
    b.lathe([(0.0, 0.0), (0.135, 0.0), (0.135, 0.055), (0.155, 0.11), (0.155, 0.46), (0.12, 0.53),
             (0.05, 0.55), (0.0, 0.55)], look, (0, 0, 0), 10)
    b.lathe([(0.075, 0.54), (0.09, 0.6), (0.095, 0.62), (0.08, 0.6), (0.075, 0.54)], "galv", (0, 0, 0), 8)
    b.cyl(0.018, 0.05, (0.0, 0.0, 0.575), "steel", 6)
    return b.finish()


def stool(coll) -> bpy.types.Object:
    """Low plastic stool (cart_02): rounded square seat, four splayed legs."""
    b = Builder(C.STOOL, coll)
    b.box((0.3, 0.3, 0.03), (0.0, 0.0, 0.425), "stool_red", 0.03, 2)
    b.box((0.27, 0.27, 0.04), (0.0, 0.0, 0.39), "stool_red", 0.012, 1)
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.cyl(0.022, 0.4, (sx * 0.15, sy * 0.15, 0.19), "stool_red", 6, r2=0.016,
                  rot=(sy * math.radians(7), -sx * math.radians(7), 0))
    return b.finish()


def bowls(coll) -> bpy.types.Object:
    """Three nested stainless bowls (cart_01, cart_03)."""
    b = Builder(C.BOWLS, coll)
    for r, z in ((0.16, 0.0), (0.13, 0.045), (0.1, 0.085)):
        b.lathe([(0.0, 0.0), (r * 0.6, 0.0), (r, r * 0.45), (r * 0.92, r * 0.44), (r * 0.5, 0.012), (0.0, 0.012)],
                "steel", (0, 0, z), 10)
    return b.finish()


# ------------------------------------------------------------------------------------------ food (round 2)
# Mid-poly templates, one look each, scattered by PI_GN_FoodScatter. Sizes from food_01: prawn vadai ~8 cm across
# with two whole prawns on top; crabs ~9 cm shells with legs spread to ~20 cm; lentil vadai ~9 cm discs.
TEMPLATES: dict[str, bpy.types.Object] = {}


def _template(coll, key, look, parts) -> bpy.types.Object:
    """A one-look food template at the origin (`parts(b)` adds primitives to a Builder); hidden from renders."""
    name = f"_tmpl_{key}"
    if name in TEMPLATES:
        return TEMPLATES[name]
    b = Builder(name, coll)
    parts(b, look)
    ob = b.finish()
    ob.hide_render = True
    TEMPLATES[name] = ob
    return ob


def _t_patty(b, look):
    b.cyl(0.05, 0.022, (0.0, 0.0, 0.011), look, 8, r2=0.044, cap="top")


def _t_prawns(b, look):
    b.blob((0.08, 0.058, 0.034), (0.0, 0.0, 0.019), look, u=6, v=4, half=True)


def _t_crab_body(b, look):
    b.blob((0.085, 0.064, 0.05), (0.0, 0.0, 0.008), look, u=6, v=4, half=True)


def _t_crab_legs(b, look):
    """Eight walking legs and two claws: thin strips arched at the knee, spread round the shell."""
    for ang, ln, wd in [(a, 0.06, 0.013) for a in (-50, -25, 0, 25, 155, 180, 205, 230)] + \
                       [(65, 0.075, 0.024), (115, 0.075, 0.024)]:
        a = math.radians(ang)
        rr = 0.03 + ln / 2
        b.strip(ln, wd, 0.014, -0.012, (math.cos(a) * rr, math.sin(a) * rr, 0.012), look, rot=(0, 0, a))


def _scatter(b, coll, key, look, parts, loc, nx, ny, sx, sy, **kw):
    b.gn(gn_scatter(_template(coll, key, look, parts), nx, ny, sx, sy, **kw), loc, look)


def _prawn_vadai(b, coll, lit, loc, nx, ny, sx, sy, seed):
    s = "_lit" if lit else ""
    kw = dict(seed=seed, jitter=0.006, tilt=0.06, spin=0.5)
    _scatter(b, coll, f"patty{s}", f"patty{s}", _t_patty, loc, nx, ny, sx, sy, **kw)
    _scatter(b, coll, f"prawns{s}", f"prawn_pair{s}", _t_prawns, loc, nx, ny, sx, sy, **kw)


def _crabs(b, coll, lit, loc, nx, ny, sx, sy, seed):
    s = "_lit" if lit else ""
    kw = dict(seed=seed, jitter=0.025, tilt=0.22, lift=0.025)
    _scatter(b, coll, f"crab_body{s}", f"crab_shell{s}", _t_crab_body, loc, nx, ny, sx, sy, **kw)
    _scatter(b, coll, f"crab_legs{s}", f"crab_leg{s}", _t_crab_legs, loc, nx, ny, sx, sy, **kw)


def _tray(b, size, loc, look):
    """Rectangular steel tray: a box with its top recessed (bmesh inset)."""
    b.box(size, loc, look, 0.0, inset=[("+z", 0.014, size[2] - 0.008)])


def food_a(coll) -> bpy.types.Object:
    """PROP_CartFood_IssoWade_A: cart A's stock (cart_03), in cart A's frame. Middle shelf: lentil vadai stacks
    full width with prawn vadai on a steel plate; bottom shelf: red cool box, jars, a steel bowl, packets; top
    shelf: one jar; counter: a tray of prawn vadai and a bowl."""
    b = Builder(C.FOOD_A, coll)
    zs = (1.272, 1.532, 1.792)                       # shelf tops (cart_a: z + 0.012)
    # middle shelf (y -0.15 .. 0.33), stocked full width as in cart_03: a back row of lentil vadai stacks,
    # in front of it prawn vadai on a steel plate (left) and a second row of lentil stacks (right)
    b.gn(gn_stacks(12, 1.42, 0.05, (0.06, 0.13), seed=21, verts=6), (0.0, 0.2, zs[1]), "lentil")
    b.box((0.74, 0.26, 0.008), (-0.38, 0.0, zs[1] + 0.004), "steel", 0.0)
    _prawn_vadai(b, coll, False, (-0.38, 0.0, zs[1] + 0.008), 6, 2, 0.66, 0.19, 31)
    b.gn(gn_stacks(6, 0.62, 0.05, (0.04, 0.09), seed=23, verts=6), (0.42, -0.02, zs[1]), "lentil")
    # bottom shelf (y -0.23 .. 0.33)
    b.box((0.32, 0.22, 0.15), (-0.52, 0.1, zs[0] + 0.075), "stool_red", 0.012, 1, inset=[("-y", 0.02, 0.006)])
    b.box((0.18, 0.12, 0.08), (-0.18, 0.12, zs[0] + 0.04), "plastic_white", 0.006)
    for x, look, lid in ((0.08, "jar_chilli", "stool_red"), (0.24, "jar_onion", "plastic_blue")):
        b.cyl(0.055, 0.15, (x, 0.05, zs[0] + 0.075), look, 6, cap="top")
        b.cyl(0.05, 0.025, (x, 0.05, zs[0] + 0.16), lid, 6, cap="top")
    b.lathe([(0.0, 0.0), (0.07, 0.0), (0.13, 0.08), (0.12, 0.075), (0.0, 0.01)], "steel", (0.55, 0.06, zs[0]), 8)
    # top shelf (y -0.07 .. 0.33): near empty in cart_03, one jar
    b.cyl(0.05, 0.13, (-0.55, 0.15, zs[2] + 0.065), "jar_onion", 6, cap="top")
    b.cyl(0.045, 0.02, (-0.55, 0.15, zs[2] + 0.14), "plastic_blue", 6, cap="top")
    # counter: a tray of prawn vadai at the front (the serving side), a steel bowl of onion sambol
    _tray(b, (0.46, 0.28, 0.03), (-0.4, -0.12, 1.005), "steel")
    _prawn_vadai(b, coll, False, (-0.4, -0.12, 1.012), 4, 2, 0.36, 0.14, 37)
    b.lathe([(0.0, 0.0), (0.08, 0.0), (0.14, 0.07), (0.13, 0.066), (0.0, 0.008)], "steel", (0.35, -0.05, 0.99), 8)
    b.grid(0.2, 0.2, (0.35, -0.05, 1.04), "jar_onion", 2, 2)
    return b.finish()


def food_b(coll) -> bpy.types.Object:
    """PROP_CartFood_IssoWade_B: cart B's display (cart_01, food_01), in cart B's frame. Two steel trays on the
    glass top, fried crabs on a bed of vadai (left) and 4 x 4 prawn vadai (right); lentil vadai stacks at both
    ends of the top and inside the box. Every piece uses the LED-lit looks (emission = albedo x LED_SPILL)."""
    b = Builder(C.FOOD_B, coll)
    top = 1.314                                       # cart_b glass top surface (gz1 + 0.006 + 0.004)
    for x, y in ((-0.49, 0.05), (0.03, 0.05)):
        _tray(b, (0.5, 0.4, 0.035), (x, y, top + 0.0175), "steel_tray_lit")
    floor = top + 0.008
    b.grid(0.46, 0.36, (-0.49, 0.05, floor), "patty_lit", 4, 3, displace=(0.06, 0.02))
    _crabs(b, coll, True, (-0.49, 0.05, floor + 0.012), 5, 2, 0.46, 0.32, 41)
    _prawn_vadai(b, coll, True, (0.03, 0.05, floor), 4, 4, 0.46, 0.38, 43)
    for x, y in ((-0.8, -0.06), (-0.8, 0.16), (0.34, -0.02), (0.34, 0.2)):
        b.gn(gn_stacks(1, 0.0, 0.045, (0.07, 0.14), seed=int(50 + 10 * x + 7 * y), verts=6), (x, y, top), "lentil_lit")
    # inside the box, on the counter: a plate with two more stacks (seen through the open front)
    b.box((0.36, 0.2, 0.008), (-0.3, 0.05, 0.984), "steel_tray_lit", 0.0)
    b.gn(gn_stacks(2, 0.18, 0.045, (0.08, 0.12), seed=57, verts=6), (-0.3, 0.05, 0.988), "lentil_lit")
    return b.finish()


def build_all(coll) -> dict[str, bpy.types.Object]:
    """Model every asset; returns name -> joined object (look materials, UVs not yet packed)."""
    make_looks()
    TEMPLATES.clear()
    out = {
        C.CART_A: cart_a(coll), C.CART_B: cart_b(coll),
        C.CYL_RED: gas_cylinder(coll, C.CYL_RED, "cyl_red"), C.CYL_BLUE: gas_cylinder(coll, C.CYL_BLUE, "cyl_blue"),
        C.STOOL: stool(coll), C.BOWLS: bowls(coll),
        C.FOOD_A: food_a(coll), C.FOOD_B: food_b(coll),
    }
    for ob in TEMPLATES.values():                     # templates only feed the scatter; the pieces are realised
        bpy.data.objects.remove(ob)
    TEMPLATES.clear()
    return out


def strip_bake_attributes(ob) -> None:
    """Drop bake-only attributes ("lp") so the game mesh carries position, normal, UV and COLOR_0 only."""
    a = ob.data.attributes.get("lp")
    if a is not None:
        ob.data.attributes.remove(a)


def pack(objs) -> None:
    """Pack every asset's islands together into the one 0-1 atlas (relative texel density kept)."""
    for o in bpy.context.scene.objects:
        if o is not None:
            o.select_set(False)
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, rotate_method="ANY", scale=True, margin_method="SCALED", margin=0.003, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")


def tris(ob) -> int:
    me = ob.data
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def load_meshes(path: str, mats) -> dict[str, bpy.types.Mesh]:
    """City build: the baked cart meshes from the asset .blend, on the pipeline's own world material."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.meshes = [n for n in src.meshes if n in C.PIECES]
    out = {}
    for me in dst.meshes:
        if me is None:
            continue
        name = me.name.split(".")[0]
        for i, m in enumerate(me.materials):
            if mats and C.MATERIAL in mats:
                me.materials[i] = mats[C.MATERIAL]
        out[name] = me
    return out
