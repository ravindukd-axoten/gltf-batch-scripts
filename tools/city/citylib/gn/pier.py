"""Geometry Nodes for HERO_DeltaFacePier (citylib/hero_pier.py): the jetty's repeated parts.

- PI_GN_PierSpans: points with an int `kind` (0 stem bent, 1 deck span, 2 head column) and a float `rot`;
  instances SRC_PierBent (squat 1.8 m square column + crosshead), SRC_PierSpan (one 5.69 m deck span: slab,
  0.1 m lip, 0.7 m fascia beams, underside) and SRC_PierColumn on them, realized (research 3.1: kit pieces
  authored once, placed by GN).
- PI_GN_PierRailing: the T-head's white railing along open polylines: a flat top rail and a bottom rail swept
  along the run, square balusters every `Spacing` metres, posts at the corners and every ~2 m. Detail 1 (LOD1):
  balusters three times sparser.

Paint: every face carries an int face attribute `pi_pk` (index + 1 into hero_pier.PAINT). It survives the AO
bake (which clears the colour attributes); apply_paint() writes it into COLOR_0 rgb after decor.paint and drops
the attribute before export.
"""
from __future__ import annotations

import math

import bmesh
import bpy
import numpy as np

from .. import hero_bays as HB
from .. import hero_pier as P
from .. import materials as M
from .facade import finish_mesh, is_detail0, store_uv
from .nodes import Tree
from .sources import Piece, _box
from .wall import _rot_from, _sweep, _trimmed_points

KEYS = {k: i + 1 for i, k in enumerate(P.PAINT)}
CB = P.CONCRETE_BLOCK


def _paint_faces(p: Piece, n0: int, key: str) -> None:
    lay = p.bm.faces.layers.int.get("pi_pk") or p.bm.faces.layers.int.new("pi_pk")
    p.bm.faces.ensure_lookup_table()
    for f in list(p.bm.faces)[n0:]:
        f[lay] = KEYS[key]


def _pbox(p: Piece, key, *args, **kw) -> None:
    n0 = len(p.bm.faces)
    _box(p, *args, **kw)
    _paint_faces(p, n0, key)


def _box_edges(x0, x1, y0, y1, z0, z1, vertical=True, top=True):
    e = []
    c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for i in range(4):
        (ax, ay), (bx, by) = c[i], c[(i + 1) % 4]
        if top:
            e.append(((ax, ay, z1), (bx, by, z1)))
        if vertical:
            e.append(((ax, ay, z0), (ax, ay, z1)))
    return e


# --- sources (bent frame: x along the jetty, y across, z = 0 at the deck top) ---------------------------

def _column(p: Piece, half: float, z_top: float) -> None:
    """Square column from below the sea bed to z_top, dark wet band below the high-water line."""
    zb = P.Z_BED - P.DECK_Z
    zw = P.WET_Z - P.DECK_Z
    _pbox(p, "wet", -half, half, -half, half, zb, zw, "FLRK", HB.BODY, CB)
    _pbox(p, "concrete", -half, half, -half, half, zw, z_top, "FLRK", HB.BODY, CB)
    p.bevel_edges += [((x, y, zb), (x, y, z_top)) for x in (-half, half) for y in (-half, half)]


def bent() -> bpy.types.Object:
    p = Piece("SRC_PierBent")
    c = P.COL / 2
    zx = -P.SLAB_T - 0.6
    _column(p, c, zx)
    hw, x = P.STEM_W / 2 - 0.05, 1.0
    _pbox(p, "concrete", -x, x, -hw, hw, zx, -P.SLAB_T, "FLRKB", HB.CORNICE, CB)
    p.bevel_edges += _box_edges(-x, x, -hw, hw, zx, -P.SLAB_T, vertical=True, top=False)
    p.bevel_edges += [((ax, ay, zx), (bx, by, zx)) for (ax, ay), (bx, by) in
                      (((-x, -hw), (x, -hw)), ((x, -hw), (x, hw)), ((x, hw), (-x, hw)), ((-x, hw), (-x, -hw)))]
    return p.finish(0.03, seams_from_uv=True)


