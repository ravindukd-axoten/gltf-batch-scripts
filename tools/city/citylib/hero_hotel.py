"""HERO_SeafaceHotel: the white colonial seafront hotel at the south end of the Green (V2 hero landmark).

Massing from the three OpenStreetMap footprints (ways 341982691, 341982692, 341982694) in a frame turned 17
degrees from east (the building's own grid; footprints are rectilinear in it to about 0.3 m), snapped to
clean numbers. Elevations from the reference photos (gf_05 aerial, gf_06 night, gf_07 from the pier, gf_09
from the Green), stylised:

- north wing facing the Green: a three-storey body with a ground-floor arcade, and three taller pavilions
  (west end, centre, east arm) under hipped tile roofs with Dutch gablets;
- the long seafront wing facing west over the lawn, with two tiers of arched verandas (the upper one with
  balustrades), closing a courtyard open to the sea with the south wing;
- the south wing with end pavilions, and an east block towards Delta Road with an arched porte-cochere;
- cream lime-wash walls (FacadeTrim_A block 0), clay-tile roofs, window surrounds, string courses, a dentil
  eave cornice, quoins on the pavilions.

Storeys: OSM says 4 levels for every part. The photos show the north wing lower than the rest (gf_09: an
arcaded ground floor and one upper floor, pavilions one storey more) and the seafront and south wings at
three storeys with four-storey pavilions (gf_06, gf_07). Floor lines: plinth 0.75 m, 5.6, 9.6, 13.6 (the
pipeline's wall height for 4 levels) and 17.6 m.
"""
from __future__ import annotations

import math

from . import hero_bays as HB
from . import hero_geom as G
from . import materials as _M
from . import wear_decals as WD
from .hero_blocks import Block, BlockBuilding, FacadeStyle

YAW_DEG = 17.0
# SLICE5 Delta Road gate (gf_22, agent 2026-11-17: a secondary gate into the service court): a narrow drive runs
# straight west between the street block (south, extended to the drive) and the gate lodge (north) to a covered
# drive-through under the two-storey block St_Drive; lawn north of the drive, no open plaza.
DRIVE_V = (-52.0, -41.0)      # St_Drive's span along the street; St_South's north face is the drive's south side
DRIVE_FACE_U = 30.9           # the drive-through's arcade face
DRIVE_LANE = (-49.8, -44.2)   # the cobbled lane (one car and a bit), the clear opening between the gate piers
LEVELS = [0.75, 5.6, 9.6, 13.6, 17.6]

# local frame: u along the north wing (17 deg north of east), v across it (north-west-ish = towards the Green)
BLOCKS = [
    # north wing (faces the Green)
    Block("NW_Pavilion", -44.8, -30.0, 36.0, 61.0, 3, pitch=30, gablet=0.6, tag="pavilion"),
    Block("N_Body_W", -30.0, -6.0, 36.0, 49.8, 2, roof_ext=(4.0, 4.0, 0.0, 0.0)),
    Block("N_Pavilion_C", -6.0, 8.9, 36.0, 56.2, 3, pitch=30, gablet=0.6, tag="pavilion"),
    Block("N_Body_E", 8.9, 33.0, 36.0, 48.9, 2, roof_ext=(4.0, 4.0, 0.0, 0.0)),
    Block("NE_Pavilion", 33.0, 46.2, 36.0, 59.1, 3, pitch=30, gablet=0.6, tag="pavilion"),
    Block("E_Block", 33.0, 48.2, 15.0, 36.0, 3),
    # seafront wing (faces west over the lawn)
    Block("W_Wing", -9.4, 10.4, -46.0, 36.0, 3, pitch=25, roof_ext=(0.0, 0.0, 0.0, 6.0)),
    Block("W_Wing_E", 10.4, 15.1, -6.9, 36.0, 3, pitch=25),
    # south wing
    Block("SW_Pavilion", -42.2, -27.2, -69.4, -45.3, 4, pitch=30, gablet=0.6, tag="pavilion"),
    Block("S_Body", -27.2, -9.4, -65.6, -48.9, 3, roof_ext=(4.0, 3.0, 0.0, 0.0)),
    Block("SE_Pavilion", -9.4, 10.3, -71.2, -46.0, 4, pitch=30, gablet=0.6, tag="pavilion"),
    # two-storey Delta Road block round the service courtyard (OSM way 341982695; gf_22, gf_23, gf_24)
    Block("St_West", 15.1, 24.9, -73.9, 5.8, 2, pitch=27, roof_ext=(0.0, 0.0, 0.0, 0.0)),
    Block("St_North", 24.9, 47.9, -28.7, 5.8, 2, pitch=27),
    Block("St_South", 24.9, 46.8, -73.9, DRIVE_V[0], 2, pitch=27),
    # SLICE5 (gf_22): the two-storey block at the end of the gate drive, its ground floor a covered drive-through
    Block("St_Drive", 24.9, 30.9, DRIVE_V[0], DRIVE_V[1], 2, pitch=27),
]

SEA_FACE_U = -9.4      # the seafront wing's west wall
COURT_V = (-46.0, 36.0)
STREET_U = 48.2        # Delta Road frontage: SLICE2 moved it 5 m back from the kerb (u 53.2) for the wide brick
                       # pavement of gf_21, gf_24 and agent h08/h16 (config "pavement_widening" lays the paving)
WALL_U = 46.0          # boundary wall across the service courtyard's street side (gf_22, gf_23)
COURT_GATE = (DRIVE_V[0], -28.7)  # the courtyard's street opening
GATE_V = DRIVE_LANE   # gate between lantern pillars (clear opening)
PORCH = (15.5, 26.5, 51.9, 58.4)  # porte-cochere on the north forecourt, in front of the north wing's loggia (gf_19)
CORNER_WALL_U = 47.7   # SLICE2: Delta Road wall in front of the north-east pavilion, hedges spilling over (gf_25, agent h09)
CORNER_WALL_V = (36.6, 62.0)


M_LAWN = _M.LAWN


def _forecourt(mid, n) -> bool:
    """Faces round the north forecourt between the centre and north-east pavilions (gf_19): arcaded loggias
    with balustraded terraces in front of the walls."""
    return 8.0 < mid[0] < 34.0 and 48.0 < mid[1] < 60.0 and (n[1] > 0.7 or abs(n[0]) > 0.7)


def _service_court(mid) -> bool:
    return 24.0 < mid[0] < STREET_U - 0.7 and DRIVE_V[1] - 0.5 < mid[1] < -28.0


def _drive_side(mid) -> bool:
    """St_South's north face and St_Drive's faces along the gate drive (gf_22: arched French doors and shutters)."""
    return 24.0 < mid[0] < STREET_U - 0.7 and DRIVE_V[0] - 0.5 < mid[1] < DRIVE_V[1] + 0.5


def style(e: G.Edge, storey: int, blk, ctx) -> FacadeStyle:
    n = e.n
    mid = e.p(e.length / 2, 0, 0)
    north, south, west, east = n[1] > 0.7, n[1] < -0.7, n[0] < -0.7, n[0] > 0.7
    in_court = mid[0] < SEA_FACE_U + 0.5 and COURT_V[0] - 0.5 <= mid[1] <= COURT_V[1] + 0.5
    sea_face = west and abs(mid[0] - SEA_FACE_U) < 0.3
    street = east and mid[0] > STREET_U - 8.0
    court = _forecourt(mid, n)
    pav = blk is not None and blk.tag == "pavilion"
    drive = _drive_side(mid)
    if storey == 0 and east and abs(mid[0] - DRIVE_FACE_U) < 0.3 and drive:
        return FacadeStyle("skip")   # drive_through() builds the open arches and the dark void
    if storey == 0:
        # SLICE6 (h05, h07): the Green front's arcade runs nearly wall to wall, arches 2.7 m on 0.9 m piers
        if court:
            return FacadeStyle("arcade", spacing=3.6, margin=1.0, arch_w=2.7, crown_gap=0.5, veranda=3.0, loggia=True)
        if not drive and (north or west or (in_court and (south or north)) or _service_court(mid)):
            if north:
                return FacadeStyle("arcade", spacing=3.6, margin=1.0, arch_w=2.7, crown_gap=0.5, veranda=3.0)
            return FacadeStyle("arcade", spacing=3.7, margin=1.7, arch_w=2.5, crown_gap=0.55, veranda=3.0)
        if street:
            # SLICE6 (gf_21, gf_24, h16): tall arched French doors close together (openings ~65% of the wall, bay
            # 2.7 m), a mix of open glazed doors, closed louvred shutters (S), dark open doorways (D) and wide
            # awninged shop windows (A), patterns from the south end of each wall
            return FacadeStyle("windows", spacing=2.7, margin=1.0, win_w=1.8, win_h=3.1, sill=0.12, french=True,
                               shutters=False, surround=True, pattern=_street_pattern(mid))
        # drive and service sides: tall round-arched French doors with fanlights and shutters (gf_22)
        return FacadeStyle("windows", spacing=3.6, margin=1.4, win_w=1.6, win_h=3.1, sill=0.12, french=True,
                           shutters=drive, surround=True)
    if storey == 1 and sea_face:
        return FacadeStyle("arcade", spacing=3.7, margin=1.7, arch_w=2.5, crown_gap=0.5, veranda=2.6, balustrade=True)
    top = blk is not None and storey == blk.storeys - 1
    if street and blk is not None and blk.name == "St_South":
        return FacadeStyle("plain")   # gf_21, h16: the south street block's upper wall is unbroken plaster
    if street or drive:
        # Delta Road elevation: arched windows with small fanlights and paired louvred shutters nearly touching
        # (gf_24: openings ~1.1 m on a 2.7 m bay)
        return FacadeStyle("windows", spacing=2.7 if street else 3.0, margin=0.9 if street else 1.2, win_w=1.1, win_h=2.2,
                           sill=0.9, arched_windows=True, shutters=True)
    if top and pav:
        return FacadeStyle("windows", spacing=3.0, margin=1.2, win_w=1.15, win_h=2.0, sill=0.9, arched_windows=True, awnings=False)
    return FacadeStyle("windows", spacing=3.0, margin=1.0 if north else 1.2, win_w=1.25, win_h=2.2, sill=0.85, awnings=True,
                       shutters=court)


