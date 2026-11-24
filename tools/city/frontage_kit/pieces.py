"""Frontage kit v2 pieces (P96): variant tables -> one assembly node group `ASM_<piece>` per kit piece.

Names, bay width (3.0 m) and storey heights (4.0 ground, 3.2 upper, 0.9 parapet) match the street kit that
`citylib/kit.py` places, so cells can swap meshes. Variant letters keep the old paint meaning (A lime, B cream,
C grey, D pastel) and now also change the geometry (FRONTAGE_KIT_SPEC.md 3). Every number is an estimate from the
reference board in the spec.
"""
from __future__ import annotations

from gnlib import group
from parts import G, tag

W, GF, UF, PAR = 3.0, 4.0, 3.2, 0.9
GF_COL = 4.5   # colonial ground storey on Delta Road (agent, 2026-11-19); shophouse/modern ground stays 4.0
WALL_T = 0.3
# Decay levels (agent, 2026-11-19): "worn" is the Delta Road default, "light" only next to the Delta Face Hotel.
# A level is a material swap (MAT_FrontageTrim_A / MAT_FrontageTrim_A_Light, same UVs) plus a variant rule: the
# decay variants below (spalls, hanging shutter, broken coping) are worn-only, so a light zone never picks them.
WORN_ONLY = ("KIT_Upper_Colonial_D", "KIT_Upper_Shophouse_D", "KIT_WallPlaster_Ground_D", "KIT_WallPlaster_Upper_D",
             "KIT_WallPlaster_GroundColonial_D", "KIT_Parapet_Cornice_D")

PAINT = {  # sRGB multipliers per role (walls: Art Bible lime-wash cream, lime-wash yellow, pale grey, faded mint) (street kit families: gf_21, gf_24, gf_25; Art Bible core palette)
    "A": {"WALL": "#EFE3C8", "ACCENT": "#F7F5EE", "TIMBER": "#2C4636", "BOARD": "#E8B931"},
    "B": {"WALL": "#EDDDA6", "ACCENT": "#FAF8F2", "TIMBER": "#563B2A", "BOARD": "#B8282E"},
    "C": {"WALL": "#DEDDD8", "ACCENT": "#EFE6D2", "TIMBER": "#3E5A6E", "BOARD": "#2D5E95"},
    "D": {"WALL": "#CFE0D2", "ACCENT": "#F4F1E8", "TIMBER": "#2C4636", "BOARD": "#2F6B48"},
}
COMMON = {"METAL": "#8C918F", "NEUTRAL": "#FFFFFF", "GREY": "#9C978E",
          "TILE": "#9A5640"}  # weathered Calicut clay tile (gf_ refs of the Old Hospital and lane-house roofs)
CANVAS = {"red": "#B23A33", "green": "#2F6B48", "blue": "#2D5E95", "cream": "#EFE7D2", "orange": "#D9822E"}


def _wall(t, h, x1=W, p=None):
    """Wall body on a 1 m grid (vertex AO and paint gradients need the vertices); LOD1 one box."""
    grid = (int(x1) + 1, 2, int(h) + 1)
    if p is not None:
        grid = tuple(t.switch(p.LOD, g, 2, "INT") for g in grid)
    return tag(t, t.cube(0, x1, 0, WALL_T, 0, h, grid), "WALL", "WALL", 0.0)


def _string(t, z, x1=W, big=False, p=None):
    """String course / cornice: stacked projecting bands (bevelled on LOD0 they read as a moulding); LOD1 keeps
    the deepest band and the top one, so the silhouette and the shadow line survive."""
    steps = ([(-0.06, 0.0, 0.06), (-0.12, 0.06, 0.12), (-0.08, 0.12, 0.16)] if not big else
             [(-0.08, 0.0, 0.08), (-0.16, 0.08, 0.16), (-0.24, 0.16, 0.24), (-0.3, 0.24, 0.3), (-0.2, 0.3, 0.36)])
    full = t.join(*[t.cube(0, x1, y, 0.01, z + a, z + b) for y, a, b in steps])
    if p is None:
        return tag(t, full, "FRAME", "ACCENT")
    lo = (-0.12, 0.0, 0.16) if not big else (-0.24, 0.0, 0.36)
    simple = t.cube(0, x1, lo[0], 0.01, z + lo[1], z + lo[2])
    return tag(t, t.switch(p.LOD, full, simple), "FRAME", "ACCENT")


