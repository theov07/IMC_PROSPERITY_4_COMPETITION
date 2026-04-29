"""Inventory-carry MM — pauses inventory-increasing side when current
position would worsen carry.

Pure carry-based throttle without PnL tracking complexity. Detects when
your existing inventory is fighting the recent trend, and stops adding to it.

Logic:
  - Compute trend = current mid - EMA(mid, half_life)
  - If position > 0 AND trend < 0 → LOSING money on long, pause bid
  - If position > 0 AND trend > 0 → MAKING money, full quotes
  - If position < 0 AND trend > 0 → losing on short, pause ask
  - If position < 0 AND trend < 0 → gaining on short, full quotes

This is similar to Tibo's late_flatten but applied tick-by-tick when carry
turns adversarial.

Params:
  maker_size           default 5
  tighten_ticks        default 1
  trend_hl             EMA half life (default 200)
  carry_pause_min_pos  min position to activate (default 3)
  hard_pause_at        default 9
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class InventoryCarryMMStrategy(BaseStrategy):

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
        trend_hl = int(self.params.get("trend_hl", 200))
        carry_min_pos = int(self.params.get("carry_pause_min_pos", 3))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # EMA of mid
        mid = (book.best_bid + book.best_ask) / 2.0
        alpha = 2.0 / (trend_hl + 1.0)
        ema_mid = memory.get("_ema_mid", mid)
        ema_mid = alpha * mid + (1 - alpha) * ema_mid
        memory["_ema_mid"] = ema_mid
        trend = mid - ema_mid
        memory["_trend"] = trend

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # Carry pause
        if abs(position) >= carry_min_pos:
            if position > 0 and trend < 0:
                post_bid = False  # don't add to long when trending down
            elif position < 0 and trend > 0:
                post_ask = False  # don't add to short when trending up

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if "_trend" in memory:
            out["trend"] = round(memory["_trend"], 2)
        return out
