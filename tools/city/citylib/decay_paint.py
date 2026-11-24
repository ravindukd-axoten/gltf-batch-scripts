"""Wear and decay layer, texture side: age a clean atlas cell into its weathered (wear 1) and old (wear 2) variants,
and paint the shared decals (fictional posters, footing patches). Pillow + numpy, seeded, same output every run.

`age(img, wear, seed, ppm, kind, mask, bolts)`:
  kind "sheeting"  retro-reflective sign film: sun bleach (reds fade to salmon first, blues and greens to chalky
                   pastel), dust film, road-grime gradient at the bottom, rain streaks from the top edge and bolts,
                   rust streaks from bolts (wear 2), scratches, crazed / cracked film and peeled patches showing the
                   aluminium (wear 2), bird dirt, algae in the bottom corners, softened text edges.
  kind "metal"     galvanised or painted steel / aluminium (sign backs, posts): dust, streaks, rust spots and blooms,
                   splash grime at the bottom, white zinc bloom.
  kind "paint"     painted bands (black / white posts, kerbs): chalking, chips down to the metal, rust in the chips.
  kind "concrete"  footings, kerbs: dirt, stains, algae at the bottom.
mask: float array (h, w), 1 where the surface is (outside keeps the clean pixels, so atlas padding stays clean).
ppm: pixels per metre of the cell, so features keep their real size whatever the cell resolution.
Other kits reuse it: road (kind "concrete" / "paint" for markings), buildings (plaster "concrete"), props ("metal").
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

GRIME = np.array([0.30, 0.27, 0.22], np.float32)
RUST = np.array([0.46, 0.25, 0.12], np.float32)
ALU = np.array([0.66, 0.67, 0.66], np.float32)
ALGAE = np.array([0.20, 0.24, 0.13], np.float32)
BLEACH = np.array([0.93, 0.90, 0.85], np.float32)


def noise(w, h, cell_px, rng):
    """Smooth value noise 0..1 with features about cell_px wide."""
    gw, gh = max(2, int(w / max(cell_px, 1)) + 2), max(2, int(h / max(cell_px, 1)) + 2)
    a = (rng.random((gh, gw)) * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(a).resize((w, h), Image.BICUBIC), np.float32) / 255.0


def _mix(a, col, k):
    k = np.clip(k, 0.0, 1.0)[..., None]
    return a * (1 - k) + col * k


def _streaks(a, rng, n, ppm, col, strength, starts=None, length=(0.08, 0.35)):
    h, w = a.shape[:2]
    out = a
    for i in range(n):
        if starts:
            x0, y0 = starts[i % len(starts)]
            x0 += rng.normal(0, 0.006 * ppm)
        else:
            x0, y0 = rng.random() * w, rng.random() * h * 0.25
        L = int(rng.uniform(*length) * ppm)
        wd = max(1, int(rng.uniform(0.003, 0.009) * ppm))
        x0, y0 = int(x0), int(y0)
        y1 = min(h, y0 + L)
        if y1 <= y0 or x0 < 0 or x0 >= w:
            continue
        x1 = min(w, x0 + wd)
        fade = np.linspace(1.0, 0.0, y1 - y0, dtype=np.float32)[:, None] ** 0.7
        k = strength * rng.uniform(0.5, 1.0) * fade
        out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - k[..., None]) + col * k[..., None]
    return out


def _lines(size, rng, n, ppm, seg=(0.01, 0.05), walk=1, horiz=True, width=1):
    """Mask image with n random-walk scratch / crack lines."""
    m = Image.new("L", size, 0)
    dr = ImageDraw.Draw(m)
    w, h = size
    for _ in range(n):
        x, y = rng.random() * w, rng.random() * h
        ang = rng.normal(0, 0.35) if horiz else rng.random() * 6.283
        pts = [(x, y)]
        for _ in range(walk):
            L = rng.uniform(*seg) * ppm
            ang += rng.normal(0, 0.6)
            x, y = x + np.cos(ang) * L, y + np.sin(ang) * L
            pts.append((x, y))
        dr.line(pts, fill=255, width=width)
    return np.asarray(m, np.float32) / 255.0


def _edge_band(mask, px):
    """1 within px of the mask's edge (inside)."""
    m = Image.fromarray((mask * 255).astype(np.uint8))
    er = m.filter(ImageFilter.MinFilter(2 * (max(1, int(px)) // 2) + 1))
    return np.clip(mask - np.asarray(er, np.float32) / 255.0, 0, 1)


def age(img: Image.Image, wear: int, seed: int, ppm: float, kind: str = "sheeting", mask=None,
        bolts=()) -> Image.Image:
    """The cell painted `wear` steps older (0 = new: a light dust film only)."""
    rng = np.random.default_rng(seed)
    s = (0.18, 0.6, 1.0)[wear]
    if kind == "sheeting" and wear == 2:   # faded, softened print edges
        img = img.filter(ImageFilter.GaussianBlur(0.0025 * ppm))
    a = np.asarray(img.convert("RGB"), np.float32) / 255.0
    h, w = a.shape[:2]
    if mask is None:
        mask = np.ones((h, w), np.float32)
    clean = a.copy()
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None] * np.ones((1, w), np.float32)
    lum = a @ np.array([0.3, 0.59, 0.11], np.float32)
    sat = a.max(-1) - a.min(-1)
    if kind == "sheeting":
        patch = noise(w, h, 0.22 * ppm, rng)
        k = s * (0.12 + 0.30 * patch) * (0.35 + 0.65 * sat)
        red = np.clip((a[..., 0] - a[..., 1]) * 1.6 - 0.3, 0, 1)        # red film fades first, toward salmon
        a[..., 1] += red * s * 0.16
        a[..., 2] += red * s * 0.14
        a = _mix(a, BLEACH, k)
        a = lum[..., None] + (a - lum[..., None]) * (1 - 0.22 * s)
    elif kind == "paint":
        a = _mix(a, BLEACH * 0.85, s * 0.18 * (1 - lum))               # black chalks to grey
        a = _mix(a, np.array([0.80, 0.78, 0.70], np.float32), s * 0.2 * lum)
    a *= np.array([1 - 0.04 * s, 1 - 0.05 * s, 1 - 0.08 * s], np.float32)   # dust film
    # road grime gradient: splash and dust settle on the bottom part
    gn = noise(w, h, 0.04 * ppm, rng)
    g = np.clip((yy - 0.5) / 0.5, 0, 1) ** 1.6 * (0.10 + 0.30 * s) * (0.5 + 0.9 * gn)
    a = _mix(a, GRIME, g)
    if wear >= 1:
        a = _streaks(a, rng, int(3 + 10 * s * w / ppm), ppm, GRIME, 0.12 * s)          # rain streaks
        if bolts:
            col = RUST if wear == 2 else GRIME
            a = _streaks(a, rng, len(bolts) * (2 if wear == 2 else 1), ppm, col, 0.35 * s, starts=list(bolts),
                         length=(0.04, 0.16))
        sc = _lines((w, h), rng, int(4 + 14 * s), ppm, (0.01, 0.05), 2, True, max(1, int(0.002 * ppm)))
        a = _mix(a, np.array([0.85, 0.85, 0.83], np.float32), sc * 0.35 * s)           # scratches
    if kind == "sheeting" and wear == 2:
        cr = _lines((w, h), rng, int(30 * w * h / ppm ** 2) + 6, ppm, (0.008, 0.03), 6, False, 1)
        a = _mix(a, a * 0.78, cr * noise(w, h, 0.15 * ppm, rng) * 1.4)                   # crazed film
        band = _edge_band(mask, 0.07 * ppm)
        pn = noise(w, h, 0.05 * ppm, rng)
        big = np.clip((noise(w, h, 0.3 * ppm, rng) - 0.55) * 5, 0, 1)   # film lifts in one or two places, not all round
        peel = (band * pn * big * (0.6 + 0.8 * yy) > 0.33).astype(np.float32)
        if rng.random() < 0.6:   # one interior patch
            cx, cy, r = rng.random() * w, rng.random() * h, 0.03 * ppm
            X, Y = np.meshgrid(np.arange(w), np.arange(h))
            peel = np.maximum(peel, ((((X - cx) / r) ** 2 + ((Y - cy) / (r * 0.7)) ** 2) * (0.6 + pn) < 1).astype(np.float32))
        lip = np.clip(_edge_band(peel, 0.006 * ppm), 0, 1)
        a = _mix(a, ALU * (0.85 + 0.2 * gn[..., None]), peel)
        a = _mix(a, np.array([0.95, 0.95, 0.93], np.float32), lip * 0.8)                # curled film edge
    if kind in ("metal", "paint") and wear >= 1:
        rn = noise(w, h, 0.012 * ppm, rng) * noise(w, h, 0.12 * ppm, rng)
        low = np.clip((yy - 0.55) / 0.45, 0, 1)            # splash zone: chips and rust gather at the foot
        if kind == "paint":
            chips = (rn > (0.62 - 0.12 * s - 0.2 * low)).astype(np.float32)
            a = _mix(a, ALU * 0.8, chips)
            if wear == 2:
                a = _mix(a, RUST, chips * (0.3 + 0.7 * low) * noise(w, h, 0.01 * ppm, rng))
        else:
            a = _mix(a, RUST, np.clip((rn - 0.5 + 0.15 * low) * 4, 0, 1) * (wear - 0.5) * (0.25 + 0.75 * low))
            a = _mix(a, np.array([0.85, 0.86, 0.84], np.float32), np.clip((rn - 0.4) * 3, 0, 1) * 0.25)
    if wear >= 1 and kind in ("sheeting", "metal"):
        for _ in range(int(rng.integers(0, 2 + 2 * wear))):                          # bird dirt with drips
            cx, cy = rng.random() * w, rng.random() * h * 0.35
            r = rng.uniform(0.004, 0.012) * ppm
            m = Image.new("L", (w, h), 0)
            d = ImageDraw.Draw(m)
            d.ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8], fill=230)
            d.line([(cx, cy), (cx + rng.normal(0, r * 0.3), cy + r * rng.uniform(2, 5))], fill=200,
                   width=max(1, int(r * 0.4)))
            a = _mix(a, np.array([0.92, 0.91, 0.86], np.float32), np.asarray(m, np.float32) / 255.0)
    if wear == 2 or (kind == "concrete" and wear >= 1):                               # algae, humid bottom corners
        an = noise(w, h, 0.05 * ppm, rng)
        X = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        corner = np.clip((yy - 0.7) / 0.3, 0, 1) * (0.4 + 0.6 * np.abs(X))
        a = _mix(a, ALGAE, corner * an * 0.9 * s)
    a = np.clip(a, 0, 1)
    out = clean * (1 - mask[..., None]) + a * mask[..., None]
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8))