def _plinth(t, x1=W, h=0.35):
    return tag(t, t.cube(0, x1, -0.035, 0.01, 0, h), "PLINTH", "GREY")


def _openings(t, p, ops):
    """Cut every opening into the wall and add its parts."""
    cut = [t.use(G["PI_OpeningCutter"], **{k: o[k] for k in ("X", "Width", "Sill", "Height", "Depth", "Arched")},
                 LOD=p.LOD) for o in ops]
    parts = [t.use(G["PI_Opening"], **o, LOD=p.LOD) for o in ops]
    return cut, parts


def _op(x, w, sill, h, d=0.22, arched=False, s=0.12, ledge=True, hood=0, glazing=1, shutters=0, grille=False):
    return {"X": x, "Width": w, "Sill": sill, "Height": h, "Depth": d, "Arched": arched, "Surround": s,
            "Ledge": ledge, "Hood": hood, "Glazing": glazing, "Shutters": shutters, "Grille": grille}


def _spalls(t, p, items):
    """Spall cutters for the wall boolean (PI_Spall entries of an extras list)."""
    return [c for kind, vals in items if kind == "PI_Spall" for c in spall_cut(t, p, **vals)]


def spall_cut(t, p, **vals):
    """Both lobes of a spall as separate closed cutters (parts._spall)."""
    return [t.use(G["PI_Spall"], **vals, LOD=p.LOD, Part=k) for k in (0, 1)]


def _extra(t, p, items):
    out = []
    for kind, vals in items:
        if kind == "PI_Spall":
            continue                      # cut into the wall by the piece (see _spalls)
        if kind == "PI_Sign":
            out.append(t.use(G[kind], **vals))
        else:
            out.append(t.use(G[kind], **vals, LOD=p.LOD))
    return out


# --- upper storeys (3.0 x 3.2) ---------------------------------------------------------------------------------
UPPER = {
    "Colonial": {
        "A": dict(ops=[_op(0.9, 1.2, 0.75, 2.05, arched=True, hood=1, shutters=1)]),
        "B": dict(ops=[_op(0.35, 0.9, 0.85, 1.75, s=0.1, hood=3, shutters=2),
                       _op(1.75, 0.9, 0.85, 1.75, s=0.1, hood=3, shutters=2)]),
        "C": dict(ops=[_op(0.85, 1.3, 0.16, 2.55, arched=True, s=0.14, ledge=False, hood=1, glazing=3)],
                  extra=[("PI_Balcony", dict(X0=0.55, X1=2.45, Z=0.16, Reach=0.38))]),
        "D": dict(ops=[_op(0.9, 1.2, 0.75, 2.05, arched=True, hood=0, shutters=3)],
                  extra=[("PI_Pipe", dict(X=2.8, Z0=0.0, Z1=3.1)),
                         ("PI_Spall", dict(X=0.45, Z=0.55, W=0.55, H=0.42))]),
    },
    "Shophouse": {
        "A": dict(ops=[_op(0.8, 1.4, 0.9, 1.5, s=0.08, hood=2)]),
        "B": dict(ops=[_op(0.9, 1.2, 0.16, 2.3, s=0.08, ledge=False, hood=2, glazing=3)],
                  extra=[("PI_Balcony", dict(X0=0.12, X1=2.88, Z=0.16, Reach=0.9))]),
        "C": dict(ops=[_op(0.3, 1.0, 0.95, 1.3, s=0.07), _op(1.7, 1.0, 0.95, 1.3, s=0.07)], band=2.42,
                  extra=[("PI_AC", dict(X=0.4, Z=0.72)), ("PI_Pipe", dict(X=2.86, Z0=0.0, Z1=3.2))]),
        "D": dict(ops=[_op(0.7, 1.6, 0.9, 1.4, s=0.06, grille=True)],
                  extra=[("PI_Wiring", dict(X=2.5, Z=0.5)), ("PI_Spall", dict(X=0.4, Z=2.5, W=0.5, H=0.36))]),
    },
    "Modern": {
        "A": dict(ops=[_op(0.25, 2.5, 0.9, 1.25, s=0.0, glazing=2, ledge=False)], box=True),
        "B": dict(ops=[_op(0.25, 2.5, 0.9, 1.25, s=0.0, glazing=2)],
                  extra=[("PI_AC", dict(X=0.35, Z=0.72)), ("PI_AC", dict(X=1.85, Z=0.72))]),
        "C": dict(ops=[_op(0.5, 2.0, 0.9, 1.4, s=0.0, glazing=2, grille=True)], fins=True),
        "D": dict(ops=[_op(0.5, 2.0, 0.9, 1.3, s=0.05, glazing=2, hood=2)],
                  extra=[("PI_AC", dict(X=2.05, Z=1.9))]),
    },
}


