"""Regime-aware carry MM for analyst A3.

Goal:
  - Mild/choppy regime: behave like the safer v19-style MM with smaller size
    and a tighter soft inventory cap.
  - Strong-trend regime: unlock the larger v3000 carry MM behavior, but only
    when the trend is large enough to justify it.

This is meant for products like PEBBLES_L / TRANSLATOR_GRAPHITE_MIST where:
  - naive_tight_mm with small size is more robust on weak/choppy days
  - inventory_carry_mm with larger size monetizes strong directional days

Params:
  size_mild                quote size in mild regime (default 3)
  mild_limit               soft inventory cap in mild regime (default 5)
  size_strong              quote size in strong regime (default 5)
  hard_pause_at            hard inventory cap in strong regime (default 9)
  tighten_ticks            quote improvement ticks (default 1)
  trend_hl                 EMA half-life for regime/trend detection (default 120)
  regime_trend_min_abs     |trend| needed to activate strong regime
  carry_pause_min_pos      min pos before pausing same-side carry (default 3)
  carry_trend_min_abs      optional extra threshold for same-side carry pause
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class RegimeCarryMMA3Strategy(BaseStrategy):

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

        size_mild = int(self.params.get("size_mild", 3))
        mild_limit = int(self.params.get("mild_limit", 5))
        size_strong = int(self.params.get("size_strong", 5))
        hard_pause = int(self.params.get("hard_pause_at", 9))
        tighten = int(self.params.get("tighten_ticks", 1))
        trend_hl = int(self.params.get("trend_hl", 120))
        regime_min_abs = float(self.params.get("regime_trend_min_abs", 80.0))
        carry_min_pos = int(self.params.get("carry_pause_min_pos", 3))
        carry_min_abs = float(self.params.get("carry_trend_min_abs", 0.0))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        mid = (book.best_bid + book.best_ask) / 2.0
        alpha = 2.0 / (trend_hl + 1.0)
        ema_mid = memory.get("_ema_mid", mid)
        ema_mid = alpha * mid + (1.0 - alpha) * ema_mid
        memory["_ema_mid"] = ema_mid
        trend = mid - ema_mid
        strong_regime = abs(trend) >= regime_min_abs

        if strong_regime:
            size = size_strong
            post_bid = position < hard_pause
            post_ask = position > -hard_pause
            if abs(position) >= carry_min_pos:
                if position > 0 and trend < -carry_min_abs:
                    post_bid = False
                elif position < 0 and trend > carry_min_abs:
                    post_ask = False
        else:
            size = size_mild
            post_bid = position < mild_limit
            post_ask = position > -mild_limit

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))

        memory["_trend"] = trend
        memory["_strong"] = 1 if strong_regime else 0
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if "_trend" in memory:
            out["trend"] = round(memory["_trend"], 2)
        if "_strong" in memory:
            out["strong"] = float(memory["_strong"])
        return out
