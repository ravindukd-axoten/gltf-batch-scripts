"""COLOR_1 wear for the place kits (P242, kit surface layer). Pure Python (no bpy), unit-tested.

Channel plan from the wear-and-decay research (docs/research/wear-and-decay-system.md 3.1, branch p151) and
`wear_color1.py`, so kit pieces and city cells carry one layout:

    R  dirt / grime         G  edge wear (chipped paint on convex edges)
    B  damp (concrete, render) or rust (painted steel)          A  age seed 0..1 (per piece)

The Blender side (`gn/wear.py`) measures each corner (height above the piece's ground, face normal z, baked AO,
convex edge angle at the vertex, distance to the overhang above) and calls `corner()` here. The levels are kept low
on purpose: the P240 audit found the car's edge channel saturated (G = 1.0 on every wiper vertex), so G is scaled by
the edge angle, by a seeded break-up and by height, and `stats()` lets the tests hold the means down.

Shader read: SHD_HeroLit does not read COLOR_1 yet (Unity-blocked); build_places_kit.py's preview shows the proposed
read (WEAR_PREVIEW there) so the review sees the channel.
"""
from __future__ import annotations

import math

FOOT_M = 0.55          # splash band: rain and tyre spray on upright faces (Cityhub monsoon, refs fuel 11/13, garage 5/9)
FOOT_RUST_M = 0.35     # rust / rising damp band at the foot
STREAK_M = 1.2         # an overhang closer than this above a wall corner sends drip grime down it
EDGE_LOW_M = 1.3       # edges below this get knocked (hands, bumpers, trolleys) and chip more
EDGE_SPREAD_M = 0.03   # vertex wear spreads over the whole face: full G only on faces this narrow (bevel strips);
                       # a 1 m panel whose corners touch an edge gets 3 % of it, an 8 cm bollard facet 38 %, so
                       # chips stay on the edges and small saturated parts keep their paint (refs fuel 04, 14)
METAL_MATS = ("StreetKit",)   # painted steel / aluminium kit faces rust; concrete and render get damp instead


def seed(name: str) -> float:
    """Per-piece age seed 0..1 (stable across rebuilds; LODs share their piece's seed)."""
    base = name.split("__")[0].replace("_LOD1", "").replace("_LOD2", "")
    return (sum(ord(c) * (i + 3) for i, c in enumerate(base)) % 997) / 997.0


def breakup(x: float, y: float, z: float, s: float) -> float:
    """Deterministic 0..1 value noise at about 0.7 m scale (no texture): keeps the chips and dirt patchy."""
    v = math.sin(x * 2.3 + s * 17.0) * math.sin(y * 1.9 - s * 11.0) * math.sin(z * 2.7 + s * 5.0)
    w = math.sin((x + y) * 5.1 + z * 3.3 + s * 29.0)
    return min(max(0.5 + 0.45 * v + 0.2 * w, 0.0), 1.0)


def corner(z: float, nz: float, ao: float, convex_deg: float, overhang_m: float | None, metal: float,
           ground: bool, s: float, x: float = 0.0, y: float = 0.0,
           face_w: float = 0.0) -> tuple[float, float, float, float]:
    """RGBA (linear 0..1) for one face corner.
    z: height above the piece's ground (m); nz: face normal z; ao: baked AO (1 open, 0 occluded); convex_deg: the
    largest convex dihedral at the vertex (0 flat); overhang_m: distance to geometry straight above (None = sky);
    metal: 1 painted steel, 0 concrete / render; ground: a floor or forecourt face (dirt from AO and break-up only);
    face_w: the face's narrow width (area / longest edge, m; 0 = unknown, treated as narrow)."""
    n = breakup(x, y, z, s)
    upright = abs(nz) < 0.5
    if ground:
        dirt = 0.18 + 0.45 * (1.0 - ao) + 0.22 * n
        return (_c(dirt), 0.0, _c(0.12 + 0.35 * (1.0 - ao) * n), s)
    foot = max(0.0, 1.0 - z / FOOT_M) if upright else 0.0
    streak = 0.0
    if upright and overhang_m is not None and overhang_m < STREAK_M:
        streak = 0.35 * (1.0 - overhang_m / STREAK_M) * (0.5 + 0.5 * n)
    cavity = 0.4 * (1.0 - ao)
    top = 0.25 * n if nz > 0.5 else 0.0                     # dust settles on ledges and tops
    dirt = 0.06 + 0.6 * foot ** 1.5 + streak + cavity + top
    edge = 0.0
    if convex_deg > 30.0:
        k = min((convex_deg - 30.0) / 60.0, 1.0)
        reach = 1.0 if z < EDGE_LOW_M else 0.45
        spread = 1.0 if face_w <= EDGE_SPREAD_M else EDGE_SPREAD_M / face_w
        edge = 0.7 * k * reach * spread * (0.25 + 0.75 * n)
    damp_band = FOOT_RUST_M if metal else FOOT_RUST_M * 0.6
    wet = max(0.0, 1.0 - z / damp_band) if upright or z < 0.05 else 0.0
    rust = wet * (0.55 if metal else 0.4) * (0.6 + 0.4 * n)
    return (_c(dirt), _c(edge), _c(rust), s)


def stats(rows: list[tuple[float, float, float, float]]) -> dict:
    """Mean and 95th percentile per channel, and the share of corners with edge wear over 0.5."""
    out = {}
    if not rows:
        return out
    for i, ch in enumerate("rgb"):
        vals = sorted(r[i] for r in rows)
        out[ch] = {"mean": round(sum(vals) / len(vals), 4), "p95": round(vals[int(0.95 * (len(vals) - 1))], 4)}
    out["g_over_half"] = round(sum(1 for r in rows if r[1] > 0.5) / len(rows), 4)
    return out


def _c(v: float) -> float:
    return round(min(max(v, 0.0), 1.0), 4)
