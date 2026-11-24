"""P388 street life: street furniture placed from data along a driven route (config `street_life`).

Why: the drive circle read as an empty street (no stalls, bins, benches) next to the Delta Face photos. The rules are
data, one entry per street type, so a new street gets dressed by adding a rule, not code (AGENTS.md "Data, not code").

How: the route (the drive loop) is walked every `sample_m`. At each sample, each side is probed along the normal:
the kerb is where the road surface ends, the pavement width is how far the pavement polygon then runs, and the side's
context is what lies behind it (`bld` a building, `lake`, `green` the Green, `prom` the promenade, `open` plots or
verge). A street rule matches by road name and side context; each of its items repeats every `every_m` along that
side, at the kerb, the back of the pavement or behind it, and slides forward up to 40 % of its spacing when the spot
is taken (road, junction, building, lake, another piece). Every choice is a stable hash of the position.

Tiers (AGENTS.md "Quality tiers", same layout on every tier): an item is `tier: all` (group `StreetLife`, every tier)
or `tier: detail` (group `StreetLifeDetail`, Medium and High). Low drops the detail group's node, so Low is a strict
subset of the same layout. Until the Unity CellBuilder learns that rule (P388 handoff), every tier shows both.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely import ops
from shapely.geometry import LineString, Point
from shapely.prepared import prep

from . import grid
from .kit import Instance, _stable_hash

GROUP_ALL = "StreetLife"
GROUP_DETAIL = "StreetLifeDetail"
MAX_PAVE_M = 6.0   # a wide paved strip (the Green's edge) counts as 6 m: items stay near the kerb they serve


@dataclass
class Side:
    """One side of the route at one sample: the kerb point, unit normal away from the road, unit tangent."""
    d: float           # metres along the route
    side: int          # +1 left of the driving direction, -1 right
    road: str          # nearest road piece's name
    kerb: tuple[float, float]
    n: tuple[float, float]
    t: tuple[float, float]
    pave: float        # pavement width behind the kerb (capped at MAX_PAVE_M)
    ctx: str           # bld | lake | green | prom | open


@dataclass
class Walker:
    """Spatial queries shared by the street-life passes (furniture, signs, planting)."""
    lay: object
    taken: list = field(default_factory=list)   # (x, y, class)

    def __post_init__(self):
        lay = self.lay
        self.road = prep(ops.unary_union([lay.road_area, lay.junctions]))
        self.junc = prep(lay.junctions.buffer(6.0))
        self.pave = prep(lay.pavement)
        blds = ops.unary_union([b.footprint for b in lay.buildings])
        self.bld = blds
        self.keep_out = prep(ops.unary_union([lay.road_area.buffer(0.5), lay.junctions.buffer(0.5), lay.lake.buffer(0.6),
                                              blds.buffer(0.6), getattr(lay, "rail", Point().buffer(0)).buffer(1.0)]))
        self.area_strip = prep(lay.area_strip)
        self.lake = lay.lake
        self.green = lay.park
        self.prom = lay.promenade
        self.cells: dict[tuple[int, int], list] = {}

    # --- occupancy (a coarse 8 m hash grid so thousands of placements stay fast) ---------------------------------
    def add_taken(self, x: float, y: float, cls: str) -> None:
        self.cells.setdefault((int(x // 8), int(y // 8)), []).append((x, y, cls))

    def near(self, x: float, y: float, r: float, cls: str | None = None, side=None) -> bool:
        """Anything (or anything of class cls) within r. side = (kerb point, normal): only count pieces on that
        side of the kerb line's far edge, so a bin across the road does not block this side's bin."""
        k = int(math.ceil(r / 8))
        cx, cy = int(x // 8), int(y // 8)
        for i in range(cx - k, cx + k + 1):
            for j in range(cy - k, cy + k + 1):
                for qx, qy, qc in self.cells.get((i, j), ()):
                    if (cls is None or qc == cls) and (x - qx) ** 2 + (y - qy) ** 2 < r * r:
                        if side is None or (qx - side[0][0]) * side[1][0] + (qy - side[0][1]) * side[1][1] > -1.0:
                            return True
        return False

    def free(self, x: float, y: float) -> bool:
        p = Point(x, y)
        return self.area_strip.contains(p) and not self.keep_out.contains(p) and not self.junc.contains(p)

    # --- the side probe -----------------------------------------------------------------------------------------
    def probe(self, c, t, side: int, max_kerb: float, roads) -> Side | None:
        lx, ly = -t[1] * side, t[0] * side
        s = 0.0
        while s < max_kerb and self.road.contains(Point(c[0] + lx * s, c[1] + ly * s)):
            s += 0.25
        if s >= max_kerb:
            return None
        k0 = s
        while s - k0 < 30.0 and self.pave.contains(Point(c[0] + lx * (s + 0.1), c[1] + ly * (s + 0.1))):
            s += 0.25
        pave = min(s - k0, MAX_PAVE_M)
        q = Point(c[0] + lx * (s + 3.0), c[1] + ly * (s + 3.0))
        ctx = ("bld" if self.bld.distance(q) < 10.0 else "lake" if self.lake.distance(q) < 15.0 else
               "green" if self.green.distance(q) < 6.0 else "prom" if self.prom.distance(q) < 6.0 else "open")
        kerb = (c[0] + lx * k0, c[1] + ly * k0)
        road = min(roads, key=lambda r: r.line.distance(Point(c))).name if roads else ""
        return Side(0.0, side, road, kerb, (lx, ly), t, pave, ctx)


def route_line(cfg: dict, data) -> LineString | None:
    """The drive loop's centreline (citylib/drive_loop.route), or the area_strip route; None without either."""
    if cfg.get("drive_loop"):
        from . import drive_loop
        return LineString(drive_loop.route(cfg, data)["points"])
    from . import layout
    # HEIGHTS/placement 2026-11-24: configs with a road_network loop (delta_face_circle) walk that loop, whose
    # simplified points are the area_strip's extra route of the same id (the inherited area_strip route is the Fort loop)
    loop_id = cfg.get("road_network", {}).get("drive_loop", {}).get("id")
    for er in cfg.get("area_strip", {}).get("extra_routes", []):
        if loop_id and er.get("id") == loop_id and len(er.get("points", [])) >= 2:
            return layout.route_line({"route": {"points": er["points"]}})
    return layout.route_line(cfg.get("area_strip", {}))


