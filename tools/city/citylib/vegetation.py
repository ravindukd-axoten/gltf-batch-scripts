"""Vegetation: the species catalogue and the data-driven placement rules (TDD "Vegetation as built").

The meshes are built by tools/city/build_vegetation.py (Blender) into Art/World/Vegetation/VEG_<Name>.glb with
_LOD0 / _LOD1 / _LOD2 (silhouette cards) nodes. The city pipeline only places markers: an empty named
`VEG_<Name>__<cell>_<i>` per tree in the cell glb (position, yaw, uniform scale), and Unity's CellBuilder puts the
three LOD meshes there, merged per 32 m chunk with a LODGroup (near prefab) and the cards in the far proxy.

Rules (config "vegetation", plus the existing "palm_roads" rows in dressing.py):
- road palms: the old PROP_Palm_Coconut_01 slots along Delta Road and Delta Face Centre Road, now one of the
  coconut variants (gf_14, gf_16: tall leaning coconut palms in a row along the road side of the Green)
- green_edge: palms just inside the Green where its edge runs along a road (gf_02, gf_12), every spacing_m
- clusters: explicit point sets, rings or lines in a local frame (the hotel's seaward lawn, its street front, the
  roundabout) for royal palms, shade trees, shrubs and hedges seen in gf_05, gf_09, gf_19, gf_20
Every choice is a stable hash of the position: no random(), same output on every build.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .kit import Instance, _stable_hash

GROUP = "Vegetation"
MARKER_SEP = "__"


@dataclass(frozen=True)
class Species:
    name: str
    kind: str            # palm, tree, shrub, hedge
    height: float        # metres, LOD0 at scale 1
    radius: float        # crown / canopy radius (spacing and LOD sizing)
    scale: tuple[float, float] = (0.9, 1.1)
    gap: float = 3.0     # minimum distance to other placed things (trunk to trunk)


CATALOGUE: dict[str, Species] = {s.name: s for s in (
    Species("VEG_Palm_Coconut_A", "palm", 11.0, 4.6, (0.9, 1.1), 4.0),
    Species("VEG_Palm_Coconut_B", "palm", 15.5, 5.0, (0.9, 1.1), 4.0),
    Species("VEG_Palm_Coconut_C", "palm", 8.5, 4.2, (0.9, 1.1), 4.0),
    Species("VEG_Palm_Coconut_D", "palm", 18.0, 5.2, (0.92, 1.05), 4.0),
    Species("VEG_Palm_Royal_A", "palm", 14.0, 4.2, (0.9, 1.1), 4.0),
    Species("VEG_Tree_RainTree_A", "tree", 13.0, 9.0, (0.85, 1.1), 10.0),
    Species("VEG_Tree_Kottamba_A", "tree", 8.6, 5.8, (0.85, 1.1), 7.0),
    Species("VEG_Tree_StreetYoung_A", "tree", 6.4, 1.9, (0.88, 1.12), 4.0),   # SLICE4a: in a steel guard (h08, h16)
    Species("VEG_Shrub_Frangipani_A", "shrub", 3.4, 1.9, (0.85, 1.15), 2.2),  # SLICE4a: araliya behind walls (h09, h10)
    Species("VEG_Shrub_Ixora_A", "shrub", 1.2, 0.8, (0.8, 1.2), 1.2),
    Species("VEG_Hedge_Clipped_A", "hedge", 1.0, 1.0, (1.0, 1.0), 0.0),
    Species("VEG_Hedge_Spill_A", "hedge", 2.8, 1.0, (1.0, 1.0), 0.0),        # SLICE4a: bush mass spilling over a wall
    Species("VEG_GrassClump_A", "shrub", 0.45, 0.7, (0.7, 1.3), 0.6),   # SLICE1 edge planting
    Species("VEG_PlantBed_A", "shrub", 0.55, 1.0, (0.85, 1.15), 0.9),
    # P295 B3 rows (manifest names; height / radius from the build report)
    Species("VEG_RainTree_01", "tree", 13.5, 9.0, (0.85, 1.1), 10.0),
    Species("VEG_RainTree_02", "tree", 14.5, 7.4, (0.85, 1.1), 9.0),
    Species("VEG_RainTree_03", "tree", 12.5, 11.2, (0.85, 1.1), 12.0),
    Species("VEG_KottambaTropicalAlmond_01", "tree", 8.7, 6.0, (0.85, 1.1), 7.0),
    Species("VEG_KottambaTropicalAlmond_02", "tree", 8.4, 5.8, (0.85, 1.1), 7.0),
    Species("VEG_MaraFlameTree_01", "tree", 8.6, 7.8, (0.85, 1.1), 9.0),
    Species("VEG_BanyanWithAerialRoots_01", "tree", 14.0, 11.2, (0.9, 1.1), 13.0),
    Species("VEG_YoungStreetTree_01", "tree", 6.4, 1.9, (0.88, 1.12), 4.0),
    Species("VEG_YoungStreetTree_02", "tree", 7.0, 1.7, (0.88, 1.12), 4.0),
    Species("VEG_CrotonShrub_01", "shrub", 1.1, 0.6, (0.8, 1.2), 0.9),
    Species("VEG_CrotonShrub_02", "shrub", 1.4, 0.55, (0.8, 1.2), 0.9),
    Species("VEG_BougainvilleaMoundWallSpill_01", "shrub", 1.7, 1.3, (0.85, 1.15), 1.6),
    Species("VEG_BougainvilleaMoundWallSpill_02", "hedge", 2.8, 1.0, (1.0, 1.0), 0.0),
    Species("VEG_FlowerBedCards_01", "shrub", 0.5, 1.0, (0.9, 1.1), 0.0),
    Species("VEG_FlowerBedCards_02", "shrub", 0.5, 1.0, (0.9, 1.1), 0.0),
    Species("VEG_WeedsInCracksKerb_01", "shrub", 0.3, 0.75, (0.7, 1.3), 0.0),
    Species("VEG_BeachCreeperDuneGrass_01", "shrub", 0.7, 1.5, (0.8, 1.2), 0.0),
    Species("VEG_WallCreeper_01", "hedge", 3.2, 1.5, (1.0, 1.0), 0.0),
)}

COCONUTS = ("VEG_Palm_Coconut_A", "VEG_Palm_Coconut_B", "VEG_Palm_Coconut_C", "VEG_Palm_Coconut_D")
# Road rows: tall leaners dominate along Delta Face (gf_14, gf_16); weights by repetition.
ROAD_PALMS = ("VEG_Palm_Coconut_B", "VEG_Palm_Coconut_A", "VEG_Palm_Coconut_D", "VEG_Palm_Coconut_B",
              "VEG_Palm_Coconut_C", "VEG_Palm_Coconut_A")
HEDGE_LENGTH_M = 2.0


def _h(x: float, y: float, salt: int) -> int:
    return _stable_hash(int(round(x * 100)), int(round(y * 100)), salt)


def hash01(x: float, y: float, salt: int = 0) -> float:
    return _h(x, y, salt) / 2**32


def pick(names, x: float, y: float) -> str:
    """Deterministic variant for a position."""
    return names[(_h(x, y, 11) >> 16) % len(names)]  # high bits: FNV's low bits barely mix


def place(name: str, x: float, y: float, z: float, yaw: float | None = None, stretch: float = 1.0,
          scale: tuple[float, float] | None = None, height: float = 1.0) -> Instance:
    """A marker instance with deterministic yaw (lean direction for palms) and uniform scale (the species range, or
    `scale` to widen it). Hedges and beds are stretched along x and scaled `height` in z (lower beds)."""
    sp = CATALOGUE[name]
    lo, hi = scale or sp.scale
    s = lo + (hi - lo) * hash01(x, y, 3)
    if yaw is None:
        yaw = hash01(x, y, 5) * 2 * math.pi
    if sp.kind == "hedge" or stretch != 1.0 or height != 1.0:
        return Instance(name, x, y, z, yaw, stretch, 1.0, height)
    return Instance(name, x, y, z, yaw, s, s, s)


# Crown offset along the lean (+x of the mesh) per metre of species height: measured on the LOD0 meshes
# (CIRCLE fix 3: Coconut A 1.7 m of 11, B 3.4 of 15.5, C 0.8 of 8.5, D 2.1 of 18, Royal 0.1 of 14).
CROWN_LEAN = {"VEG_Palm_Coconut_A": 0.16, "VEG_Palm_Coconut_B": 0.22, "VEG_Palm_Coconut_C": 0.09,
              "VEG_Palm_Coconut_D": 0.12, "VEG_Palm_Royal_A": 0.01}


def crown_point(inst: Instance) -> tuple[float, float]:
    """Plan position of a palm's crown: the trunk foot moved along its lean by the measured offset."""
    sp = CATALOGUE[inst.piece]
    reach = CROWN_LEAN.get(inst.piece, 0.0) * sp.height * inst.sx
    return inst.x + reach * math.cos(inst.rot), inst.y + reach * math.sin(inst.rot)


