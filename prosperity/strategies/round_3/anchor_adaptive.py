"""AnchorAdaptive — v4_F5 combo with confidence-weighted anchor.

Design (based on Codex r3_naive_champion analysis):

  r3_naive_champion (v4_F5 + anchor=10000) makes +124k backtest on 3 days but
  loses -3k live because the anchor is rigid when the live market drifts away.
  The solution isn't to drop the anchor (tried: r3_v4_tracking = -290k), but
  to make the anchor's influence *conditional on how much we trust it*:

    fair = w * anchor_fixed + (1 - w) * mid_smooth

  where `w` ∈ [0, 1] reflects confidence in the anchor:
    - w → 1 : market oscillates around anchor (mean-reverting regime) → anchor works
    - w → 0 : market drifts persistently away (trend regime) → fall back to mid_smooth

Confidence signal (anchor_confidence):
  - track drift_ewma = EWMA of (mid - anchor_fixed)
  - |drift_ewma| < confidence_drift_mean_rev (default 0.5) → w=1
  - |drift_ewma| > confidence_drift_trend    (default 5.0) → w=0
  - in between → linear interpolation

This preserves the +124k backtest alpha (mean-reverting days match w≈1) while
shielding us from the -3k live failure (trending days get w≈0, acts as naive
book-follower).

Params (inherited from MMFirstV4ComboStrategy + new confidence knobs):
  anchor_price                    : the fixed fair reference (e.g. 10000)
  confidence_drift_mean_rev      : |drift_ewma| below = full confidence (default 0.5)
  confidence_drift_trend         : |drift_ewma| above = zero confidence (default 5.0)
  confidence_drift_alpha         : EWMA alpha for drift (default 0.01, slow)
  confidence_min                 : floor on w to avoid fully disabling anchor (default 0.0)
  confidence_max                 : cap on w (default 1.0)
  all other v4_F5 params         : see mm_first_v4_combo docstring
"""
from __future__ import annotations

from typing import Any, Dict

from typing import List, Optional, Set, Tuple
from datamodel import Order, OrderDepth, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.round_2.leo.mm_first_v4_combo import MMFirstV4ComboStrategy


class AnchorAdaptiveStrategy(MMFirstV4ComboStrategy):
    """v4_F5 with confidence-weighted fair value = w * anchor + (1-w) * mid_smooth."""

    def _compute_anchor_signal(
        self,
        mid: float,
        book: BookSnapshot,
        mid_smooth: float,
        memory: Dict[str, Any],
    ) -> float:
        """Return adaptive fair value blending anchor and mid_smooth based on drift."""
        anchor_price = self.params.get("anchor_price")
        if anchor_price is None:
            # No anchor configured → fall back to parent behavior (mid_smooth)
            return super()._compute_anchor_signal(mid, book, mid_smooth, memory)

        anchor_fixed = float(anchor_price)

        # Track EWMA of drift = mid - anchor_fixed.
        # Slow alpha (0.01) so short-term noise doesn't flip the regime.
        drift = mid - anchor_fixed
        drift_alpha = float(self.params.get("confidence_drift_alpha", 0.01))
        drift_ewma_prev = memory.get("_anchor_drift_ewma", 0.0)
        drift_ewma = drift_alpha * drift + (1.0 - drift_alpha) * drift_ewma_prev
        memory["_anchor_drift_ewma"] = drift_ewma

        # Confidence w: 1 when |drift| small (mean-rev), 0 when large (trend).
        drift_mean_rev = float(self.params.get("confidence_drift_mean_rev", 0.5))
        drift_trend = float(self.params.get("confidence_drift_trend", 5.0))
        abs_drift = abs(drift_ewma)
        if abs_drift <= drift_mean_rev:
            w = 1.0
        elif abs_drift >= drift_trend:
            w = 0.0
        else:
            # Linear interpolation between drift_mean_rev and drift_trend
            w = 1.0 - (abs_drift - drift_mean_rev) / (drift_trend - drift_mean_rev)

        # Apply floor/cap
        w = max(
            float(self.params.get("confidence_min", 0.0)),
            min(float(self.params.get("confidence_max", 1.0)), w),
        )
        memory["_anchor_confidence"] = w

        # Blended fair value
        fair_blended = w * anchor_fixed + (1.0 - w) * mid_smooth

        # AR(1) shift (reused from parent logic) — apply on top of blended fair.
        ar_gain = float(self.params.get("ar_gain", 0.0))
        if ar_gain > 0.0:
            source = str(self.params.get("ar_shift_source", "mid_smooth"))
            signal = {"mid": mid, "mid_smooth": mid_smooth}.get(source, mid_smooth)
            prev_signal = memory.get("_ar_prev_signal")
            if prev_signal is not None:
                ar_shift = -ar_gain * (signal - prev_signal)
                fair_blended += ar_shift
            memory["_ar_prev_signal"] = signal

        # Record for dashboard
        memory["_fair_blended"] = fair_blended
        memory["_anchor_ema"] = fair_blended  # reuse existing field for compat
        return fair_blended

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        """Capture memory reference for _fire_takers override, then delegate to parent."""
        self._current_memory = memory
        return super().compute_orders(state, book, order_depth, position, memory)

    def _fire_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        buy_edge: float,
        sell_edge: float,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        """Gate takers on anchor confidence: below threshold → block takers.

        When anchor regime is weak (drift trend), v4_F5's aggressive taker logic
        crosses the spread chasing false edges — this is what made r3_v4_tracking
        fail at -290k. Gating here preserves the +124k alpha on mean-rev days
        while avoiding the taker explosion on trend days.
        """
        memory = getattr(self, "_current_memory", None) or {}
        w = float(memory.get("_anchor_confidence", 1.0))
        gate = float(self.params.get("confidence_take_gate", 0.8))
        if w < gate:
            # Effectively-infinite edges = no taker crosses this tick.
            buy_edge = 1_000_000.0
            sell_edge = 1_000_000.0
        return super()._fire_takers(
            order_depth, fair_value, bid_size, ask_size,
            buy_cap, sell_cap, buy_edge, sell_edge,
        )

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory) if hasattr(super(), "feature_prices") else {}
        if (f := memory.get("_fair_blended")) is not None:
            out["AnchorAdaptiveFair"] = f
        if (w := memory.get("_anchor_confidence")) is not None:
            out["AnchorConfidence"] = w
        if (d := memory.get("_anchor_drift_ewma")) is not None:
            out["AnchorDriftEwma"] = d
        return out
