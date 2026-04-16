"""Osmium mean-rev V17 — vol-adaptive AR(1) gain.

Key finding from regime analysis (scripts/regime_ar1.py):
  Hi-vol regime: AR(1) = -0.57 to -0.62 (strong reversal)
  Lo-vol regime: AR(1) = ~0.00 (random walk, no reversal)

V17 computes EMA of squared returns as a real-time vol estimate.
When vol is above median threshold, uses ar_gain_hi (strong reversal).
When vol is below threshold, uses ar_gain_lo (near zero = random walk).
This avoids wasting edge in quiet markets where AR signal is noise.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV17Strategy(OsmiumMeanRevStrategy):

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

        # Vol estimation: EMA of squared returns
        vol_window = int(self.params.get("vol_ema_window", 10))
        vol_threshold = float(self.params.get("vol_threshold", 3.0))
        ar_gain_hi = float(self.params.get("ar_gain_hi", 1.5))
        ar_gain_lo = float(self.params.get("ar_gain_lo", 0.0))

        prev_mid = memory.get("osm_prev_mid")
        if prev_mid is not None:
            ret_sq = (mid - prev_mid) ** 2
            alpha = 2.0 / (vol_window + 1)
            ema_sq = memory.get("vol_ema_sq", ret_sq)
            ema_sq = alpha * ret_sq + (1.0 - alpha) * ema_sq
            memory["vol_ema_sq"] = ema_sq
            vol = ema_sq ** 0.5

            if vol > vol_threshold:
                self.params["ar_gain"] = ar_gain_hi
            else:
                self.params["ar_gain"] = ar_gain_lo
        else:
            self.params["ar_gain"] = ar_gain_lo

        return super().compute_orders(state, book, order_depth, position, memory)
