"""Osmium mean-rev V16 — multi-level layered passive.

Extends v14 with a second layer at best±3 in addition to best±2, providing
a staircase of inside-spread quotes on the favourable mean-rev side.
Each layer captures progressively deeper inside-spread fills, which are
rarer but have different markout characteristics.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV16Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders, convs = super().compute_orders(state, book, order_depth, position, memory)
        if book.best_bid is None or book.best_ask is None:
            return orders, convs

        dev_thr = float(self.params.get("layer_dev_threshold", 0.0))
        layer_size = int(self.params.get("layer_size", 0))
        n_layers = int(self.params.get("n_layers", 1))
        if dev_thr <= 0.0 or layer_size <= 0 or n_layers <= 0:
            return orders, convs

        anchor = float(self.params.get("anchor_price", 10000.0))
        mid = (book.best_bid + book.best_ask) / 2.0
        dev = mid - anchor

        best_bid = book.best_bid
        best_ask = book.best_ask
        spread = best_ask - best_bid
        min_spread = 2 + n_layers + 1
        if spread < min_spread:
            return orders, convs

        limit = int(self.params.get("position_limit", 80))
        filled_buy = sum(o.quantity for o in orders if o.quantity > 0)
        filled_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        buy_room = limit - position - filled_buy
        sell_room = limit + position - filled_sell

        extras: List[Order] = []
        for layer_i in range(n_layers):
            offset = 2 + layer_i
            if dev < -dev_thr and buy_room > 0:
                price = best_bid + offset
                if price < best_ask:
                    qty = min(layer_size, buy_room)
                    extras.append(Order(self.product, price, qty))
                    buy_room -= qty
            elif dev > dev_thr and sell_room > 0:
                price = best_ask - offset
                if price > best_bid:
                    qty = min(layer_size, sell_room)
                    extras.append(Order(self.product, price, -qty))
                    sell_room -= qty

        return orders + extras, convs
