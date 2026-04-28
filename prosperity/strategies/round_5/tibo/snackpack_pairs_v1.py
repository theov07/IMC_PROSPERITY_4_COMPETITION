"""
SNACKPACK Conservation Pairs Strategy — v1

Two products move with return correlation ~-0.92 because they share a common
pool: CHOCOLATE + VANILLA ≈ 20000 (observed sum std < 80 over 3 days).

Each product instance looks at its partner's current mid price to derive a
fair value via the conservation identity:
    fair_self = sum_target - partner_mid

Trading logic (symmetric for both products):
  • TAKER BUY:  best_ask ≤ fair_value - edge_ticks        (underpriced)
  • TAKER SELL: best_bid ≥ fair_value + edge_ticks        (overpriced)
  • PASSIVE BID: fair_value - passive_half_spread          (always)
  • PASSIVE ASK: fair_value + passive_half_spread          (always)

Positions are capped at ±position_limit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, TradingState
from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base import BaseStrategy


class SnackpackPairsV1(BaseStrategy):
    """Conservation-law pairs MM for CHOCOLATE-VANILLA (or any antipodal pair)."""

    # ──────────────────────────────────────────────────────────────────
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
        partner = str(p["partner_product"])
        sum_target = float(p.get("sum_target", 20000.0))
        edge = float(p.get("edge_ticks", 8.0))
        passive_half = float(p.get("passive_half_spread", 8.0))
        taker_size = int(p.get("taker_size", 10))
        passive_size = int(p.get("passive_size", 5))

        # ── partner mid price ──────────────────────────────────────────
        partner_depth = state.order_depths.get(partner)
        if partner_depth is None:
            return [], 0

        pb = list(partner_depth.buy_orders.keys())
        pa = list(partner_depth.sell_orders.keys())
        if not pb or not pa:
            return [], 0
        partner_mid = (max(pb) + min(pa)) / 2.0

        fair_value = sum_target - partner_mid

        orders: List[Order] = []
        bb = book.best_bid
        ba = book.best_ask

        buy_room = limit - position
        sell_room = limit + position

        # ── taker BUY when ask ≤ fair - edge ──────────────────────────
        if ba is not None and ba <= fair_value - edge and buy_room > 0:
            qty = min(taker_size, buy_room)
            orders.append(Order(self.product, ba, qty))
            buy_room -= qty

        # ── taker SELL when bid ≥ fair + edge ─────────────────────────
        if bb is not None and bb >= fair_value + edge and sell_room > 0:
            qty = min(taker_size, sell_room)
            orders.append(Order(self.product, bb, -qty))
            sell_room -= qty

        # ── passive BID ────────────────────────────────────────────────
        if buy_room > 0:
            bid_px = int(fair_value - passive_half)
            # don't post below current best_bid - 1 (stay competitive)
            if bb is not None:
                bid_px = max(bid_px, bb)
            orders.append(Order(self.product, bid_px, min(passive_size, buy_room)))

        # ── passive ASK ────────────────────────────────────────────────
        if sell_room > 0:
            ask_px = int(fair_value + passive_half) + 1
            if ba is not None:
                ask_px = min(ask_px, ba)
            orders.append(Order(self.product, ask_px, -min(passive_size, sell_room)))

        return orders, 0
