"""
Cointegration Pairs Trading Strategy — v1

For two cointegrated products A (self) and B (partner):
  spread = mid_A / mean_A_est - mid_B / mean_B_est   (normalized 1:1)
  z_score = (spread - rolling_mu) / rolling_sd

Entries (taker only):
  z > +entry_z  → sell A at bid, buy  B at ask  (A overpriced vs B)
  z < -entry_z  → buy  A at ask, sell B at bid   (A underpriced vs B)

Exit (taker): when |z| < exit_z  →  unwind entire position.

Mean estimates come from a long warmup EWMA, avoiding look-ahead.
Rolling z-score uses a separate (shorter) window to track recent spread level.

Params:
    partner_product     : symbol of the partner product
    mean_half_life      : EWMA half-life (ticks) for normalizing spread (default 5000)
    z_window            : rolling window for z-score (default 1000)
    entry_z             : z-score threshold to enter (default 1.5)
    exit_z              : z-score threshold to exit (default 0.0)
    taker_size          : units per trade (default 10 = full limit)
    position_limit      : per-product limit (default 10)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class CointPairsV1(BaseStrategy):
    """Normalized spread z-score pairs trade on two cointegrated products."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        partner = str(p["partner_product"])
        mean_hl = float(p.get("mean_half_life", 5000))
        z_win = int(p.get("z_window", 1000))
        entry_z = float(p.get("entry_z", 1.5))
        exit_z = float(p.get("exit_z", 0.0))
        taker_size = int(p.get("taker_size", 10))
        limit = int(p.get("position_limit", 10))

        mid_A = book.mid_price
        if mid_A is None:
            return [], 0

        # Get partner mid
        pod = state.order_depths.get(partner)
        if pod is None:
            return [], 0
        pb = list(pod.buy_orders.keys())
        pa = list(pod.sell_orders.keys())
        if not pb or not pa:
            return [], 0
        mid_B = (max(pb) + min(pa)) / 2.0

        bb = book.best_bid
        ba = book.best_ask
        bid_A = bb if bb is not None else (mid_A - 4)
        ask_A = ba if ba is not None else (mid_A + 4)
        bid_B = max(pb)
        ask_B = min(pa)

        # ── EWMA price level estimates ──────────────────────────────────────
        alpha_m = 1.0 - math.exp(-1.0 / mean_hl)
        mean_A = memory.get("mean_A", mid_A)
        mean_B = memory.get("mean_B", mid_B)
        mean_A = alpha_m * mid_A + (1 - alpha_m) * mean_A
        mean_B = alpha_m * mid_B + (1 - alpha_m) * mean_B
        memory["mean_A"] = mean_A
        memory["mean_B"] = mean_B

        if mean_A == 0 or mean_B == 0:
            return [], 0

        # ── Rolling z-score of normalized spread ────────────────────────────
        spread = mid_A / mean_A - mid_B / mean_B
        buf: List[float] = memory.setdefault("zbuf", [])
        buf.append(spread)
        # Keep only last z_win values (plain list, JSON serializable)
        if len(buf) > z_win:
            del buf[: len(buf) - z_win]

        if len(buf) < z_win // 2:
            return [], 0  # warmup

        mu_s = sum(buf) / len(buf)
        var_s = sum((x - mu_s) ** 2 for x in buf) / len(buf)
        sd_s = math.sqrt(var_s) if var_s > 0 else 1e-9
        z = (spread - mu_s) / sd_s

        # ── Track partner position via shared state ─────────────────────────
        shared = state.__dict__.get("_shared", {}) if hasattr(state, "__dict__") else {}

        orders: List[Order] = []
        buy_room = limit - position
        sell_room = limit + position

        # ── Exit when spread reverts ─────────────────────────────────────────
        if position < 0 and z < exit_z:
            # We were short A → buy back at ask
            qty = min(-position, buy_room)
            if qty > 0:
                orders.append(Order(self.product, int(ask_A), qty))
        elif position > 0 and z > -exit_z:
            # We were long A → sell at bid
            qty = min(position, sell_room)
            if qty > 0:
                orders.append(Order(self.product, int(bid_A), -qty))

        # ── Enter when spread extreme ────────────────────────────────────────
        if position == 0:
            if z > entry_z and sell_room > 0:
                # A overpriced → sell A at bid
                qty = min(taker_size, sell_room)
                orders.append(Order(self.product, int(bid_A), -qty))
            elif z < -entry_z and buy_room > 0:
                # A underpriced → buy A at ask
                qty = min(taker_size, buy_room)
                orders.append(Order(self.product, int(ask_A), qty))

        # Store z-score for partner to read (for symmetric entry)
        memory["last_z"] = z
        memory["last_spread"] = spread

        return orders, 0
