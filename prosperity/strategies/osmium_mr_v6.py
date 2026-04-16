"""Osmium mean-rev V6 — book imbalance L1 bias.

Measured on day -2: corr(I1, ret_next) = 0.60 (R^2 = 0.36). The L1 volume
imbalance is a massive predictor of the next mid move.

V6 injects an imbalance-driven shift into anchor_price before delegating to
the champion (osmium_mr). Since osmium_mr computes trend_shift from
(anchor - mid) * sens, moving the anchor is equivalent to adding a signal to
the fair value.

    shift = imb_gain * I1 * spread

Positive I1 (more bids than asks) → price about to rise → push anchor UP →
adjusted_mid goes UP → we quote richer (less eager to sell, more eager to buy).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV6Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return super().compute_orders(state, book, order_depth, position, memory)

        imb_gain = float(self.params.get("imb_gain", 0.0))
        if imb_gain == 0.0 or not book.bid_levels or not book.ask_levels:
            return super().compute_orders(state, book, order_depth, position, memory)

        bid_vol = book.bid_levels[0][1]
        ask_vol = book.ask_levels[0][1]
        total = bid_vol + ask_vol
        if total <= 0:
            return super().compute_orders(state, book, order_depth, position, memory)

        imb = (bid_vol - ask_vol) / total
        spread = book.best_ask - book.best_bid

        # Translate imbalance into an anchor shift. Parent then picks it up
        # via trend_shift = (anchor - mid) * sens.
        sens = float(self.params.get("trend_sensitivity", 1.0)) or 1.0
        shift = imb_gain * imb * spread

        fixed_anchor = float(self.params.get("anchor_price", 10000.0))
        self.params["anchor_price"] = fixed_anchor + shift / sens
        try:
            result = super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = fixed_anchor

        return result
