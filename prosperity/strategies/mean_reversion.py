"""Rolling-quantile mean-reversion strategy.

Philosophy:
  At each tick, maintain a rolling buffer of M smoothed mid-prices and compute:
    pS = N-th largest price in window  (upper band — price in top-N tail → expect reversion down)
    pL = N-th smallest price in window (lower band — price in bottom-N tail → expect reversion up)
    band_mid = pL + exit_band_pct * (pS - pL)  (default: midpoint of the two bands)

  Entry (aggressive taker):
    mid_smooth > pS  →  sell  (price stretched above upper tail, expect reversion)
    mid_smooth < pL  →  buy   (price stretched below lower tail, expect reversion)

  Exit (aggressive taker, takes priority over entry):
    position < 0 and mid_smooth <= band_mid  →  buy to close
    position > 0 and mid_smooth >= band_mid  →  sell to close

  Adding to position: if already in a position and the entry signal is still active,
  additional units are added up to the position limit (inventory-adaptive sizing).

  No passive quoting — this strategy is taker-only.

Key params (all configurable via config.py):
  band_window       — rolling window size M (default 200)
  band_rank         — N for N-th largest/smallest (default 10)
  exit_band_pct     — exit when price reverts to this fraction of band width from pL (default 0.5)
  min_band_width    — skip entry if pS-pL is too tight (default 0)
  maker_size_base_pct — base order size as % of position limit (default 0.5)
  mid_smooth_window, mid_smooth_half_life — EWMA smoother params (inherited from base)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):

    # ── band computation ─────────────────────────────────────────────
    def _compute_bands(
        self, mid: float, memory: Dict[str, Any]
    ) -> tuple[float | None, float | None]:
        """Append mid to rolling buffer and return (pS, pL) or (None, None)."""
        window = int(self.params.get("band_window", 200))
        rank = int(self.params.get("band_rank", 10))

        buf = memory.setdefault("_band_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]

        if len(buf) < rank * 2:
            return None, None

        sorted_buf = sorted(buf)
        pL = sorted_buf[rank - 1]   # N-th smallest
        pS = sorted_buf[-rank]      # N-th largest
        return pS, pL

    # ── order construction ───────────────────────────────────────────
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        if book.best_bid is None and book.best_ask is None:
            return [], 0

        mid = book.mid_price or float(book.best_bid or book.best_ask or 0)
        mid_smooth = self._smooth_mid(mid, memory)

        pS, pL = self._compute_bands(mid_smooth, memory)

        if pS is None or pL is None:
            return [], 0

        memory["_mr_pS"] = pS
        memory["_mr_pL"] = pL

        band_width = pS - pL
        min_band_width = float(self.params.get("min_band_width", 0))
        if band_width < min_band_width:
            return [], 0

        exit_band_pct = float(self.params.get("exit_band_pct", 0.5))
        band_mid = pL + exit_band_pct * band_width
        memory["_mr_band_mid"] = band_mid

        limit = self.position_limit()
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Inventory-adaptive sizing (same logic as mm_first)
        base_size = float(self.params.get("maker_size_base_pct", 0.5)) * limit
        bid_size = int(base_size * (1.0 - position / limit)) if limit else int(base_size)
        ask_size = int(base_size * (1.0 + position / limit)) if limit else int(base_size)

        orders: List[Order] = []
        action = "none"

        # ── EXIT (priority over entry) ────────────────────────────────
        if position < 0 and mid_smooth <= band_mid:
            # Close short: buy back aggressively
            qty = min(buy_cap, abs(position))
            for ask_p in sorted(order_depth.sell_orders):
                if qty <= 0:
                    break
                available = -order_depth.sell_orders[ask_p]
                trade_qty = min(available, qty)
                if trade_qty > 0:
                    orders.append(Order(self.product, ask_p, trade_qty))
                    qty -= trade_qty
            action = "exit_short"

        elif position > 0 and mid_smooth >= band_mid:
            # Close long: sell aggressively
            qty = min(sell_cap, position)
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if qty <= 0:
                    break
                available = order_depth.buy_orders[bid_p]
                trade_qty = min(available, qty)
                if trade_qty > 0:
                    orders.append(Order(self.product, bid_p, -trade_qty))
                    qty -= trade_qty
            action = "exit_long"

        # ── ENTRY ─────────────────────────────────────────────────────
        # Only enter (or add) when not trying to exit the opposite leg.
        # Adding to an existing position in the same direction is allowed.
        elif mid_smooth > pS and sell_cap > 0 and position <= 0:
            # Short entry: sell into best bids
            qty = min(sell_cap, ask_size)
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if qty <= 0:
                    break
                available = order_depth.buy_orders[bid_p]
                trade_qty = min(available, qty)
                if trade_qty > 0:
                    orders.append(Order(self.product, bid_p, -trade_qty))
                    qty -= trade_qty
            action = "enter_short"

        elif mid_smooth < pL and buy_cap > 0 and position >= 0:
            # Long entry: buy from best asks
            qty = min(buy_cap, bid_size)
            for ask_p in sorted(order_depth.sell_orders):
                if qty <= 0:
                    break
                available = -order_depth.sell_orders[ask_p]
                trade_qty = min(available, qty)
                if trade_qty > 0:
                    orders.append(Order(self.product, ask_p, trade_qty))
                    qty -= trade_qty
            action = "enter_long"

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=None,
            ask_price=None,
            extras={
                "position": position,
                "mid_smooth": round(mid_smooth, 2),
                "pS": round(pS, 2),
                "pL": round(pL, 2),
                "band_mid": round(band_mid, 2),
                "action": action,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        for key, label in (("_mr_pS", "BandUp"), ("_mr_pL", "BandLo"), ("_mr_band_mid", "BandMid")):
            if (v := memory.get(key)) is not None:
                out[label] = v
        return out
