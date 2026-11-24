"""P140 street life: bus halts, vendor stalls and kiosks, traffic control and small furniture (PH06).

Same data model as `street_kit.py` (Pure Python, no bpy; `gn/street.py` turns each part into Geometry Nodes). Every piece
is origin at the base centre, +y to the back, its front (-y) to the road / the customer, 1 unit = 1 m, one material draw
(`MAT_StreetKit_A`, plus the signage atlas where a sign part is used). Each piece lists its Low-tier cost in
`LOW_COST`: LOD0 tris (the Piece budget is the ceiling, the measured value is in street_kit_tris.json), 0 extra
textures (trim sheet + signage atlas already resident), draw calls = materials on the piece.
Pieces with `decay=` also carry COLOR_1 (R dirt, G edge wear, B rust or damp, A age seed) from gn/street.py, per
docs/research/wear-and-decay-system.md 3.1; it is exported only for these pieces until the W3 export change.
"""
from __future__ import annotations

from .street_kit import (BLACK, CANVAS, CONE_RED, CREAM, GALV, GALV_D, IRON, RED_PLASTIC, SHOP_FRAME, STONE, WHITE,
                         Piece, array, box, cyl, lathe, sweep)

BLUE_STEEL, ROOF_TIN, TIMBER_BENCH = "#2B4C6F", "#5C7080", "#6B4A32"
LAKE_GREEN, TERRACOTTA, LAKE_TIMBER = "#1E6B3A", "#9C4F36", "#4A3426"


def _slat_bench(x0, x1, y0=0.0, z=0.45, back=True, legs=True):
    """Slatted bench from x0 to x1 (seat of four slats, optional three-slat back), steel ends."""
    w, cx = x1 - x0, (x0 + x1) / 2
    out = [array(box((w, 0.08, 0.03), (cx, y0 - 0.14, z), TIMBER_BENCH), 4, (0, 0.09, 0))]
    if back:
        out.append(array(box((w, 0.025, 0.1), (cx, y0 + 0.2, z + 0.17), TIMBER_BENCH), 3, (0, 0, 0.12)))
    if legs:
        for x in (x0 + 0.06, x1 - 0.06):
            out += [box((0.05, 0.46, z - 0.015), (x, y0, (z - 0.015) / 2), IRON)]
            if back:
                out.append(box((0.05, 0.05, z + 0.5), (x, y0 + 0.2, (z + 0.5) / 2), IRON))
    return out


def _bands(r, z0, z1, n):
    """Black / white bands up a pole, a 2 cm gap between them so the caps do not merge into non-manifold edges."""
    step = (z1 - z0) / n
    return [cyl(r, step - 0.02, (0.0, 0.0, z0 + step * k), 6, BLACK if k % 2 == 0 else WHITE) for k in range(n)]


def _jersey_stripes():
    """Red-white reflective stripes lying on both sloped faces of the jersey section (P150: vertical boxes were buried)."""
    out = []
    for k in range(5):
        x0 = -0.9 + 0.4 * k - 0.1
        for side in (1, -1):
            # face (0.2, 0.55) -> (0.09, 0.8); stripe z 0.62..0.74, 1-5 mm off the face along its normal (0.915, 0.403)
            q = [(0.2 - 0.44 * (z - 0.55) + 0.915 * d, z + 0.403 * d) for z, d in ((0.62, 0.001), (0.74, 0.001), (0.74, 0.005), (0.62, 0.005))]
            prof = [(side * px, pz) for px, pz in (q if side > 0 else q[::-1])]
            out.append(sweep([(x0, 0.0, 0.0), (x0 + 0.2, 0.0, 0.0)], prof, "#C23A30" if k % 2 else WHITE))
    return out


