"""P388 vegetation density along the route (config `street_life.planting`), from the existing VEG kit only.

Why: the look report counted few palms and bare verges; the photos show coconut palms and spreading trees on the
Green's paver strip (sv_05, sv_07, sv_10), frangipani in planters (sv_05), dense trees and spilling bushes behind the
walls on the inland side (sv_07, gf_24) and young street trees in steel guards on shop pavements (gf_24). Same rule
engine as the furniture (citylib/street_life.place_items): one rule per street type, items every N metres per side,
`tier: detail` plants (ground planting, hedges) go to the StreetLifeDetail group that Low drops.
Vegetation pieces are markers (VEG_*); Unity's CellBuilder merges their LODs per chunk on the vegetation atlases, so
more plants cost triangles and memory, not new materials.
"""
from __future__ import annotations

from .street_life import Walker, _expand, cost, place_items, route_line, seed_taken, sides

# LOD0 triangles of the VEG pieces this pass uses, measured from Art/World/Vegetation/*.glb (2026-11-22)
VEG_TRIS = {"VEG_Palm_Coconut_A": 540, "VEG_Palm_Coconut_B": 540, "VEG_Palm_Coconut_C": 540, "VEG_Palm_Coconut_D": 540,
            "VEG_Tree_RainTree_A": 1050, "VEG_Tree_Kottamba_A": 1276, "VEG_Tree_StreetYoung_A": 712,
            "VEG_Shrub_Frangipani_A": 552, "VEG_Shrub_Ixora_A": 62, "VEG_CrotonShrub_01": 356, "VEG_CrotonShrub_02": 304,
            "VEG_GrassClump_A": 16, "VEG_Hedge_Spill_A": 98, "VEG_BougainvilleaMoundWallSpill_01": 348,
            "VEG_PlantBed_A": 80, "VEG_FlowerBedCards_01": 18, "VEG_FlowerBedCards_02": 18}


def dress_planting(cfg: dict, data, lay, dress, line=None) -> dict:
    sl = cfg.get("street_life", {})
    if not sl.get("planting"):
        return {}
    line = line if line is not None else route_line(cfg, data)
    if line is None:
        return {}
    walker = Walker(lay)
    seed_taken(walker, dress)
    side_list = sides(cfg, line, walker, lay.roads)
    first = len(dress.placements)
    counts = place_items(cfg, side_list, walker, dress, "planting", _expand(walker))
    from .cells import _kit_tris
    counts["cells"] = cost(dress, first, _kit_tris(), VEG_TRIS)
    return counts
