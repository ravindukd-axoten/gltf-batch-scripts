"""Default (fictional) creatives for the frontage kit's sponsor ad faces (P96, branding research P102 section 3.3).

python3 ad_textures.py   ->  textures/T_AdFace_<aspect>_Default.png for 4x1, 3x1, 2x1 and 1x2

Every ad face in the kit is one quad with UV 0-1 on its own material MAT_AdFace_<aspect>; a slot never shows a blank
panel, so each aspect gets a default creative for the invented brand FICT_LankaFizz (research default_brand_id; no
real brand, logo or slogan). Text and emblem stay inside the safe area: 6% in from left/right, 10% from top/bottom.
Flat painted colours, no baked wear (the wear/glare overlay is a separate mask per the research). Font: Noto Sans
Bold (SIL OFL, already in the repo under Art/UI/Fonts). Needs Pillow.
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "..", "..", "..", "unity", "BatchIsland", "Assets", "BatchIsland", "Art", "UI", "Fonts",
                    "NotoSans-Bold.ttf")
SIZES = {"4x1": (640, 160), "3x1": (1152, 384), "2x1": (768, 384), "1x2": (128, 256)}   # 256 px/m on the kit faces (2.4x0.6, 4.5x1.5, 3x1.5, 0.5x1 m); Low mips to 128
SAFE = (0.06, 0.10)
TEAL, CORAL, CREAM, INK = (24, 128, 128), (232, 98, 74), (246, 236, 214), (26, 40, 48)


def creative(aspect):
    w, h = SIZES[aspect]
    im = Image.new("RGB", (w, h), TEAL)
    d = ImageDraw.Draw(im)
    sx, sy = int(w * SAFE[0]), int(h * SAFE[1])
    x0, y0, x1, y1 = sx, sy, w - sx, h - sy                       # safe area
    d.rectangle((0, int(h * 0.82), w, h), fill=CORAL)             # background band may bleed; content may not
    portrait = h > w
    r = int(min(x1 - x0, y1 - y0) * (0.22 if portrait else 0.36))
    cx, cy = (w // 2, y0 + r + 4) if portrait else (x0 + r + 4, (y0 + y1) // 2)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CREAM)        # emblem: a bottle-cap with three bubbles
    for k, (dx, dy, rr) in enumerate(((-0.25, 0.2, 0.22), (0.15, -0.15, 0.3), (0.3, 0.3, 0.14))):
        b = int(r * rr)
        d.ellipse((cx + dx * r - b, cy + dy * r - b, cx + dx * r + b, cy + dy * r + b), fill=TEAL)
    tx0 = x0 if portrait else cx + r + int(w * 0.03)
    ty0 = cy + r + int(h * 0.03) if portrait else y0
    lines = ["Lanka", "Fizz"] if portrait or aspect == "2x1" else ["Lanka Fizz"]
    avail_w, avail_h = x1 - tx0, (y1 - ty0) * (0.62 if not portrait else 0.7)
    size = 200
    while size > 8:
        f = ImageFont.truetype(FONT, size)
        bw = max(d.textbbox((0, 0), s, font=f)[2] for s in lines)
        bh = sum(d.textbbox((0, 0), s, font=f)[3] for s in lines)
        if bw <= avail_w and bh <= avail_h:
            break
        size -= 2
    y = ty0
    for s in lines:
        d.text((tx0, y), s, font=f, fill=CREAM)
        y += d.textbbox((0, 0), s, font=f)[3]
    tag = ImageFont.truetype(FONT, max(10, size // 3))
    d.text((tx0, min(y + 2, y1 - tag.size - 2)), "island cola", font=tag, fill=INK)
    return im


def main():
    os.makedirs(os.path.join(HERE, "textures"), exist_ok=True)
    for a in SIZES:
        p = os.path.join(HERE, "textures", f"T_AdFace_{a}_Default.png")
        creative(a).save(p, optimize=True)
        print(p)


if __name__ == "__main__":
    main()
