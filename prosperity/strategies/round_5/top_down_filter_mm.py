"""Top-down regime filter MM.

Detects GROUP-LEVEL regime via shared context, then applies decision logic
top-down:
  1. Compute group's recent PnL contribution (via SharedR5Context)
  2. If group is in BAD regime, throttle ALL members of group
  3. Within good groups, apply standard MM

This is hierarchical filtering: if entire group (e.g. GALAXY_SOUNDS) is
losing money in current regime, pause everyone in that group, regardless
of individual product signal.

Reads: memory["_ctx"] (SharedR5Context) for group state.

Params:
  maker_size           default 5
  tighten_ticks        default 1
  group_pnl_window     rolling window for group PnL aggregate (default 1000)
  bad_group_pnl        threshold below which throttle entire group (default -500)
  throttle_size        size when in bad regime (default 1)
  hard_pause_at        default 9
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy
from prosperity.baskets.groups import group_of, GROUPS


class TopDownFilterMMStrategy(BaseStrategy):

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
        bad_group_pnl = float(self.params.get("bad_group_pnl", -500.0))
        throttle_size = int(self.params.get("throttle_size", 1))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # Track per-product unrealized PnL change
        mid = (book.best_bid + book.best_ask) / 2.0
        last_mid = memory.get("_last_mid", mid)
        last_pos = memory.get("_last_pos", 0)
        unreal_dpnl = last_pos * (mid - last_mid)
        memory["_last_mid"] = mid
        memory["_last_pos"] = position

        # Aggregate group PnL via shared dict in ctx
        ctx = memory.get("_ctx")
        bad_group = False
        if ctx is not None:
            g = group_of(self.product)
            if g:
                # Use a shared running group_pnl in ctx.memory
                group_pnls = ctx.memory.setdefault("_group_pnl", {})
                group_pnls[g] = group_pnls.get(g, 0.0) * 0.999 + unreal_dpnl
                if group_pnls[g] < bad_group_pnl:
                    bad_group = True
        memory["_bad_group"] = bad_group

        eff_size = throttle_size if bad_group else size

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(eff_size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(eff_size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        return {"badgroup": int(memory.get("_bad_group", False))} if "_bad_group" in memory else {}
