"""Shopfront awnings and sheet-metal lean-tos (P148, FRONTAGE_CRITIC.md fix 1), built with profiles.py.

Canvas awnings come in three profiles that read apart in silhouette (critic: the old three were one wedge mesh):
- lean: straight canvas on a tube frame with lateral support arms, sag between the rafters, a free straight valance
  with a rolled hem (gf_24: green canvas, straight valance under a sloped skin).
- dutch: quarter-round curved skin on bent ribs, closed curved side cheeks and a scalloped valance (style frame
  dff6fe56: scalloped striped awnings over Delta Road shops).
- box: shallow top, deep front fascia ending in a scalloped hem, open sides on a box frame with corner posts.
The skin, cheeks and valance are one thin shell each (sheet + extrusion), so they are seen from under the awning
too. Stripe columns sit on the kitbuild stripe bands. Frame tubes are METAL; canvas faces CANVAS.
"""
from __future__ import annotations

import math

import profiles as pf
from parts import tag

PI = math.pi


def _skin(profile, reach, drop, ztop, kdrop=0.14):
    """(y(s), z(s)) of the skin centre line, s = 0 at the wall top, 1 at the front edge (plain numbers or sockets)."""
    if profile == "dutch":
        return lambda t, s: (-reach * pf.sin(t, s * (PI / 2)), ztop - drop * (1.0 - pf.cos(t, s * (PI / 2))))
    dz = kdrop if profile == "box" else drop
    return lambda t, s: (-reach * s, ztop - dz * s)


def canvas_awning(t, p, x1, ztop, reach, drop, profile="lean", valance="straight", xw=0.0):
    x0 = 0.0
    lod = p.LOD
    prof = _skin(profile, reach, drop, ztop)
    nb = max(1, int(round((x1 - x0) / 1.35)))      # frame bays (rafter spacing about 1.35 m)
    bay = (x1 - x0) / nb
    sag0, sag1 = (0.025, 0.03) if profile != "box" else (0.008, 0.012)
    xa, col, ncol = pf.stripe_cols(x0, x1, xw)
    rows = t.switch(lod, 8 if profile == "dutch" else 5, 3, "INT")

    def skin_pos(X, s, f):
        y, z = prof(t, s)
        cross = pf.m(t, "ABSOLUTE", pf.sin(t, (X - x0) * (PI / bay)))
        z = z - pf.sin(t, s * PI) * (sag0 + sag1 * cross)
        return X, y, z

    out = [pf.solid(t, pf.sheet(t, xa, col, ncol, rows, skin_pos, x0, x1), 0.012)]
    ye, ze = prof(t, 1.0) if profile != "dutch" else (-reach, ztop - drop)
    if not isinstance(ye, (int, float)):
        ye, ze = -reach, ztop - drop
    if profile == "box":
        ze = ztop - 0.14
    # valance: straight strip with a hem (lean) or a scalloped hem (dutch, box: the box front is its fascia)
    vh = {"lean": 0.24, "dutch": 0.2, "box": drop - 0.14}[profile]
    scal = 0.07 if valance == "scallop" else 0.0
    sub = t.switch(lod, 5, 3, "INT") if scal else 1

    def val_pos(X, s, f):
        z = ze - vh * s
        if scal:
            z = z - s * scal * pf.sin(t, f * PI)
        return X, ye - 0.006, z

    out.append(pf.solid(t, pf.sheet(t, xa, col, ncol, 1, val_pos, x0, x1, sub=sub), 0.006))
    if profile == "dutch":   # closed curved side cheeks (fan between the wall and the skin)
        for xc in (x0 + 0.004, x1 - 0.004):
            def cheek(X, s, f, xc=xc):
                y, z = prof(t, s)
                return xc, X * y, z
            out.append(pf.solid(t, pf.sheet(t, 0.0, 1.0, 1, rows, cheek), 0.008))
    canvas = tag(t, t.join(*out), "CANVAS", "CANVAS", 0.0)

    # frame: wall rail, front rail, rafters following the skin, arms, wall brackets
    r = 0.014
    xs = [x0 + 0.03 + i * (x1 - x0 - 0.06) / nb for i in range(nb + 1)]
    fr = [pf.rod(t, (x0, -0.03, ztop - 0.03), (x1, -0.03, ztop - 0.03), r),
          pf.rod(t, (x0, ye + 0.02, ze - 0.025), (x1, ye + 0.02, ze - 0.025), r)]
    raf = []
    for x in xs:
        def arm(s, x=x):
            y, z = prof(t, s)
            return x, y + 0.01, z - 0.025
        raf.append(pf.bent_rod(t, arm, 8 if profile == "dutch" else 1, r * 0.9))
    brk = [t.cube(x - 0.03, x + 0.03, -0.05, 0.0, ztop - 0.09, ztop + 0.02) for x in (xs[0], xs[-1])]
    if profile == "lean":   # lateral support arms from the wall to the front rail (gf_24)
        za = ztop - drop - 0.45
        raf += [pf.rod(t, (x, -0.02, za), (x, ye + 0.03, ze - 0.03), r) for x in (xs[0], xs[-1])]
        brk += [t.cube(x - 0.03, x + 0.03, -0.04, 0.0, za - 0.06, za + 0.06) for x in (xs[0], xs[-1])]
    if profile == "box":    # box frame: front corner posts and a lower front rail behind the fascia
        zb = ztop - drop + 0.06
        raf += [pf.rod(t, (x, ye + 0.02, ze - 0.02), (x, ye + 0.02, zb), r) for x in (xs[0], xs[-1])]
        raf += [pf.rod(t, (x0, ye + 0.02, zb), (x1, ye + 0.02, zb), r)]
        raf += [pf.rod(t, (x, -0.02, zb - 0.25), (x, ye + 0.03, zb), r) for x in (xs[0], xs[-1])]
        brk += [t.cube(x - 0.03, x + 0.03, -0.04, 0.0, zb - 0.31, zb - 0.19) for x in (xs[0], xs[-1])]
    hem = []
    if valance == "straight" or profile == "lean":
        hem = [pf.rod(t, (x0, ye - 0.012, ze - vh), (x1, ye - 0.012, ze - vh), 0.007, 5)]
    frame = tag(t, t.join(*fr, *raf, *brk), "METAL", "METAL", 0.0)
    return t.join(canvas, frame, t.when(t.bnot(lod), tag(t, t.join(*hem), "CANVAS", "CANVAS", 0.0)) if hem else None)


