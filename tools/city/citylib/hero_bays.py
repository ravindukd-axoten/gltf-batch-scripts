"""Bay layout for the Geometry Nodes facade generators (TDD "Blender asset methods"; pure Python, no bpy).

The hero facades are repeated bays: arcade bays (arch, piers, soffit, veranda), window bays (opening, reveal,
glass, surround, sill, shutters, fanlight, awning) and balustrade runs. Python decides *where* they go (bay
spacing from the footprint edges, the same `bays()` rule as before); the GN generators in `citylib/gn/facade.py`
decide *what* one bay looks like from the parameters below. Everything here is plain data so it is testable
with any python3:

- `FacadeLayout.bays`: one `BaySet` per distinct parameter set (one GN object each), holding `BayPoint`s in
  the hero's local frame (u along the building, v across, z up): the bay centre on the wall plane at the
  floor line, the wall direction and `s0`, the bay centre's distance along its wall (plaster UV continuity).
- `FacadeLayout.runs`: balustrade runs (start, end, posts at the ends) and `rings`: moulding runs (cornices,
  string courses, the dark plinth) as open polylines with a profile name and the trim row they map to.
- `trim_map()` is the UV row rule the generators use: FacadeTrim_A is four 4 m blocks stacked in v, each with
  wall body 0-0.8, cornice 0.8-0.9 and reveal 0.9-1.0 (Art Bible "World materials").
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

FACADE_BLOCK_COUNT = 4
BLOCK_INSET = 0.004          # keep UVs off the block edges (mip bleeding), as materials.to_world_materials

# FacadeTrim_A rows inside one 4 m block (fractions of the block height)
BODY = (0.0, 0.8)
CORNICE = (0.8, 0.9)
REVEAL = (0.9, 1.0)


def trim_map(block: int, row: tuple[float, float]) -> tuple[float, float]:
    """(scale, offset) so that v = offset + scale * t puts t = 0..1 across `row` of FacadeTrim_A block `block`."""
    if not 0 <= block < FACADE_BLOCK_COUNT:
        raise ValueError(f"block {block} not on the sheet")
    if not 0.0 <= row[0] < row[1] <= 1.0:
        raise ValueError(f"bad row {row}")
    k = (1.0 - 2 * BLOCK_INSET) / FACADE_BLOCK_COUNT
    offset = block / FACADE_BLOCK_COUNT + (BLOCK_INSET + row[0] * (1.0 - 2 * BLOCK_INSET)) / FACADE_BLOCK_COUNT
    return (row[1] - row[0]) * k, offset


def trim_v(block: int, row: tuple[float, float], t: float) -> float:
    s, o = trim_map(block, row)
    return o + s * min(max(t, 0.0), 1.0)


def bays(length: float, spacing: float, margin: float, min_n: int = 1) -> list[float]:
    """Centres of evenly spaced bays along a wall, keeping `margin` clear at both ends."""
    usable = length - 2 * margin
    n = int(usable // spacing) if spacing > 0 else 0
    if n < min_n:
        return []
    start = margin + (usable - n * spacing) / 2 + spacing / 2
    return [start + i * spacing for i in range(n)]


def bay_extents(length: float, spacing: float, margin: float) -> tuple[list[float], list[tuple[float, float]]]:
    """Bay centres and the plain wall strips left over at the two ends (contiguous bays of width `spacing`)."""
    centres = bays(length, spacing, margin)
    if not centres:
        return [], [(0.0, length)]
    left, right = centres[0] - spacing / 2, centres[-1] + spacing / 2
    return centres, [(0.0, left), (right, length)]


@dataclass(frozen=True)
class BayPoint:
    u: float
    v: float
    z: float
    angle: float      # wall direction in the local frame (radians from +u); the building is on its left
    s0: float         # bay centre's distance along its wall (metres)


@dataclass
class BaySet:
    generator: str            # node group name, e.g. "PI_GN_ArcadeBay"
    params: dict              # node group inputs (by interface name)
    points: list[BayPoint] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (self.generator, tuple(sorted(self.params.items())))


@dataclass(frozen=True)
class Run:
    """Balustrade run from a to b (local frame, z = the base it stands on); posts at the flagged ends."""
    a: tuple[float, float, float]
    b: tuple[float, float, float]
    post_a: bool = True
    post_b: bool = True

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)


@dataclass(frozen=True)
class Moulding:
    """A moulding swept along an open polyline (local frame, z in the profile) by PI_GN_CorniceRun."""
    points: tuple[tuple[float, float], ...]
    z: float
    profile: str              # profile name (citylib/gn/facade.PROFILES)
    block: int = 0
    row: tuple[float, float] = CORNICE
    material: str = ""        # "" = MAT_FacadeTrim_A


def hip_lines(u0, u1, v0, v1, z, pitch_deg, overhang, gablet=0.0, lift=0.03):
    """Ridge and hip lines of a PI_GN_HipRoof roof (rect plus overhang, the same gablet rule) for the ridge and
    hip tile rolls: [[(u, v, z), ...], ...]."""
    u0, u1, v0, v1 = u0 - overhang, u1 + overhang, v0 - overhang, v1 + overhang
    swap = (v1 - v0) > (u1 - u0)
    if swap:
        u0, u1, v0, v1 = v0, v1, u0, u1
    t = math.tan(math.radians(pitch_deg))
    w = (v1 - v0) / 2
    vc = (v0 + v1) / 2
    zr = z + w * t
    f = min(max(gablet, 0.0), 0.9)
    zg = z + (1 - f) * w * t
    ug0, ug1 = u0 + (1 - f) * w, u1 - (1 - f) * w
    if ug1 < ug0:
        ug0 = ug1 = (u0 + u1) / 2
    fw = f * w
    lines = []
    if ug1 - ug0 > 1e-3:
        lines.append([(ug0, vc, zr), (ug1, vc, zr)])
    for (cu, cv, gu, gv) in ((u0, v0, ug0, vc - fw), (u0, v1, ug0, vc + fw), (u1, v0, ug1, vc - fw), (u1, v1, ug1, vc + fw)):
        lines.append([(cu, cv, z), (gu, gv, zg)])
    out = []
    for line in lines:
        out.append([((y, x, zz + lift) if swap else (x, y, zz + lift)) for x, y, zz in line])
    return out


@dataclass(frozen=True)
class RoofRect:
    """A hipped roof for PI_GN_HipRoof (citylib/gn/roof.py): the eave rectangle with the overhang already added
    (local frame), the eave height z, the pitch in degrees, the Dutch gablet fraction (0 = plain hip) and the
    fascia depth under the eave (0 = none: LOD1 and the far proxy)."""
    u0: float
    u1: float
    v0: float
    v1: float
    z: float
    pitch: float
    gablet: float = 0.0
    fascia: float = 0.0

    @property
    def long_is_u(self) -> bool:
        return (self.u1 - self.u0) >= (self.v1 - self.v0)

    @property
    def length(self) -> float:
        return max(self.u1 - self.u0, self.v1 - self.v0)

    @property
    def width(self) -> float:
        return min(self.u1 - self.u0, self.v1 - self.v0)

    @property
    def ridge_z(self) -> float:
        return self.z + self.width / 2 * math.tan(math.radians(self.pitch))

    @property
    def gablet_z(self) -> float:
        f = min(max(self.gablet, 0.0), 0.9)
        return self.z + (1 - f) * self.width / 2 * math.tan(math.radians(self.pitch))


def roof_rect(u0, u1, v0, v1, z, pitch_deg, overhang, gablet=0.0, fascia=0.0) -> RoofRect:
    """RoofRect over the wall rectangle u0..u1 x v0..v1 plus `overhang` all round (the old hero_geom.hip_roof
    arguments)."""
    return RoofRect(u0 - overhang, u1 + overhang, v0 - overhang, v1 + overhang, z, pitch_deg,
                    min(max(gablet, 0.0), 0.9), fascia)


def roof_lines(r: RoofRect, lift=0.03) -> list[list[tuple[float, float, float]]]:
    """Ridge, hips and (with a gablet) the gablet rakes of a RoofRect for the ridge-tile rolls."""
    lines = hip_lines(r.u0, r.u1, r.v0, r.v1, r.z, r.pitch, 0.0, r.gablet, lift)
    if r.gablet > 1e-4:
        for g in gablets(r):
            a, c, b = g
            lines += [[(a[0], a[1], a[2] + lift), (c[0], c[1], c[2] + lift)], [(c[0], c[1], c[2] + lift), (b[0], b[1], b[2] + lift)]]
    return lines


def gablets(r: RoofRect) -> list[tuple]:
    """The gablet triangles of a RoofRect: [(foot a, apex, foot b), ...] in the local frame, listed so that
    a -> b runs with the gablet's outward side on its right (a moulding swept along a -> b faces out)."""
    f = min(max(r.gablet, 0.0), 0.9)
    if f <= 1e-4:
        return []
    w = r.width / 2
    fw = f * w
    zg, zr = r.gablet_z, r.ridge_z
    out = []
    if r.long_is_u:
        vc = (r.v0 + r.v1) / 2
        ug0, ug1 = r.u0 + (1 - f) * w, r.u1 - (1 - f) * w
        out.append(((ug0, vc + fw, zg), (ug0, vc, zr), (ug0, vc - fw, zg)))   # outward -u: travel -v
        out.append(((ug1, vc - fw, zg), (ug1, vc, zr), (ug1, vc + fw, zg)))   # outward +u: travel +v
    else:
        uc = (r.u0 + r.u1) / 2
        vg0, vg1 = r.v0 + (1 - f) * w, r.v1 - (1 - f) * w
        out.append(((uc - fw, vg0, zg), (uc, vg0, zr), (uc + fw, vg0, zg)))   # outward -v: travel +u
        out.append(((uc + fw, vg1, zg), (uc, vg1, zr), (uc - fw, vg1, zg)))   # outward +v: travel -u
    return out


