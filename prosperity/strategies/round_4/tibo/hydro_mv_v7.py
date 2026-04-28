"""
hydro_mv_v7.py — HYDROGEL_PACK: inventory-managed passive MM

Root cause of v6 live failure: the AR taker builds a runaway short position
when price trends up for hours without crossing the fair value (≈10000). In
the 3-day historical backtest price oscillates ±80 ticks and crosses the fair
value every ~500k ticks, so the directional bet eventually pays off. In live
(shorter horizon), the position is stuck near -200 the whole session.

V7 fix: add a two-sided passive MM layer that unwinds inventory *along the
trend* rather than waiting for mean-reversion. The MM quotes both sides every
tick with inventory-adaptive sizing (more size on the inventory-reducing side).

Architecture — two components sharing a single position counter:

  1. Anchor component (anchor_reserve_pct × limit): same inv_protected AR
     taker as v6b. Fires ONLY when |position| < anchor_limit. This limits
     the directional bet to a small fraction of capacity.

  2. MM component (remainder of capacity): always posts both bid and ask
     passively. Sizing is inventory-adaptive so the short/long inventory is
     continuously reduced regardless of how long mean-reversion takes.

mm_mode controls where the MM posts:
  'bestquote'  — bid at best_bid+1, ask at best_ask-1 (always inside market)
  'fast_mid'   — quote ± mm_spread around a short EWMA of mid price
                 (fast_mid_half_life controls reactivity, default 5 ticks)

Set anchor_reserve_pct=0 to disable the AR taker entirely (pure passive MM).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV7(BaseStrategy):

    # ── Fast EWMA mid (very reactive, tracks price closely) ───────────────

    def _compute_fast_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        hl = float(self.params.get("fast_mid_half_life", 5))
        alpha = 1.0 - 0.5 ** (1.0 / max(hl, 0.1))
        prev = float(memory.get("_fast_mid", mid))
        v = alpha * mid + (1.0 - alpha) * prev
        memory["_fast_mid"] = v
        return v

    # ── Slow AR model (identical to v6b inv_protected) ────────────────────

    def _update_slow_ar(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float]:
        """Returns (fair_value, anchor_ema, ar_momentum, dev_smooth)."""
        # Smoothed mid
        ms_hl = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        # Anchor — inv_protected: freeze when |pos| >= threshold × limit
        anchor_price = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.005))
        anchor_ema = float(memory.get("_anchor_ema", anchor_price))
        limit = self.position_limit()
        pos_thr = float(self.params.get("anchor_pos_threshold", 0.2))
        if limit > 0 and abs(position) < limit * pos_thr:
            anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
        memory["_anchor_ema"] = anchor_ema

        # AR momentum
        ar_hl = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        ar_mom = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        # Fair value and deviation
        ar_gain = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev = mid_s - fair_value
        dev_hl = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s = float(memory.get("_dev_smooth", raw_dev))
        dev_s = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s

        return fair_value, anchor_ema, ar_mom, dev_s

    # ── Anchor AR takers (limited to ±anchor_limit slot) ─────────────────

    def _anchor_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        anchor_limit: int,
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int, int]:
        """Returns (orders, remaining_buy_cap, remaining_sell_cap, bought, sold)."""
        if anchor_limit <= 0:
            return [], buy_cap, sell_cap, 0, 0

        take_edge = float(self.params.get("ar_taker_edge", 12.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.3))
        taker_size = max(1, int(taker_size_pct * self.position_limit()))

        # Remaining capacity within the anchor slot
        # anchor can hold positions in [-anchor_limit, +anchor_limit]
        anchor_sell_room = max(0, anchor_limit + position)   # can sell until position = -anchor_limit
        anchor_buy_room  = max(0, anchor_limit - position)   # can buy until position = +anchor_limit

        orders: List[Order] = []
        bought = sold = 0

        # AR buy (price well below fair value)
        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fair_value - take_edge or buy_cap <= 0 or anchor_buy_room <= 0:
                break
            avail = -order_depth.sell_orders[ask_p]
            qty = min(avail, buy_cap, taker_size, anchor_buy_room)
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_cap -= qty
                anchor_buy_room -= qty
                bought += qty

        # AR sell (price well above fair value)
        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fair_value + take_edge or sell_cap <= 0 or anchor_sell_room <= 0:
                break
            avail = order_depth.buy_orders[bid_p]
            qty = min(avail, sell_cap, taker_size, anchor_sell_room)
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap -= qty
                anchor_sell_room -= qty
                sold += qty

        return orders, buy_cap, sell_cap, bought, sold

    # ── Inventory-adaptive passive MM (both sides) ────────────────────────

    def _mm_passive(
        self,
        book: BookSnapshot,
        fast_mid: float,
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Returns (orders, bid_qty_placed, ask_qty_placed)."""
        limit = self.position_limit()
        mm_mode = self.params.get("mm_mode", "bestquote")
        base_size = int(self.params.get("mm_base_size", 20))

        # Inventory-adaptive sizing: long → push asks, short → push bids
        inv_ratio = position / max(1, limit)   # clamped implicitly by position_limit
        bid_size = max(0, int(base_size * (1.0 - inv_ratio)))
        ask_size = max(0, int(base_size * (1.0 + inv_ratio)))

        # Quote prices
        if mm_mode == "bestquote":
            bid_px = (book.best_bid + 1) if book.best_bid is not None else int(fast_mid) - 1
            ask_px = (book.best_ask - 1) if book.best_ask is not None else int(fast_mid) + 1
        else:   # "fast_mid"
            mm_spread = int(self.params.get("mm_spread", 1))
            bid_px = int(fast_mid) - mm_spread
            ask_px = int(fast_mid) + mm_spread
            # Don't post below best_bid or above best_ask (would be away from market)
            if book.best_bid is not None:
                bid_px = max(bid_px, book.best_bid)
            if book.best_ask is not None:
                ask_px = min(ask_px, book.best_ask)

        # Prevent self-crossing (happens when market spread ≤ 2 and we improve both sides)
        if bid_px >= ask_px:
            bid_px = book.best_bid if book.best_bid is not None else int(fast_mid) - 1
            ask_px = book.best_ask if book.best_ask is not None else int(fast_mid) + 1
            if bid_px >= ask_px:
                bid_px = int(fast_mid) - 1
                ask_px = int(fast_mid) + 1

        # Cap at remaining capacity
        bid_qty = min(bid_size, buy_cap)
        ask_qty = min(ask_size, sell_cap)

        orders: List[Order] = []
        if bid_qty > 0:
            orders.append(Order(self.product, bid_px, bid_qty))
        if ask_qty > 0:
            orders.append(Order(self.product, ask_px, -ask_qty))

        return orders, bid_qty, ask_qty

    # ── Main entry ────────────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        mid = book.mid_price
        if mid is None:
            return [], 0

        limit = self.position_limit()
        fast_mid = self._compute_fast_mid(float(mid), memory)
        fair_value, anchor_val, ar_mom, dev = self._update_slow_ar(float(mid), position, memory)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Component 1: anchor AR takers (limited to anchor budget)
        anchor_reserve_pct = float(self.params.get("anchor_reserve_pct", 0.2))
        anchor_limit = int(anchor_reserve_pct * limit)

        taker_orders, buy_cap, sell_cap, t_bought, t_sold = self._anchor_takers(
            order_depth, fair_value, anchor_limit, position, buy_cap, sell_cap,
        )

        # Component 2: fast passive MM on both sides (uses remaining capacity)
        mm_orders, mm_bid_qty, mm_ask_qty = self._mm_passive(
            book, fast_mid, position, buy_cap, sell_cap,
        )

        all_orders = taker_orders + mm_orders

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":       position,
                "mid":            round(float(mid), 2),
                "fast_mid":       round(fast_mid, 2),
                "FairValue":      round(fair_value, 2),
                "Anchor":         round(anchor_val, 2),
                "DevSmooth":      round(dev, 3),
                "ar_mom":         round(ar_mom, 4),
                "taker_buy":      t_bought,
                "taker_sell":     t_sold,
                "mm_bid_qty":     mm_bid_qty,
                "mm_ask_qty":     mm_ask_qty,
                "anchor_limit":   anchor_limit,
            },
        )

        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))  is not None: out["FairValue"]    = float(v)
        if (v := memory.get("_dev_smooth"))  is not None: out["DevSmooth"]    = float(v)
        if (v := memory.get("_anchor_ema"))  is not None: out["Anchor"]       = float(v)
        if (v := memory.get("_ar_momentum")) is not None: out["ar_mom"]       = float(v)
        if (v := memory.get("_fast_mid"))    is not None: out["fast_mid"]     = float(v)
        # anchor_limit is constant per session — expose so position chart can draw reference lines
        out["anchor_limit"] = float(int(
            float(self.params.get("anchor_reserve_pct", 0.2)) * self.position_limit()
        ))
        return out
