"""Geometry primitives for the hand-modelled hero landmarks (V2; TDD "Hero landmarks").

Pure Python on MeshData (no bpy, no Shapely), so the generators are testable with any python3. Every hero is
authored in its own local frame: u along the building's main axis, v across it, z up from street level (the
pivot sits at road height). `HeroMesh.to_world` turns (u, v, z) into pivot-relative Blender metres (x east,
y north, z up) with the hero's yaw. Faces are tagged "bevel" (piers, columns, cornices, quoins: Bevel +
Weighted Normal in Blender) or "plain" (walls, glass, roofs: flat shaded), so the expensive bevel only runs on
the parts that catch highlights.

UV0 follows the shared atlases (Art Bible "World materials"):
- MAT_FacadeTrim_A: 4 m x 16 m sheet, four 4 m blocks stacked in v. Walls use block 0 (cream plaster) or the
  sandstone retint of it; one storey maps onto the body rows (0-0.8), so the monsoon streaks sit under every
  floor band; mouldings use the cornice row (0.8-0.9); balustrades and dentils use block 3's strips.
- MAT_TowerGlass_A: one vision pane (u 0.03-0.22, v 0.33-0.98) per window.
- MAT_RoofTerracotta / MAT_Stone_Sandstone / MAT_PlasterColonial_Cream: real-scale tiling (metres / TILE_M).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import materials as M
from .mesh import MeshData

TRIM = M.FACADE_TRIM
GLASS = M.TOWER_GLASS
ROOF = M.ROOF_TILE
SANDSTONE = M.SANDSTONE
PLASTER = M.PLASTER
PLASTER_SMOOTH = M.PLASTER_SMOOTH
TILED = {SANDSTONE, PLASTER, PLASTER_SMOOTH}   # real-scale tiling wall materials (UV = metres / TILE_M)

# FacadeTrim_A rows (fractions inside one 4 m block)
BODY = (0.0, 0.8)
CORNICE = (0.8, 0.9)
REVEAL = (0.9, 1.0)
# block 3 strips
SHUTTER = (0.0, 0.4)
PILASTER = (0.4, 0.7)
BALUSTRADE = (0.7, 0.9)
DENTIL = (0.9, 1.0)
GLASS_U = (0.03, 0.22)
GLASS_V = M.GLASS_VISION


def trim_v(block: int, row: tuple[float, float], t: float) -> float:
    """v on the FacadeTrim_A sheet for fraction t (0..1) of a row inside a block (small inset against bleeding)."""
    t = min(max(t, 0.0), 1.0)
    f = row[0] + (row[1] - row[0]) * t
    return (block + 0.004 + f * 0.992) / M.FACADE_BLOCK_COUNT


@dataclass
class HeroMesh:
    """Two MeshData buckets (plain and bevelled) in the hero's local frame."""
    yaw_deg: float = 0.0
    plain: MeshData = field(default_factory=MeshData)
    bevel: MeshData = field(default_factory=MeshData)
    layout: object = None   # hero_bays.FacadeLayout: the repeated parts, built by the GN generators

    def target(self, bevel: bool) -> MeshData:
        return self.bevel if bevel else self.plain

    @property
    def tris(self) -> int:
        return self.plain.tris + self.bevel.tris

    def to_world(self) -> tuple[MeshData, MeshData]:
        a = math.radians(self.yaw_deg)
        ca, sa = math.cos(a), math.sin(a)
        out = []
        for md in (self.plain, self.bevel):
            w = MeshData(
                [(u * ca - v * sa, u * sa + v * ca, z) for u, v, z in md.verts],
                list(md.faces), list(md.uvs), list(md.mats), list(md.materials), list(md.colors), list(md.uv2))
            out.append(w)
        return out[0], out[1]


# --- low-level faces --------------------------------------------------------------------------

def quad(m: MeshData, a, b, c, d, uvs, mat: str) -> None:
    """Counter-clockwise (seen from the front) quad a-b-c-d."""
    m.add_face([a, b, c, d], uvs, mat)


