"""velvet_strat_theo_v7 — Theo's velvettuned_v7 as modular strategy classes.

Implements Theo's velvettuned_v7 VELVETFRUIT + VEV strategies verbatim,
using our modular infrastructure. HYDROGEL is excluded.

Product → class mapping (mirrors v7 PRODUCTS config):
  VELVETFRUIT_EXTRACT  → TheoV7VelvetMM (R3GuardedAnchorMMStrategy)
  VEV_4000..VEV_5500   → TheoV7GammaScalp (GammaScalpZGatedMixinStrategy)
"""
from __future__ import annotations

from prosperity.strategies.round_3.tibo.mm_first_v4_combo import R3GuardedAnchorMMStrategy
from prosperity.strategies.round_3.tibo.smile_iv_scalper import GammaScalpZGatedMixinStrategy


class TheoV7VelvetMM(R3GuardedAnchorMMStrategy):
    """VELVETFRUIT_EXTRACT strategy from Theo's velvettuned_v7."""


class TheoV7GammaScalp(GammaScalpZGatedMixinStrategy):
    """VEV option accumulation strategy from Theo's velvettuned_v7."""