STREET_PATTERNS = (   # (v range of the wall's middle, bay codes from its south end; hero_bays.BAY_CODES)
    ((-74.0, -52.0), "AAFFFFF"),          # St_South: the maroon-awning shop at the south end, then French doors (h16)
    ((-29.0, 6.0), "FSSDFFSDFFAA"),       # St_North: shutters, timber doors, the green-awning shop at the north end (gf_24)
    ((15.0, 36.0), "FFDFFSF"),            # E_Block
)
AWNING_RGB = {"St_South": (0.55, 0.20, 0.23), "St_North": (0.22, 0.44, 0.32)}   # h16 maroon, gf_24 green canvas


def _street_pattern(mid) -> str:
    for (v0, v1), pat in STREET_PATTERNS:
        if v0 < mid[1] < v1:
            return pat
    return ""


def building() -> BlockBuilding:
    # eave brackets only on the Delta Road wings (gf_25); the seafront and Green eaves are plain cornices (gf_19)
    return BlockBuilding(BLOCKS, LEVELS, style, yaw_deg=YAW_DEG, block_id=0, wall_mat=G.PLASTER_SMOOTH,
                         bracket_blocks=("St_West", "St_North", "St_South", "E_Block"),
                         cornice=[(0.0, -0.6), (0.14, -0.6), (0.14, -0.46), (0.24, -0.46), (0.24, -0.28), (0.5, -0.1), (0.5, 0.0), (0.0, 0.0)],
                         string=[(0.0, -0.42), (0.14, -0.42), (0.14, -0.3), (0.26, -0.16), (0.26, 0.0), (0.0, 0.0)])


def _arch_edge(hm: G.HeroMesh, e: G.Edge, n_arches: int, z_top: float, lod: int, pier: float = 1.0) -> None:
    """Through-arches along one open side of the porch: PI_GN_ArcadeBay bays (no veranda, both faces) between
    end piers `pier` wide, the walls `pier` thick."""
    L = e.length
    W = (L - pier) / n_arches
    H = z_top - 0.8
    params = {"Bay Width": round(W, 4), "Storey Height": H, "Arch Width": round(W - pier, 4), "Crown Gap": 0.45,
              "Pier Depth": pier, "Segments": 8 if lod == 0 else 5, "Detail": lod}
    if lod == 0:
        params["Veranda Depth"] = 0.0
    centres = [pier / 2 + W * (k + 0.5) for k in range(n_arches)]
    for p in HB.edge_bay_points(e.a, e.b, centres, 0.0):
        hm.layout.add_bay("PI_GN_ArcadeBay", params, p)
    for s0, s1 in ((0.0, pier / 2), (L - pier / 2, L)):
        G.edge_box(hm.plain, e, s0, s1, -pier, 0.0, 0.0, H, G.PLASTER_SMOOTH, 0, G.BODY, top=False, tile=(4.0, 4.0))
    if lod == 0:  # dark painted base round the pier feet (gf_19)
        for s0, s1 in [(-0.02, pier / 2 + 0.02)] + [(c + (W - pier) / 2 - 0.02, c + W / 2 + pier / 2 + 0.02) for c in centres]:
            s1 = min(s1, L + 0.02)
            G.edge_box(hm.plain, e, s0, s1, -pier - 0.02, 0.02, 0.0, 0.6, G.TRIM, 2, G.REVEAL, top=False)


def porte_cochere(hm: G.HeroMesh, lod: int) -> None:
    """Arched carriage porch projecting north into the forecourt (gf_19): three arches across the front, one on
    each side, a cornice and a flat roof with a balustrade. Attached to the north wing's loggia at v0."""
    u0, u1, v0, v1 = PORCH
    z1 = 6.6
    m, mb = hm.plain, hm.bevel
    front = G.Edge((u1, v1), (u0, v1))   # faces north (+v)
    west = G.Edge((u0, v1), (u0, v0))    # faces -u
    east = G.Edge((u1, v0), (u1, v1))    # faces +u
    _arch_edge(hm, front, 3, z1, lod)
    for e in (west, east):
        _arch_edge(hm, e, 1, z1, lod)
    G.box(m, u0 - 0.3, u1 + 0.3, v0, v1 + 0.3, z1 - 0.8, z1, G.TRIM, 0, G.CORNICE, bottom=True)
    if lod == 0:
        ring = [(u0 - 0.3, v0), (u1 + 0.3, v0), (u1 + 0.3, v1 + 0.3), (u0 - 0.3, v1 + 0.3)]
        hm.layout.mouldings.append(HB.Moulding(tuple(HB.open_ring(ring)), z1, "string", 0, HB.CORNICE))
        a, b, c, d = (u0 - 0.05, v0 + 0.2, z1), (u0 - 0.05, v1 + 0.05, z1), (u1 + 0.05, v1 + 0.05, z1), (u1 + 0.05, v0 + 0.2, z1)
        hm.layout.runs += [HB.Run(a, b)] + HB.split_run(b, c, 4.0) + [HB.Run(c, d)]
    else:
        G.edge_box(m, front, -0.2, front.length + 0.2, -0.25, 0.0, z1, z1 + 1.0, G.TRIM, 0, G.CORNICE)


LODGE = (WALL_U - 4.0, WALL_U + 0.12, GATE_V[1] + 0.95, GATE_V[1] + 4.95)   # gate lodge against the right pier, its
# street face just proud of the wall line so the hipped roof overhangs the pavement (gf_22, gf_23)
LODGE_H = 3.1


def street_obstacles() -> tuple[list, list]:
    """(solid, gate) rectangles (u0, u1, v0, v1) in the hotel frame for street dressing (citylib/pavement_edge.py):
    the blocks and the boundary-wall runs stop the pavement there (planting goes at their foot); the gate
    opening takes no planting or cabinets."""
    solid = [(b.u0, b.u1, b.v0, b.v1) for b in BLOCKS]
    solid += [(WALL_U - 0.3, WALL_U + 0.3, COURT_GATE[0], GATE_V[0]), (WALL_U - 0.3, WALL_U + 0.3, GATE_V[1], COURT_GATE[1]),
              (WALL_U - 0.3, WALL_U + 0.3, 5.8, 15.0),
              (CORNER_WALL_U - 0.3, CORNER_WALL_U + 0.3, CORNER_WALL_V[0], CORNER_WALL_V[1])]
    return solid, [(WALL_U - 4.0, WALL_U + 2.5, GATE_V[0] - 1.0, GATE_V[1] + 1.0)]


def boundary_wall(hm: G.HeroMesh, lod: int) -> None:
    """Low cream street wall with piers, a moulded coping and a dark base across the service courtyard's Delta
    Road side, square lantern pillars at its gate (PI_GN_BoundaryWall), and a short wall closing the gap between
    the street block and the east block (gf_22, gf_23). The street is on the right of each run (+u). No railings:
    the photos show a solid wall."""
    runs = [HB.Run((WALL_U, COURT_GATE[0], 0.0), (WALL_U, GATE_V[0] - 0.45, 0.0), False, True),
            HB.Run((WALL_U, GATE_V[1] + 0.45, 0.0), (WALL_U, COURT_GATE[1], 0.0), True, False),
            HB.Run((WALL_U, 5.8, 0.0), (WALL_U, 15.0, 0.0), False, False)]
    hm.layout.walls += runs   # the Delta Road corner wall is corner_wall() (taller, rounded coping, gf_25)


