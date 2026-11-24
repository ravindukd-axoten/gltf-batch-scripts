"""Engine-agnostic mesh container: polygons with per-corner UVs and per-face material slots.

Coordinates are Blender-style world metres: x = east, y = north, z = up. blender_scene turns a
MeshData into a bpy mesh; nothing here needs bpy or Shapely.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]


@dataclass
class MeshData:
    verts: list[Vec3] = field(default_factory=list)
    faces: list[tuple[int, ...]] = field(default_factory=list)
    uvs: list[tuple[Vec2, ...]] = field(default_factory=list)  # one UV per face corner
    mats: list[int] = field(default_factory=list)  # material slot per face
    materials: list[str] = field(default_factory=list)  # slot -> material name
    colors: list[tuple[float, float, float] | None] = field(default_factory=list)  # per-face vertex colour (sRGB)
    uv2: list[tuple[Vec2, ...] | None] = field(default_factory=list)  # optional second UV set per face corner
    # P87: optional per-corner COLOR_0.A (baked contact shade, citylib/level_edges.py); None = 1.0 on every corner
    alphas: list[tuple[float, ...] | None] = field(default_factory=list)

    def slot(self, material: str) -> int:
        if material not in self.materials:
            self.materials.append(material)
        return self.materials.index(material)

    def add_face(self, pts: list[Vec3], uvs: list[Vec2], material: str,
                 color: tuple[float, float, float] | None = None, uv2: list[Vec2] | None = None,
                 alpha: list[float] | None = None) -> None:
        base = len(self.verts)
        if alpha is not None or self.alphas:
            self.alphas = self._alpha_list()
            self.alphas.append(tuple(alpha) if alpha is not None else None)
        self.verts.extend(pts)
        self.faces.append(tuple(range(base, base + len(pts))))
        self.uvs.append(tuple(uvs))
        self.mats.append(self.slot(material))
        self.colors.append(color)
        self.uv2.append(tuple(uv2) if uv2 is not None else None)

    @property
    def has_colors(self) -> bool:
        return any(c is not None for c in self.colors)

    @property
    def has_uv2(self) -> bool:
        return any(u is not None for u in self.uv2)

    def _uv2_list(self) -> list:
        return self.uv2 + [None] * (len(self.faces) - len(self.uv2))

    @property
    def has_alpha(self) -> bool:
        return any(a is not None for a in self.alphas)

    def _alpha_list(self) -> list:
        return self.alphas + [None] * (len(self.faces) - len(self.alphas))

    def corner_alpha(self, i: int) -> tuple[float, ...]:
        """COLOR_0.A of face i's corners (1.0 where no contact shade was baked)."""
        a = self.alphas[i] if i < len(self.alphas) else None
        return a if a is not None else (1.0,) * len(self.faces[i])

    def extend(self, other: "MeshData") -> None:
        base = len(self.verts)
        self.verts.extend(other.verts)
        remap = [self.slot(m) for m in other.materials]
        self.uv2 = self._uv2_list()
        if other.has_alpha or self.has_alpha:
            self.alphas = self._alpha_list() + other._alpha_list()
        for f, uv, m, c, u2 in zip(other.faces, other.uvs, other.mats, other.colors, other._uv2_list()):
            self.faces.append(tuple(i + base for i in f))
            self.uvs.append(uv)
            self.mats.append(remap[m])
            self.colors.append(c)
            self.uv2.append(u2)

    def translated(self, dx: float, dy: float, dz: float = 0.0) -> "MeshData":
        out = MeshData(
            [(x + dx, y + dy, z + dz) for x, y, z in self.verts],
            list(self.faces), list(self.uvs), list(self.mats), list(self.materials), list(self.colors),
            list(self.uv2), list(self.alphas),
        )
        return out

    @property
    def tris(self) -> int:
        return sum(len(f) - 2 for f in self.faces)

    def is_empty(self) -> bool:
        return not self.faces


