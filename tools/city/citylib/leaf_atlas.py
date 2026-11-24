"""Leaf-card atlas for the alpha-tested canopy material (SLICE4a, agent h08-h16): painted leaf sprays with alpha.

Pure numpy (runs in Blender's Python and the system one). Every spray is painted at 2x and box-filtered down, leaf
by leaf: an analytic leaf outline (ellipse, obovate or lance) with a soft 1 px edge, a lighter tip, darker margins
and a pale midrib, composited back to front. Each spray carries its own tonal gradient (lower and inner leaves
darker, top and rim leaves lighter and yellower) so a card cluster already reads as a lit clump before the shader's
canopy AO. Transparent texels get the spray's dilated colour so mips do not fringe dark. Fixed seeds: the same
atlas on every build. No photos or source images (Art Bible "World materials": CC0 or our own).

Layout: a 4 x 4 grid of cells, v up (row 0 at the bottom). CELLS maps a name to (column, row).
"""
from __future__ import annotations

import math

import numpy as np

GRID = 4
CELLS = {
    "rain_a": (0, 3), "rain_b": (1, 3), "broad_a": (2, 3), "broad_b": (3, 3),
    "frangi_a": (0, 2), "frangi_b": (1, 2), "young_a": (2, 2), "young_b": (3, 2),
    "hedge_a": (0, 1), "hedge_b": (1, 1), "spill_a": (2, 1), "ixora_a": (3, 1),
    "spider": (0, 0), "far_rain": (1, 0), "far_broad": (2, 0), "far_bush": (3, 0),
    "palm_frond": (0, 0),
}
# SLICE4c: cells shared by several entries, split across u (fraction of the cell width). The spider-plant strap
# swatch is opaque and only needs a narrow strip; the rest holds the palm frond card (V-folded pinnate frond, rachis
# at the strip centre, base at v0, tip at v1) used by the card-crown palms.
SPLIT = {"spider": (0.0, 0.25), "palm_frond": (0.25, 1.0)}


def cell_uv(name: str, inset: float = 0.004) -> tuple[float, float, float, float]:
    """(u0, v0, u1, v1) of a cell, inset a little so bilinear filtering never reads the neighbour."""
    c, r = CELLS[name]
    f0, f1 = SPLIT.get(name, (0.0, 1.0))
    return ((c + f0) / GRID + inset, r / GRID + inset, (c + f1) / GRID - inset, (r + 1) / GRID - inset)


def _hex(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], np.float32)


