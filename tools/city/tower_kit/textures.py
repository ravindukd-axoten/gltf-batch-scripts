"""Tower trim sheet T_TowerTrim_A (P103): painted glass / slab / metal rows, lit-window emission, mask map, and the
default fictional ad face. Own work, drawn by this script (numpy + Pillow), no photo sources. Regenerate, never edit.

    python3 tools/city/tower_kit/textures.py [--out tools/city/tower_kit/textures]

Layout (must match towerlib.ROWS): 1024 x 2048 px = 8 m x 16 m at 128 px/m, v rows in metres from the bottom.
Glass rows are one 3.2 m storey of curtain wall: 0.9 m spandrel, vision panes in 0.8 m units, aluminium mullions on a
1.6 m bay; four variants differ in blinds, curtains and lit panes so a storey-by-storey seeded pick never repeats a
pattern up the shaft. The emission map (quarter size) lights the same panes warm for dusk and night.
"""
import argparse
import pathlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PX_M = 128
W, H = 1024, 2048
ROWS = {"GLASS0": (0.0, 3.2), "GLASS1": (3.2, 3.2), "GLASS2": (6.4, 3.2),
        "SLAB": (9.6, 0.8), "SOFFIT": (10.4, 1.6), "METAL": (12.0, 0.8), "BALUS": (12.8, 1.2),
        "STONE": (14.0, 0.8), "LOUVRE": (14.8, 0.8), "FAR": (15.6, 0.4)}
SMOOTH = {"GLASS": 0.78, "SLAB": 0.45, "SOFFIT": 0.2, "METAL": 0.5, "BALUS": 0.8, "STONE": 0.25, "LOUVRE": 0.4,
          "FAR": 0.45}
REPO = pathlib.Path(__file__).resolve().parents[3]
FONT = REPO / "unity/BatchIsland/Assets/BatchIsland/Art/UI/Fonts/NotoSansCondensed-Bold.ttf"


def srgb(c):
    return np.array(c, float) / 255.0


def row_px(name):
    v0, h = ROWS[name]
    top = int(round((16.0 - (v0 + h)) * PX_M))
    return top, int(round(h * PX_M))


def noise(rng, h, w, scale, amp):
    """Soft brush-like value noise: low-res random field blurred up."""
    sh, sw = max(2, h // scale), max(2, w // scale)
    small = Image.fromarray((rng.random((sh, sw)) * 255).astype(np.uint8))
    big = small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(scale / 3))
    return (np.asarray(big, float) / 255.0 - 0.5) * 2 * amp