def column() -> bpy.types.Object:
    p = Piece("SRC_PierColumn")
    _column(p, P.COL / 2 - 0.15, -P.FASCIA - 0.3)
    return p.finish(0.03, seams_from_uv=True)


def span() -> bpy.types.Object:
    """One deck span from x = 0 to SPAN: slab top, a 0.1 m lip 0.04 m proud of the 0.6 m fascia beams, underside."""
    p = Piece("SRC_PierSpan")
    L, hw = P.SPAN, P.STEM_W / 2
    lip, fz = -P.LIP, -P.FASCIA
    # top: a grid of ~0.8 m cells inside one 3.2 m trim row (u = metres / 4), so the per-vertex weathering
    # (apply_paint) has vertices to mottle (pier_02: blotchy, streaked rust-brown concrete)
    n0 = len(p.bm.faces)
    nx, ny = 7, 4
    for i in range(nx):
        for j in range(ny):
            x0, x1 = L * i / nx, L * (i + 1) / nx
            y0, y1 = -hw + 2 * hw * j / ny, -hw + 2 * hw * (j + 1) / ny
            t0, t1 = j / ny, (j + 1) / ny
            p.face([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)],
                   [(x0 / 4, HB.trim_v(CB, HB.BODY, t0)), (x1 / 4, HB.trim_v(CB, HB.BODY, t0)),
                    (x1 / 4, HB.trim_v(CB, HB.BODY, t1)), (x0 / 4, HB.trim_v(CB, HB.BODY, t1))], M.FACADE_TRIM)
    _paint_faces(p, n0, "deck")
    o = 0.04
    _pbox(p, "concrete", 0, L, -hw, -hw + o, lip, 0.0, "FB", HB.CORNICE, CB)        # lip, its underside the shadow line
    _pbox(p, "concrete", 0, L, hw - o, hw, lip, 0.0, "KB", HB.CORNICE, CB)
    _pbox(p, "concrete", 0, L, -hw + o, -hw + o + 0.3, fz, lip, "FKB", HB.BODY, CB)   # fascia beams (inner faces too)
    _pbox(p, "concrete", 0, L, hw - o - 0.3, hw - o, fz, lip, "KFB", HB.BODY, CB)
    _pbox(p, "under", 0, L, -hw + o + 0.3, hw - o - 0.3, -P.SLAB_T - 0.001, -P.SLAB_T, "B", HB.REVEAL, CB)
    p.bevel_edges += [((0, y, 0), (L, y, 0)) for y in (-hw, hw)] + [((0, y, fz), (L, y, fz)) for y in (-hw + o, hw - o)]
    return p.finish(0.025)


def _sources() -> dict:
    out = {}
    for fn, name in ((bent, "SRC_PierBent"), (column, "SRC_PierColumn"), (span, "SRC_PierSpan")):
        ob = bpy.data.objects.get(name)
        out[name] = ob if ob is not None else fn()
    return out


# --- node groups -------------------------------------------------------------------------------------

def spans_group() -> bpy.types.NodeTree:
    t = Tree("PI_GN_PierSpans")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Bent Object", "NodeSocketObject")
    t.input("Span Object", "NodeSocketObject")
    t.input("Column Object", "NodeSocketObject")
    rot = t.o(t.n("FunctionNodeEulerToRotation", {"Euler": t.vec(0.0, 0.0, t.named("rot"))}))
    kind = t.named("kind", "INT")
    parts = []
    for k, sock_name in ((0, "Bent Object"), (1, "Span Object"), (2, "Column Object")):
        geo = t.o(t.n("GeometryNodeObjectInfo", {"Object": t.gi(sock_name)}), "Geometry")
        sel = t.cmp(kind, k, "EQUAL", "INT")
        parts.append(t.o(t.n("GeometryNodeInstanceOnPoints",
                             {"Points": t.gi("Geometry"), "Selection": sel, "Instance": geo, "Rotation": rot})))
    geo = t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": t.join(*parts)}))
    geo = t.o(t.n("GeometryNodeRemoveAttribute", {"Geometry": geo, "Name": "kind"}))
    t.result(finish_mesh(t, geo, merge=0.002))
    return t.ng