class Canvas:
    """RGBA float canvas, y up, painted with soft-edged leaf shapes."""

    def __init__(self, size: int):
        self.n = size
        self.rgb = np.zeros((size, size, 3), np.float32)
        self.a = np.zeros((size, size), np.float32)

    def leaf(self, x, y, ang, length, width, col, shape="ellipse", tip=0.18, rib=0.07, edge=0.18):
        """A leaf from its base (x, y) along angle `ang` (radians, 0 = +x). Sizes in canvas pixels."""
        ca, sa = math.cos(ang), math.sin(ang)
        r = length + width + 2
        x0, x1 = max(0, int(x - r)), min(self.n, int(x + r) + 1)
        y0, y1 = max(0, int(y - r)), min(self.n, int(y + r) + 1)
        if x0 >= x1 or y0 >= y1:
            return
        gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        dx, dy = gx + 0.5 - x, gy + 0.5 - y
        s = (dx * ca + dy * sa) / max(length, 1e-3)
        t = -dx * sa + dy * ca
        sc = np.clip(s, 0.0, 1.0)
        if shape == "obovate":      # widest beyond the middle (tropical almond, frangipani young leaves)
            hw = width * 1.55 * np.sqrt(sc) * (1.0 - sc) ** 0.55
        elif shape == "lance":      # long, pointed both ends (frangipani)
            hw = width * np.maximum(np.sin(np.pi * sc), 0.0) ** 0.85 * (1.0 - 0.25 * sc)
        elif shape == "stick":      # twig
            hw = np.full_like(sc, width)
        elif shape == "blade":      # strap tapering to a point (spider plant, grass)
            hw = width * (1.0 - sc) ** 0.7
        else:
            hw = width * np.sqrt(np.clip(1.0 - (2.0 * sc - 1.0) ** 2, 0.0, 1.0))
        inside = (s >= 0.0) & (s <= 1.0)
        cov = np.clip(hw - np.abs(t) + 0.5, 0.0, 1.0) * inside
        if not cov.any():
            return
        rel = np.abs(t) / np.maximum(hw, 1e-3)
        shade = (1.0 - tip * 0.5) + tip * sc                      # lighter towards the tip
        shade = shade * (1.0 - edge * rel ** 2)                   # darker margins
        c = np.asarray(col, np.float32)[None, None, :] * shade[..., None]
        if rib > 0 and shape not in ("stick",):
            c = c + rib * (np.abs(t) < max(0.8, width * 0.08))[..., None]
        sl = (slice(y0, y1), slice(x0, x1))
        self.rgb[sl] = self.rgb[sl] * (1.0 - cov[..., None]) + c * cov[..., None]
        self.a[sl] = self.a[sl] + cov * (1.0 - self.a[sl])

    def flower(self, x, y, size, petal, centre, rng, petals=5):
        rot = rng.uniform(0, 2 * math.pi)
        for k in range(petals):
            a = rot + 2 * math.pi * k / petals
            self.leaf(x, y, a, size, size * 0.42, petal, "obovate", tip=0.05, rib=0.0, edge=0.1)
        self.leaf(x - size * 0.12, y, 0.0, size * 0.24, size * 0.16, centre, "ellipse", tip=0.0, rib=0.0, edge=0.0)

    def down(self, f: int) -> tuple[np.ndarray, np.ndarray]:
        n = self.n // f
        rgb = (self.rgb * self.a[..., None]).reshape(n, f, n, f, 3).mean(axis=(1, 3))
        a = self.a.reshape(n, f, n, f).mean(axis=(1, 3))
        rgb = rgb / np.maximum(a[..., None], 1e-4)
        return rgb, a


def _mix(c0, c1, t):
    return c0 * (1.0 - t) + c1 * t


def _palette(dark, mid, light):
    d, m, l = _hex(dark), _hex(mid), _hex(light)

    def col(t):
        t = min(1.0, max(0.0, t))
        return _mix(d, m, t * 2) if t < 0.5 else _mix(m, l, t * 2 - 1)
    return col


def _tone(x, y, n, cx=0.5, cy=0.5, rad=0.45):
    """Spray tone 0..1 at canvas (x, y): lower and inner darker, top and rim lighter."""
    u, v = x / n, y / n
    r = math.hypot(u - cx, v - cy) / rad
    return 0.15 + 0.55 * v + 0.3 * min(1.0, r)


def _lumpy(rng, n, cx=0.5, cy=0.5, rad=0.44, lobes=6, amp=0.16):
    """Lumpy disc test for spray outlines: a polar radius with random lobes."""
    ph = [rng.uniform(0, 2 * math.pi) for _ in range(3)]

    def inside(x, y):
        u, v = x / n - cx, y / n - cy
        a = math.atan2(v, u)
        rr = rad * (1.0 + amp * (math.sin(lobes * a + ph[0]) * 0.6 + math.sin((lobes + 3) * a + ph[1]) * 0.4))
        return math.hypot(u, v) <= rr
    return inside


