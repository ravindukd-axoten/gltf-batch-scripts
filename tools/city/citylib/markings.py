"""Road markings and kerbside spawn points for the Delta Face area_strip (docs/research/Delta Face Street Catalogue.md
§2 and §9). Pure Shapely, no Blender: build() returns flat decal quads (world metres, UVs into the street trim's paint
rows or the road-paint atlas) and spawn points; citylib/cells.py turns the quads into faces 1 cm above the surface.

What it draws, all driven by `cfg["markings"]` and the layout:
- per-piece line style (piece_styles): the centre line where two carriageways of a road meet (no median), the inboard
  edge lines dropped, a solid yellow line 0.3 m off the sea-side kerb; cells.road_markings applies it to the strips;
- lane legends "CITYHUB" / "WELLAWATTA" (by direction of travel) and "A2" near the north end, every ~150 m per lane;
- ahead / turn arrows, stop lines (signals) and dashed give-way lines (roundabout) on approaches to junctions;
- hatched gores on the inboard side of roundabout approaches;
- a yellow bus-bay box and "BUS" at each bus shelter; the white ring line round each roundabout island;
- angled 60 degree parking bays on the car-park apron, plus parked-vehicle spawn points for the car park, the tuk rank
  (south end, sea-side kerb) and the van line (north end, sea-side kerb). No cars are baked.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from . import materials as M
from . import osm, paint_atlas, rules
from .layout import _line, _polys, fit_circle

TRIM = M.STREET_TRIM
PAINT = M.ROAD_PAINT


@dataclass
class Quad:
    pts: list          # 4 (x, y) corners, counter-clockwise seen from above
    uvs: list          # 4 (u, v)
    mat: str           # M.STREET_TRIM or M.ROAD_PAINT
    kind: str          # legend, arrow, stop, giveway, ring, gore, bus_bay, bus_text, bay
    level: str = "road"   # "road" (carriageway) or "plot" (car-park apron)

    @property
    def centre(self) -> tuple[float, float]:
        return (sum(p[0] for p in self.pts) / 4.0, sum(p[1] for p in self.pts) / 4.0)


@dataclass
class PieceStyle:
    """Edge-line style of one road piece, sides in the piece's own line frame (+1 = left of line direction)."""
    skip_edges: set = field(default_factory=set)
    yellow_edges: set = field(default_factory=set)
    centre: int = 0     # +-1: draw the solid white centre line on this edge, 0 none
    double_centre: bool = False   # a plain double solid centre line instead of the dashed one (config double_centre_roads)
    kerbside: dict = field(default_factory=dict)  # side -> metres: edge line moved in by a kerbside strip (P117)
    hatch: float = 0.0  # CIRCLE fix 2: metres of hatched centre median on a two-way piece (04_wide), 0 none
    yellow_gap: object = None  # CIRCLE fix 4: area (parking bays) where a yellow kerb line is drawn white instead
    median: float = 0.0  # CIRCLE fix 5: metres of median zone shared by a pair (half on each piece's inboard side)
    median_skip: object = None  # CIRCLE fix 5: area (islands, gaps between them) with no median line paint


def lane_offsets(width: float, style: PieceStyle | None) -> tuple[list[float], float, float]:
    """(lane centre offsets, lo, hi) in the piece's line frame (+ = left): lanes laid between the outer edge line
    (0.3 m in from the kerb) and the median line when the piece has a median zone (CIRCLE fix 5), else across the
    whole width as before."""
    from .cells import lane_count
    if style is not None and style.median > 0.0 and len(style.skip_edges) == 1:
        sd = next(iter(style.skip_edges))
        med, outer = sd * (width / 2 - style.median / 2), -sd * (width / 2 - 0.3)
        lo, hi = min(med, outer), max(med, outer)
        n = lane_count(hi - lo)
        return [lo + (hi - lo) * (k + 0.5) / n for k in range(n)], lo, hi
    n = lane_count(width)
    return [-width / 2 + width * (k + 0.5) / n for k in range(n)], -width / 2, width / 2


