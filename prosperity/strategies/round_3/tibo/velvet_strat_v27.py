"""velvet_strat_v27 — SmileIVScalerStrategy for OTM/NTM VEV strikes.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WHAT CHANGED FROM v26
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VEV_5100 / 5200 / 5300 / 5400 — replace with SmileIVScalerV27

    v26 approach for these strikes:
      5100: GammaScalpV26 (skip_when_expensive=True, fixed BS fair)
      5200: VEVOptionMMV26 (passive bid-heavy, mode="none")
      5300: VEVOptionMMV26 (passive bid-heavy, mode="none")
      5400: VEVOptionMMV26 (passive bid-heavy, prevent_crossing=True)

    v27 approach (SmileIVScalerV27):
      - Fits polynomial smile across all live VEV strikes (LOO per strike)
      - Computes residual = market_iv - smile_fair_iv
      - Tracks EWMA baseline mean + std of residual → z-score
      - Aggressively buys when option is cheap vs smile (resid_z <= -0.9)
      - Exits passively and via taker when IV mean-reverts
      - Passive maker around smile-adjusted reference price

    Hypothesis: smile-relative fair value is more accurate than a fixed
    prior IV, capturing genuine cross-strike mispricings.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PRODUCT → CLASS MAPPING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VELVETFRUIT_EXTRACT  → VelvetMMV26    (unchanged from v26)
  VEV_4000             → VEVOptionMMV26 (unchanged from v26)
  VEV_4500             → GammaScalpV26  (skip=False, unchanged from v26)
  VEV_5000             → GammaScalpV26  (skip=False, unchanged from v26)
  VEV_5100             → SmileIVScalerV27 (NEW — replaces GammaScalp skip=True)
  VEV_5200             → SmileIVScalerV27 (NEW — replaces VEVOptionMMV26)
  VEV_5300             → SmileIVScalerV27 (NEW — replaces VEVOptionMMV26)
  VEV_5400             → SmileIVScalerV27 (NEW — replaces VEVOptionMMV26)
"""
from __future__ import annotations

from prosperity.strategies.round_3.tibo.smile_iv_scalper import SmileIVScalerStrategy


class SmileIVScalerV27(SmileIVScalerStrategy):
    """SmileIVScalerStrategy for v27 (VEV_5100/5200/5300/5400)."""