def paint_rain(cv: Canvas, rng, pal, pinnae=150):
    """Rain tree (Samanea): fine bipinnate foliage. Twigs from the base, pinnae of paired small leaflets."""
    n = cv.n
    inside = _lumpy(rng, n, 0.5, 0.54, 0.35, 5, 0.2)
    twig = _hex("#5B4A3B")
    pts = []
    while len(pts) < pinnae:
        x, y = rng.uniform(0.06, 0.94) * n, rng.uniform(0.08, 0.96) * n
        if inside(x, y):
            pts.append((x, y))
    pts.sort(key=lambda p: _tone(p[0], p[1], n))       # dark first, light on top
    base = (0.5 * n, 0.02 * n)
    for x, y in pts[:: max(1, len(pts) // 7)]:
        cv.leaf(base[0], base[1], math.atan2(y - base[1], x - base[0]), math.hypot(x - base[0], y - base[1]) * 0.85,
                n * 0.004, twig * 0.9, "stick", tip=0, rib=0, edge=0)
    for x, y in pts:
        t = _tone(x, y, n) + rng.uniform(-0.18, 0.18)
        ang = math.atan2(y - n * 0.45, x - n * 0.5) + rng.uniform(-0.9, 0.9)
        L = n * rng.uniform(0.09, 0.14)
        ca, sa = math.cos(ang), math.sin(ang)
        cv.leaf(x, y, ang, L, n * 0.003, twig, "stick", tip=0, rib=0, edge=0)
        pairs = 7
        for k in range(pairs):
            f = (k + 0.6) / pairs
            px, py = x + ca * L * f, y + sa * L * f
            ll = n * 0.03 * (1.0 - 0.3 * f)
            for side in (-1, 1):
                a2 = ang + side * rng.uniform(0.9, 1.25)
                c = pal(t + rng.uniform(-0.08, 0.08)) * rng.uniform(0.9, 1.08)
                cv.leaf(px, py, a2, ll, ll * 0.42, c, "ellipse", tip=0.2, rib=0.02, edge=0.25)


def paint_rosettes(cv: Canvas, rng, pal, count, leaves, length, width, shape, spread=0.42, autumn=0.0,
                   flowers=0, petal="#F6F1E4", centre="#F0C24A", cy=0.5):
    """Broad-leaf sprays: twigs from the base to `count` rosettes of radiating leaves (almond, frangipani, young)."""
    n = cv.n
    inside = _lumpy(rng, n, 0.5, cy, spread, 4, 0.2)
    twig = _hex("#5E4D3D")
    ros = []
    tries = 0
    while len(ros) < count and tries < 4000:
        tries += 1
        x, y = rng.uniform(0.2, 0.8) * n, rng.uniform(0.22, 0.8) * n
        if inside(x, y) and all(math.hypot(x - a, y - b) > length * 0.75 for a, b in ros):
            ros.append((x, y))
    ros.sort(key=lambda p: _tone(p[0], p[1], n))
    base = (0.5 * n, 0.02 * n)
    for x, y in ros:
        cv.leaf(base[0], base[1], math.atan2(y - base[1], x - base[0]), math.hypot(x - base[0], y - base[1]),
                n * 0.007, twig, "stick", tip=0, rib=0, edge=0)
    for i, (x, y) in enumerate(ros):
        t0 = _tone(x, y, n)
        k = leaves + rng.randint(-1, 2)
        rot = rng.uniform(0, 2 * math.pi)
        order = sorted(range(k), key=lambda j: math.sin(rot + 2 * math.pi * j / k))   # lower leaves first
        for j in order:
            a = rot + 2 * math.pi * j / k + rng.uniform(-0.25, 0.25)
            L = length * rng.uniform(0.75, 1.15)
            c = pal(t0 + 0.12 * math.sin(a) + rng.uniform(-0.15, 0.15)) * rng.uniform(0.9, 1.08)
            if autumn and rng.random() < autumn:
                c = _hex(rng.choice(["#B5582E", "#C98A3A"]))
            cv.leaf(x, y, a, L, width * rng.uniform(0.85, 1.15), c, shape, tip=0.22, rib=0.08, edge=0.2)
    # SLICE4c: flower heads last (on top of every rosette's leaves), a dense cream truss at the whorl centre of the
    # upper rosettes, big enough to read as white specks at 25 m on Low (agent h09, h10, h15)
    for i, (x, y) in enumerate(sorted(ros, key=lambda p: -p[1])[:flowers]):
        for _ in range(rng.randint(9, 13)):
            rr, aa = length * 0.32 * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi)
            cv.flower(x + rr * math.cos(aa), y + rr * math.sin(aa) * 0.8 + length * 0.08, n * rng.uniform(0.032, 0.04),
                      _hex(petal) * rng.uniform(0.94, 1.0), _hex(centre), rng)


def paint_dense(cv: Canvas, rng, pal, count, length, width, square=True, flowers=0, flower_cols=None, petals=5):
    """Clipped-hedge / bush texture: many small leaves filling a ragged rounded square (or a lumpy disc)."""
    n = cv.n
    inside = _lumpy(rng, n, 0.5, 0.5, 0.47, 7, 0.07) if not square else (
        lambda x, y: max(abs(x / n - 0.5), abs(y / n - 0.5)) < 0.47 - 0.03 * math.sin(x * 0.05) * math.cos(y * 0.07))
    pts = []
    while len(pts) < count:
        x, y = rng.uniform(0.0, 1.0) * n, rng.uniform(0.0, 1.0) * n
        if inside(x, y):
            pts.append((x, y, rng.random()))
    pts.sort(key=lambda p: p[2])                       # depth order: back (dark) to front (light)
    for x, y, d in pts:
        t = 0.1 + 0.55 * d + 0.25 * (y / n) + rng.uniform(-0.1, 0.1)
        cv.leaf(x, y, rng.uniform(0, 2 * math.pi), length * rng.uniform(0.8, 1.2), width * rng.uniform(0.85, 1.15),
                pal(t) * rng.uniform(0.92, 1.06), "ellipse", tip=0.15, rib=0.04, edge=0.3)
    cols = flower_cols or [("#F6F1E4", "#F0C24A")]
    for _ in range(flowers):
        x, y = rng.uniform(0.12, 0.88) * n, rng.uniform(0.3, 0.92) * n
        petal, centre = cols[rng.randrange(len(cols))]
        for _ in range(rng.randint(5, 9)):
            cv.flower(x + rng.uniform(-1, 1) * n * 0.04, y + rng.uniform(-1, 1) * n * 0.04, n * rng.uniform(0.017, 0.024),
                      _hex(petal) * rng.uniform(0.9, 1.0), _hex(centre), rng, petals)


def paint_far(cv: Canvas, rng, pal, width_frac, height_frac, base_frac, blobs=40, leaf=0.03):
    """Distance card: a lumpy canopy mass (union of clumps, sky gaps between some) with a short trunk stub."""
    n = cv.n
    clumps = []
    for _ in range(blobs):
        a = rng.uniform(0, math.pi)
        r = rng.uniform(0.0, 1.0) ** 0.6
        x = 0.5 + math.cos(a) * r * width_frac * 0.5
        y = base_frac + height_frac * (0.25 + 0.55 * math.sin(a) * r + rng.uniform(-0.1, 0.15))
        clumps.append((x * n, y * n, n * rng.uniform(0.06, 0.11)))
    trunk = _hex("#4D4136")
    cv.leaf(0.5 * n, 0.0, math.pi / 2, base_frac * n + n * 0.1, n * 0.025, trunk, "stick", tip=0, rib=0, edge=0.3)
    pts = []
    for cx, cy, cr in clumps:
        for _ in range(int(cr * cr / (n * leaf) ** 2 * 1.6)):
            rr, aa = cr * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi)
            pts.append((cx + rr * math.cos(aa), cy + rr * math.sin(aa), rr / cr))
    pts.sort(key=lambda p: p[1] - p[2] * n * 0.05)
    for x, y, rr in pts:
        t = 0.05 + 0.75 * ((y / n) - base_frac) / height_frac + 0.2 * rr + rng.uniform(-0.12, 0.12)
        cv.leaf(x, y, rng.uniform(0, 2 * math.pi), n * leaf, n * leaf * 0.45, pal(t), "ellipse", tip=0.1, rib=0, edge=0.3)


