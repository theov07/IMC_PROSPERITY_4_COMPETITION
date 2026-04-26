"""velvet_strat_v2 — Consolidated VELVETFRUIT + VEV option strategy (v2).

Two classes, one file. Everything you need to understand the strategy is here.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CLASS 1 — VelvetMMV2  (use for VELVETFRUIT_EXTRACT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Penny-improve passive market maker (best_bid+1 / best_ask-1).
  Inventory-adaptive sizing: bid_size shrinks when long, ask_size shrinks when short.
  Hard stop: when |pos| >= 85% of limit, stop quoting the inventory-increasing side.

  Optional delta hedge (use_delta_hedge=True):
    VEVOptionMMV2 writes net option delta to shared["vev_total_delta"] each tick.
    VelvetMMV2 treats (position + vev_total_delta) as the "effective position" for
    sizing → when long calls, the MM naturally leans toward selling VELVETFRUIT,
    creating an implicit partial delta hedge.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CLASS 2 — VEVOptionMMV2  (use for VEV option strikes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Passive penny-improve MM on selected strikes. Logic per strike:

  VEV_4000  deep ITM (S≈5250, K=4000, delta≈1.0)
            → symmetric MM: bid AND ask at ±1 tick.
            → Why: 20-tick market spread × 333-351 trades/day = pure spread capture.
            → PnL source: we capture half the spread on both sides (not directional).

  VEV_5200  moderately OTM (delta≈0.65)
  VEV_5300  OTM (delta≈0.44)     ← best gamma-theta ratio per analysis
  VEV_5400  OTM (delta≈0.32)
            → bid-heavy MM: bid at best_bid+1, ask at best_ask+ask_offset (wide).
            → Why wide ask: market participants systematically sell OTM calls;
              we accumulate long positions passively at zero spread cost.
            → PnL source: long calls appreciate when VELVETFRUIT rises (days 1, 2).

  Skipped strikes and reasons:
  VEV_4500  → 0-1 trade/day, not worth the position limit
  VEV_5000  → 0 historical trades in data (illiquid)
  VEV_5100  → 0 historical trades in data (illiquid)
  VEV_5500  → marginally negative (-20 over 3 days)
  VEV_6000  → mid=0.5 (essentially worthless)
  VEV_6500  → mid=0.5 (essentially worthless)

  TTE (Time to Expiry) — correctly set per backtest day:
  Day 0 → initial TTE = 8d  (historical_tte_by_day param)
  Day 1 → initial TTE = 7d
  Day 2 → initial TTE = 6d
  Live  → tte_days_initial = 5d (set explicitly in config)
  TTE decreases within each day (timestamp / 1_000_000 days consumed per day).

  Delta sharing: at every tick, VEVOptionMMV2 accumulates position × call_delta into
  shared["vev_total_delta"]. VelvetMMV2 reads this for the implicit delta hedge.
  The submission wrapper resets vev_total_delta=0 at the start of each tick so
  multiple VEV strikes accumulate cleanly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Key config params:
  VelvetMMV2:
    maker_size_base_pct   fraction of position_limit used as base quote size (0.30)
    pct_kept_for_takers   hard-stop reserve fraction (0.15 → stop at 85% of limit)
    mid_smooth_window     EWMA window for tracking mid (50)
    mid_smooth_half_life  EWMA half-life in ticks (20)
    use_delta_hedge       read vev_total_delta from shared for implicit hedge (True)

  VEVOptionMMV2:
    strike                option strike K (required)
    tte_days_initial      TTE at live session start (5.0)
    historical_tte_by_day backtest day→TTE map {0:8, 1:7, 2:6}
    ticks_per_day         used to scale realized vol and TTE (10000)
    ts_increment          timestamp granularity (100)
    underlying_symbol     "VELVETFRUIT_EXTRACT"
    maker_size_bid        units quoted on the bid side
    maker_size_ask        units quoted on the ask side (small → accumulate longs)
    min_quote_price       skip quoting when mid < this (avoids 0.5-tick garbage)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_delta, call_price
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


# ══════════════════════════════════════════════════════════════════════════════
#  CLASS 1 — VELVETFRUIT_EXTRACT market maker
# ══════════════════════════════════════════════════════════════════════════════

class VelvetMMV2(BaseStrategy):
    """Penny-improve passive MM for VELVETFRUIT_EXTRACT with optional delta hedge."""

    def _compute_quote_prices(
        self, book: BookSnapshot
    ) -> Tuple[Optional[int], Optional[int]]:
        bid = (book.best_bid + 1) if book.best_bid is not None else None
        ask = (book.best_ask - 1) if book.best_ask is not None else None
        if bid is not None and ask is not None and bid >= ask:
            ask = bid + 1
        return bid, ask

    def _compute_sizes(self, effective_pos: int, limit: int) -> Tuple[float, float]:
        """Inventory-adaptive sizing using effective_pos (real pos + option delta).

        When long options (vev_delta>0), effective_pos > real_pos, so bid_size
        shrinks and ask_size grows → MM naturally leans toward selling VELVETFRUIT,
        partially offsetting the long call delta.
        """
        base     = float(self.params.get("maker_size_base_pct", 0.30)) * limit
        bid_size = max(0.0, base * (1.0 - effective_pos / limit))
        ask_size = max(0.0, base * (1.0 + effective_pos / limit))
        return bid_size, ask_size

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
    ) -> List[Order]:
        """Emit passive bid/ask with hard inventory stop at (1 - pct_kept) × limit."""
        quote_buy  = min(buy_cap,  max(0, int(bid_size)))
        quote_sell = min(sell_cap, max(0, int(ask_size)))

        inv_abs   = abs(position) / float(limit) if limit else 0.0
        hard_stop = 1.0 - float(self.params.get("pct_kept_for_takers", 0.15))
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
        return orders

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
                return [], 0

        raw_mid = book.mid_price or float(book.best_bid or book.best_ask or 0)
        mid = raw_mid if raw_mid else memory.get("_last_mid", 0.0)
        if raw_mid:
            memory["_last_mid"] = raw_mid

        self._smooth_mid(mid, memory)   # tracks mid for dashboard

        limit   = self.position_limit()
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── Delta hedge: read net option delta published by VEVOptionMMV2 ──────
        # When use_delta_hedge=True, treat (position + option_delta) as effective
        # inventory. Long calls (vev_delta>0) make MM lean toward selling VELVETFRUIT.
        if bool(self.params.get("use_delta_hedge", True)):
            vev_delta = float(memory.get("_shared", {}).get("vev_total_delta", 0.0))
        else:
            vev_delta = 0.0
        effective_pos = position + int(round(vev_delta))

        bid_price, ask_price = self._compute_quote_prices(book)
        bid_size, ask_size   = self._compute_sizes(effective_pos, limit)

        orders = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size,
            buy_cap, sell_cap, position, limit,
        )

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position":    position,
                "eff_pos":     effective_pos,
                "vev_delta":   round(vev_delta, 1),
                "mid_smooth":  round(memory.get("mid_smoothed", mid), 2),
                "bid_size":    int(bid_size),
                "ask_size":    int(ask_size),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        return out


# ══════════════════════════════════════════════════════════════════════════════
#  CLASS 2 — VEV option market maker
# ══════════════════════════════════════════════════════════════════════════════

class VEVOptionMMV2(BaseStrategy):
    """Passive penny-improve option MM for selected VEV call strikes."""

    # ── Time to expiry ────────────────────────────────────────────────────────

    def _resolve_tte(self, state: TradingState) -> float:
        """Return current TTE in days.

        Uses historical_tte_by_day to pick the correct initial TTE per backtest day:
          Day 0 → 8d, Day 1 → 7d, Day 2 → 6d.
        Then subtracts elapsed time within the day based on current timestamp.
        In live submission, falls back to tte_days_initial (default 5.0).
        """
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(self.params.get("tte_days_initial", 5.0)),
            self.params.get("historical_tte_by_day"),
        )
        ts_per_day = timestamp_units_per_day_from_params(self.params)
        T = time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_per_day)
        return max(0.01, T)

    # ── Quote prices ──────────────────────────────────────────────────────────

    def _compute_quotes(
        self, book: BookSnapshot
    ) -> Tuple[Optional[int], Optional[int]]:
        """Penny-improve bid (best_bid+1). Ask offset controlled by ask_offset param.

        ask_offset=1  → best_ask-1 (symmetric, inside spread — for VEV_4000)
        ask_offset=10 → best_ask+9 (wide ask, rarely filled — for OTM accumulation)
        """
        ask_offset = int(self.params.get("ask_offset", 1))

        bid_px: Optional[int] = None
        ask_px: Optional[int] = None

        if book.best_bid is not None:
            bid_px = book.best_bid + 1
        if book.best_ask is not None:
            ask_px = book.best_ask - 1 + ask_offset   # 1→inside spread, 10→far outside
            ask_px = max(ask_px, 1)

        # Prevent bid from crossing existing ask
        if bid_px is not None and book.best_ask is not None and bid_px >= book.best_ask:
            bid_px = book.best_ask - 1
        if bid_px is not None and ask_px is not None and ask_px <= bid_px:
            ask_px = bid_px + 1

        return bid_px, ask_px

    # ── Passive quoting ───────────────────────────────────────────────────────

    def _post_passive(
        self,
        bid_px: Optional[int],
        ask_px: Optional[int],
        buy_cap: int,
        sell_cap: int,
    ) -> List[Order]:
        size_bid = int(self.params.get("maker_size_bid", 20))
        size_ask = int(self.params.get("maker_size_ask", 20))
        orders: List[Order] = []
        if bid_px is not None and bid_px > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(size_bid, buy_cap)))
        if ask_px is not None and ask_px > 0 and sell_cap > 0 and size_ask > 0:
            orders.append(Order(self.product, ask_px, -min(size_ask, sell_cap)))
        return orders

    # ── Delta publishing ──────────────────────────────────────────────────────

    def _publish_delta(
        self,
        memory: Dict[str, Any],
        position: int,
        S: float,
        K: float,
        T: float,
    ) -> None:
        """Accumulate position × call_delta into shared["vev_total_delta"].

        VelvetMMV2 reads this each tick for the implicit delta hedge.
        The submission wrapper resets vev_total_delta=0 before the first VEV
        strategy runs, so multiple strikes accumulate cleanly.
        """
        sigma_for_delta = float(self.params.get("delta_sigma", 0.022))
        delta = call_delta(S, K, T, sigma_for_delta)
        shared = memory.get("_shared", {})
        shared["vev_total_delta"] = shared.get("vev_total_delta", 0.0) + position * delta

    # ── Spot from order book ──────────────────────────────────────────────────

    def _get_spot(self, state: TradingState) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if od is None:
            return None
        bids = od.buy_orders
        asks = od.sell_orders
        best_bid = max(bids.keys()) if bids else None
        best_ask = min(asks.keys()) if asks else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        return float(best_bid or best_ask or 0) or None

    # ── Main tick ─────────────────────────────────────────────────────────────

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

        # Skip strikes below min_quote_price (deep OTM, near-worthless)
        mid = 0.5 * (book.best_bid + book.best_ask)
        min_price = float(self.params.get("min_quote_price", 2.0))
        if mid < min_price:
            return [], 0

        T   = self._resolve_tte(state)
        K   = float(self.params["strike"])
        S   = self._get_spot(state)

        # Publish delta for VELVETFRUIT hedge (even before ordering)
        if S is not None:
            self._publish_delta(memory, position, S, K, T)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_px, ask_px = self._compute_quotes(book)
        orders = self._post_passive(bid_px, ask_px, buy_cap, sell_cap)

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        return {}
