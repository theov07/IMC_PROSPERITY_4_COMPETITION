"""Osmium mean-rev V7 — conditional AR/imbalance switch.

Conditional corr table on day -2:
    |I1| in [0.0, 0.2):  corr_ar=-0.18  corr_I1=+0.25
    |I1| in [0.2, 0.4):  corr_ar=-0.65  corr_I1=+0.66
    |I1| in [0.4, 0.6):  corr_ar=-0.75  corr_I1=+0.77
    |I1| in [0.6, 0.8):  corr_ar=-0.87  corr_I1=+0.92
    |I1| in [0.8, 1.0]:  corr_ar=-0.94  corr_I1=+0.96

Strategy: use the CHAMPION (AR based) by default, but when |I1| >= threshold
we flip to imbalance-driven anchor shift and suppress AR for that tick.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV7Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if (
            book.best_bid is None
            or book.best_ask is None
            or not book.bid_levels
            or not book.ask_levels
        ):
            return super().compute_orders(state, book, order_depth, position, memory)

        bid_vol = book.bid_levels[0][1]
        ask_vol = book.ask_levels[0][1]
        total = bid_vol + ask_vol
        if total <= 0:
            return super().compute_orders(state, book, order_depth, position, memory)

        imb = (bid_vol - ask_vol) / total
        threshold = float(self.params.get("imb_threshold", 0.4))

        if abs(imb) < threshold:
            # Quiet book — champion / AR regime
            return super().compute_orders(state, book, order_depth, position, memory)

        # Strong imbalance regime: suppress AR, inject imbalance anchor shift
        imb_gain = float(self.params.get("imb_gain", 3.0))
        sens = float(self.params.get("trend_sensitivity", 1.0)) or 1.0
        spread = book.best_ask - book.best_bid
        shift = imb_gain * imb * spread

        orig_ar = self.params.get("ar_gain", 0.0)
        orig_anchor = float(self.params.get("anchor_price", 10000.0))
        self.params["ar_gain"] = 0.0
        self.params["anchor_price"] = orig_anchor + shift / sens
        try:
            result = super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["ar_gain"] = orig_ar
            self.params["anchor_price"] = orig_anchor

        return result