def tri(m: MeshData, a, b, c, uvs, mat: str) -> None:
    m.add_face([a, b, c], uvs, mat)


def box(m: MeshData, u0, u1, v0, v1, z0, z1, mat: str = TRIM, block: int = 0, row=CORNICE,
        bottom: bool = False, top: bool = True, tile=None) -> None:
    """Axis-aligned box in the local frame. UVs: sides u = metres / 4 along the face, v = the row spanning the
    box height; top/bottom planar. `tile` = (mu, mv) metres per UV unit switches to real-scale tiling."""
    pts = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    h = z1 - z0
    for i in range(4):
        (au, av), (bu, bv) = pts[i], pts[(i + 1) % 4]
        ln = math.hypot(bu - au, bv - av)
        if ln < 1e-6:
            continue
        s0 = (au + av) * 0.5  # some variation between faces
        if tile:
            uv = [(s0 / tile[0], z0 / tile[1]), ((s0 + ln) / tile[0], z0 / tile[1]),
                  ((s0 + ln) / tile[0], z1 / tile[1]), (s0 / tile[0], z1 / tile[1])]
        else:
            uv = [(s0 / 4, trim_v(block, row, 0)), ((s0 + ln) / 4, trim_v(block, row, 0)),
                  ((s0 + ln) / 4, trim_v(block, row, 1)), (s0 / 4, trim_v(block, row, 1))]
        quad(m, (au, av, z0), (bu, bv, z0), (bu, bv, z1), (au, av, z1), uv, mat)
    if top:
        uv = [(p[0] / 4, trim_v(block, row, (p[1] - v0) / max(v1 - v0, 1e-6))) for p in pts] if not tile else \
            [(p[0] / tile[0], p[1] / tile[1]) for p in pts]
        m.add_face([(p[0], p[1], z1) for p in pts], uv, mat)
    if bottom:
        uv = [(p[0] / 4, trim_v(block, REVEAL, 0.5)) for p in reversed(pts)] if not tile else \
            [(p[0] / tile[0], p[1] / tile[1]) for p in reversed(pts)]
        m.add_face([(p[0], p[1], z0) for p in reversed(pts)], uv, mat)
    _ = h


# --- rings and mouldings ----------------------------------------------------------------------

def ring_area(ring) -> float:
    return 0.5 * sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1] for i in range(len(ring)))


def ccw(ring):
    ring = list(ring)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring if ring_area(ring) > 0 else ring[::-1]


def offset_ring(ring, d: float):
    """Mitred outward offset of a counter-clockwise ring by d metres (negative = inward)."""
    n = len(ring)
    out = []
    for i in range(n):
        p0, p1, p2 = ring[i - 1], ring[i], ring[(i + 1) % n]
        t1 = _unit(p1[0] - p0[0], p1[1] - p0[1])
        t2 = _unit(p2[0] - p1[0], p2[1] - p1[1])
        n1 = (t1[1], -t1[0])
        n2 = (t2[1], -t2[0])
        k = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
        k = max(k, 0.2)
        out.append((p1[0] + d * (n1[0] + n2[0]) / k, p1[1] + d * (n1[1] + n2[1]) / k))
    return out


def _unit(x, y):
    ln = math.hypot(x, y) or 1.0
    return x / ln, y / ln


# --- facade edges -----------------------------------------------------------------------------

@dataclass
class Edge:
    """One straight exterior wall: a -> b with the building on the left (counter-clockwise ring)."""
    a: tuple[float, float]
    b: tuple[float, float]

    @property
    def length(self) -> float:
        return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])

    @property
    def t(self):
        return _unit(self.b[0] - self.a[0], self.b[1] - self.a[1])

    @property
    def n(self):
        """Outward normal."""
        t = self.t
        return (t[1], -t[0])

    def p(self, s: float, d: float, z: float):
        """Point s metres along the wall, d metres outward (negative = into the building), height z."""
        t, n = self.t, self.n
        return (self.a[0] + t[0] * s + n[0] * d, self.a[1] + t[1] * s + n[1] * d, z)


