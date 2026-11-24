"""P295 B3: second leaf-card atlas T_Vegetation_Leaves_B (1024, 4 x 4 cells) for the species the first atlas has no room
for: flame tree (mara), banyan, red-season kottamba, croton, bougainvillea, flower beds, kerb weeds, beach creeper,
dune grass and wall creeper. Same painter and conventions as citylib/leaf_atlas.py (straight alpha, v up, the twig end of
a spray at v0, cut at 0.5 in SHD_Vegetation); a species draws from one leaf atlas only, so it stays one leaf material.

Painted procedurally here from the Canvas leaf/flower primitives (own work, no source images). Colours follow the
Delta Face photos (gf_05 shade trees, gf_20/gf_22 hotel beds and bougainvillea, gf_04 beach edge) and the Art Bible
palette (paddy green trees, saturated accents kept in the distance).
"""
from __future__ import annotations

import math

import numpy as np

from .leaf_atlas import Canvas, _dilate, _hex, _palette, paint_dense, paint_far, paint_rain, paint_rosettes

GRID = 4
CELLS = {
    "mara_a": (0, 3), "mara_b": (1, 3), "almond_red": (2, 3), "banyan_a": (3, 3),
    "croton_a": (0, 2), "croton_b": (1, 2), "bougain_a": (2, 2), "bougain_b": (3, 2),
    "marigold": (0, 1), "vinca": (1, 1), "weeds": (2, 1), "ipomoea": (3, 1),
    "dune": (0, 0), "creeper": (1, 0), "far_mara": (2, 0), "far_banyan": (3, 0),
}
SCARLET = [("#D8331F", "#F2B33A"), ("#E44A22", "#F5C04A"), ("#C9281C", "#EFA233")]
MAGENTA = [("#C8246E", "#F3E7B0"), ("#D9338A", "#F6EBC0"), ("#B21C63", "#EFE0A4")]


# P316 R3 leaf-card variety: half-width sub-cells (u range inside the parent cell), so one cell holds two different
# narrow sprays and neighbouring cards stop repeating one picture. Same material, same atlas size.
SUB = {"creeper_l": ("creeper", 0.0, 0.5), "creeper_r": ("creeper", 0.5, 1.0)}


def has(name: str) -> bool:
    return name in CELLS or name in SUB


def cell_uv(name: str, inset: float = 0.004) -> tuple[float, float, float, float]:
    if name in SUB:
        parent, a, b = SUB[name]
        c, r = CELLS[parent]
        return ((c + a) / GRID + inset, r / GRID + inset, (c + b) / GRID - inset, (r + 1) / GRID - inset)
    c, r = CELLS[name]
    return (c / GRID + inset, r / GRID + inset, (c + 1) / GRID - inset, (r + 1) / GRID - inset)


def _trusses(cv: Canvas, rng, n_trusses, cols, size=0.03, spread=0.08, per=(7, 11), petals=5, lo=0.35, hi=0.92):
    """Flower trusses on top of the foliage: n clusters of `per` flowers, biased to the upper (sunlit) part."""
    n = cv.n
    for _ in range(n_trusses):
        x, y = rng.uniform(0.14, 0.86) * n, rng.uniform(lo, hi) * n
        petal, centre = cols[rng.randrange(len(cols))]
        for _ in range(rng.randint(*per)):
            rr, aa = spread * n * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi)
            cv.flower(x + rr * math.cos(aa), y + rr * math.sin(aa) * 0.7, n * size * rng.uniform(0.85, 1.15),
                      _hex(petal) * rng.uniform(0.92, 1.03), _hex(centre), rng, petals)


def paint_mara(cv, rng, flowers):
    """Delonix regia: fine bipinnate fern sprays (like the rain tree's, a fresher green) under scarlet trusses."""
    paint_rain(cv, rng, _palette("#2D5A22", "#4E8A30", "#93BA4C"), pinnae=120)
    _trusses(cv, rng, flowers, SCARLET, size=0.034, spread=0.1)


