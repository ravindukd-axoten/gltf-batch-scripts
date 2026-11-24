"""Area configs (tools/city/config/*.json). Pure Python, no dependencies.

A config may extend another with "extends": "<file next to it>". The child is merged over the parent:
nested objects merge key by key, everything else (lists, numbers, strings) replaces. This lets an area grow
(Delta Face -> the Fort loop) without copying the parent's rules, so the parent's cells keep their settings.

OSM input is "osm_file" (one extract) or "osm_files" (several, merged by osm.parse_osm_files: the first
file wins where two extracts hold the same element, so the area that was built first keeps its data).
"""
from __future__ import annotations

import json
import os


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str, _seen: tuple = ()) -> dict:
    path = os.path.abspath(path)
    if path in _seen:
        raise ValueError(f"config extends itself: {' -> '.join(_seen + (path,))}")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    parent = cfg.pop("extends", None)
    if parent:
        cfg = deep_merge(load(os.path.join(os.path.dirname(path), parent), _seen + (path,)), cfg)
    return cfg


def osm_files(cfg: dict) -> list[str]:
    """The config's OSM extracts, relative to tools/city, in priority order."""
    files = cfg.get("osm_files") or [cfg["osm_file"]]
    return list(files)


def env_suffix(cfg: dict) -> str:
    """Name part of the ENV_ pieces (sea horizon, city backdrop): 'env_name', else the CamelCased area name."""
    return cfg.get("env_name") or "".join(w.capitalize() for w in cfg["name"].split("_"))
