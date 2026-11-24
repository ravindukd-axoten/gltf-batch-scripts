"""The building kit (Art Bible "Architecture, kits and materials") and how buildings are assembled.

Every piece is authored in its own local frame:
  x = along the wall (0 .. width), z = up (0 .. height), y = depth.
  The facade lies on y = 0 and faces -y (outward); recesses go to +y (into the building).
Widths and heights sit on the 0.5 m kit grid. Pieces are greybox placeholders sized for the trim-sheet
layout below; art replaces the meshes later without changing names, pivots or dimensions.

Trim sheet layout (all MAT_*_Trim materials, 1 UV unit = 4 m, 512 px/m -> 2048 px on High):
  v 0.00-0.80  wall body (one 3.2 m storey; u tiles horizontally, u = x / 4)
  v 0.80-0.90  cornice / floor band / coping strip
  v 0.90-1.00  reveal / edge strip (window and door reveals, sills, soffits)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import materials, rules
from .mesh import MeshData, rect

MAT_FACADE = "MAT_Facade_Shophouse_Trim"
MAT_FACADE_CONCRETE = "MAT_Facade_Concrete_Trim"
MAT_ACCENT = "MAT_Facade_Accent_Trim"
MAT_GLASS = "MAT_Glass_Window"
MAT_ROOF = "MAT_Roof_Concrete"
MAT_PROP = "MAT_Prop_Shared_Atlas"
MAT_HERO = "MAT_Hero_Placeholder"

ROW_CORNICE = (0.80, 0.90)
ROW_REVEAL = (0.90, 1.00)


def wall_uv(p, loc, ul, vl):
    """Front faces: u = x / 4, v = height within the storey / 4 (stays in the wall-body row)."""
    z = p[2] % rules.UPPER_FLOOR_M if p[2] > rules.UPPER_FLOOR_M + 1e-6 else p[2]
    return p[0] / 4.0, min(z, rules.UPPER_FLOOR_M) / 4.0


def strip_uv(row):
    r0, r1 = row

    def fn(p, loc, ul, vl):
        if ul >= vl:
            return loc[0] / 4.0, r0 + (r1 - r0) * (loc[1] / vl if vl else 0.0)
        return loc[1] / 4.0, r0 + (r1 - r0) * (loc[0] / ul if ul else 0.0)
    return fn


def box_uv(p, loc, ul, vl):
    return loc[0] / 4.0, loc[1] / 4.0


X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


def _v(axis, s):
    return axis[0] * s, axis[1] * s, axis[2] * s


def _wall_uv_for(z0: float, z1: float):
    """Wall-body UVs by storey: the face's storey (4.0 m ground floor, 3.2 m upper floors, stacked tower
    floors by their 3.2 m grid) fills the trim's body row v 0-0.8 once, so window heads, sills and the
    streaks under each floor band line up on every storey."""
    eps = 1e-6
    if rules.UPPER_FLOOR_M + eps < z1 <= rules.GROUND_FLOOR_M + eps and z0 < rules.UPPER_FLOOR_M:
        base, h = 0.0, rules.GROUND_FLOOR_M
    else:
        base = math.floor((z0 + eps) / rules.UPPER_FLOOR_M) * rules.UPPER_FLOOR_M
        h = rules.UPPER_FLOOR_M

    def fn(p, loc, ul, vl):
        return p[0] / 4.0, min(max((p[2] - base) / h, 0.0), 1.0) * 0.8
    return fn


def _front(m, x0, x1, z0, z1, mat, y=0.0, uv=wall_uv):
    if uv is wall_uv:
        uv = _wall_uv_for(z0, z1)
    rect(m, (x0, y, z0), _v(X, x1 - x0), _v(Z, z1 - z0), mat, uv)


def _opening(m, x0, x1, z0, z1, depth, back_mat, reveal_mat, sill=True):
    """Recessed opening: back face plus left, right, top (and bottom) reveals."""
    _front(m, x0, x1, z0, z1, back_mat, y=depth, uv=box_uv)
    reveal = strip_uv(ROW_REVEAL)
    rect(m, (x0, 0.0, z0), _v(Y, depth), _v(Z, z1 - z0), reveal_mat, reveal)          # left side, faces +x
    rect(m, (x1, depth, z0), _v(Y, -depth), _v(Z, z1 - z0), reveal_mat, reveal)       # right side, faces -x
    rect(m, (x0, 0.0, z1), _v(Y, depth), _v(X, x1 - x0), reveal_mat, reveal)          # soffit, faces -z
    if sill:
        rect(m, (x0, 0.0, z0), _v(X, x1 - x0), _v(Y, depth), reveal_mat, reveal)      # sill top, faces +z


def _band(m, x0, x1, z0, z1, proj, mat):
    """Horizontal projecting band (cornice, sill, coping): front, top and bottom faces."""
    s = strip_uv(ROW_CORNICE)
    rect(m, (x0, -proj, z0), _v(X, x1 - x0), _v(Z, z1 - z0), mat, s)                  # front
    rect(m, (x0, -proj, z1), _v(X, x1 - x0), _v(Y, proj), mat, s)                     # top, faces +z
    rect(m, (x0, 0.0, z0), _v(X, x1 - x0), _v(Y, -proj), mat, s)                      # bottom, faces -z


# --- pieces -------------------------------------------------------------------------------------

def balcony_shophouse() -> MeshData:
    """Balcony slab with a solid railing, 3.0 m wide, 0.9 m deep; sits on a storey's floor line."""
    m = MeshData()
    w, d, t, rh = 3.0, 0.9, 0.15, 1.0
    s = strip_uv(ROW_CORNICE)
    rect(m, (0.0, -d, t), _v(X, w), _v(Y, d), MAT_FACADE, box_uv)                      # slab top
    rect(m, (0.0, 0.0, 0.0), _v(X, w), _v(Y, -d), MAT_FACADE, box_uv)                  # slab underside
    rect(m, (0.0, -d, 0.0), _v(X, w), _v(Z, t), MAT_FACADE, s)                         # slab edge
    rt = 0.06  # railing thickness, so inner and outer faces never share vertices
    ry = -d + 0.02  # railing set 2 cm in from the slab edge so no edge is shared by three faces
    rect(m, (0.0, ry, t), _v(X, w), _v(Z, rh), MAT_ACCENT, box_uv)                     # railing outside
    rect(m, (w, ry + rt, t), _v(X, -w), _v(Z, rh), MAT_ACCENT, box_uv)                 # railing inside, faces +y
    rect(m, (0.0, ry, t + rh), _v(X, w), _v(Y, rt), MAT_ACCENT, strip_uv(ROW_REVEAL))  # railing cap
    rect(m, (0.0, 0.0, t), _v(Y, ry), _v(Z, rh), MAT_ACCENT, box_uv)                   # left end, faces -x
    rect(m, (w, ry, t), _v(Y, -ry), _v(Z, rh), MAT_ACCENT, box_uv)                     # right end, faces +x
    return m