def gate_lodge(hm: G.HeroMesh, lod: int) -> None:
    """Small gate lodge with its own hipped tile roof (gf_22, gf_23), composed from the generators: one
    PI_GN_WindowGrid bay per wall (square windows with a surround and sill; a door towards the gate), the dark
    plinth and an eave cornice (PI_GN_CorniceRun) and a PI_GN_HipRoof roof."""
    if lod > 0:
        return
    u0, u1, v0, v1 = LODGE
    ring = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]   # counter-clockwise: the lodge on the left of each wall
    win = {"Storey Height": LODGE_H, "Window Width": 1.0, "Window Height": 1.2, "Sill Height": 1.05, "Arched": False,
           "Segments": 1, "Reveal Depth": 0.2, "Detail": 0, "Surround": True, "Sill": True, "Hood": False,
           "Keystone": False, "Shutters": False, "Awning": False, "Fanlight": False}
    door = dict(win, **{"Window Width": 1.1, "Window Height": 2.2, "Sill Height": 0.0, "Sill": False})
    for i, p in enumerate(HB.ring_bay_points(ring, 0.0)):
        a, b = ring[i], ring[(i + 1) % 4]
        params = dict(door if i == 0 else win, **{"Bay Width": round(math.dist(a, b), 4)})
        hm.layout.add_bay("PI_GN_WindowGrid", params, p)
    hm.layout.mouldings.append(HB.Moulding(tuple(HB.open_ring(ring)), 0.0, "plinth", 2, HB.REVEAL))
    hm.layout.mouldings.append(HB.Moulding(tuple(HB.open_ring(ring)), LODGE_H, "string", 0, HB.CORNICE))
    hm.layout.roofs.append(HB.roof_rect(u0, u1, v0, v1, LODGE_H, 30.0, 0.55, 0.0, fascia=0.18))
    hm.layout.ridges += HB.roof_lines(hm.layout.roofs[-1])


VOID_DEPTH = 9.0                       # the drive-through runs 9 m back under St_Drive into St_West (gf_22: a dark void)
VOID_RGB = (0.42, 0.40, 0.37)          # COLOR_0 on the void's ceiling and walls: shaded plaster, no sun reaches it
KERB_RGB = (0.58, 0.57, 0.54)          # grey granite drive kerbs
CONE_RGB = (0.95, 0.38, 0.10)          # traffic cones at the gate (gf_22)
POT_RGB = (0.55, 0.30, 0.20)           # terracotta planters
LEAF_RGB = (0.24, 0.40, 0.20)


def _face(m, pts, normal, mat, uvs) -> None:
    """Planar polygon facing `normal` (vertex order fixed here, so callers need not think about winding)."""
    a, b, c = pts[0], pts[1], pts[2]
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    if n[0] * normal[0] + n[1] * normal[1] + n[2] * normal[2] < 0:
        pts, uvs = pts[::-1], uvs[::-1]
    m.add_face(pts, uvs, mat)


def _cut_mouldings(lay, profile: str, u0, u1, v0, v1) -> None:
    """Remove the parts of every `profile` moulding inside the rectangle (the plinth across the drive-through)."""
    from shapely.geometry import LineString, box as sbox
    hole = sbox(u0, v0, u1, v1)
    out = []
    for mo in lay.mouldings:
        if mo.profile != profile or not LineString(mo.points).intersects(hole):
            out.append(mo)
            continue
        rest = LineString(mo.points).difference(hole)
        for g in getattr(rest, "geoms", [rest]):
            if g.length > 0.05:
                out.append(HB.Moulding(tuple(g.coords), mo.z, mo.profile, mo.block, mo.row, mo.material))
    lay.mouldings[:] = out


def drive_through(hm: G.HeroMesh, lod: int) -> None:
    """Covered drive-through under St_Drive at the end of the gate drive (gf_22): three open arches on columns
    (PI_GN_ArcadeBay through-arches, as the porte-cochere), the wall up to the first floor line over them, and a
    dark void behind: shaded ceiling and side walls (COLOR_0) and a dark back wall 9 m in."""
    e = G.Edge((DRIVE_FACE_U, DRIVE_V[0]), (DRIVE_FACE_U, DRIVE_V[1]))   # faces +u, the building on its left
    z1 = LEVELS[1]
    _arch_edge(hm, e, 3, z1, lod, pier=0.7)
    G.wall_quad(hm.plain, e, 0.0, e.length, z1 - 0.8, z1, LEVELS[0], z1, 0.0, 0, G.PLASTER_SMOOTH)
    if hm.layout is not None:
        _cut_mouldings(hm.layout, "plinth", DRIVE_FACE_U - 0.2, DRIVE_FACE_U + 0.3, DRIVE_V[0] + 0.3, DRIVE_V[1] - 0.3)
    if lod > 0:
        return
    m = hm.plain
    ua, ub = DRIVE_FACE_U - VOID_DEPTH, DRIVE_FACE_U - 0.7
    va, vb = DRIVE_V[0] + 0.35, DRIVE_V[1] - 0.35
    zc = z1 - 1.15
    zg = ground_z(DRIVE_FACE_U, (va + vb) / 2)
    row = lambda t: G.trim_v(0, G.BODY, t)
    _face(m, [(ua, va, zc), (ub, va, zc), (ub, vb, zc), (ua, vb, zc)], (0, 0, -1), G.TRIM,
          [(ua / 4, row(0.1)), (ub / 4, row(0.1)), (ub / 4, row(0.9)), (ua / 4, row(0.9))])
    for vv, nv in ((va, 1), (vb, -1)):
        _face(m, [(ua, vv, zg), (ub, vv, zg), (ub, vv, zc), (ua, vv, zc)], (0, nv, 0), G.TRIM,
              [(ua / 4, row(0.0)), (ub / 4, row(0.0)), (ub / 4, row(1.0)), (ua / 4, row(1.0))])
    _face(m, [(ua, va, zg), (ua, vb, zg), (ua, vb, zc), (ua, va, zc)], (1, 0, 0), G.TRIM,
          [(va / 4, G.trim_v(2, G.REVEAL, 0.2)), (vb / 4, G.trim_v(2, G.REVEAL, 0.2)),
           (vb / 4, G.trim_v(2, G.REVEAL, 0.8)), (va / 4, G.trim_v(2, G.REVEAL, 0.8))])
    _mark(ua - 0.05, ub + 0.05, va - 0.05, vb + 0.05, zg, zc + 0.05, VOID_RGB)


def gate_grounds(hm: G.HeroMesh, lod: int) -> None:
    """Inside the Delta Road gate (gf_22): the paved drive from the pavement to the drive-through's back wall
    between low granite kerbs, a brick footpath along the street block, and lawn north of the drive (no plaza)."""
    m = hm.plain
    l0, l1 = DRIVE_LANE
    ue = STREET_U
    z = ground_z(38.0, (l0 + l1) / 2) + EPS
    _flat(m, DRIVE_FACE_U - VOID_DEPTH, ue, l0, l1, z, _M.GREY_COBBLE, tile=(2.0, 2.0))   # SLICE6: grey setts (gf_22)
    _flat(m, DRIVE_FACE_U, WALL_U - 0.36, DRIVE_V[0], l0, z, _M.PAVER, tile=(1.8, 1.8))
    zl = z + 0.03
    _flat(m, 24.9, WALL_U - 0.36, DRIVE_V[1], COURT_GATE[1], zl, _M.LAWN_HOTEL, tile=(2.0, 2.0))
    _flat(m, DRIVE_FACE_U, WALL_U - 0.36, l1 + 0.15, DRIVE_V[1], zl, _M.LAWN_HOTEL, tile=(2.0, 2.0))
    if lod > 0:
        return
    for vv in (l0, l1):   # kerbs 0.15 wide, 0.1 high along both lane edges, stopping at the gate
        a0, a1 = (vv - 0.15, vv) if vv == l0 else (vv, vv + 0.15)
        G.box(m, DRIVE_FACE_U + 0.2, WALL_U - 0.5, a0, a1, z - 0.02, z + 0.1, G.TRIM, 0, G.CORNICE, top=True)
        _mark(DRIVE_FACE_U + 0.2, WALL_U - 0.5, a0, a1, z - 0.02, z + 0.1, KERB_RGB)


