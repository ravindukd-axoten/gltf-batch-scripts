"""World material names, preview colours and texture scales (Art Bible "World materials").

The glTF material names written by the pipeline are the keys Unity's WorldMaterialLibrary maps to authored
URP materials with the CC0-derived textures built by tools/textures/build_textures.py. TILE_M says how many
metres one UV unit covers for each material, and must match that script's "tile_m" (textures.json in Unity):
UVs are authored in metres / TILE_M, so a texture shows at real scale everywhere.

Preview colours (sRGB) are what Blender shows and what the glTF base colour factor carries; in Unity the
texture's own colour wins (the material's base colour is set to white).
"""
from __future__ import annotations

# surfaces
ASPHALT = "MAT_Asphalt"
STREET_TRIM = "MAT_StreetTrim_A"          # kerb faces, road paint, zebra, gutters (trim rows)
ROAD_EDGE_TRIM = "MAT_RoadEdgeTrim_A"     # P117 WS-0339: kerb faces from the P92b road edge kit sheet (loaded with the kit)
ROAD_PAINT = "MAT_RoadPaint_A"            # lane legends, arrows, "BUS" (T_RoadPaint_A atlas, citylib/paint_atlas.py)
PAVER = "MAT_PromenadePaver"              # promenade and pavements: terracotta herringbone pavers
SEAFRONT_PAVER = "MAT_SeafrontPaver"      # Delta Face promenade + sea-side pavement: 200x100 running bond, cream bands
PLAZA_PAVER = "MAT_PlazaPaver"            # roundabout plaza corners: 45 deg grid with a cream border band
HERRINGBONE_PAVER = "MAT_HerringbonePaver"  # SLICE4d: hotel Delta Road frontage, red-brown herringbone (agent h08, h16)
LAWN_HOTEL = "MAT_Lawn_Hotel"             # SLICE4d: the hotel's kept sea lawn, deeper and bluer than the Green (h04, h18)
CONCRETE = "MAT_Concrete_Weathered"       # flat roofs, forecourts, steps, bench-wall caps, piles
SEAWALL = "MAT_SeawallRubble"
LAWN = "MAT_Lawn_Patchy"
LAWN_WORN = "MAT_Lawn_Worn"
LAWN_STRIPE = "MAT_Lawn_Stripe"           # alternate mowing bands: the lawn texture, a shade darker
SAND_RECLAIMED = "MAT_Sand_Reclaimed"     # reclaimed / construction land: pale neutral sand
BACKDROP_GROUND = "MAT_Backdrop_Ground"   # distant-city ground outside the area_strip (untextured, haze tint)
BACKDROP_CITY = "MAT_Backdrop_City"       # distant-city block masses (untextured, haze tint)
EARTH = "MAT_Earth_Laterite"
SAND_DRY = "MAT_Sand_Dry"
SAND_WET = "MAT_Sand_Wet"
ROCK = "MAT_RockArmour"
WATER_SEA = "MAT_Water_Sea"               # the whole sea: depth-ramp texture (turquoise -> deep blue, foam bands)
WATER_LAKE = "MAT_Water_Lake"
# buildings
FACADE_TRIM = "MAT_FacadeTrim_A"          # the kit's shared trim atlas (plaster / concrete / accent blocks)
TOWER_GLASS = "MAT_TowerGlass_A"          # curtain wall module and every window
PLASTER = "MAT_PlasterColonial_Cream"     # tiling lime-wash render: landmark masses, far LOD walls
PLASTER_SMOOTH = "MAT_PlasterSmooth_Cream"  # smooth even cream render: the hero hotel's walls (V2)
SANDSTONE = "MAT_Stone_Sandstone"         # the same render retinted ochre (assembly-hall placeholder)
ROOF_TILE = "MAT_RoofTerracotta"
SCAFFOLD = "MAT_Scaffold_Mesh"
HERO = "MAT_Hero_Placeholder"
PROP = "MAT_Prop_Shared_Atlas"
LAMP = "MAT_Lamp_Emissive"
STREET_KIT = "MAT_StreetKit_A"            # street kit (SHD_HeroLit over FacadeTrim_A + decor masks; COLOR_0 paint + AO)
SIGNAGE = "MAT_Signage_A"                 # signboards (SHD_HeroLit over the T_Signage_A atlas of fictional names)
WEAR_DECAL = "MAT_WearDecal_A"            # SLICE6: hero wear decals, 2x-multiply over the walls (citylib/wear_decals.py)
GREY_COBBLE = "MAT_GreyCobble"            # SLICE6: grey granite setts, the hotel's Delta Road gate lane (gf_22)

