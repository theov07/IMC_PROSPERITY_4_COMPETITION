"""Statistical arbitrage strategy for basket/ETF products.

Computes synthetic value from components, tracks z-score of the spread,
and trades mean-reversion when z exceeds thresholds.

Config params:
  components: dict mapping component symbol -> weight (e.g. {"DIP": 4, "BAGUETTE": 2, "UKULELE": 1})
  entry_z: z-score threshold to open a position (default 2.0)
  exit_z: z-score threshold to close (default 0.5)
  window: rolling window for spread mean/std (default 100)
  maker_size: order size (default 10)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base.base import BaseStrategy


class StatArbStrategy(BaseStrategy):

    def _synthetic_value(self, state: TradingState) -> float | None:
        """Compute the fair value of the basket from component mid prices."""
        components: Dict[str, float] = self.params.get("components", {})
        if not components:
            return None

        total = 0.0
        for symbol, weight in components.items():
            od = state.order_depths.get(symbol)
            if od is None:
                return None
            comp_book = snapshot_from_order_depth(symbol, od)
            if comp_book.mid_price is None:
                return None
            total += comp_book.mid_price * weight

        # Add a constant offset if configured (some baskets have it)
        total += self.params.get("basket_offset", 0.0)
        return total

    def _update_spread_stats(
        self, spread: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        """Maintain rolling mean/std of the spread and return z-score."""
        window = self.params.get("window", 100)
        history = memory.setdefault("spread_history", [])
        history.append(spread)
        if len(history) > window:
            history[:] = history[-window:]

        n = len(history)
        if n < 5:
            return 0.0, spread, 1.0

        mean_s = sum(history) / n
        var_s = sum((x - mean_s) ** 2 for x in history) / max(n - 1, 1)
        std_s = math.sqrt(var_s) if var_s > 0 else 1.0
        z = (spread - mean_s) / std_s

        return z, mean_s, std_s

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0

        synthetic = self._synthetic_value(state)
        if synthetic is None:
            return [], 0

        spread = book.mid_price - synthetic
        z, mean_s, std_s = self._update_spread_stats(spread, memory)

        memory["spread"] = spread
        memory["z_score"] = z
        memory["synthetic"] = synthetic

        entry_z = self.params.get("entry_z", 2.0)
        exit_z = self.params.get("exit_z", 0.5)
        maker_size = self.params.get("maker_size", 10)

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if z > entry_z and sell_cap > 0:
            # Basket is expensive vs synthetic → sell basket
            qty = min(maker_size, sell_cap)
            if book.best_bid is not None:
                orders.append(Order(self.product, book.best_bid, -qty))

        elif z < -entry_z and buy_cap > 0:
            # Basket is cheap vs synthetic → buy basket
            qty = min(maker_size, buy_cap)
            if book.best_ask is not None:
                orders.append(Order(self.product, book.best_ask, qty))

        elif abs(z) < exit_z:
            # Mean-revert: unwind existing position
            if position > 0 and book.best_bid is not None:
                qty = min(position, sell_cap)
                if qty > 0:
                    orders.append(Order(self.product, book.best_bid, -qty))
            elif position < 0 and book.best_ask is not None:
                qty = min(-position, buy_cap)
                if qty > 0:
                    orders.append(Order(self.product, book.best_ask, qty))

        return orders, 0