def _upper(spec):
    def body(t, p):
        cut, parts = _openings(t, p, spec["ops"])
        wall = t.boolean(_wall(t, UF, p=p), cut + _spalls(t, p, spec.get("extra", [])))
        out = [wall, _string(t, UF - 0.16, p=p), *parts, *_extra(t, p, spec.get("extra", []))]
        if spec.get("box"):   # projecting concrete frame box round the strip window
            ring = t.boolean(t.cube(0.1, 2.9, -0.32, 0.02, 0.72, 2.32), [t.cube(0.25, 2.75, -0.5, 0.1, 0.9, 2.15)])
            out.append(tag(t, ring, "CONCRETE", "WALL"))
        if spec.get("band"):   # continuous concrete sunshade (chajja) over both windows
            z = spec["band"]
            out.append(tag(t, t.join(t.cube(0.02, 2.98, -0.55, 0.01, z, z + 0.08),
                                     t.cube(0.02, 2.98, -0.55, -0.49, z - 0.06, z + 0.08)), "CONCRETE", "WALL"))
        if spec.get("fins"):
            out.append(tag(t, t.join(t.cube(0.08, 0.24, -0.45, 0.01, 0, UF - 0.16),
                                     t.cube(2.76, 2.92, -0.45, 0.01, 0, UF - 0.16)), "CONCRETE", "WALL"))
        return t.join(*out)
    return body


# --- ground bays (3.0 x 4.0) -----------------------------------------------------------------------------------
SHOP_CUT = dict(X=0.3, Width=2.4, Sill=0.0, Height=2.9, Depth=0.26, Arched=False)


def _shopframe(t, p, items, cut=(SHOP_CUT,), fascia=True):
    cuts = [t.use(G["PI_OpeningCutter"], **c, LOD=p.LOD) for c in cut]
    wall = t.boolean(_wall(t, GF, p=p), cuts)
    out = [wall, _plinth(t), *_extra(t, p, items)]
    if fascia:
        out += [tag(t, t.cube(0, W, -0.07, 0.01, 2.9, 3.62), "WALL", "WALL", 0.0),
                tag(t, t.join(t.cube(0, 0.3, -0.06, 0.01, 2.72, 2.9), t.cube(2.7, 3.0, -0.06, 0.01, 2.72, 2.9)),
                    "FRAME", "ACCENT"),
                _string(t, GF - 0.38, big=True, p=p)]
    return out


SHOP_GLASS = _op(0.3, 2.4, 0.32, 2.2, d=0.26, s=0.0, ledge=False, glazing=2)
SHOPFRONT = {
    "Shutter": {
        "A": [("PI_Roller", dict(Curtain=1.2)), ("PI_Opening", SHOP_GLASS),
              ("PI_Awning", dict(Kind=1, Stripes=6, ZTop=2.6, Reach=1.0, Drop=0.45)),
              ("PI_Sign", dict(X0=0.2, X1=2.8, Z0=2.98, Z1=3.55))],
        "B": [("PI_Roller", dict(Curtain=2.5)), ("PI_Awning", dict(Kind=2, ZTop=2.86, Reach=0.9, Drop=0.0)),
              ("PI_Pipe", dict(X=2.88, Z0=0.0, Z1=3.6)), ("PI_Sign", dict(X0=0.25, X1=2.6, Z0=3.0, Z1=3.55))],
        "C": [("PI_Roller", dict(Curtain=0.2)), ("PI_Opening", _op(0.3, 2.4, 0.5, 1.95, d=0.26, s=0.0, ledge=False,
                                                                        glazing=2)),
              ("PI_Awning", dict(Kind=3, ZTop=2.62, Reach=1.25, Drop=0.32)), ("PI_AC", dict(X=1.98, Z=3.03)),
              ("PI_Sign", dict(X0=0.15, X1=1.9, Z0=2.98, Z1=3.55))],
        "D": [("PI_Roller", dict(Curtain=0.0)), ("PI_Opening", _op(0.3, 2.4, 0.0, 2.5, d=0.26, s=0.0, ledge=False,
                                                                        glazing=0, grille=True)),
              ("PI_Awning", dict(Kind=1, Stripes=1, ZTop=2.6, Reach=0.85, Drop=0.4)),
              ("PI_Wiring", dict(X=0.0, Z=1.2)), ("PI_Sign", dict(X0=0.35, X1=2.65, Z0=3.0, Z1=3.5))],
    },
    "Glazed": {
        "A": [("PI_Opening", _op(0.3, 2.4, 0.45, 2.3, d=0.26, s=0.0, ledge=False, glazing=2)),
              ("PI_Awning", dict(Kind=1, Stripes=6, ZTop=2.85, Reach=1.0, Drop=0.5)),
              ("PI_Sign", dict(X0=0.2, X1=2.8, Z0=3.0, Z1=3.55))],
        "B": "side_door",
        "C": [("PI_Opening", _op(0.3, 2.4, 0.5, 2.25, d=0.26, s=0.0, ledge=False, glazing=2)),
              ("PI_Awning", dict(Kind=2, ZTop=2.86, Reach=0.75, Drop=0.0)), ("PI_Pipe", dict(X=0.12, Z0=0.0, Z1=3.6)),
              ("PI_AC", dict(X=1.95, Z=3.03)), ("PI_Sign", dict(X0=0.3, X1=1.85, Z0=3.0, Z1=3.55))],
    },
}


