"""P2 roadside set: placement rules for the traffic and seafront pieces (citylib/street_kit.py `traffic()`).

Photos: references/delta-face/streetview_2026-11-16 (sv_03 south roundabout NW plaza, sv_04 barriers, sv_05 seafront
bus shelter, sv_07 kiosk / cones / tuks, sv_09 centre-line barriers, sv_11 cantilever signal masts).

Two entry points, both pure Python (Shapely), unit-tested in tests/test_roadside.py:
- `dress_shelters(cfg, data, lay, out)` runs at the end of `dressing.dress`, before the terrain offsets and before
  `markings.build` (which paints a bus bay at every shelter): the Centre Road kerb halts become land-side booths, a
  multi-bay seafront shelter goes opposite each on the sea-side kerb, and white kiosks stand on the sea-side
  pavement.
- `dress_traffic(cfg, data, lay, dress, marks)` runs after `markings.build` (it needs the centre line, the gores, the
  stop lines and the tuk rank): delineators on the centre line, police barrier runs, cones, signal masts, striped
  pole variants near junction corners, direction / CCTV / crossing / parking / chevron signs, and the patch-repair,
  drain-grate and MAT2 road-wear decals (cracks, crazing, old patches, oil; `road_wear`) added to `marks.quads`.
Config: optional "roadside" block in the city config (defaults below).
"""
from __future__ import annotations

import dataclasses
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from . import geo, markings, paint_atlas
from . import materials as M
from .kit import Instance, _stable_hash
from .layout import _polys

SHELTERS = ("PROP_BusShelter_01", "PROP_BusShelter_Seafront_01", "PROP_BusShelter_Booth_01")
DEFAULTS = {
    "road": "Delta Face Centre Road",
    "kiosk_spacing_m": 260.0,
    "delineator_spacing_m": 8.0,
    "delineator_askew": 0.12,        # share knocked askew (yaw + a lateral nudge)
    "delineator_down": 0.04,         # share knocked flat (PROP_Delineator_02)
    "signal_junction_min_m2": 250.0,
    "corner_radius_m": 28.0,         # striped lamp variants within this of a signal junction
    "patch_every_m": 22.0,
    "patch_share": 0.3,
    "drain_every_m": 25.0,
    "patch_roads": ["Delta Face Centre Road", "Delta Road"],
    "chevron_turn_deg": 18.0,        # heading change over 40 m that counts as a bend
    # MAT2 road wear (RoadPaint row 2 cells, opaque decals on the existing road-paint material: no new draw)
    "wear_every_m": 7.5,             # one try per lane-step; most tries place nothing
    "crack_share": 0.28,             # sealed longitudinal crack along a wheel path
    "alligator_share": 0.08,         # crazed asphalt in a wheel path (more on the junction approaches)
    "patch_b_share": 0.07,           # an older pale patch
    "wear_min_width_m": 5.5,         # lanes narrower than this (service lanes, the walk path) stay clean
    "oil_approach_m": 32.0,          # oil drip lines on the last metres before a junction box ...
    "oil_shelter_m": 16.0,           # ... and along a bus stop
    "oil_every_m": 6.0,
    "oil_share": 0.45,
}


def _cfg(cfg):
    rc = dict(DEFAULTS)
    rc.update(cfg.get("roadside", {}))
    return rc


def _h(x, y, salt=0):
    return _stable_hash(int(round(x * 10)), int(round(y * 10)), salt) / 2**32


def yaw_facing(fx: float, fy: float) -> float:
    """Instance yaw that turns a piece's front (local -y) to face along (fx, fy)."""
    return math.atan2(fx, -fy)


def _foot(x, y, yaw, w, d):
    c, s = math.cos(yaw), math.sin(yaw)
    pts = [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]
    return Polygon([(x + c * a - s * b, y + s * a + c * b) for a, b in pts])


def _infos(cfg, data, lay):
    infos = markings._piece_infos(cfg, data, lay, geo.CITYHUB)
    centre = {n for n, r in cfg.get("dual_carriageways", {}).items() if r.get("centre_line")}
    markings._pair_up(infos, lay, centre)
    return infos


def _sea_side(lay, line, s):
    """+1 if the sea is to the left of `line` at s, else -1."""
    if lay.coast is None:
        return 1.0
    a, b = Point(*markings.at(line, s, 8.0)), Point(*markings.at(line, s, -8.0))
    return 1.0 if lay.coast.distance(a) < lay.coast.distance(b) else -1.0