def gate_props(hm: G.HeroMesh, lod: int) -> None:
    """Things at the gate that give scale (gf_22): traffic cones along the drive and terracotta planters with
    clipped shrubs either side of the drive-through. LOD0 only, trim material painted through COLOR_0."""
    if lod > 0:
        return
    m = hm.plain
    l0, l1 = DRIVE_LANE
    for u, v in ((44.2, l0 + 0.45), (41.4, l0 + 0.45), (38.6, l0 + 0.45), (44.6, l1 - 0.5)):
        z = ground_z(u, v) + EPS
        G.box(m, u - 0.19, u + 0.19, v - 0.19, v + 0.19, z, z + 0.04, G.TRIM, 0, G.CORNICE)
        pts = [(u + 0.13 * math.cos(k * math.pi / 2 + math.pi / 4), v + 0.13 * math.sin(k * math.pi / 2 + math.pi / 4)) for k in range(4)]
        tip = (u, v, z + 0.72)
        for k in range(4):
            a, b = pts[k], pts[(k + 1) % 4]
            m.add_face([(a[0], a[1], z + 0.04), (b[0], b[1], z + 0.04), tip],
                       [(0.0, G.trim_v(0, G.CORNICE, 0.0)), (0.1, G.trim_v(0, G.CORNICE, 0.0)), (0.05, G.trim_v(0, G.CORNICE, 1.0))], G.TRIM)
        _mark(u - 0.2, u + 0.2, v - 0.2, v + 0.2, z, z + 0.75, CONE_RGB)
    for u, v in ((DRIVE_FACE_U + 1.2, DRIVE_V[0] + 1.0), (DRIVE_FACE_U + 1.2, DRIVE_V[1] - 0.9),
                 (WALL_U - 1.4, DRIVE_V[0] + 1.0)):
        z = ground_z(u, v) + EPS
        G.box(m, u - 0.4, u + 0.4, v - 0.4, v + 0.4, z, z + 0.7, G.TRIM, 0, G.CORNICE, top=False)
        _mark(u - 0.4, u + 0.4, v - 0.4, v + 0.4, z, z + 0.7, POT_RGB)
        G.box(m, u - 0.36, u + 0.36, v - 0.36, v + 0.36, z + 0.7, z + 1.5, G.TRIM, 0, G.BODY)
        _mark(u - 0.37, u + 0.37, v - 0.37, v + 0.37, z + 0.71, z + 1.5, LEAF_RGB)


CAR_RGBS = [(0.80, 0.80, 0.78), (0.10, 0.10, 0.11), (0.55, 0.56, 0.58), (0.62, 0.10, 0.08), (0.85, 0.85, 0.83)]
CABIN_RGB = (0.07, 0.08, 0.09)
TYRE_RGB = (0.05, 0.05, 0.05)
# parked cars (hero frame u, v, heading deg from +u): north forecourt between the porch and the pavilions (h05, h17)
# and one under the gate drive-through (gf_22)
CARS = [(10.6, 52.8, 90.0), (13.1, 53.0, 90.0), (28.6, 53.2, 90.0), (31.1, 53.0, 92.0), (21.0, 55.6, 0.0),
        (26.4, -47.0, 180.0)]
FORECOURT = (8.9, 33.0, 48.95, 59.0)    # dark asphalt car park in front of the north arcade (h05, h07, h17)
PORCH_LAMPS = [(14.6, 59.6), (27.4, 59.6)]


def _obox(m, cu, cv, ang, l0, l1, w0, w1, z0, z1, inset=0.0, row=G.CORNICE) -> None:
    """Oriented box (car parts): l along the heading, w across, top face shrunk by `inset` (a cabin). No bottom."""
    c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    P = lambda l, w, z: (cu + l * c - w * s_, cv + l * s_ + w * c, z)
    lo = [P(l0, w0, z0), P(l1, w0, z0), P(l1, w1, z0), P(l0, w1, z0)]
    hi = [P(l0 + inset, w0 + inset * 0.5, z1), P(l1 - inset, w0 + inset * 0.5, z1),
          P(l1 - inset, w1 - inset * 0.5, z1), P(l0 + inset, w1 - inset * 0.5, z1)]
    uv = lambda a, b: [(a, G.trim_v(0, row, 0.0)), (b, G.trim_v(0, row, 0.0)), (b, G.trim_v(0, row, 1.0)), (a, G.trim_v(0, row, 1.0))]
    for k in range(4):
        m.add_face([lo[k], lo[(k + 1) % 4], hi[(k + 1) % 4], hi[k]], uv(0.0, 0.5), G.TRIM)
    m.add_face(hi, [(0.0, G.trim_v(0, G.REVEAL, 0.0)), (0.5, G.trim_v(0, G.REVEAL, 0.0)), (0.5, G.trim_v(0, G.REVEAL, 1.0)),
                    (0.0, G.trim_v(0, G.REVEAL, 1.0))], G.TRIM)


def _car(m, u, v, ang, rgb) -> None:
    """Generic small saloon, 4.3 x 1.75 m, no brand (about 70 tris): body, glasshouse, four tyres, COLOR_0 paint."""
    z = ground_z(u, v) + EPS
    _obox(m, u, v, ang, -2.15, 2.15, -0.87, 0.87, z + 0.3, z + 0.95, 0.12)
    _obox(m, u, v, ang, -1.25, 1.0, -0.8, 0.8, z + 0.95, z + 1.42, 0.38)
    c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    for l, w in ((-1.35, -0.78), (-1.35, 0.78), (1.35, -0.78), (1.35, 0.78)):
        _obox(m, u + l * c - w * s_, v + l * s_ + w * c, ang, -0.31, 0.31, -0.11, 0.11, z, z + 0.62)
    r = 2.3
    _PAINT_SEG.append(((u - c * r, v - s_ * r), (u + c * r, v + s_ * r), 0.95, z + 0.28, z + 0.96, rgb))
    _PAINT_SEG.append(((u - c * r, v - s_ * r), (u + c * r, v + s_ * r), 0.95, z + 0.96, z + 1.45, CABIN_RGB))
    for l, w in ((-1.35, -0.78), (-1.35, 0.78), (1.35, -0.78), (1.35, 0.78)):
        cu, cv = u + l * c - w * s_, v + l * s_ + w * c
        _mark(cu - 0.33, cu + 0.33, cv - 0.33, cv + 0.33, z - 0.01, z + 0.27, TYRE_RGB)


def forecourt(hm: G.HeroMesh, lod: int) -> None:
    """North forecourt, the main entrance facing the Green (agent 2026-11-17; h05, h07, h17): dark asphalt car park
    in front of the arcade and the porte-cochere, white bay lines, parked cars, lanterns on posts at the porch."""
    m = hm.plain
    u0, u1, v0, v1 = FORECOURT
    z = ground_z((u0 + u1) / 2, (v0 + v1) / 2) + EPS
    _flat(m, u0, u1, v0, v1, z, _M.ASPHALT, tile=(6.0, 6.0))
    if lod > 0:
        return
    for k in range(5):   # bay lines either side of the porch (2.5 m bays, 5 m deep)
        for uu in (9.35 + 2.5 * k, 27.1 + 2.5 * k):
            if uu > u1 - 0.3 or (14.9 < uu < 27.0):
                continue
            _flat(m, uu - 0.05, uu + 0.05, 51.9, 56.4, z + 0.006, G.TRIM, 0, G.REVEAL)
            _mark(uu - 0.06, uu + 0.06, 51.8, 56.5, z, z + 0.01, (0.92, 0.92, 0.9))
    for i, (u, v, a) in enumerate(CARS):
        _car(m, u, v, a, CAR_RGBS[i % len(CAR_RGBS)])
    for u, v in PORCH_LAMPS:
        zg = ground_z(u, v) + EPS
        G.box(m, u - 0.18, u + 0.18, v - 0.18, v + 0.18, zg, zg + 0.5, G.TRIM, 2, G.REVEAL)
        G.box(m, u - 0.06, u + 0.06, v - 0.06, v + 0.06, zg + 0.5, zg + 3.3, G.TRIM, 2, G.REVEAL, top=False)
        G.box(m, u - 0.17, u + 0.17, v - 0.17, v + 0.17, zg + 3.3, zg + 3.8, G.GLASS, 0, G.BODY, top=False)
        G.box(m, u - 0.22, u + 0.22, v - 0.22, v + 0.22, zg + 3.8, zg + 3.9, G.TRIM, 2, G.REVEAL)


_LEVELS = None


def levels():
    """The terrain levels (config/delta_face_levels.json via citylib/terrain.py) in this hero's own frame: the same
    heights source the cells use, so the hero's grounds meet the cell ground exactly."""
    global _LEVELS
    if _LEVELS is None:
        from . import terrain
        cfg = {"levels_file": "delta_face_levels.json", "hero_models": {"HERO_SeafaceHotel": {"pivot": [0.0, 0.0], "yaw_deg": 0.0}}}
        _LEVELS = terrain.load(cfg)
    return _LEVELS


def ground_z(u: float, v: float) -> float:
    """Ground height in the hero frame (z 0 = the carriageway datum; the plot datum is a kerb above it)."""
    t = levels()
    return float(t.datum.get("kerb", 0.15)) + t.dz(u, v)


def _flat(m, u0, u1, v0, v1, z, mat=G.TRIM, block=0, row=G.BODY, tile=None) -> None:
    """Top face only (paving inlays lying on the ground or a slab)."""
    pts = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    uv = [(p[0] / tile[0], p[1] / tile[1]) for p in pts] if tile else \
        [(p[0] / 4, G.trim_v(block, row, (p[1] - v0) / max(v1 - v0, 1e-6))) for p in pts]
    m.add_face([(p[0], p[1], z) for p in pts], uv, mat)


