"""Canonical Round 3 submission strategies — v100.

Thin wrappers directly on the canonical implementation classes, skipping the
entire v25→v26→v27→v28→theo_v7 empty-wrapper chain.  The export exporter only
needs to inline three files (mm_first_v4_combo, smile_iv_scalper, velvet_strat_v3)
instead of seven, cutting the submission size significantly.

Execution logic is unchanged — same params, same algorithms.
"""

from prosperity.strategies.round_3.tibo.mm_first_v4_combo import R3GuardedAnchorMMStrategy
from prosperity.strategies.round_3.tibo.smile_iv_scalper import GammaScalpZGatedMixinStrategy
from prosperity.strategies.round_3.tibo.velvet_strat_v3 import VEVOptionMMV3


class VelvetMMV100(R3GuardedAnchorMMStrategy):
    """VELVETFRUIT_EXTRACT — GuardedAnchorMM, anchor=5250."""


class GammaScalpV100(GammaScalpZGatedMixinStrategy):
    """VEV option accumulator — GammaScalp with optional z-score gate."""


class VEVOptionMMV100(VEVOptionMMV3):
    """VEV passive bid-heavy option MM (5200/5300/5400)."""


class HydroMMV100(R3GuardedAnchorMMStrategy):
    """HYDROGEL_PACK — GuardedAnchorMM, anchor=10000."""
