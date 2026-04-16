"""Osmium mean-rev v3: 3 structural extensions over osmium_mr.

1. Size dynamique ∝ |dev|: lower take_edge when |mid-10000| is large (stronger signal).
2. Scratch layer: post best_bid/best_ask orders when |position| small to capture neutral flow.
3. Hedge actif: when position != 0, post a passive exit order at 10000 ± hedge_edge.

Each feature is gated by a flag so we can test them in isolation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV3Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        mid = (book.best_bid + book.best_ask) / 2.0
        anchor = float(self.params.get("anchor_price", 10000.0))
        dev = mid - anchor

        # -------- Feature 1: size/edge dynamique en fonction de |dev| --------
        dyn_edge_enabled = bool(self.params.get("dyn_edge_enabled", False))
        orig_take_edge = self.params.get("take_edge", 1.75)
        if dyn_edge_enabled:
            dyn_edge_k = float(self.params.get("dyn_edge_k", 0.15))
            dyn_edge_min = float(self.params.get("dyn_edge_min", 0.5))
            adj = orig_take_edge - dyn_edge_k * abs(dev)
            self.params["take_edge"] = max(dyn_edge_min, adj)

        try:
            orders, conversions = super().compute_orders(state, book, order_depth, position, memory)
        finally:
            if dyn_edge_enabled:
                self.params["take_edge"] = orig_take_edge

        limit = self.position_limit()

        # Compute remaining capacity after parent orders
        buy_used = sum(o.quantity for o in orders if o.quantity > 0)
        sell_used = sum(-o.quantity for o in orders if o.quantity < 0)
        buy_cap_remaining = max(0, limit - position - buy_used)
        sell_cap_remaining = max(0, limit + position - sell_used)

        # -------- Feature 3: Hedge actif à la sortie --------
        hedge_enabled = bool(self.params.get("hedge_enabled", False))
        if hedge_enabled and position != 0:
            hedge_edge = int(self.params.get("hedge_edge", 1))
            hedge_size = int(self.params.get("hedge_size", 5))
            if position > 0 and sell_cap_remaining > 0:
                hedge_px = int(round(anchor + hedge_edge))
                if hedge_px > book.best_bid:
                    qty = min(position, hedge_size, sell_cap_remaining)
                    if qty > 0:
                        orders.append(Order(self.product, hedge_px, -qty))
                        sell_cap_remaining -= qty
            elif position < 0 and buy_cap_remaining > 0:
                hedge_px = int(round(anchor - hedge_edge))
                if hedge_px < book.best_ask:
                    qty = min(-position, hedge_size, buy_cap_remaining)
                    if qty > 0:
                        orders.append(Order(self.product, hedge_px, qty))
                        buy_cap_remaining -= qty

        # -------- Feature 2: Scratch layer edge=0 --------
        scratch_enabled = bool(self.params.get("scratch_enabled", False))
        scratch_pos_max = int(self.params.get("scratch_pos_max", 5))
        if scratch_enabled and abs(position) <= scratch_pos_max:
            scratch_size = int(self.params.get("scratch_size", 3))
            existing_bid_px = {o.price for o in orders if o.quantity > 0}
            existing_ask_px = {o.price for o in orders if o.quantity < 0}
            if int(book.best_bid) not in existing_bid_px and buy_cap_remaining > 0:
                orders.append(Order(self.product, int(book.best_bid), min(scratch_size, buy_cap_remaining)))
            if int(book.best_ask) not in existing_ask_px and sell_cap_remaining > 0:
                orders.append(Order(self.product, int(book.best_ask), -min(scratch_size, sell_cap_remaining)))

        return orders, conversions