def sides(cfg: dict, line: LineString, walker: Walker, roads) -> list[Side]:
    """Every sample along the route, both sides, probed (the shared input of the street-life passes)."""
    sl = cfg.get("street_life", {})
    step = float(sl.get("sample_m", 2.0))
    max_kerb = float(sl.get("max_kerb_m", 16.0))
    near_roads = [r for r in roads if r.line.distance(line) < 20.0]
    out = []
    d = 0.0
    while d <= line.length:
        p = line.interpolate(d)
        a, b = line.interpolate(max(0.0, d - 1.0)), line.interpolate(min(line.length, d + 1.0))
        tl = math.hypot(b.x - a.x, b.y - a.y) or 1.0
        t = ((b.x - a.x) / tl, (b.y - a.y) / tl)
        cands = [r for r in near_roads if r.line.distance(p) < 12.0] or near_roads
        for side in (1, -1):
            s = walker.probe((p.x, p.y), t, side, max_kerb, cands)
            if s is not None:
                s.d = d
                out.append(s)
        d += step
    return out


def matches(rule: dict, s: Side) -> bool:
    roads = rule.get("roads")
    return (not roads or s.road in roads) and s.ctx in rule.get("sides", (s.ctx,))


def spot(s: Side, item: dict) -> tuple[float, float]:
    """Where an item sits across the pavement: kerb + offset, back of the pavement - offset, or behind it + offset."""
    at, off = item.get("at", "kerb"), float(item.get("offset_m", 0.8))
    if at == "road":   # HEIGHTS/placement: on the carriageway, off from the kerb face (gutter decals, parked stands)
        return s.kerb[0] - s.n[0] * off, s.kerb[1] - s.n[1] * off
    dist = off if at == "kerb" else (s.pave - off) if at == "back" else (s.pave + off)
    return s.kerb[0] + s.n[0] * dist, s.kerb[1] + s.n[1] * dist


def yaw_for(s: Side, face: str) -> float:
    """Kit frame: x along, -y is the piece's front. road = front to the road, away = front off it, along = x along."""
    lx, ly = s.n
    if face == "road":
        return math.atan2(-lx, ly)
    if face == "away":
        return math.atan2(lx, -ly)
    return math.atan2(s.t[1], s.t[0])


def pick(names, x: float, y: float, salt: int = 0) -> str:
    if isinstance(names, str):
        return names
    return names[(_stable_hash(int(round(x * 10)), int(round(y * 10)), salt) >> 11) % len(names)]   # FNV low bits repeat


