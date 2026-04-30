"""
AR1 Mean-Reversion Strategy — v2 (A2)

Builds on ar1_mean_rev_v1 with two new features:

1. Trend-direction filter
   A slow EMA (trend_ema_hl) tracks the sustained price drift from the
   session-start price. When the market is clearly trending in one direction,
   the strategy only takes AR1 bets that ARE consistent with the trend:

     trend_signal = slow_EMA - session_start

     If trend_signal >  trend_threshold:  market is trending UP
         → suppress new SHORT entries when flat (only take LONG AR1 bets on brief dips)
     If trend_signal < -trend_threshold:  market is trending DOWN
         → suppress new LONG entries when flat  (only take SHORT AR1 bets on brief rallies)
     Otherwise (ranging): original bidirectional AR1 behavior

   This prevents the strategy from repeatedly shorting an up-trending market
   (or buying a down-trending one), which was the root cause of the day-2/3 losses
   in backtest and the live -108 result despite a +22.5-tick up day.

   Important: closing an existing position is NEVER suppressed — if we're
   already long when the trend turns down, the next down-tick AR1 signal can
   still close/flip us normally.

2. Max-hold time (existing but documented)
   exit_ticks > 0 forces a taker close after that many ticks in position.
   Combined with the trend filter this limits stale directional exposure.

New params (v2):
    trend_ema_hl          : half-life (ticks) for the slow trend EMA. Default 0 = disabled.
    trend_threshold       : abs(trend_signal) to activate the direction filter. Default 0.
    passive_close_offset  : (FUTURE) reserved for passive-exit overlay, default 0.

All v1 params are unchanged and fully backward-compatible.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, TradingState
from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base import BaseStrategy


class AR1MeanRevV2A2(BaseStrategy):
    """Tick-to-tick mean-reversion with trend-direction filter and optional max hold."""

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
        exit_ticks = int(p.get("exit_ticks", 0))
        passive_size = int(p.get("passive_size", 0))

        # --- trend-filter params ---
        trend_hl = float(p.get("trend_ema_hl", 0))
        trend_thr = float(p.get("trend_threshold", 0))

        mid = book.mid_price
        if mid is None:
            return [], 0

        # --- session-start reference ---
        if "start_price" not in memory:
            memory["start_price"] = mid

        # --- previous mid for AR1 return ---
        prev_mid = memory.get("prev_mid")
        memory["prev_mid"] = mid

        if prev_mid is None:
            return [], 0

        ret = mid - prev_mid

        # --- slow trend EMA (for direction filter) ---
        trend_up = trend_down = False
        if trend_hl > 0 and trend_thr > 0:
            t_alpha = 1.0 - 0.5 ** (1.0 / trend_hl)
            trend_ema = t_alpha * mid + (1.0 - t_alpha) * memory.get("trend_ema", mid)
            memory["trend_ema"] = trend_ema
            trend_sig = trend_ema - memory["start_price"]
            trend_up = trend_sig > trend_thr
            trend_down = trend_sig < -trend_thr

        orders: List[Order] = []
        bb = book.best_bid
        ba = book.best_ask

        buy_room = limit - position
        sell_room = limit + position

        # ── taker SELL: large up-move → expect reversion ─────────────────
        # Suppress if trending UP and we would be opening/extending a short position.
        # Allow closing an existing long (position > 0) even in uptrend.
        if ret >= entry_thresh and sell_room > 0 and bb is not None:
            if not (trend_up and position <= 0):
                qty = min(taker_size, sell_room)
                orders.append(Order(self.product, bb, -qty))
                sell_room -= qty

        # ── taker BUY: large down-move → expect reversion ────────────────
        # Suppress if trending DOWN and we would be opening/extending a long position.
        # Allow closing an existing short (position < 0) even in downtrend.
        elif ret <= -entry_thresh and buy_room > 0 and ba is not None:
            if not (trend_down and position >= 0):
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
            if buy_room > 0 and bb is not None:
                orders.append(Order(self.product, bb + 1, min(passive_size, buy_room)))
            if sell_room > 0 and ba is not None:
                orders.append(Order(self.product, ba - 1, -min(passive_size, sell_room)))

        return orders, 0
