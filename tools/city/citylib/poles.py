"""Roadside pole lines and cable spans (P134, inventory rows WS-0110..0127). Placement only: the pieces are in
citylib/pole_kit.py and built by tools/city/build_poles.py.

Rules (all measured on the BUILT kerb, `lay.pavement` / `lay.road_area` / `lay.buildings`):
- A pole stands on the pavement 0.9-2.8 m outside the carriageway edge (first offset that is pavement, 0.5 m clear of
  the road, 1.5 m from anything already taken), at the district's spacing with a seeded jitter, never inside a building
  footprint (+0.5 m) and never within 1.5 m of a tree marker.
- Roles by district (`poles.districts[d]` in the city config, falling back to `poles.default`): `lamps` (slim lamp
  every `lamp_spacing` m on the sea side), `lines` (concrete pole line on the land side every `spacing` m with
  crossarms, a transformer pole every `xfmr_every` poles, a telecom pole beside every `telecom_every`-th), `wire`
  (none / lv / lv_bundle: whether spans are strung).
- A span joins two neighbouring poles of one line when 8..42 m apart and the straight plan line clears every building
  footprint (0.3 m) and tree marker (1.5 m). Marker at the first pole top, yawed to the second, scaled along x to the
  real length from the nearest built class (+-20 %). Sag is in the mesh.
- Decay (citylib/decay.py profile "prop"): wear 0..2 picks the `_W1` / `_W2` mesh variant of concrete poles (grime in
  COLOR_0), lean tips the marker where Instance carries rx / ry (p132+), bent poles get a larger lean.
- Wear by district comes from data/world/wear_rules.json (`rust`, `dirt` of the class `secondary`): rust > 0.5 turns
  every pole one wear step older (capped at 2).
"""
from __future__ import annotations

import math
from dataclasses import fields

from shapely import ops
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from . import decay as dec
from . import pole_kit as pk
from .kit import Instance

GROUP = "poles"
HAS_TILT = "rx" in {f.name for f in fields(Instance)}
SPAN_MIN, SPAN_MAX = 8.0, 42.0

DEFAULT = {"spacing": 38.0, "jitter": 3.0, "lamp_spacing": 36.0, "lines": True, "lamps": False, "wire": "lv",
           "xfmr_every": 7, "telecom_every": 3, "pole_h": 10, "arms": 2, "stay_rate": 0.25, "jbox_every": 9}


def cfg_for(cfg: dict, district: str) -> dict:
    pc = cfg.get("poles", {})
    out = dict(DEFAULT)
    out.update(pc.get("default", {}))
    out.update(pc.get("districts", {}).get(district, {}))
    return out


def _h(*v) -> float:
    return dec.stable_hash(":".join(str(round(x, 1)) if isinstance(x, float) else str(x) for x in v)) / 2**32


def along(line: LineString, spacing: float, jitter: float, seed: str, start: float = 3.0):
    """Stations (m) along `line` at `spacing` with a seeded +-jitter; never closer than 0.6 spacing."""
    out, s, i = [], start, 0
    while s < line.length - 2.0:
        out.append(s)
        s += spacing + (_h(seed, i) * 2.0 - 1.0) * jitter
        i += 1
    return out


def offset_point(line: LineString, s: float, off: float):
    """Point at station s, `off` m to the left (+) of the line direction, and the unit tangent."""
    a, b = line.interpolate(max(0.0, s - 0.5)), line.interpolate(min(line.length, s + 0.5))
    tx, ty = b.x - a.x, b.y - a.y
    n = math.hypot(tx, ty) or 1.0
    tx, ty = tx / n, ty / n
    p = line.interpolate(s)
    return (p.x - ty * off, p.y + tx * off), (tx, ty)


def spot(lay, line, s, side, w, taken, bld, trees, reach=(0.9, 1.4, 2.0, 2.8), same=(), same_clear=0.0):
    """First kerb-side position that is pavement, clear of road, buildings, trees and earlier poles; else None."""
    for o in reach:
        (x, y), t = offset_point(line, s, side * (w / 2 + o))
        p = Point(x, y)
        if not lay.pavement.contains(p) or lay.road_area.distance(p) <= 0.5:
            continue
        if bld is not None and bld.distance(p) < 0.5:
            continue
        if any(math.hypot(x - q[0], y - q[1]) < 1.5 for q in trees):
            continue
        if any(math.hypot(x - q[0], y - q[1]) < 1.5 for q in taken):
            continue
        if same_clear and any(math.hypot(x - q[0], y - q[1]) < same_clear for q in same):
            continue      # a parallel carriageway piece of the same road already has its pole / lamp here
        return (x, y), t
    return None


