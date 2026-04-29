"""Pair trading strategy using cross-asset spread mean reversion.

For a product P configured with cross_pair_partner Q and weight w:
  spread_t = mid(P) + w * mid(Q)
  z_t = (spread_t - mean) / std (rolling)

  z > +zthresh → SHORT P (sell), expect spread to drop
  z < -zthresh → LONG P (buy), expect spread to rise
  |z| < exit  → flatten

Each product has its own partner. So for SNACKPACK_CHOCOLATE pair with VANILLA (corr -0.926):
  spread = mid(CHOCOLATE) + 1.0 * mid(VANILLA)  (since corr negative, w=+1)
  When CHOCOLATE rises and VANILLA doesn't drop enough → spread up → SHORT chocolate.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class PairTraderStrategy(BaseStrategy):
    """Pair trading: spread mean reversion with rolling z-score."""

    def _partner_mid(self, state: TradingState) -> Optional[float]:
        partner = self.params.get("cross_pair_partner")
        if not partner:
            return None
        od = state.order_depths.get(partner)
        if od is None or not od.buy_orders or not od.sell_orders:
            return None
        return (max(od.buy_orders) + min(od.sell_orders)) / 2.0

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
        my_mid = (book.best_bid + book.best_ask) / 2.0

        # Pair signal
        partner_mid = self._partner_mid(state)
        weight = float(self.params.get("cross_pair_weight", 1.0))
        if partner_mid is None:
            # No partner — fall back to naive MM
            return self._naive_mm(book, position), 0

        spread = my_mid + weight * partner_mid
        # Rolling stats
        window = int(self.params.get("z_window", 200))
        buf: List[float] = memory.setdefault("_spread_buf", [])
        buf.append(spread)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < 30:
            return self._naive_mm(book, position), 0

        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-6:
            return self._naive_mm(book, position), 0
        z = (spread - mean) / std
        memory["_z"] = z

        zthresh = float(self.params.get("z_entry", 1.5))
        zexit = float(self.params.get("z_exit", 0.3))
        size_max = int(self.params.get("pair_size", 10))

        # Mode: directional taker
        target = position
        if z > zthresh:
            target = -size_max  # short
        elif z < -zthresh:
            target = +size_max  # long
        elif abs(z) < zexit:
            target = 0

        # Issue orders to reach target
        orders: List[Order] = []
        diff = target - position
        limit = self.position_limit()
        if diff > 0:
            qty = min(diff, self.buy_capacity(position))
            if qty > 0:
                orders.append(Order(self.product, book.best_ask, qty))
        elif diff < 0:
            qty = min(-diff, self.sell_capacity(position))
            if qty > 0:
                orders.append(Order(self.product, book.best_bid, -qty))

        # If no directional move, keep MM passive (capture spread when in band)
        if abs(z) <= zthresh:
            mm_orders = self._naive_mm(book, position)
            orders = orders + mm_orders
        return orders, 0

    def _naive_mm(self, book: BookSnapshot, position: int) -> List[Order]:
        orders: List[Order] = []
        size = int(self.params.get("maker_size", 5))
        tighten = int(self.params.get("tighten_ticks", 1))
        if book.best_bid is not None and book.best_ask is not None:
            spread = book.best_ask - book.best_bid
            bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
            ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask
            buy_cap = self.buy_capacity(position)
            sell_cap = self.sell_capacity(position)
            if bid_p is not None and buy_cap > 0:
                orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
            if ask_p is not None and sell_cap > 0:
                orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_z")
        return {"z_pair": round(z, 3)} if z is not None else {}