# ---- decals -------------------------------------------------------------------------------------------------------
POSTER_WORDS = ("CLASS", "ROOMS", "TUITION", "SALE", "FAIR", "WANTED")   # generic, fictional: no brands, no faces


def poster(w, h, seed, font_fn):
    """A torn, sun-faded paper poster pasted on a post, over the remnants of older ones."""
    rng = np.random.default_rng(seed)
    pal = [(222, 64, 52), (250, 205, 40), (40, 120, 200), (30, 150, 90), (240, 240, 232), (235, 120, 30)]
    im = Image.new("RGB", (w, h), (200, 196, 186))
    dr = ImageDraw.Draw(im)
    for k in range(2):   # older layers: torn strips
        y0 = int(rng.random() * h)
        dr.rectangle([0, y0, w, y0 + int(h * rng.uniform(0.1, 0.3))], fill=tuple(int(c * 0.8) for c in pal[rng.integers(6)]))
    bg = pal[int(rng.integers(6))]
    top = int(h * rng.uniform(0.0, 0.25))
    dr.rectangle([0, top, w, h], fill=bg)
    ink = (20, 20, 20) if sum(bg) > 450 else (245, 245, 240)
    word = POSTER_WORDS[int(rng.integers(len(POSTER_WORDS)))]
    f = font_fn(max(8, int(w / max(4, len(word)) * 1.5)))
    dr.text((w * 0.06, top + h * 0.08), word, font=f, fill=ink)
    for k in range(4):   # body text as bars (unreadable small print)
        y = top + h * (0.4 + k * 0.1)
        dr.rectangle([w * 0.08, y, w * rng.uniform(0.5, 0.92), y + h * 0.035], fill=ink)
    dr.rectangle([w * 0.1, top + h * 0.82, w * 0.9, top + h * 0.9], fill=pal[int(rng.integers(6))])
    # torn lower edge and corners: back to the old layer colour
    m = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(m)
    xs = np.linspace(0, w, 9)
    ys = h * (0.72 + 0.22 * rng.random(9))
    md.polygon([(0, h)] + list(zip(xs, ys)) + [(w, h)], fill=255)
    im = Image.composite(Image.new("RGB", (w, h), (176, 170, 160)), im, m)
    return age(im, 2, seed + 1, w / 0.24, "metal")


