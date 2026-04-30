"""
Cross-Group Trend Following — A2

Uses the EMA of an external product group's average price (vs session start)
as the directional signal for the target product.

Motivation: SLEEP_POD avg corr(GALAXY_SOUNDS avg) = 86% across training days.
When SP group trends up, GS products (DARK_MATTER, BLACK_HOLES) also trend up.
Using the SP group EMA as a cross-group signal is more robust than the product's
own EMA for GS products that have smaller or noisier individual moves.

Optionally, a second (inverted) group can be used as confirmation:
- signal2_products (ROBOT): RB trends DOWN when SP trends UP.
  Combined signal (SP up AND RB down) = strong buy for GS products.

Signal states:
  BULL  : sp_ema > signal_threshold  (AND rb_ema < -signal2_threshold if second group used)
  BEAR  : sp_ema < -signal_threshold (AND rb_ema > signal2_threshold)
  NEUTRAL: neither

Behavior:
  BULL  : enter LONG at best_ask (taker), passive bid only
  BEAR  : enter SHORT at best_bid (taker), passive ask only
  NEUTRAL: two-sided passive MM (naive_mm behavior), no taker entry

Params:
    signal_products    : list of product symbols forming the signal group
    signal2_products   : list of product symbols for inverted confirmation group (optional)
    signal_ema_hl      : EMA half-life for signal (default 100 ticks)
    signal_threshold   : deviation from start to enter (default 150)
    signal2_threshold  : threshold for second group (default 0 = disabled)
    signal_exit        : EMA level that exits a position (default signal_threshold/3)
    taker_size         : units to buy/sell aggressively on first entry (default 10)
    passive_size       : passive order size per side (default 3)
    position_limit     : max position (default 10)
    invert_signal      : bool — when True, flip bull/bear (use for anti-correlated signal groups,
                         e.g. MICROCHIP_SQUARE UP → target product DOWN)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class CrossGroupTrendA2(BaseStrategy):
    """Cross-group trend following strategy for Round 5."""

    def _group_mid(self, state: TradingState, products: List[str]) -> float | None:
        """Compute average mid price across a list of products."""
        mids = []
        for sym in products:
            od = state.order_depths.get(sym)
            if od is None:
                continue
            bids = list(od.buy_orders.keys())
            asks = list(od.sell_orders.keys())
            if bids and asks:
                mids.append((max(bids) + min(asks)) / 2.0)
        return sum(mids) / len(mids) if mids else None

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params

        signal_products = list(p["signal_products"])
        signal2_products = list(p.get("signal2_products", []))
        sp_ema_hl = float(p.get("signal_ema_hl", 100))
        sp_thr = float(p.get("signal_threshold", 150))
        sp2_thr = float(p.get("signal2_threshold", 0))
        sp_exit = float(p.get("signal_exit", sp_thr / 3))
        taker_size = int(p.get("taker_size", 10))
        passive_size = int(p.get("passive_size", 3))
        limit = int(p.get("position_limit", 10))

        mid = book.mid_price
        bb = book.best_bid
        ba = book.best_ask
        if mid is None or bb is None or ba is None:
            return [], 0

        # ── Compute SP group signal ───────────────────────────────────────────
        sp_avg = self._group_mid(state, signal_products)
        if sp_avg is None:
            return [], 0

        if "sp_start" not in memory:
            memory["sp_start"] = sp_avg

        sp_dev = sp_avg - memory["sp_start"]
        alpha = 1.0 - math.exp(-1.0 / sp_ema_hl)
        sp_ema = memory.get("sp_ema", 0.0)
        sp_ema = alpha * sp_dev + (1.0 - alpha) * sp_ema
        memory["sp_ema"] = sp_ema

        # ── Optional second (inverted) group signal ───────────────────────────
        rb_ema = None
        if signal2_products and sp2_thr > 0:
            rb_avg = self._group_mid(state, signal2_products)
            if rb_avg is not None:
                if "rb_start" not in memory:
                    memory["rb_start"] = rb_avg
                rb_dev = rb_avg - memory["rb_start"]
                rb_ema_v = memory.get("rb_ema", 0.0)
                rb_ema_v = alpha * rb_dev + (1.0 - alpha) * rb_ema_v
                memory["rb_ema"] = rb_ema_v
                rb_ema = rb_ema_v

        # ── Classify signal regime ────────────────────────────────────────────
        sp2_bull = rb_ema is None or rb_ema < -sp2_thr
        sp2_bear = rb_ema is None or rb_ema > sp2_thr

        is_bull = sp_ema > sp_thr and sp2_bull
        is_bear = sp_ema < -sp_thr and sp2_bear
        is_exit_bull = sp_ema < sp_exit
        is_exit_bear = sp_ema > -sp_exit

        # Flip bull/bear when signal is anti-correlated with target product
        if bool(p.get("invert_signal", False)):
            is_bull, is_bear = is_bear, is_bull
            is_exit_bull, is_exit_bear = is_exit_bear, is_exit_bull

        buy_room = limit - position
        sell_room = limit + position
        orders: List[Order] = []

        # ── Taker: entry on regime start ──────────────────────────────────────
        if position == 0:
            if is_bull and buy_room > 0:
                qty = min(taker_size, buy_room)
                orders.append(Order(self.product, int(ba), qty))
                buy_room -= qty
            elif is_bear and sell_room > 0:
                qty = min(taker_size, sell_room)
                orders.append(Order(self.product, int(bb), -qty))
                sell_room -= qty

        # ── Taker: exit when signal reverses ─────────────────────────────────
        elif position > 0 and is_exit_bull:
            qty = min(position, sell_room)
            orders.append(Order(self.product, int(bb), -qty))
            sell_room -= qty
            position -= qty  # update for passive logic below
        elif position < 0 and is_exit_bear:
            qty = min(-position, buy_room)
            orders.append(Order(self.product, int(ba), qty))
            buy_room -= qty
            position += qty

        # ── Passive MM overlay ────────────────────────────────────────────────
        if passive_size > 0 and bb is not None and ba is not None:
            bid_px = bb + 1
            ask_px = ba - 1
            if bid_px < ask_px:
                if is_bull or (not is_bear):
                    # post bid in bull or neutral
                    if buy_room > 0:
                        orders.append(Order(self.product, int(bid_px), min(passive_size, buy_room)))
                if is_bear or (not is_bull):
                    # post ask in bear or neutral
                    if sell_room > 0:
                        orders.append(Order(self.product, int(ask_px), -min(passive_size, sell_room)))

        return orders, 0
