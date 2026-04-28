"""Inventory-aware passive MM for R5 (pos_limit=10).

Improvement over naive_tight_mm:
- Skew quotes when |position| > skew_threshold (more aggressive on unwind side)
- Per-product `tighten_ticks` (auto or configured)
- Optional: pause posting on inventory-increasing side when at limit

Params (all optional, sensible defaults):
  maker_size           : default 5
  tighten_ticks        : default 1
  skew_enabled         : default True
  skew_threshold       : abs position threshold to fire skew (default 5)
  skew_offset          : extra tick on unwind side when skewing (default 1)
  hard_pause_at        : pause inventory-increasing side when |pos| >= this (default 9)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class InventoryAwareMMStrategy(BaseStrategy):
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
        skew_enabled = bool(self.params.get("skew_enabled", True))
        skew_thresh = int(self.params.get("skew_threshold", 5))
        skew_offset = int(self.params.get("skew_offset", 1))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # Inventory skew: when long > threshold → ask more aggressive
        if skew_enabled:
            if position > skew_thresh:
                # Long: skew ask DOWN (more aggressive), bid stays
                ask_p = max(ask_p - skew_offset, book.best_bid + 1)
            elif position < -skew_thresh:
                # Short: skew bid UP (more aggressive)
                bid_p = min(bid_p + skew_offset, book.best_ask - 1)

        # Hard pause: stop posting on inventory-increasing side
        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))

        memory["last_pos"] = position
        return orders, 0