def railing_group() -> bpy.types.NodeTree:
    t = Tree("PI_GN_PierRailing")
    t.input("Geometry", "NodeSocketGeometry")
    t.output("Geometry", "NodeSocketGeometry")
    t.input("Detail", "NodeSocketInt", 0, min_value=0, max_value=1)
    t.input("Height", "NodeSocketFloat", P.RAIL_H, min_value=0.5)
    t.input("Spacing", "NodeSocketFloat", 0.14, min_value=0.08)
    t.input("Post Spacing", "NodeSocketFloat", P.RAIL_POST, min_value=0.5)
    t.input("Material", "NodeSocketMaterial")
    H, mat = t.gi("Height"), t.gi("Material")
    d0 = is_detail0(t)
    crv = t.o(t.n("GeometryNodeMeshToCurve", {"Mesh": t.gi("Geometry")}))
    # light grey painted steel (gf_08): the concrete block's neutral cornice row, painted "steel"
    s0, o0 = HB.trim_map(P.CONCRETE_BLOCK, HB.CORNICE)
    uvv = lambda f: t.madd(f, s0, o0)   # noqa: E731
    # round steel tube (gf_08): a 60 mm top rail, a 42 mm bottom rail (8-sided sweeps)
    tube = lambda r: [(r * math.cos(2 * math.pi * i / 8), r * math.sin(2 * math.pi * i / 8)) for i in range(9)]  # noqa: E731
    top = _sweep(t, crv, tube(0.03), mat, uvv)
    top = t.transform(top, translation=t.vec(0.0, 0.0, t.sub(H, 0.03)))
    bot = _sweep(t, crv, tube(0.021), mat, uvv)
    bot = t.transform(bot, translation=(0.0, 0.0, 0.12))
    # balusters: square bars between the rails, sparser at Detail 1
    sp = t.switch(d0, t.mul(t.gi("Spacing"), 3.0), t.gi("Spacing"))
    bn = _trimmed_points(t, crv, 0.12, sp)
    bh = t.sub(H, 0.19)
    bar = t.o(t.n("GeometryNodeMeshCylinder", {"Vertices": 6, "Radius": 0.011, "Depth": bh}), "Mesh")
    bar = t.transform(bar, translation=t.vec(0.0, 0.0, t.add(0.12, t.mul(bh, 0.5))))
    bar = store_uv(t, bar, t.vec(0.3, HB.trim_v(P.CONCRETE_BLOCK, HB.CORNICE, 0.5)))
    bar = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": bar, "Material": mat}))
    bars = t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": t.o(bn, "Points"), "Instance": bar, "Rotation": _rot_from(t, bn)}))
    # posts (round 4, gf_08): round steel posts that rise straight and curve over the deck at the top, at every
    # polyline vertex (the corners, bisecting the turn) and every Post Spacing between, each turned to the rail.
    # The runs go clockwise seen from above, so the deck is on local -y.
    H2 = t.add(H, 0.02)
    line = t.o(t.n("GeometryNodeCurvePrimitiveLine", {"Start": t.vec(0.0, 0.0, 0.0), "End": t.vec(0.0, 0.0, H2)}))
    line = t.o(t.n("GeometryNodeResampleCurve", {"Curve": line, "Count": 6}))
    zf = t.div(t.xyz(t.position())[2], H2)
    line = t.o(t.n("GeometryNodeSetPosition", {"Geometry": line, "Offset": t.vec(0.0, t.mul(t.mul(zf, zf), -0.13), 0.0)}))
    prof = t.o(t.n("GeometryNodeCurvePrimitiveCircle", {"Resolution": 6, "Radius": 0.032}))
    post = t.o(t.n("GeometryNodeCurveToMesh", {"Curve": line, "Profile Curve": prof, "Fill Caps": True}))
    post = store_uv(t, post, t.vec(0.6, HB.trim_v(P.CONCRETE_BLOCK, HB.CORNICE, 0.5)))
    post = t.o(t.n("GeometryNodeSetMaterial", {"Geometry": post, "Material": mat}))
    pv = t.n("GeometryNodeCurveToPoints", {"Curve": crv}, mode="EVALUATED")
    pp = t.n("GeometryNodeCurveToPoints", {"Curve": crv, "Length": t.gi("Post Spacing")}, mode="LENGTH")
    near = t.o(t.n("GeometryNodeProximity", {"Geometry": t.o(pv, "Points")}, target_element="POINTS"), "Distance")
    mid = t.o(t.n("GeometryNodeDeleteGeometry", {"Geometry": t.o(pp, "Points"), "Selection": t.cmp(near, 0.6, "LESS_THAN")}))
    posts = t.join(t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": t.o(pv, "Points"), "Instance": post,
                                                              "Rotation": _rot_from(t, pv)})),
                   t.o(t.n("GeometryNodeInstanceOnPoints", {"Points": mid, "Instance": post, "Rotation": _rot_from(t, pp)})))
    geo = t.o(t.n("GeometryNodeRealizeInstances", {"Geometry": t.join(top, bot, bars, posts)}))
    geo = t.store(geo, "pi_pk", KEYS["steel"], "INT", "FACE")
    for name in ("pu", "pv"):
        geo = t.o(t.n("GeometryNodeRemoveAttribute", {"Geometry": geo, "Name": name}))
    t.result(finish_mesh(t, geo))
    return t.ng


