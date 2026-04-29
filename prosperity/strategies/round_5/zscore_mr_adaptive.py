"""Z-score adaptive mean-reversion MM with regime detection.

For mean-reverting products (high rev_ratio), this strategy:
  1. Computes rolling z of mid
  2. Posts passive MM by default
  3. When |z| > entry_thresh, skews quotes to fade the move (mean-rev expectation)
  4. ALSO adapts: if rolling PnL bad, throttle (regime detection)

Designed for products that exhibit reversion (UV_VISOR_YELLOW rev_ratio=9.6)
but with safety overlay for regime change.

Params:
  maker_size           default 5
  tighten_ticks        default 1
  z_window             default 200
  z_entry              skew threshold (default 1.5)
  z_skew               ticks to skew (default 1)
  pnl_window           rolling PnL window (default 500)
  bad_pnl_threshold    pnl threshold for throttle (default -300)
  hard_pause_at        default 9
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class ZScoreMRAdaptiveStrategy(BaseStrategy):

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
        z_window = int(self.params.get("z_window", 200))
        z_entry = float(self.params.get("z_entry", 1.5))
        z_skew = int(self.params.get("z_skew", 1))
        pnl_window = int(self.params.get("pnl_window", 500))
        bad_pnl = float(self.params.get("bad_pnl_threshold", -300.0))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        mid = (book.best_bid + book.best_ask) / 2.0

        # Rolling z (Welford EWMA-like)
        alpha = 2.0 / (z_window + 1.0)
        ema_mid = memory.get("_ema_mid", mid)
        ema_var = memory.get("_ema_var", 1.0)
        ema_mid = alpha * mid + (1 - alpha) * ema_mid
        ema_var = alpha * (mid - ema_mid) ** 2 + (1 - alpha) * ema_var
        memory["_ema_mid"] = ema_mid
        memory["_ema_var"] = ema_var
        std = math.sqrt(max(ema_var, 1e-9))
        z = (mid - ema_mid) / std if std > 1e-6 else 0.0
        memory["_z"] = z

        # Rolling PnL tracking
        last_mid = memory.get("_last_mid", mid)
        last_pos = memory.get("_last_pos", 0)
        delta_mid = mid - last_mid
        unreal_dpnl = last_pos * delta_mid

        alpha_p = 2.0 / (pnl_window + 1.0)
        rolling_pnl = memory.get("_rolling_pnl", 0.0)
        rolling_pnl = (1 - alpha_p) * rolling_pnl + unreal_dpnl
        memory["_rolling_pnl"] = rolling_pnl

        memory["_last_mid"] = mid
        memory["_last_pos"] = position

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        bad_regime = rolling_pnl < bad_pnl
        memory["_bad_regime"] = bad_regime

        # Z-score skew: fade extreme z (mean-rev expectation)
        if z > z_entry:
            # Mid is high → expect drop → skew ASK aggressive (sell aggressively)
            ask_p = max(ask_p - z_skew, book.best_bid + 1)
            # Also pause bid (don't load up at peak)
            if z > z_entry * 1.5:
                post_bid = False
        elif z < -z_entry:
            bid_p = min(bid_p + z_skew, book.best_ask - 1)
            if z < -z_entry * 1.5:
                post_ask = False

        # Adaptive: bad regime → reduce size
        eff_size = size
        if bad_regime:
            eff_size = max(1, size // 2)

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(eff_size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(eff_size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if "_z" in memory:
            out["z"] = round(memory["_z"], 2)
        if "_rolling_pnl" in memory:
            out["rpnl"] = round(memory["_rolling_pnl"], 1)
        return out
