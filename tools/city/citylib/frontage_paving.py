"""Frontage paving (SLICE4d; agent h08, h16): a named paver on a hero's street frontage, laid along its kerb.

A config "pavement_widening" rule with a "paver" material (e.g. MAT_HerringbonePaver on the hotel's Delta Road
frontage) turns the whole pavement inside the rule's box (kerb to the plot, not only the widened strip) into that
paver, with UVs measured from the kerb: s along the road, d across from the kerb. The herringbone is turned 45
degrees to the kerb (UV rotation; the texture itself is a square 90 degree herringbone), and a cream band two
courses wide (MAT_SeafrontPaver's band rows) runs parallel to the kerb BAND_D metres in.

Used by citylib/cells.py (LOD0 pavement) and citylib/pavement_edge.covers (manholes on the frontage).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import ops
from shapely.geometry import Point, Polygon

from . import materials as M
from . import terrain as terrain_mod

BAND_D = (1.0, 1.2)          # cream band, metres from the kerb face (h16: two light courses about a metre in)


@dataclass
class Zone:
    poly: object                 # pavement area that takes the paver
    band: object                 # the cream band strip inside it
    lines: list                  # (centreline, half width) of the named road's pieces next to it
    material: str


def zones(cfg: dict, lay) -> list[Zone]:
    out = []
    for rule in cfg.get("pavement_widening", []):
        mat = rule.get("paver")
        if not mat or rule.get("hero") not in cfg.get("hero_models", {}):
            continue
        f = terrain_mod.frame_to_world(cfg, rule["hero"])
        u0, u1, v0, v1 = rule["box_uv"]
        frame = Polygon([f(u, v) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))])
        width = float(rule.get("width_m", 5.0))
        lines = [(r.line, r.width / 2.0) for r in lay.roads
                 if r.name == rule["road"] and r.line.distance(frame) < r.width / 2.0 + width + 2.0]
        if not lines:
            continue
        poly = lay.pavement.intersection(frame)
        if poly.is_empty:
            continue
        band = ops.unary_union([ln.buffer(hw + BAND_D[1], cap_style="flat").difference(ln.buffer(hw + BAND_D[0], cap_style="flat"))
                                for ln, hw in lines]).intersection(poly)
        out.append(Zone(poly, band, lines, mat))
    return out


def _kerb_coords(zone: Zone, x: float, y: float) -> tuple[float, float]:
    """(s along the nearest road piece, d from its kerb face) in metres."""
    p = Point(x, y)
    ln, hw = min(zone.lines, key=lambda t: t[0].distance(p))
    s = ln.project(p)
    return s, max(0.0, ln.distance(p) - hw)


def paver_uv(zone: Zone):
    """45 degree herringbone: the square tile turned to the kerb."""
    tu, _tv = M.tile(zone.material)
    r = 1.0 / math.sqrt(2.0)

    def fn(x, y):
        s, d = _kerb_coords(zone, x, y)
        return ((s + d) * r / tu, (d - s) * r / tu)
    return fn


def band_uv(zone: Zone):
    """MAT_SeafrontPaver running bond along the kerb, v inside its cream rows (0-0.2 m of the 2.4 m tile)."""
    tu, tv = M.tile(M.SEAFRONT_PAVER)

    def fn(x, y):
        s, d = _kerb_coords(zone, x, y)
        return (s / tu, min(max(d - BAND_D[0], 0.005), 0.195) / tv)
    return fn


def kerb_frame(zone: Zone, s: float, d: float, which: int = 0):
    """World (x, y) and unit tangent at s along road piece `which`, d metres in from its kerb (on the zone's side)."""
    ln, hw = zone.lines[which]
    a, b = ln.interpolate(max(0.0, s - 0.5)), ln.interpolate(min(ln.length, s + 0.5))
    tl = math.hypot(b.x - a.x, b.y - a.y) or 1.0
    tx, ty = (b.x - a.x) / tl, (b.y - a.y) / tl
    q = ln.interpolate(s)
    c = zone.poly.representative_point()
    side = 1.0 if (tx * (c.y - q.y) - ty * (c.x - q.x)) > 0 else -1.0
    return (q.x - ty * side * (hw + d), q.y + tx * side * (hw + d)), (tx, ty)
