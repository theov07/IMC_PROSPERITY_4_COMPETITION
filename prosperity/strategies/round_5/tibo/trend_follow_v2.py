from __future__ import annotations
from typing import Any, Dict, List, Tuple
from datamodel import Order
from prosperity.strategies.base import BaseStrategy
from prosperity.market import BookSnapshot


class TrendFollowV2(BaseStrategy):
    """
    Level-based trend following for Round 5 products.

    Signal = EMA(mid, hl) - start_session_price
    - Enters max long  when signal > +entry_threshold
    - Enters max short when signal < -entry_threshold
    - Holds position until signal clearly reverses past exit_threshold
    - Optional warmup_ticks: won't enter before this many ticks have elapsed

    Using a fixed start_price (first price of each session) rather than
    a rolling reference avoids the dual-EMA noise amplification problem.

    Params:
        ema_half_life   : EMA half-life in ticks (default 100)
        threshold       : deviation from start to enter (default 80)
        exit_threshold  : deviation to close a wrong-way position (default 30)
        warmup_ticks    : ticks before first entry allowed (default 0)
        position_limit  : 10 for all R5 products
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
        hl = float(self.params.get("ema_half_life", 100))
        entry_thr = float(self.params.get("threshold", 80))
        exit_thr = float(self.params.get("exit_threshold", 30))
        min_tick = int(self.params.get("warmup_ticks", 0))

        alpha = 1.0 - 0.5 ** (1.0 / hl)

        if "start_price" not in memory:
            memory["start_price"] = mid
        if "ema" not in memory:
            memory["ema"] = mid
        tick = memory.get("tick", 0)
        memory["tick"] = tick + 1

        ema = alpha * mid + (1.0 - alpha) * memory["ema"]
        memory["ema"] = ema

        if tick < min_tick:
            return [], 0

        signal = ema - memory["start_price"]

        if signal > entry_thr:
            target = limit
        elif signal < -entry_thr:
            target = -limit
        elif position > 0 and signal < -exit_thr:
            target = 0
        elif position < 0 and signal > exit_thr:
            target = 0
        else:
            target = position  # hold

        return self._reach_target(order_depth, position, target, limit), 0

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
