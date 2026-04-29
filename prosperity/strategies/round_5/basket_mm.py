"""Basket-aware MM for R5: passive penny-improve + skew driven by group z-score.

Concept (reading the impulse-response analysis):
  - Strong inter-group impulse only fires from SNACKPACK shocks (lag=1, mu=-0.3sigma)
  - Within-group cohesion is high on LEVELS for some groups -> a member's relative
    position vs its group index is informative (mean-reversion within group)

Strategy:
  1. Default: tight passive MM (best_bid+1 / best_ask-1)
  2. If product z-score vs group index > pull_threshold -> skew ASK aggressive
     (the product is rich relative to peers -> sell harder)
  3. If product z-score vs group index < -pull_threshold -> skew BID aggressive
     (cheap vs peers -> buy harder)
  4. If group itself is at extreme z (group_z > group_pull_threshold) -> hard pause
     on the inventory-increasing side (don't accumulate on the wrong side of a
     macro move).

Reads from `memory["_ctx"]` (SharedR5Context) injected by the Trader.run().
Falls back gracefully to plain naive_tight_mm if ctx absent.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy
from prosperity.baskets.groups import group_of


class BasketAwareMMStrategy(BaseStrategy):
    """Passive MM aware of group-level signals.

    Params:
      maker_size              : default 5
      tighten_ticks           : default 1
      pull_threshold          : abs |z(product) - z(group)| beyond which we skew (default 1.0)
      pull_skew_offset        : extra ticks aggressively quoted (default 1)
      group_pull_threshold    : abs group z beyond which we hard-pause inv-increasing side (default 2.0)
      hard_pause_at           : per-product hard pause |pos| (default 9)
    """

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
        pull_thresh = float(self.params.get("pull_threshold", 1.0))
        pull_skew = int(self.params.get("pull_skew_offset", 1))
        group_thresh = float(self.params.get("group_pull_threshold", 2.0))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        ctx = memory.get("_ctx")
        product_z = 0.0
        group_z = 0.0
        if ctx is not None:
            product_z = ctx.product_z(self.product)
            g = group_of(self.product)
            if g:
                group_z = ctx.group_zscore(g, window=200)

        memory["_pz"] = product_z
        memory["_gz"] = group_z

        # === Within-group skew (relative to group index) ===
        # If product z > group z + threshold -> product is rich vs peers -> ask aggressive
        rel_z = product_z - group_z
        if rel_z > pull_thresh:
            ask_p = max(ask_p - pull_skew, book.best_bid + 1)
        elif rel_z < -pull_thresh:
            bid_p = min(bid_p + pull_skew, book.best_ask - 1)

        # === Group hard-pause on macro move ===
        post_bid = position < hard_pause
        post_ask = position > -hard_pause
        if group_z > group_thresh:
            # Group very rich -> stop loading up on bid
            post_bid = False
        elif group_z < -group_thresh:
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
        out = {}
        if "_pz" in memory:
            out["pz"] = round(memory["_pz"], 3)
        if "_gz" in memory:
            out["gz"] = round(memory["_gz"], 3)
        return out
