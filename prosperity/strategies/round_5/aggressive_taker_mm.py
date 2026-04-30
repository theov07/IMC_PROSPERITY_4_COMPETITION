"""Aggressive taker MM — fire taker (full size) on momentum + MM as backup.

Strategy logic:
  1. Standard penny-improve MM (capture spread when calm)
  2. WHEN momentum signal fires:
     - Fast move detected (last K ticks return > thresh)
     - In same direction as slow trend (avoid fakeouts)
     - → TAKE FULL SIZE (taker_size=10) at market price
  3. After taking, hold or exit on reverse signal

This is what top live teams do: aggressive directional bets when signal
clears, otherwise passive MM.

Params:
  maker_size       default 5 (passive MM size)
  taker_size       default 10 (aggressive taker size)
  fast_window      default 50 (ticks for momentum)
  slow_window      default 200 (ticks for trend confirmation)
  fast_thresh      default 5.0 (min |return| over fast_window to fire)
  trend_align      bool, default True (require fast & slow same direction)
  hard_pause_at    default 9
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class AggressiveTakerMMStrategy(BaseStrategy):

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
        taker_size = int(self.params.get("taker_size", 10))
        fast_window = int(self.params.get("fast_window", 50))
        slow_window = int(self.params.get("slow_window", 200))
        fast_thresh = float(self.params.get("fast_thresh", 5.0))
        trend_align = bool(self.params.get("trend_align", True))
        tighten = int(self.params.get("tighten_ticks", 1))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        bb, ba = book.best_bid, book.best_ask
        mid = (bb + ba) / 2.0

        # Track mid history
        mids = memory.setdefault("_mids", [])
        mids.append(mid)
        max_w = max(fast_window, slow_window) + 5
        if len(mids) > max_w:
            mids[:] = mids[-max_w:]

        # ── Compute signals ─────────────────────────────────────
        fast_return = 0.0
        slow_return = 0.0
        if len(mids) >= fast_window + 1:
            fast_return = mids[-1] - mids[-fast_window - 1]
        if len(mids) >= slow_window + 1:
            slow_return = mids[-1] - mids[-slow_window - 1]

        memory["_fast_ret"] = fast_return
        memory["_slow_ret"] = slow_return

        # ── Decide on taker ─────────────────────────────────────
        taker_signal = 0  # +1 = aggressive buy, -1 = aggressive sell
        if abs(fast_return) >= fast_thresh:
            if not trend_align or (fast_return * slow_return >= 0):
                taker_signal = 1 if fast_return > 0 else -1

        memory["_taker_sig"] = taker_signal

        # ── MM base orders ──────────────────────────────────────
        spread = ba - bb
        bid_p = bb + tighten if spread >= 2 else bb
        ask_p = ba - tighten if spread >= 2 else ba

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── Fire taker first if signal ──────────────────────────
        if taker_signal > 0 and buy_cap > 0:
            qty = min(taker_size, buy_cap)
            orders.append(Order(self.product, ba, qty))  # take ASK
            buy_cap -= qty
            post_bid = False  # don't double-bid this tick
        elif taker_signal < 0 and sell_cap > 0:
            qty = min(taker_size, sell_cap)
            orders.append(Order(self.product, bb, -qty))  # take BID
            sell_cap -= qty
            post_ask = False

        # ── Passive MM orders ───────────────────────────────────
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if "_fast_ret" in memory: out["fast_ret"] = round(memory["_fast_ret"], 2)
        if "_slow_ret" in memory: out["slow_ret"] = round(memory["_slow_ret"], 2)
        if "_taker_sig" in memory: out["taker_sig"] = memory["_taker_sig"]
        return out
