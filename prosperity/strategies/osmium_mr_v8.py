"""Osmium mean-rev V8 — passive size skew from L1 imbalance.

Key finding: OSMIUM spread ≈ 16 ticks but expected move on strong imbalance
only ~3.7 ticks. Taking on the imb signal is net-negative (pays spread > edge).
Instead, keep ALL the champion logic and just skew the *quantity* we post on
each side of the passive maker quotes:

    I1 > 0 (bids strong, price tends up) → bigger bid qty, smaller ask qty
    I1 < 0 → opposite

We trim on the losing side (adverse-selected) and load the winning side.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV8Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders, conv = super().compute_orders(state, book, order_depth, position, memory)

        if not bool(self.params.get("imb_skew_enabled", True)):
            return orders, conv
        if (
            book.best_bid is None
            or book.best_ask is None
            or not book.bid_levels
            or not book.ask_levels
        ):
            return orders, conv

        bid_vol = book.bid_levels[0][1]
        ask_vol = book.ask_levels[0][1]
        total = bid_vol + ask_vol
        if total <= 0:
            return orders, conv

        imb = (bid_vol - ask_vol) / total
        threshold = float(self.params.get("imb_skew_threshold", 0.4))
        if abs(imb) < threshold:
            return orders, conv

        # Full fade: on the adverse side, scale quantity down (even to zero).
        fade = float(self.params.get("imb_skew_fade", 0.0))  # 0 = drop entirely, 0.5 = halve
        boost = float(self.params.get("imb_skew_boost", 1.0))  # multiplier on favorable side

        best_bid = book.best_bid
        best_ask = book.best_ask
        new_orders: List[Order] = []
        for o in orders:
            # Identify taker vs passive
            is_taker = (o.quantity > 0 and o.price >= best_ask) or (
                o.quantity < 0 and o.price <= best_bid
            )
            if is_taker:
                new_orders.append(o)
                continue

            if imb > 0:
                # Price expected up: fade passive SELLS, boost passive BUYS
                if o.quantity < 0:
                    new_q = int(round(o.quantity * fade))
                    if new_q != 0:
                        new_orders.append(Order(self.product, o.price, new_q))
                    continue
                else:
                    new_q = int(round(o.quantity * boost))
                    new_orders.append(Order(self.product, o.price, new_q))
                    continue
            else:
                # Price expected down: fade passive BUYS, boost passive SELLS
                if o.quantity > 0:
                    new_q = int(round(o.quantity * fade))
                    if new_q != 0:
                        new_orders.append(Order(self.product, o.price, new_q))
                    continue
                else:
                    new_q = int(round(o.quantity * boost))
                    new_orders.append(Order(self.product, o.price, new_q))
                    continue

        return new_orders, conv