def wallplain_upper() -> MeshData:
    """Blank upper-floor wall, 3.0 x 3.2 m, with the floor band so bands run round the building."""
    m = MeshData()
    _front(m, 0.0, 3.0, 0.0, rules.UPPER_FLOOR_M - 0.15, MAT_FACADE)
    _band(m, 0.0, 3.0, rules.UPPER_FLOOR_M - 0.15, rules.UPPER_FLOOR_M, 0.06, MAT_FACADE)
    return m


def wallplain_ground() -> MeshData:
    """Blank ground-floor wall, 3.0 x 4.0 m (side and back walls)."""
    m = MeshData()
    _front(m, 0.0, 3.0, 0.0, rules.GROUND_FLOOR_M - 0.15, MAT_FACADE)
    _band(m, 0.0, 3.0, rules.GROUND_FLOOR_M - 0.15, rules.GROUND_FLOOR_M, 0.06, MAT_FACADE)
    return m


def _tower_floor(m: MeshData, z: float, w: float) -> None:
    _front(m, 0.0, w, z, z + 1.0, MAT_FACADE_CONCRETE)                                # spandrel
    _front(m, 0.0, w, z + 1.0, z + rules.UPPER_FLOOR_M, MAT_GLASS, y=0.12, uv=box_uv)  # glass ribbon
    s = strip_uv(ROW_REVEAL)
    rect(m, (0.0, 0.0, z + 1.0), _v(X, w), _v(Y, 0.12), MAT_FACADE_CONCRETE, s)          # sill, faces +z
    rect(m, (0.0, 0.0, z + rules.UPPER_FLOOR_M), _v(Y, 0.12), _v(X, w), MAT_FACADE_CONCRETE, s)  # soffit


