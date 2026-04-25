"""VelvetStratV1 — VELVETFRUIT_EXTRACT passive market maker with z-score size skew.

Philosophy:
  - VELVETFRUIT is mean-reverting at the 500-tick horizon (ACF ≈ -0.15 to -0.49).
  - Always penny-improve both sides (best_bid+1 / best_ask-1).
  - Z-score over a rolling window tilts bid/ask sizes toward the reverting side:
      mid above rolling mean → shrink bid, grow ask  (expect fall)
      mid below rolling mean → grow bid, shrink ask  (expect rise)
  - Inventory-adaptive sizing is layered on top.
  - Gap exploit and taker orders are present but off by default (set their params
    to enable for A/B testing without touching logic).

Key params (all in config.py):
  maker_size_base_pct      — base quote size as fraction of position_limit (default 0.3)
  pct_kept_for_takers      — hard stop reserve fraction (default 0.1)
  mid_smooth_window        — EWMA window for fair-value tracking (default 50)
  mid_smooth_half_life     — EWMA half-life in ticks (default 20)
  zscore_window            — rolling z-score window (default 500)
  zscore_threshold         — |z| required to start tilting (default 1.0)
  zscore_size_scale        — slope: multiplier gain per unit of excess |z| (default 2.0)
  zscore_max_scale         — cap on size multiplier (default 4.0)
  take_edge                — taker fires when ask ≤ mid_smooth - take_edge (default 999 = off)
  gap_trigger_min          — min gap L1→L2 for gap exploit (default 0 = off)
  gap_trigger_max_vol_pct  — L1 "thin" threshold as fraction of limit (default 0.10)
  gap_trigger_confirm_ticks— ticks streak before gap fires (default 2)
  OB_cleared_shift         — passive anchor shift when book side is cleared (default 10)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class VelvetStratV1(BaseStrategy):

    # ── z-score ──────────────────────────────────────────────────────────────

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        """Rolling z-score of mid over zscore_window ticks. Stored in memory['zscore']."""
        window = int(self.params.get("zscore_window", 500))
        buf: List[float] = memory.setdefault("_zscore_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]

        if len(buf) < max(3, window // 4):
            memory["zscore"] = None
            return None

        n    = len(buf)
        mean = sum(buf) / n
        var  = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
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
        """Return (bid_factor, ask_factor) multipliers.

        z >  threshold → price high, expect fall → shrink bid, grow ask.
        z < -threshold → price low, expect rise  → grow bid, shrink ask.
        Scale ramps linearly with excess |z| beyond threshold, capped at zscore_max_scale.
        """
        z = memory.get("zscore")
        if z is None:
            return 1.0, 1.0

        threshold  = float(self.params.get("zscore_threshold",  1.0))
        size_scale = float(self.params.get("zscore_size_scale", 2.0))
        max_scale  = float(self.params.get("zscore_max_scale",  4.0))

        excess = max(0.0, abs(z) - threshold)
        scale  = min(max_scale, 1.0 + size_scale * excess)

        if z > threshold:
            return 1.0 / scale, scale      # lean short: shrink bid, boost ask
        if z < -threshold:
            return scale, 1.0 / scale      # lean long:  boost bid, shrink ask
        return 1.0, 1.0

    # ── sizing ────────────────────────────────────────────────────────────────

    def _compute_sizes(self, position: int, limit: int) -> Tuple[float, float]:
        """Inventory-adaptive bid/ask sizes.

        bid_size shrinks when long (already holding enough).
        ask_size shrinks when short (already selling enough).
        """
        base     = float(self.params.get("maker_size_base_pct", 0.3)) * limit
        bid_size = base * (1.0 - position / limit)
        ask_size = base * (1.0 + position / limit)
        return max(0.0, bid_size), max(0.0, ask_size)

    # ── quote prices ──────────────────────────────────────────────────────────

    def _compute_quote_prices(
        self, book: BookSnapshot
    ) -> Tuple[Optional[int], Optional[int]]:
        """Always penny-improve both sides."""
        bid = (book.best_bid + 1) if book.best_bid is not None else None
        ask = (book.best_ask - 1) if book.best_ask is not None else None
        # Prevent crossing
        if bid is not None and ask is not None and bid >= ask:
            ask = bid + 1
        return bid, ask

    # ── taker orders ─────────────────────────────────────────────────────────

    def _fire_takers(
        self,
        order_depth: OrderDepth,
        mid_smooth: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        """Aggressive takers when price vs mid_smooth edge ≥ take_edge.

        Disabled by default (take_edge=999 in config).
        To enable: set take_edge to a real edge in ticks (e.g. 2).
        """
        take_edge            = float(self.params.get("take_edge", 999.0))
        taker_buy_threshold  = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")

        orders: List[Order] = []
        buy_px:  Set[int] = set()
        sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= mid_smooth - take_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, max(1, int(bid_size * 0.3)))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume     = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= mid_smooth + take_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, max(1, int(ask_size * 0.3)))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, buy_px, sell_px

    # ── gap exploit + re-anchor ───────────────────────────────────────────────

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
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        """Re-anchor passive prices to effective post-taker book.
        Optionally sweeps a thin L1 when gap to L2 is large.

        Disabled by default (gap_trigger_min=0 in config).
        To enable: set gap_trigger_min to e.g. 10.
        """
        gap_min     = float(self.params.get("gap_trigger_min", 0))
        shift       = float(self.params.get("OB_cleared_shift", 10))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 2))

        orders: List[Order] = []
        memory["_gap_buy_px"]  = []
        memory["_gap_sell_px"] = []

        all_bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        all_asks = sorted(order_depth.sell_orders.keys())
        if all_bids:
            memory["_last_best_bid"] = all_bids[0]
        if all_asks:
            memory["_last_best_ask"] = all_asks[0]
        last_best_bid = memory.get("_last_best_bid")
        last_best_ask = memory.get("_last_best_ask")

        remaining_bids = [p for p in all_bids if p not in taker_sell_px]
        remaining_asks = [p for p in all_asks if p not in taker_buy_px]

        gap_swept_bids: Set[int] = set()
        gap_swept_asks: Set[int] = set()

        if gap_min > 0 and gap_max_vol > 0:
            # Bid side gap
            bid_gap_ok = False
            bid1 = bid2 = bid1_vol = None
            if len(remaining_bids) >= 2:
                bid1, bid2 = remaining_bids[0], remaining_bids[1]
                bid1_vol = order_depth.buy_orders[bid1]
                bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol

            bid_streak = memory.get("_gap_bid_streak", 0)
            bid_streak = bid_streak + 1 if bid_gap_ok else 0
            memory["_gap_bid_streak"] = bid_streak

            if bid_streak >= gap_confirm and bid_gap_ok and sell_cap > 0:
                qty = min(bid1_vol, sell_cap, int(ask_size))
                if qty > 0:
                    orders.append(Order(self.product, bid1, -qty))
                    sell_cap -= qty
                    memory["_gap_sell_px"].append(bid1)
                    if qty >= bid1_vol:
                        gap_swept_bids.add(bid1)

            # Ask side gap
            ask_gap_ok = False
            ask1 = ask2 = ask1_vol = None
            if len(remaining_asks) >= 2:
                ask1, ask2 = remaining_asks[0], remaining_asks[1]
                ask1_vol = -order_depth.sell_orders[ask1]
                ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol

            ask_streak = memory.get("_gap_ask_streak", 0)
            ask_streak = ask_streak + 1 if ask_gap_ok else 0
            memory["_gap_ask_streak"] = ask_streak

            if ask_streak >= gap_confirm and ask_gap_ok and buy_cap > 0:
                qty = min(ask1_vol, buy_cap, int(bid_size))
                if qty > 0:
                    orders.append(Order(self.product, ask1, qty))
                    buy_cap -= qty
                    memory["_gap_buy_px"].append(ask1)
                    if qty >= ask1_vol:
                        gap_swept_asks.add(ask1)

        # Re-anchor to effective remaining book
        final_bids = [p for p in remaining_bids if p not in gap_swept_bids]
        final_asks = [p for p in remaining_asks if p not in gap_swept_asks]

        if final_asks:
            ask_price = final_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + int(shift)

        if final_bids:
            bid_price = final_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - int(shift)

        return orders, buy_cap, sell_cap, bid_price, ask_price

    # ── passive quoting ───────────────────────────────────────────────────────

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
        """Emit passive bid/ask with hard inventory stop.

        When |pos| ≥ limit × (1 - pct_kept_for_takers), suppress the
        inventory-increasing side to reserve room for taker unwinds.
        """
        quote_buy  = min(buy_cap,  max(0, int(bid_size)))
        quote_sell = min(sell_cap, max(0, int(ask_size)))

        inv_abs   = abs(position) / float(limit) if limit else 0.0
        hard_stop = 1.0 - float(self.params.get("pct_kept_for_takers", 0.1))
        if inv_abs >= hard_stop:
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

    # ── main tick ─────────────────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        # Skip tick with no book and no prior mid reference
        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0

        # ── Mid price ─────────────────────────────────────────────────────────
        raw_mid = book.mid_price
        if raw_mid is None:
            raw_mid = float(book.best_bid or book.best_ask)
        mid = raw_mid if raw_mid is not None else memory["_last_mid"]
        if raw_mid is not None:
            memory["_last_mid"] = raw_mid

        mid_smooth = self._smooth_mid(mid, memory)
        self._update_volatility(mid, memory)
        # self._compute_zscore(mid, memory)      # A/B: z-score — commented out

        limit           = self.position_limit()
        buy_cap         = self.buy_capacity(position)
        sell_cap        = self.sell_capacity(position)

        # ── Delta hedge from VEV options (A/B: set use_delta_hedge=True to enable) ─
        # VEV strategies (velvet_strat_v2) write their net delta to shared["vev_total_delta"].
        # When we're long calls (vev_delta > 0), we should be SHORT VELVETFRUIT to hedge.
        # We model this by treating (position + vev_delta) as our effective inventory:
        # the MM will then lean toward selling VELVETFRUIT to offset the option delta.
        if bool(self.params.get("use_delta_hedge", False)):
            vev_delta = float(memory.get("_shared", {}).get("vev_total_delta", 0.0))
        else:
            vev_delta = 0.0
        effective_pos = position + int(round(vev_delta))

        # ── Quote prices (penny-improve) ──────────────────────────────────────
        bid_price, ask_price = self._compute_quote_prices(book)

        # ── Sizes: inventory-adaptive base (uses effective_pos including hedge delta) ─
        bid_size, ask_size = self._compute_sizes(effective_pos, limit)

        # ── Z-score size tilt (A/B: comment in/out) ──────────────────────────
        # bid_factor, ask_factor = self._zscore_size_factors(memory)
        # bid_size = max(0.0, bid_size * bid_factor)
        # ask_size = max(0.0, ask_size * ask_factor)

        # ── Taker orders (off by default: take_edge=999) ──────────────────────
        taker_orders, buy_cap, sell_cap, _, _ = self._fire_takers(
            order_depth, mid_smooth, bid_size, ask_size, buy_cap, sell_cap,
        )

        # ── Gap exploit + re-anchor (A/B: comment in/out) ────────────────────
        # gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
        #     order_depth, memory, limit, bid_size, ask_size,
        #     bid_price, ask_price, buy_cap, sell_cap,
        #     taker_buy_px, taker_sell_px,
        # )
        gap_orders: list = []

        # ── Passive quoting ───────────────────────────────────────────────────
        passive_orders, buy_cap, sell_cap = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit,
        )

        # ── Log ───────────────────────────────────────────────────────────────
        z = memory.get("zscore")
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position":   position,
                "mid_smooth": round(mid_smooth, 2),
                "bid_size":   int(bid_size),
                "ask_size":   int(ask_size),
                "zscore":     round(z, 4) if z is not None else None,
            },
        )

        return taker_orders + gap_orders + passive_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        if (z := memory.get("zscore")) is not None:
            out["Z"] = float(z)
        if (s := memory.get("sigma_smoothed")) is not None:
            out["sigma"] = float(s)
        return out
