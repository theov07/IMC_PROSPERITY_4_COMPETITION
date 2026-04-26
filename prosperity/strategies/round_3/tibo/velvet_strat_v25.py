"""velvet_strat_v25 — Best-of-both combination of v3 and v24.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WHAT CHANGED FROM v3 / v24
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Problem 1 — VELVETFRUIT in v24:
    mm_first_v4_combo's AR signal built a -185 short on D2 when price rose,
    costing ~6.5k. The model is directional and wrong when the underlying
    trends against its mean-reversion assumption.
    Fix: revert to VelvetMMV3 (passive penny-improve, never directional).
    Cost: loses D0/D1 AR alpha (+5k/day) but eliminates directional risk.

  Problem 2 — VEV_5200/5300 in v24:
    GammaScalpZGatedStrategy with skip_when_expensive=True + threshold=0.5
    silenced accumulation whenever VELVETFRUIT z > 0.5. On D1 (trending up),
    VEV_5200 only traded 27 units vs v3's 300.
    Fix: use VEVOptionMMV25 (≡ VEVOptionMMV3) — never skips bids, only
    adapts the ask side via z-score.

  v24 wins kept:
    VEV_4500 (+16k), VEV_5000 (+9.5k), VEV_5100 (+19.5k) via GammaScalpV25
    — these strikes were completely absent in v3.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CLASSES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VelvetMMV25      — VELVETFRUIT MM (≡ VelvetMMV3: passive MM + delta hedge)
  VEVOptionMMV25   — VEV options MM for 4000/5200/5300/5400
                     (≡ VEVOptionMMV3: penny-improve + z-score ask adaptation)
  GammaScalpV25    — VEV options accumulation for 4500/5000/5100
                     (≡ GammaScalpZGatedStrategy: BS-fair-value taker + passive bid)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PRODUCT → CLASS MAPPING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VELVETFRUIT_EXTRACT  → VelvetMMV25
  VEV_4000             → VEVOptionMMV25  (symmetric MM, ask_offset=1)
  VEV_4500             → GammaScalpV25   (taker when ask ≤ BS_fair)
  VEV_5000             → GammaScalpV25
  VEV_5100             → GammaScalpV25
  VEV_5200             → VEVOptionMMV25  (bid-heavy, ask_adapt z-score)
  VEV_5300             → VEVOptionMMV25  (bid-heavy, ask_adapt z-score)
  VEV_5400             → VEVOptionMMV25  (prevent_crossing=True, passive only)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EXECUTION ORDER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VEV strategies run first → publish vev_total_delta to shared dict
  VelvetMMV25 runs last    → reads vev_total_delta for implicit delta hedge

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BACKTEST RESULTS (3-day, --match-trades realistic)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VELVETFRUIT: +20,127   VEV_4000: +12,157
  VEV_4500:   +16,061   VEV_5000:  +9,536   VEV_5100: +19,564
  VEV_5200:   +11,882   VEV_5300:  +4,426   VEV_5400:    +330
  TOTAL: +94,083  (vs v3: +48,922, v24: +91,560)
"""
from __future__ import annotations

from prosperity.strategies.round_3.tibo.gamma_scalp_zgated import GammaScalpZGatedStrategy
from prosperity.strategies.round_3.tibo.velvet_strat_v3 import VelvetMMV3, VEVOptionMMV3


class VelvetMMV25(VelvetMMV3):
    """VELVETFRUIT MM for v25.

    Passive penny-improve + inventory-adaptive sizing + implicit delta hedge
    from accumulated VEV option positions. Writes z-score to shared dict for
    VEVOptionMMV25 (1-tick lag, negligible at 500-tick window).

    Identical to VelvetMMV3. Kept as a named class so v25 has its own
    identity and can diverge independently in future versions.
    """


class VEVOptionMMV25(VEVOptionMMV3):
    """VEV option MM for v25 (strikes 4000 / 5200 / 5300 / 5400).

    Penny-improve bid + wide ask (rarely sells) → passively accumulates long
    calls. Z-score adapts the ask side only (ask_adapt mode):
      expensive → tighten ask (sell some at peak)
      cheap     → widen ask extra (hold through dip)
    Never skips bids — always accumulates regardless of z-score.

    Identical to VEVOptionMMV3. Kept as a named class so v25 has its own
    identity and can diverge independently in future versions.
    """


class GammaScalpV25(GammaScalpZGatedStrategy):
    """VEV option accumulation for v25 (strikes 4500 / 5000 / 5100).

    Active taker when ask ≤ BS_fair + edge_ticks, passive penny-improve bid
    otherwise. Z-score gates entry (skip_when_expensive). Unwinds near expiry
    (TTE < unwind_tte_threshold).

    These strikes were excluded from v3 (illiquid in passive fill model) but
    earn significant MTM gains in v24/v25 via active taker entries.

    Identical to GammaScalpZGatedStrategy. Kept as a named class so v25 has
    its own identity and can diverge independently in future versions.
    """
