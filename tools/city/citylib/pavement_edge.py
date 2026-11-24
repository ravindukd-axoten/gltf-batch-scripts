"""Pavement-edge dressing (SLICE1; gf_21-gf_25): the strip between a street's kerb and whatever stands behind its pavement.

Generic rules, applied to each side of every road named in config "dressing.frontage.roads" (other cells inherit them
by adding a road name, nothing is placed by hand):
- back edge: where the pavement ends against a plot, lawn, boundary wall or hero grounds (not a kit shopfront: doors),
  grass clumps and planted strips hide the hard line where the wall meets the paving (gf_23, gf_24, gf_25); a plant
  bed every few slots, grass clumps between, gaps by hash so it never reads as a row.
- utility cabinets (CEB-style feeder pillars) pulled 0.35 m off the back edge every cabinet_every_m (gf_21, gf_25).
- kerb: a galvanised single-arm lamp on any side with none within lamp_gap_m (the hotel side of Delta Road, gf_21,
  gf_24), a bin set beside every other new lamp, grass tufts in the kerb joint now and then (gf_23).
- wide pavements (>= tree_min_width_m): a shade tree in a galvanised tree guard every tree_every_m (gf_24).
Deterministic: hashes of positions, never random().
"""
from __future__ import annotations

import importlib
import math

from shapely import ops
from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from . import vegetation
from .kit import Instance

GRASS, BED = "VEG_GrassClump_A", "VEG_PlantBed_A"
TREE_GUARD, TREE = "PROP_TreeGuard_01", "VEG_Tree_StreetYoung_A"   # SLICE4a: young street tree, spider plants built in
PLANTER, HEDGE = "PROP_MedianPlanter_01", "VEG_Hedge_Clipped_A"


def _h(*v: float) -> float:
    return vegetation.hash01(v[0], v[1], int(v[2]) if len(v) > 2 else 0)