def _shop(fam, v):
    items = SHOPFRONT[fam][v]

    def body(t, p):
        if items == "side_door":
            cuts = (dict(X=0.3, Width=1.45, Sill=0.5, Height=2.25, Depth=0.26, Arched=False),
                    dict(X=1.95, Width=0.78, Sill=0.0, Height=2.75, Depth=0.26, Arched=False))
            its = [("PI_Opening", _op(0.3, 1.45, 0.5, 2.25, d=0.26, s=0.0, ledge=False, glazing=2)),
                   ("PI_Opening", _op(1.95, 0.78, 0.0, 2.75, d=0.26, s=0.0, ledge=False, glazing=3)),
                   ("PI_Sign", dict(X0=0.15, X1=2.85, Z0=2.98, Z1=3.6)), ("PI_Pipe", dict(X=2.9, Z0=0.0, Z1=3.6))]
            return t.join(*_shopframe(t, p, its, cuts))
        return t.join(*_shopframe(t, p, items))
    return body


ARCHED = {   # colonial ground storey, GF_COL (gf_21: arched doors 3.3-3.5 m with fanlight under a 4.5-5 m storey)
    "A": dict(op=_op(0.65, 1.7, 0.0, 3.45, d=0.3, arched=True, s=0.16, ledge=False, hood=1, glazing=3), items=[]),
    "B": dict(op=_op(0.55, 1.9, 0.62, 2.85, d=0.3, arched=True, s=0.14, hood=1, glazing=1),
              items=[("PI_Awning", dict(X0=0.5, X1=2.5, Kind=1, Stripes=1, ZTop=2.55, Reach=0.9, Drop=0.55))]),
}


def _arched(v):
    spec = ARCHED[v]

    def body(t, p):
        cut, parts = _openings(t, p, [spec["op"]])
        wall = t.boolean(_wall(t, GF_COL, p=p), cut)
        return t.join(wall, _plinth(t), _string(t, GF_COL - 0.36, big=True, p=p), *parts,
                      *_extra(t, p, spec["items"]))
    return body


def _corner(h):
    """Rusticated corner pier (gf_25): banded blocks with 20 mm joints round a core, plinth and cap. The blocks
    are bevelled on their street edges only (the joint shadow carries the rustication, 500-tri cap)."""
    n = int(round((h - 0.37 - 0.38) / 0.42))
    pitch = (h - 0.37 - 0.38) / n

    def body(t, p):
        lod0 = t.bnot(p.LOD)
        ins = t.switch(p.LOD, 0.03, 0.0, "FLOAT")   # LOD1: one block, no bands (20 mm joints vanish at 35 m)
        core = tag(t, t.cube(ins, 0.9 - ins, -0.06 + ins, 0.9 - ins, 0, h), "WALL", "WALL", 0.0)
        block = t.cube(0.0, 0.9, -0.06, 0.9, 0.0, pitch - 0.02)
        bands = t.when(lod0, tag(t, t.array(block, n, (0, 0, pitch), (0, 0, 0.37)), "WALL", "WALL"))
        cap = tag(t, t.join(t.when(t.bnot(p.LOD), t.cube(-0.04, 0.94, -0.12, 0.94, h - 0.38, h - 0.22)),
                            t.cube(-0.08, 0.98, -0.2, 0.98, h - 0.22, h - 0.08),
                            t.cube(-0.04, 0.94, -0.12, 0.94, h - 0.08, h)), "FRAME", "ACCENT", 0.0)
        base = tag(t, t.cube(-0.05, 0.95, -0.11, 0.95, 0, 0.37), "PLINTH", "GREY", 0.0)
        return t.join(core, bands, cap, base)
    return body