def _group(name, fn):
    return bpy.data.node_groups.get(name) or fn()


def _to_world(u, v, yaw):
    a = math.radians(yaw)
    return u * math.cos(a) - v * math.sin(a), u * math.sin(a) + v * math.cos(a)


def _mod(ob, ng, values):
    from .nodes import set_inputs
    mod = ob.modifiers.new("GN", "NODES")
    mod.node_group = ng
    set_inputs(mod, values)


def objects(name, lay, yaw, coll, lod, mats) -> list:
    """The pier's GN objects (unapplied; build_heroes applies them): the head railing."""
    if lod >= 2:
        return []
    obs = []
    # the spans, bents and columns are modelled since round 3 (citylib/pier_model.jetty_pieces)
    if lay.pier_rails:
        verts, edges = [], []
        for line in lay.pier_rails:
            base = len(verts)
            verts += [(*_to_world(u, v, yaw), z) for u, v, z in line]
            edges += [(base + i, base + i + 1) for i in range(len(line) - 1)]
        me = bpy.data.meshes.new(f"{name}_pier_railing")
        me.from_pydata(verts, edges, [])
        ob = bpy.data.objects.new(f"{name}_pier_railing", me)
        coll.objects.link(ob)
        _mod(ob, _group("PI_GN_PierRailing", railing_group), {"Detail": min(lod, 1), "Material": mats[M.FACADE_TRIM]})
        obs.append(ob)
    return obs


# --- paint ---------------------------------------------------------------------------------------------

def col_to_paint(ob) -> None:
    """MeshData part: nearest PAINT entry to each face's 'Col' colour -> int face attribute pi_pk."""
    me = ob.data
    ca = me.color_attributes.get("Col")
    if ca is None or not len(me.polygons):
        return
    srgb = [0.0] * (len(ca.data) * 4)
    ca.data.foreach_get("color_srgb", srgb)
    table = [(KEYS[k], c) for k, c in P.PAINT.items()]
    out = []
    for p in me.polygons:
        li = p.loop_start * 4
        c = srgb[li:li + 3]
        out.append(min(table, key=lambda kc: sum((a - b) ** 2 for a, b in zip(kc[1], c)))[0])
    a = me.attributes.get("pi_pk") or me.attributes.new("pi_pk", "INT", "FACE")
    a.data.foreach_set("value", out)


def _vnoise(x, y, s):
    """decor._hash_noise over numpy arrays (same values)."""
    def h(i, j):
        n = np.sin(i * 127.1 + j * 311.7 + s * 74.7) * 43758.5453
        return n - np.floor(n)
    xi, yi = np.floor(x), np.floor(y)
    xf, yf = x - xi, y - yi
    u, v = xf * xf * (3 - 2 * xf), yf * yf * (3 - 2 * yf)
    a, b, c, d = h(xi, yi), h(xi + 1, yi), h(xi, yi + 1), h(xi + 1, yi + 1)
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v


