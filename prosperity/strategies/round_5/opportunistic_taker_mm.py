"""Round 5 market maker with conservative opportunistic taker overlay.

Keeps the existing passive logic family per product, but adds a separate taker
layer when the top of book is meaningfully away from an internal fair anchor.

Supported modes:
  - naive: tight passive MM + microprice/trend fair anchor
  - carry: inventory_carry_mm baseline + microprice/trend fair anchor
  - pair: pair_skip_mm baseline + pair-aware fair anchor
  - coint: coint_mm_v1 baseline + extra opportunistic taker / unwind
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class OpportunisticTakerMMStrategy(BaseStrategy):
    def _clamp(self, value: float, limit: float) -> float:
        return max(-limit, min(limit, value))

    def _online_z(self, value: float, key: str, memory: Dict[str, Any], window: int) -> float:
        buf = memory.setdefault(key, [])
        buf.append(value)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(30, window // 8):
            return 0.0
        n = len(buf)
        mu = sum(buf) / n
        var = sum((x - mu) ** 2 for x in buf) / max(n - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return 0.0
        return (value - mu) / std

    def _trend(self, mid: float, memory: Dict[str, Any], key: str, half_life: int) -> float:
        alpha = 2.0 / (half_life + 1.0)
        ema = memory.get(key, mid)
        ema = alpha * mid + (1.0 - alpha) * ema
        memory[key] = ema
        return mid - ema

    def _coint_signal(
        self,
        *,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[float, int]:
        p = self.params
        partner = str(p["partner_product"])
        mean_hl = float(p.get("mean_half_life", 5000))
        z_win = int(p.get("z_window", 1000))

        pod = state.order_depths.get(partner)
        if pod is None or not pod.buy_orders or not pod.sell_orders or book.mid_price is None:
            return 0.0, 0

        mid_a = float(book.mid_price)
        mid_b = (max(pod.buy_orders) + min(pod.sell_orders)) / 2.0

        alpha_m = 1.0 - math.exp(-1.0 / mean_hl)
        mean_a = memory.get("_coint_mean_a", mid_a)
        mean_b = memory.get("_coint_mean_b", mid_b)
        mean_a = alpha_m * mid_a + (1.0 - alpha_m) * mean_a
        mean_b = alpha_m * mid_b + (1.0 - alpha_m) * mean_b
        memory["_coint_mean_a"] = mean_a
        memory["_coint_mean_b"] = mean_b
        if mean_a == 0 or mean_b == 0:
            return 0.0, 0

        spread = mid_a / mean_a - mid_b / mean_b
        alpha_z = 2.0 / (z_win + 1)
        n_ticks = int(memory.get("_coint_ticks", 0)) + 1
        memory["_coint_ticks"] = n_ticks
        mu_z = memory.get("_coint_mu", spread)
        var_z = memory.get("_coint_var", 1e-6)
        delta = spread - mu_z
        mu_z = mu_z + alpha_z * delta
        var_z = (1.0 - alpha_z) * (var_z + alpha_z * delta * delta)
        memory["_coint_mu"] = mu_z
        memory["_coint_var"] = var_z
        if n_ticks < z_win // 2:
            return 0.0, n_ticks
        sd_z = math.sqrt(var_z) if var_z > 0 else 1e-9
        if sd_z < 1e-9:
            return 0.0, n_ticks
        return (spread - mu_z) / sd_z, n_ticks

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.mid_price is None:
            return [], 0

        p = self.params
        mode = str(p.get("mode", "naive"))
        maker_size = int(p.get("maker_size", 5))
        passive_size = int(p.get("passive_size", maker_size))
        tighten = int(p.get("tighten_ticks", 1))
        hard_pause = int(p.get("hard_pause_at", 9))
        limit = self.position_limit()

        opportunity_size = int(p.get("opportunity_taker_size", 0))
        opportunity_edge = float(p.get("taker_threshold", 1.5))
        opportunity_gate = float(p.get("min_opportunity_ticks", 0.75))
        taker_pos_cap = int(p.get("taker_position_cap", max(limit - 1, 1)))
        taker_cooldown = int(p.get("taker_cooldown_ts", 0))
        min_spread = int(p.get("min_spread_for_taker", 1))

        unwind_min_pos = int(p.get("unwind_min_pos", limit + 1))
        unwind_size = int(p.get("unwind_size", maker_size))
        unwind_edge = float(p.get("unwind_edge", 1.0))

        signal_shift_per_unit = float(p.get("signal_shift_per_unit", 0.0))
        signal_shift_clamp = float(p.get("signal_shift_clamp", 3.0))
        microprice_weight = float(p.get("microprice_weight", 0.0))
        microprice_clamp = float(p.get("microprice_clamp", 2.0))
        trend_weight = float(p.get("trend_weight", 0.0))
        trend_clamp = float(p.get("trend_clamp", 2.0))
        trend_hl = int(p.get("trend_hl", 120))

        inv_skew_thresh = int(p.get("inv_skew_thresh", limit + 1))
        inv_skew_ticks = int(p.get("inv_skew_ticks", 0))
        size_inv_factor = float(p.get("size_inv_factor", 0.0))
        carry_min_pos = int(p.get("carry_pause_min_pos", 3))

        mid = float(book.mid_price)
        spread = int(book.best_ask - book.best_bid)
        micro = book.microprice if book.microprice is not None else mid
        micro_ticks = self._clamp((micro - mid) * microprice_weight, microprice_clamp)
        trend = self._trend(mid, memory, "_ema_mid", trend_hl)
        trend_ticks = self._clamp(trend * trend_weight, trend_clamp)

        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask
        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        signal_value = 0.0
        signal_ticks = 0.0
        coint_z = 0.0
        pair_z = 0.0

        if mode == "pair":
            partner = p.get("partner")
            partner_sign = float(p.get("partner_sign", -1.0))
            pair_thresh = float(p.get("pair_thresh", 1.5))
            z_window = int(p.get("z_window", 300))
            self_z = self._online_z(mid, "_pair_self_z", memory, z_window)
            partner_mid = None
            if partner in state.order_depths:
                pdepth = state.order_depths[partner]
                if pdepth.buy_orders and pdepth.sell_orders:
                    partner_mid = (max(pdepth.buy_orders) + min(pdepth.sell_orders)) / 2.0
            if partner_mid is not None:
                partner_z = self._online_z(partner_mid, "_pair_partner_z", memory, z_window)
                pair_z = self_z - partner_sign * partner_z
                signal_value = pair_z
                signal_ticks = self._clamp(-pair_z * signal_shift_per_unit, signal_shift_clamp)
            if pair_z > pair_thresh:
                post_bid = False
            elif pair_z < -pair_thresh:
                post_ask = False
        elif mode == "carry":
            signal_value = trend
            signal_ticks = self._clamp(-trend * signal_shift_per_unit, signal_shift_clamp)
            if abs(position) >= carry_min_pos:
                if position > 0 and trend < 0:
                    post_bid = False
                elif position < 0 and trend > 0:
                    post_ask = False
        elif mode == "coint":
            coint_z, _ = self._coint_signal(state=state, book=book, memory=memory)
            signal_value = coint_z
            signal_ticks = self._clamp(-coint_z * signal_shift_per_unit, signal_shift_clamp)
        else:
            signal_value = micro - mid
            signal_ticks = 0.0

        fair_anchor = mid + signal_ticks + micro_ticks + trend_ticks
        opportunity_score = max(abs(signal_ticks), abs(micro_ticks), abs(trend_ticks))
        memory["_fair_anchor"] = fair_anchor
        memory["_trend"] = trend
        memory["_pair_z"] = pair_z
        memory["_coint_z"] = coint_z

        bid_shift = 0
        ask_shift = 0
        if abs(position) >= inv_skew_thresh and inv_skew_ticks > 0:
            if position > 0:
                bid_shift -= inv_skew_ticks
                ask_shift -= inv_skew_ticks
            else:
                bid_shift += inv_skew_ticks
                ask_shift += inv_skew_ticks
        bid_p += bid_shift
        ask_p += ask_shift

        if bid_p >= ask_p:
            bid_p = min(bid_p, book.best_ask - 1)
            ask_p = max(ask_p, book.best_bid + 1)
            if bid_p >= ask_p:
                bid_p = book.best_bid
                ask_p = book.best_ask

        orders: List[Order] = []
        buy_room = self.buy_capacity(position)
        sell_room = self.sell_capacity(position)

        if mode == "coint":
            entry_z = float(p.get("entry_z", 1.5))
            exit_z = float(p.get("exit_z", 0.0))
            entry_size = int(p.get("taker_size", opportunity_size))
            if position < 0 and coint_z < exit_z and buy_room > 0:
                qty = min(-position, buy_room, max(book.best_ask_volume, 1))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_ask), qty))
                    self.log_taker_fill(state=state, memory=memory, side="BUY", price=int(book.best_ask), quantity=qty)
                    buy_room -= qty
            elif position > 0 and coint_z > -exit_z and sell_room > 0:
                qty = min(position, sell_room, max(book.best_bid_volume, 1))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_bid), -qty))
                    self.log_taker_fill(state=state, memory=memory, side="SELL", price=int(book.best_bid), quantity=qty)
                    sell_room -= qty

            if position == 0:
                if coint_z > entry_z and sell_room > 0:
                    qty = min(entry_size, sell_room, max(book.best_bid_volume, 1))
                    if qty > 0:
                        orders.append(Order(self.product, int(book.best_bid), -qty))
                        self.log_taker_fill(state=state, memory=memory, side="SELL", price=int(book.best_bid), quantity=qty)
                        sell_room -= qty
                elif coint_z < -entry_z and buy_room > 0:
                    qty = min(entry_size, buy_room, max(book.best_ask_volume, 1))
                    if qty > 0:
                        orders.append(Order(self.product, int(book.best_ask), qty))
                        self.log_taker_fill(state=state, memory=memory, side="BUY", price=int(book.best_ask), quantity=qty)
                        buy_room -= qty

        last_taker_ts = int(memory.get("_last_taker_ts", -10**9))
        can_taker = (
            opportunity_size > 0
            and spread >= min_spread
            and opportunity_score >= opportunity_gate
            and int(state.timestamp) - last_taker_ts >= taker_cooldown
        )
        did_taker = False
        if can_taker:
            if (
                book.best_ask <= fair_anchor - opportunity_edge
                and buy_room > 0
                and position < taker_pos_cap
            ):
                qty = min(opportunity_size, buy_room, max(book.best_ask_volume, 1), taker_pos_cap - position)
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_ask), qty))
                    self.log_taker_fill(state=state, memory=memory, side="BUY", price=int(book.best_ask), quantity=qty)
                    buy_room -= qty
                    memory["_last_taker_ts"] = int(state.timestamp)
                    did_taker = True
            elif (
                book.best_bid >= fair_anchor + opportunity_edge
                and sell_room > 0
                and position > -taker_pos_cap
            ):
                qty = min(opportunity_size, sell_room, max(book.best_bid_volume, 1), taker_pos_cap + position)
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_bid), -qty))
                    self.log_taker_fill(state=state, memory=memory, side="SELL", price=int(book.best_bid), quantity=qty)
                    sell_room -= qty
                    memory["_last_taker_ts"] = int(state.timestamp)
                    did_taker = True

        if not did_taker and abs(position) >= unwind_min_pos:
            if position > 0 and sell_room > 0 and book.best_bid >= fair_anchor + unwind_edge:
                qty = min(unwind_size, sell_room, position, max(book.best_bid_volume, 1))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_bid), -qty))
                    self.log_taker_fill(state=state, memory=memory, side="SELL", price=int(book.best_bid), quantity=qty)
                    sell_room -= qty
            elif position < 0 and buy_room > 0 and book.best_ask <= fair_anchor - unwind_edge:
                qty = min(unwind_size, buy_room, -position, max(book.best_ask_volume, 1))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_ask), qty))
                    self.log_taker_fill(state=state, memory=memory, side="BUY", price=int(book.best_ask), quantity=qty)
                    buy_room -= qty

        if limit > 0 and size_inv_factor > 0.0:
            bid_size = max(1, int(round(passive_size * (1.0 - size_inv_factor * max(position, 0) / limit))))
            ask_size = max(1, int(round(passive_size * (1.0 - size_inv_factor * max(-position, 0) / limit))))
        else:
            bid_size = passive_size
            ask_size = passive_size

        if post_bid and buy_room > 0:
            orders.append(Order(self.product, int(bid_p), min(bid_size, buy_room)))
        if post_ask and sell_room > 0:
            orders.append(Order(self.product, int(ask_p), -min(ask_size, sell_room)))

        memory["_prev_bid_quote"] = int(bid_p)
        memory["_prev_ask_quote"] = int(ask_p)
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_p if post_bid else None,
            ask_price=ask_p if post_ask else None,
            extras={
                "fair": round(fair_anchor, 2),
                "sig": round(signal_value, 3),
                "micro": round(micro - mid, 3),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if "_fair_anchor" in memory:
            out["fair"] = round(memory["_fair_anchor"], 2)
        if "_pair_z" in memory:
            out["pair_z"] = round(memory["_pair_z"], 3)
        if "_coint_z" in memory:
            out["coint_z"] = round(memory["_coint_z"], 3)
        if "_trend" in memory:
            out["trend"] = round(memory["_trend"], 2)
        return out
