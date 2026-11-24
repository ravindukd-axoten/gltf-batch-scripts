"""Written ground v1 (RX-0012, WS-0003): the road surface re-cut on a 2 m strip grid, with wear written in COLOR_0.

Each road piece is laid out in its own (s, d) frame (s = metres along the centreline, d = signed offset, + = left of
travel, the same frame as `cells.road_uv`). Rows are 2 m along; across, the breakpoints sit at the kerbs, 0.6 m in
from each kerb (dust band), and per lane at the two wheel paths (lane centre +-0.85 m) and the lane centre (oil
drip line). Colours are per face corner, so the wear ramps smoothly between breakpoints and the patches (whole grid
cells set to one colour) keep crisp edges.

COLOR_0.rgb follows the HeroLit paint convention (`tint = lerp(1, saturate(rgb * 1.1), _PaintStrength)`): neutral
asphalt is 1 / 1.1 = 0.909, so the untouched surface is unchanged and darker is wheel path / oil / fresh patch.
The tint saturates at 1, so nothing can be paler than plain asphalt in game: kerb dust and sea-side sand drift are
written as a warm shift (blue and green pulled down, red kept), and every channel is capped at NEUTRAL (P328: v1
wrote paler dust that the shader clamps away, and the review render did not clamp, so it overstated the dust). COLOR_0.a stays the light bake's AO slot (flat faces keep 1), so the
WS-0003 "two-layer A blend" is carried in rgb, not alpha (doc deviation noted in the P325 done list). Unity reads it
once MAT_Asphalt sets `_PaintStrength` 1 (parked: no Unity this lane).

Parts of the piece the strip grid does not cover (flared ends, tight curves where a row would fold) are filled by
constrained Delaunay as before and written with the same colour function, so there are no holes or overlaps.
"""
from __future__ import annotations

import math
import os

import shapely
from shapely.geometry import Point, Polygon
from shapely.prepared import prep
from shapely.ops import unary_union

ENABLED = os.environ.get("PI_ROAD_WRITING", "1") != "0"  # False (env 0) = the old plain CDT road
NEUTRAL = 1.0 / 1.1          # COLOR_0 rgb that the HeroLit tint maps to 1.0 (no change)
ROW_M = 2.0                  # strip grid row length along the road (RX-0012)
DUST_M = 0.6                 # kerb dust band width
TRACK_OFF_M = 0.85           # wheel path offset from the lane centre (half a 1.7 m car track)
TRACK_SIGMA_M = 0.32         # wheel path half width (gaussian)
PATCH_RATE = 0.05            # share of lane grid cells that start a patch
LANE_TONE = 0.09             # long-wave tone drift per lane (resurfaced lanes differ, sv_09)
LANE_BASE = 0.06             # driven lanes sit darker than the kerb strip (the tint cannot lift the kerb instead)
SAND_REACH_M = 70.0          # sand drift only on carriageways within this distance of the coast

# P328 contrast pass (v1 read as barely different from plain asphalt at eye level, sv_09): factors on the asphalt
WHEEL = (0.60, 0.615, 0.64)  # polished, oil-darkened wheel path (slightly cool)
OIL = (0.56, 0.535, 0.51)    # drip line at the lane centre (warm brown-black)
DUST = (1.0, 0.955, 0.87)    # kerb dust: warm shift only (the tint cannot go paler than the asphalt)
SAND = (1.0, 0.92, 0.76)     # wind-blown sand on the sea-side kerb (Delta Face), warm shift
PATCH = (0.58, 0.59, 0.61)   # fresh dark patch (newer, still black asphalt)
PATCH_OLD = (0.97, 0.95, 0.90)  # old grey patch (cement-skimmed utility cut): warm grey


def lane_count(width: float) -> int:
    return max(1, round(width / 3.25))


def _hash(*k: float) -> float:
    """Deterministic 0..1 hash (no global RNG state, same on every run and machine)."""
    h = 0.0
    for i, v in enumerate(k):
        h += v * (12.9898 + 31.7 * i)
    x = math.sin(h) * 43758.5453
    return x - math.floor(x)