def _checker(m, u0, v0, n_u, n_v, sq, z) -> None:
    """Black-and-white checker paving: a light slab with dark squares laid 15 mm above it (agent h18, gf_20). The
    dark squares are the trim's cream painted near-black through COLOR_0 (paint()), so they cost no material."""
    _flat(m, u0, u0 + n_u * sq, v0, v0 + n_v * sq, z, G.TRIM, 0, G.CORNICE)
    for i in range(n_u):
        for j in range(n_v):
            if (i + j) % 2:
                a0, a1, b0, b1 = u0 + i * sq, u0 + (i + 1) * sq, v0 + j * sq, v0 + (j + 1) * sq
                _flat(m, a0, a1, b0, b1, z + 0.015, G.TRIM, 0, G.REVEAL)
                _mark(a0, a1, b0, b1, z + 0.015, z + 0.015, BLACK_RGB)


TERRACE_EDGE_U = -30.0               # balustrade along the sea terrace edge, the lawn a step below (gf_20, agent h18)
TERRACE = (-30.0, -9.6, -48.6, 35.6)  # raised sea terrace (levels 'hotel_sea_terrace'), u0, u1, v0, v1
CHECKER_SQ = 1.2                      # black-and-white marble squares, about two chair widths (agent h18)
CHECKER_APRON = (-15.6, 9.0, 5, 16)   # checker along the seafront veranda: u0, v0, squares u, v (h18)
CHECKER_PATIO = (-28.6, 27.0, 10, 5)  # checker patio in the corner with the north wing (h18: two wings meet behind it)
GREEN_COURTS = [(-28.6, -16.6, -11.0, 27.0), (-28.6, -11.0, -46.0, -15.0)]   # raised green courts (h03 dark strip, gf_20)
CHESS = (-48.0, 8.0, 8, 8, 1.0)       # giant chess board on the lawn (h03, gf_20)
POOL = (-58.5, -50.5, -68.0, -50.0)   # pool south-west of the lawn, by the seawall (h03, gf_20)
POOL_DECK = (-61.5, -46.5, -74.0, -45.0)
PERGOLA = (-60.0, -53.0, -8.0, 0.0)   # sea-edge grill pavilion on the lawn (h03)
DINING = (-63.4, -50.0, -26.0, 6.0)   # red-brick dining terrace round the grill, white umbrellas (gf_20 lower left)
TERRACE_STEPS = (12.0, -30.0)         # v of the two flights from the terrace down to the lawn (gf_20, h18)
STEP_W = 4.0
BRICK_PATHS = [(-34.0, -30.0, -44.0, 35.6),    # walk along the terrace foot (gf_20: red brick between the lawns)
               (-40.0, -34.0, 10.5, 13.5),     # to the chess board
               (-49.0, -39.0, 7.0, 17.0),      # brick surround of the chess board
               (-50.0, -34.0, -31.5, -28.5)]   # to the dining terrace
NORTH_BOUNDARY_V = 64.0              # the hotel's north boundary: the public promenade ends here (agent h03)
EPS = 0.025                          # overlays above the cell ground (mobile depth precision at 150 m)
HEDGE_RGB = (0.30, 0.47, 0.24)       # COLOR_0 tint on the trim's cream body: clipped dark-green hedge (gf_20, gf_25)
BLACK_RGB = (0.16, 0.16, 0.16)       # black marble squares, rattan chairs, pole bands (h18, gf_25)
CABINET_RGB = (0.62, 0.68, 0.64)     # grey-green feeder pillars (gf_25)

_PAINT: list[tuple] = []             # (u0, u1, v0, v1, z0, z1, rgb) boxes in the hero frame, painted by paint()
_PAINT_SEG: list[tuple] = []         # (a, b, half width, z0, z1, rgb): faces within half width of segment a-b (hedges)


def _mark(u0, u1, v0, v1, z0, z1, rgb) -> None:
    _PAINT.append((min(u0, u1) - 0.01, max(u0, u1) + 0.01, min(v0, v1) - 0.01, max(v0, v1) + 0.01, z0 - 0.01, z1 + 0.01, rgb))


PARAPET_H, PARAPET_T, PIER_EVERY = 0.85, 0.22, 5.0