def ring_bay_points(ring, z) -> list[BayPoint]:
    """One bay per edge of a counter-clockwise ring (a small building: the gate lodge), centred on the edge."""
    pts = []
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        pts += edge_bay_points(a, b, [math.dist(a, b) / 2], z)
    return pts


@dataclass
class FacadeLayout:
    bays: dict = field(default_factory=dict)          # key -> BaySet
    runs: list[Run] = field(default_factory=list)
    mouldings: list[Moulding] = field(default_factory=list)
    brackets: list[tuple[tuple[float, float], tuple[float, float], float]] = field(default_factory=list)  # (a, b, z)
    ridges: list[list[tuple[float, float, float]]] = field(default_factory=list)   # ridge / hip tile rolls
    pipes: list[tuple[tuple[float, float], float, float]] = field(default_factory=list)  # downpipes: (u, v), z0, z1
    roofs: list[RoofRect] = field(default_factory=list)         # hipped roofs (PI_GN_HipRoof)
    walls: list[Run] = field(default_factory=list)              # boundary wall runs, gate piers at flagged ends (PI_GN_BoundaryWall)
    baluster_spacing: float = 0.36                              # PI_GN_Balustrade 'Spacing' (m between balusters)
    # SLICE6: every facade storey as built, for the wear decals and shopfront awnings (citylib/wear_decals.py):
    # (a, b, zf0, zf1, style, [(bay centre s, code, (s0, s1, z0, z1) opening extent)])
    facades: list = field(default_factory=list)

    def add_bay(self, generator: str, params: dict, pt: BayPoint) -> None:
        bs = BaySet(generator, dict(params))
        self.bays.setdefault(bs.key, bs).points.append(pt)

    @property
    def bay_count(self) -> int:
        return sum(len(b.points) for b in self.bays.values())