def _noise1(s: float, scale: float, seed: float) -> float:
    """Smooth 1D value noise 0..1 along s."""
    t = s / scale
    i = math.floor(t)
    f = t - i
    f = f * f * (3 - 2 * f)
    return _hash(i, seed) * (1 - f) + _hash(i + 1, seed) * f


def breakpoints(width: float) -> list[float]:
    """Across-road offsets d (right kerb -w/2 to left kerb +w/2) where the strip grid has vertices."""
    w = width
    n = lane_count(w)
    lw = w / n
    ds = {-w / 2, w / 2, -w / 2 + DUST_M, w / 2 - DUST_M}
    for k in range(n):
        c = -w / 2 + lw * (k + 0.5)
        for o in (-TRACK_OFF_M, 0.0, TRACK_OFF_M):
            if abs(o) + 0.15 < lw / 2:
                ds.add(c + o)
        if k:
            ds.add(-w / 2 + lw * k)  # lane line: wear lifts between lanes
    out = sorted(d for d in ds if -w / 2 <= d <= w / 2)
    merged = [out[0]]
    for d in out[1:]:
        if d - merged[-1] > 0.2:
            merged.append(d)
    merged[-1] = w / 2
    return merged


class Writer:
    """Colour function for one road piece (pure Python, deterministic per piece)."""

    def __init__(self, piece, sea_side: int = 0, seed: float = 0.0):
        self.piece = piece
        self.w = piece.width
        self.n = lane_count(self.w)
        self.lw = self.w / self.n
        self.sea_side = sea_side  # -1 right kerb faces the sea, +1 left, 0 inland
        self.seed = seed
        self.patches = self._patches()

    def _patches(self) -> list[tuple[float, float, float, float, tuple]]:
        """Rectangles in (s, d): (s0, s1, d0, d1, colour); 1-3 rows long, one lane (or a wheel path) wide."""
        out = []
        length = self.piece.line.length
        rows = int(length // ROW_M)
        for i in range(rows):
            for k in range(self.n):
                if _hash(i, k, self.seed, 1.0) < PATCH_RATE:
                    span = 1 + int(_hash(i, k, self.seed, 2.0) * 3)
                    d0 = -self.w / 2 + self.lw * k
                    d1 = d0 + self.lw
                    if _hash(i, k, self.seed, 3.0) < 0.5:  # half-lane cut along one wheel path
                        mid = (d0 + d1) / 2
                        d0, d1 = (d0, mid) if _hash(i, k, self.seed, 4.0) < 0.5 else (mid, d1)
                    col = PATCH if _hash(i, k, self.seed, 5.0) < 0.7 else PATCH_OLD
                    out.append((i * ROW_M, (i + span) * ROW_M, d0, d1, col))
        return out

    def patch_at(self, s: float, d: float):
        for s0, s1, d0, d1, col in self.patches:
            if s0 - 1e-6 <= s <= s1 + 1e-6 and d0 - 1e-6 <= d <= d1 + 1e-6:
                return tuple(min(NEUTRAL, NEUTRAL * c) for c in col)
        return None

    def cell_patch(self, s0, s1, d0, d1):
        """Patch colour if the whole grid cell lies in one patch (keeps patch edges on grid lines)."""
        sm, dm = (s0 + s1) / 2, (d0 + d1) / 2
        for ps0, ps1, pd0, pd1, col in self.patches:
            if ps0 - 1e-6 <= sm <= ps1 + 1e-6 and pd0 - 1e-6 <= dm <= pd1 + 1e-6:
                return tuple(min(NEUTRAL, NEUTRAL * c) for c in col)  # factors on the asphalt, like colour()
        return None

    def colour(self, s: float, d: float) -> tuple[float, float, float]:
        w, lw = self.w, self.lw
        u = d + w / 2
        e = min(u, w - u)  # metres to the nearest kerb
        t = (u % lw) - lw / 2 if 0 < u < w else lw / 2
        r = g = b = 1.0
        # wheel paths: two per lane, intensity drifts along the road
        k = math.exp(-((abs(t) - TRACK_OFF_M) / TRACK_SIGMA_M) ** 2) * (0.75 + 0.5 * _noise1(s, 23.0, self.seed + 7))
        r, g, b = r + (WHEEL[0] - 1) * k, g + (WHEEL[1] - 1) * k, b + (WHEEL[2] - 1) * k
        # oil drip line at the lane centre, blotchy, stronger near the piece ends (stop lines at junctions)
        end = min(s, self.piece.line.length - s)
        stop = 1.0 + 0.8 * max(0.0, 1 - end / 25.0)
        blot = min(1.0, max(0.0, (_noise1(s, 5.0, self.seed + 11) - 0.25) / 0.5))
        o = min(1.0, math.exp(-(t / 0.34) ** 2) * blot * 0.85 * stop)
        r, g, b = r + (OIL[0] - 1) * o, g + (OIL[1] - 1) * o, b + (OIL[2] - 1) * o
        # resurfaced lanes: a slow tone drift per lane, so the carriageway is not one flat grey
        lane = min(self.n - 1, max(0, int(u // lw)))
        inner = min(1.0, e / 1.2)  # the driven lanes are darker than the dusty kerb strip (sv_09)
        tone = 1.0 - inner * (LANE_BASE + LANE_TONE * _noise1(s, 37.0, self.seed + 23 + 5.3 * lane))
        r, g, b = r * tone, g * tone, b * tone
        # kerb dust, and sand drift on the sea-side kerb
        dust = max(0.0, 1 - e / (DUST_M + 0.15)) * (0.6 + 0.4 * _noise1(s, 9.0, self.seed + 13))
        side = -1 if u < w / 2 else 1
        if self.sea_side and side == self.sea_side:
            reach = 1.6 * (0.5 + _noise1(s, 14.0, self.seed + 17))
            sand = max(0.0, 1 - e / reach) * (0.5 + 0.5 * _noise1(s, 5.0, self.seed + 19))
            tgt = SAND
            dust = max(dust, sand)
        else:
            tgt = DUST
        r, g, b = r + (tgt[0] - r) * dust, g + (tgt[1] - g) * dust, b + (tgt[2] - b) * dust
        return (min(NEUTRAL, NEUTRAL * r), min(NEUTRAL, NEUTRAL * g), min(NEUTRAL, NEUTRAL * b))


def sea_side_of(piece, layout) -> int:
    """Which kerb faces the sea: -1 right, +1 left, 0 when the piece is farther than SAND_REACH_M from the coast."""
    coast = getattr(layout, "coast", None)
    if coast is None or coast.is_empty or piece.line.distance(coast) > SAND_REACH_M:
        return 0
    mid = piece.line.interpolate(0.5, normalized=True)
    a = piece.line.interpolate(max(0.0, piece.line.project(mid) - 1.0))
    b = piece.line.interpolate(min(piece.line.length, piece.line.project(mid) + 1.0))
    tx, ty = b.x - a.x, b.y - a.y
    tl = math.hypot(tx, ty) or 1.0
    nx, ny = -ty / tl, tx / tl
    left = Point(mid.x + nx * 20, mid.y + ny * 20).distance(coast)
    right = Point(mid.x - nx * 20, mid.y - ny * 20).distance(coast)
    return 1 if left < right else -1


def _frame(line, s):
    q = line.interpolate(s)
    a = line.interpolate(max(0.0, s - 0.5))
    b = line.interpolate(min(line.length, s + 0.5))
    tx, ty = b.x - a.x, b.y - a.y
    tl = math.hypot(tx, ty) or 1.0
    return q.x, q.y, -ty / tl, tx / tl


def sd_of(line, x: float, y: float) -> tuple[float, float]:
    s = line.project(Point(x, y))
    qx, qy, nx, ny = _frame(line, s)
    return s, (x - qx) * nx + (y - qy) * ny


def _area2(q) -> float:
    a = 0.0
    for i in range(len(q)):
        x0, y0 = q[i]
        x1, y1 = q[(i + 1) % len(q)]
        a += x0 * y1 - x1 * y0
    return a


def write_piece(m, piece, clip, origin, z: float, uvfn, material: str, writer: Writer) -> int:
    """Add the written road surface of `piece` inside `clip` (cell box, junctions already cut) to MeshData `m`.
    Returns the triangle count added."""
    if clip is None or clip.is_empty:
        return 0
    line, w = piece.line, piece.width
    ox, oy = origin
    ds = breakpoints(w)
    total = line.length
    ss = [i * ROW_M for i in range(int(total // ROW_M) + 1)]
    if total - ss[-1] > 0.05:
        ss.append(total)
    frames = [_frame(line, s) for s in ss]
    pclip = prep(clip)
    minx, miny, maxx, maxy = clip.bounds
    rows_used = []
    tris = 0
    for i in range(len(ss) - 1):
        s0, s1 = ss[i], ss[i + 1]
        f0, f1 = frames[i], frames[i + 1]

        def P(f, d):
            return f[0] + f[2] * d, f[1] + f[3] * d
        row = [P(f0, -w / 2), P(f1, -w / 2), P(f1, w / 2), P(f0, w / 2)]
        xs = [p[0] for p in row]
        ys = [p[1] for p in row]
        if max(xs) < minx or min(xs) > maxx or max(ys) < miny or min(ys) > maxy:
            continue
        quads = []
        ok = True
        for j in range(len(ds) - 1):
            d0, d1 = ds[j], ds[j + 1]
            q = [P(f0, d0), P(f1, d0), P(f1, d1), P(f0, d1)]
            if _area2(q) <= 1e-4:
                ok = False
                break
            quads.append((q, ((s0, d0), (s1, d0), (s1, d1), (s0, d1)), (s0, s1, d0, d1)))
        if not ok:
            continue  # folded row (tight curve): left to the residual fill
        rpoly = Polygon(row)
        if not rpoly.is_valid or not pclip.intersects(rpoly):
            continue
        rows_used.append(rpoly)
        for q, sd, cellsd in quads:
            col = writer.cell_patch(*cellsd)
            qp = Polygon(q)
            if pclip.contains(qp):
                cols = [col or writer.colour(s, d) for s, d in sd]
                m.add_face([(x - ox, y - oy, z) for x, y in q], [uvfn(x, y) for x, y in q], material, tuple(cols))
                tris += 2
            else:
                tris += _fill(m, clip.intersection(qp), origin, z, uvfn, material, writer, line, col)
    if rows_used:
        rest = clip.difference(unary_union(rows_used).buffer(0))
    else:
        rest = clip
    tris += _fill(m, rest, origin, z, uvfn, material, writer, line, None, densify=4.0)
    return tris


def _fill(m, geom, origin, z, uvfn, material, writer, line, col, densify=None) -> int:
    """CDT fill of a clipped or residual area, colours from (s, d) of each corner."""
    ox, oy = origin
    n = 0
    if geom is None or geom.is_empty:
        return 0
    polys = [g for g in getattr(geom, "geoms", [geom]) if isinstance(g, Polygon) and g.area > 1e-4]
    for poly in polys:
        if densify:
            poly = shapely.segmentize(poly, densify)
        try:
            tris = shapely.constrained_delaunay_triangles(poly)
        except shapely.errors.GEOSException:
            continue
        for t in getattr(tris, "geoms", []):
            cs = list(t.exterior.coords)[:3]
            if len(cs) < 3:
                continue
            a2 = _area2(cs)
            if abs(a2) < 1e-6:
                continue
            if a2 < 0:
                cs = [cs[0], cs[2], cs[1]]
            cols = tuple(col or writer.colour(*sd_of(line, x, y)) for x, y in cs)
            m.add_face([(x - ox, y - oy, z) for x, y in cs], [uvfn(x, y) for x, y in cs], material, cols)
            n += 1
    return n
