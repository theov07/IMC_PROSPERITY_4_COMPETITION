"""Tick-reversal skip MM: skip bid after positive tick, skip ask after negative tick.

Targets products with negative AR1 of returns (= mean-reverting tick-to-tick).
Validated by PCA-residual analysis:
  - ROBOT_DISHES: AR1_resid = -0.22 (strongest)
  - ROBOT_IRONING: -0.12
  - OXYGEN_SHAKE_EVENING_BREATH: -0.12
  - OXYGEN_SHAKE_CHOCOLATE: -0.08

Strategy:
  - Default: tight passive MM
  - If last_return > +eps: skip BID (price went up, expect mean-rev down -> don't buy peak)
  - If last_return < -eps: skip ASK (price went down, expect rise -> don't sell trough)

Params:
  maker_size       : default 5
  tighten_ticks    : default 1
  reversal_eps     : minimum return magnitude to fire skip (default 0.5 ticks)
  hard_pause_at    : default 9
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class TickReversalSkipMMStrategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        size = int(self.params.get("maker_size", 5))
        tighten = int(self.params.get("tighten_ticks", 1))
        eps = float(self.params.get("reversal_eps", 0.5))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        mid = (book.best_bid + book.best_ask) / 2.0
        last_mid = memory.get("_last_mid", mid)
        last_ret = mid - last_mid
        memory["_last_mid"] = mid
        memory["_last_ret"] = last_ret

        if last_ret > eps:
            post_bid = False  # price up, expect down
        elif last_ret < -eps:
            post_ask = False  # price down, expect up

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        r = memory.get("_last_ret")
        return {"last_ret": round(r, 3)} if r is not None else {}