def lean_to(t, p, x1=2.7, reach=1.25, drop=0.32, zt=0.82):
    """Sheet-metal lean-to: corrugated galvanised sheet (76-80 mm pitch, 18 mm deep) in four lapped lengths, each a
    corrugated grid that fits the SHEET row; two purlins on three angle-iron brackets; a box gutter at the eave."""
    lod = p.LOD
    n = 4
    ln = reach / n
    amp = 0.018
    half = 0.04
    cols = t.switch(lod, int(round(x1 / half)), 1, "INT")
    sheets = []
    for k in range(n):
        lift = 0.004 * (n - k)          # upper lengths lie on the lower ones (laps shed rain)
        s0, s1 = k * ln - (0.03 if k else 0.0), (k + 1) * ln

        def pos(X, s, f, s0=s0, s1=s1, lift=lift):
            yy = s0 + (s1 - s0) * s
            z = zt - drop * (yy / reach) + lift + amp * pf.wave(t, X, half)
            return X, -yy, z

        g = _corrugated(t, x1, cols, pos)
        sheets.append(pf.two_sided(t, g, 0.003))
    a = math.atan2(drop, reach)
    purl = [t.move(t.cube(0.0, x1, -0.03, 0.03, -0.05, 0.0), (0, -yy, zt - drop * yy / reach - 0.004), (a, 0, 0))
            for yy in (0.35, 1.05)]
    brk = []
    for xb in (0.08, x1 / 2, x1 - 0.08):   # angle-iron bracket: arm under the sheet, diagonal brace, wall plate
        za = zt - 0.06
        zf = zt - drop * 1.15 / reach - 0.06
        brk += [pf.rod(t, (xb, -0.01, za), (xb, -1.15, zf), 0.022, 4),
                pf.rod(t, (xb, -0.01, zt - 0.75), (xb, -0.8, zt - drop * 0.8 / reach - 0.07), 0.018, 4),
                t.cube(xb - 0.045, xb + 0.045, -0.012, 0.0, zt - 0.82, zt + 0.02)]
    ze = zt - drop
    gutter = t.join(t.cube(0.0, x1, -reach - 0.12, -reach - 0.1, ze - 0.12, ze - 0.02),
                    t.cube(0.0, x1, -reach - 0.12, -reach + 0.02, ze - 0.14, ze - 0.12),
                    t.cube(0.0, x1, -reach, -reach + 0.02, ze - 0.12, ze - 0.06))
    return t.join(tag(t, t.join(*sheets), "SHEET", "NEUTRAL", 0.0),
                  tag(t, t.join(*purl, *brk), "METAL", "METAL", 0.0), tag(t, gutter, "METAL", "GREY", 0.0))


