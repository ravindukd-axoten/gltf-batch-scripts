"""Compose render_tiles.py PNGs into one labelled sheet no wider than 1280 px (P96 dev tool).

python3 compose_tiles.py TILE_DIR SHEET.png [--cols 6] [--tile 210] [--extra IMG ...] (extra images are added as
first tiles, e.g. reference crops; keep sheets with third-party crops out of git)
"""
import glob
import os
import sys

from PIL import Image, ImageDraw

a = sys.argv[1:]
src, dst = a[0], a[1]
cols = int(a[a.index("--cols") + 1]) if "--cols" in a else 6
tile = int(a[a.index("--tile") + 1]) if "--tile" in a else 210
extra = a[a.index("--extra") + 1:] if "--extra" in a else []
files = extra + sorted(glob.glob(os.path.join(src, "*.png")))
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tile, rows * (tile + 14)), (24, 24, 26))
d = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    im = Image.open(f).convert("RGB")
    im.thumbnail((tile, tile))
    x, y = (i % cols) * tile, (i // cols) * (tile + 14)
    sheet.paste(im, (x, y + 14))
    d.text((x + 2, y + 1), os.path.basename(f).split(".")[0].replace("KIT_", "")[:34], fill=(230, 230, 200))
sheet.save(dst)
print(dst, sheet.size)
