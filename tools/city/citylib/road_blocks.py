"""Road blocks on the drive circle's exits (Vertical Slice Plan "Drive circle": no unbuilt area to drive into).

Each block in the road network data (citylib/road_network.py, `blocks`) becomes, in the cell build:
- a row of PROP_Barrier_Police_01 (the red water-filled barrier seen on the A2, sv_04/sv_09/sv_14) across the
  carriageway on the barrier line, kerb to kerb plus the overhang;
- a collision wall BLOCK_WALL_M high along the same line (both faces), so a car stops even between two props.
The road beyond stays built (scenery the player sees, not drives). Kind "gate" (the hotel spur) gets the same row for
now; a closed-gate kit piece is a later art task (ROADS2_HANDOFF.md).
"""
from __future__ import annotations

import math

from .kit import Instance
from .layout import WallSeg

BARRIER_PIECE = "PROP_Barrier_Police_01"
BARRIER_LEN_M = 1.6       # the piece's own length (street_kit.py)
BARRIER_GAP_M = 0.1       # end lugs touch: a closed line
BLOCK_WALL_M = 1.2        # collision height above the road surface


def barrier_slots(p0: tuple[float, float], p1: tuple[float, float]) -> list[tuple[float, float, float]]:
    """(x, z, yaw) for barrier props filling p0 -> p1: as many whole pieces as cover the line, centred."""
    length = math.dist(p0, p1)
    n = max(1, math.ceil(length / (BARRIER_LEN_M + BARRIER_GAP_M)))
    pitch = length / n
    ux, uz = (p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length
    yaw = math.atan2(uz, ux)
    return [(p0[0] + ux * pitch * (i + 0.5), p0[1] + uz * pitch * (i + 0.5), yaw) for i in range(n)]


def place(network: dict, road_z: float, dressing=None) -> tuple[list[Instance], list[WallSeg]]:
    """Barrier instances (added to dressing group "Street" when given) and collision walls for every block."""
    insts, walls = [], []
    for b in network.get("blocks", []):
        p0, p1 = tuple(b["barrier"][0]), tuple(b["barrier"][1])
        for x, z, yaw in barrier_slots(p0, p1):
            inst = Instance(BARRIER_PIECE, x, z, road_z, yaw)
            insts.append(inst)
            if dressing is not None:
                dressing.add("Street", inst)
        walls.append(WallSeg(p0, p1, road_z, road_z, road_z + BLOCK_WALL_M, "barrier"))
        walls.append(WallSeg(p1, p0, road_z, road_z, road_z + BLOCK_WALL_M, "barrier"))
    return insts, walls
