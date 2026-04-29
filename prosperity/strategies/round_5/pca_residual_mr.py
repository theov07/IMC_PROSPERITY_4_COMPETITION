"""PCA-residual mean-reversion MM.

For products with strong negative AR1 of PC1-residual (notably ROBOT_DISHES
with AR1_resid=-0.22), trade the residual mean reversion via passive MM
with adaptive bid/ask placement.

Logic:
  - Read SharedR5Context.product_z(self) and group_index(group)
  - Compute residual = z(self) - β × z(group)  (proxy for PC1-residual)
  - If residual highly positive (product rich vs group factor): skew ASK aggressive
  - If residual highly negative: skew BID aggressive
  - Default tight passive MM

This is a refined version of basket_mm that uses regression coefficient
instead of simple subtraction for the partner-z.

Params:
  maker_size           default 5
  tighten_ticks        default 1
  beta                 regression coefficient (default 1.0)
  z_window             rolling window for product z (default 200)
  resid_thresh         abs residual threshold for skew (default 1.5)
  skew_offset          extra ticks to skew (default 1)
  hard_pause_at        default 9
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy
from prosperity.baskets.groups import group_of


class PCAResidualMRStrategy(BaseStrategy):

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
        beta = float(self.params.get("beta", 1.0))
        z_window = int(self.params.get("z_window", 200))
        resid_thresh = float(self.params.get("resid_thresh", 1.5))
        skew_offset = int(self.params.get("skew_offset", 1))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # Read shared context
        ctx = memory.get("_ctx")
        residual = 0.0
        if ctx is not None:
            zp = ctx.product_z(self.product)
            g = group_of(self.product)
            if g:
                zg = ctx.group_zscore(g, window=z_window)
                residual = zp - beta * zg
        memory["_residual"] = residual

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # Skew based on residual
        if residual > resid_thresh:
            # Product rich vs group → expect to revert down → skew ASK aggressive
            ask_p = max(ask_p - skew_offset, book.best_bid + 1)
            # Also: don't load up on bid side (rich, will fall)
            post_bid = False
        elif residual < -resid_thresh:
            # Product cheap vs group → expect to revert up → skew BID aggressive
            bid_p = min(bid_p + skew_offset, book.best_ask - 1)
            post_ask = False

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        r = memory.get("_residual")
        return {"resid": round(r, 3)} if r is not None else {}
