"""Tracking-error skip MM: skip side when product deviates from group mean.

Successor to tracking_error_mm (which used price skew, costing spread).
This version : default tight passive MM + skip BID when product is rich vs
group mean, skip ASK when cheap. No price skew = full spread captured.

Hypothesis : groups with flat mean (TRANSLATOR R²=0.005, PEBBLES R²=0) have
member deviations that are bounded oscillations -> skip-side reduces adverse fills.

Params:
  maker_size       : default 5
  tighten_ticks    : default 1
  z_window         : rolling window for dev z (default 300)
  dev_thresh       : abs z to fire skip (default 1.5)
  hard_pause_at    : default 9
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy
from prosperity.baskets.groups import group_of, GROUPS


class TrackingErrorSkipMMStrategy(BaseStrategy):

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

        size = int(self.params.get("maker_size", 5))
        tighten = int(self.params.get("tighten_ticks", 1))
        z_window = int(self.params.get("z_window", 300))
        dev_thresh = float(self.params.get("dev_thresh", 1.5))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # Compute deviation from group mean
        ctx = memory.get("_ctx")
        dev_z = 0.0
        if ctx is not None:
            g = group_of(self.product)
            if g:
                mid = (book.best_bid + book.best_ask) / 2.0
                members = GROUPS[g]
                vals = [ctx.mids.get(m) for m in members if ctx.mids.get(m) is not None]
                if vals and len(vals) >= 2:
                    fv = sum(vals) / len(vals)
                    dev = mid - fv
                    buf = memory.setdefault("_dev_buf", [])
                    buf.append(dev)
                    if len(buf) > z_window:
                        buf[:] = buf[-z_window:]
                    if len(buf) >= 30:
                        n = len(buf)
                        mu = sum(buf) / n
                        var = sum((x - mu) ** 2 for x in buf) / max(n - 1, 1)
                        std = math.sqrt(var)
                        if std > 1e-6:
                            dev_z = (dev - mu) / std
        memory["_dev_z"] = dev_z

        # Skip-side based on dev_z
        if dev_z > dev_thresh:
            post_bid = False  # rich vs basket -> don't load up
        elif dev_z < -dev_thresh:
            post_ask = False  # cheap vs basket -> don't sell

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_dev_z")
        return {"dev_z": round(z, 3)} if z is not None else {}
