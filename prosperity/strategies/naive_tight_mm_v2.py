"""Naive passive market maker V2 — adaptive tightening + inventory skew.

Builds on naive_tight_mm with two improvements:
  1. Adaptive tightening: when quotes are not filled for several ticks,
     progressively intercale deeper inside the spread. Resets on fill.
  2. Inventory skew: shift the bid/ask prices to favour unwinding
     accumulated position.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV2Strategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        # ── params ──
        maker_size = int(self.params.get("maker_size", 10))
        base_tighten = int(self.params.get("tighten_ticks", 1))
        max_tighten = int(self.params.get("max_tighten_ticks", 4))
        decay_interval = int(self.params.get("decay_interval", 3))
        inv_skew_ticks = int(self.params.get("inv_skew_ticks", 0))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── detect fill since last tick ──
        prev_position = memory.get("prev_position", 0)
        filled = position != prev_position
        memory["prev_position"] = position

        # ── adaptive tighten counter ──
        if filled:
            ticks_since_fill = 0
        else:
            ticks_since_fill = memory.get("ticks_since_fill", 0) + 1
        memory["ticks_since_fill"] = ticks_since_fill

        # how many extra ticks to tighten (grows every decay_interval ticks without fill)
        extra_tighten = min(ticks_since_fill // decay_interval, max_tighten - base_tighten)
        tighten = base_tighten + extra_tighten

        # ── inventory skew ──
        limit = self.position_limit()
        inv_ratio = position / limit if limit > 0 else 0.0
        # skew > 0 when long → lower bid, lower ask (favour selling)
        skew = round(inv_ratio * inv_skew_ticks)

        # ── price logic ──
        bid_price = None
        ask_price = None

        if book.best_bid is not None:
            bid_price = book.best_bid
        if book.best_ask is not None:
            ask_price = book.best_ask

        if book.best_bid is not None and book.best_ask is not None:
            spread = book.best_ask - book.best_bid
            if spread >= 2:
                bid_price = min(book.best_bid + tighten, book.best_ask - 1)
                ask_price = max(book.best_ask - tighten, book.best_bid + 1)

        # apply inventory skew
        if bid_price is not None:
            bid_price = bid_price - skew
        if ask_price is not None:
            ask_price = ask_price - skew

        # safety: never cross
        if bid_price is not None and ask_price is not None and bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── orders ──
        if bid_price is not None and buy_cap > 0:
            orders.append(Order(self.product, bid_price, min(maker_size, buy_cap)))
        if ask_price is not None and sell_cap > 0:
            orders.append(Order(self.product, ask_price, -min(maker_size, sell_cap)))

        # ── memory / logging ──
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        memory["last_tighten"] = tighten

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={"tighten": tighten, "skew": skew},
        )

        return orders, 0
