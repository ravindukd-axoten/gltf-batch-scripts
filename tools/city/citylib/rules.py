"""Tag -> dimension rules for roads and buildings. Pure functions, no dependencies.

Numbers are proposals for the tech test (AGENTS.md: people decide; agents propose). Sources:
lane widths follow common urban practice (3.5 m on trunk and primary roads, narrower on minor
roads); storey heights fit the kit (4.0 m shopfront ground floor, 3.2 m upper floors) per the Art
Bible "Shophouse: ground-floor shopfront, 2-3 upper floors".
"""
from __future__ import annotations

import re

# --- roads -----------------------------------------------------------------------------------

# highway value -> (lane width m, default total lanes two-way, default lanes one-way, pavement m per side)
ROAD_CLASSES: dict[str, tuple[float, int, int, float]] = {
    "motorway": (3.65, 4, 2, 0.0),
    "trunk": (3.5, 4, 2, 3.0),
    "primary": (3.5, 2, 2, 2.5),
    "secondary": (3.25, 2, 1, 2.0),
    "tertiary": (3.25, 2, 1, 2.0),
    "unclassified": (3.0, 2, 1, 1.5),
    "residential": (3.0, 2, 1, 1.5),
    "living_street": (2.75, 2, 1, 0.0),
    "service": (3.0, 1, 1, 0.0),
}
for _base in ("motorway", "trunk", "primary", "secondary", "tertiary"):
    ROAD_CLASSES[_base + "_link"] = (ROAD_CLASSES[_base][0], 1, 1, ROAD_CLASSES[_base][3])

# Paths that become paved pedestrian areas rather than carriageway.
FOOT_CLASSES = {"footway": 2.0, "pedestrian": 4.0, "path": 1.5, "cycleway": 2.0, "steps": 2.0}

# Service sub-types that are narrower than a full service road.
SERVICE_WIDTHS = {"driveway": 3.0, "parking_aisle": 5.5, "alley": 3.0, "drive-through": 3.0}

_NUM = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(m|meters?|metres?|ft|feet|')?\s*$", re.IGNORECASE)


def parse_length(value: str | None) -> float | None:
    """'7', '7 m', '7.5m', '23 ft', "23'" -> metres; None for anything else."""
    if not value:
        return None
    value = value.split(";")[0].strip()
    m = _NUM.match(value)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "m").lower()
    if unit in ("ft", "feet", "'"):
        num *= 0.3048
    return num if num > 0 else None


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        n = int(round(float(value.split(";")[0].strip())))
    except ValueError:
        return None
    return n if n > 0 else None


def is_carriageway(tags: dict[str, str]) -> bool:
    hw = tags.get("highway")
    if hw not in ROAD_CLASSES:
        return False
    if tags.get("area") == "yes" or tags.get("tunnel") in ("yes", "building_passage"):
        return False
    return True


def is_footpath(tags: dict[str, str]) -> bool:
    hw = tags.get("highway")
    if hw not in FOOT_CLASSES or tags.get("area") == "yes":
        return False
    # Sidewalks drawn as separate ways are covered by the generated pavements.
    return tags.get("footway") not in ("sidewalk", "crossing") and tags.get("tunnel") != "yes"


def road_lanes(tags: dict[str, str]) -> int:
    hw = tags.get("highway", "residential")
    _, two_way, one_way, _ = ROAD_CLASSES.get(hw, ROAD_CLASSES["residential"])
    lanes = parse_int(tags.get("lanes"))
    if lanes:
        return lanes
    return one_way if tags.get("oneway") in ("yes", "1", "-1") or tags.get("junction") == "roundabout" else two_way


def road_width(tags: dict[str, str]) -> float:
    """Carriageway width in metres (kerb to kerb): width tag, else lanes x lane width."""
    hw = tags.get("highway", "residential")
    explicit = parse_length(tags.get("width")) or parse_length(tags.get("width:carriageway"))
    if explicit and 2.0 <= explicit <= 40.0:
        return explicit
    if hw == "service" and tags.get("service") in SERVICE_WIDTHS:
        return SERVICE_WIDTHS[tags["service"]]
    lane_w = ROAD_CLASSES.get(hw, ROAD_CLASSES["residential"])[0]
    return road_lanes(tags) * lane_w