def wallbay_tower() -> MeshData:
    """Modern concrete/glass bay, 6.0 x 3.2 m: spandrel plus recessed ribbon window (one storey)."""
    m = MeshData()
    _tower_floor(m, 0.0, 6.0)
    return m


def wallbay_tower_4f() -> MeshData:
    """Four stacked tower storeys, 6.0 x 12.8 m, so tall buildings need a quarter of the instances."""
    m = MeshData()
    for f in range(4):
        _tower_floor(m, f * rules.UPPER_FLOOR_M, 6.0)
    return m


def _tower_floor_punched(m: MeshData, z: float, w: float) -> None:
    """HEIGHTS/placement 2026-11-24 (agent r8: repeated buildings): punched-window storey, two 1.8 m windows per
    6 m bay between concrete piers (the older Cityhub office and apartment blocks), 30 triangles."""
    uf = rules.UPPER_FLOOR_M
    _front(m, 0.0, w, z, z + 0.9, MAT_FACADE_CONCRETE)
    _front(m, 0.0, w, z + 2.8, z + uf, MAT_FACADE_CONCRETE)
    for a, b in ((0.0, 0.6), (2.4, 3.6), (5.4, w)):
        _front(m, a, b, z + 0.9, z + 2.8, MAT_FACADE_CONCRETE)
    for a, b in ((0.6, 2.4), (3.6, 5.4)):
        _opening(m, a, b, z + 0.9, z + 2.8, 0.15, MAT_GLASS, MAT_FACADE_CONCRETE)


def _tower_floor_balcony(m: MeshData, z: float, w: float) -> None:
    """HEIGHTS/placement 2026-11-24: residential storey, the glass ribbon behind a 0.9 m deep balcony with a solid
    1.0 m upstand (the newer apartment towers' horizontal banding), 14 triangles."""
    _tower_floor(m, z, w)
    _band(m, 0.0, w, z, z + 1.0, 0.9, MAT_FACADE_CONCRETE)


def _stack(floor, n: int):
    def build() -> MeshData:
        m = MeshData()
        for f in range(n):
            floor(m, f * rules.UPPER_FLOOR_M, 6.0)
        return m
    return build


TOWER_FAMILIES = "ABC"   # A ribbon glass (V1), B punched windows, C balcony bands


def parapet_concrete() -> MeshData:
    """Roof parapet, 3.0 x 0.9 m, 0.2 m thick: outer face, coping top and inner face."""
    m = MeshData()
    w, h, t = 3.0, rules.PARAPET_M, 0.2
    _front(m, 0.0, w, 0.0, h, MAT_FACADE_CONCRETE)
    rect(m, (0.0, 0.0, h), _v(X, w), _v(Y, t), MAT_FACADE_CONCRETE, strip_uv(ROW_CORNICE))  # coping
    rect(m, (w, t, 0.0), _v(X, -w), _v(Z, h), MAT_FACADE_CONCRETE, wall_uv)              # inner, faces +y
    return m


def roof_tank() -> MeshData:
    """Rooftop water tank (Art Bible: rooflines matter most), 1.2 m diameter, 1.1 m tall, 8 sides."""
    m = MeshData()
    r, h, n = 0.6, 1.1, 8
    ring = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    for i in range(n):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % n]
        rect(m, (ax, ay, 0.0), (bx - ax, by - ay, 0.0), _v(Z, h), MAT_PROP, box_uv)
    m.add_face([(x, y, h) for x, y in ring], [(0.5 + x / 2.4, 0.5 + y / 2.4) for x, y in ring], MAT_PROP)
    return m


@dataclass(frozen=True)
class KitPiece:
    name: str
    width: float
    height: float
    build: object  # () -> MeshData


