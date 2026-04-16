"""Penny-improve market maker with inventory-adaptive level stepping.

Philosophy:
  - Default: always penny-improve both sides (best_bid+1 / best_ask-1)
  - Level stepping: when |position| >= inv_step_threshold * limit,
    back off the inventory-increasing side to level 2 (join best instead
    of improving) while keeping level 1 on the reducing side.
  - Taker orders: sweep aggressively when ask_p <= mid_smooth - take_edge
    or bid_p >= mid_smooth + take_edge.
  - Gap exploit: clear a thin L1 when the gap to L2 is large, then let
    normal passive quoting re-enter cheaply just above the new best.
  - Sizing: inventory-adaptive (same logic as avellaneda_stoikov).

Key params (all configurable via config.py):
  inv_step_threshold        — fraction of limit at which bid/ask steps to L2 (default 0.8)
  take_edge                 — min edge vs mid_smooth to trigger a taker order (default 1.0)
  maker_size_base_pct       — base passive quote size as % of position limit (default 0.2)
  pct_kept_for_takers       — fraction of remaining capacity reserved for takers (default 0.2)
  gap_trigger_min           — min tick gap L1→L2 to enable gap exploit (default 10)
  gap_trigger_max_vol_pct   — max L1 volume as % of limit to consider "thin" (default 0.10)
  gap_trigger_confirm_ticks — consecutive ticks condition must hold before firing (default 1)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class MMFirstStrategy(BaseStrategy):

    # ── helpers ──────────────────────────────────────────────────────────

    def _compute_quote_prices(
        self,
        book: BookSnapshot,
        inventory_ratio: float,
        mid_smooth: float,
    ) -> Tuple[Optional[int], Optional[int], str]:
        """Select L1/L2 passive prices + apply crossing prevention.

        L1 (default): penny-improve — post one tick inside the market.
        L2 (high inventory): join best on the inventory-increasing side.
          Long  → back off bid to best_bid (join), keep ask at best_ask-1.
          Short → back off ask to best_ask (join), keep bid at best_bid+1.

        Returns (bid_price, ask_price, level_label).
        """
        bid_price: Optional[int] = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price: Optional[int] = (book.best_ask - 1) if book.best_ask is not None else None
        level = "L1"

        # if inventory_ratio >= step_threshold:
        #     # Long: ease off buying, stay aggressive on selling
        #     if book.best_bid is not None:
        #         bid_price = book.best_bid       # join, no improvement
        #     level = "L2"
        # elif inventory_ratio <= -step_threshold:
        #     # Short: ease off selling, stay aggressive on buying
        #     if book.best_ask is not None:
        #         ask_price = book.best_ask       # join, no improvement
        #     level = "L2"

        # Crossing prevention
        # if bid_price is not None and book.best_ask is not None:
        #     bid_price = min(bid_price, mid_smooth - 1)
        # if ask_price is not None and book.best_bid is not None:
        #     ask_price = max(ask_price, mid_smooth + 1)
        # if bid_price is not None and ask_price is not None and ask_price <= bid_price:
        #     ask_price = bid_price + 1

        return bid_price, ask_price, level

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        """Rolling z-score of mid price.

        z = (mid - rolling_mean) / rolling_std  over the last zscore_window ticks.
        Returns None until the warm-up period completes (window // 4 samples),
        or when std ~ 0 (flat price series).

        Stored values (all accessible via memory):
          memory["zscore"]    — current z  (None if not ready)
          memory["_zs_mean"]  — rolling mean (for band overlay in dashboard)
          memory["_zs_std"]   — rolling std

        Params:
          zscore_window — rolling window size (default 50)
        """
        window = int(self.params.get("zscore_window", 50))
        buf: List[float] = memory.setdefault("_zscore_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]

        if len(buf) < max(3, window // 4):
            memory["zscore"] = None
            return None

        n    = len(buf)
        mean = sum(buf) / n
        var  = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)  # sample variance
        std  = var ** 0.5

        if std < 1e-9:
            memory["zscore"] = None
            return None

        z = (mid - mean) / std
        memory["zscore"]   = z
        memory["_zs_mean"] = mean
        memory["_zs_std"]  = std
        return z

    def _zscore_size_factors(self, memory: Dict[str, Any]) -> Tuple[float, float]:
        """Return (bid_factor, ask_factor) multipliers based on the current z-score.

        Neutral  (|z| <= threshold):  both 1.0 — no adjustment.
        z >  threshold (price high):  ask_factor > 1, bid_factor < 1  (lean short).
        z < -threshold (price low):   bid_factor > 1, ask_factor < 1  (lean long).

        Scale ramps linearly with excess z beyond the threshold, capped at zscore_max_scale.

        Params:
          zscore_threshold  — |z| must exceed this to trigger scaling (default 1.0)
          zscore_size_scale — slope of scale vs excess z (default 0.5)
          zscore_max_scale  — cap on the multiplier (default 3.0)
        """
        z = memory.get("zscore")
        if z is None:
            return 1.0, 1.0

        threshold  = float(self.params.get("zscore_threshold",  1.0))
        size_scale = float(self.params.get("zscore_size_scale", 0.5))
        max_scale  = float(self.params.get("zscore_max_scale",  3.0))

        excess = max(0.0, abs(z) - threshold)
        scale  = min(max_scale, 1.0 + size_scale * excess)

        if z > threshold:
            return 1.0 / scale, scale      # lean short: boost ask, shrink bid
        if z < -threshold:
            return scale, 1.0 / scale      # lean long:  boost bid, shrink ask
        return 1.0, 1.0

    def _compute_sizes(self, position: int, limit: int) -> Tuple[float, float]:
        """Inventory-adaptive bid/ask sizes.

        bid_size shrinks when long (we're already holding enough).
        ask_size shrinks when short (we're already selling enough).

        Returns (bid_size, ask_size) as floats — callers cast to int as needed.
        """
        base = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base * (1.0 - position / limit)
        ask_size = base * (1.0 + position / limit)
        return bid_size, ask_size

    def _fire_takers(
        self,
        order_depth: OrderDepth,
        mid_smooth: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        """Emit aggressive taker orders when price vs fair-value edge is sufficient.

        Two OR-conditions trigger a taker:
          1. mid_smooth edge:    ask <= mid_smooth - take_edge  (buy)
                                 bid >= mid_smooth + take_edge  (sell)
          2. absolute threshold: ask <= taker_buy_threshold     (buy, optional)
                                 bid >= taker_sell_threshold    (sell, optional)

        Size is capped at 30% of the inventory-adaptive quote size.
        Returns (orders, remaining_buy_cap, remaining_sell_cap, buy_px_set, sell_px_set).
        """
        take_edge            = float(self.params.get("take_edge", 1.0))
        taker_buy_threshold  = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")

        orders: List[Order] = []
        taker_buy_px:  Set[int] = set()
        taker_sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= mid_smooth - take_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, int(bid_size * 0.3)) # TODO could set the threshold with zscore
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                taker_buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume     = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= mid_smooth + take_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, int(ask_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                taker_sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px

    def _reanchor_passive(
        self,
        order_depth: OrderDepth,
        bid_price: Optional[int],
        ask_price: Optional[int],
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[Optional[int], Optional[int]]:
        """Re-anchor passive prices after taker sweeps.

        The pre-computed passive price is stale once a taker sweeps that level.
        Re-anchor to the first level NOT swept by this tick's taker orders.
        """
        if taker_buy_px:
            new_best_ask = next(
                (p for p in sorted(order_depth.sell_orders) if p not in taker_buy_px),
                None,
            )
            if new_best_ask is not None:
                ask_price = new_best_ask - 1
            # else: all ask levels cleared — gap exploit will handle it

        if taker_sell_px:
            new_best_bid = next(
                (p for p in sorted(order_depth.buy_orders, reverse=True) if p not in taker_sell_px),
                None,
            )
            if new_best_bid is not None:
                bid_price = new_best_bid + 1
            # else: all bid levels cleared — gap exploit will handle it

        return bid_price, ask_price

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        limit: int,
        bid_size: float,
        ask_size: float,
        bid_price: Optional[int],
        ask_price: Optional[int],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        """Sweep a thin L1 when the gap to L2 is large.

        After clearing L1, normal passive quoting re-enters just above the new best,
        capturing the gap spread from any participant who then hits our quote.

        Mitigation: gap_trigger_confirm_ticks — only fire after the condition has
        held for N consecutive ticks, filtering transient thin levels.

        Also handles an empty book by anchoring passives far from last known best.

        Returns (orders, buy_cap, sell_cap, bid_price, ask_price).
        """
        gap_min     = float(self.params.get("gap_trigger_min", 10))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

        # Z-score gate: suppress gap exploit when price is already stretched
        # against the direction of the sweep.
        #   Bid-side = SELL → don't sell when z already strongly negative
        #   Ask-side = BUY  → don't buy  when z already strongly positive
        # z=None (warm-up) → no gate, allow through.
        z         = memory.get("zscore")
        gap_gate  = float(self.params.get("zscore_gap_gate", self.params.get("zscore_threshold", 1.0)))
        bid_z_ok  = z is None or z >= -gap_gate   # ok to sell unless price already stretched low
        ask_z_ok  = z is None or z <=  gap_gate   # ok to buy  unless price already stretched high

        orders: List[Order] = []

        if not (gap_min > 0 and gap_max_vol > 0):
            return orders, buy_cap, sell_cap, bid_price, ask_price

        # Track last known best bid/ask for empty-book anchoring
        bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        asks = sorted(order_depth.sell_orders.keys())
        if bids:
            memory["_last_best_bid"] = bids[0]
        if asks:
            memory["_last_best_ask"] = asks[0]
        last_best_bid = memory.get("_last_best_bid")
        last_best_ask = memory.get("_last_best_ask")

        # Bid side: sell into thin best bid when gap to L2 is large
        bid_gap_ok = False
        bid1 = bid2 = bid1_vol = None
        if len(bids) >= 2:
            bid1, bid2 = bids[0], bids[1]
            bid1_vol = order_depth.buy_orders[bid1]
            bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol
        # 1-level case: no L2 to measure gap against → skip aggressive clearing
        bid_streak = memory.get("_gap_bid_streak", 0)
        bid_streak = bid_streak + 1 if bid_gap_ok else 0
        memory["_gap_bid_streak"] = bid_streak
        if bid_streak >= gap_confirm and bid_gap_ok and sell_cap > 0 and bid_z_ok:
            qty = min(bid1_vol, sell_cap, int(ask_size))
            if qty > 0:
                orders.append(Order(self.product, bid1, -qty))
                sell_cap -= qty
                bid_price = (bid2 + 1) if bid2 is not None else (bid1 - int(gap_min))
        elif len(bids) == 0 and last_best_bid is not None:
            bid_price = last_best_bid - int(gap_min)

        # Ask side: buy into thin best ask when gap to L2 is large
        ask_gap_ok = False
        ask1 = ask2 = ask1_vol = None
        if len(asks) >= 2:
            ask1, ask2 = asks[0], asks[1]
            ask1_vol = -order_depth.sell_orders[ask1]
            ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol
        # 1-level case: no L2 to measure gap against → skip aggressive clearing
        ask_streak = memory.get("_gap_ask_streak", 0)
        ask_streak = ask_streak + 1 if ask_gap_ok else 0
        memory["_gap_ask_streak"] = ask_streak
        if ask_streak >= gap_confirm and ask_gap_ok and buy_cap > 0 and ask_z_ok:
            qty = min(ask1_vol, buy_cap, int(bid_size))
            if qty > 0:
                orders.append(Order(self.product, ask1, qty))
                buy_cap -= qty
                ask_price = (ask2 - 1) if ask2 is not None else (ask1 + int(gap_min))
        elif len(asks) == 0 and last_best_ask is not None:
            ask_price = last_best_ask + int(gap_min)

        return orders, buy_cap, sell_cap, bid_price, ask_price

    def _passive_quotes(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        limit: int,
    ) -> Tuple[List[Order], int, int]:
        """Size and emit passive bid/ask orders with a hard inventory stop.

        Hard stop: when |position| >= limit * (1 - pct_kept_for_takers), suppress
        the inventory-increasing side to preserve capacity for taker unwinds.

        Returns (orders, remaining_buy_cap, remaining_sell_cap) so this function
        can be called in any order relative to _fire_takers / _gap_exploit without
        risking a position-limit breach — each caller chains the returned caps into
        the next call, exactly like _fire_takers and _gap_exploit already do.
        """
        quote_buy  = min(buy_cap,  int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))

        inv_abs = abs(position) / float(limit) if limit else 0.0
        hard_stop_thr = 1.0 - float(self.params.get("pct_kept_for_takers", 0.2))
        if inv_abs >= hard_stop_thr:
            if position > 0:
                quote_buy  = 0
            elif position < 0:
                quote_sell = 0

        orders: List[Order] = []
        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))

        return orders, buy_cap - quote_buy, sell_cap - quote_sell

    def _log_taker_fills(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        this_taker_buy_px: Set[int],
        this_taker_sell_px: Set[int],
    ) -> None:
        """Detect and log taker fills by comparing own_trades against last tick's taker prices."""
        prev_taker_buy_px  = set(memory.get("_taker_buy_px",  []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        memory["_taker_buy_px"]  = list(this_taker_buy_px)
        memory["_taker_sell_px"] = list(this_taker_sell_px)

        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY",  trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                )

    # ── order construction ───────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0   # no price reference at all yet — skip tick
            # fall through with stale mid so passive anchoring still runs

        raw_mid = book.mid_price
        if raw_mid is None and book.best_bid is not None:
            raw_mid = float(book.best_bid)
        if raw_mid is None and book.best_ask is not None:
            raw_mid = float(book.best_ask)
        mid = raw_mid if raw_mid is not None else memory["_last_mid"]
        if raw_mid is not None:
            memory["_last_mid"] = raw_mid

        mid_smooth = self._smooth_mid(mid, memory)
        self._compute_zscore(mid, memory)  # result stored in memory["zscore"]

        limit     = self.position_limit()
        inventory_ratio = position / float(limit) if limit else 0.0

        # ── QUOTE LEVEL SELECTION ──────────────────────────────────────
        bid_price, ask_price, _ = self._compute_quote_prices(book, inventory_ratio, mid_smooth)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── DYNAMIC SIZING / Ideal order size ─────────────────────────────────────────────
        bid_size, ask_size = self._compute_sizes(position, limit)

        # ── Z-SCORE SIZE TILT ─────────────────────────────────────────
        bid_factor, ask_factor = self._zscore_size_factors(memory)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)

        # ── TAKER ORDERS ───────────────────────────────────────────────
        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._fire_takers(
            order_depth, mid_smooth, bid_size, ask_size, buy_cap, sell_cap
        )

        # ── GAP EXPLOIT TAKERS ─────────────────────────────────────────
        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap
        )

        # ── TAKER PASSIVE RE-ANCHOR ────────────────────────────────────
        bid_price, ask_price = self._reanchor_passive(
            order_depth, bid_price, ask_price, taker_buy_px, taker_sell_px
        )
        
        # ── PASSIVE QUOTING ────────────────────────────────────────────
        passive_orders, buy_cap, sell_cap = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit
        )

        # ── LOGGING ────────────────────────────────────────────────────
        self._log_taker_fills(state, memory, taker_buy_px, taker_sell_px)
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position":   position,
                "mid_smooth": round(mid_smooth, 2),
                "bid_size":   int(bid_size),
                "ask_size":   int(ask_size),
            },
        )

        return taker_orders + gap_orders + passive_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        return out