def place_items(cfg: dict, side_list: list[Side], walker: Walker, dress, rules_key: str, expand=None) -> dict:
    """Run one rule list (config street_life[rules_key]) over the probed sides. expand(item, x, y, yaw, s) may
    return extra (piece, x, y, z, yaw) tuples (cart sets, bollard pairs). Returns per-item counts."""
    sl = cfg.get("street_life", {})
    h = walker.lay.heights
    counts: dict[str, int] = {}
    for rule in sl.get(rules_key, []):
        for ii, item in enumerate(rule.get("items", [])):
            every = float(item["every_m"])
            slide = every * float(item.get("slide", 0.4))
            group = GROUP_DETAIL if item.get("tier", "all") == "detail" else GROUP_ALL
            cls = item.get("class", item["piece"] if isinstance(item["piece"], str) else item["piece"][0])
            key = f"{rule['id']}.{cls}"
            for side in (1, -1):
                due = float(item.get("phase_m", every / 2))
                for s in (q for q in side_list if q.side == side):
                    if s.d < due:
                        continue
                    if s.d > due + slide:
                        due += every * max(1, math.floor((s.d - due) / every))
                        if s.d < due:
                            continue
                    if not matches(rule, s) or s.pave < float(item.get("min_pave_m", 0.0)):
                        continue
                    x, y = spot(s, item)
                    on_road = item.get("at") == "road"
                    if on_road:
                        p = Point(x, y)
                        if not walker.area_strip.contains(p) or walker.junc.contains(p) or \
                                walker.near(x, y, float(item.get("clear_m", 2.0)), cls):
                            continue
                    elif not walker.free(x, y) or walker.near(x, y, float(item.get("clear_m", 2.0))):
                        continue
                    if walker.near(x, y, float(item.get("same_m", every * 0.6)), cls, (s.kerb, s.n)):
                        continue
                    yaw = yaw_for(s, item.get("face", "road")) + math.radians(float(item.get("yaw_deg", 0.0)))
                    z = (h.road + float(item.get("z_m", 0.012))) if on_road else h.plot
                    piece = pick(item["piece"], x, y, ii)
                    px, py = x, y
                    if item.get("pivot_x_m"):   # pieces whose pivot is at one end (benches): centre them on the spot
                        px -= math.cos(yaw) * float(item["pivot_x_m"])
                        py -= math.sin(yaw) * float(item["pivot_x_m"])
                    if piece.startswith("VEG_"):   # vegetation markers: hashed size and turn (citylib/vegetation.py)
                        from . import vegetation
                        dress.add(group, vegetation.place(piece, px, py, h.plot,
                                                          None if item.get("face", "any") == "any" else yaw))
                    else:
                        dress.add(group, Instance(piece, px, py, z, yaw))
                    walker.add_taken(x, y, cls)
                    counts[key] = counts.get(key, 0) + 1
                    for extra in (expand(item, piece, x, y, yaw, s) if expand else ()):
                        dress.add(group, Instance(*extra))
                    due = s.d + every
    return counts


def _expand(walker: Walker):
    """Item `set` expansions: `cart` = an isso wade cart with its food and small props (citylib/carts.cart_set),
    `bollards` = a white bollard either side of the piece, along the kerb."""
    from .carts import FOOD_FOR, cart_set, to_world
    h = walker.lay.heights
    slot = [0]

    def run(item, piece_placed, x, y, yaw, s):
        kind = item.get("set")
        out = []
        if kind == "cart":
            slot[0] += 1
            for piece, ox, oy, dyaw in cart_set(slot[0], _stable_hash(int(x * 10), int(y * 10))):
                if (ox, oy) == (0.0, 0.0):
                    continue   # the cart itself is the placed piece; its food rides at the same pivot below
                px, py = to_world(x, y, yaw, ox, oy)
                if walker.free(px, py):
                    out.append((piece, px, py, h.plot, yaw + dyaw))
            # cart_set lists (cart, 0, 0), (food, 0, 0) first: the placed cart's own food shares its pivot
            out.insert(0, (FOOD_FOR[piece_placed], x, y, h.plot, yaw))
        elif kind == "nameplate":   # HEIGHTS/placement: a street-name plate on its post (round-5 kit, 2.35 m up)
            plates = item.get("plates", ["SIGN_NamePlate_A"])
            out.append((pick(plates, x, y, 7), x, y, h.plot + float(item.get("plate_z_m", 2.35)), yaw))
        elif kind == "guard":   # a young street tree in its galvanised guard (gf_24)
            out.append(("PROP_TreeGuard_01", x, y, h.plot, yaw))
        elif kind == "bollards":
            for sgn in (-1.0, 1.0):
                bx, by = x + s.t[0] * sgn * float(item.get("pair_m", 1.8)), y + s.t[1] * sgn * float(item.get("pair_m", 1.8))
                if walker.free(bx, by):
                    out.append(("PROP_Bollard_01", bx, by, h.plot, 0.0))
                    walker.add_taken(bx, by, "bollard")
        return out
    return run


