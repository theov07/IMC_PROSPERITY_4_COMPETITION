"""
Cointegration + Passive MM Strategy — v2

v1 with two optional guards to prevent catching a falling knife:

1. max_extreme_ticks (default 0 = off):
   If the z-score has stayed on the same entry-side extreme for more than
   max_extreme_ticks consecutive ticks without touching exit_z, stop
   opening new taker positions on that side. Existing positions still unwind.

2. require_reverting (default False):
   Only enter a new taker position when the z-score is ACTIVELY reverting:
   z-score must have been more extreme at the previous tick than now
   (i.e., z is moving back toward 0). Prevents entering into a trend.

Either guard alone helps; enabling both is most conservative.

New params vs CointMMV1:
    max_extreme_ticks : int  (default 0 = off)
    require_reverting : bool (default False)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class CointMMV2(BaseStrategy):
    """CointMMV1 + extreme-ticks guard + reverting-z filter. O(1) memory."""

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
        passive_size = int(p.get("passive_size", 3))
        tighten = int(p.get("tighten_ticks", 1))
        max_extreme = int(p.get("max_extreme_ticks", 0))     # 0 = disabled
        req_rev = bool(p.get("require_reverting", False))

        mid_A = book.mid_price
        if mid_A is None:
            return [], 0

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

        # ── Long EWMA for price-level normalization ──────────────────────────
        alpha_m = 1.0 - math.exp(-1.0 / mean_hl)
        mean_A = memory.get("mean_A", mid_A)
        mean_B = memory.get("mean_B", mid_B)
        mean_A = alpha_m * mid_A + (1 - alpha_m) * mean_A
        mean_B = alpha_m * mid_B + (1 - alpha_m) * mean_B
        memory["mean_A"] = mean_A
        memory["mean_B"] = mean_B

        if mean_A == 0 or mean_B == 0:
            return [], 0

        spread = mid_A / mean_A - mid_B / mean_B

        # ── EWMA running mean + variance (O(1)) ──────────────────────────────
        alpha_z = 2.0 / (z_win + 1)
        n_ticks = memory.get("n_ticks", 0) + 1
        memory["n_ticks"] = n_ticks

        mu_z = memory.get("mu_z", spread)
        var_z = memory.get("var_z", 1e-6)
        delta = spread - mu_z
        mu_z = mu_z + alpha_z * delta
        var_z = (1.0 - alpha_z) * (var_z + alpha_z * delta * delta)
        memory["mu_z"] = mu_z
        memory["var_z"] = var_z

        orders: List[Order] = []
        buy_room = limit - position
        sell_room = limit + position

        if n_ticks < z_win // 2:
            # Still in warmup — passive MM only
            if passive_size > 0 and bb is not None and ba is not None:
                bid_px = bb + tighten
                ask_px = ba - tighten
                if bid_px < ask_px:
                    if buy_room > 0:
                        orders.append(Order(self.product, int(bid_px), min(passive_size, buy_room)))
                    if sell_room > 0:
                        orders.append(Order(self.product, int(ask_px), -min(passive_size, sell_room)))
            return orders, 0

        sd_z = math.sqrt(var_z) if var_z > 0 else 1e-9
        z = (spread - mu_z) / sd_z
        prev_z = memory.get("last_z", z)
        memory["last_z"] = z

        # ── Extreme-ticks counter ─────────────────────────────────────────────
        # Tracks how long z has been stuck on the same side of entry_z
        ext_ticks = memory.get("ext_ticks", 0)
        if abs(z) > entry_z:
            ext_ticks += 1
        else:
            ext_ticks = 0
        memory["ext_ticks"] = ext_ticks

        blocked_by_extreme = max_extreme > 0 and ext_ticks > max_extreme

        bid_A = bb if bb is not None else int(mid_A - 4)
        ask_A = ba if ba is not None else int(mid_A + 4)

        # ── Exit taker (always allowed, no guards) ────────────────────────────
        if position < 0 and z < exit_z and buy_room > 0:
            qty = min(-position, buy_room)
            orders.append(Order(self.product, int(ask_A), qty))
            buy_room -= qty
        elif position > 0 and z > -exit_z and sell_room > 0:
            qty = min(position, sell_room)
            orders.append(Order(self.product, int(bid_A), -qty))
            sell_room -= qty

        # ── Entry taker (subject to guards) ───────────────────────────────────
        if position == 0 and not blocked_by_extreme:
            if z > entry_z and sell_room > 0:
                # z is high → A expensive → sell A. Reverting means z decreasing.
                reverting = (not req_rev) or (prev_z > z)
                if reverting:
                    qty = min(taker_size, sell_room)
                    orders.append(Order(self.product, int(bid_A), -qty))
                    sell_room -= qty
            elif z < -entry_z and buy_room > 0:
                # z is low → A cheap → buy A. Reverting means z increasing.
                reverting = (not req_rev) or (prev_z < z)
                if reverting:
                    qty = min(taker_size, buy_room)
                    orders.append(Order(self.product, int(ask_A), qty))
                    buy_room -= qty

        # ── Passive MM ────────────────────────────────────────────────────────
        if passive_size > 0 and bb is not None and ba is not None:
            bid_px = bb + tighten
            ask_px = ba - tighten
            if bid_px < ask_px:
                if buy_room > 0:
                    orders.append(Order(self.product, int(bid_px), min(passive_size, buy_room)))
                if sell_room > 0:
                    orders.append(Order(self.product, int(ask_px), -min(passive_size, sell_room)))

        return orders, 0
