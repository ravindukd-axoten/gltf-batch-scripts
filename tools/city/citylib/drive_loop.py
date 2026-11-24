"""The Delta Face drive circle (Vertical Slice M6; agent 2026-11-17/18): the closed loop the player drives, the joins
OSM lacks, and the blocks on every road that leaves it. Pure Python (no Shapely), so the verifier and its tests run on
any python3.

Config "drive_loop" (see config/drive_circle.json):
  ways   OSM way ids the loop uses (each must contribute at least one driven edge)
  start  "<way>:start|end" node the loop starts and ends at; via: the nodes it passes, in driving order
  joins  short synthetic roads where OSM leaves a gap ({"id", "from", "to", "tags"}); added to the OSM data
         (negative way ids) so the pipeline builds them as road, the router drives them
  blocks [{"id", "ways", "at": [lat, lon], "why"}]: a barrier line across each listed way, moved along the way out
         to clear_m from the loop centreline
  cells  "buffer_m" round the loop + "scenery_boxes" ([[lat0, lon0], [lat1, lon1]]): the cells the slice needs
Road tags are read after the config's road_overrides (by name, then "way/<id>"), as the pipeline reads them.
"""
from __future__ import annotations

import heapq
import math

from . import geo, grid, osm, rules

ONEWAY_FWD = ("yes", "true", "1")


def tags_of(cfg: dict, w: osm.Way) -> dict[str, str]:
    ov = cfg.get("road_overrides", {})
    return {**w.tags, **ov.get(w.tags.get("name", ""), {}), **ov.get(f"way/{w.id}", {})}


def _node_ref(data: osm.OsmData, ref: str) -> int:
    wid, end = ref.split(":")
    w = data.ways[int(wid)]
    return w.node_ids[0] if end == "start" else w.node_ids[-1]


def add_joins(cfg: dict, data: osm.OsmData) -> list[osm.Way]:
    """Add the loop's join roads to the OSM data as ways -1, -2, ... between existing nodes (idempotent)."""
    out = []
    for k, j in enumerate(cfg.get("drive_loop", {}).get("joins", [])):
        wid = -(k + 1)
        w = osm.Way(wid, [_node_ref(data, j["from"]), _node_ref(data, j["to"])], dict(j.get("tags", {})))
        data.ways[wid] = w
        out.append(w)
    return out


def xy(data: osm.OsmData, n: int, tm=geo.CITYHUB) -> tuple[float, float]:
    return tm.forward(*data.nodes[n])


def _edges(cfg: dict, data: osm.OsmData, way_ids) -> dict[int, list[tuple[int, float, int]]]:
    adj: dict[int, list[tuple[int, float, int]]] = {}
    for wid in way_ids:
        w = data.ways[wid]
        t = tags_of(cfg, w)
        ow = t.get("oneway", "")
        if t.get("junction") in ("roundabout", "circular") and not ow:
            ow = "yes"
        fw, bw = ow != "-1", ow not in ONEWAY_FWD
        for a, b in zip(w.node_ids, w.node_ids[1:]):
            d = math.dist(xy(data, a), xy(data, b))
            if fw:
                adj.setdefault(a, []).append((b, d, wid))
            if bw:
                adj.setdefault(b, []).append((a, d, wid))
    return adj


def _dijkstra(adj, s: int, t: int) -> list[tuple[int, int]] | None:
    """Shortest directed path s -> t as [(node, way used to reach it)], first = (s, 0); None if unreachable.
    s == t asks for the shortest cycle back to s (at least one edge)."""
    dist: dict[int, float] = {}
    prev: dict[int, tuple[int, int]] = {}
    h: list[tuple[float, int]] = []

    def relax(u: int, c: float) -> None:
        for v, d, w in adj.get(u, []):
            if c + d < dist.get(v, 1e18):
                dist[v] = c + d
                prev[v] = (u, w)
                heapq.heappush(h, (c + d, v))

    relax(s, 0.0)
    while h:
        c, u = heapq.heappop(h)
        if u == t:
            break
        if c <= dist[u]:
            relax(u, c)
    if t not in prev:
        return None
    path, v = [], t
    while True:
        u, w = prev[v]
        path.append((v, w))
        v = u
        if v == s:
            break
    path.append((s, 0))
    path.reverse()
    return path


