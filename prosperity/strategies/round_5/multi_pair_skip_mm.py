"""Multi-pair-skip MM: skip side based on weighted basket of partners.

Generalizes pair_skip_mm to N partners (cluster basket).

Concept (validated by PCA: SNACKPACK_PC1 = +RASP -0.6*STRAW -0.4*PIST):
  - Instead of pairing PEBBLES_XL with just PEBBLES_S, use the average z
    of {PEBBLES_S, PEBBLES_M, PEBBLES_L, PEBBLES_XS} as the partner index.
  - For SNACKPACK_RASPBERRY, use average z of cluster B = {STRAW, PIST}.

  basket_z = sum(w_i * z(partner_i)) / sum(w_i)
  pair_z   = z(self) - sign * basket_z

This is MORE ROBUST than single-partner pair because it averages out noise.

Params:
  partners            : list of (symbol, weight) tuples
  partner_sign        : -1 (anti-corr) or +1 (pos-corr)
  pair_thresh         : default 1.5
  ... (other params identical to pair_skip_mm)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class MultiPairSkipMMStrategy(BaseStrategy):

    def _online_z(self, value: float, key: str, memory: Dict[str, Any], window: int) -> float:
        buf = memory.setdefault(key, [])
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
        partner_sign = float(self.params.get("partner_sign", -1.0))
        partners = self.params.get("partners", [])  # list of (sym, w)
        hard_pause = int(self.params.get("hard_pause_at", 9))
        z_window = int(self.params.get("z_window", 300))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        post_bid = position < hard_pause
        post_ask = position > -hard_pause

        pair_z = 0.0
        if partners:
            mid = (book.best_bid + book.best_ask) / 2.0
            zp_self = self._online_z(mid, "_z_self", memory, z_window)
            # Compute basket z = weighted average of partner z's
            num = 0.0
            den = 0.0
            for (psym, w) in partners:
                if psym in state.order_depths:
                    pd = state.order_depths[psym]
                    if pd.buy_orders and pd.sell_orders:
                        pmid = (max(pd.buy_orders.keys()) + min(pd.sell_orders.keys())) / 2.0
                        zb = self._online_z(pmid, f"_z_p_{psym}", memory, z_window)
                        num += w * zb
                        den += abs(w)
            if den > 0:
                basket_z = num / den
                pair_z = zp_self - partner_sign * basket_z
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
        return {"pair_z": round(z, 3)} if z is not None else {}
