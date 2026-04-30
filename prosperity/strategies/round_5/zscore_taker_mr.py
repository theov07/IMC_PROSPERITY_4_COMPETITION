"""Z-score mean reversion taker (port of coloc's SOLO logic).

When mid is statistically extreme (|z| > enter_threshold), take FULL POSITION
in the reverting direction immediately. Hold until z reverts to near 0.

Logic:
  z = (mid - mean(window)) / std(window)
  if z > enter_threshold:  target = -size  (short max — expect mean revert down)
  if z < -enter_threshold: target = +size  (long max — expect mean revert up)
  if |z| < exit_threshold: target = 0       (flatten)

Orders are CROSSING (taker):
  buy at ask+1 to ensure fill
  sell at bid-1 to ensure fill

Per-product tunable params (mimics coloc's per-product config):
  window           rolling stats window (25-500)
  min_hist         require this many ticks before firing (==window typically)
  enter            entry threshold in z-units (1.5-3.0)
  exit             exit threshold (0.5-1.0)
  size             max position size (10 = full pos_limit)
  max_spread       skip if spread > this (avoid wide-spread products)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class ZScoreTakerMRStrategy(BaseStrategy):

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

        window = int(self.params.get("window", 200))
        min_hist = int(self.params.get("min_hist", window))
        enter = float(self.params.get("enter", 2.5))
        exit_thr = float(self.params.get("exit", 0.5))
        size = int(self.params.get("size", 10))
        max_spread = int(self.params.get("max_spread", 100))

        bb, ba = book.best_bid, book.best_ask
        mid = (bb + ba) / 2.0
        spread = ba - bb

        if spread > max_spread:
            return [], 0

        # Track mid history
        hist = memory.setdefault("_mids", [])
        hist.append(mid)
        if len(hist) > window + 5:
            hist[:] = hist[-(window + 5):]

        if len(hist) < min_hist:
            return [], 0

        # Z-score over last `window` mids
        sample = hist[-min(window, len(hist)):]
        n = len(sample)
        mu = sum(sample) / n
        var = sum((x - mu)**2 for x in sample) / max(n - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return [], 0
        z = (mid - mu) / std
        memory["_z"] = z

        # Determine target side
        side = int(memory.get("_side", 0))
        if z > enter:
            side = -1
        elif z < -enter:
            side = 1
        elif abs(z) < exit_thr:
            side = 0
        memory["_side"] = side

        target = side * size
        # Clamp to position limit
        limit = int(self.params.get("position_limit", 10))
        target = max(-limit, min(limit, target))

        diff = target - position
        orders: List[Order] = []
        if diff > 0:
            # BUY (taker) — cross at ask+1 to ensure fill
            qty = min(diff, limit - position)
            if qty > 0:
                orders.append(Order(self.product, int(ba) + 1, int(qty)))
        elif diff < 0:
            # SELL (taker)
            qty = min(-diff, limit + position)
            if qty > 0:
                orders.append(Order(self.product, int(bb) - 1, -int(qty)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if "_z" in memory: out["z"] = round(memory["_z"], 2)
        if "_side" in memory: out["side"] = memory["_side"]
        return out
