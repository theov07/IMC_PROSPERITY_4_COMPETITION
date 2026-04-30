"""Microprice + OBI-aware MM.

Improvements over naive_tight_mm:
  1. Skew quotes around microprice (volume-weighted) instead of mid
  2. OBI (order book imbalance) gate: skip side when OBI strongly opposes
  3. Inventory-aware adverse selection avoidance

Logic per tick:
  microprice = (bid_vol*ask + ask_vol*bid) / (bid_vol+ask_vol)
  obi = (bid_vol - ask_vol) / (bid_vol + ask_vol)

  bid_p = round(microprice - half_spread)  but at least best_bid+1
  ask_p = round(microprice + half_spread)  but at most best_ask-1

  If obi > obi_thresh: skip ASK (heavy buying pressure, ask likely to be hit hard)
  If obi < -obi_thresh: skip BID (heavy selling pressure)

Params:
  maker_size       default 5
  half_spread      default 1
  obi_thresh       default 0.5
  hard_pause_at    default 9
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class MicroOBIMMStrategy(BaseStrategy):

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
        half_spread = float(self.params.get("half_spread", 1.0))
        obi_thresh = float(self.params.get("obi_thresh", 0.5))
        hard_pause = int(self.params.get("hard_pause_at", 9))
        use_obi_skip = bool(self.params.get("use_obi_skip", True))

        bb, ba = book.best_bid, book.best_ask
        bv = book.best_bid_volume
        av = book.best_ask_volume

        # Microprice: weighted toward the side with MORE volume
        if bv + av > 0:
            microprice = (bv * ba + av * bb) / (bv + av)
        else:
            microprice = (bb + ba) / 2.0
        memory["_microprice"] = microprice

        # OBI
        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0
        memory["_obi"] = obi

        # Compute quotes around microprice
        bid_p = max(int(round(microprice - half_spread)), bb + 1) if (ba - bb) >= 2 else bb
        ask_p = min(int(round(microprice + half_spread)), ba - 1) if (ba - bb) >= 2 else ba
        # Sanity
        bid_p = min(bid_p, ba - 1)
        ask_p = max(ask_p, bb + 1)

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # OBI gate
        if use_obi_skip:
            if obi < -obi_thresh:
                post_bid = False  # heavy sell pressure → don't add to long
            elif obi > obi_thresh:
                post_ask = False  # heavy buy pressure → don't add to short

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
        if "_microprice" in memory:
            out["microprice"] = round(memory["_microprice"], 2)
        if "_obi" in memory:
            out["obi"] = round(memory["_obi"], 3)
        return out