def clear_palm(inst: Instance, road, clear_m: float):
    """CIRCLE fix 3 (critic round 3, s1): keep a palm's trunk and crown out of the clear zone beside the
    carriageway. A trunk nearer than clear_m is dropped (None); a crown that leans back over it is turned to lean
    away from the nearest road point (same jitter), and dropped if it still reaches into the zone."""
    from shapely.geometry import Point
    from shapely.ops import nearest_points

    if CATALOGUE[inst.piece].kind != "palm" or road is None or road.is_empty:
        return inst
    foot = Point(inst.x, inst.y)
    if road.distance(foot) < clear_m:
        return None
    if road.distance(Point(*crown_point(inst))) >= clear_m:
        return inst
    q = nearest_points(road, foot)[0]
    away = math.atan2(inst.y - q.y, inst.x - q.x) + (hash01(inst.x, inst.y, 7) * 2 - 1) * 0.5
    turned = Instance(inst.piece, inst.x, inst.y, inst.z, away, inst.sx, inst.sy, inst.sz)
    return turned if road.distance(Point(*crown_point(turned))) >= clear_m else None


def lean_towards(x: float, y: float, tx: float, ty: float, spread: float = 0.6) -> float:
    """Yaw that points a palm's lean (+x of the mesh) towards (tx, ty), jittered by +-spread radians."""
    base = math.atan2(ty - y, tx - x)
    return base + (hash01(x, y, 7) * 2 - 1) * spread


