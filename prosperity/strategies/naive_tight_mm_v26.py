"""Trend carry market maker V26.

V26 keeps the V25 carry-first accumulation profile, but adds a more
actionable sell regime once we are already well loaded:

- trims are keyed off a flatter local fair reference
- buy aggression is blocked while price is rich versus that local fair
- the strongest local over-extensions can be sold directly at the bid
- after an aggressive trim, rebuys are paused briefly unless a real dip appears
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


def _ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


class TrendCarryMMV26Strategy(BaseStrategy):

    def _take_orders(
        self,
        order_depth: OrderDepth,
        fair: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
        buy_take_cap: int,
        sell_take_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        orders: List[Order] = []
        take_count = 0
        buy_take_remaining = min(buy_cap, max(0, buy_take_cap))
        sell_take_remaining = min(sell_cap, max(0, sell_take_cap))

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > fair - buy_edge or buy_take_remaining <= 0:
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
            if bid_price < fair + sell_edge or sell_take_remaining <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap, sell_take_remaining)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            sell_take_remaining -= qty
            take_count += 1

        return orders, buy_cap, sell_cap, take_count

    def _size_quotes(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.45))
        aggravate_min = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost = float(self.params.get("unwind_boost_frac", 0.35))
        limit = float(self.position_limit())

        pressure = abs(position - inv_target) / max(1.0, limit)
        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        agg_frac = 1.0 - (1.0 - aggravate_min) * scaled
        boost = 1.0 + unwind_boost * scaled

        if position > inv_target:
            buy_size = max(1, int(round(buy_size * agg_frac)))
            sell_size = min(sell_cap, max(1, int(round(sell_size * boost))))
        elif position < inv_target:
            sell_size = max(1, int(round(sell_size * agg_frac)))
            buy_size = min(buy_cap, max(1, int(round(buy_size * boost))))

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

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        fv_alpha = float(self.params.get("fv_alpha", 0.05))
        short_alpha = float(self.params.get("short_alpha", 0.22))
        slope_window = int(self.params.get("slope_window", 20))
        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        trend_weight = float(self.params.get("trend_weight", 0.55))
        stretch_weight = float(self.params.get("stretch_weight", 0.75))
        trim_reference_slope_weight = float(self.params.get("trim_reference_slope_weight", 0.15))

        target_bull_base = int(self.params.get("target_bull_base", 64))
        target_bull_min = int(self.params.get("target_bull_min", 56))
        target_bull_max = int(self.params.get("target_bull_max", 78))
        target_bull_per_tick = float(self.params.get("target_bull_per_tick", 2.0))
        startup_ticks = int(self.params.get("startup_ticks", 15000))
        startup_target = int(self.params.get("startup_target", 78))
        dip_target = int(self.params.get("dip_target", 80))
        neutral_target = int(self.params.get("neutral_target", 0))
        warmup_no_sell_ticks = int(self.params.get("warmup_no_sell_ticks", 3000))

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        bid_spread_bull_under = float(self.params.get("bid_spread_bull_under", 0.0))
        bid_spread_neut = float(self.params.get("bid_spread_neut", 2.0))
        ask_spread_bull_hold = float(self.params.get("ask_spread_bull_hold", 8.0))
        ask_spread_bull_trim = float(self.params.get("ask_spread_bull_trim", 2.0))
        ask_spread_neut = float(self.params.get("ask_spread_neut", 4.0))
        bid_join_ticks = int(self.params.get("bid_join_ticks", 1))
        trim_ask_improve_ticks = int(self.params.get("trim_ask_improve_ticks", 1))
        trim_ask_local_edge = float(self.params.get("trim_ask_local_edge", 1.0))

        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -6.0))
        take_buy_edge_under_boost = float(self.params.get("take_buy_edge_under_boost", 2.0))
        take_buy_edge_dip_boost = float(self.params.get("take_buy_edge_dip_boost", 1.5))
        take_buy_edge_chase_penalty = float(self.params.get("take_buy_edge_chase_penalty", 2.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 8.0))
        max_take_buy_size = int(self.params.get("max_take_buy_size", 12))
        max_take_sell_size = int(self.params.get("max_take_sell_size", 8))

        under_target_buy_mult = float(self.params.get("under_target_buy_mult", 1.50))
        startup_buy_mult = float(self.params.get("startup_buy_mult", 1.35))
        dip_buy_mult = float(self.params.get("dip_buy_mult", 1.35))
        chase_buy_frac = float(self.params.get("chase_buy_frac", 0.60))
        hold_buy_frac = float(self.params.get("hold_buy_frac", 0.75))
        hold_sell_frac = float(self.params.get("hold_sell_frac", 0.25))
        under_target_sell_frac = float(self.params.get("under_target_sell_frac", 0.0))

        dip_threshold = float(self.params.get("dip_threshold", 1.5))
        chase_threshold = float(self.params.get("chase_threshold", 2.5))
        trim_start_position = int(self.params.get("trim_start_position", 76))
        trim_floor_position = int(self.params.get("trim_floor_position", 72))
        trim_extension_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        trim_signal_edge = float(self.params.get("trim_signal_edge", 0.75))
        trim_sell_size = int(self.params.get("trim_sell_size", 2))
        trim_cooldown_ticks = int(self.params.get("trim_cooldown_ticks", 10))
        trim_take_position = int(self.params.get("trim_take_position", 78))
        trim_take_edge = float(self.params.get("trim_take_edge", 1.25))
        trim_take_stretch = float(self.params.get("trim_take_stretch", 1.25))
        trim_take_sell_size = int(self.params.get("trim_take_sell_size", 2))
        rebuy_block_ticks = int(self.params.get("rebuy_block_ticks", 15))

        spot = book.microprice if book.microprice is not None else (book.mid_price or (book.best_bid + book.best_ask) / 2.0)

        fv = _ewma(memory.get("fv"), spot, fv_alpha)
        short_ema = _ewma(memory.get("short_ema"), spot, short_alpha)
        memory["fv"] = fv
        memory["short_ema"] = short_ema

        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[: -(slope_window + 1)]

        slope = 0.0
        if len(fv_hist) >= slope_window:
            slope = fv_hist[-1] - fv_hist[-slope_window]

        stretch = spot - short_ema
        fair = fv + trend_weight * slope - stretch_weight * stretch
        trim_reference = fv + trim_reference_slope_weight * max(0.0, slope)

        bullish = slope > bull_threshold
        on_dip = bullish and stretch <= -dip_threshold
        chasing = bullish and stretch >= chase_threshold and not on_dip
        startup_loading = bullish and state.timestamp <= startup_ticks

        if bullish:
            dyn_target = target_bull_base + target_bull_per_tick * max(0.0, slope - bull_threshold)
            inv_target = int(round(max(target_bull_min, min(target_bull_max, dyn_target))))
            if startup_loading:
                inv_target = max(inv_target, startup_target)
            if on_dip:
                inv_target = max(inv_target, dip_target)
            inv_target = min(self.position_limit(), inv_target)
        else:
            inv_target = neutral_target

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        last_trim_ts = int(memory.get("last_trim_ts", -10**9))
        rebuy_block_until = int(memory.get("rebuy_block_until", -10**9))
        rebuy_blocked = bullish and not on_dip and state.timestamp < rebuy_block_until
        pre_trim_signal = (
            bullish
            and position > trim_floor_position
            and position >= trim_start_position
            and stretch >= trim_extension_threshold
            and book.best_bid >= trim_reference + trim_signal_edge
        )

        if bullish:
            buy_edge = take_buy_edge_bull
            if position < inv_target:
                buy_edge -= take_buy_edge_under_boost
            if on_dip:
                buy_edge -= take_buy_edge_dip_boost
            elif chasing:
                buy_edge += take_buy_edge_chase_penalty
            sell_edge = 1_000_000.0
            buy_take_cap = max_take_buy_size
            if position < inv_target:
                buy_take_cap = max(buy_take_cap, int(round(max_take_buy_size * under_target_buy_mult)))
            if startup_loading:
                buy_take_cap = max(buy_take_cap, int(round(max_take_buy_size * startup_buy_mult)))
            if on_dip:
                buy_take_cap = max(buy_take_cap, int(round(max_take_buy_size * dip_buy_mult)))
            if chasing:
                buy_take_cap = max(1, int(round(buy_take_cap * chase_buy_frac)))
            if pre_trim_signal or rebuy_blocked:
                buy_take_cap = 0
            sell_take_cap = 0
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut
            if position > inv_target:
                pressure = min(1.0, (position - inv_target) / max(1.0, float(self.position_limit())))
                sell_edge = sell_edge - unwind_take_edge * pressure
            buy_take_cap = max_take_buy_size
            sell_take_cap = max_take_sell_size

        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth,
            fair=fair,
            buy_edge=buy_edge,
            sell_edge=sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            buy_take_cap=buy_take_cap,
            sell_take_cap=sell_take_cap,
        )
        orders.extend(take_orders)

        real_best_ask = book.best_ask
        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        for ask_price, _ in book.ask_levels:
            if ask_price not in swept_ask_prices:
                real_best_ask = ask_price
                break

        real_best_bid = book.best_bid
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}
        for bid_price, _ in book.bid_levels:
            if bid_price not in swept_bid_prices:
                real_best_bid = bid_price
                break

        trim_quote_mode = (
            bullish
            and position > trim_floor_position
            and position >= trim_start_position
            and stretch >= trim_extension_threshold
            and real_best_bid >= trim_reference + trim_signal_edge
        )
        trim_take_mode = (
            trim_quote_mode
            and position >= trim_take_position
            and stretch >= trim_take_stretch
            and real_best_bid >= trim_reference + trim_take_edge
            and state.timestamp - last_trim_ts >= trim_cooldown_ticks * 100
        )

        trim_take_qty = 0
        if trim_take_mode:
            trim_take_qty = min(sell_cap, max(0, position - trim_floor_position), max(1, trim_take_sell_size))
            if trim_take_qty > 0:
                orders.append(Order(self.product, real_best_bid, -trim_take_qty))
                sell_cap -= trim_take_qty
                memory["last_trim_ts"] = state.timestamp
                memory["rebuy_block_until"] = state.timestamp + rebuy_block_ticks * 100
                rebuy_blocked = True
                take_count += 1

        buy_size, sell_size = self._size_quotes(
            position=position,
            inv_target=inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if bullish and position < inv_target:
            buy_size = min(buy_cap, max(1, int(round(buy_size * under_target_buy_mult))))
            sell_size = int(round(sell_size * under_target_sell_frac))
        elif bullish:
            buy_size = min(buy_cap, max(1, int(round(buy_size * hold_buy_frac)))) if buy_size > 0 else 0
            sell_size = min(sell_cap, max(0, int(round(sell_size * hold_sell_frac))))

        if startup_loading and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * startup_buy_mult))))
        if on_dip and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * dip_buy_mult))))
        elif chasing and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * chase_buy_frac))))

        bid_spread = bid_spread_bull_under if bullish and position < inv_target else (bid_spread_bull if bullish else bid_spread_neut)
        raw_bid = round(fair - bid_spread)
        bid_price = min(max(raw_bid, 1), real_best_ask - 1)
        if bullish and buy_size > 0:
            bid_price = max(bid_price, min(real_best_bid + bid_join_ticks, real_best_ask - 1))

        if bullish:
            ask_edge = ask_spread_bull_trim if trim_quote_mode else ask_spread_bull_hold
        else:
            ask_edge = ask_spread_neut

        raw_ask = round(fair + ask_edge)
        ask_price = max(raw_ask, real_best_bid + 1)
        if trim_quote_mode:
            trim_ask_target = round(trim_reference + trim_ask_local_edge)
            ask_price = max(real_best_bid + 1, min(real_best_ask - trim_ask_improve_ticks, trim_ask_target))
            ask_price = max(ask_price, real_best_bid + 1)

        if (state.timestamp <= warmup_no_sell_ticks and position <= 0) or startup_loading or (bullish and position < trim_floor_position):
            sell_size = 0

        if trim_quote_mode:
            allowed_sell = max(0, position - trim_floor_position)
            sell_size = min(sell_cap, allowed_sell, max(1, trim_sell_size))
            buy_size = 0

        if rebuy_blocked and not on_dip:
            buy_size = 0

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["fair"] = fair
        memory["trim_reference"] = trim_reference
        memory["slope"] = slope
        memory["stretch"] = stretch
        memory["inv_target"] = inv_target
        memory["bullish"] = int(bullish)
        memory["on_dip"] = int(on_dip)
        memory["chasing"] = int(chasing)
        memory["trim_quote_mode"] = int(trim_quote_mode)
        memory["trim_take_mode"] = int(trim_take_mode)
        memory["rebuy_blocked"] = int(rebuy_blocked)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "fair": round(fair, 2),
                "fv": round(fv, 2),
                "trim_reference": round(trim_reference, 2),
                "slope": round(slope, 2),
                "stretch": round(stretch, 2),
                "bullish": int(bullish),
                "inv_target": inv_target,
                "on_dip": int(on_dip),
                "chasing": int(chasing),
                "trim_quote_mode": int(trim_quote_mode),
                "trim_take_mode": int(trim_take_mode),
                "rebuy_blocked": int(rebuy_blocked),
                "trim_take_qty": trim_take_qty,
                "takes": take_count,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if memory.get("fv") is not None:
            out["fv"] = memory["fv"]
        if memory.get("fair") is not None:
            out["fair"] = memory["fair"]
        if memory.get("short_ema") is not None:
            out["short_ema"] = memory["short_ema"]
        if memory.get("trim_reference") is not None:
            out["trim_reference"] = memory["trim_reference"]
        return out
