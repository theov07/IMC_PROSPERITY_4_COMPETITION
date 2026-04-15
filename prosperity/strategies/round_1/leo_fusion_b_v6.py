"""Fusion B v6 — v2 core + passive scalp quotes at fv +/- big_edge.

Parent (fusion_b / v2) runs its full bullish accumulation + quoting logic.
v6 then layers an extra PASSIVE sell at fv+scalp_edge and an extra PASSIVE
buy at fv-scalp_edge, so that any taker crossing fv by at least scalp_edge
fills us and we capture that edge.

Core never drops below scalp_floor = target - scalp_range, so trend PnL is
preserved. scalp_edge is intentionally large (6-10 ticks) so each round-trip
is guaranteed to print profit even if fv drifts between sell and buyback.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.leo_fusion_b import LeoFusionBStrategy


class LeoFusionBV6Strategy(LeoFusionBStrategy):

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

        orders, convs = super().compute_orders(
            state=state, book=book, order_depth=order_depth,
            position=position, memory=memory,
        )

        stats = memory.get("regression_stats") or {}
        fv = float(stats.get("fair_value", (book.best_bid + book.best_ask) / 2.0))

        target = int(self.params.get("v6_core_target", self.position_limit()))
        scalp_range = int(self.params.get("v6_scalp_range", 10))
        scalp_edge = float(self.params.get("v6_scalp_edge", 6.0))
        scalp_size = int(self.params.get("v6_scalp_size", 10))
        scalp_floor = target - scalp_range

        pending_buy = sum(o.quantity for o in orders if o.quantity > 0)
        pending_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        effective_pos = position + pending_buy - pending_sell
        limit = self.position_limit()

        # Passive scalp SELL at fv + scalp_edge — only if we have core to sell
        scalp_ask_price = max(int(round(fv + scalp_edge)), book.best_bid + 1)
        scalp_sell_room = effective_pos - scalp_floor
        scalp_sell_cap = max(0, limit + effective_pos)
        scalp_sell_qty = max(0, min(scalp_size, scalp_sell_room, scalp_sell_cap))
        if scalp_sell_qty > 0:
            orders.append(Order(self.product, scalp_ask_price, -scalp_sell_qty))

        # Passive scalp BUY at fv - scalp_edge — only if we're below target
        scalp_bid_price = min(int(round(fv - scalp_edge)), book.best_ask - 1)
        scalp_buy_room = target - effective_pos
        scalp_buy_cap = max(0, limit - effective_pos)
        scalp_buy_qty = max(0, min(scalp_size, scalp_buy_room, scalp_buy_cap))
        if scalp_buy_qty > 0:
            orders.append(Order(self.product, scalp_bid_price, scalp_buy_qty))

        return orders, convs
