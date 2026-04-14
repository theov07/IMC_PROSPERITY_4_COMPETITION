"""Fusion B v3 — pure fair-value crossing around block-OLS regression.

Takes any ask <= fair_value (buy cheap) and any bid >= fair_value (sell rich).
Inventory target is flat (0); the bullish-skew that prevented selling on spikes
is removed. Passive quotes stay one tick inside fv +/- spread.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


class LeoFusionBV3Strategy(Round1RegressionMMV5Strategy):

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

        take_buy_edge = float(self.params.get("v3_take_buy_edge", 0.0))
        take_sell_edge = float(self.params.get("v3_take_sell_edge", 0.0))
        passive_spread = float(self.params.get("v3_passive_spread", 2.0))

        bid_price = min(round(fv - passive_spread), book.best_ask - 1)
        ask_price = max(round(fv + passive_spread), book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Takes: buy anything at or below fv - take_buy_edge
        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - take_buy_edge or buy_cap <= 0:
                break
            qty = min(-order_depth.sell_orders[ask_p], buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            buy_cap -= qty

        # Takes: sell anything at or above fv + take_sell_edge
        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fv + take_sell_edge or sell_cap <= 0:
                break
            qty = min(order_depth.buy_orders[bid_p], sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_p, -qty))
            sell_cap -= qty

        # Passive quotes, flat inventory target (0)
        limit = self.position_limit()
        passive_max = int(self.params.get("v3_passive_size", limit))
        buy_size = max(0, min(buy_cap, passive_max, limit - position))
        sell_size = max(0, min(sell_cap, passive_max, limit + position))

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "reg_slope": round(stats["slope"], 4),
                "reg_r2": round(stats["r2"], 3),
                "trend_ticks": round(trend_ticks, 2),
                "residual_z": round(residual_z, 2),
                "block_count": int(stats["block_count"]),
                "fair_value": round(fv, 2),
            },
        )
        return orders, 0
