"""
AR1 Mean-Reversion Strategy — v1

Some products exhibit significant tick-to-tick negative autocorrelation (AR1 < 0).
When a large one-tick move occurs, the NEXT tick statistically reverts.

Signals (all taker):
  • If mid_return[t] > entry_threshold : SELL at bid[t+1] (expect reversion down)
  • If mid_return[t] < -entry_threshold: BUY  at ask[t+1] (expect reversion up)

Position management:
  • Hard cap at ±position_limit; signal must have room to trade
  • No passive MM — pure signal-driven taker strategy
  • Optional: flat the position after exit_ticks to avoid stale holds

Products with measurable AR1 edge (verified on 3-day backtest data):
  ROBOT_DISHES      AR1=-0.232  spread=7.4   thresh=15-20 is profitable
  ROBOT_IRONING     AR1=-0.125  spread=6.4   thresh=20 marginally profitable
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, TradingState
from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base import BaseStrategy


class AR1MeanRevV1(BaseStrategy):
    """Tick-to-tick mean-reversion strategy using the AR1 signal."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        limit = int(p.get("position_limit", 10))
        entry_thresh = float(p.get("entry_threshold", 20.0))
        taker_size = int(p.get("taker_size", 10))
        exit_ticks = int(p.get("exit_ticks", 0))    # 0 = hold until reverse signal
        passive_size = int(p.get("passive_size", 0))  # optional passive MM alongside

        mid = book.mid_price
        if mid is None:
            return [], 0

        prev_mid = memory.get("prev_mid")
        memory["prev_mid"] = mid

        if prev_mid is None:
            return [], 0

        ret = mid - prev_mid  # this tick's return
        orders: List[Order] = []
        bb = book.best_bid
        ba = book.best_ask

        buy_room = limit - position
        sell_room = limit + position

        # ── taker SELL: large up-move → expect reversion ─────────────────
        if ret >= entry_thresh and sell_room > 0 and bb is not None:
            qty = min(taker_size, sell_room)
            orders.append(Order(self.product, bb, -qty))
            sell_room -= qty

        # ── taker BUY: large down-move → expect reversion ────────────────
        elif ret <= -entry_thresh and buy_room > 0 and ba is not None:
            qty = min(taker_size, buy_room)
            orders.append(Order(self.product, ba, qty))
            buy_room -= qty

        # ── exit stale positions after exit_ticks ────────────────────────
        if exit_ticks > 0:
            ticks_held = memory.get("ticks_held", 0)
            if position != 0:
                ticks_held += 1
                if ticks_held >= exit_ticks:
                    if position > 0 and bb is not None and sell_room > 0:
                        orders.append(Order(self.product, bb, -min(position, sell_room)))
                    elif position < 0 and ba is not None and buy_room > 0:
                        orders.append(Order(self.product, ba, min(-position, buy_room)))
                    ticks_held = 0
            else:
                ticks_held = 0
            memory["ticks_held"] = ticks_held

        # ── optional passive MM alongside (narrow spread) ─────────────────
        if passive_size > 0:
            passive_half = float(p.get("passive_half_spread", 4.0))
            if buy_room > 0 and bb is not None:
                orders.append(Order(self.product, bb + 1, min(passive_size, buy_room)))
            if sell_room > 0 and ba is not None:
                orders.append(Order(self.product, ba - 1, -min(passive_size, sell_room)))

        return orders, 0
