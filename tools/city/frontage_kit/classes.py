"""Building classes (P143): the CLS_* rows of docs/inventory/buildings_heroes.csv as data-driven class rules.

One builder, `block`, turns a class rule (bays, storeys, ground family, upper window family, add-ons, roof) into a
building from the P96 parts (PI_Opening + its cutter, PI_Roller, PI_Awning, PI_Sign, PI_AC, PI_Wiring, PI_Balcony)
and the P143 elements (shop glass, doors, gates, downpipes), on the one frontage trim sheet. Axes as the kit: x
along the street frontage from the left corner, street on -y, front wall face y = 0, depth +y, z up from the
pavement. Walls are per storey and store the storey base and height (zb_cm, sh_cm), so each storey maps onto the
4 m wall row by itself (kitbuild). Flat decks and soffits are strips under 4 m so the trim never squashes them.
LOD1 = the same rule with the parts' LOD switch (fewer bars, no small add-ons); LOD2 = mass, roof and window cards.
Numbers: buildings_heroes.csv descriptions and budgets; colonial ground storey 4.5 m (decided for Delta Road).
"""
from __future__ import annotations

import math

import pieces
from elements import awning, downpipe, glazed_door, grilled_gate, shop_glass, threshold, _use
from parts import G, tag
import roofs
from shopfront import roller_shutter

TH = 0.3          # wall thickness (the PI_OpeningCutter reaches through it)


def _st(t, geo, z0, h):
    geo = t.store(geo, "zb_cm", int(round(z0 * 100)), "INT", "FACE")
    return t.store(geo, "sh_cm", int(round(h * 100)), "INT", "FACE")


def wall(t, x0, x1, y0, y1, z0, z1, zb=None, h=None, role="WALL"):
    return _st(t, tag(t, t.cube(x0, x1, y0, y1, z0, z1), "WALL", role, 1.0), z0 if zb is None else zb, (z1 - z0) if h is None else h)


def strips(t, x0, x1, y0, y1, z0, z1, trim="WALL", role="WALL", step=3.6):
    """A deck as strips under the trim row height (each strip its own UV island)."""
    n = max(1, int(math.ceil((y1 - y0) / step)))
    dy = (y1 - y0) / n
    return tag(t, t.join(*[t.cube(x0, x1, y0 + i * dy, y0 + (i + 1) * dy, z0, z1) for i in range(n)]), trim, role, 0.0)


def shell(t, W, D, z0, h, front=True):
    """Side and back walls of one storey (hollow box; the front comes from the facade rule)."""
    parts = [wall(t, 0, TH, TH, D, z0, z0 + h), wall(t, W - TH, W, TH, D, z0, z0 + h), wall(t, TH, W - TH, D - TH, D, z0, z0 + h)]
    if front:
        parts.append(wall(t, 0, W, 0, TH, z0, z0 + h))
    return t.join(*parts)


def punched(t, p, W, bw, z0, h, win, skip=()):
    """Front wall of one storey: one panel, one opening per bay (PI_OpeningCutter), cut in one boolean (no bay seams)."""
    ops = []
    for j in range(int(round(W / bw))):
        if j in skip:
            continue
        ow = win["w"]
        ops.append(pieces._op(j * bw + (bw - ow) / 2, ow, z0 + win["sill"], win["h"], d=0.22, arched=win.get("arched", False),
                              s=win.get("s", 0.12), ledge=win.get("ledge", True), hood=win.get("hood", 0),
                              glazing=win.get("glazing", 1), shutters=win.get("shutters", 0), grille=win.get("grille", False)))
    panel = wall(t, 0, W, 0, TH, z0, z0 + h)
    if not ops:
        return panel
    cut, parts = pieces._openings(t, p, ops)
    return t.join(t.boolean(panel, cut), *parts)


def cards(t, W, bw, z0, win):
    """LOD2: dark window cards proud of a plain front."""
    ow = min(win["w"], 1.15)
    return tag(t, t.join(*[t.cube(j * bw + (bw - ow) / 2, j * bw + (bw + ow) / 2, -0.02, 0.0, z0 + win["sill"], z0 + win["sill"] + win["h"])
                          for j in range(int(round(W / bw)))]), "GLASS", "NEUTRAL", 0.0)


