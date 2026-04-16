"""Osmium mean-rev V11 — adds L2 gap asymmetry signal.

OLS on day -2/-1/0 pooled (fwd_1 mid change in price units):
    I1-only           R2=0.347
    I1+I2+I3+L2_gaps  R2=0.450   (+0.10 incremental!)

Coefs: L2_bid_gap=-0.37  L2_ask_gap=+0.37  (symmetric)

V11 injects `l2gap_gain * (L2_ask_gap - L2_bid_gap)` into the anchor shift,
on top of champion's AR(1) term. Signal is orthogonal to I1 (which parent
does NOT use) and to AR(1) (price-based vs book-depth-based).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV11Strategy(OsmiumMeanRevStrategy):

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

        l2gap_gain = float(self.params.get("l2gap_gain", 0.0))
        l2_shift = 0.0
        if l2gap_gain > 0.0 and len(book.bid_levels) >= 2 and len(book.ask_levels) >= 2:
            bid_l1 = book.bid_levels[0][0]
            bid_l2 = book.bid_levels[1][0]
            ask_l1 = book.ask_levels[0][0]
            ask_l2 = book.ask_levels[1][0]
            l2_bid_gap = bid_l1 - bid_l2
            l2_ask_gap = ask_l2 - ask_l1
            # OLS-derived: predicted fwd move (ticks) = +k*(ask_gap - bid_gap)
            l2_shift = l2gap_gain * (l2_ask_gap - l2_bid_gap)

        saved_anchor = self.params.get("anchor_price", 10000.0)
        if l2_shift != 0.0:
            sens = float(self.params.get("trend_sensitivity", 1.0)) or 1.0
            self.params["anchor_price"] = float(saved_anchor) + l2_shift / sens

        try:
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = saved_anchor
