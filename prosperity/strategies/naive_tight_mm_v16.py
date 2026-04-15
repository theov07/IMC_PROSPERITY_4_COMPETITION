"""Naive passive market maker V16.

V16 keeps the V11 IPR hold profile, then adds one focused idea from the
strategy discussion:

- buy the dips, don't chase too much

Concretely:
- In a positive trend, we maintain the long-biased hold behavior from V11.
- We track a fast EMA plus a recent-high window.
- When the market is in uptrend but locally pulled back, we modestly increase
  buy aggressiveness ("buy the dip").
- When the market is extended above the fast EMA, we cap and penalize buy
  taking so we do not rush into the first upward stretch ("don't chase").

This is intentionally narrower than the rejected V14 family: it tries to fix
entry timing without reintroducing heavy inventory cycling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV16Strategy(BaseStrategy):

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
        dip_min_pullback = float(self.params.get("dip_min_pullback", 3.0))
        dip_take_boost = float(self.params.get("dip_take_boost", 0.35))
        dip_buy_size_boost = float(self.params.get("dip_buy_size_boost", 0.15))
        chase_max_extension = float(self.params.get("chase_max_extension", 2.5))
        chase_take_edge_penalty = float(self.params.get("chase_take_edge_penalty", 0.75))
        chase_take_size_frac = float(self.params.get("chase_take_size_frac", 0.5))
        max_take_buy_size = int(self.params.get("max_take_buy_size", self.position_limit()))

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

        buy_edge = take_edge
        sell_edge = take_edge

        pressure = abs(position - inv_target) / max(1.0, float(limit))
        if position < inv_target:
            buy_edge = max(0.0, buy_edge - unwind_take_edge * pressure)
        elif position > inv_target:
            sell_edge = max(0.0, sell_edge - unwind_take_edge * pressure)

        if trend_shift > 0.0:
            buy_edge = buy_edge - trend_shift * trend_take_boost
        elif trend_shift < 0.0:
            sell_edge = sell_edge - (-trend_shift) * trend_take_boost

        if on_dip:
            buy_edge = max(0.0, buy_edge - dip_take_boost)
        elif chasing:
            buy_edge = buy_edge + chase_take_edge_penalty

        take_buy_cap = max_take_buy_size
        if chasing:
            take_buy_cap = max(1, int(round(take_buy_cap * chase_take_size_frac)))

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
            inv_target=inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if on_dip and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * (1.0 + dip_buy_size_boost)))))

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
        if hold_long_trend and sell_size > 0:
            if trend_hold_sell_size_frac <= 0.0:
                sell_size = 0
            else:
                sell_size = int(round(sell_size * trend_hold_sell_size_frac))
                sell_size = min(sell_cap, max(1, sell_size))

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
        memory["inv_target"] = inv_target
        memory["trend_shift"] = trend_shift
        memory["hold_long_trend"] = hold_long_trend
        memory["pullback"] = pullback
        memory["extension"] = extension
        memory["on_dip"] = on_dip
        memory["chasing"] = chasing

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
                "inv_target": inv_target,
                "pullback": round(pullback, 2),
                "extension": round(extension, 2),
                "on_dip": int(on_dip),
                "chasing": int(chasing),
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