@dataclass
class Markings:
    quads: list = field(default_factory=list)
    styles: dict = field(default_factory=dict)     # id(piece) -> PieceStyle
    spawns: list = field(default_factory=list)     # {"kind", "group", "x", "y", "yaw_deg"}
    stats: dict = field(default_factory=dict)


# --- small geometry helpers -------------------------------------------------------------------

def at(line: LineString, s: float, off: float = 0.0) -> tuple[float, float]:
    """Point at arc length s, `off` metres to the left of the line's direction (negative = right)."""
    s = max(0.0, min(line.length, s))
    p = line.interpolate(s)
    a, b = line.interpolate(max(0.0, s - 0.5)), line.interpolate(min(line.length, s + 0.5))
    tx, ty = b.x - a.x, b.y - a.y
    tl = math.hypot(tx, ty) or 1.0
    return p.x - ty / tl * off, p.y + tx / tl * off


def tangent(line: LineString, s: float) -> tuple[float, float]:
    a, b = line.interpolate(max(0.0, s - 0.5)), line.interpolate(min(line.length, s + 0.5))
    tx, ty = b.x - a.x, b.y - a.y
    tl = math.hypot(tx, ty) or 1.0
    return tx / tl, ty / tl


def oriented_quad(cx, cy, fwd, length, width, rect, mat, kind, level="road") -> Quad:
    """Decal centred at (cx, cy): v (rect's v range) along `fwd`, u across to the right of `fwd`."""
    fx, fy = fwd
    rx, ry = fy, -fx
    hl, hw = length / 2.0, width / 2.0
    u0, v0, u1, v1 = rect
    pts = [(cx - fx * hl - rx * hw, cy - fy * hl - ry * hw), (cx - fx * hl + rx * hw, cy - fy * hl + ry * hw),
           (cx + fx * hl + rx * hw, cy + fy * hl + ry * hw), (cx + fx * hl - rx * hw, cy + fy * hl - ry * hw)]
    return Quad(pts, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], mat, kind, level)


