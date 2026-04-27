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

        mark_signal = self._counterparty_signal(state, memory)
        anchor_shift = self._mark_anchor_shift(mark_signal)
        inventory_target = self._mark_inventory_target(mark_signal)
        use_anchor = self._use_anchor(float(mid), float(anchor), position, memory)
        memory["_guard_use_anchor"] = int(use_anchor)
        memory["_mark_signal"] = mark_signal
        memory["_mark_anchor_shift"] = anchor_shift
        memory["_mark_inventory_target"] = inventory_target

        old_anchor = self.params.get("anchor_price")
        old_inventory_target = self.params.get("inventory_target", 0)
        old_ar = self.params.get("ar_gain")
        old_take_lo = self.params.get("take_edge_lo")
        old_take_hi = self.params.get("take_edge_hi")
        try:
            self.params["inventory_target"] = inventory_target
            if old_anchor is not None:
                self.params["anchor_price"] = float(old_anchor) + anchor_shift

            if use_anchor:
                return super().compute_orders(state, book, order_depth, position, memory)

            self.params["anchor_price"] = None
            self.params["ar_gain"] = 0.0
            self.params["take_edge_lo"] = 1_000_000.0
            self.params["take_edge_hi"] = 1_000_000.0
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = old_anchor
            self.params["inventory_target"] = old_inventory_target
            self.params["ar_gain"] = old_ar
            self.params["take_edge_lo"] = old_take_lo
            self.params["take_edge_hi"] = old_take_hi

    def _counterparty_signal(self, state: TradingState, memory: Dict[str, Any]) -> float:
        if not bool(self.params.get("mark_signal_enabled", False)):
            return 0.0

        buy_weights = self.params.get("mark_buy_weights", {})
        sell_weights = self.params.get("mark_sell_weights", {})
        alpha = float(self.params.get("mark_signal_alpha", 0.35))
        decay = float(self.params.get("mark_signal_decay", 0.72))
        qty_norm = max(1.0, float(self.params.get("mark_qty_norm", 10.0)))
        clip = max(0.0, float(self.params.get("mark_signal_clip", 6.0)))

        raw = 0.0
        for trade in state.market_trades.get(self.product, []):
            raw += float(buy_weights.get(getattr(trade, "buyer", None), 0.0)) * float(trade.quantity)
            raw += float(sell_weights.get(getattr(trade, "seller", None), 0.0)) * float(trade.quantity)
        raw /= qty_norm

        prev = float(memory.get("_mark_signal", 0.0))
        signal = (prev * decay) if abs(raw) < 1e-9 else (alpha * raw + (1.0 - alpha) * prev)
        if clip > 0.0:
            signal = max(-clip, min(clip, signal))
        return signal

    def _mark_anchor_shift(self, mark_signal: float) -> float:
        per_unit = float(self.params.get("mark_anchor_shift_per_unit", 0.0))
        max_shift = float(self.params.get("mark_anchor_shift_max", 0.0))
        if per_unit == 0.0 or max_shift <= 0.0:
            return 0.0
        shift = mark_signal * per_unit
        return max(-max_shift, min(max_shift, shift))

    def _mark_inventory_target(self, mark_signal: float) -> int:
        per_unit = float(self.params.get("mark_inventory_target_per_unit", 0.0))
        max_target = int(self.params.get("mark_inventory_target_max", 0))
        if per_unit == 0.0 or max_target <= 0:
            return 0
        target = int(round(mark_signal * per_unit))
        return max(-max_target, min(max_target, target))

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
        if (mark_signal := memory.get("_mark_signal")) is not None:
            out["MarkSignal"] = float(mark_signal)
        if (mark_target := memory.get("_mark_inventory_target")) is not None:
            out["MarkTarget"] = float(mark_target)
        return out