def route(cfg: dict, data: osm.OsmData, tm=geo.CITYHUB) -> dict:
    """Drive the loop: start -> via... -> start over the loop's ways (one-ways respected). Returns nodes, the ways
    used per edge, world points, length and the checks (closed, every listed way used, gaps between nodes)."""
    dl = cfg["drive_loop"]
    joins = [w.id for w in add_joins(cfg, data)] if not any(k < 0 for k in data.ways) else \
        [k for k in data.ways if k < 0]
    ways = [int(w) for w in dl["ways"]] + joins
    missing = [w for w in ways if w not in data.ways]
    if missing:
        raise ValueError(f"drive_loop ways not in the OSM data: {missing}")
    adj = _edges(cfg, data, ways)
    start = _node_ref(data, dl["start"])
    stops = [start] + [_node_ref(data, r) for r in dl.get("via", [])] + [start]
    nodes, used = [start], []
    broken = None
    for a, b in zip(stops, stops[1:]):
        p = _dijkstra(adj, a, b)
        if p is None:
            broken = (a, b)
            break
        nodes += [n for n, _ in p[1:]]
        used += [w for _, w in p[1:]]
    pts = [xy(data, n) for n in nodes]
    length = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
    per_way: dict[int, float] = {}
    for (p, q), w in zip(zip(pts, pts[1:]), used):
        per_way[w] = per_way.get(w, 0.0) + math.dist(p, q)
    drivable = {w: rules.is_carriageway(tags_of(cfg, data.ways[w])) for w in ways}
    return {
        "nodes": nodes, "ways_used": used, "points": pts, "length_m": length,
        "closed": broken is None and nodes[0] == nodes[-1] and len(nodes) > 2,
        "broken_between": broken,
        "unused_ways": [w for w in ways if w not in per_way],
        "not_drivable": [w for w, ok in drivable.items() if not ok],
        "per_way_m": per_way,
        "max_step_m": max((math.dist(p, q) for p, q in zip(pts, pts[1:])), default=0.0),
    }


def samples(pts: list[tuple[float, float]], step: float = 2.0) -> list[tuple[float, float]]:
    out = []
    carry = 0.0
    for p, q in zip(pts, pts[1:]):
        seg = math.dist(p, q)
        s = carry
        while s < seg:
            f = s / seg
            out.append((p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f))
            s += step
        carry = s - seg
    out.append(pts[-1])
    return out


def seg_dist(p, a, b) -> float:
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    f = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.dist(p, (ax + dx * f, ay + dy * f))


def line_dist(p, pts) -> float:
    return min(seg_dist(p, a, b) for a, b in zip(pts, pts[1:]))


def _along(pts, s: float):
    """Point and unit tangent at distance s along a polyline (clamped)."""
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if s <= seg or b is pts[-1]:
            f = 0.0 if seg == 0 else max(0.0, min(1.0, s / seg))
            t = ((b[0] - a[0]) / (seg or 1), (b[1] - a[1]) / (seg or 1))
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), t
        s -= seg
    return pts[-1], (0.0, 1.0)


