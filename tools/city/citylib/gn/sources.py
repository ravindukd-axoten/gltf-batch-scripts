"""Instance sources for the facade generators: small mid-poly pieces modelled to the trim-sheet grid.

Each source is a mesh object in the hidden collection `PI_GN_Sources`, in the bay frame the generators use:
x along the wall, y into the building (the wall plane is y = 0, so proud parts have y < 0), z up. They carry
their own material slot, `UVMap` on FacadeTrim_A rows (or real-scale plaster), a face attribute `uvk` (how the
generator offsets their UVs per bay: 0 none, 1 along the wall) and `uv_seam` edges for the UV1 unwrap (TDD
"Blender asset methods", workaround 2). Boxy pieces get a Bevel (1 segment) on their front edges only, chosen
with bevel weights, and a Weighted Normal, both applied: every source is repeated hundreds of times, so a full
bevel would cost more than the LOD0 budget allows.
"""
from __future__ import annotations

import math

import bmesh
import bpy

from .. import hero_bays as HB
from .. import materials as M

COLLECTION = "PI_GN_Sources"


def _coll() -> bpy.types.Collection:
    c = bpy.data.collections.get(COLLECTION)
    if c is None:
        c = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(c)
        c.hide_render = True
        c.hide_viewport = True
    return c


class Piece:
    """bmesh helper: faces with per-corner UVs, a material slot and a uvk flag."""

    def __init__(self, name: str):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.uvk = self.bm.faces.layers.int.new("uvk")
        self.mats: list[str] = []
        self.bevel_edges: list[tuple] = []

    def face(self, pts, uvs, mat: str, uvk: int = 1):
        vs = [self.bm.verts.new(p) for p in pts]
        f = self.bm.faces.new(vs)
        if mat not in self.mats:
            self.mats.append(mat)
        f.material_index = self.mats.index(mat)
        f[self.uvk] = uvk
        for lp, uv in zip(f.loops, uvs):
            lp[self.uv].uv = uv
        return f

    def trim_quad(self, pts, length, row=HB.CORNICE, block=0, t0=0.0, t1=1.0, u0=0.0, mat=M.FACADE_TRIM):
        """Quad a-b-c-d (a-b along the run, b-c up the row) on a trim row."""
        v0, v1 = HB.trim_v(block, row, t0), HB.trim_v(block, row, t1)
        return self.face(pts, [(u0, v0), (u0 + length / 4, v0), (u0 + length / 4, v1), (u0, v1)], mat)

    def finish(self, bevel_width: float = 0.0, smooth: bool = False, seams_from_uv: bool = False) -> bpy.types.Object:
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:]) if False else None
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(bpy.data.materials.get(m) or bpy.data.materials.new(m))
        old = bpy.data.objects.get(self.name)
        if old is not None:
            bpy.data.objects.remove(old)
        ob = bpy.data.objects.new(self.name, me)
        _coll().objects.link(ob)
        if smooth:
            me.shade_smooth()
        if bevel_width > 0 and self.bevel_edges:
            _weight_edges(me, self.bevel_edges)
            _bevel_apply(ob, bevel_width)
        if seams_from_uv:
            _seams_from_uv(ob)
        return ob


def _weight_edges(me, segments) -> None:
    """Bevel weight 1 on edges matching the given (p, q) segments (positions, either order)."""
    attr = me.attributes.get("bevel_weight_edge") or me.attributes.new("bevel_weight_edge", "FLOAT", "EDGE")
    want = [(tuple(round(c, 4) for c in p), tuple(round(c, 4) for c in q)) for p, q in segments]
    for e in me.edges:
        a = tuple(round(c, 4) for c in me.vertices[e.vertices[0]].co)
        b = tuple(round(c, 4) for c in me.vertices[e.vertices[1]].co)
        for p, q in want:
            if (a, b) in ((p, q), (q, p)) or _on_segment(a, b, p, q):
                attr.data[e.index].value = 1.0


def _on_segment(a, b, p, q) -> bool:
    """Edge a-b lies on segment p-q."""
    def onseg(x):
        px = [x[i] - p[i] for i in range(3)]
        d = [q[i] - p[i] for i in range(3)]
        ln2 = sum(c * c for c in d) or 1e-12
        t = sum(px[i] * d[i] for i in range(3)) / ln2
        if t < -1e-4 or t > 1 + 1e-4:
            return False
        return sum((px[i] - d[i] * t) ** 2 for i in range(3)) < 1e-8
    return onseg(a) and onseg(b)