def footing(w, h, seed, collar=False):
    """Concrete patch round a post foot: rough edge, contact shadow ring at the centre, dirt, a crack."""
    rng = np.random.default_rng(seed)
    X, Y = np.meshgrid(np.linspace(-1, 1, w), np.linspace(-1, 1, h))
    r = np.sqrt(X ** 2 + Y ** 2)
    base = np.array([0.66, 0.64, 0.60] if not collar else [0.72, 0.70, 0.66], np.float32)
    a = np.ones((h, w, 3), np.float32) * base
    a *= (0.85 + 0.3 * noise(w, h, w * 0.08, rng))[..., None]
    a = _mix(a, GRIME, np.clip(1 - r, 0, 1) ** 0.5 * 0.25 + noise(w, h, w * 0.15, rng) * 0.2)
    a = _mix(a, np.array([0.12, 0.11, 0.10], np.float32), np.clip((0.42 - r) / 0.2, 0, 1) * 0.75)   # contact AO
    a = _mix(a, np.array([0.40, 0.38, 0.34], np.float32), np.clip((r - 0.85) / 0.15, 0, 1) * 0.6)    # worn edge
    cr = _lines((w, h), rng, 3, w, (0.1, 0.25), 3, False, 1)
    a = _mix(a, a * 0.6, cr)
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