def paint_croton(cv, rng, broad):
    """Codiaeum variegatum: stiff leathery leaves in rosettes, each leaf its own mix of deep green, gold, orange and
    crimson with a bright midrib (the variegation is what reads, not the leaf shape)."""
    n = cv.n
    cols = ["#2E5C26", "#C9A227", "#D9762A", "#B3322A", "#7A2A3A", "#9FB236"]
    twig = _hex("#5A4636")
    ros = [(rng.uniform(0.25, 0.75) * n, rng.uniform(0.3, 0.75) * n) for _ in range(5)]
    for x, y in ros:
        cv.leaf(0.5 * n, 0.02 * n, math.atan2(y - 0.02 * n, x - 0.5 * n), math.hypot(x - 0.5 * n, y - 0.02 * n), n * 0.008,
                twig, "stick", tip=0, rib=0, edge=0)
    for x, y in sorted(ros, key=lambda p: p[1]):
        k = rng.randint(7, 10)
        rot = rng.uniform(0, 2 * math.pi)
        for j in range(k):
            a = rot + 2 * math.pi * j / k + rng.uniform(-0.2, 0.2)
            c = _hex(rng.choice(cols)) * rng.uniform(0.88, 1.08)
            L = n * (0.2 if broad else 0.24) * rng.uniform(0.75, 1.1)
            cv.leaf(x, y, a, L, n * (0.05 if broad else 0.028), c, "ellipse" if broad else "lance", tip=0.3, rib=0.22,
                    edge=0.25)


def paint_ground(cv, rng, pal, blades, broad, cols=None, flowers=0, petals=5, size=0.028, blade_len=0.5):
    """Low ground cover card (base at v0): grass blades rising from the bottom edge, small leaves in a band above it,
    optional flowers on top (flower beds, kerb weeds, beach creeper, dune grass)."""
    n = cv.n
    for _ in range(blades):
        x = rng.uniform(0.06, 0.94) * n
        a = math.pi / 2 + rng.uniform(-0.5, 0.5)
        cv.leaf(x, 0.01 * n, a, n * blade_len * rng.uniform(0.45, 1.0), n * rng.uniform(0.008, 0.016),
                pal(rng.uniform(0.15, 0.95)), "blade", tip=0.25, rib=0.0, edge=0.1)
    for _ in range(broad):
        x, y = rng.uniform(0.08, 0.92) * n, rng.uniform(0.04, 0.42) * n
        cv.leaf(x, y, rng.uniform(0, 2 * math.pi), n * rng.uniform(0.05, 0.085), n * rng.uniform(0.025, 0.04),
                pal(0.2 + 0.7 * y / n + rng.uniform(-0.1, 0.1)), "ellipse", tip=0.15, rib=0.05, edge=0.25)
    if flowers:
        _trusses(cv, rng, flowers, cols, size=size, spread=0.035, per=(1, 3), petals=petals, lo=0.18, hi=0.5)


def _arc(p0, ctrl, p1, t):
    a = [(1 - t) ** 2 * p0[i] + 2 * (1 - t) * t * ctrl[i] + t * t * p1[i] for i in (0, 1)]
    return a[0], a[1]


def paint_bougain(cv, rng, canes, bract_share, leaf_pal, seed_side=0):
    """P316 R3 bougainvillea spray (gf_22, gf_25 hotel boundary): 2-3 thin canes arch out of the twig end (v0) and droop
    at the tips; alternate small leaves line the inner part, papery bract triplets crowd the outer half so the spray end
    is a magenta mass with leaves showing between, never a speckled green disc. The cut outline is ragged."""
    n = cv.n
    cane = _hex("#6A5A3E")
    bract_cols = ["#C8246E", "#D9338A", "#B21C63", "#E0479A", "#A8195A"]
    for k in range(canes):
        side = (1 if (k + seed_side) % 2 else -1) * rng.uniform(0.35, 1.0)
        p0 = (0.5 * n + rng.uniform(-0.06, 0.06) * n, 0.02 * n)
        top = (0.5 * n + side * rng.uniform(0.08, 0.2) * n, rng.uniform(0.86, 1.02) * n)
        p1 = (0.5 * n + side * rng.uniform(0.3, 0.4) * n, rng.uniform(0.3, 0.55) * n)   # the drooping tip
        ctrl = (top[0], top[1] + 0.12 * n)
        pts = [_arc(p0, ctrl, p1, t / 24) for t in range(25)]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            cv.leaf(x0, y0, math.atan2(y1 - y0, x1 - x0), math.hypot(x1 - x0, y1 - y0) + 1.5, n * 0.007, cane, "stick",
                    tip=0, rib=0, edge=0)
        for i in range(3, 25):
            x, y = pts[i]
            t = i / 24
            nx, ny = pts[min(24, i + 1)][0] - pts[i - 1][0], pts[min(24, i + 1)][1] - pts[i - 1][1]
            a = math.atan2(ny, nx)
            if t < 0.7 and i % 2 == 0:
                for s in (-1, 1):
                    if rng.random() < 0.8:
                        cv.leaf(x, y, a + s * rng.uniform(0.7, 1.2), n * rng.uniform(0.055, 0.08),
                                n * rng.uniform(0.024, 0.034), leaf_pal(rng.uniform(0.2, 0.9)), "ellipse", tip=0.2,
                                rib=0.06, edge=0.3)
            if t > 0.4 and rng.random() < bract_share:
                for _ in range(rng.randint(2, 4)):
                    cx, cy = x + rng.uniform(-1, 1) * n * 0.075, y + rng.uniform(-1, 1) * n * 0.075
                    col = _hex(rng.choice(bract_cols)) * rng.uniform(0.88, 1.06)
                    rot = rng.uniform(0, 2 * math.pi)
                    s = n * rng.uniform(0.036, 0.05)
                    for j in range(3):   # a bract triplet: three papery bracts round a cream floret
                        cv.leaf(cx, cy, rot + 2.094 * j, s, s * 0.62, col * rng.uniform(0.9, 1.05), "obovate", tip=0.12,
                                rib=0.03, edge=0.22)
                    cv.leaf(cx - s * 0.08, cy, rot, s * 0.22, s * 0.1, _hex("#F3E7B0"), "ellipse", tip=0, rib=0, edge=0)
            elif t > 0.6 and rng.random() < 0.35:
                cv.leaf(x, y, a + rng.choice((-1, 1)) * rng.uniform(0.6, 1.1), n * 0.05, n * 0.024,
                        leaf_pal(rng.uniform(0.4, 1.0)), "ellipse", tip=0.2, rib=0.05, edge=0.3)


