"""Theo round-2 clean generalized v5.

Adds a mirrored downside gap trap on top of v4's sell-gap and reserve logic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.strategies.round_2.theo.theo_best_clean_generalized_v4 import (
    TheoBestCleanGeneralizedV4Strategy,
)


class TheoBestCleanGeneralizedV5Strategy(TheoBestCleanGeneralizedV4Strategy):
    """V5: keep v4 intact and add a mirrored buy-side gap trap."""

    def _buy_gap_trap_quotes(
        self,
        book,
        position: int,
        memory: Dict[str, Any],
        buy_cap: int,
        active_bid_price: int,
        trend_ticks: float,
        gap_rebuy_mode: bool,
    ) -> Tuple[List[Order], List[int]]:
        orders: List[Order] = []
        gap_buy_prices: List[int] = []
        if buy_cap <= 0 or book.best_bid is None:
            memory["buy_gap_trap_active"] = 0
            return orders, gap_buy_prices

        empty_side_shift = int(self.params.get("empty_side_shift", 85))

        buy_gap_trap_fragile_streak = int(memory.get("_buy_gap_trap_fragile_streak", 0))
        buy_gap_trap_clear_streak = int(memory.get("_buy_gap_trap_clear_streak", 0))
        buy_gap_trap_anchor_bid = memory.get("_buy_gap_trap_anchor_bid")
        buy_gap_trap_trough_bid = memory.get("_buy_gap_trap_trough_bid")

        buy_gap_trap_floor_position = int(
            self.params.get(
                "buy_gap_trap_floor_position",
                self._reserve_normal_inventory_cap(),
            )
        )
        buy_gap_trap_arm_streak = int(self.params.get("buy_gap_trap_arm_streak", 2))
        buy_gap_trap_clear_after = int(self.params.get("buy_gap_trap_clear_after", 4))
        buy_gap_trap_min_trend = float(self.params.get("buy_gap_trap_min_trend", 0.0))
        buy_gap_trap_min_gap = int(self.params.get("buy_gap_trap_min_gap", 3))
        buy_gap_trap_top_bid_max = int(self.params.get("buy_gap_trap_top_bid_max", 12))
        buy_gap_trap_max_imbalance = float(self.params.get("buy_gap_trap_max_imbalance", 0.05))
        buy_gap_trap_recent_bid_window = int(self.params.get("buy_gap_trap_recent_bid_window", 12))
        buy_gap_trap_fragile_bid_window = int(self.params.get("buy_gap_trap_fragile_bid_window", 6))
        buy_gap_trap_base_size = int(
            self.params.get(
                "buy_gap_trap_base_size",
                max(1, min(2, self._reserve_inventory_size())),
            )
        )
        buy_gap_trap_premium_size_limit = int(
            self.params.get(
                "buy_gap_trap_premium_size",
                max(0, self._reserve_inventory_size() - buy_gap_trap_base_size),
            )
        )
        buy_gap_trap_premium_streak = int(self.params.get("buy_gap_trap_premium_streak", 2))
        buy_gap_trap_premium_extra = int(self.params.get("buy_gap_trap_premium_extra", 2))

        bid_gap_fragile = len(book.bid_levels) == 1
        if len(book.bid_levels) >= 2:
            bid_gap_fragile = bid_gap_fragile or (
                book.bid_levels[0][0] - book.bid_levels[1][0] >= buy_gap_trap_min_gap
            )
        bid_size_fragile = book.best_bid_volume > 0 and book.best_bid_volume <= buy_gap_trap_top_bid_max
        imbalance_supportive = book.imbalance is None or book.imbalance <= buy_gap_trap_max_imbalance
        bid_side_fragile = bid_gap_fragile or (bid_size_fragile and imbalance_supportive)

        trap_recent_bids = memory.setdefault("_buy_gap_trap_recent_bids", [])
        trap_recent_bids.append(int(book.best_bid))
        if len(trap_recent_bids) > buy_gap_trap_recent_bid_window:
            del trap_recent_bids[:-buy_gap_trap_recent_bid_window]

        trap_fragile_bids = memory.setdefault("_buy_gap_trap_fragile_bids", [])
        if bid_side_fragile:
            trap_fragile_bids.append(int(book.best_bid))
            if len(trap_fragile_bids) > buy_gap_trap_fragile_bid_window:
                del trap_fragile_bids[:-buy_gap_trap_fragile_bid_window]
        else:
            trap_fragile_bids[:] = []

        trap_armable = (
            trend_ticks >= buy_gap_trap_min_trend
            and not gap_rebuy_mode
            and position >= buy_gap_trap_floor_position
            and buy_cap > 0
        )

        if trap_armable and bid_side_fragile:
            buy_gap_trap_fragile_streak += 1
            buy_gap_trap_clear_streak = 0
        elif buy_gap_trap_anchor_bid is not None:
            buy_gap_trap_clear_streak += 1
            buy_gap_trap_fragile_streak = max(0, buy_gap_trap_fragile_streak - 1)
        else:
            buy_gap_trap_fragile_streak = 0
            buy_gap_trap_clear_streak = 0

        if (
            buy_gap_trap_anchor_bid is None
            and trap_armable
            and buy_gap_trap_fragile_streak >= buy_gap_trap_arm_streak
            and trap_recent_bids
        ):
            buy_gap_trap_anchor_bid = max(trap_recent_bids)
            buy_gap_trap_trough_bid = min(trap_fragile_bids) if trap_fragile_bids else int(book.best_bid)

        if buy_gap_trap_anchor_bid is not None:
            if not trap_armable or buy_gap_trap_clear_streak >= buy_gap_trap_clear_after:
                buy_gap_trap_anchor_bid = None
                buy_gap_trap_trough_bid = None
                buy_gap_trap_fragile_streak = 0
                buy_gap_trap_clear_streak = 0
            else:
                if trap_recent_bids:
                    buy_gap_trap_anchor_bid = max(int(buy_gap_trap_anchor_bid), max(trap_recent_bids))
                if trap_fragile_bids:
                    latest_trough = min(trap_fragile_bids)
                    buy_gap_trap_trough_bid = min(
                        int(buy_gap_trap_trough_bid or latest_trough),
                        latest_trough,
                    )

        buy_gap_trap_buy_price = None
        buy_gap_trap_buy_size = 0
        buy_gap_trap_premium_price = None
        buy_gap_trap_premium_size = 0
        buy_gap_trap_active = False
        buy_gap_trap_armed = False

        if buy_gap_trap_anchor_bid is not None:
            buy_gap_trap_armed = True
            candidate_buy_gap_trap = int(buy_gap_trap_anchor_bid) - empty_side_shift
            if candidate_buy_gap_trap < active_bid_price:
                buy_gap_trap_buy_price = candidate_buy_gap_trap
                buy_gap_trap_buy_size = min(buy_cap, buy_gap_trap_base_size)
                buy_gap_trap_active = buy_gap_trap_buy_size > 0

            if (
                buy_gap_trap_trough_bid is not None
                and buy_gap_trap_fragile_streak >= buy_gap_trap_premium_streak
                and buy_cap > buy_gap_trap_buy_size
            ):
                candidate_buy_gap_premium = min(
                    (buy_gap_trap_buy_price or active_bid_price) - buy_gap_trap_premium_extra,
                    int(buy_gap_trap_trough_bid) - empty_side_shift - buy_gap_trap_premium_extra,
                )
                if candidate_buy_gap_premium < (buy_gap_trap_buy_price or active_bid_price):
                    buy_gap_trap_premium_price = candidate_buy_gap_premium
                    buy_gap_trap_premium_size = min(
                        max(0, buy_cap - buy_gap_trap_buy_size),
                        buy_gap_trap_premium_size_limit,
                    )
                    buy_gap_trap_active = buy_gap_trap_active or buy_gap_trap_premium_size > 0

        if buy_gap_trap_buy_size > 0 and buy_gap_trap_buy_price is not None:
            orders.append(Order(self.product, buy_gap_trap_buy_price, buy_gap_trap_buy_size))
            gap_buy_prices.append(buy_gap_trap_buy_price)
        if buy_gap_trap_premium_size > 0 and buy_gap_trap_premium_price is not None:
            orders.append(Order(self.product, buy_gap_trap_premium_price, buy_gap_trap_premium_size))
            gap_buy_prices.append(buy_gap_trap_premium_price)

        memory["_buy_gap_trap_fragile_streak"] = buy_gap_trap_fragile_streak
        memory["_buy_gap_trap_clear_streak"] = buy_gap_trap_clear_streak
        memory["_buy_gap_trap_anchor_bid"] = buy_gap_trap_anchor_bid
        memory["_buy_gap_trap_trough_bid"] = buy_gap_trap_trough_bid
        memory["buy_gap_trap_active"] = int(buy_gap_trap_active)
        memory["buy_gap_trap_armed"] = int(buy_gap_trap_armed)

        return orders, gap_buy_prices

    def compute_orders(
        self,
        state: TradingState,
        book,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders, conversions = super().compute_orders(state, book, order_depth, position, memory)

        if book.best_bid is None or book.best_ask is None:
            return orders, conversions

        buy_cap_remaining = self.buy_capacity(position) - sum(max(order.quantity, 0) for order in orders)
        if buy_cap_remaining <= 0:
            return orders, conversions

        stats = memory.get("regression_stats", {})
        trend_ticks = float(stats.get("trend_ticks", 0.0))
        active_bid_price = int(memory.get("last_bid_price", book.best_bid))
        gap_rebuy_mode = bool(memory.get("gap_rebuy_mode", 0))

        buy_gap_orders, buy_gap_prices = self._buy_gap_trap_quotes(
            book=book,
            position=position,
            memory=memory,
            buy_cap=buy_cap_remaining,
            active_bid_price=active_bid_price,
            trend_ticks=trend_ticks,
            gap_rebuy_mode=gap_rebuy_mode,
        )
        if not buy_gap_orders:
            return orders, conversions

        orders.extend(buy_gap_orders)
        active_gap_buy_quotes = {int(p) for p in memory.get("_active_gap_buy_quotes", [])}
        active_gap_buy_quotes.update(buy_gap_prices)
        memory["_active_gap_buy_quotes"] = sorted(active_gap_buy_quotes)
        memory["_gap_buy_px"] = memory["_active_gap_buy_quotes"]
        return orders, conversions
