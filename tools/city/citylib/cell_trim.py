"""Cell budget trim (P117, TASKS B4 / RX-0051): keep a cell under its LOD0 triangle target by dropping dressing,
farthest from the drive circle first. Pure Python, no Blender or Shapely (the caller passes the distance function).

Why: the measured B3 widths (15.5 m promenade) put more promenade frontage and carts into the seafront cells
cell_-1_-1 and cell_-1_0, which lie outside the drive circle (only 87 of cell_-1_-1's 60,691 triangles are inside
the circle and its 60 m band). The cell is trimmed toward the circle edge: what is far from the circle goes first,
what the driver sees from the circle stays.

Rules, config "cell_trim" (delta_face_circle.json):
- `sets`: piece-name prefixes that anchor a set, in drop order (e.g. the isso wade carts, then kade stalls). A set is
  the anchor plus every `companions` piece within `companion_m` of it (stools, gas cylinders, bowl stacks), so a
  dropped cart never leaves its stools standing on an empty patch.
- `loose`: prefixes dropped one by one after the sets run out (benches, plant pots); never structure (seawall,
  steps, kerbs, lamps, buildings).
- Within a class, the instance farthest from the circle edge goes first; ties break by position, never random().
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrimResult:
    keep: list                 # [(group, instance)] kept, in the input order
    dropped: list = field(default_factory=list)   # [(group, instance)] dropped
    tris_before: int = 0
    tris_after: int = 0


def _match(piece: str, prefixes) -> int:
    for i, p in enumerate(prefixes):
        if piece.startswith(p):
            return i
    return -1


def trim(placements: list, over_tris: int, tris_of, dist_of, rule: dict) -> TrimResult:
    """placements: [(group, inst)] of one cell (inst has .piece, .x, .y); over_tris: how many triangles to shed
    (<= 0 keeps all); tris_of(piece) -> int; dist_of(x, y) -> metres from the circle edge (0 inside it)."""
    total = sum(tris_of(i.piece) for _, i in placements)
    res = TrimResult(list(placements), [], total, total)
    if over_tris <= 0 or not rule:
        return res
    sets = list(rule.get("sets", []))
    comps = tuple(rule.get("companions", []))
    loose = list(rule.get("loose", []))
    reach2 = float(rule.get("companion_m", 3.5)) ** 2
    min_dist = float(rule.get("min_dist_m", 0.0))   # never trim what sits this close to the circle (driver's view)
    alive = list(range(len(placements)))
    gone: set[int] = set()

    def order(idx):
        g, i = placements[idx]
        return (-dist_of(i.x, i.y), round(i.x, 2), round(i.y, 2))

    def candidates(prefixes):
        out = []
        for k, prefix in enumerate(prefixes):
            cls = [j for j in alive if j not in gone and placements[j][1].piece.startswith(prefix)
                   and dist_of(placements[j][1].x, placements[j][1].y) >= min_dist]
            out += [(k, j) for j in sorted(cls, key=order)]
        return out

    shed = 0
    for _, j in candidates(sets):
        if shed >= over_tris:
            break
        if j in gone:
            continue
        a = placements[j][1]
        group = [j] + [q for q in alive if q not in gone and q != j and placements[q][1].piece.startswith(comps)
                       and (placements[q][1].x - a.x) ** 2 + (placements[q][1].y - a.y) ** 2 <= reach2]
        for q in group:
            gone.add(q)
            shed += tris_of(placements[q][1].piece)
    for _, j in candidates(loose):
        if shed >= over_tris:
            break
        gone.add(j)
        shed += tris_of(placements[j][1].piece)
    res.keep = [placements[j] for j in alive if j not in gone]
    res.dropped = [placements[j] for j in alive if j in gone]
    res.tris_after = total - shed
    return res
