"""Naive passive market maker V4 — full capacity + inventory skew.

Same as V1 max (single order per side, full capacity) but with inventory
management via price skew:

  When we accumulate a long position, we shift BOTH bid and ask DOWN
  to make our ask more attractive to buyers → encourages selling to unwind.
  When short, we shift UP → encourages buying.

  skew = round((position / position_limit) * inv_skew_ticks)

  Example: position=+40, limit=80, inv_skew_ticks=3
    → inv_ratio = 0.5, skew = round(0.5 * 3) = 2
    → bid and ask both shift DOWN by 2 ticks
    → ask is now 2 ticks cheaper → easier to sell and unwind

Why this matters:
  V1 max hits position_limit (max_pos=80) frequently. Once at the limit,
  one side can't quote at all → missed trades → lost PnL. The skew keeps
  us closer to neutral so we can keep quoting both sides.

Parameters:
  inv_skew_ticks  (int, default 2):  max ticks to skew at full inventory
  tighten_ticks   (int, default 1):  how many ticks to intercale inside spread
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV4Strategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        inv_skew_ticks = int(self.params.get("inv_skew_ticks", 2))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        # ── Price logic (same as V1) ──
        spread = book.best_ask - book.best_bid
        if spread >= 2:
            bid_price = min(book.best_bid + tighten_ticks, book.best_ask - 1)
            ask_price = max(book.best_ask - tighten_ticks, book.best_bid + 1)
        else:
            bid_price = book.best_bid
            ask_price = book.best_ask

        # ── Inventory skew ──
        limit = self.position_limit()
        inv_ratio = position / limit if limit > 0 else 0.0
        # skew > 0 when long → shift both prices down (favour selling)
        skew = round(inv_ratio * inv_skew_ticks)

        bid_price = bid_price - skew
        ask_price = ask_price - skew

        # safety: never cross
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Orders (full capacity) ──
        if buy_cap > 0:
            orders.append(Order(self.product, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(self.product, ask_price, -sell_cap))

        # ── memory / logging ──
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        memory["last_skew"] = skew

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={"skew": skew, "position": position},
        )

        return orders, 0
