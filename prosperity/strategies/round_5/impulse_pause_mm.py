"""Impulse-pause MM: skip a side temporarily after a SNACKPACK group shock.

Validated by impulse-response analysis (research/round_5/structure_analysis):
  - SNACKPACK group shock +2σ → 7 other groups move -0.21 to -0.33σ at lag=1
  - The signal decays quickly (lag-5 = 5% of magnitude)
  - Direction: opposite (so SNACKPACK +shock → others go DOWN next tick)

Strategy:
  - If SNACKPACK group_z > +leader_thresh, skip BID for `pause_ticks` ticks
    (don't accumulate at peak before the predicted dip)
  - If SNACKPACK group_z < -leader_thresh, skip ASK for `pause_ticks` ticks

Reads SharedR5Context from memory['_ctx'].

Params:
  leader_group        : 'SNACKPACK' (default; the cross-group leader)
  leader_thresh       : abs z to fire pause (default 2.0)
  pause_ticks         : how many ticks to keep paused (default 2)
  maker_size          : default 5
  tighten_ticks       : default 1
  hard_pause_at       : default 9
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class ImpulsePauseMMStrategy(BaseStrategy):

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
        leader_group = str(self.params.get("leader_group", "SNACKPACK"))
        leader_thresh = float(self.params.get("leader_thresh", 2.0))
        pause_ticks = int(self.params.get("pause_ticks", 2))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # Read shared context
        ctx = memory.get("_ctx")
        leader_z = 0.0
        if ctx is not None:
            leader_z = ctx.group_zscore(leader_group, window=200)

        # Pause counter (positive = pause bid, negative = pause ask)
        pc = int(memory.get("_pause_counter", 0))
        if leader_z > leader_thresh:
            pc = pause_ticks  # pause bid
        elif leader_z < -leader_thresh:
            pc = -pause_ticks  # pause ask

        if pc > 0:
            post_bid = False
            pc -= 1
        elif pc < 0:
            post_ask = False
            pc += 1
        memory["_pause_counter"] = pc
        memory["_leader_z"] = leader_z

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if "_leader_z" in memory:
            out["lz"] = round(memory["_leader_z"], 3)
        if "_pause_counter" in memory:
            out["pc"] = memory["_pause_counter"]
        return out
