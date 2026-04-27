"""R3GuardedAnchorMM — MMFirstV4Combo + guard logic on VELVET.

Optional delta-hedge layer (R4): when `delta_hedge_enabled=True`, override the
position passed to the parent strategy by `position - target_velvet_pos`, where
`target_velvet_pos = -sum_K(delta_K * pos_K)` across VEV options. This makes
the inventory-skew machinery push quotes to bring net portfolio delta to 0.


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
from prosperity.options.black_scholes import call_delta
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.round_2.leo.mm_first_v4_combo import MMFirstV4ComboStrategy

# VEV strikes used for delta-hedge aggregation
_VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


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

        # Delta-hedge layer (opt-in): inject inventory_target so MMFirstV4Combo's
        # skew/sizing helpers treat real_pos - target as the effective inventory.
        dh_saved_target = None
        if bool(self.params.get("delta_hedge_enabled", False)) and mid is not None:
            target_pos = self._compute_velvet_hedge_target(state, float(mid), memory)
            memory["_dh_target_pos"] = target_pos
            hedge_strength = float(self.params.get("delta_hedge_strength", 1.0))
            scaled_target = int(round(target_pos * hedge_strength))
            memory["_dh_scaled_target"] = scaled_target
            dh_saved_target = self.params.get("inventory_target", 0)
            self.params["inventory_target"] = scaled_target

        # Counterparty bias layer (opt-in): shift anchor based on trader-flow signal.
        # When Mark 55+67 net buying or Mark 01+14 net selling → bullish → anchor up.
        # When opposite → bearish → anchor down.
        cp_saved_anchor = None
        if bool(self.params.get("counterparty_bias_enabled", False)):
            cp_signal = self._counterparty_signal(state, memory)
            cp_threshold = float(self.params.get("cp_signal_threshold", 30.0))
            cp_max_offset = float(self.params.get("cp_max_anchor_offset", 5.0))
            cp_scale = float(self.params.get("cp_anchor_scale_per_unit", 0.05))
            old_anchor = self.params.get("anchor_price")
            if old_anchor is not None and abs(cp_signal) > cp_threshold:
                offset = max(-cp_max_offset, min(cp_max_offset, cp_signal * cp_scale))
                cp_saved_anchor = old_anchor
                self.params["anchor_price"] = old_anchor + offset
                memory["_cp_anchor_offset"] = offset

        try:
            return self._compute_orders_inner(state, book, order_depth, position, memory, mid)
        finally:
            if dh_saved_target is not None:
                self.params["inventory_target"] = dh_saved_target
            if cp_saved_anchor is not None:
                self.params["anchor_price"] = cp_saved_anchor

    def _compute_orders_inner(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
        mid,
    ) -> Tuple[List[Order], int]:
        anchor = self.params.get("anchor_price")
        if mid is None or anchor is None:
            return super().compute_orders(state, book, order_depth, position, memory)

        # Trend gate (opt-in via params): when downtrend persistent, disable
        # bullish mean-rev BUYs (the cause of the D3 last-5% bleed in R4 baseline).
        if bool(self.params.get("trend_gate_enabled", False)):
            trend_dir = self._trend_direction(float(mid), memory)
            memory["_trend_dir"] = trend_dir
            if trend_dir == -1 and position >= int(self.params.get("trend_gate_long_block_pos", 0)):
                return self._run_trend_blocked(state, book, order_depth, position, memory)

        # VWAP gate (opt-in via params): more robust trend signal than EMA-fast/slow.
        if bool(self.params.get("vwap_gate_enabled", False)):
            vwap_dir = self._vwap_signal(state, float(mid), memory)
            memory["_vwap_dir"] = vwap_dir
            if vwap_dir == -1 and position >= int(self.params.get("vwap_gate_long_block_pos", 0)):
                return self._run_trend_blocked(state, book, order_depth, position, memory)

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

    def _compute_velvet_hedge_target(
        self,
        state: TradingState,
        mid: float,
        memory: Dict[str, Any],
    ) -> int:
        """Compute target VELVET position to delta-hedge our option portfolio.

        Sum across all VEV_K options held: delta_K * pos_K
        Target VELVET = -sum (so portfolio delta = 0).
        Capped at +/- velvet position_limit.
        """
        # Use VELVET prior_vol if set, else default
        iv = float(self.params.get("delta_hedge_implied_vol", 0.0125))
        # Compute T from initial TTE + day mapping
        ts_per_day = timestamp_units_per_day_from_params(self.params)
        tte0 = resolve_initial_tte_days(
            getattr(state, "traderData", "") or "",
            self.params.get("tte_days_initial", 4.0),
            self.params.get("historical_tte_by_day"),
        )
        T_days = time_to_expiry_days(int(state.timestamp), tte0,
                                     timestamp_units_per_day=ts_per_day)
        T_years = max(T_days / 365.0, 1e-6)

        total_delta = 0.0
        for K in _VEV_STRIKES:
            sym = f"VEV_{K}"
            pos = state.position.get(sym, 0)
            if pos == 0:
                continue
            d = call_delta(mid, float(K), T_years, iv)
            total_delta += d * pos

        target = -int(round(total_delta))
        # Cap at +/- VELVET position limit (default 200)
        cap = int(self.params.get("position_limit", 200))
        target = max(-cap, min(cap, target))
        memory["_dh_total_delta"] = total_delta
        return target

    def _run_trend_blocked(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        """Same as guard-off mode (pure passive penny-improve, no anchor, no taker)."""
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
        if (trend_dir := memory.get("_trend_dir")) is not None:
            out["TrendDir"] = float(trend_dir)
        return out
