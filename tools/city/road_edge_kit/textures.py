"""Compose T_RoadEdgeTrim_A (P92): 1024 x 2048 over 4 m x 8 m (256 px/m), URP map layout.

Inputs: the Blender bake of trim_high.py onto TRIM_Low (normal / ao / curvature, rows v 0-4 m) and the CC0 Poly
Haven scans used by tools/textures (concrete_floor_worn_001, asphalt_02, rusty_metal_02; fetched by
tools/textures/fetch_textures.py). Kerb A granite is the floor scan under a drawn salt-and-pepper grain (P92b: the old
concrete_wall_008 base showed form-tie holes). Upper half (v 4-8 m) is opaque road decals drawn here (masks from
noise), a grey 200 x 100 mm paver field (u 2.5-4.0, v 5.75-7.0: crossover ramps) and the paver border course row
(v 7.6-8.0).
Our own derived work; deterministic (fixed seeds).

    python3 tools/city/road_edge_kit/textures.py --bake <dir with TRIM_Low_*.png> [--source <tools/textures/source>]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "textures"))
import build_textures as bt  # noqa: E402

PX = 256
W, H = 1024, 2048
OUT = os.path.join(HERE, "textures")
ASPH = "#858480"


def vrow(v0, v1):
    """Image rows for sheet v metres [v0, v1) (image y runs down from v = 8 m)."""
    return slice(int(round((8.0 - v1) * PX)), int(round((8.0 - v0) * PX)))


def ucol(u0, u1):
    return slice(int(round(u0 * PX)), int(round(u1 * PX)))


def load(path, mode="RGB"):
    return np.asarray(Image.open(path).convert(mode), dtype=np.float32) / 255.0


def lerp(a, b, t):
    t = t[..., None] if (np.ndim(t) == 2 and np.ndim(a) == 3) else t
    return a + (b - a) * t


def vgrid(rows):
    """Per-pixel v (metres) for an image row slice, broadcast to (h, W)."""
    y = np.arange(rows.start, rows.stop, dtype=np.float32)
    return np.repeat((8.0 - (y + 0.5) / PX)[:, None], W, axis=1)


def ugrid(h):
    return np.repeat(((np.arange(W, dtype=np.float32) + 0.5) / PX)[None, :], h, axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bake", required=True)
    ap.add_argument("--source", default=None)
    a = ap.parse_args()
    if a.source:
        bt.SOURCE = a.source
    os.makedirs(OUT, exist_ok=True)
    nrm_b = load(os.path.join(a.bake, "TRIM_Low_normal.png"))
    ao_b = load(os.path.join(a.bake, "TRIM_Low_ao.png"), "L")
    cv_b = load(os.path.join(a.bake, "TRIM_Low_curvature.png"), "L")

    col = np.zeros((H, W, 3), np.float32)
    nrm = np.zeros((H, W, 3), np.float32)
    nrm[...] = (0.5, 0.5, 1.0)
    ao = np.ones((H, W), np.float32)
    sm = np.full((H, W), 0.2, np.float32)
    metal = np.zeros((H, W), np.float32)
    low = vrow(0.0, 4.0)
    nrm[low], ao[low] = nrm_b, ao_b
    curv = np.full((H, W), 0.5, np.float32)
    curv[low] = cv_b

    # CC0 bases at true scale over the whole sheet
    floor = bt.tiled("concrete_floor_worn_001", "diff", W, H, 4.0, 8.0)
    floor_n = bt.tiled("concrete_floor_worn_001", "nor_gl", W, H, 4.0, 8.0)
    asph = bt.tiled("asphalt_02", "diff", W, H, 4.0, 8.0)
    asph_n = bt.tiled("asphalt_02", "nor_gl", W, H, 4.0, 8.0)
    rust = bt.tiled("rusty_metal_02", "diff", W, H, 4.0, 8.0)
    big = bt.tile_noise(H, W, 180, 7)            # 0.7 m blotches
    mid = bt.tile_noise(H, W, 40, 8)
    fine = bt.tile_noise(H, W, 6, 9, octaves=2)
    edge = np.clip((curv - 0.5) * 4.0, 0, 1)     # convex arrises from the curvature bake
    cav = np.clip((0.5 - curv) * 4.0, 0, 1)
    dirt = np.clip(1.0 - ao, 0, 1)

    def surface(rows, base, target, contrast=1.0, sat=0.6):
        col[rows] = bt.grade(base[rows], target, contrast, sat)

    # --- kerbs: v is distance along the profile from the buried toe (0.05 toe, 0.15 face, ~0.05 nose, 0.25 top)
    for key, v0, tgt, smooth in (("A", 0.0, "#BEBBB2", 0.22), ("B", 0.5, "#C4BFB3", 0.18), ("C", 1.0, "#A29F97", 0.2)):
        r = vrow(v0, v0 + 0.5)
        surface(r, floor, tgt, 0.85 if key == "A" else 0.8, 0.45)   # P92b: calmer, pale weathered grey (sv_03, sv_05);
        # CIRCLE fix 2: A / B lifted about 12 % so the face reads against #858480 asphalt at driver eye (sv_04, sv_15)
        if key == "A":                              # granite grain: dark mica, pale quartz / feldspar, 2-8 mm
            col[r] = _granite(col[r], r)
        pv = vgrid(r) - v0                         # metres along the profile
        foot = bt.smoothstep(0.10, 0.04, pv)       # road grime at the foot, splash up the face
        nose = np.exp(-((pv - 0.215) / 0.03) ** 2)  # nose rubbed by tyres and feet
        top = bt.smoothstep(0.24, 0.30, pv) * bt.smoothstep(0.47, 0.42, pv)
        c = col[r]
        if key == "C":                              # painted black / white bands 0.5 m, worn through on the nose
            u = ugrid(c.shape[0])
            white = (np.floor(u / 0.5) % 2) == 0
            paint = np.where(white[..., None], bt.hex_rgb("#E4E1D8"), bt.hex_rgb("#252423"))
            # crisp bands; paint lost only as small chips on the nose and arrises and under the foot grime
            chips = (fine[r] > 0.72).astype(np.float32) * np.clip((mid[r] - 0.4) * 5.0, 0, 1)
            wear = np.clip(chips * (nose * 1.5 + edge[r] * 2.0) + foot * 0.6, 0, 1)
            wear = np.where(wear > 0.5, 1.0, wear * 0.3)
            c = lerp(paint * (0.95 + 0.08 * fine[r][..., None]), c, wear)
            sm[r] = np.where(wear > 0.5, 0.18, 0.32)
        else:
            sm[r] = smooth + 0.12 * nose + 0.06 * top
        c = c * (1 - 0.35 * foot[..., None] * (0.6 + 0.4 * big[r][..., None]))
        c = c * (1 + 0.10 * nose[..., None] + 0.08 * edge[r][..., None])
        c = c * (1 - 0.45 * dirt[r][..., None])   # joints and chips
        if key != "C":                              # per-block tint and a few stained blocks (0.5 m / 1.0 m units)
            bid = np.floor(ugrid(c.shape[0]) / (1.0 if key == "B" else 0.5)).astype(np.int64)
            h1 = (bid * 2654435761 % 997) / 997.0
            h2 = (bid * 40503 % 991) / 991.0
            tint = 0.97 + 0.06 * h1                 # P92b: per-block tone within about 6 % (was 18 %, read as patchwork)
            warm = np.stack([1.0 + 0.012 * h2, 1.0 + 0.004 * h2, 1.0 - 0.012 * h2], -1)
            stain = np.where(h2 > 0.9, 0.92 + 0.05 * big[r], 1.0)
            c = c * (tint * stain)[..., None] * warm
        col[r] = c
    # --- channel 0.36 m (road edge at v 1.53, kerb side at v 1.89), asphalt fade above
    r = vrow(1.5, 2.0)
    surface(r, floor, "#B3AC9E", 0.75, 0.5)
    pv = vgrid(r) - 1.5
    edge_grime = np.exp(-((pv - 0.035) / 0.03) ** 2) * (0.5 + 0.5 * big[r])   # dirt where channel meets asphalt
    col[r] = col[r] * (1 - 0.35 * edge_grime[..., None])
    kside = bt.smoothstep(0.30, 0.39, pv)
    sand = np.clip(kside * (0.4 + big[r]) + (mid[r] - 0.6) * 1.5 * kside, 0, 1)
    c = lerp(col[r], bt.hex_rgb("#BDB29C") * (0.9 + 0.2 * fine[r][..., None]), sand * 0.8)
    wet = np.exp(-((pv - 0.37) / 0.012) ** 2) * (0.5 + 0.5 * big[r])
    c = c * (1 - 0.3 * wet[..., None]) * (1 - 0.4 * dirt[r][..., None])
    fade = bt.smoothstep(0.39, 0.42, pv)
    c = lerp(c, _road_band("BaseMap")[: r.stop - r.start], fade)     # meets the road texture
    col[r] = c
    sm[r] = 0.18 + 0.1 * wet
    # --- footway slabs: per-slab tint, stains, two cracked slabs, black sealant in the expansion joints
    r = vrow(2.0, 3.0)
    surface(r, floor, "#A09C93", 0.8, 0.5)
    u, v = ugrid(r.stop - r.start), vgrid(r)
    sid = (np.floor(u / 0.5) + 13 * np.floor((v - 2.0) / 0.5)).astype(np.int64)
    tint = 0.92 + 0.12 * ((sid * 2654435761) % 1000 / 1000.0)
    stains = np.clip((big[r] - 0.58) * 3.0, 0, 1) * 0.15
    gum = (fine[r] > 0.83).astype(np.float32) * 0.35
    c = col[r] * tint[..., None] * (1 - stains[..., None]) * (1 - gum[..., None] * 0.5)
    c = c * (1 - 0.5 * dirt[r][..., None])
    sealant = (np.abs(((u + 0.006) % 2.0) - 0.006) < 0.007) & (dirt[r] > 0.15)
    c[sealant] = bt.hex_rgb("#2E2C2A")
    col[r] = c
    sm[r] = 0.16 + 0.1 * stains
    cracks = _cracks(r.stop - r.start, 2, seed=31, region=((0.5, 1.0), (2.5, 3.0)), v0=2.0)
    col[r] *= (1 - 0.55 * cracks[..., None])
    nrm[r] = bt.blend_normals(nrm[r], bt.height_to_normal(-cracks * 0.6, 3.0))
    # --- tiles row: concrete surrounds, cast iron covers / grates, tactile yellow
    r = vrow(3.0, 4.0)
    surface(r, floor, "#9C988F", 1.0, 0.5)
    col[r] *= (1 - 0.5 * dirt[r][..., None])[...]
    iron_mask = _iron_mask(r)
    iron = bt.grade(rust[r], "#34312D", 0.9, 0.6)   # CIRCLE fix 2: darker mouth (was #4A4540)
    iron = lerp(iron, bt.hex_rgb("#6E6A63"), np.clip(edge[r] * 2.0, 0, 1))   # polished raised pattern
    iron = iron * (1 - 0.6 * dirt[r][..., None])
    col[r] = lerp(col[r], iron, iron_mask)
    metal[r] = iron_mask * np.clip(0.25 + edge[r] * 1.2, 0, 0.85)
    sm[r] = lerp(sm[r], 0.28 + 0.35 * edge[r], iron_mask)
    tac = np.zeros_like(iron_mask)
    tac[:, ucol(3.0, 3.8)] = 1.0
    tac[: int(0.2 * PX), :] = 0.0                  # tactile region is v 3.0-3.8
    yellow = bt.hex_rgb("#C9A43C") * (0.85 + 0.2 * mid[r][..., None])
    yellow = lerp(yellow, bt.hex_rgb("#A8A296"), np.clip(edge[r] * 1.5 + (big[r] - 0.55) * 2.0, 0, 0.8))
    col[r] = lerp(col[r], yellow * (1 - 0.4 * dirt[r][..., None]), tac)
    # --- decals (v 4-8 m): opaque, edges fade to plain sheet asphalt
    _decals(col, nrm, sm, ao, asph, asph_n, big, mid, fine)
    # --- grey concrete pavers 200 x 100 mm, stretcher bond along u: crossover field and border course row
    pav_mask = np.zeros((H, W), bool)
    for (u0, u1, v0, v1, seed) in ((2.5, 4.0, 5.75, 7.0, 81), (0.0, 4.0, 7.6, 8.0, 82)):
        rr, cc = vrow(v0, v1), ucol(u0, u1)
        pc, pn, ps, pa = _pavers(rr, cc, v0 + 0.05, seed, floor, big, mid, fine)
        col[rr, cc], nrm[rr, cc], sm[rr, cc], ao[rr, cc] = pc, pn, ps, pa
        pav_mask[rr, cc] = True

    # tiles row: high-pass the baked normal (ray-cast slope across the big covers is not real surface)
    t = vrow(3.0, 4.0)
    for ch in (0, 1):
        nrm[t, :, ch] = np.clip(0.5 + nrm[t, :, ch] - _blur(nrm[t, :, ch], 20), 0, 1)
    nrm[t, :, 2] = np.sqrt(np.clip(1 - ((nrm[t, :, 0] - 0.5) * 2) ** 2 - ((nrm[t, :, 1] - 0.5) * 2) ** 2, 0, 1)) * 0.5 + 0.5
    # detail normals from the scans, gentle, everywhere except iron
    detail = np.where(((vgrid(slice(0, H)) >= 4.0) & ~pav_mask)[..., None], np.float32((0.5, 0.5, 1.0)), floor_n)
    nrm = bt.blend_normals(nrm, bt.normal_scale(detail, 0.6))
    ao = np.clip(ao * (0.85 + 0.15 * bt.tile_noise(H, W, 30, 11)), 0, 1)
    col = np.clip(col, 0.03, 0.9)
    written = []
    for nm, arr in (("BaseMap", col), ("NormalMap", nrm),
                    ("MaskMap", np.stack([metal, ao, np.ones_like(ao), np.clip(sm, 0, 0.8)], -1))):
        img = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA" if arr.shape[2] == 4 else "RGB")
        p = os.path.join(OUT, f"T_RoadEdgeTrim_A_{nm}.png")
        img.save(p, optimize=True)
        written.append(p)
    print("\n".join(written))


def _granite(c, r):
    """Weathered granite grain over the scan: about 5 % dark mica, 18 % pale quartz / feldspar, grains 2-8 mm."""
    h = r.stop - r.start
    g1 = bt.tile_noise(h, W, 1.4, 41, octaves=2)
    g2 = bt.tile_noise(h, W, 2.2, 42, octaves=2)
    g3 = bt.tile_noise(h, W, 3.0, 43, octaves=2)
    dark = bt.smoothstep(np.quantile(g1, 0.94), np.quantile(g1, 0.965), g1)
    pale = bt.smoothstep(np.quantile(g2, 0.80), np.quantile(g2, 0.85), g2)
    pink = bt.smoothstep(np.quantile(g3, 0.90), np.quantile(g3, 0.93), g3)
    c = c * (1 - 0.2 * dark[..., None])
    c = lerp(c, c * 1.12 + 0.02, pale * 0.35)
    return lerp(c, c * np.float32((1.06, 1.0, 0.96)), pink * 0.35)


def _pavers(rr, cc, vbase, seed, floor, big, mid, fine, period_u=None):
    """Grey concrete pavers 200 x 100 mm in stretcher bond along u, 3 mm sanded joints, 4 mm chamfers. Tone ids repeat
    every 1 m in u inside the crossover field (1 m pieces) and every 4 m in the border row, so tiling has no seam."""
    h, w = rr.stop - rr.start, cc.stop - cc.start
    u, v = ugrid(h)[:, cc], vgrid(rr)[:, cc]
    rowf = (v - vbase) / 0.1
    row = np.floor(rowf)
    y = (rowf - row) * 0.1
    off = (row % 2) * 0.1
    x = (u + off) % 0.2
    e = np.minimum(np.minimum(x, 0.2 - x), np.minimum(y, 0.1 - y))
    width = cc.stop - cc.start
    per = int(round((period_u or (4.0 if width >= 4 * PX else 1.0)) / 0.2))
    cid = np.floor((u + off) / 0.2).astype(np.int64) % per
    pid = (cid * 73856093 + row.astype(np.int64) * 19349663 + seed * 83492791) % 1000003
    h1 = (pid * 2654435761 % 1009) / 1009.0
    h2 = (pid * 40503 % 997) / 997.0
    tone = 0.92 + 0.10 * h1                                # P92b: calm grey course, half the old spread
    tone = np.where(h2 > 0.95, 0.85, tone)                 # oil-darkened or older pavers
    base = bt.grade(floor[rr, cc], "#ADA89E", 1.0, 0.35)   # CIRCLE fix 2: was #8F8C86, asphalt's value
    base = base * (tone * (0.95 + 0.1 * fine[rr, cc]))[..., None]
    base = np.where((h2 < 0.04)[..., None], base * np.float32((1.04, 1.02, 0.985)), base)   # newer, buff replacements
    cham = bt.smoothstep(0.0015, 0.0055, e)
    joint = e < 0.0016
    col = base * (0.72 + 0.28 * cham)[..., None]
    col[joint] = bt.hex_rgb("#8F8778") * 0.62
    dust = np.clip((big[rr, cc] - 0.55) * 2.0, 0, 0.45) * (1 - cham * 0.5)
    col = lerp(col, bt.hex_rgb("#B8AE9A") * (0.92 + 0.15 * fine[rr, cc][..., None]), dust)
    nrm = bt.height_to_normal(cham * 0.12 - joint * 0.05, 4.0)
    ao = 0.5 + 0.5 * cham
    sm = 0.13 + 0.07 * h1 - 0.05 * dust
    return col, nrm, sm.astype(np.float32), ao.astype(np.float32)


def _blur(a, rad):
    """Three-pass box blur (about Gaussian, sigma ~ rad), edges clamped."""
    for _ in range(3):
        for ax in (0, 1):
            p = np.pad(a, [(rad + 1, rad)] * 1 + [(0, 0)] if ax == 0 else [(0, 0), (rad + 1, rad)], mode="edge")
            c = np.cumsum(p, axis=ax)
            a = ((c[2 * rad + 1:] - c[:-2 * rad - 1]) if ax == 0 else (c[:, 2 * rad + 1:] - c[:, :-2 * rad - 1])) / (2 * rad + 1)
    return a


def _iron_mask(r):
    """Cast iron areas in the tiles row, from pieces.TILE (kept in sync by hand: covers, grates)."""
    h = r.stop - r.start
    m = np.zeros((h, W), np.float32)
    u, v = ugrid(h), vgrid(r)
    d = np.hypot(u - 0.5, v - 3.5)
    m[d < 0.352] = 1.0                                   # round cover
    sq = (np.abs(u - 1.5) < 0.35) & (np.abs(v - 3.5) < 0.35)
    m[sq] = 1.0                                          # chequer cover + frame
    m[(np.abs(u - 2.35) < 0.30) & (np.abs(v - 3.18) < 0.15)] = 1.0     # gully
    fr = (np.abs(u - 2.35) < 0.30) & (np.abs(v - 3.68) < 0.30) & ~((np.abs(u - 2.35) < 0.27) & (np.abs(v - 3.68) < 0.27))
    m[fr] = 1.0                                          # tray frame
    m[(np.abs(u - 3.90) < 0.075) & (np.abs(v - 3.5) < 0.5)] = 1.0      # slot grate
    return m


def _cracks(h, n, seed, region, v0):
    """Thin branching crack lines (random walks) as a 0..1 mask over rows of height h, inside the u/v boxes."""
    rng = np.random.default_rng(seed)
    m = np.zeros((h, W), np.float32)
    for (u0, u1) in [region[0]] if n == 1 else list(region):
        x, y = rng.uniform(u0, u1) * PX, rng.uniform(0.05, 0.45) * PX
        ang = rng.uniform(0, np.pi)
        if n == 1:                                   # one long crack along u near the bottom of the rows
            x, y, ang = 0.0, h - 0.12 * PX, rng.normal(0, 0.1)
        base = ang
        for _ in range(int(0.9 * PX)):
            ang += rng.normal(0, 0.06) - 0.02 * np.sin(ang - base)   # wander, pulled back to the base heading
            x, y = x + np.cos(ang), y + np.sin(ang)
            xi, yi = int(x) % W, int(y) % h
            m[yi, xi] = 1.0
            if rng.random() < 0.004:
                ang += rng.choice([-1, 1]) * 0.9
    k = np.array([[0.2, 0.5, 0.2], [0.5, 1.0, 0.5], [0.2, 0.5, 0.2]], np.float32)
    from numpy.lib.stride_tricks import sliding_window_view as sw
    p = np.pad(m, 1, mode="wrap")
    return np.clip((sw(p, (3, 3)) * k).sum(axis=(-1, -2)), 0, 1)


def _decals(col, nrm, sm, ao, asph, asph_n, big, mid, fine):
    r = vrow(4.0, 8.0)
    h = r.stop - r.start
    # background = the game's own road texture (T_Asphalt, 4.0 x 3.5 m lane), its kerb-side 1 m band mirror-tiled,
    # so an opaque decal's faded edge meets the same grain, tone, AO and gloss as the road it lies on
    bg = {k: _road_band(k) for k in ("BaseMap", "NormalMap", "MaskMap")}
    col[r] = bg["BaseMap"]
    sm[r] = bg["MaskMap"][..., 3]
    ao_bg = bg["MaskMap"][..., 1]
    asph = _asph_full(h)
    u, v = ugrid(h), vgrid(r)
    hgt = np.zeros((h, W), np.float32)

    def box_mask(u0, v0, w, hh, feather=0.08, jag=0.0, seed=0):
        du = np.minimum(u - u0, u0 + w - u)
        dv = np.minimum(v - v0, v0 + hh - v)
        d = np.minimum(du, dv)
        if jag:
            d = d + (bt.tile_noise(h, W, 20, seed) - 0.5) * jag
        return np.clip(d / feather, 0, 1)

    def put(mask, colour, smooth=None, height=None):
        col[r] = lerp(col[r], colour, mask)
        if smooth is not None:
            sm[r] = lerp(sm[r], smooth, mask)
        if height is not None:
            hgt[...] = hgt + height * mask

    newer = bt.grade(asph, "#4F4D4A", 1.25, 0.25)       # fresh hot-mix: darker, coarser than the worn road
    # rectangular patches (sawn edges) and the trench reinstatement strip, sealed with a glossy bitumen overband
    # 50-60 mm wide that wanders over the saw cut (what makes a patch read from the driver's seat)
    for (u0, v0, w, hh, seed) in ((0.0, 4.75, 1.2, 0.8, 1), (1.2, 4.75, 2.0, 1.0, 2), (0.0, 7.0, 4.0, 0.6, 3)):
        inner = box_mask(u0 + 0.1, v0 + 0.1, w - 0.2, hh - 0.2, 0.003)
        band = box_mask(u0 + 0.045, v0 + 0.045, w - 0.09, hh - 0.09, 0.006, jag=0.05, seed=20 + seed)
        seal = np.clip(band - box_mask(u0 + 0.105, v0 + 0.105, w - 0.21, hh - 0.21, 0.006, jag=0.04, seed=30 + seed),
                       0, 1)
        put(inner, newer * (0.93 + 0.14 * big[r][..., None]), 0.2, 0.004)
        put(seal * 0.8, bt.hex_rgb("#252423") * (0.9 + 0.2 * fine[r][..., None]), 0.55, 0.0015)
    # irregular patch (hand-laid cold mix): noisy outline, lumpy
    cu, cv = 0.75, 6.35
    rr = np.hypot((u - cu) / 0.6, (v - cv) / 0.48) + (bt.tile_noise(h, W, 25, 4) - 0.5) * 0.5
    irr = np.clip((1.0 - rr) / 0.06, 0, 1) * box_mask(0.0, 5.75, 1.5, 1.2, 0.05)
    put(irr, bt.grade(asph[r], "#55534F", 1.3, 0.3), 0.2, 0.004 * (0.5 + mid[r]))
    # crazing (alligator cracks): Voronoi cell edges in 1 x 1 m, fading out at the borders
    vor = _voronoi_edges(h, (1.5, 5.75), 1.0, 0.12, seed=5)
    fadec = box_mask(1.5, 5.75, 1.0, 1.0, 0.25)
    put(vor * fadec * 0.9, bt.hex_rgb("#3A3936"), None, -0.004)
    # long crack along the channel joint (4 m strip)
    cr = _cracks(h, 1, 6, ((0.0, 4.0), (0.0, 4.0)), 4.0)
    cr = cr * box_mask(0.0, 4.0, 4.0, 0.25, 0.05)
    put(cr, bt.hex_rgb("#2F2E2C"), None, -0.004)
    # kerb-side dust / sea sand drift: strongest at the kerb edge (top of the strip)
    dm = box_mask(0.0, 4.25, 4.0, 0.5, 0.25) * bt.smoothstep(4.3, 4.75, v) * (0.5 + 0.8 * (big[r] - 0.3))
    put(np.clip(dm, 0, 1) * 0.85, bt.hex_rgb("#B8AE9A") * (0.9 + 0.2 * fine[r][..., None]), 0.12, 0.0)
    # oil: drip cluster under a parked tuk, not a disc. Multiplied into the asphalt (grain shows through), darkest at
    # the drops, a stronger rim where the oil wicked out, satellite drips, glossy centre
    rng = np.random.default_rng(12)
    drops = [(3.58, 5.06, 0.17, 0.11, 1.0)] + [(3.58 + rng.normal(0, 0.12), 5.06 + rng.normal(0, 0.08),
                                                 rng.uniform(0.02, 0.07), rng.uniform(0.02, 0.05),
                                                 rng.uniform(0.5, 0.9)) for _ in range(9)]
    om = np.zeros((h, W), np.float32)
    rim = np.zeros((h, W), np.float32)
    wob = (bt.tile_noise(h, W, 6, 13) - 0.5) * 1.1 + (mid[r] - 0.5) * 0.6   # ragged, wicked-out edge
    for (cu, cv, ru, rv, k) in drops:
        d = np.hypot((u - cu) / ru, (v - cv) / rv) + wob
        om = np.maximum(om, k * np.clip((1.0 - d) / 0.35, 0, 1))
        rim = np.maximum(rim, k * np.exp(-((d - 0.92) / 0.08) ** 2))
    om = om * box_mask(3.2, 4.75, 0.8, 0.6, 0.06)
    rim = rim * box_mask(3.2, 4.75, 0.8, 0.6, 0.06)
    halo = np.clip(np.exp(-np.hypot((u - 3.58) / 0.3, (v - 5.06) / 0.22) ** 2) * (0.6 + 0.6 * (big[r] - 0.5)), 0, 1)
    halo = halo * box_mask(3.2, 4.75, 0.8, 0.6, 0.12) * np.clip((big[r] - 0.3) * 2.0, 0, 1)   # broken, not an ellipse
    tint = np.float32((1.0, 0.96, 0.9))
    dark = np.clip(0.12 * halo + 0.62 * om ** 0.7 + 0.22 * rim, 0, 0.8)   # absorbed, darkest at the drops
    col[r] = col[r] * (1.0 - dark[..., None]) * lerp(np.ones(3, np.float32), tint, np.clip(om + halo, 0, 1)[..., None])
    sm[r] = lerp(sm[r], 0.62, np.clip(om * 1.2, 0, 1))
    nrm[r] = bt.blend_normals(bg["NormalMap"], bt.height_to_normal(hgt * 40.0, 6.0))
    ao[r] = ao_bg * (1.0 - np.clip(-hgt * 60.0, 0, 0.4))


ROAD_TEX = os.path.join(REPO, "unity", "BatchIsland", "Assets", "BatchIsland", "Art", "World", "Textures")


def _road_band(kind):
    """T_Asphalt_<kind> at 256 px/m (1024 x 896 over 4.0 x 3.5 m); its bottom 1 m (kerb side) mirror-tiled to 1024 rows."""
    im = Image.open(os.path.join(ROAD_TEX, f"T_Asphalt_{kind}.png"))
    im = im.convert("RGBA" if kind == "MaskMap" else "RGB").resize((W, int(3.5 * PX)), Image.LANCZOS)
    a = np.asarray(im, dtype=np.float32) / 255.0
    band = a[-PX:]
    flip = band[::-1].copy()
    if kind == "NormalMap":
        flip[..., 1] = 1.0 - flip[..., 1]          # mirrored in v: flip the green (v) slope
    return np.concatenate([flip, band, flip, band], axis=0)


def _asph_full(h):
    return _road_band("BaseMap")[:h]


def _voronoi_edges(h, origin, size, cell, seed):
    rng = np.random.default_rng(seed)
    n = int((size / cell) ** 2 * 1.3)
    pts = rng.uniform(0, size, (n, 2)) + np.array(origin)
    u, v = ugrid(h), vgrid(slice(0, h))  # v recomputed below
    v = 8.0 - (np.arange(h, dtype=np.float32)[:, None] + 0.5) / PX + 0 * u
    sel = (u >= origin[0] - 0.05) & (u < origin[0] + size + 0.05) & (v >= origin[1] - 0.05) & (v < origin[1] + size + 0.05)
    out = np.zeros((h, W), np.float32)
    uu, vv = u[sel], v[sel]
    d = np.sqrt((uu[:, None] - pts[None, :, 0]) ** 2 + (vv[:, None] - pts[None, :, 1]) ** 2)
    d.sort(axis=1)
    gap = d[:, 1] - d[:, 0]
    out[sel] = np.clip(1.0 - gap / 0.006, 0, 1)
    return out


if __name__ == "__main__":
    main()
