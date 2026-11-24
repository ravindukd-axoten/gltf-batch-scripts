"""Delta Face skyline towers kit v2 (P103). Builds TOWER_KIT_A.blend: five towers and the skybridge, LOD0-2 each.

    blender -b -X --factory-startup -P tools/city/tower_kit/towers.py -- [--out tools/city/tower_kit/TOWER_KIT_A.blend]

Heights and storeys are measured (tools/city/config/measured_values.json r2.towers.heights_m, P98); spec and budgets in
TOWER_KIT_SPEC.md. Every tower is axis aligned around its own base centre; the city pipeline places and turns it.
Names follow data/world/names.json (tower.seaview, tower.green_court, tower.curve): fictional, no real brand.
"""
import json
import math
import pathlib
import sys

import bmesh
import bpy
from mathutils import Vector

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import towerlib as T  # noqa: E402

OUT_COLL = "Towers"
AD_SAFE = [0.06, 0.10]


# --- small part helpers -------------------------------------------------------------------------------------------
def cap(name, pts, z, row="SOFFIT", inset=0.0, down=False):
    """Flat roof / setback / soffit over a plan polygon, cut into strips one trim row tall along Y so every strip
    maps at true scale (128 px/m) instead of stretching the row over the whole roof. down=True faces -Z."""
    pts = T.scale_pts(pts, 1.0 - inset) if inset else pts
    if T.signed_area(pts) < 0:
        pts = list(reversed(pts))
    rh = T.ROWS[row][1]
    bm = bmesh.new()
    bm.faces.new([bm.verts.new((x, y, z)) for x, y in pts])
    ys = [p[1] for p in pts]
    y0, y1 = min(ys), max(ys)
    k = 1
    while y0 + k * rh < y1 - 0.05:
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-5, plane_co=(0, y0 + k * rh, z), plane_no=(0, 1, 0))
        k += 1
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    if down:
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    uv = bm.loops.layers.uv.new("UVMap")
    for fc in bm.faces:
        band = math.floor((fc.calc_center_median().y - y0) / rh)
        b0 = y0 + band * rh
        for l in fc.loops:
            l[uv].uv = T.row_uv(row, l.vert.co.x, l.vert.co.y - b0, rh)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def cut_top(me, z_low, z_high, half_x, row="SOFFIT"):
    """Oblique crown: cut the mesh by a plane rising along +X from z_low (x = -half_x) to z_high (x = +half_x) and cap
    the cut. The Curve Towers' sloped tops (photos 05-08 in map_refs_2026-11-16)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    slope = (z_high - z_low) / (2 * half_x)
    n = Vector((-slope, 0, 1)).normalized()
    co = Vector((0, 0, (z_low + z_high) / 2))
    geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
    bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-4, plane_co=co, plane_no=n, clear_outer=True)
    edges = [e for e in bm.edges if e.is_boundary and all(abs((v.co - co).dot(n)) < 1e-3 for v in e.verts)]
    res = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
    newf = res["faces"]
    if newf:
        bmesh.ops.triangulate(bm, faces=newf)
        uv = bm.loops.layers.uv.active
        tri = [f for f in bm.faces if abs(f.normal.dot(n)) > 0.999 and f.normal.z > 0]
        ys = [v.co.y for f in tri for v in f.verts] or [0, 1]
        for f in tri:
            for l in f.loops:
                l[uv].uv = T.row_uv(row, l.vert.co.x, l.vert.co.y - min(ys), max(ys) - min(ys))
    bm.to_mesh(me)
    bm.free()
    return me


def plant(prefix, boxes):
    """Roof plant: lift overrun, chillers, BMU track (cx, cy, z, sx, sy, sz, row)."""
    return [(T.box_mesh(f"{prefix}_{i}", (cx, cy, z + sz / 2), (sx, sy, sz), row), 0)
            for i, (cx, cy, z, sx, sy, sz, row) in enumerate(boxes)]


def ad(prefix, slot, center, w, h, yaw, out=0.12):
    me = T.quad_mesh(f"{prefix}_{slot}", center, w, h, yaw, out_offset=out)
    meta = {"slot_id": f"{prefix}.{slot}", "ad_slot_type": f"tower_{slot}", "aspect": "3:1", "safe_area": AD_SAFE,
            "size_m": [w, h], "district_hint": "delta_face", "default": "T_AdFace_BatchCityDev_3x1"}
    return (me, 1), meta


S = math.pi / 2  # yaw facing south is -S


# --- the towers -----------------------------------------------------------------------------------------------------
def seaview_a(lod):
    """Seaview Towers (tower.seaview), twin glass residential, 194 m, 51 storeys (P98 r2: 194 m, 51 floors).
    Square plan with re-entrant corner notches and a mid slot on two faces (gf_13, gf_14, map_refs 02, 08): a white
    frame of vertical lines and thin floor lines over dark glass; white corner frames; open white crown frame."""
    W, D = 34.0, 32.0
    plan = T.notched_rect(W, D, 3.0, 2.4, slot=(3.2, 1.4)) if lod < 2 else T.rect(W, D)
    parts, ads = [], []
    lobby_h, h, n = 8.0, 3.45, 50
    top = lobby_h + h * n  # 180.5
    fc = [1, 0, 0][lod]
    if lod < 2:
        parts.append((T.storeys_mesh(f"SV{lod}_lobby", plan, T.prof_lobby(lobby_h), 1, lobby_h, 0.0, 11, fr=0.4, fc=fc), 0))
        # gf_13 / gf_14: dark glass behind a white frame of vertical lines (every second bay), thin floor lines;
        # the balconies are recessed behind the frame, so the floor line is a shallow slab nose, not a deep balcony
        prof = T.prof_curtain(h, nose=0.15, inset=0.35, band=0.15) if lod == 0 else T.prof_flat(h, "GLASS", -0.1)  # v3: thin white floor line
        parts.append((T.storeys_mesh(f"SV{lod}_shaft", plan, prof, n, h, lobby_h, 12, fr=0.4, fc=fc), 0))
        parts.append((T.fins_mesh(f"SV{lod}_frame", plan, 9.6, 0.25, 0.2, lobby_h, top, 16, fr=0.4, fc=fc), 0))  # v3: every 3rd, slim
        tie = T.Profile("SV_Tie", [((-0.3, 0.0), (0.65, 0.0), "SOFFIT"), ((0.65, 0.0), (0.65, 0.3), "SLAB"),
                                   ((0.65, 0.3), (-0.3, 0.3), "SOFFIT")], 4 * h)
        parts.append((T.storeys_mesh(f"SV{lod}_ties", plan, tie, n // 4, 4 * h, lobby_h + 4 * h - 0.3, 17, fr=0.4, fc=fc), 0))
        # crown: a glazed plant storey, then an open white frame (posts + two ring beams) to 194 m
        parts.append((T.storeys_mesh(f"SV{lod}_crown", plan, T.prof_curtain(4.5, band=0.8), 1, 4.5, top, 13, fr=0.4, fc=fc), 0))
        z1 = top + 4.5
        parts.append((cap(f"SV{lod}_roof", plan, z1), 0))
        frame = T.scale_pts(T.rect(W - 1.0, D - 1.0), 1.0)
        parts.append((T.fins_mesh(f"SV{lod}_posts", frame, [4.1, 8.2][lod], 0.7, 0.7, z1 - 0.2, 194.0, 14, out=-0.35, fr=0, fc=0), 0))
        for zb in ([z1 + 4.4, 193.2] if lod == 0 else [193.2]):
            parts.append((T.storeys_mesh(f"SV{lod}_beam{zb:.0f}", frame, T.prof_flat(0.8, "SLAB"), 1, 0.8, zb, 15, fr=0, fc=0), 0))
        # white vertical corner frames at the notches (gf_13: bright corner edges up the full shaft)
        hx, hy = W / 2, D / 2
        for sx in (-1, 1):
            for sy in (-1, 1):
                for (cx, cy) in [((hx - 3.0) * sx, hy * sy), (hx * sx, (hy - 2.4) * sy)]:
                    parts.append((T.box_mesh(f"SV{lod}_cf{sx}{sy}{cx:.0f}", (cx, cy, (lobby_h + z1) / 2),
                                             (0.35, 0.35, z1 - lobby_h - 0.4), "SLAB"), 0))
        if lod == 0:
            parts += plant(f"SV{lod}_pl", [(0, 0, z1, 8, 6, 5.5, "METAL"), (-9, 5, z1, 6, 4, 2.8, "METAL"),
                                           (9, -5, z1, 6, 4, 2.8, "METAL"), (0, -9, z1, 14, 1.0, 1.2, "SOFFIT")])
            parts.append((T.box_mesh(f"SV{lod}_canopy", (0, -D / 2 - 2.0, 4.6), (12, 4.6, 0.45), "SLAB", bottom=True), 0))
        else:
            parts += plant(f"SV{lod}_pl", [(0, 0, z1, 8, 6, 5.5, "METAL")])
        p, m = ad("seaview_a", "crown", (0, -hy - 0.0, z1 + 2.2), 12.0, 4.0, -S, out=0.5)
        parts.append(p); ads.append(m)
        p, m = ad("seaview_a", "podium", (0, -hy - 0.6, 6.6), 9.0, 3.0, -S, out=0.2)
        parts.append(p); ads.append(m)
    else:
        parts.append((T.storeys_mesh("SV2_body", plan, T.prof_flat(4 * h, "GLASS"), (n + 2) // 4 + 1, 4 * h, 0.0, 12, fr=0, fc=0, far=True), 0))
        z1 = 4 * h * ((n + 2) // 4 + 1)
        parts.append((cap("SV2_roof", plan, z1), 0))
        parts.append((T.storeys_mesh("SV2_frame", T.rect(W - 1, D - 1), T.prof_flat(194.0 - z1, "SLAB"), 1, 194.0 - z1, z1, 15, fr=0, fc=0), 0))
        p, m = ad("seaview_a", "crown", (0, -D / 2, z1 - 3.0), 12.0, 4.0, -S, out=0.3)
        parts.append(p); ads.append(m)
    return parts, ads


def seaview_b(lod):
    """Seaview Towers B (tower.seaview; the old FinTower_B), glass office, 158-165 m, 32-35 storeys (P98 r2).
    Dark glass with white vertical fins on a 3.2 m rhythm (README 'dark glass with white vertical fins', map_refs
    03/04), chamfered corners, louvred plant crown set back."""
    W, D = 42.0, 30.0
    plan = [(-W / 2 + 2, -D / 2), (W / 2 - 2, -D / 2), (W / 2, -D / 2 + 2), (W / 2, D / 2 - 2), (W / 2 - 2, D / 2),
            (-W / 2 + 2, D / 2), (-W / 2, D / 2 - 2), (-W / 2, -D / 2 + 2)]
    parts, ads = [], []
    lobby_h, h, n = 10.0, 4.2, 34
    top = lobby_h + h * n  # 152.8
    if lod < 2:
        parts.append((T.storeys_mesh(f"SB{lod}_lobby", plan, T.prof_lobby(lobby_h), 1, lobby_h, 0.0, 21, fc=0), 0))
        parts.append((T.storeys_mesh(f"SB{lod}_shaft", plan, T.prof_curtain(h, nose=0.4, band=0.9) if lod == 0 else
                                     T.prof_flat(h, "GLASS", -0.1), n, h, lobby_h, 22, fc=0), 0))
        # v3: fewer, bolder fins (6.4 m, 1.0 x 1.5 m) over thick white floor bands: a bold grid, unlike Seaview A's
        # fine white verticals on black glass
        parts.append((T.fins_mesh(f"SB{lod}_fins", plan, 6.4, 1.0, 1.5, lobby_h, top + 1.0, 23, skip=0.0, fc=0), 0))
        crown = T.scale_pts(plan, 0.9)
        parts.append((T.storeys_mesh(f"SB{lod}_crown", crown, T.prof_flat(0.8, "LOUVRE"), 10, 0.8, top, 24, fc=0), 0))
        parts.append((cap(f"SB{lod}_roofA", plan, top), 0))
        parts.append((cap(f"SB{lod}_roofB", crown, top + 8.0), 0))
        if lod == 0:
            parts += plant("SB0_pl", [(-6, 0, top, 8, 6, 6.0, "METAL"), (8, 4, top, 7, 5, 3.0, "METAL"),
                                      (0, 0, top + 8.0, 6, 4, 3.0, "METAL")])
            parts.append((T.box_mesh("SB0_canopy", (0, -D / 2 - 2.5, 5.5), (14, 5.0, 0.5), "SLAB", bottom=True), 0))
        p, m = ad("seaview_b", "crown", (0, -D / 2 * 0.9, top + 4.0), 12.0, 4.0, -S, out=0.4)
        parts.append(p); ads.append(m)
        p, m = ad("seaview_b", "podium", (0, -D / 2 - 0.6, 7.8), 9.0, 3.0, -S, out=0.2)
        parts.append(p); ads.append(m)
    else:
        parts.append((T.storeys_mesh("SB2_body", T.rect(W, D), T.prof_flat(4 * h, "GLASS"), 9, 4 * h, 0.0, 22, fc=0, far=True), 0))
        parts.append((T.storeys_mesh("SB2_crown", T.rect(W * 0.9, D * 0.9), T.prof_flat(160.0 - 151.2, "LOUVRE"), 1, 160.0 - 151.2, 151.2, 24, fc=0), 0))
        parts.append((cap("SB2_roof", T.rect(W * 0.9, D * 0.9), 160.0), 0))
        p, m = ad("seaview_b", "crown", (0, -D / 2 * 0.9, 155.5), 12.0, 4.0, -S, out=0.3)
        parts.append(p); ads.append(m)
    return parts, ads


def green_court_a(lod):
    """Green Court Towers (tower.green_court; the old SlabHotel_A), hotel slab, 134 m, 32 storeys (P98 r2).
    White floor bands and pilasters over recessed dark glass, two stepped setbacks and a top frame (gf_13, map_refs 08)."""
    W, D = 46.0, 24.0
    plan = T.rect(W, D)
    parts, ads = [], []
    lobby_h, h, n = 7.0, 3.6, 30
    top = lobby_h + h * n  # 115
    t1, t2 = T.scale_pts(plan, 0.86, 0.82), T.scale_pts(plan, 0.68, 0.62)
    if lod < 2:
        fr, fc = (0.8, 1) if lod == 0 else (0.0, 0)
        parts.append((T.storeys_mesh(f"GC{lod}_lobby", plan, T.prof_lobby(lobby_h), 1, lobby_h, 0.0, 31, fr=fr, fc=fc), 0))
        parts.append((T.storeys_mesh(f"GC{lod}_shaft", plan, T.prof_grid(h, nose=1.0, inset=0.5, band=1.15) if lod == 0 else T.prof_curtain(h, 1.0, 0.5, 1.15),
                                     n, h, lobby_h, 32, fr=fr, fc=fc), 0))
        # v3: horizontals lead (gf_14): slim, grey pilasters every 7.2 m sit behind the deep white floor bands
        parts.append((T.fins_mesh(f"GC{lod}_pil", plan, [7.2, 14.4][lod], 0.4, 0.6, lobby_h, top, 33, row="SOFFIT", fr=fr, fc=fc), 0))
        parts.append((T.storeys_mesh(f"GC{lod}_t1", t1, T.prof_grid(3.0), 3, 3.0, top, 34, fr=fr, fc=fc), 0))
        parts.append((T.storeys_mesh(f"GC{lod}_t2", t2, T.prof_grid(3.5), 2, 3.5, top + 9.0, 35, fr=fr, fc=fc), 0))
        parts.append((T.storeys_mesh(f"GC{lod}_frame", t2, T.prof_flat(0.75, "SLAB", 0.3), 4, 0.75, top + 16.0, 36, fr=fr, fc=fc), 0))
        parts.append((cap(f"GC{lod}_r0", plan, top), 0))
        parts.append((cap(f"GC{lod}_r1", t1, top + 9.0), 0))
        parts.append((cap(f"GC{lod}_r2", t2, top + 16.0 + (0.0 if lod else 0.6)), 0))
        if lod == 0:
            parts += plant("GC0_pl", [(-10, 0, top, 6, 5, 3.0, "METAL"), (11, 2, top, 5, 4, 2.5, "METAL"),
                                      (0, 0, top + 16.6, 7, 4, 2.4, "METAL")])
            parts.append((T.box_mesh("GC0_porte", (0, -D / 2 - 4.0, 5.0), (16, 8.0, 0.6), "SLAB", bottom=True), 0))
        p, m = ad("green_court_a", "crown", (0, -D * 0.31, top + 12.5), 12.0, 4.0, -S, out=0.6)
        parts.append(p); ads.append(m)
        p, m = ad("green_court_a", "podium", (0, -D / 2 - 0.6, 5.6), 9.0, 3.0, -S, out=0.2)
        parts.append(p); ads.append(m)
    else:
        parts.append((T.storeys_mesh("GC2_body", plan, T.prof_flat(4 * h, "GLASS"), 8, 4 * h, 0.0, 32, fc=0, far=True), 0))
        parts.append((T.storeys_mesh("GC2_t1", t1, T.prof_flat(9.0, "GLASS"), 1, 9.0, 115.2, 34, fc=0, far=True), 0))
        parts.append((T.storeys_mesh("GC2_t2", t2, T.prof_flat(9.8, "SLAB"), 1, 9.8, 124.2, 35, fc=0), 0))
        for i, (pp, z) in enumerate([(plan, 115.2), (t1, 124.2), (t2, 134.0)]):
            parts.append((cap(f"GC2_r{i}", pp, z), 0))
        p, m = ad("green_court_a", "crown", (0, -D * 0.31, 128.0), 12.0, 4.0, -S, out=0.3)
        parts.append(p); ads.append(m)
    return parts, ads


def curve(lod, key, a, b, height, storeys, bulge, taper, seed, rise_x):
    """Curve Towers (tower.curve): rounded superellipse plan, wrap-around balconies, belly and taper, glazed crown cut
    by a sloping plane (map_refs 05-08, gf_08). rise_x = +1: the crown rises towards +X (towards the skybridge side)."""
    plan = T.oval(a, b, [44, 28, 16][lod], 2.5)
    parts, ads = [], []
    lobby_h, h = 9.0, 3.75
    top = lobby_h + h * storeys
    s_end = (1 + bulge * math.sin(math.pi)) * (1 - taper)
    pre = f"{key}{lod}"
    if lod < 2:
        parts.append((T.storeys_mesh(f"{pre}_lobby", plan, T.prof_lobby(lobby_h), 1, lobby_h, 0.0, seed, fc=0), 0))
        prof = T.prof_balcony(h, depth=1.1) if lod == 0 else T.prof_balcony_lod1(h, depth=1.1)
        parts.append((T.storeys_mesh(f"{pre}_shaft", plan, prof, storeys, h, lobby_h, seed + 1, bulge=bulge, taper=taper, fc=0), 0))
        crown_plan = T.scale_pts(plan, s_end)
        ch = height - top
        k = max(1, round(ch / 3.3))
        cm = T.storeys_mesh(f"{pre}_crown", crown_plan, T.prof_curtain(ch / k, band=0.35), k, ch / k, top, seed + 2, fc=0)
        lo, hi = (top + 1.2, height) if rise_x > 0 else (height, top + 1.2)
        parts.append((cut_top(cm, lo, hi, a * s_end + 2.0), 0))
        parts.append((cap(f"{pre}_roof", T.scale_pts(plan, s_end * 0.96), top + 0.6), 0))
        if lod == 0:
            parts += plant(f"{pre}_pl", [(-rise_x * a * 0.35, 0, top + 0.6, 6, 5, 3.0, "METAL")])
            parts.append((T.box_mesh(f"{pre}_canopy", (0, -b - 3.0, 5.0), (12, 6.0, 0.5), "SLAB", bottom=True), 0))
        p, m = ad(f"curve_{key[-1].lower()}", "crown", (0, -b * s_end - 0.2, top + 2.8), 12.0, 4.0, -S, out=0.3)
        parts.append(p); ads.append(m)
        p, m = ad(f"curve_{key[-1].lower()}", "podium", (0, -b - 0.6, 6.0), 9.0, 3.0, -S, out=0.2)
        parts.append(p); ads.append(m)
    else:
        g = 4
        parts.append((T.storeys_mesh(f"{pre}_body", plan, T.prof_flat(g * h, "GLASS"), storeys // g, g * h, lobby_h + h * (storeys % g),
                                     seed + 1, bulge=bulge, taper=taper, fc=0, far=True), 0))
        parts.append((T.storeys_mesh(f"{pre}_base", plan, T.prof_flat(lobby_h + h * (storeys % g), "STONE"), 1,
                                     lobby_h + h * (storeys % g), 0.0, seed, fc=0), 0))
        cm = T.storeys_mesh(f"{pre}_crown", T.scale_pts(plan, s_end), T.prof_flat(height - top, "GLASS"), 1, height - top, top, seed + 2, fc=0, far=True)
        lo, hi = (top + 1.2, height) if rise_x > 0 else (height, top + 1.2)
        parts.append((cut_top(cm, lo, hi, a * s_end + 2.0), 0))  # the cut cap closes the top; no roof under it
        p, m = ad(f"curve_{key[-1].lower()}", "crown", (0, -b * s_end, top + 2.8), 12.0, 4.0, -S, out=0.3)
        parts.append(p); ads.append(m)
    return parts, ads


def curve_a(lod):
    """Tall slender residential, 223-225 m, 55 storeys (P98 r2 itc_sapphire)."""
    return curve(lod, "CA", 21.0, 11.5, 225.0, 53, 0.07, 0.06, 41, +1)  # 55 floors incl. 2 in the crown


def curve_b(lod):
    """Hotel, 135-140 m, 29-33 storeys (P98 r2 itc_hotel); built at 138 m, 33 storeys."""
    return curve(lod, "CB", 20.0, 14.0, 138.0, 31, 0.05, 0.05, 51, -1)  # 33 floors incl. 2 in the crown


BRIDGE_L, BRIDGE_W, BRIDGE_H = 30.0, 16.0, 9.6  # agent 2026-11-19: real gap ~30 m; chunky two-storey box (map_refs 06, 08)
BRIDGE_FASCIA = 0.9  # solid dark slab band under and over the glazing


def bridge_storey(h):
    """Skybridge storey: thin dark floor band proud of recessed dark glazing (map_refs 08: a dark glazed box, no
    white floor lines; the white reads only as thin lips on the top and bottom fascia)."""
    return T.Profile(f"Bridge_{h:.2f}", [
        ((-0.4, 0.0), (0.2, 0.0), "SOFFIT"),
        ((0.2, 0.0), (0.2, 0.45), "METAL"),
        ((0.2, 0.45), (-0.4, 0.45), "SOFFIT"),
        ((-0.4, 0.45), (-0.4, h), "GLASS"),
    ], h)


def curve_bridge(lod):
    """Curve Towers skybridge, underside 100 m above ground (P98 r2 itc_skybridge_above_ground), 16 m wide, 13.6 m
    deep: 0.9 m dark fascia, two 3.9 m glazed storeys, 0.9 m fascia, thin white lips at the fascia edges.
    Built along X with 1.5 m embedded at each end; origin at its underside centre."""
    L = BRIDGE_L + 3.0
    plan = T.rect(L, BRIDGE_W)
    F, n, sh = BRIDGE_FASCIA, 2, (BRIDGE_H - 2 * BRIDGE_FASCIA) / 2
    parts = []
    if lod < 2:
        parts.append((T.storeys_mesh(f"BR{lod}_body", plan, bridge_storey(sh) if lod == 0 else T.prof_flat(sh, "GLASS"),
                                     n, sh, F, 61, fc=0), 0))
        fw = BRIDGE_W + 0.8
        parts.append((T.box_mesh(f"BR{lod}_fasciaB", (0, 0, F / 2), (L, fw, F), "METAL", top=False, bottom=True), 0))
        parts.append((T.box_mesh(f"BR{lod}_fasciaT", (0, 0, BRIDGE_H - F / 2), (L, fw, F), "METAL", top=True), 0))
        if lod == 0:
            for z in (F - 0.1, BRIDGE_H - F + 0.1, 0.1, BRIDGE_H - 0.1):  # thin white lips (map_refs 08)
                parts.append((T.box_mesh(f"BR0_lip{z:.1f}", (0, 0, z), (L, fw + 0.12, 0.2), "SLAB", top=False), 0))
            parts.append((T.fins_mesh("BR0_mull", plan, 3.2, 0.3, 0.3, F, BRIDGE_H - F, 62, row="METAL", fc=0), 0))
    else:
        parts.append((T.storeys_mesh("BR2_body", plan, T.prof_flat(BRIDGE_H, "GLASS"), 1, BRIDGE_H, 0.0, 61, fc=0, far=True), 0))
        parts.append((cap("BR2_roof", plan, BRIDGE_H), 0))
        parts.append((cap("BR2_under", plan, 0.0, down=True), 0))
    return parts, []


TOWERS = {
    # name: (builder, names.json id, height m, LODs)
    "BLD_SeaviewTower_A": (seaview_a, "tower.seaview", 194.0),
    "BLD_SeaviewTower_B": (seaview_b, "tower.seaview", 160.0),
    "BLD_GreenCourtTower_A": (green_court_a, "tower.green_court", 134.0),
    "BLD_CurveTower_A": (curve_a, "tower.curve", 225.0),
    "BLD_CurveTower_B": (curve_b, "tower.curve", 138.0),
    "BLD_CurveSkybridge_A": (curve_bridge, "tower.curve", BRIDGE_H),
}


# --- materials -----------------------------------------------------------------------------------------------------
def materials():
    tex = HERE / "textures"

    def img(name, non_color=False):
        im = bpy.data.images.load(str(tex / name), check_existing=True)
        if non_color:
            im.colorspace_settings.name = "Non-Color"
        return im

    mats = []
    m = bpy.data.materials.new("MAT_TowerTrim_A")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    base = nt.nodes.new("ShaderNodeTexImage")
    base.image = img("T_TowerTrim_A_BaseMap.png")
    mask = nt.nodes.new("ShaderNodeTexImage")
    mask.image = img("T_TowerTrim_A_MaskMap.png", True)
    emi = nt.nodes.new("ShaderNodeTexImage")
    emi.image = img("T_TowerTrim_A_Emission.png")
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = "Col"
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    nt.links.new(base.outputs["Color"], mul.inputs[6])
    nt.links.new(vc.outputs["Color"], mul.inputs[7])
    nt.links.new(mul.outputs[2], bsdf.inputs["Base Color"])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(mask.outputs["Alpha"], inv.inputs[1])
    nt.links.new(inv.outputs[0], bsdf.inputs["Roughness"])
    nt.links.new(emi.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 0.0  # 0 by day; dusk/night previews raise it
    mats.append(m)
    a = bpy.data.materials.new("MAT_AdFace_3x1")
    a.use_nodes = True
    at = a.node_tree
    ai = at.nodes.new("ShaderNodeTexImage")
    ai.image = img("T_AdFace_BatchCityDev_3x1.png")
    at.links.new(ai.outputs["Color"], at.nodes["Principled BSDF"].inputs["Base Color"])
    at.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.7
    mats.append(a)
    return mats


# LOD1/LOD2 lose the balcony and fin self-shadowing, so they render lighter than LOD0 at the same distance. Their
# COLOR_0 is scaled by these factors (calibrated with review_scene.py --mode lodcheck, golden hour, 450 m) so the
# switch does not pop. COLOR_0 = AO x far tint; the shader uses it as occlusion for diffuse and specular.
LOD_TINT = {"BLD_SeaviewTower_A": (1.17, 0.75),
            "BLD_SeaviewTower_B": (1.38, 0.86),
            "BLD_GreenCourtTower_A": (1.08, 0.98),
            "BLD_CurveTower_A": (0.97, 0.6),
            "BLD_CurveTower_B": (0.97, 0.59),
            "BLD_CurveSkybridge_A": (1.92, 0.46)}


def ao_remap(objs, glass_floor=0.6, solid_floor=0.3):
    """Raw vertex AO interpolated over long glass faces reads as dirt smears (critic pass 1). Keep the full range
    on soffits, fins and recesses but floor it on glass rows (v below the glass block) and on the ad faces."""
    glass_v = T.ROWS[T.GLASS_ROWS[-1]][0] + T.ROWS[T.GLASS_ROWS[-1]][1]
    for o in objs:
        me = o.data
        col = me.color_attributes["Col"].data
        uv = me.uv_layers[0].data
        for poly in me.polygons:
            vmin = min(uv[li].uv[1] for li in poly.loop_indices) * T.SHEET_H_M
            fl = 1.0 if poly.material_index == 1 else (glass_floor if vmin < glass_v - 1e-3 else solid_floor)
            for li in poly.loop_indices:
                r, g, b, a = col[li].color
                col[li].color = (fl + (1 - fl) * r, fl + (1 - fl) * g, fl + (1 - fl) * b, a)


def far_tint(objs):
    for o in objs:
        for lod in (1, 2):
            if o.name.endswith(f"_LOD{lod}"):
                k = LOD_TINT.get(o.name[: -5], (1.0, 1.0))[lod - 1]
                if k != 1.0:
                    col = o.data.color_attributes["Col"].data
                    for c in col:
                        r, g, b, a = c.color
                        c.color = (min(1.0, r * k), min(1.0, g * k), min(1.0, b * k), a)


def build_all(out, bake=True):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    mats = materials()
    report = {}
    objs = []
    for name, (fn, nid, height) in TOWERS.items():
        for lod in range(3):
            parts, ads = fn(lod)
            oname = name if lod == 0 else f"{name}_LOD{lod}"
            obj = T.join_meshes(oname, parts, OUT_COLL)
            for m in mats:
                obj.data.materials.append(m)
            T.shade(obj, 30.0)
            obj["name_id"] = nid
            obj["height_m"] = height
            if ads:
                obj["ad_slots"] = json.dumps(ads)
            if name == "BLD_CurveSkybridge_A":
                obj["mount_z_m"] = 100.0
                obj["span_m"] = BRIDGE_L
            objs.append(obj)
            report[oname] = T.tri_count(obj)
            print(f"{oname}: {report[oname]} tris")
    # lay the pieces out in a row for review (pieces are checked at their own origin by the validator: positions
    # are object locations only, meshes stay around their own base centre)
    x = 0.0
    for name in TOWERS:
        for lod in range(3):
            o = bpy.data.objects[name if lod == 0 else f"{name}_LOD{lod}"]
            o.location = (x, lod * 90.0, 0.0)
        x += 80.0
    # the GN generator objects all sit at the origin: keep them out of the AO bake (they would occlude the tower
    # standing there) and out of renders; they stay in the file as the editable generators
    src = bpy.data.collections[T.SRC]
    src.hide_render = True
    src.hide_viewport = True
    lc = bpy.context.view_layer.layer_collection.children[T.SRC]
    if bake:
        lc.exclude = True
        T.bake_ao_vertex(objs)
        ao_remap(objs)
        far_tint(objs)
        lc.exclude = False
    if out.exists():
        out.chmod(0o644)  # lockable LFS files check out read-only
    bpy.ops.wm.save_as_mainfile(filepath=str(out), relative_remap=True)
    (HERE / "export").mkdir(exist_ok=True)
    (HERE / "export" / "tris.json").write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = pathlib.Path(argv[argv.index("--out") + 1]) if "--out" in argv else HERE / "TOWER_KIT_A.blend"
    build_all(out, bake="--no-bake" not in argv)
