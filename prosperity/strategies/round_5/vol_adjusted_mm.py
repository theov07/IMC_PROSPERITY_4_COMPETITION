"""Volatility-adjusted MM — size scales inversely with realized vol.

For high-vol products: smaller size (less inventory risk per fill).
For low-vol products: larger size (more spread captured).

The size is computed at config time from precomputed product std.
This is a simple wrapper around naive_tight_mm with size = round(base_size * scale)
where scale = vol_ref / vol_product (clipped).

Params:
  maker_size           base size at vol_ref (default 5)
  vol_ref              reference std (default 600 — average R5 product std)
  vol_clip_min         min size cap (default 2)
  vol_clip_max         max size cap (default 8)
  product_std          actual std of this product (computed offline)
  tighten_ticks        default 1
  hard_pause_at        default 9
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class VolAdjustedMMStrategy(BaseStrategy):

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

        base_size = int(self.params.get("maker_size", 5))
        vol_ref = float(self.params.get("vol_ref", 600.0))
        vol_clip_min = int(self.params.get("vol_clip_min", 2))
        vol_clip_max = int(self.params.get("vol_clip_max", 8))
        product_std = float(self.params.get("product_std", vol_ref))
        tighten = int(self.params.get("tighten_ticks", 1))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        # Size scaling: vol_ref / product_std (high vol → small size, low vol → large size)
        scale = vol_ref / max(product_std, 1.0)
        size = int(round(base_size * scale))
        size = max(vol_clip_min, min(vol_clip_max, size))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        return {}
