"""velvet_strat_v26 — thin v26 wrappers around the v25 round-3 strategies.

These classes intentionally do not change logic. v26 was an ablation / config
iteration over v25, so the code-level strategy classes remain aliases with
version-specific names.
"""
from __future__ import annotations

from prosperity.strategies.round_3.tibo.velvet_strat_v25 import GammaScalpV25, VEVOptionMMV25, VelvetMMV25


class VelvetMMV26(VelvetMMV25):
    """VELVETFRUIT MM for v26."""


class VEVOptionMMV26(VEVOptionMMV25):
    """VEV option MM for v26."""


class GammaScalpV26(GammaScalpV25):
    """VEV option accumulation for v26."""
