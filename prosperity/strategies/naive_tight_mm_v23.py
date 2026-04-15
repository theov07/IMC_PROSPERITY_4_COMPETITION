"""Naive passive market maker V23.

V23 starts from V17 and adds an explicit long carry floor for IPR:

- when the trend is strong enough, target a minimum long inventory floor
- while we are below that floor, slightly accelerate accumulation
- when we trim in trend, never sell below the carry floor

This is meant to keep the good "long carry" behavior of V17 while letting us
monetize a few local extensions without draining the core long too early.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV23Strategy(BaseStrategy):

    def _take_orders(
        self,
        order_depth: OrderDepth,
        adjusted_mid: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
        take_buy_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        orders: List[Order] = []
        take_count = 0
        buy_take_remaining = min(buy_cap, max(0, take_buy_cap))

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > adjusted_mid - buy_edge or buy_cap <= 0 or buy_take_remaining <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap, buy_take_remaining)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            buy_take_remaining -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < adjusted_mid + sell_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            take_count += 1

        return orders, buy_cap, sell_cap, take_count

    def _apply_inventory_sizing(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.35))
        aggravate_min_frac = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost_frac = float(self.params.get("unwind_boost_frac", 0.25))

        limit = float(self.position_limit())
        pressure = abs(position - inv_target) / max(1.0, limit)

        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        aggravate_frac = 1.0 - (1.0 - aggravate_min_frac) * scaled
        unwind_mult = 1.0 + unwind_boost_frac * scaled

        if position > inv_target:
            if buy_size > 0:
                buy_size = max(1, int(round(buy_size * aggravate_frac)))
            if sell_size > 0:
                sell_size = min(sell_cap, max(1, int(round(sell_size * unwind_mult))))
        elif position < inv_target:
            if sell_size > 0:
                sell_size = max(1, int(round(sell_size * aggravate_frac)))
            if buy_size > 0:
                buy_size = min(buy_cap, max(1, int(round(buy_size * unwind_mult))))

        return buy_size, sell_size

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        take_edge = float(self.params.get("take_edge", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 0.0))
        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_threshold = float(self.params.get("toxic_threshold", 0.6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.5))
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))

        signal_mode = str(self.params.get("signal_mode", "trend"))
        anchor_price = float(self.params.get("anchor_price", 0.0))
        trend_alpha = float(self.params.get("trend_alpha", 0.0))
        trend_sensitivity = float(self.params.get("trend_sensitivity", 1.0))
        trend_max_shift = float(self.params.get("trend_max_shift", 5.0))
        trend_inv_target_per_tick = float(self.params.get("trend_inv_target_per_tick", 0.0))
        trend_take_boost = float(self.params.get("trend_take_boost", 0.0))
        trend_jump_threshold = float(self.params.get("trend_jump_threshold", 0.0))
        trend_hold_threshold = float(self.params.get("trend_hold_threshold", 0.0))
        trend_hold_min_position_frac = float(self.params.get("trend_hold_min_position_frac", 1.01))
        trend_hold_sell_size_frac = float(self.params.get("trend_hold_sell_size_frac", 0.0))

        fast_alpha = float(self.params.get("fast_alpha", 0.22))
        dip_window = int(self.params.get("dip_window", 30))
        dip_trend_threshold = float(self.params.get("dip_trend_threshold", 2.0))
        dip_min_pullback = float(self.params.get("dip_min_pullback", 4.0))
        dip_take_boost = float(self.params.get("dip_take_boost", 0.35))
        dip_buy_size_boost = float(self.params.get("dip_buy_size_boost", 0.15))
        chase_max_extension = float(self.params.get("chase_max_extension", 1.5))
        chase_take_edge_penalty = float(self.params.get("chase_take_edge_penalty", 0.75))
        chase_take_size_frac = float(self.params.get("chase_take_size_frac", 0.5))
        max_take_buy_size = int(self.params.get("max_take_buy_size", self.position_limit()))

        core_position_frac = float(self.params.get("core_position_frac", 0.80))
        rebuy_block_buy_size_frac = float(self.params.get("rebuy_block_buy_size_frac", 0.15))
        rebuy_block_take_cap_frac = float(self.params.get("rebuy_block_take_cap_frac", 0.0))
        rebuy_block_extension_threshold = float(self.params.get("rebuy_block_extension_threshold", 0.5))
        trim_trend_threshold = float(self.params.get("trim_trend_threshold", 4.0))
        trim_extension_threshold = float(self.params.get("trim_extension_threshold", 1.0))
        trim_sell_size = int(self.params.get("trim_sell_size", 6))
        trim_ask_improve_ticks = int(self.params.get("trim_ask_improve_ticks", 1))

        carry_floor_trend_threshold = float(self.params.get("carry_floor_trend_threshold", 4.0))
        carry_floor_position_frac = float(self.params.get("carry_floor_position_frac", 0.875))
        carry_fill_take_boost = float(self.params.get("carry_fill_take_boost", 0.35))
        carry_fill_buy_size_boost = float(self.params.get("carry_fill_buy_size_boost", 0.20))
        carry_fill_take_cap = int(self.params.get("carry_fill_take_cap", 8))
        carry_trim_start_frac = float(self.params.get("carry_trim_start_frac", 0.90))
        carry_trim_signal_edge = float(self.params.get("carry_trim_signal_edge", 1.0))
        carry_trim_size = int(self.params.get("carry_trim_size", 2))
        carry_trim_cooldown_ticks = int(self.params.get("carry_trim_cooldown_ticks", 8))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        trend_shift = 0.0
        inv_target = 0
        limit = self.position_limit()

        if signal_mode == "mean_rev" and anchor_price != 0.0:
            raw_signal = anchor_price - mid
            trend_shift = max(-trend_max_shift, min(trend_max_shift, raw_signal * trend_sensitivity))
            inv_target = int(round(max(-limit, min(limit, trend_shift * trend_inv_target_per_tick))))

        elif signal_mode == "trend" and trend_alpha > 0.0:
            trend_ema = memory.get("trend_ema")
            if trend_ema is None:
                trend_ema = mid
            trend_ema = trend_alpha * mid + (1.0 - trend_alpha) * trend_ema
            memory["trend_ema"] = trend_ema

            raw_signal = mid - trend_ema
            trend_shift = max(-trend_max_shift, min(trend_max_shift, raw_signal * trend_sensitivity))
            inv_target = int(round(max(-limit, min(limit, trend_shift * trend_inv_target_per_tick))))

        adjusted_mid = mid + trend_shift

        fast_ema = memory.get("fast_ema")
        if fast_ema is None:
            fast_ema = mid
        fast_ema = fast_alpha * mid + (1.0 - fast_alpha) * fast_ema
        memory["fast_ema"] = fast_ema

        recent_highs = memory.setdefault("recent_highs", [])
        recent_highs.append(mid)
        if dip_window > 0 and len(recent_highs) > dip_window:
            del recent_highs[:-dip_window]
        recent_high = max(recent_highs) if recent_highs else mid

        pullback = recent_high - mid
        extension = mid - fast_ema
        on_dip = trend_shift >= dip_trend_threshold and pullback >= dip_min_pullback
        chasing = trend_shift >= dip_trend_threshold and extension >= chase_max_extension and not on_dip

        carry_floor_active = signal_mode == "trend" and trend_shift >= carry_floor_trend_threshold
        carry_floor_target = int(round(limit * carry_floor_position_frac)) if carry_floor_active else 0
        effective_inv_target = max(inv_target, carry_floor_target)
        below_carry_floor = carry_floor_active and position < carry_floor_target

        core_position = int(round(limit * core_position_frac))
        above_core = position >= core_position
        block_rebuy = above_core and not on_dip and extension >= rebuy_block_extension_threshold and not below_carry_floor

        bid_is_rich = book.best_bid >= adjusted_mid + carry_trim_signal_edge
        carry_trim_start = int(round(limit * carry_trim_start_frac))
        trim_mode = (
            position >= carry_trim_start
            and position > carry_floor_target
            and bid_is_rich
            and state.timestamp - int(memory.get("last_carry_trim_ts", -10**9)) >= carry_trim_cooldown_ticks * 100
        )

        buy_edge = take_edge
        sell_edge = take_edge

        pressure = abs(position - effective_inv_target) / max(1.0, float(limit))
        if position < effective_inv_target:
            buy_edge = max(0.0, buy_edge - unwind_take_edge * pressure)
        elif position > effective_inv_target:
            sell_edge = max(0.0, sell_edge - unwind_take_edge * pressure)

        if trend_shift > 0.0:
            buy_edge = buy_edge - trend_shift * trend_take_boost
        elif trend_shift < 0.0:
            sell_edge = sell_edge - (-trend_shift) * trend_take_boost

        if on_dip:
            buy_edge = max(0.0, buy_edge - dip_take_boost)
        elif chasing:
            buy_edge = buy_edge + chase_take_edge_penalty

        if below_carry_floor:
            buy_edge = max(0.0, buy_edge - carry_fill_take_boost)

        take_buy_cap = max_take_buy_size
        if chasing:
            take_buy_cap = max(1, int(round(take_buy_cap * chase_take_size_frac)))
        if block_rebuy:
            take_buy_cap = int(round(limit * rebuy_block_take_cap_frac))
        if below_carry_floor:
            take_buy_cap = max(take_buy_cap, carry_fill_take_cap)

        if carry_floor_active:
            sell_room = max(0, position - carry_floor_target)
            sell_cap = min(sell_cap, sell_room)

        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth,
            adjusted_mid=adjusted_mid,
            buy_edge=buy_edge,
            sell_edge=sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            take_buy_cap=take_buy_cap,
        )
        orders.extend(take_orders)

        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}

        real_best_ask = book.best_ask
        for ask_price, _ in book.ask_levels:
            if ask_price not in swept_ask_prices:
                real_best_ask = ask_price
                break

        real_best_bid = book.best_bid
        for bid_price, _ in book.bid_levels:
            if bid_price not in swept_bid_prices:
                real_best_bid = bid_price
                break

        spread = real_best_ask - real_best_bid
        if spread >= 2:
            bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1)
            ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1)
        else:
            bid_price = real_best_bid
            ask_price = real_best_ask

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        buy_size, sell_size = self._apply_inventory_sizing(
            position=position,
            inv_target=effective_inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if on_dip and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * (1.0 + dip_buy_size_boost)))))
        if below_carry_floor and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * (1.0 + carry_fill_buy_size_boost)))))
        if block_rebuy and buy_size > 0:
            buy_size = int(round(buy_size * rebuy_block_buy_size_frac))
            buy_size = min(buy_cap, max(0, buy_size))

        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")
        bid_jumped = bool(prev_best_bid is not None and real_best_bid == prev_best_bid + 1)
        ask_jumped = bool(prev_best_ask is not None and real_best_ask == prev_best_ask - 1)

        flow_history = memory.setdefault("flow_history", [])
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None and trades:
            for trade in trades:
                if trade.price >= prev_best_ask:
                    flow_history.append(trade.quantity)
                elif trade.price <= prev_best_bid:
                    flow_history.append(-trade.quantity)
            if len(flow_history) > toxic_window:
                del flow_history[:-toxic_window]

        flow_score = 0.0
        if flow_history:
            signed = sum(flow_history)
            total = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total

        suppress_toxic = (
            (flow_score > 0 and trend_shift > 1.0)
            or (flow_score < 0 and trend_shift < -1.0)
        )
        if not suppress_toxic:
            if flow_score > toxic_threshold and sell_size > 0:
                sell_size = max(1, int(round(sell_size * toxic_size_frac)))
            elif flow_score < -toxic_threshold and buy_size > 0:
                buy_size = max(1, int(round(buy_size * toxic_size_frac)))

        if bid_jumped and sell_size > 0:
            if trend_shift >= -trend_jump_threshold:
                sell_size = max(1, int(round(sell_size * jump_size_frac)))
        if ask_jumped and buy_size > 0:
            if trend_shift <= trend_jump_threshold:
                buy_size = max(1, int(round(buy_size * jump_size_frac)))

        hold_long_trend = (
            signal_mode == "trend"
            and trend_shift >= trend_hold_threshold > 0.0
            and position >= int(round(limit * trend_hold_min_position_frac))
        )

        if trim_mode and sell_cap > 0:
            trim_room = max(0, position - carry_floor_target)
            sell_size = min(sell_cap, trim_room, max(1, carry_trim_size))
            ask_price = max(real_best_bid + 1, real_best_ask - trim_ask_improve_ticks)
            if sell_size > 0:
                memory["last_carry_trim_ts"] = state.timestamp
        elif hold_long_trend and sell_size > 0:
            allowed_sell = max(0, position - carry_floor_target) if carry_floor_active else sell_cap
            if trend_hold_sell_size_frac <= 0.0:
                sell_size = 0
            else:
                sell_size = int(round(sell_size * trend_hold_sell_size_frac))
                sell_size = min(sell_cap, allowed_sell, max(1, sell_size))

        if carry_floor_active and sell_size > 0:
            sell_size = min(sell_size, max(0, position - carry_floor_target))

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["prev_best_bid"] = real_best_bid
        memory["prev_best_ask"] = real_best_ask
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_flow_score"] = flow_score
        memory["last_take_count"] = take_count
        memory["inv_target"] = effective_inv_target
        memory["trend_shift"] = trend_shift
        memory["hold_long_trend"] = hold_long_trend
        memory["pullback"] = pullback
        memory["extension"] = extension
        memory["on_dip"] = on_dip
        memory["chasing"] = chasing
        memory["above_core"] = above_core
        memory["block_rebuy"] = block_rebuy
        memory["trim_mode"] = trim_mode
        memory["carry_floor_target"] = carry_floor_target
        memory["below_carry_floor"] = below_carry_floor

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "flow_score": flow_score,
                "takes": take_count,
                "trend_shift": round(trend_shift, 2),
                "inv_target": effective_inv_target,
                "carry_floor": carry_floor_target,
                "below_carry_floor": int(below_carry_floor),
                "pullback": round(pullback, 2),
                "extension": round(extension, 2),
                "on_dip": int(on_dip),
                "chasing": int(chasing),
                "above_core": int(above_core),
                "block_rebuy": int(block_rebuy),
                "trim_mode": int(trim_mode),
                "hold_long_trend": int(hold_long_trend),
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if memory.get("trend_ema") is not None:
            out["trend_ema"] = memory["trend_ema"]
        if memory.get("fast_ema") is not None:
            out["fast_ema"] = memory["fast_ema"]
        trend_shift = memory.get("trend_shift", 0.0)
        prev_bid = memory.get("last_bid_price")
        prev_ask = memory.get("last_ask_price")
        if prev_bid is not None and prev_ask is not None and trend_shift:
            out["adjusted_mid"] = (prev_bid + prev_ask) / 2.0 + trend_shift
        return out