def bus_halts() -> list[Piece]:
    out = []
    # CTB-style flag pole (catalogue 7): 76 mm galvanised pole, the yellow BUS HALT plate over a route plate,
    # black / white bands at eye height, a concrete collar
    out.append(Piece("PROP_BusHalt_Pole_01", 0.9, 3.0, [
        lathe([(0.12, 0.0), (0.12, 0.1), (0.05, 0.14), (0.038, 2.9), (0.0, 2.92)], 8, GALV),
        *_bands(0.052, 0.1, 1.3, 4),   # outside the 0.05-0.038 pole taper (P150: 0.042 was buried)
        box((0.9, 0.025, 0.225), (0, -0.05, 2.78), "#FFFFFF", "sign", uv=("sign", 0, 5)),
        box((0.9, 0.025, 0.225), (0, -0.05, 2.5), "#FFFFFF", "sign", uv=("sign", 1, 5))],
        260, bevel=0.0, refs=["sv_12"], decay="metal"))
    out.append(Piece("PROP_BusHalt_Bench_01", 1.8, 0.95, _slat_bench(-0.9, 0.9), 200, bevel=0.0,
                      refs=["sv_05", "sv_12"], decay="timber"))
    # modular two-bay steel shelter: mono-pitch tin roof falling to the road, back and end panels, benches
    post = lambda x, y, h: box((0.08, 0.08, h), (x, y, h / 2 + 0.1), BLUE_STEEL)  # noqa: E731
    out.append(Piece("PROP_BusHalt_Shelter_01", 3.9, 2.8, [
        box((3.8, 2.0, 0.1), (0, 0, 0.05), STONE),
        *[post(x, 0.8, 2.6) for x in (-1.7, 1.7)], *[post(x, -0.75, 2.3) for x in (-1.7, 1.7)], post(0, 0.8, 2.6),
        sweep([(-1.95, 0.0, 0.0), (1.95, 0.0, 0.0)],
              [(-0.95, 2.35), (0.95, 2.67), (0.95, 2.72), (-0.95, 2.40)], ROOF_TIN),
        box((3.9, 0.04, 0.2), (0, -0.98, 2.38), BLUE_STEEL),
        box((3.5, 0.04, 1.5), (0, 0.84, 1.3), "#8FA3AE"), box((0.04, 1.5, 1.5), (1.76, 0.05, 1.3), "#8FA3AE"),
        box((0.7, 0.02, 0.18), (0.9, -1.0, 2.38), "#FFFFFF", "sign", uv=("sign", 0, 5)),
        *_slat_bench(-1.5, 1.5, y0=0.45, z=0.5, back=False)], 620, bevel=0.0, refs=["sv_12", "sv_02"],
        decay="metal"))
    # Lake Halt variant: a low open timber pavilion at the lake edge, gable terracotta roof over a stone plinth
    # with a built-in seat ledge on three sides, a lake-green name plate on the front beam. Proportions only from
    # the catalogue; no photo of the real halt is in references/ (NOT checked against a real halt).
    lt = LAKE_TIMBER
    out.append(Piece("PROP_BusHalt_Lake_01", 4.6, 3.5, [
        box((4.6, 2.6, 0.18), (0, 0, 0.09), STONE),
        box((4.0, 0.3, 0.4), (0, 0.95, 0.38), STONE),
        *[box((0.3, 1.5, 0.4), (x, 0.1, 0.38), STONE) for x in (-1.95, 1.95)],
        *[cyl(0.08, 2.44, (x, y, 0.18), 8, lt) for x in (-1.85, 1.85) for y in (-0.95, 0.95)],
        box((4.1, 0.12, 0.22), (0, -0.95, 2.52), lt), box((4.1, 0.12, 0.22), (0, 0.95, 2.52), lt),
        box((0.12, 1.9, 0.18), (-1.85, 0, 2.52), lt), box((0.12, 1.9, 0.18), (1.85, 0, 2.52), lt),
        box((1.5, 0.02, 0.3), (0, -1.02, 2.52), "#FFFFFF", "sign", uv=("sign", 1, 5)),
        sweep([(-2.4, 0.0, 2.62), (2.4, 0.0, 2.62)], [(-1.5, 0.0), (1.5, 0.0), (0.0, 0.8)], TERRACOTTA),
        sweep([(-2.45, 0.0, 3.4), (2.45, 0.0, 3.4)], [(-0.07, 0.0), (0.07, 0.0), (0.07, 0.06), (-0.07, 0.06)], lt),
        ], 600, bevel=0.0, refs=["catalogue-7"], decay="timber"))
    return out


