"""velvet_strat_v28 — Best-of-both: v7 VELVETFRUIT/4000 + v26 5200/5300/5400 + ablation skip fixes.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WHAT CHANGED FROM tibo_theo_v7
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. VEV_5000 — disable skip_when_expensive
       Theo v7: skip=True, thresh=1.0  → 10,668 PnL
       v28:     skip=False              → +~1-2k expected (v26 ablation: +2,265)

  2. VEV_5200 / 5300 / 5400 — switch from GammaScalp to VEVOptionMMV26 (passive bid-heavy)
       Theo v7: GammaScalp skip=True → 7,536 / 3,152 / -286
       v26:     VEVOptionMMV26        → 11,882 / 4,426 / 330  (+6.2k total)
       Reason: OTM options benefit from passive accumulation on every tick,
               not from aggressive entry gated by zscore. The gamma-scalp taker
               logic adds noise without meaningful edge at these strikes.

  3. VELVETFRUIT / VEV_4000 / VEV_4500 / VEV_5100 / VEV_5500 — unchanged from v7
       VELVETFRUIT: R3GuardedAnchorMM (massive edge vs our passive MM)
       VEV_4000:    GammaScalp skip=True thresh=1.5 (v7 already better)
       VEV_4500:    GammaScalp skip=True thresh=2.0 (near-equiv to skip=False)
       VEV_5100:    GammaScalp skip=True thresh=0.5 (ablation: keep skip)
       VEV_5500:    GammaScalp skip=True thresh=0.5 (keep Theo's config)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PRODUCT → CLASS MAPPING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VELVETFRUIT_EXTRACT  → TheoV7VelvetMM   (R3GuardedAnchorMMStrategy)
  VEV_4000             → TheoV7GammaScalp (skip=True thresh=1.5)
  VEV_4500             → TheoV7GammaScalp (skip=True thresh=2.0)
  VEV_5000             → TheoV7GammaScalp (skip=False)      ← changed
  VEV_5100             → TheoV7GammaScalp (skip=True thresh=0.5)
  VEV_5200             → VEVOptionMMV28   (passive bid-heavy) ← changed
  VEV_5300             → VEVOptionMMV28   (passive bid-heavy) ← changed
  VEV_5400             → VEVOptionMMV28   (passive bid-heavy) ← changed
  VEV_5500             → TheoV7GammaScalp (skip=True thresh=0.5)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EXPECTED BACKTEST RESULTS (3-day, --match-trades realistic)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  v7 baseline:    +165,634
  Changes:        +~2,000 (VEV_5000 skip=False)
                  +4,346  (VEV_5200 passive)
                  +1,274  (VEV_5300 passive)
                  +616    (VEV_5400 passive)
  Expected v28:   ~173,870
"""
from __future__ import annotations

from prosperity.strategies.round_3.tibo.velvet_strat_theo_v7 import TheoV7GammaScalp, TheoV7VelvetMM
from prosperity.strategies.round_3.tibo.velvet_strat_v26 import VEVOptionMMV26


class VEVOptionMMV28(VEVOptionMMV26):
    """Passive bid-heavy option MM for v28 (VEV_5200/5300/5400).

    Identical to VEVOptionMMV26. The passive accumulation strategy
    outperforms GammaScalp for far-OTM options by ~6k on 3-day backtest.
    """


class TheoV7GammaScalpV28(TheoV7GammaScalp):
    """GammaScalp for v28 — config-driven, no logic changes."""


class TheoV7VelvetMMV28(TheoV7VelvetMM):
    """VELVETFRUIT MM for v28 — identical to v7."""
