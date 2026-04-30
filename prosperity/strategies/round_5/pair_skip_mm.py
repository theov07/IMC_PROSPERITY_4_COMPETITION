"""Pair-skip MM: passive penny-improve + skip-side based on partner mid.

Concept (validated by copula analysis: CHOC<->VAN have rho=-0.92, lambda_L=lambda_U=0):
  - For two anti-correlated products, when one is high vs its history, the
    other is mechanically low.
  - Don't price-skew (it costs spread). Instead, just skip the bid/ask on
    the "wrong side" when the pair signal is extreme.

For each product, we configure a `partner` in params. The strategy:
  1. Compute z(product mid) and z(partner mid) using rolling stats.
  2. Compute pair_z = z(product) - z(partner)
     * If they're inversely correlated, pair_z > 0 means product is HIGH and
       partner LOW = product is RICH vs the pair fair value
  3. If pair_z > +pair_thresh -> skip BID (don't load up on rich product)
  4. If pair_z < -pair_thresh -> skip ASK (don't sell cheap product)

Params:
  partner             : symbol of the inverse partner
  partner_sign        : +1 if positively corr, -1 if inversely corr (default -1)
  pair_thresh         : abs threshold to fire skip (default 1.5)
  maker_size          : default 5
  tighten_ticks       : default 1
  hard_pause_at       : default 9
  z_window            : rolling window for mid z (default 300)
  skip_size           : size to post on the "skipped" side instead of fully suppressing (default 0
                        = hard skip). E.g. skip_size=1 posts 1 unit even when pair_z fires, giving
                        partial exposure rather than a binary on/off. Useful for hybrid tuning.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class PairSkipMMStrategy(BaseStrategy):

    def _online_z(self, value: float, key_prefix: str, memory: Dict[str, Any], window: int) -> float:
        """Online rolling z using last `window` observations."""
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
        pair_thresh = float(self.params.get("pair_thresh", 1.5))
        partner = self.params.get("partner")
        partner_sign = float(self.params.get("partner_sign", -1.0))  # -1 = inverse
        hard_pause = int(self.params.get("hard_pause_at", 9))
        z_window = int(self.params.get("z_window", 300))
        skip_size = int(self.params.get("skip_size", 0))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        # Default skip-pair signal = 0
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
            zp = self._online_z(mid, "_z_self", memory, z_window)
            if partner_mid is not None:
                # Adjust partner z by partner_sign so positively corr partner gives same direction
                zq = self._online_z(partner_mid, "_z_partner", memory, z_window)
                pair_z = zp - partner_sign * zq  # if partner_sign=-1, pair_z = zp + zq
                # If both rich -> pair_z high; if self rich and partner cheap (inverse pair) -> pair_z high

        memory["_pair_z"] = pair_z

        # Determine effective bid/ask sizes
        bid_size = size
        ask_size = size
        if pair_z > pair_thresh:
            if skip_size > 0:
                bid_size = skip_size  # soft skip: reduced size
            else:
                post_bid = False      # hard skip
        elif pair_z < -pair_thresh:
            if skip_size > 0:
                ask_size = skip_size  # soft skip: reduced size
            else:
                post_ask = False      # hard skip

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(bid_size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(ask_size, sell_cap)))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_pair_z")
        return {"pair_z": round(z, 3)} if z is not None else {}