# name -> (preview sRGB hex, roughness, metallic)
MATERIALS: dict[str, tuple[str, float, float]] = {
    ASPHALT: ("#7D7C79", 0.85, 0.0),
    STREET_TRIM: ("#C9C0B2", 0.75, 0.0),
    ROAD_PAINT: ("#7D7B77", 0.8, 0.0),
    PAVER: ("#9E6450", 0.8, 0.0),
    SEAFRONT_PAVER: ("#9F8A7B", 0.8, 0.0),
    PLAZA_PAVER: ("#A08C7D", 0.8, 0.0),
    HERRINGBONE_PAVER: ("#8F6451", 0.8, 0.0),
    WEAR_DECAL: ("#808080", 1.0, 0.0),
    GREY_COBBLE: ("#8A8780", 0.8, 0.0),
    LAWN_HOTEL: ("#5E8A3E", 0.9, 0.0),
    CONCRETE: ("#A39A8C", 0.8, 0.0),
    SEAWALL: ("#7D705F", 0.85, 0.0),
    LAWN: ("#78A042", 0.9, 0.0),
    LAWN_WORN: ("#8E8048", 0.9, 0.0),
    EARTH: ("#A46650", 0.9, 0.0),
    SAND_DRY: ("#CFB287", 0.9, 0.0),
    SAND_WET: ("#A07B4F", 0.5, 0.0),
    ROCK: ("#88837C", 0.8, 0.0),
    WATER_SEA: ("#1F8FA0", 0.08, 0.0),      # Indian Ocean teal; the real sea shader is V5
    LAWN_STRIPE: ("#6C963E", 0.9, 0.0),
    SAND_RECLAIMED: ("#CFC6B4", 0.9, 0.0),
    BACKDROP_GROUND: ("#8C9A74", 0.95, 0.0),
    BACKDROP_CITY: ("#D6B8A4", 0.9, 0.0),
    WATER_LAKE: ("#3F7F5F", 0.12, 0.0),
    FACADE_TRIM: ("#E6DBC2", 0.8, 0.0),
    TOWER_GLASS: ("#3B5566", 0.1, 0.0),
    PLASTER: ("#E4D9C0", 0.8, 0.0),
    SANDSTONE: ("#D2AE7A", 0.8, 0.0),
    PLASTER_SMOOTH: ("#E9DDC4", 0.75, 0.0),
    ROOF_TILE: ("#A65E4B", 0.7, 0.0),
    SCAFFOLD: ("#3E8E5A", 0.9, 0.0),
    HERO: ("#E8664A", 0.7, 0.0),            # Sunset coral: reads as "placeholder" at a glance
    PROP: ("#FFFFFF", 0.6, 0.0),            # colour from vertex colours (props)
    LAMP: ("#FFE2A8", 0.4, 0.0),
    STREET_KIT: ("#FFFFFF", 0.7, 0.0),      # colour from COLOR_0 paint
    SIGNAGE: ("#FFFFFF", 0.6, 0.0),
    "MAT_Cart_IssoWade_A": ("#FFFFFF", 0.5, 0.0),   # isso wade carts + props (citylib/carts.py, T_CartIssoWade_*)
}

