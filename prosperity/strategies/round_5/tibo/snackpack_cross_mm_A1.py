"""
Snackpack Cross-Product Market Maker — A1

Exploits the AR1 mean-reversion in SNACKPACK product SUMS:
  CHOC + VANI sum: AR1 = -0.34 (consistent across all 3 days)
  STRAW + RASP sum: AR1 = -0.27 (consistent)

Pairs:
  CHOCOLATE   ↔ VANILLA      (return corr = -0.92, sum is stable)
  STRAWBERRY  ↔ RASPBERRY    (return corr = -0.92, sum is stable)

When sum = mid_A + mid_B is high relative to its EWMA (z > threshold):
  → both products are elevated; the sum will likely revert downward
  → lower our bid/ask to avoid adverse selection and capture the downside fill
When sum is low (z < -threshold):
  → both products are depressed; sum will likely revert upward
  → raise our bid/ask to capture the upside fill

Key params:
  partner_product : the negatively-correlated partner
  z_window        : EWMA window for z-score (default 300)
  shift_per_z     : quote shift per unit of z-score (default 1.0 tick)
  z_clamp         : max |z| used for shifting (prevents extreme shifts)
  maker_size      : passive order size
  tighten_ticks   : how many ticks to tighten from best bid/ask
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class SnackpackCrossMMV1_A1(BaseStrategy):
    """
    Sum-signal-aware passive market maker for negatively-correlated SNACKPACK pairs.
    Uses the CHOC+VANI (or STRAW+RASP) sum z-score to shift quotes.
    Self-contained, no external dependencies beyond BaseStrategy.
    """

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        partner = str(p["partner_product"])
        z_win = int(p.get("z_window", 300))
        shift_per_z = float(p.get("shift_per_z", 1.0))
        z_clamp = float(p.get("z_clamp", 3.0))
        maker_size = int(p.get("maker_size", 5))
        tighten = int(p.get("tighten_ticks", 1))
        limit = int(p.get("position_limit", 10))

        mid_A = book.mid_price
        if mid_A is None:
            return [], 0

        # Get partner's mid price
        pod = state.order_depths.get(partner)
        if pod and pod.buy_orders and pod.sell_orders:
            mid_B = (max(pod.buy_orders) + min(pod.sell_orders)) / 2.0
            memory["mid_B_prev"] = mid_B
        else:
            mid_B = memory.get("mid_B_prev")
            if mid_B is None:
                return [], 0

        # sum of the two negatively-correlated products (should be stable)
        current_sum = mid_A + mid_B

        # EWMA running mean + variance of the sum (O(1) memory)
        alpha_z = 2.0 / (z_win + 1)
        n_ticks = memory.get("n_ticks", 0) + 1
        memory["n_ticks"] = n_ticks

        mu_sum = memory.get("mu_sum", current_sum)
        var_sum = memory.get("var_sum", 1e-6)
        delta = current_sum - mu_sum
        mu_sum = mu_sum + alpha_z * delta
        var_sum = (1.0 - alpha_z) * (var_sum + alpha_z * delta * delta)
        memory["mu_sum"] = mu_sum
        memory["var_sum"] = var_sum

        bb = book.best_bid
        ba = book.best_ask
        if bb is None or ba is None:
            return [], 0

        orders: List[Order] = []
        buy_room = limit - position
        sell_room = limit + position

        # Compute z-score and quote shift
        # Only apply shift after warmup (z_win/2 ticks)
        quote_shift = 0
        if n_ticks >= z_win // 2 and var_sum > 1e-9:
            sd_sum = math.sqrt(var_sum)
            z = (current_sum - mu_sum) / sd_sum
            # Clamp z to avoid runaway shifts
            z_clamped = max(-z_clamp, min(z_clamp, z))
            # When sum is HIGH (z>0): product prices elevated → shift quotes DOWN
            # When sum is LOW  (z<0): product prices depressed → shift quotes UP
            quote_shift = -int(round(shift_per_z * z_clamped))
            memory["last_z"] = z

        # Standard passive MM around best bid/ask, with z-score shift
        spread = ba - bb
        if spread >= 2:
            bid_px = bb + tighten + quote_shift
            ask_px = ba - tighten + quote_shift
        else:
            bid_px = bb + quote_shift
            ask_px = ba + quote_shift

        # Safety: never let bid >= ask
        if bid_px >= ask_px:
            bid_px = ask_px - 1

        if buy_room > 0:
            orders.append(Order(self.product, int(bid_px), min(maker_size, buy_room)))
        if sell_room > 0:
            orders.append(Order(self.product, int(ask_px), -min(maker_size, sell_room)))

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_px,
            ask_price=ask_px,
            extras={"z": memory.get("last_z", 0.0), "shift": quote_shift},
        )

        return orders, 0
