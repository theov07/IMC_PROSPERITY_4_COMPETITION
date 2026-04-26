"""R3GuardedAnchorMM — MMFirstV4Combo + guard logic on VELVET.

Theo's discovery (v5_guardedtuned, +74k VELVET vs our +27k with naive R2 anchor):

The anchor pull (toward fixed mid 5250) is GREAT when price is mean-reverting
back to the anchor. But TERRIBLE when price drifts away (we keep loading
wrong-way inventory and get crushed).

Solution: only USE the anchor pull when:
  - We're near the anchor (mean-rev band), OR
  - We're far but the trend is SHRINKING the distance (= reverting)
  - AND we don't have wrong-way inventory (long below anchor / short above)

When we're trending AWAY from anchor with wrong-way inventory:
  Disable anchor + ar_gain + takers → fall back to pure passive penny-improve.

Params (additions on top of MMFirstV4Combo):
  guard_trend_alpha          : EWMA alpha for trend EMA (default 0.45 — fast)
  guard_reversion_threshold  : require dist*trend ≤ -threshold (default 7.5)
  guard_inventory_dist       : wrong-way inventory threshold (default 40)
  guard_min_dist             : min |dist| for "reverting" zone (default 0)
  guard_max_dist             : max |dist| for "reverting" zone (default 80)
  guard_near_band            : |dist| ≤ this → always use anchor (default 0)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_2.leo.mm_first_v4_combo import MMFirstV4ComboStrategy


class R3GuardedAnchorMMStrategy(MMFirstV4ComboStrategy):
    """MMFirstV4Combo + regime detector that disables anchor when wrong-way."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        mid = book.mid_price
        anchor = self.params.get("anchor_price")
        if mid is None or anchor is None:
            return super().compute_orders(state, book, order_depth, position, memory)

        use_anchor = self._use_anchor(float(mid), float(anchor), position, memory)
        memory["_guard_use_anchor"] = int(use_anchor)

        if use_anchor:
            return super().compute_orders(state, book, order_depth, position, memory)

        # Disable anchor + takers, run as pure passive MM
        old_anchor = self.params.get("anchor_price")
        old_ar = self.params.get("ar_gain")
        old_take_lo = self.params.get("take_edge_lo")
        old_take_hi = self.params.get("take_edge_hi")
        try:
            self.params["anchor_price"] = None
            self.params["ar_gain"] = 0.0
            self.params["take_edge_lo"] = 1_000_000.0
            self.params["take_edge_hi"] = 1_000_000.0
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = old_anchor
            self.params["ar_gain"] = old_ar
            self.params["take_edge_lo"] = old_take_lo
            self.params["take_edge_hi"] = old_take_hi

    def _use_anchor(self, mid: float, anchor: float, position: int, memory: Dict[str, Any]) -> bool:
        """Decide whether to use the anchor pull this tick."""
        prev_mid = memory.get("_guard_prev_mid")
        memory["_guard_prev_mid"] = mid
        raw_trend = 0.0 if prev_mid is None else mid - float(prev_mid)
        alpha = float(self.params.get("guard_trend_alpha", 0.3))
        trend = float(memory.get("_guard_trend_ema", raw_trend))
        trend = alpha * raw_trend + (1.0 - alpha) * trend
        memory["_guard_trend_ema"] = trend

        dist = mid - anchor
        memory["_guard_dist"] = dist
        memory["_guard_trend"] = trend

        near_band = float(self.params.get("guard_near_band", 0.0))
        min_dist = float(self.params.get("guard_min_dist", 0.0))
        max_dist = float(self.params.get("guard_max_dist", 80.0))
        threshold = float(self.params.get("guard_reversion_threshold", 0.0))
        inventory_dist = float(self.params.get("guard_inventory_dist", 40.0))

        near_anchor = abs(dist) <= near_band
        # "reverting" = dist far enough to be meaningful, AND trend opposite to dist
        # dist > 0 (above anchor) + trend < 0 (going down) → dist*trend < 0 ≤ -threshold
        reverting = (
            min_dist <= abs(dist) <= max_dist
            and (dist * trend) <= -threshold
        )
        wrong_way_inventory = (
            (position > 0 and dist < -inventory_dist)
            or (position < 0 and dist > inventory_dist)
        )
        return (near_anchor or reverting) and not wrong_way_inventory

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (dist := memory.get("_guard_dist")) is not None:
            out["GuardDist"] = float(dist)
        if (trend := memory.get("_guard_trend")) is not None:
            out["GuardTrend"] = float(trend)
        if (use_anchor := memory.get("_guard_use_anchor")) is not None:
            out["GuardOn"] = float(use_anchor)
        return out
