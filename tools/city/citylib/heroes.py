"""Hero landmark sites: where the hand-modelled heroes stand and what they replace (TDD "Hero landmarks").

Config (`hero_models` in the area config), one entry per hero prefab:

    "HERO_SeafaceHotel": {"builder": "hotel", "landmark": "LMK_SeafaceHotel", "pivot": [72.0, -262.0], "yaw_deg": 17.0}
    "HERO_FountainRoundabout": {"builder": "fountain", "fountain": "Lotus Round About", "pivot": [-366.57, 988.87]}

- `pivot` is the hero's origin in world metres (x east, y north); the model is authored around it in a frame
  turned `yaw_deg` from east. Unity places the hero prefab at the pivot at road height, unrotated, so the
  pivot and yaw are part of the model and must not change without rebuilding it.
- `landmark` names the OSM buildings (config `landmarks`) whose placeholder massing the hero replaces: the
  cells drop their LOD0 mass and LOD1 prism, keep their collision blocks, and get an empty `HERO_<Name>`
  marker node in the cell that holds the pivot.
- `fountain` names a roundabout whose fountain prop the hero replaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import grid


@dataclass(frozen=True)
class HeroSite:
    name: str
    builder: str
    pivot: tuple[float, float, float]       # world metres, z = road height
    yaw_deg: float = 0.0
    landmark: str = ""
    fountain: str = ""
    osm_ids: tuple[int, ...] = field(default_factory=tuple)

    @property
    def cell(self) -> tuple[int, int]:
        return grid.cell_of(self.pivot[0], self.pivot[1])


def hero_sites(cfg: dict, buildings=(), road_z: float = 3.8) -> list[HeroSite]:
    """Hero sites from the config, with the OSM ids of the buildings each one replaces (sorted by name)."""
    out = []
    for name, spec in sorted(cfg.get("hero_models", {}).items()):
        lm = spec.get("landmark", "")
        ids = tuple(sorted(b.osm_id for b in buildings if lm and b.landmark == lm))
        px, py = spec["pivot"]
        out.append(HeroSite(name, spec["builder"], (float(px), float(py), road_z), float(spec.get("yaw_deg", 0.0)),
                            lm, spec.get("fountain", ""), ids))
    return out


def replaced_landmarks(cfg: dict) -> set[str]:
    return {s["landmark"] for s in cfg.get("hero_models", {}).values() if s.get("landmark")}


def replaced_fountains(cfg: dict) -> set[str]:
    return {s["fountain"] for s in cfg.get("hero_models", {}).values() if s.get("fountain")}


def replaced_piers(cfg: dict) -> list[tuple[float, float]]:
    """Pivots (the stem's root on the seawall) of piers modelled as heroes (`"pier": true`): the dressing drops
    the kit pier modules, flagpole and kiosk of the OSM pier whose root is nearest."""
    return [tuple(s["pivot"]) for s in cfg.get("hero_models", {}).values() if s.get("pier")]