KIT: dict[str, KitPiece] = {p.name: p for p in (
    KitPiece("KIT_Balcony_Shophouse_A", 3.0, 1.15, balcony_shophouse),
    KitPiece("KIT_WallPlain_Upper_A", 3.0, rules.UPPER_FLOOR_M, wallplain_upper),
    KitPiece("KIT_WallPlain_Ground_A", 3.0, rules.GROUND_FLOOR_M, wallplain_ground),
    KitPiece("KIT_WallBay_Tower_A", 6.0, rules.UPPER_FLOOR_M, wallbay_tower),
    KitPiece("KIT_WallBay_Tower_4F_A", 6.0, 4 * rules.UPPER_FLOOR_M, wallbay_tower_4f),
    KitPiece("KIT_WallBay_Tower_B", 6.0, rules.UPPER_FLOOR_M, _stack(_tower_floor_punched, 1)),
    KitPiece("KIT_WallBay_Tower_4F_B", 6.0, 4 * rules.UPPER_FLOOR_M, _stack(_tower_floor_punched, 4)),
    KitPiece("KIT_WallBay_Tower_C", 6.0, rules.UPPER_FLOOR_M, _stack(_tower_floor_balcony, 1)),
    KitPiece("KIT_WallBay_Tower_4F_C", 6.0, 4 * rules.UPPER_FLOOR_M, _stack(_tower_floor_balcony, 4)),
    KitPiece("KIT_Parapet_Concrete_A", 3.0, rules.PARAPET_M, parapet_concrete),
    KitPiece("KIT_RoofTank_A", 1.2, 1.1, roof_tank),
)}

from . import props as _props  # noqa: E402

KIT.update({p.name: p for p in (
    KitPiece("KIT_Revetment_Rock_A", 2.4, 1.35, _props.revetment_rock),
    KitPiece("KIT_RoadMarking_Zebra_A", 7.5, 0.01, _props.zebra_crossing),
    KitPiece("KIT_PierPile_A", 0.6, 1.0, _props.pier_pile),
    KitPiece("KIT_Pier_Pedestrian_A", 4.0, 1.2, _props.pier_pedestrian),
    KitPiece("KIT_Fin_Vertical_A", 0.35, 1.0, _props.fin_vertical),
)})

PROPS: dict[str, KitPiece] = {p.name: p for p in (
    KitPiece("PROP_Palm_Coconut_01", 2.6, 9.6, _props.palm_coconut),
    KitPiece("PROP_PlantPot_01", 1.1, 1.35, _props.plant_pot),
    KitPiece("PROP_Fountain_Roundabout_01", 20.0, 5.2, _props.fountain_roundabout),
    KitPiece("PROP_LampMonument_01", 3.0, 12.5, _props.lamp_monument),
    KitPiece("PROP_Flagpole_01", 4.6, 25.0, _props.flagpole),
    KitPiece("PROP_Cannon_Plinth_01", 2.4, 1.6, _props.cannon_plinth),
    KitPiece("PROP_Kiosk_01", 2.6, 2.3, _props.kiosk),
    KitPiece("PROP_Vendor_Balloons_01", 1.0, 2.9, _props.vendor_balloons),
)}

def _on_world_materials(build):
    """Kit pieces are authored against the kit's 4 m sheets; the exported mesh uses the shared atlases."""
    def built() -> MeshData:
        md = build()
        materials.to_world_materials(md)
        return md
    return built


KIT = {n: KitPiece(p.name, p.width, p.height, _on_world_materials(p.build)) for n, p in KIT.items()}

# The street kit (citylib/street_kit.py data, built by Geometry Nodes in citylib/gn/street.py inside Blender):
# same names and pivots as the V1 placeholders it replaced; `build` is None (no Python geometry).
from . import street_kit as _sk  # noqa: E402

STREET: dict[str, KitPiece] = {n: KitPiece(n, p.width, p.height, None) for n, p in _sk.pieces().items()}
# Isso wade carts and their small props (citylib/carts.py data; modelled and baked by tools/city/build_carts.py,
# loaded from tools/city/assets/PROP_Cart_IssoWade.blend inside Blender): `build` is None too.
from . import carts as _carts  # noqa: E402

CARTS: dict[str, KitPiece] = {n: KitPiece(n, p.width, p.height, None) for n, p in _carts.PIECES.items()}

# Every instanced piece, by name (what blender_scene builds and exports one .glb for).
# P92b road edge kit (tools/city/road_edge_kit/KIT_RoadEdge_A.blend, placed by citylib/road_edge.py): `build` None.
from . import road_edge as _road_edge  # noqa: E402