def dress(cfg: dict, lay, add, taken: list[tuple[float, float]]) -> dict:
    """`add(group, inst)` records a placement; `taken` (lamps, palms, signals) grows. Returns counts."""
    fc = cfg.get("dressing", {}).get("frontage")
    counts: dict[str, int] = {}
    if not fc:
        return counts
    from .dressing import _along, _ray_hit

    h = lay.heights
    names = set(fc.get("roads", []))
    step = float(fc.get("step_m", 2.5))
    pave = prep(lay.pavement)
    edge = lay.pavement.boundary
    shops = prep(lay_shops(lay))
    junction = prep(lay.junctions.buffer(float(fc.get("junction_clear_m", 5.0))))
    solid, gate = _hero_obstacles(lay)
    solid_p, solid_b, gate_p = prep(solid), solid.boundary, prep(gate)
    lamp_clear = prep(solid.buffer(0.35))

    def put(group, inst):
        add(group, inst)
        counts[inst.piece] = counts.get(inst.piece, 0) + 1

    def free(x, y, gap):
        return all(math.hypot(x - a, y - b) >= gap for a, b in taken)

    for r in lay.roads:
        if r.name not in names:
            continue
        w = r.width
        for side in (-1.0, 1.0):
            last_cab = -1e9
            new_lamps = 0
            last_lamp = -1e9
            last_tree = -1e9
            for (x, y), (tx, ty), d in _along(r.line, step, step / 2):
                lx, ly = -ty * side, tx * side
                kx, ky = x + lx * (w / 2 + 0.35), y + ly * (w / 2 + 0.35)       # just inside the kerb
                if not pave.contains(Point(kx, ky)) or junction.contains(Point(kx, ky)) or solid_p.contains(Point(kx, ky)):
                    continue
                back = _ray_hit((kx, ky), (lx, ly), edge, 0.3, 14.0)
                wall = _ray_hit((kx, ky), (lx, ly), solid_b, 0.3, 14.0) if not solid.is_empty else None
                if wall is not None and (back is None or wall < back):
                    back = wall                                                 # a hero facade or wall stops the pavement
                if back is None:
                    continue
                bx, by = kx + lx * back, ky + ly * back                         # back of pavement
                behind = Point(bx + lx * 0.8, by + ly * 0.8)
                rot_in = math.atan2(-ly, -lx)                                   # facing the road
                slot = int(d / step)
                hv = _h(bx, by, 41)
                # --- kerb lamps where this side has none (gf_21, gf_24) ---------------------------------
                lamp_gap = float(fc.get("lamp_gap_m", 30.0))
                lpx, lpy = x + lx * (w / 2 + 0.7), y + ly * (w / 2 + 0.7)
                if d - last_lamp >= lamp_gap and free(lpx, lpy, lamp_gap * 0.6) and not lamp_clear.contains(Point(lpx, lpy)):
                    put("Street", Instance("PROP_StreetLamp_SingleArm_01", lpx, lpy, h.plot, math.atan2(-ly, -lx)))
                    taken.append((lpx, lpy))
                    last_lamp = d
                    new_lamps += 1
                    if new_lamps % 2 == 0 and back > 2.6:
                        qx, qy = lpx + tx * 1.6 + lx * 0.5, lpy + ty * 1.6 + ly * 0.5
                        put("Street", Instance("PROP_Bin_Set_01", qx, qy, h.plot, rot_in))
                        taken.append((qx, qy))
                    continue
                # --- back edge: cabinets and planting (not in front of shop doors) -----------------------
                if shops.contains(behind) or gate_p.contains(Point(bx, by)):
                    continue
                cab_every = float(fc.get("cabinet_every_m", 55.0))
                if d - last_cab >= cab_every and hv < 0.5 and back > 2.2:
                    cx, cy = bx - lx * 0.35, by - ly * 0.35
                    if free(cx, cy, 2.0):
                        piece = "PROP_UtilityCabinet_0%d" % (1 + int(hv * 4) % 2)
                        put("Street", Instance(piece, cx, cy, h.plot, rot_in))
                        taken.append((cx, cy))
                        last_cab = d
                        continue
                if hv < float(fc.get("planting", 0.7)):
                    px, py = bx - lx * 0.25, by - ly * 0.25
                    name = BED if slot % 4 == 0 and back > 2.0 else GRASS
                    if free(px, py, 0.8):
                        yaw = math.atan2(ty, tx) + (math.pi if hv < 0.35 else 0.0)
                        put(vegetation.GROUP, vegetation.place(name, px, py, h.plot, yaw))
                # --- kerb joint tufts --------------------------------------------------------------------
                if _h(kx, ky, 43) < float(fc.get("kerb_tufts", 0.12)):
                    gx, gy = x + lx * (w / 2 + 0.12), y + ly * (w / 2 + 0.12)
                    if free(gx, gy, 1.0):
                        put(vegetation.GROUP, vegetation.place(GRASS, gx, gy, h.plot - 0.05, math.atan2(ty, tx)))
                # --- shade trees in galvanised guards on wide pavements (gf_24, agent h08, h15) -------------
                tree_min = float(fc.get("tree_min_width_m", 0.0))
                if tree_min > 0.0 and back >= tree_min and d - last_tree >= float(fc.get("tree_every_m", 14.0)):
                    gx, gy = x + lx * (w / 2 + 1.25), y + ly * (w / 2 + 1.25)
                    if free(gx, gy, 3.0) and not solid_p.contains(Point(gx, gy)) and not gate_p.contains(Point(gx, gy)):
                        yaw = math.atan2(ty, tx)
                        put("Street", Instance(TREE_GUARD, gx, gy, h.plot, yaw))
                        # the young tree is modelled at street size (thin trunk, sparse crown, spider plants at its
                        # foot: agent h08, h16), so it goes in at its own scale; tree_scale only trims it if set
                        tree = vegetation.place(TREE, gx, gy, h.plot)
                        k = float(fc.get("young_tree_scale", 1.0))
                        put(vegetation.GROUP, Instance(TREE, gx, gy, h.plot, tree.rot, tree.sx * k, tree.sy * k, tree.sz * k))
                        last_tree = d   # not in `taken`: a young tree never pushes a kerb lamp away
    for piece, n in median_planters(cfg, lay, add, taken).items():
        counts[piece] = counts.get(piece, 0) + n
    return dict(sorted(counts.items()))


def median_planters(cfg: dict, lay, add, taken: list[tuple[float, float]]) -> dict:
    """Raised median planters (SLICE2, agent h10-h14): wherever a road named in config "dressing.median_planters.roads"
    has a paved median between its two carriageways (a pavement strip min_width_m..max_width_m wide), a
    PROP_MedianPlanter_01 run every segment_m along its middle with a clipped hedge on top; gaps at junctions and
    crossings (junction_clear_m) and where a median lamp or another prop already stands."""
    mc = cfg.get("dressing", {}).get("median_planters")
    counts: dict[str, int] = {}
    if not mc:
        return counts
    from .dressing import _along, _ray_hit
    h = lay.heights
    seg = float(mc.get("segment_m", 6.0))
    lo, hi = float(mc.get("min_width_m", 0.9)), float(mc.get("max_width_m", 3.0))
    pave = prep(lay.pavement)
    junction = prep(lay.junctions.buffer(float(mc.get("junction_clear_m", 8.0))))
    edge = lay.road_area.boundary
    placed: list[tuple[float, float]] = []
    names = set(mc.get("roads", []))
    for r in lay.roads:
        if r.name not in names:
            continue
        for (x, y), (tx, ty), d in _along(r.line, seg, seg / 2):
            for side in (-1.0, 1.0):
                lx, ly = -ty * side, tx * side
                kx, ky = x + lx * (r.width / 2 + 0.05), y + ly * (r.width / 2 + 0.05)
                if not pave.contains(Point(kx, ky)):
                    continue
                hit = _ray_hit((kx, ky), (lx, ly), edge, 0.05, hi + 0.2)
                if hit is None or not lo <= hit + 0.05 <= hi:
                    continue
                cx, cy = kx + lx * hit / 2, ky + ly * hit / 2
                ends = [Point(cx + tx * seg / 2 * k, cy + ty * seg / 2 * k) for k in (-1, 1)]
                if not all(pave.contains(e) and not junction.contains(e) for e in ends):
                    continue
                if any(math.hypot(cx - a, cy - b) < seg * 0.6 for a, b in placed):
                    continue
                if any(abs((a - cx) * tx + (b - cy) * ty) < seg / 2 + 0.6 and abs((a - cx) * lx + (b - cy) * ly) < hit
                       for a, b in taken):
                    continue
                yaw = math.atan2(ty, tx)
                add("Street", Instance(PLANTER, cx, cy, h.plot, yaw))
                counts[PLANTER] = counts.get(PLANTER, 0) + 1
                hedge_w = min(0.9, hit - 0.25)
                for k in (-1, 0, 1):
                    add(vegetation.GROUP, Instance(HEDGE, cx + tx * 2.0 * k, cy + ty * 2.0 * k, h.plot + 0.56, yaw,
                                                   0.98, hedge_w, 0.5))
                    counts[HEDGE] = counts.get(HEDGE, 0) + 1
                placed.append((cx, cy))
    return counts