# --- vendor stalls and kiosks (item 2) and traffic control (item 3) are added by their own commits ---

LOW_COST = {}   # name -> (draw calls, extra textures MB); tris come from street_kit_tris.json

# vendor colour life (P153, critic fix 5): goods, crates and fruit in flat palette colours (gf_03, sv_07; no brands)
FRUIT = {"orange": "#E0892C", "lime": "#6E9A2E", "banana": "#E4C23C", "red": "#B83A2C", "coconut": "#E39B2E",
         "green": "#4E7F2A"}
CRATE = {"red": "#B8312F", "blue": "#2D5E95", "green": "#2F7A45", "yellow": "#E0B72E"}
PACKET = ["#D8452E", "#E8B52E", "#2E7FB8", "#3E9A4E", "#E07A2E", "#C23A7A", "#F2EBD8"]


def _pile(x, y, z, r, colour):
    """A heaped mound of fruit or nuts on a counter (low 8-sided dome)."""
    return lathe([(r, 0.0), (r * 0.7, r * 0.5), (0.0, r * 0.7)], 7, colour, at=(x, y, z))


def _crate(x, y, z, colour, w=0.5, d=0.36, h=0.28):
    """Stackable plastic crate: body and the dark hand-hole band through the long faces."""
    return [box((w, d, h), (x, y, z + h / 2), colour),
            box((w * 0.5, d + 0.01, 0.05), (x, y, z + h * 0.62), BLACK)]


def _hang(x0, x1, y, z, n, colours, w=0.09, h=0.22):
    """A string of hanging packets (snacks, sachets) under a front beam."""
    step = (x1 - x0) / max(n - 1, 1)
    return [box((w, 0.04, h), (x0 + i * step, y, z - h / 2), colours[i % len(colours)]) for i in range(n)]


def _kade_tarp(name, tarp, tarp_d, goods, refs, budget=1300):
    """Tarp kade stall: four poles, plank counter, a tarp that sags between the poles and across its span, a hanging
    valance; `goods` adds the colour life on and around the counter."""
    KADE_T = "#7A5738"
    sag = [(-1.3, 0.0, 2.22), (-0.65, 0.0, 2.13), (0.0, 0.0, 2.1), (0.65, 0.0, 2.13), (1.3, 0.0, 2.22)]   # sags between poles
    prof = [(-0.92, 0.0), (-0.45, 0.07), (0.0, 0.16), (0.45, 0.02), (0.92, -0.1), (0.92, -0.13), (0.45, -0.01),
            (0.0, 0.13), (-0.45, 0.04), (-0.92, -0.03)]
    return Piece(name, 2.6, 2.4, [
        *[box((0.06, 0.06, 2.2), (x, y, 1.1), KADE_T) for x in (-1.15, 1.15) for y in (-0.65, 0.65)],
        box((2.3, 0.7, 0.9), (0, -0.4, 0.45), KADE_T), box((2.4, 0.8, 0.05), (0, -0.4, 0.92), CREAM),
        sweep(sag, prof, tarp),
        box((2.5, 0.03, 0.28), (0, -1.0, 1.98), tarp_d),
        box((2.0, 0.04, 0.35), (0, -0.83, 1.7), "#FFFFFF", "sign", uv=("sign", 2, 6)),
        *goods], budget, bevel=0.01, refs=refs, decay="timber")


