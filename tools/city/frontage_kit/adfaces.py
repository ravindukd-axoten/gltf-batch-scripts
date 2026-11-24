"""Sponsor-surface pieces and mounts for the frontage kit (P96; branding research P102 section 3.3).

Called by build_kit.py after kitbuild.build(). Adds four sign-frame pieces, one per fixed aspect:
  KIT_AdFascia_4x1_A   fascia sign frame over a shopfront (face 2.4 x 0.6 m)
  KIT_AdBracket_1x2_A  bracket sign perpendicular to the street (face 0.5 x 1.0 m, both sides)
  KIT_AdRoof_3x1_A     rooftop scaffold board (face 4.5 x 1.5 m) on the parapet
  KIT_AdRoof_2x1_A     rooftop scaffold board (face 3.0 x 1.5 m)
Each ad face is a single quad, UV 0-1 over the whole panel, on its own material MAT_AdFace_<aspect> (default
creative from ad_textures.py; never baked into the trim). Frames, posts and braces use MAT_FrontageTrim_A (METAL
row). Custom properties on every piece: ad_slot_type, aspect, safe_area, district_hint, for tools/city to emit slot
ids. Every Shopfront piece gets an `ad_mounts` property (fascia 4:1 at its signboard, bracket 1:2 at the pier) and
every Parapet piece a rooftop 3:1 / 2:1 mount, so the city pipeline places sign frames per bay without new geometry.
"""
import json
import os

import bmesh
import bpy

import pieces

HERE = os.path.dirname(os.path.abspath(__file__))
SAFE = "0.06,0.10"
METAL_RGB = (0x8C / 255, 0x91 / 255, 0x8F / 255)
ASPECTS = {"4x1": (2.4, 0.6), "3x1": (4.5, 1.5), "2x1": (3.0, 1.5), "1x2": (0.5, 1.0)}


def ad_material(aspect):
    name = f"MAT_AdFace_{aspect}"
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1)      # neutral grey if the creative is missing
    bsdf.inputs["Roughness"].default_value = 0.8
    p = os.path.join(HERE, "textures", f"T_AdFace_{aspect}_Default.png")
    if os.path.exists(p):
        img = nt.nodes.new("ShaderNodeTexImage")
        img.image = bpy.data.images.load(p, check_existing=True)
        nt.links.new(img.outputs["Color"], bsdf.inputs["Base Color"])
    return m


def _box(bm, x0, x1, y0, y1, z0, z1, mat=1):
    r = bmesh.ops.create_cube(bm, size=1.0)
    for v in r["verts"]:
        v.co.x = x0 + (v.co.x + 0.5) * (x1 - x0)
        v.co.y = y0 + (v.co.y + 0.5) * (y1 - y0)
        v.co.z = z0 + (v.co.z + 0.5) * (z1 - z0)
    for f in {f for v in r["verts"] for f in v.link_faces}:
        f.material_index = mat


def _quad(bm, corners, mat=0):
    vs = [bm.verts.new(c) for c in corners]
    f = bm.faces.new(vs)
    f.material_index = mat
    return f


def _finish(name, bm, trim_mat, aspect, kind, coll, at, lod):
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    uv = bm.loops.layers.uv.new("UVMap")
    col = bm.loops.layers.color.new("Col")
    for f in bm.faces:
        if f.material_index == 0:                    # ad face: UV 0-1 over the panel (corners in BL, BR, TR, TL)
            for l, c in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                l[uv].uv = c
                l[col] = (1, 1, 1, 1)
        else:                                        # frame: a 1D strip in the METAL row, metres along the member
            n = [abs(c) for c in f.normal]           # (members are 3-8 cm: no cross detail to show, so V is one
            axes = [k for k in range(3) if k != n.index(max(n))]   # line; rust still varies along the length)
            ext = [max(v.co[k] for v in f.verts) - min(v.co[k] for v in f.verts) for k in axes]
            ua = axes[0] if ext[0] >= ext[1] else axes[1]
            for l in f.loops:
                l[uv].uv = (l.vert.co[ua] / 4.0, (13.6 + 0.35) / 16.0)
                l[col] = (*METAL_RGB, 1.0)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(ad_material(aspect))         # slot 0: the ad face (its own texture decides density)
    me.materials.append(trim_mat)
    ob = bpy.data.objects.new(name, me)
    ob.location = at
    coll.objects.link(ob)
    ob["ad_slot_type"], ob["aspect"], ob["safe_area"], ob["district_hint"] = kind, aspect.replace("x", ":"), SAFE, "delta_road"
    ob["refs"] = "gf_24,gf_21; P102 research 3.3"
    if lod:
        ob.hide_render = True
    return sum(len(p.vertices) - 2 for p in me.polygons)


