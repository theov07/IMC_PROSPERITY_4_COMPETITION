"""Naive passive market maker V6 — top of book + sweep absurd orders.

Two simple rules:
  1. ALWAYS be at the best bid/offer (top of book). When the spread is
     wide enough (>= 2), intercale 1 tick inside. Otherwise join the best.
     Full remaining capacity on every quote — nothing left on the table.

  2. Before quoting, sweep any absurd order in the book that is clearly
     mispriced relative to the mid price. After sweeping, recalculate the
     real best bid/ask from the clean book, then quote on that.

     Example: mid=10000, someone sells at 9996 → we buy at 9996 (free money),
     then quote based on the next real best ask (e.g. 10002), not on 9996.

No inventory skew, no imbalance filter, no fair value model.
Pure top-of-book market making + opportunistic taking.

Parameters:
  tighten_ticks  (int, default 1):   ticks to intercale inside spread
  take_edge      (float, default 1.0): distance from mid to trigger taking
                 1.0 = take orders more than 1 tick from mid
                 0.0 = take anything at or below mid
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV6Strategy(BaseStrategy):

    def _take_absurd_orders(
        self, order_depth: OrderDepth, mid: float, buy_cap: int, sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Sweep mispriced orders before passive quoting."""
        orders: List[Order] = []
        take_edge = float(self.params.get("take_edge", 1.0))

        # Buy cheap asks (someone selling below mid - take_edge)
        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > mid - take_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty

        # Sell to expensive bids (someone buying above mid + take_edge)
        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < mid + take_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_price, -qty))
                sell_cap -= qty

        return orders, buy_cap, sell_cap

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

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        # ── Step 1: sweep absurd orders ──
        take_orders, buy_cap, sell_cap = self._take_absurd_orders(
            order_depth, mid, buy_cap, sell_cap,
        )
        orders.extend(take_orders)

        # ── Step 2: find the REAL best bid/ask after removing swept levels ──
        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}

        real_best_ask = book.best_ask
        for ask_p, _ in book.ask_levels:
            if ask_p not in swept_ask_prices:
                real_best_ask = ask_p
                break

        real_best_bid = book.best_bid
        for bid_p, _ in book.bid_levels:
            if bid_p not in swept_bid_prices:
                real_best_bid = bid_p
                break

        # ── Step 3: quote at top of book on the clean book ──
        spread = real_best_ask - real_best_bid

        if spread >= 2:
            bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1)
            ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1)
        else:
            bid_price = real_best_bid
            ask_price = real_best_ask

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Orders: full remaining capacity ──
        if buy_cap > 0:
            orders.append(Order(self.product, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(self.product, ask_price, -sell_cap))

        # ── logging ──
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        memory["takes"] = len(take_orders)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={"position": position, "takes": len(take_orders)},
        )

        return orders, 0
