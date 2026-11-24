"""Which config built the cell glbs on disk (read from each glb's own "config" extra).

delta_face.json and fort_loop.json write the same cell folder, and fort_loop covers more cells than delta_face.
A full build of one config prunes and overwrites the other's cells (route misses in RouteColliderTests), so
build_city refuses to do that unless asked with --adopt-cells.
"""
from __future__ import annotations

import json
import os
import struct


def glb_config(path: str) -> str | None:
    """The "config" extra of the first node in a .glb, or None (LFS pointer, unreadable, no extra)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(20)
            if len(head) < 20 or head[:4] != b"glTF":
                return None
            length = struct.unpack("<I", head[12:16])[0]
            doc = json.loads(fh.read(length))
    except (OSError, ValueError, struct.error):
        return None
    for node in doc.get("nodes", []):
        cfg = (node.get("extras") or {}).get("config")
        if cfg:
            return cfg
    for key in ("scenes", "asset"):
        for item in (doc.get(key) if isinstance(doc.get(key), list) else [doc.get(key) or {}]):
            cfg = ((item or {}).get("extras") or {}).get("config")
            if cfg:
                return cfg
    return None


def foreign_cells(cells_dir: str, config_rel: str) -> dict[str, list[str]]:
    """{other config: [cell ids]} for cell glbs in cells_dir that a different config built."""
    out: dict[str, list[str]] = {}
    if not os.path.isdir(cells_dir):
        return out
    for f in sorted(os.listdir(cells_dir)):
        if f.startswith("cell_") and f.endswith(".glb"):
            cfg = glb_config(os.path.join(cells_dir, f))
            if cfg and os.path.normpath(cfg) != os.path.normpath(config_rel):
                out.setdefault(cfg, []).append(f[:-4])
    return out