def _corrugated(t, x1, cols, pos):
    """Grid of `cols` columns over 0..x1 and one row, placed by pos(X, s, f)."""
    from gnlib import S
    g = t.node("GeometryNodeMeshGrid")
    t.set(g.inputs["Size X"], x1)
    t.set(g.inputs["Size Y"], 1.0)
    t.set(g.inputs["Vertices X"], cols + 1)
    t.set(g.inputs["Vertices Y"], 2)
    geo = t.move(S(t, g.outputs["Mesh"]), (x1 / 2, 0.5, 0.0))
    px, py, _ = pf._pos(t)
    return pf.set_pos(t, geo, *pos(px, py, None))


# --- roller shutters (FRONTAGE_CRITIC.md fix 2) ------------------------------------------------------------------
SLAT = 0.08          # slat pitch on the ROLLER trim row (trim_high.py bakes its slats at 0.08 m too)


def slats(t, p, x0, x1, ztop, length, y=0.02, amp=0.011, role="METAL"):
    """Slatted curtain: lifts of at most 1.2 m (each fits the ROLLER row unscaled and unrotated), every lift a grid
    whose rows step 40 mm and alternate proud/back, so each 80 mm slat has a lit upper and a shaded lower face;
    a flipped copy behind closes it. LOD1 keeps one row per lift (flat, the trim carries the slats)."""
    out = []
    n = max(1, int(math.ceil(length / 1.2 - 1e-6)))
    step = length / n
    for k in range(n):
        top = ztop - k * step
        rows = max(1, int(round(step / (SLAT / 2))))
        rr = t.switch(p.LOD, rows, 1, "INT")

        def pos(X, s, f, top=top):
            d = s * step
            return X, y - amp * pf.wave(t, d, SLAT / 2), top - d

        g = pf.sheet(t, x0, x1 - x0, 1, rr, pos)
        fl = t.node("GeometryNodeFlipFaces")
        t.set(fl.inputs["Mesh"], t.move(g, (0.0, 0.012, 0.0)))
        from gnlib import S
        out += [g, S(t, fl.outputs["Mesh"])]
    return tag(t, t.join(*out), "ROLLER", role, 0.0)


def padlock(t, x, y, z, shut=True):
    """Hasp plate and a brass-less steel padlock (body 50 x 22 x 60 mm, shackle); open ones hang off the lug."""
    body = t.cube(x - 0.025, x + 0.025, y - 0.022, y, z - 0.07, z - 0.01)
    sh = [pf.rod(t, (x - 0.014, y - 0.011, z - 0.012), (x - 0.014, y - 0.011, z + 0.03), 0.004, 4),
          pf.rod(t, (x + 0.014, y - 0.011, z - 0.012 + (0.0 if shut else 0.02)), (x + 0.014, y - 0.011, z + 0.03), 0.004, 4),
          pf.rod(t, (x - 0.016, y - 0.011, z + 0.03), (x + 0.016, y - 0.011, z + 0.03), 0.004, 4)]
    return t.join(body, *sh)


