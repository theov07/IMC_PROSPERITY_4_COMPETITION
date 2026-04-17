"""Theo's generalized trending strategy for INTARIAN_PEPPER_ROOT.

Built on top of the V5 block-OLS regression signal.

Key ideas vs earlier versions:
- Direction-agnostic: bullish / bearish / neutral regime detection via trend_ticks
- Trim system: when stretched long (or short) at position limit, quotes tighter
  on the reducing side to opportunistically trim without chasing
- Build phase: aggressively accumulates inventory in trend direction early in
  session or when far from target
- Adaptive tick adjustments to bid/ask based on z-score and trend strength
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


def _ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


class TheoGeneralizedStrategy(Round1RegressionMMV5Strategy):
    """Leo-fusion buy logic + V34 trim system, direction-agnostic."""

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

        mid = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        trend_ticks = stats["trend_ticks"]
        residual_z  = stats["residual_z"]
        fv          = stats["fair_value"]

        # Short-term EMA for stretch detection
        short_alpha = float(self.params.get("short_alpha", 0.15))
        short_ema   = _ewma(memory.get("short_ema"), mid, short_alpha)
        memory["short_ema"] = short_ema
        stretch = mid - short_ema

        base_target = self._inventory_target(state=state, stats=stats, position=position)

        # Trend regime: direction-agnostic
        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        bear_threshold = float(self.params.get("bear_threshold", -bull_threshold))
        bullish  = trend_ticks > bull_threshold
        bearish  = trend_ticks < bear_threshold
        limit    = self.position_limit()

        # Build phase: accumulate in trend direction
        fastfill_target = int(self.params.get("fastfill_target", limit))
        fastfill_end_ts = int(self.params.get("fastfill_end_ts", 15000))

        if bullish:
            build_phase = position < fastfill_target or int(state.timestamp) <= fastfill_end_ts
            inv_target  = max(base_target, fastfill_target) if build_phase else base_target
        elif bearish:
            build_phase = position > -fastfill_target or int(state.timestamp) <= fastfill_end_ts
            inv_target  = min(base_target, -fastfill_target) if build_phase else base_target
        else:
            build_phase = False
            inv_target  = base_target

        # Trim parameters
        trim_start_position   = int(self.params.get("trim_start_position",   80))
        trim_floor_position   = int(self.params.get("trim_floor_position",   78))
        trim_sell_size        = int(self.params.get("trim_sell_size",         1))
        trim_stretch_threshold = float(self.params.get("trim_stretch_threshold", 2.0))
        trim_take_stretch     = float(self.params.get("trim_take_stretch",   3.5))
        trim_take_sell_size   = int(self.params.get("trim_take_sell_size",    2))
        rebuy_block_ticks     = int(self.params.get("rebuy_block_ticks",      8))
        trim_take_enabled     = bool(self.params.get("trim_take_enabled",     False))
        trim_ask_mid_offset   = float(self.params.get("trim_ask_mid_offset",  5.0))

        rebuy_block_until = int(memory.get("rebuy_block_until", -10**9))
        rebuy_blocked     = bool(bullish or bearish) and int(state.timestamp) < rebuy_block_until

        # Quote prices: direction-adaptive spreads
        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))

        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
        elif bearish:
            raw_bid = round(fv - ask_spread_bull)
            raw_ask = round(fv + bid_spread_bull)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)

        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # Signal-adaptive tick adjustments
        bid_extra  = 0
        ask_relax  = 0
        strong      = float(self.params.get("strong_trend_ticks",      1.1))
        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        cheap_z     = float(self.params.get("cheap_residual_z",        0.9))
        rich_z      = float(self.params.get("rich_residual_z",         1.0))

        if trend_ticks >= strong:
            bid_extra += 1
        if trend_ticks >= very_strong:
            bid_extra += 1
        if trend_ticks <= -strong:
            ask_relax -= 1
        if trend_ticks <= -very_strong:
            ask_relax -= 1
        if residual_z <= -cheap_z:
            bid_extra += 1
        if residual_z >= rich_z:
            ask_relax -= 1

        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        max_ask_relax = int(self.params.get("max_ask_relax_ticks", 2))
        bid_extra = max(-max_bid_extra, min(max_bid_extra, bid_extra))
        ask_relax = max(-max_ask_relax, min(max_ask_relax, ask_relax))

        bid_price = min(book.best_ask - 1, bid_price + bid_extra)
        ask_price = max(book.best_bid + 1, ask_price + ask_relax)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # Build phase: penny-improve in trend direction
        build_bid_offset = int(self.params.get("build_bid_offset", 1))
        if build_phase and bullish:
            bid_price = book.best_ask - build_bid_offset
        elif build_phase and bearish:
            ask_price = book.best_bid + build_bid_offset

        # Taker edges
        take_buy_edge_bull  = float(self.params.get("take_buy_edge_bull",  -8.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull",  6.0))
        take_buy_edge_neut  = float(self.params.get("take_buy_edge_neut",   2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut",  2.0))
        unwind_take_edge    = float(self.params.get("unwind_take_edge",    10.0))
        fastfill_buy_edge_boost    = float(self.params.get("fastfill_buy_edge_boost",    0.0))
        build_block_counter_edge   = float(self.params.get("build_block_counter_edge", 1_000_000.0))

        if bullish:
            buy_edge  = take_buy_edge_bull
            sell_edge = take_sell_edge_bull
            if build_phase:
                buy_edge  -= fastfill_buy_edge_boost
                sell_edge  = build_block_counter_edge
            elif residual_z >= rich_z:
                buy_edge = take_buy_edge_neut
        elif bearish:
            sell_edge = take_buy_edge_bull
            buy_edge  = take_sell_edge_bull
            if build_phase:
                sell_edge -= fastfill_buy_edge_boost
                buy_edge   = build_block_counter_edge
            elif residual_z <= -cheap_z:
                sell_edge = take_buy_edge_neut
        else:
            buy_edge  = take_buy_edge_neut
            sell_edge = take_sell_edge_neut

        # Unwind pressure when offside
        if (not bullish) and position > inv_target:
            pressure  = min(1.0, (position - inv_target) / max(1.0, float(limit)))
            sell_edge = sell_edge - unwind_take_edge * pressure
        if (not bearish) and position < inv_target:
            pressure = min(1.0, (inv_target - position) / max(1.0, float(limit)))
            buy_edge = buy_edge - unwind_take_edge * pressure

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Trim detection (direction-agnostic)
        trim_quote_mode = False
        if bullish and not build_phase and position >= trim_start_position and stretch >= trim_stretch_threshold:
            trim_quote_mode = True
        elif bearish and not build_phase and position <= -trim_start_position and stretch <= -trim_stretch_threshold:
            trim_quote_mode = True

        trim_take_mode = False
        if trim_take_enabled:
            if bullish and not build_phase and position >= trim_start_position and stretch >= trim_take_stretch:
                trim_take_mode = True
            elif bearish and not build_phase and position <= -trim_start_position and stretch <= -trim_take_stretch:
                trim_take_mode = True

        # Taker orders (buy side)
        pending_buy = 0
        first_take_ask: int | None = None
        deep_take_guard_end_ts = int(self.params.get("fastfill_deep_take_guard_end_ts", 0))
        deep_take_max_gap      = int(self.params.get("fastfill_deep_take_max_gap_ticks", 999999))
        deep_take_guard = build_phase and bullish and int(state.timestamp) <= deep_take_guard_end_ts

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0:
                break
            room = max(0, inv_target - position - pending_buy)
            if build_phase and bullish and room <= 0:
                break
            if first_take_ask is None:
                first_take_ask = ask_p
            elif deep_take_guard and ask_p - first_take_ask > deep_take_max_gap:
                break
            qty = min(-order_depth.sell_orders[ask_p], buy_cap, room if (build_phase and bullish) else buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            buy_cap     -= qty
            pending_buy += qty

        # Taker orders (sell side)
        pending_sell = 0
        if not (build_phase and bullish) and not trim_quote_mode:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fv + sell_edge or sell_cap <= 0:
                    break
                room_sell = max(0, position + pending_sell - pending_buy - inv_target) if (build_phase and bearish) else sell_cap
                qty = min(order_depth.buy_orders[bid_p], sell_cap, room_sell)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap     -= qty
                pending_sell += qty

        # Trim take (disabled by default)
        trim_take_qty = 0
        if trim_take_mode:
            if position > 0:
                trim_take_qty = min(sell_cap, max(0, position - trim_floor_position), max(1, trim_take_sell_size))
                if trim_take_qty > 0:
                    orders.append(Order(self.product, book.best_bid, -trim_take_qty))
                    sell_cap     -= trim_take_qty
                    pending_sell += trim_take_qty
            elif position < 0:
                trim_take_qty = min(buy_cap, max(0, -position - trim_floor_position), max(1, trim_take_sell_size))
                if trim_take_qty > 0:
                    orders.append(Order(self.product, book.best_ask, trim_take_qty))
                    buy_cap     -= trim_take_qty
                    pending_buy += trim_take_qty
            if trim_take_qty > 0:
                memory["last_trim_ts"]       = int(state.timestamp)
                memory["rebuy_block_until"]  = int(state.timestamp) + rebuy_block_ticks * 100
                rebuy_blocked = True

        # Passive sizing
        buy_size, sell_size = self._size_from_target(
            position=position + pending_buy - pending_sell,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        # Build phase: suppress counter-trend passive, boost trend passive
        if build_phase and bullish:
            sell_size = 0
            buy_size  = max(buy_size, min(buy_cap, int(self.params.get("fastfill_min_passive_buy", 20))))
            buy_size  = min(buy_size, max(0, inv_target - position - pending_buy))
        elif build_phase and bearish:
            buy_size  = 0
            sell_size = max(sell_size, min(sell_cap, int(self.params.get("fastfill_min_passive_buy", 20))))
            sell_size = min(sell_size, max(0, -inv_target + position - pending_sell))

        # Trim quote mode: passive trim inside spread
        if trim_quote_mode and not build_phase:
            if position > 0:
                allowed_sell = max(0, position - trim_floor_position)
                sell_size    = min(sell_cap, allowed_sell, max(1, trim_sell_size))
                trim_ask     = max(book.best_bid + 1, book.best_ask - 1, round(mid + trim_ask_mid_offset))
                ask_price    = trim_ask
            elif position < 0:
                allowed_buy = max(0, -position - trim_floor_position)
                buy_size    = min(buy_cap, allowed_buy, max(1, trim_sell_size))
                trim_bid    = min(book.best_ask - 1, book.best_bid + 1, round(mid - trim_ask_mid_offset))
                bid_price   = trim_bid

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        # Persist state
        memory["last_bid_price"]  = bid_price
        memory["last_ask_price"]  = ask_price
        memory["inv_target"]      = inv_target
        memory["bullish"]         = int(bullish)
        memory["bearish"]         = int(bearish)
        memory["build_phase"]     = int(build_phase)
        memory["trim_quote_mode"] = int(trim_quote_mode)
        memory["trim_take_mode"]  = int(trim_take_mode)
        memory["rebuy_blocked"]   = int(rebuy_blocked)
        memory["stretch"]         = stretch

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position":       position,
                "reg_slope":      round(stats["slope"], 4),
                "reg_r2":         round(stats["r2"], 3),
                "trend_ticks":    round(trend_ticks, 2),
                "residual_z":     round(residual_z, 2),
                "block_count":    int(stats["block_count"]),
                "fair_value":     round(fv, 2),
                "inv_target":     inv_target,
                "bullish":        int(bullish),
                "bearish":        int(bearish),
                "build_phase":    int(build_phase),
                "buy_size":       buy_size,
                "sell_size":      sell_size,
                "stretch":        round(stretch, 2),
                "trim_quote_mode": int(trim_quote_mode),
                "trim_take_mode": int(trim_take_mode),
                "trim_take_qty":  trim_take_qty,
                "rebuy_blocked":  int(rebuy_blocked),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        stats = memory.get("regression_stats")
        if not stats:
            return {}
        out = {
            "reg_fitted_now": float(stats["fitted_now"]),
            "reg_forecast":   float(stats["forecast"]),
            "reg_fair_value": float(stats["fair_value"]),
        }
        if memory.get("short_ema") is not None:
            out["short_ema"] = memory["short_ema"]
        return out