def _ss(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _mix(rgb, col, w, mask):
    w = (np.clip(w, 0.0, 1.0) * mask)[:, None]
    return rgb * (1 - w) + np.asarray(col, dtype=float) * w


# weathering colours (sRGB tints on the tiling sets: SHD_HeroLit multiplies the albedo by COLOR_0 rgb * 1.1)
WEATHER = {
    "deck_gain": (1.30, 1.48, 1.45),   # lifts the deck to pier_02's rust-brown ~ (130, 88, 66) in the Unity top view
    "worn": (0.78, 0.64, 0.55),        # (x deck_gain) the walking line: scuffed, dusty, lighter than the rust-brown deck
    "wet": (0.34, 0.33, 0.29),         # round 4: below the tide line, wet dark concrete (pier_03, gf_08)
    "wet_deep": (0.27, 0.29, 0.22),    #   algae-darkened feet, olive black
    "salt": (1.0, 0.98, 0.93),         # salt crust in the splash zone above the tide line
    "rust": (0.60, 0.34, 0.22),        # rust streaks run down the head fascia from the railing posts
    "rock_wet": (0.60, 0.57, 0.52),    # round 4: dark wet grey-brown rock (pier_01 / pier_02 under the surf), not blue
    "rock_dry": (0.86, 0.82, 0.76),    #   dry crowns of the armour at the seawall foot, warm grey
    "weed": (0.36, 0.46, 0.30),
}


def apply_paint(ob, seed: int = 23) -> None:
    """COLOR_0 rgb from pi_pk (alpha = the baked AO stays), then the weathering by position, normal and vertex
    convexity (pier_01-03, gf_08): the deck's rust blotches and lighter worn walking line, a dark wet band and
    salt crust on the columns, rust streaks under the head railing, lighter chipped edges and darker cavities,
    wet / dry / weed rock by height above the sea. Then drops pi_pk."""
    from ..pier_model import convexity
    me = ob.data
    a = me.attributes.get("pi_pk")
    ca = me.color_attributes.get("Col")
    if a is None or ca is None:
        return
    nl, nf = len(me.loops), len(me.polygons)
    keys = np.zeros(nf, dtype=np.int64)
    a.data.foreach_get("value", keys)
    srgb = np.zeros(nl * 4)
    ca.data.foreach_get("color_srgb", srgb)
    srgb = srgb.reshape(-1, 4)
    lt = np.zeros(nf, dtype=np.int64)
    me.polygons.foreach_get("loop_total", lt)
    face_of = np.repeat(np.arange(nf), lt)
    k = keys[face_of]
    vi = np.zeros(nl, dtype=np.int64)
    me.loops.foreach_get("vertex_index", vi)
    co = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)[vi]
    fn = np.zeros(nf * 3)
    me.polygons.foreach_get("normal", fn)
    fn = fn.reshape(-1, 3)[face_of]
    conv = convexity(me)[vi]
    ya = math.radians(P.YAW_DEG)
    c_, s_ = math.cos(ya), math.sin(ya)
    x, y, z = co[:, 0], co[:, 1], co[:, 2]
    u, v = x * c_ + y * s_, -x * s_ + y * c_
    nu, nv, nz = fn[:, 0] * c_ + fn[:, 1] * s_, -fn[:, 0] * s_ + fn[:, 1] * c_, fn[:, 2]
    zs = z - P.Z_SEA
    names = {i: kk for kk, i in KEYS.items()}
    base = np.array([P.PAINT[names[i]] if i > 0 else (1.0, 1.0, 1.0) for i in range(len(KEYS) + 1)])
    rgb = base[k].copy()
    n = _vnoise(x / 5.0, y / 5.0 + z / 7.0, seed)
    m = _vnoise(x / 1.3, y / 1.3, seed + 5)
    is_ = lambda *ks: np.isin(k, [KEYS[q] for q in ks]).astype(float)   # noqa: E731
    top = (nz > 0.7).astype(float)
    deck = is_("deck") * top
    conc = is_("concrete", "under") + is_("deck") * (1 - top)
    rock = is_("rock", "algae")
    stone = is_("granite", "granite_dark")
    # deck: dull rust-brown, blotchy, bleached grey-brown patches, dark rust stains
    w = _vnoise(x / 2.4 + 7.0, y / 2.4, seed + 9)
    kk = (0.74 + 0.34 * n + 0.10 * m) * np.where(w > 0.62, 1.0 - 0.9 * (w - 0.62), 1.0)
    g = 0.25 * (1.0 - n)
    grey = rgb.mean(axis=1, keepdims=True)
    blot = (rgb * (1 - g)[:, None] + grey * g[:, None]) * kk[:, None]
    blot[:, 0] *= 1.0 + 0.05 * (1 - n)
    blot[:, 2] *= 0.94 + 0.08 * n
    rgb = np.where(deck[:, None] > 0, blot * np.asarray(WEATHER["deck_gain"]), rgb)
    # the walking line: the stem's centre, the steps and landing, a worn fan where the stem meets the head
    wobble = (m - 0.5) * 0.35
    stem = ((u > -0.1) & (u < P.HEAD_U0 + 0.5)).astype(float) * (1 - _ss(0.3, 1.0, np.abs(v) + wobble))
    steps = (u < P.STEM_START).astype(float) * 0.7
    fan = 0.75 * (1 - _ss(1.2, 4.2, np.hypot((u - P.HEAD_U0 - 2.2) * 0.9, v * 0.7) + wobble * 2))
    rgb = _mix(rgb, np.asarray(WEATHER["worn"]) * np.asarray(WEATHER["deck_gain"]), 0.6 * np.maximum(np.maximum(stem, steps), fan), deck)
    # concrete: warm grey-brown, a dark wet band low on the columns, salt crust above it, rust under the railing
    kc = 0.88 + 0.14 * n
    rgb = np.where(conc[:, None] > 0, rgb * np.stack([kc, kc * (0.97 + 0.03 * n), kc * (0.95 + 0.05 * n)], 1), rgb)
    rgb = _mix(rgb, (0.70, 0.68, 0.66), 0.35, conc * (nz < -0.7))                       # soffits: greyer, shaded
    # round 4 (pier_03): a crisp tide line at P.TIDE (cut rows on both sides of it), wet dark concrete under it
    # with olive-black algae at the feet, a thin salt line on it and a blotchy salt crust in the splash zone above
    tide = P.TIDE
    rgb = _mix(rgb, WEATHER["wet"], (1 - _ss(tide - 0.02, tide + 0.02, zs)) * (0.85 + 0.15 * m), conc)
    rgb = _mix(rgb, WEATHER["wet_deep"], 1 - _ss(0.05, 0.4, zs + (m - 0.5) * 0.25), conc)
    along = np.where(np.abs(nu) > np.abs(nv), v, u)
    side = (np.abs(nz) < 0.3).astype(float)
    line = _ss(tide - 0.01, tide + 0.03, zs) * (1 - _ss(tide + 0.03, tide + 0.2, zs))
    crust = _ss(0.45, 0.7, _vnoise(along * 2.6, z * 3.4, seed + 3)) * _ss(tide, tide + 0.05, zs) * (
        1 - _ss(tide + 0.35, tide + 0.95, zs))
    rgb = _mix(rgb, WEATHER["salt"], np.maximum(0.55 * line, 0.6 * crust), conc * side)
    grime = _ss(0.4, 0.75, _vnoise(along * 0.9, z * 0.6, seed + 17)) * _ss(tide + 0.4, tide + 1.2, zs)
    rgb = _mix(rgb, (0.58, 0.53, 0.47), 0.4 * grime, conc * side)                       # weathered, mottled upper
    # rust under the head railing: a streak below each post (1.5 m apart) and thinner random ones, fading down
    post = 1 - _ss(0.04, 0.16, np.abs(((along + 0.75) % P.RAIL_POST) - 0.75 + (m - 0.5) * 0.1))
    streak = np.maximum(post, 0.7 * _ss(0.6, 0.85, _vnoise(along * 3.1, 0.0, seed + 7)))
    streak = streak * np.clip(1.0 - (P.DECK_Z - z) / 1.4, 0.0, 1.0) * (0.6 + 0.4 * n)
    rgb = _mix(rgb, WEATHER["rust"], 0.8 * streak, conc * side * (u > P.HEAD_U0 - 0.2))
    run = _ss(0.6, 0.85, _vnoise(along * 1.1, 3.0, seed + 11)) * np.clip(1.0 - (P.DECK_Z - z) / 2.2, 0.0, 1.0)
    rgb = _mix(rgb, (0.55, 0.45, 0.38), 0.35 * run, conc * side)                       # run-off from the deck
    # granite plinth: a lighter top framed by the darker rim (pier_01), slight mottling
    pl0, pl1, plw = P.PLINTH
    r = P.PLINTH_RIM
    rim = ~((u > pl0 + r) & (u < pl1 - r) & (np.abs(v) < plw - r)) & (np.abs(z - P.Z_GREEN - P.PLINTH_H) < 0.05)
    rgb = _mix(rgb, P.PAINT["granite_dark"], 1.0, stone * top * rim)
    rgb = np.where(stone[:, None] > 0, rgb * (0.93 + 0.08 * n)[:, None], rgb)
    # chipped edges show fresher, lighter concrete; cavities hold dirt
    hard = np.clip(conc + deck + stone, 0, 1)
    edge = _ss(0.06, 0.28, conv)
    rgb = np.where(hard[:, None] > 0, rgb * (1 + 0.22 * edge * hard)[:, None], rgb)
    rgb = np.where(hard[:, None] > 0, rgb * (1 - 0.25 * _ss(0.05, 0.25, -conv) * hard)[:, None], rgb)
    # rock: near-black wet rock, lighter dry crowns above the splash, weed at the waterline, dark crevices
    kr = 0.8 + 0.35 * n + 0.15 * m
    rgb = np.where(rock[:, None] > 0, np.asarray(WEATHER["rock_wet"]) * kr[:, None], rgb)
    rgb = _mix(rgb, WEATHER["rock_dry"], 0.55 * _ss(0.35, 0.8, zs + (n - 0.5) * 0.5), rock)
    weed = _ss(0.45, 0.65, _vnoise(x / 1.6, y / 1.6, seed + 13)) * _ss(-0.25, 0.0, zs) * (1 - _ss(0.25, 0.5, zs))
    rgb = _mix(rgb, WEATHER["weed"], 0.7 * weed, rock)
    rgb = np.where(rock[:, None] > 0, rgb * (1 + 0.18 * _ss(0.04, 0.2, conv) - 0.35 * _ss(0.04, 0.2, -conv))[:, None], rgb)
    # paint on the old trim parts (unchanged): faded pink, paving, kerbs
    pink = is_("pink")
    kp = 0.82 + 0.26 * n + 0.08 * m
    rgb = np.where(pink[:, None] > 0, rgb * kp[:, None] + (1 - kp)[:, None] * np.asarray(P.PAINT["deck"]), rgb)
    pav = is_("paving", "kerb")
    rgb = np.where(pav[:, None] > 0, rgb * (0.93 + 0.08 * n)[:, None], rgb)
    sel = keys[face_of] > 0
    srgb[sel, :3] = np.clip(rgb[sel], 0.0, 1.0)
    srgb[k == KEYS["flag"], 3] = 1.0   # a sheet in open air: its two sides 24 mm apart would bake each other black
    # the rock under the stem: the deck 4 m up bakes a wide black halo into it that reads as holes from the air
    rk = sel & (rock > 0)
    srgb[rk, 3] = 0.45 + 0.55 * srgb[rk, 3]
    ca.data.foreach_set("color_srgb", srgb.ravel())
    me.attributes.remove(me.attributes["pi_pk"])
