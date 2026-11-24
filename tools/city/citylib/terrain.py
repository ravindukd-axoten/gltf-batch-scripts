"""Terrain levels: the one heights source the layout, cells, dressing, vegetation and heroes read (SLICE3).

Delta Face is not flat (agent, 2026-11-16). The datum surfaces stay in `layout.Heights` (sea, carriageway, kerb,
promenade step); on top of them a levels file (config key "levels_file", e.g. config/delta_face_levels.json)
lists named level areas, each a polygon (world metres, or a hero's own u/v frame) with a height offset `dz`
from the plot datum (pavements, the Green, building plots), a source photo and an ESTIMATE flag:

- `ramp_m` > 0: a smooth ramp from dz back to the datum over that many metres outside the polygon;
- `ramp_m` == 0: a hard step; the layout adds a vertical wall face (`edge`: "retaining" rubble or "terrace"
  white render) wherever the polygon edge meets lower ground.

Roads never take an offset (the drivable lanes and RouteColliderTests stay at the carriageway datum); areas
apply to the ground surfaces only. Areas are applied in file order and an earlier area wins where they
overlap (put the specific ones first). Spot heights are recorded measurements the tests check against.

City-wide later: add areas per district in the same file format, or fill `dz` from a coarse DEM sampled into
the same polygons (needs the agent's OK before any download). Nothing else in the pipeline changes.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import shapely
import shapely.prepared
from shapely import ops
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient


@dataclass
class LevelArea:
    name: str
    poly: Polygon            # world metres
    dz: float                # offset from the plot datum (m)
    ramp_m: float = 0.0
    edge: str = "retaining"  # hard-step wall kind: "retaining" | "terrace" | "none"
    source: str = ""
    estimate: bool = True
    clip: Polygon | None = None  # P87: the ramp only spreads inside this polygon (e.g. into the Green, not the pavement)
    ramp_to: str = "datum"       # P117: "below" ramps to the later areas' height (a deeper pit inside a lower area)
    relief: bool = False         # HEIGHTS 2026-11-24: the lawn relief (crown, mounds) still applies inside this area

    def reach(self, quad_segs: int = 8):
        r = self.poly.buffer(self.ramp_m, quad_segs=quad_segs) if self.ramp_m > 0 else self.poly
        return r if self.clip is None else self.poly.union(r.intersection(self.clip))


@dataclass
class Relief:
    """Gentle ground relief over a lawn (ROADS2 / Green levels, agent 2026-11-19 'the Green is not flat'): a crown that
    rises from the road side toward the sea, plus smooth mounds from value noise, both faded to zero within edge_m of
    the region's boundary, so kerbs, the promenade wall, the steps and every level area keep their datum heights.
    All numbers are estimates from photos (no survey or DEM resolves the Green): see DELTA_FACE_MEASURED.md."""
    name: str
    region: Polygon            # where the relief applies (world metres)
    land_edge: object          # line the crown rises from (the road side)
    sea_edge: object           # line the crown rises toward (the coast)
    crown_m: float = 0.3       # extra height reached at crown_at across the width
    crown_at: float = 0.7      # 0 = road side, 1 = sea side
    mound_m: float = 0.25      # +- amplitude of the mounds
    mound_scale_m: float = 35.0
    edge_m: float = 6.0
    grid_m: float = 8.0        # triangulation grid inside the region (LOD0 and collision)
    seed: int = 7
    source: str = ""

    def __post_init__(self):
        self._prep = shapely.prepared.prep(self.region)
        self._bnd = self.region.boundary

    def dz(self, x: float, y: float) -> float:
        p = Point(x, y)
        if not self._prep.covers(p):
            return 0.0
        e = self._bnd.distance(p) / self.edge_m
        if e <= 0.0:
            return 0.0
        fade = 1.0 if e >= 1.0 else e * e * (3.0 - 2.0 * e)
        dl, ds = self.land_edge.distance(p), self.sea_edge.distance(p)
        t = dl / (dl + ds) if dl + ds > 0 else 0.0
        # crown: smooth rise to crown_m at crown_at, easing back a little toward the sea edge (the fade does the rest)
        c = t / self.crown_at if t < self.crown_at else 1.0 - 0.3 * (t - self.crown_at) / max(1e-6, 1.0 - self.crown_at)
        crown = self.crown_m * (c * c * (3.0 - 2.0 * c) if t < self.crown_at else c)
        return fade * (crown + self.mound_m * _noise(x, y, self.mound_scale_m, self.seed))


def _noise(x: float, y: float, scale: float, seed: int) -> float:
    """Smooth value noise in [-1, 1] (two octaves), deterministic."""
    def lattice(i, j):
        h = (i * 374761393 + j * 668265263 + seed * 2147483647) & 0xFFFFFFFF
        h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
        return ((h ^ (h >> 16)) & 0xFFFF) / 32767.5 - 1.0

    def octave(u, v):
        i, j = math.floor(u), math.floor(v)
        fu, fv = u - i, v - j
        su, sv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
        a = lattice(i, j) + (lattice(i + 1, j) - lattice(i, j)) * su
        b = lattice(i, j + 1) + (lattice(i + 1, j + 1) - lattice(i, j + 1)) * su
        return a + (b - a) * sv
    return 0.7 * octave(x / scale, y / scale) + 0.3 * octave(x / (scale * 0.45) + 17.3, y / (scale * 0.45) - 5.1)


@dataclass
class Grade:
    """A road profile (HEIGHTS 2026-11-24): heights `profile` [(station m, dz m)] along `line` (from the line's first
    point), full strength within half_width_m of the line, smoothstep to nothing over falloff_m beyond it, and faded in
    over end_fade_m past either end. dz is added to every surface there, roads included (Terrain.grade)."""
    name: str
    line: object               # shapely LineString, world metres
    profile: list              # [(station_m, dz_m)], stations increasing
    half_width_m: float = 12.0
    falloff_m: float = 25.0
    end_fade_m: float = 0.0
    source: str = ""
    estimate: bool = True

    def at(self, s: float) -> float:
        pr = self.profile
        if s <= pr[0][0]:
            return pr[0][1]
        for (s0, z0), (s1, z1) in zip(pr, pr[1:]):
            if s <= s1:
                t = (s - s0) / (s1 - s0) if s1 > s0 else 1.0
                t = t * t * (3.0 - 2.0 * t)   # smooth vertical curves between the stations
                return z0 + (z1 - z0) * t
        return pr[-1][1]

    def sample(self, x: float, y: float) -> tuple[float, float]:
        """(weight, dz) at a point: weight 1 on the road and its pavements, smoothstep to 0 at the falloff edge."""
        p = Point(x, y)
        d = self.line.distance(p)
        reach = self.half_width_m + self.falloff_m
        if d >= reach:
            return 0.0, 0.0
        s = self.line.project(p)
        w = 1.0 if d <= self.half_width_m else _smooth(1.0 - (d - self.half_width_m) / max(1e-6, self.falloff_m))
        if self.end_fade_m > 0.0 and (s <= 1e-6 or s >= self.line.length - 1e-6):
            # past an end of the line: fade by the distance beyond the end point
            end = Point(self.line.coords[0] if s <= 1e-6 else self.line.coords[-1])
            w *= _smooth(1.0 - min(1.0, end.distance(p) / self.end_fade_m))
        return w, self.at(s)


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


@dataclass
class Terrain:
    areas: list[LevelArea] = field(default_factory=list)
    spots: list[dict] = field(default_factory=list)
    features: dict = field(default_factory=dict)   # named polylines (world metres), e.g. a sea balustrade
    datum: dict = field(default_factory=dict)       # Heights overrides
    reliefs: list = field(default_factory=list)     # Relief: smooth lawn height fields (the Green)
    grades: list = field(default_factory=list)      # Grade: road profiles that lift whole streets (Baladaksha, bridges)
    layer_levels: list = field(default_factory=list)  # raw "layer_levels" specs, turned into areas by the layout
    green_dz: float = 0.0                           # the Green's level below the plot datum (set by the layout)

    @property
    def empty(self) -> bool:
        return not self.areas and not self.reliefs

    def relief_dz(self, x: float, y: float) -> float:
        return sum(r.dz(x, y) for r in self.reliefs) if self.reliefs else 0.0

    def relief_cells(self, geom, coarse: bool = False):
        """Split geom by each relief's grid (pieces outside every relief returned whole), so a triangulation gets
        vertices inside the lawn and follows the relief; grid lines are shared, so neighbours meet without cracks."""
        if not self.reliefs or geom is None or geom.is_empty:
            return [geom]
        out, rest = [], geom
        for r in self.reliefs:
            if not r.region.intersects(rest):
                continue
            inside = rest.intersection(r.region)
            rest = rest.difference(r.region)
            if inside.is_empty or any(math.isnan(v) for v in inside.bounds):
                continue  # a touch-only overlap (or an invalid piece) leaves nothing to grid
            g = r.grid_m * (2.0 if coarse else 1.0)
            x0, y0, x1, y1 = inside.bounds
            i0, j0 = math.floor(x0 / g), math.floor(y0 / g)
            for i in range(i0, math.floor(x1 / g) + 1):
                for j in range(j0, math.floor(y1 / g) + 1):
                    sq = Polygon([(i * g, j * g), ((i + 1) * g, j * g), ((i + 1) * g, (j + 1) * g), (i * g, (j + 1) * g)])
                    if not sq.intersects(inside):
                        continue
                    piece = inside.intersection(sq)
                    if not piece.is_empty and piece.area > 1e-4:
                        out.append(shapely.segmentize(piece, g / 2.0))
        if not rest.is_empty:
            out.append(rest)
        return out

    def dz(self, x: float, y: float) -> float:
        """Ground offset from the plot datum at (x, y): the first area that holds the point (or its ramp), plus the
        lawn relief where there is no level area."""
        rel = self.relief_dz(x, y) if self.reliefs else 0.0
        if rel and not any(a.reach().contains(Point(x, y)) for a in self.areas if not a.relief):
            return rel + self._area_dz(x, y)
        return self._area_dz(x, y)

    def grade(self, x: float, y: float) -> float:
        """HEIGHTS 2026-11-24: the slow road grade at (x, y) (levels file "grades"): an offset that lifts everything
        there (carriageway, kerbs, pavements, plots, props, building bases) by the same amount, so every step and kerb
        keeps its height while the street climbs. Blended where two grades overlap, zero away from every grade."""
        if not self.grades:
            return 0.0
        num = wsum = 0.0
        for g in self.grades:
            w, v = g.sample(x, y)
            if w > 0.0:
                num += w * v
                wsum += w
        return num / wsum if wsum > 1.0 else num

    def _area_dz(self, x: float, y: float, start: int = 0) -> float:
        p = Point(x, y)
        for i, a in enumerate(self.areas[start:], start):
            if a.poly.contains(p) or a.poly.boundary.distance(p) < 1e-6:
                return a.dz
            if a.ramp_m > 0.0 and (a.clip is None or a.clip.contains(p)):
                d = a.poly.distance(p)
                if d < a.ramp_m:
                    t = d / a.ramp_m
                    s = t * t * (3.0 - 2.0 * t)
                    if a.ramp_to == "below":   # smoothstep to whatever the later areas give here
                        return a.dz + (self._area_dz(x, y, i + 1) - a.dz) * s
                    return a.dz * (1.0 - s)   # smoothstep back to the datum
        return 0.0

    def pieces(self, geom):
        """Split a ground (multi)polygon by the level areas: [(piece, zoffset(x, y))]. Each piece is triangulated
        on its own, so hard steps stay sharp (the wall face fills the gap) and ramps are densified."""
        if geom is None or geom.is_empty:
            return []
        if not self.areas or not any(a.reach().intersects(geom) for a in self.areas):
            return [(geom, lambda x, y: 0.0)]
        out, rest = [], geom
        for k, a in enumerate(self.areas):
            reach = a.reach(quad_segs=4)
            if not reach.intersects(rest):
                continue
            inner = rest.intersection(a.poly)
            if not inner.is_empty:
                out.append((inner, (lambda dz: (lambda x, y: dz))(a.dz)))
            if a.ramp_m > 0:
                band = rest.intersection(reach.difference(a.poly))
                if not band.is_empty:
                    band = shapely.segmentize(band, 1.0)
                    # HEIGHTS: _area_dz from this area on, so a ramp_to "below" band meets the lower area in the
                    # mesh too (the plain _ramp went back to the datum, leaving a step the dz() probe never saw)
                    out.append((band, (lambda ar, kk: (lambda x, y: self._area_dz(x, y, kk) if ar.ramp_to == "below"
                                                       else _ramp(ar, x, y)))(a, k)))
            rest = rest.difference(reach)
            if rest.is_empty:
                break
        if not rest.is_empty:
            out.append((rest, lambda x, y: 0.0))
        return out

    def step_edges(self, ground, plot_z: float):
        """Hard-step wall faces [(p0, p1, bottom, top, kind)] along the area edges that meet ground, each facing
        the lower side (left of p0 -> p1, the layout's WallSeg convention)."""
        out = []
        probe = ground.buffer(0.05)
        for a in self.areas:
            if a.ramp_m > 0 or a.edge == "none":
                continue
            ring = orient(a.poly, 1.0).exterior  # counter-clockwise: the area on the left
            edge = ring.intersection(probe)
            for line in _lines(edge):
                cs = list(line.coords)
                for p0, p1 in zip(cs, cs[1:]):
                    L = math.dist(p0, p1)
                    if L < 0.05:
                        continue
                    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
                    nx, ny = (p1[1] - p0[1]) / L, -(p1[0] - p0[0]) / L   # outward (right of the ccw ring)
                    if not ground.contains(Point(mx + nx * 0.3, my + ny * 0.3)):
                        continue  # nothing outside (sea, a building, a road): no wall face
                    outside = self.dz(mx + nx * 0.3, my + ny * 0.3)
                    if abs(outside - a.dz) < 0.05:
                        continue
                    lo, hi = sorted((outside, a.dz))
                    seg = (p1, p0) if a.dz > outside else (p0, p1)   # face the lower side
                    out.append((seg[0], seg[1], plot_z + lo, plot_z + hi, a.edge))
        return out


def _ramp(a: LevelArea, x: float, y: float) -> float:
    d = a.poly.distance(Point(x, y))
    t = min(1.0, d / a.ramp_m)
    return a.dz * (1.0 - t * t * (3.0 - 2.0 * t))


def _lines(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type in ("MultiLineString", "GeometryCollection"):
        return [x for x in g.geoms if x.geom_type == "LineString"]
    return []


def frame_to_world(cfg: dict, frame: str):
    """(u, v) -> world (east, north) for a hero's frame ("HERO_..."), or the identity for "world"."""
    if frame in ("", "world"):
        return lambda u, v: (u, v)
    hero = cfg.get("hero_models", {})[frame]
    (px, py), a = hero["pivot"], math.radians(float(hero.get("yaw_deg", 0.0)))
    c, s = math.cos(a), math.sin(a)
    return lambda u, v: (px + u * c - v * s, py + u * s + v * c)


def read_levels(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def levels_path(cfg: dict, cfg_dir: str | None = None) -> str | None:
    rel = cfg.get("levels_file")
    if not rel:
        return None
    base = cfg_dir or cfg.get("_dir") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(base, rel))


def from_data(cfg: dict, levels: dict) -> Terrain:
    areas = []
    for a in levels.get("areas", []):
        f = frame_to_world(cfg, a.get("frame", "world"))
        poly = Polygon([f(u, v) for u, v in a["poly"]])
        if not poly.is_valid:
            poly = poly.buffer(0)
        areas.append(LevelArea(a["name"], orient(poly, 1.0), float(a["dz"]), float(a.get("ramp_m", 0.0)),
                               a.get("edge", "retaining"), a.get("source", ""), bool(a.get("estimate", True)),
                               Polygon([f(u, v) for u, v in a["ramp_clip"]]) if a.get("ramp_clip") else None,
                               a.get("ramp_to", "datum"), bool(a.get("relief", False))))
    spots = []
    for s in levels.get("spots", []):
        f = frame_to_world(cfg, s.get("frame", "world"))
        spots.append(dict(s, xy=f(*s["at"])))
    feats = {}
    for name, ft in levels.get("features", {}).items():
        f = frame_to_world(cfg, ft.get("frame", "world"))
        feats[name] = [f(u, v) for u, v in ft["line"]]
    datum = {k: v for k, v in levels.get("datum", {}).items() if not k.startswith("_")}
    t = Terrain(areas, spots, feats, datum)
    t.layer_levels = [x for x in levels.get("layer_levels", []) if isinstance(x, dict)]
    from shapely.geometry import LineString
    for g in levels.get("grades", []):
        if g.get("line"):   # world polyline; "ways" (OSM way ids) are resolved by the layout (resolve_grades)
            f = frame_to_world(cfg, g.get("frame", "world"))
            t.grades.append(grade_from(g, LineString([f(u, v) for u, v in g["line"]])))
    t.grade_specs = [g for g in levels.get("grades", []) if not g.get("line")]
    # P87 (citylib/level_edges.py): swept step runs and the level-edge contact shade settings
    from . import level_edges
    t.step_runs = level_edges.step_runs(levels)
    t.contact_shade = levels.get("contact_shade", {})
    return t


def grade_from(spec: dict, line) -> Grade:
    return Grade(spec["name"], line, [(float(a), float(b)) for a, b in spec["profile"]],
                 float(spec.get("half_width_m", 12.0)), float(spec.get("falloff_m", 25.0)),
                 float(spec.get("end_fade_m", 0.0)), spec.get("source", ""), bool(spec.get("estimate", True)))


def resolve_grades(t: Terrain, data, tm) -> None:
    """Grades given by OSM way ids ("ways", in order, chained end to end; a way is reversed where needed): the line is
    the ways' nodes projected with tm. Unknown ways are skipped; a grade with no resolvable way is dropped."""
    from shapely.geometry import LineString
    for spec in getattr(t, "grade_specs", []):
        pts: list = []
        for wid in spec.get("ways", []):
            w = data.ways.get(int(wid))
            if w is None:
                continue
            cs = [tm.forward(*data.nodes[n]) for n in w.node_ids if n in data.nodes]
            if pts and cs and math.dist(pts[-1], cs[-1]) < math.dist(pts[-1], cs[0]):
                cs = cs[::-1]
            if pts and cs and math.dist(pts[-1], cs[0]) < 0.5:
                cs = cs[1:]
            pts += cs
        if spec.get("reverse"):
            pts = pts[::-1]
        if len(pts) >= 2:
            t.grades.append(grade_from(spec, LineString(pts)))
    t.grade_specs = []


def load(cfg: dict, cfg_dir: str | None = None) -> Terrain:
    path = levels_path(cfg, cfg_dir)
    if not path or not os.path.exists(path):
        return Terrain()
    return from_data(cfg, read_levels(path))


def union(t: Terrain):
    return ops.unary_union([a.poly for a in t.areas]) if t.areas else Polygon()