def _collider(name, x0, x1, y0, y1, z0, z1, coll, at):
    bm = bmesh.new()
    _box(bm, x0, x1, y0, y1, z0, z1)
    me = bpy.data.meshes.new(name + "_COL")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name + "_COL", me)
    ob.location, ob.hide_render = at, True
    coll.objects.link(ob)


def fascia(bm, lod):
    w, h = ASPECTS["4x1"]
    t = 0.05
    for b in ((0, w, -0.1, 0.0, 0, t), (0, w, -0.1, 0.0, h - t, h), (0, t, -0.098, -0.002, t, h - t),
              (w - t, w, -0.098, -0.002, t, h - t)):          # stiles set in 2 mm: no edge shared with the rails
        _box(bm, *b)
    if not lod:                                       # two wall cleats behind the frame
        for x in (0.3, w - 0.36):
            _box(bm, x, x + 0.06, -0.02, 0.01, 0.1, h - 0.1)
    _quad(bm, ((t, -0.07, t), (w - t, -0.07, t), (w - t, -0.07, h - t), (t, -0.07, h - t)))


def bracket(bm, lod):
    w, h = ASPECTS["1x2"]
    y0 = -0.25
    _box(bm, -0.02, 0.02, -0.25 - w - 0.05, 0.0, h + 0.05, h + 0.1)       # arm from the wall
    _box(bm, -0.04, 0.04, -0.06, 0.0, h - 0.2, h + 0.15)                  # wall plate
    if not lod:
        _box(bm, -0.015, 0.015, y0 - w, y0, h + 0.0, h + 0.05)            # hanger bar
    # frame (thin) and the two faces back to back, perpendicular to the street (plane X = 0)
    _box(bm, -0.03, 0.03, y0 - w, y0, 0.0, 0.03)                         # sign box: bottom, two stiles, top
    _box(bm, -0.03, 0.03, y0 - 0.03, y0, 0.032, h - 0.032)                # (gaps of 2 mm: no shared edges, and
    _box(bm, -0.03, 0.03, y0 - w, y0 - w + 0.03, 0.032, h - 0.032)        # the panel's edge is closed, so no
    _box(bm, -0.03, 0.03, y0 - w, y0, h - 0.03, h - 0.002)                # see-through from a raking view)
    _quad(bm, ((-0.031, y0, 0), (-0.031, y0 - w, 0), (-0.031, y0 - w, h), (-0.031, y0, h)))
    _quad(bm, ((0.031, y0 - w, 0), (0.031, y0, 0), (0.031, y0, h), (0.031, y0 - w, h)))


def roof(aspect):
    def build(bm, lod):
        w, h = ASPECTS[aspect]
        z0 = 1.2                                       # board clears the parapet and roof clutter
        for x in (0.2, w - 0.28) if w < 4 else (0.2, w / 2 - 0.04, w - 0.28):
            _box(bm, x, x + 0.08, 0.3, 0.38, 0.0, z0 + h)                 # posts
            if not lod:
                _box(bm, x - 0.02, x + 0.1, 0.38, 1.2, 0.0, 0.06)         # base skid
                _box(bm, x + 0.01, x + 0.07, 0.38, 1.1, 0.06, 0.12)
        _box(bm, 0, w, 0.22, 0.3, z0 - 0.08, z0)                           # rails
        _box(bm, 0, w, 0.22, 0.3, z0 + h, z0 + h + 0.06)
        if not lod:
            _box(bm, 0, w, 0.24, 0.3, z0 + h * 0.5 - 0.03, z0 + h * 0.5 + 0.03)
        _quad(bm, ((0, 0.21, z0), (w, 0.21, z0), (w, 0.21, z0 + h), (0, 0.21, z0 + h)))
    return build


