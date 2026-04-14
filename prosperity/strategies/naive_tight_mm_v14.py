"""Naive passive market maker V14.

V14 keeps the V11/V13 trend estimator and microstructure filters, but adds a
configurable long-bias framework for INTARIAN_PEPPER_ROOT:

1. Dynamic inventory targets:
   - pure time-based accumulation / unwind
   - trend target with a positive time-based floor
   - trend target with an additive long bias

2. Long-biased quoting:
   - bid can be skewed more aggressively when below target
   - ask can be kept further away while we still want to stay long
   - passive sell size can be shrunk instead of fully suppressed

3. Dip-buy / anti-chase execution:
   - buy more readily on local pullbacks inside an uptrend
   - avoid sweeping too much size when price is extended above a fast anchor

4. Per-tick taker caps:
   - stops the strategy from filling the entire 80-lot target in a handful of
     aggressive buys when the take edge opens up.

The goal is to let us test the user-requested families cleanly:
  A. long inventory simple
  B. long inventory + dip buying
  C. long-biased MM
  D. combination
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV14Strategy(BaseStrategy):

    def _take_orders(
        self,
        order_depth: OrderDepth,
        adjusted_mid: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
        max_take_buy_size: int,
        max_take_sell_size: int,
        allow_buy_takes: bool,
        allow_sell_takes: bool,
    ) -> Tuple[List[Order], int, int, int]:
        orders: List[Order] = []
        take_count = 0
        take_buy_cap = min(buy_cap, max_take_buy_size) if allow_buy_takes and max_take_buy_size > 0 else 0
        take_sell_cap = min(sell_cap, max_take_sell_size) if allow_sell_takes and max_take_sell_size > 0 else 0

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > adjusted_mid - buy_edge or take_buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, take_buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            take_buy_cap -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < adjusted_mid + sell_edge or take_sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, take_sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            take_sell_cap -= qty
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

    def _schedule_target_frac(self, progress: float) -> float:
        t1 = float(self.params.get("schedule_t1_frac", 0.25))
        t2 = float(self.params.get("schedule_t2_frac", 0.70))
        t3 = float(self.params.get("schedule_t3_frac", 0.90))
        early = float(self.params.get("schedule_early_target_frac", 0.0))
        mid = float(self.params.get("schedule_mid_target_frac", 0.0))
        late = float(self.params.get("schedule_late_target_frac", 0.0))
        end = float(self.params.get("schedule_end_target_frac", 0.0))

        if progress < t1:
            return early
        if progress < t2:
            return mid
        if progress < t3:
            return late
        return end

    def _combine_targets(self, trend_target: int, time_target: int) -> int:
        mode = str(self.params.get("target_mode", "trend"))
        limit = self.position_limit()

        if mode == "time_only":
            combined = time_target
        elif mode == "trend_plus_floor":
            combined = trend_target
            if combined >= 0:
                combined = max(combined, time_target)
        elif mode == "trend_plus_bias":
            combined = trend_target + time_target
        else:
            combined = trend_target

        return int(round(max(-limit, min(limit, combined))))

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
        trend_hold_position_frac = float(self.params.get("trend_hold_position_frac", 0.70))
        trend_hold_sell_size_frac = float(self.params.get("trend_hold_sell_size_frac", 1.0))
        trend_sell_patience = float(self.params.get("trend_sell_patience", 0.0))

        max_take_buy_size = int(self.params.get("max_take_buy_size", self.position_limit()))
        max_take_sell_size = int(self.params.get("max_take_sell_size", self.position_limit()))

        fast_alpha = float(self.params.get("fast_alpha", 0.20))
        dip_window = int(self.params.get("dip_window", 20))
        dip_trend_threshold = float(self.params.get("dip_trend_threshold", 0.0))
        dip_min_pullback = float(self.params.get("dip_min_pullback", 0.0))
        dip_take_boost = float(self.params.get("dip_take_boost", 0.0))
        dip_buy_size_boost = float(self.params.get("dip_buy_size_boost", 0.0))
        chase_max_extension = float(self.params.get("chase_max_extension", 1e9))
        chase_buy_edge_penalty = float(self.params.get("chase_buy_edge_penalty", 0.0))
        chase_buy_size_frac = float(self.params.get("chase_buy_size_frac", 1.0))

        buy_size_boost_when_under = float(self.params.get("buy_size_boost_when_under", 0.0))
        sell_size_frac_when_under = float(self.params.get("sell_size_frac_when_under", 1.0))
        sell_size_boost_when_over = float(self.params.get("sell_size_boost_when_over", 0.0))
        buy_size_frac_when_over = float(self.params.get("buy_size_frac_when_over", 1.0))

        bid_skew_ticks_when_under = float(self.params.get("bid_skew_ticks_when_under", 0.0))
        ask_skew_ticks_when_under = float(self.params.get("ask_skew_ticks_when_under", 0.0))
        bid_retreat_ticks_when_over = float(self.params.get("bid_retreat_ticks_when_over", 0.0))
        ask_unwind_ticks_when_over = float(self.params.get("ask_unwind_ticks_when_over", 0.0))

        schedule_total_ticks = float(self.params.get("schedule_total_ticks", 100000))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0
        limit = self.position_limit()

        trend_shift = 0.0
        trend_target = 0

        if signal_mode == "mean_rev" and anchor_price != 0.0:
            raw_signal = anchor_price - mid
            trend_shift = max(-trend_max_shift, min(trend_max_shift, raw_signal * trend_sensitivity))
            trend_target = int(round(max(-limit, min(limit, trend_shift * trend_inv_target_per_tick))))
        elif signal_mode == "trend" and trend_alpha > 0.0:
            trend_ema = memory.get("trend_ema")
            if trend_ema is None:
                trend_ema = mid
            trend_ema = trend_alpha * mid + (1.0 - trend_alpha) * trend_ema
            memory["trend_ema"] = trend_ema

            raw_signal = mid - trend_ema
            trend_shift = max(-trend_max_shift, min(trend_max_shift, raw_signal * trend_sensitivity))
            trend_target = int(round(max(-limit, min(limit, trend_shift * trend_inv_target_per_tick))))

        progress = 0.0 if schedule_total_ticks <= 0 else min(1.0, max(0.0, state.timestamp / schedule_total_ticks))
        time_target = int(round(limit * self._schedule_target_frac(progress)))
        inv_target = self._combine_targets(trend_target, time_target)
        adjusted_mid = mid + trend_shift

        recent_mids = memory.setdefault("recent_mids", [])
        recent_mids.append(mid)
        if dip_window > 0 and len(recent_mids) > dip_window:
            del recent_mids[:-dip_window]

        fast_ema = memory.get("fast_ema")
        if fast_ema is None:
            fast_ema = mid
        fast_ema = fast_alpha * mid + (1.0 - fast_alpha) * fast_ema
        memory["fast_ema"] = fast_ema

        recent_high = max(recent_mids) if recent_mids else mid
        pullback = recent_high - mid
        extension = mid - fast_ema

        buy_edge = take_edge
        sell_edge = take_edge + max(0.0, trend_shift) * trend_sell_patience

        pressure = abs(position - inv_target) / max(1.0, float(limit))
        if position < inv_target:
            buy_edge = max(0.0, buy_edge - unwind_take_edge * pressure)
        elif position > inv_target:
            sell_edge = max(0.0, sell_edge - unwind_take_edge * pressure)

        if trend_shift > 0.0:
            buy_edge = max(0.0, buy_edge - trend_shift * trend_take_boost)
        elif trend_shift < 0.0:
            sell_edge = max(0.0, sell_edge - (-trend_shift) * trend_take_boost)

        on_dip = trend_shift >= dip_trend_threshold and pullback >= dip_min_pullback
        chasing = trend_shift >= dip_trend_threshold and extension >= chase_max_extension and not on_dip
        if on_dip:
            buy_edge = max(0.0, buy_edge - dip_take_boost)
        elif chasing:
            buy_edge = buy_edge + chase_buy_edge_penalty
            max_take_buy_size = max(0, int(round(max_take_buy_size * chase_buy_size_frac)))

        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth,
            adjusted_mid=adjusted_mid,
            buy_edge=buy_edge,
            sell_edge=sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            max_take_buy_size=max_take_buy_size,
            max_take_sell_size=max_take_sell_size,
            allow_buy_takes=not chasing or max_take_buy_size > 0,
            allow_sell_takes=True,
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

        target_gap = inv_target - position
        if target_gap > 0:
            gap_frac = min(1.0, target_gap / max(1.0, float(limit)))
            if buy_size > 0:
                buy_size = min(buy_cap, max(1, int(round(buy_size * (1.0 + buy_size_boost_when_under * gap_frac)))))
            if on_dip and buy_size > 0:
                buy_size = min(buy_cap, max(1, int(round(buy_size * (1.0 + dip_buy_size_boost)))))
            if sell_size > 0:
                sell_size = int(round(sell_size * sell_size_frac_when_under))
                sell_size = min(sell_cap, max(0, sell_size))
            bid_price = min(int(round(bid_price + bid_skew_ticks_when_under * gap_frac)), ask_price - 1)
            ask_price = int(round(ask_price + ask_skew_ticks_when_under * gap_frac))
        elif target_gap < 0:
            gap_frac = min(1.0, (-target_gap) / max(1.0, float(limit)))
            if sell_size > 0:
                sell_size = min(sell_cap, max(1, int(round(sell_size * (1.0 + sell_size_boost_when_over * gap_frac)))))
            if buy_size > 0:
                buy_size = int(round(buy_size * buy_size_frac_when_over))
                buy_size = min(buy_cap, max(0, buy_size))
            bid_price = int(round(bid_price - bid_retreat_ticks_when_over * gap_frac))
            ask_price = max(bid_price + 1, int(round(ask_price - ask_unwind_ticks_when_over * gap_frac)))

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
            and position >= int(round(limit * trend_hold_position_frac))
        )
        if hold_long_trend and sell_size > 0:
            sell_size = int(round(sell_size * trend_hold_sell_size_frac))
            sell_size = min(sell_cap, max(0, sell_size))

        if buy_size > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_price, min(buy_cap, buy_size)))
        if sell_size > 0 and sell_cap > 0:
            orders.append(Order(self.product, ask_price, -min(sell_cap, sell_size)))

        memory["prev_best_bid"] = real_best_bid
        memory["prev_best_ask"] = real_best_ask
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_flow_score"] = flow_score
        memory["last_take_count"] = take_count
        memory["inv_target"] = inv_target
        memory["trend_shift"] = trend_shift
        memory["time_target"] = time_target
        memory["trend_target"] = trend_target
        memory["hold_long_trend"] = hold_long_trend
        memory["recent_high"] = recent_high
        memory["pullback"] = pullback
        memory["extension"] = extension
        memory["progress"] = progress

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
                "trend_target": trend_target,
                "time_target": time_target,
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
        if memory.get("recent_high") is not None:
            out["recent_high"] = memory["recent_high"]
        trend_shift = memory.get("trend_shift", 0.0)
        prev_bid = memory.get("last_bid_price")
        prev_ask = memory.get("last_ask_price")
        if prev_bid is not None and prev_ask is not None and trend_shift:
            out["adjusted_mid"] = (prev_bid + prev_ask) / 2.0 + trend_shift
        return out