# --- plain walls and parapets ------------------------------------------------------------------------------------
def _plaster(h, v):
    def body(t, p):
        spall = spall_cut(t, p, X=0.8, Z=0.45, W=0.7, H=0.5) if v == "D" else []   # one patch, wall foot
        out = [t.boolean(_wall(t, h, p=p), spall) if spall else _wall(t, h, p=p), _string(t, h - 0.16, p=p)]
        if h >= GF:
            out.append(_plinth(t))
        top = h - 0.16
        if v == "B":   # pilaster pair with base and capital
            for x in (0.2, 2.45):
                out.append(tag(t, t.join(t.cube(x, x + 0.35, -0.08, 0.01, 0, top),
                                         t.cube(x - 0.04, x + 0.39, -0.12, 0.01, 0, 0.3 if h >= GF else 0.12),
                                         t.cube(x - 0.04, x + 0.39, -0.13, 0.01, top - 0.22, top)), "FRAME", "ACCENT"))
        if v == "C":   # downpipe and a vent grille
            out += _extra(t, p, [("PI_Pipe", dict(X=1.5, Z0=0.0, Z1=h))])
            out.append(tag(t, t.cube(0.6, 0.9, -0.03, 0.01, h - 0.9, h - 0.7), "METAL", "METAL"))
        if v == "D":   # decay: spalls and wiring
            out += _extra(t, p, [("PI_Wiring", dict(X=2.5, Z=0.9 if h >= GF else 0.3))])
        return t.join(*out)
    return body


