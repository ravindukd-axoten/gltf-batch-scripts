"""Road edge kit placement (P117, WS-0339; P92b kit tools/city/road_edge_kit/KIT_RoadEdge_A.blend, its spec §1-§4).

Generic rules for every kerb the layout makes (config "road_edge"; nothing is placed by hand):
- Side of each kerb run, probed `probe_m` behind the kerb back: "sea" (the promenade / seaside paver strip, P92b
  agent 2026-11-19: red herringbone with a grey border course), "island" (road again within `island_m`: medians and
  traffic islands) or "land" (footways in front of plots and buildings: precast concrete, gf_21 / gf_23).
- Channel: a gully every `gully_every_m` (spec §1, catalogue "dark drain grates every ~20 m"), the first at half that
  so short runs get one; on land runs every `inlet_every`-th one is a kerb inlet instead. None within
  `crossing_clear_m` of a dropped crossing, none on runs shorter than `min_run_m` (corner fillets, island noses).
- Sea-side kerbs: a grey border course along the kerb back (`KIT_BorderCourse_Straight`, 2 m, stretched to fill each
  straight stretch exactly; pieces only where a stretch is at least 1 m, so tight curves keep the plain kerb).
- Crossings (ROADS network crossings): the kerb drops on both sides where the crossing meets it: ramp, `flush_m` of
  flush kerb, ramp up (spec "3-6 m flat"), only where the kerb turns less than `drop_max_turn_deg` over that length, and a crossover behind the whole length so no 0.13 m step is left
  (Paver on the sea side, Conc on land and islands). Tactile ridge band behind the flush length on roadside
  footways only (land): never on the Delta Face promenade, the seaside strip or a median refuge (P117 self-check:
  on a 2.5 m refuge the pads from one kerb landed on the far carriageway).
Kit convention: pivot at the kerb-face foot, the piece runs along local +X, road on local -Y. The layout's kerb walls
face left of p0 -> p1 (road on the left), so pieces run p1 -> p0.

Low-tier cost (LOD0 / LOD1 tris, one material MAT_RoadEdgeTrim_A, about 1.05 MB on Low, one draw call per cell when
batched): gully 64/2 and inlet 72/6 every 20 m (about 3.3 / 0.1 per metre of kerb); border course 24/3 per metre of
sea-side kerb; one crossing side (2 ramps + 3 flush + 5 crossovers + 2 tactile) about 500/90.
Deterministic: positions and hashes, never random(). Pure Python here; `apply` (Shapely) cuts the layout.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

GULLY, INLET = "KIT_Gutter_Gully", "KIT_Gutter_KerbInlet"
BORDER = "KIT_BorderCourse_Straight"
RAMP, FLUSH, RAMP_UP = "KIT_Kerb_Dropped_Ramp", "KIT_Kerb_Dropped_Flush", "KIT_Kerb_Dropped_RampUp"
TACTILE = "KIT_TactilePad_1200"
GROUP = "RoadEdge"
MATERIAL = "MAT_RoadEdgeTrim_A"

# local x length of each run piece (m), from the kit (validate_asset bounds)
LENGTH = {GULLY: 1.0, INLET: 1.0, BORDER: 2.0, RAMP: 1.0, FLUSH: 1.0, RAMP_UP: 1.0, TACTILE: 1.2}
for _k in ("Flat", "Flush", "SideDown", "SideUp"):
    for _m in ("Paver", "Conc"):
        LENGTH[f"KIT_Crossover_{_k}_{_m}"] = 1.0
PIECES = tuple(LENGTH)
# LOD0 triangles (P92b handoff, validate_asset): what the cell budget counts
TRIS = {GULLY: 64, INLET: 72, BORDER: 48, RAMP: 44, FLUSH: 44, RAMP_UP: 44, TACTILE: 60,
        **{f"KIT_Crossover_{k}_{m}": (16 if k in ("Flat", "Flush") else 24)
           for k in ("Flat", "Flush", "SideDown", "SideUp") for m in ("Paver", "Conc")}}
BLEND = __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "road_edge_kit", "KIT_RoadEdge_A.blend")

DEFAULTS = {
    "probe_m": 1.0, "island_m": 4.0, "gully_every_m": 20.0, "inlet_every": 3, "min_run_m": 6.0,
    "crossing_clear_m": 4.0, "crossing_reach_m": 14.0, "flush_m": 3, "crossover_depth_m": 1.235,
    "kerb_h_range": [0.12, 0.18], "border_min_m": 1.0, "drop_max_turn_deg": 10.0,
}


@dataclass
class Place:
    piece: str
    x: float
    y: float
    z: float
    rot: float
    sx: float = 1.0


@dataclass
class Result:
    places: list = field(default_factory=list)          # [Place]
    cuts: list = field(default_factory=list)            # [(kerb chain index, s0, s1)] kerb length removed (dropped)
    seg_sides: list = field(default_factory=list)       # side of each input segment
    zones: list = field(default_factory=list)           # [[(x, y)] * 4] paving cut behind each dropped kerb
    sides: dict = field(default_factory=dict)           # side -> metres of kerb
    counts: dict = field(default_factory=dict)


def chains(segs: list, sides: list | None = None) -> list[list]:
    """Kerb segments [(p0, p1, bottom, top)] in layout order -> runs of contiguous segments (p1 == next p0) of one
    side (sides[i] for segs[i]; a road-area ring runs past sea, land and islands, so it is split where that changes)."""
    out: list[list] = []
    last = None
    for k, s in enumerate(segs):
        sd = sides[k] if sides else None
        if out and math.dist(out[-1][-1][1], s[0]) < 1e-6 and sd == last:
            out[-1].append(s)
        else:
            out.append([s])
        last = sd
    return out


def seg_sides(segs: list, probe, min_run_m: float = 3.0) -> list[str]:
    """Side of each kerb segment, probed behind its midpoint; runs shorter than min_run_m take the side before them
    (a 1 m blip at a lay-by mouth does not start a new run)."""
    raw = []
    for p0, p1, _b, _t in segs:
        L = math.dist(p0, p1)
        if L < 1e-9:
            raw.append(raw[-1] if raw else "land")
            continue
        dx, dy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
        raw.append(probe((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, dy, -dx))
    out = list(raw)
    i = 0
    while i < len(out):
        j = i
        while j + 1 < len(out) and out[j + 1] == out[i] and math.dist(segs[j][1], segs[j + 1][0]) < 1e-6:
            j += 1
        run = sum(math.dist(segs[k][0], segs[k][1]) for k in range(i, j + 1))
        if i > 0 and run < min_run_m and math.dist(segs[i - 1][1], segs[i][0]) < 1e-6:
            for k in range(i, j + 1):
                out[k] = out[i - 1]
        i = j + 1
    return out


def _length(chain) -> float:
    return sum(math.dist(s[0], s[1]) for s in chain)


def _frame(chain, s: float):
    """Point at arc length s along the chain, its unit direction (p0 -> p1), the segment and the kerb top."""
    acc = 0.0
    for seg in chain:
        L = math.dist(seg[0], seg[1])
        if L < 1e-9:
            continue
        if acc + L >= s or seg is chain[-1]:
            t = min(max((s - acc) / L, 0.0), 1.0)
            dx, dy = (seg[1][0] - seg[0][0]) / L, (seg[1][1] - seg[0][1]) / L
            return (seg[0][0] + dx * t * L, seg[0][1] + dy * t * L), (dx, dy), seg
        acc += L
    seg = chain[-1]
    return seg[1], (1.0, 0.0), seg


def _place(chain, s_start: float, length: float, piece: str, dy_back: float = 0.0, z_top: bool = False,
           sx: float = 1.0) -> Place:
    """A run piece occupying [s_start, s_start + length] of the chain; it runs p1 -> p0, so its pivot is the far end.
    dy_back moves it behind the kerb (away from the road); z_top puts its base 0.15 below the kerb top."""
    (x, y), (dx, dy), seg = _frame(chain, s_start + length)
    bx, by = dy, -dx                                    # right of p0 -> p1 = behind the kerb (road is on the left)
    z = seg[3] - 0.15 if z_top else seg[2]
    return Place(piece, x + bx * dy_back, y + by * dy_back, z, math.atan2(-dy, -dx), sx)


def _straights(chain, max_turn_deg: float = 8.0):
    """[(s0, s1)] stretches of the chain whose segments turn less than max_turn_deg from the stretch's first one."""
    out, acc, start, d0 = [], 0.0, 0.0, None
    for p0, p1, _b, _t in chain:
        L = math.dist(p0, p1)
        if L < 1e-6:
            continue
        d = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        if d0 is not None and abs((d - d0 + math.pi) % (2 * math.pi) - math.pi) > math.radians(max_turn_deg):
            out.append((start, acc))
            start, d0 = acc, d
        elif d0 is None:
            d0 = d
        acc += L
    out.append((start, acc))
    return out