def vendors() -> list[Piece]:
    out = []
    KG, KG_D, TARP, TARP_D, KADE_T = "#2E6B45", "#1F4A31", "#2F5E8C", "#B8452E", "#7A5738"
    # regulated Green kiosk 01: small council-licensed green cabin, counter hatch with a hinged flap, flat roof, sign band
    out.append(Piece("PROP_Kiosk_Green_01", 2.0, 2.5, [
        box((2.0, 1.6, 0.1), (0, 0, 0.05), STONE),
        box((1.8, 1.4, 2.2), (0, 0, 1.2), KG),
        box((1.3, 0.03, 0.75), (0, -0.71, 1.45), "#55646A"),
        box((1.5, 0.3, 0.05), (0, -0.85, 1.0), GALV),
        box((1.3, 0.03, 0.5), (0, -0.74, 1.95), KG_D),
        box((2.2, 1.8, 0.1), (0, 0, 2.35), KG_D),
        box((1.5, 0.04, 0.3), (0, -0.74, 2.15), "#FFFFFF", "sign", uv=("sign", 0, 4)),
        box((0.5, 0.04, 1.7), (0.6, -0.71, 0.95), SHOP_FRAME),
        *_hang(-0.55, 0.15, -0.77, 1.8, 4, PACKET),
        *[box((0.12, 0.1, 0.1), (x, -0.86, 1.08), c) for x, c in ((-0.5, PACKET[1]), (-0.3, PACKET[2]), (-0.1, PACKET[0]))],
        box((0.5, 0.4, 0.75), (-1.35, -0.3, 0.475), CRATE["blue"]), box((0.52, 0.42, 0.05), (-1.35, -0.3, 0.875), WHITE),
        *_crate(-1.35, -0.3, 0.9, CRATE["red"], 0.45, 0.32, 0.22)], 1000, bevel=0.01, refs=["sv_07"], decay="metal"))
    # regulated Green kiosk 02: longer two-hatch kiosk with side shelf and pitched roof
    out.append(Piece("PROP_Kiosk_Green_02", 3.2, 2.7, [
        box((3.2, 1.8, 0.1), (0, 0, 0.05), STONE),
        box((3.0, 1.6, 2.2), (0, 0, 1.2), KG),
        *[box((1.0, 0.03, 0.7), (x, -0.81, 1.45), "#55646A") for x in (-0.7, 0.7)],
        box((2.8, 0.3, 0.05), (0, -0.95, 1.0), GALV),
        sweep([(-1.7, 0.0, 2.3), (1.7, 0.0, 2.3)], [(-0.95, 0.0), (0.0, 0.3), (0.95, 0.0), (0.95, -0.06), (-0.95, -0.06)], KG_D),
        box((2.0, 0.04, 0.3), (0, -0.82, 2.1), "#FFFFFF", "sign", uv=("sign", 0, 2)),
        box((0.6, 0.5, 0.04), (1.8, 0, 0.9), GALV),
        *[pk for x0 in (-1.1, 0.3) for pk in _hang(x0, x0 + 0.8, -0.86, 1.78, 4, PACKET[x0 > 0:] + PACKET[:x0 > 0])],
        *[cyl(0.04, 0.22, (x, -0.95, 1.135), 6, c) for x, c in ((-1.0, "#C23A30"), (-0.88, "#2E7FB8"), (0.85, "#E8B52E"))],
        _pile(0.1, -0.95, 1.025, 0.13, FRUIT["banana"]),
        *_crate(1.8, 0.0, 0.92, CRATE["yellow"], 0.5, 0.36, 0.24)], 1300, bevel=0.01, refs=["sv_07"], decay="metal"))
    # kade stall 02: blue-tarp fruit stall, tarp sagging between four poles, fruit piles on the counter, bananas
    # hanging from the front beam, plastic crates stacked beside and under it (gf_03)
    out.append(_kade_tarp("PROP_Kade_Stall_02", TARP, "#1F4466", [
        *[_pile(x, -0.45, 0.945, 0.2, c) for x, c in ((-0.8, FRUIT["orange"]), (-0.35, FRUIT["lime"]),
                                                       (0.1, FRUIT["red"]), (0.55, FRUIT["orange"]))],
        *[box((0.26, 0.1, 0.28), (x, -0.98, 1.66), FRUIT["banana"]) for x in (-0.75, 0.75)],
        *_crate(1.55, -0.3, 0.0, CRATE["red"]), *_crate(1.55, -0.3, 0.29, CRATE["blue"]),
        *_crate(-1.55, -0.2, 0.0, CRATE["green"])], ["gf_03"]))
    # kade stall 04: colour variant of 02, orange tarp king-coconut stall: a coconut heap on the counter and a
    # bunch-pile on the ground, yellow crates (gf_03, sv_07)
    out.append(_kade_tarp("PROP_Kade_Stall_04", CANVAS["orange"], TARP_D, [
        *[_pile(x, -0.45, 0.945, 0.26, FRUIT["coconut"]) for x in (-0.65, 0.05, 0.7)],
        _pile(-1.6, -0.3, 0.0, 0.42, FRUIT["coconut"]),
        *_crate(1.55, -0.3, 0.0, CRATE["yellow"]), *_crate(1.55, -0.3, 0.29, CRATE["yellow"]),
        *_hang(-0.9, 0.9, -0.98, 1.84, 5, PACKET)], ["gf_03", "sv_07"]))
    # kade stall 03: timber stall with a goods rack on the back wall and a slanted tin roof
    out.append(Piece("PROP_Kade_Stall_03", 2.4, 2.3, [
        *[box((0.07, 0.07, 2.1), (x, y, 1.05), KADE_T) for x in (-1.05, 1.05) for y in (-0.6, 0.6)],
        box((2.1, 0.6, 0.85), (0, -0.4, 0.425), KADE_T), box((2.2, 0.7, 0.05), (0, -0.4, 0.88), CREAM),
        box((2.1, 0.04, 1.8), (0, 0.62, 1.0), "#D9D2BE"),
        *[box((2.0, 0.3, 0.03), (0, 0.45, z), KADE_T) for z in (0.9, 1.35, 1.8)],
        sweep([(-1.25, 0.0, 2.1), (1.25, 0.0, 2.1)], [(-0.85, 0.0), (0.85, 0.2), (0.85, 0.24), (-0.85, 0.04)], GALV),
        box((1.8, 0.04, 0.3), (0, -0.78, 1.9), "#FFFFFF", "sign", uv=("sign", 2, 6)),
        *[box((0.3, 0.18, 0.2 + 0.04 * (i % 2)), (-0.76 + i * 0.38, 0.45, z + 0.115 + 0.02 * (i % 2)),
              PACKET[(i + 2 * k) % len(PACKET)]) for k, z in enumerate((0.9, 1.35, 1.8)) for i in range(5)],
        *[cyl(0.06, 0.16, (x, -0.5, 0.985), 6, c) for x, c in ((-0.8, "#E8B52E"), (-0.62, "#C23A30"))],
        *_crate(0.55, -0.45, 0.905, CRATE["blue"], 0.5, 0.36, 0.2),
        box((0.5, 0.36, 0.28), (-1.45, -0.3, 0.14), CRATE["red"])], 1500, bevel=0.01, refs=["gf_03"], decay="timber"))
    # display rack (BH-0129): free-standing three-tier rack of newspapers / fruit crates with a back frame
    out.append(Piece("PROP_DisplayRack_01", 1.2, 1.6, [
        *[box((0.04, 0.04, 1.6), (x, y, 0.8), IRON) for x in (-0.55, 0.55) for y in (-0.25, 0.25)],
        *[box((1.1, 0.5, 0.03), (0, 0, z), GALV) for z in (0.3, 0.75, 1.2)],
        *[box((1.1, 0.03, 0.1), (0, -0.25, z + 0.06), GALV_D) for z in (0.3, 0.75, 1.2)],
        box((1.1, 0.03, 0.3), (0, 0.25, 1.45), "#FFFFFF", "sign", uv=("sign", 0, 4)),
        *[part for k, z in enumerate((0.315, 0.765, 1.215)) for j, x in enumerate((-0.27, 0.27))
          for part in (*_crate(x, 0.0, z, list(CRATE.values())[(k + j) % 4], 0.48, 0.4, 0.14),
                       _pile(x, 0.0, z + 0.14, 0.17, list(FRUIT.values())[(2 * k + j) % 6]))]], 900, bevel=0.0,
        refs=["gf_03"], decay="metal"))
    return out


