"""Volatility-adaptive MM.

Adjusts tighten_ticks (how aggressive penny-improve is) based on realized vol.
- Low vol: tighten=1 (aggressive penny improve, more fills)
- High vol: tighten=2 or 3 (wider, avoid adverse selection)

Vol = std of recent mid changes over `vol_window` ticks.

Params:
  maker_size       default 5
  vol_window       default 100
  vol_low_thresh   below this = aggressive (default 1.0)
  vol_high_thresh  above this = passive (default 3.0)
  tighten_low      default 1 (aggressive)
  tighten_high     default 3 (passive)
  hard_pause_at    default 9
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class VolAdaptiveMMStrategy(BaseStrategy):

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
        vol_window = int(self.params.get("vol_window", 100))
        vol_low = float(self.params.get("vol_low_thresh", 1.0))
        vol_high = float(self.params.get("vol_high_thresh", 3.0))
        tighten_low = int(self.params.get("tighten_low", 1))
        tighten_high = int(self.params.get("tighten_high", 3))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        mid = (book.best_bid + book.best_ask) / 2.0
        # Track mid history for vol
        mids = memory.setdefault("_mids", [])
        mids.append(mid)
        if len(mids) > vol_window:
            mids[:] = mids[-vol_window:]

        # Compute realized vol = std of returns
        if len(mids) >= 30:
            returns = [mids[i+1] - mids[i] for i in range(len(mids)-1)]
            n = len(returns)
            mu = sum(returns) / n
            var = sum((r - mu)**2 for r in returns) / max(n-1, 1)
            vol = math.sqrt(var)
        else:
            vol = 1.5  # default mid

        memory["_vol"] = vol

        # Adaptive tighten
        if vol < vol_low:
            tighten = tighten_low
        elif vol > vol_high:
            tighten = tighten_high
        else:
            # Linear interpolation
            frac = (vol - vol_low) / (vol_high - vol_low)
            tighten = round(tighten_low + frac * (tighten_high - tighten_low))

        spread = book.best_ask - book.best_bid
        if spread >= 2 * tighten:
            bid_p = book.best_bid + tighten
            ask_p = book.best_ask - tighten
        else:
            bid_p = book.best_bid
            ask_p = book.best_ask

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
        out = {}
        if "_vol" in memory:
            out["vol"] = round(memory["_vol"], 2)
        return out