def _bevel_apply(ob, width: float) -> None:
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.width = width
    bev.segments = 1
    bev.limit_method = "WEIGHT"
    bev.harden_normals = True
    bev.face_strength_mode = "FSTR_ALL"
    bev.miter_outer = "MITER_ARC"
    wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.mode = "FACE_AREA"
    wn.use_face_influence = True
    wn.keep_sharp = True
    wn.weight = 50
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
        for mod in list(ob.modifiers):
            bpy.ops.object.modifier_apply(modifier=mod.name)


def _seams_from_uv(ob) -> None:
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv["UVMap"]
    seam = [False] * len(bm.edges)
    for e in bm.edges:
        if len(e.link_loops) != 2:
            seam[e.index] = True
            continue
        l1, l2 = e.link_loops
        # the two faces' corners at each end of the edge must share UVs
        a1, b1 = l1[uv].uv, l1.link_loop_next[uv].uv
        a2, b2 = l2.link_loop_next[uv].uv, l2[uv].uv
        if (a1 - a2).length > 1e-5 or (b1 - b2).length > 1e-5:
            seam[e.index] = True
    bm.free()
    attr = me.attributes.get("uv_seam") or me.attributes.new("uv_seam", "BOOLEAN", "EDGE")
    attr.data.foreach_set("value", seam)


def _box(p: Piece, x0, x1, y0, y1, z0, z1, faces="FTLRK", row=HB.CORNICE, block=0, mat=M.FACADE_TRIM):
    """Box faces: F front (y0, faces -y), T top, B bottom, L/R ends, K back. UVs on a trim row."""
    w, d, h = x1 - x0, y1 - y0, z1 - z0
    if "F" in faces:
        p.trim_quad([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], w, row, block, u0=x0 / 4, mat=mat)
    if "T" in faces:
        p.trim_quad([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], w, HB.REVEAL, block, u0=x0 / 4, mat=mat)
    if "B" in faces:
        p.trim_quad([(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)], w, HB.REVEAL, block, u0=x0 / 4, mat=mat)
    if "L" in faces:
        p.trim_quad([(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)], d, row, block, mat=mat)
    if "R" in faces:
        p.trim_quad([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], d, row, block, mat=mat)
    if "K" in faces:
        p.trim_quad([(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], w, row, block, mat=mat)
    _ = h


def _extrude_profile(p: Piece, prof, x0, x1, row=HB.CORNICE, block=0, caps=True, mat=M.FACADE_TRIM):
    """Moulding along x from x0 to x1 with profile [(y, z), ...] listed so that the faces look outwards
    (front-bottom to top-back). End caps as n-gons."""
    w = x1 - x0
    n = len(prof) - 1
    for j in range(n):
        (ya, za), (yb, zb) = prof[j], prof[j + 1]
        p.trim_quad([(x0, ya, za), (x1, ya, za), (x1, yb, zb), (x0, yb, zb)], w, row, block, j / n, (j + 1) / n, x0 / 4, mat)
    if caps:
        uv = [(0.0, HB.trim_v(block, HB.REVEAL, 0.5))] * len(prof)
        p.face([(x0, y, z) for y, z in reversed(prof)], uv, mat)
        p.face([(x1, y, z) for y, z in prof], uv, mat)
    return [((x0, y, z), (x1, y, z)) for y, z in prof]


# --- the pieces ------------------------------------------------------------------------------------

def keystone(block=0) -> bpy.types.Object:
    """Tapered keystone, 0.30 m at the foot, 0.42 m at the head, 0.5 m tall, 0.1 m proud; foot at z = 0."""
    p = Piece("SRC_Keystone")
    b0, b1, h, d = 0.15, 0.21, 0.5, -0.1
    pts = [(-b0, d, 0), (b0, d, 0), (b1, d, h), (-b1, d, h)]
    p.face(pts, [(0, HB.trim_v(block, HB.CORNICE, 0)), (0.075, HB.trim_v(block, HB.CORNICE, 0)),
                 (0.105, HB.trim_v(block, HB.CORNICE, 1)), (-0.03, HB.trim_v(block, HB.CORNICE, 1))], M.FACADE_TRIM)
    for a, b in ((pts[1], pts[2]), (pts[3], pts[0]), (pts[2], pts[3]), (pts[0], pts[1])):
        a0, b0_ = (a[0], 0.0, a[2]), (b[0], 0.0, b[2])
        p.trim_quad([a, a0, b0_, b], math.dist(a, b), HB.REVEAL, block)
    return p.finish()


def impost(block=0) -> bpy.types.Object:
    """Impost band at an arch's springing: a 0.5 m block, 0.2 m tall, with a chamfered under-edge; top at z = 0."""
    p = Piece("SRC_Impost")
    prof = [(-0.02, -0.2), (-0.09, -0.12), (-0.09, 0.0), (0.0, 0.0)]  # (y, z) front-bottom to top-back
    _extrude_profile(p, prof, -0.25, 0.25, HB.CORNICE, block, caps=False)
    return p.finish()


def sill(block=0) -> bpy.types.Object:
    """Window sill 1 m long (scaled to the window), top at z = 0, 0.13 m proud with a drip under the nose."""
    p = Piece("SRC_Sill")
    prof = [(0.0, -0.14), (-0.14, -0.1), (-0.14, 0.0), (0.0, 0.0)]
    _extrude_profile(p, prof, -0.5, 0.5, HB.CORNICE, block)
    return p.finish()


def hood(block=0) -> bpy.types.Object:
    """Cornice hood over a rectangular window, 1 m long (scaled), bottom at z = 0, 0.18 m proud at the top."""
    p = Piece("SRC_Hood")
    prof = [(0.0, 0.0), (-0.06, 0.0), (-0.06, 0.08), (-0.18, 0.18), (-0.18, 0.24), (0.0, 0.24)]
    edges = _extrude_profile(p, prof, -0.5, 0.5, HB.CORNICE, block)
    p.bevel_edges = [edges[4]]
    return p.finish(0.012)


def shutter(mat=M.PLASTER_SMOOTH) -> bpy.types.Object:
    """One louvred shutter leaf flat against the wall, 1 m x 1 m (scaled to the window), gf_22, gf_24.
    SLICE6 card: a flat painted panel 0.06 m proud with its two long edges (6 tris), the frame, slats and their
    shadow lines drawn by a louvre decal 4 mm in front of it (wear_decals.LOUVRE on the shared wear sheet,
    2 tris); was 22 tris of modelled frame and slats. Pays for the closer bay rhythm."""
    from .. import wear_decals as WD
    p = Piece("SRC_Shutter")
    t = M.tile(mat)
    D = -0.06

    def uvq(pts):
        return [(x / t[0], z / t[1]) for x, _, z in pts]

    def q(pts):
        p.face(pts, uvq(pts), mat, 0)
    q([(0, D, 0), (1, D, 0), (1, D, 1), (0, D, 1)])              # panel front
    q([(0, 0, 0), (0, D, 0), (0, D, 1), (0, 0, 1)])              # hinge-side edge
    q([(1, D, 0), (1, 0, 0), (1, 0, 1), (1, D, 1)])              # free edge
    u0, v0, u1, v1 = WD.cell("louvre")
    y = D - 0.004
    p.face([(0, y, 0), (1, y, 0), (1, y, 1), (0, y, 1)], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], WD.MATERIAL, 0)
    return p.finish()


