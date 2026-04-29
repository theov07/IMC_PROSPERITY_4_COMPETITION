"""R5 product groups (10 wiki-defined categories of 5 each).

Source : docs/wiki/round_5_wiki.txt
"""
from __future__ import annotations

from typing import Dict, List, Optional

GROUPS: Dict[str, List[str]] = {
    "GALAXY_SOUNDS": [
        "GALAXY_SOUNDS_DARK_MATTER",
        "GALAXY_SOUNDS_BLACK_HOLES",
        "GALAXY_SOUNDS_PLANETARY_RINGS",
        "GALAXY_SOUNDS_SOLAR_WINDS",
        "GALAXY_SOUNDS_SOLAR_FLAMES",
    ],
    "SLEEP_POD": [
        "SLEEP_POD_SUEDE",
        "SLEEP_POD_LAMB_WOOL",
        "SLEEP_POD_POLYESTER",
        "SLEEP_POD_NYLON",
        "SLEEP_POD_COTTON",
    ],
    "MICROCHIP": [
        "MICROCHIP_CIRCLE",
        "MICROCHIP_OVAL",
        "MICROCHIP_SQUARE",
        "MICROCHIP_RECTANGLE",
        "MICROCHIP_TRIANGLE",
    ],
    "PEBBLES": [
        "PEBBLES_XS",
        "PEBBLES_S",
        "PEBBLES_M",
        "PEBBLES_L",
        "PEBBLES_XL",
    ],
    "ROBOT": [
        "ROBOT_VACUUMING",
        "ROBOT_MOPPING",
        "ROBOT_DISHES",
        "ROBOT_LAUNDRY",
        "ROBOT_IRONING",
    ],
    "UV_VISOR": [
        "UV_VISOR_YELLOW",
        "UV_VISOR_AMBER",
        "UV_VISOR_ORANGE",
        "UV_VISOR_RED",
        "UV_VISOR_MAGENTA",
    ],
    "TRANSLATOR": [
        "TRANSLATOR_SPACE_GRAY",
        "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL",
        "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_VOID_BLUE",
    ],
    "PANEL": [
        "PANEL_1X2",
        "PANEL_2X2",
        "PANEL_1X4",
        "PANEL_2X4",
        "PANEL_4X4",
    ],
    "OXYGEN_SHAKE": [
        "OXYGEN_SHAKE_MORNING_BREATH",
        "OXYGEN_SHAKE_EVENING_BREATH",
        "OXYGEN_SHAKE_MINT",
        "OXYGEN_SHAKE_CHOCOLATE",
        "OXYGEN_SHAKE_GARLIC",
    ],
    "SNACKPACK": [
        "SNACKPACK_CHOCOLATE",
        "SNACKPACK_VANILLA",
        "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY",
        "SNACKPACK_RASPBERRY",
    ],
}

GROUP_NAMES: List[str] = list(GROUPS.keys())

# Reverse lookup: product -> group
_PRODUCT_TO_GROUP: Dict[str, str] = {p: g for g, ms in GROUPS.items() for p in ms}


def group_of(product: str) -> Optional[str]:
    return _PRODUCT_TO_GROUP.get(product)


# === Within-group inverse-pair sub-clusters (from R5 correlation analysis) ===
# SNACKPACK : Cluster A (CHOC, RASP) vs Cluster B (VAN, STRAW, PIST), corr ≈ -0.92
SNACKPACK_CLUSTER_A = ["SNACKPACK_CHOCOLATE", "SNACKPACK_RASPBERRY"]
SNACKPACK_CLUSTER_B = ["SNACKPACK_VANILLA", "SNACKPACK_STRAWBERRY", "SNACKPACK_PISTACHIO"]

# PEBBLES : XL anti-correlated with all others (-0.48 to -0.51)
PEBBLES_OUTLIER = "PEBBLES_XL"
PEBBLES_REST = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L"]

# Inter-group LEVEL clusters (from r5_groups.py)
# Cluster + (positively corr): GALAXY_SOUNDS, SLEEP_POD, UV_VISOR
# Cluster - (positively corr): MICROCHIP, ROBOT, PANEL
# A vs B inversely correlated (-0.47 to -0.84)
MACRO_CLUSTER_PLUS = ["GALAXY_SOUNDS", "SLEEP_POD", "UV_VISOR"]
MACRO_CLUSTER_MINUS = ["MICROCHIP", "ROBOT", "PANEL"]
