"""Real MM strategy for R5 — combines best practices from previous rounds.

Inspired by Tibo's mm_first_v4_combo (R3), adapted to R5's pos_limit=10.

Features:
  1. Penny-improve quotes (best_bid+1 / best_ask-1)
  2. Inventory-adaptive sizing: shrink BID size when long, ASK size when short
  3. Inventory-skew: when |pos| > skew_thresh, push aggressive on unwind side
  4. Carry-aware: if |pos|>=3 and trend opposes position, pause inv-increasing side
  5. Hard pause at limit boundary (pos >= 9 → no bid, pos <= -9 → no ask)
  6. NO timestamp-based logic (no late_flatten — overfit per Léo's feedback)

Params:
  maker_size              base size (default 5)
  tighten_ticks           default 1
  inv_skew_thresh         |pos| at which to skew price (default 5)
  inv_skew_offset         extra ticks aggressive on unwind (default 1)
  size_inv_factor         shrink factor: bid_size = size * (1 - pos/limit) (default 1.0 = full)
  trend_hl                EMA half-life for trend detect (default 200)
  carry_pause_min_pos     |pos| threshold for carry pause (default 3)
  hard_pause_at           default 9
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class RealMMStrategy(BaseStrategy):

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
        inv_skew_thresh = int(self.params.get("inv_skew_thresh", 5))
        inv_skew_offset = int(self.params.get("inv_skew_offset", 1))
        size_inv_factor = float(self.params.get("size_inv_factor", 1.0))
        trend_hl = int(self.params.get("trend_hl", 200))
        carry_min_pos = int(self.params.get("carry_pause_min_pos", 3))
        hard_pause = int(self.params.get("hard_pause_at", 9))
        limit = self.position_limit()

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # 1. Trend detection
        mid = (book.best_bid + book.best_ask) / 2.0
        alpha = 2.0 / (trend_hl + 1.0)
        ema_mid = memory.get("_ema_mid", mid)
        ema_mid = alpha * mid + (1 - alpha) * ema_mid
        memory["_ema_mid"] = ema_mid
        trend = mid - ema_mid

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # 2. Inventory price skew (push aggressive on unwind side when |pos| > thresh)
        if abs(position) > inv_skew_thresh:
            if position > 0:
                # Long: push ASK aggressive (sell faster)
                ask_p = max(ask_p - inv_skew_offset, book.best_bid + 1)
            else:
                # Short: push BID aggressive
                bid_p = min(bid_p + inv_skew_offset, book.best_ask - 1)

        # 3. Carry-aware pause (don't add to losing position)
        if abs(position) >= carry_min_pos:
            if position > 0 and trend < 0:
                post_bid = False
            elif position < 0 and trend > 0:
                post_ask = False

        # 4. Inventory-adaptive sizing (shrink size on inv-increasing side)
        # bid_size = size * (1 - position/limit) so when long → smaller bid
        if size_inv_factor > 0 and limit > 0:
            bid_size = max(1, int(size * (1.0 - size_inv_factor * position / limit)))
            ask_size = max(1, int(size * (1.0 + size_inv_factor * position / limit)))
        else:
            bid_size = ask_size = size

        memory["_trend"] = trend

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(bid_size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(ask_size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if "_trend" in memory:
            out["trend"] = round(memory["_trend"], 2)
        return out