def awning(mat=M.PLASTER_SMOOTH) -> bpy.types.Object:
    """Canvas window canopy 1 m wide (scaled): a sloped sheet from the wall (top at z = 0) out and down, a
    valance and side cheeks (gf_19, gf_25)."""
    p = Piece("SRC_Awning")
    t = M.tile(mat)
    drop, reach, val = 0.6, 0.75, 0.12
    a0, b0 = (-0.5, 0.0, 0.0), (0.5, 0.0, 0.0)
    a1, b1 = (-0.5, -reach, -drop), (0.5, -reach, -drop)
    a2, b2 = (-0.5, -reach, -drop - val), (0.5, -reach, -drop - val)
    sl = math.hypot(reach, drop) / t[1]
    p.face([a1, b1, b0, a0], [(0, 0), (1 / t[0], 0), (1 / t[0], sl), (0, sl)], mat, 0)          # top
    p.face([a0, b0, b1, a1], [(0, sl), (1 / t[0], sl), (1 / t[0], 0), (0, 0)], mat, 0)          # underside
    p.face([a2, b2, b1, a1], [(0, 0), (1 / t[0], 0), (1 / t[0], 0.03), (0, 0.03)], mat, 0)      # valance front
    p.face([a1, b1, b2, a2], [(0, 0.03), (1 / t[0], 0.03), (1 / t[0], 0), (0, 0)], mat, 0)      # valance back
    p.face([(-0.5, 0.0, -drop), a1, a0], [(0, 0), (0.2, 0), (0, 0.15)], mat, 0)                 # cheeks
    p.face([(0.5, 0.0, -drop), b0, b1], [(0, 0), (0, 0.15), (0.2, 0)], mat, 0)
    return p.finish()