def blocks(cfg: dict, data: osm.OsmData, loop: dict, tm=geo.CITYHUB) -> list[dict]:
    """One barrier line per (block, way): start at the way point nearest the block's "at", step along the way away
    from the loop until the line's centre is clear_m from the loop centreline. Width = carriageway + 1 m."""
    dl = cfg["drive_loop"]
    clear = float(dl.get("block_clear_m", 12.0))
    loop_pts = loop["points"]
    loop_nodes = set(loop["nodes"])
    out = []
    for b in dl.get("blocks", []):
        at = tm.forward(*b["at"])
        for wid in b["ways"]:
            w = data.ways[int(wid)]
            t = tags_of(cfg, w)
            pts = [xy(data, n) for n in w.node_ids]
            total = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
            # the end of the way nearer the loop is where traffic would leave it; walk from there outwards
            d0, d1 = line_dist(pts[0], loop_pts), line_dist(pts[-1], loop_pts)
            forward = d0 <= d1
            s, found = 0.0, None
            while s <= total:
                p, tan = _along(pts, s if forward else total - s)
                if line_dist(p, loop_pts) >= clear:
                    found = (p, tan)
                    break
                s += 1.0
            if found is None:
                out.append({"id": b["id"], "way": int(wid), "ok": False, "why": b.get("why", ""),
                            "error": f"way never clears {clear} m from the loop"})
                continue
            (x, y), (tx, ty) = found
            if not forward:
                tx, ty = -tx, -ty                 # heading away from the loop (the cluster's cones face the loop)
            width = rules.road_width(t) + 1.0
            out.append({
                "id": b["id"], "way": int(wid), "ok": True, "why": b.get("why", ""),
                "x": round(x, 2), "z": round(y, 2), "yaw_deg": round(math.degrees(math.atan2(tx, ty)), 1),
                "width_m": round(width, 2), "kind": b.get("kind", "barrier"),
                "pavement_m": round(rules.pavement_width(t), 2),
                "touches_loop": sum(1 for n in set(w.node_ids) if n in loop_nodes),
                **({"taper": b["taper"]} if str(wid) in (b.get("taper") or {}).get("ways", []) else {}),
                "dist_from_at_m": round(math.dist((x, y), at), 1),
                "clear_m": round(line_dist((x, y), loop_pts), 1),
                "name": t.get("name", ""), "highway": t.get("highway", ""),
            })
    return out


def barrier_instances(block: dict, piece_w: float = 1.6, gap: float = 0.15) -> list[tuple[float, float, float]]:
    """(x, y, yaw radians) for a row of barrier pieces across the road at a block (pieces face along the road)."""
    yaw = math.radians(block["yaw_deg"])
    tx, ty = math.sin(yaw), math.cos(yaw)       # along the road
    nx, ny = ty, -tx                            # across
    n = max(2, math.ceil(block["width_m"] / (piece_w + gap)))
    span = n * (piece_w + gap) - gap
    rot = math.atan2(ny, nx)                    # piece length runs across the road
    return [(block["x"] + nx * (-span / 2 + piece_w / 2 + k * (piece_w + gap)),
             block["z"] + ny * (-span / 2 + piece_w / 2 + k * (piece_w + gap)), rot) for k in range(n)]


CONE_PIECE = "PROP_TrafficCone_01"
RUN_PIECE = "PROP_Barrier_PoliceRun_01"   # three interlocked water-barriers (street kit v2), 4.7 m long
RUN_W = 4.7
CLUSTER_ROW_GAP_M = 1.1      # second barrier row behind the first, staggered by half a piece (sv_04, sv_14)
CLUSTER_CONE_M = 2.4         # cone line on the loop side of the barriers (sv_07, sv_09)
COLLIDER_H_M = 1.0           # block collider height above the road (a car cannot climb it; barrier tops at 0.85 m)


def _frame(block: dict):
    yaw = math.radians(block["yaw_deg"])
    tx, ty = math.sin(yaw), math.cos(yaw)       # along the road, away from the loop
    return tx, ty, ty, -tx                      # (along, across)


