"""Naive tight MM + late-session inventory flatten.

This keeps the full intraday behaviour of naive_tight_mm and only intervenes
near the end of the session, where the live log showed many MM products
finishing with +7 / -6 inventory and donating MTM into the close.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class LateFlattenTightMMV1(BaseStrategy):
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

        bid_price = book.best_bid if book.best_bid is not None else None
        ask_price = book.best_ask if book.best_ask is not None else None

        if book.best_bid is not None and book.best_ask is not None:
            spread = book.best_ask - book.best_bid
            if spread >= 2:
                bid_price = min(book.best_bid + tighten_ticks, book.best_ask - 0.1)
                ask_price = max(book.best_ask - tighten_ticks, book.best_bid + 0.1)

        ts = int(state.timestamp)
        passive_unwind_start = int(self.params.get("late_passive_unwind_start_ts", 98000))
        taker_unwind_start = int(self.params.get("late_taker_unwind_start_ts", 99400))
        late_unwind_qty = int(self.params.get("late_unwind_qty", 2))
        late_unwind_pos_gate = int(self.params.get("late_unwind_pos_gate", 4))

        if ts >= passive_unwind_start and abs(position) >= late_unwind_pos_gate:
            if position > 0:
                bid_price = None
                if ask_price is not None and book.best_bid is not None:
                    ask_price = min(ask_price, book.best_bid + 1)
            elif position < 0:
                ask_price = None
                if bid_price is not None and book.best_ask is not None:
                    bid_price = max(bid_price, book.best_ask - 1)

        if bid_price is not None and buy_cap > 0:
            orders.append(Order(self.product, bid_price, min(maker_size, buy_cap)))
        if ask_price is not None and sell_cap > 0:
            orders.append(Order(self.product, ask_price, -min(maker_size, sell_cap)))

        if ts >= taker_unwind_start and abs(position) >= late_unwind_pos_gate:
            if position > 0 and book.best_bid is not None and sell_cap > 0:
                qty = min(late_unwind_qty, sell_cap, position, int(book.best_bid_volume or 0))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_bid), -qty))
            elif position < 0 and book.best_ask is not None and buy_cap > 0:
                qty = min(late_unwind_qty, buy_cap, -position, int(book.best_ask_volume or 0))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_ask), qty))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        self.log_quote_snapshot(state=state, memory=memory, bid_price=bid_price, ask_price=ask_price)
        return orders, 0
