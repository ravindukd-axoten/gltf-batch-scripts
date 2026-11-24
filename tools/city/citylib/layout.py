"""OSM -> 2D layout with Shapely (TDD "The city pipeline", step 2).

Builds, in world metres (x east, y north, origin = Cityhub world origin):
  area_strip   the build area: a rectangle along the road axis, sea side widened to the coast + offshore
  sea/land   the area_strip split by the OSM coastline (land is on the left of a coastline way)
  roads      carriageway pieces, each owning a centreline for road-trim UVs, plus merged junctions
  pavements  footpaths beside roads by class, and mapped footways
  beach, promenade, green, plots, lake: the remaining ground surfaces
  kerbs and seawalls: vertical edges between surfaces at different heights
  buildings  cleaned footprints with storeys, street-facing edges and landmark / sacred flags
Everything is exact 2D geometry, cut on the streaming grid later by cells.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import shapely
from shapely import ops
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient

from . import geo, grid, osm, rules, terrain as terrain_mod
from . import heroes as hero_sites_mod


@dataclass
class Heights:
    """Unity Y = metres above mean sea level. These are the datum surfaces; the ground is not flat: level areas
    from the config's levels file (citylib/terrain.py) offset the ground surfaces from the plot datum."""
    sea: float = 0.0
    road: float = 3.8          # carriageway surface (Delta Face sits ~4 m above the sea)
    kerb: float = 0.15         # kerb upstand
    promenade_step: float = -0.45  # promenade 0.45 m below the Green: the edge is a low stone bench wall
    beach_top: float = 0.4     # sand height at the seawall foot
    beach_slope: float = 0.08  # m rise per m inland from the coastline
    beach_min: float = -0.5    # underwater apron depth
    beach_wet_m: float = 7.0   # wet sand band landward of the waterline (gf_03, gf_04); config "heights" may narrow it
    lake_drop: float = 0.6     # inland water surface below the road

    @property
    def plot(self) -> float:   # pavements, the Green and building plots
        return self.road + self.kerb

    @property
    def promenade(self) -> float:
        return self.plot + self.promenade_step

    @property
    def lake(self) -> float:
        return self.road - self.lake_drop


@dataclass
class RoadPiece:
    poly: Polygon | MultiPolygon
    line: LineString
    width: float
    name: str
    priority: int = 99  # rules.road_priority of the way (road class: lower = more important)


@dataclass
class Building:
    osm_id: int
    footprint: Polygon
    levels: int
    levels_source: str
    tags: dict[str, str]
    street: list[list[bool]] = field(default_factory=list)
    landmark: str = ""   # fictional placeholder name for hand-modelled heroes ("" = kit building)
    sacred: bool = False
    base: float = 0.0    # metres above the street where the mass starts (building:part min_height)
    hero: dict = field(default_factory=dict)  # {"name": generic node name, "style": "kit" | "fin_tower"}
    district: str = ""   # rules.DISTRICTS key from the config's district_zones ("" = the config's district)


@dataclass
class WallSeg:
    """A vertical wall face along p0 -> p1, facing left of that direction. z = (bottom0, bottom1, top)."""
    p0: tuple[float, float]
    p1: tuple[float, float]
    bottom0: float
    bottom1: float
    top: float
    kind: str  # "kerb", "seawall", "bank"


@dataclass
class Layout:
    area_strip: Polygon
    axis: LineString
    land: Polygon | MultiPolygon
    sea: Polygon | MultiPolygon
    coast: LineString | MultiLineString | None
    roads: list[RoadPiece]
    junctions: Polygon | MultiPolygon
    road_area: Polygon | MultiPolygon
    pavement: Polygon | MultiPolygon
    promenade: Polygon | MultiPolygon
    beach: Polygon | MultiPolygon
    green: Polygon | MultiPolygon
    plots: Polygon | MultiPolygon
    worn: Polygon | MultiPolygon   # trampled turf: grass and red-brown earth mixed (Green and open plots)
    earth: Polygon | MultiPolygon  # bare laterite (worst-worn patches of the Green, dirt plots)
    forecourt: Polygon | MultiPolygon  # paved strips round buildings
    park: Polygon | MultiPolygon   # the whole Green before the wear split (for dressing)
    lawn_stripe: Polygon | MultiPolygon  # alternate mowing bands of the Green's lawn
    parking: Polygon | MultiPolygon
    bare: Polygon | MultiPolygon   # unbuilt reclaimed / construction land: bare sand at plot level
    lake: Polygon | MultiPolygon
    walls: list[WallSeg]
    seawall: list[tuple[tuple[float, float], tuple[float, float], float]]  # (p0, p1, top z), beach on the left
    terrace: list[tuple[tuple[float, float], tuple[float, float]]]  # promenade/Green edges, promenade on the left
    shallow: Polygon | MultiPolygon
    surf: Polygon | MultiPolygon
    buildings: list[Building]
    heights: Heights
    stats: dict
    heroes: list = field(default_factory=list)   # heroes.HeroSite: hand-modelled landmarks that replace massing
    base_area_strip: Polygon | None = None  # the straight area_strip before the route was added (None = no route)
    rail: Polygon | MultiPolygon = Polygon()   # railway ballast beds (plot level), cut out of the ground surfaces
    rail_lines: list = field(default_factory=list)  # track centrelines (LineString) for the rails
    terrain: terrain_mod.Terrain = field(default_factory=terrain_mod.Terrain)  # level areas over the datum (SLICE3)
    private: Polygon | MultiPolygon = Polygon()  # private seafront grounds (no public beach or promenade)
    lake_edge: object = None  # P165 lake_edge.LakeEdge: the Baladaksha lake-edge layers (None = no lake edge)
    road_block_walls: list = field(default_factory=list)  # ROADS2: collision walls at the drive circle's road blocks
    focus: Polygon | None = None   # P117: the drive circle and its band (filled extra_routes); cells trim toward it
    cell_trim: dict = field(default_factory=dict)   # P117: config "cell_trim" (citylib/cell_trim.py)
    # CIRCLE fix 5 (agent 2026-11-20, r5.centre_rd.*): the parking lane inside the carriageway (road level, part of
    # road_area, kerb on its outer edge), the raised median islands (pavement, cut out of road_area) and the open
    # gaps between them (no median paint)
    parking_lane: Polygon | MultiPolygon = Polygon()
    medians: Polygon | MultiPolygon = Polygon()
    median_gaps: Polygon | MultiPolygon = Polygon()


EMPTY = Polygon()


def _polys(g) -> list[Polygon]:
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    if hasattr(g, "geoms"):
        out = []
        for part in g.geoms:
            out.extend(_polys(part))
        return out
    return []


def clean(g, min_area: float = 0.05):
    """Valid polygonal geometry only, slivers dropped, rings oriented (outer CCW, holes CW)."""
    if g is None or g.is_empty:
        return EMPTY
    g = shapely.make_valid(g)
    parts = [orient(p, 1.0) for p in _polys(g) if p.area >= min_area]
    if not parts:
        return EMPTY
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _line(data: osm.OsmData, node_ids: list[int], tm) -> LineString | None:
    pts = [tm.forward(lat, lon) for lat, lon in data.coords(node_ids)]
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    return LineString(pts) if len(pts) >= 2 else None


def _area_poly(data: osm.OsmData, area: osm.Area, tm):
    polys = []
    for outer in area.outers:
        shell = [tm.forward(lat, lon) for lat, lon in data.coords(outer)]
        if len(shell) < 4:
            continue
        holes = []
        for inner in area.inners:
            ring = [tm.forward(lat, lon) for lat, lon in data.coords(inner)]
            if len(ring) >= 4:
                holes.append(ring)
        poly = shapely.make_valid(Polygon(shell))
        for h in holes:
            hp = Polygon(h)
            if poly.contains(hp.representative_point()):
                poly = poly.difference(hp)
        polys.append(poly)
    return clean(ops.unary_union(polys)) if polys else EMPTY


def _side(line: LineString, p: Point) -> float:
    """> 0 when p is left of the line's direction at its nearest point."""
    s = line.project(p)
    a = line.interpolate(max(0.0, s - 0.5))
    b = line.interpolate(min(line.length, s + 0.5))
    q = line.interpolate(s)
    return (b.x - a.x) * (p.y - q.y) - (b.y - a.y) * (p.x - q.x)


def widen_beach(coast, zones: list):
    """CIRCLE fix 4 (critic round 4, w1 vs gf_12 / gf_10: 20-40 m of sand below the Green's seawall, the OSM
    coastline leaves about 6 m). Each zone {"near": [x, y], "radius_m", "taper_m", "extra_m"} pushes the coastline
    seaward (to the right of a coastline way; land is on its left) by extra_m inside radius_m, easing to 0 over
    taper_m beyond it. Returns (new coast, strips): strips are the land gained between the old and new line, which
    build_layout lays as beach so the seawall stays where it was. No zones: the coast is returned unchanged."""
    if coast is None or not zones:
        return coast, []
    lines, strips = [], []
    for ln in getattr(coast, "geoms", [coast]):
        # densify (4 m) only the segments a zone reaches, so the sea, sand and wall meshes elsewhere keep their
        # vertex count (and their cells their triangle budget)
        src, old = list(ln.coords), []
        for p, q in zip(src, src[1:]):
            seg = LineString([p, q])
            near = any(seg.distance(Point(*z["near"])) < float(z["radius_m"]) + float(z.get("taper_m", 60.0))
                       for z in zones)
            pts = list(shapely.segmentize(seg, 4.0).coords) if near else [p, q]
            old += pts[:-1]
        old.append(src[-1])
        new = []
        for i, (x, y) in enumerate(old):
            a, b = old[max(0, i - 1)], old[min(len(old) - 1, i + 1)]
            tx, ty = b[0] - a[0], b[1] - a[1]
            tl = math.hypot(tx, ty) or 1.0
            rx, ry = ty / tl, -tx / tl                      # right of the way = sea side
            push = 0.0
            for z in zones:
                d = math.hypot(x - z["near"][0], y - z["near"][1])
                r, tp = float(z["radius_m"]), max(1e-6, float(z.get("taper_m", 60.0)))
                w = 1.0 if d <= r else max(0.0, 0.5 + 0.5 * math.cos(math.pi * min(1.0, (d - r) / tp)))
                push = max(push, float(z["extra_m"]) * w)
            new.append((x + rx * push, y + ry * push))
        for i in range(len(old) - 1):
            if old[i] != new[i] or old[i + 1] != new[i + 1]:
                q = Polygon([old[i], old[i + 1], new[i + 1], new[i]])
                if q.is_valid and q.area > 0.01:
                    strips.append(q.buffer(0.05))
        lines.append(LineString(new))
    return (lines[0] if len(lines) == 1 else MultiLineString(lines)), strips


