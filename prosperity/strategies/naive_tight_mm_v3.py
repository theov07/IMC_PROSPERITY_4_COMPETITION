"""Naive passive market maker V3 — 2-level best-spread quoting, full capacity.

Philosophy:
  We want to ALWAYS be at the best spread, using ALL available capacity.
  Instead of a single order, we split into two layers per side to manage risk:

  Level 0 — "front" (inside the spread):
      Small size (front_size). This is our most aggressive quote: it intercales
      1 tick inside the spread to be first in line. Small because if we get
      picked off (adverse selection), we lose little.

  Level 1 — "back" (join the best bid/ask):
      All remaining capacity (buy_cap - front_size). Sits at the current best
      price. Fills when someone sweeps through the front and keeps going,
      or when the spread is only 1 tick (front joins best, back goes 1 behind).

  Total quoted per side = position_limit - abs(position).
  Nothing is left on the table.

Compared to V1 (single order, capped at maker_size=18):
  - V1 quotes 18 out of 80 capacity → misses large incoming orders
  - V3 quotes ALL 80 → captures everything, with the front layer limiting
    adverse selection exposure at the most aggressive price

Parameters:
  front_size     (int, default 5):  size of the front (inside-spread) layer
  tighten_ticks  (int, default 1):  how many ticks to intercale inside spread
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV3Strategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        front_size = int(self.params.get("front_size", 5))
        tighten_ticks = int(self.params.get("tighten_ticks", 1))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        spread = book.best_ask - book.best_bid

        # ── Level 0 (front): inside the spread ──
        # ── Level 1 (back): join best bid/ask ──
        if spread >= 2:
            front_bid = min(book.best_bid + tighten_ticks, book.best_ask - 1)
            front_ask = max(book.best_ask - tighten_ticks, book.best_bid + 1)
            back_bid = book.best_bid
            back_ask = book.best_ask
        else:
            # Spread == 1: can't intercale, front joins best, back goes behind
            front_bid = book.best_bid
            front_ask = book.best_ask
            back_bid = book.best_bid - 1
            back_ask = book.best_ask + 1

        # ── Size: front = small probe, back = remaining capacity ──
        # Buy side
        front_buy = min(front_size, buy_cap)
        back_buy = buy_cap - front_buy

        # Sell side
        front_sell = min(front_size, sell_cap)
        back_sell = sell_cap - front_sell

        # ── Place orders ──
        if front_buy > 0:
            orders.append(Order(self.product, front_bid, front_buy))
        if back_buy > 0:
            orders.append(Order(self.product, back_bid, back_buy))

        if front_sell > 0:
            orders.append(Order(self.product, front_ask, -front_sell))
        if back_sell > 0:
            orders.append(Order(self.product, back_ask, -back_sell))

        # ── memory / logging ──
        memory["last_spread"] = book.spread

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=front_bid,
            ask_price=front_ask,
            extras={"buy_capacity": buy_cap, "sell_capacity": sell_cap},
        )

        return orders, 0