def stroke(a, b, half_w, row, kind, level="road", u0=0.0) -> Quad | None:
    """A paint strip from a to b on a street-trim paint row (4 m of paint per u unit)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    dl = math.hypot(dx, dy)
    if dl < 0.05:
        return None
    nx, ny = -dy / dl, dx / dl
    r0, r1 = row
    return Quad([(a[0] - nx * half_w, a[1] - ny * half_w), (b[0] - nx * half_w, b[1] - ny * half_w),
                 (b[0] + nx * half_w, b[1] + ny * half_w), (a[0] + nx * half_w, a[1] + ny * half_w)],
                [(u0, r0), (u0 + dl / 4.0, r0), (u0 + dl / 4.0, r1), (u0, r1)], TRIM, kind, level)


# --- road pieces: travel direction, partner carriageway, junction approaches ------------------------

class PieceInfo:
    def __init__(self, piece, tsign: int, oneway: bool):
        self.piece = piece
        self.tsign = tsign
        self.oneway = oneway
        ln = piece.line
        self.tline = ln if tsign > 0 else LineString(list(ln.coords)[::-1])
        self.inboard = 0      # side (line frame) facing the partner carriageway, 0 = none
        self.seaward = False  # the carriageway nearer the sea of a pair

    @property
    def lanes(self) -> int:
        from .cells import lane_count
        return lane_count(self.piece.width)


def _piece_infos(cfg, data, lay, tm) -> list[PieceInfo]:
    ow = []
    for w in osm.lines(data, lambda t: rules.is_carriageway(t) and t.get("oneway") in ("yes", "1", "-1")
                       or t.get("junction") in ("roundabout", "circular")):
        ln = _line(data, w.node_ids, tm)
        if ln is not None:
            if w.tags.get("oneway") == "-1":
                ln = LineString(list(ln.coords)[::-1])
            ow.append((w.tags.get("name", ""), ln))
    infos = []
    for r in lay.roads:
        mid = r.line.interpolate(0.5, normalized=True)
        best = None
        for name, ln in ow:
            if name != r.name:
                continue
            d = ln.distance(mid)
            if d < 3.5 and (best is None or d < best[0]):
                best = (d, ln)
        if best is None:
            infos.append(PieceInfo(r, 1, False))
            continue
        ln = best[1]
        s = ln.project(mid)
        t1 = tangent(ln, s)
        t2 = tangent(r.line, r.line.project(mid))
        infos.append(PieceInfo(r, 1 if t1[0] * t2[0] + t1[1] * t2[1] >= 0 else -1, True))
    return infos


def _pair_up(infos: list[PieceInfo], lay, centre_roads: set) -> None:
    for a in infos:
        r = a.piece
        if r.name not in centre_roads or r.line.length < 30:
            continue
        best = None
        for b in infos:
            if b is a or b.piece.name != r.name or b.piece.line.length < 30:
                continue
            d = b.piece.line.distance(r.line.interpolate(0.5, normalized=True))
            if d < r.width + 2.0 and (best is None or d < best[0]):
                best = (d, b)
        if best is None:
            continue
        b = best[1]
        mid = r.line.interpolate(0.5, normalized=True)
        s = r.line.project(mid)
        t = tangent(r.line, s)
        q = b.piece.line.interpolate(b.piece.line.project(mid))
        cross = t[0] * (q.y - mid.y) - t[1] * (q.x - mid.x)
        a.inboard = 1 if cross > 0 else -1
        da = lay.coast.distance(mid) if lay.coast is not None else 0.0
        db = lay.coast.distance(q) if lay.coast is not None else 0.0
        a.seaward = da < db


def piece_styles(infos: list[PieceInfo], yellow_roads: set, kerbside_land: dict | None = None,
                 hatch_roads: dict | None = None, kerb_yellow_roads: set | None = None,
                 median_roads: dict | None = None, double_roads: frozenset = frozenset()) -> dict:
    """kerbside_land {road name: m} (P117, measured_values centre_road.sb_carriageway_m): the landward carriageway of
    a pair keeps a kerbside strip that wide between its outboard edge line and the kerb; lanes share the rest."""
    kerbside_land = kerbside_land or {}
    hatch_roads = hatch_roads or {}
    styles: dict = {}
    done_pair: set = set()
    for a in infos:
        st = PieceStyle()
        if a.inboard:
            st.skip_edges.add(a.inboard)
            key = frozenset((id(a), id(_partner(infos, a))))
            if key not in done_pair and a.seaward:
                done_pair.add(key)
                st.centre = a.inboard
        if a.piece.name in yellow_roads and a.inboard and a.seaward:
            st.yellow_edges.add(-a.inboard)
        st.double_centre = a.piece.name in double_roads
        if a.piece.name in kerbside_land and a.inboard and not a.seaward:
            st.kerbside[-a.inboard] = float(kerbside_land[a.piece.name])
        if a.piece.name in hatch_roads and not a.inboard and not a.oneway:
            st.hatch = float(hatch_roads[a.piece.name])
        if a.piece.name in (kerb_yellow_roads or ()):
            # CIRCLE fix 4 (sv_15): a solid yellow no-parking line along every outer kerb (both sides of a two-way
            # road, the outboard side of each carriageway of a pair)
            st.yellow_edges |= {-a.inboard} if a.inboard else {-1, 1}
        if a.piece.name in (median_roads or {}) and a.inboard:
            st.median = float(median_roads[a.piece.name])   # CIRCLE fix 5: two median lines, no centre line
            st.centre = 0
        styles[id(a.piece)] = st
    return styles


def _partner(infos, a):
    r = a.piece
    mid = r.line.interpolate(0.5, normalized=True)
    best = None
    for b in infos:
        if b is a or b.piece.name != r.name or b.piece.line.length < 30:
            continue
        d = b.piece.line.distance(mid)
        if d < r.width + 2.0 and (best is None or d < best[0]):
            best = (d, b)
    return best[1] if best else a


# --- the build ----------------------------------------------------------------------------------

def build(cfg: dict, data, lay, dressing=None, tm=None) -> Markings:
    from . import geo
    tm = tm or geo.CITYHUB
    mc = cfg.get("markings", {})
    out = Markings()
    if not mc:
        return out
    centre_roads = {n for n, rule in cfg.get("dual_carriageways", {}).items() if rule.get("centre_line")}
    yellow_roads = set(mc.get("yellow_edge_roads", []))
    infos = _piece_infos(cfg, data, lay, tm)
    _pair_up(infos, lay, centre_roads)
    out.styles = piece_styles(infos, yellow_roads, mc.get("kerbside_land_m", {}), mc.get("centre_hatch_m", {}),
                              set(mc.get("kerb_yellow_roads", [])), mc.get("centre_median_m", {}), set(mc.get("double_centre_roads", [])))
    skip_g = unary_union([g for g in (getattr(lay, "medians", None), getattr(lay, "median_gaps", None))
                          if g is not None and not g.is_empty] or [Polygon()])
    if not skip_g.is_empty:
        from shapely.prepared import prep
        skip = prep(skip_g.buffer(0.4))
        for st in out.styles.values():
            if st.median > 0.0:
                st.median_skip = skip
    gap_m = float(mc.get("yellow_gap_parking_m", 0.0))
    bays_area = unary_union([lay.parking, getattr(lay, "parking_lane", Polygon())])
    if gap_m > 0.0 and not bays_area.is_empty:
        # CIRCLE fix 4 (critic round 4, s7 vs sv_08): no yellow no-parking line beside the parking bays; the kerb
        # line there is white (the bays are a parking lane of the road)
        from shapely.prepared import prep
        gap = prep(bays_area.buffer(gap_m))
        for st in out.styles.values():
            if st.yellow_edges:
                st.yellow_gap = gap

    road_ok = lay.road_area.buffer(0.1)
    junc = lay.junctions.buffer(1.5)
    road_area = lay.road_area
    quads: list[Quad] = []
    counts: dict[str, int] = {}

    def add(q, ok_poly=road_ok, plot_ok=None):
        if q is None:
            return
        if q.level == "plot":
            if plot_ok is None or not plot_ok.contains(Polygon(q.pts)):
                return
        elif not ok_poly.contains(Polygon(q.pts)):
            return
        quads.append(q)
        counts[q.kind] = counts.get(q.kind, 0) + 1

    # roundabouts: fitted centre and radius
    rounds = []
    for name in mc.get("roundabouts", []):
        ways = osm.lines(data, lambda t, n=name: t.get("junction") in ("roundabout", "circular") and t.get("name") == n)
        pts = [tm.forward(*c) for w in ways for c in data.coords(w.node_ids)]
        if len(pts) >= 5:
            cx, cy, rad = fit_circle(pts)
            width = max(rules.road_width(w.tags) for w in ways)
            rounds.append({"name": name, "x": cx, "y": cy, "r": rad, "w": width})
    out.stats["roundabouts"] = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()} for r in rounds]
    for rb in rounds:
        # white ring line ~1.5 m outside the island edge (island edge = centreline radius - half the carriageway)
        rr = rb["r"] - rb["w"] / 2 + float(mc.get("ring_gap_m", 1.5))
        n = 48
        for k in range(n):
            a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
            add(stroke((rb["x"] + rr * math.cos(a0), rb["y"] + rr * math.sin(a0)),
                       (rb["x"] + rr * math.cos(a1), rb["y"] + rr * math.sin(a1)), 0.08, M.TRIM_WHITE, "ring"),
                ok_poly=road_area.buffer(0.1))

    # approaches, legends
    legend_cfg = mc.get("legends", {})
    spacing = float(legend_cfg.get("spacing_m", 150.0))
    a2_from_end = float(legend_cfg.get("a2_from_north_end_m", 330.0))
    sig_min = float(cfg.get("dressing", {}).get("signal_junction_min_m2", 250.0))
    sig_polys = [p for p in _polys(lay.junctions) if p.area >= sig_min and lay.area_strip.contains(p.centroid)
                 and not any(math.hypot(p.centroid.x - r["x"], p.centroid.y - r["y"]) < r["r"] + 20 for r in rounds)]
    legend_log = []
    stop_log = []
    for inf in infos:
        r = inf.piece
        L = inf.tline.length
        if L < 25 or r.width < 6.0:
            continue
        offs, _, _ = lane_offsets(r.width, out.styles.get(id(r)))
        n = len(offs)
        lane_off = [o * inf.tsign for o in offs][::inf.tsign]   # tline frame, + left; k = 0 is the rightmost lane
        ymax = max(p[1] for p in inf.tline.coords)
        # legends
        if r.name in legend_cfg.get("roads", []) and inf.oneway:
            for k, off in enumerate(lane_off):
                s = 70.0 + (spacing / n) * k
                while s < L - 40.0:
                    x, y = at(inf.tline, s, off)
                    fwd = tangent(inf.tline, s)
                    if fwd[1] > 0 and y > ymax - a2_from_end:
                        word = "A2"
                    else:
                        word = "CITYHUB" if fwd[1] > 0 else "WELLAWATTA"
                    w_, l_ = paint_atlas.SIZE_M[word]
                    if lay.junctions.distance(Point(x, y)) > 8.0:
                        q = oriented_quad(x, y, fwd, l_, w_, paint_atlas.uv_rect(word), PAINT, "legend")
                        before = len(quads)
                        add(q)
                        if len(quads) > before:
                            legend_log.append({"word": word, "lane": k, "x": round(x, 1), "y": round(y, 1), "s": round(s, 1),
                                               "piece": id(r)})
                    s += spacing
        # approach to a junction at the line's travel end
        end = Point(inf.tline.coords[-1])
        if not inf.oneway or lay.junctions.distance(end) > 1.0:
            continue
        s_e = L
        while s_e > 5 and not r.poly.buffer(0.3).contains(inf.tline.interpolate(s_e)):
            s_e -= 0.5
        s_stop = s_e - 0.8
        rb = next((rb for rb in rounds if math.hypot(end.x - rb["x"], end.y - rb["y"]) < rb["r"] + rb["w"] / 2 + 12.0), None)
        sig = next((p for p in sig_polys if p.distance(end) < 2.0), None)
        if rb is None and sig is None:
            continue
        # stop line (signal) or dashed give-way line (roundabout), across the whole carriageway
        half = r.width / 2 - 0.05
        a, b = at(inf.tline, s_stop, -half), at(inf.tline, s_stop, half)
        if sig is not None and rb is None:
            add(stroke(a, b, 0.15, M.TRIM_ZEBRA, "stop"))
        else:
            segs = 12
            for k in range(segs):
                if k % 2:
                    continue
                pa = (a[0] + (b[0] - a[0]) * k / segs, a[1] + (b[1] - a[1]) * k / segs)
                pb = (a[0] + (b[0] - a[0]) * (k + 1) / segs, a[1] + (b[1] - a[1]) * (k + 1) / segs)
                add(stroke(pa, pb, 0.2, M.TRIM_ZEBRA, "giveway"))
        stop_log.append({"kind": "giveway" if rb else "stop", "x": round(a[0], 1), "y": round(a[1], 1), "piece": id(r)})
        # arrows: left lane turns left onto the roundabout / junction, the others ahead
        for k, off in enumerate(lane_off):
            name = "ARROW_STRAIGHT" if (n == 1 or k > 0) else "ARROW_LEFT"
            if k == 0 and n >= 3 and sig is not None:
                name = "ARROW_RIGHT"
            if k == n - 1 and n >= 2:
                name = "ARROW_LEFT" if k == n - 1 else name
            for ds in (8.0, 24.0):
                x, y = at(inf.tline, s_stop - ds, off)
                w_, l_ = paint_atlas.SIZE_M[name]
                add(oriented_quad(x, y, tangent(inf.tline, s_stop - ds), l_, w_, paint_atlas.uv_rect(name), PAINT, "arrow"))
        # hatched gore on the inboard side of a roundabout approach (a splitter island's painted twin)
        if rb is not None and inf.inboard:
            side = inf.inboard * inf.tsign          # tline frame
            edge = side * r.width / 2.0
            gw_max, s0, s1 = float(mc.get("gore_width_m", 2.0)), s_stop - 34.0, s_stop - 4.0
            gw = lambda s: gw_max * max(0.0, min(1.0, (s - s0) / (s1 - s0)))   # noqa: E731
            add(stroke(at(inf.tline, s0, edge), at(inf.tline, s1, edge - side * gw(s1)), 0.075, M.TRIM_WHITE, "gore"))
            add(stroke(at(inf.tline, s1, edge), at(inf.tline, s1, edge - side * gw(s1)), 0.075, M.TRIM_WHITE, "gore"))
            s = s0 + 3.0
            while s <= s1:
                add(stroke(at(inf.tline, s, edge), at(inf.tline, s - 2.2, edge - side * gw(s - 2.2)), 0.1, M.TRIM_WHITE, "gore"))
                s += 3.2
    out.stats["legends"] = legend_log
    out.stats["stop_lines"] = stop_log

    # CIRCLE fix 5: the raised median islands' painted white outline (aerial: white paint round the rounded ends)
    med = getattr(lay, "medians", None)
    if med is not None and not med.is_empty:
        for poly in _polys(med):
            cs = list(poly.buffer(0.1, quad_segs=4).exterior.coords)
            for a, b in zip(cs, cs[1:]):
                add(stroke(a, b, 0.06, M.TRIM_WHITE, "median"))

    # bus bays at the bus shelters the dressing placed
    bay_len = float(mc.get("bus_bay_length_m", 12.0))
    bay_w = float(mc.get("bus_bay_width_m", 2.5))
    buses = []
    for group, inst in (dressing.placements if dressing is not None else []):
        if inst.piece not in ("PROP_BusShelter_01", "PROP_BusShelter_Seafront_01", "PROP_BusShelter_Booth_01"):
            continue
        p = Point(inst.x, inst.y)
        cand = [(i.piece.poly.distance(p), i) for i in infos if i.piece.width >= 6.0]
        if not cand:
            continue
        d, inf = min(cand, key=lambda t: t[0])
        if d > 12.0:
            continue
        ln = inf.tline
        s = ln.project(p)
        q = ln.interpolate(s)
        t = tangent(ln, s)
        side = 1.0 if t[0] * (p.y - q.y) - t[1] * (p.x - q.x) > 0 else -1.0
        # kerb side at the shelter; the box needs the kerb to be that carriageway's outer edge
        edge = side * inf.piece.width / 2.0
        inner = edge - side * bay_w
        a0, a1 = s - bay_len / 2, s + bay_len / 2
        if a0 < 12 or a1 > ln.length - 12:
            continue
        before = len(quads)
        for pa, pb in ((at(ln, a0, inner), at(ln, a1, inner)), (at(ln, a0, edge), at(ln, a0, inner)),
                       (at(ln, a1, edge), at(ln, a1, inner))):
            add(stroke(pa, pb, 0.075, M.TRIM_YELLOW, "bus_bay"))
        w_, l_ = paint_atlas.SIZE_M["BUS"]
        x, y = at(ln, s, edge - side * bay_w / 2)
        add(oriented_quad(x, y, tangent(ln, s), l_, w_, paint_atlas.uv_rect("BUS"), PAINT, "bus_text"))
        if len(quads) > before:
            buses.append({"x": round(x, 1), "y": round(y, 1)})
    out.stats["bus_bays"] = buses

    # car park, tuk rank, van line
    _kerbside(mc, lay, infos, out, quads, counts)
    out.quads = quads
    out.stats["quads"] = counts
    return out


def _spawn(out, kind, group, x, y, fwd, extra=None):
    out.spawns.append({"kind": kind, "group": group, "x": round(x, 2), "y": round(y, 2),
                       "yaw_deg": round(math.degrees(math.atan2(fwd[0], fwd[1])) % 360.0, 1)})


def _sea_piece(infos, name):
    """The oneway carriageway of `name` that runs north on the sea side (the seaward partner)."""
    c = [i for i in infos if i.piece.name == name and i.seaward and i.tline.length > 100]
    return max(c, key=lambda i: i.tline.length) if c else None


def _lane_bays(cp, lane, ln, edge, sea_side, angle, bay_w, depth, pitch, near, out, quads, counts) -> int:
    """CIRCLE fix 5 (agent 2026-11-20, r5.centre_rd.parking_band_m / bay_angle_and_pitch): bays in the parking lane
    of the road. The kerb is the lane's outer edge; each bay line leans forward (travel direction and towards the
    kerb) at `angle`, its paint from mark_from_kerb_m to the bay depth off the kerb (the aerial's short marks), and a
    parked-vehicle spawn sits mid-bay, nose to the kerb. Returns the spawns placed."""
    from shapely.prepared import prep
    inside = prep(lane.buffer(0.05))
    mark0 = float(cp.get("mark_from_kerb_m", 0.0))
    bays, s, L = 0, 2.0, ln.length
    while s < L - 2.0:
        t = tangent(ln, s)
        o = 0.5
        if not inside.contains(Point(*at(ln, s, edge + sea_side * o))):
            s += pitch
            continue
        while o < 14.0 and inside.contains(Point(*at(ln, s, edge + sea_side * (o + 0.25)))):
            o += 0.25
        kerb = o - 0.05                                     # lane width beyond the carriageway edge here
        if kerb < depth - 0.5:
            s += pitch
            continue
        n = (-t[1] * sea_side, t[0] * sea_side)             # towards the kerb
        d = (t[0] * math.cos(angle) + n[0] * math.sin(angle), t[1] * math.cos(angle) + n[1] * math.sin(angle))
        o_in, o_out = kerb - depth, kerb - mark0
        a = at(ln, s, edge + sea_side * o_in)
        run = (o_out - o_in) / math.sin(angle)
        b = (a[0] + d[0] * run, a[1] + d[1] * run)
        if inside.contains(Point(*b)):
            q = stroke(a, b, 0.06, M.TRIM_WHITE, "bay")
            if q is not None:
                quads.append(q)
                counts["bay"] = counts.get("bay", 0) + 1
            if near is None or math.hypot(a[0] - near[0], a[1] - near[1]) < float(cp.get("near_radius_m", 100.0)):
                half = depth / 2 / math.sin(angle)          # mid-depth along the bay line, then half a pitch on
                cx, cy = a[0] + d[0] * half + t[0] * pitch / 2, a[1] + d[1] * half + t[1] * pitch / 2
                _spawn(out, "parked_vehicle", "car_park", cx, cy, d)
                bays += 1
        s += pitch
    return bays


def _kerbside(mc, lay, infos, out, quads, counts):
    cp = mc.get("car_park", {})
    inf = _sea_piece(infos, cp.get("road", ""))
    if inf is None:
        return
    ln = inf.tline
    L = ln.length
    sea_side = 1.0 if lay.coast is not None and lay.coast.distance(Point(*at(ln, L / 2, 8.0))) < \
        lay.coast.distance(Point(*at(ln, L / 2, -8.0))) else -1.0
    edge = sea_side * inf.piece.width / 2.0
    # angled bays on the apron (lay.parking) beside the sea-side kerb
    angle = math.radians(float(cp.get("angle_deg", 60.0)))
    bay_w = float(cp.get("bay_width_m", 2.5))
    depth = float(cp.get("bay_length_m", 5.0))
    pitch = bay_w / math.sin(angle)
    lane = getattr(lay, "parking_lane", None)
    near = cp.get("near")
    bays = 0
    if cp.get("lane") and lane is not None and not lane.is_empty:
        bays = _lane_bays(cp, lane, ln, edge, sea_side, angle, bay_w, depth, pitch, near, out, quads, counts)
    park = lay.parking.buffer(0.1)
    s = 4.0
    while s < L - 4.0 and not (cp.get("lane") and lane is not None and not lane.is_empty):
        t = tangent(ln, s)
        kx = ky = None
        o = 0.3
        while o < 8.0:                                       # the apron starts where the car-park surface does
            kx, ky = at(ln, s, edge + sea_side * o)
            if park.contains(Point(kx, ky)):
                break
            o += 0.25
        else:
            s += pitch
            continue
        n = (-t[1] * sea_side, t[0] * sea_side)             # away from the road, towards the apron
        d = (t[0] * math.cos(angle) + n[0] * math.sin(angle), t[1] * math.cos(angle) + n[1] * math.sin(angle))
        far = (kx + d[0] * depth, ky + d[1] * depth)
        if park.contains(Point(kx, ky)) and park.contains(Point(*far)):
            # the bay lines run the whole apron beside the Green (config roadside_strips); parked vehicles
            # (spawn data) only fill the bays near the car park
            q = stroke((kx, ky), far, 0.06, M.TRIM_WHITE, "bay", "plot")
            if q is not None:
                quads.append(q)
                counts["bay"] = counts.get("bay", 0) + 1
                if near is None or math.hypot(kx - near[0], ky - near[1]) < float(cp.get("near_radius_m", 100.0)):
                    # a spawn point in the middle of the bay between this stroke and the next one
                    cx = kx + d[0] * depth * 0.55 + t[0] * pitch / 2
                    cy = ky + d[1] * depth * 0.55 + t[1] * pitch / 2
                    _spawn(out, "parked_vehicle", "car_park", cx, cy, d)
                    bays += 1
        s += pitch
    out.stats["car_park_bays"] = bays
    # CIRCLE fix 2 (sv_08): ahead arrows in the kerb lane beside the bays, so the car park reads from the road
    every = float(cp.get("aisle_arrow_every_m", 0.0))
    if every > 0.0 and near is not None:
        w_, l_ = paint_atlas.SIZE_M["ARROW_STRAIGHT"]
        s, n_arr = every / 2, 0
        while s < L - 4.0:
            x, y = at(ln, s, edge - sea_side * float(cp.get("aisle_arrow_in_m", 1.7)))
            if math.hypot(x - near[0], y - near[1]) < float(cp.get("near_radius_m", 100.0)):
                quads.append(oriented_quad(x, y, tangent(ln, s), l_, w_, paint_atlas.uv_rect("ARROW_STRAIGHT"), PAINT,
                                           "arrow"))
                n_arr += 1
            s += every
        counts["aisle_arrow"] = n_arr
    # tuk rank: south end, tuks angled into the sea-side kerb in the outer lane
    tr = mc.get("tuk_rank", {})
    n_tuk, start, step = int(tr.get("count", 8)), float(tr.get("start_s_m", 30.0)), float(tr.get("pitch_m", 3.2))
    for k in range(n_tuk):
        s = start + k * step
        x, y = at(ln, s, edge - sea_side * 1.2)
        t = tangent(ln, s)
        n = (-t[1] * sea_side, t[0] * sea_side)
        a = math.radians(60.0)
        _spawn(out, "parked_vehicle", "tuk_rank", x, y, (t[0] * math.cos(a) + n[0] * math.sin(a), t[1] * math.cos(a) + n[1] * math.sin(a)))
    # van line: north end, nose to tail along the sea-side kerb, outer lane
    vl = mc.get("van_line", {})
    n_van, back, step = int(vl.get("count", 8)), float(vl.get("end_back_m", 140.0)), float(vl.get("pitch_m", 6.5))
    for k in range(n_van):
        s = L - back + k * step
        x, y = at(ln, s, edge - sea_side * 1.5)
        _spawn(out, "parked_vehicle", "van_line", x, y, tangent(ln, s))
    out.stats["spawn_groups"] = {g: sum(1 for sp in out.spawns if sp["group"] == g) for g in ("car_park", "tuk_rank", "van_line")}
