"""Trend carry market maker V41 — detrend + rolling-window dip-buy signal.

Strategy logic:
  1. Fit a rolling linear regression on the mid price (window = reg_window).
  2. Subtract the predicted trend line from the current mid price to get a
     "detrended" residual.
  3. Maintain a rolling window of the last `rolling_window_size` detrended
     residuals.
  4. BUY (taker) with a fixed size whenever the current detrended price is
     among the `buy_rank_threshold` lowest values in the rolling window
     (i.e. the price is cheap relative to its local trend).
  5. Post a passive maker ask far above fair value to capture any spikes;
     this is the only sell-side logic (no active selling).

Parameters
----------
reg_window            : int   = 200  — look-back for the detrend regression
rolling_window_size   : int   = 100  — rolling window used for rank comparison
buy_rank_threshold    : int   = 5    — buy if rank < this value (bottom-N)
detrend_buy_size      : int   = 20   — fixed quantity per buy signal
detrend_sell_edge     : float = 6.0  — maker ask placed at fair + this edge
detrend_sell_size     : int   = 2    — maker sell quote size
position_target       : int   = 80   — stop buying above this position
"""

from __future__ import annotations

import bisect
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


def _fit_linear(prices: list) -> Tuple[float, float]:
    """OLS linear regression y = slope*x + intercept over prices (x = index)."""
    n = len(prices)
    if n < 2:
        return 0.0, prices[0] if prices else 0.0
    sum_x = n * (n - 1) / 2.0
    sum_x2 = n * (n - 1) * (2 * n - 1) / 6.0
    sum_y = sum(prices)
    sum_xy = sum(i * y for i, y in enumerate(prices))
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0.0:
        return 0.0, sum_y / n
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


class TrendCarryMMV41Strategy(BaseStrategy):
    """Detrend-and-dip-buy strategy for strongly trending instruments."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        # ── Parameters ────────────────────────────────────────────────────
        reg_window = int(self.params.get("reg_window", 200))
        rolling_window_size = int(self.params.get("rolling_window_size", 100))
        buy_rank_threshold = int(self.params.get("buy_rank_threshold", 5))
        detrend_buy_size = int(self.params.get("detrend_buy_size", 20))
        detrend_sell_edge = float(self.params.get("detrend_sell_edge", 6.0))
        detrend_sell_size = int(self.params.get("detrend_sell_size", 2))
        position_target = int(self.params.get("position_target", 80))

        mid = (book.best_bid + book.best_ask) / 2.0

        # ── 1. Update mid history and fit regression ──────────────────────
        mid_hist: list = memory.setdefault("mid_hist", [])
        mid_hist.append(mid)
        if len(mid_hist) > reg_window:
            del mid_hist[:-reg_window]

        slope, intercept = _fit_linear(mid_hist)
        n = len(mid_hist)
        predicted_now = intercept + slope * (n - 1)
        detrended_now = mid - predicted_now

        # ── 2. Update rolling window of detrended values ──────────────────
        detrend_win: list = memory.setdefault("detrend_win", [])
        # Track what was dropped from the window (for sorted-list maintenance)
        if len(detrend_win) >= rolling_window_size:
            oldest = detrend_win[0]
        else:
            oldest = None
        detrend_win.append(detrended_now)
        if len(detrend_win) > rolling_window_size:
            del detrend_win[0]

        # ── 3. Maintain sorted copy for O(log n) rank queries ─────────────
        sorted_win: list = memory.setdefault("sorted_win", [])
        bisect.insort(sorted_win, detrended_now)
        if oldest is not None:
            idx = bisect.bisect_left(sorted_win, oldest)
            if idx < len(sorted_win) and sorted_win[idx] == oldest:
                del sorted_win[idx]

        # ── 4. Rank of current detrended price (0 = cheapest) ─────────────
        # rank = number of elements strictly less than detrended_now
        rank = bisect.bisect_left(sorted_win, detrended_now)

        # ── 5. Buy signal ─────────────────────────────────────────────────
        enough_data = len(detrend_win) >= max(buy_rank_threshold, rolling_window_size // 2)
        if enough_data and rank < buy_rank_threshold and position < position_target:
            available_buy = self.buy_capacity(position)
            qty = min(detrend_buy_size, available_buy)
            if qty > 0:
                orders.append(Order(self.product, book.best_ask, qty))

        # ── 6. Passive maker ask far above fair (harvest spikes) ──────────
        fair = predicted_now  # use the trend line as fair value
        sell_cap = self.sell_capacity(position)
        if sell_cap > 0 and detrend_sell_size > 0:
            ask_price = int(round(fair + detrend_sell_edge))
            ask_price = max(ask_price, book.best_bid + 1)
            qty = min(detrend_sell_size, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_price, -qty))

        # ── Memory logging ────────────────────────────────────────────────
        memory["slope"] = slope
        memory["intercept"] = intercept
        memory["detrended_now"] = round(detrended_now, 4)
        memory["rank"] = rank
        memory["win_size"] = len(detrend_win)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=book.best_bid,
            ask_price=book.best_ask,
            extras={
                "position": position,
                "detrended_now": round(detrended_now, 4),
                "rank": rank,
                "slope": round(slope, 6),
                "predicted_now": round(predicted_now, 2),
                "win_size": len(detrend_win),
                "buy_signal": int(enough_data and rank < buy_rank_threshold and position < position_target),
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if memory.get("intercept") is not None and memory.get("slope") is not None:
            # Export the linear trend as a "fair value" line for the visualizer
            n = len(memory.get("mid_hist", []))
            if n > 0:
                out["Reservation"] = memory["intercept"] + memory["slope"] * (n - 1)
        return out