def cluster_instances(block: dict, piece_w: float = 1.6, gap: float = 0.8,
                      on_road=None) -> list[tuple[str, float, float, float, bool]]:
    """(piece, x, y, yaw radians, road_only) for a block cluster, as the red police barrier groups in sv_04, sv_09
    and sv_14: a front row across the carriageway with each piece knocked a few degrees off line, a second row
    1.1 m behind it staggered by half a piece, a barrier at each end angled back towards the loop (the funnel
    the police set at a closed side road), and a cone line on the loop side across the carriageway and pavements.
    Deterministic (hash of the block centre). road_only pieces stand on the carriageway only. on_road(x, y): the
    built road surface; with it the taper measures from the real kerb at each station (carriageways shift and narrow
    upstream of the block line)."""
    tx, ty, nx, ny = _frame(block)
    rot = math.atan2(ny, nx)
    n = max(2, math.ceil(block["width_m"] / (piece_w + gap)))
    span = n * (piece_w + gap) - gap
    seed = int(abs(block["x"] * 7.0 + block["z"] * 13.0)) % 9973
    out = []

    def at(u: float, v: float):
        return block["x"] + nx * u + tx * v, block["z"] + ny * u + ty * v

    for k in range(n):
        u = -span / 2 + piece_w / 2 + k * (piece_w + gap)
        jit = math.radians(((seed + 37 * k) % 11 - 5) * 2.8)        # -14..+14 degrees: hand-placed, not a fence
        out.append((BARRIER_PIECE, *at(u, 0.0), rot + jit, True))
    # second row behind: the interlocking red water-barrier runs of sv_04/sv_09/sv_14 (P161; 4.7 m each, 0.2 m apart)
    n_run = max(2, math.ceil(span / (RUN_W + 0.2)))
    span_run = n_run * (RUN_W + 0.2) - 0.2
    for k in range(n_run):
        u = -span_run / 2 + RUN_W / 2 + k * (RUN_W + 0.2)
        jit = math.radians(((seed + 53 * k) % 7 - 3) * 2.0)
        out.append((RUN_PIECE, *at(u, CLUSTER_ROW_GAP_M), rot + jit, True))
    for side in (-1.0, 1.0):                                         # end pieces angled back to the loop, 35 deg
        u = side * (span / 2 + 0.35)
        out.append((BARRIER_PIECE, *at(u, -0.75), rot + side * math.radians(55.0), True))
    tp = block.get("taper")
    if tp:
        # lane-closure taper on the loop side (sv_13, the agent's circled crop): a diagonal of cones with a barrier
        # every third slot, from the kerb length_m before the block line out to lanes_closed lanes in, so the kerb
        # lane is shut ahead of the closure and traffic funnels into the open lane(s)
        side = -1.0 if tp.get("side", "left") == "left" else 1.0       # -u is left of the heading
        kerb = side * (span / 2 - 0.5)
        inner = side * (span / 2 - float(tp.get("lane_m", 3.5)) * int(tp.get("lanes_closed", 1)))
        length = float(tp.get("length_m", 36.0))
        steps = max(2, int(length / float(tp.get("spacing_m", 3.0))))
        v0, v1 = -CLUSTER_CONE_M - length, -CLUSTER_CONE_M - 0.8
        line_yaw = math.atan2(ny * (inner - kerb) + ty * (v1 - v0), nx * (inner - kerb) + tx * (v1 - v0))
        for k in range(steps + 1):
            f = k / steps
            u, v = kerb + (inner - kerb) * f, v0 + (v1 - v0) * f
            if on_road is not None:
                # walk from the far side of the frame towards the closed side until the road ends: that is the kerb
                edge = None
                for q in range(0, 81):
                    uq = -side * 4.0 + side * q * 0.25
                    if on_road(*at(uq, v)):
                        edge = uq
                    elif edge is not None:
                        break
                if edge is None:
                    continue
                u = edge - side * (0.5 + (float(tp.get("lane_m", 3.5)) * int(tp.get("lanes_closed", 1)) - 0.5) * f)
            if k % 3 == 2:
                out.append((BARRIER_PIECE, *at(u, v), line_yaw, True))   # along the taper
            else:
                out.append((CONE_PIECE, *at(u, v), rot + k, True))
    reach = span / 2 + float(block.get("pavement_m", 0.0)) + 0.4
    m = max(3, int(2 * reach / 1.5))
    for k in range(m + 1):
        u = -reach + 2 * reach * k / m
        out.append((CONE_PIECE, *at(u, -CLUSTER_CONE_M), rot + (seed + k) % 6, False))
    return out


def cluster_collider(block: dict, piece_w: float = 1.6, gap: float = 0.8) -> list[tuple[float, float]]:
    """The block's collision box (4 corners, world x/z, counter-clockwise): the barrier rows and the end pieces,
    across the carriageway and both pavements (a car cannot drive round it on the kerb)."""
    tx, ty, nx, ny = _frame(block)
    n = max(2, math.ceil(block["width_m"] / (piece_w + gap)))
    span = n * (piece_w + gap) - gap
    half = span / 2 + float(block.get("pavement_m", 0.0)) + 0.6
    v0, v1 = -1.2, CLUSTER_ROW_GAP_M + 0.35
    pts = [(-half, v0), (half, v0), (half, v1), (-half, v1)]
    ring = [(block["x"] + nx * u + tx * v, block["z"] + ny * u + ty * v) for u, v in pts]
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))
    return ring if area2 > 0 else ring[::-1]