def edge_bay_points(a, b, centres, z) -> list[BayPoint]:
    """BayPoints for bay centres (distances along the wall a -> b) at floor height z."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1.0
    tx, ty = dx / ln, dy / ln
    ang = math.atan2(ty, tx)
    return [BayPoint(a[0] + tx * s, a[1] + ty * s, z, ang, s) for s in centres]


def split_run(a, b, max_len: float) -> list[Run]:
    """Split a long balustrade into equal runs no longer than max_len (a post at every joint, gf_20)."""
    ln = math.dist(a, b)
    n = max(1, math.ceil(ln / max_len - 1e-9))
    pts = [tuple(a[k] + (b[k] - a[k]) * i / n for k in range(3)) for i in range(n + 1)]
    return [Run(pts[i], pts[i + 1]) for i in range(n)]


def opening_runs(a, b, z, depth, openings) -> list[Run]:
    """Balustrade runs across arcade openings [(s_a, s_b)] on wall a -> b, `depth` metres into the building,
    without posts (the arch piers stand at both ends)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1.0
    tx, ty = dx / ln, dy / ln
    nx, ny = -ty, tx  # into the building (left of a -> b)
    out = []
    for sa, sb in openings:
        pa = (a[0] + tx * sa + nx * depth, a[1] + ty * sa + ny * depth, z)
        pb = (a[0] + tx * sb + nx * depth, a[1] + ty * sb + ny * depth, z)
        out.append(Run(pa, pb, False, False))
    return out