def glass_row(rng, variant):
    """One curtain-wall storey, 8 m x 3.2 m: returns albedo (h, w, 3), emission (h, w, 3), smooth mask (h, w)."""
    h, w = int(round(3.2 * PX_M)), W
    y = np.linspace(1.0, 0.0, h)[:, None]  # 1 at the top of the storey
    alb = np.zeros((h, w, 3))
    emi = np.zeros((h, w, 3))
    spandrel = int(0.9 * PX_M)
    pane_w = int(0.8 * PX_M)
    # v3: near-black charcoal (gf_13: the twins read black-grey with thin white lines); vision panes ~0.035-0.05
    # linear, the sky reflection comes from the shader (smoothness 0.86), so only a trace is painted in
    tints = [srgb((36, 40, 45)), srgb((40, 43, 49)), srgb((33, 37, 42)), srgb((43, 47, 53))]  # charcoal, faint blue
    sky_top, sky_low = srgb((96, 112, 128)), srgb((150, 160, 168))
    # v3 dusk: the variants differ strongly in how busy a floor is (GLASS0 a near-dark floor, GLASS2 a busy one and
    # the lobby row), so the per-storey seeded pick clusters lights by floor instead of spreading them evenly
    blind_p, lit_p, curtain_p = [(0.18, 0.0, 0.08), (0.42, 0.15, 0.15), (0.12, 0.35, 0.05), (0.28, 0.24, 0.22)][variant]
    # panes are grouped into rooms of 2-4 panes: blinds, curtains and lights are decided per room, so the
    # lit-window pattern reads as flats and offices instead of salt-and-pepper noise
    n_panes, room_of, rooms = w // pane_w, [], []
    while len(room_of) < n_panes:
        k = int(rng.choice([2, 3, 3, 4]))  # a row is only 8 m wide, so rooms stay small; floors carry the clustering
        rooms.append({"r": rng.random(), "lit": rng.random() < lit_p, "blind": (0.25 + 0.6 * rng.random()),
                      "warm": rng.choice(6, p=[0.25, 0.25, 0.2, 0.15, 0.1, 0.05]), "lum": 0.45 + 0.55 * rng.random()})
        room_of += [len(rooms) - 1] * k
    for i in range(n_panes):
        x0, x1 = i * pane_w, (i + 1) * pane_w
        room = rooms[room_of[i]]
        tint = tints[rng.integers(len(tints))] * (0.92 + 0.16 * rng.random())
        tilt = rng.normal(0, 0.06)  # each pane reflects a slightly different patch of sky
        # vision glass: horizon light low, deeper sky high; painted, so the gradient is broad and soft
        g = np.clip(y[: h - spandrel] * (1.0 + tilt) - 0.05, 0, 1)
        refl = sky_low * (1 - g) + sky_top * g
        pane = 0.9 * tint + 0.1 * refl
        pane = np.broadcast_to(pane[:, None, :], (h - spandrel, x1 - x0, 3)).copy()
        # interior: ceiling shadow band under the slab, a darker room behind
        pane[: int(0.18 * PX_M)] *= 0.72
        r = room["r"]
        if r < blind_p:  # roller blind pulled part way down
            d = int(room["blind"] * (h - spandrel))
            col = srgb((206, 196, 176)) if rng.random() < 0.7 else srgb((168, 170, 166))
            pane[:d] = pane[:d] * 0.7 + col * 0.14  # seen through dark tinted glass: a dim band, not a white one
            pane[d - 3 : d] *= 0.8
        elif r < blind_p + curtain_p:  # curtains at the sides
            cw = int(0.22 * pane_w)
            col = srgb((214, 204, 186))
            pane[:, :cw] = pane[:, :cw] * 0.7 + col * 0.16
            pane[:, -cw:] = pane[:, -cw:] * 0.7 + col * 0.16
        alb[: h - spandrel, x0:x1] = pane
        if room["lit"]:  # lit room (emission only; day albedo a touch warmer): warm flat, cool office, dim TV
            # 2700 K, 3000 K, 3500 K, 4000 K, cool office white, dim TV blue; brightness 0.45-1.0
            warm = [srgb((255, 169, 87)), srgb((255, 180, 107)), srgb((255, 196, 137)), srgb((255, 209, 163)),
                    srgb((228, 234, 240)), srgb((120, 150, 210)) * 0.5][room["warm"]] * room["lum"]
            if rng.random() > 0.3:  # a lit flat still has a dark room or a drawn blind here and there
                emi[int(0.18 * PX_M) : h - spandrel, x0 + 6 : x1 - 6] = warm
            alb[: h - spandrel, x0:x1] = alb[: h - spandrel, x0:x1] * 0.92 + srgb((150, 130, 100)) * 0.06
        # spandrel: fritted opaque glass, a little greener and darker, very soft gradient
        sp = 0.85 * tint + 0.15 * srgb((56, 60, 64))
        alb[h - spandrel :, x0:x1] = sp * (0.85 + 0.1 * np.linspace(0, 1, spandrel))[:, None, None]
    # soft painted sheen: two diagonal broad strokes
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(2):
        c, k = rng.random() * w, 0.6 + rng.random() * 0.6
        band = np.exp(-(((xx - c - yy * k) % w - w / 2) / (w * 0.06)) ** 2)
        alb[: h - spandrel] += band[: h - spandrel, :, None] * 0.02
    alb += noise(rng, h, w, 24, 0.012)[:, :, None]
    # aluminium: mullions every 0.8 m (thin) and 1.6 m (bay), transom at the spandrel, head at the slab
    alu, alu_dark = srgb((214, 216, 214)), srgb((40, 42, 44))  # thin white lines on black glass
    for i in range(w // pane_w + 1):
        xm = i * pane_w
        t = 1  # v3: a third of the v2 width
        # thin white line on the 1.6 m bay only; the 0.8 m mullion between is dark (gf_13: few, crisp lines)
        alb[:, max(0, xm - t) : xm + t] = alu if i % 2 == 0 else srgb((58, 62, 66))
        alb[:, xm + t : xm + t + 2] = alu_dark  # shadow side of the mullion
        emi[:, max(0, xm - t) : xm + t] = 0
    for yr, t in [(h - spandrel, 3), (0, 3), (h - 3, 3)]:
        alb[max(0, yr - t) : yr + t] = alu
        emi[max(0, yr - t) : yr + t] = 0
    smooth = np.full((h, w), SMOOTH["GLASS"])
    smooth[h - spandrel :] = 0.6
    return np.clip(alb, 0, 1), emi, smooth


def flat_row(rng, name):
    top, h = row_px(name)
    w = W
    yy = np.linspace(0, 1, h)[:, None, None]  # 0 at the top of the row
    if name == "SLAB":  # white painted aluminium / concrete floor band: lit top lip, grime under it
        a = srgb((226, 224, 214)) * (1.02 - 0.12 * yy)
        a = np.broadcast_to(a, (h, w, 3)).copy()
        a[:4] *= 1.06
        a[-6:] *= 0.86
        a += noise(rng, h, w, 32, 0.02)[:, :, None]
    elif name == "SOFFIT":
        a = np.broadcast_to(srgb((112, 110, 106)), (h, w, 3)).copy() + noise(rng, h, w, 20, 0.03)[:, :, None]  # v3: in shade under dark glass
    elif name == "METAL":  # dark grey plant cladding with vertical ribs every 0.2 m
        a = np.broadcast_to(srgb((50, 53, 57)), (h, w, 3)).copy()  # v3 dark: skybridge fascia and floor bands
        for x in range(0, w, int(0.2 * PX_M)):
            a[:, x : x + 3] = srgb((72, 76, 80))
            a[:, x + 3 : x + 5] = srgb((38, 40, 43))
        a += noise(rng, h, w, 24, 0.02)[:, :, None]
    elif name == "BALUS":  # glass balustrade: pale teal, posts on the 1.6 m bay, top rail
        a = srgb((86, 114, 122)) * (0.9 + 0.2 * (1 - yy))
        a = np.broadcast_to(a, (h, w, 3)).copy()
        for x in range(0, w, int(1.6 * PX_M)):
            a[:, x : x + 4] = srgb((200, 204, 202))
        a[:5] = srgb((214, 216, 212))
        a += noise(rng, h, w, 40, 0.03)[:, :, None]
    elif name == "STONE":  # warm granite cladding, joints every 1.2 m and at mid-height
        a = np.broadcast_to(srgb((176, 160, 140)), (h, w, 3)).copy() + noise(rng, h, w, 8, 0.04)[:, :, None]
        for x in range(0, w, int(1.2 * PX_M)):
            a[:, x : x + 2] *= 0.7
        a[h // 2 : h // 2 + 2] *= 0.7
    elif name == "LOUVRE":  # crown screen: horizontal slats with dark gaps
        a = np.zeros((h, w, 3))
        for yrow in range(h):
            a[yrow] = srgb((206, 208, 204)) if (yrow % 10) < 6 else srgb((70, 76, 80))
    elif name == "FAR":  # four storeys at far-LOD scale: slab line, dark glass, scattered lit panes
        a = np.zeros((h, w, 3))
        sh = h // 4
        for s in range(4):
            y0 = s * sh
            a[y0 : y0 + sh] = srgb((34, 38, 43))  # v3 charcoal, matches the near glass rows
            a[y0 : y0 + sh // 3] = srgb((44, 49, 55))
            a[y0 + sh - 2 : y0 + sh] = srgb((206, 206, 200))
            for x in range(0, w, int(1.6 * PX_M)):
                a[y0 : y0 + sh - 2, x : x + 1] = srgb((120, 124, 126))
        a += noise(rng, h, w, 16, 0.012)[:, :, None]
    return top, np.clip(a, 0, 1)


def flat_emission(rng, name, h):
    """LOUVRE: a warm crown uplight fading up the louvres. FAR: lit panes for far LODs at dusk, clustered in runs of
    3-8 panes on some storeys only (mirrors the per-floor clustering of the near rows)."""
    e = np.zeros((h, W, 3))
    if name == "LOUVRE":
        yy = np.linspace(1.0, 0.0, h)[:, None, None]  # 1 at the bottom of the row
        e[:] = srgb((255, 200, 140)) * 0.55 * yy ** 2
    else:
        sh, pw = h // 4, int(0.8 * PX_M)  # four far storeys; panes at true width
        for s in range(4):
            busy = [0.0, 0.1, 0.24][rng.integers(3)]
            x = 0
            while x < W:
                run = int(rng.integers(3, 9)) * pw
                if rng.random() < busy:
                    col = [srgb((255, 196, 128)), srgb((236, 238, 230))][int(rng.random() < 0.3)] * (0.6 + 0.4 * rng.random())
                    e[s * sh + 2 : (s + 1) * sh - 3, x : x + run] = col
                x += run
    return e


def ad_default(path, aspect=(3, 1), px=256):
    """Default sponsor-slot art for the fictional 'Batch City Developments' (no real brand). 6 % x 10 % safe area."""
    w, h = px * aspect[0], px * aspect[1]
    im = Image.new("RGB", (w, h), (238, 234, 224))
    d = ImageDraw.Draw(im)
    sx, sy = int(0.06 * w), int(0.10 * h)
    d.rectangle([0, h - int(0.08 * h), w, h], fill=(32, 92, 104))
    r = int(0.30 * h)
    cx, cy = sx + r, h // 2 - int(0.03 * h)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(246, 244, 238), outline=(32, 92, 104), width=max(3, r // 10))
    d.ellipse([cx - r // 3, cy - r // 2, cx + r // 6, cy], fill=(255, 255, 255))  # batch highlight
    try:
        f1 = ImageFont.truetype(str(FONT), int(0.30 * h))
        f2 = ImageFont.truetype(str(FONT), int(0.14 * h))
    except OSError:
        f1 = f2 = ImageFont.load_default()
    x = cx + r + int(0.05 * w)
    d.text((x, sy + int(0.08 * h)), "BATCH CITY", font=f1, fill=(32, 92, 104))
    d.text((x, sy + int(0.46 * h)), "DEVELOPMENTS", font=f2, fill=(60, 70, 72))
    im.save(path)


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(103)
    base = np.zeros((H, W, 3))
    emis = np.zeros((H, W, 3))
    smooth = np.zeros((H, W))
    for k in range(3):
        top, h = row_px(f"GLASS{k}")
        a, e, s = glass_row(rng, k)
        base[top : top + h], emis[top : top + h], smooth[top : top + h] = a, e, s
    for name in ["SLAB", "SOFFIT", "METAL", "BALUS", "STONE", "LOUVRE", "FAR"]:
        top, a = flat_row(rng, name)
        base[top : top + a.shape[0]] = a
        if name in ("LOUVRE", "FAR"):
            emis[top : top + a.shape[0]] = flat_emission(rng, name, a.shape[0])
        smooth[top : top + a.shape[0]] = SMOOTH[name]
    Image.fromarray((base * 255).round().astype(np.uint8)).save(out / "T_TowerTrim_A_BaseMap.png")
    e_small = Image.fromarray((emis * 255).round().astype(np.uint8)).resize((W // 4, H // 4), Image.BOX)
    e_small.save(out / "T_TowerTrim_A_Emission.png")
    mask = np.zeros((H, W, 4))
    mask[..., 1] = 1.0  # G occlusion (AO comes from COLOR_0)
    mask[..., 3] = smooth
    Image.fromarray((mask * 255).round().astype(np.uint8), "RGBA").resize((W // 4, H // 4), Image.BOX).save(
        out / "T_TowerTrim_A_MaskMap.png")
    ad_default(out / "T_AdFace_BatchCityDev_3x1.png")
    print("wrote", sorted(p.name for p in out.glob("T_*.png")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(pathlib.Path(__file__).parent / "textures"))
    build(pathlib.Path(ap.parse_args().out))
