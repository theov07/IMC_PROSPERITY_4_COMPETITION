"""HydrogelReversionMM — clone of Theo's R3HydroReversionMM (live winner +920 HYDRO).

The key innovation vs our asym_mm:
  **trend_guard**: mean-reversion signal ONLY fires when |fast_ema - slow_ema| < guard.
  In strongly trending markets (|trend| >= guard), the strategy SUPPRESSES the
  one-sided mean-rev quote and lets inventory skew handle position management.

  Our asym_mm v2 fired the mean-rev signal even during day 2's slow drift down,
  so we kept trying to "buy the dip" while mid kept dropping. Theo's trend_guard
  prevents this by requiring trend = 0 for mean-rev to fire.

Differences from asym_mm:
  - Uses raw price thresholds (not z-score): quote_threshold=6 ticks, take=12 ticks
  - Dual EMA: slow (alpha=0.008), fast (alpha=0.03) — trend = fast - slow
  - trend_guard=6 ticks: signal disabled when |trend| >= 6
  - signal_pos_gate=12: don't fire signal if already at this position
  - max_signal_size_boost=12: cap on directional size
  - Standard inventory skew: 0.4 reduce wrong, 0.3 unwind, max boost 20
  - Tiny taker (size=1, cooldown=2000) at take_threshold=12

Optional `session_drift_bias` (Léo's daily-trend insight, off by default):
  HYDROGEL drifts -37 ticks on average in first 1000 ticks of session across
  days 0/1/2 (live window). Mean-reverts toward 0 by ts ~5M, then can drift
  up. When `session_drift_bias > 0`, the strategy tilts ask_size up and
  bid_size down by `session_drift_bias` units in the early-session window.
  Default OFF to match Theo's exact parameters.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelReversionMMStrategy(BaseStrategy):
    """Mean-reversion MM with trend-guard (Theo's R3HydroReversionMM)."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.mid_price is None:
            return [], 0

        p = self._read_params()
        mid = float(book.mid_price)

        # Dual EMA
        ema, fast_ema = self._update_emas(mid, memory, p)
        deviation = mid - ema
        trend = fast_ema - ema  # positive = up, negative = down

        memory["_ema"] = ema
        memory["_fast_ema"] = fast_ema
        memory["_dev"] = deviation
        memory["_trend"] = trend

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._quote_sizes(position, deviation, trend, p)

        # Optional session-drift bias (Léo's insight: first 1000 ticks bias short)
        bias = self._session_drift_bias(state, p)
        if bias > 0:  # bias short → smaller bid, larger ask
            bid_size = max(0, bid_size - bias)
            ask_size = ask_size + bias
        elif bias < 0:  # bias long → larger bid, smaller ask
            bid_size = bid_size + (-bias)
            ask_size = max(0, ask_size + bias)
        memory["_session_bias"] = bias

        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            sell_cap -= qty

        # Tiny taker overlay (Theo-style)
        take = self._take_order(state, book, position, deviation, trend, memory, buy_cap, sell_cap, p)
        if take is not None:
            orders.append(take)

        return orders, 0

    # ── Dual EMA ────────────────────────────────────────────────────────

    def _update_emas(self, mid: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Tuple[float, float]:
        slow_a = p["ema_alpha"]
        fast_a = p["fast_ema_alpha"]
        ema = memory.get("ema")
        fast_ema = memory.get("fast_ema")
        ema = mid if ema is None else slow_a * mid + (1 - slow_a) * float(ema)
        fast_ema = mid if fast_ema is None else fast_a * mid + (1 - fast_a) * float(fast_ema)
        memory["ema"] = ema
        memory["fast_ema"] = fast_ema
        return ema, fast_ema

    # ── Quote prices (penny-improve inside spread) ──────────────────────

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, book.best_bid + 1)
        return bid, ask

    # ── Quote sizes with trend-guard ────────────────────────────────────

    def _quote_sizes(
        self,
        position: int,
        deviation: float,
        trend: float,
        p: Dict[str, Any],
    ) -> Tuple[int, int]:
        maker = p["maker_size"]
        min_size = p["min_maker_size"]
        quote_thr = p["quote_threshold"]
        signal_boost = p["max_signal_size_boost"]
        trend_guard = p["trend_guard"]
        pos_gate = p["signal_pos_gate"]
        reduce_per = p["inventory_reduce_per_unit"]
        unwind_per = p["inventory_unwind_per_unit"]
        unwind_boost = p["max_unwind_boost"]

        bid_size = maker
        ask_size = maker

        # Trend-guard: only fire mean-rev signal when not strongly trending
        if abs(trend) < trend_guard:
            if deviation > quote_thr and position > -pos_gate:
                # Mid is rich vs slow EMA → expect drop → grow ASK, kill BID
                bid_size = 0
                ask_size = maker + min(signal_boost, int(abs(deviation) // 4))
            elif deviation < -quote_thr and position < pos_gate:
                # Mid is cheap → expect rise → grow BID, kill ASK
                ask_size = 0
                bid_size = maker + min(signal_boost, int(abs(deviation) // 4))

        # Inventory skew (always applied)
        if position > 0:
            bid_size = max(0, bid_size - int(position * reduce_per))
            ask_size += min(unwind_boost, int(position * unwind_per))
        elif position < 0:
            ask_size = max(0, ask_size - int(-position * reduce_per))
            bid_size += min(unwind_boost, int(-position * unwind_per))

        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size
        return max(0, bid_size), max(0, ask_size)

    # ── Session-drift bias (Léo's daily-trend insight) ──────────────────

    def _session_drift_bias(self, state: TradingState, p: Dict[str, Any]) -> int:
        """Return signed bias: >0 = lean short, <0 = lean long, 0 = neutral.

        Based on observation: HYDROGEL drifts -37 ticks on avg over first
        1000 ticks (live window). Apply short-bias in this window, fade out.
        """
        bias_strength = int(p.get("session_drift_bias", 0))
        if bias_strength == 0:
            return 0
        ts = int(state.timestamp)
        # Strong bias in first 100,000 ts (1000 ticks), fade out by 300,000 ts
        early_end = int(p.get("session_bias_strong_until_ts", 100_000))
        fade_end = int(p.get("session_bias_fade_until_ts", 300_000))
        if ts < early_end:
            return bias_strength  # full short bias
        elif ts < fade_end:
            # Linear fade
            frac = 1.0 - (ts - early_end) / (fade_end - early_end)
            return int(bias_strength * frac)
        else:
            return 0

    # ── Tiny taker (Theo-style) ─────────────────────────────────────────

    def _take_order(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        deviation: float,
        trend: float,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        threshold = p["take_threshold"]
        trend_guard = p["trend_guard"]
        pos_gate = p["signal_pos_gate"]
        cooldown = p["take_cooldown_ts"]
        size = p["take_size"]
        last_ts = int(memory.get("last_take_ts", -10 ** 9))
        if int(state.timestamp) - last_ts < cooldown:
            return None

        if abs(trend) < trend_guard:
            if deviation > threshold and position > -pos_gate and sell_cap > 0:
                qty = min(size, sell_cap, pos_gate + position)
                if qty > 0:
                    memory["last_take_ts"] = int(state.timestamp)
                    return Order(self.product, int(book.best_bid), -qty)
            if deviation < -threshold and position < pos_gate and buy_cap > 0:
                qty = min(size, buy_cap, pos_gate - position)
                if qty > 0:
                    memory["last_take_ts"] = int(state.timestamp)
                    return Order(self.product, int(book.best_ask), qty)
        return None

    # ── Params ──────────────────────────────────────────────────────────

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "ema_alpha": float(params.get("ema_alpha", 0.008)),
            "fast_ema_alpha": float(params.get("fast_ema_alpha", 0.03)),
            "maker_size": int(params.get("maker_size", 24)),
            "min_maker_size": int(params.get("min_maker_size", 3)),
            "quote_threshold": float(params.get("quote_threshold", 6.0)),
            "max_signal_size_boost": int(params.get("max_signal_size_boost", 12)),
            "trend_guard": float(params.get("trend_guard", 6.0)),
            "signal_pos_gate": int(params.get("signal_pos_gate", 12)),
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.30)),
            "max_unwind_boost": int(params.get("max_unwind_boost", 20)),
            "tighten_ticks": int(params.get("tighten_ticks", 1)),
            "take_threshold": float(params.get("take_threshold", 12.0)),
            "take_size": int(params.get("take_size", 1)),
            "take_cooldown_ts": int(params.get("take_cooldown_ts", 2000)),
            # Léo's session-drift bias (off by default to match Theo)
            "session_drift_bias": int(params.get("session_drift_bias", 0)),
            "session_bias_strong_until_ts": int(params.get("session_bias_strong_until_ts", 100_000)),
            "session_bias_fade_until_ts": int(params.get("session_bias_fade_until_ts", 300_000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ema", "_fast_ema", "_dev", "_trend", "_session_bias"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        return out
