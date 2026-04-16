"""Osmium mean-rev V10 — adds AR(2) term on ret_{t-2}.

Analysis day -2/-1/0 pooled:
    AR(1): a(ret_t)=-0.4959 R2=0.244
    AR(2): a=-0.6456  b(ret_{t-1})=-0.3005  R2=0.312  (+0.068)

Champion (v1) already captures AR(1) via ar_gain=1.0. V10 adds a second lag
term so total shift = -ar_gain*ret_{t-1} - ar2_gain*ret_{t-2}.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV10Strategy(OsmiumMeanRevStrategy):

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
        ar2_gain = float(self.params.get("ar2_gain", 0.0))

        # Track last two returns for AR(2). Parent osmium_mr uses osm_prev_mid
        # for AR(1); we shadow with a second-lag slot.
        prev1 = memory.get("osm_v10_prev_mid")
        prev2 = memory.get("osm_v10_prev2_mid")

        ar2_shift = 0.0
        if ar2_gain > 0.0 and prev1 is not None and prev2 is not None:
            ret_tm1 = prev1 - prev2  # ret at t-1 = mid_{t-1} - mid_{t-2}
            ar2_shift = -ar2_gain * ret_tm1

        memory["osm_v10_prev2_mid"] = prev1
        memory["osm_v10_prev_mid"] = mid

        saved_anchor = self.params.get("anchor_price", 10000.0)
        if ar2_shift != 0.0:
            sens = float(self.params.get("trend_sensitivity", 1.0)) or 1.0
            self.params["anchor_price"] = float(saved_anchor) + ar2_shift / sens

        try:
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            # osmium_mr parent resets anchor when anchor_alpha==0, but we may
            # have added to an already-mutated value. Restore safely.
            self.params["anchor_price"] = saved_anchor
