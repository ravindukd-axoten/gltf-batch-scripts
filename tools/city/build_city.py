"""Batch Island city pipeline: OpenStreetMap -> Shapely layout -> per-cell glTF for Unity.

Run headless from the repo root (Blender 5.3, its bundled Python, Shapely in tools/city/vendor):

    blender -b -P tools/city/build_city.py -- --config tools/city/config/delta_face.json

Options (after the "--"):
    --config PATH      area config (default tools/city/config/fort_loop.json, which extends delta_face.json)
    --cells-out DIR    cell .glb folder (default unity/BatchIsland/Assets/BatchIsland/Art/World/Cells)
    --kit-out DIR      kit .glb folder (default unity/BatchIsland/Assets/BatchIsland/Art/World/Kit)
    --out DIR          intermediates: report.json, the .blend (default tools/city/out, gitignored)
    --only IDS         comma-separated cell ids to rebuild (others are left alone)
    --adopt-cells      full build may replace cells built by another config (delta_face / fort_loop)
    --no-export        build the Blender scene and report only
    --export-kit       with --only, also export the kit .glb pieces
The same script runs inside a live Blender (MCP execute_python): call main([...]) with the args list.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
for p in (os.path.join(HERE, "vendor"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import bpy  # noqa: E402

from citylib import blender_scene, cell_agent, cells, dressing, geo, grid, kit, layout, markings, osm  # noqa: E402
from citylib import config as cfglib  # noqa: E402
from citylib import drive_loop, light_bake  # noqa: E402

DEFAULT_CELLS = os.path.join(REPO, "unity/BatchIsland/Assets/BatchIsland/Art/World/Cells")
DEFAULT_KIT = os.path.join(REPO, "unity/BatchIsland/Assets/BatchIsland/Art/World/Kit")
# per-cell ground light maps (citylib/lightmap.py), next to the cell glbs; Unity CellBuilder picks them up by cell id
DEFAULT_MAPS = os.path.join(REPO, "unity/BatchIsland/Assets/BatchIsland/Art/World/Cells/GroundLight")
ROUTES_DIR = "unity/BatchIsland/Assets/BatchIsland/Data/World/Routes"


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="build_city.py")
    ap.add_argument("--config", default=os.path.join(HERE, "config/fort_loop.json"))
    ap.add_argument("--cells-out", default=DEFAULT_CELLS)
    ap.add_argument("--kit-out", default=DEFAULT_KIT)
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--only", default="")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--adopt-cells", action="store_true",
                    help="allow a full build to overwrite/prune cells another config built (delta_face vs fort_loop)")
    ap.add_argument("--export-kit", action="store_true", help="with --only: also export the kit pieces (new props)")
    ap.add_argument("--maps-out", default=DEFAULT_MAPS)
    ap.add_argument("--no-bake", action="store_true", help="skip vertex AO and ground light maps (fast layout checks)")
    ap.add_argument("--routes-out", default=os.path.join(REPO, ROUTES_DIR),
                    help="where ROUTE_/SPAWNS_/BLOCKS_ json go (point it outside Assets for a staged build)")
    ap.add_argument("--no-provenance", action="store_true", help="leave docs/provenance/provenance.csv alone (staged builds)")
    return ap.parse_args(argv)


def _section(ob) -> str:
    """Which part of a cell an object belongs to: LOD0, LOD1 or COL."""
    while ob is not None:
        for tag in ("_LOD0", "_LOD1", "_COL"):
            if ob.name.endswith(tag):
                return tag[1:]
        ob = ob.parent
    return "ROOT"


def cell_report(coll, budgets: dict) -> dict:
    deps = bpy.context.evaluated_depsgraph_get()
    tris = {"LOD0": 0, "LOD1": 0, "COL": 0}
    mats: dict[str, set] = {"LOD0": set(), "LOD1": set()}
    submeshes = {"LOD0": 0, "LOD1": 0}
    meshes_by_section: dict[str, set] = {"LOD0": set(), "LOD1": set(), "COL": set()}
    nodes = len(coll.objects)
    instances = 0
    buildings = []
    kit_counts: dict[str, int] = {}
    for ob in coll.objects:
        if ob.name.startswith("bld_") and ob.type == "EMPTY":
            buildings.append(ob.name)
        if ob.type != "MESH":
            continue
        sec = _section(ob)
        me = ob.evaluated_get(deps).data
        me.calc_loop_triangles()
        n = len(me.loop_triangles)
        tris[sec] = tris.get(sec, 0) + n
        meshes_by_section.setdefault(sec, set()).add(ob.data.name)
        if ob.data.name in kit.PIECES:
            instances += 1
            kit_counts[ob.data.name] = kit_counts.get(ob.data.name, 0) + 1
        if sec in mats:
            used = {me.materials[p.material_index].name for p in me.polygons if me.materials}
            mats[sec] |= used
            submeshes[sec] += len(used)
    b = budgets
    return {
        "tris": tris,
        "budget": {"lod0_tris": b["cell_lod0_tris"], "lod1_tris": b["cell_lod1_tris"], "materials": b["cell_materials"]},
        "within_budget": tris["LOD0"] <= b["cell_lod0_tris"] and tris["LOD1"] <= b["cell_lod1_tris"]
        and len(mats["LOD0"]) <= b["cell_materials"],
        "materials": {k: sorted(v) for k, v in mats.items()},
        "draw_calls_estimate": {
            "LOD0_unbatched_submeshes": submeshes["LOD0"],
            "LOD0_srp_batcher_materials": len(mats["LOD0"]),
            "LOD1_submeshes": submeshes["LOD1"],
        },
        "objects": {"nodes": nodes, "kit_instances": instances, "buildings": len(buildings),
                    "unique_meshes_lod0": len(meshes_by_section["LOD0"])},
        "kit_instances": dict(sorted(kit_counts.items())),
        "building_ids": sorted(buildings),
    }


def _mesh_tris(me) -> int:
    me.calc_loop_triangles()
    return len(me.loop_triangles)


PROVENANCE = os.path.join(REPO, "docs/provenance/provenance.csv")
PROV_COLUMNS = ["asset_path", "asset_type", "creator_kind", "creator", "source", "licence", "licence_proof",
                "date_added", "notes"]


def update_provenance(paths: list[str], cfg: dict, osm_base: str, managed_dirs: list[str]) -> tuple[int, int]:
    """Keep docs/provenance/provenance.csv in step with the generated files: add rows for new files,
    drop rows for generated files that no longer exist, keep existing rows (and their dates) as they are."""
    import csv
    import datetime as dt
    with open(PROVENANCE, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    managed = [os.path.relpath(d, REPO).replace(os.sep, "/") + "/" for d in managed_dirs]
    current = {os.path.relpath(p, REPO).replace(os.sep, "/") for p in paths}
    kept = [r for r in rows if not any(r["asset_path"].startswith(m) for m in managed)
            or r["asset_path"] in current or os.path.exists(os.path.join(REPO, r["asset_path"]))]
    removed = len(rows) - len(kept)
    have = {r["asset_path"] for r in kept}
    today = dt.date.today().isoformat()
    added = 0
    for rel in sorted(current - have):
        base = os.path.basename(rel)
        if base.startswith("cell_"):
            kind, lic = "model/world-cell", "ODbL-1.0 AND LicenseRef-Axoten-Proprietary"
            notes = (f"Generated from {cfg['osm_file']} (OSM base {osm_base}). Contains information from "
                     "OpenStreetMap, (c) OpenStreetMap contributors, available under the ODbL 1.0; "
                     "attribution required wherever the map geometry is shown. Regenerate, do not edit.")
            proof = "https://www.openstreetmap.org/copyright; tools/city/README.md (Attribution)"
        elif base.startswith("ROUTE_"):
            kind, lic = "data/route", "ODbL-1.0 AND LicenseRef-Axoten-Proprietary"
            notes = (f"Driven route centreline (2 m samples) from the config's area_strip.route, OSM node positions from {cfg['osm_file']}; "
                     "(c) OpenStreetMap contributors, ODbL 1.0. Regenerate, do not edit.")
            proof = "https://www.openstreetmap.org/copyright; tools/city/README.md (Attribution)"
        elif base.startswith("TEX_GroundLight_"):
            kind, lic = "texture/world-lightmap", "ODbL-1.0 AND LicenseRef-Axoten-Proprietary"
            notes = (f"Per-cell ground light map (R sky visibility, G/B/A sun visibility for the golden hour, noon and blue hour "
                     f"presets) baked with Cycles by tools/city/citylib/light_bake.py from the cell geometry built from {cfg['osm_file']}; "
                     "(c) OpenStreetMap contributors, ODbL 1.0. Regenerate, do not edit.")
            proof = "https://www.openstreetmap.org/copyright; tools/city/README.md (Attribution)"
        elif base.startswith("ENV_"):
            kind, lic = "model/world-environment", "ODbL-1.0 AND LicenseRef-Axoten-Proprietary"
            notes = ("Environment beyond the cells (open sea / generic distant-city block masses), placed from the OSM-derived area_strip and coastline "
                     f"({cfg['osm_file']}); (c) OpenStreetMap contributors, ODbL 1.0. Regenerate, do not edit.")
            proof = "https://www.openstreetmap.org/copyright; tools/city/README.md (Attribution)"
        else:
            kind = "model/street-prop" if base.startswith("PROP_") else "model/kit-piece"
            lic = "LicenseRef-Axoten-Proprietary"
            notes = "Greybox kit/prop built procedurally by the city pipeline; no external data. Regenerate, do not edit."
            proof = "IP assignment in Axoten contracts (Safety doc > Contracts)"
        kept.append({"asset_path": rel, "asset_type": kind, "creator_kind": "script",
                     "creator": f"tools/city/build_city.py (Blender {bpy.app.version_string}, Shapely)",
                     "source": "tools/city/build_city.py", "licence": lic, "licence_proof": proof,
                     "date_added": today, "notes": notes})
        added += 1
    with open(PROVENANCE, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=PROV_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(kept)
    return added, removed


def main(argv: list[str]) -> dict:
    args = parse_args(argv)
    t0 = time.perf_counter()
    cfg_path = os.path.abspath(args.config)
    if not args.no_export and not args.adopt_cells:
        # fail before the slow build: a full run prunes, and any run overwrites, cells owned by another config
        foreign = cell_agent.foreign_cells(args.cells_out, os.path.relpath(cfg_path, REPO))
        if foreign and not args.only:
            raise SystemExit("refusing a full build: cells in %s were built by %s; rebuild that config or pass "
                             "--adopt-cells to take them over (pruning any cell this config does not make)"
                             % (args.cells_out, ", ".join("%s (%d cells)" % (k, len(v)) for k, v in foreign.items())))
    cfg = cfglib.load(cfg_path)
    osm_list = cfglib.osm_files(cfg)
    cfg["osm_file"] = " + ".join(osm_list)  # provenance notes and extras name every extract used
    data = osm.parse_osm_files([os.path.join(HERE, f) for f in osm_list])
    lay = layout.build_layout(cfg, data)
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    dress = dressing.dress(cfg, data, lay)
    lay.stats["dressing"] = dress.stats
    from citylib import road_blocks, road_network  # noqa: E402  (ROADS2: barriers on the drive circle's exits)
    net = road_network.network_from_config(cfg, data, geo.CITYHUB)
    if net is not None:
        _, lay.road_block_walls = road_blocks.place(net, lay.heights.road, dress)
        lay.stats["road_network"] = {"segments": len(net["segments"]), "blocks": len(net["blocks"]),
                                     "loop_m": net["drive_loop"]["length_m"]}
    marks = markings.build(cfg, data, lay, dress)
    from citylib import roadside  # noqa: E402  (P2: traffic furniture and decals need the markings)
    lay.stats["roadside"] = roadside.dress_traffic(cfg, data, lay, dress, marks)
    drive = blocks = None
    if cfg.get("drive_loop"):
        # M6 drive circle: barrier rows on every road that leaves the loop, and the loop's road-surface check
        drive, blocks = drive_loop.dress_blocks(cfg, data, lay, dress)
    from citylib import street_life  # noqa: E402  (P388: street furniture along the route, config street_life)
    lay.stats["street_life"] = street_life.dress_furniture(cfg, data, lay, dress)
    from citylib import street_signs  # noqa: E402  (P388: more shop and wall signs on facades facing the route)
    lay.stats["street_signs"] = street_signs.dress_signs(cfg, data, lay, dress)
    from citylib import street_planting  # noqa: E402  (P388: palms, street trees and ground planting along the route)
    lay.stats["street_planting"] = street_planting.dress_planting(cfg, data, lay, dress)
    from citylib import frontage_paving, pavement_edge  # noqa: E402  (SLICE4d: hotel frontage paver, manholes)
    lay.frontage_paving = frontage_paving.zones(cfg, lay)
    lay.stats["frontage_covers"] = pavement_edge.covers(cfg, lay, marks, dress)
    lay.stats["markings"] = marks.stats
    from citylib import poles  # noqa: E402  (P134: pole lines and cable spans on the built kerb)
    lay.stats["poles"] = poles.place(cfg, lay, dress)
    from citylib import road_edge  # noqa: E402  (P117 WS-0339: the P92b road edge kit on every kerb)
    lay.stats["road_edge"] = road_edge.apply(cfg, lay, net, dress, marks)
    from citylib import signs  # noqa: E402  (P123: the sign kit, placed against the built road)
    lay.stats["signs"] = signs.place(cfg, lay, dress)
    cell_geoms = cells.build_cells(lay, dress, only, marks)
    lay.stats["material_fold"] = cells.fold_materials(cell_geoms, cfg.get("material_fold", {}))
    t_layout = time.perf_counter() - t0

    blender_scene.reset_scene()
    mats = blender_scene.ensure_materials()
    kit_meshes = blender_scene.build_kit(mats)
    extras = {
        "generator": "tools/city/build_city.py",
        "config": os.path.relpath(cfg_path, REPO),
        "osm_file": cfg["osm_file"],
        "osm_base": data.base_timestamp,
        "attribution": "(c) OpenStreetMap contributors, ODbL 1.0",
        "world_origin_lat_lon": [geo.CITYHUB_ORIGIN_LAT, geo.CITYHUB_ORIGIN_LON],
        "projection": "local Transverse Mercator, WGS84, k0=1, centred on the world origin",
        "unity_y": "metres above mean sea level",
    }
    colls = {cg.id: blender_scene.build_cell(cg, mats, kit_meshes, extras) for cg in cell_geoms}
    env_name = f"ENV_SeaHorizon_{cfglib.env_suffix(cfg)}"
    blender_scene.build_env(env_name, cells.sea_horizon(lay), mats, extras)
    backdrop_name = env_name.replace("SeaHorizon", "CityBackdrop")
    blender_scene.build_env(backdrop_name, cells.city_backdrop(lay), mats, extras)
    # baked occlusion (vertex AO in COLOR_0.A, per-cell ground light maps) with every cell in the scene
    bake = None
    if not args.no_bake:
        maps_dir = args.maps_out if not args.no_export else os.path.join(args.out, "GroundLight")
        bake = light_bake.bake_city(list(colls), {cg.id: cg.origin for cg in cell_geoms}, maps_dir,
                                    lay.heights.road, REPO, prune=only is None)

    report = {
        "generator": "tools/city/build_city.py",
        "blender": bpy.app.version_string,
        "config": os.path.relpath(cfg_path, REPO),
        "osm_file": cfg["osm_file"],
        "osm_base": data.base_timestamp,
        "world_origin": {"lat": geo.CITYHUB_ORIGIN_LAT, "lon": geo.CITYHUB_ORIGIN_LON},
        "cell_size_m": grid.CELL_SIZE,
        "layout": lay.stats,
        "kit": {name: {"tris": _mesh_tris(kit_meshes[name]), "width_m": p.width, "height_m": p.height,
                       "budget_tris": kit.max_tris(name), "within_budget": _mesh_tris(kit_meshes[name]) <= kit.max_tris(name)}
                for name, p in kit.PIECES.items() if name in kit_meshes},
        "cells": {cid: cell_report(c, cfg["budgets"]) for cid, c in colls.items()},
    }
    for cg in cell_geoms:   # P117: dressing the cell trim dropped (citylib/cell_trim.py)
        if cg.trimmed and cg.id in report["cells"]:
            report["cells"][cg.id]["trimmed"] = cg.trimmed
    report["totals"] = {
        "cells": len(colls),
        "tris_lod0": sum(c["tris"]["LOD0"] for c in report["cells"].values()),
        "tris_lod1": sum(c["tris"]["LOD1"] for c in report["cells"].values()),
        "kit_instances": sum(c["objects"]["kit_instances"] for c in report["cells"].values()),
        "cells_over_budget": [k for k, c in report["cells"].items() if not c["within_budget"]],
    }

    if bake is not None:
        report["bake"] = {k: v for k, v in bake.items() if k != "files"}
    os.makedirs(args.out, exist_ok=True)
    written = list(bake["files"]) if bake is not None and not args.no_export else []
    if not args.no_export:
        blender_scene.to_export_frame()
        try:
            for cid in colls:
                path = os.path.join(args.cells_out, f"{cid}.glb")
                blender_scene.export_collection(cid, path)
                written.append(path)
            if only is not None and args.export_kit:
                written += blender_scene.export_kit(args.kit_out)
            if only is None:
                written += blender_scene.export_kit(args.kit_out)
                for name in (env_name, backdrop_name):
                    env_path = os.path.join(args.kit_out, f"{name}.glb")
                    blender_scene.export_collection(name, env_path)
                    written.append(env_path)
                # drop cells from earlier runs that this config no longer produces
                for f in sorted(os.listdir(args.cells_out)):
                    if f.startswith("cell_") and f.endswith(".glb") and f[:-4] not in colls:
                        os.remove(os.path.join(args.cells_out, f))
                        if os.path.exists(os.path.join(args.cells_out, f + ".meta")):
                            os.remove(os.path.join(args.cells_out, f + ".meta"))
        finally:
            blender_scene.to_export_frame()  # back to the true frame for previews and the saved .blend
    route = layout.route_line(cfg["area_strip"])
    # area_strip.route.export false: the route only shapes the build area (the drive circle closes the Fort loop with
    # road blocks, so its area strip is no longer a driven route; the drive loop writes ROUTE_DriveCircle instead)
    export_route = cfg["area_strip"].get("route", {}).get("export", True)
    if net is not None:   # ROADS2: the driven route is the road network's drive loop, not the scenery strip route
        from shapely.geometry import LineString  # noqa: E402
        route = LineString(net["drive_loop"]["polyline"])
    if route is not None and export_route and not args.no_export:
        # the driven loop as data for Unity (centreline checks now; AI traffic and timed runs later):
        # world metres, Unity x = east, z = north, y = road surface; points every 2 m along the route
        asset = cfg["area_strip"]["route"].get("asset") or cfglib.env_suffix({'name': cfg['name']})
        rpath = os.path.join(args.routes_out, f"ROUTE_{asset}.json")
        os.makedirs(os.path.dirname(rpath), exist_ok=True)
        n = int(route.length // 2.0)
        pts = [route.interpolate(k * 2.0) for k in range(n + 1)]
        with open(rpath, "w", encoding="utf-8") as fh:
            json.dump({"name": cfg["name"], "generator": "tools/city/build_city.py", "config": os.path.relpath(cfg_path, REPO),
                       "attribution": "(c) OpenStreetMap contributors, ODbL 1.0", "length_m": round(route.length, 1),
                       "step_m": 2.0, "road_y": lay.heights.road, "closed": route.coords[0] == route.coords[-1],
                       "x": [round(p.x, 2) for p in pts], "z": [round(p.y, 2) for p in pts],
                       # HEIGHTS 2026-11-24: per-sample road surface where the levels file grades the road (else road_y)
                       **({"y": [round(lay.heights.road + lay.terrain.grade(p.x, p.y), 2) for p in pts]}
                          if getattr(lay.terrain, "grades", None) else {})}, fh)
        written.append(rpath)
    if drive is not None and not args.no_export:
        written += drive_loop.write_assets(cfg, drive, blocks, lay.heights.road, args.routes_out, os.path.relpath(cfg_path, REPO))
    if drive is not None:
        report["drive_loop"] = lay.stats["drive_loop"]
    by_cell: dict[str, list] = {}
    for sp in marks.spawns:
        by_cell.setdefault(grid.cell_id_at(sp["x"], sp["y"]), []).append(sp)
    report["spawn_points"] = {cid: {g: sum(1 for sp in v if sp["group"] == g) for g in sorted({sp["group"] for sp in v})}
                              for cid, v in sorted(by_cell.items())}
    if marks.spawns and not args.no_export:
        # parked-vehicle spawn points (car park, tuk rank, van line) as data: the game spawns the cars, none are baked.
        # World metres, x = east, z = north; yaw is the heading in degrees clockwise from north.
        spath = os.path.join(args.routes_out, f"SPAWNS_{cfglib.env_suffix({'name': cfg['name']})}.json")
        with open(spath, "w", encoding="utf-8") as fh:
            json.dump({"name": cfg["name"], "generator": "tools/city/build_city.py", "config": os.path.relpath(cfg_path, REPO),
                       "attribution": "(c) OpenStreetMap contributors, ODbL 1.0", "road_y": lay.heights.road,
                       "points": [{"kind": sp["kind"], "group": sp["group"], "cell": grid.cell_id_at(sp["x"], sp["y"]),
                                   "x": sp["x"], "z": sp["y"], "yaw_deg": sp["yaw_deg"]} for sp in marks.spawns]}, fh, indent=1)
        written.append(spath)
    report["files"] = {os.path.relpath(p, REPO): os.path.getsize(p) for p in written}
    if written and only is None and not args.no_provenance:
        report["provenance_rows"] = dict(zip(("added", "removed"), update_provenance(
            written, cfg, data.base_timestamp, [args.cells_out, args.kit_out, os.path.join(REPO, ROUTES_DIR)])))
    # (args.maps_out sits under args.cells_out, so its rows are kept in step with the cells)
    report["seconds"] = {"layout_and_cells": round(t_layout, 2), "total": round(time.perf_counter() - t0, 2)}
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.out, f"{cfg['name']}.blend"), check_existing=False)
    t = report["totals"]
    print(f"[city] {t['cells']} cells, LOD0 {t['tris_lod0']} tris, LOD1 {t['tris_lod1']} tris, "
          f"{t['kit_instances']} kit instances, over budget: {t['cells_over_budget'] or 'none'}, "
          f"{report['seconds']['total']} s")
    return report


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    main(argv)