# metres per UV unit (u, v); must match tools/textures/build_textures.py
TILE_M: dict[str, tuple[float, float]] = {
    ASPHALT: (4.0, 3.5),       # one lane across (tools/textures/street_surfaces.py tyre tracks)
    STREET_TRIM: (4.0, 4.0),
    ROAD_PAINT: (9.6, 18.0),   # paint_atlas.TILE_M
    PAVER: (1.8, 1.8),
    SEAFRONT_PAVER: (2.4, 2.4),
    PLAZA_PAVER: (2.4, 2.4),
    HERRINGBONE_PAVER: (2.4, 2.4),
    GREY_COBBLE: (2.0, 2.0),
    LAWN_HOTEL: (2.0, 2.0),
    CONCRETE: (3.0, 3.0),
    SEAWALL: (2.0, 2.0),
    LAWN: (2.0, 2.0),
    LAWN_WORN: (2.0, 2.0),
    EARTH: (2.0, 2.0),
    SAND_DRY: (1.5, 1.5),
    SAND_WET: (2.0, 2.0),
    ROCK: (1.8, 1.8),
    LAWN_STRIPE: (2.0, 2.0),
    SAND_RECLAIMED: (1.5, 1.5),
    WATER_LAKE: (32.0, 32.0),
    TOWER_GLASS: (4.0, 3.2),
    PLASTER: (1.0, 1.0),
    SANDSTONE: (1.0, 1.0),
    PLASTER_SMOOTH: (4.0, 4.0),
    ROOF_TILE: (2.5, 2.5),
    SCAFFOLD: (4.0, 4.0),
    HERO: (4.0, 4.0),
}

# StreetTrim_A rows (v ranges in the 0..1 sheet)
TRIM_KERB = (0.02, 0.23)
TRIM_WHITE = (0.26, 0.365)
TRIM_YELLOW = (0.385, 0.49)
TRIM_ZEBRA = (0.51, 0.74)

# FacadeTrim_A: the kit's 4 m sheets (body 0-0.8, cornice 0.8-0.9, reveal 0.9-1.0) become blocks stacked in v
FACADE_BLOCKS = {
    "MAT_Facade_Shophouse_Trim": 0,   # kit.MAT_FACADE: lime-wash cream plaster
    "MAT_Facade_Concrete_Trim": 1,    # kit.MAT_FACADE_CONCRETE: cast concrete
    "MAT_Facade_Accent_Trim": 2,      # kit.MAT_ACCENT: painted accent (signboards, awnings, railings)
}
FACADE_BLOCK_COUNT = 4
GLASS_VISION = (0.33, 0.98)           # TowerGlass_A rows that hold vision glass (kit windows use these)


def tile(material: str) -> tuple[float, float]:
    return TILE_M.get(material, (4.0, 4.0))


def to_world_materials(md) -> None:
    """Rewrite a kit MeshData (authored with the kit's 4 m-sheet materials) onto the shared atlases:
    facade sheets -> FacadeTrim_A blocks, windows -> TowerGlass_A vision rows, flat roofs -> concrete.
    UVs keep u (4 m per unit, tiling); v moves into the block with a small inset against bleeding."""
    from . import kit  # local import: kit imports this module
    old = list(md.materials)
    new_names = []
    for name in old:
        if name in FACADE_BLOCKS:
            new_names.append(FACADE_TRIM)
        elif name == kit.MAT_GLASS:
            new_names.append(TOWER_GLASS)
        elif name == kit.MAT_ROOF:
            new_names.append(CONCRETE)
        else:
            new_names.append(name)
    for f, mi in enumerate(md.mats):
        name = old[mi]
        if name in FACADE_BLOCKS:
            k = FACADE_BLOCKS[name]
            md.uvs[f] = tuple((u, (k + 0.004 + min(max(v, 0.0), 1.0) * 0.992) / FACADE_BLOCK_COUNT) for u, v in md.uvs[f])
        elif name == kit.MAT_GLASS:
            g0, g1 = GLASS_VISION
            md.uvs[f] = tuple((u, g0 + min(max(v, 0.0), 0.55) / 0.55 * (g1 - g0)) for u, v in md.uvs[f])
        elif name == kit.MAT_ROOF:
            t = tile(CONCRETE)
            md.uvs[f] = tuple((u * 4.0 / t[0], v * 4.0 / t[1]) for u, v in md.uvs[f])
    # merge slots that now share a name
    final: list[str] = []
    remap = []
    for n in new_names:
        if n not in final:
            final.append(n)
        remap.append(final.index(n))
    md.materials = final
    md.mats = [remap[i] for i in md.mats]
