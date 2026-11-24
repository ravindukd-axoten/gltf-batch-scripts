"""The drivable road network as data: segments, junctions, lanes, the drive circle and its road blocks.

The cell build makes road *surfaces* (layout.build_layout). This module makes the road *graph* the game needs on top:
what the server checks positions against and what NPC traffic drives (TDD "World", Vertical Slice Plan "Drive circle").
It reads the same OSM ways, the same `road_overrides` and the same widths (rules.road_width), so a lane line and the
asphalt under it come from one source. Pure Shapely, no Blender; written to data/roads/<id>.json
(schema data/schemas/road_network.schema.json) by tools/city/build_roads.py.

Coordinates are world metres, +X east, +Z north (AGENTS.md rule 5): a point is [x, z]. Heights are not stored: the
cell colliders hold the road surface (Delta Face has stacked levels), so a reader raycasts down from the polyline.

Left-hand traffic (Sri Lanka): on a two-way road the forward lanes sit LEFT of the centreline in the way's direction.
Lane polylines run in the travel direction; lane 0 is the kerb lane (leftmost), the last is next to the centre line.

Config (`road_network` in the area config):
    "drive_loop": {"id", "direction", "waypoints": [osm node ids in driving order, first = last],
                   "ways": [osm way ids the loop may use],
                   "joins": [{"from": node, "to": node, "_doc": ...}]}   synthetic links where OSM leaves a gap
    "blocks": [{"id", "way": osm way id, "from_node": node on the loop or inner network, "stop_m", "why"}]
    "scope_margin_m": inner roads are the carriageways inside the loop polygon grown by this much
    "speed_classes": {class: km/h}  proposed, a person signs off (AGENTS.md: people decide numbers)
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from shapely import ops
from shapely.geometry import LineString, Point, Polygon

from . import osm, rules

# OSM highway -> speed class. Classes, not limits: the km/h per class is config (proposed).
SPEED_CLASS = {
    "motorway": "arterial", "trunk": "arterial", "primary": "arterial",
    "secondary": "collector", "tertiary": "collector",
    "unclassified": "local", "residential": "local", "living_street": "local",
    "service": "service",
}
DEFAULT_SPEEDS_KMH = {"arterial": 50, "collector": 40, "local": 30, "service": 15, "ring": 25}
SURFACES = {"asphalt": "asphalt", "paved": "asphalt", "concrete": "concrete", "paving_stones": "pavers",
            "sett": "pavers", "cobblestone": "pavers", "unpaved": "gravel", "gravel": "gravel", "compacted": "gravel"}
SURFACE_MATERIAL = {"asphalt": "MAT_Asphalt", "concrete": "MAT_Concrete_Weathered", "pavers": "MAT_PlazaPaver",
                    "gravel": "MAT_Earth_Laterite"}  # names from Data/World/WorldMaterials.json, restyled there


def is_oneway(tags: dict) -> int:
    """+1 forward only, -1 reverse only, 0 two-way."""
    v = tags.get("oneway", "")
    if v in ("yes", "1", "true"):
        return 1
    if v == "-1":
        return -1
    if tags.get("junction") in ("roundabout", "circular") and v != "no":
        return 1
    return 0


def lane_split(tags: dict) -> tuple[int, int]:
    """(lanes forward, lanes backward) in the way's own direction."""
    total = rules.road_lanes(tags)
    ow = is_oneway(tags)
    if ow == 1:
        return total, 0
    if ow == -1:
        return 0, total
    fwd = rules.parse_int(tags.get("lanes:forward"))
    back = rules.parse_int(tags.get("lanes:backward"))
    if fwd is not None and back is not None:
        return fwd, back
    if fwd is not None:
        return fwd, max(1, total - fwd)
    if back is not None:
        return max(1, total - back), back
    return max(1, (total + 1) // 2), max(1, total // 2)


def speed_class(tags: dict) -> str:
    if tags.get("junction") in ("roundabout", "circular"):
        return "ring"
    return SPEED_CLASS.get(tags.get("highway", "").removesuffix("_link"), "local")


def surface(tags: dict) -> str:
    return SURFACES.get(tags.get("surface", "asphalt"), "asphalt")


# --- graph -------------------------------------------------------------------------------------

@dataclass
class Edge:
    a: int
    b: int
    way: int          # OSM way id, or 0 for a config join
    length: float


@dataclass
class Graph:
    pos: dict[int, tuple[float, float]] = field(default_factory=dict)
    out: dict[int, list[Edge]] = field(default_factory=dict)

    def add(self, a: int, b: int, way: int) -> None:
        d = math.dist(self.pos[a], self.pos[b])
        self.out.setdefault(a, []).append(Edge(a, b, way, d))


def build_graph(data: osm.OsmData, ways: list[osm.Way], tm, joins: list[dict] = ()) -> Graph:
    """Directed node graph of carriageway ways, one-ways respected; joins are two-way synthetic links."""
    g = Graph()
    for w in ways:
        for n in w.node_ids:
            if n in data.nodes and n not in g.pos:
                g.pos[n] = tm.forward(*data.nodes[n])
    for w in ways:
        ow = is_oneway(w.tags)
        ids = [n for n in w.node_ids if n in g.pos]
        for a, b in zip(ids, ids[1:]):
            if ow >= 0:
                g.add(a, b, w.id)
            if ow <= 0:
                g.add(b, a, w.id)
    for j in joins:
        a, b = int(j["from"]), int(j["to"])
        if a in g.pos and b in g.pos:
            g.add(a, b, 0)
            if not j.get("oneway"):
                g.add(b, a, 0)
    return g


def shortest(g: Graph, a: int, b: int, only: set[int] | None = None) -> list[Edge] | None:
    """Dijkstra from node a to node b; with `only`, just those way ids (0 = config joins) may be used."""
    best = {a: 0.0}
    prev: dict[int, Edge] = {}
    q = [(0.0, a)]
    while q:
        d, n = heapq.heappop(q)
        if n == b:
            break
        if d > best.get(n, math.inf):
            continue
        for e in g.out.get(n, []):
            if only is not None and e.way not in only:
                continue
            nd = d + e.length
            if nd < best.get(e.b, math.inf):
                best[e.b] = nd
                prev[e.b] = e
                heapq.heappush(q, (nd, e.b))
    if b not in prev:
        return None
    path = []
    n = b
    while n != a:
        e = prev[n]
        path.append(e)
        n = e.a
    return path[::-1]


def route_loop(g: Graph, waypoints: list[int], ways: list[int] | None = None) -> list[Edge]:
    """The closed drive loop through the waypoints in order (first == last), on the listed `ways` only (the agent's
    loop, so a shorter cut through an inner road is never taken). Raises if a leg has no one-way-legal route."""
    only = None if ways is None else {int(w) for w in ways} | {0}
    if waypoints[0] != waypoints[-1]:
        raise ValueError("drive_loop waypoints must start and end on the same node")
    edges: list[Edge] = []
    for a, b in zip(waypoints, waypoints[1:]):
        leg = shortest(g, a, b, only)
        if leg is None:
            raise ValueError(f"drive_loop: no one-way-legal route from node {a} to {b}")
        edges += leg
    return edges


def loop_runs(edges: list[Edge]) -> list[dict]:
    """Collapse loop edges into runs of one way: [{"way", "nodes": [...], "dir": +1/-1 vs the way's own order}]."""
    runs: list[dict] = []
    for e in edges:
        if runs and runs[-1]["way"] == e.way and runs[-1]["nodes"][-1] == e.a:
            runs[-1]["nodes"].append(e.b)
        else:
            runs.append({"way": e.way, "nodes": [e.a, e.b]})
    return runs


# --- segments and lanes ------------------------------------------------------------------------

def offset(line: LineString, d: float) -> LineString:
    """Parallel line d metres to the LEFT (negative: right), keeping the input's direction."""
    if abs(d) < 1e-6:
        return line
    o = line.offset_curve(d, quad_segs=4, join_style="mitre", mitre_limit=3.0)
    if o.is_empty:
        return line
    if o.geom_type != "LineString":
        o = max(o.geoms, key=lambda q: q.length)
    return o


def lane_lines(centre: LineString, width: float, fwd: int, back: int) -> list[dict]:
    """Lane centrelines for one carriageway. Left-hand traffic: forward lanes left of the centre line.
    One-way: the lanes share the full width. Two-way: each direction gets width * its share of the lanes."""
    n = fwd + back
    if n <= 0:
        return []
    lw = width / n
    out = []
    # positions measured from the right kerb (-width/2) to the left kerb (+width/2), in the way's direction:
    # right kerb ... backward lanes ... centre line ... forward lanes ... left kerb
    for i in range(fwd):        # forward lane i counted from the left kerb (0 = kerb lane)
        d = width / 2 - lw * (i + 0.5)
        out.append({"dir": 1, "index": i, "line": offset(centre, d), "width": lw})
    for i in range(back):       # backward lane i counted from the right kerb (its own left kerb)
        d = -width / 2 + lw * (i + 0.5)
        ln = offset(centre, d)
        out.append({"dir": -1, "index": i, "line": LineString(list(ln.coords)[::-1]), "width": lw})
    return out


def split_at(ids: list[int], cut: set[int]) -> list[list[int]]:
    """Split a node list at the cut nodes (kept at both pieces)."""
    pieces, cur = [], [ids[0]]
    for n in ids[1:]:
        cur.append(n)
        if n in cut:
            pieces.append(cur)
            cur = [n]
    if len(cur) > 1:
        pieces.append(cur)
    return pieces


def _r(p, nd=2):
    return [round(p[0], nd), round(p[1], nd)]


def _pts(line: LineString) -> list[list[float]]:
    return [_r(p) for p in line.simplify(0.05).coords]


def build_network(cfg: dict, data: osm.OsmData, tm, ways: list[osm.Way], way_lines: dict[int, LineString]) -> dict:
    """The network dict for data/roads/<id>.json. `ways` are the carriageway ways (overrides applied);
    `way_lines` their world lines (dual carriageways already shifted apart, as the cell build uses them)."""
    rn = cfg["road_network"]
    loop_cfg = rn["drive_loop"]
    joins = loop_cfg.get("joins", [])
    g = build_graph(data, ways, tm, joins)
    loop_edges = route_loop(g, [int(n) for n in loop_cfg["waypoints"]], loop_cfg.get("ways"))
    loop_nodes = [e.a for e in loop_edges]
    ring = Polygon([g.pos[n] for n in loop_nodes])
    if not ring.is_valid:
        ring = ring.buffer(0)
    loop_way_ids = {e.way for e in loop_edges if e.way}
    scope = ring.buffer(float(rn.get("scope_margin_m", 3.0)))
    by_id = {w.id: w for w in ways}

    # blocks: each exit way is cut stop_m from where it leaves the loop network; the stub up to the barrier is kept
    # (in the way's own direction, so one-way lanes stay right) and the rest of the way is not part of the network
    # segments: loop ways (whole), inner ways (wholly inside the scope), and for each blocked exit way its inner part
    # plus a stub to the barrier. The stub is cut stop_m from where the way leaves the network and kept in the way's
    # own direction (so one-way lanes stay right); the rest of the way is not part of the network.
    blocked_way_ids = {int(x) for b in rn.get("blocks", []) for x in b["ways"]}
    keep: dict[int, list[int]] = {}
    for w in ways:
        ln = way_lines.get(w.id)
        if ln is None or w.id in blocked_way_ids:
            continue
        if w.id in loop_way_ids or scope.contains(ln):
            keep[w.id] = w.node_ids
    net_nodes = {n for ids in keep.values() for n in ids}
    stub_ways = {}
    for b in rn.get("blocks", []):
        for wid in (int(x) for x in b["ways"]):
            w = by_id.get(wid)
            if w is None:
                raise ValueError(f"block {b['id']}: way {wid} is not a carriageway in the extract")
            touch = [i for i, n in enumerate(w.node_ids) if n in net_nodes]
            if not touch:
                raise ValueError(f"block {b['id']}: way {wid} does not touch the loop network")
            # the touching node where the way leaves the network: its one side inside the scope (kept, may be a single
            # node), the other side running out; with several touching nodes the longest inside part wins
            best = None
            for i in touch:
                for stub, inside, end in ((w.node_ids[i:], w.node_ids[:i + 1], "end"),
                                          (w.node_ids[:i + 1], w.node_ids[i:], "start")):
                    if len(stub) < 2:
                        continue
                    far = stub[-1] if end == "end" else stub[0]
                    if scope.distance(Point(g.pos[far])) <= 0.0:
                        continue
                    ins = LineString([g.pos[n] for n in inside]).length if len(inside) > 1 else 0.0
                    if len(inside) > 1 and not scope.contains(LineString([g.pos[n] for n in inside])):
                        continue
                    if best is None or ins > best[0]:
                        best = (ins, stub, inside, end)
            if best is None:
                raise ValueError(f"block {b['id']}: way {wid} does not leave the loop network")
            _, stub, inside, barrier_end = best
            stub_ways[wid] = (stub, barrier_end, float(b.get("stop_m", 20.0)), b)
            if len(inside) > 1 and scope.contains(LineString([g.pos[n] for n in inside])):
                keep[wid] = inside      # e.g. the A2 south-bound: its part inside the loop stays a road
    use: dict[int, int] = {}
    for wid, ids in list(keep.items()) + [(k, v[0]) for k, v in stub_ways.items()]:
        for i, n in enumerate(ids):
            use[n] = use.get(n, 0) + (1 if i in (0, len(ids) - 1) else 2)
    cut = {n for n, k in use.items() if k >= 3}   # a node where three segment ends meet splits the ways there
    for j in joins:
        cut |= {int(j["from"]), int(j["to"])}

    speeds = {**DEFAULT_SPEEDS_KMH, **rn.get("speed_classes_kmh", {})}
    segments, seg_of_edge = [], {}

    def add_segment(sid: str, w: osm.Way, node_ids: list[int], line: LineString, block: dict | None = None):
        t = w.tags
        fwd, back = lane_split(t)
        width = rules.road_width(t)
        lanes = lane_lines(line, width, fwd, back)
        sc = speed_class(t)
        seg = {
            "id": sid, "osm_way": w.id, "name": t.get("name", ""), "highway": t.get("highway", ""),
            "from_node": node_ids[0], "to_node": node_ids[-1],
            "length_m": round(line.length, 2), "width_m": round(width, 2),
            "lanes_forward": fwd, "lanes_backward": back, "oneway": is_oneway(t) != 0,
            "roundabout": t.get("junction") in ("roundabout", "circular"),
            "speed_class": sc, "speed_kmh": speeds[sc], "surface": surface(t),
            "material": SURFACE_MATERIAL[surface(t)],
            "on_loop": w.id in loop_way_ids, "centreline": _pts(line),
            "lanes": [{"id": f"{sid}:{'f' if ln['dir'] > 0 else 'b'}{ln['index']}", "direction": ln["dir"],
                       "index": ln["index"], "width_m": round(ln["width"], 2), "points": _pts(ln["line"])}
                      for ln in lanes],
            "source": {"osm_way": w.id, "width": "road_overrides" if _overridden(cfg, w) else "osm_rules"},
        }
        if block:
            seg["block"] = block["id"]
        segments.append(seg)
        return seg

    for wid in sorted(keep):
        w = by_id[wid]
        full = way_lines[wid]
        for k, piece in enumerate(split_at(keep[wid], cut)):
            line = _sub_line(full, [g.pos[n] for n in piece if n in g.pos])
            if line is None:
                continue
            seg = add_segment(f"seg_{wid}_{k}", w, piece, line)
            for a, b in zip(piece, piece[1:]):
                seg_of_edge[(a, b)] = seg_of_edge[(b, a)] = seg["id"]
    blocks_out = []
    for wid, (ids, barrier_end, stop_m, b) in sorted(stub_ways.items()):
        w = by_id[wid]
        line = _sub_line(way_lines[wid], [g.pos[n] for n in ids if n in g.pos])
        if line is None:
            continue
        stop = min(stop_m, line.length - 0.5)
        if barrier_end == "end":
            stub = ops.substring(line, 0.0, stop)
            p, q = stub.coords[-1], stub.coords[-2]
            nodes = [ids[0], f"blk_{b['id']}_{wid}"]
        else:
            stub = ops.substring(line, line.length - stop, line.length)
            p, q = stub.coords[0], stub.coords[1]
            nodes = [f"blk_{b['id']}_{wid}", ids[-1]]
        seg = add_segment(f"seg_{wid}_blk", w, [0, 0], stub, block=b)
        seg["from_node"], seg["to_node"] = nodes
        ang = math.atan2(p[1] - q[1], p[0] - q[0])   # heading out of the network, towards the barrier
        half = seg["width_m"] / 2 + float(b.get("overhang_m", 0.5))
        nx, nz = -math.sin(ang), math.cos(ang)
        blocks_out.append({
            "id": f"{b['id']}_{wid}", "group": b["id"], "segment": seg["id"], "osm_way": wid,
            "at": _r(p), "heading_deg": round(math.degrees(ang), 1),
            "barrier": [_r((p[0] + nx * half, p[1] + nz * half)), _r((p[0] - nx * half, p[1] - nz * half))],
            "blocks": b.get("blocks", ["vehicle"]), "kind": b.get("kind", "barrier"), "why": b.get("why", ""),
        })
    for j in joins:
        a, b = int(j["from"]), int(j["to"])
        line = LineString([g.pos[a], g.pos[b]])
        jw = float(j.get("width_m", 7.0))
        jl = int(j.get("lanes", 2))
        fake = osm.Way(0, [a, b], {"highway": j.get("highway", "trunk"), "lanes": str(jl), "width": str(jw),
                                   "oneway": "yes" if j.get("oneway") else "no", "name": j.get("name", "")})
        sid = f"join_{a}_{b}"
        seg = add_segment(sid, fake, [a, b], line)
        seg["osm_way"] = 0
        seg["on_loop"] = True
        seg["source"] = {"osm_way": 0, "width": "config join", "doc": j.get("_doc", "")}
        seg_of_edge[(a, b)] = seg_of_edge[(b, a)] = sid

    # junctions: every node where three or more segment ends meet, and every loop end
    ends: dict[int, list[str]] = {}
    for s in segments:
        for k in ("from_node", "to_node"):
            if isinstance(s[k], int):
                ends.setdefault(s[k], []).append(s["id"])
    junctions = []
    for n, sids in sorted(ends.items()):
        if len(sids) < 2 and n not in cut:
            continue
        ring_here = any(next(s for s in segments if s["id"] == x)["roundabout"] for x in sids)
        junctions.append({"id": f"jn_{n}", "osm_node": n, "at": _r(g.pos[n]), "segments": sorted(set(sids)),
                          "kind": "roundabout" if ring_here else ("join" if any(x.startswith("join_") for x in sids)
                                                                 else "junction")})

    # the loop as an ordered list of (segment, direction)
    loop_seq: list[dict] = []
    for e in loop_edges:
        sid = seg_of_edge.get((e.a, e.b))
        if sid is None:
            raise ValueError(f"drive_loop edge {e.a}->{e.b} has no segment")
        s = next(x for x in segments if x["id"] == sid)
        d = 1 if _walks_forward(s, e, g) else -1
        if loop_seq and loop_seq[-1]["segment"] == sid:
            continue
        loop_seq.append({"segment": sid, "direction": d})
    loop_len = sum(e.length for e in loop_edges)

    crossings = []
    tagged = {nid for nid, t in data.node_tags.items() if t.get("highway") == "crossing"}
    for s in segments:
        w = by_id.get(s["osm_way"])
        if w is None:
            continue
        for n in w.node_ids:
            if n in tagged and n in g.pos and Point(g.pos[n]).distance(LineString(s["centreline"])) < 0.5 \
                    and n not in {c["osm_node"] for c in crossings}:
                t = data.node_tags[n]
                crossings.append({"id": f"xing_{n}", "osm_node": n, "segment": s["id"], "at": _r(g.pos[n]),
                                  "kind": "zebra" if t.get("crossing") in ("zebra", "uncontrolled", "marked", None)
                                  or t.get("crossing_ref") == "zebra" else t.get("crossing", "zebra"),
                                  "signals": t.get("crossing") == "traffic_signals"})

    return {
        "segments": segments, "junctions": junctions, "blocks": blocks_out, "crossings": crossings,
        "drive_loop": {"id": loop_cfg["id"], "direction": loop_cfg.get("direction", "clockwise"),
                       "length_m": round(loop_len, 1), "sequence": loop_seq,
                       "polyline": [_r(g.pos[n]) for n in loop_nodes + [loop_nodes[0]]]},
    }


def network_from_config(cfg: dict, data: osm.OsmData, tm) -> dict | None:
    """build_network for an area config with a `road_network` block (None without one): the carriageway ways with the
    config's overrides and the cell build's dual-carriageway shifts, so lane lines sit on the built asphalt."""
    if "road_network" not in cfg:
        return None
    from . import layout   # layout does not import this module; imported here to keep the module light for tests
    ways = [w for w in layout.override_ways(data, cfg.get("road_overrides", {})) if rules.is_carriageway(w.tags)]
    lines = {w.id: layout._line(data, w.node_ids, tm) for w in ways}
    lines.update(layout.dual_shift(cfg, ways, lines))
    net = build_network(cfg, data, tm, ways, lines)
    net["frontages"] = frontages(cfg, net)
    return net


def frontages(cfg: dict, net: dict) -> list[dict]:
    """Kerbside places on the network (config road_network.frontages): for each, the street's kerb on the lot side,
    kerbside parking lay-bys (asphalt at road level, cut into the pavement) and a clear forecourt apron from the kerb
    to the lot. Points world [x, z]. Used by the cell build (layout adds the lay-bys and apron to the road surface) and
    by the places-as-data package (shops, fuel, repair round Beira Yard)."""
    out = []
    segs = {s["id"]: s for s in net["segments"]}
    for f in cfg.get("road_network", {}).get("frontages", []):
        x0, z0, x1, z1 = f["lot_box_xz"]
        lot = Polygon([(x0, z0), (x1, z0), (x1, z1), (x0, z1)])
        cand = [s for s in segs.values() if s["osm_way"] == int(f["way"])]
        seg = min(cand, key=lambda s: LineString(s["centreline"]).distance(lot))
        line = LineString(seg["centreline"])
        ss = sorted(line.project(Point(c)) for c in lot.exterior.coords[:-1])
        s0, s1 = max(0.0, ss[0]), min(line.length, ss[-1])
        mid = line.interpolate((s0 + s1) / 2)
        side = 1.0 if _left_of(line, (s0 + s1) / 2, lot.centroid) else -1.0
        half = seg["width_m"] / 2
        kerb = offset(ops.substring(line, s0, s1), side * half)
        depth = float(f.get("bay_depth_m", 2.5))
        outer = offset(ops.substring(line, s0, s1), side * (half + depth))
        apron_w = float(f.get("apron_width_m", 12.0))
        sa0, sa1 = (s0 + s1) / 2 - apron_w / 2, (s0 + s1) / 2 + apron_w / 2
        reach = max(depth, lot.distance(mid) - half + 0.5)
        apron = _band(line, sa0, sa1, side * half, side * (half + reach))
        bays, bay_len, gap = [], float(f.get("bay_length_m", 6.0)), float(f.get("apron_clear_m", 1.5))
        end = float(f.get("junction_clear_m", 8.0))   # no lay-by in a junction mouth
        if f.get("parking_bays", True):
            for a0, a1 in ((s0 + end, sa0 - gap), (sa1 + gap, s1 - end)):
                n = int((a1 - a0) // bay_len)
                for k in range(n):
                    c = a0 + bay_len * (k + 0.5)
                    p = offset(line, side * (half + depth / 2)).interpolate(line.project(line.interpolate(c)))
                    t0, t1 = line.interpolate(max(0, c - 0.5)), line.interpolate(min(line.length, c + 0.5))
                    bays.append({"at": _r((p.x, p.y)), "heading_deg": round(math.degrees(math.atan2(t1.y - t0.y, t1.x - t0.x)), 1),
                                 "length_m": bay_len, "width_m": depth})
        layby = [_band(line, a0, a1, side * half, side * (half + depth))
                 for a0, a1 in ((s0 + end, sa0 - gap), (sa1 + gap, s1 - end)) if a1 - a0 >= bay_len] \
            if f.get("parking_bays", True) else []
        out.append({
            "id": f["id"], "name": f.get("name", ""), "segment": seg["id"], "street": seg["name"],
            "side": "left" if side > 0 else "right", "s_m": [round(s0, 2), round(s1, 2)],
            "kerb": _pts(kerb), "layby_outer_edge": _pts(outer),
            "apron": [_r(c) for c in apron.exterior.coords[:-1]],
            "laybys": [[_r(c) for c in lb.exterior.coords[:-1]] for lb in layby if not lb.is_empty],
            "parking_bays": bays, "lot_box": [x0, z0, x1, z1], "why": f.get("_doc", ""),
        })
    return out


def _left_of(line: LineString, s: float, p: Point) -> bool:
    a = line.interpolate(max(0.0, s - 1.0))
    b = line.interpolate(min(line.length, s + 1.0))
    return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) > 0


def _band(line: LineString, s0: float, s1: float, d0: float, d1: float) -> Polygon:
    """The area between offsets d0 and d1 (left positive) of line[s0:s1]."""
    part = ops.substring(line, max(0.0, s0), min(line.length, s1))
    a, b = offset(part, d0), offset(part, d1)
    return Polygon(list(a.coords) + list(b.coords)[::-1]).buffer(0)


def _overridden(cfg: dict, w: osm.Way) -> bool:
    o = cfg.get("road_overrides", {})
    return any(k in o.get(w.tags.get("name", ""), {}) or k in o.get(f"way/{w.id}", {}) for k in ("width", "lanes"))


def _sub_line(full: LineString, pts: list[tuple[float, float]]) -> LineString | None:
    """The part of `full` (maybe shifted) between the projections of the first and last of `pts`."""
    if len(pts) < 2:
        return None
    s0, s1 = full.project(Point(pts[0])), full.project(Point(pts[-1]))
    if abs(s1 - s0) < 0.2:
        return LineString(pts) if LineString(pts).length >= 0.2 else None
    sub = ops.substring(full, min(s0, s1), max(s0, s1))
    if s1 < s0:
        sub = LineString(list(sub.coords)[::-1])
    return sub if sub.geom_type == "LineString" else None


def _walks_forward(seg: dict, e: Edge, g: Graph) -> bool:
    """Does driving node e.a -> e.b follow the segment's own direction?"""
    line = LineString(seg["centreline"])
    return line.project(Point(g.pos[e.b])) >= line.project(Point(g.pos[e.a]))
