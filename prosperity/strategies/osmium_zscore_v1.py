"""Osmium z-score target-position strategy.

Hypothesis: OSMIUM is cyclical around a slow-moving mean. Instead of a symmetric
MM we drive a *target position* from a rolling z-score:

    z = (mid - mean) / std
    target_pos = clamp(-z_k * z, -limit, limit)

Negative z (price crashed) → long target; positive z (price spiked) → short.
We reach the target with aggressive takes when the gap is large, then post
passive quotes at best ± 1 on the side that still needs size.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class OsmiumZScoreV1Strategy(BaseStrategy):

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

        limit = int(self.position_limit())
        mid = (book.best_bid + book.best_ask) / 2.0

        window = int(self.params.get("z_window", 200))
        z_k = float(self.params.get("z_k", 40.0))
        z_entry = float(self.params.get("z_entry", 0.3))
        take_gap = int(self.params.get("take_gap", 5))
        post_size = int(self.params.get("post_size", 20))
        min_std = float(self.params.get("min_std", 0.5))

        buf: List[float] = memory.get("mid_buf")
        if buf is None:
            buf = []
            memory["mid_buf"] = buf
        buf.append(mid)
        if len(buf) > window:
            del buf[: len(buf) - window]

        if len(buf) < max(20, window // 4):
            return [], 0

        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / n
        std = max(var ** 0.5, min_std)

        z = (mid - mean) / std

        if abs(z) < z_entry:
            target = 0
        else:
            target = int(round(-z_k * z))
            if target > limit:
                target = limit
            elif target < -limit:
                target = -limit

        orders: List[Order] = []
        take_enabled = bool(self.params.get("take_enabled", False))

        if take_enabled:
            delta = target - position
            if delta >= take_gap:
                need = delta
                for ask_p in sorted(order_depth.sell_orders):
                    avail = -order_depth.sell_orders[ask_p]
                    qty = min(avail, need)
                    if qty <= 0:
                        break
                    orders.append(Order(self.product, ask_p, qty))
                    need -= qty
                    if need <= 0:
                        break
            elif delta <= -take_gap:
                need = -delta
                for bid_p in sorted(order_depth.buy_orders, reverse=True):
                    avail = order_depth.buy_orders[bid_p]
                    qty = min(avail, need)
                    if qty <= 0:
                        break
                    orders.append(Order(self.product, bid_p, -qty))
                    need -= qty
                    if need <= 0:
                        break

        filled_buy = sum(o.quantity for o in orders if o.quantity > 0)
        filled_sell = -sum(o.quantity for o in orders if o.quantity < 0)
        pos_after = position + filled_buy - filled_sell
        residual = target - pos_after

        bid_price = book.best_bid + 1 if book.best_ask - book.best_bid >= 2 else book.best_bid
        ask_price = book.best_ask - 1 if book.best_ask - book.best_bid >= 2 else book.best_ask

        if residual > 0:
            cap = limit - pos_after
            qty = min(post_size, cap, residual + post_size)
            if qty > 0:
                orders.append(Order(self.product, bid_price, qty))
        elif residual < 0:
            cap = limit + pos_after
            qty = min(post_size, cap, -residual + post_size)
            if qty > 0:
                orders.append(Order(self.product, ask_price, -qty))

        return orders, 0
