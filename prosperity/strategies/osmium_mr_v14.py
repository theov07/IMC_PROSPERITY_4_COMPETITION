"""Osmium mean-rev V14 — layered passive on favourable side.

When dev indicates strong mean-reversion, add an extra passive order one
tick deeper inside the spread (best±2 instead of just best±1). The idea:
the base best±1 order captures "random" passive fills, and the layered
best±2 catches moments when aggressors push through to the inside tick —
both contribute edge, and the layer costs nothing if no fill happens.

Trade-off: best±2 has slightly less edge per fill (one tick closer to mid)
but much higher fill probability. Live markout is +5 ticks so even reduced
edge stays profitable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV14Strategy(OsmiumMeanRevStrategy):

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
        if dev_thr <= 0.0 or layer_size <= 0:
            return orders, convs

        anchor = float(self.params.get("anchor_price", 10000.0))
        mid = (book.best_bid + book.best_ask) / 2.0
        dev = mid - anchor

        best_bid = book.best_bid
        best_ask = book.best_ask
        spread = best_ask - best_bid
        if spread < 4:
            return orders, convs

        limit = int(self.params.get("position_limit", 80))
        filled_buy = sum(o.quantity for o in orders if o.quantity > 0)
        filled_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        buy_room = limit - position - filled_buy
        sell_room = limit + position - filled_sell

        extras: List[Order] = []
        if dev < -dev_thr and buy_room > 0:
            price = best_bid + 2
            if price < best_ask:
                qty = min(layer_size, buy_room)
                extras.append(Order(self.product, price, qty))
        elif dev > dev_thr and sell_room > 0:
            price = best_ask - 2
            if price > best_bid:
                qty = min(layer_size, sell_room)
                extras.append(Order(self.product, price, -qty))

        return orders + extras, convs
