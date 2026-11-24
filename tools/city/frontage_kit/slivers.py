"""Find zero-area triangles left after the bevel and say which vertex pairs to merge (pure Python, no bpy).

A bevel next to a boolean cut can leave a quad with three collinear corners: one of its two triangulations has
zero area, and blender_qa fails the glb on it (BLD_CLS_School_A, P145). dissolve_degenerate misses it because the
short edge (about 1 mm) is longer than its distance. genbuild merges the short edge of each such triangle at its
midpoint, which moves geometry by under max_edge / 2 and leaves a clean triangle.
"""
from __future__ import annotations

import math

MIN_AREA = 1e-9     # same threshold as blender_qa qa_core.check_topology
MAX_EDGE = 0.005    # only merge edges under 5 mm; a longer zero-area edge is reported, not moved


def tri_area(a, b, c):
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    x = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return 0.5 * math.sqrt(sum(k * k for k in x))


def sliver_merges(tris, max_edge=MAX_EDGE, min_area=MIN_AREA):
    """tris: iterable of (vertex ids (3), coords (3 xyz)). Returns (merge pairs, unfixable count).

    Pairs are disjoint (a vertex is in at most one pair), so they can all be merged in one pass.
    """
    pairs, used, unfixable = [], set(), 0
    for ids, co in tris:
        if tri_area(*co) >= min_area:
            continue
        edges = sorted(((math.dist(co[i], co[(i + 1) % 3]), ids[i], ids[(i + 1) % 3]) for i in range(3)))
        length, a, b = edges[0]
        if length > max_edge or a == b:
            unfixable += 1
            continue
        if a in used or b in used:
            continue
        used.update((a, b))
        pairs.append((min(a, b), max(a, b)))
    return sorted(pairs), unfixable