def frame_points(spec: dict) -> list[tuple[float, float, float]]:
    """(x, y, yaw_or_nan) world points of a cluster spec: "points", "ring" or "line", in an optional frame
    {"pivot": [x, y], "yaw_deg": a}. Lines yield one point per spacing_m with the line's direction as yaw."""
    fr = spec.get("frame", {})
    px, py = fr.get("pivot", (0.0, 0.0))
    a = math.radians(fr.get("yaw_deg", 0.0))
    ca, sa = math.cos(a), math.sin(a)

    def w(u, v):
        return px + u * ca - v * sa, py + u * sa + v * ca

    out = []
    for u, v in spec.get("points", []):
        out.append((*w(u, v), math.nan))
    ring = spec.get("ring")
    if ring:
        cu, cv = ring["center"]
        n = int(ring["count"])
        start = math.radians(ring.get("start_deg", 0.0))
        for j, r in enumerate(ring.get("radii", [ring.get("radius", 0.0)])):
            for k in range(n):
                t = start + 2 * math.pi * (k + 0.5 * j) / n
                out.append((*w(cu + float(r) * math.cos(t), cv + float(r) * math.sin(t)), math.nan))
    line = spec.get("line")
    if line:
        step = float(spec.get("spacing_m", HEDGE_LENGTH_M))
        for (u0, v0), (u1, v1) in zip(line, line[1:]):
            ln = math.hypot(u1 - u0, v1 - v0)
            n = max(1, round(ln / step))
            yaw = math.atan2(v1 - v0, u1 - u0) + a
            for k in range(n):
                t = (k + 0.5) / n
                out.append((*w(u0 + (u1 - u0) * t, v0 + (v1 - v0) * t), yaw))
    return out


def far_enough(x: float, y: float, taken: list[tuple[float, float]], gap: float) -> bool:
    return all(math.hypot(x - qx, y - qy) >= gap for qx, qy in taken)


