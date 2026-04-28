from __future__ import annotations
from typing import Any, Dict, List, Tuple
from datamodel import Order
from prosperity.strategies.base import BaseStrategy
from prosperity.market import BookSnapshot


class TrendFollowV1(BaseStrategy):
    """
    Dual-EMA trend following for Round 5 products.

    Uses a fast and slow EMA of mid price.
    Signal = fast_ema - slow_ema.
    When |signal| > threshold, takes max position in that direction.

    Works in both backtest (memory resets per day) and live (EMAs adapt naturally).
    All entries/exits are aggressive (taker) for immediate execution.

    Params:
        ema_half_life_fast  : fast EMA half-life in ticks (default 50)
        ema_half_life_slow  : slow EMA half-life in ticks (default 500)
        threshold           : |signal| required to enter (default 20)
        exit_threshold      : signal below this flattens position (default 5)
        position_limit      : max abs position (default 10)
    """

    def compute_orders(
        self,
        state,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0

        mid = book.mid_price
        limit = int(self.params.get("position_limit", 10))
        hl_fast = float(self.params.get("ema_half_life_fast", 50))
        hl_slow = float(self.params.get("ema_half_life_slow", 500))
        entry_thr = float(self.params.get("threshold", 20))
        exit_thr = float(self.params.get("exit_threshold", 5))

        alpha_fast = 1.0 - 0.5 ** (1.0 / hl_fast)
        alpha_slow = 1.0 - 0.5 ** (1.0 / hl_slow)

        ema_fast = memory.get("ema_fast", mid)
        ema_slow = memory.get("ema_slow", mid)
        ema_fast = alpha_fast * mid + (1.0 - alpha_fast) * ema_fast
        ema_slow = alpha_slow * mid + (1.0 - alpha_slow) * ema_slow
        memory["ema_fast"] = ema_fast
        memory["ema_slow"] = ema_slow

        signal = ema_fast - ema_slow

        if signal > entry_thr:
            target = limit
        elif signal < -entry_thr:
            target = -limit
        elif abs(signal) < exit_thr:
            target = 0
        else:
            target = position  # hold

        orders = self._reach_target(order_depth, position, target, limit)
        return orders, 0

    def _reach_target(self, order_depth, position: int, target: int, limit: int) -> List[Order]:
        delta = target - position
        if delta == 0:
            return []
        orders = []
        if delta > 0 and order_depth.sell_orders:
            ask = min(order_depth.sell_orders.keys())
            avail = -order_depth.sell_orders[ask]
            qty = min(delta, avail, limit - position)
            if qty > 0:
                orders.append(Order(self.product, ask, qty))
        elif delta < 0 and order_depth.buy_orders:
            bid = max(order_depth.buy_orders.keys())
            avail = order_depth.buy_orders[bid]
            qty = min(-delta, avail, limit + position)
            if qty > 0:
                orders.append(Order(self.product, bid, -qty))
        return orders