def _ground_z(lay, x, y):
    h = lay.heights
    return h.plot + (lay.terrain.dz(x, y) if not lay.terrain.empty else 0.0)


def _free(p, taken, r):
    return all(math.hypot(p[0] - q[0], p[1] - q[1]) >= r for q in taken)


# --- before markings: shelters and kiosks ----------------------------------------------------------------

def dress_shelters(cfg, data, lay, out) -> dict:
    rc = _cfg(cfg)
    h = lay.heights
    infos = _infos(cfg, data, lay)
    sea = [i for i in infos if i.piece.name == rc["road"] and i.seaward and i.tline.length > 100]
    if not sea:
        return {}
    blocked = unary_union([lay.road_area.buffer(0.4), lay.parking.buffer(0.3)])
    ground = unary_union([lay.pavement, lay.park]).buffer(0.05)
    taken = [(i.x, i.y) for g, i in out.placements if g in ("Street", "Promenade", "Landmarks")]
    counts = {"booths": 0, "seafront_shelters": 0, "white_kiosks": 0}

    def site(inf, s, out_m, w, d):
        ln = inf.piece.line
        side = _sea_side(lay, ln, s)
        x, y = markings.at(ln, s, side * (inf.piece.width / 2 + out_m))
        t = markings.tangent(ln, s)
        yaw = yaw_facing(t[1] * side, -t[0] * side)          # front to the road: right of the sea-side normal
        foot = _foot(x, y, yaw, w, d)
        if foot.intersects(blocked) or not ground.contains(Point(x, y)) or not _free((x, y), taken, 4.5):
            return None
        return x, y, yaw

    road_poly = unary_union([i.piece.poly for i in infos if i.piece.name == rc["road"]])
    for k, (g, inst) in enumerate(list(out.placements)):
        if inst.piece != "PROP_BusShelter_01" or road_poly.distance(Point(inst.x, inst.y)) > 6.0:
            continue
        # the land-side kerb halt becomes the small booth (sv_12); the seafront shelter goes opposite (sv_05)
        out.placements[k] = (g, dataclasses.replace(inst, piece="PROP_BusShelter_Booth_01"))
        counts["booths"] += 1
        inf = min(sea, key=lambda i: i.piece.line.distance(Point(inst.x, inst.y)))
        s0 = inf.piece.line.project(Point(inst.x, inst.y))
        for ds in (0.0, 12.0, -12.0, 24.0, -24.0, 36.0, -36.0):
            st = site(inf, s0 + ds, 2.6, 7.9, 2.5)
            if st and 20.0 < s0 + ds < inf.piece.line.length - 20.0:
                out.add("Street", Instance("PROP_BusShelter_Seafront_01", st[0], st[1], h.plot, st[2]))
                taken.append(st[:2])
                counts["seafront_shelters"] += 1
                break
    for inf in sea:
        ln = inf.piece.line
        s = 120.0
        while s < ln.length - 60.0:
            for ds in (0.0, 8.0, -8.0, 16.0, -16.0):
                st = site(inf, s + ds, 4.2, 2.9, 2.3)
                if st:
                    out.add("Promenade", Instance("PROP_Kiosk_White_01", st[0], st[1], h.plot, st[2]))
                    taken.append(st[:2])
                    counts["white_kiosks"] += 1
                    break
            s += float(rc["kiosk_spacing_m"])
    return counts


# --- after markings: traffic furniture and surface decals -----------------------------------------------

def _signal_junctions(lay, rc):
    return [jp for jp in _polys(lay.junctions)
            if jp.area >= float(rc["signal_junction_min_m2"]) and lay.area_strip.contains(jp.centroid)]


def _kerb_spot(lay, line, s, side, w, taken, reach=(0.9, 1.4, 2.0, 2.8)):
    for o in reach:
        x, y = markings.at(line, s, side * (w / 2 + o))
        if lay.pavement.contains(Point(x, y)) and lay.road_area.distance(Point(x, y)) > 0.5 and _free((x, y), taken, 1.5):
            return x, y
    return None