def lay_shops(lay):
    """Kit buildings (shopfronts at the pavement): no planting in front of their doors."""
    from shapely import ops
    polys = [b.footprint for b in lay.buildings if not getattr(b, "hero", None) and not getattr(b, "landmark", "")]  # heroes: street_obstacles()
    return ops.unary_union(polys) if polys else Point(0, 0).buffer(0.01)


def _hero_obstacles(lay):
    """World polygons of hero massing and walls that end the pavement (solid) and gate openings kept clear (gate),
    from each hero builder module's optional street_obstacles() (rectangles in the hero's turned frame)."""
    solid, gate = [], []
    for site in getattr(lay, "heroes", []):
        try:
            mod = importlib.import_module(f"{__package__}.hero_{site.builder}")
        except ImportError:
            continue
        if not hasattr(mod, "street_obstacles"):
            continue
        px, py = site.pivot[0], site.pivot[1]
        c, s = math.cos(math.radians(site.yaw_deg)), math.sin(math.radians(site.yaw_deg))
        for out, rects in zip((solid, gate), mod.street_obstacles()):
            for u0, u1, v0, v1 in rects:
                out.append(Polygon([(px + u * c - v * s, py + u * s + v * c) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]))
    return ops.unary_union(solid) if solid else Polygon(), ops.unary_union(gate) if gate else Polygon()


MANHOLE_UV = (0.78, 0.78, 0.97, 0.97)   # StreetTrim_A gutter row: round cast-iron cover in a square concrete frame
MANHOLE_M = 0.76


def covers(cfg: dict, lay, marks, dress) -> dict:
    """SLICE4d (agent h16): utility manholes on the pavements of the frontage roads, plot-level decals in
    marks.quads (citylib/cells.paint_quads lays them 1 cm over the paving). One every manhole_every_m (default 24 m)
    on each side, skipped by hash, 1.7-2.5 m in from the kerb, clear of trees, lamps, cabinets and hero walls.
    The kerb drain grates are citylib/roadside.py's gutter decals."""
    from . import markings
    from . import materials as M
    from .dressing import _along

    fc = cfg.get("dressing", {}).get("frontage")
    counts = {"manhole": 0}
    if not fc or marks is None:
        return counts
    names = set(fc.get("roads", []))
    every = float(fc.get("manhole_every_m", 24.0))
    inner = prep(lay.pavement.buffer(-0.1))
    junction = prep(lay.junctions.buffer(float(fc.get("junction_clear_m", 5.0))))
    solid, _gate = _hero_obstacles(lay)
    solid_p = prep(solid.buffer(0.3))
    near = [(i.x, i.y) for _g, i in dress.placements]
    for r in lay.roads:
        if r.name not in names:
            continue
        for side in (-1.0, 1.0):
            for (x, y), (tx, ty), _d in _along(r.line, every, every / 2):
                if _h(x, y, 61 + side) < 0.25:
                    continue
                lx, ly = -ty * side, tx * side
                k = r.width / 2 + 1.7 + 0.8 * _h(x, y, 62 + side)     # clear of the frontage cream band
                cx, cy = x + lx * k, y + ly * k
                q = markings.oriented_quad(cx, cy, (tx, ty), MANHOLE_M, MANHOLE_M, MANHOLE_UV, M.STREET_TRIM,
                                           "manhole", level="plot")
                poly = Polygon(q.pts)
                if not inner.contains(poly) or junction.intersects(poly) or solid_p.intersects(poly):
                    continue
                if any(math.hypot(cx - a, cy - b) < 1.2 for a, b in near):
                    continue
                marks.quads.append(q)
                near.append((cx, cy))
                counts["manhole"] += 1
    return counts
