"""Tracking-error MM: trade deviation from group equal-weight mean.

Hypothesis (validated for TRANSLATOR, PEBBLES groups where group_mean R^2=0):
  - Group mean is FLAT or near-flat
  - Members oscillate around the mean via internal substitution
  - Member's deviation from mean is mean-reverting at slow timescale

Strategy:
  - Compute fair_value = mean of group mids (read from SharedR5Context)
  - Compute deviation = mid - fair_value
  - Track rolling mean and std of deviation
  - If z(deviation) > z_entry  -> overpriced vs basket -> skew ASK aggressive
    or post passive sell at fair value level
  - If z(deviation) < -z_entry -> underpriced -> skew BID aggressive
  - Default: tight passive MM

Params:
  maker_size           default 5
  tighten_ticks        default 1
  z_window             rolling window for dev z (default 200)
  z_entry              abs z threshold (default 1.0)
  z_skew_offset        ticks added when skewing (default 1)
  hard_pause_at        |pos| at which inv-increasing side pauses (default 9)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy
from prosperity.baskets.groups import group_of, GROUPS


class TrackingErrorMMStrategy(BaseStrategy):

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
        z_window = int(self.params.get("z_window", 200))
        z_entry = float(self.params.get("z_entry", 1.0))
        z_skew = int(self.params.get("z_skew_offset", 1))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # Read shared context (injected by trader)
        ctx = memory.get("_ctx")
        dev_z = 0.0
        if ctx is not None:
            g = group_of(self.product)
            mid = (book.best_bid + book.best_ask) / 2.0
            if g:
                # Compute fair value = mean of group members' mids in ctx
                members = GROUPS[g]
                vals = [ctx.mids.get(m) for m in members if ctx.mids.get(m) is not None]
                if vals:
                    fv = sum(vals) / len(vals)
                    dev = mid - fv
                    # Rolling buffer of deviations
                    buf = memory.setdefault("_dev_buf", [])
                    buf.append(dev)
                    if len(buf) > z_window:
                        buf[:] = buf[-z_window:]
                    if len(buf) >= 30:
                        n = len(buf)
                        mu = sum(buf) / n
                        var = sum((x - mu) ** 2 for x in buf) / max(n - 1, 1)
                        std = var ** 0.5
                        if std > 1e-6:
                            dev_z = (dev - mu) / std
        memory["_dev_z"] = dev_z

        # Skew based on tracking error z
        if dev_z > z_entry:
            # Overpriced vs basket -> sell harder
            ask_p = max(ask_p - z_skew, book.best_bid + 1)
        elif dev_z < -z_entry:
            bid_p = min(bid_p + z_skew, book.best_ask - 1)

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

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