def required_cells(cfg: dict, loop: dict, tm=geo.CITYHUB) -> set[str]:
    """Cells the slice needs: every cell within buffer_m of the loop centreline, plus every cell a scenery box
    touches (City of Dreams, view-only)."""
    c = cfg["drive_loop"].get("cells", {})
    buf = float(c.get("buffer_m", 40.0))
    out = set()
    for x, y in samples(loop["points"], 4.0):
        for dx, dy in ((0, 0), (buf, 0), (-buf, 0), (0, buf), (0, -buf)):
            out.add(grid.cell_id_at(x + dx, y + dy))
    for (la0, lo0), (la1, lo1) in c.get("scenery_boxes", []):
        xs, ys = zip(*(tm.forward(la, lo) for la in (la0, la1) for lo in (lo0, lo1)))
        for cell in grid.cells_in_bounds(min(xs), min(ys), max(xs) - 1e-6, max(ys) - 1e-6):
            out.add(grid.cell_id(cell))
    return out


def junctions_on_loop(cfg: dict, data: osm.OsmData, loop: dict) -> list[dict]:
    """Loop nodes where a carriageway other than the loop's own edges meets it (after overrides)."""
    deg: dict[int, set[int]] = {}
    for w in data.ways.values():
        if "highway" not in w.tags or not rules.is_carriageway(tags_of(cfg, w)):
            continue
        for n in w.node_ids:
            deg.setdefault(n, set()).add(w.id)
    out = []
    seen = set()
    for n in loop["nodes"]:
        ws = deg.get(n, set())
        if len(ws) >= 2 and n not in seen:
            seen.add(n)
            out.append({"node": n, "ways": sorted(ws)})
    return out


def inside(p, ring) -> bool:
    """Point in polygon (even-odd ray cast), ring = closed list of (x, y)."""
    x, y = p
    hit = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def leaks(cfg: dict, data: osm.OsmData, loop: dict, blks: list[dict], leak_m: float = 60.0) -> list[dict]:
    """Roads that still lead out: walk every carriageway (both ways, one-ways ignored: a player can drive the wrong
    way) from the loop, never through a block's barrier segment; any node reached outside the loop ring and more than
    leak_m from its centreline is a leak (reported once per way it was reached by). Open spurs (drive_loop.open_spurs)
    are allowed dead ends."""
    ring = loop["points"]
    spurs = {int(w) for w in cfg["drive_loop"].get("open_spurs", [])}
    cut: set[tuple[int, int]] = set()
    for b in blks:
        if not b.get("ok"):
            continue
        w = data.ways[b["way"]]
        segs = list(zip(w.node_ids, w.node_ids[1:]))
        a, c = min(segs, key=lambda s: seg_dist((b["x"], b["z"]), xy(data, s[0]), xy(data, s[1])))
        cut |= {(a, c), (c, a)}
    adj: dict[int, list[tuple[int, int]]] = {}
    for w in data.ways.values():
        if "highway" not in w.tags or not rules.is_carriageway(tags_of(cfg, w)):
            continue
        for a, c in zip(w.node_ids, w.node_ids[1:]):
            if (a, c) in cut or a not in data.nodes or c not in data.nodes:
                continue
            adj.setdefault(a, []).append((c, w.id))
            adj.setdefault(c, []).append((a, w.id))
    seen = set(loop["nodes"])
    todo = list(loop["nodes"])
    out: dict[int, dict] = {}
    while todo:
        u = todo.pop()
        for v, wid in adj.get(u, []):
            if v in seen:
                continue
            seen.add(v)
            p = xy(data, v)
            if wid not in spurs and not inside(p, ring) and line_dist(p, ring) > leak_m:
                if wid not in out:
                    t = tags_of(cfg, data.ways[wid])
                    out[wid] = {"way": wid, "name": t.get("name", ""), "highway": t.get("highway", ""),
                                "x": round(p[0], 1), "z": round(p[1], 1)}
                continue                          # report where it escapes, not the whole city beyond
            todo.append(v)
    return list(out.values())