PIECES = {"KIT_AdFascia_4x1_A": ("4x1", "fascia", fascia, (0, 2.4, -0.1, 0.0, 0, 0.6)),
          "KIT_AdBracket_1x2_A": ("1x2", "bracket", bracket, (-0.04, 0.04, -0.8, 0.0, 0, 1.15)),
          "KIT_AdRoof_3x1_A": ("3x1", "rooftop", roof("3x1"), (0, 4.5, 0.2, 1.2, 0, 2.76)),
          "KIT_AdRoof_2x1_A": ("2x1", "rooftop", roof("2x1"), (0, 3.0, 0.2, 1.2, 0, 2.76))}


def _sign_rects():
    out = {}
    for fam, table in (("Shutter", pieces.SHOPFRONT.get("Shutter", {})), ("Glazed", pieces.SHOPFRONT.get("Glazed", {}))):
        for var, parts_ in table.items():
            for kind, kw in (p for p in parts_ if isinstance(p, tuple)):
                if kind == "PI_Sign":
                    out[f"KIT_Shopfront_{fam}_{var}"] = kw
    return out


def add_mounts():
    """`ad_mounts` (JSON, metres in piece space) on every Shopfront and Parapet piece."""
    rects = _sign_rects()
    for ob in bpy.data.objects:
        n = ob.name
        if n.startswith("KIT_Shopfront_") and not n.endswith(("_LOD1", "_COL")) and "Corner" not in n:
            r = rects.get(n, dict(X0=0.3, X1=2.7, Z0=3.0, Z1=3.6))
            wid = min(r["X1"] - r["X0"], 4 * (r["Z1"] - r["Z0"]))
            x0 = (r["X0"] + r["X1"] - wid) / 2
            ob["ad_mounts"] = json.dumps([
                {"slot": "fascia", "aspect": "4:1", "piece": "KIT_AdFascia_4x1_A", "x": round(x0, 3), "y": -0.152,
                 "z": round((r["Z0"] + r["Z1"]) / 2 - wid / 8, 3), "w": round(wid, 3), "h": round(wid / 4, 3)},
                {"slot": "bracket", "aspect": "1:2", "piece": "KIT_AdBracket_1x2_A", "x": 2.95, "y": 0.0, "z": 3.0}])
        elif n.startswith("KIT_Parapet_") and not n.endswith(("_LOD1", "_COL")):
            ob["ad_mounts"] = json.dumps([
                {"slot": "rooftop", "aspect": "2:1", "piece": "KIT_AdRoof_2x1_A", "x": 0.0, "y": 0.3, "z": "parapet_top"},
                {"slot": "rooftop", "aspect": "3:1", "piece": "KIT_AdRoof_3x1_A", "x": 0.0, "y": 0.3, "z": "parapet_top",
                 "spans_bays": 2}])


def build(tris):
    kit = bpy.data.collections["FrontageKit"]
    trim = bpy.data.materials["MAT_FrontageTrim_A"]
    for i, (name, (aspect, kind, fn, col)) in enumerate(PIECES.items()):
        at = (i * 6.0, 40.0, 0.0)
        for lod in (0, 1):
            bm = bmesh.new()
            fn(bm, lod)
            n = name if lod == 0 else name + "_LOD1"
            tris.setdefault(name, {})[f"lod{lod}"] = _finish(n, bm, trim, aspect, kind, kit, at, lod)
        _collider(name, *col, kit, at)
    add_mounts()
    return tris
