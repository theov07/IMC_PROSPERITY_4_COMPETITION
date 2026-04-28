from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_4.theo.R4_BASELINE__r4_velvet_options_only__pnl158k_dd73k_ratio217 import (
    GammaScalpZGatedStrategy as BaselineGammaScalpZGatedStrategy,
)
from prosperity.strategies.round_4.theo.R4_BASELINE__r4_velvet_options_only__pnl158k_dd73k_ratio217 import (
    R3GuardedAnchorMMStrategy as BaselineGuardedAnchorStrategy,
    call_delta,
    call_gamma,
    call_price,
)


class BaselineMarkedGammaScalpStrategy(BaselineGammaScalpZGatedStrategy):
    """Baseline gamma scalp with a conservative counterparty overlay."""

    def _counterparty_signal(self, state: TradingState, memory: Dict[str, Any]) -> float:
        if not bool(self.params.get("mark_signal_enabled", False)):
            memory["_mark_signal"] = 0.0
            return 0.0

        buy_weights = self.params.get("mark_buy_weights", {})
        sell_weights = self.params.get("mark_sell_weights", {})
        alpha = float(self.params.get("mark_signal_alpha", 0.45))
        decay = float(self.params.get("mark_signal_decay", 0.75))
        qty_norm = max(1.0, float(self.params.get("mark_qty_norm", 4.0)))
        clip = max(0.0, float(self.params.get("mark_signal_clip", 4.0)))

        raw = 0.0
        for trade in state.market_trades.get(self.product, []):
            raw += float(buy_weights.get(getattr(trade, "buyer", None), 0.0)) * float(trade.quantity)
            raw += float(sell_weights.get(getattr(trade, "seller", None), 0.0)) * float(trade.quantity)
        raw /= qty_norm

        prev = float(memory.get("_mark_signal", 0.0))
        signal = (prev * decay) if abs(raw) < 1e-9 else (alpha * raw + (1.0 - alpha) * prev)
        if clip > 0.0:
            signal = max(-clip, min(clip, signal))
        memory["_mark_signal"] = signal
        return signal

    def _mark_fair_shift(self, mark_signal: float) -> float:
        per_unit = float(self.params.get("mark_fair_shift_per_unit", 0.0))
        max_shift = float(self.params.get("mark_max_fair_shift", 0.0))
        if per_unit == 0.0 or max_shift <= 0.0:
            return 0.0
        shift = mark_signal * per_unit
        return max(-max_shift, min(max_shift, shift))

    def _mark_entry_multiplier(self, mark_signal: float) -> float:
        boost = float(self.params.get("mark_entry_size_boost", 0.0))
        clip = max(1e-9, float(self.params.get("mark_signal_clip", 4.0)))
        if boost <= 0.0 or mark_signal <= 0.0:
            return 1.0
        return 1.0 + boost * min(1.0, mark_signal / clip)

    def _mark_target_bonus(self, mark_signal: float) -> int:
        bonus = int(self.params.get("mark_target_bonus", 0))
        clip = max(1e-9, float(self.params.get("mark_signal_clip", 4.0)))
        if bonus <= 0 or mark_signal <= 0.0:
            return 0
        return int(round(bonus * min(1.0, mark_signal / clip)))

    def _mark_skip_relax(self, mark_signal: float) -> float:
        relax = float(self.params.get("mark_skip_relax", 0.0))
        clip = max(1e-9, float(self.params.get("mark_signal_clip", 4.0)))
        if relax <= 0.0 or mark_signal <= 0.0:
            return 0.0
        return relax * min(1.0, mark_signal / clip)

    def _mark_should_unwind(self, mark_signal: float) -> bool:
        threshold = float(self.params.get("mark_unwind_threshold", 0.0))
        return threshold > 0.0 and mark_signal <= -threshold

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        p = self._read_params(state)
        S = self._get_spot(state)
        if S is None:
            return [], 0

        z = self._update_zscore(S, memory, p)
        mark_signal = self._counterparty_signal(state, memory)
        memory["_velvet_z"] = z
        memory["_mark_signal"] = mark_signal

        fair = call_price(S, p["K"], p["T"], p["implied_vol_prior"]) + self._mark_fair_shift(mark_signal)
        gamma = call_gamma(S, p["K"], p["T"], p["implied_vol_prior"])
        delta = call_delta(S, p["K"], p["T"], p["implied_vol_prior"])
        memory["_gamma"] = gamma
        memory["_delta"] = delta
        memory["_fair_iv"] = fair
        memory["_spot"] = S
        memory["_T"] = p["T"]

        if fair < p["min_quote_price"]:
            return [], 0

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        target_qty = p["target_qty"] + self._mark_target_bonus(mark_signal)

        if p["T"] < p["unwind_tte_threshold"] or position >= target_qty:
            if sell_cap > 0 and position > 0:
                ask_px = book.best_ask - 1
                if ask_px <= book.best_bid:
                    ask_px = book.best_bid + 1
                qty = min(p["passive_bid_size"], sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "unwind"
            return orders, 0

        if (
            p["sell_when_very_expensive"]
            and z is not None
            and z > p["zscore_sell_threshold"]
            and position > 0
            and sell_cap > 0
        ):
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            sell_qty = max(1, int(round(position * p["sell_size_pct"])))
            qty = min(sell_qty, sell_cap, position, p["passive_bid_size"])
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "z_profit_take"
            return orders, 0

        effective_zskip = p["zscore_skip_threshold"] + self._mark_skip_relax(mark_signal)
        if p["skip_when_expensive"] and z is not None and z > effective_zskip:
            memory["_mode"] = "z_skipped_expensive"
            return [], 0

        if self._mark_should_unwind(mark_signal) and position > 0 and sell_cap > 0:
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            qty = min(p["passive_bid_size"], sell_cap, position)
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "mark_unwind"
            return orders, 0

        size_mult = self._mark_entry_multiplier(mark_signal)
        if p["boost_when_cheap"] and z is not None and z < -p["zscore_boost_threshold"]:
            size_mult = max(size_mult, p["entry_size_boost"])
            memory["_mode"] = "z_boost_cheap"
        else:
            memory["_mode"] = "accumulate"

        eff_entry_size = max(1, int(round(p["entry_size"] * size_mult)))
        eff_passive_size = max(1, int(round(p["passive_bid_size"] * size_mult)))

        if buy_cap > 0 and position < target_qty:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty = -order_depth.sell_orders.get(ask, 0)
                headroom = target_qty - position
                take_qty = min(ask_qty, buy_cap, eff_entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty
                    position += take_qty

        if buy_cap > 0 and position < target_qty:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(eff_passive_size, buy_cap, target_qty - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0


class BaselineMarkedGuardedAnchorStrategy(BaselineGuardedAnchorStrategy):
    """Baseline velvet MM with counterparty-driven anchor and target nudges."""

    def _counterparty_signal(self, state: TradingState, memory: Dict[str, Any]) -> float:
        if not bool(self.params.get("mark_signal_enabled", False)):
            memory["_mark_signal"] = 0.0
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
        memory["_mark_signal"] = signal
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

        mark_signal = self._counterparty_signal(state, memory)
        anchor_shift = self._mark_anchor_shift(mark_signal)
        inventory_target = self._mark_inventory_target(mark_signal)
        use_anchor = self._use_anchor(float(mid), float(anchor) + anchor_shift, position, memory)

        memory["_guard_use_anchor"] = int(use_anchor)
        memory["_mark_anchor_shift"] = anchor_shift
        memory["_mark_inventory_target"] = inventory_target

        old_anchor = self.params.get("anchor_price")
        old_inventory_target = self.params.get("inventory_target", 0)
        old_ar = self.params.get("ar_gain")
        old_take_lo = self.params.get("take_edge_lo")
        old_take_hi = self.params.get("take_edge_hi")
        try:
            self.params["anchor_price"] = float(old_anchor) + anchor_shift
            self.params["inventory_target"] = inventory_target

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
