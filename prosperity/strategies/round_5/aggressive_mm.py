"""Aggressive live-MM with tighter posting and optional taker triggers.

Designed for IMC live where counterparty may not have strong adverse selection.

Modes:
  mode='at_mid' : post AT (mid-spread/2) — tightest, almost taker-level
  mode='tight'  : tighten_ticks=2 (more inside spread than penny-improve)
  mode='taker_on_signal' : penny-improve + taker when external signal fires

Params:
  maker_size       default 5
  mode             'at_mid' | 'tight' | 'taker_on_signal'
  tighten_ticks    default 2
  half_spread      for 'at_mid' mode (default 0.5)
  hard_pause_at    default 9
  taker_size       size of taker order on signal (default 10)
  signal_threshold for taker mode (default 1.5 std)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class AggressiveMMStrategy(BaseStrategy):

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
        mode = self.params.get("mode", "tight")
        tighten = int(self.params.get("tighten_ticks", 2))
        half_spread = float(self.params.get("half_spread", 0.5))
        hard_pause = int(self.params.get("hard_pause_at", 9))
        taker_size = int(self.params.get("taker_size", 10))

        bb, ba = book.best_bid, book.best_ask
        spread = ba - bb

        # Mode-dependent quote calculation
        if mode == "at_mid":
            # Post AT mid (tightest possible without crossing)
            mid = (bb + ba) / 2.0
            bid_p = int(math.floor(mid - half_spread))  # just below mid
            ask_p = int(math.ceil(mid + half_spread))   # just above mid
            # Sanity
            bid_p = max(bid_p, bb)  # don't post below market
            ask_p = min(ask_p, ba)  # don't post above market
            # If posting would cross, fall back to naive
            if bid_p >= ask_p:
                bid_p = bb + 1 if spread >= 2 else bb
                ask_p = ba - 1 if spread >= 2 else ba
        elif mode == "tight":
            # Aggressive tighten (default 2 ticks)
            if spread >= 2 * tighten:
                bid_p = bb + tighten
                ask_p = ba - tighten
            elif spread >= 2:
                bid_p = bb + 1
                ask_p = ba - 1
            else:
                bid_p = bb
                ask_p = ba
        else:
            # Default penny-improve (taker_on_signal uses this for MM legs)
            bid_p = bb + 1 if spread >= 2 else bb
            ask_p = ba - 1 if spread >= 2 else ba

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ─ Optional taker on external signal (fed via memory by Trader)
        # If memory has 'taker_signal' = +1 (buy aggressive) or -1 (sell aggressive)
        if mode == "taker_on_signal":
            sig = memory.get("_external_taker_signal", 0)
            if sig > 0 and buy_cap > 0:
                # Aggressive BUY at ask
                orders.append(Order(self.product, ba, min(taker_size, buy_cap)))
                buy_cap -= min(taker_size, buy_cap)
            elif sig < 0 and sell_cap > 0:
                orders.append(Order(self.product, bb, -min(taker_size, sell_cap)))
                sell_cap -= min(taker_size, sell_cap)

        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0
