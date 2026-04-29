"""Lag-based pair_skip MM: use partner mid from k ticks ago.

Same logic as pair_skip_mm but signals on z(partner_{t-k}) instead of z(partner_t).
Hypothesis: laggers respond to leader moves with a delay → using lagged partner
z-score should catch the move BEFORE it reaches us.

Optimal lags from correl.md (negative = partner leads us):
  * UV_VISOR_AMBER ↔ PEBBLES_XS : lag=-692
  * PANEL_2X4 ↔ PEBBLES_XL : lag=-159
  * SLEEP_POD_COTTON ↔ SLEEP_POD_POLYESTER : lag=-293
  * SNACKPACK_STRAWBERRY ↔ SLEEP_POD_POLYESTER : lag=-763
  * Most other pairs : lag=-1000 (max lag tested)

Params (in addition to pair_skip_mm):
  partner_lag : ticks of lag to use (default 100, ts=10000ms = 100 raw ticks)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class PairSkipLagMMStrategy(BaseStrategy):

    def _online_z_lagged(
        self, value: float, key_prefix: str, memory: Dict[str, Any],
        window: int, lag: int = 0
    ) -> float:
        """Online z over rolling window, evaluated at lag ticks ago."""
        buf = memory.setdefault(key_prefix, [])
        buf.append(value)
        if len(buf) > window + lag + 5:
            buf[:] = buf[-(window + lag + 5):]
        if len(buf) < max(30, lag + 30):
            return 0.0
        # Use buf[-lag-1] as "value at lag ticks ago"
        # Use the prior `window` elements before that to compute mean/std
        idx = -lag - 1 if lag > 0 else -1
        try:
            target = buf[idx]
            ref_buf = buf[max(0, idx - window):idx] if lag > 0 else buf[-window:]
        except IndexError:
            return 0.0
        if len(ref_buf) < 30:
            return 0.0
        n = len(ref_buf)
        mu = sum(ref_buf) / n
        var = sum((x - mu) ** 2 for x in ref_buf) / max(n - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return 0.0
        return (target - mu) / std

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
        pair_thresh = float(self.params.get("pair_thresh", 1.5))
        partner = self.params.get("partner")
        partner_sign = float(self.params.get("partner_sign", -1.0))
        hard_pause = int(self.params.get("hard_pause_at", 9))
        z_window = int(self.params.get("z_window", 300))
        partner_lag = int(self.params.get("partner_lag", 0))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        pair_z = 0.0
        if partner is not None:
            mid = (book.best_bid + book.best_ask) / 2.0
            partner_mid = None
            if partner in state.order_depths:
                pdepth = state.order_depths[partner]
                if pdepth.buy_orders and pdepth.sell_orders:
                    pbb = max(pdepth.buy_orders.keys())
                    pba = min(pdepth.sell_orders.keys())
                    partner_mid = (pbb + pba) / 2.0
            zp = self._online_z_lagged(mid, "_z_self", memory, z_window, lag=0)
            if partner_mid is not None:
                # Use partner's z-score from `partner_lag` ticks ago
                zq = self._online_z_lagged(partner_mid, "_z_partner", memory, z_window, lag=partner_lag)
                pair_z = zp - partner_sign * zq

        memory["_pair_z"] = pair_z

        if pair_z > pair_thresh:
            post_bid = False
        elif pair_z < -pair_thresh:
            post_ask = False

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_pair_z")
        return {"pair_z_lag": round(z, 3)} if z is not None else {}