BARRIER_PIECE = "PROP_Barrier_Police_01"   # the red water-filled barrier of the street kit (sv_04), 1.6 m


def dress_blocks(cfg: dict, data: osm.OsmData, lay, dress) -> tuple[dict, list[dict]]:
    """Pipeline step (Blender/Shapely): barrier rows at every block, and the loop's on-road check (every 2 m sample
    of the centreline must stand on road or junction surface, so the joins and the lake-side road really are built)."""
    from shapely import ops  # noqa: E402  (pipeline only; the verifier stays pure)
    from shapely.geometry import Point  # noqa: E402

    from .kit import Instance  # noqa: E402

    loop = route(cfg, data)
    blks = blocks(cfg, data, loop)
    surface = ops.unary_union([lay.road_area, lay.junctions]).buffer(0.25)
    walkable = ops.unary_union([surface, lay.pavement]).buffer(0.1)
    placed = cones = 0
    lay.block_colliders = []
    for b in blks:
        if not b["ok"]:
            continue
        b["pieces"] = b["cones"] = 0
        for piece, x, y, rot, road_only in cluster_instances(b, on_road=lambda x_, y_: surface.contains(Point(x_, y_))):
            if not (surface if road_only else walkable).contains(Point(x, y)):
                continue                      # a piece past the kerb would stand in a wall or a lawn
            z = lay.heights.road if surface.contains(Point(x, y)) else lay.heights.plot
            dress.add("Street", Instance(piece, x, y, z, rot))
            if piece in (BARRIER_PIECE, RUN_PIECE):
                b["pieces"] += 1
                placed += 1
            else:
                b["cones"] += 1
                cones += 1
        b["collider"] = [[round(px, 2), round(pz, 2)] for px, pz in cluster_collider(b)]
        b["collider_h_m"] = COLLIDER_H_M
        lay.block_colliders.append((cluster_collider(b), lay.heights.road - 0.2, lay.heights.road + COLLIDER_H_M))
    lakeside = dress_lakeside(cfg, lay, dress)
    pts = samples(loop["points"], 2.0)
    off = [i for i, (x, y) in enumerate(pts) if not surface.contains(Point(x, y))]
    runs: list[list[int]] = []
    for i in off:
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    lay.stats["drive_loop"] = {
        **lay.stats.get("drive_loop", {}),
        "length_m": round(loop["length_m"], 1), "closed": loop["closed"], "samples": len(pts),
        "off_road_samples": len(off),
        "off_road_runs_m": [[round(a * 2.0), round((b - a + 1) * 2.0)] for a, b in runs][:20],
        "blocks": len(blks), "block_lines_ok": sum(1 for b in blks if b["ok"]), "barrier_pieces": placed, "cones": cones, "lakeside": lakeside,
        "blocks_without_pieces": [f"{b['id']}:{b['way']}" for b in blks if b["ok"] and not b.get("pieces")],
    }
    return loop, blks


LAMP_PIECE = "PROP_StreetLamp_SingleArm_01"
# LOD0 triangles of the vegetation markers (Art/World/Vegetation/VEG_*.glb, read 2026-11-19); the cell report counts
# only kit meshes, so the lake-side cost per cell adds these
VEG_LOD0_TRIS = {"VEG_Palm_Coconut_A": 540, "VEG_Palm_Coconut_B": 540, "VEG_Palm_Coconut_C": 540,
                 "VEG_Palm_Coconut_D": 540, "VEG_Tree_RainTree_A": 1050, "VEG_Tree_Kottamba_A": 1276}


def sf_tris() -> dict[str, int]:
    """LOD0 triangles of the generated KIT_SF pieces (frontage_kit/rowmap_sf.json, written by the generator)."""
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "frontage_kit", "rowmap_sf.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return {k: v["lod0"] for k, v in json.load(fh).get("tris", {}).items() if "lod0" in v}