ROAD_EDGE: dict[str, KitPiece] = {n: KitPiece(n, _road_edge.LENGTH[n], 0.16, None) for n in _road_edge.PIECES}

PIECES: dict[str, KitPiece] = {**KIT, **PROPS, **STREET, **CARTS, **ROAD_EDGE}
# The ones still written as Python MeshData (V1 greybox, moving to the TDD methods asset by asset).
PY_PIECES: dict[str, KitPiece] = {**KIT, **PROPS}

# AGENTS.md / Art Bible budgets (LOD0 triangles): kit building piece 500-3,000; street prop 100-1,500.
# The upper bounds are enforced; greybox pieces sit below the lower bounds until art replaces them.
KIT_MAX_TRIS = 3000
PROP_MAX_TRIS = 1500


def max_tris(name: str) -> int:
    if name in STREET:
        return _sk.pieces()[name].budget
    if name in CARTS:
        return _carts.PIECES[name].budget
    if name in ROAD_EDGE:
        return 300   # street prop small-piece cap; the kit's own budgets are in ROAD_EDGE_KIT_SPEC.md §2
    return PROP_MAX_TRIS if name.startswith("PROP_") else KIT_MAX_TRIS


# --- assembly -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Instance:
    piece: str
    x: float          # world east of the piece origin
    y: float          # world north
    z: float
    rot: float        # radians about +z
    sx: float = 1.0   # stretch along the wall so whole bays fill an edge exactly
    sy: float = 1.0
    sz: float = 1.0
    rx: float = 0.0   # tilt about x / y (radians, Blender XYZ Euler with rot): leaning signs and posts (citylib/decay.py)
    ry: float = 0.0


