"""Buy-and-hold strategy.

Buys one unit on the first available tick (taker order at best_ask),
then holds for the rest of the day. No selling, no passive quoting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class BuyAndHoldStrategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        if position >= 1:
            return [], 0  # holding — do nothing

        if book.best_ask is None:
            return [], 0  # no ask available yet, wait

        return [Order(self.product, book.best_ask, 1)], 0
