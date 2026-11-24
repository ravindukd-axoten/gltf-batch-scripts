"""Delta Face isso wade (prawn / crab vadai) carts and their small props: the data side (pure Python, no bpy).

References (references/delta-face/pier_and_carts_2026-11-16/NOTES.md, third-party: reference only):
  PROP_Cart_IssoWade_A  day cart (cart_03): bright green painted body, big bicycle-type spoked wheels, open
                        wooden shelves of stacked vadai, rusty corrugated tin canopy on 4 poles, a white plastic
                        water can on the ground and a blue bag hung from the canopy.
  PROP_Cart_IssoWade_B  night cart (cart_01, cart_02): maroon cabinet on bicycle wheels, glass display box with a
                        cool-white LED strip, white corrugated canopy with an LED tube and small coloured pole
                        lights, trays of fried crabs and prawn vadai (food_01, stylised), wok and steel bowls.
  Shared small props    gas cylinder (red and blue), plastic stool, a stack of steel bowls.
  PROP_CartFood_IssoWade_A / _B  (round 2) the food, modelled: mid-poly crabs, prawn vadai and lentil vadai
                        instanced by Geometry Nodes onto steel trays and shelves. Each is its own piece on its cart's
                        pivot (cart_set always places it), so cart + food stay inside the 1,500-tri street-prop cap.

The shapes are modelled in Blender by citylib/cart_model.py (primitives + Bevel / Weighted Normal, Geometry
Nodes for the spokes, the corrugation and the vadai stacks), unwrapped into one shared atlas and baked by
tools/city/build_carts.py. Everything uses one material, MAT_Cart_IssoWade_A (SHD_HeroLit over
T_CartIssoWade_*); the LED strips and pole lights are emissive texels of the same material (no real lights).

Frame (same as the street kit): x along the cart (handle end +x), the customer / display side faces -y, z up,
pivot on the ground under the cart's middle. Dressing turns -y towards the promenade, the back to the sea.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

MATERIAL = "MAT_Cart_IssoWade_A"
TEXTURE_SET = "CartIssoWade"          # T_CartIssoWade_BaseMap / _MaskMap / _Emission in Art/World/Textures
TRIS_JSON = os.path.join(os.path.dirname(__file__), "carts_tris.json")   # measured by build_carts.py
BLEND = os.path.join(os.path.dirname(__file__), "..", "assets", "PROP_Cart_IssoWade.blend")


@dataclass(frozen=True)
class CartPiece:
    name: str
    width: float        # x extent (m)
    depth: float        # y extent (m)
    height: float       # top (m)
    budget: int         # LOD0 triangle cap: street prop 100-1,500 (AGENTS.md); small props <= 300
    refs: list = field(default_factory=list)


CART_A = "PROP_Cart_IssoWade_A"
CART_B = "PROP_Cart_IssoWade_B"
CYL_RED = "PROP_GasCylinder_Red_01"
CYL_BLUE = "PROP_GasCylinder_Blue_01"
STOOL = "PROP_Stool_Plastic_01"
BOWLS = "PROP_SteelBowls_Stack_01"
FOOD_A = "PROP_CartFood_IssoWade_A"   # cart A's shelf stock (round 2: modelled food, its own piece for the budget)
FOOD_B = "PROP_CartFood_IssoWade_B"   # cart B's display: crabs, prawn vadai, lentil vadai stacks (LED-lit looks)
FOOD_FOR = {CART_A: FOOD_A, CART_B: FOOD_B}
ON_CART = (CART_A, CART_B, FOOD_A, FOOD_B)   # placed at the cart's own pivot, no promenade check of their own

PIECES: dict[str, CartPiece] = {p.name: p for p in (
    CartPiece(CART_A, 2.35, 1.2, 2.16, 1500, ["cart_03"]),
    CartPiece(CART_B, 2.25, 1.5, 2.28, 1500, ["cart_01", "cart_02", "food_01"]),
    CartPiece(CYL_RED, 0.32, 0.32, 0.62, 300, ["cart_01"]),
    CartPiece(CYL_BLUE, 0.32, 0.32, 0.62, 300, ["cart_02", "cart_03"]),
    CartPiece(STOOL, 0.40, 0.40, 0.44, 300, ["cart_02"]),
    CartPiece(BOWLS, 0.34, 0.34, 0.16, 300, ["cart_01", "cart_03"]),
    CartPiece(FOOD_A, 1.6, 0.6, 1.95, 1500, ["cart_03"]),
    CartPiece(FOOD_B, 1.3, 0.5, 1.46, 1500, ["cart_01", "food_01"]),
)}

# Small props beside a cart, in the cart's frame (x along, -y = promenade side): (piece, x, y, yaw offset)
CYLINDER_AT = (1.02, 0.18)      # under the handle end, sea side of the wheel (cart_01, cart_03)
STOOL_AT = (1.45, -0.55)        # the vendor's stool at the handle end, promenade side (cart_02)
BOWLS_AT = (-1.05, 0.25)        # washing bowls on the ground at the leg end


def cart_set(slot: int, h: int) -> list[tuple[str, float, float, float]]:
    """Pieces for the `slot`-th cart along the promenade, `h` a stable hash of its position: the cart, its food
    piece (same pivot), then its small props.

    A and B alternate with a hashed swap so the row mixes day and night carts without a strict rhythm; two in
    three carts get a gas cylinder (red or blue by hash), every other one a stool, B carts sometimes bowls."""
    cart = CART_A if (slot + (h >> 3)) % 2 == 0 else CART_B
    out = [(cart, 0.0, 0.0, 0.0), (FOOD_FOR[cart], 0.0, 0.0, 0.0)]   # the cart's food always rides with it
    if h % 3 != 2:
        out.append((CYL_RED if (h >> 1) % 2 else CYL_BLUE, *CYLINDER_AT, math.radians((h % 40) - 20)))
    if (h >> 2) % 2 == 0:
        out.append((STOOL, *STOOL_AT, math.radians((h % 30) - 15)))
    if cart == CART_B and (h >> 4) % 3 == 0:
        out.append((BOWLS, *BOWLS_AT, 0.0))
    return out


def to_world(cx: float, cy: float, yaw: float, lx: float, ly: float) -> tuple[float, float]:
    """Cart-frame offset (lx, ly) to plan coordinates for a cart at (cx, cy) turned by yaw."""
    c, s = math.cos(yaw), math.sin(yaw)
    return cx + c * lx - s * ly, cy + s * lx + c * ly


def measured_tris() -> dict[str, int]:
    if not os.path.exists(TRIS_JSON):
        return {}
    with open(TRIS_JSON, encoding="utf-8") as fh:
        return json.load(fh)