def pavement_width(tags: dict[str, str]) -> float:
    """Pavement (sidewalk) width per side in metres; 0 when tagged sidewalk=no/none or for service roads."""
    if tags.get("sidewalk") in ("no", "none") or tags.get("sidewalk:both") == "no":
        return 0.0
    explicit = parse_length(tags.get("sidewalk:width"))   # measured (road_overrides), else the class default
    if explicit is not None and 0.0 <= explicit <= 15.0:
        return explicit
    hw = tags.get("highway", "residential")
    return ROAD_CLASSES.get(hw, ROAD_CLASSES["residential"])[3]


def road_priority(tags: dict[str, str]) -> int:
    """Lower = more important; wider roads claim shared surface first."""
    order = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
             "living_street", "service"]
    hw = tags.get("highway", "service").replace("_link", "")
    return order.index(hw) if hw in order else len(order)


def footpath_width(tags: dict[str, str]) -> float:
    explicit = parse_length(tags.get("width"))
    if explicit and 0.8 <= explicit <= 20.0:
        return explicit
    return FOOT_CLASSES.get(tags.get("highway", "footway"), 2.0)


# --- buildings --------------------------------------------------------------------------------

GROUND_FLOOR_M = 4.0   # KIT_Shopfront height
UPPER_FLOOR_M = 3.2    # KIT_WallBay height
PARAPET_M = 0.9        # KIT_Parapet height
TOWER_MIN_LEVELS = 8   # from here buildings use the modern concrete/glass kit

# Default storeys by district and building tag where OSM has neither levels nor height.
# A tuple (lo, hi) picks deterministically from the OSM id so rebuilds are stable.
DISTRICTS: dict[str, dict[str, object]] = {
    # Delta Face / Delta Road frontage: shophouses and modern concrete, Art Bible "Shophouse: 2-3 upper floors".
    "delta_face": {
        "yes": (2, 4), "commercial": (3, 5), "retail": 2, "office": (4, 6), "hotel": (4, 8),
        "apartments": (5, 9), "residential": (2, 3), "house": 2, "detached": 2, "terrace": 2,
        "civic": 3, "public": 3, "government": 3, "school": 2, "hospital": 4, "church": 2,
        "mosque": 2, "temple": 2, "garage": 1, "garages": 1, "shed": 1, "hut": 1, "kiosk": 1,
        "service": 1, "industrial": 2, "warehouse": 2, "construction": 3,
    },
    # Pettah: dense and low (GDD/Art Bible), reserved for later districts.
    "pettah": {"yes": (2, 3), "commercial": (2, 4), "retail": (2, 3), "house": 2},
    # Fort: colonial commercial blocks (3-4 tall storeys, arcades) between modern bank and office towers.
    "fort": {"yes": (3, 4), "commercial": (3, 5), "retail": (2, 3), "office": (4, 7), "government": (3, 4),
             "civic": (3, 4), "public": 3, "hotel": (5, 8), "apartments": (4, 6), "house": 2, "garage": 1,
             "shed": 1, "hut": 1, "kiosk": 1, "service": 1, "warehouse": 2, "construction": 3},
    # Slave Island: mixed, low shophouse rows (1-2 upper floors) and walk-up flats.
    "slave_island": {"yes": (2, 3), "commercial": (2, 3), "retail": 2, "office": (3, 5), "apartments": (4, 7),
                     "residential": (2, 3), "house": 2, "terrace": 2, "detached": 2, "garage": 1, "shed": 1,
                     "hut": 1, "kiosk": 1, "service": 1, "warehouse": 2, "industrial": 2, "construction": 3},
}

