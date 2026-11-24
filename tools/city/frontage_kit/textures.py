"""Paint the shipped frontage trim albedo T_FrontageTrim_A_BaseMap (P96) from the high-poly bakes.

python3 textures.py [--bakes bakes] [--src ../../textures/source] [--out textures/T_FrontageTrim_A_BaseMap.png]
                   [--decay worn|light]   (light writes T_FrontageTrim_A_Light_BaseMap.png by default)

Painted Cityhub A (Art Bible): one albedo, no normal map. The high-poly bakes from trim_high.py (AO, tangent
normal, height) are turned into painted light (key from the upper left, as hand-painted trims do), contact
shadow and edge wear; CC0 Poly Haven luminance (tools/textures/sources.json: white_rough_plaster,
concrete_wall_008, rusty_metal_02) gives the surface grain; seamless FFT noise gives rain streaks, repaint
patches, splash grime and rust. Rows that carry paint stay near-white so the per-face vertex colour (kitbuild.py)
gives the hue; glass, brick and canvas weave carry their own colour. 1024 x 4096 = 4 x 16 m at 256 px/m, rows as
in FRONTAGE_KIT_SPEC.md. Everything repeats along U, so rows tile. Needs Pillow + numpy.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
a = sys.argv[1:]
BAKES = a[a.index("--bakes") + 1] if "--bakes" in a else os.path.join(HERE, "bakes")
SRC = a[a.index("--src") + 1] if "--src" in a else os.path.join(HERE, "..", "..", "textures", "source")
DECAY = a[a.index("--decay") + 1] if "--decay" in a else "worn"
# decay level (agent 2026-11-19): worn on Delta Road, light only next to the Delta Face Hotel; light keeps the grain
# and a trace of every stain so the two levels sit together on one street
K = {"worn": dict(runs=0.16, sill=0.12, splash=0.30, rust=1.0, stain=1.0, wash=0.035, grime=0.16),
     "light": dict(runs=0.025, sill=0.02, splash=0.08, rust=0.35, stain=0.4, wash=0.02, grime=0.03)}[DECAY]
_name = "T_FrontageTrim_A_BaseMap.png" if DECAY == "worn" else "T_FrontageTrim_A_Light_BaseMap.png"
OUT = a[a.index("--out") + 1] if "--out" in a else os.path.join(HERE, "textures", _name)
PX = 256
W, H = 4 * PX, 16 * PX
ROWS = {"WALL": (0, 4), "REVEAL": (4, 5), "FRAME": (5, 6), "CONCRETE": (6, 7), "ROLLER": (7, 9.4),
        "LOUVRE": (9.4, 10.6), "PANEL": (10.6, 11.6), "GLASS": (11.6, 12.8), "CANVAS": (12.8, 13.6),
        "METAL": (13.6, 14.4), "SPALL": (14.4, 15.2), "PLINTH": (15.2, 15.6), "SHEET": (15.6, 16.0)}
rng = np.random.default_rng(96)


def load(name):
    im = Image.open(os.path.join(BAKES, name + ".png")).convert("RGB").resize((W, H), Image.BILINEAR)
    return np.asarray(im).astype(np.float32) / 255.0


def cc0(name, tile_m):
    """Seamless luminance detail (mean 1) of a CC0 diffuse, resampled to `tile_m` metres per tile, tiled to W x H."""
    p = os.path.join(SRC, name, f"{name}_diff_2k.jpg")
    t = int(tile_m * PX)
    im = Image.open(p).convert("L").resize((t, t), Image.LANCZOS)
    g = np.asarray(im).astype(np.float32) / 255.0
    blur = np.asarray(im.filter(ImageFilter.GaussianBlur(t / 6))).astype(np.float32) / 255.0
    d = g / np.maximum(blur, 0.05)                       # high-pass: keep the grain, drop the source's lighting
    return np.tile(d, (H // t + 1, W // t + 1))[:H, :W]


def noise(scale_u, scale_v, shape=(H, W)):
    """Periodic (seamless on both axes) smooth noise, std 1; `scale_*` are feature sizes in metres."""
    f = np.fft.fft2(rng.standard_normal(shape))
    fu = np.fft.fftfreq(shape[1], 1.0 / PX)[None, :]
    fv = np.fft.fftfreq(shape[0], 1.0 / PX)[:, None]
    n = np.real(np.fft.ifft2(f * np.exp(-((fu * scale_u) ** 2 + (fv * scale_v) ** 2))))
    return (n - n.mean()) / (n.std() + 1e-6)


def band(name):
    v0, v1 = ROWS[name]
    return slice(int(H - v1 * PX), int(H - v0 * PX))


def local_v(name):
    """0 at the row bottom, 1 at the top, as a column (H rows of the band)."""
    s = band(name)
    n = s.stop - s.start
    return np.linspace(1, 0, n, dtype=np.float32)[:, None]


def main():
    ao = load("trim_ao")[..., 0]
    nrm = load("trim_nrm") * 2 - 1
    hgt = load("trim_h")[..., 0]
    light = np.clip(1 + 0.55 * (-0.45 * nrm[..., 0] + 0.6 * nrm[..., 1]), 0.55, 1.3)   # key from the upper left
    gy, gx = np.gradient(hgt)
    edge = np.clip(np.hypot(gx, gy) * 18, 0, 1)                                            # worn arrises
    shade = light * (0.35 + 0.65 * ao) ** 0.9
    plaster = np.clip(cc0("white_rough_plaster", 1.0), 0.6, 1.25)
    concrete = cc0("concrete_wall_008", 2.0)
    rust_src = cc0("rusty_metal_02", 1.0)
    noise(0.5, 0.5)                                 # unused since v3; drawn to keep the other rows' rng sequence
    streak = noise(0.05, 1.6)                       # long vertical runs, thin in U
    thin = noise(0.015, 1.2)                        # rain runs on the wall: 15 mm wide features
    fine = noise(0.012, 0.012)
    out = np.ones((H, W, 3), np.float32)

    def paint(name, base, grain, k, tint=(1, 1, 1)):
        s = band(name)
        g = 1 + k * (grain[s] - 1)
        out[s] = (base * g * shade[s])[..., None] * np.array(tint, np.float32)
        return s

    # WALL: lime-washed render, repaint patches, rain runs from the top (v = 4 sits under the parapet), splash.
    s = band("WALL")
    lv = local_v("WALL")
    # v3 pass 2 (critic: full-wall thin runs read as wood grain): broad soft limewash patches (repaint and uneven
    # lime, 0.6-1 m, soft edges) carry the wall; thin runs only under the cornice band (top 0.7 m of the storey) and
    # under sills, gated by a sparse mask so they gather in a few places; a soft grime band under the cornice.
    # `wash` and `grime` set the gap between worn (Delta Road) and light (next to the hotel).
    wash = np.clip(noise(0.8, 0.7)[s] * 0.9, -1, 1)
    wash = np.sign(wash) * np.abs(wash) ** 0.7
    gate = np.clip(noise(0.35, 0.5)[s] - 0.6, 0, 1)
    top = np.clip((lv * 4 - 3.3) / 0.7, 0, 1)
    runs = np.clip((thin[s] - 1.4) * 1.6, 0, 1) * gate * np.clip((lv * 4 - 2.6) / 1.4, 0, 1) ** 1.5
    grime = top ** 1.6 * (0.7 + 0.3 * np.clip(noise(0.25, 0.08)[s], -1, 1))
    splash = np.clip(1 - lv / 0.1, 0, 1) ** 1.6 * (0.75 + 0.25 * np.clip(fine[s], -1, 1))
    sill = np.clip((thin[s] - 1.2) * 1.4, 0, 1) * gate * np.clip(1 - (1.7 - lv * 4) / 0.7, 0, 1) * (lv * 4 < 1.7)
    lum = 0.975 * (1 + 0.05 * (plaster[s] - 1)) * (1 + K["wash"] * wash) * (1 - K["sill"] * sill) * \
        (1 - K["runs"] * runs) * (1 - K["splash"] * splash) * (1 - K["grime"] * grime)
    dirt = runs + splash + grime + 0.5 * np.clip(-wash, 0, 1) * K["wash"] * 10
    out[s] = lum[..., None] * np.array([1.0, 0.985, 0.95]) ** dirt[..., None]
    # REVEAL: smoother render, darker toward the sill end.
    s = paint("REVEAL", 0.86 * (1 - 0.12 * (1 - local_v("REVEAL"))), plaster, 0.05)
    # FRAME: painted timber; grain along U, worn edges lighter.
    s = band("FRAME")
    grain = 1 + 0.015 * noise(0.6, 0.01)[s]
    out[s] = ((0.9 * grain * shade[s]) * (1 + 0.12 * edge[s]))[..., None]
    paint("CONCRETE", 0.8, concrete, 0.35)
    s = band("CONCRETE")
    out[s] *= (1 - 0.18 * K["stain"] * np.clip(streak[s] * 0.5, 0, 1) * local_v("CONCRETE"))[..., None]
    # ROLLER: enamelled steel slats, dust in the overlaps, faint rust runs.
    s = paint("ROLLER", 0.88, rust_src, 0.12)
    out[s] *= (1 - 0.06 * K["stain"] * np.clip(streak[s], 0, 1))[..., None]
    for nm in ("LOUVRE", "PANEL"):
        s = band(nm)
        out[s] = ((0.9 * (1 + 0.012 * noise(0.6, 0.01)[s]) * shade[s]) * (1 + 0.1 * edge[s]))[..., None]
    # GLASS: own colour (NEUTRAL role). Daylight glass is mostly reflection: pale sky caught in the upper part,
    # grading into a dim teal interior with faint shelf lines, and three sheens of different width and angle (the
    # old pane was one dark slab with a single sheen). Mean about 0.45, never black.
    s = band("GLASS")
    lv = local_v("GLASS")
    u = np.linspace(0, 4, W, dtype=np.float32)[None, :]
    diag = (np.clip(np.cos((u * 1.0 + lv * 1.2) * np.pi * 2) - 0.8, 0, 1) * 2.5 +
            np.clip(np.cos((u * 2.3 + lv * 2.0 + 0.3) * np.pi * 2) - 0.9, 0, 1) * 3.0 +
            np.clip(np.cos((u * 0.55 + lv * 0.6 + 0.6) * np.pi * 2) - 0.6, 0, 1) * 0.8)
    sky = np.array([0.66, 0.74, 0.78])
    inner = np.array([0.30, 0.35, 0.34])
    k = np.clip(lv * 1.15 - 0.15, 0, 1)[..., None] ** 1.3
    shelves = 1 - 0.07 * ((np.sin(lv * np.pi * 7.0) > 0.92) & (lv < 0.6))[..., None]
    room = (inner * (1 - k) + sky * k) * shelves + 0.10 * diag[..., None]
    curtain = np.clip((lv - 0.74) * 25, 0, 1)[..., None] * (0.9 + 0.1 * np.cos(u * 18)[..., None])
    out[s] = (room * (1 - curtain) + np.array([0.80, 0.74, 0.62]) * curtain) * shade[s][..., None]
    # CANVAS: folds in the light, fine weave, dirt toward the valance.
    s = band("CANVAS")
    weave = 1 + 0.05 * np.sign(np.sin(np.arange(W)[None, :] * 1.3)) * np.sign(np.sin(np.arange(s.stop - s.start)[:, None] * 1.3))
    lv = local_v("CANVAS")
    out[s] = (0.95 * weave * shade[s] * (1 - 0.15 * (1 - lv) ** 3))[..., None]
    # METAL: painted steel with rust patches and runs (METAL role multiplies grey).
    s = paint("METAL", 0.92, rust_src, 0.35)
    rmask = K["rust"] * np.clip((noise(0.06, 0.06)[s] - 1.6) * 1.2 + 0.15 * np.clip(streak[s] - 0.5, 0, 1), 0, 0.8)
    out[s] = out[s] * (1 - rmask[..., None]) + out[s] * rmask[..., None] * np.array([0.86, 0.56, 0.38])
    # SPALL: own colour: fired brick (per-brick variation) in grey lime mortar.
    s = band("SPALL")
    brick = np.clip((hgt[s] - 0.25) * 6, 0, 1)
    var = 1 + 0.12 * noise(0.06, 0.03)[s]
    col = np.array([0.55, 0.42, 0.36]) * var[..., None] * brick[..., None] + \
        np.array([0.62, 0.60, 0.55]) * (1 - brick[..., None])     # weathered brick in cement, not new red
    # AO only, no key light: the baked top-left highlight made the recessed brick read as a proud lump (critic, v3)
    out[s] = 0.85 * col * (1 + 0.25 * (plaster[s] - 1))[..., None] * ((0.35 + 0.65 * ao[s]) ** 1.2)[..., None]
    # PLINTH: grey cement skirting, wet-splash band at the bottom.
    s = paint("PLINTH", 0.86, concrete, 0.45)
    lv = local_v("PLINTH")
    out[s] *= (1 - 0.3 * K["stain"] * np.clip(1 - lv / 0.4, 0, 1) * (0.8 + 0.2 * fine[s]))[..., None]
    # SHEET: galvanised corrugated iron, rust runs down the corrugations.
    s = paint("SHEET", 0.88, rust_src, 0.2)
    rr = K["rust"] * np.clip(noise(0.03, 0.4)[s] - 1.2, 0, 0.6)
    out[s] = out[s] * (1 - rr[..., None]) + out[s] * rr[..., None] * np.array([0.8, 0.5, 0.33])

    img = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, optimize=True)
    print(OUT, img.size, "mean", np.round(out.reshape(-1, 3).mean(0), 3))


main()
