"""P388 signage along the route (config `street_life.signs`): more shop and wall signs on the facades that face it.

Why: the look report found blocky facades with few signs; Cityhub frontages carry a sign on nearly every bay, stacked
up the first floors (gf_24 hotel street: painted boards and an awning over every opening; sv_03, sv_04: boards on
the colonial frontages by the roundabout). The kit already puts one fascia over each shop bay (kit.assemble_building);
this pass adds, on building edges that face the route only:
  - plain ground walls (side walls, towers' concrete base, blank plaster): fascia boards over runs of bays, and a
    painted wall sign at eye level on some of the rest (tier all: what a driver reads);
  - shop edges: boards on the first upper floors' floor lines and a few more projecting signs (tier detail).
Text comes from the existing sign atlas (T_Signage_A, tools/textures/signage.json): fictional shop names and generic
trades only, no brands. Pieces and bay grid match kit.assemble_building, so a board sits on its bay exactly.
"""
from __future__ import annotations

import math

from shapely.geometry import Point

from . import rules
from .kit import Instance, _stable_hash, bays_for_edge
from .street_life import GROUP_ALL, GROUP_DETAIL, cost

FASCIA = [f"PROP_Sign_Fascia_{k:02d}" for k in range(1, 13)]
WALL = [f"PROP_Sign_Wall_{k:02d}" for k in range(1, 5)]
PROJ = [f"PROP_Sign_Projecting_{k:02d}" for k in range(1, 5)]
WALL_BOARD_Z = 1.6   # PROP_Sign_Wall_*: board centre above the piece origin (street_kit.signs)


def facing_edges(b, line, reach: float, min_len: float = 4.0):
    """(ring index 0 only) edges of a building that face the route: (e, a, b, ux, uy, length, street flag)."""
    ring = list(b.footprint.exterior.coords)[:-1]
    n = len(ring)
    for e in range(n):
        (ax, ay), (bx, by) = ring[e], ring[(e + 1) % n]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy)
        if ln < min_len:
            continue
        ux, uy = dx / ln, dy / ln
        mx, my = (ax + bx) / 2, (ay + by) / 2
        d0 = line.distance(Point(mx, my))
        if d0 > reach:
            continue
        ox, oy = uy, -ux   # outward (kit frame -y) for the counter-clockwise outer ring
        if line.distance(Point(mx + ox * 8.0, my + oy * 8.0)) > d0 - 5.0:
            continue        # the edge does not look towards the route
        street = bool(b.street and b.street[0] and e < len(b.street[0]) and b.street[0][e])
        yield e, (ax, ay), ux, uy, ln, street


def dress_signs(cfg: dict, data, lay, dress, line=None) -> dict:
    sc = cfg.get("street_life", {}).get("signs")
    if not sc:
        return {}
    if line is None:
        from .street_life import route_line
        line = route_line(cfg, data)
    if line is None:
        return {}
    reach = float(sc.get("reach_m", 40.0))
    # HEIGHTS/placement 2026-11-24: the fascia board list is data (config signs.fascia_pieces, e.g. the round-5
    # SIGN_Fascia_00..29, whose pivot is the board's bottom centre: fascia_offset_m [along, up] puts it on the band)
    fascia = list(sc.get("fascia_pieces") or []) or FASCIA
    fdx, fdz = (float(v) for v in sc.get("fascia_offset_m", [1.5, 2.95]))
    off = float(sc.get("stand_off_m", 0.12))   # clear of the wall kit's string courses and pilasters
    h = lay.heights
    first = len(dress.placements)
    counts = {"plain_fascia": 0, "plain_wall": 0, "upper_boards": 0, "projecting": 0, "buildings": 0}
    near = line.buffer(reach + 40.0)
    for b in lay.buildings:
        if b.landmark or b.sacred or b.hero or b.base > 0 or not near.intersects(b.footprint):
            continue
        base = h.road + b.base
        tower = b.levels >= rules.TOWER_MIN_LEVELS
        touched = False
        for e, (ax, ay), ux, uy, ln, street in facing_edges(b, line, reach):
            rot = math.atan2(uy, ux)
            ox, oy = uy * off, -ux * off
            count, sx = bays_for_edge(ln, 3.0)
            step = ln / count

            def put(group, piece, k, z):
                dress.add(group, Instance(piece, ax + ux * step * k + ox, ay + uy * step * k + oy, z, rot, sx))

            hs = lambda k, salt: _stable_hash(b.osm_id, e, k, salt)  # noqa: E731
            boarded = set()   # bays with a ground fascia: no first-floor board stacked straight on top of it
            if not street:
                # a blank ground floor: runs of 1-3 boarded bays (a shop that took over the wall), a painted wall sign
                # on about a third of the rest; towers keep every third bay clear (lobby glazing rhythm)
                for k in range(count):
                    r = hs(k, 21) >> 9
                    if tower and k % 3 == 2:
                        continue
                    if r % 100 < int(sc.get("plain_fascia_pct", 45)):
                        if fascia is FASCIA:
                            put(GROUP_ALL, FASCIA[(hs(k // 2, 22) >> 7) % len(FASCIA)], k, base)
                        else:   # centre-pivot boards (SIGN_Fascia_*): shift to the bay middle, up to the fascia band
                            fx = fdx * step / 3.0
                            dress.add(GROUP_ALL, Instance(fascia[(hs(k // 2, 22) >> 7) % len(fascia)],
                                                          ax + ux * (step * k + fx) + ox, ay + uy * (step * k + fx) + oy,
                                                          base + fdz, rot, sx))
                        boarded.add(k)
                        counts["plain_fascia"] += 1
                    elif r % 100 < int(sc.get("plain_fascia_pct", 45)) + int(sc.get("plain_wall_pct", 25)):
                        put(GROUP_ALL, WALL[(hs(k, 23) >> 7) % len(WALL)], k, base)
                        counts["plain_wall"] += 1
                touched = True
            if b.levels >= 2 and not tower:
                # stacked boards on the floor lines of the first upper floors (tuition, clinics, offices upstairs)
                floors = min(b.levels - 1, int(sc.get("upper_floors", 2)))
                for f in range(1, floors + 1):
                    # board centred just over the floor line, between the windows below and the sills above
                    z_line = base + rules.GROUND_FLOOR_M + rules.UPPER_FLOOR_M * (f - 1) + 0.05
                    for k in range(count):
                        if f == 1 and (street or k in boarded):
                            continue   # the kit's (or this pass's) fascia already sits under this floor line
                        if (hs(k, 30 + f) >> 9) % 100 < int(sc.get("upper_board_pct", 30)):
                            put(GROUP_DETAIL, WALL[(hs(k, 40 + f) >> 7) % len(WALL)], k, z_line - WALL_BOARD_Z)
                            counts["upper_boards"] += 1
                if street and b.levels >= 3:   # the second upper floor (the kit's own projecting signs use the first)
                    for k in range(count):
                        if (hs(k, 50) >> 9) % 100 < int(sc.get("projecting_pct", 20)):
                            put(GROUP_DETAIL, PROJ[(hs(k, 51) >> 7) % len(PROJ)], k,
                                base + rules.GROUND_FLOOR_M + rules.UPPER_FLOOR_M + 0.6)
                            counts["projecting"] += 1
                touched = True
        counts["buildings"] += touched
    from .cells import _kit_tris
    counts["cells"] = cost(dress, first, _kit_tris())
    return counts