def sub(a: Vec3, b: Vec3) -> Vec3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def face_normal(pts: list[Vec3]) -> Vec3:
    """Newell normal (unnormalised direction is enough for orientation checks)."""
    nx = ny = nz = 0.0
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / length, ny / length, nz / length


def rect(m: MeshData, origin: Vec3, u: Vec3, v: Vec3, material: str,
         uv_fn=None, color=None) -> None:
    """Quad origin, origin+u, origin+u+v, origin+v. Its normal is u x v (counter-clockwise from the front).
    uv_fn(point, u_len, v_len, corner_index) -> (u, v); default maps metres / 4 (the 4 m trim sheet)."""
    o = origin
    pts = [o,
           (o[0] + u[0], o[1] + u[1], o[2] + u[2]),
           (o[0] + u[0] + v[0], o[1] + u[1] + v[1], o[2] + u[2] + v[2]),
           (o[0] + v[0], o[1] + v[1], o[2] + v[2])]
    ul = math.sqrt(u[0] ** 2 + u[1] ** 2 + u[2] ** 2)
    vl = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    local = [(0.0, 0.0), (ul, 0.0), (ul, vl), (0.0, vl)]
    if uv_fn is None:
        uvs = [(a / 4.0, b / 4.0) for a, b in local]
    else:
        uvs = [uv_fn(pts[i], local[i], ul, vl) for i in range(4)]
    m.add_face(pts, uvs, material, color)


def hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def prism_ring(m: MeshData, ring: list[tuple[float, float]], z0: float, z1: float, material: str,
               color=None, cap: bool = True, taper: float = 1.0, cx: float = 0.0, cy: float = 0.0) -> None:
    """Closed vertical prism around a counter-clockwise ring (open list), optional top cap and taper
    towards (cx, cy). Used for props: posts, pots, trunks, basins."""
    top = [(cx + (x - cx) * taper, cy + (y - cy) * taper) for x, y in ring]
    n = len(ring)
    for i in range(n):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % n]
        (tax, tay), (tbx, tby) = top[i], top[(i + 1) % n]
        m.add_face([(ax, ay, z0), (bx, by, z0), (tbx, tby, z1), (tax, tay, z1)],
                   [(i / n, 0.0), ((i + 1) / n, 0.0), ((i + 1) / n, 1.0), (i / n, 1.0)], material, color)
    if cap:
        m.add_face([(x, y, z1) for x, y in top], [(0.5 + (x - cx) / 4, 0.5 + (y - cy) / 4) for x, y in top],
                   material, color)


def circle(cx: float, cy: float, r: float, n: int, phase: float = 0.0) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(phase + 2 * math.pi * i / n), cy + r * math.sin(phase + 2 * math.pi * i / n))
            for i in range(n)]


def box(m: MeshData, x0, y0, z0, x1, y1, z1, material: str, color=None, bottom: bool = False) -> None:
    """Axis-aligned box with outward normals (bottom face optional)."""
    prism_ring(m, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, material, color)
    if bottom:
        m.add_face([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
                   [(0, 0), (0, 1), (1, 1), (1, 0)], material, color)


def box_project(m: MeshData, material: str, tile: tuple[float, float] | None = None) -> None:
    """Box (tri-planar style) UVs for every face of one material: each face is projected along its
    dominant normal axis, in the mesh's own metres / the material's texture size. Used for rocks, piles
    and other chunky shapes where a single unwrap would stretch."""
    from .materials import tile as tile_of
    tu, tv = tile or tile_of(material)
    if material not in m.materials:
        return
    slot = m.materials.index(material)
    for f, face in enumerate(m.faces):
        if m.mats[f] != slot:
            continue
        pts = [m.verts[i] for i in face]
        nx, ny, nz = (abs(c) for c in face_normal(pts))
        if nz >= nx and nz >= ny:
            uv = [(p[0] / tu, p[1] / tv) for p in pts]
        elif nx >= ny:
            uv = [(p[1] / tu, p[2] / tv) for p in pts]
        else:
            uv = [(p[0] / tu, p[2] / tv) for p in pts]
        m.uvs[f] = tuple(uv)