def _parapet(m, mb, line, zfn) -> None:
    """Low white balustraded wall along a polyline (hero frame) at ground z = zfn(u, v): a thin panel carrying the
    trim sheet's painted balusters (block 3, BALUSTRADE row; ~28 tris per 5 m bay instead of ~300 for the
    PI_GN_Balustrade runs, which keep the near facade), square piers every bay and a thick rounded coping."""
    for (au, av), (bu, bv) in zip(line, line[1:]):
        L = math.dist((au, av), (bu, bv))
        if L < 0.1:
            continue
        tu, tv = (bu - au) / L, (bv - av) / L
        nu, nv = -tv, tu
        n = max(1, math.ceil(L / PIER_EVERY))
        h = PARAPET_T / 2
        for k in range(n):
            s0, s1 = L * k / n, L * (k + 1) / n
            pa = (au + tu * s0, av + tv * s0)
            pb = (au + tu * s1, av + tv * s1)
            z = zfn((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
            ring = [(pa[0] - nu * h, pa[1] - nv * h), (pb[0] - nu * h, pb[1] - nv * h),
                    (pb[0] + nu * h, pb[1] + nv * h), (pa[0] + nu * h, pa[1] + nv * h)]
            G._box_from_ring(m, ring, z, z + PARAPET_H - 0.12, G.TRIM, 3, G.BALUSTRADE, False, False)
            c = 0.06
            cring = [(pa[0] - nu * (h + c), pa[1] - nv * (h + c)), (pb[0] - nu * (h + c), pb[1] - nv * (h + c)),
                     (pb[0] + nu * (h + c), pb[1] + nv * (h + c)), (pa[0] + nu * (h + c), pa[1] + nv * (h + c))]
            G._box_from_ring(mb, cring, z + PARAPET_H - 0.12, z + PARAPET_H, G.TRIM, 0, G.CORNICE, True, False)
            q = 0.2
            G.box(mb, pa[0] - q, pa[0] + q, pa[1] - q, pa[1] + q, z, z + PARAPET_H + 0.12, G.TRIM, 0, G.BODY)
        G.box(mb, bu - 0.2, bu + 0.2, bv - 0.2, bv + 0.2, zfn(bu, bv), zfn(bu, bv) + PARAPET_H + 0.12, G.TRIM, 0, G.BODY)


BALUSTER_SPACING = 0.55   # SLICE6 0.50 -> 0.55 (pays for the street bays); wider than the 0.36 default: the veranda balustrades read the same at game distance and
                          # the saved ~2.5k tris pay for the SLICE3/4b sea side and corner under the 60k hero cap
OCTAGON = (39.5, 25.3, 4.6, 15.2, 18.2, 3.4)   # NE pavilion (agent h03, h05): centre u, v, radius, drum foot, eaves, rise


def octagon_roof(hm: G.HeroMesh, lod: int) -> None:
    """The octagonal pavilion roof on the Delta Road range's north-east block (agent h03 top-down, h05 aerial): a
    cream drum standing out of the E_Block hip, a cornice band and an eight-sided tiled spire roof. ~56 tris."""
    cu, cv, r, z0, z1, rise = OCTAGON
    m = hm.plain
    n = 8
    ring = [(cu + r * math.cos(2 * math.pi * (k + 0.5) / n), cv + r * math.sin(2 * math.pi * (k + 0.5) / n)) for k in range(n)]
    G.prism_ring(m, ring, z0, z1, G.PLASTER_SMOOTH, 0, G.BODY, top=False, tile=(G_TILE, G_TILE))
    ov = r + 0.7
    eave = [(cu + ov * math.cos(2 * math.pi * (k + 0.5) / n), cv + ov * math.sin(2 * math.pi * (k + 0.5) / n)) for k in range(n)]
    G.prism_ring(m, eave, z1 - 0.25, z1, G.TRIM, 0, G.CORNICE, top=False)
    apex = (cu, cv, z1 + rise)
    slope = math.hypot(ov, rise)
    side = 2 * ov * math.sin(math.pi / n)
    for k in range(n):
        a, b = eave[k], eave[(k + 1) % n]
        G.tri(m, (*a, z1), (*b, z1), apex, [(0.0, 0.0), (side / 2.0, 0.0), (side / 4.0, slope / 2.0)], G.ROOF)


G_TILE = 3.0


def _hedge(m, a, b, z, w=0.8, h=0.9, lumpy=0.0) -> None:
    """Clipped hedge along a -> b (hero frame) on ground z: vertical sides, chamfered shoulders and a flat top
    (gf_20, gf_25), cream trim painted dark green through COLOR_0. `lumpy` lifts the top unevenly (overgrown)."""
    L = math.dist(a, b)
    if L < 0.2:
        return
    tu, tv = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nu, nv = -tv, tu
    hw, sh = w / 2, 0.8 * h
    top = h + lumpy * (_hash(a[0], a[1]) - 0.3)
    prof = [(-hw, 0.0), (hw, 0.0), (hw, sh), (hw * 0.62, top), (-hw * 0.62, top), (-hw, sh)]   # across, up

    def P(p, k):
        return (p[0] + nu * k[0], p[1] + nv * k[0], z + k[1])
    for i in range(1, len(prof)):
        k0, k1 = prof[i], prof[(i + 1) % len(prof)]
        if k0[1] == 0.0 and k1[1] == 0.0:
            continue
        G.quad(m, P(a, k0), P(a, k1), P(b, k1), P(b, k0),
               [(0.0, G.trim_v(0, G.BODY, 0.1)), (0.0, G.trim_v(0, G.BODY, 0.6)), (L / 4, G.trim_v(0, G.BODY, 0.6)),
                (L / 4, G.trim_v(0, G.BODY, 0.1))], G.TRIM)
    for end, sgn in ((a, -1), (b, 1)):
        ring = [P(end, k) for k in (prof if sgn > 0 else prof[::-1])]
        m.add_face(ring, [(k[0] / 4, G.trim_v(0, G.BODY, 0.5)) for k in prof], G.TRIM)
    _PAINT_SEG.append((a, b, hw * 0.95, z - 0.01, z + top + 0.3, HEDGE_RGB))


def _hash(x: float, y: float) -> float:
    return (math.sin(x * 12.9898 + y * 78.233) * 43758.5453) % 1.0


def _offset_line(line, d):
    """Polyline offset by d to the left of its direction (mitre joints)."""
    out = []
    for i, p in enumerate(line):
        ns = []
        for a, b in ((line[i - 1], p) if i > 0 else (p, line[1]), (p, line[i + 1]) if i + 1 < len(line) else (line[i - 1], p)):
            L = math.dist(a, b) or 1.0
            ns.append((-(b[1] - a[1]) / L, (b[0] - a[0]) / L))
        nu, nv = ns[0][0] + ns[1][0], ns[0][1] + ns[1][1]
        k = math.hypot(nu, nv) or 1.0
        nu, nv = nu / k, nv / k
        cosh = max(0.5, nu * ns[0][0] + nv * ns[0][1])
        out.append((p[0] + nu * d / cosh, p[1] + nv * d / cosh))
    return out


def _resample(line, step):
    pts = [line[0]]
    for a, b in zip(line, line[1:]):
        L = math.dist(a, b)
        n = max(1, round(L / step))
        pts += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]
    return pts


def rock_armour(m, line, lod: int) -> None:
    """Dark rubble revetment at the foot of the hotel's sea wall (agent h04, h06: black boulders under the white
    balustrade, surf on them): two jittered rows of MAT_RockArmour seaward of the wall face, from about 1.2 m under the
    lawn edge down below the waterline (sea level is 3.8 m under the hero datum)."""
    pts = _resample(line, 4.0 if lod == 0 else 8.0)
    rows = [(1.6, -1.5, 0.0), (4.2, -3.1, 0.45), (7.0, -4.4, 0.2)]   # offset seaward (m), z, jitter
    grid = []
    for d, z, j in rows:
        off = _offset_line(pts, -d)   # the sea is to the right of the line's direction (north -> south, west side)
        grid.append([(q[0] + j * (_hash(q[0], q[1]) - 0.5), q[1], z + j * 1.2 * (_hash(q[1], q[0]) - 0.5)) for q in off])
    for r in range(len(rows) - 1):
        for i in range(len(pts) - 1):
            a, b, c, d = grid[r][i], grid[r][i + 1], grid[r + 1][i + 1], grid[r + 1][i]
            uv = [(p[0] / 1.8, p[1] / 1.8) for p in (a, b, c, d)]
            m.add_face([a, d, c, b], [uv[0], uv[3], uv[2], uv[1]], _M.ROCK)


def _steps(m, mb, u_edge, v_mid, z_lo, z_hi, w=STEP_W, n=4, tread=0.4) -> None:
    """A flight of n risers from the lawn up to the terrace edge at u_edge (going -u), with low cheek walls."""
    H = z_hi - z_lo
    v0, v1 = v_mid - w / 2, v_mid + w / 2
    for k in range(1, n):
        G.box(m, u_edge - tread * (n - k), u_edge, v0, v1, z_lo, z_lo + H * k / n, G.TRIM, 0, G.CORNICE)
    for vv in (v0 - 0.3, v1):
        G.box(mb, u_edge - tread * n, u_edge, vv, vv + 0.3, z_lo, z_hi + 0.12, G.TRIM, 0, G.BODY)


def _umbrella(m, u, v, z, r=1.4, h=2.45, table=True) -> None:
    """White market umbrella (hexagonal canopy, both faces), a pole and a small table (gf_20 dining terrace)."""
    ring = [(u + r * math.cos(k * math.pi / 3), v + r * math.sin(k * math.pi / 3)) for k in range(6)]
    apex = (u, v, z + h + 0.35)
    for k in range(6):
        a, b = ring[k], ring[(k + 1) % 6]
        uv = [(0.0, G.trim_v(0, G.CORNICE, 0.2)), (0.4, G.trim_v(0, G.CORNICE, 0.2)), (0.2, G.trim_v(0, G.CORNICE, 0.8))]
        G.tri(m, (*a, z + h), (*b, z + h), apex, uv, G.TRIM)
        G.tri(m, (*b, z + h - 0.02), (*a, z + h - 0.02), (u, v, z + h + 0.2), uv, G.TRIM)
    G.box(m, u - 0.04, u + 0.04, v - 0.04, v + 0.04, z, z + h, G.TRIM, 1, G.REVEAL, top=False)
    if table:
        G.box(m, u - 0.45, u + 0.45, v - 0.45, v + 0.45, z + 0.7, z + 0.76, G.TRIM, 0, G.CORNICE)


def _table_set(m, u, v, z) -> None:
    """Round-ish café table with two dark rattan chairs (agent h18)."""
    G.box(m, u - 0.4, u + 0.4, v - 0.4, v + 0.4, z + 0.68, z + 0.74, G.TRIM, 0, G.CORNICE)
    G.box(m, u - 0.06, u + 0.06, v - 0.06, v + 0.06, z, z + 0.68, G.TRIM, 1, G.REVEAL, top=False)
    for dv in (-0.85, 0.85):
        G.box(m, u - 0.3, u + 0.3, v + dv - 0.3, v + dv + 0.3, z, z + 0.78, G.TRIM, 0, G.REVEAL)   # tub chair
        _mark(u - 0.3, u + 0.3, v + dv - 0.3, v + dv + 0.3, z, z + 0.78, BLACK_RGB)


def _lounger(m, u, v, z) -> None:
    G.box(m, u - 0.35, u + 0.35, v - 0.95, v + 0.95, z, z + 0.32, G.TRIM, 0, G.CORNICE)


def sea_terrace(hm: G.HeroMesh, lod: int) -> None:
    """SLICE4b sea side (agent h03, h04, h06, h18, gf_20). The lawn, the raised terrace and the pool deck are cell
    ground at the terrain levels; the hero lays what makes them read: cream stone paving and two raised green
    courts on the terrace, the checker apron and patio by the veranda, the terrace-edge balustrade with two flights
    of steps, red-brick walks and a dining terrace (white umbrellas) on the lawn, clipped hedges, the chess board, the
    pool with loungers, the grill pergola, the low balustraded sea wall on the seawall top (the levels file's
    'hotel_sea_balustrade' line) over a dark rock-armour revetment, and the north boundary wall to the Green."""
    m, mb = hm.plain, hm.bevel
    t = levels()
    zt = ground_z(-20.0, 0.0)
    zl = ground_z(-45.0, 30.0)
    p0, p1, q0, q1 = POOL
    d0, d1, e0, e1 = POOL_DECK
    zd = ground_z((p0 + p1) / 2, (q0 + q1) / 2)
    line = t.features.get("hotel_sea_balustrade", [])
    tu0, tu1, tv0, tv1 = TERRACE
    lawn_tile = (2.0, 2.0)
    # surfaces both LODs carry (2 tris each): terrace stone, green courts, brick walks, dining terrace, pool water
    _flat(m, tu0, tu1, tv0, tv1, zt + EPS, G.TRIM, 0, G.BODY)
    for a0, a1, b0, b1 in GREEN_COURTS:
        _flat(m, a0, a1, b0, b1, zt + 2 * EPS, _M.LAWN_STRIPE, tile=lawn_tile)
    for a0, a1, b0, b1 in BRICK_PATHS + [DINING]:
        _flat(m, a0, a1, b0, b1, ground_z((a0 + a1) / 2, (b0 + b1) / 2) + EPS, _M.PAVER, tile=(1.8, 1.8))
    _flat(m, p0, p1, q0, q1, zd + 0.02, _M.WATER_LAKE, tile=(4.0, 4.0))
    if line:
        rock_armour(m, line, lod)
    if lod > 0:
        _flat(m, d0, d1, e0, e1, zd + 0.01, G.TRIM, 0, G.CORNICE)
        return
    # checker apron along the veranda and the corner patio (h18), the giant chess board on the lawn (h03, gf_20)
    for cu, cv, nu, nv in (CHECKER_APRON, CHECKER_PATIO):
        _checker(m, cu, cv, nu, nv, CHECKER_SQ, zt + 2 * EPS)
    cu, cv, nu, nv, sq = CHESS
    _checker(m, cu, cv, nu, nv, sq, ground_z(cu + 4.0, cv + 4.0) + 2 * EPS)
    # terrace edge: balustrade with gaps for the two flights of steps down to the lawn walk
    cuts = sorted(TERRACE_STEPS)
    vs = [tv0]
    for c in cuts:
        vs += [c - STEP_W / 2 - 0.3, c + STEP_W / 2 + 0.3]
    vs.append(tv1)
    for a, b in zip(vs[0::2], vs[1::2]):
        _parapet(m, mb, [(TERRACE_EDGE_U + 0.25, a), (TERRACE_EDGE_U + 0.25, b)], lambda u, v: zt)
    for c in cuts:
        _steps(m, mb, TERRACE_EDGE_U, c, zl, zt)
    # café tables on the checker apron (agent h18)
    for k in range(3):
        _table_set(m, -12.6, 12.5 + 5.5 * k, zt + 2 * EPS)
    # pool: pale stone deck, white coping, water, loungers along the inland side
    _flat(m, d0, d1, e0, e1, zd + 0.01, G.TRIM, 0, G.CORNICE)
    for u_0, u_1, v_0, v_1 in ((p0 - 0.4, p1 + 0.4, q0 - 0.4, q0), (p0 - 0.4, p1 + 0.4, q1, q1 + 0.4),
                               (p0 - 0.4, p0, q0, q1), (p1, p1 + 0.4, q0, q1)):
        G.box(m, u_0, u_1, v_0, v_1, zd, zd + 0.08, G.TRIM, 0, G.CORNICE)
    for k in range(4):
        _lounger(m, p1 + 2.0, q0 + 2.0 + 3.4 * k, zd + 0.01)
    # grill pergola: posts and a low hipped tile roof, white umbrellas round it on the brick (gf_20)
    pu0, pu1, pv0, pv1 = PERGOLA
    zg = ground_z((pu0 + pu1) / 2, (pv0 + pv1) / 2)
    for pu in (pu0, (pu0 + pu1) / 2, pu1):
        for pv in (pv0, pv1):
            G.box(mb, pu - 0.18, pu + 0.18, pv - 0.18, pv + 0.18, zg, zg + 2.6, G.TRIM, 0, G.BODY, top=False)
    G.box(m, pu0 - 0.3, pu1 + 0.3, pv0 - 0.3, pv1 + 0.3, zg + 2.6, zg + 2.8, G.TRIM, 0, G.CORNICE, bottom=True)
    hm.layout.roofs.append(HB.roof_rect(pu0, pu1, pv0, pv1, zg + 2.8, 22.0, 0.6, 0.0, fascia=0.15))
    zdn = ground_z(-56.0, -15.0) + EPS
    for uu, vv in ((-61.0, -22.0), (-56.0, -22.5), (-51.6, -20.5), (-61.2, -14.5), (-61.0, 3.0)):
        _umbrella(m, uu, vv, zdn)
    # clipped hedges: inside the sea wall along the north lawn, framing the dining terrace and the pool deck edge
    if line:
        north = [p for p in line if p[1] >= 6.0]
        inner = _offset_line(north + [(north[-1][0], 6.6)], 1.1)
        for a, b in zip(inner, inner[1:]):
            _hedge(m, a, b, ground_z(*a))
    _hedge(m, (-63.0, 6.8), (-50.4, 6.8), zl)
    _hedge(m, (-49.6, -25.5), (-49.6, -12.0), zl)
    _hedge(m, (-46.0, -43.4), (-35.0, -43.4), zl)
    _hedge(m, (-34.6, 24.0), (-34.6, 35.0), zl, w=0.7, h=0.7)
    # low balustraded sea wall on the seawall top, in runs that follow the ground levels
    _parapet(m, mb, line, lambda u, v: ground_z(u + 1.0, v))
    # north boundary wall between the hotel lawn and the Green's promenade (street side north, on the right)
    zn = ground_z(-60.0, NORTH_BOUNDARY_V - 1.0)
    hm.layout.walls.append(HB.Run((-44.8, NORTH_BOUNDARY_V, zn), (line[0][0] if line else -71.0, NORTH_BOUNDARY_V, zn), False, True))


CORNER_WALL_H, CORNER_WALL_T = 2.6, 0.36   # tall white wall at the Delta Road corner (gf_25, agent h09: about 1.5 people)
CORNER_POLE = (52.4, 60.6)                 # black-and-white banded pole at the corner kerb (agent h09, catalogue "Striped poles")
CORNER_CABINETS = [(48.35, 43.2), (48.35, 44.6)]   # grey feeder pillars at the wall foot (gf_25, h09)

# SLICE4c: the bushes over the corner wall are vegetation instances, not hero geometry (agent h09, h10). Hero-frame
# cluster specs (citylib.vegetation.frame_points format, frame filled from config hero_models) that
# vegetation.dress() adds to the config clusters; "supersedes" names a config cluster line this one replaces
# (config cluster 12, SLICE2/4a, until the street session deletes it). VEG_Hedge_Spill_A expects its wall's centre
# line 0.9 m in front (+u, the street) and the coping 1.8 m up, so the 2.6 m corner wall raises it 0.8 m.
VEG_CLUSTERS = [
    {"_doc": "SLICE4c: dense spill hedge billowing over the corner wall coping and hanging down its street face",
     "species": ["VEG_Hedge_Spill_A"], "line": [[CORNER_WALL_U - 0.9, CORNER_WALL_V[0] + 0.9],
                                                [CORNER_WALL_U - 0.9, CORNER_WALL_V[1] - 0.9]],
     "spacing_m": 2.0, "ignore_buildings": True, "z_offset": CORNER_WALL_H - 1.8 + 0.15,
     "supersedes": [[46.95, 37.5], [46.95, 61.0]]},
    {"_doc": "SLICE4c: frangipani (araliya) crowns rising behind it, white flowers over the coping (h09, h10)",
     "species": ["VEG_Shrub_Frangipani_A"], "points": [[CORNER_WALL_U - 2.3, 40.5], [CORNER_WALL_U - 2.1, 49.5],
                                                      [CORNER_WALL_U - 2.4, 58.0]],
     "ignore_buildings": True, "z_offset": 0.15, "gap_m": 2.0},
]


def corner_wall(hm: G.HeroMesh, lod: int) -> None:
    """North-east corner on Delta Road (gf_25, agent h09): a tall white boundary wall with a dark plinth and a
    rounded coping, end piers, a striped pole and two utility cabinets; the bushes over it are VEG_CLUSTERS
    (SLICE4c). Hero frame, street on +u."""
    m, mb = hm.plain, hm.bevel
    cu, (v0, v1) = CORNER_WALL_U, CORNER_WALL_V
    h2 = CORNER_WALL_T / 2
    z0 = ground_z(cu + 0.6, (v0 + v1) / 2)
    zt = z0 + CORNER_WALL_H
    G.box(m, cu - h2, cu + h2, v0, v1, z0, zt, G.PLASTER_SMOOTH, 0, G.BODY, top=False, tile=(G_TILE, G_TILE))
    # rounded coping: a half-round 0.05 m proud of both faces (four facets, smoothed by the bevel pass)
    r = h2 + 0.05
    prof = [(cu + r * math.cos(math.pi * k / 4), zt + 0.62 * r * math.sin(math.pi * k / 4)) for k in range(5)]
    for (ua, za), (ub, zb) in zip(prof, prof[1:]):
        G.quad(mb, (ua, v0, za), (ua, v1, za), (ub, v1, zb), (ub, v0, zb),
               [(v0 / 4, G.trim_v(0, G.CORNICE, 0.0)), (v1 / 4, G.trim_v(0, G.CORNICE, 0.0)),
                (v1 / 4, G.trim_v(0, G.CORNICE, 1.0)), (v0 / 4, G.trim_v(0, G.CORNICE, 1.0))], G.TRIM)
    for vv, rev in ((v0, False), (v1, True)):
        pts = [(u, vv, z) for u, z in prof]
        pts = pts[::-1] if rev else pts
        m.add_face(pts, [(p[0] / 4, G.trim_v(0, G.CORNICE, 0.5)) for p in pts], G.TRIM)
    if lod > 0:
        return        # SLICE4c: the hedges behind and over the wall are VEG_CLUSTERS instances now
    G.box(m, cu + h2 - 0.01, cu + h2 + 0.04, v0, v1, z0, z0 + 0.35, G.TRIM, 1, G.REVEAL)        # dark plinth band
    for vv in (v0, v1):
        G.box(mb, cu - 0.32, cu + 0.32, vv - 0.32, vv + 0.32, z0, zt + 0.25, G.TRIM, 0, G.BODY)  # end piers
    # banded pole: black and white to 2.1 m, galvanised above
    pu, pv = CORNER_POLE
    zp = ground_z(pu, pv)
    for k in range(6):
        G.box(m, pu - 0.06, pu + 0.06, pv - 0.06, pv + 0.06, zp + 0.35 * k, zp + 0.35 * (k + 1), G.TRIM, 0, G.CORNICE, top=False)
        if k % 2 == 0:
            _mark(pu - 0.06, pu + 0.06, pv - 0.06, pv + 0.06, zp + 0.35 * k, zp + 0.35 * (k + 1), BLACK_RGB)
    G.box(m, pu - 0.05, pu + 0.05, pv - 0.05, pv + 0.05, zp + 2.1, zp + 4.2, G.TRIM, 1, G.REVEAL)
    for u, v in CORNER_CABINETS:
        zc = ground_z(u, v)
        G.box(m, u - 0.22, u + 0.22, v - 0.5, v + 0.5, zc, zc + 1.3, G.TRIM, 0, G.BODY)
        _mark(u - 0.22, u + 0.22, v - 0.5, v + 0.5, zc, zc + 1.3, CABINET_RGB)


def _paint_at(u: float, v: float, z: float):
    """COLOR_0 rgb for a face centre (hero frame), or None."""
    for u0, u1, v0, v1, z0, z1, rgb in _PAINT:
        if u0 <= u <= u1 and v0 <= v <= v1 and z0 <= z <= z1:
            return rgb
    for a, b, hw, z0, z1, rgb in _PAINT_SEG:
        if not z0 <= z <= z1:
            continue
        L = math.dist(a, b)
        tu, tv = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        s_, d_ = (u - a[0]) * tu + (v - a[1]) * tv, -(u - a[0]) * tv + (v - a[1]) * tu
        if -0.01 <= s_ <= L + 0.01 and abs(d_) <= hw:
            return rgb
    return None


def paint(ob) -> None:
    """build_heroes hook after decor.paint: COLOR_0 rgb for the faces whose centre lies in a _mark box (hero frame):
    black marble squares, rattan chairs, hedges, the striped pole. Alpha (baked AO) is kept. The trim's paint tint
    multiplies the albedo (SHD_HeroLit), so these cost no material or texture."""
    me = ob.data
    ca = me.color_attributes.get("Col")
    if ca is None:
        return
    a = math.radians(YAW_DEG)
    c, s = math.cos(a), math.sin(a)
    trim = {i for i, mt in enumerate(me.materials) if mt and mt.name == G.TRIM}
    plaster = {i for i, mt in enumerate(me.materials) if mt and mt.name == G.PLASTER_SMOOTH}
    buf = [0.0] * (len(ca.data) * 4)
    ca.data.foreach_get("color_srgb", buf)

    n = nt = 0
    for p in me.polygons:
        if p.material_index in plaster and abs(p.normal.z) < 0.3:
            # SLICE6 per-wall tone (gf_21, gf_24: each wing and wall is a slightly different cream, some warmer,
            # some greyer from weathering): one factor per wall plane, darker or warmer only (the tint is near 1)
            nx, ny = round(p.normal.x, 1), round(p.normal.y, 1)
            dpl = round((p.center.x * p.normal.x + p.center.y * p.normal.y) / 2.0)
            h = math.sin(nx * 12.99 + ny * 78.23 + dpl * 37.72) * 43758.55
            h -= math.floor(h)
            k = 0.89 + 0.11 * h
            warm = 0.985 + 0.03 * ((h * 7.31) % 1.0)
            for li in p.loop_indices:
                r, g, b_ = buf[li * 4:li * 4 + 3]
                buf[li * 4:li * 4 + 3] = (r * k * min(1.0, warm + 0.01), g * k, b_ * k * (2.0 - warm) * 0.985)
            nt += 1
            continue
        if p.material_index not in trim:
            continue
        x, y, z = p.center
        u, v = x * c + y * s, -x * s + y * c
        rgb = _paint_at(u, v, z)
        if rgb is not None:
            for li in p.loop_indices:
                buf[li * 4:li * 4 + 3] = rgb
            n += 1
    ca.data.foreach_set("color_srgb", buf)
    print(f"hero_hotel.paint: {n} faces painted, {nt} wall faces toned")


def _a_runs(hm: G.HeroMesh):
    """Consecutive shop-window (A) bays on the ground storey: (edge, s0, s1, zf0, block name)."""
    out = []
    for a, b, zf0, zf1, st, info in hm.layout.facades:
        if abs(zf0 - LEVELS[0]) > 0.05 or st.kind != "windows":
            continue
        run = []
        for c, code, o in info + [(None, "", None)]:
            if code == "A" and (not run or abs(c - run[-1][0] - st.spacing) < 0.01):
                run.append((c, o))
                continue
            if run:
                e = G.Edge(a, b)
                mid = e.p((run[0][0] + run[-1][0]) / 2, 0, 0)
                name = "St_South" if mid[1] < DRIVE_V[0] else "St_North"
                out.append((e, run[0][0] - st.spacing / 2 + 0.15, run[-1][0] + st.spacing / 2 - 0.15, zf0, name))
            run = [(c, o)] if code == "A" else []
    return out


def shop_awnings(hm: G.HeroMesh, lod: int) -> None:
    """SLICE6 (h16, gf_24): a canvas awning over each run of shop windows, sloping 1.3 m out over the pavement with
    a valance and closed cheeks; trim body tinted maroon or green through COLOR_0 (no new material)."""
    if hm.layout is None:
        return
    m = hm.plain
    row = lambda t: G.trim_v(0, G.BODY, t)
    for e, s0, s1, zf0, name in _a_runs(hm):
        zt, zb, D = zf0 + 3.55, zf0 + 2.95, 1.3
        p = lambda s, d, z: e.p(s, d, z)
        u0, u1 = s0 / 4, s1 / 4
        G.quad(m, p(s1, 0.02, zt), p(s0, 0.02, zt), p(s0, D, zb), p(s1, D, zb), [(u1, row(0.9)), (u0, row(0.9)), (u0, row(0.1)), (u1, row(0.1))], G.TRIM)
        if lod == 0:
            G.quad(m, p(s0, D, zb), p(s0, D, zb - 0.28), p(s1, D, zb - 0.28), p(s1, D, zb), [(u0, row(0.6)), (u0, row(0.3)), (u1, row(0.3)), (u1, row(0.6))], G.TRIM)
            G.quad(m, p(s1, D, zb), p(s0, D, zb), p(s0, 0.02, zt), p(s1, 0.02, zt), [(u1, row(0.4)), (u0, row(0.4)), (u0, row(0.2)), (u1, row(0.2))], G.TRIM)
            for s_, sg in ((s0, -1), (s1, 1)):
                tri = [p(s_, 0.02, zt), p(s_, D, zb), p(s_, D, zb - 0.28)]
                G.tri(m, *(tri if sg > 0 else tri[::-1]), [(0.0, row(0.9)), (0.3, row(0.1)), (0.3, row(0.0))], G.TRIM)
        a, b = p(s0, 0.3, 0), p(s1, D + 0.05, 0)   # face centres of the awning only, not the window head behind
        c_, d_ = p(s1, 0.3, 0), p(s0, D + 0.05, 0)
        uu = [x[0] for x in (a, b, c_, d_)]
        vv = [x[1] for x in (a, b, c_, d_)]
        _mark(min(uu), max(uu), min(vv), max(vv), zb - 0.3, zt + 0.02, AWNING_RGB[name])


def wear(hm: G.HeroMesh) -> None:
    """SLICE6 mesh decals (citylib/wear_decals.py) on every recorded wall, downpipe stains, and hand and wheel wear
    on the gate pillars' lane faces (gf_22). LOD0 only: one draw call (MAT_WearDecal_A)."""
    lay = hm.layout
    n = WD.place(hm.plain, lay.facades, LEVELS[0], lay.pipes)
    zg = ground_z(WALL_U, GATE_V[0])
    for v, sg in ((GATE_V[0], 1), (GATE_V[1], -1)):   # 0.9 m square pillars centred 0.45 m outside the lane
        a, b = (WALL_U + 0.45, v), (WALL_U - 0.45, v)
        if sg < 0:
            a, b = b, a
        WD.wear_quad(hm.plain, a, b, zg, zg + 1.5, "wear0")
        n += 1
    print(f"hero_hotel.wear: {n} decal quads")


def build(lod: int) -> G.HeroMesh:
    if lod == 0:
        _PAINT.clear()
        _PAINT_SEG.clear()
    b = building()
    if lod == 2:
        hm = b.build_far()
        G.box(hm.plain, PORCH[0], PORCH[1], PORCH[2], PORCH[3], 0.0, 7.6, G.TRIM, 0, G.BODY)
        return hm
    hm = b.build(lod)
    porte_cochere(hm, lod)
    boundary_wall(hm, lod)
    gate_lodge(hm, lod)
    drive_through(hm, lod)
    gate_grounds(hm, lod)
    gate_props(hm, lod)
    forecourt(hm, lod)
    sea_terrace(hm, lod)
    corner_wall(hm, lod)
    octagon_roof(hm, lod)
    shop_awnings(hm, lod)
    if lod == 0:
        wear(hm)
    if hm.layout is not None:
        hm.layout.baluster_spacing = BALUSTER_SPACING
    return hm
