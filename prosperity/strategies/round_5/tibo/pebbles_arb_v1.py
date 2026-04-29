"""
PEBBLES Basket-Conservation Strategy — v1

The 5 PEBBLES products obey an exact conservation law:
    L + M + S + XL + XS = 50000  (sum of mid prices, std < 3 ticks)

For each product P, the fair value at any tick is:
    fair_P = 50000 - sum(others_mid)

Trading logic per product:
  • TAKER BUY:  best_ask ≤ fair_value - edge_ticks
  • TAKER SELL: best_bid ≥ fair_value + edge_ticks
  • PASSIVE BID/ASK: quote tightly around fair_value

When only some partner order books are available the strategy falls back to
a simple EWMA-anchored fair value.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, TradingState
from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base import BaseStrategy


class PebblesArbV1(BaseStrategy):
    """Basket-conservation market maker for any of the 5 PEBBLES products."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        limit = int(p.get("position_limit", 10))
        partners: List[str] = list(p["partner_products"])
        sum_target = float(p.get("sum_target", 50000.0))
        edge = float(p.get("edge_ticks", 6.0))
        passive_half = float(p.get("passive_half_spread", 7.0))
        taker_size = int(p.get("taker_size", 10))
        passive_size = int(p.get("passive_size", 5))

        # ── compute partners mid sum ───────────────────────────────────
        partners_sum = 0.0
        available = 0
        for sym in partners:
            od = state.order_depths.get(sym)
            if od is None:
                continue
            pb = list(od.buy_orders.keys())
            pa = list(od.sell_orders.keys())
            if not pb or not pa:
                continue
            partners_sum += (max(pb) + min(pa)) / 2.0
            available += 1

        if available < len(partners):
            # fall back: use last known fair value from EWMA
            mid = book.mid_price
            if mid is None:
                return [], 0
            ewma = memory.get("fair_ewma", mid)
            alpha = float(p.get("ewma_alpha", 0.01))
            ewma = alpha * mid + (1 - alpha) * ewma
            memory["fair_ewma"] = ewma
            fair_value = ewma
        else:
            fair_value = sum_target - partners_sum
            # update EWMA with current fair value for fallback continuity
            alpha = float(p.get("ewma_alpha", 0.01))
            memory["fair_ewma"] = alpha * fair_value + (1 - alpha) * memory.get("fair_ewma", fair_value)

        orders: List[Order] = []
        bb = book.best_bid
        ba = book.best_ask

        buy_room = limit - position
        sell_room = limit + position

        # ── taker BUY ─────────────────────────────────────────────────
        if ba is not None and ba <= fair_value - edge and buy_room > 0:
            qty = min(taker_size, buy_room)
            orders.append(Order(self.product, ba, qty))
            buy_room -= qty

        # ── taker SELL ────────────────────────────────────────────────
        if bb is not None and bb >= fair_value + edge and sell_room > 0:
            qty = min(taker_size, sell_room)
            orders.append(Order(self.product, bb, -qty))
            sell_room -= qty

        # ── passive BID ───────────────────────────────────────────────
        if buy_room > 0:
            bid_px = int(fair_value - passive_half)
            if bb is not None:
                bid_px = max(bid_px, bb)
            orders.append(Order(self.product, bid_px, min(passive_size, buy_room)))

        # ── passive ASK ───────────────────────────────────────────────
        if sell_room > 0:
            ask_px = int(fair_value + passive_half) + 1
            if ba is not None:
                ask_px = min(ask_px, ba)
            orders.append(Order(self.product, ask_px, -min(passive_size, sell_room)))

        return orders, 0
