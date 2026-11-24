"""Per-cell ground light map: layout maths, packing and PNG writing (no Blender; unit-tested in plain Python).

Research "Lighting and Look" 3.2 and work list 3; TDD "Baked occlusion and ground light map as built".
One RGBA8 texture of MAP_RES x MAP_RES per 128 m cell, linear (not sRGB), mapped by world XZ:
  R = sky visibility (AO) at ground level, G / B / A = sun visibility for the golden hour, noon and blue hour keys.
Texel centres sit on a lattice of CELL / (MAP_RES - 1) m that includes both cell edges, so the last column of a cell
and the first column of its east neighbour sample the same world line and bilinear sampling (clamped) has no seam.
"""
from __future__ import annotations

import math
import os
import re
import struct
import zlib

MAP_RES = 256
CELL = 128.0
SPACING = CELL / (MAP_RES - 1)        # metres between texel centres (0.502 m)
# sun keys in channel order G, B, A; the directions come from the Unity presets (data, not code)
SUN_KEYS = (("GoldenHour", 8.0, 250.0), ("Noon", 68.0, 200.0), ("BlueHour", 38.0, 255.0))
PRESET_ASSET = "unity/BatchIsland/Assets/BatchIsland/Data/Lighting/LIGHT_{}.asset"


def texel_world(i: int, x0: float) -> float:
    """World coordinate of texel centre i (0 .. MAP_RES - 1) in a cell starting at x0."""
    return x0 + i * SPACING


def uv_of(x: float, x0: float) -> float:
    """Texture coordinate of world coordinate x in the cell starting at x0 (the shader's _GroundLightST)."""
    return ((x - x0) / SPACING + 0.5) / MAP_RES


def shader_st(x0: float, z0: float) -> tuple[float, float, float, float]:
    """(scale x, scale z, offset x, offset z): uv = worldXZ * st.xy + st.zw, the same mapping as uv_of."""
    k = 1.0 / (SPACING * MAP_RES)
    return (k, k, 0.5 / MAP_RES - x0 * k, 0.5 / MAP_RES - z0 * k)


def sun_vector(elevation_deg: float, azimuth_deg: float) -> tuple[float, float, float]:
    """Unit vector towards the sun in Blender world axes (x east, y north, z up); azimuth is a compass bearing."""
    el, az = math.radians(elevation_deg), math.radians(azimuth_deg)
    return (math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el))


def read_sun_keys(repo: str) -> list[tuple[str, float, float]]:
    """Sun elevation / azimuth of each key from the Unity LightingPreset assets (falls back to SUN_KEYS)."""
    out = []
    for name, el, az in SUN_KEYS:
        path = os.path.join(repo, PRESET_ASSET.format(name))
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            el = float(re.search(r"^\s*SunElevation:\s*([-\d.]+)", text, re.M).group(1))
            az = float(re.search(r"^\s*SunAzimuth:\s*([-\d.]+)", text, re.M).group(1))
        except (OSError, AttributeError, ValueError):
            pass
        out.append((name, el, az))
    return out


def atlas_side(n_cells: int) -> int:
    """Tiles per side of the square bake atlas that holds n_cells tiles."""
    return max(1, math.ceil(math.sqrt(n_cells)))


def fill_masked(tile, valid, passes: int = 4):
    """Fill texels where valid is False (under buildings: no ground) from the mean of valid 4-neighbours, a few
    rings deep, so bilinear sampling at a wall base blends ground with ground. tile: (H, W, C) float numpy array.
    Returns (tile, still_invalid)."""
    import numpy as np
    t = tile.copy()
    v = valid.copy()
    for _ in range(passes):
        acc = np.zeros_like(t)
        cnt = np.zeros(v.shape, dtype=np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sv = np.roll(v, (dy, dx), axis=(0, 1))
            st = np.roll(t, (dy, dx), axis=(0, 1))
            # no wrap-around across the tile edge
            if dy == 1: sv[0, :] = False
            if dy == -1: sv[-1, :] = False
            if dx == 1: sv[:, 0] = False
            if dx == -1: sv[:, -1] = False
            acc += st * sv[..., None]
            cnt += sv
        grow = (~v) & (cnt > 0)
        t[grow] = acc[grow] / cnt[grow][:, None]
        v = v | grow
    return t, ~v


def png_rgba(path: str, rows: list[bytes], width: int, height: int) -> None:
    """Write an 8-bit RGBA PNG (rows top to bottom, each width*4 bytes). Deterministic: no timestamps."""
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(png)


def tile_rows(tile) -> list[bytes]:
    """(H, W, 4) float tile, row 0 = south (Blender image order) -> PNG rows top (north) to bottom, 8-bit."""
    import numpy as np
    b = np.clip(np.rint(tile * 255.0), 0, 255).astype(np.uint8)
    return [b[j].tobytes() for j in range(b.shape[0] - 1, -1, -1)]


def file_name(cell_id: str) -> str:
    return f"TEX_GroundLight_{cell_id}.png"
