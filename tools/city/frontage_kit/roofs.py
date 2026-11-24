"""Clay tile gable roofs for the building classes (P148 fix 3): Calicut (Mangalore pattern) tile courses, a timber
fascia under each eave, exposed rafter tails, barge boards on the gable ends and a half-round ridge cap.

Each slope is one profiles.sheet: the grid rows go in pairs per course, so every course is a face that rises from its
head (z 0) to its butt standing LIP proud of the course below, with the lip as a short downhill face. That gives the
horizontal shadow line of every course from one Grid node. The two channels of each tile come from the SHEET trim row
(its baked corrugations run along V, which the box projection lays down the slope); its course depth (0.31 m in plan
at 32 deg) stays under the 0.4 m row, so the row is not squashed. Columns every 1.2 m only carry vertex AO and wear.
LOD1 keeps the courses at double depth on one column; rafters and fascia are LOD0 only.
"""
from __future__ import annotations

import math

import profiles as pr
from parts import tag

COURSE = 0.36   # exposed length of one tile course along the slope (Mangalore pattern ~0.41 m tile, 0.05 m lap)
LIP = 0.035     # how far the butt of a course stands off the course below
RAFTER = 0.6    # rafter spacing (exposed tails under the eave)


def _courses(t, x0, x1, sl, course, col_w):
    n = max(2, int(math.ceil(sl / course)))
    c = sl / n
    ncol = max(1, int(math.ceil((x1 - x0) / col_w)))
    col = (x1 - x0) / ncol

    def fpos(X, s, f):
        i = pr.m(t, "ROUND", s * float(2 * n))
        k = pr.m(t, "FLOOR", i * 0.5 + 1e-3)
        return X, k * c - sl / 2, (i - k * 2.0) * LIP
    return tag(t, pr.sheet(t, x0, col, ncol, 2 * n, fpos), "SHEET", "TILE", 0.0)


def slope(t, p, x0, x1, sl, pitch, tail, simple):
    """One roof slope in its own frame: x along the eave, y from -sl/2 (eave) to sl/2 (ridge), z off the rafters.
    `tail` is how far the rafters run in from the eave (the overhang along the slope plus a bearing)."""
    lod0 = _courses(t, x0, x1, sl, COURSE, 1.2)
    lod1 = _courses(t, x0, x1, sl, COURSE * 2, x1 - x0)
    tiles = lod1 if simple else t.switch(p.LOD, lod0, lod1)
    n = max(1, int(math.ceil(sl / 0.95)))
    dy = sl / n
    under = tag(t, t.join(*[t.cube(x0, x1, -sl / 2 + i * dy, -sl / 2 + (i + 1) * dy, -0.08, 0.0) for i in range(n)]),
                "CONCRETE", "TILE", 0.0)
    barge = tag(t, t.join(t.cube(x0 - 0.05, x0, -sl / 2 - 0.02, sl / 2, -0.26, LIP + 0.05),
                          t.cube(x1, x1 + 0.05, -sl / 2 - 0.02, sl / 2, -0.26, LIP + 0.05)), "FRAME", "TIMBER", 1.0)
    out = [tiles, under, barge]
    if not simple:
        # fascia: plumb (turned back by the pitch inside the slope frame), its top under the tile eave
        fascia = t.move(t.move(t.cube(x0, x1, 0.0, 0.035, -0.24, 0.0), (0, 0, 0), (-pitch, 0, 0)), (0, -sl / 2 + 0.05, -0.01))
        cnt = int((x1 - x0 - 0.3) / RAFTER) + 1
        raft = t.array(t.cube(-0.035, 0.035, -sl / 2 + 0.07, -sl / 2 + tail, -0.22, -0.08), cnt, t.vec(RAFTER, 0, 0),
                       (x0 + 0.15 + (x1 - x0 - 0.3 - (cnt - 1) * RAFTER) / 2, 0, 0))
        # rafters unbevelled: 2 x 30+ small boxes per roof, a bevel would treble their cost for no read at street range
        out.append(t.when(t.bnot(p.LOD), t.join(tag(t, fascia, "FRAME", "TIMBER", 1.0), tag(t, raft, "FRAME", "TIMBER", 0.0))))
    return t.join(*out)


def ridge(t, W, D, z, ext=0.4):
    """Half-round ridge tiles over the apex (a low cylinder; its lower half sits inside the slopes)."""
    return tag(t, t.cyl(0.13, W + 2 * ext + 0.1, (W / 2, D / 2, z), "x", 8), "CONCRETE", "TILE", 0.0)
