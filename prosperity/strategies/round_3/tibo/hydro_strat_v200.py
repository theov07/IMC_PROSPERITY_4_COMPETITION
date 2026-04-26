"""HYDROGEL_PACK standalone strategy — v200.

Thin wrapper directly on R3GuardedAnchorMMStrategy (mm_first_v4_combo.py).
Anchor = 10000, tuned for HYDROGEL's tighter spreads and lower volatility.
"""

from prosperity.strategies.round_3.tibo.mm_first_v4_combo import R3GuardedAnchorMMStrategy


class HydroMMV200(R3GuardedAnchorMMStrategy):
    pass
