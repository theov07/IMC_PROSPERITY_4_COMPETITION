"""Fusion B + gap exploit + gap_scout/gap_rebuy — ported from Theo's TestTheoStrategy.

Builds on leo_fusion_b_gap (which already has thin-L1 gap exploit) by adding
two more passive/active modules that catch ephemeral OB dislocations:

  1. gap_scout   — passive sell at anchor_ask + empty_side_shift during
                   specific time windows when the ask side is fragile.
                   Fires only when bullish, position >= gap_scout_floor_position,
                   L1 ask is alone or L1->L2 gap >= gap_scout_min_gap, and
                   state.timestamp falls inside one of three configurable windows.
  2. gap_rebuy   — after a scout sell executed (tracked via _last_gap_sell_ts),
                   sweep asks aggressively with a much looser buy_edge while
                   position is below inv_target and market has dropped by at
                   least gap_rebuy_min_discount from the scout sell price.

Modular style mirrors mm_first_v2: each module is a private helper that
takes the current order list and returns an updated one.

Params:
  empty_side_shift               : sell premium when posting scout sell (default 85)
  gap_scout_floor_position       : min position to enable scout (default 78)
  gap_scout_min_gap              : min L1->L2 ask gap to consider side fragile (default 3)
  gap_scout_size_limit           : max scout sell size (default 5)
  gap_scout_recent_ask_window    : rolling window size for anchor ask (default 6)
  gap_scout_{early,mid,late}_{start,end}_ts : 3 time windows (tune per round!)
  gap_rebuy_window               : ticks after scout sell during which rebuy active (default 2500)
  gap_rebuy_min_discount         : min price drop from scout sell to trigger rebuy (default 20.0)
  gap_rebuy_buy_edge             : taker buy_edge override when rebuying (default -10.0)
  gap_rebuy_take_cap             : max aggressive take qty per tick during rebuy (default 8)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.leo_fusion_b_gap import LeoFusionBGapStrategy


class LeoFusionBScoutStrategy(LeoFusionBGapStrategy):

    # ── memory helpers ─────────────────────────────────────────────

    def _track_recent_best_asks(
        self,
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> None:
        """Maintain rolling window of recent best asks for scout anchor."""
        if book.best_ask is None:
            return
        window = int(self.params.get("gap_scout_recent_ask_window", 6))
        recent = memory.setdefault("_recent_best_asks", [])
        recent.append(int(book.best_ask))
        if len(recent) > window:
            del recent[:-window]

    def _is_bullish(self, memory: Dict[str, Any]) -> bool:
        """Read bullish flag stored by parent compute_orders."""
        return bool(memory.get("bullish", 0))

    def _inv_target(self, memory: Dict[str, Any]) -> int:
        return int(memory.get("inv_target", 0))

    # ── gap_scout: passive sell at big premium ────────────────────

    def _gap_scout_sell(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        memory: Dict[str, Any],
        current_orders: List[Order],
    ) -> List[Order]:
        """Post a passive sell at min(recent_best_asks) + empty_side_shift
        when the ask side is fragile during a configured time window.
        """
        floor_pos = int(self.params.get("gap_scout_floor_position", 78))
        if not self._is_bullish(memory) or position < floor_pos:
            return current_orders

        sell_cap = self.sell_capacity(position)
        # Subtract any sells already queued this tick to respect position limit
        for o in current_orders:
            if o.quantity < 0:
                sell_cap += o.quantity  # quantity negative
        if sell_cap <= 0:
            return current_orders

        if not book.ask_levels:
            return current_orders
        min_gap = int(self.params.get("gap_scout_min_gap", 3))
        ask_fragile = len(book.ask_levels) == 1
        if len(book.ask_levels) >= 2:
            ask_fragile = ask_fragile or (
                book.ask_levels[1][0] - book.ask_levels[0][0] >= min_gap
            )
        if not ask_fragile:
            return current_orders

        ts = int(state.timestamp)
        in_window = (
            int(self.params.get("gap_scout_early_start_ts", 3600))
            <= ts
            <= int(self.params.get("gap_scout_early_end_ts", 8500))
            or int(self.params.get("gap_scout_mid_start_ts", 56500))
            <= ts
            <= int(self.params.get("gap_scout_mid_end_ts", 57500))
            or int(self.params.get("gap_scout_late_start_ts", 143000))
            <= ts
            <= int(self.params.get("gap_scout_late_end_ts", 145000))
        )
        if not in_window:
            return current_orders

        recent = memory.get("_recent_best_asks", [])
        if not recent:
            return current_orders

        empty_side_shift = int(self.params.get("empty_side_shift", 85))
        anchor_ask = min(recent)
        candidate_price = anchor_ask + empty_side_shift

        # Only post if above any existing sell price this tick (don't cannibalise)
        existing_sell_prices = [o.price for o in current_orders if o.quantity < 0]
        if existing_sell_prices and candidate_price <= max(existing_sell_prices):
            return current_orders

        size_limit = int(self.params.get("gap_scout_size_limit", 5))
        qty = min(sell_cap, size_limit, max(0, position - floor_pos + 1))
        if qty <= 0:
            return current_orders

        memory["_last_gap_sell_ts"] = ts
        memory["_last_gap_sell_price"] = candidate_price
        memory["gap_scout_active"] = 1
        return current_orders + [Order(self.product, candidate_price, -qty)]

    # ── gap_rebuy: aggressive taker after scout sell ──────────────

    def _gap_rebuy_buy(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
        current_orders: List[Order],
    ) -> List[Order]:
        """After a scout sell executed, buy back aggressively if the book
        dropped by at least gap_rebuy_min_discount from the scout price.
        """
        if not self._is_bullish(memory):
            return current_orders

        last_sell_ts = int(memory.get("_last_gap_sell_ts", -10**9))
        last_sell_price = memory.get("_last_gap_sell_price")
        if last_sell_price is None or book.best_ask is None:
            return current_orders

        window = int(self.params.get("gap_rebuy_window", 2500))
        age = int(state.timestamp) - last_sell_ts
        if age < 0 or age > window:
            return current_orders

        min_discount = float(self.params.get("gap_rebuy_min_discount", 20.0))
        discount = float(last_sell_price) - float(book.best_ask)
        if discount < min_discount:
            return current_orders

        inv_target = self._inv_target(memory)
        if position >= inv_target:
            return current_orders

        # Compute remaining buy capacity minus already queued buys
        buy_cap = self.buy_capacity(position)
        for o in current_orders:
            if o.quantity > 0:
                buy_cap -= o.quantity
        if buy_cap <= 0:
            return current_orders

        rebuy_edge = float(self.params.get("gap_rebuy_buy_edge", -10.0))
        take_cap = min(buy_cap, int(self.params.get("gap_rebuy_take_cap", 8)))
        room = max(0, inv_target - position)
        take_cap = min(take_cap, room)
        if take_cap <= 0:
            return current_orders

        # Use fair value from parent's stored regression stats if available
        fv_ref = memory.get("regression_stats", {}).get("fair_value")
        if fv_ref is None:
            fv_ref = float(book.best_ask)

        extra: List[Order] = []
        queued_ask_qty: Dict[int, int] = {}
        for o in current_orders:
            if o.quantity > 0:
                queued_ask_qty[o.price] = queued_ask_qty.get(o.price, 0) + o.quantity

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > float(fv_ref) - rebuy_edge:
                break
            if take_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_p] - queued_ask_qty.get(ask_p, 0)
            if available <= 0:
                continue
            qty = min(available, take_cap)
            extra.append(Order(self.product, ask_p, qty))
            take_cap -= qty

        memory["gap_rebuy_mode"] = 1
        memory["gap_rebuy_discount"] = discount
        return current_orders + extra

    # ── hold_sell: 1 unit passive at best_ask when full long ──────

    def _hold_sell(
        self,
        book: BookSnapshot,
        position: int,
        memory: Dict[str, Any],
        current_orders: List[Order],
    ) -> List[Order]:
        """When saturated long and bullish, post a small passive sell at
        best_ask + offset to scrape ticks without unwinding the core position.
        """
        if not self._is_bullish(memory) or book.best_ask is None:
            return current_orders
        size = int(self.params.get("hold_sell_size", 1))
        if size <= 0:
            return current_orders
        limit = self.position_limit()
        if position < limit - size + 1:
            return current_orders

        sell_cap = self.sell_capacity(position)
        for o in current_orders:
            if o.quantity < 0:
                sell_cap += o.quantity
        if sell_cap <= 0:
            return current_orders

        offset = int(self.params.get("hold_sell_offset", 0))
        price = int(book.best_ask) + offset
        qty = min(size, sell_cap)

        existing_sell_prices = [o.price for o in current_orders if o.quantity < 0]
        if price in existing_sell_prices:
            return current_orders
        return current_orders + [Order(self.product, price, -qty)]

    # ── entry point ───────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        self._track_recent_best_asks(book, memory)

        orders, conv = super().compute_orders(
            state, book, order_depth, position, memory,
        )

        if book.best_bid is None or book.best_ask is None:
            return orders, conv

        orders = self._gap_rebuy_buy(
            state, book, order_depth, position, memory, orders,
        )
        orders = self._gap_scout_sell(
            state, book, position, memory, orders,
        )
        orders = self._hold_sell(book, position, memory, orders)
        return orders, conv
