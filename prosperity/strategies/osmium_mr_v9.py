"""Osmium mean-rev V9 — tight-spread imbalance take.

Data analysis on day -2:
    spread<=6 & |I1|>0.2: n=97  E[edge]=+5.18  half_sp=2.8  → +2.36 net
    spread<=8 & |I1|>0.2: n=147 E[edge]=+5.12  half_sp=3.1  → +2.03 net

When the spread compresses AND the L1 imbalance is strong, taking in the
direction of imbalance is net profitable (expected move exceeds half-spread).

V9 keeps the champion logic intact and *adds* a conditional take on those
rare tight-spread + strong-imb ticks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV9Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders, conv = super().compute_orders(state, book, order_depth, position, memory)

        if not bool(self.params.get("tight_take_enabled", True)):
            return orders, conv
        if (
            book.best_bid is None
            or book.best_ask is None
            or not book.bid_levels
            or not book.ask_levels
        ):
            return orders, conv

        spread = book.best_ask - book.best_bid
        max_spread = int(self.params.get("tight_take_max_spread", 8))
        if spread > max_spread:
            return orders, conv

        bid_vol = book.bid_levels[0][1]
        ask_vol = book.ask_levels[0][1]
        total = bid_vol + ask_vol
        if total <= 0:
            return orders, conv

        imb = (bid_vol - ask_vol) / total
        thr = float(self.params.get("tight_take_imb_threshold", 0.2))
        if abs(imb) < thr:
            return orders, conv

        max_qty = int(self.params.get("tight_take_size", 15))
        limit = int(self.position_limit())

        # Existing buy/sell amounts in the super() orders
        existing_buy = sum(o.quantity for o in orders if o.quantity > 0)
        existing_sell = -sum(o.quantity for o in orders if o.quantity < 0)

        if imb > 0:
            # Price expected up → TAKE asks (buy aggressive)
            room = limit - (position + existing_buy)
            if room <= 0:
                return orders, conv
            need = min(max_qty, room)
            for ask_p in sorted(order_depth.sell_orders):
                avail = -order_depth.sell_orders[ask_p]
                qty = min(avail, need)
                if qty <= 0:
                    break
                orders.append(Order(self.product, ask_p, qty))
                need -= qty
                if need <= 0:
                    break
        else:
            room = limit + (position - existing_sell)
            if room <= 0:
                return orders, conv
            need = min(max_qty, room)
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                avail = order_depth.buy_orders[bid_p]
                qty = min(avail, need)
                if qty <= 0:
                    break
                orders.append(Order(self.product, bid_p, -qty))
                need -= qty
                if need <= 0:
                    break

        return orders, conv