def paint_spider(cv: Canvas):
    """Opaque variegated strap swatch (spider plant / chlorophytum, agent h08): u runs across the blade."""
    n = cv.n
    u = (np.arange(n, dtype=np.float32) + 0.5) / n
    stripe = np.clip(1.0 - np.abs(u - 0.5) / 0.16, 0.0, 1.0) ** 0.6
    edge = np.abs(u - 0.5) * 2
    green = _hex("#4F8A33") * (1.0 - 0.25 * edge[:, None])
    cream = _hex("#E6E4C2")
    row = green * (1 - stripe[:, None]) + cream * stripe[:, None]
    v = (np.arange(n, dtype=np.float32) + 0.5) / n
    cv.rgb[:] = row[None, :, :] * (0.78 + 0.3 * v)[:, None, None]
    cv.a[:] = 1.0


def paint_frond(cv: Canvas, rng, pal, per_side=34):
    """Coconut frond (SLICE4c card crowns, agent h08, h16, gf_14): a yellow-green rachis up the centre (base at the
    bottom), bare petiole for the first 13 %, then narrow lance leaflets on both sides swept towards the tip, longest
    at mid frond, a few torn gaps and browned tips. Painted in a square canvas and squashed into the 0.75-wide strip."""
    n = cv.n
    rach = _hex("#9C9A4E")
    y0, y1 = 0.13 * n, 0.985 * n
    leaflets = []
    for side in (-1, 1):
        gaps = {rng.randrange(per_side) for _ in range(3)}
        for k in range(per_side):
            if k in gaps:
                continue
            f = (k + rng.uniform(0.2, 0.8)) / per_side
            y = y0 + (y1 - y0) * f
            prof = math.sin(math.pi * (0.06 + 0.9 * f)) ** 0.6
            L = n * 0.5 * (0.28 + 0.72 * prof) * rng.uniform(0.9, 1.04)
            ang = math.pi / 2 - side * math.radians(62 - 22 * f + rng.uniform(-5, 5))   # out and towards the tip
            leaflets.append((rng.random(), side, y, ang, L, f))
    leaflets.sort(key=lambda q: q[0])
    for d, side, y, ang, L, f in leaflets:
        c = pal(0.25 + 0.5 * d + 0.25 * f + rng.uniform(-0.1, 0.1)) * rng.uniform(0.92, 1.06)
        if rng.random() < 0.08:
            c = _hex("#A08A45") * rng.uniform(0.9, 1.05)
        cv.leaf(n * 0.5 + side * n * 0.006, y, ang, L, n * rng.uniform(0.011, 0.014), c, "lance", tip=0.25, rib=0.05,
                edge=0.25)
    cv.leaf(n * 0.5, n * 0.0, math.pi / 2, n * 0.99, n * 0.011, rach, "blade", tip=0.1, rib=0.0, edge=0.2)


