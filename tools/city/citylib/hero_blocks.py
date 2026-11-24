"""Block-massed hero buildings: the shared facade machinery for the colonial hotel and the assembly hall.

A hero is a set of axis-aligned blocks in its local frame (u, v), each with a storey count and a roof. For
every storey the blocks taller than it are unioned (Shapely) and each exterior edge of that outline gets a
facade for that storey from a style function: an arcade (real arches with a veranda behind), windows (inset
glass with surrounds), or plain wall. Mouldings run around each storey outline, quoins sit on convex
corners, and roofs are hipped (optionally with Dutch gablets) per block. The same description builds three
levels of detail:

- LOD0: everything above (target 35-55k triangles for a 100 m building).
- LOD1: flat walls with glass and dark arch faces laid on them, the eave cornice and the same roofs (~10k).
- Far: one box and one hip roof per block (a few hundred triangles), for the cell's far proxy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from shapely import ops
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient

from . import hero_bays as HB
from . import hero_geom as G


@dataclass
class Block:
    name: str
    u0: float
    u1: float
    v0: float
    v1: float
    storeys: int
    pitch: float = 27.0
    gablet: float = 0.0
    roof: bool = True
    roof_ext: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # extend the roof rect (u0-, u1+, v0-, v1+)
    tag: str = ""

    def contains(self, u, v) -> bool:
        return self.u0 - 1e-6 <= u <= self.u1 + 1e-6 and self.v0 - 1e-6 <= v <= self.v1 + 1e-6


@dataclass
class FacadeStyle:
    """What one storey of one edge looks like."""
    kind: str                    # "arcade" | "windows" | "plain"
    spacing: float = 3.6
    margin: float = 1.4
    win_w: float = 1.3
    win_h: float = 2.4
    sill: float = 0.9
    arch_w: float = 2.6
    crown_gap: float = 0.55      # wall above the arch crown
    veranda: float = 3.0
    balustrade: bool = False     # balustrade across each arcade opening (upper verandas)
    surround: bool = True
    arched_windows: bool = False
    shutters: bool = False       # paired open louvred shutters (street side, gf_22, gf_24)
    awnings: bool = False        # canvas canopies over the windows (gf_19, gf_25)
    french: bool = False         # tall round-arched French doors with radial fanlights (gf_21)
    loggia: bool = False         # arcade projecting in front of the wall, terrace and balustrade on top (gf_19)
    pattern: str = ""            # SLICE6: per-bay variant codes from the edge start (hero_bays.BAY_CODES), cycled; "" = all F


@dataclass
class BlockBuilding:
    blocks: list[Block]
    levels: list[float]                       # z of each floor line: levels[s] .. levels[s+1] is storey s
    style: Callable[["G.Edge", int, Block, dict], FacadeStyle]
    yaw_deg: float = 0.0
    block_id: int = 0                         # FacadeTrim_A block for walls (0 = cream plaster)
    wall_mat: str = G.TRIM
    plinth: float = 0.75
    overhang: float = 1.15
    eave_lift: float = 0.7        # frieze between the eave cornice and the roof, where the eave brackets sit
    brackets: bool = True
    bracket_blocks: tuple = ()   # block names with eave brackets (empty = every block)
    cornice: list[tuple[float, float]] = field(default_factory=lambda: [(0.0, -0.5), (0.12, -0.5), (0.12, -0.35), (0.42, -0.1), (0.42, 0.0), (0.0, 0.0)])
    string: list[tuple[float, float]] = field(default_factory=lambda: [(0.0, -0.3), (0.1, -0.3), (0.16, -0.1), (0.16, 0.0), (0.0, 0.0)])
    quoins: bool = True
    arch_segs: int = 8

    # --- outlines ---------------------------------------------------------------------------------
    def outline(self, storey: int) -> list[list[tuple[float, float]]]:
        """Counter-clockwise exterior rings and clockwise hole rings of the blocks taller than `storey`."""
        polys = [box(b.u0, b.v0, b.u1, b.v1) for b in self.blocks if b.storeys > storey]
        if not polys:
            return []
        geom = ops.unary_union(polys).simplify(0.01)
        rings = []
        for p in getattr(geom, "geoms", [geom]):
            p = orient(Polygon(p.exterior, p.interiors), 1.0)
            rings.append(_dedupe(list(p.exterior.coords)[:-1]))
            for hole in p.interiors:
                rings.append(_dedupe(list(hole.coords)[:-1]))
        return rings

    def block_at(self, u, v, storey) -> Block | None:
        for b in self.blocks:
            if b.storeys > storey and b.contains(u, v):
                return b
        return None

    # --- build ---------------------------------------------------------------------------------------
    def build(self, lod: int) -> G.HeroMesh:
        """Python part (plain wall strips, quoins, eave friezes) in hm.plain/hm.bevel, and the repeated parts and
        the roofs as a FacadeLayout in hm.layout for the GN generators (citylib/gn/facade.py)."""
        hm = G.HeroMesh(self.yaw_deg)
        lay = hm.layout = HB.FacadeLayout()
        top = max(b.storeys for b in self.blocks)
        for s in range(top):
            zf0, zf1 = self.levels[s], self.levels[s + 1]
            for ring in self.outline(s):
                n = len(ring)
                for i in range(n):
                    e = G.Edge(ring[i], ring[(i + 1) % n])
                    if e.length < 0.3:
                        continue
                    mid = e.p(e.length / 2, -0.5, 0)
                    blk = self.block_at(mid[0], mid[1], s)
                    st = self.style(e, s, blk, {"zf0": zf0, "zf1": zf1, "storey": s})
                    self._edge(hm, e, zf0, zf1, st, lod)
                    if lod == 0 and self.quoins and blk is not None and blk.tag == "pavilion":
                        nxt = G.Edge(ring[(i + 1) % n], ring[(i + 2) % n])
                        if _cross(e.t, nxt.t) > 0.5:  # convex corner at e.b
                            G.edge_box(hm.plain, e, e.length - 0.75, e.length + 0.14, 0.0, 0.14, zf0, zf1, G.TRIM, self.block_id, G.CORNICE, top=False)
                            G.edge_box(hm.plain, nxt, -0.14, 0.75, 0.0, 0.14, zf0, zf1, G.TRIM, self.block_id, G.CORNICE, top=False)
                # eave frieze (and brackets) on edges where this storey is the top of its block
                if self.eave_lift > 0:
                    for i in range(n):
                        e = G.Edge(ring[i], ring[(i + 1) % n])
                        if e.length < 0.3:
                            continue
                        mid = e.p(e.length / 2, -0.5, 0)
                        blk = self.block_at(mid[0], mid[1], s)
                        if blk is None or blk.storeys != s + 1:
                            continue
                        G.wall_quad(hm.plain, e, -0.05, e.length + 0.05, zf1, zf1 + self.eave_lift, zf1, zf1 + 4.0, 0.0, self.block_id, self.wall_mat)
                        if lod == 0 and self.brackets and (not self.bracket_blocks or blk.name in self.bracket_blocks):
                            lay.brackets.append((e.a, e.b, zf1 + self.eave_lift - 0.25))
                # mouldings at the top of this storey (string course or eave cornice)
                is_top = self._is_top(s, ring)
                prof = ("cornice" if is_top else "string") + ("" if lod == 0 else "_lod1")
                lay.mouldings.append(HB.Moulding(tuple(HB.open_ring(ring)), zf1, prof, self.block_id, HB.CORNICE))
            if s == 0 and lod == 0:
                # rainwater downpipes from the eave to the plinth, one near the start of each long wall
                for ring in self.outline(0):
                    for i in range(len(ring)):
                        a, b_ = ring[i], ring[(i + 1) % len(ring)]
                        e = G.Edge(a, b_)
                        mid = e.p(0.8, -0.5, 0)
                        blk = self.block_at(mid[0], mid[1], 0)
                        if blk is None:
                            continue
                        for spot in HB.downpipe_spots(a, b_):
                            lay.pipes.append((spot, 0.1, self.levels[blk.storeys] - 0.6))
            if s == 0 and lod == 0 and self.plinth > 0:
                for ring in self.outline(0):
                    # dark painted base skirting (gf_21, gf_24): FacadeTrim_A block 2's dark reveal row
                    lay.mouldings.append(HB.Moulding(tuple(HB.open_ring(ring)), 0.0, "plinth", 2, HB.REVEAL))
        for b in self.blocks:
            if not b.roof:
                continue
            e0, e1, e2, e3 = b.roof_ext
            r = HB.roof_rect(b.u0 - e0, b.u1 + e1, b.v0 - e2, b.v1 + e3, self.levels[b.storeys] + self.eave_lift, b.pitch,
                             self.overhang, b.gablet, fascia=0.25 if lod == 0 else 0.0)
            lay.roofs.append(r)   # PI_GN_HipRoof
            if lod == 0:
                lay.ridges += HB.roof_lines(r)
        return hm

    def build_far(self) -> G.HeroMesh:
        hm = G.HeroMesh(self.yaw_deg)
        hm.layout = HB.FacadeLayout()
        for b in self.blocks:
            ring = [(b.u0, b.v0), (b.u1, b.v0), (b.u1, b.v1), (b.u0, b.v1)]
            G.prism_ring(hm.plain, ring, 0.0, self.levels[b.storeys] + self.eave_lift, self.wall_mat, self.block_id, G.BODY, top=not b.roof)
            if b.roof:
                e0, e1, e2, e3 = b.roof_ext
                hm.layout.roofs.append(HB.roof_rect(b.u0 - e0, b.u1 + e1, b.v0 - e2, b.v1 + e3, self.levels[b.storeys] + self.eave_lift,
                                                    b.pitch, self.overhang * 0.5))
        return hm

    def _is_top(self, s: int, ring) -> bool:
        """True when storey s is the top storey of some block: that floor line is an eave and gets the full
        cornice (on taller blocks it reads as a strong band); other floor lines get a string course."""
        return any(b.storeys == s + 1 for b in self.blocks)

    # --- facades: bays for the GN generators, plain strips here ------------------------------------
    def _edge(self, hm: G.HeroMesh, e: G.Edge, zf0, zf1, st: FacadeStyle, lod: int) -> None:
        m, lay = hm.plain, hm.layout
        blk, mat = self.block_id, self.wall_mat
        L = e.length
        if st.kind == "skip":   # SLICE5: the edge's storey is built by the hero itself (hotel drive-through)
            return
        if st.kind == "arcade" and st.loggia:
            self._loggia(hm, e, zf0, zf1, st, lod)
            return
        if st.kind not in ("arcade", "windows"):
            G.wall_quad(m, e, 0, L, zf0, zf1, zf0, zf1, 0.0, blk, mat)
            lay.facades.append((e.a, e.b, zf0, zf1, st, []))
            return
        centres, strips = HB.bay_extents(L, st.spacing, st.margin)
        for s0, s1 in strips:
            G.wall_quad(m, e, s0, s1, zf0, zf1, zf0, zf1, 0.0, blk, mat)
        if not centres:
            lay.facades.append((e.a, e.b, zf0, zf1, st, []))
            return
        codes = [(st.pattern[i % len(st.pattern)] if st.pattern and st.kind == "windows" else "F") for i in range(len(centres))]
        info = []
        for c, code in zip(centres, codes):
            if code == "-":
                continue
            hw, z0, z1 = HB.opening_extent(st, code, zf0, zf1, st.spacing)
            info.append((c, code, (c - hw, c + hw, z0, z1)))
        lay.facades.append((e.a, e.b, zf0, zf1, st, info))
        if st.kind == "arcade":
            gen, params = "PI_GN_ArcadeBay", HB.arcade_params(st, zf0, zf1, lod)
            if lod == 0:
                V = st.veranda
                # veranda end walls between the last pier and the first/last bay edge
                ceil_z = zf1 - 0.35
                for sx, sgn in ((centres[0] - st.spacing / 2, 1), (centres[-1] + st.spacing / 2, -1)):
                    p = [e.p(sx, -V, zf0), e.p(sx, -0.6, zf0), e.p(sx, -0.6, ceil_z), e.p(sx, -V, ceil_z)]
                    if sgn < 0:
                        p = [p[1], p[0], p[3], p[2]]
                    G.quad(m, *p, [G.wall_uv(mat, blk, G.BODY, 0, zf0, zf0, zf1), G.wall_uv(mat, blk, G.BODY, V, zf0, zf0, zf1),
                                   G.wall_uv(mat, blk, G.BODY, V, ceil_z, zf0, zf1), G.wall_uv(mat, blk, G.BODY, 0, ceil_z, zf0, zf1)], mat)
                if st.balustrade:
                    hw = st.arch_w / 2
                    lay.runs += HB.opening_runs(e.a, e.b, zf0, 0.3, [(c - hw, c + hw) for c in centres])
            for p in HB.edge_bay_points(e.a, e.b, centres, zf0):
                lay.add_bay(gen, params, p)
            return
        for c, code, pt in zip(centres, codes, HB.edge_bay_points(e.a, e.b, centres, zf0)):
            if code == "-":   # plain bay: wall across it
                G.wall_quad(m, e, c - st.spacing / 2, c + st.spacing / 2, zf0, zf1, zf0, zf1, 0.0, blk, mat)
                continue
            lay.add_bay("PI_GN_WindowGrid", HB.window_params(st, zf0, zf1, st.spacing, lod, code), pt)

    def _loggia(self, hm: G.HeroMesh, e: G.Edge, zf0, zf1, st: FacadeStyle, lod: int) -> None:
        """Arcade standing in front of the wall (gf_19's forecourt): the arch wall at d = +veranda, the building
        wall behind it as the veranda's back wall, closed ends, a flat terrace on top with a balustrade."""
        V = st.veranda
        m, mb = hm.plain, hm.bevel
        blk, mat = self.block_id, self.wall_mat
        L = e.length
        front = _shift(e, V)
        centres = HB.bays(L, st.spacing, st.margin)
        if not centres:
            G.wall_quad(m, e, 0, L, zf0, zf1, zf0, zf1, 0.0, blk, mat)
            return
        sub = FacadeStyle("arcade", st.spacing, st.margin, arch_w=st.arch_w, crown_gap=st.crown_gap, veranda=V)
        self._edge(hm, front, zf0, zf1, sub, lod)
        if lod > 0:
            G.edge_box(m, e, -0.1, L + 0.1, 0.0, V + 0.25, zf1, zf1 + 1.3, G.TRIM, blk, G.CORNICE)
            for sx, sgn in ((0.0, -1), (L, 1)):
                p = [e.p(sx, 0.0, zf0 - 0.75), e.p(sx, V, zf0 - 0.75), e.p(sx, V, zf1), e.p(sx, 0.0, zf1)]
                if sgn > 0:
                    p = [p[1], p[0], p[3], p[2]]
                G.quad(m, *p, [(0, 0), (V / 4, 0), (V / 4, 1), (0, 1)], mat)
            return
        # the veranda's back wall is the building wall: plain outside the bays and above the ceiling
        _, strips = HB.bay_extents(L, st.spacing, st.margin)
        for s0_, s1_ in strips:
            G.wall_quad(m, e, s0_, s1_, zf0, zf1, zf0, zf1, 0.0, blk, mat)
        G.wall_quad(m, e, 0, L, zf1 - 0.35, zf1, zf0, zf1, 0.0, blk, mat)
        # end caps
        for sx, sgn in ((0.0, -1), (L, 1)):
            p = [e.p(sx, 0.0, zf0 - 0.75), e.p(sx, V, zf0 - 0.75), e.p(sx, V, zf1 + 0.3), e.p(sx, 0.0, zf1 + 0.3)]
            if sgn > 0:
                p = [p[1], p[0], p[3], p[2]]
            G.quad(m, *p, [G.wall_uv(mat, blk, G.BODY, 0, zf0, zf0, zf1), G.wall_uv(mat, blk, G.BODY, V, zf0, zf0, zf1),
                           G.wall_uv(mat, blk, G.BODY, V, zf1, zf0, zf1), G.wall_uv(mat, blk, G.BODY, 0, zf1, zf0, zf1)], mat)
        # front plinth, terrace slab edge, and the terrace balustrade (front and both returns)
        G.edge_box(m, e, 0.0, L, V - 0.02, V + 0.12, zf0 - 0.75, zf0 + 0.04, G.TRIM, 2, G.REVEAL, top=True)
        G.edge_box(mb, e, -0.1, L + 0.1, 0.0, V + 0.25, zf1, zf1 + 0.3, G.TRIM, blk, G.CORNICE, top=True, bottom=False)
        z = zf1 + 0.3
        p0, p1 = e.p(0.0, V, z), e.p(L, V, z)
        q0, q1 = e.p(0.0, 0.15, z), e.p(L, 0.15, z)
        hm.layout.runs += HB.split_run(p1, p0, 3.8) + [HB.Run(q0, p0), HB.Run(p1, q1)]


def _shift(e: G.Edge, d: float) -> G.Edge:
    n = e.n
    return G.Edge((e.a[0] + n[0] * d, e.a[1] + n[1] * d), (e.b[0] + n[0] * d, e.b[1] + n[1] * d))


def _cross(a, b) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _dedupe(ring):
    out = []
    for p in ring:
        p = (round(p[0], 4), round(p[1], 4))
        if not out or math.dist(p, out[-1]) > 1e-3:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) < 1e-3:
        out.pop()
    # drop collinear points
    res = []
    n = len(out)
    for i in range(n):
        a, b, c = out[i - 1], out[i], out[(i + 1) % n]
        if abs(_cross((b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1]))) > 1e-6:
            res.append(b)
    return res


def _ring_mid(ring):
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
