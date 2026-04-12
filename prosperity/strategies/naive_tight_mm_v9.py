"""Naive passive market maker V9.

V9 keeps the V8 passive market making core, but changes the directional
overlay for TOMATOES:

1. Smart sizing and selective taking from V8 stay intact.
2. Toxicity filtering from V8 stays intact.
3. The directional bias is now trend-following instead of mean reversion:
   - current pressure from microprice / imbalance / inferred flow
   - pressure EMA over previous ticks
   - confirmation when the same pressure sign persists across ticks
   - optional confirmation from recent price drift in the same direction

The goal is to follow persistent short-term buying/selling pressure without
chasing every single one-tick move in the mid.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV9Strategy(BaseStrategy):
    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _signal_sign(value: float, threshold: float) -> int:
        if value > threshold:
            return 1
        if value < -threshold:
            return -1
        return 0

    def _inventory_pressure(self, position: int) -> float:
        limit = self.position_limit()
        if limit <= 0:
            return 0.0
        return abs(position) / float(limit)

    def _compute_trend_signal(
        self,
        book: BookSnapshot,
        mid: float,
        flow_score: float,
        memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float, float, float]:
        micro_weight = float(self.params.get("trend_micro_weight", 0.0))
        imbalance_weight = float(self.params.get("trend_imbalance_weight", 0.0))
        flow_weight = float(self.params.get("trend_flow_weight", 0.0))
        current_weight_sum = abs(micro_weight) + abs(imbalance_weight) + abs(flow_weight)

        microprice = book.microprice if book.microprice is not None else mid
        micro_scale = float(self.params.get("trend_microprice_scale", 1.0))
        if micro_scale <= 0.0:
            micro_edge = 0.0
        else:
            micro_edge = self._clip((microprice - mid) / micro_scale, -1.0, 1.0)

        imbalance = float(book.imbalance or 0.0)
        clipped_flow = self._clip(flow_score, -1.0, 1.0)

        current_pressure = 0.0
        if current_weight_sum > 0.0:
            current_pressure = (
                micro_weight * micro_edge
                + imbalance_weight * imbalance
                + flow_weight * clipped_flow
            ) / current_weight_sum

        ema_alpha = self._clip(float(self.params.get("trend_pressure_ema_alpha", 0.4)), 0.0, 1.0)
        prev_pressure_ema = float(memory.get("trend_pressure_ema", 0.0))
        if ema_alpha <= 0.0:
            pressure_ema = prev_pressure_ema
        elif ema_alpha >= 1.0:
            pressure_ema = current_pressure
        else:
            pressure_ema = ema_alpha * current_pressure + (1.0 - ema_alpha) * prev_pressure_ema

        prev_mid = memory.get("prev_mid")
        price_scale = float(self.params.get("trend_price_scale", 2.0))
        if prev_mid is None or price_scale <= 0.0:
            price_trend = 0.0
        else:
            price_trend = self._clip((mid - float(prev_mid)) / price_scale, -1.0, 1.0)

        streak_threshold = float(self.params.get("trend_streak_threshold", 0.08))
        current_sign = self._signal_sign(current_pressure, streak_threshold)
        prev_sign = int(memory.get("trend_pressure_sign", 0))
        prev_streak = int(memory.get("trend_pressure_streak", 0))
        if current_sign == 0:
            streak = 0
        elif current_sign == prev_sign:
            streak = prev_streak + 1
        else:
            streak = 1

        streak_cap = max(1, int(self.params.get("trend_streak_cap", 4)))
        streak_factor = min(1.0, streak / float(streak_cap))

        ema_sign = self._signal_sign(pressure_ema, max(1e-9, streak_threshold * 0.5))
        aligned = current_sign != 0 and current_sign == ema_sign
        alignment_signal = current_sign * streak_factor if aligned else 0.0
        price_confirm = price_trend if (current_sign != 0 and price_trend * current_sign > 0.0) else 0.0

        current_weight = float(self.params.get("trend_current_weight", 0.7))
        ema_weight = float(self.params.get("trend_pressure_ema_weight", 0.9))
        streak_weight = float(self.params.get("trend_streak_weight", 0.5))
        price_weight = float(self.params.get("trend_price_confirm_weight", 0.2))
        total_weight = abs(current_weight) + abs(ema_weight) + abs(streak_weight) + abs(price_weight)
        if total_weight <= 0.0:
            raw_signal = pressure_ema
        else:
            raw_signal = (
                current_weight * current_pressure
                + ema_weight * pressure_ema
                + streak_weight * alignment_signal
                + price_weight * price_confirm
            ) / total_weight

        signal_alpha = self._clip(float(self.params.get("trend_signal_alpha", 0.5)), 0.0, 1.0)
        prev_signal = float(memory.get("trend_signal", 0.0))
        if signal_alpha <= 0.0:
            trend_signal = prev_signal
        elif signal_alpha >= 1.0:
            trend_signal = raw_signal
        else:
            trend_signal = signal_alpha * raw_signal + (1.0 - signal_alpha) * prev_signal

        return (
            self._clip(trend_signal, -1.0, 1.0),
            current_pressure,
            pressure_ema,
            float(streak),
            micro_edge,
            price_trend,
        )

    def _take_selective_orders(
        self,
        order_depth: OrderDepth,
        mid: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
    ) -> Tuple[List[Order], int, int, int]:
        orders: List[Order] = []
        take_edge = float(self.params.get("take_edge", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 0.0))
        pressure = self._inventory_pressure(position)

        buy_edge = take_edge
        sell_edge = take_edge
        if position < 0:
            buy_edge = max(0.0, take_edge - unwind_take_edge * pressure)
        elif position > 0:
            sell_edge = max(0.0, take_edge - unwind_take_edge * pressure)

        take_count = 0

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > mid - buy_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < mid + sell_edge or sell_cap <= 0:
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
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.35))
        aggravate_min_frac = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost_frac = float(self.params.get("unwind_boost_frac", 0.25))

        pressure = self._inventory_pressure(position)
        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        aggravate_frac = 1.0 - (1.0 - aggravate_min_frac) * scaled
        unwind_mult = 1.0 + unwind_boost_frac * scaled

        if position > 0:
            if buy_size > 0:
                buy_size = max(1, int(round(buy_size * aggravate_frac)))
            if sell_size > 0:
                sell_size = min(sell_cap, max(1, int(round(sell_size * unwind_mult))))
        elif position < 0:
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
        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_threshold = float(self.params.get("toxic_threshold", 0.6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.5))
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")

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

        trend_signal, current_pressure, pressure_ema, streak, micro_edge, price_trend = self._compute_trend_signal(
            book=book,
            mid=mid,
            flow_score=flow_score,
            memory=memory,
        )
        directional_take_shift = float(self.params.get("directional_take_shift", 0.0))
        directional_mid = mid + trend_signal * directional_take_shift

        take_orders, buy_cap, sell_cap, take_count = self._take_selective_orders(
            order_depth=order_depth,
            mid=directional_mid,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            position=position,
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
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        bid_jumped = bool(prev_best_bid is not None and real_best_bid == prev_best_bid + 1)
        ask_jumped = bool(prev_best_ask is not None and real_best_ask == prev_best_ask - 1)

        if flow_score > toxic_threshold and sell_size > 0:
            sell_size = max(1, int(round(sell_size * toxic_size_frac)))
        elif flow_score < -toxic_threshold and buy_size > 0:
            buy_size = max(1, int(round(buy_size * toxic_size_frac)))

        if bid_jumped and sell_size > 0:
            sell_size = max(1, int(round(sell_size * jump_size_frac)))
        if ask_jumped and buy_size > 0:
            buy_size = max(1, int(round(buy_size * jump_size_frac)))

        directional_size_skew = float(self.params.get("directional_size_skew", 0.0))
        if directional_size_skew > 0.0 and abs(trend_signal) > 0.0:
            skew = directional_size_skew * abs(trend_signal)
            if trend_signal > 0:
                if buy_size > 0:
                    buy_size = min(buy_cap, max(1, int(round(buy_size * (1.0 + skew)))))
                if sell_size > 0:
                    sell_size = max(1, int(round(sell_size * (1.0 - skew))))
            else:
                if sell_size > 0:
                    sell_size = min(sell_cap, max(1, int(round(sell_size * (1.0 + skew)))))
                if buy_size > 0:
                    buy_size = max(1, int(round(buy_size * (1.0 - skew))))

        max_quote_bias_ticks = int(self.params.get("directional_max_quote_bias_ticks", 0))
        if max_quote_bias_ticks > 0 and abs(trend_signal) > 0.0:
            quote_bias = int(round(trend_signal * max_quote_bias_ticks))
            if quote_bias > 0:
                bid_price = min(bid_price + quote_bias, real_best_ask - 1)
                ask_price = min(real_best_ask, ask_price + quote_bias)
            elif quote_bias < 0:
                bid_price = max(real_best_bid, bid_price + quote_bias)
                ask_price = max(real_best_bid + 1, ask_price + quote_bias)

            if bid_price >= ask_price:
                ask_price = min(real_best_ask, max(bid_price + 1, ask_price))

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["prev_best_bid"] = real_best_bid
        memory["prev_best_ask"] = real_best_ask
        memory["prev_mid"] = mid
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_flow_score"] = flow_score
        memory["last_take_count"] = take_count
        memory["trend_pressure_ema"] = pressure_ema
        memory["trend_pressure_sign"] = self._signal_sign(current_pressure, float(self.params.get("trend_streak_threshold", 0.08)))
        memory["trend_pressure_streak"] = int(streak)
        memory["trend_signal"] = trend_signal
        memory["last_trend_signal"] = trend_signal
        memory["last_trend_pressure"] = current_pressure
        memory["last_trend_micro_edge"] = micro_edge
        memory["last_trend_price_confirm"] = price_trend
        memory["last_directional_mid"] = directional_mid

        flush_ts = int(self.params.get("log_flush_ts", 0))
        last_tick_ts = int(self.params.get("total_ticks", 10_000_000)) - 100
        end_of_sim = state.timestamp >= last_tick_ts
        checkpoint = flush_ts > 0 and (state.timestamp % flush_ts) == (flush_ts - 100)
        if flush_ts > 0 or end_of_sim:
            log = memory.setdefault("_log", [])
            log.append([
                state.timestamp,
                bid_price,
                ask_price,
                position,
                buy_size,
                sell_size,
                flow_score,
                trend_signal,
                take_count,
            ])

        if end_of_sim or checkpoint:
            print(json.dumps({
                "product": self.product,
                "chunk_end": state.timestamp,
                "columns": [
                    "timestamp",
                    "bid",
                    "ask",
                    "position",
                    "buy_size",
                    "sell_size",
                    "flow_score",
                    "trend_signal",
                    "takes",
                ],
                "log": log,
            }))
            memory["_log"] = []

        return orders, 0
