"""Per-building paint tint for ordinary kit buildings (materials pass MAT2, task 3).

Every `bld_<osm id>` gets one wall tint, written into COLOR_0.rgb of its plaster and facade-trim faces: LOD0 by
`light_bake._write_alpha` (linear, the bake's per-piece mesh copies), LOD1 by `cells.prism` (sRGB, MeshData's
contract). SHD_HeroLit applies it as `lerp(1, saturate(rgb * 1.1), _PaintStrength)`, so a value of 0.91 is "no
change" and the palette can darken and shift hue but never brighten past the texture.

Palette from the Delta Face / Kollupitiya photos (`references/delta-face/`) and the Art Bible core palette: lime-wash
and warm cream (#EFE3C8 family), pale lime-yellow wash, weathered pale grey, faded mint and pale blue-grey, plus
older greyed buildings. Same families as the street kit (`street_kit.WALL_FAMILIES`): no ochre, rose or gold.
Deterministic (crc32 of the building name), so the same building is the same colour on every tier and every build.
"""
from __future__ import annotations

import zlib

NEUTRAL = 0.91  # x 1.1 in the shader = 1.0

# (name, linear rgb as the shader reads it, weight)
FAMILIES: tuple[tuple[str, tuple[float, float, float], float], ...] = (
    ("as_built", (0.91, 0.91, 0.91), 3.0),
    # P46e: warm cream and lime wash paler in blue-loss: with PAINT_SAT 1.3 and the +38 grade, 0.63 blue read as
    # lime-yellow (S1 style_street facade 228,194,115, s 0.68, against the frame's 153,115,101 and gf_21/24 off-white)
    ("warm_cream", (0.91, 0.87, 0.78), 3.0),
    ("lime_wash", (0.90, 0.88, 0.76), 1.5),
    ("pale_grey", (0.80, 0.82, 0.86), 2.5),
    ("faded_mint", (0.76, 0.88, 0.80), 1.5),
    ("blue_grey", (0.75, 0.82, 0.91), 1.0),
    ("weathered", (0.72, 0.71, 0.68), 1.5),
)
JITTER = 0.06  # per-building brightness, 0.94 .. 1.0 of the family

# faces whose COLOR_0.rgb takes the tint (their WorldMaterials entries set _PaintStrength); the hero hotel's smooth
# render, the assembly-hall sandstone, glass, roofs and the street kit (its own paint) are left alone
TINT_MATERIALS = frozenset({"MAT_PlasterColonial_Cream", "MAT_FacadeTrim_A"})

# MAT3: the Delta Road street kit (MAT_StreetKit_A) carries its own paint in COLOR_0.rgb, and its wall families
# (street_kit.WALL_FAMILIES) are all near-white, so without this the kerb blocks all read as one fresh coat and the
# MAT2 tint, bleach and streaks had nothing to show on. Corners whose rgb is exactly a wall family (linear, as the
# generator writes it) take the building's tint relative to NEUTRAL; trim white, shutters, glass, awnings and
# signs keep theirs. Same tint, so a building's plaster pieces and its street-kit bays match.
STREET_KIT_MATERIAL = "MAT_StreetKit_A"
WALL_MATCH_TOL = 0.006   # BYTE_COLOR round trip is < 0.004 in linear at these values
# Half strength: the kit walls carry their own family colour, and the full factor on a coloured family (mint x
# lime wash) went olive and read as dirt in the MAT3 close captures.
STREET_KIT_MIX = 0.5


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def street_kit_walls_linear() -> tuple[tuple[float, float, float], ...]:
    """Linear rgb of every street-kit wall paint family (the corners the building tint applies to)."""
    from .street_kit import WALL_FAMILIES
    return tuple(tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (1, 3, 5)) for h in WALL_FAMILIES.values())


def street_kit_factor_from_tint(tint) -> tuple[float, float, float]:
    """Multiplier on a street-kit wall corner's own paint: the tint over NEUTRAL, at STREET_KIT_MIX strength."""
    return tuple(round(1.0 + STREET_KIT_MIX * (c / NEUTRAL - 1.0), 4) for c in tint)


def street_kit_factor(name: str) -> tuple[float, float, float]:
    """street_kit_factor_from_tint of the building's tint (as_built = 1.0)."""
    return street_kit_factor_from_tint(building_tint_linear(name))


def _unit(name: str, salt: int) -> float:
    return (zlib.crc32(f"{name}#{salt}".encode()) & 0xFFFFFFFF) / 2 ** 32


def family(name: str) -> str:
    return _pick(name)[0]


def _pick(name: str):
    total = sum(w for _, _, w in FAMILIES)
    r = _unit(name, 1) * total
    for fam in FAMILIES:
        r -= fam[2]
        if r < 0:
            return fam
    return FAMILIES[-1]


def building_tint_linear(name: str) -> tuple[float, float, float]:
    """Linear COLOR_0.rgb for the building `name` (`bld_<osm id>`)."""
    _, rgb, _ = _pick(name)
    k = 1.0 - JITTER * _unit(name, 2)
    return tuple(round(c * k, 4) for c in rgb)


def linear_to_srgb(c: float) -> float:
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def building_tint_srgb(name: str) -> tuple[float, float, float]:
    """The same tint for MeshData.colors (sRGB, written with color_srgb)."""
    return tuple(linear_to_srgb(c) for c in building_tint_linear(name))
