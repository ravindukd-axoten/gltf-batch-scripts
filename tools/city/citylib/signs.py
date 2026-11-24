"""Road signs on the drive circle (P123): data/world/signs_delta_face.json placed against the BUILT road.

The sign file describes each sign as road chain + station + side + lateral offset behind the kerb + bottom height
(docs/research/delta-face-sign-placement.md). Its world numbers are drafts from the OSM road graph (+-3 m): fix 5
rebuilt Centre Road's carriageways, so the build resolves every sign here, after the layout:
- road signs: from the chain point, walk along the side normal to the first kerb of the built carriageway (road area +
  junctions, parking lane included, raised islands are holes), then `lateral_from_kerb_m` further. A sign whose
  offset would land in the next carriageway (a splitter island) goes to the island's middle.
- `median`: the raised island to that side; the chevron sits on its upstream nose, facing the traffic that meets it.
- `island`: the roundabout island; the chevron sits 0.7 m inside the island edge on the bearing to its entry.
Signs at the same spot facing the same way share one post (a plate hangs under its sign); boards get a twin post.
Wear and decay (`plan`, citylib/decay.py): each sign uses its age variant piece, posts lean (marker rx / ry), and
footings, collars, posters and empty clamps are added per post within the cell's triangle cap.

Output, like the vegetation markers: empties in the cell glb (citylib/blender_scene.py), `SIGN_<Type>[_<V>]` at the
face's bottom edge and `POST_Round_76` / `POST_Twin_76` at the foot with z scale = post height; the meshes are
Art/World/Signs/*.glb (tools/city/build_signs.py). The generic signs the roadside pass put on the circle
(config signs.replaces) are removed inside the circle band, so no spot carries two sign sets.
"""
from __future__ import annotations

import json
import math
import os

from . import decay as dec
from .kit import Instance

GROUP = "Signs"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TRIS_JSON = os.path.join(HERE, "signs_tris.json")
POST_TOP_M = 0.03          # post above the top sign
SHARE_M = 1.0              # signs closer than this, facing the same way, share a post
STACK_GAP_M = 0.05
JUNCTION_SLACK_M = 4.0    # a kerb this much beyond the usual one for that road side is a side-road mouth
CELL_CAP = 1190            # sign LOD0 triangles per cell (spec 1,200): decay decals only go where they fit
BAND_SHARE = 0.55          # single posts painted black / white (0.25 m bands), the rest bare galvanised
COLLAR_SHARE = 0.3         # posts set in a raised concrete collar, the rest in a flush mortar patch
TWIN_LEAN = 0.5            # twin-post boards lean half as much (two legs)
TWIN_TYPES = ("DIR_", "NAME_")   # boards and street-name plates stand on twin posts (sv_03)
KINK_SHARE = 0.6           # plain single posts carrying a bent sign: this share is kinked by a bumper strike
KINK_Z = (0.45, 0.85)      # kink height (m): car bumper / tuk footboard height
KINK_DEG = (5.0, 12.0)     # bend of the upper post at the kink
MISSING_TYPES = ("PLATE_", "WARN_", "INFO_Parking")   # never a regulatory sign, board or bus stop
MISSING_POOR = 0.2         # share of poor-condition add-on signs whose plate is gone (damaged: always)


