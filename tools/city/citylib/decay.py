"""Wear and decay layer (P123 signs first; road, buildings, props and vehicles reuse it). Pure Python, no bpy.

The standard game method (research 3: no extra materials or draw calls per instance):
1. Seeded per-instance state: `decay(id, profile)` gives age (years), condition (good / worn / poor / damaged) and
   the derived numbers below from a stable hash of the instance id, so every run gives the same city.
2. Atlas / trim variants: each surface has a few painted age variants in its shared atlas (wear 0 new, 1 weathered,
   2 old; citylib/decay_paint.py paints them from the clean cell). An instance picks its variant mesh by `wear`
   (`variant_suffix`), so the variants share the one material and merge into the cell's draw.
3. Vertex colour (COLOR_0, read by SHD_HeroLit): rgb = grime multiply (bottom splash, edges), a = baked AO. Use
   `vertex_rgba` with a height, an AO term and an edge (curvature) term per vertex.
4. Small mesh variation: `bent` variants warp outline vertices (no extra triangles); lean / tilt is the marker's
   rotation (`lean_matrix`, `compose`), free at run time.
5. Decals: a few extra small quads (posters, stickers, footing patches) on the same atlas, placed per instance and
   capped by the cell's triangle budget.
"""
from __future__ import annotations

import math
import random

WEARS = (0, 1, 2)                    # new, weathered, old (atlas variants)
CONDITIONS = ("good", "worn", "poor", "damaged")

# per kit family: age bands (cumulative share, min years, max years), wear cut-offs (years), lean (deg) per condition,
# chance of a poster / sticker per condition. Delta Face is a kept-up seafront: most street furniture 4-10 years old.
PROFILES = {
    "sign": {"ages": [(0.22, 0, 3), (0.67, 4, 10), (1.0, 11, 20)], "wear_cut": (3, 10),
             "lean": {"good": (0.0, 0.8), "worn": (0.4, 1.8), "poor": (1.5, 3.5), "damaged": (3.0, 6.0)},
             "decal": {"good": 0.05, "worn": 0.25, "poor": 0.45, "damaged": 0.6}},
    "prop": {"ages": [(0.25, 0, 3), (0.7, 4, 10), (1.0, 11, 25)], "wear_cut": (3, 10),
             "lean": {"good": (0.0, 0.5), "worn": (0.2, 1.2), "poor": (1.0, 2.5), "damaged": (2.0, 5.0)},
             "decal": {"good": 0.05, "worn": 0.2, "poor": 0.4, "damaged": 0.5}},
    "road": {"ages": [(0.15, 0, 2), (0.6, 3, 8), (1.0, 9, 20)], "wear_cut": (2, 8),
             "lean": {c: (0.0, 0.0) for c in CONDITIONS},
             "decal": {"good": 0.1, "worn": 0.3, "poor": 0.6, "damaged": 0.8}},
    "building": {"ages": [(0.1, 0, 5), (0.5, 6, 25), (1.0, 26, 120)], "wear_cut": (5, 25),
                 "lean": {c: (0.0, 0.0) for c in CONDITIONS},
                 "decal": {"good": 0.05, "worn": 0.2, "poor": 0.4, "damaged": 0.6}},
}


def stable_hash(s: str) -> int:
    """FNV-1a 32 bit: the same on every machine and Python (unlike hash())."""
    h = 2166136261
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def decay(uid: str, profile: str = "sign") -> dict:
    """Seeded age / condition and what follows from them for one instance."""
    p = PROFILES[profile]
    seed = stable_hash(f"{profile}:{uid}")
    rng = random.Random(seed)
    r = rng.random()
    lo, hi = next((a, b) for c, a, b in p["ages"] if r <= c)
    age = rng.randint(lo, hi)
    top = p["ages"][-1][2]
    k = age / top
    c = rng.random()
    if c < 0.02 + 0.03 * k:
        cond = "damaged"
    elif c < 0.10 + 0.22 * k:
        cond = "poor"
    elif c < 0.35 + 0.35 * k:
        cond = "worn"
    else:
        cond = "good"
    w0, w1 = p["wear_cut"]
    wear = 0 if age <= w0 else 1 if age <= w1 else 2
    bent = cond == "damaged" or (cond == "poor" and rng.random() < 0.5)
    a, b = p["lean"][cond]
    lean = round(a + (b - a) * rng.random(), 2)
    az = round(rng.random() * 360.0, 1)
    decal = rng.random() < p["decal"][cond]
    return {"seed": seed, "age_years": age, "condition": cond, "wear": wear, "bent": bent,
            "lean_deg": lean, "lean_az_deg": az, "decal": decal, "pick": round(rng.random(), 4)}


def variant_suffix(wear: int, bent: bool = False) -> str:
    """Mesh / atlas variant name: '' for new and straight, else _W1, _W2, plus _Bent."""
    return ("" if wear == 0 else f"_W{wear}") + ("_Bent" if bent else "")


# ---- lean: world rotation about a horizontal axis, composed with the instance yaw, as Blender XYZ Euler ----------
def lean_matrix(lean_deg: float, az_deg: float):
    """Rotation that tips +z toward the horizontal direction az (deg from +x, counter-clockwise) by lean_deg."""
    t = math.radians(lean_deg)
    a = math.radians(az_deg)
    ux, uy = -math.sin(a), math.cos(a)          # rotation axis, perpendicular to the tip direction
    c, s = math.cos(t), math.sin(t)
    C = 1 - c
    return [[c + ux * ux * C, ux * uy * C, uy * s],
            [uy * ux * C, c + uy * uy * C, -ux * s],
            [-uy * s, ux * s, c]]


def matmul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def apply(M, v):
    return tuple(sum(M[i][k] * v[k] for k in range(3)) for i in range(3))


def rot_z(yaw: float):
    c, s = math.cos(yaw), math.sin(yaw)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def euler_xyz(M) -> tuple[float, float, float]:
    """Blender XYZ Euler (R = Rz @ Ry @ Rx) of a rotation matrix."""
    ry = -math.asin(max(-1.0, min(1.0, M[2][0])))
    rx = math.atan2(M[2][1], M[2][2])
    rz = math.atan2(M[1][0], M[0][0])
    return rx, ry, rz


def compose(L, yaw: float) -> tuple[float, float, float]:
    """Euler of the lean L applied after the instance's own yaw."""
    return euler_xyz(matmul(L, rot_z(yaw)))


# ---- vertex colour ------------------------------------------------------------------------------------------------
GRIME = (0.78, 0.72, 0.62)   # road dust / splash multiply at full strength (warm grey-brown)
WEAR_GRIME = (0.35, 0.65, 1.0)


def vertex_rgba(h01: float, ao: float = 1.0, edge: float = 0.0, wear: int = 1) -> tuple[float, float, float, float]:
    """COLOR_0 for one vertex: h01 = height in the piece (0 bottom .. 1 top), ao = baked occlusion (1 open),
    edge = convexity / exposure (0..1: edges catch dust and lose paint). rgb multiplies the albedo (never black:
    SHD_HeroLit reads rgb 0 as glass), a is AO."""
    g = WEAR_GRIME[wear] * (0.55 * (1.0 - h01) ** 2 + 0.25 * edge + 0.2 * (1.0 - ao))
    g = max(0.0, min(1.0, g))
    rgb = tuple(round(1.0 - (1.0 - c) * g, 4) for c in GRIME)
    return (*rgb, round(max(0.2, min(1.0, ao)), 4))
