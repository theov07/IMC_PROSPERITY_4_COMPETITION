"""
Cointegration + Passive MM Strategy — v1

Combines CointPairsV1 z-score signal with passive naive_tight_mm quoting.

Extra params vs CointPairsV1:
    passive_size : units to quote passively (default 3, set 0 to disable)
    tighten_ticks: tighten by this many ticks from best_bid/ask (default 1)

Memory: O(1) — uses EWMA-based running mean/variance (no rolling buffer).
z_window controls the effective EWMA half-life: alpha = 2/(z_window+1).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class CointMMV1(BaseStrategy):
    """Cointegration spread z-score with passive MM overlay. O(1) memory."""

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

        # ── Long EWMA for normalizing price levels ──────────────────────────
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

        # ── EWMA running mean + variance (O(1), no rolling buffer) ──────────
        # alpha equivalent to a window of z_win: alpha = 2/(z_win+1)
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

        # Warmup: require at least z_win/2 ticks before trading
        if n_ticks >= z_win // 2:
            sd_z = math.sqrt(var_z) if var_z > 0 else 1e-9
            z = (spread - mu_z) / sd_z
            memory["last_z"] = z

            bid_A = bb if bb is not None else int(mid_A - 4)
            ask_A = ba if ba is not None else int(mid_A + 4)

            # Exit taker
            if position < 0 and z < exit_z and buy_room > 0:
                qty = min(-position, buy_room)
                orders.append(Order(self.product, int(ask_A), qty))
                buy_room -= qty
            elif position > 0 and z > -exit_z and sell_room > 0:
                qty = min(position, sell_room)
                orders.append(Order(self.product, int(bid_A), -qty))
                sell_room -= qty

            # Entry taker
            if position == 0:
                if z > entry_z and sell_room > 0:
                    qty = min(taker_size, sell_room)
                    orders.append(Order(self.product, int(bid_A), -qty))
                    sell_room -= qty
                elif z < -entry_z and buy_room > 0:
                    qty = min(taker_size, buy_room)
                    orders.append(Order(self.product, int(ask_A), qty))
                    buy_room -= qty

        # Passive MM alongside (if not at limit)
        if passive_size > 0 and bb is not None and ba is not None:
            bid_px = bb + tighten
            ask_px = ba - tighten
            if bid_px < ask_px:
                if buy_room > 0:
                    orders.append(Order(self.product, int(bid_px), min(passive_size, buy_room)))
                if sell_room > 0:
                    orders.append(Order(self.product, int(ask_px), -min(passive_size, sell_room)))

        return orders, 0
