"""Dress the layout with instanced kit pieces and props (TDD "The city pipeline", step 3).

Rules come from OSM where it has the data (crossings, groynes, piers, roundabouts) and from the
config where it does not (which roads get median lamps and palms, where the food carts gather).
Every placement is deterministic: hashes of positions and ids, never random().
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

from shapely import ops
from shapely.geometry import LineString, Point, Polygon

from . import geo, heroes, osm, pavement_edge, props, rules, vegetation
from .kit import Instance, _stable_hash, bays_for_edge
from .carts import ON_CART, cart_set, to_world as cart_to_world
from .layout import Layout, _polys, clean, override_ways


@dataclass
class Dressing:
    placements: list[tuple[str, Instance]] = field(default_factory=list)  # (group, world-space instance)
    piers: list[Polygon] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, group: str, inst: Instance) -> None:
        self.placements.append((group, inst))


def _hash01(*vals: float) -> float:
    return _stable_hash(*(int(round(v * 100)) for v in vals)) / 2**32


def _along(line: LineString, step: float, start: float = 0.0):
    """Points, unit tangents and distances every `step` metres along a line."""
    d = start
    while d <= line.length:
        p = line.interpolate(d)
        a = line.interpolate(max(0.0, d - 1.0))
        b = line.interpolate(min(line.length, d + 1.0))
        tx, ty = b.x - a.x, b.y - a.y
        tl = math.hypot(tx, ty) or 1.0
        yield (p.x, p.y), (tx / tl, ty / tl), d
        d += step


def _chord_dev(line: LineString, d0: float, length: float) -> float:
    """Largest distance (m) between a line and the straight chord from d0 to d0 + length along it."""
    a, b = line.interpolate(d0), line.interpolate(d0 + length)
    chord = LineString([a, b])
    n = max(2, int(length))
    return max(chord.distance(line.interpolate(d0 + length * k / n)) for k in range(n + 1))


def _terrace_steps_continuous(out, lay: Layout, dcfg: dict, rise: float, z: float) -> None:
    """P117 critic (gf_10, gf_12): the seating steps run the whole Green / promenade edge, broken only by short gaps
    with a bin set or a stone bench, not one 24 m run every 60 m. The terrace segments are merged into lines, then
    each line is walked: a 24 m KIT_Steps_TerraceLong_A where the edge is straight over 24 m (chord within
    terrace_steps_chord_tol_m), else 6 m KIT_Steps_Terrace_A pieces, skipping bends; after terrace_steps_run_m of
    steps a terrace_steps_gap_m gap. Low cost: 96 tris per piece, kit material, no new draw call per cell."""
    prom = lay.promenade
    segs = [LineString([p0, p1]) for p0, p1 in lay.terrace if math.dist(p0, p1) > 1e-3]
    if not segs:
        return
    merged = ops.linemerge(segs)
    run_m = float(dcfg.get("terrace_steps_run_m", 24.0))
    gap_m = float(dcfg.get("terrace_steps_gap_m", 6.0))
    tol = float(dcfg.get("terrace_steps_chord_tol_m", 0.35))
    scale = rise / props.TERRACE_H
    gaps = 0
    for line in getattr(merged, "geoms", [merged]):
        if line.length < 7.0:
            continue
        m0, m1 = line.interpolate(line.length / 2 - 0.5), line.interpolate(line.length / 2 + 0.5)
        tx, ty = m1.x - m0.x, m1.y - m0.y
        tl = math.hypot(tx, ty) or 1.0
        if not prom.contains(Point(m0.x + ty / tl * 1.5, m0.y - tx / tl * 1.5)):
            line = LineString(list(line.coords)[::-1])      # the promenade on the right: the kit's -y side faces it
        d, placed = 0.5, 0.0
        while d + 6.0 <= line.length - 0.5:
            if placed >= run_m - 1e-6:
                g = line.interpolate(d + gap_m / 2)
                q = line.interpolate(min(line.length, d + gap_m / 2 + 1.0))
                ux, uy = q.x - g.x, q.y - g.y
                ul = math.hypot(ux, uy) or 1.0
                ux, uy = ux / ul, uy / ul
                piece, off = ("PROP_Bench_StoneWall_01", 3.0) if gaps % 2 else ("PROP_Bin_Set_01", 1.2)
                if prom.contains(Point(g.x + uy * off, g.y - ux * off)):
                    out.add("Promenade", Instance(piece, g.x + uy * off, g.y - ux * off, z, math.atan2(uy, ux)))
                gaps += 1
                d, placed = d + gap_m, 0.0
                continue
            for length, piece in ((24.0, "KIT_Steps_TerraceLong_A"), (6.0, "KIT_Steps_Terrace_A")):
                if length > 6.0 and (placed > 0.0 or run_m < 24.0 or d + length > line.length - 0.5):
                    continue
                if _chord_dev(line, d, length) <= tol:
                    a, b = line.interpolate(d), line.interpolate(d + length)
                    out.add("Promenade", Instance(piece, a.x, a.y, z, math.atan2(b.y - a.y, b.x - a.x), 1.0, 1.0, scale))
                    d, placed = d + length, placed + length
                    break
            else:
                d += 1.0                                       # a bend: no piece fits, step past it


def _ray_hit(origin, direction, targets, near: float, far: float):
    """Distance to the first target line hit by a ray between near and far, or None."""
    ox, oy = origin
    ray = LineString([(ox + direction[0] * near, oy + direction[1] * near),
                      (ox + direction[0] * far, oy + direction[1] * far)])
    hit = ray.intersection(targets)
    if hit.is_empty:
        return None
    pts = [hit] if hit.geom_type == "Point" else [g for g in getattr(hit, "geoms", []) if g.geom_type == "Point"]
    if not pts:
        return None
    return min(math.hypot(p.x - ox, p.y - oy) for p in pts)


def dress(cfg: dict, data: osm.OsmData, lay: Layout, tm=geo.CITYHUB) -> Dressing:
    h = lay.heights
    out = Dressing()
    land = lay.land
    dcfg = cfg.get("dressing", {})

    # --- seawall: battered rubble bays along every beach edge, beach on the piece's outer side -----
    run = 0.0
    next_steps = float(dcfg.get("steps_every_m", 110.0)) / 2
    for p0, p1, top in lay.seawall:
        (ax, ay), (bx, by) = p1, p0  # reversed: the beach is left of p0->p1, the kit's outer side is right
        length = math.hypot(bx - ax, by - ay)
        if length < 0.05:
            continue
        ux, uy = (bx - ax) / length, (by - ay) / length
        rot = math.atan2(uy, ux)
        n, sx = bays_for_edge(length, 4.0)
        step = length / n
        for k in range(n):
            x0_, y0_ = ax + ux * step * k, ay + uy * step * k
            variant = "ABC"[_stable_hash(int(x0_ * 10), int(y0_ * 10), 5) % 3]   # three rubble bays (TDD seawall kit)
            out.add("Seawall", Instance(f"KIT_Seawall_Rubble_{variant}", x0_, y0_, top - props.SEAWALL_H, rot, sx))
        if top >= h.promenade - 1e-6 and length >= 4.0 and run + length >= next_steps:
            t = (length - 3.0) / 2
            out.add("Seawall", Instance("KIT_SeawallSteps_A", ax + ux * t, ay + uy * t, top - props.STEPS_H, rot))
            next_steps = run + length + float(dcfg.get("steps_every_m", 110.0))
        run += length

    # --- groynes and revetments: armour stone along OSM lines -----------------------------------
    rock_lines = [w for w in osm.lines(data, lambda t: t.get("man_made") in ("groyne", "breakwater", "revetment")
                                       and t.get("natural") != "coastline")]
    for w in rock_lines:
        pts = [tm.forward(*c) for c in data.coords(w.node_ids)]
        if len(pts) < 2:
            continue
        line = LineString(pts).intersection(lay.area_strip)
        for part in getattr(line, "geoms", [line]):
            if part.is_empty or part.geom_type != "LineString":
                continue
            for (x, y), (tx, ty), d in _along(part, 1.8):
                for side in (-1.0, 1.0):
                    hsh = _hash01(x, y, side)
                    s = 0.8 + 0.5 * hsh
                    out.add("Coast", Instance("KIT_Revetment_Rock_A", x - ty * side * 0.9, y + tx * side * 0.9,
                                              -0.3, hsh * 6.283, s, s, s))

    # --- piers: KIT_Pier_Pedestrian_A modules along each OSM pier's long axis, from the land end out --
    pier_roots, hero_pier_roots = [], []
    for ar in osm.areas(data, lambda t: t.get("man_made") == "pier"):
        ring = [tm.forward(*c) for c in data.coords(ar.outers[0])]
        if len(ring) < 4:
            continue
        poly = clean(Polygon(ring))
        if poly.is_empty or not poly.intersects(lay.area_strip):
            continue
        cs = list(poly.minimum_rotated_rectangle.exterior.coords)[:4]
        e0, e1 = math.dist(cs[0], cs[1]), math.dist(cs[1], cs[2])
        if e1 > e0:
            cs = cs[1:] + cs[:1]
            e0, e1 = e1, e0
        ends = [((cs[0][0] + cs[3][0]) / 2, (cs[0][1] + cs[3][1]) / 2), ((cs[1][0] + cs[2][0]) / 2, (cs[1][1] + cs[2][1]) / 2)]
        if land.distance(Point(ends[0])) > land.distance(Point(ends[1])):
            ends.reverse()
        (ax, ay), (bx, by) = ends
        ln = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / ln, (by - ay) / ln
        n = max(1, round(ln / 4.0))
        sy = max(0.8, min(2.0, e1 / 3.0))
        if any(math.dist(r, (ax, ay)) < 8.0 for r in heroes.replaced_piers(cfg)):
            # modelled as a hero (citylib/hero_pier.py): no kit modules and no boulder spill; the hero brings the
            # flat dark rock shelf the stem stands on (pier_01, pier_02: a shelf under the surf, not boulders)
            hero_pier_roots.append((ax, ay))
            n = 0
        for k in range(n):
            out.add("Coast", Instance("KIT_Pier_Pedestrian_A", ax + ux * ln * k / n, ay + uy * ln * k / n,
                                      h.promenade, math.atan2(uy, ux), ln / (n * 4.0), sy))
        out.piers.append(poly)
        pier_roots.append(((ax, ay), (ux, uy)))

    # --- zebra crossings on carriageways --------------------------------------------------------
    overrides = cfg.get("road_overrides", {})
    crossings: set[int] = set()
    tagged = {nid for nid, t in data.node_tags.items() if t.get("highway") == "crossing"}
    for w in (w for w in override_ways(data, overrides) if rules.is_carriageway(w.tags)):
        tags = w.tags
        width = rules.road_width(tags)
        for i, nid in enumerate(w.node_ids):
            if nid not in tagged or nid in crossings or nid not in data.nodes:
                continue
            x, y = tm.forward(*data.nodes[nid])
            if not land.contains(Point(x, y)) or lay.junctions.contains(Point(x, y)):
                continue
            a = data.nodes[w.node_ids[max(0, i - 1)]]
            b = data.nodes[w.node_ids[min(len(w.node_ids) - 1, i + 1)]]
            (ax, ay), (bx, by) = tm.forward(*a), tm.forward(*b)
            tl = math.hypot(bx - ax, by - ay) or 1.0
            tx, ty = (bx - ax) / tl, (by - ay) / tl
            lx, ly = -ty, tx  # across the road
            ox = x - lx * width / 2 + tx * 1.5
            oy = y - ly * width / 2 + ty * 1.5
            out.add("Street", Instance("KIT_RoadMarking_Zebra_A", ox, oy, h.road, math.atan2(ly, lx), width / 7.5))
            crossings.add(nid)

    # P117 critic (s6 vs sv_04): crossings and barrier lines the OSM data lacks, from config with a source each.
    # extra_crossings [{road, near: [x, y]}]: a zebra across the nearest piece of that road at the projected point;
    # barrier_lines [{at: [x, y], yaw_deg, count}]: red barriers end to end (1.6 m) along yaw, on the road.
    for xc in dcfg.get("extra_crossings", []):
        cand = [r for r in lay.roads if r.name == xc["road"]]
        if not cand:
            continue
        pt = Point(*xc["near"])
        r = min(cand, key=lambda r_: r_.line.distance(pt))
        s_ = r.line.project(pt)
        q0, q1 = r.line.interpolate(max(0.0, s_ - 1.0)), r.line.interpolate(min(r.line.length, s_ + 1.0))
        q = r.line.interpolate(s_)
        tl = math.hypot(q1.x - q0.x, q1.y - q0.y) or 1.0
        tx, ty = (q1.x - q0.x) / tl, (q1.y - q0.y) / tl
        lx, ly = -ty, tx
        out.add("Street", Instance("KIT_RoadMarking_Zebra_A", q.x - lx * r.width / 2, q.y - ly * r.width / 2, h.road,
                                   math.atan2(ly, lx), r.width / 7.5))
    for bl in dcfg.get("barrier_lines", []):
        yaw = math.radians(float(bl.get("yaw_deg", 0.0)))
        n = int(bl.get("count", 4))
        for k in range(n):
            d = (k - (n - 1) / 2) * 1.62
            out.add("Street", Instance("PROP_Barrier_Police_01", bl["at"][0] + math.cos(yaw) * d,
                                       bl["at"][1] + math.sin(yaw) * d, h.road, yaw))

    # --- median lamps and roadside palms --------------------------------------------------------
    def lines_named(name):
        return [r.line for r in lay.roads if r.name == name]

    lamps = []
    for name in dcfg.get("median_lamp_roads", []):
        group = lines_named(name)
        if len(group) < 1:
            continue
        union = ops.unary_union(group)
        for line in group:
            for (x, y), (tx, ty), d in _along(line, float(dcfg.get("lamp_spacing_m", 32.0)), 8.0):
                for side in (-1.0, 1.0):
                    lx, ly = -ty * side, tx * side
                    hit = _ray_hit((x, y), (lx, ly), union, 4.0, 30.0)
                    if hit is None:
                        continue
                    mx, my = x + lx * hit / 2, y + ly * hit / 2
                    if lay.road_area.contains(Point(mx, my)) or any(math.hypot(mx - px, my - py) < 18.0 for px, py in lamps):
                        continue
                    lamps.append((mx, my))
                    out.add("Street", Instance("PROP_StreetLamp_DoubleArm_01", mx, my, h.plot, math.atan2(ly, lx)))

    palms = []
    street_furniture = []
    coast = lay.coast
    for name in dcfg.get("palm_roads", []):
        group = lines_named(name)
        union = ops.unary_union(group) if group else None
        widths = {id(r.line): r.width for r in lay.roads if r.name == name}
        for line in group:
            w = widths.get(id(line), 7.0)
            for (x, y), (tx, ty), d in _along(line, float(dcfg.get("palm_spacing_m", 11.0)), 4.0):
                best = None
                for side in (-1.0, 1.0):
                    lx, ly = -ty * side, tx * side
                    px, py = x + lx * (w / 2 + 1.7), y + ly * (w / 2 + 1.7)
                    dist = coast.distance(Point(px, py)) if coast is not None else 0.0
                    if best is None or dist > best[0]:
                        best = (dist, px, py, lx, ly)
                _, px, py, lx, ly = best
                if _ray_hit((x, y), (lx, ly), union, 3.0, 30.0) is not None:
                    continue  # another carriageway further inland: this side is the median
                if not lay.pavement.contains(Point(px, py)) or lay.road_area.distance(Point(px, py)) < 0.8:
                    continue
                if any(math.hypot(px - qx, py - qy) < 6.0 for qx, qy in palms + lamps):
                    continue
                palms.append((px, py))
                slot = len(palms)
                if slot % 3 == 0 and lay.pavement.contains(Point(x + lx * (w / 2 + 0.7), y + ly * (w / 2 + 0.7))):
                    # Delta Road edge (gf_21, gf_24, gf_25): galvanised single-arm lamp at the kerb, arm over the road
                    qx, qy = x + lx * (w / 2 + 0.7) + tx * 5.5, y + ly * (w / 2 + 0.7) + ty * 5.5
                    out.add("Street", Instance("PROP_StreetLamp_SingleArm_01", qx, qy, h.plot, math.atan2(-ly, -lx)))
                    street_furniture.append((qx, qy))
                if slot % int(dcfg.get("bus_halt_every_palms", 28)) == 14:
                    bx, by = x + lx * (w / 2 + 2.6) - tx * 4.0, y + ly * (w / 2 + 2.6) - ty * 4.0
                    if lay.pavement.contains(Point(bx, by)):
                        # bus halt facing the road (style frame), its back to the buildings
                        out.add("Street", Instance("PROP_BusShelter_01", bx, by, h.plot, math.atan2(ty, tx) + math.pi))
                        street_furniture.append((bx, by))
                # V4: coconut palm variants (citylib/vegetation.py), leaning away from the carriageway
                yaw = vegetation.lean_towards(px, py, px + lx, py + ly, 0.9)
                out.add(vegetation.GROUP, vegetation.place(vegetation.pick(vegetation.ROAD_PALMS, px, py), px, py, h.plot, yaw))

    # Centre Road is two-way 2 + 2 with no median (Delta Face Street Catalogue §6, sv_06/sv_13/sv_15): a single-arm lamp
    # on each kerb, arm over the lane, the two kerbs staggered by half the spacing.
    kl = dcfg.get("kerb_lamp_roads", {})
    for name in kl.get("names", []):
        union = ops.unary_union(lines_named(name)) if lines_named(name) else None
        for r in (r for r in lay.roads if r.name == name):
            for side in (-1.0, 1.0):
                for (x, y), (tx, ty), d in _along(r.line, float(kl.get("spacing_m", 37.0)), 8.0):
                    lx, ly = -ty * side, tx * side
                    if _ray_hit((x, y), (lx, ly), union, 0.5 + r.width / 2, 30.0) is not None:
                        continue                      # that side faces the other carriageway
                    sea = coast is not None and coast.distance(Point(x + lx * 12, y + ly * 12)) < coast.distance(Point(x, y))
                    if sea != (int(d // float(kl.get("spacing_m", 37.0))) % 2 == 0):
                        continue                      # stagger: sea kerb on even slots, inland kerb on odd slots
                    qx, qy = x + lx * (r.width / 2 + 0.7), y + ly * (r.width / 2 + 0.7)
                    ok = lay.pavement.union(lay.promenade).contains(Point(qx, qy)) and lay.junctions.distance(Point(qx, qy)) > 6.0
                    if not ok or any(math.hypot(qx - px, qy - py) < 5.0 for px, py in palms + lamps):
                        continue
                    lamps.append((qx, qy))
                    out.add("Street", Instance("PROP_StreetLamp_SingleArm_01", qx, qy, h.plot, math.atan2(-ly, -lx)))

    delta_lamps = sum(1 for g, i in out.placements if i.piece == "PROP_StreetLamp_SingleArm_01")
    # --- other streets (route extension): kerb lamps and shade trees on the pavement --------------
    sr = dcfg.get("street_roads", {})
    street_trees = []
    if sr:
        names = set(sr.get("names", []))
        lamp_step = float(sr.get("lamp_spacing_m", 33.0))
        tree_step = float(sr.get("tree_spacing_m", 22.0))
        lake_probe = lay.lake.buffer(18.0) if not lay.lake.is_empty else None
        base = lay.base_area_strip.buffer(-1.0) if lay.base_area_strip is not None else Polygon()
        taken = palms + lamps + street_furniture
        for r in lay.roads:
            if r.name not in names:
                continue
            w = r.width
            for (x, y), (tx, ty), d in _along(r.line, tree_step, tree_step / 2):
                slot = int(d / tree_step)
                for side in (-1.0, 1.0):
                    lx, ly = -ty * side, tx * side
                    px, py = x + lx * (w / 2 + 1.6), y + ly * (w / 2 + 1.6)
                    p = Point(px, py)
                    if base.contains(p) or not lay.pavement.contains(p) or lay.road_area.distance(p) < 0.9 or lay.junctions.distance(p) < 6.0:
                        continue
                    if not all(math.hypot(px - qx, py - qy) >= 9.0 for qx, qy in taken + street_trees):
                        continue
                    if not lay.pavement.contains(Point(x + lx * (w / 2 + 3.0), y + ly * (w / 2 + 3.0))):
                        continue  # narrow pavement (under ~3 m): no room for a trunk and people
                    lakeside = lake_probe is not None and lake_probe.contains(p)
                    species = sr.get("lake_trees" if lakeside else "trees", ["VEG_Tree_RainTree_A"])
                    street_trees.append((px, py))
                    yaw = vegetation.lean_towards(px, py, px + lx, py + ly, 0.9)
                    out.add(vegetation.GROUP, vegetation.place(vegetation.pick(species, px, py), px, py, h.plot, yaw))
            for (x, y), (tx, ty), d in _along(r.line, lamp_step, 6.0):
                side = -1.0 if int(d / lamp_step) % 2 else 1.0  # staggered, alternate sides
                lx, ly = -ty * side, tx * side
                qx, qy = x + lx * (w / 2 + 0.7), y + ly * (w / 2 + 0.7)
                q = Point(qx, qy)
                if base.contains(q) or not lay.pavement.contains(q) or lay.junctions.distance(q) < 4.0:
                    continue
                if not all(math.hypot(qx - ax_, qy - ay_) >= 4.0 for ax_, ay_ in street_trees + street_furniture):
                    continue
                out.add("Street", Instance("PROP_StreetLamp_SingleArm_01", qx, qy, h.plot, math.atan2(-ly, -lx)))
                street_furniture.append((qx, qy))

    # --- roundabout fountains and their ornamental lamps (gf_17, gf_18) ----------------------------
    for name in dcfg.get("fountains", []):
        ways_ = [w for w in osm.lines(data, lambda t: t.get("junction") in ("roundabout", "circular") and t.get("name") == name)]
        pts_ = [tm.forward(*c) for w in ways_ for c in data.coords(w.node_ids)]
        if len(pts_) >= 3:
            cx_, cy_ = sum(p[0] for p in pts_) / len(pts_), sum(p[1] for p in pts_) / len(pts_)
            wd = max(rules.road_width(w.tags) for w in ways_)
            ring_r = min(math.hypot(p[0] - cx_, p[1] - cy_) for p in pts_) - wd / 2 - 1.2
            n_l = int(dcfg.get("roundabout_lamps", 8))
            for k in range(n_l if ring_r > 4.0 else 0):
                a = 2 * math.pi * (k + 0.5) / n_l
                out.add("Landmarks", Instance("PROP_Lamp_Roundabout_01", cx_ + ring_r * math.cos(a), cy_ + ring_r * math.sin(a),
                                              h.plot, a))
        if name in heroes.replaced_fountains(cfg):
            continue  # a hand-modelled hero (hero_models) stands here instead of the prop
        ways = [w for w in osm.lines(data, lambda t: t.get("junction") in ("roundabout", "circular")
                                     and t.get("name") == name)]
        pts = [tm.forward(*c) for w in ways for c in data.coords(w.node_ids)]
        if len(pts) < 3:
            continue
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        width = max(rules.road_width(w.tags) for w in ways)
        r = min(math.hypot(p[0] - cx, p[1] - cy) for p in pts) - width / 2 - 2.0
        if r > 3.0 and land.contains(Point(cx, cy)):
            s = r / float(dcfg.get("fountain_base_radius_m", 10.0))
            out.add("Landmarks", Instance(dcfg.get("fountain_piece", "PROP_Fountain_Roundabout_01"), cx, cy, h.plot, 0.0, s, s, s))

    # --- roundabout monuments (config dressing.monuments): a piece at the fitted centre of a named ring -------
    for mon in dcfg.get("monuments", []):
        pts_ = [c for r in lay.roads if r.name == mon.get("roundabout") for c in r.line.coords]
        if len(pts_) >= 5:
            from .layout import fit_circle
            mx_, my_, _ = fit_circle(pts_)
            out.add("Landmarks", Instance(mon["piece"], mx_, my_, h.plot, math.radians(float(mon.get("yaw_deg", 0.0)))))

    # --- promenade: planters on the inland edge, food carts near the seawall --------------------
    prom = lay.promenade
    pots = []
    # CIRCLE fix 4: planter_spacing_m 0 lays no promenade planters (gf_10 has none; the placeholder pot read as a
    # white faceted block in the w3 foreground)
    for poly in (_polys(prom) if float(dcfg.get("planter_spacing_m", 14.0)) > 0.0 else []):
        ring = LineString(poly.exterior.coords)
        for (x, y), (tx, ty), d in _along(ring, float(dcfg.get("planter_spacing_m", 14.0))):
            lx, ly = -ty, tx  # inside of a counter-clockwise ring
            inside = Point(x + lx * 1.0, y + ly * 1.0)
            outside = Point(x - lx * 2.0, y - ly * 2.0)
            if not prom.contains(inside) or lay.beach.buffer(1.0).contains(outside) or lay.sea.contains(outside):
                continue
            if lay.road_area.buffer(2.0).contains(outside):
                continue
            pots.append((inside.x, inside.y))
            out.add("Promenade", Instance("PROP_PlantPot_01", inside.x, inside.y, h.promenade, 0.0))
    lo, hi = dcfg.get("food_cart_range", [0.05, 0.4])
    axis = lay.axis
    carts = []
    wall_lines = ops.unary_union([LineString([p0, p1]) for p0, p1, _ in lay.seawall])
    for p0, p1, top in lay.seawall:
        if top < h.promenade - 1e-6:
            continue
        seg = LineString([p1, p0])
        for (x, y), (tx, ty), d in _along(seg, float(dcfg.get("food_cart_spacing_m", 7.0)), 2.0):
            t = axis.project(Point(x, y)) / axis.length
            if not lo <= t <= hi:
                continue
            lx, ly = -ty, tx  # promenade side (the beach is on the right of p1->p0)
            # P117 critic (w3 stood in a kade stall): food_cart_depth_m keeps carts and stalls against the seawall and
            # the inland walking lane clear (gf_10: an open walk 6-8 m wide beside the steps); default mid-promenade
            depth = float(dcfg.get("food_cart_depth_m", float(cfg.get("promenade_m", 6.0)) * 0.55))
            cx, cy = x + lx * depth, y + ly * depth
            if not prom.contains(Point(cx, cy)) or any(math.hypot(cx - qx, cy - qy) < 5.0 for qx, qy in carts + pots):
                continue
            carts.append((cx, cy))
            yaw = math.atan2(ty, tx) + math.pi        # local -y (counter / display side) to the promenade
            if len(carts) % 4 == 0:
                # seawall kade (gf_03): tin-roofed stall, counter to the promenade
                stalls = dcfg.get("kade_stalls", ["PROP_Kade_Stall_01"])
                out.add("Promenade", Instance(stalls[len(carts) // 4 % len(stalls)], cx, cy, h.promenade, yaw))
                continue
            # isso wade carts (pier_and_carts refs cart_01-03): backs to the sea, close to the seawall, A (day,
            # green) and B (night, glass box) mixed, a gas cylinder / stool / bowls beside some
            setback = float(dcfg.get("food_cart_setback_m", 1.4))
            kx, ky = x + lx * setback, y + ly * setback
            if any(wall_lines.distance(Point(kx + tx * e, ky + ty * e)) < 0.8 * setback for e in (-1.1, 0.0, 1.1)):
                continue                              # a bend in the seawall (pier root, steps): no room
            for piece, ox, oy, dyaw in cart_set(len(carts), _stable_hash(int(cx * 10), int(cy * 10))):
                px, py = cart_to_world(kx, ky, yaw, ox, oy)
                if piece not in ON_CART and not prom.contains(Point(px, py)):
                    continue
                out.add("Promenade", Instance(piece, px, py, h.promenade, yaw + dyaw))

    # --- terrace edge: wide steps, bench walls and bin sets where the Green meets the promenade ------
    rise = h.plot + getattr(lay.terrain, "green_dz", 0.0) - h.promenade   # HEIGHTS: the Green may sit below the plot datum
    run = 0.0
    next_steps = 25.0
    continuous = dcfg.get("terrace_steps_mode") == "continuous" and rise > 0.05
    if continuous:
        _terrace_steps_continuous(out, lay, dcfg, rise, h.promenade)
    for p0, p1 in ([] if continuous else lay.terrace):
        (ax, ay), (bx, by) = p1, p0  # promenade is left of p0->p1, the kit's outer (-y) side must face it
        ln = math.hypot(bx - ax, by - ay)
        if ln < 0.5 or rise <= 0.05:
            run += ln
            continue
        ux, uy = (bx - ax) / ln, (by - ay) / ln
        rot = math.atan2(uy, ux)
        if ln >= 7.0 and run + ln >= next_steps:
            # a run of seating steps (gf_10: long, shallow, bleacher-like), pieces end to end; config
            # terrace_steps_run_m (default 6 m = one piece), as many 6 m pieces as fit the segment
            n = max(1, min(int((ln - 1.0) // 6.0), int(round(float(dcfg.get("terrace_steps_run_m", 6.0)) / 6.0))))
            t = (ln - 6.0 * n) / 2
            if n == 4:   # one continuous 24 m piece: 6 m pieces end to end showed a cheek wall every 6 m (captures 2026-11-17)
                out.add("Promenade", Instance("KIT_Steps_TerraceLong_A", ax + ux * t, ay + uy * t,
                                              h.promenade, rot, 1.0, 1.0, rise / props.TERRACE_H))
            else:
                for k in range(n):
                    out.add("Promenade", Instance("KIT_Steps_Terrace_A", ax + ux * (t + 6.0 * k), ay + uy * (t + 6.0 * k),
                                                  h.promenade, rot, 1.0, 1.0, rise / props.TERRACE_H))
            # bins beside the steps, on the promenade
            bx_, by_ = ax + ux * (t - 2.0) + uy * 1.2, ay + uy * (t - 2.0) - ux * 1.2
            if prom.contains(Point(bx_, by_)):
                out.add("Promenade", Instance("PROP_Bin_Set_01", bx_, by_, h.promenade, rot))
            next_steps = run + ln + float(dcfg.get("terrace_steps_every_m", 60.0))
        elif ln >= 4.0 and int(run / float(dcfg.get("bench_every_m", 40.0))) != int((run + ln) / float(dcfg.get("bench_every_m", 40.0))):
            t = (ln - 3.0) / 2
            # freestanding stone bench wall on the promenade, parallel to the edge
            out.add("Promenade", Instance("PROP_Bench_StoneWall_01", ax + ux * t + uy * 3.0, ay + uy * t - ux * 3.0,
                                          h.promenade, rot))
        run += ln

    # promenade lamps (single pole, twin globes) just inside the seawall bench, and kiosks
    lamp2 = []
    for p0, p1, top in lay.seawall:
        if top < h.promenade - 1e-6:
            continue
        seg = LineString([p1, p0])
        for (x, y), (tx, ty), d in _along(seg, 3.0, 1.5):
            lx, ly = -ty, tx
            px, py = x + lx * 1.4, y + ly * 1.4
            if not prom.contains(Point(px, py)):
                continue
            if any(math.hypot(px - qx, py - qy) < float(dcfg.get("promenade_lamp_spacing_m", 28.0)) for qx, qy in lamp2):
                continue
            if "food_cart_depth_m" in dcfg and any(math.hypot(px - qx, py - qy) < 2.6 for qx, qy in carts):
                continue                              # carts and stalls stand against the seawall: no lamp inside one
            lamp2.append((px, py))
            out.add("Promenade", Instance("PROP_Lamp_TwinGlobe_01", px, py, h.promenade, math.atan2(ty, tx)))

    # viewing platform at each pier root: finial railing along the seawall bench, a flagpole, a kiosk
    for (rx, ry), (ux, uy) in pier_roots:
        if (rx, ry) in hero_pier_roots:
            continue   # the hero pier brings its own flag plinth and hut; pier_01 shows a plain low seawall there
        for p0, p1, top in lay.seawall:
            seg = LineString([p1, p0])
            if seg.distance(Point(rx, ry)) > 30.0:
                continue
            for (x, y), (tx, ty), d in _along(seg, 2.5):
                if math.hypot(x - rx, y - ry) > 22.0 or math.hypot(x - rx, y - ry) < 3.0:
                    continue
                lx, ly = -ty, tx
                out.add("Promenade", Instance("PROP_Railing_Finial_01", x + lx * 0.7, y + ly * 0.7, top + 0.45,
                                              math.atan2(ty, tx)))
        fx, fy = rx - ux * 9.0, ry - uy * 9.0
        out.add("Landmarks", Instance("PROP_Flagpole_01", fx, fy, h.promenade, math.atan2(uy, ux)))
        kx, ky = rx - ux * 6.0 - uy * 7.0, ry - uy * 6.0 + ux * 7.0
        out.add("Promenade", Instance("PROP_Kiosk_01", kx, ky, h.promenade, math.atan2(uy, ux)))

    # cannons along the Green's seaward edge and balloon / toy vendors on the Green (south half)
    clo, chi = dcfg.get("cannon_range", [0.04, 0.55])
    cannons, vendors = [], []
    for p0, p1 in lay.terrace:
        seg = LineString([p0, p1])
        for (x, y), (tx, ty), d in _along(seg, 4.0, 2.0):
            t = axis.project(Point(x, y)) / axis.length
            if not clo <= t <= chi:
                continue
            rx_, ry_ = ty, -tx  # right of p0->p1: the Green side
            cx, cy = x + rx_ * 4.5, y + ry_ * 4.5
            green_all = lay.park
            if not green_all.contains(Point(cx, cy)):
                continue
            if all(math.hypot(cx - qx, cy - qy) >= float(dcfg.get("cannon_spacing_m", 24.0)) for qx, qy in cannons):
                cannons.append((cx, cy))
                out.add("Promenade", Instance(dcfg.get("cannon_piece", "PROP_Cannon_Plinth_01"), cx, cy, h.plot, math.atan2(-ry_, -rx_)))
            hsh = _hash01(x, y, 3.0)
            vx, vy = x + rx_ * (14.0 + 10.0 * hsh), y + ry_ * (14.0 + 10.0 * hsh)
            if green_all.contains(Point(vx, vy)) and all(math.hypot(vx - qx, vy - qy) >= 38.0 for qx, qy in vendors):
                vendors.append((vx, vy))
                out.add("Promenade", Instance("PROP_Vendor_Balloons_01", vx, vy, h.plot, hsh * 6.283))

    # --- junctions: traffic lights and road sign posts (gf_17, gf_18, gf_25) -----------------------
    lights = []
    for jp in _polys(lay.junctions):
        if jp.area < float(dcfg.get("signal_junction_min_m2", 250.0)) or not lay.area_strip.contains(jp.centroid):
            continue
        cs = list(jp.minimum_rotated_rectangle.exterior.coords)[:4]
        jc = jp.centroid
        for i in (0, 2):
            ex, ey = cs[i]
            dx, dy = ex - jc.x, ey - jc.y
            dl = math.hypot(dx, dy) or 1.0
            px, py = ex + dx / dl * 1.5, ey + dy / dl * 1.5
            if not lay.pavement.contains(Point(px, py)) or any(math.hypot(px - qx, py - qy) < 12 for qx, qy in lights):
                continue
            lights.append((px, py))
            out.add("Street", Instance("PROP_TrafficLight_01", px, py, h.plot, math.atan2(-dy, -dx)))
            sx_, sy_ = px + dy / dl * 2.5, py - dx / dl * 2.5
            if lay.pavement.contains(Point(sx_, sy_)):
                plate = 1 + _stable_hash(int(px), int(py)) % 5
                out.add("Street", Instance(f"PROP_SignPost_{plate:02d}", sx_, sy_, h.plot, math.atan2(-dy, -dx)))

    # V4 vegetation: Green-edge palms and the config clusters (hotel lawn, roundabout, shade trees, hedges)
    veg_counts = vegetation.dress(cfg, lay, out.add, palms + lamps + cannons + vendors)
    # SLICE1: pavement edges of the config's frontage roads (kerb lamps, cabinets, wall-foot planting)
    edge_counts = pavement_edge.dress(cfg, lay, out.add, [(i.x, i.y) for g, i in out.placements if g in ("Street", vegetation.GROUP)])

    out.stats = {
        "seawall_bays": sum(1 for g, i in out.placements if i.piece.startswith("KIT_Seawall_Rubble_")),
        "seawall_steps": sum(1 for g, i in out.placements if i.piece == "KIT_SeawallSteps_A"),
        "revetment_rocks": sum(1 for g, i in out.placements if i.piece == "KIT_Revetment_Rock_A"),
        "piers": len(out.piers),
        "zebra_crossings": len(crossings),
        "zebra_crossings_extra": sum(1 for g, i in out.placements if i.piece == "KIT_RoadMarking_Zebra_A") - len(crossings),
        "median_lamps": len(lamps),
        "palms": len(palms),
        "planters": len(pots),
        "food_carts": len(carts),
        "fountains": sum(1 for g, i in out.placements if i.piece == dcfg.get("fountain_piece", "PROP_Fountain_Roundabout_01")),
        "pier_modules": sum(1 for g, i in out.placements if i.piece == "KIT_Pier_Pedestrian_A"),
        "terrace_steps": sum(1 for g, i in out.placements if i.piece == "KIT_Steps_Terrace_A"),
        "terrace_steps_long": sum(1 for g, i in out.placements if i.piece == "KIT_Steps_TerraceLong_A"),
        "bin_sets": sum(1 for g, i in out.placements if i.piece == "PROP_Bin_Set_01"),
        "benches": sum(1 for g, i in out.placements if i.piece == "PROP_Bench_StoneWall_01"),
        "promenade_lamps": len(lamp2),
        "delta_road_lamps": delta_lamps,
        "bus_halts": sum(1 for g, i in out.placements if i.piece == "PROP_BusShelter_01"),
        "traffic_lights": len(lights),
        "roundabout_lamps": sum(1 for g, i in out.placements if i.piece == "PROP_Lamp_Roundabout_01"),
        "monuments": sum(1 for g, i in out.placements if i.piece in {m["piece"] for m in dcfg.get("monuments", [])}),
        "kade_stalls": sum(1 for g, i in out.placements if i.piece in dcfg.get("kade_stalls", ["PROP_Kade_Stall_01"])),
        "railing_panels": sum(1 for g, i in out.placements if i.piece == "PROP_Railing_Finial_01"),
        "cannons": len(cannons),
        "vendors": len(vendors),
        "vegetation": veg_counts,
        "pavement_edge": edge_counts,
        "street_trees": len(street_trees),
        "street_lamps": sum(1 for g, i in out.placements if i.piece == "PROP_StreetLamp_SingleArm_01") - delta_lamps,
    }
    # P2 roadside set (citylib/roadside.py): Centre Road booths, seafront shelters and white kiosks, before the
    # terrain offsets and before markings paints a bus bay at every shelter
    from . import roadside
    out.stats["roadside"] = roadside.dress_shelters(cfg, data, lay, out)
    # SLICE3 terrain: everything standing on the ground follows the level areas (citylib/terrain.py); things on
    # the carriageway (markings) stay at the road datum, which never takes an offset
    if not lay.terrain.empty:
        moved = 0
        for k, (_g, inst) in enumerate(out.placements):
            if abs(inst.z - h.road) > 0.05:
                dz = lay.terrain.dz(inst.x, inst.y)
                if dz:
                    out.placements[k] = (_g, dataclasses.replace(inst, z=inst.z + dz))  # Instance is frozen
                    moved += 1
        out.stats["terrain_moved"] = moved
    return out