def _project(chain, pt):
    """(arc length, distance) of the chain point nearest pt."""
    best, acc = (0.0, float("inf")), 0.0
    for p0, p1, _b, _t in chain:
        L = math.dist(p0, p1)
        if L < 1e-9:
            continue
        t = max(0.0, min(1.0, ((pt[0] - p0[0]) * (p1[0] - p0[0]) + (pt[1] - p0[1]) * (p1[1] - p0[1])) / (L * L)))
        q = (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
        d = math.dist(q, pt)
        if d < best[1]:
            best = (acc + t * L, d)
        acc += L
    return best


def place(segs: list, crossings: list, probe, rule: dict | None = None) -> Result:
    """segs: kerb walls [(p0, p1, bottom, top)] in layout order; crossings: [(x, y)] on road centrelines;
    probe(x, y, bx, by) -> side of the point behind the kerb (b = unit vector away from the road)."""
    r = {**DEFAULTS, **(rule or {})}
    res = Result()
    lo_h, hi_h = r["kerb_h_range"]
    res.seg_sides = seg_sides(segs, probe)
    cs = chains(segs, res.seg_sides)
    first = 0
    for ci, ch in enumerate(cs):
        side = res.seg_sides[first]
        first += len(ch)
        L = _length(ch)
        if L < 1e-6:
            continue
        res.sides[side] = res.sides.get(side, 0.0) + L
        mat = "Paver" if side == "sea" else "Conc"
        # dropped crossings: one per crossing whose foot on this kerb is within reach and fully on the chain
        drops = []
        n_flush = int(r["flush_m"])
        span = n_flush + 2.0
        for (cx, cy) in crossings:
            s, d = _project(ch, (cx, cy))
            if d > r["crossing_reach_m"] or s - span / 2 < 0.0 or s + span / 2 > L:
                continue
            (_x, _y), _d, seg = _frame(ch, s)
            if not lo_h <= seg[3] - seg[2] <= hi_h:
                continue                                 # kerb not at its 0.15 m upstand (levels): leave it
            if any(abs(s - o) < span for o in drops):
                continue
            _p, d0, _s0 = _frame(ch, s - span / 2)
            _p, d1, _s1 = _frame(ch, s + span / 2)
            if d0[0] * d1[0] + d0[1] * d1[1] < math.cos(math.radians(r["drop_max_turn_deg"])):
                continue                                 # corner radius: crossovers and tactile would splay apart
            drops.append(s)
        for s in sorted(drops):
            s0 = s - span / 2
            res.cuts.append((ci, s0, s0 + span))
            # pieces run toward decreasing s, so in increasing s the ramp up comes first (kit: Ramp falls along +X)
            seq = [RAMP_UP] + [FLUSH] * n_flush + [RAMP]
            back = ["SideUp"] + ["Flush"] * n_flush + ["SideDown"]
            for k, (front, rear) in enumerate(zip(seq, back)):
                res.places.append(_place(ch, s0 + k, 1.0, front))
                res.places.append(_place(ch, s0 + k, 1.0, f"KIT_Crossover_{rear}_{mat}"))
            if side == "land":   # tactile on roadside footways only: never the promenade or a narrow median refuge
                for k in range(int(n_flush // 1.2) or 1):
                    res.places.append(_place(ch, s0 + 1.0 + k * 1.2, 1.2, TACTILE, dy_back=1.0))
                res.counts["tactile_sites"] = res.counts.get("tactile_sites", 0) + 1
            pts = []
            for ss, back_m in ((s0, 0.0), (s0 + span, 0.0), (s0 + span, r["crossover_depth_m"]),
                               (s0, r["crossover_depth_m"])):
                (x, y), (dx, dy), _sg = _frame(ch, ss)
                pts.append((x + dy * back_m, y - dx * back_m))
            res.zones.append(pts)
            res.counts["dropped"] = res.counts.get("dropped", 0) + 1
        clear = [(s - span / 2 - r["crossing_clear_m"], s + span / 2 + r["crossing_clear_m"]) for s in drops]
        # channel: gullies and kerb inlets
        if L >= r["min_run_m"]:
            every = r["gully_every_m"]
            n, s = 0, every / 2
            while s + 1.0 <= L:
                if not any(a <= s <= b for a, b in clear):
                    n += 1
                    piece = INLET if side == "land" and n % int(r["inlet_every"]) == 0 else GULLY
                    res.places.append(_place(ch, s, 1.0, piece))
                    res.counts[piece] = res.counts.get(piece, 0) + 1
                s += every
        # sea-side border course along each straight stretch, around the dropped crossings
        if side == "sea":
            for a, b in _straights(ch):
                pieces = [(a, b)]
                for c0, c1 in sorted((s - span / 2, s + span / 2) for s in drops):
                    pieces = [q for p in pieces for q in ((p[0], min(p[1], c0)), (max(p[0], c1), p[1])) if q[1] > q[0]]
                for p0, p1 in pieces:
                    run = p1 - p0
                    if run < r["border_min_m"]:
                        continue
                    n = max(1, round(run / LENGTH[BORDER]))
                    step = run / n
                    for k in range(n):
                        res.places.append(_place(ch, p0 + k * step, step, BORDER, z_top=True, sx=step / LENGTH[BORDER]))
                    res.counts[BORDER] = res.counts.get(BORDER, 0) + n
    return res


def split_walls(segs: list, cuts: list, sides: list | None = None) -> list:
    """The kerb segments with the dropped lengths removed: cuts [(chain index, s0, s1)] and sides from place();
    each kept piece is (p0, p1, bottom, top, side)."""
    cs = chains(segs, sides)
    first = 0
    by_chain: dict[int, list] = {}
    for ci, s0, s1 in cuts:
        by_chain.setdefault(ci, []).append((s0, s1))
    out = []
    for ci, ch in enumerate(cs):
        gaps = sorted(by_chain.get(ci, []))
        side = sides[first] if sides else None
        first += len(ch)
        acc = 0.0
        for seg in ch:
            p0, p1, b, t = seg
            L = math.dist(p0, p1)
            keep = [(0.0, L)]
            for g0, g1 in gaps:
                a, c = g0 - acc, g1 - acc
                keep = [q for k0, k1 in keep for q in ((k0, min(k1, a)), (max(k0, c), k1)) if q[1] - q[0] > 1e-3]
            for k0, k1 in keep:
                if L < 1e-9:
                    continue
                f0, f1 = k0 / L, k1 / L
                out.append(((p0[0] + (p1[0] - p0[0]) * f0, p0[1] + (p1[1] - p0[1]) * f0),
                            (p0[0] + (p1[0] - p0[0]) * f1, p0[1] + (p1[1] - p0[1]) * f1), b, t, side))
            acc += L
    return out


def _kerb_seg_class():
    from dataclasses import dataclass as _dc

    from .layout import WallSeg

    @_dc
    class KerbSeg(WallSeg):
        """A kerb wall that knows its side: sea = granite Kerb A row, land / island = precast Kerb B row, painted =
        the black / white Kerb C row."""
        side: str = "land"
    return KerbSeg


def apply(cfg: dict, lay, net, dress, marks=None) -> dict:
    """Config "road_edge": place the kit on the layout's kerbs, cut dropped kerbs out of the kerb walls and the
    crossover strips out of the paving behind them. Returns stats for the build report."""
    rule = cfg.get("road_edge")
    if not rule:
        return {}
    KerbSeg = _kerb_seg_class()
    from shapely import ops
    from shapely.geometry import Point, Polygon
    from shapely.prepared import prep

    from .kit import Instance

    kerbs = [w for w in lay.walls if w.kind == "kerb"]
    segs = [(w.p0, w.p1, w.bottom0, w.top) for w in kerbs]
    # sea side = the seafront paver strip (citylib/roadside.paver_zones, the same zone cells.py paves in red
    # herringbone) or a kerb right against the promenade / beach
    zones = getattr(marks, "paver_zones", None) if marks is not None else None
    sea_parts = [ops.unary_union([lay.promenade, lay.beach, lay.sea]).buffer(float(rule.get("sea_reach_m", 3.0)))]
    if zones and not zones[0].is_empty:
        sea_parts.append(zones[0].buffer(0.5))
    sea_p = prep(ops.unary_union(sea_parts))
    road_p = prep(lay.road_area)
    r = {**DEFAULTS, **rule}

    def probe(x, y, bx, by):
        px, py = x + bx * r["probe_m"], y + by * r["probe_m"]
        if road_p.contains(Point(x + bx * r["island_m"], y + by * r["island_m"])):
            return "island"
        return "sea" if sea_p.contains(Point(px, py)) else "land"

    xings = [tuple(c["at"]) for c in (net or {}).get("crossings", [])]
    res = place(segs, xings, probe, rule)
    for p in res.places:
        dress.add(GROUP, Instance(p.piece, p.x, p.y, p.z, p.rot, p.sx))
    # every kerb is rebuilt with its side, so cells.py draws its face from the kit's trim rows (KerbSeg.side)
    kept = split_walls(segs, res.cuts, res.seg_sides)
    # CIRCLE fix 2 (sv_04, sv_15): island kerbs (medians, splitter and roundabout islands) are painted black / white
    # in Cityhub; "painted_islands" draws their faces from the kit's painted Kerb C row
    painted = bool(rule.get("painted_islands", False)) if isinstance(rule, dict) else False
    lay.walls = [w for w in lay.walls if w.kind != "kerb"] + [
        KerbSeg(p0, p1, b, b, t, "kerb", "painted" if painted and sd == "island" else sd) for p0, p1, b, t, sd in kept]
    if res.cuts:
        zone = ops.unary_union([Polygon(z).buffer(0.02, join_style=2) for z in res.zones])
        for name in ("pavement", "promenade", "forecourt", "plots", "green", "parking"):
            g = getattr(lay, name, None)
            if g is not None and not g.is_empty:
                setattr(lay, name, g.difference(zone))
    stats = {k: v for k, v in sorted(res.counts.items())}
    stats["kerb_m"] = {k: round(v) for k, v in sorted(res.sides.items())}
    return stats