def _value_noise(xs, ys, scale: float, seed: int):
    """Smooth value noise in 0..1 at world points (numpy arrays), lattice spacing `scale` metres."""
    import numpy as np
    gx, gy = xs / scale, ys / scale
    x0, y0 = np.floor(gx), np.floor(gy)
    fx, fy = gx - x0, gy - y0
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)

    def h(ix, iy):
        n = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263 + seed * 2246822519) & 0xFFFFFFFF
        n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
        return (n & 0xFFFF) / 65535.0
    a, b = h(x0, y0), h(x0 + 1, y0)
    c, d = h(x0, y0 + 1), h(x0 + 1, y0 + 1)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _raster_to_polys(mask, x0: float, y0: float, step: float):
    """Union of the raster cells set in mask (rows = y), merged per row run, then rounded so the outline
    reads as a worn edge rather than a staircase."""
    boxes = []
    for j in range(mask.shape[0]):
        row = mask[j]
        i = 0
        n = len(row)
        while i < n:
            if row[i]:
                k = i
                while k < n and row[k]:
                    k += 1
                boxes.append(box(x0 + i * step, y0 + j * step, x0 + k * step, y0 + (j + 1) * step))
                i = k
            else:
                i += 1
    if not boxes:
        return EMPTY
    r = step * 0.9
    return ops.unary_union(boxes).buffer(r, quad_segs=3).buffer(-r * 1.6, quad_segs=3).buffer(r * 0.6, quad_segs=3)


def split_wear(area, axis: LineString, wear_lines, fractions, seed: int = 1, step: float = 3.0, bias=None):
    """Split an area into (lawn, worn, earth) by a wear field: two octaves of value noise, plus trampling
    within ~12 m of the promenade and ~4 m of paths, plus a dry gradient towards the south (start) of the
    axis. Thresholds come from quantiles so the split hits the wanted fractions (lawn, worn; earth = rest)."""
    import numpy as np
    if area.is_empty:
        return EMPTY, EMPTY, EMPTY
    x0, y0, x1, y1 = area.bounds
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    xs = x0 + (np.arange(nx) + 0.5) * step
    ys = y0 + (np.arange(ny) + 0.5) * step
    X, Y = np.meshgrid(xs, ys)
    pts = shapely.points(X.ravel(), Y.ravel())
    inside = shapely.contains_xy(area, X.ravel(), Y.ravel()).reshape(X.shape)
    if not inside.any():
        return area, EMPTY, EMPTY
    # noise only breaks the edges up; the wear itself follows feet: the promenade side and the paths
    f = 0.6 * _value_noise(X, Y, 40.0, seed) + 0.3 * _value_noise(X, Y, 12.0, seed + 7) + 0.1 * _value_noise(X, Y, 5.0, seed + 13)
    wear = 0.35 * f
    for k, g in enumerate(wear_lines):
        d = shapely.distance(pts, g).reshape(X.shape)
        reach, amount = ((5.0, 0.55), (2.5, 0.35))[min(k, 1)]
        wear += amount * np.exp(-d / reach)
    t = np.array([axis.project(p) for p in shapely.points(X[::4, ::4].ravel(), Y[::4, ::4].ravel())]).reshape(X[::4, ::4].shape)
    t = np.kron(t, np.ones((4, 4)))[:ny, :nx] / max(axis.length, 1.0)
    wear += 0.04 * (1.0 - np.clip(t, 0.0, 1.0))
    if bias is not None and not bias[0].is_empty:
        wear += bias[1] * shapely.contains_xy(bias[0], X.ravel(), Y.ravel()).reshape(X.shape)
    vals = wear[inside]
    lawn_f, worn_f = fractions
    t_worn = np.quantile(vals, lawn_f)
    t_earth = np.quantile(vals, min(0.999, lawn_f + worn_f))
    # Simplify the raster outlines FIRST, then cut every surface from the same simplified shapes, so lawn, worn
    # and earth share their edges exactly. (Simplifying worn and earth after the cut, and the lawn not at all,
    # left sliver gaps and overlaps round every patch: white triangles at the grass edges, 2026-11-17.)
    earth = clean(_raster_to_polys(inside & (wear >= t_earth), x0, y0, step).simplify(0.4).intersection(area))
    worn_all = clean(ops.unary_union([_raster_to_polys(inside & (wear >= t_worn), x0, y0, step).simplify(0.4),
                                      earth]).intersection(area))
    worn = clean(worn_all.difference(earth))
    lawn = clean(area.difference(worn_all))
    return lawn, worn, earth


def override_ways(data: osm.OsmData, overrides: dict) -> list[osm.Way]:
    """Every way with the config's road_overrides (by name) applied to its tags BEFORE it is classified, so an
    override can turn a road into a footpath (e.g. {"highway": "pedestrian"}: a walk path that OSM tags as
    a road) as well as change its lanes. A key "way/<osm id>" overrides one unnamed way (SLICE5: {"highway": ""}
    drops it, e.g. the hotel's service loop that the hero models as its own gate drive). Sorted by id, like osm.lines."""
    return [osm.Way(w.id, w.node_ids, {**w.tags, **overrides.get(w.tags.get("name", ""), {}), **overrides.get(f"way/{w.id}", {})})
            for w in osm.lines(data, lambda t: "highway" in t)]


def route_line(c: dict, tm=geo.CITYHUB) -> LineString | None:
    """The area_strip's route polyline in world metres ("area_strip.route.points", [lat, lon] pairs), or None."""
    pts = c.get("route", {}).get("points")
    if not pts:
        return None
    return LineString([tm.forward(lat, lon) for lat, lon in pts])


def widened_pavements(cfg: dict, roads: list[RoadPiece], road_area, area_strip_land) -> Polygon | MultiPolygon:
    """Config "pavement_widening" (SLICE2, gf_21 / gf_24): wider pavements than the road class gives, on one side
    of a named road, inside a box in a hero's frame. Each rule {"road", "hero", "width_m", "box_uv": [u0, u1, v0,
    v1]} adds the strip within width_m of the road's kerb (half width + width_m from the centreline) that lies in
    the box; the carriageway is never touched (the width comes from the plot or verge behind the kerb), so the
    drivable lanes and the route colliders stay as they were. The hero's own massing must stand behind it."""
    heroes = cfg.get("hero_models", {})
    strips = []
    for rule in cfg.get("pavement_widening", []):
        hero = heroes.get(rule.get("hero", ""))
        if hero is None:
            continue
        (px, py), a = hero["pivot"], math.radians(float(hero.get("yaw_deg", 0.0)))
        c, s = math.cos(a), math.sin(a)
        u0, u1, v0, v1 = rule["box_uv"]
        frame = Polygon([(px + u * c - v * s, py + u * s + v * c) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))])
        width = float(rule["width_m"])
        for r in roads:
            if r.name == rule["road"] and r.line.distance(frame) < r.width / 2 + width:
                strips.append(r.line.buffer(r.width / 2 + width, quad_segs=4, cap_style="flat").intersection(frame))
    if not strips:
        return EMPTY
    return clean(ops.unary_union(strips).intersection(area_strip_land).difference(road_area))


def _band(line: LineString, d0: float, d1: float) -> Polygon | None:
    """The strip between two parallel offsets of a line (+ = left of its direction)."""
    a, b = line.offset_curve(d0), line.offset_curve(d1)
    if a.is_empty or b.is_empty or a.geom_type != "LineString" or b.geom_type != "LineString":
        return None
    poly = Polygon(list(a.coords) + list(b.coords)[::-1])
    return poly if poly.is_valid else poly.buffer(0)


def fit_circle(pts) -> tuple[float, float, float]:
    """Least-squares circle (Kasa): centre x, y and radius through points (shared with markings.py)."""
    n = len(pts)
    mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    suu = svv = suv = suuu = svvv = suvv = svuu = 0.0
    for x, y in pts:
        u, v = x - mx, y - my
        suu += u * u
        svv += v * v
        suv += u * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-9:
        return mx, my, sum(math.hypot(p[0] - mx, p[1] - my) for p in pts) / n
    c1 = 0.5 * (suuu + suvv)
    c2 = 0.5 * (svvv + svuu)
    uc = (c1 * svv - c2 * suv) / det
    vc = (suu * c2 - suv * c1) / det
    return mx + uc, my + vc, math.sqrt(uc * uc + vc * vc + (suu + svv) / n)

def roundabout_fill(cfg: dict, ways: list, way_lines: dict, way_width: dict, area_strip_land):
    """Config "roundabout_islands" {name: {"island_d_m": d}}: where the real central island is smaller than the
    one the OSM ring centreline leaves (the centreline follows the outer lane), the asphalt between the island and
    the ring's inner edge. The ring's circle is fitted to its ways' centrelines; the inner edge is that radius minus
    half the ring width. Delta Face Roundabout (2026-11-17): centreline radius 12.0 m, ring 11.5 m, so the build
    left a 12.5 m island where Google Maps measures 5.9 m (gf_19, sv_01). Returns the fill (empty when none)."""
    out = []
    for name, rule in cfg.get("roundabout_islands", {}).items():
        if name.startswith("_") or not isinstance(rule, dict):
            continue
        ring = [w for w in ways if w.tags.get("name") == name and w.tags.get("junction") in ("roundabout", "circular")
                and way_lines.get(w.id) is not None and w.id in way_width]
        pts = [c for w in ring for c in way_lines[w.id].coords]
        if len(pts) < 5:
            continue
        cx, cy, r = fit_circle(pts)
        inner = r - max(way_width[w.id] for w in ring) / 2.0
        island = float(rule["island_d_m"]) / 2.0
        if inner <= island + 0.2:
            continue
        centre = Point(cx, cy)
        out.append(centre.buffer(inner + 0.3, quad_segs=16).difference(centre.buffer(island, quad_segs=16)))
    return clean(ops.unary_union(out).intersection(area_strip_land)) if out else EMPTY