# --- ground storeys ---------------------------------------------------------------------------------------------
def ground(t, p, c):
    W, bw, g = c["W"], c["bw"], c["ground"]
    h, kind, n = g["h"], g["kind"], int(round(c["W"] / c["bw"]))
    out = []
    if kind in ("arch", "solid", "punched"):
        win = g.get("win") or {"w": 1.7, "sill": 0.0, "h": h - 0.9, "arched": True, "s": 0.18, "ledge": False, "glazing": 1}
        out.append(punched(t, p, W, bw, 0.0, h, win, skip=g.get("skip", ())))
        if kind == "arch":   # plaster plinth band (gf_25)
            out.append(tag(t, t.cube(0, W, -0.06, 0.0, 0.0, 0.45), "PLINTH", "WALL", 1.0))
    elif kind in ("shop", "garage", "parts"):
        zt = g.get("zt", 3.0)
        cur = {"shop": 1.2, "garage": 0.15, "parts": 0.15}[kind]
        for j in range(n):
            x0 = j * bw
            out += [wall(t, x0, x0 + 0.3, 0, TH, 0, h, 0, h), wall(t, x0 + bw - 0.3, x0 + bw, 0, TH, 0, h, 0, h),
                    wall(t, x0 + 0.3, x0 + bw - 0.3, 0, TH, zt, h, 0, h),
                    t.move(roller_shutter(t, p, x1=bw - 0.6, zt=zt, curtain=cur if j % 3 else cur * 0.5 + 0.1,
                                          role=("METAL", "BOARD", "TIMBER")[j % 3], locks="open", handles=1), (x0 + 0.3, 0, 0)),
                    tag(t, t.cube(x0 + 0.3, x0 + bw - 0.3, 1.2, 1.22, 0.0, 1.2), "GLASS", "NEUTRAL", 0.0),
                    tag(t, t.cube(x0 + 0.3, x0 + bw - 0.3, 1.2, 1.22, 1.2, zt), "GLASS", "NEUTRAL", 0.0)]
            if g.get("awning") and j % 2 == 0:
                prof = ("dutch", "box", "lean")[(j // 2) % 3]   # mixed profiles along a row (style frame dff6fe56)
                out.append(t.move(awning(1, 6, 0.7, 0.75 if prof != "dutch" else 0.65, 0.45 if prof != "dutch" else 0.7,
                                         x1=bw - 0.6, profile=prof, valance="scallop", xw=x0 + 0.3)(t, p), (x0 + 0.3, 0, zt + 0.05)))
        out.append(t.use(G["PI_Sign"], X0=0.15, X1=W - 0.15, Z0=zt + 0.1, Z1=min(h - 0.1, zt + 0.8)))
        if kind == "parts":   # parts racks seen through the open shutters
            racks = [t.cube(j * bw + 0.5, j * bw + bw - 0.5, 0.8, 1.15, z, z + 0.04) for j in range(n) for z in (0.6, 1.2, 1.8)]
            out.append(t.when(t.bnot(p.LOD), tag(t, t.join(*racks), "METAL", "GREY", 0.0)))
        if kind == "garage":  # oil-stained concrete apron
            out.append(strips(t, 0, W, -3.0, 0.0, 0.0, 0.03, "CONCRETE", "GREY", 0.95))
    elif kind in ("glass", "lobby"):
        for j in range(n):
            x0 = j * bw
            out += [wall(t, x0, x0 + (bw - 2.4) / 2, 0, TH, 0, h, 0, h), wall(t, x0 + (bw + 2.4) / 2, x0 + bw, 0, TH, 0, h, 0, h),
                    wall(t, x0 + (bw - 2.4) / 2, x0 + (bw + 2.4) / 2, 0, TH, 2.5, h, 0, h),
                    wall(t, x0 + (bw - 2.4) / 2, x0 + (bw + 2.4) / 2, 0, TH, 0, 0.3, 0, h)]
            body = glazed_door if (kind == "lobby" and j == n // 2) or (kind == "glass" and j == 0) else shop_glass
            zz = 0.0 if body is glazed_door else 0.3
            out.append(t.move(body(t, p), (x0 + (bw - 2.4) / 2, 0.02, zz)))
        out.append(t.use(G["PI_Sign"], X0=0.15, X1=W - 0.15, Z0=2.75, Z1=min(h - 0.1, 3.45)))
        out.append(t.move(threshold(t, p), (((n // 2) * bw) + (bw - 2.4) / 2 if kind == "lobby" else (bw - 2.4) / 2, 0, 0)))
    elif kind == "arcade":
        a = g.get("deep", 3.0)
        win = {"w": 1.6, "sill": 0.0, "h": min(3.2, h - 0.8), "arched": True, "s": 0.12, "ledge": False}
        out.append(t.move(punched(t, p, W, bw, 0.0, h, win), (0, a, 0)))
        cols = [_st(t, tag(t, t.cyl(0.24, h - 0.6, (j * bw, TH / 2, (h - 0.6) / 2), "z", 12), "WALL", "WALL", 0.0), 0, h)
                for j in range(1, int(round(W / bw)))]
        cols += [wall(t, 0, 0.5, 0, TH, 0, h - 0.6, 0, h), wall(t, W - 0.5, W, 0, TH, 0, h - 0.6, 0, h)]
        beam = wall(t, 0, W, 0, TH, h - 0.6, h, 0, h)
        soffit = strips(t, 0, W, TH, a, h - 0.25, h - 0.2)
        floor = strips(t, 0, W, -0.4, a, 0.0, 0.15, "CONCRETE", "GREY", 0.95)
        out += [t.join(*cols), beam, soffit, floor]
    return t.join(*out)


# --- the class block ---------------------------------------------------------------------------------------------
def block(c, simple=False):
    def body(t, p):
        W, D, bw = c["W"], c["D"], c["bw"]
        gh = c["ground"]["h"]
        ups = c.get("uppers", [])
        H = gh + sum(ups)
        win = c.get("win", {"w": 1.2, "sill": 0.9, "h": 1.6})
        out = [shell(t, W, D, 0.0, gh, front=False)]
        z = gh
        for i, h in enumerate(ups):
            out.append(shell(t, W, D, z, h, front=simple))
            if simple:
                out.append(cards(t, W, bw, z, win))
            elif c.get("bands"):
                out.append(bands(t, p, W, z, h))
            else:
                out.append(punched(t, p, W, bw, z, h, win, skip=c.get("skip_up", ())))
                if c.get("sunshade"):
                    ow = win["w"]
                    zz = z + win["sill"] + win["h"] + 0.15
                    out.append(tag(t, t.join(*[t.cube(j * bw + (bw - ow) / 2 - 0.2, j * bw + (bw + ow) / 2 + 0.2, -0.6, 0.0, zz, zz + 0.09)
                                               for j in range(int(round(W / bw)))]), "CONCRETE", "WALL", 1.0))
                for j in c.get("balcony", {}).get(i, ()):
                    out.append(_use(t, p, "PI_Balcony", X0=j * bw + 0.15, X1=(j + 1) * bw - 0.15, Z=z, Reach=c.get("reach", 0.9)))
                for j in c.get("ac", {}).get(i, ()):
                    out.append(t.when(t.bnot(p.LOD), _use(t, p, "PI_AC", X=j * bw + 0.2, Z=z + 0.4)))
                if c.get("string") and i < len(ups) - 1:
                    out.append(t.move(pieces._string(t, 0.0, x1=W, big=False, p=p), (0, 0, z + h - 0.16)))
            z += h
        if simple:
            out.append(wall(t, 0, W, 0, TH, 0, gh, 0, gh))
            out.append(cards(t, W, bw, 0.0, {"w": 2.4, "sill": 0.3, "h": min(2.2, gh - 0.6)}))
        else:
            out.append(ground(t, p, c))
            for x in c.get("pipes", ()):
                out.append(t.move(downpipe(t, p, z1=H - 0.1), (x, 0, 0)))
            if c.get("wiring") is not None:
                out.append(_use(t, p, "PI_Wiring", X=c["wiring"], Z=gh + 0.3))
            if c.get("pilasters"):
                for j in range(int(round(W / bw)) + 1):
                    x = min(max(j * bw - 0.2, 0.0), W - 0.4)
                    for zb, h in [(gh, hh) for hh in ups[:1]] + [(gh + sum(ups[:k]), ups[k]) for k in range(1, len(ups))]:
                        out.append(wall(t, x, x + 0.4, -0.08, 0.0, zb, zb + h, zb, h, role="ACCENT"))
        out.append(roof(t, p, c, H, simple))
        for fn in c.get("extras", ()):
            out.append(fn(t, p, c, simple))
        return t.join(*out)
    return body


def bands(t, p, W, z, h):
    """Modernist slab storey: spandrel, glass band in two lifts, mullions, solid-front balcony (Samudra-type)."""
    gz, gh = z + 0.9, (h - 1.05) / 2
    glass = tag(t, t.join(t.cube(0.3, W - 0.3, 0.2, 0.22, gz, gz + gh), t.cube(0.3, W - 0.3, 0.2, 0.22, gz + gh, gz + 2 * gh)), "GLASS", "NEUTRAL", 0.0)
    mull = tag(t, t.array(t.cube(-0.04, 0.04, 0.12, 0.2, gz, z + h - 0.15), int(W / 2.0), (2.0, 0, 0), (1.0, 0, 0)), "METAL", "GREY", 0.0)
    slab = strips(t, 0, W, -1.2, 0.0, z, z + 0.15, "CONCRETE", "WALL", 0.95)
    return t.join(wall(t, 0, W, 0, TH, z, gz, z, h), wall(t, 0, W, 0, TH, z + h - 0.15, z + h, z, h), glass,
                  t.when(t.bnot(p.LOD), mull), slab, wall(t, 0, W, -1.2, -1.08, z + 0.15, z + 1.0, z, h, role="ACCENT"))


def roof(t, p, c, H, simple):
    W, D, kind = c["W"], c["D"], c.get("roof", "parapet")
    deck = strips(t, 0, W, 0, D, H, H + 0.2)
    if kind == "gable":
        pitch = math.radians(c.get("pitch", 24))
        rise, ov = (D / 2) * math.tan(pitch), 0.5
        sl = (D / 2 + ov) / math.cos(pitch)
        ym, zm = (D / 2 - ov) / 2, H + (rise - ov * math.tan(pitch)) / 2 + 0.07
        # P148: clay tile courses, fascia, rafter tails and barge boards per slope (roofs.py), ridge cap over the apex
        side = roofs.slope(t, p, -0.4, W + 0.4, sl, pitch, ov / math.cos(pitch) + 0.35, simple)
        out = [t.move(side, (0, ym, zm), (pitch, 0, 0)),
               t.move(side, (W, D - ym, zm), (pitch, 0, math.pi)), roofs.ridge(t, W, D, H + rise + 0.07)]
        cut = [t.move(t.cube(-1, W + 1, -60, 60, 0, 60), (0, y, H), (sg * pitch, 0, 0)) for y, sg in ((0.0, 1), (D, -1))]
        gab = [t.boolean(wall(t, x, x + TH, 0.0, D, H, H + rise, H, 4.0), cut) for x in (0.0, W - TH)]
        return t.join(*out, *gab)
    out = [deck]
    if kind in ("parapet", "balustrade", "stubs", "tanks"):
        ph = 0.9 if kind != "balustrade" else 0.35
        out.append(wall(t, 0, W, 0, TH, H, H + ph, H, 1.0))
        out += [wall(t, 0, TH, TH, D, H, H + ph, H, 1.0), wall(t, W - TH, W, TH, D, H, H + ph, H, 1.0),
                wall(t, TH, W - TH, D - TH, D, H, H + ph, H, 1.0)]
        if c.get("cornice", kind == "balustrade") and not simple:
            out.append(t.move(pieces._string(t, 0.0, x1=W, big=True, p=p), (0, 0, H - 0.3)))
    if kind == "balustrade" and not simple:
        pitch_b = t.switch(p.LOD, 0.3, 0.6, "FLOAT")
        bal = t.array(t.cube(-0.06, 0.06, 0.06, 0.18, H + 0.35, H + 0.9), (W - 0.4) / pitch_b, t.vec(pitch_b, 0, 0), (0.3, 0, 0))
        rail = t.cube(0, W, 0.0, 0.25, H + 0.9, H + 1.02)
        out.append(tag(t, t.join(bal, rail), "FRAME", "ACCENT", 0.0))
    if kind in ("stubs", "tanks") and not simple:
        xs = [W * f for f in (0.2, 0.5, 0.8)]
        out.append(tag(t, t.join(*[t.cube(x - 0.15, x + 0.15, D * 0.6 - 0.15, D * 0.6 + 0.15, H + 0.2, H + 1.4) for x in xs]), "CONCRETE", "WALL", 1.0))
        if kind == "tanks":
            out.append(t.when(t.bnot(p.LOD), tag(t, t.join(*[t.cyl(0.55, 1.3, (x, D * 0.35, H + 0.85), "z", 10) for x in xs[:2]]), "METAL", "GREY", 0.0)))
    return t.join(*out)


# --- class-specific extras -------------------------------------------------------------------------------------
def fuel_canopy(t, p, c, simple):
    x0, x1, y0, y1, zt = 2.0, 16.0, -11.0, -2.0, 5.2
    out = [strips(t, x0, x1, y0, y1, zt - 0.08, zt, "WALL", "WALL"),
           tag(t, t.join(t.cube(x0, x1, y0, y0 + 0.08, zt - 0.7, zt + 0.1), t.cube(x0, x1, y1 - 0.08, y1, zt - 0.7, zt + 0.1),
                         t.cube(x0, x0 + 0.08, y0, y1, zt - 0.7, zt + 0.1), t.cube(x1 - 0.08, x1, y0, y1, zt - 0.7, zt + 0.1)), "PANEL", "ACCENT", 0.0)]
    for x in (5.5, 12.5):
        out.append(wall(t, x - 0.2, x + 0.2, -6.7, -6.3, 0.0, zt - 0.7, 0, 4.0, role="NEUTRAL"))
        isl = tag(t, t.cube(x - 2.2, x + 2.2, -7.1, -5.9, 0.0, 0.18), "CONCRETE", "GREY", 1.0)
        pumps = tag(t, t.join(*[t.cube(x + dx - 0.35, x + dx + 0.35, -6.85, -6.15, 0.18, 1.85) for dx in (-1.3, 1.3)]), "PANEL", "ACCENT", 0.0)
        out += [isl] + ([] if simple else [t.when(t.bnot(p.LOD), pumps)])
    board = t.join(wall(t, 17.0, 17.3, -11.5, -11.2, 0.0, 2.2, 0, 4.0), tag(t, t.cube(16.55, 17.75, -11.6, -11.1, 2.2, 4.6), "PANEL", "BOARD", 0.0))
    apron = strips(t, 0.0, c["W"], -12.0, 0.0, 0.0, 0.03, "CONCRETE", "GREY", 0.95)
    return t.join(*out, board, apron)


def compound_wall(t, p, c, simple):
    L, h = c.get("wall_len", 60.0), 2.4
    n = int(L / 3.0)
    panels = [wall(t, i * 3.0 + 0.2, (i + 1) * 3.0 - 0.2, -8.0, -7.75, 0.0, h, 0, 4.0) for i in range(n) if i != n // 2]
    piers = [wall(t, i * 3.0 - 0.2, i * 3.0 + 0.2, -8.05, -7.7, 0.0, h + 0.25, 0, 4.0) for i in range(n + 1)]
    cope = tag(t, t.cube(0.0, L, -8.08, -7.67, h, h + 0.08), "CONCRETE", "WALL", 1.0)
    gate = t.move(grilled_gate(t, p), ((n // 2) * 3.0 + 0.2, -8.0, 0.0))
    booth = t.join(shell(t, 2.4, 2.4, 0.0, 2.6), strips(t, -0.3, 2.7, -0.3, 2.7, 2.6, 2.75))
    return t.join(*panels, *piers, cope, gate, t.move(booth, ((n // 2) * 3.0 + 3.4, -7.5, 0.0)))


def low_wall_gate(t, p, c, simple):
    W = c["W"]
    wl = [wall(t, 0.0, W * 0.45, -3.0, -2.8, 0.0, 1.1, 0, 4.0), wall(t, W * 0.45 + 2.6, W, -3.0, -2.8, 0.0, 1.1, 0, 4.0)]
    gate = t.move(_use(t, p, "PI_Opening", X=0.0, Width=2.5, Sill=0.0, Height=1.3, Depth=0.06, Arched=False, Surround=0.0,
                       Ledge=False, Hood=0, Glazing=0, Shutters=0, Grille=True), (W * 0.45 + 0.05, -3.0, 0.0))
    return t.join(*wl, t.when(t.bnot(p.LOD), gate))


def portico(t, p, c, simple):
    """Columned portico with a pediment (neo-classical, no emblems)."""
    x0, x1, h = c["W"] / 2 - 9.0, c["W"] / 2 + 9.0, c["ground"]["h"] + c["uppers"][0]
    cols = [_st(t, tag(t, t.cyl(0.45, h - 1.2, (x0 + 0.6 + i * (x1 - x0 - 1.2) / 5, -3.6, 0.6 + (h - 1.2) / 2), "z", 16 if not simple else 8),
                    "WALL", "WALL", 0.0), 0.6, h - 1.2) for i in range(6)]
    plinths = tag(t, t.join(*[t.cube(x0 + i * (x1 - x0 - 1.2) / 5, x0 + 1.2 + i * (x1 - x0 - 1.2) / 5, -4.2, -3.0, 0.0, 0.6) for i in range(6)]), "PLINTH", "WALL", 1.0)
    ent = wall(t, x0 - 0.3, x1 + 0.3, -4.4, 0.0, h - 0.6, h + 0.6, h - 0.6, 1.2)
    soffit = strips(t, x0, x1, -4.2, 0.0, h - 0.62, h - 0.6)
    steps = strips(t, x0 - 1.0, x1 + 1.0, -6.0, -4.2, 0.0, 0.3, "CONCRETE", "WALL", 0.95)
    rise = 2.6
    ped = wall(t, x0 - 0.3, x1 + 0.3, -4.2, -3.7, h + 0.6, h + 0.6 + rise, h + 0.6, 4.0)
    a = math.atan2(rise, (x1 - x0) / 2 + 0.3)
    cut = [t.move(t.cube(0, 30, -10, 10, 0, 30), ((x0 + x1) / 2, 0, h + 0.6 + rise), (0, a, 0)),
           t.move(t.cube(-30, 0, -10, 10, 0, 30), ((x0 + x1) / 2, 0, h + 0.6 + rise), (0, -a, 0))]
    ped = t.boolean(ped, cut)
    return t.join(*cols, plinths, ent, soffit, steps, ped)


def towers(t, p, c, simple):
    """View-only look-alike complex: banded glass towers on the podium (no logo, no crown sign)."""
    out = []
    for (x0, y0, w, d, ht) in c["towers"]:
        z = c["ground"]["h"] + sum(c["uppers"]) + 0.2
        bands = []
        k = 0
        while z < ht:
            bh = 1.1 if k % 2 == 0 else 2.9
            trim, role = ("GLASS", "NEUTRAL") if k % 2 else ("CONCRETE", "WALL")
            bands.append(tag(t, t.join(t.cube(x0, x0 + w, y0, y0 + 0.2, z, z + bh), t.cube(x0, x0 + w, y0 + d - 0.2, y0 + d, z, z + bh),
                                       t.cube(x0, x0 + 0.2, y0, y0 + d, z, z + bh), t.cube(x0 + w - 0.2, x0 + w, y0, y0 + d, z, z + bh)), trim, role, 0.0))
            z += bh
            k += 1
        bands.append(strips(t, x0, x0 + w, y0, y0 + d, z, z + 0.3))
        out += bands
    return t.join(*out)


def cls(row, name, c, refs):
    return dict(row=row, name=f"BLD_CLS_{name}_A", body=block(c), lod2=block(c, simple=True), h=c["ground"]["h"], variant="A",
                refs=refs, storey_h=c["ground"]["h"])


COL = ["gf_21", "gf_24", "gf_25", "sv_04"]
SHOP = ["gf_24", "style frame dff6fe56"]
WIN_COL = {"w": 1.2, "sill": 0.6, "h": 2.2, "arched": True, "s": 0.14, "shutters": 2, "hood": 1}
WIN_SHOP = {"w": 1.3, "sill": 0.9, "h": 1.4, "s": 0.08, "grille": True}
WIN_MOD = {"w": 2.4, "sill": 0.9, "h": 1.2, "s": 0.0, "ledge": False}
WIN_OFF = {"w": 2.4, "sill": 0.8, "h": 2.2, "s": 0.0, "ledge": False}


def catalogue():
    return [
        cls("CLS_Colonial_DeltaRoad", "Colonial_DeltaRoad", dict(W=18.0, D=14.0, bw=3.6, ground={"h": 4.5, "kind": "arch"},
            uppers=[3.2, 3.2], win=WIN_COL, string=True, pilasters=True, roof="balustrade", cornice=True, pipes=(0.15,)), COL),
        cls("CLS_Shophouse_DeltaRoad", "Shophouse_DeltaRoad", dict(W=12.0, D=14.0, bw=3.0,
            ground={"h": 4.0, "kind": "shop", "awning": True, "zt": 3.0}, uppers=[3.0, 3.0], win=WIN_SHOP, sunshade=True,
            balcony={0: (1,)}, ac={0: (0, 3), 1: (2,)}, pipes=(0.15, 11.7), wiring=6.1, roof="stubs"), SHOP),
        cls("CLS_ColonialArcade", "ColonialArcade", dict(W=18.0, D=14.0, bw=3.6, ground={"h": 4.5, "kind": "arcade", "deep": 3.0},
            uppers=[3.6], win=WIN_COL, pilasters=True, roof="balustrade", cornice=True), COL),
        cls("CLS_ModernConcrete_MidRise", "ModernConcrete_MidRise", dict(W=18.0, D=16.0, bw=3.0,
            ground={"h": 4.0, "kind": "shop", "zt": 3.0}, uppers=[3.2] * 4, win=WIN_MOD, sunshade=True,
            ac={0: (1, 4), 1: (2,), 2: (0, 5), 3: (3,)}, pipes=(0.15,), roof="tanks"), ["gf_21", "OSM 529639570"]),
        cls("CLS_OfficeBlock_Generic", "OfficeBlock_Generic", dict(W=21.0, D=18.0, bw=3.0, ground={"h": 4.5, "kind": "lobby"},
            uppers=[3.6] * 7, win=WIN_OFF, roof="parapet"), ["gf_21"]),
        cls("CLS_HotelLookalike_Samudra", "HotelLookalike_Samudra", dict(W=72.0, D=16.0, bw=4.0, ground={"h": 5.0, "kind": "lobby"},
            uppers=[3.2] * 9, win={"w": 2.8, "sill": 0.9, "h": 2.0, "s": 0.0, "ledge": False}, bands=True, roof="parapet", extras=(portico,)), ["drive_circle M6", "gf_21"]),
        cls("CLS_CityOfDreams_Lookalike", "CityOfDreams_Lookalike", dict(W=60.0, D=40.0, bw=6.0, ground={"h": 6.0, "kind": "lobby"},
            uppers=[5.0, 5.0], win={"w": 4.8, "sill": 0.5, "h": 3.6, "s": 0.0, "ledge": False}, roof="parapet",
            towers=[(4.0, 6.0, 22.0, 20.0, 120.0), (34.0, 14.0, 20.0, 20.0, 95.0)], extras=(towers,)), ["drive_circle view-only"]),
        cls("CLS_MallPodium_GreenCourt", "MallPodium_GreenCourt", dict(W=48.0, D=30.0, bw=6.0, ground={"h": 7.0, "kind": "glass", "skip": ()},
            uppers=[7.0, 7.0], win={"w": 5.0, "sill": 2.5, "h": 1.15, "s": 0.0, "ledge": False}, string=True, roof="parapet"), ["gf_21"]),
        cls("CLS_Government_AssemblyHouse", "Government_AssemblyHouse", dict(W=48.0, D=22.0, bw=4.0,
            ground={"h": 6.0, "kind": "arch", "win": {"w": 1.8, "sill": 0.0, "h": 4.4, "arched": True, "s": 0.2, "ledge": False}},
            uppers=[6.0], win={"w": 1.6, "sill": 0.8, "h": 3.4, "arched": False, "s": 0.2, "hood": 2}, pilasters=True,
            roof="balustrade", cornice=True, extras=(portico,)), COL),
        cls("CLS_Government_Secretariat", "Government_Secretariat", dict(W=40.0, D=18.0, bw=4.0,
            ground={"h": 5.0, "kind": "arcade", "deep": 3.5}, uppers=[4.5, 4.5], win={"w": 1.5, "sill": 0.8, "h": 2.6, "s": 0.18, "hood": 1},
            pilasters=True, string=True, roof="balustrade", cornice=True), COL),
        cls("CLS_Bank_Branch", "Bank_Branch", dict(W=12.0, D=14.0, bw=3.0, ground={"h": 4.2, "kind": "lobby"}, uppers=[3.4],
            win={"w": 2.0, "sill": 0.9, "h": 1.6, "s": 0.0, "ledge": False, "grille": True}, roof="parapet"), SHOP),
        cls("CLS_FuelStation_Roadside", "FuelStation_Roadside", dict(W=18.0, D=8.0, bw=3.0, ground={"h": 3.6, "kind": "glass"},
            uppers=[], roof="parapet", extras=(fuel_canopy,)), ["drive_circle STN_Fuel_DeltaFace"]),
        cls("CLS_TukDealer_Showroom", "TukDealer_Showroom", dict(W=15.0, D=14.0, bw=3.0, ground={"h": 4.5, "kind": "glass"},
            uppers=[3.2], win=WIN_MOD, ac={0: (1, 3)}, roof="parapet",
            extras=(lambda t, p, c, s: strips(t, 0, c["W"], -6.0, 0.0, 0.0, 0.03, "CONCRETE", "GREY", 0.95),)), SHOP),
        cls("CLS_PartsShop", "PartsShop", dict(W=6.0, D=10.0, bw=3.0, ground={"h": 3.8, "kind": "parts"}, uppers=[3.0],
            win=WIN_SHOP, ac={0: (0,)}, pipes=(5.85,), roof="stubs"), SHOP),
        cls("CLS_RepairGarage", "RepairGarage", dict(W=9.0, D=12.0, bw=4.5, ground={"h": 4.5, "kind": "garage", "zt": 3.8},
            uppers=[], roof="parapet"), SHOP),
        cls("CLS_Compound_FormerArmyHQ", "Compound_FormerArmyHQ", dict(W=24.0, D=14.0, bw=4.0,
            ground={"h": 4.0, "kind": "punched", "win": {"w": 1.4, "sill": 0.9, "h": 1.8, "s": 0.12}}, uppers=[3.6],
            win={"w": 1.4, "sill": 0.9, "h": 1.8, "s": 0.12}, roof="parapet", wall_len=60.0, extras=(compound_wall,)), ["gf_21"]),
        cls("CLS_SacredExterior_Generic", "SacredExterior_Generic", dict(W=10.0, D=20.0, bw=2.5,
            ground={"h": 6.5, "kind": "punched", "win": {"w": 1.0, "sill": 1.6, "h": 3.6, "arched": True, "s": 0.12}, "skip": (1, 2)},
            uppers=[], roof="gable", pitch=30, extras=(low_wall_gate,)), ["generic, no symbols (Makeover s4)"]),
        cls("CLS_School", "School", dict(W=36.0, D=9.0, bw=3.6, ground={"h": 3.6, "kind": "arcade", "deep": 2.4}, uppers=[3.4],
            win={"w": 2.4, "sill": 0.9, "h": 1.6, "s": 0.0, "ledge": False}, roof="gable", pitch=20, extras=(low_wall_gate,)), ["generic"]),
        cls("CLS_PolicePost_Generic", "PolicePost_Generic", dict(W=3.0, D=3.0, bw=3.0,
            ground={"h": 2.8, "kind": "punched", "win": {"w": 1.6, "sill": 1.0, "h": 1.2, "s": 0.0, "ledge": False}}, uppers=[],
            roof="parapet"), ["generic, no insignia"]),
        cls("CLS_LaneHouse", "LaneHouse", dict(W=9.0, D=11.0, bw=3.0,
            ground={"h": 3.2, "kind": "arcade", "deep": 2.4}, uppers=[], roof="gable", pitch=26, extras=(low_wall_gate,)), ["Cityhub lanes"]),
        cls("CLS_DutchColonial_OldHospitalRow", "DutchColonial_OldHospitalRow", dict(W=21.6, D=12.0, bw=3.6,
            ground={"h": 4.5, "kind": "arcade", "deep": 3.0}, uppers=[], roof="gable", pitch=32), COL),
    ]
