"""Minimal reader for OSM XML (.osm) files as written by the Overpass API.

Returns plain dicts and lists so the rest of the pipeline stays independent of any OSM library.
Multipolygon relations are assembled into closed rings (outer and inner) by joining member ways
end to end.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Way:
    id: int
    node_ids: list[int]
    tags: dict[str, str]

    @property
    def closed(self) -> bool:
        return len(self.node_ids) >= 4 and self.node_ids[0] == self.node_ids[-1]


@dataclass
class Area:
    """A closed area from a closed way or a multipolygon relation. Rings are lists of node ids."""
    id: int
    kind: str  # "way" or "relation"
    outers: list[list[int]]
    inners: list[list[int]]
    tags: dict[str, str]


@dataclass
class OsmData:
    nodes: dict[int, tuple[float, float]] = field(default_factory=dict)  # id -> (lat, lon)
    ways: dict[int, Way] = field(default_factory=dict)
    relations: list[dict] = field(default_factory=list)
    node_tags: dict[int, dict[str, str]] = field(default_factory=dict)  # only nodes that carry tags
    base_timestamp: str = ""

    def coords(self, node_ids: list[int]) -> list[tuple[float, float]]:
        """(lat, lon) for each node id that exists in the file (Overpass may omit far nodes)."""
        return [self.nodes[n] for n in node_ids if n in self.nodes]


def parse_osm(path: str) -> OsmData:
    data = OsmData()
    root = ET.parse(path).getroot()
    meta = root.find("meta")
    if meta is not None:
        data.base_timestamp = meta.get("osm_base", "")
    for el in root:
        if el.tag == "node":
            nid = int(el.get("id"))
            data.nodes[nid] = (float(el.get("lat")), float(el.get("lon")))
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tags:
                data.node_tags[nid] = tags
        elif el.tag == "way":
            nds = [int(nd.get("ref")) for nd in el.findall("nd")]
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            data.ways[int(el.get("id"))] = Way(int(el.get("id")), nds, tags)
        elif el.tag == "relation":
            members = [
                {"type": m.get("type"), "ref": int(m.get("ref")), "role": m.get("role") or ""}
                for m in el.findall("member")
            ]
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            data.relations.append({"id": int(el.get("id")), "members": members, "tags": tags})
    return data


def merge(first: OsmData, *more: OsmData) -> OsmData:
    """One dataset from several extracts. The first holder of an element wins (nodes, ways, relations and
    node tags), so adding an extract never moves geometry the earlier one already built. The base timestamp
    lists every extract's, in order, joined by ' + '."""
    out = OsmData(dict(first.nodes), dict(first.ways), list(first.relations), dict(first.node_tags),
                  first.base_timestamp)
    stamps = [first.base_timestamp]
    rel_ids = {r["id"] for r in out.relations}
    for d in more:
        for k, v in d.nodes.items():
            out.nodes.setdefault(k, v)
        for k, v in d.ways.items():
            out.ways.setdefault(k, v)
        for k, v in d.node_tags.items():
            if k not in first.nodes:
                out.node_tags.setdefault(k, v)
        for r in d.relations:
            if r["id"] not in rel_ids:
                out.relations.append(r)
                rel_ids.add(r["id"])
        stamps.append(d.base_timestamp)
    out.base_timestamp = " + ".join(s for s in stamps if s)
    return out


def parse_osm_files(paths: list[str]) -> OsmData:
    datas = [parse_osm(p) for p in paths]
    return merge(*datas) if len(datas) > 1 else datas[0]


def join_rings(segments: list[list[int]]) -> list[list[int]]:
    """Join open node-id sequences end to end into closed rings. Unclosable leftovers are dropped."""
    pending = [list(s) for s in segments if len(s) >= 2]
    rings: list[list[int]] = []
    while pending:
        ring = pending.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, seg in enumerate(pending):
                if seg[0] == ring[-1]:
                    ring += seg[1:]
                elif seg[-1] == ring[-1]:
                    ring += list(reversed(seg))[1:]
                elif seg[-1] == ring[0]:
                    ring = seg[:-1] + ring
                elif seg[0] == ring[0]:
                    ring = list(reversed(seg))[:-1] + ring
                else:
                    continue
                pending.pop(i)
                changed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def areas(data: OsmData, predicate) -> list[Area]:
    """Closed ways and multipolygon relations whose tags satisfy predicate(tags)."""
    out: list[Area] = []
    for way in data.ways.values():
        if way.closed and predicate(way.tags):
            out.append(Area(way.id, "way", [way.node_ids], [], way.tags))
    for rel in data.relations:
        if rel["tags"].get("type") != "multipolygon" or not predicate(rel["tags"]):
            continue
        outer_segs, inner_segs = [], []
        for m in rel["members"]:
            if m["type"] != "way" or m["ref"] not in data.ways:
                continue
            (inner_segs if m["role"] == "inner" else outer_segs).append(data.ways[m["ref"]].node_ids)
        outers = join_rings(outer_segs)
        if outers:
            out.append(Area(rel["id"], "relation", outers, join_rings(inner_segs), rel["tags"]))
    return out


def lines(data: OsmData, predicate) -> list[Way]:
    """Ways (open or closed) whose tags satisfy predicate(tags), sorted by id for determinism."""
    return sorted((w for w in data.ways.values() if predicate(w.tags)), key=lambda w: w.id)
