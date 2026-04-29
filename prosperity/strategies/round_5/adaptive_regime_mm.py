"""Adaptive regime-aware MM — dynamically throttles based on rolling PnL.

Core idea: instead of statically dropping products, MONITOR the rolling
PnL contribution per product. If a product is losing money over the recent
window, throttle aggressively. If profitable, full size.

This is the dynamic counterpart to the static "drop or keep" logic. Adapts
to whichever regime is actually playing out, with no fixed hyperparameters.

Mechanism:
  1. Track per-product rolling PnL (Welford EWMA over last N ticks)
  2. Track inventory carry: position × delta_mid_recent
  3. Compute regime_score = recent_pnl + carry_pnl
  4. If regime_score < bad_threshold: pause inventory-increasing side
  5. If position would worsen carry (long when trending down): pause bid

This is purely passive — no taker. Only side-skipping based on observed regime.

Params:
  maker_size           default 5
  tighten_ticks        default 1
  hard_pause_at        default 9 (pos limit)
  pnl_window           rolling window for PnL/carry tracking (default 500)
  bad_pnl_threshold    cumulative recent PnL below which we throttle (default -200)
  trend_window         EMA half-life for trend detection (default 100)
  trend_carry_thresh   |position * trend| above which we pause same side (default 50)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class AdaptiveRegimeMMStrategy(BaseStrategy):

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
        hard_pause = int(self.params.get("hard_pause_at", 9))
        pnl_window = int(self.params.get("pnl_window", 500))
        bad_pnl = float(self.params.get("bad_pnl_threshold", -200.0))
        trend_hl = int(self.params.get("trend_window", 100))
        trend_carry_thresh = float(self.params.get("trend_carry_thresh", 50.0))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # Compute mid for trend tracking
        mid = (book.best_bid + book.best_ask) / 2.0
        last_mid = memory.get("_last_mid", mid)

        # EMA mid (trend signal)
        alpha_t = 2.0 / (trend_hl + 1.0)
        ema_mid = memory.get("_ema_mid", mid)
        ema_mid = alpha_t * mid + (1 - alpha_t) * ema_mid
        memory["_ema_mid"] = ema_mid
        # Trend = mid - ema = how much current mid above its EMA (positive = uptrend)
        trend = mid - ema_mid

        # Track unrealized PnL change since last tick (mark-to-market on position)
        last_pos = memory.get("_last_pos", 0)
        delta_mid = mid - last_mid
        unreal_dpnl = last_pos * delta_mid  # what we made/lost on existing inventory

        # Rolling PnL EMA (window = pnl_window, alpha = 2/(N+1))
        alpha_p = 2.0 / (pnl_window + 1.0)
        rolling_pnl = memory.get("_rolling_pnl", 0.0)
        rolling_pnl = (1 - alpha_p) * rolling_pnl + unreal_dpnl
        memory["_rolling_pnl"] = rolling_pnl

        # Carry score: position × trend = expected damage if trend continues
        carry_score = position * trend  # positive if position aligned with trend
        memory["_carry_score"] = carry_score

        # Regime detection
        bad_regime = rolling_pnl < bad_pnl
        memory["_bad_regime"] = bad_regime

        # Default: post both sides
        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # Throttle 1: bad regime → reduce size
        effective_size = size
        if bad_regime:
            effective_size = max(1, size // 3)  # reduce to 1/3 size

        # Throttle 2: carry-based pause
        # If position long and trend up → ok, we'll exit at higher price (don't pause)
        # If position long and trend down → DANGER, position is worsening (pause bid)
        # If position short and trend up → DANGER (pause ask)
        # If position short and trend down → ok
        if position > 0 and trend < -trend_carry_thresh / max(abs(position), 1):
            post_bid = False
        elif position < 0 and trend > trend_carry_thresh / max(abs(position), 1):
            post_ask = False

        # Save state
        memory["_last_mid"] = mid
        memory["_last_pos"] = position

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(effective_size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(effective_size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if "_rolling_pnl" in memory:
            out["rpnl"] = round(memory["_rolling_pnl"], 1)
        if "_carry_score" in memory:
            out["carry"] = round(memory["_carry_score"], 1)
        if "_bad_regime" in memory:
            out["bad"] = int(memory["_bad_regime"])
        return out
