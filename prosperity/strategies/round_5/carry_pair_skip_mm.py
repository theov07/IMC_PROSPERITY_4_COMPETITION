"""Hybrid carry + pair_skip MM.

Combines two defenses:
  1. pair_skip: skip side when pair z-score is extreme (cross-product signal)
  2. carry: skip side when current inventory would lose to trend

Skip BID if EITHER:
  - pair_z > pair_thresh (rich vs partner)
  - position >= carry_min_pos AND trend < 0 (carry adverse on long)

Skip ASK if EITHER:
  - pair_z < -pair_thresh (cheap vs partner)
  - position <= -carry_min_pos AND trend > 0 (carry adverse on short)

This unifies pair_skip_mm and inventory_carry_mm into one passive MM.
Useful for products where BOTH pair_skip wins BT AND carry helps live.

Params combine both:
  partner, partner_sign, pair_thresh, z_window  (from pair_skip)
  trend_hl, carry_pause_min_pos                  (from carry)
  maker_size, tighten_ticks, hard_pause_at       (shared)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class CarryPairSkipMMStrategy(BaseStrategy):

    def _online_z(self, value: float, key_prefix: str, memory: Dict[str, Any], window: int) -> float:
        buf = memory.setdefault(key_prefix, [])
        buf.append(value)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < 30:
            return 0.0
        n = len(buf)
        mu = sum(buf) / n
        var = sum((x - mu) ** 2 for x in buf) / max(n - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return 0.0
        return (value - mu) / std

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
        pair_thresh = float(self.params.get("pair_thresh", 1.25))
        partner = self.params.get("partner")
        partner_sign = float(self.params.get("partner_sign", -1.0))
        z_window = int(self.params.get("z_window", 300))
        trend_hl = int(self.params.get("trend_hl", 200))
        carry_min_pos = int(self.params.get("carry_pause_min_pos", 3))
        hard_pause = int(self.params.get("hard_pause_at", 9))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # ── Pair signal ────────────────────────────────────────────
        mid = (book.best_bid + book.best_ask) / 2.0
        pair_z = 0.0
        if partner is not None:
            partner_mid = None
            if partner in state.order_depths:
                pdepth = state.order_depths[partner]
                if pdepth.buy_orders and pdepth.sell_orders:
                    pbb = max(pdepth.buy_orders.keys())
                    pba = min(pdepth.sell_orders.keys())
                    partner_mid = (pbb + pba) / 2.0
            zp = self._online_z(mid, "_z_self", memory, z_window)
            if partner_mid is not None:
                zq = self._online_z(partner_mid, "_z_partner", memory, z_window)
                pair_z = zp - partner_sign * zq

        memory["_pair_z"] = pair_z

        # ── Carry/trend signal ─────────────────────────────────────
        alpha = 2.0 / (trend_hl + 1.0)
        ema_mid = memory.get("_ema_mid", mid)
        ema_mid = alpha * mid + (1 - alpha) * ema_mid
        memory["_ema_mid"] = ema_mid
        trend = mid - ema_mid
        memory["_trend"] = trend

        # ── Combined skip logic ────────────────────────────────────
        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # Pair_skip side
        if pair_z > pair_thresh:
            post_bid = False
        elif pair_z < -pair_thresh:
            post_ask = False

        # Carry side (separate check; either trigger pauses)
        if abs(position) >= carry_min_pos:
            if position > 0 and trend < 0:
                post_bid = False
            elif position < 0 and trend > 0:
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
        out = {}
        if "_pair_z" in memory:
            out["pair_z"] = round(memory["_pair_z"], 3)
        if "_trend" in memory:
            out["trend"] = round(memory["_trend"], 2)
        return out