def planted_islands(cfg: dict, roads: list[RoadPiece], road_area):
    """Config "roundabout_islands" entries with "planted": true: the island the ring encloses (the hole in the road
    surface round the ring's fitted centre, or round "at" [x, y] for a junction that is not one named ring, e.g.
    the Macan Markar oval) becomes kept lawn, inset by "kerb_m" (default 1.0) of pavement as its kerb edge.
    Google Maps 2026-11-17: Slave Island's island is planted with trees, the south roundabout's is a low planted bed;
    both were paved in the build. Returns the planted area (empty when none)."""
    out = []
    for name, rule in cfg.get("roundabout_islands", {}).items():
        if name.startswith("_") or not isinstance(rule, dict) or not rule.get("planted"):
            continue
        if "at" in rule:
            centre = Point(*rule["at"])
        else:
            pts = [c for r in roads if r.name == name for c in r.line.coords]
            if len(pts) < 5:
                continue
            cx, cy, _ = fit_circle(pts)
            centre = Point(cx, cy)
        for poly in _polys(road_area):
            for ring in poly.interiors:
                hole = Polygon(ring)
                if hole.contains(centre):
                    out.append(hole.buffer(-float(rule.get("kerb_m", 1.0)), quad_segs=8))
    return clean(ops.unary_union(out)) if out else EMPTY


def pair_centre(roads: list[RoadPiece], name: str, near: Point) -> LineString | None:
    """The line where the two carriageways of `name` meet near `near` (the nearer piece's line moved half its width
    towards its partner), running north (last point north of the first)."""
    cand = [r for r in roads if r.name == name and r.line.length > 100.0]
    if len(cand) < 2:
        return None
    a = min(cand, key=lambda r: r.line.distance(near))
    mid = a.line.interpolate(a.line.project(near))
    d, b = min(((r.line.distance(mid), r) for r in cand if r is not a), key=lambda t: t[0])
    if d > a.width + b.width:
        return None
    q = b.line.interpolate(b.line.project(mid))
    sgn = 1.0 if _side(a.line, q) > 0 else -1.0
    ln = a.line.offset_curve(sgn * a.width / 2.0, quad_segs=2, join_style="mitre", mitre_limit=3.0)
    if ln.is_empty or ln.geom_type != "LineString":
        return None
    return ln if ln.coords[-1][1] >= ln.coords[0][1] else LineString(list(ln.coords)[::-1])


def parking_lane_gaps(cfg: dict, data: osm.OsmData, tm, roads: list[RoadPiece], junctions):
    """Config "parking_lane_gaps" (CIRCLE fix 5, agent aerials b2/b3 2026-11-20: the bays stop at crossings, bus
    stops and junctions): {"road", "crossing_m", "bus_stop_m", "junction_m", "extra": [{"near", "half_m"}]}. Returns
    the area cut out of the parking lane: a box across the road +-crossing_m along the meeting line at every OSM
    crossing node on the carriageway (within 6 m of the meeting line; side-road mouths are further out), +-bus_stop_m
    at every OSM bus stop on the parking (west) side, and the junctions grown by junction_m."""
    rule = cfg.get("parking_lane_gaps")
    if not rule:
        return EMPTY
    out = []
    jm = float(rule.get("junction_m", 0.0))
    if jm > 0.0 and not junctions.is_empty:
        out.append(junctions.buffer(jm))
    cand = sorted((r for r in roads if r.name == rule["road"] and r.line.length > 100.0),
                  key=lambda r: -r.line.length)   # the long seafront pair, not the short pieces at the south end
    centre = None
    if len(cand) >= 2:
        probe = cand[0].line.interpolate(0.5, normalized=True)
        centre = pair_centre(roads, rule["road"], Point(probe.x, probe.y))
    if centre is not None:
        feats = [(Point(*e["near"]), float(e.get("half_m", 12.0))) for e in rule.get("extra", [])]
        for nid, t in data.node_tags.items():
            if nid not in data.nodes:
                continue
            p = Point(*tm.forward(*data.nodes[nid]))
            d = centre.distance(p)
            if t.get("highway") == "crossing" and d < 6.0:
                feats.append((p, float(rule.get("crossing_m", 12.0))))
            elif t.get("highway") == "bus_stop" and d < 12.0 and _side(centre, p) > 0:
                feats.append((p, float(rule.get("bus_stop_m", 15.0))))
        for p, half in feats:
            s = centre.project(p)
            seg = ops.substring(centre, max(0.0, s - half), min(centre.length, s + half))
            if seg.length > 0.5:
                out.append(seg.buffer(30.0, cap_style="flat"))
    return clean(ops.unary_union(out)) if out else EMPTY


def road_medians(cfg: dict, roads: list[RoadPiece]):
    """Config "road_medians" (CIRCLE fix 5, r5.centre_rd.median_*): raised islands on the line where a road's two
    carriageways meet. Each rule {"road", "at": [x, y], "width_m", "islands_m": [[s0, s1], ...]}: island k runs from
    s0 to s1 metres north of `at` (projected on the meeting line), round ends inside that length. Returns
    (islands, gaps): the islands, and the open stretches between consecutive islands (no median paint there)."""
    islands, gaps = [], []
    for rule in cfg.get("road_medians", []):
        if not isinstance(rule, dict):
            continue
        centre = pair_centre(roads, rule["road"], Point(*rule["at"]))
        if centre is None:
            continue
        s_at = centre.project(Point(*rule["at"]))
        hw = float(rule.get("width_m", 2.0)) / 2.0
        spans = sorted((float(s0), float(s1)) for s0, s1 in rule["islands_m"])
        for s0, s1 in spans:
            core = ops.substring(centre, s_at + s0 + hw, s_at + s1 - hw)
            if core.length > 0.1:
                islands.append(core.buffer(hw, quad_segs=6))
        for (_, e0), (b1, _) in zip(spans, spans[1:]):
            gap = ops.substring(centre, s_at + e0, s_at + b1)
            if gap.length > 0.1:
                gaps.append(gap.buffer(hw + 0.6, cap_style="flat"))
    return (clean(ops.unary_union(islands)) if islands else EMPTY), (clean(ops.unary_union(gaps)) if gaps else EMPTY)


def roadside_strips(cfg: dict, greens: list, roads: list[RoadPiece], road_area, coast, area_strip_land,
                    lanes: list | None = None):
    """Config "roadside_strips" (agent 2026-11-17, ROAD_WIDTHS_MEASURED.md and DELTA_FACE_MEASURED.md): on the sea
    side of a named road, a row of angled parking beside the kerb and a wider paved strip behind it, only where
    the road runs along the named green (within near_m of it). Each rule {"road", "green", "parking_m",
    "strip_m", "near_m", "parking_zones"}. "parking_zones" (optional, 2026-11-17 Google Maps check: the bays are
    only in the car-park stretches, sv_06 / sv_09 / the south end show none) is a list of {"near": [x, y],
    "radius_m": r}; outside them the parking band is paved like the strip, so the total width from the kerb stays
    parking_m + strip_m. Without the key the parking band runs the whole length. Returns (parking, strip): the
    parking band and the paved strip behind it. The carriageway is never touched.
    CIRCLE fix 5 (agent 2026-11-20: parking is a 5th lane of the road, not a lot): a rule with "parking_lane": true
    measures parking_m from the kerb to the lane edge line, which sits "edge_line_m" (0.3) inside the carriageway
    edge; its bands go to `lanes` (road level, joined to the road by the caller) instead of the parking surface, and
    they overlap the carriageway by 5 cm so the union has no seam."""
    parking, strip = [], []
    for rule in cfg.get("roadside_strips", []):
        zone = ops.unary_union([g for name, g in greens if name == rule["green"]])
        if zone.is_empty or coast is None:
            continue
        zone = zone.buffer(float(rule.get("near_m", 20.0)))
        pk, st = float(rule["parking_m"]), float(rule["strip_m"])
        as_lane = bool(rule.get("parking_lane")) and lanes is not None
        if as_lane:
            pk -= float(rule.get("edge_line_m", 0.3))
        pzones = None
        if "parking_zones" in rule:
            pzones = ops.unary_union([Point(*z["near"]).buffer(float(z["radius_m"]), quad_segs=16)
                                      for z in rule["parking_zones"]] or [EMPTY])
        for r in roads:
            if r.name != rule["road"] or not r.line.intersects(zone):
                continue
            mid = r.line.interpolate(0.5, normalized=True)
            nearest = ops.nearest_points(coast, mid)[0]
            sgn = 1.0 if _side(r.line, nearest) > 0 else -1.0   # the sea side
            h = r.width / 2.0
            probe = r.line.interpolate(0.5, normalized=True)
            ahead = r.line.interpolate(min(r.line.length, r.line.project(probe) + 1.0))
            dx, dy = ahead.x - probe.x, ahead.y - probe.y
            norm = math.hypot(dx, dy) or 1.0
            out_pt = Point(probe.x - sgn * dy / norm * (h + 2.5), probe.y + sgn * dx / norm * (h + 2.5))
            if road_area.contains(out_pt):   # another carriageway of this road lies seaward of this one
                continue
            for lo, hi, out in ((h - (0.05 if as_lane else 0.0), h + pk, lanes if as_lane else parking),
                                (h + pk, h + pk + st, strip)):
                band = _band(r.line, sgn * lo, sgn * hi)
                if band is None:
                    continue
                band = band.intersection(zone)
                if out is not strip and pzones is not None:
                    if as_lane:   # outside the zones the kerb stays at the carriageway edge; pave from there
                        strip.append(_band(r.line, sgn * h, sgn * (h + pk)).intersection(zone).difference(pzones))
                    else:
                        strip.append(band.difference(pzones))
                    band = band.intersection(pzones)
                out.append(band)
    def fin(parts):
        return clean(ops.unary_union(parts).intersection(area_strip_land).difference(road_area)) if parts else EMPTY
    if lanes:
        lanes[:] = [clean(ops.unary_union(lanes).intersection(area_strip_land))]
        strip = [ops.unary_union(strip).difference(lanes[0])] if strip else strip
    return fin(parking), fin(strip)