def dress_lakeside(cfg: dict, lay, dress) -> dict:
    """Config drive_loop.lakeside: the lake-side road's verges (sv_05: coconut palms at the kerb; sv_15: granite kerb,
    galvanised single-arm lamps every 35-40 m; catalogue: temporary furniture everywhere). The verge facing the lake
    gets a palm row, kerb lamps between the palms (arm over the road), benches facing the water and a bollard pair at
    each bench gap; the inland verge gets shade trees. A spot must be open ground: off the carriageway and junctions,
    out of the lake and every building, inside the area_strip. Returns counts for the report."""
    from shapely import ops  # noqa: E402
    from shapely.geometry import Point  # noqa: E402

    from . import vegetation  # noqa: E402
    from .kit import Instance  # noqa: E402

    lc = cfg.get("drive_loop", {}).get("lakeside")
    if not lc:
        return {}
    names = set(lc.get("roads", []))
    h = lay.heights
    road = ops.unary_union([lay.road_area, lay.junctions])
    keep_out = ops.unary_union([road.buffer(0.6), lay.lake.buffer(0.8)]
                               + [b.footprint.buffer(1.0) for b in lay.buildings])
    junc = lay.junctions.buffer(5.0)
    lake = lay.lake
    taken: list[tuple[float, float]] = [(i.x, i.y) for _, i in dress.placements]
    first = len(dress.placements)
    counts = {"palms": 0, "verge_trees": 0, "trees": 0, "lamps": 0, "benches": 0, "bollards": 0, "pavement_share": 0.0}
    pave_hits = probes = 0

    def free(x: float, y: float, gap: float) -> bool:
        p = Point(x, y)
        if keep_out.contains(p) or junc.contains(p) or not lay.area_strip.contains(p):
            return False
        return all((x - qx) ** 2 + (y - qy) ** 2 >= gap * gap for qx, qy in taken)

    for r in (r for r in lay.roads if r.name in names):
        w = r.width
        line = r.line
        n = int(line.length // 2.0)
        for k in range(n + 1):
            d = k * 2.0
            p0, p1 = line.interpolate(max(0.0, d - 0.5)), line.interpolate(min(line.length, d + 0.5))
            ln = math.hypot(p1.x - p0.x, p1.y - p0.y) or 1.0
            tx, ty = (p1.x - p0.x) / ln, (p1.y - p0.y) / ln
            c = line.interpolate(d)
            sides = []
            for side in (-1.0, 1.0):
                lx, ly = -ty * side, tx * side
                sides.append((lake.distance(Point(c.x + lx * 15, c.y + ly * 15)) if not lake.is_empty else 1e9, lx, ly))
            sides.sort()
            (_, lx, ly), (_, ix, iy) = sides
            if k % 5 == 0:
                probes += 1
                pave_hits += lay.pavement.contains(Point(c.x + lx * (w / 2 + 1.0), c.y + ly * (w / 2 + 1.0)))
            off = w / 2 + float(lc.get("palm_offset_m", 1.8))
            if k % max(1, int(float(lc.get("palm_spacing_m", 12.0)) / 2.0)) == 0:
                px, py = c.x + lx * off, c.y + ly * off
                row = lc.get("palms", vegetation.ROAD_PALMS)
                # agent 2026-11-20: no palm row; "palms": [] puts small young verge trees in the same slots (os_10)
                if not row:
                    row, key = lc.get("verge_trees", []), "verge_trees"
                else:
                    key = "palms"
                if row and free(px, py, 5.0):
                    yaw = vegetation.lean_towards(px, py, px + lx, py + ly, 0.7)   # lean over the water
                    dress.add(vegetation.GROUP, vegetation.place(vegetation.pick(row, px, py), px, py, h.plot, yaw))
                    taken.append((px, py))
                    counts[key] += 1
            if k % max(1, int(float(lc.get("lamp_spacing_m", 36.0)) / 2.0)) == 3:
                qx, qy = c.x + lx * (w / 2 + 0.9), c.y + ly * (w / 2 + 0.9)
                if free(qx, qy, 3.0):
                    dress.add("Street", Instance(LAMP_PIECE, qx, qy, h.plot, math.atan2(-ly, -lx)))
                    taken.append((qx, qy))
                    counts["lamps"] += 1
            if k % max(1, int(float(lc.get("tree_spacing_m", 24.0)) / 2.0)) == 6:
                ox = w / 2 + float(lc.get("tree_offset_m", 2.6))
                px, py = c.x + ix * ox, c.y + iy * ox
                if free(px, py, 7.0):
                    yaw = vegetation.lean_towards(px, py, px + ix, py + iy, 0.9)
                    dress.add(vegetation.GROUP, vegetation.place(vegetation.pick(lc.get("trees", ["VEG_Tree_RainTree_A"]),
                                                                                 px, py), px, py, h.plot, yaw))
                    taken.append((px, py))
                    counts["trees"] += 1
    counts["pavement_share"] = round(pave_hits / max(1, probes), 2)
    if lc.get("edge"):
        # P165: the edge is city geometry (citylib/lake_edge.py), built per cell by cells.build_cells; only the props
        # are instances here
        from . import lake_edge  # noqa: E402
        le = lake_edge.build(lay, names, lc["edge"])
        lay.lake_edge = le
        if le is not None:
            def add(piece, x, y, z, yaw, sz=1.0):
                dress.add("Street" if not piece.startswith("VEG_") else vegetation.GROUP,
                          Instance(piece, x, y, z, yaw, sz=sz) if not piece.startswith("VEG_") else vegetation.place(piece, x, y, z, yaw))
            counts["edge"] = {"props": lake_edge.place_props(le, lay, taken, add, (lc.get("shrubs") or [None])[0]),
                              "layers": lake_edge.cost(le, lay)}
    # Low-tier cost per cell: LOD0 triangles (kit table + VEG_LOD0_TRIS) and new distinct meshes (draw calls before
    # instancing/SRP batching: one per distinct piece; vegetation shares the VEG atlases)
    from .cells import _kit_tris  # noqa: E402
    table = _kit_tris()
    per: dict[str, dict] = {}
    for _, i in dress.placements[first:]:
        c = per.setdefault(grid.cell_id_at(i.x, i.y), {"tris": 0, "instances": 0, "pieces": set()})
        c["tris"] += VEG_LOD0_TRIS.get(i.piece, sf_tris().get(i.piece, table.get(i.piece, 100)))
        c["instances"] += 1
        c["pieces"].add(i.piece)
    counts["cells"] = {k: {"tris": v["tris"], "instances": v["instances"], "distinct_meshes": len(v["pieces"])}
                       for k, v in sorted(per.items())}
    return counts


def write_assets(cfg: dict, loop: dict, blks: list[dict], road_y: float, out_dir: str, cfg_rel: str) -> list[str]:
    """ROUTE_<asset>.json (2 m samples, the Fort loop route's format) and BLOCKS_<asset>.json (barrier lines: centre,
    heading, width, the way each closes) for Unity's colliders, AI traffic and the minimap."""
    import json
    import os
    dl = cfg["drive_loop"]
    asset = dl.get("asset", "DriveCircle")
    os.makedirs(out_dir, exist_ok=True)
    pts = samples(loop["points"], 2.0)
    common = {"name": dl.get("id", asset), "generator": "tools/city/build_city.py", "config": cfg_rel,
              "attribution": "(c) OpenStreetMap contributors, ODbL 1.0"}
    rpath = os.path.join(out_dir, f"ROUTE_{asset}.json")
    with open(rpath, "w", encoding="utf-8") as fh:
        json.dump({**common, "length_m": round(loop["length_m"], 1), "step_m": 2.0, "road_y": road_y,
                   "closed": loop["closed"], "direction": dl.get("direction", ""),
                   "x": [round(p[0], 2) for p in pts], "z": [round(p[1], 2) for p in pts]}, fh)
    bpath = os.path.join(out_dir, f"BLOCKS_{asset}.json")
    keys = ("id", "way", "name", "highway", "x", "z", "yaw_deg", "width_m", "pavement_m", "kind", "why", "clear_m",
            "pieces", "cones", "collider", "collider_h_m")
    with open(bpath, "w", encoding="utf-8") as fh:
        json.dump({**common, "road_y": road_y, "piece": BARRIER_PIECE,
                   "blocks": [{k: b[k] for k in keys if k in b} for b in blks if b["ok"]]}, fh, indent=1)
    return [rpath, bpath]
