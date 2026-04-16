"""Osmium mean-rev V4 — anti-adverse-selection quote skew.

Observation on live log: as a symmetric penny-improve MM we end up LONG above
anchor and SHORT below (bids get hit on the way up, asks get hit on the way
down). For a mean-reverting product that's the wrong inventory sign.

V4 post-processes the parent's passive orders:
  - if mid < anchor - skew_deadband: drop (or widen) the ASK → don't sell low
  - if mid > anchor + skew_deadband: drop (or widen) the BID → don't buy high

Two modes via `skew_mode`:
  - "drop"  : remove the offending side entirely
  - "widen" : push it further from mid by `skew_widen_ticks`

Gated by `skew_enabled` so we can A/B against the champion.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV4Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders, conv = super().compute_orders(state, book, order_depth, position, memory)

        if not bool(self.params.get("skew_enabled", True)):
            return orders, conv
        if book.best_bid is None or book.best_ask is None:
            return orders, conv

        mid = (book.best_bid + book.best_ask) / 2.0
        anchor = float(self.params.get("anchor_price", 10000.0))
        deadband = float(self.params.get("skew_deadband", 1.0))
        mode = str(self.params.get("skew_mode", "drop"))
        widen = int(self.params.get("skew_widen_ticks", 5))

        dev = mid - anchor
        if abs(dev) < deadband:
            return orders, conv

        # Keep aggressive (taker) orders — identify by price crossing the book.
        def is_taker_buy(o: Order) -> bool:
            return o.quantity > 0 and book.best_ask is not None and o.price >= book.best_ask

        def is_taker_sell(o: Order) -> bool:
            return o.quantity < 0 and book.best_bid is not None and o.price <= book.best_bid

        new_orders: List[Order] = []
        for o in orders:
            taker = is_taker_buy(o) or is_taker_sell(o)
            if taker:
                new_orders.append(o)
                continue

            # Passive: apply skew
            if dev < 0:
                # mid below anchor → suppress passive SELL (don't sell cheap)
                if o.quantity < 0:
                    if mode == "drop":
                        continue
                    new_orders.append(Order(self.product, o.price + widen, o.quantity))
                    continue
            else:
                # mid above anchor → suppress passive BUY (don't buy dear)
                if o.quantity > 0:
                    if mode == "drop":
                        continue
                    new_orders.append(Order(self.product, o.price - widen, o.quantity))
                    continue

            new_orders.append(o)

        return new_orders, conv