def private_grounds(cfg: dict) -> Polygon | MultiPolygon:
    """Config "private_grounds" (SLICE3, agent-approved): boxes in a hero's frame where private grounds run to the
    seawall (the hotel lawn, terrace and pool: agent h03, h04, h06, h18). No public beach or promenade is laid
    there; the coastline keeps its rubble seawall and the leftover plot is a kept lawn."""
    boxes = []
    for rule in cfg.get("private_grounds", []):
        if rule.get("hero") not in cfg.get("hero_models", {}):
            continue
        f = terrain_mod.frame_to_world(cfg, rule["hero"])
        u0, u1, v0, v1 = rule["box_uv"]
        boxes.append(Polygon([f(u, v) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]))
    return ops.unary_union(boxes) if boxes else EMPTY


def route_area_strip(base: Polygon, route: LineString | None, half_width_m: float) -> Polygon:
    """The build area: the straight base area_strip (may be empty) joined with the route buffered half_width_m
    each side (round ends and joins, so a closed loop and its corners stay covered). Holes the loop encloses
    are kept as holes: the area_strip follows the streets, it does not fill the block they go round."""
    if route is None:
        return base
    band = route.buffer(half_width_m, quad_segs=8)
    out = band if base.is_empty else ops.unary_union([base, band])
    out = max(_polys(out), key=lambda p: p.area) if out.geom_type != "Polygon" else out
    return orient(out, 1.0)



def apply_frontage_rules(cfg: dict, roads: list[RoadPiece], promenade, buildings: list[Building]) -> list[dict]:
    """Config "frontage_rules": [{"roads": [names], "highways": [classes], "frontage": "plain", "reach_m": 4.0,
    "min_footprint_m2": 0}] (a road matches by name or by OSM highway class; only footprints at least that big). A building edge already
    flagged as street-facing that faces only the rule's roads (no other road or the promenade within 4 m of its 6 m
    probe) becomes a plain wall: no shop bays, windows or balconies along that road. For roads that were not shop
    streets in the place (a lake-side road past a podium) and whose shopfronts would break a cell's LOD0 budget.
    Returns per rule how many edges and buildings changed."""
    out = []
    for rule in cfg.get("frontage_rules", []):
        names = set(rule.get("roads", []))
        prios = {rules.road_priority({"highway": hw}) for hw in rule.get("highways", [])}
        if rule.get("frontage", "plain") != "plain" or not (names or prios):
            continue
        reach = float(rule.get("reach_m", 4.0))
        hit = [r.name in names or r.priority in prios for r in roads]
        named = [r.poly for r, h_ in zip(roads, hit) if h_]
        if not named:
            out.append({"roads": sorted(names), "highways": rule.get("highways", []), "edges": 0, "buildings": 0})
            continue
        zone = ops.unary_union(named).buffer(reach)
        others = [r.poly for r, h_ in zip(roads, hit) if not h_]
        other = ops.unary_union(others + ([promenade] if promenade is not None else [])).buffer(reach)
        edges, blds = 0, 0
        min_area = float(rule.get("min_footprint_m2", 0.0))
        for bld in buildings:
            if bld.footprint.area < min_area:
                continue                  # small shophouses on lanes keep their shop bays
            changed = False
            for ring, rf in zip([bld.footprint.exterior] + list(bld.footprint.interiors), bld.street):
                cs = list(ring.coords)[:-1]
                for i, on in enumerate(rf):
                    if not on:
                        continue
                    (ax, ay), (bx, by) = cs[i], cs[(i + 1) % len(cs)]
                    ln = math.hypot(bx - ax, by - ay) or 1.0
                    probe = Point((ax + bx) / 2 + (by - ay) / ln * 6.0, (ay + by) / 2 - (bx - ax) / ln * 6.0)
                    if zone.distance(probe) < 4.0 and other.distance(probe) >= 4.0:
                        rf[i] = False
                        edges += 1
                        changed = True
            blds += changed
        out.append({"roads": sorted(names), "highways": rule.get("highways", []), "edges": edges, "buildings": blds})
    return out


def _focus(c: dict, tm=geo.CITYHUB) -> Polygon | None:
    """P117: the filled extra routes (the drive circle plus its band) as one area, or None."""
    parts = [extra_route_area(Polygon(), e, tm) for e in c.get("extra_routes", []) if e.get("fill")]
    return ops.unary_union(parts) if parts else None


def extra_route_area(area_strip: Polygon, extra: dict, tm=geo.CITYHUB) -> Polygon:
    """Grow the build area by another route ("area_strip.extra_routes": points [lat, lon], half_width_m, fill).
    fill=true also takes the area a closed route encloses (the drive circle's inner blocks are drivable and built)."""
    line = LineString([tm.forward(lat, lon) for lat, lon in extra["points"]])
    parts = [line.buffer(float(extra.get("half_width_m", 60.0)), quad_segs=8)]
    if extra.get("fill") and len(line.coords) >= 4:
        parts.append(Polygon(line.coords).buffer(0))
    out = ops.unary_union([area_strip, *parts]) if not area_strip.is_empty else ops.unary_union(parts)
    out = max(_polys(out), key=lambda p: p.area) if out.geom_type != "Polygon" else out
    return orient(out, 1.0)


def frontage_infill(cfg: dict, data: osm.OsmData, tm, roads: list[RoadPiece], road_area, pavement, area_strip_land,
                    built, district_at) -> list[Building]:
    """Synthetic street-wall lots where OSM maps no building along a named street (config "frontage_infill":
    York Street in Fort and Kumaran Ratnam Road in Slave Island are built up end to end, but OSM has gaps).
    Each side of the street is walked in lot widths; a lot runs from the back of the pavement inland, minus roads,
    pavements, water, parks, parking, the railway and existing buildings (with a gap). Lots are kit buildings with
    negative ids (named bld_infill_<n>), tagged source=infill, levels from the district defaults. Not OSM data."""
    fcfg = cfg.get("frontage_infill") or {}
    by_road = fcfg.get("roads", {})
    if not by_road:
        return []
    lots_cfg = fcfg.get("lots", {})
    blocked = [built.buffer(float(fcfg.get("gap_m", 2.0)))]
    for ar in osm.areas(data, lambda t: t.get("natural") == "water" or t.get("amenity") == "parking"
                        or t.get("leisure") in ("park", "garden", "pitch", "playground")
                        or t.get("landuse") in ("grass", "railway", "cemetery")):
        blocked.append(_area_poly(data, ar, tm))
    for w in osm.lines(data, lambda t: t.get("railway") in ("rail", "light_rail")):
        ln = _line(data, w.node_ids, tm)
        if ln is not None:
            blocked.append(ln.buffer(4.0))
    blocked = ops.unary_union([g for g in blocked if not g.is_empty])
    front_zone = ops.unary_union([road_area, pavement])
    keep_out = ops.unary_union([front_zone.buffer(0.05), blocked])
    out: list[Building] = []
    taken = EMPTY
    for r in sorted(roads, key=lambda q: (q.name, q.line.length)):
        district = by_road.get(r.name)
        if not district:
            continue
        lc = lots_cfg.get(district, {})
        w_lo, w_hi = lc.get("width_m", [6.0, 9.0])
        d_lo, d_hi = lc.get("depth_m", [11.0, 15.0])
        ln = r.line
        for side in (-1.0, 1.0):
            d = 0.0
            k = 0
            while d < ln.length - 3.0:
                hsh = (int(ln.length * 10) * 7919 + k * 104729 + (1 if side > 0 else 2) * 15485863) % 1000
                wid = w_lo + (w_hi - w_lo) * (hsh % 97) / 96.0
                dep = d_lo + (d_hi - d_lo) * (hsh % 89) / 88.0
                k += 1
                p0, p1 = ln.interpolate(d), ln.interpolate(min(ln.length, d + wid))
                d += wid
                tx, ty = p1.x - p0.x, p1.y - p0.y
                tl = math.hypot(tx, ty)
                if tl < 3.0:
                    continue
                nx, ny = -ty / tl * side, tx / tl * side
                s0, s1 = r.width / 2.0 - 0.5, r.width / 2.0 + 6.0 + dep
                rect = Polygon([(p0.x + nx * s0, p0.y + ny * s0), (p1.x + nx * s0, p1.y + ny * s0),
                                (p1.x + nx * s1, p1.y + ny * s1), (p0.x + nx * s1, p0.y + ny * s1)])
                lot = clean(rect.intersection(area_strip_land).difference(keep_out).difference(taken.buffer(0.1)))
                polys = sorted(_polys(lot), key=lambda q: q.area, reverse=True)
                if not polys:
                    continue
                lot = polys[0].simplify(0.25, preserve_topology=True)
                if lot.area < 0.55 * tl * dep or lot.distance(front_zone) > 0.6:
                    continue
                mrr = lot.minimum_rotated_rectangle
                mc = list(mrr.exterior.coords)
                if min(math.dist(mc[0], mc[1]), math.dist(mc[1], mc[2])) < 4.5 or lot.area < 0.75 * mrr.area:
                    continue  # slivers and wedges at junctions read as glitches, not buildings
                if district_at(lot.centroid) != district:
                    continue
                bid = -(len(out) + 1)
                tags = {"building": "yes", "source": "infill"}
                levels = rules.default_levels(bid, "yes", district, lot.area)
                out.append(Building(bid, orient(lot, 1.0), levels, "infill", tags, district=district))
                taken = ops.unary_union([taken, lot])
    return out


