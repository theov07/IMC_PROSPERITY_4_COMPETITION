"""Penny-improve market maker with inventory-adaptive level stepping.

Philosophy:
  - Default: always penny-improve both sides (best_bid+1 / best_ask-1)
  - Level stepping: when |position| >= inv_step_threshold * limit,
    back off the inventory-increasing side to level 2 (join best instead
    of improving) while keeping level 1 on the reducing side.
  - Taker orders: sweep aggressively when ask_p <= mid_smooth - take_edge
    or bid_p >= mid_smooth + take_edge.
  - Sizing: inventory-adaptive (same logic as avellaneda_stoikov).

Key params (all configurable via config.py):
  inv_step_threshold   — fraction of limit at which bid/ask steps to L2 (default 0.8)
  take_edge            — min edge vs smoothed mid to trigger a taker order (default 1.0)
  maker_size_base_pct  — base passive quote size as % of position limit (default 0.2)
  pct_kept_for_takers  — fraction of remaining capacity reserved for takers (default 0.2)
  mid_smooth_window    — rolling window for mid-price EMA smoothing (default 20, 0=off)
  mid_smooth_half_life — EMA half-life for mid smoothing (default window/2)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class MMFirstStrategy(BaseStrategy):

    # ── mid price smoothing ──────────────────────────────────────────
    def _smooth_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        window = int(self.params.get("mid_smooth_window", 20))
        if window <= 0:
            return mid
        half_life = float(self.params.get("mid_smooth_half_life", window / 2.0))
        buf = memory.setdefault("mid_smooth_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < 2:
            return mid
        alpha = 1.0 - 2.0 ** (-1.0 / half_life) if half_life > 0 else 1.0
        smoothed = buf[0]
        for p in buf[1:]:
            smoothed = alpha * p + (1.0 - alpha) * smoothed
        memory["mid_smoothed"] = smoothed
        return smoothed

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

        mid = book.mid_price or (book.best_bid or book.best_ask)
        mid_smooth = self._smooth_mid(mid, memory)

        limit = self.position_limit()
        inv_ratio = position / float(limit) if limit else 0.0
        step_threshold = float(self.params.get("inv_step_threshold", 0.8))

        # ─────────────── QUOTE LEVEL SELECTION ────────────────────────
        # L1 (default): penny-improve — post one tick inside the market
        # L2 (high inventory): join best on the inventory-increasing side
        #   Long  → back off bid to best_bid (join), keep ask at best_ask-1
        #   Short → back off ask to best_ask (join), keep bid at best_bid+1

        bid_price: int | None = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price: int | None = (book.best_ask - 1) if book.best_ask is not None else None
        quote_level = "L1"

        if inv_ratio >= step_threshold:
            # Long: ease off buying, stay aggressive on selling
            if book.best_bid is not None:
                bid_price = book.best_bid   # join, no improvement
            quote_level = "L2"
        elif inv_ratio <= -step_threshold:
            # Short: ease off selling, stay aggressive on buying
            if book.best_ask is not None:
                ask_price = book.best_ask   # join, no improvement
            quote_level = "L2"

        # Crossing prevention
        if bid_price is not None and book.best_ask is not None:
            bid_price = min(bid_price, book.best_ask - 1)
        if ask_price is not None and book.best_bid is not None:
            ask_price = max(ask_price, book.best_bid + 1)
        if bid_price is not None and ask_price is not None and ask_price <= bid_price:
            ask_price = bid_price + 1

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        # ─────────────── DYNAMIC SIZING (shared by takers + passive) ──────────
        # Inventory-adaptive: scale bid size down when long, ask size down when short

        base_size = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base_size * (1.0 - position / limit)
        ask_size = base_size * (1.0 + position / limit)

        # ─────────────── TAKER ORDERS ─────────────────────────────────
        # Two conditions (OR) trigger a taker order:
        #   1. mid_smooth edge:  ask <= mid_smooth - take_edge  (or bid >= mid_smooth + take_edge)
        #   2. absolute threshold (optional): ask <= taker_buy_threshold / bid >= taker_sell_threshold
        # Either condition alone is sufficient.
        # Size is capped to the same dynamic size as passive quotes (min of capacity and inv-scaled size).

        this_taker_buy_px: set = set()
        this_taker_sell_px: set = set()

        take_edge           = float(self.params.get("take_edge", 1.0))
        taker_buy_threshold  = self.params.get("taker_buy_threshold")   # None = disabled
        taker_sell_threshold = self.params.get("taker_sell_threshold")  # None = disabled

        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= mid_smooth - take_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, int(bid_size*0.3))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                this_taker_buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume     = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= mid_smooth + take_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, int(ask_size*0.3))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                this_taker_sell_px.add(bid_p)
                sell_cap -= qty

        quote_buy = min(buy_cap, int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))

        # Hard stop: keep capacity free for takers at extreme inventory
        inv_abs = abs(position) / float(limit) if limit else 0.0
        if inv_abs >= 1.0 - float(self.params.get("pct_kept_for_takers", 0.2)):
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0

        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))

        # ─────────────── TAKER FILL LOGGING ───────────────────────────
        prev_taker_buy_px = set(memory.get("_taker_buy_px", []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        memory["_taker_buy_px"] = list(this_taker_buy_px)
        memory["_taker_sell_px"] = list(this_taker_sell_px)

        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY", trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                )

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "mid_smooth": round(mid_smooth, 2),
                "level": quote_level,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        return out
