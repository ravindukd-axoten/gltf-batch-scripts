"""Delta Face level edges that read from the road (P87; research advanced-features-plan B3 + B5, row L).

Two build-time pieces, both 0 ms on Low (no texture, no shader change: COLOR_0.A that PaintedLit already reads as
occlusion through `_VertexAO`):

1. Contact shade baked into vertex alpha where a floor meets the foot of a level edge: the promenade along the
   0.7 m Green wall, the sand along the 2.9 m seawall toe, the Green below the north-end steps. The floor next to
   each edge is cut into two narrow profile bands (B3 strip cut, a few hundred triangles a cell) whose corners carry
   the sky visibility of a floor point in front of a long wall: vis(d, h) = 0.5 * (1 + d / sqrt(d^2 + h^2))
   (the view factor of an infinite strip), 0.5 at the foot, about 0.85 one wall height out.
2. Step runs swept along a config polyline (a curve profile: n treads and risers to the lower side) for edges the
   kit does not cover; first use: the north-end steps from the roadside paver strip down to the Green by
   One Delta Face (DELTA_FACE_MEASURED.md "North end steps", map_refs 03/04).

Config (levels file, `config/delta_face_levels.json`): `contact_shade` {strength, bands_m, edges}, and
`step_runs` [{name, line (world x east, y north), down: "left"|"right", steps, tread_m, material, source}].
Pure Shapely/Python, so the logic is unit-tested without Blender (tests/test_level_edges.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import ops
from shapely.geometry import LineString, MultiLineString, Point, Polygon

EMPTY = Polygon()


def wall_visibility(d: float, h: float) -> float:
    """Sky visibility (0..1) of a floor point d metres in front of a long wall h metres high: 1 - the view factor
    from the point to the wall face. 0.5 at the foot, 1.0 far away or for no wall."""
    if h <= 1e-6:
        return 1.0
    d = max(d, 0.0)
    return 0.5 * (1.0 + d / math.hypot(d, h))


@dataclass
class EdgeClass:
    """One kind of level edge in a cell: foot lines on the lower floor, the wall height above them, `offset_m` the
    distance from the line to the wall's real foot (the seawall's battered toe stands 1.25 m in front of its line),
    and the floor region the shade lands on."""
    name: str
    lines: MultiLineString
    height: float
    offset_m: float
    region: object

    def alpha(self, x: float, y: float, strength: float) -> float:
        d = self.lines.distance(Point(x, y)) - self.offset_m
        return 1.0 - strength * (1.0 - wall_visibility(d, self.height))


def edge_class(name: str, segs, height: float, offset_m: float, region) -> EdgeClass | None:
    lines = [LineString([p0, p1]) for p0, p1 in segs if math.dist(p0, p1) > 0.05]
    if not lines or region is None or region.is_empty:
        return None
    return EdgeClass(name, MultiLineString(lines), height, offset_m, region)


def contact_bands(ec: EdgeClass, bands_m: list[float], clip=None) -> list:
    """[(band polygon, (lo, hi) metres from the line)] on the edge's floor region: nested strips 0..b0, b0..b1, ...
    measured from the line plus offset_m, so each band edge gets its own row of vertices (the alpha is linear
    across a band). The caller cuts the union out of the floor and triangulates each band with `ec.alpha`."""
    region = ec.region if clip is None else ec.region.intersection(clip)
    if region.is_empty:
        return []
    out, inner = [], EMPTY
    for i, w in enumerate(bands_m):
        reach = ec.lines.buffer(ec.offset_m + w, cap_style="flat", join_style="mitre", mitre_limit=3.0)
        ring = region.intersection(reach).difference(inner)
        lo = 0.0 if i == 0 else ec.offset_m + bands_m[i - 1]
        if not ring.is_empty and ring.area > 0.01:
            out.append((ring, (lo, ec.offset_m + w)))
        inner = inner.union(reach)
    return out


# --- step runs (curve profile sweep) --------------------------------------------------------------------------

@dataclass
class StepRun:
    name: str
    line: LineString      # the top edge of the run (the upper level's edge)
    side: float           # +1: the run goes down to the left of the line, -1: to the right
    steps: int
    tread: float
    material: str

    @property
    def depth(self) -> float:
        return self.steps * self.tread

    def footprint(self) -> Polygon:
        return self.line.buffer(self.side * self.depth, single_sided=True, join_style="mitre")


def step_runs(levels: dict) -> list[StepRun]:
    out = []
    for r in levels.get("step_runs", []):
        side = 1.0 if r.get("down", "left") == "left" else -1.0
        out.append(StepRun(r["name"], LineString(r["line"]), side, int(r["steps"]), float(r["tread_m"]),
                           r.get("material", "MAT_Concrete_Weathered")))
    return out


def _offset(p, q, side: float, d: float):
    """Point p moved d metres to the `side` of direction p -> q."""
    L = math.dist(p, q) or 1.0
    nx, ny = -(q[1] - p[1]) / L * side, (q[0] - p[0]) / L * side
    return (p[0] + nx * d, p[1] + ny * d)


def _emit(add_face, pts, uvs, alpha, want) -> None:
    """add_face with the corners reversed when the quad's normal does not point along `want`."""
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = pts[0], pts[1], pts[2]
    ux, uy, uz, vx, vy, vz = x1 - x0, y1 - y0, z1 - z0, x2 - x0, y2 - y0, z2 - z0
    n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    if n[0] * want[0] + n[1] * want[1] + n[2] * want[2] < 0:
        pts, uvs, alpha = pts[::-1], uvs[::-1], alpha[::-1]
    add_face(list(pts), list(uvs), list(alpha))