def _parapet(v):
    def body(t, p):
        if v == "A":   # moulded cornice, parapet wall, coping
            out = [_string(t, 0.0, big=True, p=p), tag(t, t.cube(0, W, 0, 0.25, 0.36, 0.84), "WALL", "WALL", 0.0),
                   tag(t, t.cube(0, W, -0.05, 0.3, 0.84, 0.9), "CONCRETE", "ACCENT")]
        elif v == "B":   # deco parapet: wall-coloured stepped pediment (one solid with the parapet), each step under
            # its own thin coping, a sunk name panel and two end piers (the old white stacked boxes read as a crate)
            body = t.join(t.cube(0, W, 0, 0.25, 0.16, 0.84), t.cube(0.7, 2.3, 0, 0.25, 0.84, 1.08),
                          t.cube(1.05, 1.95, 0, 0.25, 1.08, 1.3))
            panel = t.cube(1.0, 2.0, -0.1, 0.03, 0.42, 0.98)                     # sunk 30 mm date plaque
            wall = t.boolean(tag(t, body, "WALL", "WALL", 0.0), [tag(t, panel, "REVEAL", "WALL", 0.0)])
            # raised moulded border round the plaque and a roundel on the top step: a pediment, not a signboard
            border = t.join(t.cube(0.92, 2.08, -0.035, 0.0, 0.34, 0.42), t.cube(0.92, 2.08, -0.035, 0.0, 0.98, 1.06),
                            t.cube(0.92, 1.0, -0.035, 0.0, 0.42, 0.98), t.cube(2.0, 2.08, -0.035, 0.0, 0.42, 0.98),
                            t.cyl(0.085, 0.04, (1.5, -0.02, 1.19), "y", 10))
            cope = t.join(t.cube(0, 0.7, -0.04, 0.29, 0.84, 0.9), t.cube(2.3, W, -0.04, 0.29, 0.84, 0.9),
                          t.cube(0.66, 1.05, -0.04, 0.29, 1.08, 1.14), t.cube(1.95, 2.34, -0.04, 0.29, 1.08, 1.14),
                          t.cube(1.01, 1.99, -0.04, 0.29, 1.3, 1.36))
            piers = t.join(t.cube(0.0, 0.22, -0.05, 0.25, 0.16, 0.96), t.cube(2.78, W, -0.05, 0.25, 0.16, 0.96))
            out = [_string(t, 0.0, p=p), wall, tag(t, cope, "CONCRETE", "ACCENT"), tag(t, piers, "FRAME", "ACCENT"),
                   tag(t, border, "FRAME", "ACCENT")]
        elif v == "C":   # balustrade between pedestals
            bal = t.join(t.cyl(0.045, 0.3, (0, 0.1, 0.6), "z", 6), t.cube(-0.06, 0.06, 0.04, 0.16, 0.45, 0.5),
                         t.cube(-0.05, 0.05, 0.05, 0.15, 0.72, 0.77))
            balusters = tag(t, t.array(bal, 9, (0.24, 0, 0), (0.54, 0, 0)), "FRAME", "ACCENT", 0.0)
            panel = tag(t, t.cube(0.3, 2.7, 0.08, 0.12, 0.45, 0.77), "FRAME", "ACCENT", 0.0)
            out = [_string(t, 0.0, big=True, p=p),
                   tag(t, t.join(t.cube(0, 0.3, -0.04, 0.26, 0.36, 0.9), t.cube(2.7, 3.0, -0.04, 0.26, 0.36, 0.9),
                                 t.cube(0.3, 2.7, -0.0, 0.22, 0.36, 0.45), t.cube(0.3, 2.7, -0.03, 0.24, 0.77, 0.86)),
                       "CONCRETE", "ACCENT"),
                   t.switch(p.LOD, balusters, panel)]
        else:   # plain parapet with a drip edge, broken coping and rebar stubs (unfinished upper floor)
            out = [tag(t, t.cube(0, W, -0.12, 0.01, 0.0, 0.1), "CONCRETE", "WALL"),
                   t.boolean(tag(t, t.cube(0, W, 0, 0.22, 0.1, 0.86), "WALL", "WALL", 0.0),
                             spall_cut(t, p, X=2.4, Z=0.5, W=0.5, H=0.3)),
                   tag(t, t.cube(0, 2.1, -0.03, 0.25, 0.86, 0.92), "CONCRETE", "WALL"),
                   tag(t, t.join(*[t.cyl(0.008, 0.45, (x, 0.11, 1.08), "z", 4) for x in (0.4, 1.3, 2.25, 2.8)]),
                       "METAL", "GREY", 0.0)]
        return t.join(*out)
    return body


def catalogue() -> list[tuple[str, float, float, str, callable, list]]:
    """(name, width, height, variant letter, body fn, refs) for every piece."""
    out = []
    for fam, vs in UPPER.items():
        for v, spec in vs.items():
            out.append((f"KIT_Upper_{fam}_{v}", W, UF, v, _upper(spec), ["gf_21", "gf_24", "sv_04", "style frame"]))
    for fam, vs in SHOPFRONT.items():
        for v in vs:
            out.append((f"KIT_Shopfront_{fam}_{v}", W, GF, v, _shop(fam, v), ["style frame", "gf_24"]))
    for v in ARCHED:
        out.append((f"KIT_Shopfront_Arched_{v}", W, GF_COL, v, _arched(v), ["gf_21", "gf_24"]))
    out.append(("KIT_Shopfront_Corner_A", 0.9, GF, "A", _corner(GF), ["gf_25"]))
    out.append(("KIT_Shopfront_CornerColonial_A", 0.9, GF_COL, "A", _corner(GF_COL), ["gf_25"]))
    for h, nm in ((GF, "Ground"), (GF_COL, "GroundColonial"), (UF, "Upper")):
        for v in "ABCD":
            out.append((f"KIT_WallPlaster_{nm}_{v}", W, h, v, _plaster(h, v), ["gf_24", "sv_04"]))
    for v in "ABCD":
        out.append((f"KIT_Parapet_Cornice_{v}", W, PAR, v, _parapet(v), ["sv_04", "gf_25"]))
    import arcade   # walk-under colonial arcade bays (P186)
    out += arcade.catalogue()
    return out


def build_assemblies() -> dict:
    """ASM_<piece> groups with one LOD input each."""
    return {name: (group(f"ASM_{name}", [("LOD", bool, False)], fn), w, h, v, refs)
            for name, w, h, v, fn, refs in catalogue()}