def _dilate(rgb: np.ndarray, a: np.ndarray, steps: int = 24) -> np.ndarray:
    """Spread opaque colours into transparent texels (mips stay leaf-coloured at the silhouette)."""
    w = (a > 0.02).astype(np.float32)
    acc = rgb * w[..., None]
    out = rgb.copy()
    known = w.copy()
    for _ in range(steps):
        s = np.zeros_like(acc)
        k = np.zeros_like(known)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            s += np.roll(np.roll(acc, dy, 0), dx, 1)
            k += np.roll(np.roll(known, dy, 0), dx, 1)
        new = (known == 0) & (k > 0)
        acc[new] = s[new] / k[new][:, None]
        known[new] = 1.0
    mean = (rgb * w[..., None]).sum((0, 1)) / max(1.0, w.sum())
    acc[known == 0] = mean
    out[a <= 0.02] = acc[a <= 0.02]
    return out


SPECS = {
    "rain_a": lambda cv, r: paint_rain(cv, r, _palette("#2C5524", "#4F8233", "#8DAF4B")),
    "rain_b": lambda cv, r: paint_rain(cv, r, _palette("#2F5A25", "#557F30", "#97B34F"), pinnae=135),
    "broad_a": lambda cv, r: paint_rosettes(cv, r, _palette("#28502A", "#477F35", "#86AF4A"), 12, 7, cv.n * 0.11,
                                            cv.n * 0.04, "obovate", autumn=0.04),
    "broad_b": lambda cv, r: paint_rosettes(cv, r, _palette("#2B5528", "#4C8636", "#8CB24E"), 10, 8, cv.n * 0.12,
                                            cv.n * 0.042, "obovate", autumn=0.02),
    "frangi_a": lambda cv, r: paint_rosettes(cv, r, _palette("#2A5C2B", "#447A36", "#79A44A"), 4, 9, cv.n * 0.23,
                                             cv.n * 0.05, "lance", flowers=4),
    "frangi_b": lambda cv, r: paint_rosettes(cv, r, _palette("#2C5F2C", "#477D37", "#7DA74B"), 4, 10, cv.n * 0.22,
                                             cv.n * 0.048, "lance", flowers=3),
    "young_a": lambda cv, r: paint_rosettes(cv, r, _palette("#3A6A2C", "#5E953B", "#A3C45A"), 14, 7, cv.n * 0.085,
                                            cv.n * 0.032, "obovate", spread=0.44),
    "young_b": lambda cv, r: paint_rosettes(cv, r, _palette("#3D6E2D", "#62993D", "#A8C85E"), 11, 6, cv.n * 0.09,
                                            cv.n * 0.034, "obovate", spread=0.4),
    "hedge_a": lambda cv, r: paint_dense(cv, r, _palette("#22471F", "#3A6E2C", "#6C9C42"), 1500, cv.n * 0.05, cv.n * 0.022),
    "hedge_b": lambda cv, r: paint_dense(cv, r, _palette("#24491F", "#3E722E", "#74A146"), 1300, cv.n * 0.055,
                                         cv.n * 0.024, square=False),
    "spill_a": lambda cv, r: paint_dense(cv, r, _palette("#24501F", "#3D7530", "#6E9E44"), 700, cv.n * 0.085,
                                         cv.n * 0.032, square=False, flowers=6),
    "ixora_a": lambda cv, r: paint_dense(cv, r, _palette("#22491F", "#386C2C", "#5E8F3E"), 1000, cv.n * 0.06,
                                         cv.n * 0.025, square=False, flowers=12,
                                         flower_cols=[("#D9362B", "#C2271F"), ("#E8552F", "#D23A22")], petals=4),
    "spider": lambda cv, r: paint_spider(cv),
    "palm_frond": lambda cv, r: paint_frond(cv, r, _palette("#2E5A22", "#4F8A2E", "#9BBE4E")),
    "far_rain": lambda cv, r: paint_far(cv, r, _palette("#2A4F23", "#4B7B32", "#86A84A"), 0.92, 0.42, 0.4, blobs=60, leaf=0.04),
    "far_broad": lambda cv, r: paint_far(cv, r, _palette("#294F25", "#467C35", "#82AA4A"), 0.78, 0.58, 0.3, blobs=55, leaf=0.04),
    "far_bush": lambda cv, r: paint_dense(cv, r, _palette("#24491F", "#3C712E", "#6A9A43"), 900, cv.n * 0.07,
                                          cv.n * 0.03, square=False),
}


