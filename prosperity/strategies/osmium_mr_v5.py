"""Osmium mean-rev V5 — multi-layer passive quoting.

Hypothesis: in OSMIUM's wide 16-20 tick spread, the champion only posts one
level (best ± 1). Top teams do ~5× our volume — likely by **layering** passive
orders deeper in the spread to catch sweeps that don't touch L1.

V5 keeps the champion's logic intact (takes, AR1 bias, trend, make at L1)
and **adds extra layers** at progressively worse prices inside the spread:
  - layer 1: best_bid - layer_offset_1 / best_ask + layer_offset_1
  - layer 2: best_bid - layer_offset_2 / best_ask + layer_offset_2
  - ...

Each layer has its own size. Gated by `layers_enabled` so we A/B cleanly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV5Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders, conv = super().compute_orders(state, book, order_depth, position, memory)

        if not bool(self.params.get("layers_enabled", True)):
            return orders, conv
        if book.best_bid is None or book.best_ask is None:
            return orders, conv

        layer_offsets = self.params.get("layer_offsets", [3, 6])
        layer_sizes = self.params.get("layer_sizes", [20, 20])

        limit = int(self.position_limit())

        # Split existing passive (maker) orders into layers. Takers are kept
        # fully; passives get trimmed to make room for deeper layers.
        best_bid = book.best_bid
        best_ask = book.best_ask

        taker_buys = [o for o in orders if o.quantity > 0 and o.price >= best_ask]
        taker_sells = [o for o in orders if o.quantity < 0 and o.price <= best_bid]
        passive_buys = [o for o in orders if o.quantity > 0 and o.price < best_ask]
        passive_sells = [o for o in orders if o.quantity < 0 and o.price > best_bid]

        filled_buy_taker = sum(o.quantity for o in taker_buys)
        filled_sell_taker = -sum(o.quantity for o in taker_sells)
        pos_after_takers = position + filled_buy_taker - filled_sell_taker
        buy_budget = limit - pos_after_takers
        sell_budget = limit + pos_after_takers

        # Total layer sizes we want to post (deeper layers)
        total_layer_buy = sum(max(0, int(s)) for s in layer_sizes)
        total_layer_sell = total_layer_buy

        # L1 passive gets the remainder after carving out layer budgets
        l1_buy_budget = max(0, buy_budget - total_layer_buy)
        l1_sell_budget = max(0, sell_budget - total_layer_sell)

        new_orders: List[Order] = list(taker_buys) + list(taker_sells)

        # Keep passive L1 orders but trim their quantity to l1_*_budget
        remaining_l1_buy = l1_buy_budget
        for o in passive_buys:
            q = min(o.quantity, remaining_l1_buy)
            if q > 0:
                new_orders.append(Order(self.product, o.price, q))
                remaining_l1_buy -= q

        remaining_l1_sell = l1_sell_budget
        for o in passive_sells:
            q = min(-o.quantity, remaining_l1_sell)
            if q > 0:
                new_orders.append(Order(self.product, o.price, -q))
                remaining_l1_sell -= q

        # Add deeper layers within their carved budget
        buy_room = buy_budget - (l1_buy_budget - remaining_l1_buy)
        sell_room = sell_budget - (l1_sell_budget - remaining_l1_sell)

        for off, size in zip(layer_offsets, layer_sizes):
            if off <= 0 or size <= 0:
                continue
            bid_p = best_bid - int(off)
            ask_p = best_ask + int(off)
            if buy_room > 0:
                q = min(int(size), buy_room)
                if q > 0:
                    new_orders.append(Order(self.product, bid_p, q))
                    buy_room -= q
            if sell_room > 0:
                q = min(int(size), sell_room)
                if q > 0:
                    new_orders.append(Order(self.product, ask_p, -q))
                    sell_room -= q

        return new_orders, conv