def tris_table() -> dict[str, int]:
    if not os.path.exists(TRIS_JSON):
        return {}
    with open(TRIS_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def _yaw(fx: float, fy: float) -> float:
    """Instance yaw that turns the sign's front (local -y) to face along (fx, fy) (as roadside.yaw_facing)."""
    return math.atan2(fx, -fy)


def _first_exit(inside, c, n, far=30.0, step=0.1):
    """Distance along n from c (inside the surface) to where the surface ends; None if it never ends within far."""
    k = step
    while k <= far:
        if not inside(c[0] + n[0] * k, c[1] + n[1] * k):
            lo, hi = k - step, k
            for _ in range(12):
                mid = (lo + hi) / 2
                if inside(c[0] + n[0] * mid, c[1] + n[1] * mid):
                    lo = mid
                else:
                    hi = mid
            return hi
        k += step
    return None


def _first_entry(inside, c, n, start, far):
    k = start
    while k <= far:
        if inside(c[0] + n[0] * k, c[1] + n[1] * k):
            return k
        k += 0.05
    return None


def _into_road(inside, c, n):
    """The chain point if it lies on the carriageway, else the nearest point along +-n that does (draft +-3 m)."""
    if inside(*c):
        return c
    for k in [x * 0.25 for x in range(1, 49)]:
        for sg in (-1.0, 1.0):
            p = (c[0] + n[0] * k * sg, c[1] + n[1] * k * sg)
            if inside(*p):
                return (p[0] + n[0] * 0.3 * sg, p[1] + n[1] * 0.3 * sg) if inside(p[0] + n[0] * 0.3 * sg, p[1] + n[1] * 0.3 * sg) else p
    return None


def resolve(data: dict, lay) -> list[dict]:
    """Every sign instance with its built position: x, y (world), facing, kerb_m (chain point to the built kerb),
    post_off_m (post to the road surface), ok and why."""
    from shapely import ops
    from shapely.geometry import Point
    from shapely.prepared import prep

    road = ops.unary_union([lay.road_area, lay.junctions])
    rp = prep(road)
    med = lay.medians
    mp = prep(med) if med is not None and not med.is_empty else None

    def inside(x, y):
        return rp.contains(Point(x, y))

    out, pending = [], []
    for e in data["instances"]:
        r = {"id": e["id"], "type": e["type"], "piece": e["piece"], "side": e["side"], "ok": True, "why": ""}
        if e["side"] == "island":
            cx, cz = e["anchor"]["roundabout_centre"]
            b = math.radians(e["anchor"]["bearing_deg"])
            u = (math.sin(b), math.cos(b))
            edge = _first_entry(inside, (cx, cz), u, 0.5, 20.0)
            if edge is None or inside(cx, cz):
                x, y = e["world_xz"]
                r.update(ok=False, why="no island hole round the centre: draft position")
            else:
                x, y = cx + u[0] * (edge - 0.7), cz + u[1] * (edge - 0.7)
                r["island_r_m"] = round(edge, 2)
            r.update(x=x, y=y, facing=u)
        elif e["side"] == "median":
            c, n = tuple(e["chain_xz"]), tuple(e["normal_xz"])
            t = tuple(e["traffic_xz"])
            hit = None
            if mp is not None:
                k = 0.0
                while k <= 14.0:
                    if mp.contains(Point(c[0] + n[0] * k, c[1] + n[1] * k)):
                        hit = Point(c[0] + n[0] * k, c[1] + n[1] * k)
                        break
                    k += 0.2
            isl = None
            if hit is not None:
                geoms = getattr(med, "geoms", [med])
                isl = next((g for g in geoms if g.buffer(0.01).contains(hit)), None)
            if isl is None:
                x, y = e["world_xz"]
                r.update(ok=False, why="no raised island beside the chain point")
            else:
                pts = list(isl.exterior.coords)
                nose = min(pts, key=lambda p: p[0] * t[0] + p[1] * t[1])
                ctr = isl.centroid
                # walk from the nose along the traffic direction to the island's middle line
                x, y = nose[0] + t[0] * 0.9, nose[1] + t[1] * 0.9
                lat = ((ctr.x - x) * n[0] + (ctr.y - y) * n[1])
                x, y = x + n[0] * lat, y + n[1] * lat
                if not isl.contains(Point(x, y)):
                    q = isl.representative_point()
                    x, y = q.x, q.y
                    r["why"] = "nose point outside the island: representative point"
            r.update(x=x, y=y, facing=(-t[0], -t[1]))
        else:
            c0, n = tuple(e["chain_xz"]), tuple(e["normal_xz"])
            t = tuple(e["traffic_xz"])
            got = _kerbside(inside, road, c0, n, float(e["lateral_from_kerb_m"]))
            if got is None:
                x, y = e["world_xz"]
                r.update(ok=False, why="chain point not near the built road: draft position")
            else:
                x, y, r["kerb_m"], r["why"] = got
                if r["kerb_m"] is None:
                    r["ok"] = False
            r.update(x=x, y=y, facing=(-t[0], -t[1]))
            pending.append((r, e))
        out.append(r)
    # junction mouths: the side normal runs up a side road (kerb far beyond the usual for that road side) or never
    # meets a kerb; slide the sign along its road (upstream first) to the nearest station with a usual kerb
    usual: dict[tuple, list[float]] = {}
    for r, e in pending:
        if r.get("kerb_m") is not None and not r["why"]:
            usual.setdefault((e["anchor"].get("road"), e["side"]), []).append(r["kerb_m"])
    for r, e in pending:
        ks = sorted(usual.get((e["anchor"].get("road"), e["side"]), []))
        med = ks[len(ks) // 2] if ks else None
        k = r.get("kerb_m")
        if med is None or (k is not None and k <= med + JUNCTION_SLACK_M):
            continue
        c0, n, t = tuple(e["chain_xz"]), tuple(e["normal_xz"]), tuple(e["traffic_xz"])
        for step in [s * 1.0 for s in range(1, 21)]:
            hit = None
            for sg in (-1.0, 1.0):
                c = (c0[0] + t[0] * step * sg, c0[1] + t[1] * step * sg)
                got = _kerbside(inside, road, c, n, float(e["lateral_from_kerb_m"]))
                if got and got[2] is not None and abs(got[2] - med) <= JUNCTION_SLACK_M and \
                        road.distance(Point(got[0], got[1])) >= 0.3:
                    hit = (got, sg * step)
                    break
            if hit:
                (x, y, kerb, why), moved = hit
                r.update(x=x, y=y, kerb_m=kerb, ok=True,
                         why=f"junction mouth: moved {moved:+.0f} m along the road" + (f"; {why}" if why else ""))
                break
    for r in out:
        e = next(i for i in data["instances"] if i["id"] == r["id"])
        r["post_off_m"] = round(road.distance(Point(r["x"], r["y"])), 3)
        r["in_lane"] = inside(r["x"], r["y"])
        r["draft_err_m"] = round(math.dist((r["x"], r["y"]), e["world_xz"]), 2)
    return out


def _kerbside(inside, road, c0, n, off):
    """Kerb-side post: from the chain point (pulled onto the carriageway) along the side normal to the first kerb, then
    `off` further, then out until the post clears every road surface by `off` (flared mouths and bends). Returns
    (x, y, kerb_m, why) with kerb_m from the chain point, kerb_m None when no kerb within 30 m; None off the road."""
    from shapely.geometry import Point
    c = _into_road(inside, c0, n)
    if c is None:
        return None
    d = _first_exit(inside, c, n)
    if d is None:
        x, y = c0
        return x, y, None, "no kerb within 30 m"
    why = ""
    back = _first_entry(inside, c, n, d + 0.05, d + off + 0.6)
    if back is not None:   # an island narrower than the offset: the post on its middle line
        k = (d + back) / 2
        why = f"island {back - d:.1f} m wide: post on its middle line"
    else:
        k = d + off
        while k < d + off + 2.0 and 0.0 < road.distance(Point(c[0] + n[0] * (k + 0.1), c[1] + n[1] * (k + 0.1))) and \
                road.distance(Point(c[0] + n[0] * k, c[1] + n[1] * k)) < off - 0.1:
            k += 0.1
    kp = (c[0] + n[0] * d, c[1] + n[1] * d)
    return c[0] + n[0] * k, c[1] + n[1] * k, round((kp[0] - c0[0]) * n[0] + (kp[1] - c0[1]) * n[1], 2), why


def mount(data: dict, res: list[dict]) -> list[dict]:
    """Group the resolved signs onto posts. Returns posts: {x, y, facing, twin, signs: [(id, piece, bottom, h, facing)]}."""
    face = {k["type"]: k["face_m"] for k in data["kit"]}
    bottom_default = {k["type"]: k["bottom_m"] for k in data["kit"]}
    inst = {e["id"]: e for e in data["instances"]}
    posts: list[dict] = []
    for r in res:
        e = inst[r["id"]]
        w, h = face[e["type"]]
        b = float(e.get("bottom_height_m", bottom_default[e["type"]]))
        twin = e["type"].startswith(TWIN_TYPES)
        host = None
        if not twin or e["type"].startswith("NAME_"):   # signs share a post as on site (name plates: one pair)
            host = next((p for p in posts if p["twin"] == twin and
                         math.dist((p["x"], p["y"]), (r["x"], r["y"])) < SHARE_M), None)
        if host is None:
            host = {"x": r["x"], "y": r["y"], "facing": r["facing"], "twin": twin, "signs": []}
            posts.append(host)
        host["signs"].append([r["id"], e["piece"], b, h, list(r["facing"])])
    for p in posts:   # stack per facing: the top sign keeps its height, the ones below hang under it without overlap
        p["signs"].sort(key=lambda s: -(s[2] + s[3]))
        for i in range(1, len(p["signs"])):
            s = p["signs"][i]
            above = [a for a in p["signs"][:i] if a[4][0] * s[4][0] + a[4][1] * s[4][1] > 0.9]
            if above and s[2] + s[3] > above[-1][2] - STACK_GAP_M:
                s[2] = round(max(0.9, above[-1][2] - STACK_GAP_M - s[3]), 3)
        p["height"] = round(max(s[2] + s[3] for s in p["signs"]) + POST_TOP_M, 3)
    return posts


def sign_piece(e: dict) -> str:
    """The decay variant of a sign's kit piece (build_signs.py builds every one the sign file uses)."""
    d = e["decay"]
    return e["piece"] + dec.variant_suffix(d["wear"], d["bent"])


def post_piece(twin: bool, band: bool, wear: int, kink: str = "") -> str:
    """kink: "" straight, "Lo" the stub below a kink, "Up" the bent upper length (plain single posts only)."""
    base = "POST_Twin_76" if twin else "POST_Round_76" + ("_Band" if band else "") + (f"_Kink{kink}" if kink else "")
    return base + dec.variant_suffix(wear)


def kink_of(p: dict, top: dict, any_bent: bool, band: bool) -> tuple[float, float, float] | None:
    """(height m, bend deg, azimuth deg) of a seeded bumper-strike kink, or None. Plain single posts carrying a bent
    sign only; the post folds away along the traffic it serves (the car hits it going that way), +-40 deg."""
    seed = top["seed"]
    if p["twin"] or band or not any_bent or (seed >> 16) % 100 >= KINK_SHARE * 100:
        return None
    kz = KINK_Z[0] + (KINK_Z[1] - KINK_Z[0]) * ((seed >> 20) % 41) / 40.0
    deg = KINK_DEG[0] + (KINK_DEG[1] - KINK_DEG[0]) * ((seed >> 24) % 15) / 14.0
    az = math.degrees(math.atan2(-p["facing"][1], -p["facing"][0])) + ((seed >> 2) % 81 - 40)
    return round(kz, 3), round(deg, 2), round(az % 360.0, 1)


def is_missing(e: dict) -> bool:
    """A plate gone from its clamps (stolen / fallen): damaged add-on signs, and a seeded share of poor ones."""
    if not e["type"].startswith(MISSING_TYPES):
        return False
    return e["condition"] == "damaged" or (e["condition"] == "poor" and (e["decay"]["seed"] >> 18) % 100 < MISSING_POOR * 100)


def plan(data: dict, posts: list[dict], ground=lambda x, y: 0.0, cap: int = CELL_CAP) -> tuple[list[Instance], dict]:
    """Every marker for the mounted posts with wear and decay (citylib/decay.py): variant pieces by each sign's
    wear, the post's lean (from its top sign; signs ride the leaning post), the post's paint and wear (the oldest
    sign on it: posts outlive their signs), a missing plate (damaged) left as an empty clamp, then footings and
    posters while the cell stays under `cap`. Returns (instances, stats)."""
    from . import grid
    inst = {e["id"]: e for e in data["instances"]}
    tris = tris_table()
    out: list[Instance] = []
    by_cell: dict[str, int] = {}
    extras: list[tuple[int, str, list[Instance]]] = []
    counts = {"lean_deg_max": 0.0, "kinked_posts": 0, "missing_plates": 0, "banded_posts": 0, "footings": 0, "collars": 0,
              "posters": 0, "skipped_for_budget": 0}
    for p in posts:
        cid = grid.cell_id_at(p["x"], p["y"])
        top = inst[p["signs"][0][0]]["decay"]
        wear = max(inst[s[0]]["decay"]["wear"] for s in p["signs"])
        band = not p["twin"] and top["pick"] < BAND_SHARE
        lean = top["lean_deg"] * (TWIN_LEAN if p["twin"] else 1.0)
        L = dec.lean_matrix(lean, top["lean_az_deg"])
        z = ground(p["x"], p["y"])
        yaw = _yaw(*p["facing"])
        rx, ry, rz = dec.compose(L, yaw)
        kink = kink_of(p, top, any(inst[s[0]]["decay"]["bent"] for s in p["signs"]), band)
        if kink:   # stub to the kink, then the upper length folded by B about the kink point (signs ride it)
            kz, kdeg, kaz = kink
            LB = dec.matmul(L, dec.lean_matrix(kdeg, kaz))
            K = dec.apply(L, (0.0, 0.0, kz))
            ux, uy, uz = dec.compose(LB, yaw)
            cell = [Instance(post_piece(False, False, wear, "Lo"), p["x"], p["y"], z, rz, 1.0, 1.0, kz, rx, ry),
                    Instance(post_piece(False, False, wear, "Up"), p["x"] + K[0], p["y"] + K[1], z + K[2], uz,
                             1.0, 1.0, round(p["height"] - kz, 3), ux, uy)]
            counts["kinked_posts"] += 1
        else:
            cell = [Instance(post_piece(p["twin"], band, wear), p["x"], p["y"], z, rz, 1.0, 1.0, p["height"], rx, ry)]

        def ride(hz, f):   # world offset and Euler of a piece at height hz on the (leaning, maybe kinked) post
            if kink and hz > kink[0]:
                o = dec.apply(LB, (0.0, 0.0, hz - kink[0]))
                return (K[0] + o[0], K[1] + o[1], K[2] + o[2]), dec.compose(LB, _yaw(*f))
            return dec.apply(L, (0.0, 0.0, hz)), dec.compose(L, _yaw(*f))
        for sid, piece, b, h, f in p["signs"]:
            e = inst[sid]
            if is_missing(e):   # empty clamp straps where the plate was
                counts["missing_plates"] += 1
                hzs = [b + h * 0.5] if h < 0.3 else [b + h * 0.22, b + h * 0.78]
                names = ["POST_Clamp_Empty"] * len(hzs)
            else:
                hzs, names = [b], [sign_piece(e)]
            for name, hz in zip(names, hzs):
                o, (ex, ey, ez) = ride(hz, f)
                cell.append(Instance(name, p["x"] + o[0], p["y"] + o[1], z + o[2], ez, 1.0, 1.0, 1.0, ex, ey))
        out += cell
        by_cell[cid] = by_cell.get(cid, 0) + sum(tris.get(i.piece, 0) for i in cell)
        counts["lean_deg_max"] = max(counts["lean_deg_max"], round(lean, 2))
        counts["banded_posts"] += band
        # decals, in priority order: the foot's contact patch first, then posters
        seed = top["seed"]
        collar = not p["twin"] and (seed >> 8) % 100 < COLLAR_SHARE * 100
        legs = [(-0.5, 0.0), (0.5, 0.0)] if p["twin"] else [(0.0, 0.0)]
        c, s_ = math.cos(yaw), math.sin(yaw)
        foot = [Instance("POST_Footing_Collar" if collar else "POST_Footing_A", p["x"] + lx * c, p["y"] + lx * s_,
                         z, yaw) for lx, _ in legs]
        extras.append((0, cid, foot))
        if any(inst[s[0]]["decay"]["decal"] for s in p["signs"]) and not p["twin"]:
            hz = 1.1 + ((seed >> 4) % 60) / 100.0
            turn = (0.0, 0.7, -0.7, math.pi)[(seed >> 12) % 4]
            if kink and hz > kink[0]:
                q = dec.apply(LB, (0.0, 0.0, hz - kink[0]))
                o = (K[0] + q[0], K[1] + q[1], K[2] + q[2])
                ex, ey, ez = dec.compose(LB, yaw + turn)
            else:
                o = dec.apply(L, (0.0, 0.0, hz))
                ex, ey, ez = dec.compose(L, yaw + turn)
            extras.append((1, cid, [Instance(f"POST_Poster_{'ABC'[seed % 3]}", p["x"] + o[0], p["y"] + o[1],
                                             z + o[2], ez, 1.0, 1.0, 1.0, ex, ey)]))
    for _, cid, pieces in sorted(extras, key=lambda t: t[0]):
        t = sum(tris.get(i.piece, 0) for i in pieces)
        if by_cell.get(cid, 0) + t > cap:
            counts["skipped_for_budget"] += 1
            continue
        by_cell[cid] = by_cell.get(cid, 0) + t
        out += pieces
        for i in pieces:
            k = {"POST_Footing_A": "footings", "POST_Footing_Collar": "collars"}.get(i.piece, "posters")
            counts[k] += 1
    stats = {"lod0_tris": sum(by_cell.values()), "lod0_tris_per_cell": dict(sorted(by_cell.items())),
             "decay": counts}
    return out, stats


def place(cfg: dict, lay, dress) -> dict:
    """Config "signs": {"file": repo-relative sign file, "replaces": roadside sign pieces removed in the circle band}."""
    sc = cfg.get("signs")
    if not sc:
        return {}
    from shapely.geometry import Point

    with open(os.path.join(REPO, sc["file"]), encoding="utf-8") as fh:
        data = json.load(fh)
    res = resolve(data, lay)
    posts = mount(data, res)
    # the roadside pass's generic signs inside the circle band give way to the kit
    band = lay.focus.buffer(float(sc.get("band_m", 0.0))) if lay.focus is not None else None
    drop = set(sc.get("replaces", []))
    near = [(r["x"], r["y"]) for r in res]
    keep, removed = [], 0
    for g, i in dress.placements:
        if i.piece in drop and ((band is not None and band.contains(Point(i.x, i.y))) or
                                (band is None and any(math.dist((i.x, i.y), q) < 40.0 for q in near))):
            removed += 1
            continue
        keep.append((g, i))
    dress.placements[:] = keep
    from .roadside import _ground_z

    insts, pst = plan(data, posts, lambda x, y: _ground_z(lay, x, y))
    for i in insts:
        dress.add(GROUP, i)
    bad = [r for r in res if not r["ok"] or r["in_lane"]]
    stats = {"signs": len(res), "posts": len(posts), "twin_posts": sum(p["twin"] for p in posts),
             "replaced_roadside_signs": removed, **pst,
             "draft_error_m": {"max": max(r["draft_err_m"] for r in res),
                               "mean": round(sum(r["draft_err_m"] for r in res) / len(res), 2)},
             "unresolved": [f"{r['id']}: {r['why']}" for r in bad],
             "notes": [f"{r['id']}: {r['why']}" for r in res if r["ok"] and r["why"]]}
    lay.sign_resolved, lay.sign_posts = res, posts
    return stats