# Facade kit choices by district (kit.assemble_building). Districts not listed keep the Delta Face mix.
# upper: KIT_Upper_<style> families, repeated to weight them; ground: shopfront bays; paint: plaster families.
DISTRICT_STYLES: dict[str, dict[str, tuple[str, ...] | str]] = {
    # Fort: Colonial upper floors (arched, corniced), arched and glazed ground bays, cream and lime plaster
    "fort": {"upper": ("Colonial", "Colonial", "Colonial", "Modern"),
             "ground": ("KIT_Shopfront_Arched_A", "KIT_Shopfront_Arched_B", "KIT_Shopfront_Glazed_A",
                        "KIT_Shopfront_Glazed_B"),
             "paint": "AABBC"},
    # Slave Island: shophouse rows with roller shutters, a few modern infills, more colour
    "slave_island": {"upper": ("Shophouse", "Shophouse", "Shophouse", "Modern"),
                     "ground": ("KIT_Shopfront_Shutter_A", "KIT_Shopfront_Shutter_B", "KIT_Shopfront_Shutter_A",
                                "KIT_Shopfront_Glazed_A"),
                     "paint": "ABCDD"},
}

SKIP_BUILDINGS = {"roof", "carport", "ruins", "no", "collapsed", "bridge", "canopy"}
SACRED_BUILDINGS = {"church", "mosque", "temple", "chapel", "cathedral", "shrine", "kovil", "religious",
                    "synagogue", "monastery"}


def is_sacred(tags: dict[str, str]) -> bool:
    """Protected sites (Art Bible): never dressed with shop kit; hand-modelled heroes later."""
    return tags.get("building") in SACRED_BUILDINGS or tags.get("amenity") == "place_of_worship"


KIOSK_MAX_AREA_M2 = 60.0  # untagged footprints this small are kiosks, stalls and huts: one storey


def default_levels(osm_id: int, building: str, district: str = "delta_face", area_m2: float | None = None) -> int:
    if area_m2 is not None and area_m2 < KIOSK_MAX_AREA_M2:
        return 1
    table = DISTRICTS.get(district, DISTRICTS["delta_face"])
    rule = table.get(building, table["yes"])
    if isinstance(rule, tuple):
        lo, hi = rule
        return lo + (osm_id * 2654435761 % 2**32) % (hi - lo + 1)  # Knuth hash: stable, well spread
    return int(rule)


def levels_from_height(height_m: float) -> int:
    """Nearest storey count whose kit height (4.0 + 3.2 * (n - 1)) matches the tagged height."""
    return max(1, 1 + round((height_m - GROUND_FLOOR_M) / UPPER_FLOOR_M))


TOWER_STOREY_M = 3.9   # real floor to floor in towers (OSM: 194 m / 47 levels = 4.1, 134 m / 39 = 3.4 with podium)


def building_levels(osm_id: int, tags: dict[str, str], district: str = "delta_face",
                    area_m2: float | None = None) -> tuple[int, str]:
    """Storeys above ground (kit storeys of 4.0 + 3.2 m) and where the number came from ('height', 'levels' or
    'default'). A tagged `height` wins over `building:levels` (DELTA_FACE_MEASURED.md: towers built from level
    counts at 3.2 m a storey came out 20-30 % short). A tower tagged with levels only (TOWER_MIN_LEVELS and up)
    is scaled to about 3.9 m a storey, so its roof matches the real height."""
    height = parse_length(tags.get("height"))
    if height:
        return min(levels_from_height(height), 80), "height"
    levels = parse_int(tags.get("building:levels"))
    if levels:
        if levels >= TOWER_MIN_LEVELS:
            levels = round(levels * TOWER_STOREY_M / UPPER_FLOOR_M)
        return min(levels, 80), "levels"
    return default_levels(osm_id, tags.get("building", "yes"), district, area_m2), "default"


def wall_height(levels: int) -> float:
    """Height of the top of the walls (roof slab) for a storey count, snapped to the kit."""
    return GROUND_FLOOR_M + UPPER_FLOOR_M * max(0, levels - 1)
