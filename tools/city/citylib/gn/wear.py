"""Blender side of the kit COLOR_1 wear (P242): measures every face corner and writes `Col1` with
citylib.kit_wear.corner(). Runs after the AO bake (it reads the AO in `Col` alpha) and before the kit material remap.
glTF: exported as COLOR_1 when the exporter writes all colour attributes (build_places_kit.py does)."""
from __future__ import annotations

import math

import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .. import kit_wear as KW

LAYER = "Col1"
GROUND_Z = 0.15     # forecourt top is 0.08 (fuel_kit.G); an up face this low is lying on the slab (bay paint, stains, drain lids): ground dirt, no chips


def write_color1(ob, name: str) -> dict:
    me = ob.data
    col = me.color_attributes.get("Col")
    if col is None:
        return {}
    ao = [0.0] * (4 * len(col.data))
    col.data.foreach_get("color_srgb", ao)
    names = [m.name if m else "" for m in me.materials]
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    convex = [0.0] * len(bm.verts)
    for e in bm.edges:
        if len(e.link_faces) != 2 or (e.smooth and all(f.smooth for f in e.link_faces)):
            continue                    # a facet edge of a round (smooth-shaded post, hose, drum) is not a chip edge
        a = math.degrees(e.calc_face_angle_signed(0.0))
        if a > 0.0:
            for v in e.verts:
                convex[v.index] = max(convex[v.index], a)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    s = KW.seed(name)
    up = Vector((0.0, 0.0, 1.0))
    out = [0.0] * (4 * len(me.loops))
    rows = []
    for p in me.polygons:
        mat = names[p.material_index] if names else ""
        nz = p.normal.z
        ground = nz > 0.9 and ("Concrete" in mat or p.center.z < GROUND_Z)     # slab, and paint / stains lying on it
        ln = max((me.vertices[a].co - me.vertices[b].co).length for a, b in p.edge_keys)
        fw = p.area / ln if ln > 0.0 else 0.0
        metal = 1.0 if any(k in mat for k in KW.METAL_MATS) else 0.0
        skip = "Lamp" in mat or "Signage" in mat
        for li in p.loop_indices:
            if skip or (not ground and sum(ao[4 * li:4 * li + 3]) <= 0.0):     # lamps, signs, glass: no wear
                out[4 * li:4 * li + 4] = (0.0, 0.0, 0.0, s)
                continue
            vi = me.loops[li].vertex_index
            co = me.vertices[vi].co
            over = None
            if abs(nz) < 0.5:
                hit = tree.ray_cast(co + p.normal * 0.02 + up * 0.01, up, KW.STREAK_M)
                over = hit[3] if hit[0] is not None else None
            rgba = KW.corner(co.z, nz, ao[4 * li + 3], convex[vi], over, metal, ground, s, co.x, co.y, fw)
            out[4 * li:4 * li + 4] = rgba
            rows.append(rgba)
    for ca in [c for c in me.color_attributes if c.name == LAYER]:
        me.color_attributes.remove(ca)
    ca = me.color_attributes.new(name=LAYER, type="BYTE_COLOR", domain="CORNER")
    ca.data.foreach_set("color", out)      # linear data, exported unchanged
    me.color_attributes.active_color = me.color_attributes["Col"]
    me.color_attributes.render_color_index = me.color_attributes.active_color_index
    return KW.stats(rows)