def span_ok(a, b, bld, trees) -> tuple[bool, float]:
    d = math.dist(a, b)
    if not SPAN_MIN <= d <= SPAN_MAX:
        return False, d
    seg = LineString([a, b])
    if bld is not None and seg.distance(bld) < 0.3:
        return False, d
    if any(seg.distance(Point(q)) < 1.5 for q in trees):
        return False, d
    return True, d


def span_marker(a, b, z_a, sag_ok=True):
    """(piece-class length, scale, yaw) for a span from a to b."""
    d = math.dist(a, b)
    c = pk.span_length_class(d)
    return c, d / c, math.atan2(b[1] - a[1], b[0] - a[0])


def pole_variant(piece: str, wear: int) -> str:
    return piece + (dec.variant_suffix(wear) if piece.startswith("POLE_Conc_") else "")


def _inst(piece, x, y, z, rot, sz=1.0, sx=1.0, rx=0.0, ry=0.0):
    if HAS_TILT and (rx or ry):
        return Instance(piece, x, y, z, rot, sx, 1.0, sz, rx, ry)
    return Instance(piece, x, y, z, rot, sx, 1.0, sz)


def plan_line(poles: list[dict], rc: dict, bld, trees, uid: str, rust: float):
    """Markers for one pole line: `poles` are dicts x, y, z, t (tangent), side. Returns (instances, stats)."""
    out, st = [], {"poles": 0, "xfmr": 0, "telecom": 0, "stays": 0, "spans": 0, "wire_m": 0.0, "wire_tris": 0,
                   "skipped_spans": 0}
    n = len(poles)
    h = int(rc["pole_h"])
    top_arm = {1: "POLE_Arm_1", 2: "POLE_Arm_2", 3: "POLE_Arm_3"}[int(rc["arms"])]
    for i, p in enumerate(poles):
        d = dec.decay(f"{uid}:{i}:{round(p['x'])}:{round(p['y'])}", "prop")
        wear = min(2, d["wear"] + (1 if rust > 0.5 else 0))
        yaw = math.atan2(p["t"][1], p["t"][0])
        lean = d["lean_deg"] * (1.8 if d["bent"] else 1.0)
        tilt = dec.compose(dec.lean_matrix(lean, d["lean_az_deg"]), yaw) if lean > 0.05 else (0.0, 0.0, yaw)
        rx, ry, rz = tilt
        xfmr = rc["xfmr_every"] and i % int(rc["xfmr_every"]) == int(rc["xfmr_every"]) // 2
        if xfmr:
            out.append(_inst("POLE_Xfmr_H", p["x"], p["y"], p["z"], yaw))
            st["xfmr"] += 1
        else:
            out.append(_inst(pole_variant(f"POLE_Conc_{h}", wear), p["x"], p["y"], p["z"], rz, rx=rx, ry=ry))
            end = i in (0, n - 1)
            out.append(_inst("POLE_Arm_Dead" if end else top_arm, p["x"], p["y"], p["z"] + h, rz, rx=rx, ry=ry))
            out.append(_inst("POLE_LampArm", p["x"], p["y"], p["z"] + h, rz + (math.pi if p["side"] > 0 else 0.0)))
            st["poles"] += 1
            if end and _h(uid, i, "stay") < 0.9:
                out.append(_inst("POLE_Stay", p["x"], p["y"], p["z"], rz))
                st["stays"] += 1
            elif _h(uid, i, "stay2") < rc["stay_rate"]:
                out.append(_inst("POLE_Stay", p["x"], p["y"], p["z"], rz + math.pi))
                st["stays"] += 1
        if rc["telecom_every"] and i % int(rc["telecom_every"]) == 1 and not xfmr:
            ox, oy = p["x"] + p["t"][0] * 3.0, p["y"] + p["t"][1] * 3.0
            out.append(_inst("POLE_Telecom_" + "AB"[int(_h(uid, i, "tel") * 2)], ox, oy, p["z"], rz))
            st["telecom"] += 1
    mode = rc["wire"]
    if mode != "none":
        for i in range(n - 1):
            a, b = poles[i], poles[i + 1]
            ok, d = span_ok((a["x"], a["y"]), (b["x"], b["y"]), bld, trees)
            if not ok:
                st["skipped_spans"] += 1
                continue
            c, k, yaw = span_marker((a["x"], a["y"]), (b["x"], b["y"]), a["z"])
            ci = int(c)
            out.append(_inst(f"WIRE_LV4_L{ci}", a["x"], a["y"], a["z"] + h, yaw, sx=k))
            st["spans"] += 1
            st["wire_m"] += d
            st["wire_tris"] += pk.tris(pk.wire_lv(c))
            if mode == "lv_bundle":
                out.append(_inst(f"WIRE_Bundle_L{ci}", a["x"], a["y"], a["z"] + h, yaw, sx=k))
                st["wire_tris"] += pk.tris(pk.wire_bundle(c))
    return out, st