def fanlight(block=0) -> bpy.types.Object:
    """Radial fanlight glazing bars for a half-round head of radius 1 (scaled to the opening): a transom bar on
    the springing line and three spokes (gf_21). Bars are 0.06 thick at r = 0.8, flat at y = 0."""
    p = Piece("SRC_Fanlight")
    bar = 0.075
    v0, v1 = HB.trim_v(block, HB.REVEAL, 0.2), HB.trim_v(block, HB.REVEAL, 0.8)
    uv = [(0, v0), (0.5, v0), (0.5, v1), (0, v1)]
    p.face([(-1, 0, -bar / 2), (1, 0, -bar / 2), (1, 0, bar / 2), (-1, 0, bar / 2)], uv, M.FACADE_TRIM)
    for ang in (45.0, 90.0, 135.0):
        a = math.radians(ang)
        ux, uz = math.cos(a), math.sin(a)
        px, pz = -uz * bar / 2, ux * bar / 2
        p.face([(-px, 0, bar / 2 - pz), (ux * 0.98 - px, 0, uz * 0.98 - pz), (ux * 0.98 + px, 0, uz * 0.98 + pz), (px, 0, bar / 2 + pz)],
               uv, M.FACADE_TRIM)
    return p.finish()


def baluster(block=0, sides=4) -> bpy.types.Object:
    """Turned baluster 0.66 m tall at scale 1 (base, bulb, neck, top block), smooth shaded, a UV seam down one
    side so the UV1 unwrap does not collapse it (TDD workaround 2). The rail and plinth hide its ends."""
    p = Piece("SRC_Baluster")
    prof = [(0.065, 0.0), (0.085, 0.2), (0.036, 0.48), (0.062, 0.66)]  # (radius, z) bottom to top
    circ = 2 * math.pi * 0.08
    for j in range(len(prof) - 1):
        (ra, za), (rb, zb) = prof[j], prof[j + 1]
        va, vb = HB.trim_v(block, HB.CORNICE, za / 0.66), HB.trim_v(block, HB.CORNICE, zb / 0.66)
        for k in range(sides):
            a0, a1 = 2 * math.pi * k / sides + math.pi / sides, 2 * math.pi * (k + 1) / sides + math.pi / sides
            pts = [(ra * math.cos(a0), ra * math.sin(a0), za), (ra * math.cos(a1), ra * math.sin(a1), za),
                   (rb * math.cos(a1), rb * math.sin(a1), zb), (rb * math.cos(a0), rb * math.sin(a0), zb)]
            u0, u1 = k / sides * circ / 4, (k + 1) / sides * circ / 4
            p.face(pts, [(u0, va), (u1, va), (u1, vb), (u0, vb)], M.FACADE_TRIM)
    return p.finish(smooth=True, seams_from_uv=True)


def post(block=0) -> bpy.types.Object:
    """Balustrade pedestal 0.34 m square, 1 m tall at scale 1 (scaled to the balustrade), a cap slab on top."""
    p = Piece("SRC_BalPost")
    s, c = 0.17, 0.22
    _box(p, -s, s, -s, s, 0.0, 0.9, "FLRK", HB.BODY, block)
    _box(p, -c, c, -c, c, 0.9, 1.0, "FTLRKB", HB.CORNICE, block)
    p.bevel_edges = [((-c, -c, 1.0), (c, -c, 1.0)), ((c, -c, 1.0), (c, c, 1.0)), ((c, c, 1.0), (-c, c, 1.0)), ((-c, c, 1.0), (-c, -c, 1.0))]
    return p.finish(0.015)


def bracket(block=0) -> bpy.types.Object:
    """Eave bracket (gf_25): a curved wedge 0.16 m wide reaching 1.0 m out under the eave, 0.45 m deep at the
    wall; top at z = 0 (the soffit), wall at y = 0, reaching towards -y."""
    p = Piece("SRC_Bracket")
    w = 0.08
    prof = [(0.0, -0.45), (-1.0, -0.1), (-1.0, 0.0)]  # (y, z): underside out to the tip
    n = len(prof) - 1
    for j in range(n):
        (ya, za), (yb, zb) = prof[j], prof[j + 1]
        p.trim_quad([(-w, ya, za), (w, ya, za), (w, yb, zb), (-w, yb, zb)], 2 * w, HB.CORNICE, block, j / n, (j + 1) / n)
    side = prof + [(0.0, 0.0)]
    uv = [(abs(y) / 4, HB.trim_v(block, HB.CORNICE, 1 + z / 0.45)) for y, z in side]
    p.face([(-w, y, z) for y, z in reversed(side)], list(reversed(uv)), M.FACADE_TRIM)
    p.face([(w, y, z) for y, z in side], uv, M.FACADE_TRIM)
    return p.finish()