def hero_clusters(cfg: dict) -> list[dict]:
    """SLICE4c: vegetation cluster specs owned by hero builders (VEG_CLUSTERS in hero frame, e.g. the bushes over
    the hotel's corner wall), with the hero's config pivot / yaw as their frame."""
    from . import hero_hotel

    hero = cfg.get("hero_models", {}).get("HERO_SeafaceHotel")
    if not hero or hero.get("builder") != "hotel":
        return []
    frame = {"pivot": list(hero.get("pivot", (0.0, 0.0))), "yaw_deg": float(hero.get("yaw_deg", 0.0))}
    return [dict(spec, frame=frame) for spec in hero_hotel.VEG_CLUSTERS]


def clusters(cfg: dict) -> list[dict]:
    """Config clusters plus hero clusters; a config cluster whose line equals a hero cluster's "supersedes" (and
    shares its frame) is dropped, so moving a definition into the hero never places it twice."""
    hc = hero_clusters(cfg)
    gone = [(json_key(s["supersedes"]), json_key(s["frame"])) for s in hc if "supersedes" in s]
    keep = [s for s in cfg.get("vegetation", {}).get("clusters", [])
            if not any(json_key(s.get("line")) == ln and json_key(s.get("frame")) == fr for ln, fr in gone)]
    return keep + hc


def json_key(v) -> str:
    import json

    return json.dumps(v, sort_keys=True) if v is not None else ""


def road_row(spec: dict, lay, free, taken: list[tuple[float, float]], put, clear=None) -> int:
    """One "road_rows" spec: plants every spacing_m along each road named in spec["roads"], offset_m beyond the
    road's half width, on spec["side"] ("sea", "land" or "both"; sea = the side nearer the coast). Palms lean
    away from the carriageway; hedges are stretched to the spacing and turned along the road. Returns the count."""
    from shapely.geometry import Point

    names = spec["species"]
    step, off = float(spec.get("spacing_m", 12.0)), float(spec.get("offset_m", 2.0))
    side = spec.get("side", "both")
    near, rad = spec.get("near"), float(spec.get("radius_m", 1e9))
    jitter = float(spec.get("jitter_m", 0.0))
    # CIRCLE fix 3 (critic round 3: one height, even spacing): spacing_jitter varies each step by +-that fraction,
    # skip drops that share of the stations (planting gaps), scale widens the size range, height lowers beds
    sjit, skip = float(spec.get("spacing_jitter", 0.0)), float(spec.get("skip", 0.0))
    scale = tuple(spec["scale"]) if "scale" in spec else None
    hgt = float(spec.get("height", 1.0))
    run, gap_every = int(spec.get("run", 0)), int(spec.get("gap_every", 0))
    coast = lay.coast
    n = 0
    for r in lay.roads:
        if r.name not in spec["roads"]:
            continue
        ln = r.line
        d = float(spec.get("start_m", step / 2))
        while d < ln.length:
            p, q = ln.interpolate(d), ln.interpolate(min(ln.length, d + 1.0))
            if q.distance(p) < 0.5:
                q, p = p, ln.interpolate(max(0.0, d - 1.0))
            d += step * (1.0 + (hash01(p.x, p.y, 19) * 2 - 1) * sjit)
            k = int(round(d / step))
            if skip > 0 and hash01(p.x, p.y, 23) < skip:
                continue
            if run > 0 and gap_every > 0 and k % (run + gap_every) >= run:
                continue
            tx, ty = q.x - p.x, q.y - p.y
            tl = math.hypot(tx, ty) or 1.0
            tx, ty = tx / tl, ty / tl
            cands = []
            for sg in (-1.0, 1.0):
                lx, ly = -ty * sg, tx * sg
                o = r.width / 2 + off + (hash01(p.x, p.y, 17 + int(sg)) * 2 - 1) * jitter
                cands.append((p.x + lx * o, p.y + ly * o, lx, ly))
            if side != "both" and coast is not None:
                cands.sort(key=lambda c: coast.distance(Point(c[0], c[1])))
                cands = cands[:1] if side == "sea" else cands[1:]
            for x, y, lx, ly in cands:
                if near is not None and math.hypot(x - near[0], y - near[1]) > rad:
                    continue
                name = pick(names, x, y)
                sp = CATALOGUE[name]
                if not free(x, y):
                    continue
                if sp.kind == "hedge" or spec.get("bed"):
                    put(place(name, x, y, lay.heights.plot, math.atan2(ty, tx),
                              float(spec.get("stretch", step / HEDGE_LENGTH_M)), height=hgt))
                    n += 1
                    continue
                if not far_enough(x, y, taken, float(spec.get("gap_m", sp.gap))):
                    continue
                yaw = lean_towards(x, y, x + lx, y + ly, 0.8) if sp.kind == "palm" else None
                inst = place(name, x, y, lay.heights.plot, yaw, scale=scale)
                inst = clear(inst) if clear is not None else inst
                if inst is None:
                    continue
                put(inst)
                taken.append((x, y))
                n += 1
    return n