def roller_shutter(t, p, x1=2.4, zt=2.9, curtain=2.5, hood="box", role="METAL", locks="shut", handles=2):
    """Roller shutter: sheet-metal hood (box with a folded drip lip, or quarter-round) with end caps, U-channel
    guides, slatted curtain `curtain` m long, angle bottom bar with lift handles and padlocks (shut on floor hasps
    when the curtain is down, hanging open off the guide lugs when it is up)."""
    lod = p.LOD
    x0 = 0.0
    hz = zt - 0.36
    if hood == "round":
        R = 0.3

        def hpos(X, s, f):
            return X, -R * pf.sin(t, s * (PI / 2)) + 0.06, zt - R * (1.0 - pf.cos(t, s * (PI / 2)))

        skin = pf.solid(t, pf.sheet(t, x0 - 0.03, x1 + 0.06, 1, t.switch(lod, 6, 3, "INT"), hpos), 0.003)
        caps = []
        for xc in (x0 - 0.03, x1 + 0.03):
            def cap(X, s, f, xc=xc):
                _, y, z = hpos(X, s, f)
                return xc, 0.06 + X * (y - 0.06), z
            caps.append(pf.solid(t, pf.sheet(t, 0.0, 1.0, 1, t.switch(lod, 6, 3, "INT"), cap), 0.004))
        lip = t.cube(x0 - 0.03, x1 + 0.03, -0.25, -0.23, hz, zt - 0.27)
        hood_g = t.join(skin, *caps, lip)
    else:
        hood_g = t.join(t.cube(x0 - 0.03, x1 + 0.03, -0.24, 0.06, zt - 0.02, zt),            # top
                        t.cube(x0 - 0.03, x1 + 0.03, -0.26, -0.24, hz, zt),                  # front plate
                        t.cube(x0 - 0.03, x1 + 0.03, -0.29, -0.24, hz, hz + 0.025),          # folded drip lip
                        t.cube(x0 - 0.035, x0 - 0.025, -0.26, 0.06, hz, zt),                 # end caps
                        t.cube(x1 + 0.025, x1 + 0.035, -0.26, 0.06, hz, zt))
    hood_g = tag(t, hood_g, "METAL", role, 0.0)
    # U-channel guides: back plate and two lips each side, fixed to the jamb
    g = []
    for a, b in ((x0 - 0.02, x0 + 0.06), (x1 - 0.06, x1 + 0.02)):
        g += [t.cube(a, b, 0.035, 0.05, 0.0, hz), t.cube(a, a + 0.012, -0.015, 0.035, 0.0, hz),
              t.cube(b - 0.012, b, -0.015, 0.035, 0.0, hz)]
    guides = tag(t, t.join(*g), "METAL", "METAL", 0.0)
    out = [hood_g, guides]
    zb = hz - curtain
    if curtain > 0.05:
        out.append(slats(t, p, x0 + 0.03, x1 - 0.03, hz, curtain, role=role))
    zb = max(zb, 0.0)
    bar = t.join(t.cube(x0 + 0.03, x1 - 0.03, -0.012, 0.035, zb, zb + 0.06),
                 t.cube(x0 + 0.03, x1 - 0.03, -0.03, -0.012, zb, zb + 0.015))
    det = []
    for i in range(handles):
        hx = x0 + (x1 - x0) * (i + 1) / (handles + 1)
        det += [pf.rod(t, (hx - 0.07, -0.012, zb + 0.03), (hx - 0.07, -0.05, zb + 0.03), 0.007, 4),
                pf.rod(t, (hx + 0.07, -0.012, zb + 0.03), (hx + 0.07, -0.05, zb + 0.03), 0.007, 4),
                pf.rod(t, (hx - 0.07, -0.05, zb + 0.03), (hx + 0.07, -0.05, zb + 0.03), 0.007, 4)]
    if locks == "shut":     # bar hasps over floor staples, locked
        for lx in (x0 + 0.16, x1 - 0.16):
            det += [t.cube(lx - 0.03, lx + 0.03, -0.035, -0.012, zb + 0.005, zb + 0.06), padlock(t, lx, -0.035, zb + 0.03)]
    elif locks == "open":   # padlocks hanging open off the guide lugs at hand height
        for lx in (x0 + 0.02, x1 - 0.02):
            det += [t.cube(lx - 0.02, lx + 0.02, -0.04, -0.015, 1.0, 1.06), padlock(t, lx, -0.04, 1.0, shut=False)]
    out += [tag(t, bar, "METAL", role, 0.0), t.when(t.bnot(lod), tag(t, t.join(*det), "METAL", "METAL", 0.0))]
    return t.join(*out)