def _stable_hash(*vals: int) -> int:
    h = 2166136261
    for v in vals:
        h = ((h ^ (v & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return h


def bays_for_edge(length: float, bay: float) -> tuple[int, float]:
    """Whole bays along an edge and the stretch that makes them fit exactly (kept within 0.75-1.5)."""
    n = max(1, round(length / bay))
    return n, length / (n * bay)


def assemble_building(osm_id: int, rings: list[list[tuple[float, float]]], street: list[list[bool]],
                      levels: int, base_z: float, style: dict | None = None) -> tuple[list[Instance], float]:
    """Kit instances for a footprint. rings[0] is the outer ring (counter-clockwise), the rest are
    courtyards (clockwise); each ring is open (first point not repeated). street[r][e] says whether
    edge e of ring r faces a street (shopfronts, windows, balconies) or not (plain walls).
    style: rules.DISTRICT_STYLES entry (upper families, ground bays, paints); None = the Delta Face mix.
    Returns the instances and the roof height (top of the walls)."""
    style = style or {}
    upper_styles = style.get("upper", UPPER_STYLES)
    ground_bays = style.get("ground", GROUND_BAYS)
    paints = style.get("paint", "AAABBCD")
    tfams = style.get("tower_families", TOWER_FAMILIES)
    tower = levels >= rules.TOWER_MIN_LEVELS
    inst: list[Instance] = []
    # long street frontages (whole-block buildings) keep plain upper walls (cell LOD0 budget, cell_-1_4)
    frontage = sum(math.dist(ring[e], ring[(e + 1) % len(ring)]) for r_, ring in enumerate(rings)
                   for e in range(len(ring)) if street[r_][e])
    street_floors = STREET_UPPER_FLOORS if frontage <= LONG_FRONTAGE_M else 0
    street_floors = min(street_floors, int(style.get("street_floors", street_floors)))  # cell budget fit (cells.py)
    top = base_z + rules.wall_height(levels)
    paint = paints[_stable_hash(osm_id, 13) % len(paints)]   # mostly off-white lime (gf_21/24/25), few alternatives
    # plain walls and roofline: towers keep the V1 concrete pieces; the rest the street kit's lime plaster family
    plain_ground = "KIT_WallPlain_Ground_A" if tower else f"KIT_WallPlaster_Ground_{paint}"
    plain_upper = f"KIT_WallPlaster_Upper_{paint}"
    parapet = "KIT_Parapet_Concrete_A" if tower else f"KIT_Parapet_Cornice_{paint}"
    for r, ring in enumerate(rings):
        n = len(ring)
        for e in range(n):
            (ax, ay), (bx, by) = ring[e], ring[(e + 1) % n]
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy)
            if length < 0.05:
                continue
            ux, uy = dx / length, dy / length
            rot = math.atan2(dy, dx)
            facing = street[r][e]

            def place(piece, bay: float, z: float, piece_w: float | None = None) -> None:
                """piece: a name, or k -> name for per-bay choices (street kit variants). piece_w: the piece's
                own width when the bay is wider (stretched bays, cell budget fit)."""
                count, sx = bays_for_edge(length, bay)
                sx *= bay / piece_w if piece_w else 1.0
                step = length / count
                for k in range(count):
                    name = piece(k) if callable(piece) else piece
                    if name:
                        inst.append(Instance(name, ax + ux * step * k, ay + uy * step * k, z, rot, sx))

            if facing:
                # Delta Road shopfront kit (street_kit.py): bay type per bay, fascia board over shutter/glazed bays
                ground = lambda k: ground_bays[_stable_hash(osm_id, r, e, k) % len(ground_bays)]  # noqa: E731
                bay_m = float(style.get("ground_bay_m", 3.0))  # cell budget fit: wider (stretched) bays cost less
                place(ground, bay_m, base_z, 3.0)
                place(lambda k: (f"PROP_Sign_Fascia_{1 + _stable_hash(osm_id, e, k, 3) % FASCIA_SIGNS:02d}"
                                 if "Arched" not in ground(k) else None), bay_m, base_z, 3.0)
                if style.get("corners", True):
                    inst.append(Instance("KIT_Shopfront_Corner_A", ax - ux * 0.45, ay - uy * 0.45, base_z, rot))
            else:
                place(plain_ground, 3.0, base_z)
            z = base_z + rules.GROUND_FLOOR_M
            upper = levels - 1
            if tower:
                # facade family per building (agent r8: repeated buildings), from the style's tower_families
                fam = tfams[_stable_hash(osm_id, 17) % len(tfams)]
                while upper >= 4:
                    place(f"KIT_WallBay_Tower_4F_{fam}", 6.0, z)
                    z += 4 * rules.UPPER_FLOOR_M
                    upper -= 4
                for _ in range(upper):
                    place(f"KIT_WallBay_Tower_{fam}", 6.0, z)
                    z += rules.UPPER_FLOOR_M
            else:
                ustyle = upper_styles[_stable_hash(osm_id, 11) % len(upper_styles)]
                for f in range(upper):
                    if facing and f < street_floors:
                        # one paint family per building; about one bay in five repainted (per-bay ageing variation)
                        place(lambda k: f"KIT_Upper_{ustyle}_" + (paint if _stable_hash(osm_id, e, f, k) % 5 else
                                                                  "AB"[(_stable_hash(osm_id, e, f, k, 1)) % 2]), 3.0, z)
                        if f == 0:
                            place(lambda k: (f"PROP_Sign_Projecting_{1 + _stable_hash(osm_id, e, k) % 4:02d}"
                                             if _stable_hash(osm_id, e, k, 9) % 4 == 0 else None), 3.0, z + 0.6)
                    else:
                        place(plain_upper, 3.0, z)
                    # no projecting balcony band (the old accent railing read as a thick yellow stripe): the upper
                    # modules' thin string course and cornice carry the floor line, as on gf_24
                    z += rules.UPPER_FLOOR_M
            place(parapet, 3.0, top)
    return inst, top


GROUND_BAYS = ("KIT_Shopfront_Shutter_A", "KIT_Shopfront_Glazed_A", "KIT_Shopfront_Shutter_B", "KIT_Shopfront_Glazed_B",
               "KIT_Shopfront_Arched_A", "KIT_Shopfront_Arched_B")
UPPER_STYLES = ("Colonial", "Shophouse", "Modern")
FASCIA_SIGNS = 12
LONG_FRONTAGE_M = 80.0
STREET_UPPER_FLOORS = 2   # detail sits at eye level (Art Bible): window modules on the first two upper floors only


def roof_tank_positions(osm_id: int, centroid: tuple[float, float], area: float, levels: int) -> int:
    """How many tanks a roof gets (0-2): small and mid-rise buildings only, chosen by a stable hash."""
    if levels >= rules.TOWER_MIN_LEVELS or area < 40.0:
        return 0
    return _stable_hash(osm_id, 7) % 3