def open_ring(ring) -> list[tuple[float, float]]:
    """A closed ring as an open polyline that starts and ends at the middle of its longest edge, so a profile
    swept along it has its UV seam and its start/end on a straight run (every corner gets a mitre)."""
    n = len(ring)
    if n < 3:
        return list(ring)
    k = max(range(n), key=lambda i: math.dist(ring[i], ring[(i + 1) % n]))
    a, b = ring[k], ring[(k + 1) % n]
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    pts = [mid] + [ring[(k + 1 + i) % n] for i in range(n)] + [mid]
    return pts


BAY_CODES = "FSDA-"   # SLICE6 per-bay variants: F glazed (the style's window), S closed louvred doors, D open
                      # doorway (dark interior card), A shop window (wide, square head, awning built by the hero), - plain


def window_params(st, zf0: float, zf1: float, bay_w: float, lod: int, code: str = "F") -> dict:
    """PI_GN_WindowGrid inputs for one storey of a window FacadeStyle (old hero_blocks rules kept); `code` is the
    bay's variant (BAY_CODES)."""
    win_w = st.win_w
    if code == "A":
        win_w = round(max(st.win_w, bay_w - 0.7), 4)
    hw = win_w / 2
    sill = st.sill
    top = min(zf0 + sill + st.win_h, zf1 - 0.5) - zf0
    arched = bool(st.arched_windows or st.french) and code != "A"
    if arched:
        top += hw * 0.3
    if code == "A":
        top = min(top, 3.2)
    p = {
        "Bay Width": round(bay_w, 4), "Storey Height": round(zf1 - zf0, 4), "Window Width": win_w,
        "Window Height": round(top - sill, 4), "Sill Height": sill, "Arched": arched,
        "Segments": (6 if st.french else 4) if lod == 0 else 4, "Reveal Depth": 0.3 if lod == 0 else 0.2,
        "Detail": lod,
    }
    if code in ("S", "D"):
        p["Closed" if code == "S" else "Dark"] = True
    if lod == 0:
        fr = bool(st.french) and code != "A"
        p.update({"Surround": bool(st.surround and not fr and not st.awnings and code != "A"), "Sill": bool(st.surround and not fr and code != "A"),
                  "Hood": bool(st.surround and not arched and not st.awnings and code != "A"), "Keystone": bool(st.surround and arched),
                  "Shutters": bool(st.shutters) and code == "F", "Awning": bool(st.awnings) and code != "A", "Fanlight": fr})
    return p


def opening_extent(st, code: str, zf0: float, zf1: float, bay_w: float) -> tuple[float, float, float]:
    """(half width incl. surround, z0, z1) of a bay's opening, for decals that must not cross it."""
    if st.kind == "arcade":
        return st.arch_w / 2 + 0.05, zf0, zf1 - st.crown_gap
    p = window_params(st, zf0, zf1, bay_w, 1, code)
    return p["Window Width"] / 2 + 0.16, zf0 + p["Sill Height"] - 0.16, zf0 + p["Sill Height"] + p["Window Height"] + 0.2


def arcade_params(st, zf0: float, zf1: float, lod: int, veranda: bool = True) -> dict:
    # SLICE5: arcade arcs 7 -> 6 segments and French fanlights 8 -> 6 (window_params) pay for the gate's depth;
    # SLICE6: 5 segments except the Green front's wide arches (h05, h07), paying for the street bays and decals
    p = {"Bay Width": st.spacing, "Storey Height": round(zf1 - zf0, 4), "Arch Width": st.arch_w,
         "Crown Gap": st.crown_gap, "Pier Depth": 0.6, "Segments": 6 if lod == 0 and st.arch_w >= 2.7 else 5, "Detail": lod}
    if lod == 0:
        p["Veranda Depth"] = st.veranda if veranda else 0.0
    elif veranda and st.veranda > 0.0:
        p["Recess Depth"] = st.veranda   # P46e: the LOD1 arch is as deep as the LOD0 veranda (gf_19, Low forecourt)
    return p


def downpipe_spots(a, b, min_len=12.0, inset=0.55, off=0.13):
    """Rainwater downpipe position on wall a -> b (building on the left): near its start corner, standing `off`
    proud of the wall; walls shorter than `min_len` get none."""
    ln = math.dist(a, b)
    if ln < min_len:
        return []
    tx, ty = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
    return [(a[0] + tx * inset + ty * off, a[1] + ty * inset - tx * off)]
