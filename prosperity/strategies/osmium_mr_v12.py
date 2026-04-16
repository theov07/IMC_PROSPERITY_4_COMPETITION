"""Osmium mean-rev V12 — adds microprice deviation signal.

Microprice = (bid*ask_vol + ask*bid_vol) / (bid_vol + ask_vol)
micro_dev = microprice - mid

Analysis (day -2/-1/0):
    corr(micro_dev, fwd_1)  = +0.502
    I1-only R2              = 0.347
    I1 + micro_dev R2       = 0.393  (+0.046 incremental)

V12 shifts anchor by `micro_gain * micro_dev` on top of champion AR(1) logic.
Unlike I1 (which failed as direct skew in v6), microprice carries incremental
information beyond L1 imbalance.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV12Strategy(OsmiumMeanRevStrategy):

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

        micro_gain = float(self.params.get("micro_gain", 0.0))
        micro_shift = 0.0
        if micro_gain > 0.0:
            bv = float(book.best_bid_volume or 0)
            av = float(book.best_ask_volume or 0)
            tot = bv + av
            if tot > 0:
                mid = (book.best_bid + book.best_ask) / 2.0
                microprice = (book.best_bid * av + book.best_ask * bv) / tot
                micro_dev = microprice - mid
                micro_shift = micro_gain * micro_dev

        saved_anchor = self.params.get("anchor_price", 10000.0)
        if micro_shift != 0.0:
            sens = float(self.params.get("trend_sensitivity", 1.0)) or 1.0
            self.params["anchor_price"] = float(saved_anchor) + micro_shift / sens

        try:
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = saved_anchor