def paint_creeper(cv, rng, runners, x_lo, x_hi):
    """P316 R3 creeping fig (Ficus pumila) runner strip in the cell's [x_lo, x_hi] band: runners wander up from the twig
    end, each lined with small overlapping leaves pressed flat (shingled), so a card reads as a vine with wall showing
    between runners, not a round clump. Two strips per cell = two card variants (SUB creeper_l / creeper_r)."""
    n = cv.n
    pal = _palette("#24502A", "#3E7A34", "#74A852")
    stem = _hex("#4E4A36")
    cx, span = (x_lo + x_hi) * 0.5, (x_hi - x_lo)
    for r in range(runners):
        x = (cx + (r - (runners - 1) / 2) * span * 0.3 + rng.uniform(-0.04, 0.04)) * n
        y = 0.02 * n
        top = rng.uniform(0.78, 0.96) * n
        drift = rng.uniform(-0.6, 0.6)
        while y < top:
            ny = y + n * rng.uniform(0.018, 0.028)
            xn = min(max(x + (drift + rng.uniform(-1.2, 1.2)) * n * 0.016, (x_lo + 0.12) * n), (x_hi - 0.12) * n)
            cv.leaf(x, y, math.atan2(ny - y, xn - x), math.hypot(xn - x, ny - y) + 1.0, n * 0.004, stem, "stick",
                    tip=0, rib=0, edge=0)
            for s in (-1, 1):
                if rng.random() < 0.85:
                    cv.leaf(x, y, math.pi / 2 + s * rng.uniform(0.9, 1.9), n * rng.uniform(0.055, 0.08),
                            n * rng.uniform(0.03, 0.042), pal(0.15 + 0.7 * rng.random() * (0.6 + 0.4 * y / n)), "obovate",
                            tip=0.25, rib=0.08, edge=0.35)
            x, y = xn, ny
            if rng.random() < 0.3:      # a side shoot: a short leafy spur
                a = math.pi / 2 + rng.choice((-1, 1)) * rng.uniform(0.8, 1.3)
                for j in range(3):
                    cv.leaf(x + math.cos(a) * n * 0.025 * j, y + math.sin(a) * n * 0.025 * j, a + rng.uniform(-0.6, 0.6),
                            n * 0.045, n * 0.025, pal(rng.uniform(0.3, 0.9)), "obovate", tip=0.25, rib=0.08, edge=0.35)


