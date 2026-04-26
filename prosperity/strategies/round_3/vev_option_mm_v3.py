"""VEVOptionMMV3 — Tibo's 2-sided passive MM for far-OTM options (VEV_5200/5300/5400).

Key insight from Tibo's v28 backtest:
  "The passive accumulation strategy outperforms GammaScalp for far-OTM options
   by ~6k on 3-day backtest" — and crucially allows the strategy to REDUCE position
   via passive ask fills, instead of being stuck long like target_qty gamma scalp.

Strategy:
  - Bid: penny-improve (size 20)
  - Ask: WIDE (best_ask + ask_offset_neutral=10, size 5)
  - Z-score gating with 'none' mode = default behavior (no signal exec)
  - prevent_crossing for tight 1-tick spreads (e.g. VEV_5400)

This complements gamma_scalp_zgated: the latter is target_qty long-only (drag on
far OTM); this one allows occasional sells to release inventory.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy
from prosperity.options.black_scholes import call_delta
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)


class VEVOptionMMV3Strategy(BaseStrategy):
    """Tibo's 2-sided passive MM with z-score gating (default mode='none')."""

    # ── Z-score (self-contained from VELVET spot) ──────────────────────────
    def _compute_zscore(self, state: TradingState, memory: Dict[str, Any]) -> Optional[float]:
        S = self._get_spot(state)
        if S is None:
            return None
        window = int(self.params.get("zscore_window", 500))
        buf: List[float] = memory.setdefault("_velvet_buf", [])
        buf.append(S)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (S - mean) / std

    def _signal_state(self, z: Optional[float]) -> str:
        if z is None:
            return "neutral"
        threshold = float(self.params.get("zscore_threshold", 1.0))
        if z < -threshold:
            return "cheap"
        if z > threshold:
            return "expensive"
        return "neutral"

    def _quote_bid(self, book: BookSnapshot, signal: str, mode: str) -> Optional[int]:
        if book.best_bid is None:
            return None
        if mode in ("bid_only", "both"):
            if signal == "cheap" and bool(self.params.get("allow_taker", True)):
                return book.best_ask if book.best_ask is not None else book.best_bid + 1
            if signal == "expensive":
                return None  # skip bid when expensive
        bid = book.best_bid + 1
        if bool(self.params.get("prevent_crossing", False)):
            if book.best_ask is not None and bid >= book.best_ask:
                bid = book.best_ask - 1
        return bid

    def _quote_ask(self, book: BookSnapshot, signal: str, mode: str) -> Optional[int]:
        if book.best_ask is None:
            return None
        neutral_offset = int(self.params.get("ask_offset_neutral", 10))
        if mode in ("ask_adapt", "both"):
            if signal == "expensive":
                return book.best_ask - 1
            if signal == "cheap":
                return book.best_ask + neutral_offset + 5
        return book.best_ask - 1 + neutral_offset

    def _resolve_tte(self, state: TradingState) -> float:
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(self.params.get("tte_days_initial", 5.0)),
            self.params.get("historical_tte_by_day"),
        )
        ts_per_day = timestamp_units_per_day_from_params(self.params)
        return max(0.01, time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_per_day))

    def _get_spot(self, state: TradingState) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if od is None:
            return None
        bb = max(od.buy_orders.keys()) if od.buy_orders else None
        ba = min(od.sell_orders.keys()) if od.sell_orders else None
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return float(bb or ba or 0) or None

    def _post_orders(
        self,
        bid_px: Optional[int],
        ask_px: Optional[int],
        buy_cap: int,
        sell_cap: int,
    ) -> List[Order]:
        size_bid = int(self.params.get("maker_size_bid", 20))
        size_ask = int(self.params.get("maker_size_ask", 5))
        orders: List[Order] = []
        if bid_px is not None and bid_px > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(size_bid, buy_cap)))
        if ask_px is not None and ask_px > 0 and sell_cap > 0 and size_ask > 0:
            orders.append(Order(self.product, ask_px, -min(size_ask, sell_cap)))
        return orders

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
        mid = 0.5 * (book.best_bid + book.best_ask)
        if mid < float(self.params.get("min_quote_price", 2.0)):
            return [], 0

        z = self._compute_zscore(state, memory)
        memory["_zscore"] = z
        mode = str(self.params.get("zscore_exec_mode", "none"))
        signal = self._signal_state(z)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_px = self._quote_bid(book, signal, mode)
        ask_px = self._quote_ask(book, signal, mode)

        # Safety: prevent crossing
        if bid_px is not None and ask_px is not None and ask_px <= bid_px:
            ask_px = bid_px + 1

        orders = self._post_orders(bid_px, ask_px, buy_cap, sell_cap)
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_zscore")
        return {"z_velvet": round(z, 3)} if z is not None else {}