def dress_traffic(cfg, data, lay, dress, marks) -> dict:
    rc = _cfg(cfg)
    h = lay.heights
    infos = _infos(cfg, data, lay)
    by_id = {id(i.piece): i for i in infos}
    juncs = _signal_junctions(lay, rc)
    jzone = lay.junctions.buffer(4.0)
    taken = [(i.x, i.y) for g, i in dress.placements if g in ("Street", "Promenade", "Landmarks")]
    counts: dict[str, int] = {}

    def add(piece, x, y, yaw, road=False, group="Street"):
        z = h.road if road else _ground_z(lay, x, y)
        dress.add(group, Instance(piece, x, y, z, yaw))
        taken.append((x, y))
        counts[piece] = counts.get(piece, 0) + 1

    # 1. police barrier runs of 2-4 (sv_04): at the gore clusters, and where the centre line meets a big junction
    runs = []
    gores = [Polygon(q.pts) for q in marks.quads if q.kind == "gore"]
    for cl in _polys(unary_union([g.buffer(2.0) for g in gores])) if gores else []:
        rect = cl.minimum_rotated_rectangle
        cs = list(rect.exterior.coords)[:4]
        e = max(((cs[i], cs[(i + 1) % 4]) for i in range(4)), key=lambda ab: math.dist(*ab))
        runs.append((cl.centroid.x, cl.centroid.y, math.atan2(e[1][1] - e[0][1], e[1][0] - e[0][0])))
    keep_out = []
    for inf in infos:
        st = marks.styles.get(id(inf.piece))
        if not st or not st.centre:
            continue
        ln = inf.piece.line
        off = st.centre * inf.piece.width / 2
        # where the painted line meets a signal junction's box (its ends, or a junction it crosses), a run of
        # barriers carries the divider on, away from the box
        inside = [jzone.contains(Point(*markings.at(ln, float(s), off))) for s in range(int(ln.length) + 1)]
        starts = []
        if not inside[0]:
            starts.append((0.0, 1.0))
        for k in range(1, len(inside)):
            if inside[k - 1] != inside[k]:
                starts.append((float(k), 1.0) if inside[k - 1] else (float(k - 1), -1.0))
        if not inside[-1]:
            starts.append((ln.length, -1.0))
        for s, sgn in starts:
            p = Point(*markings.at(ln, s, off))
            if not any(jp.distance(p) < 12.0 for jp in juncs):
                continue
            n = 2 + int(_h(p.x, p.y, 7) * 3)
            for k in range(n):
                sk = s + sgn * (0.8 + 1.6 * k)
                x, y = markings.at(ln, sk, off)
                t = markings.tangent(ln, sk)
                add("PROP_Barrier_Police_01", x, y, math.atan2(t[1], t[0]), road=True)
            keep_out.append(LineString([markings.at(ln, s, off), markings.at(ln, s + sgn * (1.6 * n + 2.0), off)]).buffer(1.5))
    for cx, cy, a in runs:
        n = 2 + int(_h(cx, cy, 7) * 3)
        for k in range(n):
            o = (k - (n - 1) / 2) * 1.6
            add("PROP_Barrier_Police_01", cx + math.cos(a) * o, cy + math.sin(a) * o, a, road=True)
    counts["barrier_runs"] = len(runs) + len(keep_out)

    # 2. delineators every ~8 m on the painted centre line, some knocked askew or flat (sv_07)
    ko = unary_union(keep_out) if keep_out else Polygon()
    step = float(rc["delineator_spacing_m"])
    for inf in infos:
        st = marks.styles.get(id(inf.piece))
        if not st or not st.centre:
            continue
        ln = inf.piece.line
        off = st.centre * inf.piece.width / 2
        s = step / 2
        while s < ln.length - 2.0:
            x, y = markings.at(ln, s, off)
            p = Point(x, y)
            if not jzone.contains(p) and not ko.contains(p):
                t = markings.tangent(ln, s)
                yaw = math.atan2(t[1], t[0])
                r = _h(x, y, 11)
                if r < float(rc["delineator_down"]):
                    add("PROP_Delineator_02", x, y, yaw + (_h(x, y, 12) - 0.5) * 5.0, road=True)
                elif r < float(rc["delineator_down"]) + float(rc["delineator_askew"]):
                    nud = (_h(x, y, 13) - 0.5) * 0.6
                    add("PROP_Delineator_01", x - t[1] * nud, y + t[0] * nud, yaw + (_h(x, y, 14) - 0.5) * 2.0, road=True)
                else:
                    add("PROP_Delineator_01", x, y, yaw, road=True)
            s += step

    # 3. cones at both ends of the tuk rank, on its traffic side (sv_07)
    rank = [sp for sp in marks.spawns if sp.get("group") == "tuk_rank"]
    if len(rank) >= 2:
        a, b = rank[0], rank[-1]
        L = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) or 1.0
        fx, fy = (b["x"] - a["x"]) / L, (b["y"] - a["y"]) / L
        q = lay.road_area.boundary.interpolate(lay.road_area.boundary.project(Point(a["x"], a["y"])))
        nx, ny = -fy, fx
        if nx * (q.x - a["x"]) + ny * (q.y - a["y"]) < 0:
            nx, ny = -nx, -ny
        for (ex, ey), sgn in (((a["x"], a["y"]), -1.0), ((b["x"], b["y"]), 1.0)):
            for k, along in enumerate((2.8, 4.2, 5.6)):
                x = ex + fx * sgn * along + nx * (1.0 + 0.3 * k)
                y = ey + fy * sgn * along + ny * (1.0 + 0.3 * k)
                add("PROP_TrafficCone_01", x, y, _h(x, y, 3) * 6.28, road=True)

    # 4. cantilever signal masts (sv_11): before every stop line, and on both approaches of the other signal
    # junctions on the centre-line road; on the left (outer) kerb, the arm over the lanes
    approaches = []
    for sl in marks.stats.get("stop_lines", []):
        inf = by_id.get(sl.get("piece"))
        if sl.get("kind") == "stop" and inf is not None:
            approaches.append((inf, inf.tline.project(Point(sl["x"], sl["y"])) - 1.5))
    for jp in juncs:
        if any(jp.distance(Point(sl["x"], sl["y"])) < 15 for sl in marks.stats.get("stop_lines", [])):
            continue
        r = math.sqrt(jp.area / math.pi)
        for inf in infos:
            if inf.piece.name == rc["road"] and inf.oneway and inf.tline.distance(jp.centroid) < 12.0:
                approaches.append((inf, inf.tline.project(jp.centroid) - r - 3.0))
    masts = []
    for inf, s in approaches:
        if s < 5.0:
            continue
        spot = _kerb_spot(lay, inf.tline, s, 1.0, inf.piece.width, taken)
        if spot is None or not _free(spot, masts, 10.0):
            continue
        t = markings.tangent(inf.tline, s)
        add("PROP_SignalMast_01", spot[0], spot[1], math.atan2(-t[0], t[1]))
        masts.append(spot)

    # 5. striped feet near junction corners (sv_03): every traffic light, kerb lamps by a signal junction
    near = unary_union([jp.buffer(float(rc["corner_radius_m"])) for jp in juncs]) if juncs else Polygon()
    swap = {"PROP_TrafficLight_01": "PROP_TrafficLight_02", "PROP_StreetLamp_SingleArm_01": "PROP_StreetLamp_SingleArm_02"}
    for k, (g, inst) in enumerate(dress.placements):
        if inst.piece in swap and (inst.piece == "PROP_TrafficLight_01" or near.contains(Point(inst.x, inst.y))):
            dress.placements[k] = (g, dataclasses.replace(inst, piece=swap[inst.piece]))
            counts[swap[inst.piece]] = counts.get(swap[inst.piece], 0) + 1

    # 6. corner signs at each signal junction: the direction sign at the NW corner of a stop-line junction, CCTV
    # poles at the NW and SE corners (sv_03)
    for jp in juncs:
        c = jp.centroid
        cand = []
        for k in range(72):
            a = math.radians(k * 5.0)
            for r in (14.0, 18.0, 22.0, 26.0):
                x, y = c.x + math.cos(a) * r, c.y + math.sin(a) * r
                d = lay.road_area.distance(Point(x, y))
                if lay.pavement.contains(Point(x, y)) and 1.2 < d < 3.0 and _free((x, y), taken, 3.0):
                    cand.append((x, y))
        if not cand:
            continue

        def facing(x, y):
            q = lay.road_area.boundary.interpolate(lay.road_area.boundary.project(Point(x, y)))
            return yaw_facing(q.x - x, q.y - y)

        nw = max(cand, key=lambda p: (p[1] - c.y) - (p[0] - c.x))
        se = max(cand, key=lambda p: (p[0] - c.x) - (p[1] - c.y))
        if any(jp.distance(Point(sl["x"], sl["y"])) < 15 for sl in marks.stats.get("stop_lines", [])):
            add("PROP_Sign_Direction_01", nw[0], nw[1], facing(*nw))
            rest = [p for p in cand if math.dist(p, nw) > 6.0 and _free(p, taken, 3.0)]
            nw2 = max(rest, key=lambda p: (p[1] - c.y) - (p[0] - c.x)) if rest else None
            if nw2:
                add("PROP_CCTVPole_01", nw2[0], nw2[1], facing(*nw2))
        else:
            add("PROP_CCTVPole_01", nw[0], nw[1], facing(*nw))
        if math.dist(se, nw) > 10.0 and _free(se, taken, 3.0):
            add("PROP_CCTVPole_01", se[0], se[1], facing(*se))

    # 7. pedestrian-crossing signs at both ends of every zebra, facing the traffic that meets them
    for g, z in list(dress.placements):
        if z.piece != "KIT_RoadMarking_Zebra_A":
            continue
        lx, ly = math.cos(z.rot), math.sin(z.rot)
        w = z.sx * 7.5
        for o, sgn in ((-1.2, 1.0), (w + 1.2, -1.0)):
            x, y = z.x + lx * o + ly * 1.8 * sgn, z.y + ly * o - lx * 1.8 * sgn
            if lay.pavement.contains(Point(x, y)) and _free((x, y), taken, 1.5):
                add("PROP_Sign_PedCrossing_01", x, y, yaw_facing(ly * sgn, -lx * sgn))

    # 8. parking plates at the ends of the angled bay run (sv_08), no-parking plates beside every bus bay
    bays = [q for q in marks.quads if q.kind == "bay"]
    if bays:
        for q in (bays[0], bays[len(bays) // 2], bays[-1]):
            (ax, ay), (bx, by) = q.pts[0], q.pts[1]
            far = ((q.pts[1][0] + q.pts[2][0]) / 2, (q.pts[1][1] + q.pts[2][1]) / 2)
            near_ = ((q.pts[0][0] + q.pts[3][0]) / 2, (q.pts[0][1] + q.pts[3][1]) / 2)
            dx, dy = far[0] - near_[0], far[1] - near_[1]
            dl = math.hypot(dx, dy) or 1.0
            x, y = far[0] + dx / dl * 0.8, far[1] + dy / dl * 0.8
            if not lay.road_area.contains(Point(x, y)) and _free((x, y), taken, 1.5):
                add("PROP_Sign_Parking_01", x, y, yaw_facing(-dx, -dy))
    for bb in marks.stats.get("bus_bays", []):
        p = Point(bb["x"], bb["y"])
        inf = min(infos, key=lambda i: i.piece.poly.distance(p))
        ln = inf.piece.line
        s = ln.project(p)
        side = 1.0 if markings.tangent(ln, s)[0] * (p.y - ln.interpolate(s).y) - markings.tangent(ln, s)[1] * (p.x - ln.interpolate(s).x) > 0 else -1.0
        for ds in (-8.5, 8.5):
            spot = _kerb_spot(lay, ln, s + ds, side, inf.piece.width, taken, (0.5, 0.8, 1.2))
            if spot:
                t = markings.tangent(ln, s)
                add("PROP_Sign_NoParking_01", spot[0], spot[1], yaw_facing(-t[1] * side, t[0] * side))

    # 9. curve chevrons: on each roundabout island facing every entry, and on the outside of the centre-line
    # road's bends (sv_15; Centre Road itself has none sharper than chevron_turn_deg)
    for rb in marks.stats.get("roundabouts", []):
        for sl in marks.stats.get("stop_lines", []):
            dx, dy = sl["x"] - rb["x"], sl["y"] - rb["y"]
            dl = math.hypot(dx, dy)
            if sl.get("kind") != "giveway" or dl > rb["r"] + 25.0 or dl < 1.0:
                continue
            for back in (0.8, 1.5, 2.5, 3.5):
                ri = rb["r"] - rb["w"] / 2 - back
                x, y = rb["x"] + dx / dl * ri, rb["y"] + dy / dl * ri
                if lay.road_area.distance(Point(x, y)) > 0.4 and _free((x, y), taken, 2.0):
                    add("PROP_Sign_Chevron_01", x, y, yaw_facing(dx, dy))
                    break
    turn = math.radians(float(rc["chevron_turn_deg"]))
    for inf in infos:
        if inf.piece.name != rc["road"] or not inf.seaward or inf.tline.length < 60:
            continue
        ln = inf.tline
        s = 20.0
        while s < ln.length - 20.0:
            t0, t1 = markings.tangent(ln, s - 20.0), markings.tangent(ln, s + 20.0)
            cr = t0[0] * t1[1] - t0[1] * t1[0]
            if abs(math.asin(max(-1.0, min(1.0, cr)))) > turn:
                outer = -1.0 if cr > 0 else 1.0                 # turning left: the outside is the right kerb
                for k in (-6.0, 0.0, 6.0):
                    spot = _kerb_spot(lay, ln, s + k, outer, inf.piece.width, taken, (0.6, 1.0, 1.6))
                    if spot:
                        t = markings.tangent(ln, s + k)
                        add("PROP_Sign_Chevron_01", spot[0], spot[1], yaw_facing(-t[0], -t[1]))
                s += 40.0
            s += 5.0

    # 10. surface decals: patch repairs in the lanes (RoadPaint PATCH cell) and drain grates at the kerb (trim)
    rect = paint_atlas.uv_rect("PATCH")
    pw, pl = paint_atlas.SIZE_M["PATCH"]
    road_ok = lay.road_area.buffer(-0.3)
    for inf in infos:
        if inf.piece.name not in rc["patch_roads"]:
            continue
        ln, w = inf.piece.line, inf.piece.width
        lanes = max(1, inf.lanes)
        s = 6.0
        while s < ln.length - 6.0:
            x0, y0 = markings.at(ln, s)
            if _h(x0, y0, 21) < float(rc["patch_share"]):
                lane = int(_h(x0, y0, 22) * lanes)
                off = -w / 2 + (lane + 0.5) * w / lanes + (_h(x0, y0, 23) - 0.5) * 0.8
                x, y = markings.at(ln, s, off)
                q = markings.oriented_quad(x, y, markings.tangent(ln, s), pl * (0.6 + 0.6 * _h(x, y, 24)), pw,
                                           rect, M.ROAD_PAINT, "patch")
                if road_ok.contains(Polygon(q.pts)) and not jzone.intersects(Polygon(q.pts)):
                    marks.quads.append(q)
                    counts["patch"] = counts.get("patch", 0) + 1
            s += float(rc["patch_every_m"])
        s = 10.0
        while s < ln.length - 10.0:
            for side in (-1.0, 1.0):
                if inf.inboard and side == inf.inboard:
                    continue                                    # no gutter on the centre-line side
                x, y = markings.at(ln, s, side * (w / 2 - 0.28))
                t = markings.tangent(ln, s)                     # trim u runs along the kerb: fwd is across
                q = markings.oriented_quad(x, y, (-t[1], t[0]), 0.45, 0.8, (0.40, 0.78, 0.60, 0.97),
                                           M.STREET_TRIM, "drain")
                if lay.road_area.buffer(0.05).contains(Polygon(q.pts)) and not jzone.intersects(Polygon(q.pts)):
                    marks.quads.append(q)
                    counts["drain"] = counts.get("drain", 0) + 1
            s += float(rc["drain_every_m"])
    road_wear(rc, infos, lay, jzone, dress, marks, counts)
    marks.stats["roadside"] = counts
    marks.paver_zones = paver_zones(cfg, lay, infos, juncs, marks)
    return counts


WHEEL_PATH_M = 0.75   # wheel paths sit 0.75 m either side of a lane's centre (asphalt tile: 1.0 and 2.5 of 3.5 m)


def road_wear(rc, infos, lay, jzone, dress, marks, counts) -> int:
    """MAT2 road wear decals (paint_atlas row 2) by rule, deterministic (position hashes):
    - cracks and crazing follow the wheel paths, where the load is (crazing twice as likely near junction boxes);
    - an older pale patch now and then in a lane;
    - oil drip lines down the lane centre on junction approaches and along bus stops, where vehicles stand.
    Opaque quads on MAT_RoadPaint_A that never overlap another marking or each other (no stacked overdraw; on the
    PowerVR Low GPU hidden-surface removal shades only the top opaque layer). Returns the number placed."""
    from shapely.strtree import STRtree
    road_ok = lay.road_area.buffer(-0.3)
    approach = jzone.buffer(float(rc["oil_approach_m"])).difference(jzone)
    stops = [(i.x, i.y) for g, i in dress.placements if i.piece in SHELTERS]
    near_stop = unary_union([Point(p).buffer(float(rc["oil_shelter_m"])) for p in stops]) if stops else None
    taken = [Polygon(q.pts) for q in marks.quads]
    tree = STRtree(taken) if taken else None
    placed: list[Polygon] = []
    n0 = len(marks.quads)

    def free(poly) -> bool:
        if not road_ok.contains(poly) or jzone.intersects(poly):
            return False
        if tree is not None and any(taken[i].intersects(poly) for i in tree.query(poly)):
            return False
        return not any(p.intersects(poly) for p in placed)

    def put(name, x, y, fwd, scale) -> None:
        w, l_ = paint_atlas.SIZE_M[name]
        q = markings.oriented_quad(x, y, fwd, l_ * scale, w * scale, paint_atlas.uv_rect(name), M.ROAD_PAINT,
                                   name.lower())
        poly = Polygon(q.pts)
        if free(poly):
            marks.quads.append(q)
            placed.append(poly)
            counts[name.lower()] = counts.get(name.lower(), 0) + 1

    for inf in infos:
        ln, w = inf.piece.line, inf.piece.width
        lanes = max(1, inf.lanes)
        if w / lanes < 2.6 or w < float(rc["wear_min_width_m"]):
            continue
        for lane in range(lanes):
            centre = -w / 2 + (lane + 0.5) * w / lanes
            s = 4.0 + 5.0 * _h(ln.coords[0][0], ln.coords[0][1], 30 + lane)
            while s < ln.length - 4.0:
                x0, y0 = markings.at(ln, s, centre)
                fwd = markings.tangent(ln, s)
                r = _h(x0, y0, 31)
                side = WHEEL_PATH_M if _h(x0, y0, 32) < 0.5 else -WHEEL_PATH_M
                near_j = approach.contains(Point(x0, y0))
                crack, alli = float(rc["crack_share"]), float(rc["alligator_share"]) * (2.0 if near_j else 1.0)
                if r < crack:
                    put("CRACK", *markings.at(ln, s, centre + side), fwd, 0.7 + 0.6 * _h(x0, y0, 33))
                elif r < crack + alli:
                    put("ALLIGATOR", *markings.at(ln, s, centre + side * 0.8), fwd, 0.8 + 0.4 * _h(x0, y0, 34))
                elif r < crack + alli + float(rc["patch_b_share"]):
                    put("PATCH_B", *markings.at(ln, s, centre + (_h(x0, y0, 35) - 0.5) * 0.6), fwd,
                        0.7 + 0.5 * _h(x0, y0, 36))
                s += float(rc["wear_every_m"]) * (0.7 + 0.6 * _h(x0, y0, 37))
            # oil: down the lane centre where vehicles wait
            s = 3.0
            while s < ln.length - 3.0:
                x, y = markings.at(ln, s, centre + (_h(s, lane, 38) - 0.5) * 0.3)
                pt = Point(x, y)
                waits = approach.contains(pt) or (near_stop is not None and near_stop.contains(pt))
                if waits and _h(x, y, 39) < float(rc["oil_share"]):
                    put("OIL", x, y, markings.tangent(ln, s), 0.7 + 0.6 * _h(x, y, 40))
                s += float(rc["oil_every_m"])
    return len(marks.quads) - n0


def paver_zones(cfg, lay, infos, juncs, marks):
    """(seafront, plaza) areas for citylib/cells.py: the seafront running bond on the sea side of the centre-line
    road (kerb to 14 m out), the 45 degree plaza in the NW quarter (30 m) of every junction with stop lines."""
    rc = _cfg(cfg)
    sea = []
    for inf in infos:
        if inf.piece.name != rc["road"] or not inf.seaward:
            continue
        ln = inf.piece.line
        side = _sea_side(lay, ln, ln.length / 2)
        sea.append(ln.buffer(side * (inf.piece.width / 2 + 14.0), single_sided=True))
    plaza = []
    stops = [Point(s["x"], s["y"]) for s in marks.stats.get("stop_lines", []) if s.get("kind") == "stop"]
    for jp in juncs:
        if not any(jp.distance(p) < 15.0 for p in stops):
            continue
        c = jp.centroid
        quarter = Polygon([(c.x + 5, c.y - 5), (c.x - 40, c.y - 5), (c.x - 40, c.y + 40), (c.x + 5, c.y + 40)])
        plaza.append(c.buffer(30.0).intersection(quarter))
    return unary_union(sea) if sea else Polygon(), unary_union(plaza) if plaza else Polygon()