def place(cfg: dict, lay, dress) -> dict:
    """Config "poles": {default, districts, roads: {road name: overrides}}; see module doc. Adds POLE_ and WIRE_ markers to `dress` and returns stats."""
    pc = cfg.get("poles")
    if not pc:
        return {}
    from .roadside import _ground_z
    from .wear_rules import load as load_wear

    wr = load_wear()
    bld = ops.unary_union([b.footprint for b in lay.buildings]) if lay.buildings else None
    trees = [(i.x, i.y) for g, i in dress.placements if "tree" in i.piece.lower() or "palm" in i.piece.lower()]
    taken: list[tuple[float, float]] = [(i.x, i.y) for g, i in dress.placements if "pole" in i.piece.lower()
                                        or "lamp" in i.piece.lower()]
    district = cfg.get("district", "delta_face")
    district_at = getattr(lay, "district_at", None)
    rc0 = cfg_for(cfg, district)
    stats = {"poles": 0, "lamps": 0, "xfmr": 0, "telecom": 0, "stays": 0, "spans": 0, "wire_m": 0.0, "wire_tris": 0,
             "skipped_spans": 0, "tris": 0, "district": district}
    names_done = set()
    lamp_pts: list[tuple[float, float]] = []
    pole_pts: list[tuple[float, float]] = []
    for r in sorted(lay.roads, key=lambda r: r.name):
        if r.width < 5.0 or r.priority > 6 or r.line.length < 25.0:
            continue
        key = (r.name, round(r.line.length))
        if key in names_done:
            continue
        names_done.add(key)
        mid = r.line.interpolate(r.line.length / 2)
        dist = district_at(mid) if callable(district_at) else district
        rc = cfg_for(cfg, dist)
        rc.update(cfg["poles"].get("roads", {}).get(r.name, {}))
        uid = f"{r.name}:{round(r.line.length)}"
        sea = _sea(lay, r.line)
        try:
            rust = float(wr.rule(dist, "secondary")["rust"])
        except Exception:
            rust = 0.4
        if rc["lamps"]:
            for s in along(r.line, rc["lamp_spacing"], rc["jitter"], uid + ":lamp"):
                sp = spot(lay, r.line, s, sea, r.width, taken, bld, trees, same=lamp_pts, same_clear=0.55 * rc["lamp_spacing"])
                if sp is None:
                    continue
                (x, y), t = sp
                z = _ground_z(lay, x, y)
                piece = rc.get("lamp_piece", "POLE_Lamp_Solar")
                dress.add(GROUP, _inst(piece, x, y, z, math.atan2(t[1], t[0])))
                taken.append((x, y))
                lamp_pts.append((x, y))
                stats["lamps"] += 1
                stats["tris"] += _tris(piece)
        if rc["lines"]:
            poles = []
            for s in along(r.line, rc["spacing"], rc["jitter"], uid + ":line", 8.0):
                sp = spot(lay, r.line, s, -sea, r.width, taken, bld, trees, same=pole_pts, same_clear=0.55 * rc["spacing"])
                if sp is None:
                    continue
                (x, y), t = sp
                poles.append({"x": x, "y": y, "z": _ground_z(lay, x, y), "t": t, "side": -sea})
                taken.append((x, y))
                pole_pts.append((x, y))
            if len(poles) >= 3:
                insts, st = plan_line(poles, rc, bld, trees, uid, rust)
                for i in insts:
                    dress.add(GROUP, i)
                    stats["tris"] += _tris(i.piece)
                for k in ("poles", "xfmr", "telecom", "stays", "spans", "wire_tris", "skipped_spans"):
                    stats[k] += st[k]
                stats["wire_m"] += st["wire_m"]
    stats["wire_m"] = round(stats["wire_m"], 1)
    return stats


_TRIS: dict[str, int] = {}


def tris_table() -> dict[str, int]:
    """LOD0 triangles per marker piece (incl. wear variants), for the cell triangle budget (cells.py table)."""
    out = {}
    for n, p in pk.pieces().items():
        out[n] = p.tris
        if n.startswith("POLE_Conc_"):
            out[n + "_W1"] = out[n + "_W2"] = p.tris
    return out


def _tris(piece: str) -> int:
    if not _TRIS:
        _TRIS.update({n: p.tris for n, p in pk.pieces().items()})
    base = piece
    for suf in ("_W1", "_W2"):
        base = base.removesuffix(suf)
    return _TRIS.get(base, 0)


def _sea(lay, line) -> float:
    from .roadside import _sea_side

    return _sea_side(lay, line, line.length / 2)