def paint(size: int = 1024, supersample: int = 2, seed: int = 4242) -> np.ndarray:
    """RGBA float array (size, size, 4), v up, sRGB colour, straight alpha."""
    import random

    cell = size // GRID
    out = np.zeros((size, size, 4), np.float32)
    for i, (name, (c, r)) in enumerate(CELLS.items()):
        cv = Canvas(cell * supersample)
        SPECS[name](cv, random.Random(seed + i * 101))
        rgb, a = cv.down(supersample)
        if name != "spider":
            e = np.minimum(np.arange(cell), np.arange(cell)[::-1]).astype(np.float32)
            border = np.clip((e - 2.0) / 10.0, 0.0, 1.0)
            a = a * np.minimum(border[:, None], border[None, :])
        rgb = _dilate(np.clip(rgb, 0, 1), a)
        x0, x1 = 0, cell
        if name in SPLIT:   # squash the square painting across u into its strip (box filter)
            f0, f1 = SPLIT[name]
            x0, x1 = int(round(f0 * cell)), int(round(f1 * cell))
            src = (np.arange(x1 - x0) + 0.5) * cell / (x1 - x0)
            idx = np.clip(src.astype(int), 0, cell - 1)
            rgb, a = rgb[:, idx], a[:, idx]
        out[r * cell:(r + 1) * cell, c * cell + x0:c * cell + x1, :3] = rgb
        out[r * cell:(r + 1) * cell, c * cell + x0:c * cell + x1, 3] = a
    return out


def coverage(atlas: np.ndarray, cutoff: float = 0.5) -> dict[str, float]:
    """Fraction of each cell that survives the alpha test (for the overdraw estimate)."""
    cell = atlas.shape[0] // GRID
    out = {}
    for name, (c, r) in CELLS.items():
        f0, f1 = SPLIT.get(name, (0.0, 1.0))
        x0, x1 = c * cell + int(round(f0 * cell)), c * cell + int(round(f1 * cell))
        out[name] = float((atlas[r * cell:(r + 1) * cell, x0:x1, 3] >= cutoff).mean())
    return out


if __name__ == "__main__":  # quick look: python3 -m citylib.leaf_atlas out.png (needs Pillow)
    import sys

    from PIL import Image

    img = paint()
    Image.fromarray((np.flipud(img) * 255).astype(np.uint8), "RGBA").save(sys.argv[1] if len(sys.argv) > 1 else "leaves.png")
    print({k: round(v, 2) for k, v in coverage(img).items()})
