"""P165: the Baladaksha lake edge as city geometry, generated from the road edge and the lake shoreline.

The agent's complaint on P162 (separate 4 m kit pieces tiled by dry-run placement) was that the edge followed the road,
stepped sideways on curves and was not part of the city. This module builds it the way the city builds roads, kerbs and
footways: Shapely polygons from the layout's own geometry (the road area and the lake polygon), cut per cell by
`cells.build_cells` into one `<cell>_LakeEdge` mesh (one draw per material), with the wall and the railing swept along
the real shoreline.

Layers, from the kerb to the water (agent 2026-11-20, shots os_10, os_13, os_14, os_20):
  kerb line (yellow stone, 0.3 m) | red paver strip (2.5 m) | grass verge (the rest) | stone walking path (4 m, low
  step, yellow tactile strip) | lake wall (0.3 m, half-round coping) with a green-bar railing on top.
The path and the wall are measured from the SHORELINE, the paver strip and the kerb line from the ROAD EDGE, the verge
fills what is left, so every layer follows its own curve and the widths hold on bends.

Props (`place_props`) stand on the same distance fields: block seats and cube seats beside the path, rust slab stubs
near the road, verge shrubs and trees; lamps come from `drive_loop.dress_lakeside`.

Pure Shapely and `MeshData` (no bpy), so the unit tests run anywhere.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely import ops
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from . import materials as M
from .mesh import MeshData, hex_rgb, prism_ring

# defaults for `drive_loop.lakeside.edge` (config wins); every number has a source in the agent shots or a reason
DEFAULTS = {
    "paver_strip_m": 2.5,        # os_13, os_20: red-brown strip beside the kerb
    "kerb_line_m": 0.3,          # os_13: yellow kerb stone (the paint on the asphalt is a marking, not here)
    "walking_path_m": 4.0,       # os_14
    "tactile_m": 0.4,            # os_14: yellow guiding strip, offset to the middle of the path
    "path_step_m": 0.12,         # os_14: the path stands a hand above the verge
    "reach_m": 20.0,             # the edge only exists where the shore is within this of the road edge
    "wall": {"stem_m": 0.3, "coping_r_m": 0.19, "above_path_m": 0.35},   # kit LakeWall: stem 0.3, coping r 0.19, 0.35 above the path
    "rail": {"height_m": 1.05, "post_pitch_m": 2.0, "bar_pitch_m": 0.3, "bar_m": 0.025, "color": "#2F5D3A"},
    "seat_pitch_m": 4.2,         # os_13: long block seats in a regular row
    "seat_row": 6,               # seats a row, then a gap
    "seat_gap_m": 22.0,
    "cube_pitch_m": 1.5,         # os_14: cubes in small groups on the grass
    "cube_group": 3,
    "cube_every_m": 45.0,
    "stub_pitch_m": 1.4,         # os_13: rust stubs in a short row near the road
    "stub_row": 5,
    "stub_every_m": 48.0,
    "stub_scale_z": 0.6,         # os_13: knee-to-thigh height, not the 1.1 m slab
    "shrub_every_m": 14.0,
}
SHORE_CLEAR = 0.35               # the wall band (stem + coping overhang), from the shoreline
SAMPLE_M = 2.0
EPS = 1e-6


def cfg_of(edge: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in (edge or {}).items():
        if k.startswith("_") or k in ("pieces", "pieces_doc", "missing"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


@dataclass
class LakeEdge:
    """Per-layer polygons (world metres) plus the oriented lines the props and the sweeps follow."""
    cfg: dict
    layers: dict[str, BaseGeometry]            # kerb_line, paver, verge, path, tactile, wall (band), zone
    wall_lines: list[LineString] = field(default_factory=list)    # wall centre, land on the LEFT of travel
    length_m: float = 0.0                       # shoreline length that carries the wall

    @property
    def footprint(self) -> BaseGeometry:
        return ops.unary_union([self.layers[k] for k in ("kerb_line", "paver", "verge", "path", "tactile", "wall")
                                if not self.layers[k].is_empty])


def _clean(g: BaseGeometry, open_m: float = 0.0) -> BaseGeometry:
    if g.is_empty:
        return g
    if not g.is_valid:
        g = g.buffer(0)
    if open_m > 0:
        g = g.buffer(-open_m, join_style=2).buffer(open_m, join_style=2)
    return g


def _lines(g) -> list[LineString]:
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type in ("MultiLineString", "GeometryCollection"):
        return [x for p in g.geoms for x in _lines(p)]
    return []


def _merge(g) -> list[LineString]:
    ls = _lines(g)
    if not ls:
        return []
    m = ops.linemerge(MultiLineString(ls)) if len(ls) > 1 else ls[0]
    return _lines(m)


def _tangent(line: LineString, d: float, h: float = 0.6) -> tuple[float, float]:
    a, b = line.interpolate(max(0.0, d - h)), line.interpolate(min(line.length, d + h))
    ln = math.hypot(b.x - a.x, b.y - a.y) or 1.0
    return (b.x - a.x) / ln, (b.y - a.y) / ln


def _median(flags: list[bool], k: int = 2) -> list[bool]:
    n = len(flags)
    return [sum(flags[max(0, i - k):i + k + 1]) * 2 > len(flags[max(0, i - k):i + k + 1]) for i in range(n)]


def reach_zone(lay, roads, reach: float) -> BaseGeometry:
    """The land beside the lake-side roads that belongs to the edge: per 2 m sample and per side, a slab from the road
    edge outward where the nearest water lies that way and within `reach` (the other side of a causeway and the far
    side of the road drop out), unioned. Short flickers at the margin are filtered so the ends are clean."""
    lake = lay.lake
    quads = []
    for r in roads:
        line, w = r.line, r.width
        n = max(1, int(line.length // SAMPLE_M))
        d_at = [i * line.length / n for i in range(n + 1)]
        for side in (-1.0, 1.0):
            ok = []
            for d in d_at:
                tx, ty = _tangent(line, d)
                c = line.interpolate(d)
                nx, ny = -ty * side, tx * side
                e = Point(c.x + nx * (w / 2 + 0.05), c.y + ny * (w / 2 + 0.05))
                dist = lake.distance(e)
                if dist > reach or dist <= EPS:
                    ok.append(False)
                    continue
                q = ops.nearest_points(lake, e)[0]
                ok.append(((q.x - e.x) * nx + (q.y - e.y) * ny) / dist > 0.3)
            ok = _median(_median(ok))
            for i in range(n):
                if not (ok[i] or ok[i + 1]):
                    continue
                pts = []
                for d in (d_at[i] - 0.05, d_at[i + 1] + 0.05):
                    d = min(max(d, 0.0), line.length)
                    tx, ty = _tangent(line, d)
                    c = line.interpolate(d)
                    nx, ny = -ty * side, tx * side
                    pts.append(((c.x + nx * (w / 2 - 0.2), c.y + ny * (w / 2 - 0.2)), (c.x + nx * (w / 2 + reach), c.y + ny * (w / 2 + reach))))
                (a0, a1), (b0, b1) = pts
                quads.append(Polygon([a0, a1, b1, b0]).buffer(0))
    return _clean(ops.unary_union(quads).buffer(0.05)) if quads else Polygon()


def build(lay, names, edge_cfg: dict) -> LakeEdge | None:
    """Generate the layers for every road in `names` (see the module doc). None when no lake is within reach."""
    cfg = cfg_of(edge_cfg)
    roads = [r for r in lay.roads if r.name in set(names)]
    lake = lay.lake
    if not roads or lake.is_empty:
        return None
    reach = float(cfg["reach_m"])
    zone = reach_zone(lay, roads, reach)
    if zone.is_empty:
        return None
    road_u = ops.unary_union([lay.road_area, lay.junctions]) if not lay.junctions.is_empty else lay.road_area
    blds = [b.footprint.buffer(0.6) for b in lay.buildings]
    solid = ops.unary_union([road_u] + blds) if blds else road_u
    shore = lake.buffer(SHORE_CLEAR)
    land = _clean(zone.difference(solid).difference(shore))
    paver_m, path_m = float(cfg["paver_strip_m"]), float(cfg["walking_path_m"])
    kerb = _clean(land.intersection(road_u.buffer(float(cfg["kerb_line_m"]))), 0.03)
    paver_all = land.intersection(road_u.buffer(paver_m))
    paver = _clean(paver_all.difference(kerb), 0.05)
    # the path sits on the shore side; a path narrower than 1.5 m is dropped (its ground joins the verge)
    path_all = land.intersection(lake.buffer(SHORE_CLEAR + path_m)).difference(paver_all)
    path = _clean(path_all, 0.75)
    tactile = Polygon()
    if not path.is_empty and float(cfg["tactile_m"]) > 0:
        mid = SHORE_CLEAR + path_m * 0.5
        half = float(cfg["tactile_m"]) / 2
        tactile = _clean(path.intersection(lake.buffer(mid + half)).difference(lake.buffer(mid - half)), 0.05)
        path = _clean(path.difference(tactile))
    verge = _clean(land.difference(paver_all).difference(path).difference(tactile), 0.15)
    wall = _clean(zone.difference(solid).intersection(shore).difference(lake))
    lines = []
    for ln in _merge(lake.buffer(float(cfg["wall"]["stem_m"]) / 2 + 0.02).boundary.intersection(zone.difference(solid))):
        if ln.length < 1.0:
            continue
        ln = ln.simplify(0.02)
        # orient so that the land is on the left of travel
        mid = ln.interpolate(ln.length / 2)
        tx, ty = _tangent(ln, ln.length / 2)
        left = Point(mid.x - ty * 1.0, mid.y + tx * 1.0)
        right = Point(mid.x + ty * 1.0, mid.y - tx * 1.0)
        lines.append(ln if lake.distance(left) > lake.distance(right) else LineString(list(ln.coords)[::-1]))
    layers = {"kerb_line": kerb, "paver": paver, "verge": verge, "path": path, "tactile": tactile, "wall": wall, "zone": zone}
    return LakeEdge(cfg, layers, lines, sum(x.length for x in lines))


# ---- mesh -------------------------------------------------------------------------------------------------------

def _cut_lines(g, cbox) -> list[LineString]:
    return [x for x in _lines(g.intersection(cbox)) if x.length > 0.05]


def sweep(m: MeshData, pts: list[tuple[float, float]], profile: list[tuple[float, float]], z_of, origin, material: str,
          uv_tile: tuple[float, float], color=None, uv_v: float | None = None) -> None:
    """Sweep a cross-section along a polyline. `profile` is [(u, dz)]: u metres to the LEFT of travel, dz above `z_of(x, y)`.
    Faces are wound so the outside faces away from the profile's inside when the profile runs from the right side up
    over the top and down the left side (the lake wall runs lake side -> coping -> land side)."""
    ox, oy = origin
    n = len(pts)
    if n < 2:
        return
    rings = []
    along = [0.0]
    for i in range(1, n):
        along.append(along[-1] + math.dist(pts[i - 1], pts[i]))
    for i, (x, y) in enumerate(pts):
        a, b = pts[max(0, i - 1)], pts[min(n - 1, i + 1)]
        ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        tx, ty = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
        # miter: scale the offset by 1/cos(half turn), capped
        if 0 < i < n - 1:
            p, q = pts[i - 1], pts[i + 1]
            l1, l2 = math.dist(p, pts[i]) or 1.0, math.dist(pts[i], q) or 1.0
            d1, d2 = ((pts[i][0] - p[0]) / l1, (pts[i][1] - p[1]) / l1), ((q[0] - pts[i][0]) / l2, (q[1] - pts[i][1]) / l2)
            cosh = max(0.5, math.sqrt(max(0.0, (1 + d1[0] * d2[0] + d1[1] * d2[1]) / 2)))
        else:
            cosh = 1.0
        nx, ny = -ty / cosh, tx / cosh
        z0 = z_of(x, y)
        rings.append([(x + nx * u - ox, y + ny * u - oy, z0 + dz) for u, dz in profile])
    tu, tv = uv_tile
    for i in range(n - 1):
        for j in range(len(profile) - 1):
            a, b = rings[i][j], rings[i + 1][j]
            c, d = rings[i + 1][j + 1], rings[i][j + 1]
            vj = (uv_v if uv_v is not None else profile[j][1] / tv)
            vj1 = (uv_v if uv_v is not None else profile[j + 1][1] / tv)
            u0, u1 = (0.5, 0.5) if uv_v is not None else (along[i] / tu, along[i + 1] / tu)
            m.add_face([a, b, c, d], [(u0, vj), (u1, vj), (u1, vj1), (u0, vj1)], material, color=color)


def wall_profile(cfg: dict, z_bottom_lake: float, z_bottom_land: float, top: float) -> list[tuple[float, float]]:
    """Cross-section (u to the left = land, dz above the datum) from the lake-side foot over the half-round coping to the
    land-side foot. `top` is the coping crown above the datum."""
    w = cfg["wall"]
    s, r = w["stem_m"] / 2, w["coping_r_m"]
    zs = top - r
    pts = [(-s, z_bottom_lake), (-s, zs), (-r, zs)]
    for a in (150, 120, 90, 60, 30):
        pts.append((r * math.cos(math.radians(a)), zs + r * math.sin(math.radians(a))))
    pts += [(r, zs), (s, zs), (s, z_bottom_land)]
    return pts


def build_mesh(le: LakeEdge, lay, cbox: BaseGeometry, origin) -> MeshData:
    """The edge layers inside `cbox`, coordinates relative to `origin`: surfaces at the plot datum (the layers are carved
    out of the other ground by `cells.build_cells`, so nothing overlaps), the path on a low step with risers, the swept
    wall and the railing. Materials: paver, lawn, street trim (yellow), concrete, facade trim (rail paint)."""
    from . import cells  # local: cells imports this module's output via the layout, not the reverse

    h, terr = lay.heights, lay.terrain
    cfg = le.cfg
    m = MeshData()
    ox, oy = origin

    def cut(g):
        return cells.clean(g.intersection(cbox)) if not g.is_empty else g

    yv = sum(M.TRIM_YELLOW) / 2
    cells.tri_ground(m, cut(le.layers["paver"]), origin, h.plot, terr, cells.planar(M.HERRINGBONE_PAVER), M.HERRINGBONE_PAVER)
    cells.tri_ground(m, cut(le.layers["kerb_line"]), origin, h.plot, terr, lambda x, y: (x / 4.0, yv), M.STREET_TRIM)
    cells.tri_ground(m, cut(le.layers["verge"]), origin, h.plot, terr, cells.planar(M.LAWN), M.LAWN)
    step = float(cfg["path_step_m"])
    path_top = h.plot + step
    cells.tri_ground(m, cut(le.layers["path"]), origin, path_top, terr, cells.planar(M.CONCRETE), M.CONCRETE)
    cells.tri_ground(m, cut(le.layers["tactile"]), origin, path_top, terr, lambda x, y: (x / 4.0, yv), M.STREET_TRIM)
    # risers around the path (and tactile) wherever it does not meet the wall
    both = _clean(ops.unary_union([le.layers["path"], le.layers["tactile"]]))
    if not both.is_empty:
        wall_near = le.layers["wall"].buffer(0.15)
        segs = []
        for poly in cells._polys(both):
            poly = Polygon(poly.exterior.coords, [i.coords for i in poly.interiors])
            from shapely.geometry.polygon import orient
            poly = orient(poly, 1.0)
            for ring in [poly.exterior] + list(poly.interiors):
                cs = list(ring.coords)
                for a, b in zip(cs, cs[1:]):
                    if math.dist(a, b) < 0.05 or wall_near.contains(Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)):
                        continue
                    za, zb = h.plot + terr.dz(*a), h.plot + terr.dz(*b)
                    segs.append(cells.WallSeg(b, a, zb, za, path_top, "lake_path"))   # reversed: faces the right of travel = outward
        cells.wall_quads(m, segs, cells.grid.cell_of(ox + 64.0, oy + 64.0), origin, lambda w: M.CONCRETE)
    # wall and railing swept along the shoreline
    w = cfg["wall"]
    rail = cfg["rail"]
    z_of = lambda x, y: h.plot + terr.dz(x, y)   # noqa: E731
    top = step + float(w["above_path_m"])
    prof = wall_profile(cfg, h.lake - 0.3 - h.plot, step - 0.06, top)
    green = hex_rgb(rail["color"])
    for ln in le.wall_lines:
        for piece in _cut_lines(ln, cbox):
            pts = _resample(piece, 2.5)
            sweep(m, pts, prof, z_of, origin, M.CONCRETE, M.tile(M.CONCRETE))
            if rail:
                _rail(m, pts, ln, cbox, z_of, origin, top, rail, green)
    return m


def _resample(line: LineString, max_step: float) -> list[tuple[float, float]]:
    """Vertices of a line, subdivided to at most `max_step`, so a curve keeps its shape through the sweep."""
    out = []
    cs = list(line.coords)
    for (ax, ay), (bx, by) in zip(cs, cs[1:]):
        k = max(1, math.ceil(math.hypot(bx - ax, by - ay) / max_step))
        out += [(ax + (bx - ax) * i / k, ay + (by - ay) * i / k) for i in range(k)]
    out.append(cs[-1])
    return out


def _rail(m: MeshData, pts, whole: LineString, cbox, z_of, origin, wall_top: float, rail: dict, color) -> None:
    """Green-bar railing on the wall top: a top rail and a low rail swept along the line, posts and vertical bars at fixed
    arc-length pitch (positions come from the whole line, so a cell border never shifts them)."""
    ox, oy = origin
    hgt = float(rail["height_m"])
    mat = M.FACADE_TRIM
    uv = (0.5, 0.62)
    for z0, z1, hw in ((hgt - 0.06, hgt, 0.03), (0.10, 0.14, 0.025)):
        prof = [(-hw, wall_top + z0), (-hw, wall_top + z1), (hw, wall_top + z1), (hw, wall_top + z0)]
        sweep(m, pts, prof, z_of, origin, mat, (1.0, 1.0), color=color, uv_v=0.62)
    post_pitch, bar_pitch, bar = float(rail["post_pitch_m"]), float(rail["bar_pitch_m"]), float(rail["bar_m"])
    s = 0.0
    from . import grid
    cell = grid.cell_of(origin[0] + 64.0, origin[1] + 64.0)
    while s <= whole.length + 1e-6:
        p = whole.interpolate(s)
        if grid.cell_of(p.x, p.y) == cell:
            tx, ty = _tangent(whole, s)
            is_post = abs((s / post_pitch) - round(s / post_pitch)) < 1e-6
            hw = 0.035 if is_post else bar / 2
            z0, z1 = (0.0, hgt) if is_post else (0.14, hgt - 0.06)
            ring = [(p.x + tx * a - ty * b - ox, p.y + ty * a + tx * b - oy) for a, b in ((-hw, -hw), (hw, -hw), (hw, hw), (-hw, hw))]
            z = z_of(p.x, p.y) + wall_top
            prism_ring(m, ring, z + z0, z + z1, mat, color=color, cap=is_post)
        s += bar_pitch
    del uv


# ---- props ------------------------------------------------------------------------------------------------------

def _hash(*v) -> float:
    h = 2166136261
    for x in v:
        h = ((h ^ (int(round(x * 7)) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return (h % 10000) / 10000.0


def iso_lines(le: LakeEdge, lay, dist: float, inside: BaseGeometry, source: str = "shore") -> list[LineString]:
    """Lines at `dist` from the shoreline (or from the road edge when source == "road") that lie inside `inside`, with
    the land on the left of travel for shore lines and the road on the right for road lines."""
    lake = lay.lake
    if source == "shore":
        base = lake.buffer(dist).boundary
        ref = lake
    else:
        road_u = ops.unary_union([lay.road_area, lay.junctions]) if not lay.junctions.is_empty else lay.road_area
        base = road_u.buffer(dist).boundary
        ref = road_u
    out = []
    for ln in _merge(base.intersection(inside)):
        if ln.length < 1.5:
            continue
        mid = ln.interpolate(ln.length / 2)
        tx, ty = _tangent(ln, ln.length / 2)
        left = Point(mid.x - ty, mid.y + tx)
        right = Point(mid.x + ty, mid.y - tx)
        near_left = ref.distance(left) < ref.distance(right)
        # shore: land on the left means the reference (water) is on the right -> flip when it is on the left
        out.append(LineString(list(ln.coords)[::-1]) if near_left else ln)
    return out


def _along(line: LineString, pitch: float, first: float, count: int, last_clear: float = 0.0):
    s = first
    for _ in range(count):
        if s + last_clear > line.length:
            return
        yield s
        s += pitch


def place_props(le: LakeEdge, lay, taken: list[tuple[float, float]], add, veg=None) -> dict:
    """Seats, slab stubs and verge shrubs along the edge. `add(piece, x, y, z, yaw, sz)` stores one instance; `taken`
    is the list of (x, y) already used (lamps, trees) and grows. Spacing rules are in DEFAULTS (agent shots)."""
    cfg = le.cfg
    h = lay.heights
    pieces = cfg.get("pieces", {})
    seat_a = cfg.get("block_seat_piece") or pieces.get("block_seat", "KIT_SF_BlockSeat_Concrete_A")
    seat_b = pieces.get("cube_seat", "KIT_SF_BlockSeat_Cube_B")
    stub = pieces.get("slab_marker", "KIT_SF_SlabMarker_Rust_A")
    cnt = {"block_seats": 0, "cube_seats": 0, "slab_stubs": 0, "shrubs": 0}
    path_m, paver_m = float(cfg["walking_path_m"]), float(cfg["paver_strip_m"])
    verge = le.layers["verge"]
    if verge.is_empty:
        return cnt

    def free(x, y, gap):
        return all((x - qx) ** 2 + (y - qy) ** 2 >= gap * gap for qx, qy in taken)

    def put(piece, x, y, yaw, sz=1.0, gap=0.6, key="", zoff=0.0):
        if not verge.contains(Point(x, y)) or not free(x, y, gap):
            return False
        add(piece, x, y, h.plot + zoff, yaw, sz)
        taken.append((x, y))
        cnt[key] += 1
        return True

    inner = verge.buffer(-0.55)
    # block seats: a row of six on the verge side of the path, then a gap (os_13); the long side runs along the path
    seat_d = SHORE_CLEAR + path_m + 0.75
    for li, ln in enumerate(iso_lines(le, lay, seat_d, inner)):
        row, gap = int(cfg["seat_row"]), float(cfg["seat_gap_m"])
        pitch = float(cfg["seat_pitch_m"])
        span = row * pitch + gap
        s0 = 3.0 + 7.0 * _hash(li, ln.length)
        s = s0
        while s + 1.6 < ln.length:
            k = int((s - s0) // pitch) % (row + int(gap // pitch) + 1)
            if k < row:
                a, b = ln.interpolate(s), ln.interpolate(s + 1.6)
                yaw = math.atan2(b.y - a.y, b.x - a.x)
                # the seat pivots at its start and is centred on the line; the piece's +x runs along the path
                put(seat_a, a.x, a.y, yaw, 1.0, 1.2, "block_seats")
            s += pitch
        del span
    # cube seats: groups of three nearer the middle of the verge (os_14)
    cube_d = SHORE_CLEAR + path_m + 1.6
    for li, ln in enumerate(iso_lines(le, lay, cube_d, verge.buffer(-0.5))):
        every, grp, pitch = float(cfg["cube_every_m"]), int(cfg["cube_group"]), float(cfg["cube_pitch_m"])
        s = 10.0 + 12.0 * _hash(li, 3.0, ln.length)
        while s + grp * pitch < ln.length:
            for j in range(grp):
                p = ln.interpolate(s + j * pitch + 0.25 * math.sin(j * 2.1))
                put(seat_b, p.x, p.y, 0.4 * math.sin(s + j), 1.0, 0.9, "cube_seats")
            s += every
    # rust slab stubs: a row of five parallel to the road, 1 m inside the paver strip (os_13), low
    stub_d = paver_m + 1.1
    for li, ln in enumerate(iso_lines(le, lay, stub_d, verge.buffer(-0.5), source="road")):
        every, row, pitch = float(cfg["stub_every_m"]), int(cfg["stub_row"]), float(cfg["stub_pitch_m"])
        s = 6.0 + 15.0 * _hash(li, 9.0, ln.length)
        while s + row * pitch < ln.length:
            for j in range(row):
                a = ln.interpolate(s + j * pitch)
                tx, ty = _tangent(ln, s + j * pitch)
                # the slab is 0.7 m long from its pivot: shift back half so it centres on the line
                put(stub, a.x - tx * 0.35, a.y - ty * 0.35, math.atan2(ty, tx), float(cfg["stub_scale_z"]), 0.6, "slab_stubs")
            s += every
    # verge shrubs: small ixora clumps just inside the paver strip, between the slab rows (os_13 bush by the stubs)
    if veg is not None:
        for li, ln in enumerate(iso_lines(le, lay, paver_m + 0.9, verge.buffer(-0.5), source="road")):
            s = 3.0
            while s < ln.length:
                a = ln.interpolate(s + 4.0 * _hash(li, s))
                if free(a.x, a.y, 4.0) and verge.contains(a):
                    add(veg, a.x, a.y, h.plot, 0.0, 1.0)
                    taken.append((a.x, a.y))
                    cnt["shrubs"] += 1
                s += float(cfg["shrub_every_m"])
    return cnt


def cost(le: LakeEdge, lay) -> dict:
    """Low-tier cost of the generated layers: triangles per 100 m of edge and draws (one per material); props excluded."""
    from shapely.geometry import box
    big = box(-1e6, -1e6, 1e6, 1e6)
    m = build_mesh(le, lay, big, (0.0, 0.0))
    per_mat: dict[str, int] = {}
    for f, mi in zip(m.faces, m.mats):
        per_mat[m.materials[mi]] = per_mat.get(m.materials[mi], 0) + len(f) - 2
    length = max(le.length_m, 1.0)
    return {"tris": m.tris, "tris_per_100m": round(m.tris * 100.0 / length), "draws": len(per_mat), "by_material": per_mat,
            "edge_length_m": round(length, 1)}
