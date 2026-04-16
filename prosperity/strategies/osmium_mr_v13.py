"""Osmium mean-rev V13 — asymmetric passive posting.

Deep redesign motivated by live-log fill analysis (log 170620):
Passive fills are indistinguishable from baseline — they fire randomly when
we post inside-spread. Since each side-fill is 50/50 whether it's the
mean-rev favourable direction, posting BOTH sides every tick is wasteful:
half the fills push inventory the wrong way.

V13 drops the wrong-side passive when |dev| >= dev_asymm_threshold:
    dev > +thr   →  post ASK only (expect down-reversion)
    dev < -thr   →  post BID only (expect up-reversion)
    |dev| <= thr →  post both (neutral regime)

Aggressive taker logic is unchanged (already optimal under all fill models).
This halves inventory churn on the wrong side while keeping passive edge
fully on the favourable side.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV13Strategy(OsmiumMeanRevStrategy):

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

        dev_thr = float(self.params.get("dev_asymm_threshold", 0.0))
        if dev_thr <= 0.0:
            return orders, convs

        anchor = float(self.params.get("anchor_price", 10000.0))
        mid = (book.best_bid + book.best_ask) / 2.0
        dev = mid - anchor

        best_bid = book.best_bid
        best_ask = book.best_ask

        def is_aggressive(o: Order) -> bool:
            if o.quantity > 0:
                return o.price >= best_ask
            return o.price <= best_bid

        if dev > dev_thr:
            orders = [o for o in orders if o.quantity < 0 or is_aggressive(o)]
        elif dev < -dev_thr:
            orders = [o for o in orders if o.quantity > 0 or is_aggressive(o)]

        return orders, convs
