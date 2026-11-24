"""The round-5 street kit (tools/art/street2, 2026-11-23): fascia boards, name plates, road decals, clutter, barriers
and the tuk stand that the street-life rules place (HEIGHTS/placement 2026-11-24). Cells carry them as empty markers
named `<piece>__<cell>_<i>`, like the VEG_ and SIGN_ markers; the GLBs (with _LOD1) live in tools/art/street2/export
until Unity imports the kit. Triangle counts come from the kit's own table (tools/art/street2/tri_table_all.json)."""
from __future__ import annotations

import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "art", "street2"))
TRIS_JSON = os.path.join(ROOT, "tri_table_all.json")
EXPORT = os.path.join(ROOT, "export")

_TABLE: dict | None = None


def table() -> dict:
    """{piece: {"LOD0", "LOD1", "material"}}; empty when the kit is not checked out."""
    global _TABLE
    if _TABLE is None:
        _TABLE = {}
        if os.path.exists(TRIS_JSON):
            with open(TRIS_JSON, encoding="utf-8") as fh:
                _TABLE = json.load(fh)
    return _TABLE


def tris_table() -> dict[str, int]:
    return {k: int(v["LOD0"]) for k, v in table().items()}


def is_piece(name: str) -> bool:
    return name in table()


def materials(pieces) -> set[str]:
    """The kit materials a set of pieces uses (one draw call each per batch on Low: MAT_StreetKit_E is opaque,
    the two decal materials are alpha)."""
    t = table()
    return {t[p]["material"] for p in pieces if p in t}