def wall_uv(mat, block, row, s, z, zf0, zf1):
    """UV of a wall point: tiling materials at real scale, the trim sheet with the storey on `row`."""
    if mat in TILED:
        t = M.tile(mat)
        return (s / t[0], z / t[1])
    return (s / 4, trim_v(block, row, (z - zf0) / max(zf1 - zf0, 1e-6)))


def wall_quad(m: MeshData, e: Edge, s0, s1, z0, z1, zf0, zf1, d=0.0, block=0, mat=TRIM, row=BODY, u_off=0.0) -> None:
    """Rectangle of wall on edge e (s0..s1, z0..z1) at depth d; v maps the storey zf0..zf1 onto `row`."""
    if s1 - s0 < 1e-4 or z1 - z0 < 1e-4:
        return
    uv = [wall_uv(mat, block, row, s0 + u_off, z0, zf0, zf1), wall_uv(mat, block, row, s1 + u_off, z0, zf0, zf1),
          wall_uv(mat, block, row, s1 + u_off, z1, zf0, zf1), wall_uv(mat, block, row, s0 + u_off, z1, zf0, zf1)]
    quad(m, e.p(s0, d, z0), e.p(s1, d, z0), e.p(s1, d, z1), e.p(s0, d, z1), uv, mat)


# --- boxes (roofs: PI_GN_HipRoof in citylib/gn/roof.py, from hero_bays.RoofRect) ---------------------


def edge_box(m: MeshData, e: Edge, s0, s1, d0, d1, z0, z1, mat=TRIM, block=0, row=CORNICE, top=True, bottom=False, tile=None) -> None:
    """Box aligned to a wall: s0..s1 along it, d0..d1 outward (d1 > d0), z0..z1."""
    corners = [(s0, d1), (s1, d1), (s1, d0), (s0, d0)]  # front, then around
    pts2 = [e.p(s, d, 0)[:2] for s, d in corners]
    # orientation: ensure counter-clockwise in plan
    if ring_area(pts2) < 0:
        pts2 = pts2[::-1]
    _box_from_ring(m, pts2, z0, z1, mat, block, row, top, bottom, tile)


def _box_from_ring(m, ring, z0, z1, mat, block, row, top, bottom, tile=None):
    n = len(ring)
    s = 0.0
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        if tile:
            uv = [(s / tile[0], z0 / tile[1]), ((s + ln) / tile[0], z0 / tile[1]), ((s + ln) / tile[0], z1 / tile[1]), (s / tile[0], z1 / tile[1])]
        else:
            uv = [(s / 4, trim_v(block, row, 0)), ((s + ln) / 4, trim_v(block, row, 0)), ((s + ln) / 4, trim_v(block, row, 1)), (s / 4, trim_v(block, row, 1))]
        quad(m, (*a, z0), (*b, z0), (*b, z1), (*a, z1), uv, mat)
        s += ln
    if top:
        uv = [(p[0] / 4, trim_v(block, REVEAL, 0.5)) for p in ring] if not tile else [(p[0] / tile[0], p[1] / tile[1]) for p in ring]
        m.add_face([(*p, z1) for p in ring], uv, mat)
    if bottom:
        r = list(reversed(ring))
        uv = [(p[0] / 4, trim_v(block, REVEAL, 0.5)) for p in r] if not tile else [(p[0] / tile[0], p[1] / tile[1]) for p in r]
        m.add_face([(*p, z0) for p in r], uv, mat)


def prism_ring(m: MeshData, ring, z0, z1, mat=TRIM, block=0, row=BODY, top=True, tile=None) -> None:
    """Closed vertical prism of a counter-clockwise ring (far proxies, plinths). Top is a fan (convex rings) or
    is triangulated by the caller."""
    _box_from_ring(m, ring, z0, z1, mat, block, row, top, False, tile)