def dress(cfg: dict, lay, add, taken: list[tuple[float, float]]) -> dict:
    """Green-edge palms and clusters. `add(group, inst)` records a placement; `taken` holds positions already
    used (road palms, lamps) and grows. Returns per-species counts."""
    from shapely.geometry import LineString, Point

    from .layout import _polys

    vcfg = cfg.get("vegetation", {})
    h = lay.heights
    counts: dict[str, int] = {}

    road_clear = float(vcfg.get("palm_clear_m", 0.0))

    def put(inst: Instance, clear: bool = False) -> bool:
        """Records a placement; clear=True applies the palm clear zone (palm_clear_m from the carriageway)."""
        if clear:
            inst = clearing(inst)
            if inst is None:
                return False
        add(GROUP, inst)
        counts[inst.piece] = counts.get(inst.piece, 0) + 1
        return True

    def clearing(inst: Instance):
        if road_clear <= 0:
            return inst
        got = clear_palm(inst, lay.road_area, road_clear)
        if got is None:
            counts["_cleared"] = counts.get("_cleared", 0) + 1
        return got

    blocked = lay.road_area.buffer(float(vcfg.get("road_clear_m", 1.0)))
    from shapely import ops
    from shapely.prepared import prep
    built = prep(ops.unary_union([b.footprint for b in lay.buildings]).buffer(1.5)) if lay.buildings else None
    land, prom = prep(lay.land), prep(lay.promenade)
    blocked = prep(blocked)

    def free(x, y, ignore_buildings=False) -> bool:
        p = Point(x, y)
        if not land.contains(p) or blocked.contains(p) or prom.contains(p):
            return False
        return ignore_buildings or built is None or not built.contains(p)

    # --- palms just inside the Green where it runs along a road -----------------------------------------
    ge = vcfg.get("green_edge")
    if ge:
        step, inset = float(ge.get("spacing_m", 16.0)), float(ge.get("inset_m", 3.0))
        near_road = float(ge.get("road_within_m", 14.0))
        ge_scale = tuple(ge["scale"]) if "scale" in ge else None
        ge_names = ge.get("species", COCONUTS)
        for poly in _polys(lay.park):
            if poly.area < float(ge.get("min_area_m2", 2000.0)):
                continue
            ring = LineString(poly.exterior.coords)
            d = step / 2
            while d < ring.length:
                p, q = ring.interpolate(d), ring.interpolate(min(ring.length, d + 1.0))
                tx, ty = q.x - p.x, q.y - p.y
                tl = math.hypot(tx, ty) or 1.0
                lx, ly = -ty / tl, tx / tl          # inside of a counter-clockwise ring
                if not poly.exterior.is_ccw:
                    lx, ly = -lx, -ly
                x, y = p.x + lx * inset, p.y + ly * inset
                d += step * (1.0 + (hash01(p.x, p.y, 19) * 2 - 1) * float(ge.get("spacing_jitter", 0.0)))
                if lay.road_area.distance(Point(p.x, p.y)) > near_road or not poly.contains(Point(x, y)):
                    continue
                if not free(x, y) or not far_enough(x, y, taken, 6.0):
                    continue
                name = pick(ge_names, x, y)
                # Delta Face palms lean away from the road, towards the open Green and the light
                yaw = lean_towards(x, y, x + lx, y + ly, 0.9)
                if put(place(name, x, y, h.plot, yaw, scale=ge_scale), True):
                    taken.append((x, y))

    # --- rows along named roads, a fixed distance off the kerb, on the sea side, land side or both --------
    # (CIRCLE fix 2: sv_15 palms on the A2 sea strip, 04_wide the palm row between New Baladaksha and the podium,
    # sv_08 the carpark's far edge). Optional "near" + "radius_m" limit a row to a stretch.
    for spec in vcfg.get("road_rows", []):
        road_row(spec, lay, free, taken, put, clearing)

    # --- palms along the Green's seaward edge, just inside the lawn above the steps (sv_08, gf_12) ----------
    pe = vcfg.get("promenade_edge")
    if pe and not lay.promenade.is_empty:
        step, inset = float(pe.get("spacing_m", 20.0)), float(pe.get("inset_m", 6.0))
        within = float(pe.get("within_m", 3.0))
        for poly in _polys(lay.park):
            if poly.area < float(pe.get("min_area_m2", 2000.0)):
                continue
            ring = LineString(poly.exterior.coords)
            d = step / 2
            while d < ring.length:
                p, q = ring.interpolate(d), ring.interpolate(min(ring.length, d + 1.0))
                d += step * (0.75 + 0.5 * hash01(p.x, p.y, 13))          # irregular, as planted (sv_08)
                if lay.promenade.distance(p) > within:
                    continue
                tx, ty = q.x - p.x, q.y - p.y
                tl = math.hypot(tx, ty) or 1.0
                lx, ly = -ty / tl, tx / tl
                if not poly.exterior.is_ccw:
                    lx, ly = -lx, -ly
                x, y = p.x + lx * inset, p.y + ly * inset
                name = pick(pe.get("species", COCONUTS), x, y)
                if not poly.contains(Point(x, y)) or not free(x, y) or not far_enough(x, y, taken, CATALOGUE[name].gap * 2):
                    continue
                # sea palms lean landward, away from the onshore wind (gf_12, sv_08)
                if put(place(name, x, y, h.plot, lean_towards(x, y, x + lx, y + ly, 0.7),
                             scale=tuple(pe["scale"]) if "scale" in pe else None), True):
                    taken.append((x, y))

    # --- shade trees along the Green's edge near a point (hotel end, gf_05 / gf_19) ------------------------
    for spec in vcfg.get("edge_trees", []):
        cx, cy = spec["near"]
        rad, step, inset = float(spec["radius_m"]), float(spec.get("spacing_m", 18.0)), float(spec.get("inset_m", 6.0))
        for poly in _polys(lay.park):
            ring = LineString(poly.exterior.coords)
            d = 0.0
            while d < ring.length:
                p, q = ring.interpolate(d), ring.interpolate(min(ring.length, d + 1.0))
                d += step
                if math.hypot(p.x - cx, p.y - cy) > rad:
                    continue
                tx, ty = q.x - p.x, q.y - p.y
                tl = math.hypot(tx, ty) or 1.0
                lx, ly = -ty / tl, tx / tl
                if not poly.exterior.is_ccw:
                    lx, ly = -lx, -ly
                x, y = p.x + lx * inset, p.y + ly * inset
                name = pick(spec["species"], x, y)
                if not poly.contains(Point(x, y)) or not free(x, y) or not far_enough(x, y, taken, CATALOGUE[name].gap):
                    continue
                taken.append((x, y))
                put(place(name, x, y, h.plot))

    # --- clusters: points / rings / lines in a frame ----------------------------------------------------
    for spec in clusters(cfg):
        names = spec["species"]
        z = h.plot + float(spec.get("z_offset", 0.0))
        ign = bool(spec.get("ignore_buildings", False))
        local: list[tuple[float, float]] = []
        for x, y, yaw in frame_points(spec):
            name = pick(names, x, y)
            sp = CATALOGUE[name]
            if not free(x, y, ign):
                continue
            if sp.kind == "hedge":
                if not far_enough(x, y, local, HEDGE_LENGTH_M * 0.5):
                    continue
                stretch = float(spec.get("spacing_m", HEDGE_LENGTH_M)) / HEDGE_LENGTH_M
                local.append((x, y))
                put(place(name, x, y, z, yaw, stretch))
                continue
            gap = float(spec.get("gap_m", sp.gap))
            if not far_enough(x, y, taken, gap):
                continue
            if sp.kind == "palm" and "lean_to" in spec:
                yaw = lean_towards(x, y, *spec["lean_to"])
            taken.append((x, y))
            put(place(name, x, y, z, None if math.isnan(yaw) else yaw))
    return dict(sorted(counts.items()))