def dual_shift(cfg: dict, ways: list, way_lines: dict) -> dict:
    """Centrelines of dual-carriageway ways moved so the pair sits widths + median apart (config
    "dual_carriageways"); {way id: moved line}. Shared by the cell build and the road network data."""
    dual = cfg.get("dual_carriageways", {})
    shifted: dict[int, LineString] = {}
    for w in ways:
        # OSM draws each carriageway of a dual road as its own centreline. Where they sit closer than
        # their widths plus the median allow, push each one outwards so lanes keep their true width.
        rule = dual.get(w.tags.get("name", ""))
        ln = way_lines[w.id]
        if rule is None or ln is None or ln.length < 5.0:
            continue
        mid = ln.interpolate(0.5, normalized=True)
        partners = [(way_lines[o.id].distance(mid), o) for o in ways
                    if o.id != w.id and o.tags.get("name") == w.tags.get("name") and way_lines[o.id] is not None
                    and not set(o.node_ids) & set(w.node_ids)]
        partners = [(d, o) for d, o in partners if d < 25.0]
        if not partners:
            continue
        dist, other = min(partners, key=lambda t: t[0])
        need = (rules.road_width(w.tags) + rules.road_width(other.tags)) / 2 + float(rule.get("median_m", 1.5))
        delta = (need - dist) / 2
        if rule.get("centre_line"):
            # no median: the carriageways must meet at a painted centre line, so pull them together as well as push apart
            if abs(delta) <= 0.05:
                continue
        elif delta <= 0.05:
            continue
        q = way_lines[other.id].interpolate(way_lines[other.id].project(mid))
        side = -1.0 if _side(ln, q) > 0 else 1.0  # move away from the partner (+ = left)
        if delta < 0:
            side, delta = -side, -delta                # pull towards the partner
        moved = ln.offset_curve(side * delta, quad_segs=2, join_style="mitre", mitre_limit=3.0)
        if not moved.is_empty and moved.geom_type == "LineString":
            shifted[w.id] = moved
    shifted.update(_parallel_ways(dual, ways, {**way_lines, **shifted}))
    return shifted


def _parallel_ways(dual: dict, ways: list, way_lines: dict) -> dict:
    """CIRCLE fix 5: a dual rule's "parallel_ways" {moved way id: reference way id} rebuilds the moved way's line as
    the reference line offset by half both widths plus the median, towards the moved way, so the pair keeps the
    measured section along its whole length (OSM draws Centre Road's pair 3.2-5.8 m off a constant spacing). The
    moved way keeps its own end points; it follows the offset from "parallel_ends_m" (30 m) in from each end."""
    out: dict[int, LineString] = {}
    by_id = {w.id: w for w in ways}
    for rule in dual.values():
        if not isinstance(rule, dict):
            continue
        ends = float(rule.get("parallel_ends_m", 30.0))
        for mid_s, ref_s in rule.get("parallel_ways", {}).items():
            w, ref = by_id.get(int(mid_s)), by_id.get(int(ref_s))
            if w is None or ref is None or way_lines.get(w.id) is None or way_lines.get(ref.id) is None:
                continue
            ln, rl = way_lines[w.id], way_lines[ref.id]
            need = (rules.road_width(w.tags) + rules.road_width(ref.tags)) / 2 + float(rule.get("median_m", 0.0))
            side = 1.0 if _side(rl, ln.interpolate(0.5, normalized=True)) > 0 else -1.0
            off = rl.offset_curve(side * need, quad_segs=2, join_style="mitre", mitre_limit=3.0)
            if off.is_empty or off.geom_type != "LineString":
                continue
            pts = [c for c in off.coords if ends <= ln.project(Point(c)) <= ln.length - ends]
            pts.sort(key=lambda c: ln.project(Point(c)))
            if len(pts) < 2:
                continue
            out[w.id] = LineString([ln.coords[0], *pts, ln.coords[-1]])
    return out


def _layer_levels(terr, green_polys, lawn, private, stats: dict, buildings=(), road_area=None) -> None:
    """Levels file "layer_levels" (HEIGHTS 2026-11-24): [{"name", "layer": "green", "park_names": [...], "dz",
    "edge", "relief"}] -> one hard-edged LevelArea over the named parks' lawn layers (less private grounds), so the
    whole layer sits dz from the plot datum with step faces where it meets the pavement. Sets terr.green_dz.
    {"layer": "building_base", "osm_ids": [...], "apron_m", "keep_off_road_m", "dz", "edge", "ramp_m"}: a podium /
    forecourt pad round those buildings' footprints, kept keep_off_road_m back from every carriageway so the kerb and
    the street pavement stay at datum; inserted first, so the pad wins over the Green and the hand-drawn areas."""
    for spec in getattr(terr, "layer_levels", []):
        if spec.get("layer") == "building_base":
            ids = {int(i) for i in spec.get("osm_ids", [])}
            fps = [b.footprint for b in buildings if b.osm_id in ids]
            if not fps:
                continue
            pad = ops.unary_union(fps).buffer(float(spec.get("apron_m", 4.0)), join_style=2)
            if road_area is not None and not road_area.is_empty:
                pad = pad.difference(road_area.buffer(float(spec.get("keep_off_road_m", 3.0)), quad_segs=2))
            pad = clean(pad)
            parts = [q for q in _polys(pad) if q.area >= 4.0]
            for q in parts:
                terr.areas.insert(0, terrain_mod.LevelArea(
                    spec["name"], orient(q, 1.0), float(spec["dz"]), float(spec.get("ramp_m", 0.0)),
                    spec.get("edge", "terrace"), spec.get("source", ""), bool(spec.get("estimate", True))))
            stats.setdefault("layer_levels", {})[spec["name"]] = {"dz": float(spec["dz"]),
                                                                   "m2": round(sum(q.area for q in parts))}
            continue
        if spec.get("layer") != "green":
            continue
        names = set(spec.get("park_names", []))
        named = [poly for name, poly in green_polys if name in names and poly is not None]
        if not named or lawn.is_empty:
            continue
        region = clean(ops.unary_union(named).buffer(0).intersection(lawn).difference(private))
        if region.is_empty:
            continue
        for part in _polys(region):
            if part.area < 4.0:
                continue
            terr.areas.append(terrain_mod.LevelArea(
                spec["name"], orient(part, 1.0), float(spec["dz"]), 0.0, spec.get("edge", "terrace"),
                spec.get("source", ""), bool(spec.get("estimate", True)), None, "datum", bool(spec.get("relief", True))))
        terr.green_dz = float(spec["dz"])
        stats.setdefault("layer_levels", {})[spec["name"]] = {"dz": float(spec["dz"]), "m2": round(region.area)}


