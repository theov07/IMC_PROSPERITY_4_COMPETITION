"""Round 3 guarded anchor market maker.

This keeps the profitable Round 2 anchor machinery available, but only while
short-term price action is moving back toward the anchor. When the market is
drifting away, the strategy falls back to passive book-following quotes and
blocks anchor-driven takers.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_2.leo.mm_first_v4_combo import MMFirstV4ComboStrategy


class R3GuardedAnchorMMStrategy(MMFirstV4ComboStrategy):
    """Anchor MM with a live-drift guard."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[list[Order], int]:
        mid = book.mid_price
        anchor = self.params.get("anchor_price")
        if mid is None or anchor is None:
            return super().compute_orders(state, book, order_depth, position, memory)

        use_anchor = self._use_anchor(float(mid), float(anchor), position, memory)
        memory["_guard_use_anchor"] = int(use_anchor)

        if use_anchor:
            return super().compute_orders(state, book, order_depth, position, memory)

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
        reverting = min_dist <= abs(dist) <= max_dist and (dist * trend) <= -threshold
        wrong_way_inventory = (position > 0 and dist < -inventory_dist) or (
            position < 0 and dist > inventory_dist
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