def traffic_control() -> list[Piece]:
    out = []
    YEL, ORG, CONC, SIG = "#E3B91F", "#D8601F", "#A6A39B", "#2A2C2E"
    # steel bollard 02: 114 mm pipe, domed cap, yellow reflective band, base plate
    out.append(Piece("PROP_Bollard_02", 0.3, 0.95, [
        box((0.3, 0.3, 0.02), (0, 0, 0.01), IRON),
        lathe([(0.057, 0.02), (0.057, 0.88), (0.04, 0.93), (0.0, 0.95)], 8, GALV_D),
        cyl(0.059, 0.08, (0, 0, 0.68), 8, YEL)], 140, bevel=0.0, refs=["sv_07"], decay="metal"))
    # flexible post: orange delineator on a rubber base, two white reflective bands
    out.append(Piece("PROP_Bollard_Flex_01", 0.3, 1.0, [
        cyl(0.15, 0.04, (0, 0, 0.0), 10, BLACK),
        cyl(0.035, 0.94, (0, 0, 0.04), 6, ORG),
        cyl(0.037, 0.1, (0, 0, 0.62), 6, WHITE), cyl(0.037, 0.1, (0, 0, 0.8), 6, WHITE)], 120, bevel=0.0,
        refs=["sv_07"], decay="plastic"))
    # pedestrian crowd-control fence panel (the police barrier is a separate piece)
    out.append(Piece("PROP_Barrier_Fence_01", 2.2, 1.1, [
        *[box((0.05, 0.4, 0.04), (x, 0, 0.02), IRON) for x in (-1.0, 1.0)],
        *[box((0.04, 0.04, 1.08), (x, 0, 0.56), GALV) for x in (-1.05, 1.05)],
        box((2.1, 0.03, 0.04), (0, 0, 1.06), GALV), box((2.1, 0.03, 0.04), (0, 0, 0.1), GALV),
        *[box((0.02, 0.02, 0.9), (-0.9 + 0.12 * k, 0, 0.58), GALV) for k in range(16)]], 520, bevel=0.0,
        refs=["sv_09"], decay="metal"))
    # concrete jersey barrier: tapered section, a red-white reflective stripe band on top
    out.append(Piece("PROP_Barrier_Jersey_01", 2.0, 0.8, [
        sweep([(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
              [(-0.3, 0.0), (0.3, 0.0), (0.3, 0.1), (0.2, 0.55), (0.09, 0.8), (-0.09, 0.8), (-0.2, 0.55), (-0.3, 0.1)], CONC,
              "concrete", uv="world"),
        *_jersey_stripes()],
        240, bevel=0.0, refs=["sv_09"], decay="concrete"))
    # boom barrier: housing, arm with red / white stripes, raised-arm rest post
    out.append(Piece("PROP_Barrier_Boom_01", 4.6, 1.12, [
        box((0.4, 0.35, 1.05), (-2.1, 0, 0.525), "#D9D2BE"), box((0.44, 0.39, 0.06), (-2.1, 0, 1.09), GALV_D),
        *[box((0.43, 0.05, 0.1), (-1.7 + 0.45 * k, 0, 1.0), "#C23A30" if k % 2 else WHITE) for k in range(9)],
        box((0.1, 0.1, 0.9), (2.2, 0, 0.45), IRON), box((0.2, 0.15, 0.06), (2.2, 0, 0.93), GALV)],
        320, bevel=0.0, refs=["sv_14"], decay="metal"))
    # road cone 02: 700 mm police / work-zone cone (sv_07, sv_09; P153 critic fix 5 - the 300 mm cone was toy-sized
    # beside a person): heavy black square base, red body, two white reflective collars following the surface
    out.append(Piece("PROP_TrafficCone_02", 0.4, 0.7, [
        box((0.4, 0.4, 0.035), (0, 0, 0.0175), BLACK),
        lathe([(0.15, 0.035), (0.13, 0.12), (0.025, 0.69), (0.0, 0.7)], 10, CONE_RED),
        cyl(0.106, 0.09, (0, 0, 0.30), 10, WHITE, r2=0.088),
        cyl(0.068, 0.07, (0, 0, 0.50), 10, WHITE, r2=0.054)], 220, bevel=0.0, refs=["sv_07", "sv_09"], decay="plastic"))
    # police barrier run (sv_04, sv_09, sv_14): three red water-filled barriers lugged end to end, a fill cap on each,
    # the POLICE label cell of the signage atlas on the -y face (same cell as PROP_Barrier_Police_01, no new text)
    body = [(0.22, 0.0), (0.2, 0.08), (0.1, 0.76), (0.07, 0.84), (-0.07, 0.84), (-0.1, 0.76), (-0.2, 0.08), (-0.22, 0.0)]
    run = []
    for k, x in enumerate((-1.55, 0.0, 1.55)):
        run += [sweep([(x - 0.72, 0, 0), (x + 0.72, 0, 0)], body, RED_PLASTIC),
                box((0.12, 0.16, 0.5), (x - 0.76, 0, 0.36 if k % 2 else 0.31), RED_PLASTIC),   # lugs interlock
                cyl(0.06, 0.03, (x + 0.3, 0, 0.855), 8, "#9C2A24"),
                box((0.9, 0.012, 0.22), (x, -0.142, 0.5), "#FFFFFF", "sign", uv=("sign", 3, 7))]
    run.append(box((0.12, 0.16, 0.5), (2.31, 0, 0.36), RED_PLASTIC))
    out.append(Piece("PROP_Barrier_PoliceRun_01", 4.7, 0.86, run, 400, bevel=0.0, refs=["sv_04", "sv_09", "sv_14"],
                     decay="plastic"))
    # park steel bin: perforated drum on a post with a lid (separate from the three bin set pieces)
    out.append(Piece("PROP_Bin_Steel_01", 0.5, 1.0, [
        box((0.5, 0.5, 0.03), (0, 0, 0.015), STONE),
        cyl(0.2, 0.7, (0, 0, 0.1), 10, BLUE_STEEL), box((0.46, 0.46, 0.04), (0, 0, 0.84), GALV_D),
        box((0.2, 0.03, 0.12), (0, -0.2, 0.65), "#FFFFFF", "sign", uv=("sign", 0, 4))], 180, bevel=0.0,
        refs=["sv_05"], decay="metal"))
    # park bench: concrete ends, three timber slats on seat and back
    out.append(Piece("PROP_Bench_Park_01", 1.8, 0.85, [
        *[box((0.1, 0.5, 0.45), (x, 0, 0.225), STONE, "concrete", uv="world") for x in (-0.8, 0.8)],
        *[box((0.1, 0.05, 0.4), (x, 0.2, 0.65), STONE, "concrete", uv="world") for x in (-0.8, 0.8)],
        array(box((1.8, 0.12, 0.04), (0, -0.14, 0.47), TIMBER_BENCH), 3, (0, 0.14, 0)),
        array(box((1.8, 0.03, 0.12), (0, 0.22, 0.58), TIMBER_BENCH), 3, (0, 0, 0.14))], 260, bevel=0.0,
        refs=["sv_05"], decay="timber"))
    # signal housing: three-lamp black head with visors on a short stub, for hand-placed junction work
    out.append(Piece("PROP_SignalHousing_01", 0.5, 1.3, [
        cyl(0.04, 0.4, (0, 0, 0.0), 6, GALV),
        box((0.32, 0.26, 0.96), (0, 0, 0.88), SIG),
        *[box((0.22, 0.03, 0.22), (0, -0.14, z), c) for z, c in ((1.14, "#B3281E"), (0.88, "#D9A61B"), (0.62, "#2E9E4A"))],
        *[box((0.28, 0.1, 0.03), (0, -0.17, z + 0.13), SIG) for z in (1.14, 0.88, 0.62)]], 240, bevel=0.0,
        refs=["sv_14"], decay="plastic"))
    return out


def pieces() -> list[Piece]:
    return [*bus_halts(), *vendors(), *traffic_control()]
