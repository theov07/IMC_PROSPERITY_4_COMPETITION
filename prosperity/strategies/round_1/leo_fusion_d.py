"""Fusion D — regime hybrid: bootstrap / strong_trend / choppy.

3 regimes based on the V5 block-OLS signal:
- bootstrap  (t < startup_end_ts or block_count < min_blocks)
    -> V22 follow-book quoting, fixed target_bull, no take
- strong_trend (|trend_ticks| > strong and confidence > conf_floor)
    -> V18 biased quoting + aggressive take
- choppy (else)
    -> V5 top-of-book passive only

IPR uniquement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


class LeoFusionDStrategy(Round1RegressionMMV5Strategy):

    # ---- helpers -------------------------------------------------------

    def _v22_quote(
        self,
        *,
        book: BookSnapshot,
        fv: float,
        bullish: bool,
    ) -> Tuple[int, int]:
        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 7.0))
        neut_spread = float(self.params.get("neut_spread", 3.0))
        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
            bid_price = max(raw_bid, book.best_bid)
            bid_price = min(bid_price, book.best_ask - 1)
            ask_price = min(raw_ask, book.best_ask)
            ask_price = max(ask_price, book.best_bid + 1)
        else:
            raw_bid = round(fv - neut_spread)
            raw_ask = round(fv + neut_spread)
            bid_price = min(raw_bid, book.best_ask - 1)
            ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            bid_price = ask_price - 1
        return bid_price, ask_price

    def _v18_quote(
        self,
        *,
        book: BookSnapshot,
        fv: float,
        bullish: bool,
    ) -> Tuple[int, int]:
        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull_wide = float(self.params.get("ask_spread_bull_wide", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))
        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull_wide)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)
        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1
        return bid_price, ask_price

    def _simple_sizing(
        self,
        *,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)
        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.40))
        aggravate_min = float(self.params.get("aggravate_min_frac", 0.20))
        unwind_boost = float(self.params.get("unwind_boost_frac", 0.40))
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

    # ---- main ----------------------------------------------------------

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
        fv = stats["fair_value"]
        trend_ticks = stats["trend_ticks"]
        residual_z = stats["residual_z"]
        confidence = stats["confidence"]
        block_count = int(stats["block_count"])

        min_blocks = int(self.params.get("min_completed_blocks", 5))
        bootstrap_end_ts = int(self.params.get("startup_end_ts", 30000))
        strong = float(self.params.get("strong_trend_ticks", 1.1))
        conf_floor = float(self.params.get("regime_confidence_floor", 0.5))

        in_bootstrap = block_count < min_blocks or int(state.timestamp) < bootstrap_end_ts
        in_strong = (not in_bootstrap) and abs(trend_ticks) >= strong and confidence >= conf_floor

        limit = self.position_limit()
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── Bootstrap regime: V22 follow-book, fixed target, passive only ─
        if in_bootstrap:
            bullish = trend_ticks > 0.0
            target_bull = int(self.params.get("bootstrap_target_bull", 40))
            inv_target = target_bull if bullish else 0

            bid_price, ask_price = self._v22_quote(book=book, fv=fv, bullish=bullish)
            buy_size, sell_size = self._simple_sizing(
                position=position, inv_target=inv_target, buy_cap=buy_cap, sell_cap=sell_cap,
            )
            if buy_size > 0:
                orders.append(Order(self.product, bid_price, buy_size))
            if sell_size > 0:
                orders.append(Order(self.product, ask_price, -sell_size))
            memory["regime"] = "bootstrap"
            memory["inv_target"] = inv_target
            return orders, 0

        # ── Strong trend regime: V18 biased quoting + aggressive take ─────
        if in_strong:
            bullish = trend_ticks > 0.0
            inv_target = self._inventory_target(state=state, stats=stats, position=position)
            bid_price, ask_price = self._v18_quote(book=book, fv=fv, bullish=bullish)

            take_edge = float(self.params.get("strong_take_edge", 2.0))
            max_take = int(self.params.get("strong_take_size", 8))
            position_now = position

            if bullish and buy_cap > 0 and position_now < inv_target:
                for ask_p in sorted(order_depth.sell_orders):
                    if ask_p > fv - take_edge:
                        break
                    qty = min(-order_depth.sell_orders[ask_p], buy_cap, max_take)
                    if qty <= 0:
                        continue
                    orders.append(Order(self.product, ask_p, qty))
                    buy_cap -= qty
                    position_now += qty
                    if buy_cap <= 0 or position_now >= inv_target:
                        break

            if (not bullish) and sell_cap > 0 and position_now > inv_target:
                for bid_p in sorted(order_depth.buy_orders, reverse=True):
                    if bid_p < fv + take_edge:
                        break
                    qty = min(order_depth.buy_orders[bid_p], sell_cap, max_take)
                    if qty <= 0:
                        continue
                    orders.append(Order(self.product, bid_p, -qty))
                    sell_cap -= qty
                    position_now -= qty
                    if sell_cap <= 0 or position_now <= inv_target:
                        break

            buy_size, sell_size = self._size_from_target(
                position=position_now, inv_target=inv_target, stats=stats,
                buy_cap=buy_cap, sell_cap=sell_cap,
            )
            if buy_size > 0:
                orders.append(Order(self.product, bid_price, buy_size))
            if sell_size > 0:
                orders.append(Order(self.product, ask_price, -sell_size))
            memory["regime"] = "strong"
            memory["inv_target"] = inv_target
            return orders, 0

        # ── Choppy regime: V5 top-of-book passive ─────────────────────────
        inv_target = self._inventory_target(state=state, stats=stats, position=position)
        bid_price, ask_price, _, _ = self._quote_prices(
            book=book, stats=stats, position=position, inv_target=inv_target,
        )
        buy_size, sell_size = self._size_from_target(
            position=position, inv_target=inv_target, stats=stats,
            buy_cap=buy_cap, sell_cap=sell_cap,
        )
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))
        memory["regime"] = "choppy"
        memory["inv_target"] = inv_target
        return orders, 0
