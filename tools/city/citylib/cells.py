"""Cut the layout on the streaming grid and turn it into per-cell meshes (LOD0, LOD1, collision).

All mesh coordinates are local to the cell's south-west corner (WorldGrid.CellOrigin), so each cell's
root node sits at the cell origin and vertex values stay small. UVs are computed from world
coordinates, so textures run on seamlessly across cell borders.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import shapely
from shapely import ops
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box

from . import frontage_paving as fpave
from . import cell_trim, grid, kit, level_edges, paint_variation, road_writing, rules
from . import lake_edge as lake_edge_mod
from . import materials as M
from .dressing import Dressing
from .layout import EMPTY, Building, Layout, WallSeg, _polys, clean
from .mesh import MeshData

MAT_ROAD = M.ASPHALT
MAT_TRIM = M.STREET_TRIM
MAT_PAVEMENT = M.PAVER
MAT_SEAWALL = M.SEAWALL
MAT_GRASS = M.LAWN
MAT_STRIPE = M.LAWN_STRIPE
MAT_RECLAIMED = M.SAND_RECLAIMED
MAT_WORN = M.LAWN_WORN
MAT_EARTH = M.EARTH
MAT_CONCRETE = M.CONCRETE
MAT_SAND = M.SAND_DRY
MAT_SAND_WET = M.SAND_WET
MAT_SEA = M.WATER_SEA
MAT_LAKE = M.WATER_LAKE
MAT_PROMENADE = M.PAVER
MAT_TERRACOTTA = M.ROOF_TILE
MAT_SANDSTONE = M.SANDSTONE
MAT_PLASTER = M.PLASTER
MAT_SCAFFOLD = M.SCAFFOLD
MAT_TOWER_GLASS = M.TOWER_GLASS
MAT_HERO = M.HERO
NO_MAT = "__none__"  # collision meshes carry no material

WET_SAND_M = 7.0  # wet sand band landward of the waterline (gf_03, gf_04)


@dataclass
class BuildingGeom:
    name: str                      # bld_<osm id>
    pos: tuple[float, float, float]  # cell-local pivot (footprint centroid at road level)
    instances: list[kit.Instance]  # positions relative to pos
    roof: MeshData | None
    landmark_name: str = ""
    landmark_mesh: MeshData | None = None
    props: dict = field(default_factory=dict)


@dataclass
class CellGeom:
    cell: tuple[int, int]
    id: str
    origin: tuple[float, float]
    lod0: dict[str, MeshData] = field(default_factory=dict)
    buildings: list[BuildingGeom] = field(default_factory=list)
    lod1: MeshData = field(default_factory=MeshData)
    col: dict[str, MeshData] = field(default_factory=dict)
    groups: dict[str, list[kit.Instance]] = field(default_factory=dict)  # props and seafront kit, cell-local
    heroes: list[tuple[str, tuple[float, float, float], dict]] = field(default_factory=list)  # HERO_<Name> markers, cell-local
    budget_steps: int = 0  # building detail downgrades taken to fit the LOD0 budget (fit_styled_buildings)
    trimmed: dict = field(default_factory=dict)  # P117 cell_trim: {"dropped": n, "tris": shed} when dressing was trimmed


# --- primitives -------------------------------------------------------------------------------

def tri_poly(m: MeshData, geom, origin, zfn, uvfn, material: str, densify: float | None = None, uv2fn=None,
             afn=None) -> None:
    """Constrained Delaunay triangulation of a (multi)polygon onto MeshData, counter-clockwise (+z normals)."""
    ox, oy = origin
    for poly in _polys(clean(geom)):  # clean: simplify() can leave invalid rings
        if densify:
            poly = shapely.segmentize(poly, densify)
        try:
            tris = shapely.constrained_delaunay_triangles(poly)
        except shapely.errors.GEOSException:
            try:  # rare GEOS failure on touching holes: retry on a slightly regularised ring
                tris = shapely.constrained_delaunay_triangles(clean(poly.buffer(0.01).buffer(-0.01)))
            except shapely.errors.GEOSException:
                continue
        for t in getattr(tris, "geoms", []):
            cs = list(t.exterior.coords)[:3]
            if len(cs) < 3:
                continue
            (x0, y0), (x1, y1), (x2, y2) = cs
            area2 = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area2) < 1e-6:
                continue
            if area2 < 0:
                cs = [cs[0], cs[2], cs[1]]
            m.add_face([(x - ox, y - oy, zfn(x, y)) for x, y in cs], [uvfn(x, y) for x, y in cs], material,
                       uv2=[uv2fn(x, y) for x, y in cs] if uv2fn else None,
                       alpha=[afn(x, y) for x, y in cs] if afn else None)


SEA_RAMP_M = (256.0, 64.0)  # T_SeaRamp: u = metres offshore / 256 (clamped), v = metres along the shore / 64


def sea_uv(coast, axis):
    """Sea UV0 for the depth-ramp texture (MAT_Water_Sea, until the V5 sea shader): u = distance offshore,
    so colour runs turquoise -> teal -> deep blue and the broken foam bands follow the real coastline; v =
    position along the area_strip axis, which breaks the foam up along the shore. Same formula in the cells and
    the horizon band, so they meet without a seam."""
    (ax, ay), (bx, by) = axis.coords[0], axis.coords[-1]
    ln = math.hypot(bx - ax, by - ay) or 1.0
    ux, uy = (bx - ax) / ln, (by - ay) / ln

    def fn(x, y):
        d = coast.distance(Point(x, y)) if coast is not None else 300.0
        return min(d, 1000.0) / SEA_RAMP_M[0], ((x - ax) * ux + (y - ay) * uy) / SEA_RAMP_M[1]
    return fn


def planar(scale):
    """World planar UVs: scale is metres per UV unit, or a material name (its texture size)."""
    su, sv = M.tile(scale) if isinstance(scale, str) else (scale, scale)
    return lambda x, y: (x / su, y / sv)


def along_axis(layout: Layout, scale: float):
    """Planar UVs turned to the area_strip axis, so paver courses (stretcher / herringbone trim) run along
    the promenade."""
    (ax, ay), (bx, by) = layout.axis.coords[0], layout.axis.coords[-1]
    ln = math.hypot(bx - ax, by - ay) or 1.0
    ux, uy = (bx - ax) / ln, (by - ay) / ln
    return lambda x, y: ((x * ux + y * uy) / scale, (-x * uy + y * ux) / scale)


def flat(z: float):
    return lambda x, y: z


def tri_ground(m: MeshData, geom, origin, base: float, terr, uvfn, material: str, densify: float | None = None,
               coarse: bool = False) -> None:
    """tri_poly for a ground surface at the plot datum, split by the terrain level areas (citylib/terrain.py):
    each piece at base + its offset, so hard steps stay sharp and ramps follow the smoothstep. Inside a lawn relief
    (terrain.Relief, the Green) the piece is cut on the relief's grid (twice as coarse with coarse=True, for LOD1) and
    every vertex takes the relief height."""
    if geom is not None and not geom.is_empty and not geom.is_valid:
        geom = shapely.make_valid(geom)  # fort_loop's merged area_strip leaves a sliver self-touch near (204, -295)
    reliefs = getattr(terr, "reliefs", None)
    for piece, off in terr.pieces(geom):
        if not reliefs:
            tri_poly(m, piece, origin, (lambda f: (lambda x, y: base + f(x, y)))(off), uvfn, material, densify)
            continue
        zfn = (lambda f: (lambda x, y: base + f(x, y) + terr.relief_dz(x, y)))(off)
        for sub in terr.relief_cells(piece, coarse):
            tri_poly(m, sub, origin, zfn, uvfn, material, densify)


def wall_quads(m: MeshData, segs: list[WallSeg], cell, origin, material_for, with_uv: bool = True,
               foot_alpha=None) -> None:
    """Vertical faces for wall segments, cut at cell borders; each faces left of p0 -> p1."""
    ox, oy = origin
    for w in segs:
        length = math.dist(w.p0, w.p1)
        for c, a, b in grid.split_segment(w.p0, w.p1):
            if c != cell:
                continue
            ta = math.dist(w.p0, a) / length if length else 0.0
            tb = math.dist(w.p0, b) / length if length else 0.0
            ba = w.bottom0 + (w.bottom1 - w.bottom0) * ta
            bb = w.bottom0 + (w.bottom1 - w.bottom0) * tb
            if w.top - min(ba, bb) < 0.01:
                continue
            pts = [(b[0] - ox, b[1] - oy, bb), (a[0] - ox, a[1] - oy, ba),
                   (a[0] - ox, a[1] - oy, w.top), (b[0] - ox, b[1] - oy, w.top)]
            mat = material_for(w)
            if not with_uv:
                uvs = [(0.0, 0.0)] * 4
            elif mat == MAT_TRIM:
                # kerb face: the street trim's kerb row, 4 m per unit along the kerb
                k0, k1 = M.TRIM_KERB
                span = max(w.top - min(ba, bb), 0.01)
                fv = lambda z: k0 + (k1 - k0) * (z - min(ba, bb)) / span  # noqa: E731
                ua, ub = ta * length / 4.0, tb * length / 4.0
                uvs = [(ub, fv(bb)), (ua, fv(ba)), (ua, k1), (ub, k1)]
            elif mat == M.ROAD_EDGE_TRIM:
                # P117 WS-0339: kerb face from the road edge kit sheet (4 m x 8 m; ROAD_EDGE_KIT_SPEC.md §3): the face
                # band (0.05-0.20 m of the unrolled profile) of Kerb A granite (sea side) or Kerb B precast (land)
                side = getattr(w, "side", "land")
                row = 0.0 if side == "sea" else 1.0 if side == "painted" else 0.5   # Kerb A, C (painted), B
                zb = min(ba, bb)
                span = max(w.top - zb, 0.01)
                fv = lambda z: (row + 0.05 + 0.15 * (z - zb) / span) / 8.0  # noqa: E731
                ua, ub = ta * length / 4.0, tb * length / 4.0
                uvs = [(ub, fv(bb)), (ua, fv(ba)), (ua, fv(w.top)), (ub, fv(w.top))]
            else:
                # stone walls at true scale: u along the wall, v = height in metres (texture size)
                tu, tv = M.tile(mat)
                ua, ub = ta * length / tu, tb * length / tu
                uvs = [(ub, bb / tv), (ua, ba / tv), (ua, w.top / tv), (ub, w.top / tv)]
            fa = foot_alpha(w) if foot_alpha else None   # P87: contact shade at the wall foot (COLOR_0.A)
            m.add_face(pts, uvs, mat, alpha=[fa, fa, 1.0, 1.0] if fa is not None else None)


def building_name(b: Building) -> str:
    """The building's node name: `bld_<osm id>` (< 0: frontage infill), or the hero's generic node name."""
    return b.hero.get("name") or (f"bld_infill_{-b.osm_id}" if b.osm_id < 0 else f"bld_{b.osm_id}")


def prism(m: MeshData, poly: Polygon, origin, z0: float, z1: float, wall_mat: str, roof_mat: str,
          storey_base: float | None = None, wall_color: tuple[float, float, float] | None = None) -> None:
    """Extruded footprint: walls (outward normals) plus a flat roof. No floor (never seen). Wall UVs are
    metres / the wall material's texture size; v counts from storey_base (default z0) so storey-module
    textures (the curtain wall) line up with the floors."""
    ox, oy = origin
    tu, tv = M.tile(wall_mat)
    zb = z0 if storey_base is None else storey_base
    for ring in [poly.exterior] + list(poly.interiors):
        cs = list(ring.coords)
        u = 0.0
        for (ax, ay), (bx, by) in zip(cs, cs[1:]):
            ln = math.hypot(bx - ax, by - ay)
            if ln < 1e-3:
                continue
            pts = [(ax - ox, ay - oy, z0), (bx - ox, by - oy, z0), (bx - ox, by - oy, z1), (ax - ox, ay - oy, z1)]
            va, vb = (z0 - zb) / tv, (z1 - zb) / tv
            m.add_face(pts, [(u / tu, va), ((u + ln) / tu, va), ((u + ln) / tu, vb), (u / tu, vb)], wall_mat,
                       wall_color)
            u += ln
    tri_poly(m, poly, origin, flat(z1), planar(roof_mat), roof_mat)


def road_uv(piece):
    line, w = piece.line, piece.width

    def fn(x, y):
        p = Point(x, y)
        s = line.project(p)
        a = line.interpolate(max(0.0, s - 0.5))
        b = line.interpolate(min(line.length, s + 0.5))
        q = line.interpolate(s)
        tx, ty = b.x - a.x, b.y - a.y
        tl = math.hypot(tx, ty) or 1.0
        d = (tx * (y - q.y) - ty * (x - q.x)) / tl  # signed offset, + = left of travel direction
        tu, tv = M.tile(MAT_ROAD)
        return s / tu, (d + w / 2.0) / tv
    return fn


def lane_count(width: float) -> int:
    return max(1, round(width / 3.25))


def road_markings(piece, keep, origin, z: float, cell, style=None) -> MeshData:
    """Paint lines as thin strips 1 cm above the asphalt, following the piece's centreline (so they follow
    curves): solid white edge lines 0.3 m in from each edge, dashed white lane lines (3 m paint, 5 m gap)
    between lanes. UVs index the street trim's paint rows, 4 m per unit along the line. Strips outside
    `keep` (junctions, other pieces) are dropped; each quad goes to the cell holding its centre. A style with
    `hatch` (config markings.centre_hatch_m) splits a two-way 2 + 2 piece with a hatched centre median."""
    m = MeshData()
    line, w = piece.line, piece.width
    n = lane_count(w)
    ox, oy = origin
    # style (citylib/markings.PieceStyle): edges on a dual road's inboard side are dropped (the carriageways meet at a
    # painted centre line, drawn once on the seaward piece) and the sea-side kerb edge is solid yellow
    skip = style.skip_edges if style else set()
    # P117: a kerbside strip (style.kerbside {side: m}) moves that edge line in; the lanes share what is left
    ks = style.kerbside if style else {}
    lo, hi = -w / 2 + ks.get(-1, 0.0), w / 2 - ks.get(1, 0.0)
    if ks:
        n = lane_count(hi - lo)
    yel = style.yellow_edges if style else set()
    # a side with a kerbside strip keeps its white edge line moved in; its yellow line runs at the kerb (fix 4)
    lines = [(lo + 0.3, 0.12, None, M.TRIM_YELLOW if -1 in yel and -1 not in ks else M.TRIM_WHITE),
             (hi - 0.3, 0.12, None, M.TRIM_YELLOW if 1 in yel and 1 not in ks else M.TRIM_WHITE)]
    lines = [ln for ln, sd in zip(lines, (-1, 1)) if sd not in skip]
    lines += [(sd * (w / 2 - 0.3), 0.12, None, M.TRIM_YELLOW) for sd in (-1, 1) if sd in yel and sd in ks
              and sd not in skip]
    gap = getattr(style, "yellow_gap", None) if style else None
    median = getattr(style, "median", 0.0) if style else 0.0
    med_skip = getattr(style, "median_skip", None) if style else None
    med_off = None
    if median > 0.0 and len(skip) == 1:
        # CIRCLE fix 5 (r5.centre_rd): a painted median zone between the carriageways: a solid line on this piece's
        # inboard edge of it (none beside the raised islands or in the gaps between them); the lanes are laid
        # between the outer edge line and that line
        from .markings import lane_offsets
        med_off = next(iter(skip)) * (w / 2 - median / 2)
        lines.append((med_off, 0.1, None, M.TRIM_WHITE))
    elif style and style.centre:
        lines.append((style.centre * w / 2, 0.1, None, M.TRIM_WHITE))
    hatch = getattr(style, "hatch", 0.0) if style else 0.0
    if med_off is not None:
        _, l0, l1 = lane_offsets(w, style)
        nm = lane_count(l1 - l0)
        lines += [(l0 + (l1 - l0) * k / nm, 0.1, (3.0, 5.0), M.TRIM_WHITE) for k in range(1, nm)]
    elif hatch > 0.0 and n >= 2 and n % 2 == 0:
        # CIRCLE fix 2 (04_wide, sv_15): a two-way 2 + 2 road gets a hatched centre median, solid lines each side
        # and diagonal bars every 4 m; each direction's lanes share its half
        hh = hatch / 2
        lines += [(-hh, 0.1, None, M.TRIM_WHITE), (hh, 0.1, None, M.TRIM_WHITE)]
        half = n // 2
        lines += [(lo + (-hh - lo) * k / half, 0.1, (3.0, 5.0), M.TRIM_WHITE) for k in range(1, half)]
        lines += [(hh + (hi - hh) * k / half, 0.1, (3.0, 5.0), M.TRIM_WHITE) for k in range(1, half)]
        total, s = line.length, 2.0
        while s + hatch < total:
            pa, pb = line.interpolate(s), line.interpolate(s + hatch)
            pc = line.interpolate(min(total, s + 0.5))
            tx, ty = pc.x - pa.x, pc.y - pa.y
            tl = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / tl, tx / tl
            a = (pa.x - nx * (hh - 0.1), pa.y - ny * (hh - 0.1))
            b = (pb.x + nx * (hh - 0.1), pb.y + ny * (hh - 0.1))
            mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if keep.contains(mid) and grid.cell_of(mid.x, mid.y) == cell:
                dx, dy = b[0] - a[0], b[1] - a[1]
                dl = math.hypot(dx, dy) or 1.0
                px, py = -dy / dl * 0.15, dx / dl * 0.15
                r0, r1 = M.TRIM_WHITE
                m.add_face([(a[0] - px - ox, a[1] - py - oy, z), (b[0] - px - ox, b[1] - py - oy, z),
                            (b[0] + px - ox, b[1] + py - oy, z), (a[0] + px - ox, a[1] + py - oy, z)],
                           [(0.0, r0), (dl / 4.0, r0), (dl / 4.0, r1), (0.0, r1)], MAT_TRIM)
            s += 4.0
    else:
        double = bool(style and style.double_centre and n % 2 == 0)
        for k in range(1, n):
            if double and k == n // 2:
                # Baladaksha (os_16, os_18, os_20): two solid white lines 0.2 m apart, no dashes, no hatched strip
                lines += [(lo + (hi - lo) * k / n + d, 0.1, None, M.TRIM_WHITE) for d in (-0.2, 0.2)]
            else:
                lines.append((lo + (hi - lo) * k / n, 0.1, (3.0, 5.0), M.TRIM_WHITE))
    step = 2.0
    total = line.length
    for off, half_w, dash, (r0, r1) in lines:
        s = 0.0
        while s < total - 0.1:
            s1 = min(total, s + step)
            if dash:
                period = dash[0] + dash[1]
                ph = s % period
                if ph >= dash[0]:
                    s = s - ph + period
                    continue
                s1 = min(s1, s - ph + dash[0])
            pa, pb = line.interpolate(s), line.interpolate(s1)
            tx, ty = pb.x - pa.x, pb.y - pa.y
            tl = math.hypot(tx, ty)
            if tl < 0.05:
                s = s1
                continue
            nx, ny = -ty / tl, tx / tl  # left normal
            a = (pa.x + nx * off, pa.y + ny * off)
            b = (pb.x + nx * off, pb.y + ny * off)
            mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if off == med_off and med_skip is not None and med_skip.contains(mid):
                s = s1
                continue
            if keep.contains(mid) and grid.cell_of(mid.x, mid.y) == cell:
                q = [(a[0] - nx * half_w, a[1] - ny * half_w), (b[0] - nx * half_w, b[1] - ny * half_w),
                     (b[0] + nx * half_w, b[1] + ny * half_w), (a[0] + nx * half_w, a[1] + ny * half_w)]
                v0, v1 = M.TRIM_WHITE if gap is not None and (r0, r1) == M.TRIM_YELLOW and gap.contains(mid) \
                    else (r0, r1)   # fix 4: no yellow no-parking line beside parking bays
                m.add_face([(x - ox, y - oy, z) for x, y in q],
                           [(s / 4.0, v0), (s1 / 4.0, v0), (s1 / 4.0, v1), (s / 4.0, v1)], MAT_TRIM)
            s = s1
    return m


# --- buildings --------------------------------------------------------------------------------

def _open_rings(poly: Polygon) -> list[list[tuple[float, float]]]:
    return [list(r.coords)[:-1] for r in [poly.exterior] + list(poly.interiors)]


def hipped_roof(m: MeshData, poly: Polygon, origin, z: float, material: str,
                pitch: float = 0.6, overhang: float = 0.6) -> None:
    """Hipped roof over the footprint's minimum rotated rectangle (Art Bible: terracotta hipped roofs).
    Non-rectangular footprints are cut into strips along the long axis, each with its own hip."""
    ox, oy = origin
    mrr = poly.minimum_rotated_rectangle
    cs = list(mrr.exterior.coords)[:4]
    e0 = math.dist(cs[0], cs[1])
    e1 = math.dist(cs[1], cs[2])
    if e1 > e0:
        cs = cs[1:] + cs[:1]
        e0, e1 = e1, e0
    pieces = [poly]
    if poly.area / max(mrr.area, 1e-6) < 0.8 and e0 > 1.6 * e1:
        n = max(2, round(e0 / (e1 * 0.9)))
        ux, uy = (cs[1][0] - cs[0][0]) / e0, (cs[1][1] - cs[0][1]) / e0
        vx, vy = (cs[3][0] - cs[0][0]) / e1, (cs[3][1] - cs[0][1]) / e1
        pieces = []
        for k in range(n):
            a0, a1 = e0 * k / n, e0 * (k + 1) / n
            strip = Polygon([(cs[0][0] + ux * a0, cs[0][1] + uy * a0), (cs[0][0] + ux * a1, cs[0][1] + uy * a1),
                             (cs[0][0] + ux * a1 + vx * e1, cs[0][1] + uy * a1 + vy * e1),
                             (cs[0][0] + ux * a0 + vx * e1, cs[0][1] + uy * a0 + vy * e1)])
            pieces += [p for p in _polys(poly.intersection(strip)) if p.area > 20.0]
    for piece in pieces:
        r = piece.minimum_rotated_rectangle.buffer(overhang, join_style="mitre")
        c = list(orient_ccw(r).exterior.coords)[:4]
        l0, l1 = math.dist(c[0], c[1]), math.dist(c[1], c[2])
        if l1 > l0:
            c = c[1:] + c[:1]
            l0, l1 = l1, l0
        hr = l1 / 2 * pitch
        mx, my = sum(p[0] for p in c) / 4, sum(p[1] for p in c) / 4
        ux, uy = (c[1][0] - c[0][0]) / l0, (c[1][1] - c[0][1]) / l0
        half = (l0 - l1) / 2
        r0 = (mx - ux * half, my - uy * half)
        r1 = (mx + ux * half, my + uy * half)
        P = lambda q, zz: (q[0] - ox, q[1] - oy, zz)  # noqa: E731
        zt = z + hr
        tu, tv = M.tile(material)

        def slope_face(e0, e1, others):
            """Roof plane on eave e0 -> e1: u along the eave, v up the slope, both in metres / tile, so
            the tile courses run level and the tiles keep their real size on every pitch."""
            ex, ey = e1[0] - e0[0], e1[1] - e0[1]
            el = math.hypot(ex, ey) or 1.0
            ex, ey = ex / el, ey / el
            pts = [(e0, z), (e1, z)] + others

            def uv(q, zz):
                du = (q[0] - e0[0]) * ex + (q[1] - e0[1]) * ey
                dn = abs(-(q[0] - e0[0]) * ey + (q[1] - e0[1]) * ex)
                return du / tu, math.hypot(dn, zz - z) / tv
            m.add_face([P(q, zz) for q, zz in pts], [uv(q, zz) for q, zz in pts], material)
        slope_face(c[0], c[1], [(r1, zt), (r0, zt)])
        slope_face(c[1], c[2], [(r1, zt)])
        slope_face(c[2], c[3], [(r0, zt), (r1, zt)])
        slope_face(c[3], c[0], [(r0, zt)])


def orient_ccw(poly: Polygon) -> Polygon:
    from shapely.geometry.polygon import orient
    return orient(poly, 1.0)


def portico(m: MeshData, poly: Polygon, origin, base: float, top: float, toward, material: str) -> None:
    """Columned portico with pediment on the footprint edge that faces `toward` (a point)."""
    ox, oy = origin
    cs = list(poly.exterior.coords)
    best = None
    for (ax, ay), (bx, by) in zip(cs, cs[1:]):
        ln = math.hypot(bx - ax, by - ay)
        if ln < 12.0:
            continue
        nx, ny = (by - ay) / ln, -(bx - ax) / ln
        mx, my = (ax + bx) / 2, (ay + by) / 2
        tx, ty = toward[0] - mx, toward[1] - my
        tl = math.hypot(tx, ty) or 1.0
        score = (nx * tx + ny * ty) / tl * math.sqrt(ln)
        if best is None or score > best[0]:
            best = (score, ax, ay, bx, by, ln, nx, ny)
    if best is None:
        return
    _, ax, ay, bx, by, ln, nx, ny = best
    ux, uy = (bx - ax) / ln, (by - ay) / ln
    width, depth = ln * 0.6, 4.5
    s0 = (ln - width) / 2

    def F(a, b, z):  # a along the edge from its start, b outward from the facade
        return (ax + ux * (s0 + a) + nx * b - ox, ay + uy * (s0 + a) + ny * b - oy, z)

    def quad(p, q, r, t):
        m.add_face([p, q, r, t], [(0, 0), (1, 0), (1, 1), (0, 1)], material)

    def block(a0, a1, b0, b1, z0, z1):
        corners = [F(a0, b1, 0), F(a1, b1, 0), F(a1, b0, 0), F(a0, b0, 0)]  # outer edge first: ccw seen from above
        ring = [(c[0], c[1]) for c in corners]
        if sum((ring[i][0] * ring[(i + 1) % 4][1] - ring[(i + 1) % 4][0] * ring[i][1]) for i in range(4)) < 0:
            ring.reverse()
        prism_xy(m, ring, z0, z1, material)

    block(-1.0, width + 1.0, 0.0, depth + 1.5, base, base + 1.0)             # plinth and steps
    ncol = max(4, int(width / 3.2) + 1)
    for k in range(ncol):
        a = width * k / (ncol - 1)
        cx, cy, _ = F(a, depth - 0.3, 0)
        ring = [(cx + 0.45 * math.cos(2 * math.pi * i / 8), cy + 0.45 * math.sin(2 * math.pi * i / 8)) for i in range(8)]
        prism_xy(m, ring, base + 1.0, top - 1.6, material)
    block(-0.3, width + 0.3, 0.0, depth + 0.2, top - 1.6, top - 0.6)          # entablature
    hp = 3.0                                                                   # pediment
    apex_a = width / 2
    for b, flip in ((depth + 0.2, False), (0.0, True)):
        tri = [F(-0.3, b, top - 0.6), F(width + 0.3, b, top - 0.6), F(apex_a, b, top - 0.6 + hp)]
        if flip:
            tri.reverse()
        m.add_face(tri, [(0, 0), (1, 0), (0.5, 1)], material)
    quad(F(apex_a, depth + 0.2, top - 0.6 + hp), F(width + 0.3, depth + 0.2, top - 0.6),
         F(width + 0.3, 0.0, top - 0.6), F(apex_a, 0.0, top - 0.6 + hp))
    quad(F(-0.3, depth + 0.2, top - 0.6), F(apex_a, depth + 0.2, top - 0.6 + hp),
         F(apex_a, 0.0, top - 0.6 + hp), F(-0.3, 0.0, top - 0.6))


def _lines_of(g) -> list:
    if g is None or g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    return [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString" and x.length > 0.1]


def prism_xy(m: MeshData, ring, z0: float, z1: float, material: str) -> None:
    """Closed prism (walls + cap) for a counter-clockwise ring already in cell-local coordinates."""
    n = len(ring)
    for i in range(n):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % n]
        m.add_face([(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1)], [(0, 0), (1, 0), (1, 1), (0, 1)], material)
    m.add_face([(x, y, z1) for x, y in ring], [(x / 4, y / 4) for x, y in ring], material)


LAKE_BED_M = 1.2        # collision-only lake bed below the water surface
SEA_BED_M = 2.0         # collision-only sea bed below sea level (nothing falls into a void offshore)
SEA_BED_REACH_M = 1.5   # the sea bed collider reaches this far past the sea (covers the simplify error)
LAKE_BARRIER_M = 1.0    # invisible barrier height above the bank top (plot level)
SEAWALL_BARRIER_M = 0.9  # invisible barrier on the seawall top
STEP_GAP_M = 3.0        # barrier left open this far either side of a seawall step


def _both_sides(w: WallSeg) -> list[WallSeg]:
    return [w, WallSeg(w.p1, w.p0, w.bottom1, w.bottom0, w.top, w.kind)]


def safety_barriers(layout: Layout, dressing: Dressing | None) -> list[WallSeg]:
    """Collision-only walls: lake banks closed down to the lake bed and raised LAKE_BARRIER_M above the bank top,
    and SEAWALL_BARRIER_M on the seawall tops with gaps at the beach steps (TDD "Cell streaming as built")."""
    h = layout.heights
    out: list[WallSeg] = []
    for w in layout.walls:
        if w.kind != "bank":
            continue
        out.append(WallSeg(w.p0, w.p1, h.lake - LAKE_BED_M, h.lake - LAKE_BED_M, h.lake, "bank_bed"))
        out += _both_sides(WallSeg(w.p0, w.p1, w.top, w.top, w.top + LAKE_BARRIER_M, "barrier"))
    # sea edges that are not beach (quays, the canal mouth): a closed drop to the sea bed plus a barrier
    if not layout.sea.is_empty:
        beach_probe = layout.beach.buffer(0.5) if not layout.beach.is_empty else Polygon()
        rim = layout.area_strip.exterior.buffer(0.1)
        for poly in _polys(layout.sea):
            for ring in [poly.exterior] + list(poly.interiors):
                cs = list(ring.coords)
                for a, b in zip(cs, cs[1:]):
                    mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    if math.dist(a, b) < 0.05 or rim.contains(mid) or beach_probe.contains(mid):
                        continue
                    out += _both_sides(WallSeg(a, b, h.sea - SEA_BED_M, h.sea - SEA_BED_M, h.plot + LAKE_BARRIER_M, "barrier_sea"))
    steps = [(i.x, i.y) for g, i in (dressing.placements if dressing else []) if i.piece.startswith("KIT_SeawallSteps")]
    for p0, p1, top in layout.seawall:
        seg = LineString([p0, p1])
        if steps:
            gaps = ops.unary_union([Point(x, y).buffer(STEP_GAP_M) for x, y in steps if seg.distance(Point(x, y)) < 6.0]) \
                if any(seg.distance(Point(x, y)) < 6.0 for x, y in steps) else None
            parts = seg.difference(gaps) if gaps is not None else seg
        else:
            parts = seg
        for part in _lines_of(parts):
            cs = list(part.coords)
            for a, b in zip(cs, cs[1:]):
                out += _both_sides(WallSeg(a, b, top, top, top + SEAWALL_BARRIER_M, "barrier"))
    out += list(getattr(layout, "road_block_walls", []))   # road blocks on the drive circle's exits (road_blocks.py)
    return out


# Cell LOD0 budget fit for district-styled buildings (the route extension): if a cell's styled buildings
# exceed this many kit triangles, the largest are rebuilt with less detail, step by step (BUDGET_STEPS).
STYLED_BUILDING_TRIS = 44000
CELL_LOD0_TARGET = 57000  # fit target for a whole cell: 3k under the 60k LOD0 budget (estimates, roofs, tanks)
BUDGET_STEPS = ({"street_floors": 1}, {"street_floors": 0},
                {"street_floors": 0, "ground": ("KIT_Shopfront_Glazed_B", "KIT_Shopfront_Shutter_B")},
                # dense frontage (Fort with infill): 4.5 m then 6 m wide shutter bays, no corner piers
                {"street_floors": 0, "ground": ("KIT_Shopfront_Glazed_B", "KIT_Shopfront_Shutter_B"),
                 "ground_bay_m": 4.5, "corners": False},
                {"street_floors": 0, "ground": ("KIT_Shopfront_Glazed_B", "KIT_Shopfront_Shutter_B"),
                 "ground_bay_m": 6.0, "corners": False})


def _kit_tris() -> dict[str, int]:
    import json
    import os
    from . import street_kit
    if not os.path.exists(street_kit.TRIS_JSON):
        return {}
    with open(street_kit.TRIS_JSON, encoding="utf-8") as fh:
        table = json.load(fh)
    from . import poles   # P134: pole / wire markers (Art/World/Poles) count at their LOD0 triangles
    table.update(poles.tris_table())
    from . import carts   # P117: the carts are ~1.3-1.5k triangles each, not the 100 default
    if os.path.exists(carts.TRIS_JSON):
        with open(carts.TRIS_JSON, encoding="utf-8") as fh:
            table.update(json.load(fh))
    from . import road_edge   # P117 WS-0339: the P92b road edge kit
    table.update(road_edge.TRIS)
    from . import signs   # P123: sign kit markers (Art/World/Signs) count at their LOD0 triangles
    table.update(signs.tris_table())
    from . import street2_kit   # HEIGHTS/placement 2026-11-24: the round-5 street kit markers
    table.update(street2_kit.tris_table())
    return table


def building_tris(bg: BuildingGeom, table: dict[str, int]) -> int:
    return sum(table.get(i.piece, 100) for i in bg.instances)


def fit_styled_buildings(mine: list[Building], layout: Layout, origin, table: dict[str, int],
                         budget: int = STYLED_BUILDING_TRIS, other_tris: int | None = None) -> tuple[list[BuildingGeom], int]:
    """Buildings of one cell. District-styled ones are rebuilt with less street detail, largest first, until
    their kit triangles fit the budget; unstyled (Delta Face) buildings are never touched. With other_tris (the
    cell's surfaces and dressing), the budget is what is left of CELL_LOD0_TARGET after them and the unstyled
    buildings. Returns the geometry and how many downgrade steps were taken."""
    level = {b.osm_id: -1 for b in mine}
    geoms = {b.osm_id: building_geom(b, layout, origin) for b in mine}
    styled = [b for b in mine if rules.DISTRICT_STYLES.get(b.district)]
    if other_tris is not None:
        unstyled = sum(building_tris(geoms[b.osm_id], table) for b in mine if not rules.DISTRICT_STYLES.get(b.district))
        budget = CELL_LOD0_TARGET - other_tris - unstyled
    steps = 0
    while styled and table:
        total = sum(building_tris(geoms[b.osm_id], table) for b in styled)
        if total <= budget:
            break
        cand = [b for b in styled if level[b.osm_id] < len(BUDGET_STEPS) - 1]
        if not cand:
            break
        b = max(cand, key=lambda q: building_tris(geoms[q.osm_id], table))
        level[b.osm_id] += 1
        geoms[b.osm_id] = building_geom(b, layout, origin, BUDGET_STEPS[level[b.osm_id]])
        steps += 1
    return [geoms[b.osm_id] for b in mine], steps


def building_geom(b: Building, layout: Layout, origin, detail: dict | None = None) -> BuildingGeom:
    h = layout.heights
    fp = b.footprint
    c = fp.centroid
    base = h.road + b.base
    pos = (c.x - origin[0], c.y - origin[1], h.road)
    name = building_name(b)
    props = {"osm_id": b.osm_id, "levels": b.levels, "levels_source": b.levels_source,
             "building": b.tags.get("building", "yes")}
    if b.base > 0:
        props["base_m"] = round(b.base, 2)
    if b.hero:
        props["hero"] = b.hero.get("style", "kit")
    top = base + rules.wall_height(b.levels)
    local = (c.x, c.y)
    if b.landmark or b.sacred:
        # Hand-modelled hero later (TDD "Heroes"): a named mass that holds the footprint, height and the
        # big recognisable shapes (hipped terracotta roofs, the columned portico), nothing finer.
        lm = MeshData()
        if b.landmark.endswith("Hotel"):
            prism(lm, fp, local, base, top, MAT_PLASTER, MAT_CONCRETE)
            hipped_roof(lm, fp, local, top, MAT_TERRACOTTA)
        elif "Assembly" in b.landmark:
            prism(lm, fp, local, base, top, MAT_SANDSTONE, MAT_SANDSTONE)
            near = layout.road_area.boundary.interpolate(layout.road_area.boundary.project(fp.centroid))
            portico(lm, fp, local, base, top, (near.x, near.y), MAT_SANDSTONE)
        else:
            prism(lm, fp, local, base, top, MAT_HERO, MAT_HERO)
        lm_name = b.landmark or "SACRED_Placeholder"
        props["placeholder"] = lm_name
        return BuildingGeom(name, pos, [], None, f"{lm_name}_{b.osm_id}", lm, props)

    if b.hero.get("style") == "fin_tower":
        # Dark glazed tower with white vertical fins and banding (facade rhythm as geometry + trim).
        lm = MeshData()
        prism(lm, fp, local, base, top, MAT_TOWER_GLASS, MAT_CONCRETE, storey_base=base + rules.GROUND_FLOOR_M)
        fins = []
        for ring in _open_rings(fp)[:1]:
            n = len(ring)
            for e in range(n):
                (ax, ay), (bx, by) = ring[e], ring[(e + 1) % n]
                ln = math.hypot(bx - ax, by - ay)
                if ln < 2.0:
                    continue
                cnt = max(1, round(ln / float(b.hero.get("fin_spacing_m", 4.5))))
                rot = math.atan2(by - ay, bx - ax)
                for k in range(cnt + (1 if e == 0 else 0)):
                    t = k / cnt
                    fins.append(kit.Instance("KIT_Fin_Vertical_A", ax + (bx - ax) * t - c.x, ay + (by - ay) * t - c.y,
                                             b.base, rot, 1.0, 1.0, top - base))
        return BuildingGeom(name, pos, fins, None, f"{name}_Mass", lm, props)

    rings = _open_rings(fp)
    style = rules.DISTRICT_STYLES.get(b.district)
    if style is not None and detail:
        style = {**style, **detail}
    inst, top = kit.assemble_building(b.osm_id, rings, b.street, b.levels, base, style)
    inst_local = [kit.Instance(i.piece, i.x - c.x, i.y - c.y, i.z - h.road, i.rot, i.sx) for i in inst]
    roof = MeshData()
    tri_poly(roof, fp, local, flat(top - h.road), planar(MAT_CONCRETE), MAT_CONCRETE)
    if b.base > 0:  # floating mass (skybridge, overhang): close the underside
        under = MeshData()
        tri_poly(under, fp, local, flat(b.base), planar(MAT_CONCRETE), MAT_CONCRETE)
        under.faces = [tuple(reversed(f)) for f in under.faces]
        under.uvs = [tuple(reversed(u)) for u in under.uvs]
        roof.extend(under)
    tanks = kit.roof_tank_positions(b.osm_id, local, fp.area, b.levels)
    inner = fp.buffer(-1.2)
    spots = []
    if tanks and not inner.is_empty:
        rp = inner.representative_point()
        spots.append((rp.x, rp.y))
        far = max(_open_rings(fp)[0], key=lambda q: math.dist(q, (rp.x, rp.y)))
        q2 = (rp.x + (far[0] - rp.x) * 0.4, rp.y + (far[1] - rp.y) * 0.4)
        if tanks > 1 and inner.contains(Point(q2)) and math.dist(q2, spots[0]) > 1.6:
            spots.append(q2)
    for k, (x, y) in enumerate(spots):
        inst_local.append(kit.Instance("KIT_RoofTank_A", x - c.x, y - c.y, top - h.road, 0.3 * k + (b.osm_id % 7) * 0.2))
    return BuildingGeom(name, pos, inst_local, roof, props=props)


def layout_skybridges(layout: Layout) -> list[dict]:
    return layout.stats.get("_skybridges", [])


def skybridge_geom(spec: dict, layout: Layout, origin) -> tuple[tuple[float, float], BuildingGeom] | None:
    """A box bridge between two tower masses (config "skybridges"), as a named hero placeholder."""
    by_id = {b.osm_id: b for b in layout.buildings}
    a, b2 = (by_id.get(i) for i in spec["between"])
    if a is None or b2 is None:
        return None
    pa, pb = a.footprint.centroid, b2.footprint.centroid
    mx, my = (pa.x + pb.x) / 2, (pa.y + pb.y) / 2
    dx, dy = pb.x - pa.x, pb.y - pa.y
    ln = math.hypot(dx, dy) or 1.0
    ux, uy = dx / ln, dy / ln
    w = float(spec.get("width_m", 14.0)) / 2
    z0, z1 = (layout.heights.road + z for z in spec["z_m"])
    ring = [(pa.x - uy * w, pa.y + ux * w), (pa.x + uy * w, pa.y - ux * w),
            (pb.x + uy * w, pb.y - ux * w), (pb.x - uy * w, pb.y + ux * w)]
    poly = orient_ccw(Polygon(ring))
    m = MeshData()
    prism(m, poly, (mx, my), z0, z1, MAT_TOWER_GLASS, MAT_CONCRETE)
    under = MeshData()
    tri_poly(under, poly, (mx, my), flat(z0), planar(MAT_CONCRETE), MAT_CONCRETE)
    under.faces = [tuple(reversed(f)) for f in under.faces]
    under.uvs = [tuple(reversed(u)) for u in under.uvs]
    m.extend(under)
    m = m.translated(0.0, 0.0, -layout.heights.road)
    name = spec["name"]
    return (mx, my), BuildingGeom(name, (mx - origin[0], my - origin[1], layout.heights.road), [], None,
                                  f"{name}_Bridge", m, {"hero": "skybridge", "between": list(spec["between"])})


# --- cells ------------------------------------------------------------------------------------

def paint_quads(m: MeshData, quads, origin, z_road: float, z_plot, cell) -> None:
    """Decals from citylib/markings.py: each quad goes to the cell holding its centre, 1 cm above its surface."""
    ox, oy = origin
    for q in quads:
        cx, cy = q.centre
        if grid.cell_of(cx, cy) != cell:
            continue
        z = z_road if q.level == "road" else z_plot(cx, cy)
        m.add_face([(x - ox, y - oy, z) for x, y in q.pts], list(q.uvs), q.mat)


def fold_materials(cell_geoms: list, fold: dict) -> dict:
    """P117 (cell material cap): config "material_fold" {cell id: {material: replacement}} renames a material in that
    cell's LOD0 meshes to one the cell already draws (a few wall faces in a cell one material over the cap), so the
    SRP batcher count drops by one without a look change elsewhere. Returns {cell id: faces moved}."""
    moved = {}
    for cg in cell_geoms:
        rule = {k: v for k, v in fold.get(cg.id, {}).items() if not k.startswith("_")}
        if not rule:
            continue
        n = 0
        for m in cg.lod0.values():
            if not any(name in rule for name in m.materials):
                continue
            remap = {i: m.slot(rule.get(name, name)) for i, name in enumerate(list(m.materials))}
            n += sum(1 for k in m.mats if remap[k] != k)
            m.mats = [remap[k] for k in m.mats]
            used = sorted(set(m.mats))
            keep = {old: new for new, old in enumerate(used)}
            m.materials = [m.materials[i] for i in used]
            m.mats = [keep[k] for k in m.mats]
        moved[cg.id] = n
    return moved


def build_cells(layout: Layout, dressing: Dressing | None = None, only: set[str] | None = None, marks=None) -> list[CellGeom]:
    h = layout.heights
    area_strip = layout.area_strip
    beach_coast = layout.coast

    def beach_z(x, y):
        if beach_coast is None:
            return h.beach_top
        p = Point(x, y)
        d = beach_coast.distance(p) * (1.0 if layout.land.contains(p) else -1.0)
        return max(h.beach_min, min(h.beach_top, h.sea + h.beach_slope * d))

    if beach_coast is not None and not layout.beach.is_empty:
        beach_wet = clean(layout.beach.intersection(beach_coast.buffer(getattr(h, "beach_wet_m", WET_SAND_M))))
        beach_dry = clean(layout.beach.difference(beach_wet))
    else:
        beach_wet, beach_dry = EMPTY, layout.beach

    def offshore(x, y):
        """UV2 for water: (metres offshore from the coastline, 0) for the V5 sea shader's depth/foam ramps."""
        if beach_coast is None:
            return (0.0, 0.0)
        return (round(beach_coast.distance(Point(x, y)), 2), 0.0)

    seauv = sea_uv(beach_coast, layout.axis)
    replaced = {s.landmark for s in layout.heroes if s.landmark}
    cells = []
    tris_table = _kit_tris()
    safety_walls = safety_barriers(layout, dressing)
    # P87 level edges (citylib/level_edges.py): swept step runs cut out of the ground, contact-shade bands at wall feet
    runs = getattr(layout.terrain, "step_runs", [])
    stairs_cut = level_edges.footprints(runs)
    shade = getattr(layout.terrain, "contact_shade", {}) or {}
    strength = float(shade.get("strength", 0.0))
    bands_m = [float(b) for b in shade.get("bands_m", [0.4, 1.6])]
    drive_m = float(shade.get("promenade_drive_m", 0.0))
    seawall_segs = [(p0, p1) for p0, p1, _top in layout.seawall]
    drive = (clean(layout.promenade.intersection(MultiLineString([list(sg) for sg in seawall_segs]).buffer(drive_m, cap_style="flat")))
             if drive_m > 0 and seawall_segs and not layout.promenade.is_empty else EMPTY)
    retaining = [(w.p0, w.p1) for w in layout.walls if w.kind == "retaining"
                 and abs(min(w.bottom0, w.bottom1) - h.promenade) < 0.05]
    edge_prom = level_edges.edge_class("promenade_wall", retaining, h.plot - h.promenade, 0.0, layout.promenade) \
        if strength > 0 else None
    wall_foot = 1.0 - strength * (1.0 - float(shade.get("wall_foot_alpha", 0.6)))
    bands_m_sea = [float(b) for b in shade.get("seawall_bands_m", [1.0, 3.5])]
    edge_sea = level_edges.edge_class("seawall", seawall_segs, h.promenade - h.beach_top,
                                      float(shade.get("seawall_toe_m", 1.25)), layout.beach) if strength > 0 else None
    for cell in grid.cells_in_bounds(*area_strip.bounds):
        cid = grid.cell_id(cell)
        if only and cid not in only:
            continue
        cbox = box(*grid.cell_bounds(cell))
        if area_strip.intersection(cbox).area < 1.0:
            continue
        o = grid.cell_origin(cell)
        cg = CellGeom(cell, cid, o)

        edge = getattr(layout, "lake_edge", None)
        edge_fp = clean(edge.footprint.intersection(cbox)) if edge is not None else EMPTY   # P165: the edge replaces what lay under it

        def cut(g):
            if g.is_empty:
                return EMPTY
            g = g.intersection(cbox)
            g = g.difference(stairs_cut) if not stairs_cut.is_empty and g.intersects(stairs_cut) else g
            return clean(g.difference(edge_fp)) if not edge_fp.is_empty else clean(g)

        # LOD0 flat layers
        road = MeshData()
        for piece in layout.roads:
            if road_writing.ENABLED:  # RX-0012 / WS-0003: 2 m strip grid with wear in COLOR_0.rgb
                wr = road_writing.Writer(piece, road_writing.sea_side_of(piece, layout),
                                         seed=float(sum(ord(ch) for ch in piece.name) % 997))
                road_writing.write_piece(road, piece, cut(piece.poly), o, h.road, road_uv(piece), MAT_ROAD, wr)
            else:
                tri_poly(road, cut(piece.poly), o, flat(h.road), road_uv(piece), MAT_ROAD, densify=4.0)
        tri_poly(road, cut(layout.junctions), o, flat(h.road), planar(MAT_ROAD), MAT_ROAD)
        lane = getattr(layout, "parking_lane", None)
        if lane is not None and not lane.is_empty and lane.intersects(cbox):
            # CIRCLE fix 5: the parking lane is road; its asphalt carries on the UVs of the carriageway beside it
            for part in _polys(cut(lane)):
                rp = part.representative_point()
                piece = min(layout.roads, key=lambda r: r.poly.distance(rp))
                tri_poly(road, part, o, flat(h.road), road_uv(piece), MAT_ROAD, densify=4.0)
        open_road = layout.road_area.difference(layout.junctions).buffer(-0.05)
        for piece in layout.roads:
            if piece.line.intersects(cbox.buffer(20.0)):
                road.extend(road_markings(piece, open_road.intersection(piece.poly.buffer(0.3)), o, h.road + 0.01, cell,
                                          marks.styles.get(id(piece)) if marks else None))
        if marks:
            def plot_z(x, y):
                for _p, off in layout.terrain.pieces(Point(x, y).buffer(0.05)):
                    return h.plot + off(x, y) + 0.01
                return h.plot + 0.01
            paint_quads(road, marks.quads, o, h.road + 0.012, plot_z, cell)

        pav = MeshData()

        def promenade_surface(paver_mat):
            """P87: the promenade as brick paver on the Green side and the Delta Face Drive asphalt (promenade_drive_m)
            along the seawall, one level (DELTA_FACE_MEASURED.md layer 5), with the contact-shade bands at the foot of
            the Green wall cut out of the floor and carrying COLOR_0.A."""
            prom = cut(layout.promenade)
            if prom.is_empty:
                return
            bands = level_edges.contact_bands(edge_prom, bands_m, cbox) if edge_prom else []
            band_u = ops.unary_union([b for b, _r in bands]) if bands else EMPTY
            drv = clean(prom.intersection(drive)) if not drive.is_empty else EMPTY
            uv_p = along_axis(layout, M.tile(paver_mat)[0])
            uv_d = along_axis(layout, M.tile(M.ASPHALT)[0])
            tri_poly(pav, clean(prom.difference(drv).difference(band_u)), o, flat(h.promenade), uv_p, paver_mat)
            tri_poly(pav, clean(drv.difference(band_u)), o, flat(h.promenade), uv_d, M.ASPHALT)
            af = (lambda x, y: edge_prom.alpha(x, y, strength))
            for b, _r in bands:
                b = clean(b.intersection(prom))
                tri_poly(pav, clean(b.difference(drv)), o, flat(h.promenade), uv_p, paver_mat, densify=1.0, afn=af)
                tri_poly(pav, clean(b.intersection(drv)), o, flat(h.promenade), uv_d, M.ASPHALT, densify=1.0, afn=af)

        # P2 (citylib/roadside.paver_zones): seafront running bond beside Centre Road's sea side and on the
        # promenade, the 45 degree plaza at signal-junction NW corners (sv_03, sv_15); the rest keeps MAT_PAVEMENT
        zones = getattr(marks, "paver_zones", None) if marks else None
        # SLICE4d (citylib/frontage_paving.py): a hero's frontage paver (hotel Delta Road herringbone) wins over both
        front = getattr(layout, "frontage_paving", None) or []
        if zones:
            pv = cut(layout.pavement)
            for fz in front:
                fp = clean(pv.intersection(fz.poly))
                if fp.is_empty:
                    continue
                pv = clean(pv.difference(fz.poly))
                tri_ground(pav, clean(fp.difference(fz.band)), o, h.plot, layout.terrain, fpave.paver_uv(fz), fz.material)
                tri_ground(pav, clean(fp.intersection(fz.band)), o, h.plot, layout.terrain, fpave.band_uv(fz), M.SEAFRONT_PAVER)
            sea_z, plaza_z = zones
            tri_ground(pav, clean(pv.difference(sea_z.union(plaza_z))), o, h.plot, layout.terrain, planar(MAT_PAVEMENT), MAT_PAVEMENT)
            tri_ground(pav, clean(pv.intersection(sea_z).difference(plaza_z)), o, h.plot, layout.terrain,
                       planar(M.SEAFRONT_PAVER), M.SEAFRONT_PAVER)
            tri_ground(pav, clean(pv.intersection(plaza_z)), o, h.plot, layout.terrain, planar(M.PLAZA_PAVER), M.PLAZA_PAVER)
            promenade_surface(M.SEAFRONT_PAVER)
        else:
            tri_ground(pav, cut(layout.pavement), o, h.plot, layout.terrain, planar(MAT_PAVEMENT), MAT_PAVEMENT)
            promenade_surface(MAT_PROMENADE)
        wall_quads(pav, layout.walls, cell, o,
                   lambda w: (M.ROAD_EDGE_TRIM if hasattr(w, "side") else MAT_TRIM) if w.kind == "kerb" else MAT_PLASTER if w.kind == "terrace" else MAT_SEAWALL,
                   foot_alpha=(lambda w: wall_foot if w.kind in ("retaining", "terrace") else None) if strength > 0 else None)
        # retaining walls and banks: rubble stone; terrace steps (citylib/terrain.py): white render

        ground = MeshData()
        # SLICE4d: the hotel's kept sea lawn (private grounds) gets its own deeper tint; the Green keeps MAT_GRASS
        tri_ground(ground, clean(cut(layout.green).difference(layout.private)), o, h.plot, layout.terrain, planar(MAT_GRASS), MAT_GRASS)
        tri_ground(ground, clean(cut(layout.green).intersection(layout.private)), o, h.plot, layout.terrain,
                   planar(M.LAWN_HOTEL), M.LAWN_HOTEL)
        tri_ground(ground, cut(layout.lawn_stripe), o, h.plot, layout.terrain, planar(MAT_STRIPE), MAT_STRIPE)
        tri_ground(ground, cut(layout.worn), o, h.plot, layout.terrain, planar(MAT_WORN), MAT_WORN)
        tri_ground(ground, cut(layout.earth), o, h.plot, layout.terrain, planar(MAT_EARTH), MAT_EARTH)
        tri_ground(ground, cut(layout.plots), o, h.plot, layout.terrain, planar(MAT_CONCRETE), MAT_CONCRETE)
        tri_ground(ground, cut(layout.bare), o, h.plot, layout.terrain, planar(MAT_RECLAIMED), MAT_RECLAIMED)
        tri_ground(ground, cut(layout.parking), o, h.plot, layout.terrain, planar(MAT_ROAD), MAT_ROAD)
        if not layout.rail.is_empty:  # railway: granite ballast bed and two rails (1.676 m broad gauge)
            tri_poly(ground, cut(layout.rail), o, flat(h.plot + 0.02), planar(M.ROCK), M.ROCK)
            for ln in layout.rail_lines:
                for seg in _lines_of(ln.intersection(cbox)):
                    for off in (-0.84, 0.84):
                        rail = seg.offset_curve(off)
                        for (ax, ay), (bx, by) in zip(rail.coords, list(rail.coords)[1:]):
                            dl = math.hypot(bx - ax, by - ay)
                            if dl < 0.05:
                                continue
                            nx, ny = -(by - ay) / dl * 0.04, (bx - ax) / dl * 0.04
                            prism_xy(ground, [(ax - o[0] - nx, ay - o[1] - ny), (bx - o[0] - nx, by - o[1] - ny),
                                              (bx - o[0] + nx, by - o[1] + ny), (ax - o[0] + nx, ay - o[1] + ny)],
                                     h.plot + 0.02, h.plot + 0.18, M.CONCRETE)
        # P87: contact shade on the sand along the seawall toe (bands cut out of the beach, COLOR_0.A)
        sbands = level_edges.contact_bands(edge_sea, bands_m_sea, cbox) if edge_sea else []
        sband_u = ops.unary_union([b for b, _r in sbands]) if sbands else EMPTY
        tri_poly(ground, clean(cut(beach_dry).difference(sband_u)), o, beach_z, planar(MAT_SAND), MAT_SAND, densify=3.0)
        tri_poly(ground, clean(cut(beach_wet).difference(sband_u)), o, beach_z, planar(MAT_SAND_WET), MAT_SAND_WET, densify=3.0)
        for b, _r in sbands:
            for part, mat in ((beach_dry, MAT_SAND), (beach_wet, MAT_SAND_WET)):
                tri_poly(ground, clean(b.intersection(part)), o, beach_z, planar(mat), mat, densify=1.0,
                         afn=lambda x, y: edge_sea.alpha(x, y, strength))
        # P87: swept step runs (north-end steps): treads and risers from the upper edge down to the level below
        for run in runs:
            if not run.footprint().intersects(cbox):
                continue

            def ground_z(x, y):
                return h.plot + layout.terrain.dz(x, y)

            def add(pts, uvs, alpha, _mat=run.material):
                cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
                if grid.cell_of(cx, cy) == cell:
                    ground.add_face([(x - o[0], y - o[1], z) for x, y, z in pts], uvs, _mat, alpha=alpha)
            level_edges.sweep_steps(run, ground_z, ground_z, add)

        water = MeshData()
        # one sea surface: the depth ramp in UV0 (shallow water and foam live in the texture), metres offshore
        # in UV2; densified near the shore so the ramp follows the coastline closely
        tri_poly(water, cut(layout.sea.difference(layout.shallow)), o, flat(h.sea), seauv, MAT_SEA,
                 densify=16.0, uv2fn=offshore)
        tri_poly(water, cut(layout.shallow), o, flat(h.sea), seauv, MAT_SEA, densify=4.0, uv2fn=offshore)
        tri_poly(water, cut(layout.lake), o, flat(h.lake), planar(MAT_LAKE), MAT_LAKE)

        lake_edge_mesh = lake_edge_mod.build_mesh(edge, layout, cbox, o) if not edge_fp.is_empty else MeshData()
        for name, m in (("Road", road), ("Pavement", pav), ("Ground", ground), ("Water", water), ("LakeEdge", lake_edge_mesh)):
            if not m.is_empty():
                cg.lod0[f"{cid}_{name}"] = m

        # buildings: whole building in the cell that holds its footprint centroid
        mine = [b for b in layout.buildings if grid.cell_of(b.footprint.centroid.x, b.footprint.centroid.y) == cell
                and b.landmark not in replaced]  # hand-modelled heroes replace their placeholder mass (marker below)
        # what the cell already holds (surfaces, dressing) sets how much the styled buildings may use
        other = sum(len(f) - 2 for m in cg.lod0.values() for f in m.faces)
        placed = [(g, i) for g, i in dressing.placements if grid.cell_of(i.x, i.y) == cell] if dressing else []
        if placed and layout.cell_trim:
            # P117 (B4 / RX-0051, citylib/cell_trim.py): dressing over the cell target goes, farthest from the circle
            unstyled = sum(building_tris(building_geom(b, layout, o), tris_table) for b in mine
                           if not rules.DISTRICT_STYLES.get(b.district))
            dress_tris = sum(tris_table.get(i.piece, 100) for _, i in placed)
            target = CELL_LOD0_TARGET - int(layout.cell_trim.get("headroom_tris", 0))
            focus = layout.focus
            dist = (lambda x, y: focus.distance(Point(x, y))) if focus is not None else (lambda x, y: 0.0)
            res = cell_trim.trim(placed, other + unstyled + dress_tris - target,
                                 lambda n: tris_table.get(n, 100), dist, layout.cell_trim)
            placed = res.keep
            if res.dropped:
                cg.trimmed = {"dropped": len(res.dropped), "tris": res.tris_before - res.tris_after}
        other += sum(tris_table.get(i.piece, 100) for g, i in placed)
        geoms, cg.budget_steps = fit_styled_buildings(mine, layout, o, tris_table, other_tris=other)
        cg.buildings.extend(geoms)
        for site in layout.heroes:
            if site.cell == cell:
                props = {"hero": site.name, "hero_yaw_deg": site.yaw_deg, "replaces_osm_ids": list(site.osm_ids),
                         "replaces_fountain": site.fountain}
                cg.heroes.append((site.name, (site.pivot[0] - o[0], site.pivot[1] - o[1], site.pivot[2]),
                                  {k: v for k, v in props.items() if v not in ("", [])}))
        for spec in layout_skybridges(layout):
            res = skybridge_geom(spec, layout, o)
            if res and grid.cell_of(*res[0]) == cell:
                cg.buildings.append(res[1])

        for group, inst in placed:
            cg.groups.setdefault(group, []).append(
                kit.Instance(inst.piece, inst.x - o[0], inst.y - o[1], inst.z, inst.rot, inst.sx, inst.sy, inst.sz))

        seawall_faces = [WallSeg(p0, p1, beach_z(*p0), beach_z(*p1), top, "seawall") for p0, p1, top in layout.seawall]

        # LOD1: one merged mesh, no kerbs, coarse buildings
        lod1 = MeshData()
        tri_poly(lod1, cut(layout.road_area).simplify(0.5), o, flat(h.road), planar(MAT_ROAD), MAT_ROAD)
        tri_ground(lod1, cut(layout.pavement).simplify(0.5), o, h.plot, layout.terrain, planar(MAT_PAVEMENT), MAT_PAVEMENT)
        tri_poly(lod1, cut(layout.promenade).simplify(0.5), o, flat(h.promenade), planar(MAT_PROMENADE), MAT_PROMENADE)
        if not edge_fp.is_empty:   # LOD1 keeps the edge's footprint as flat grass (the swept parts are LOD0 only)
            tri_ground(lod1, edge_fp.simplify(0.5), o, h.plot, layout.terrain, planar(MAT_GRASS), MAT_GRASS)
        wall_quads(lod1, seawall_faces, cell, o, lambda w: MAT_SEAWALL)
        tri_ground(lod1, cut(ops.unary_union([layout.green, layout.lawn_stripe, layout.worn])).simplify(1.5), o, h.plot, layout.terrain, planar(MAT_GRASS), MAT_GRASS, coarse=True)
        tri_ground(lod1, cut(layout.earth).simplify(1.5), o, h.plot, layout.terrain, planar(MAT_EARTH), MAT_EARTH, coarse=True)
        tri_ground(lod1, cut(layout.plots).simplify(1.0), o, h.plot, layout.terrain, planar(MAT_CONCRETE), MAT_CONCRETE)
        tri_ground(lod1, cut(layout.bare).simplify(1.0), o, h.plot, layout.terrain, planar(MAT_RECLAIMED), MAT_RECLAIMED)
        tri_ground(lod1, cut(layout.parking).simplify(1.0), o, h.plot, layout.terrain, planar(MAT_ROAD), MAT_ROAD)
        tri_poly(lod1, cut(layout.beach).simplify(1.0), o, lambda x, y: min(beach_z(x, y), h.beach_top), planar(MAT_SAND), MAT_SAND)
        tri_poly(lod1, cut(layout.sea), o, flat(h.sea), seauv, MAT_SEA, densify=24.0, uv2fn=offshore)
        tri_poly(lod1, cut(layout.lake), o, flat(h.lake), planar(MAT_LAKE), MAT_LAKE)
        for b in mine:
            if b.landmark in replaced:
                continue  # the hero prefab's far mesh is merged into this cell's far proxy in Unity
            fp = clean(b.footprint.simplify(1.0, preserve_topology=True))
            for p in _polys(fp):
                bz = h.road + b.base
                top = bz + rules.wall_height(b.levels)
                if b.landmark.endswith("Hotel"):
                    prism(lod1, p, o, bz, top, MAT_PLASTER, MAT_TERRACOTTA)
                elif "Assembly" in b.landmark:
                    prism(lod1, p, o, bz, top, MAT_SANDSTONE, MAT_SANDSTONE)
                elif b.landmark or b.sacred:
                    prism(lod1, p, o, bz, top, MAT_HERO, MAT_HERO)
                elif b.hero.get("style") == "fin_tower":
                    prism(lod1, p, o, bz, top, MAT_TOWER_GLASS, MAT_CONCRETE, storey_base=bz + rules.GROUND_FLOOR_M)
                else:
                    # far view: towers read as glass storeys, low blocks as cream render
                    if b.levels >= rules.TOWER_MIN_LEVELS:
                        prism(lod1, p, o, bz, top + rules.PARAPET_M, MAT_TOWER_GLASS, MAT_CONCRETE,
                              storey_base=bz + rules.GROUND_FLOOR_M)
                    else:
                        prism(lod1, p, o, bz, top + rules.PARAPET_M, MAT_PLASTER, MAT_CONCRETE,
                              wall_color=paint_variation.building_tint_srgb(building_name(b)))  # LOD0's paint (MAT2)
        cg.lod1 = lod1

        # collision: walkable/drivable surfaces with kerbs and seawalls; building blocks
        colg = MeshData()
        tri_poly(colg, cut(layout.road_area).simplify(0.2), o, flat(h.road), lambda x, y: (0, 0), NO_MAT)
        tri_ground(colg, cut(ops.unary_union([layout.pavement, layout.green, layout.plots, layout.bare, layout.worn, layout.earth, layout.lawn_stripe,
                                         layout.parking, layout.rail])).simplify(0.2), o, h.plot, layout.terrain,
                   lambda x, y: (0, 0), NO_MAT, coarse=True)
        tri_poly(colg, cut(layout.promenade).simplify(0.2), o, flat(h.promenade), lambda x, y: (0, 0), NO_MAT)
        if not edge_fp.is_empty:
            tri_ground(colg, edge_fp.simplify(0.2), o, h.plot, layout.terrain, lambda x, y: (0, 0), NO_MAT)
        tri_poly(colg, cut(layout.beach).simplify(0.5), o, beach_z, lambda x, y: (0, 0), NO_MAT, densify=6.0)
        wall_quads(colg, layout.walls + seawall_faces, cell, o, lambda w: NO_MAT, with_uv=False)
        # safety colliders (no render mesh): a lake bed so nothing falls into a void, the bank walls closed down
        # to it, an invisible 1 m barrier along every lake edge (cars cannot drive into the water; on bridges it is
        # the parapet), and a 0.9 m barrier on the seawall tops except at the beach steps
        tri_poly(colg, cut(layout.lake).simplify(0.2), o, flat(h.lake - LAKE_BED_M), lambda x, y: (0, 0), NO_MAT)
        # the sea bed is one floor under the whole build area (and SEA_BED_REACH_M past the sea), so a seam between
        # surface pieces (beach/lake/promenade slivers dropped by simplify) never opens onto a void
        tri_poly(colg, cut(ops.unary_union([layout.sea.buffer(SEA_BED_REACH_M, join_style=2), layout.area_strip])).simplify(1.0),
                 o, flat(h.sea - SEA_BED_M), lambda x, y: (0, 0), NO_MAT)
        wall_quads(colg, safety_walls, cell, o, lambda w: NO_MAT, with_uv=False)
        colb = MeshData()
        for b in mine:
            for p in _polys(clean(b.footprint.simplify(0.5, preserve_topology=True))):
                bz = h.road + b.base
                prism(colb, p, o, bz, bz + rules.wall_height(b.levels) + rules.PARAPET_M, NO_MAT, NO_MAT)
        # drive circle blocks (drive_loop.dress_blocks): one box per barrier cluster, in the cell of its centre
        for ring, z0, z1 in getattr(layout, "block_colliders", []):
            box_ = Polygon(ring)
            if grid.cell_of(box_.centroid.x, box_.centroid.y) == cell:
                prism(colb, box_, o, z0, z1, NO_MAT, NO_MAT)
        if not colg.is_empty():
            cg.col[f"{cid}_Ground_COL"] = colg
        if not colb.is_empty():
            cg.col[f"{cid}_Buildings_COL"] = colb
        cells.append(cg)
    apply_grade(cells, layout)
    return cells


def apply_grade(cells: list[CellGeom], layout: Layout) -> dict:
    """HEIGHTS 2026-11-24: lift each cell by the terrain's road grades (levels file "grades", terrain.Grade), after
    everything is built, so every surface, kerb, wall, prop and building at a point rises by the same amount and all
    relative heights (kerb 0.15 m, the Green's steps, wall tops) stay as built. Water stays level: a vertex is lifted
    fully from 0.3 m above the lake datum up, not at all at or below it (lake banks keep their foot in the water);
    meshes named *Water* are never touched. Buildings and heroes move rigidly with the grade at their pivot."""
    terr = layout.terrain
    if not getattr(terr, "grades", None):
        return {}
    lake = layout.heights.lake
    moved = {"verts": 0, "instances": 0, "buildings": 0, "max_m": 0.0}

    def lift(z: float, g: float) -> float:
        t = max(0.0, min(1.0, (z - lake) / 0.3))
        return z + g * t

    def mesh(m: MeshData, ox: float, oy: float) -> None:
        out = []
        for x, y, z in m.verts:
            g = terr.grade(x + ox, y + oy)
            if g:
                moved["verts"] += 1
                moved["max_m"] = max(moved["max_m"], abs(g))
                z = lift(z, g)
            out.append((x, y, z))
        m.verts = out

    for cg in cells:
        ox, oy = cg.origin
        for name, m in list(cg.lod0.items()) + list(cg.col.items()) + [("lod1", cg.lod1)]:
            if "Water" not in name:
                mesh(m, ox, oy)
        for b in cg.buildings:
            g = terr.grade(b.pos[0] + ox, b.pos[1] + oy)
            if g:
                b.pos = (b.pos[0], b.pos[1], lift(b.pos[2], g))
                moved["buildings"] += 1
        for insts in cg.groups.values():
            for k, i in enumerate(insts):
                g = terr.grade(i.x + ox, i.y + oy)
                if g:
                    insts[k] = dataclasses.replace(i, z=lift(i.z, g))
                    moved["instances"] += 1
        cg.heroes = [(n, (p[0], p[1], lift(p[2], terr.grade(p[0] + ox, p[1] + oy))), d) for n, p, d in cg.heroes]
    moved["max_m"] = round(moved["max_m"], 2)
    layout.stats["grade"] = moved
    return moved


def _surroundings(layout: Layout, reach_m: float, along_m: float):
    """Land and sea outside the area_strip, in world coordinates: the area_strip's land side (east) and, past
    both area_strip ends, everything inland of the coastline's offset at that end; the rest is sea."""
    (ax, ay), (bx, by) = layout.axis.coords[0], layout.axis.coords[-1]
    ln = math.hypot(bx - ax, by - ay) or 1.0
    ux, uy = (bx - ax) / ln, (by - ay) / ln
    lx, ly = -uy, ux
    west = layout.stats["area_strip"]["west_m"]
    east = layout.stats["area_strip"]["east_m"]

    def P(t, o):
        return ax + ux * t + lx * o, ay + uy * t + ly * o

    def coast_offset(t):
        if layout.coast is None:
            return 0.0
        p = Point(*P(t, 0.0))
        q = layout.coast.interpolate(layout.coast.project(p))
        return (q.x - ax) * lx + (q.y - ay) * ly
    c0, c1 = coast_offset(0.0), coast_offset(ln)
    land = orient_ccw(Polygon([P(-along_m, -reach_m), P(ln + along_m, -reach_m), P(ln + along_m, c1), P(ln, c1),
                               P(ln, -east), P(0.0, -east), P(0.0, c0), P(-along_m, c0)]))
    big = orient_ccw(Polygon([P(-along_m, -reach_m), P(ln + along_m, -reach_m), P(ln + along_m, west + reach_m),
                              P(-along_m, west + reach_m)]))
    land = clean(land.difference(layout.area_strip))
    sea = clean(big.difference(layout.area_strip).difference(land))
    return land, sea


def sea_horizon(layout: Layout, out_m: float = 6000.0, along_m: float = 4000.0) -> MeshData:
    """Open sea beyond the area_strip, out to the horizon (world coordinates, origin = world origin), with the
    same depth-ramp UVs as the cells' sea so they meet without a seam (deep blue beyond 256 m). UV2 carries
    metres offshore for the V5 sea shader."""
    _, band = _surroundings(layout, out_m, along_m)
    coast = layout.coast
    m = MeshData()

    def offshore(x, y):
        return (round(coast.distance(Point(x, y)), 1) if coast is not None else 0.0, 0.0)
    tri_poly(m, band, (0.0, 0.0), flat(layout.heights.sea), sea_uv(coast, layout.axis), MAT_SEA, densify=150.0,
             uv2fn=offshore)
    return m


def city_backdrop(layout: Layout, reach_m: float = 5000.0, along_m: float = 4000.0, seed: int = 7) -> MeshData:
    """Generic distant city outside the area_strip (no real buildings, no OSM): a ground plane just below
    street level and a scatter of plain block masses from 120 m beyond the area_strip, in a haze-tinted
    backdrop material. About 320 boxes (~3.5k triangles, two draws), so no void shows from any view.
    A placeholder until HLOD districts replace it."""
    import random
    land, _ = _surroundings(layout, reach_m, along_m)
    m = MeshData()
    z0 = layout.heights.road - 0.25
    tri_poly(m, land, (0.0, 0.0), flat(z0), planar(64.0), M.BACKDROP_GROUND)
    rng = random.Random(seed)
    keep_out = layout.area_strip.buffer(120.0)
    x0, y0, x1, y1 = land.bounds
    placed = tries = 0
    while placed < 320 and tries < 20000:
        tries += 1
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
        p = Point(cx, cy)
        if not land.contains(p) or keep_out.contains(p) or layout.area_strip.distance(p) > 2200.0:
            continue
        w, dd = rng.uniform(18, 45), rng.uniform(18, 45)
        hgt = rng.choice((12, 15, 18, 24, 30, 40, 55, 70, 90)) * (0.7 + 0.6 * rng.random())
        rot = rng.uniform(0, math.pi)
        c, sn = math.cos(rot), math.sin(rot)
        ring = [(cx + c * px - sn * py, cy + sn * px + c * py) for px, py in
                ((-w / 2, -dd / 2), (w / 2, -dd / 2), (w / 2, dd / 2), (-w / 2, dd / 2))]
        prism_xy(m, ring, z0, z0 + hgt, M.BACKDROP_CITY)
        placed += 1
    return m
