"""Wear rules loader (data/world/wear_rules.json, task W2). Pure Python, no bpy.

Condition is data: per district and street class the age band, dirt, damp, rust and edge-wear levels and the decal
counts. A placement rule asks `rules.condition(district, street_class, uid)` and gets the COLOR_1 channel values
(R dirt, G edge wear, B damp or rust, A age seed) for that instance. The per-instance variation reuses the seeds of
`citylib/decay.py` (stable FNV hash of an id), so a rebuild gives the same city.

    from citylib import wear_rules
    rules = wear_rules.load()
    c = rules.condition("pettah", "secondary", "bld_123")   # dict: age_years, dirt, damp, rust, edge, seed
    n = rules.decal_budget("pettah", "secondary", 240.0, "road")
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from . import decay

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "world" / "wear_rules.json"
LEVELS = ("dirt", "damp", "rust", "edge_wear")
DECAL_KINDS = ("road", "kerb", "wall", "metal")


def _mid(c):
    return (c["age_years"][0] + c["age_years"][1]) / 2.0


def validate(doc, names_ids=None):
    """Errors for a parsed wear_rules.json (the rules data/schemas/wear_rules.schema.json states, plus the cross-rules)."""
    errs = []
    if doc.get("schema_version") != 1:
        errs.append("schema_version must be 1")
    if doc.get("status") not in ("proposed", "approved"):
        errs.append("status must be proposed or approved")
    classes = doc.get("street_classes")
    if not isinstance(classes, list) or not classes or len(set(classes)) != len(classes):
        return errs + ["street_classes must be a non-empty list without duplicates"]
    if not isinstance(doc.get("jitter"), (int, float)) or not 0 <= doc["jitter"] <= 0.5:
        errs.append("jitter must be 0..0.5")
    if not isinstance(doc.get("low_tier_road_decal_quads_per_cell"), int) or doc["low_tier_road_decal_quads_per_cell"] < 0:
        errs.append("low_tier_road_decal_quads_per_cell must be a non-negative integer")
    pd = doc.get("projected_decals_visible", {})
    if pd.get("low") != 0:
        errs.append("projected_decals_visible.low must be 0 (no projected decals on Low)")
    if not all(isinstance(pd.get(k), int) and pd[k] >= 0 for k in ("medium", "high")) or pd.get("medium", 0) > pd.get("high", 0):
        errs.append("projected_decals_visible needs integer medium <= high")
    districts = doc.get("districts", {})
    order = doc.get("condition_order", [])
    if sorted(order) != sorted(districts) or len(set(order)) != len(order):
        errs.append("condition_order must list each district exactly once")
    for d, dd in districts.items():
        def err(m, d=d):
            errs.append(f"{d}: {m}")
        if not isinstance(dd.get("label"), str) or not dd["label"]:
            err("label missing")
        if order and d in order and dd.get("condition_rank") != order.index(d):
            err("condition_rank must equal the position in condition_order")
        if names_ids is not None and "names_id" in dd and dd["names_id"] not in names_ids:
            err(f"names_id {dd['names_id']} not in data/names/names.json")
        cl = dd.get("classes", {})
        if set(cl) != set(classes):
            err(f"classes must be exactly {sorted(classes)}")
        for k, c in cl.items():
            a = c.get("age_years")
            if not (isinstance(a, list) and len(a) == 2 and all(isinstance(x, int) and 0 <= x <= 200 for x in a) and a[0] <= a[1]):
                err(f"{k}: age_years must be [min, max] integers, min <= max")
                continue
            for lv in LEVELS:
                v = c.get(lv)
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1:
                    err(f"{k}: {lv} must be 0..1")
            dc = c.get("decals_per_100m", {})
            if set(dc) != set(DECAL_KINDS) or not all(isinstance(x, int) and 0 <= x <= 40 for x in dc.values()):
                err(f"{k}: decals_per_100m needs integer 0..40 for {list(DECAL_KINDS)}")
    # worse districts never look better on dirt, damp, mean age or total decals (per street class)
    if not errs:
        for k in classes:
            for a, b in zip(order, order[1:]):
                ca, cb = districts[a]["classes"][k], districts[b]["classes"][k]
                for name, fa, fb in (("dirt", ca["dirt"], cb["dirt"]), ("damp", ca["damp"], cb["damp"]),
                                     ("mean age", _mid(ca), _mid(cb)),
                                     ("decals", sum(ca["decals_per_100m"].values()), sum(cb["decals_per_100m"].values()))):
                    if fb < fa:
                        errs.append(f"{k}: {b} has lower {name} than {a}, but condition_order puts it after")
        if order and "pettah" in districts and "delta_face_green" in districts:
            for k in classes:
                if districts["pettah"]["classes"][k]["dirt"] <= districts["delta_face_green"]["classes"][k]["dirt"]:
                    errs.append(f"{k}: pettah must be dirtier than delta_face_green")
    return errs


class WearRules:
    def __init__(self, doc):
        self.doc = doc
        self.jitter = float(doc["jitter"])
        self.street_classes = tuple(doc["street_classes"])
        self.districts = tuple(doc["condition_order"])
        self.low_decal_quads_per_cell = int(doc["low_tier_road_decal_quads_per_cell"])

    def rule(self, district, street_class):
        try:
            return self.doc["districts"][district]["classes"][street_class]
        except KeyError:
            raise KeyError(f"no wear rule for district {district!r}, street class {street_class!r}") from None

    def condition(self, district, street_class, uid):
        """COLOR_1 values for one instance: age in years inside the class band, levels 0..1 jittered by the id seed."""
        r = self.rule(district, street_class)
        seed = decay.stable_hash(f"wear:{district}:{street_class}:{uid}")
        rng = random.Random(seed)
        lo, hi = r["age_years"]
        age = rng.randint(lo, hi)
        out = {"age_years": age, "seed": seed}
        for lv in LEVELS:
            j = (rng.random() * 2.0 - 1.0) * self.jitter
            out[lv] = round(min(1.0, max(0.0, r[lv] + j)), 3)
        out["age_seed"] = round(rng.random(), 4)         # COLOR_1.A
        return out

    def color1(self, district, street_class, uid, surface="wall"):
        """(R dirt, G edge wear, B damp for walls or rust for metal, A age seed) in 0..1."""
        c = self.condition(district, street_class, uid)
        b = c["rust"] if surface == "metal" else c["damp"]
        return (c["dirt"], c["edge_wear"], b, c["age_seed"])

    def decal_budget(self, district, street_class, length_m, kind):
        """Most decals of a kind for a street stretch (rounded up); callers still honour the Low per-cell quad cap."""
        if kind not in DECAL_KINDS:
            raise KeyError(f"unknown decal kind {kind!r}")
        per100 = self.rule(district, street_class)["decals_per_100m"][kind]
        return int(-(-per100 * float(length_m) // 100))


def load(path=None, names_path=None):
    """Load and validate data/world/wear_rules.json; raises ValueError listing every problem."""
    p = Path(path) if path else DEFAULT_PATH
    doc = json.loads(p.read_text(encoding="utf-8"))
    ids = None
    np_ = Path(names_path) if names_path else p.parents[1] / "names" / "names.json"
    if np_.exists():
        ids = {e["id"] for e in json.loads(np_.read_text(encoding="utf-8")).get("entries", [])}
    errs = validate(doc, ids)
    if errs:
        raise ValueError("wear_rules invalid:\n  " + "\n  ".join(errs))
    return WearRules(doc)