def crossing_bollards(cfg: dict, walker: Walker, dress, line: LineString) -> int:
    """A white bollard pair on each kerb end of every zebra within reach of the route (gf_18: bollards at the
    roundabout crossings; catalogue: bollards keep cars off the pavement at crossings)."""
    sl = cfg.get("street_life", {}).get("crossings")
    if not sl:
        return 0
    h = walker.lay.heights
    reach = float(sl.get("route_reach_m", 25.0))
    n = 0
    zebras = [i for _, i in dress.placements if i.piece == "KIT_RoadMarking_Zebra_A" and line.distance(Point(i.x, i.y)) < reach]
    for z in zebras:
        # the zebra piece is laid across the road: its x axis runs kerb to kerb (dressing.py, width / 7.5 stretch)
        ux, uy = math.cos(z.rot), math.sin(z.rot)
        half = 7.5 * z.sx / 2
        for end in (-1.0, 1.0):
            ex, ey = z.x + ux * (half * (1 + end)), z.y + uy * (half * (1 + end))
            for along in (-1.0, 1.0):
                for push in (0.6, 0.9, 1.3, 1.8):
                    bx = ex + ux * end * push + (-uy) * along * float(sl.get("pair_m", 2.0))
                    by = ey + uy * end * push + ux * along * float(sl.get("pair_m", 2.0))
                    if walker.free(bx, by) and not walker.near(bx, by, 0.9):
                        dress.add(GROUP_ALL, Instance("PROP_Bollard_01", bx, by, h.plot, 0.0))
                        walker.add_taken(bx, by, "bollard")
                        n += 1
                        break
    return n


def seed_taken(walker: Walker, dress) -> None:
    """Everything already placed counts as taken, by class (lamps, shelters, benches, ...)."""
    for _, i in dress.placements:
        walker.add_taken(i.x, i.y, piece_class(i.piece))


def piece_class(piece: str) -> str:
    for key, cls in (("StreetLamp", "lamp"), ("Lamp_", "lamp"), ("BusShelter", "shelter"), ("Bench", "bench"),
                     ("Bin_", "bin"), ("Bollard", "bollard"), ("Kade", "kade"), ("Kiosk", "kiosk"),
                     ("Cart_", "cart"), ("CartFood", "cart_food"), ("VEG_Palm", "palm"), ("VEG_Tree", "tree"),
                     ("VEG_", "plant"), ("UtilityCabinet", "cabinet"), ("TreeGuard", "tree")):
        if key in piece:
            return cls
    return piece


def cost(dress, first: int, tris_table: dict, veg_tris: dict | None = None) -> dict:
    """Low-tier cost of what this pass added, per cell: LOD0 triangles on Low (tier all) and on Medium/High (plus
    detail), instances, and the distinct pieces (the Unity cell build merges a cell's props per material and
    chunk, so new draw calls only come from materials the cell did not already have)."""
    per: dict[str, dict] = {}
    for g, i in dress.placements[first:]:
        c = per.setdefault(grid.cell_id_at(i.x, i.y), {"tris_low": 0, "tris_high": 0, "instances": 0, "pieces": set()})
        tr = (veg_tris or {}).get(i.piece, tris_table.get(i.piece, 100))
        c["tris_high"] += tr
        if g != GROUP_DETAIL:
            c["tris_low"] += tr
        c["instances"] += 1
        c["pieces"].add(i.piece)
    return {k: {"tris_low": v["tris_low"], "tris_high": v["tris_high"], "instances": v["instances"],
                "distinct_pieces": len(v["pieces"])} for k, v in sorted(per.items())}


def dress_furniture(cfg: dict, data, lay, dress) -> dict:
    """Config street_life.furniture: bins, benches, kade stalls, kiosks, isso wade carts, lamps in the gaps, bus
    halts, utility cabinets and bollards along the route, plus bollard pairs at the route's zebras."""
    sl = cfg.get("street_life")
    if not sl:
        return {}
    line = route_line(cfg, data)
    if line is None:
        return {}
    walker = Walker(lay)
    seed_taken(walker, dress)
    side_list = sides(cfg, line, walker, lay.roads)
    first = len(dress.placements)
    counts = place_items(cfg, side_list, walker, dress, "furniture", _expand(walker))
    counts["crossing_bollards"] = crossing_bollards(cfg, walker, dress, line)
    from .cells import _kit_tris
    counts["cells"] = cost(dress, first, _kit_tris())
    counts["contexts"] = _ctx_share(side_list)
    return counts


def _ctx_share(side_list: list[Side]) -> dict:
    out: dict[str, int] = {}
    for s in side_list:
        out[s.ctx] = out.get(s.ctx, 0) + 1
    return out