def sweep_steps(run: StepRun, z_top, z_bottom, add_face, foot_alpha: float = 0.72, riser_alpha: float = 0.8) -> int:
    """Sweep the stair profile along the run's line: per line segment, `steps` treads and risers falling from
    z_top(x, y) (sampled 0.3 m past the upper edge) to z_bottom(x, y) (sampled 0.3 m past the foot), plus the two end
    cheeks. add_face(pts3, uvs, alpha) receives world-space quads wound to face out. Returns the face count."""
    cs = list(run.line.coords)
    n, t, s = run.steps, run.tread, run.side
    faces = 0

    def left(p, q):
        L = math.dist(p, q) or 1.0
        return (-(q[1] - p[1]) / L, (q[0] - p[0]) / L)

    def at(a, nrm, d):
        return (a[0] + nrm[0] * d, a[1] + nrm[1] * d)

    def heights(a, nrm):
        top = z_top(*at(a, nrm, -0.3))
        bot = z_bottom(*at(a, nrm, run.depth + 0.3))
        return top, (top - bot) / n

    for i, (p, q) in enumerate(zip(cs, cs[1:])):
        L = math.dist(p, q)
        if L < 0.05:
            continue
        lx, ly = left(p, q)
        nrm = (lx * s, ly * s)                       # towards the lower side
        (zt0, r0), (zt1, r1) = heights(p, nrm), heights(q, nrm)
        u = L / 2.0
        for k in range(n):
            a0, a1 = at(p, nrm, k * t), at(q, nrm, k * t)
            b0, b1 = at(p, nrm, (k + 1) * t), at(q, nrm, (k + 1) * t)
            z0, z1 = zt0 - (k + 1) * r0, zt1 - (k + 1) * r1
            zu0, zu1 = zt0 - k * r0, zt1 - k * r1
            _emit(add_face, [(a0[0], a0[1], z0), (a1[0], a1[1], z1), (a1[0], a1[1], zu1), (a0[0], a0[1], zu0)],
                  [(0, 0), (u, 0), (u, r1 / 2.0), (0, r0 / 2.0)], [riser_alpha, riser_alpha, 1.0, 1.0],
                  (nrm[0], nrm[1], 0.0))
            _emit(add_face, [(a0[0], a0[1], z0), (b0[0], b0[1], z0), (b1[0], b1[1], z1), (a1[0], a1[1], z1)],
                  [(0, 0), (0, t / 2.0), (u, t / 2.0), (u, 0)], [foot_alpha, 1.0, 1.0, foot_alpha], (0.0, 0.0, 1.0))
            faces += 2
        ends = []
        if i == 0:
            ends.append((p, zt0, r0, (-(q[0] - p[0]) / L, -(q[1] - p[1]) / L)))
        if i == len(cs) - 2:
            ends.append((q, zt1, r1, ((q[0] - p[0]) / L, (q[1] - p[1]) / L)))
        for e, zt, r, out in ends:
            zb = zt - n * r
            for k in range(n - 1):                   # the last tread is the landing at the foot level: no cheek
                c0, c1 = at(e, nrm, k * t), at(e, nrm, (k + 1) * t)
                zk = zt - (k + 1) * r
                _emit(add_face, [(c0[0], c0[1], zb), (c1[0], c1[1], zb), (c1[0], c1[1], zk), (c0[0], c0[1], zk)],
                      [(0, 0), (t / 2, 0), (t / 2, r), (0, r)], [riser_alpha, riser_alpha, 1.0, 1.0], (out[0], out[1], 0.0))
                faces += 1
    return faces


def footprints(runs: list[StepRun]):
    return ops.unary_union([r.footprint() for r in runs]) if runs else EMPTY
