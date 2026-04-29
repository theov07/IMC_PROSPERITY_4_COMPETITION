"""Z-score MM strategy: passive MM with z-score band gating.

Posts MM quotes always (capture spread). Adds aggressive skew when mid
deviates strongly from rolling mean (z-score) — short the band when overbought,
long when oversold.

Designed for high-rev_ratio products (e.g., UV_VISOR_YELLOW).

Params:
  maker_size           : default 5
  tighten_ticks        : default 1
  z_window             : rolling window size for mid (default 200)
  z_entry              : abs z to trigger skew (default 1.5)
  z_skew_offset        : ticks to push quote when z > entry (default 1)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class ZScoreMMStrategy(BaseStrategy):
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

        mid = (book.best_bid + book.best_ask) / 2.0

        # Rolling mid buffer
        window = int(self.params.get("z_window", 200))
        buf: List[float] = memory.setdefault("_mid_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]

        # Compute z-score
        z = 0.0
        if len(buf) >= 30:
            n = len(buf)
            mean = sum(buf) / n
            var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
            std = var ** 0.5
            if std > 1e-6:
                z = (mid - mean) / std

        memory["_z"] = z

        size = int(self.params.get("maker_size", 5))
        tighten = int(self.params.get("tighten_ticks", 1))
        z_entry = float(self.params.get("z_entry", 1.5))
        z_skew = int(self.params.get("z_skew_offset", 1))

        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask

        # Z-score skew: overbought → ask more aggressive (lower price)
        if z > z_entry:
            ask_p = max(ask_p - z_skew, book.best_bid + 1)
        elif z < -z_entry:
            bid_p = min(bid_p + z_skew, book.best_ask - 1)

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_z")
        return {"z": round(z, 3)} if z is not None else {}
