"""Naive passive market maker.

Very simple idea:
  - never estimate fair value
  - never take aggressively
  - always quote around the current best bid / ask
  - tighten by `tighten_ticks` when there is room inside the spread
  - otherwise join the current best prices

This is intentionally simple and is useful as:
  - a baseline
  - a sanity-check submission
  - a first strategy for learning the framework
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerStrategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        maker_size = int(self.params.get("maker_size", 10))
        tighten_ticks = int(self.params.get("tighten_ticks", 1))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_price = None
        ask_price = None

        if book.best_bid is not None:
            bid_price = book.best_bid
        if book.best_ask is not None:
            ask_price = book.best_ask

        if book.best_bid is not None and book.best_ask is not None:
            spread = book.best_ask - book.best_bid
            if spread >= 2:
                bid_price = min(book.best_bid + tighten_ticks, book.best_ask - 1)
                ask_price = max(book.best_ask - tighten_ticks, book.best_bid + 1)

        if bid_price is not None and buy_cap > 0:
            orders.append(Order(self.product, bid_price, min(maker_size, buy_cap)))

        if ask_price is not None and sell_cap > 0:
            orders.append(Order(self.product, ask_price, -min(maker_size, sell_cap)))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread

        # ── Per-tick log accumulation ──
        flush_ts = int(self.params.get("log_flush_ts", 10000))
        last_tick_ts = int(self.params.get("total_ticks", 199900) - 100)

        log = memory.setdefault("_log", [])
        log.append([state.timestamp, bid_price, ask_price])

        end_of_sim = state.timestamp >= last_tick_ts
        checkpoint = flush_ts > 0 and (state.timestamp % flush_ts) == (flush_ts - 100)
        if end_of_sim or checkpoint:
            print(json.dumps({
                "product": self.product,
                "chunk_end": state.timestamp,
                "log": log,  # [[timestamp, bid, ask], ...]
            }))
            memory["_log"] = []

        return orders, 0
