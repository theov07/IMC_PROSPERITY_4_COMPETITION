"""Fusion C — V5 base passive + take aggressif conditionnel en dip de trend fort.

V5 reste la strategie principale (quoting top-of-book + sizing trend-driven).
On active un take aggressif uniquement quand trend_ticks >= very_strong ET
residual_z <= cheap_z (dip dans un uptrend), en direction de la cible.

IPR uniquement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


class LeoFusionCStrategy(Round1RegressionMMV5Strategy):

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
        inv_target = self._inventory_target(state=state, stats=stats, position=position)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        cheap_z = float(self.params.get("cheap_residual_z", 0.9))
        rich_z = float(self.params.get("rich_residual_z", 0.9))

        trend_ticks = stats["trend_ticks"]
        residual_z = stats["residual_z"]
        fv = stats["fair_value"]

        strong_buy_window = trend_ticks >= very_strong and residual_z <= -cheap_z * 0.0
        # ^ we allow any non-rich residual as long as the trend is very strong
        # i.e. take when mid is at or below fitted level (residual <= 0 proxy)
        strong_buy_window = trend_ticks >= very_strong and residual_z <= 0.0
        strong_sell_window = trend_ticks <= -very_strong and residual_z >= 0.0

        take_edge = float(self.params.get("aggressive_take_edge", 2.0))
        max_take = int(self.params.get("aggressive_take_size", 8))

        position_now = position
        if strong_buy_window and buy_cap > 0 and position_now < inv_target:
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

        if strong_sell_window and sell_cap > 0 and position_now > inv_target:
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

        # V5 quoting path
        bid_price, ask_price, _, _ = self._quote_prices(
            book=book,
            stats=stats,
            position=position_now,
            inv_target=inv_target,
        )
        buy_size, sell_size = self._size_from_target(
            position=position_now,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["inv_target"] = inv_target
        return orders, 0