def build_layout(cfg: dict, data: osm.OsmData, tm=geo.CITYHUB) -> Layout:
    terr = terrain_mod.load(cfg)
    terrain_mod.resolve_grades(terr, data, tm)   # HEIGHTS: road profiles given by OSM way ids
    h = Heights(**{**{k: v for k, v in cfg.get("heights", {}).items() if not k.startswith("_")}, **terr.datum})
    stats: dict = {}

    # --- area_strip ---------------------------------------------------------------------------
    c = cfg["area_strip"]
    route = route_line(c, tm)
    if "start" in c:
        a = tm.forward(*c["start"])
        b = tm.forward(*c["end"])
    else:  # route only: the axis (stripes, sea UVs, wear gradient) runs from the route start to its farthest point
        a = route.coords[0]
        b = max(route.coords, key=lambda q: math.dist(q, a))
    axis = LineString([a, b])
    ux, uy = (b[0] - a[0]) / axis.length, (b[1] - a[1]) / axis.length
    lx, ly = -uy, ux  # left normal (west / sea side when heading north)

    coast_lines = [ln for w in osm.lines(data, lambda t: t.get("natural") == "coastline")
                   if (ln := _line(data, w.node_ids, tm)) is not None]
    coast = ops.linemerge(MultiLineString(coast_lines)) if coast_lines else None
    old_coast = coast
    coast, beach_strips = widen_beach(coast, cfg.get("beach_widen", []))

    west = float(c.get("west_m", 0.0))
    if c.get("west_auto") and coast is not None:
        # widest coastline offset (left of the axis) within the axis span, plus the sea margin
        reach = 0.0
        for ln in getattr(coast, "geoms", [coast]):
            for x, y in ln.coords:
                t = (x - a[0]) * ux + (y - a[1]) * uy
                if -20.0 <= t <= axis.length + 20.0:
                    reach = max(reach, (x - a[0]) * lx + (y - a[1]) * ly)
        west = max(west, reach + float(c.get("sea_offshore_m", 150.0)))
        west = min(west, float(c.get("west_max_m", 1e9)))
    east = float(c.get("east_m", 0.0))
    area_strip = Polygon([
        (a[0] - lx * east, a[1] - ly * east),
        (b[0] - lx * east, b[1] - ly * east),
        (b[0] + lx * west, b[1] + ly * west),
        (a[0] + lx * west, a[1] + ly * west),
    ])
    area_strip = orient(area_strip, 1.0)
    base_area_strip = area_strip if "start" in c else EMPTY
    area_strip = route_area_strip(base_area_strip, route, float(c.get("route", {}).get("half_width_m", 80.0)))
    for extra in c.get("extra_routes", []):
        area_strip = extra_route_area(area_strip, extra, tm)
    drive = None
    if cfg.get("drive_loop"):
        # M6 drive circle: its joins become roads, its centreline buffer and the scenery boxes join the build area
        from . import drive_loop  # noqa: E402
        drive = drive_loop.route(cfg, data, tm)
        extras = [LineString(drive["points"]).buffer(float(cfg["drive_loop"].get("area_buffer_m", 90.0)), quad_segs=8)]
        extras += [Polygon([tm.forward(lat, lon) for lat, lon in ring]) for ring in c.get("extra_areas", [])]
        grown = clean(ops.unary_union([area_strip, *extras]))
        area_strip = orient(max(_polys(grown), key=lambda q: q.area), 1.0)
        stats["drive_loop"] = {"length_m": round(drive["length_m"], 1), "closed": drive["closed"],
                               "area_pieces_dropped": len(_polys(grown)) - 1}
    reach = float(c.get("route", {}).get("water_reach_m", 0.0))
    if route is not None and reach > 0.0:
        # lakes seen from the route are part of the build area out to water_reach_m (a lake beyond the frontage
        # band would otherwise stop as a 3 m sliver), so the road along Beira Lake looks over open water
        waters = [_area_poly(data, ar, tm) for ar in osm.areas(data, lambda t: t.get("natural") == "water")]
        near = clean(ops.unary_union(waters).intersection(route.buffer(reach, quad_segs=8))) if waters else EMPTY
        if not near.is_empty:
            area_strip = orient(max(_polys(clean(ops.unary_union([area_strip, near.buffer(0.5)]))), key=lambda q: q.area), 1.0)
    stats["area_strip"] = {"length_m": round(axis.length, 1), "west_m": round(west, 1), "east_m": east,
                         "area_m2": round(area_strip.area)}
    if route is not None:
        stats["area_strip"]["route_m"] = round(route.length, 1)
        stats["area_strip"]["route_half_width_m"] = float(c["route"].get("half_width_m", 80.0))

    # --- land and sea ------------------------------------------------------------------------
    if coast is not None and coast.intersects(area_strip):
        pieces = ops.split(area_strip, coast if isinstance(coast, LineString) else MultiLineString(list(coast.geoms)))
        land_parts, sea_parts = [], []
        for piece in pieces.geoms:
            rp = piece.representative_point()
            nearest = min(getattr(coast, "geoms", [coast]), key=lambda ln: ln.distance(rp))
            (land_parts if _side(nearest, rp) > 0 else sea_parts).append(piece)
        land = clean(ops.unary_union(land_parts))
        sea = clean(ops.unary_union(sea_parts))
    else:
        land, sea = area_strip, EMPTY
    area_strip_land = land

    # --- roads -------------------------------------------------------------------------------
    reach_box = area_strip.buffer(40.0)
    overrides = cfg.get("road_overrides", {})
    ways = [w for w in override_ways(data, overrides) if rules.is_carriageway(w.tags)]
    node_use: dict[int, int] = {}
    for w in ways:
        for i, n in enumerate(w.node_ids):
            node_use[n] = node_use.get(n, 0) + (1 if i in (0, len(w.node_ids) - 1) else 2)
    groups: dict[tuple, list[LineString]] = {}
    way_width: dict[int, float] = {}
    way_lines = {w.id: _line(data, w.node_ids, tm) for w in ways}
    shifted = dual_shift(cfg, ways, way_lines)
    way_lines.update(shifted)
    for w in ways:
        ln = way_lines[w.id]
        if ln is None or not ln.intersects(reach_box):
            continue
        width = rules.road_width(w.tags)
        way_width[w.id] = width
        key = (rules.road_priority(w.tags), width, rules.pavement_width(w.tags), w.tags.get("name", ""))
        groups.setdefault(key, []).append(ln)
    merged: list[tuple[tuple, LineString]] = []
    for key in sorted(groups):
        m = ops.linemerge(MultiLineString(groups[key]))
        for ln in getattr(m, "geoms", [m]):
            merged.append((key, ln))

    bufs = [ln.buffer(k[1] / 2.0, quad_segs=4) for k, ln in merged]
    road_area = clean(ops.unary_union(bufs).intersection(area_strip_land))
    ring_fill = roundabout_fill(cfg, ways, way_lines, way_width, area_strip_land)
    if not ring_fill.is_empty:
        road_area = clean(ops.unary_union([road_area, ring_fill]))
        stats["roundabout_fill_m2"] = round(ring_fill.area)

    disks = []
    for w in ways:
        if w.id not in way_width:
            continue
        for n in w.node_ids:
            if node_use.get(n, 0) >= 3 and n in data.nodes:
                x, y = tm.forward(*data.nodes[n])
                disks.append(Point(x, y).buffer(way_width[w.id] / 2.0 + 2.0, quad_segs=4))
    junctions = clean(road_area.intersection(ops.unary_union(disks))) if disks else EMPTY
    if not ring_fill.is_empty:
        junctions = clean(ops.unary_union([junctions, ring_fill]))

    open_road = road_area.difference(junctions)
    claimed = EMPTY
    roads: list[RoadPiece] = []
    for (key, ln), buf in zip(merged, bufs):
        piece = clean(open_road.intersection(ln.buffer(key[1] / 2.0 + 0.05, quad_segs=4)).difference(claimed))
        if piece.is_empty:
            continue
        claimed = ops.unary_union([claimed, piece])
        roads.append(RoadPiece(piece, ln, key[1], key[3], key[0]))
    stats["roads"] = {"dual_carriageway_ways_shifted": len(shifted), "ways": len(way_width), "merged_lines": len(merged), "pieces": len(roads),
                      "junction_area_m2": round(junctions.area), "road_area_m2": round(road_area.area)}

    # --- pavements and footpaths -------------------------------------------------------------
    pav = [ln.buffer(k[1] / 2.0 + k[2], quad_segs=4) for k, ln in merged if k[2] > 0]
    for w in (w for w in override_ways(data, overrides) if rules.is_footpath(w.tags)):
        ln = _line(data, w.node_ids, tm)
        if ln is not None and ln.intersects(reach_box):
            pav.append(ln.buffer(rules.footpath_width(w.tags) / 2.0, quad_segs=2))
    pavement = clean(ops.unary_union(pav).intersection(area_strip_land).difference(road_area)) if pav else EMPTY
    wide = widened_pavements(cfg, roads, road_area, area_strip_land)
    if not wide.is_empty:
        pavement = clean(ops.unary_union([pavement, wide]))
        stats["pavement_widening_m2"] = round(wide.area)
    green_polys = [(ar.tags.get("name", ""), _area_poly(data, ar, tm))
                   for ar in osm.areas(data, lambda t: t.get("leisure") in ("park", "garden"))]
    lane_out: list = []
    strip_parking, strip_paved = roadside_strips(cfg, green_polys, roads, road_area, coast, area_strip_land, lane_out)
    parking_lane = lane_out[0] if lane_out else EMPTY
    if not strip_paved.is_empty or not strip_parking.is_empty:
        pavement = clean(ops.unary_union([pavement, strip_paved]).difference(strip_parking))
        stats["roadside_strip_m2"] = {"parking": round(strip_parking.area), "paved": round(strip_paved.area)}
    if not parking_lane.is_empty:
        cut_out = parking_lane_gaps(cfg, data, tm, roads, junctions)
        if not cut_out.is_empty:
            # the kerb comes back to the carriageway edge at crossings, bus stops and junctions; the gap is paved
            dropped = clean(parking_lane.intersection(cut_out))
            parking_lane = clean(parking_lane.difference(cut_out))
            pavement = clean(ops.unary_union([pavement, dropped.difference(road_area)]))
            stats["parking_lane_gaps_m2"] = round(dropped.area)
    if not parking_lane.is_empty:
        # CIRCLE fix 5: the parking lane is road (asphalt at road level, no kerb between it and the driving lanes)
        road_area = clean(ops.unary_union([road_area, parking_lane]))
        pavement = clean(pavement.difference(parking_lane))
        stats["roadside_strip_m2"] = {**stats.get("roadside_strip_m2", {}), "parking_lane": round(parking_lane.area)}
    medians, median_gaps = road_medians(cfg, roads)
    if not medians.is_empty:
        # CIRCLE fix 5: raised median islands are pavement-level islands with kerbs all round (the road's holes)
        road_area = clean(road_area.difference(medians))
        for r in roads:
            if r.poly.intersects(medians):
                r.poly = clean(r.poly.difference(medians))
        pavement = clean(ops.unary_union([pavement, medians]))
        stats["road_medians"] = {"islands": len(_polys(medians)), "m2": round(medians.area, 1)}

    # --- kerbside places (ROADS2): lay-bys and forecourt aprons at road level, cut out of the pavement ----------
    if cfg.get("road_network", {}).get("frontages"):
        from . import road_network  # noqa: PLC0415  (road_network imports layout lazily too)
        net = road_network.network_from_config(cfg, data, tm)
        extra = []
        for f in net["frontages"]:
            polys = [Polygon(f["apron"])] + [Polygon(lb) for lb in f["laybys"]]
            for poly in polys:
                poly = clean(poly.buffer(0).intersection(area_strip_land))
                if poly.is_empty:
                    continue
                extra.append(poly)
                roads.append(RoadPiece(poly, LineString(f["kerb"]), 2.5, f["street"]))
        if extra:
            add = ops.unary_union(extra)
            road_area = clean(ops.unary_union([road_area, add]))
            pavement = clean(pavement.difference(add))
            stats["kerbside_m2"] = round(add.area)

    district0 = cfg.get("district", "delta_face")
    zones = [(z["district"], Polygon([tm.forward(lat, lon) for lat, lon in z["polygon"]]))
             for z in cfg.get("district_zones", [])]

    def district_at(p) -> str:
        # zones style the route extension only: the base area_strip's buildings keep their district and look
        if not base_area_strip.is_empty and base_area_strip.contains(p):
            return district0
        return next((d for d, zp in zones if zp.contains(p)), district0)
    landmarks = {int(k): v for k, v in cfg.get("landmarks", {}).items()}
    heroes = {int(k): v for k, v in cfg.get("heroes", {}).items()}
    parts = [(ar.id, _area_poly(data, ar, tm), ar.tags) for ar in osm.areas(data, lambda t: "building:part" in t)]
    buildings: list[Building] = []
    footprints = []
    for ar in sorted(osm.areas(data, lambda t: "building" in t), key=lambda ar: ar.id):
        t = ar.tags
        if t.get("building") in rules.SKIP_BUILDINGS or t.get("location") == "underground":
            continue
        fp = _area_poly(data, ar, tm)
        if fp.is_empty or not area_strip_land.contains(fp.centroid):
            continue
        fp = fp.simplify(0.25, preserve_topology=True)
        fp = clean(fp.difference(road_area))
        polys = sorted(_polys(fp), key=lambda p: p.area, reverse=True)
        if not polys or polys[0].area < 15.0:
            continue
        fp = orient(polys[0], 1.0)
        district = district_at(fp.centroid)
        levels, src = rules.building_levels(ar.id, t, district, fp.area)
        # building:part masses (towers on podiums, skybridges) replace the outline where OSM has them
        inside = [(pid, pp, pt) for pid, pp, pt in parts
                  if not pp.is_empty and fp.buffer(1.0).contains(pp.representative_point())
                  and ("building:levels" in pt or "height" in pt)]
        if inside:
            covered = EMPTY
            for pid, pp, pt in inside:
                ppoly = sorted(_polys(clean(pp.simplify(0.25, preserve_topology=True))), key=lambda q: q.area, reverse=True)
                if not ppoly or ppoly[0].area < 15.0:
                    continue
                base = rules.parse_length(pt.get("min_height")) or 0.0
                height = rules.parse_length(pt.get("height"))
                if height:
                    plev = rules.levels_from_height(height - base)
                else:
                    plev = max(1, (rules.parse_int(pt.get("building:levels")) or 1) - (rules.parse_int(pt.get("building:min_level")) or 0))
                    base = base or (rules.parse_int(pt.get("building:min_level")) or 0) * rules.UPPER_FLOOR_M
                b_part = Building(pid, orient(ppoly[0], 1.0), min(plev, 80), "parts", {**t, **pt}, base=base,
                                  landmark=landmarks.get(pid, ""), hero=heroes.get(pid, {}), district=district if zones else "")
                buildings.append(b_part)
                footprints.append(ppoly[0])
                if base <= 0.0:
                    covered = ops.unary_union([covered, ppoly[0]])
            rest = sorted(_polys(clean(fp.difference(covered.buffer(0.3)))), key=lambda q: q.area, reverse=True)
            if rest and rest[0].area > max(60.0, 0.2 * fp.area):
                podium = Building(ar.id, orient(rest[0], 1.0), min(levels, 3), "podium", t,
                                  landmark=landmarks.get(ar.id, ""), sacred=rules.is_sacred(t), hero=heroes.get(ar.id, {}), district=district if zones else "")
                buildings.append(podium)
                footprints.append(rest[0])
            continue
        if src == "default":
            inside_lv = [rules.building_levels(0, pt)[0] for pp, pt in [(q[1], q[2]) for q in parts]
                         if not pp.is_empty and fp.contains(pp.representative_point())]
            if inside_lv:
                levels, src = max(inside_lv), "parts"
        bld = Building(ar.id, fp, levels, src, t, landmark=landmarks.get(ar.id, ""), sacred=rules.is_sacred(t),
                       hero=heroes.get(ar.id, {}), district=district if zones else "")
        buildings.append(bld)
        footprints.append(fp)
    infill = frontage_infill(cfg, data, tm, roads, road_area, pavement, area_strip_land,
                             ops.unary_union(footprints) if footprints else EMPTY, district_at)
    buildings += infill
    footprints += [b.footprint for b in infill]
    stats["frontage_infill"] = {"lots": len(infill), "area_m2": round(sum(b.footprint.area for b in infill))}
    built = ops.unary_union(footprints) if footprints else EMPTY

    # --- beach, promenade, green, plots, lake -------------------------------------------------
    ground_free = area_strip_land.difference(road_area).difference(pavement)
    beaches = [_area_poly(data, ar, tm) for ar in osm.areas(data, lambda t: t.get("natural") in ("beach", "sand"))]
    foreshore = coast.buffer(float(cfg.get("foreshore_m", 6.0))) if coast is not None else EMPTY
    if beach_strips:  # widened beach (widen_beach): the gained land and the old foreshore band are sand too
        beaches += beach_strips + [old_coast.buffer(float(cfg.get("foreshore_m", 6.0)))]
    beach_land = clean(ops.unary_union(beaches + [foreshore]).intersection(ground_free).difference(built))
    private = private_grounds(cfg)
    if not private.is_empty:  # private seafront grounds run to the seawall: no public beach or promenade there
        beach_land = clean(beach_land.difference(private))
    apron = clean(foreshore.intersection(sea)) if coast is not None else EMPTY
    beach = clean(ops.unary_union([beach_land, apron]))
    prom_w = float(cfg.get("promenade_m", 6.0))
    # the promenade is one continuous paver surface: OSM footways drawn along it are absorbed into it
    # (they would otherwise sit 0.45 m higher, at pavement level, and cut it into strips with walls)
    promenade = clean(beach_land.buffer(prom_w, quad_segs=2).intersection(area_strip_land.difference(road_area))
                      .difference(beach_land).difference(built).difference(private)) if not beach_land.is_empty else EMPTY
    # hero piers (citylib/hero_pier.py, `"pier": true`) start on the seawall line: the coastline's 2 m promenade
    # tongue along the OSM pier root would poke through the jetty deck, so it becomes beach under the jetty
    for spec in cfg.get("hero_models", {}).values():
        if spec.get("pier") and not promenade.is_empty:
            (px, py), ya = spec["pivot"], math.radians(float(spec.get("yaw_deg", 0.0)))
            cut = Polygon([(px + u * math.cos(ya) - v * math.sin(ya), py + u * math.sin(ya) + v * math.cos(ya))
                           for u, v in ((0.05, -6.0), (40.0, -6.0), (40.0, 6.0), (0.05, 6.0))])
            tongue = ops.unary_union([promenade, pavement]).intersection(cut)   # the pier's OSM footway too
            tongue = tongue.buffer(0.3, join_style=2).intersection(cut).intersection(land)   # no slivers left
            promenade = clean(promenade.difference(cut))
            pavement = clean(pavement.difference(cut))
            beach_land = clean(ops.unary_union([beach_land, tongue]))
            beach = clean(ops.unary_union([beach, tongue]))
    if not promenade.is_empty:
        pavement = clean(pavement.difference(promenade))
        ground_free = area_strip_land.difference(road_area).difference(pavement)
    lakes = [_area_poly(data, ar, tm) for ar in osm.areas(data, lambda t: t.get("natural") == "water")]
    lake = clean(ops.unary_union(lakes).intersection(ground_free).difference(beach_land)) if lakes else EMPTY
    greens = [_area_poly(data, ar, tm) for ar in osm.areas(
        data, lambda t: t.get("leisure") in ("park", "garden", "pitch", "playground")
        or t.get("landuse") in ("grass", "recreation_ground", "village_green") or t.get("natural") in ("grassland", "scrub"))]
    parks = [_area_poly(data, ar, tm) for ar in osm.areas(data, lambda t: t.get("amenity") == "parking"
                                                          and t.get("parking") not in ("underground", "multi-storey"))]
    parking = clean(ops.unary_union(parks).intersection(ground_free).difference(
        ops.unary_union([beach_land, promenade, lake, built]))) if parks else EMPTY
    if not strip_parking.is_empty:
        parking = clean(ops.unary_union([parking, strip_parking.difference(built)]))
    taken = ops.unary_union([beach_land, promenade, lake, parking])
    green = clean(ops.unary_union(greens).intersection(ground_free).difference(taken)) if greens else EMPTY
    # The Green and the leftover plots are split into lawn / worn turf / bare laterite by a natural wear
    # field (layout noise + trampling along the promenade and paths, drier in the south half where the
    # cannons and vendors are: references gf_02, gf_05, gf_09, gf_12, gf_16), not by hashed discs.
    park = green
    plots = clean(ground_free.difference(taken).difference(green))
    bares = [_area_poly(data, ar, tm) for ar in osm.areas(
        data, lambda t: t.get("landuse") in ("construction", "brownfield") or t.get("natural") == "sand")]
    bare = clean(ops.unary_union(bares).intersection(plots).difference(built.buffer(3.0))) if bares else EMPTY
    plots = clean(plots.difference(bare)) if not bare.is_empty else plots
    # forecourts: the strip of plot round each building is paved (concrete), as on Delta Road
    forecourt = clean(plots.intersection(built.buffer(float(cfg.get("forecourt_m", 6.0)), quad_segs=2))) \
        if not built.is_empty else EMPTY
    open_plots = clean(plots.difference(forecourt))
    wear_cfg = cfg.get("wear", {})
    wear_lines = [g for g in (promenade.boundary if not promenade.is_empty else None,
                              pavement.boundary if not pavement.is_empty else None) if g is not None]
    # one field over the Green and the open plots, so there is no seam where they meet; plots are biased
    # drier (unkempt verges and dirt lots), the Green keeps most of its lawn
    wear_area = clean(ops.unary_union([park, open_plots]))
    wear_parts = [wear_area] if base_area_strip.is_empty or route is None else \
        [clean(wear_area.intersection(base_area_strip)), clean(wear_area.difference(base_area_strip))]
    # the route extension is town, not park: unbuilt plots there are mostly worn ground and bare earth
    fracs = [wear_cfg.get("fractions", [0.86, 0.09]), wear_cfg.get("route_fractions", wear_cfg.get("fractions", [0.86, 0.09]))]
    split = [split_wear(part, axis, wear_lines, fracs[k], seed=1 + 10 * k,
                        bias=(open_plots, float(wear_cfg.get("plot_bias", 0.12)))) for k, part in enumerate(wear_parts)]
    green, worn, earth = (clean(ops.unary_union([sp[i] for sp in split])) for i in range(3))
    plots = forecourt  # what is left of the plots after the wear split: paved forecourts
    if not private.is_empty:  # kept grounds: a watered lawn, no trampled turf or bare earth (gf_20, agent h04, h18)
        kept = clean(ops.unary_union([worn, earth]).intersection(private).difference(ops.unary_union([road_area, pavement])))
        green = clean(ops.unary_union([green, kept]))
        worn, earth = clean(worn.difference(private)), clean(earth.difference(private))
    planted = planted_islands(cfg, roads, road_area)
    if not planted.is_empty:
        green = clean(ops.unary_union([green, planted]))
        worn, earth, plots, parking = (clean(g.difference(planted)) for g in (worn, earth, plots, parking))
        forecourt = plots
        pavement = clean(pavement.difference(planted))
        stats["planted_islands_m2"] = round(planted.area)
    # mowing stripes on the Green's lawn (gf_02, gf_05, gf_14): 9 m bands across the axis, alternate material
    lawn_stripe = EMPTY
    if not green.is_empty:
        lx_, ly_ = -uy, ux
        bands = []
        for k in range(-200, 200, 2):
            t0, t1 = k * 9.0, k * 9.0 + 9.0
            bands.append(Polygon([(a[0] + ux * t0 - lx_ * 600, a[1] + uy * t0 - ly_ * 600),
                                  (a[0] + ux * t1 - lx_ * 600, a[1] + uy * t1 - ly_ * 600),
                                  (a[0] + ux * t1 + lx_ * 600, a[1] + uy * t1 + ly_ * 600),
                                  (a[0] + ux * t0 + lx_ * 600, a[1] + uy * t0 + ly_ * 600)]))
        lawn_stripe = clean(green.intersection(park).intersection(ops.unary_union(bands)))
        green = clean(green.difference(lawn_stripe))
    # railway: a 3.4 m ballast bed per track where it runs through open ground (not over roads or water)
    rail_lines = [ln for w in osm.lines(data, lambda t: t.get("railway") in ("rail", "light_rail")
                                        and t.get("tunnel") != "yes")
                  if (ln := _line(data, w.node_ids, tm)) is not None and ln.intersects(area_strip_land)]
    rail = EMPTY
    if rail_lines:
        open_ground = ops.unary_union([green, lawn_stripe, worn, earth, plots, bare, parking])
        rail = clean(ops.unary_union([ln.buffer(1.7, cap_style="flat") for ln in rail_lines])
                     .intersection(open_ground).difference(built.buffer(0.5)))
        if not rail.is_empty:
            green, lawn_stripe, worn, earth, plots, bare, parking = (
                clean(g.difference(rail)) for g in (green, lawn_stripe, worn, earth, plots, bare, parking))
            forecourt = plots
    stats["railway"] = {"tracks": len(rail_lines), "ballast_m2": round(rail.area)}
    stats["wear"] = {"green_lawn_m2": round(green.area), "worn_m2": round(worn.area), "earth_m2": round(earth.area),
                     "forecourt_m2": round(forecourt.area)}

    # --- vertical edges ----------------------------------------------------------------------
    walls: list[WallSeg] = []
    cut = area_strip.exterior.buffer(0.05)
    sea_probe = sea.buffer(0.3) if not sea.is_empty else EMPTY

    def beach_z(x: float, y: float) -> float:
        if coast is None:
            return h.beach_top
        p = Point(x, y)
        d = coast.distance(p) * (1.0 if area_strip_land.contains(p) else -1.0)
        return max(h.beach_min, min(h.beach_top, h.sea + h.beach_slope * d))

    def rings(g):
        for p in _polys(g):
            yield p.exterior
            yield from p.interiors

    def segs(g):
        for r in rings(g):
            cs = list(r.coords)
            for p0, p1 in zip(cs, cs[1:]):
                mid = Point((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                if math.dist(p0, p1) > 1e-3 and not cut.contains(mid):
                    yield p0, p1, mid

    # HEIGHTS 2026-11-24 (levels file "layer_levels"): whole map layers set to a level, e.g. the Green a few steps
    # below the A2 pavement. Appended after the hand-drawn areas, so those (hotel terraces, step feet, mounds) win.
    _layer_levels(terr, green_polys, ops.unary_union([park, lawn_stripe, worn, earth, green]), private, stats,
                  buildings, road_area)
    # kerbs: every road edge, facing into the road (rings are oriented, so the road is on the left)
    for p0, p1, mid in segs(road_area):
        dz = terr.dz(*mid.coords[0])
        walls.append(WallSeg(p0, p1, h.road, h.road, h.plot + max(0.0, dz), "kerb"))  # kerb tops follow the levels
        if dz < -0.05:   # ground sunk below the kerb (the Green): a face from the sunk ground up to the kerb top
            walls.append(WallSeg(p1, p0, h.plot + dz, h.plot + dz, h.plot, "retaining"))
    # seawall: the beach's inland edges, facing the beach, up to whatever surface is behind
    prom_probe = promenade.buffer(0.3) if not promenade.is_empty else EMPTY
    seawall = []
    for p0, p1, mid in segs(beach):
        if not sea_probe.is_empty and sea_probe.contains(mid):
            continue
        top = h.promenade if (not prom_probe.is_empty and prom_probe.contains(mid)) else h.plot + terr.dz(*mid.coords[0])
        seawall.append((p0, p1, top))  # dressed with KIT_Seawall_Rubble_A by dressing.py
    # promenade edges below the Green or plots: low stone retaining walls facing the promenade
    beach_probe = beach.buffer(0.3) if not beach.is_empty else EMPTY
    road_probe = road_area.buffer(0.3)
    terrace = []
    for p0, p1, mid in segs(promenade):
        if beach_probe.contains(mid) or road_probe.contains(mid):
            continue
        # the ground behind the promenade edge (the Green may sit below the plot datum: HEIGHTS layer_levels)
        L = math.dist(p0, p1) or 1.0
        nx, ny = (p1[1] - p0[1]) / L, -(p1[0] - p0[0]) / L   # right of p0 -> p1: away from the promenade
        mx, my = mid.coords[0]
        lo, hi = sorted((h.promenade, h.plot + terr.dz(mx + nx * 0.5, my + ny * 0.5)))
        if h.promenade < hi:
            walls.append(WallSeg(p0, p1, lo, lo, hi, "retaining"))  # promenade on the left (ring interior)
            terrace.append((p0, p1))
        else:
            walls.append(WallSeg(p1, p0, lo, lo, hi, "retaining"))
    # level steps (citylib/terrain.py): wall faces where a hard-edged level area meets lower ground
    if not terr.empty:
        ground_all = clean(ops.unary_union([green, lawn_stripe, worn, earth, plots, bare, parking, pavement]))
        steps = terr.step_edges(ground_all, h.plot)
        walls += [WallSeg(p0, p1, lo, lo, hi, kind) for p0, p1, lo, hi, kind in steps]
        stats["terrain"] = {"areas": len(terr.areas), "step_faces": len(steps), "private_m2": round(private.area)}
    # lake banks, facing the water
    for p0, p1, mid in segs(lake):
        walls.append(WallSeg(p0, p1, h.lake, h.lake, h.plot, "bank"))

    # --- street-facing edges -----------------------------------------------------------------
    street_zone = ops.unary_union([road_area, pavement, promenade]).buffer(1.0)
    # ROADS2 "frontage_roads" {osm id: [road names]}: that building's street fronts face only the listed roads. Filling the
    # drive circle builds the One Delta Face podium's service alleys, which would turn its loading sides into shopfronts
    # (+25.5k LOD0 tris in cell_-1_4, budget 60k).
    only_roads = {int(k): v for k, v in cfg.get("frontage_roads", {}).items() if not k.startswith("_")}
    for bld in buildings:
        fp = bld.footprint
        flags = []
        for ring in [fp.exterior] + list(fp.interiors):
            cs = list(ring.coords)[:-1]
            rf = []
            for i in range(len(cs)):
                (ax, ay), (bx, by) = cs[i], cs[(i + 1) % len(cs)]
                ln = math.hypot(bx - ax, by - ay) or 1.0
                nx, ny = (by - ay) / ln, -(bx - ax) / ln  # outward (right of a CCW outer ring)
                probe = Point((ax + bx) / 2 + nx * 6.0, (ay + by) / 2 + ny * 6.0)
                front = street_zone.distance(probe) < 4.0 and not fp.contains(probe)
                if front and bld.osm_id in only_roads:
                    front = any(r.poly.distance(probe) < 4.0 + 6.0 for r in roads if r.name in only_roads[bld.osm_id])
                rf.append(front)
            flags.append(rf)
        bld.street = flags
    stats["frontage_rules"] = apply_frontage_rules(cfg, roads, promenade, buildings)

    stats["_skybridges"] = cfg.get("skybridges", [])
    stats["surfaces_m2"] = {k: round(v.area) for k, v in {
        "land": area_strip_land, "sea": sea, "road": road_area, "pavement": pavement, "promenade": promenade,
        "beach": beach, "green": green, "worn_turf": worn, "earth": earth, "forecourt": forecourt, "parking": parking, "plots": plots, "bare": bare, "lake": lake}.items()}
    stats["buildings"] = {"count": len(buildings),
                          "levels_from": {s: sum(1 for b in buildings if b.levels_source == s)
                                          for s in ("levels", "height", "parts", "podium", "default", "infill")},
                          "landmarks": sorted({b.landmark for b in buildings if b.landmark}),
                          "sacred": [b.osm_id for b in buildings if b.sacred]}
    stats["walls"] = {k: sum(1 for w in walls if w.kind == k) for k in ("kerb", "retaining", "bank")}
    stats["walls"]["seawall_kit_segments"] = len(seawall)

    # --- sea bands: shallow water near the shore and the surf line -----------------------------
    if coast is not None and not sea.is_empty:
        shallow = clean(sea.intersection(coast.buffer(float(cfg.get("shallow_m", 40.0)))))
        surf = clean(sea.intersection(coast.buffer(float(cfg.get("surf_m", 5.0)))))
    else:
        shallow = surf = EMPTY

    hero_list = hero_sites_mod.hero_sites(cfg, buildings, h.road)
    if not terr.empty:  # heroes stand on the terrain at their pivot (the hero's own grounds model the rest)
        import dataclasses
        hero_list = [dataclasses.replace(s, pivot=(s.pivot[0], s.pivot[1], s.pivot[2] + terr.dz(s.pivot[0], s.pivot[1])))
                     for s in hero_list]
    stats["heroes"] = {s.name: {"pivot": list(s.pivot), "yaw_deg": s.yaw_deg, "cell": grid.cell_id(s.cell),
                                "replaces": list(s.osm_ids) or s.fountain} for s in hero_list}
    # --- the Green's relief (agent 2026-11-19: "the Green is not flat"; config "green_relief") ----------------
    gr = cfg.get("green_relief")
    if gr and not park.is_empty:
        named = [poly for name, poly in green_polys if name in set(gr.get("park_names", []))]
        region = clean(ops.unary_union(named).intersection(ops.unary_union([park, lawn_stripe, worn, earth]))
                       .difference(private)) if named else EMPTY
        land = [r.line for r in roads if r.name in set(gr.get("land_roads", []))]
        if not region.is_empty and land and coast is not None:
            terr.reliefs.append(terrain_mod.Relief(
                "delta_face_green", region.buffer(0), ops.unary_union(land), coast,
                crown_m=float(gr.get("crown_m", 0.3)), crown_at=float(gr.get("crown_at", 0.7)),
                mound_m=float(gr.get("mound_m", 0.25)), mound_scale_m=float(gr.get("mound_scale_m", 35.0)),
                edge_m=float(gr.get("edge_m", 6.0)), grid_m=float(gr.get("grid_m", 8.0)), seed=int(gr.get("seed", 7)),
                source=gr.get("_doc", "")))
            stats["green_relief_m2"] = round(region.area)

    return Layout(area_strip, axis, area_strip_land, sea, coast, roads, junctions, road_area, pavement, promenade,
                  beach, green, plots, worn, earth, forecourt, park, lawn_stripe, parking, bare, lake, walls, seawall, terrace, shallow, surf, buildings, h, stats,
                  hero_list, None if route is None or base_area_strip.is_empty else base_area_strip, rail,
                  [ln.intersection(rail.buffer(0.1)) for ln in rail_lines] if not rail.is_empty else [],
                  terrain=terr, private=private, focus=_focus(c, tm), cell_trim=cfg.get("cell_trim", {}),
                  parking_lane=parking_lane, medians=medians, median_gaps=median_gaps)