def wall_pier(block=0, thickness=0.36) -> bpy.types.Object:
    """Boundary-wall pier (gf_23): 0.56 m wide, standing 0.1 m proud of both wall faces, 1.95 m tall at scale 1
    (the generator scales z with the wall height), a moulded cap and a dark base; centred on the wall."""
    p = Piece("SRC_WallPier")
    c = thickness / 2
    s, k = 0.28, 0.34
    _box(p, -s, s, c - s, c + s, 0.32, 1.95, "FLRK", HB.BODY, block)
    _box(p, -s - 0.02, s + 0.02, c - s - 0.02, c + s + 0.02, 0.0, 0.32, "FLRK", HB.REVEAL, 2)
    _box(p, -k, k, c - k, c + k, 1.95, 2.1, "FTLRKB", HB.CORNICE, block)
    p.bevel_edges = [((-k, c - k, 2.1), (k, c - k, 2.1)), ((k, c - k, 2.1), (k, c + k, 2.1)),
                     ((k, c + k, 2.1), (-k, c + k, 2.1)), ((-k, c + k, 2.1), (-k, c - k, 2.1))]
    return p.finish(0.015)


def gate_pier(block=0, thickness=0.36) -> bpy.types.Object:
    """Square gate pillar (gf_22, gf_23): 0.9 m square, 2.6 m to a moulded cap, a dark base and a glazed lantern
    with a dark roof on top; centred on the wall line it ends."""
    p = Piece("SRC_GatePier")
    c = thickness / 2
    s, k = 0.45, 0.55
    # SLICE5 (gf_22): taller pier, a two-tier moulded cap, and a black lantern hanging from a bracket on the street
    # face (-y) instead of standing on top
    zt = 3.05
    _box(p, -s, s, c - s, c + s, 0.35, zt, "FLRK", HB.BODY, block)
    _box(p, -s - 0.02, s + 0.02, c - s - 0.02, c + s + 0.02, 0.0, 0.35, "FLRK", HB.REVEAL, 2)
    _box(p, -s - 0.04, s + 0.04, c - s - 0.04, c + s + 0.04, zt - 0.22, zt - 0.14, "FLRKB", HB.CORNICE, block)   # neck band
    _box(p, -k, k, c - k, c + k, zt, zt + 0.22, "FTLRKB", HB.CORNICE, block)
    _box(p, -0.36, 0.36, c - 0.36, c + 0.36, zt + 0.22, zt + 0.36, "FTLRK", HB.CORNICE, block)
    yf = c - s                                   # street face
    _box(p, -0.03, 0.03, yf - 0.42, yf, 2.42, 2.48, "FTLRKB", HB.REVEAL, 2)              # bracket arm
    _box(p, -0.12, 0.12, yf - 0.02, yf, 2.2, 2.6, "FLR", HB.REVEAL, 2)                    # wall plate
    yl = yf - 0.36
    _box(p, -0.015, 0.015, yl - 0.015, yl + 0.015, 2.2, 2.42, "FLRK", HB.REVEAL, 2)      # hanger
    _box(p, -0.17, 0.17, yl - 0.17, yl + 0.17, 2.12, 2.2, "FTLRKB", HB.REVEAL, 2)         # lantern roof
    _box(p, -0.12, 0.12, yl - 0.12, yl + 0.12, 1.74, 2.12, "FLRK", HB.BODY, 0, mat=M.TOWER_GLASS)
    _box(p, -0.14, 0.14, yl - 0.14, yl + 0.14, 1.68, 1.74, "FLRKB", HB.REVEAL, 2)         # lantern base
    p.bevel_edges = [((-k, c - k, zt + 0.22), (k, c - k, zt + 0.22)), ((k, c - k, zt + 0.22), (k, c + k, zt + 0.22)),
                     ((k, c + k, zt + 0.22), (-k, c + k, zt + 0.22)), ((-k, c + k, zt + 0.22), (-k, c - k, zt + 0.22))]
    return p.finish(0.015)


def build_all() -> dict[str, bpy.types.Object]:
    return {ob.name: ob for ob in (keystone(), impost(), sill(), hood(), shutter(), awning(), fanlight(), baluster(),
                                   post(), bracket(), wall_pier(), gate_pier())}
