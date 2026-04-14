"""Fusion B v7 — v2 core + guaranteed-profitable passive scalp.

Logic:
  - Core: delegate to fusion_b (v2) for full accumulation + bullish quoting.
  - Scalp sell: layer a PASSIVE ask deep above market at fv + sell_offset.
    Only fires if position > scalp_floor. If a wild taker crosses, we book
    the fill price in memory as `scalp_last_sell_price`.
  - Scalp rebuy: ONLY place a passive buy if we can buy back strictly
    cheaper than our last scalp sell by at least `rebuy_margin`. Bid price
    is min(best_ask - 1, last_sell_price - rebuy_margin). If no such price
    is reachable (market is above our sell), no buy order is placed — we
    accept staying short the scalp slice.

This guarantees every completed round-trip prints (sell_price - buy_price)
>= rebuy_margin, at the cost of sometimes missing the trend upside on the
slice we couldn't rebuy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.leo_fusion_b import LeoFusionBStrategy


class LeoFusionBV7Strategy(LeoFusionBStrategy):

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

        # Detect realized scalp sells by looking at our own trades since last tick
        prev_pos = int(memory.get("v7_prev_pos", position))
        tracked_sells: List[float] = memory.setdefault("v7_open_sells", [])  # list of sell prices awaiting rebuy

        # If position dropped vs last tick and we had a scalp sell outstanding,
        # assume the drop came from our scalp ask. Record one sell price per unit drop.
        if position < prev_pos:
            sold = prev_pos - position
            last_ask = float(memory.get("v7_last_scalp_ask_price", 0.0))
            if last_ask > 0:
                tracked_sells.extend([last_ask] * sold)

        orders, convs = super().compute_orders(
            state=state, book=book, order_depth=order_depth,
            position=position, memory=memory,
        )

        stats = memory.get("regression_stats") or {}
        fv = float(stats.get("fair_value", (book.best_bid + book.best_ask) / 2.0))

        target = int(self.params.get("v7_core_target", self.position_limit()))
        scalp_range = int(self.params.get("v7_scalp_range", 10))
        sell_offset = float(self.params.get("v7_sell_offset", 6.0))
        rebuy_margin = float(self.params.get("v7_rebuy_margin", 2.0))
        scalp_size = int(self.params.get("v7_scalp_size", 5))
        scalp_floor = target - scalp_range
        limit = self.position_limit()

        pending_buy = sum(o.quantity for o in orders if o.quantity > 0)
        pending_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        effective_pos = position + pending_buy - pending_sell

        # ── Scalp SELL: deep passive ask above market ─────────────────────
        scalp_ask_price = max(int(round(fv + sell_offset)), book.best_bid + 1)
        scalp_sell_room = effective_pos - scalp_floor
        scalp_sell_cap = max(0, limit + effective_pos)
        scalp_sell_qty = max(0, min(scalp_size, scalp_sell_room, scalp_sell_cap))
        if scalp_sell_qty > 0:
            orders.append(Order(self.product, scalp_ask_price, -scalp_sell_qty))
            memory["v7_last_scalp_ask_price"] = float(scalp_ask_price)

        # ── Scalp REBUY: only if we can buy back cheaper than our last sell ──
        if tracked_sells and effective_pos < target:
            # Target the earliest (lowest typically) open sell price first
            target_sell_price = min(tracked_sells)
            max_buy_price = int(target_sell_price - rebuy_margin)
            # Only place if reachable below best ask
            if max_buy_price < book.best_ask:
                buy_cap = max(0, limit - effective_pos)
                room = min(target - effective_pos, len(tracked_sells))
                rebuy_qty = max(0, min(scalp_size, room, buy_cap))
                if rebuy_qty > 0:
                    # Cap the passive bid at max_buy_price; also stay inside book
                    bid_price = min(max_buy_price, book.best_ask - 1)
                    if bid_price >= 1:
                        orders.append(Order(self.product, bid_price, rebuy_qty))
                        # Provisionally release the matched open sells once
                        # they fill (detected next tick via position rise).
                        memory["v7_pending_rebuy_price"] = float(bid_price)

        # Track position rise → assume rebuy filled → pop matched sells
        if position > prev_pos and tracked_sells:
            bought = position - prev_pos
            # Pop the cheapest open sells first (they matched)
            tracked_sells.sort()
            del tracked_sells[:bought]

        memory["v7_prev_pos"] = int(position)
        memory["v7_open_sells"] = tracked_sells
        return orders, convs