SPECS = {
    "mara_a": lambda cv, r: paint_mara(cv, r, 9),
    "mara_b": lambda cv, r: paint_mara(cv, r, 3),
    "almond_red": lambda cv, r: paint_rosettes(cv, r, _palette("#2B5428", "#4A8236", "#8AB04C"), 11, 7, cv.n * 0.115,
                                               cv.n * 0.042, "obovate", autumn=0.45),
    "banyan_a": lambda cv, r: paint_rosettes(cv, r, _palette("#1C4020", "#30652C", "#5A8C40"), 13, 7, cv.n * 0.1,
                                             cv.n * 0.05, "ellipse", spread=0.45),
    "croton_a": lambda cv, r: paint_croton(cv, r, True),
    "croton_b": lambda cv, r: paint_croton(cv, r, False),
    # P316 R3: arching cane sprays (a = leafier, two canes; b = bract-heavy, three canes) replace the B3 speckled discs
    "bougain_a": lambda cv, r: paint_bougain(cv, r, 4, 0.3, _palette("#24501F", "#3D7530", "#6E9E44"), 0),
    "bougain_b": lambda cv, r: paint_bougain(cv, r, 5, 0.7, _palette("#2A5522", "#447A32", "#73A046"), 1),
    "marigold": lambda cv, r: paint_ground(cv, r, _palette("#24481F", "#3B6E2D", "#6A9A43"), 30, 70,
                                           [("#F08A12", "#C9600A"), ("#F6B21C", "#D9861A")], flowers=16, petals=9,
                                           size=0.03, blade_len=0.3),
    "vinca": lambda cv, r: paint_ground(cv, r, _palette("#22471F", "#3A6E2C", "#62944A"), 0, 120,
                                        [("#E46FA8", "#B8336E"), ("#F4EEF2", "#D6487E"), ("#EE8FBE", "#C2407A")],
                                        flowers=22, petals=5, size=0.026),
    "weeds": lambda cv, r: paint_ground(cv, r, _palette("#4A5E2A", "#6F8A38", "#A9B25A"), 46, 14, blade_len=0.85),
    "ipomoea": lambda cv, r: paint_ground(cv, r, _palette("#2C5A22", "#4A8634", "#7FB04A"), 0, 110,
                                          [("#A65CC4", "#F2E7F4"), ("#B86CCF", "#F6EEF6")], flowers=10, petals=5, size=0.034),
    "dune": lambda cv, r: paint_ground(cv, r, _palette("#6F7A3A", "#A5A055", "#D6C98A"), 70, 0, blade_len=0.95),
    # P316 R3: two runner strips (left half = creeper_l, right half = creeper_r) instead of one lumpy leaf disc
    "creeper": lambda cv, r: (paint_creeper(cv, r, 2, 0.0, 0.5), paint_creeper(cv, r, 3, 0.5, 1.0)),
    "far_mara": lambda cv, r: (paint_far(cv, r, _palette("#2C5323", "#4C8032", "#8AAE4A"), 0.95, 0.4, 0.38, blobs=60,
                                         leaf=0.04), _trusses(cv, r, 14, SCARLET, size=0.022, spread=0.06, lo=0.55,
                                                              hi=0.82)),
    "far_banyan": lambda cv, r: paint_far(cv, r, _palette("#1F4421", "#356B30", "#62924A"), 0.98, 0.62, 0.32, blobs=70,
                                          leaf=0.04),
}
GROUND = {"marigold", "vinca", "weeds", "ipomoea", "dune"}   # base on the cell's bottom edge: no border fade there


def paint(size: int = 1024, supersample: int = 2, seed: int = 9595) -> np.ndarray:
    """RGBA float array (size, size, 4), v up, sRGB colour, straight alpha."""
    import random

    cell = size // GRID
    out = np.zeros((size, size, 4), np.float32)
    for i, (name, (c, r)) in enumerate(CELLS.items()):
        cv = Canvas(cell * supersample)
        SPECS[name](cv, random.Random(seed + i * 101))
        rgb, a = cv.down(supersample)
        e = np.minimum(np.arange(cell), np.arange(cell)[::-1]).astype(np.float32)
        border = np.clip((e - 2.0) / 10.0, 0.0, 1.0)
        rows = border.copy()
        if name in GROUND:
            rows[: cell // 2] = np.clip((np.arange(cell // 2) - 1.0) / 2.0, 0.0, 1.0)
        a = a * np.minimum(rows[:, None], border[None, :])
        rgb = _dilate(np.clip(rgb, 0, 1), a)
        out[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell, :3] = rgb
        out[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell, 3] = a
    return out


def coverage(atlas: np.ndarray, cutoff: float = 0.5) -> dict[str, float]:
    cell = atlas.shape[0] // GRID
    return {name: float((atlas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell, 3] >= cutoff).mean())
            for name, (c, r) in CELLS.items()}


if __name__ == "__main__":  # quick look: python3 -m citylib.leaf_atlas_b out.png (needs Pillow)
    import sys

    from PIL import Image

    img = paint()
    Image.fromarray((np.flipud(img) * 255).astype(np.uint8), "RGBA").save(sys.argv[1] if len(sys.argv) > 1 else "leaves_b.png")
    print({k: round(v, 2) for k, v in coverage(img).items()})
