"""HydrogelRobustMM — regime-aware mean-rev (aggressive default, defensive on big range).

Léo's idea: early algos like `r3_hydrogel_mean_rev` (z-skew gain=3) crushed
day 0/1 in backtest (+10,523 day 2, +44k 3-day) but had only +385 live due
to queue priority. Yet the SIGNAL was real. What if we use the aggressive
mean-rev as DEFAULT (which is great for mean-reverting days like 0/1) and
SWITCH to a defensive mode (Theo's trend_guard) once we detect the day is
high-range (like day 2)?

Regime detector based on **cumulative_range_since_session_open**:

  Day 0 cumulative range over time:
    ts=10k: +24    ts=50k: +57    ts=99k: +84
  Day 1: ts=10k: +28    ts=50k: +48    ts=99k: +66
  Day 2: ts=10k: +21    ts=50k: +79    ts=99k: +116

  By ts=50k (mid-session), range > 70 cleanly identifies day 2.
  Days 0/1 stay below 70 for most of live window.

Strategy:

  Phase 1 (range_so_far < range_threshold): AGGRESSIVE mean-rev
    - Bigger maker_size (30 vs Theo's 24)
    - Bigger signal_boost (24 vs Theo's 12)
    - Lower quote_threshold (4 vs 6, fires earlier on |dev|)
    - Smaller pos_gate (10) to keep position contained while aggressive
    - Trend_guard relaxed (8 vs 6) to fire signal more often

  Phase 2 (range_so_far ≥ range_threshold): DEFENSIVE (Theo's exact logic)
    - Theo's defaults: maker 24, signal_boost 12, threshold 6, trend_guard 6
    - Once defensive, STAY defensive for the rest of the session (don't flip-flop)

Plus Léo's session_drift_bias (lean short in first 1000 ticks) — applied
only in aggressive mode where it helps. Removed in defensive mode where
the high-range day might not be bearish.

Plus inventory skew (Theo's standard 0.4 / 0.3 / 20 boost), trend_guard
suppresses one-sided quoting when |fast_ema - slow_ema| ≥ guard.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelRobustMMStrategy(BaseStrategy):
    """Aggressive mean-rev by default; defensive once cumulative range too big."""

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

        # ── Track session range (cumulative max/min since open) ──────────
        session_max = memory.get("_session_max", mid)
        session_min = memory.get("_session_min", mid)
        session_max = max(session_max, mid)
        session_min = min(session_min, mid)
        memory["_session_max"] = session_max
        memory["_session_min"] = session_min
        cum_range = session_max - session_min
        memory["_cum_range"] = cum_range

        # ── Dual EMA + trend ─────────────────────────────────────────────
        ema = memory.get("ema", mid)
        fast_ema = memory.get("fast_ema", mid)
        ema = p["ema_alpha"] * mid + (1 - p["ema_alpha"]) * ema
        fast_ema = p["fast_ema_alpha"] * mid + (1 - p["fast_ema_alpha"]) * fast_ema
        deviation = mid - ema
        trend = fast_ema - ema
        memory["ema"] = ema
        memory["fast_ema"] = fast_ema
        memory["_dev"] = deviation
        memory["_trend"] = trend

        # ── Regime: aggressive (default) → defensive (sticky once triggered) ──
        was_defensive = bool(memory.get("_defensive", False))
        is_defensive = was_defensive or (cum_range >= p["range_threshold"])
        memory["_defensive"] = is_defensive
        regime = "defensive" if is_defensive else "aggressive"
        memory["_regime"] = regime

        rp = self._regime_params(regime, p)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._quote_sizes(position, deviation, trend, rp)

        # Drift bias only in aggressive mode (defensive mode = no overrides)
        if regime == "aggressive":
            bias = self._session_drift_bias(state, p)
            if bias > 0:
                bid_size = max(0, bid_size - bias)
                ask_size = ask_size + bias if ask_size > 0 else ask_size
            elif bias < 0:
                bid_size = bid_size + (-bias)
                ask_size = max(0, ask_size + bias)
            memory["_session_bias"] = bias
        else:
            memory["_session_bias"] = 0

        orders: List[Order] = []
        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            sell_cap -= qty

        # Tiny taker (Theo style, regime-adjusted threshold)
        take = self._take_order(state, book, position, deviation, trend, memory, buy_cap, sell_cap, rp)
        if take is not None:
            orders.append(take)

        return orders, 0

    @staticmethod
    def _regime_params(regime: str, p: Dict[str, Any]) -> Dict[str, Any]:
        if regime == "aggressive":
            return {
                "maker_size": p["agg_maker_size"],
                "min_maker_size": p["min_maker_size"],
                "quote_threshold": p["agg_quote_threshold"],
                "max_signal_size_boost": p["agg_max_signal_size_boost"],
                "trend_guard": p["agg_trend_guard"],
                "signal_pos_gate": p["agg_signal_pos_gate"],
                "inventory_reduce_per_unit": p["inventory_reduce_per_unit"],
                "inventory_unwind_per_unit": p["inventory_unwind_per_unit"],
                "max_unwind_boost": p["max_unwind_boost"],
                "take_threshold": p["agg_take_threshold"],
                "take_size": p["take_size"],
                "take_cooldown_ts": p["take_cooldown_ts"],
            }
        # Defensive — Theo's exact params
        return {
            "maker_size": p["def_maker_size"],
            "min_maker_size": p["min_maker_size"],
            "quote_threshold": p["def_quote_threshold"],
            "max_signal_size_boost": p["def_max_signal_size_boost"],
            "trend_guard": p["def_trend_guard"],
            "signal_pos_gate": p["def_signal_pos_gate"],
            "inventory_reduce_per_unit": p["inventory_reduce_per_unit"],
            "inventory_unwind_per_unit": p["inventory_unwind_per_unit"],
            "max_unwind_boost": p["max_unwind_boost"],
            "take_threshold": p["def_take_threshold"],
            "take_size": p["take_size"],
            "take_cooldown_ts": p["take_cooldown_ts"],
        }

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, book.best_bid + 1)
        return bid, ask

    def _quote_sizes(
        self,
        position: int,
        deviation: float,
        trend: float,
        rp: Dict[str, Any],
    ) -> Tuple[int, int]:
        maker = rp["maker_size"]
        min_size = rp["min_maker_size"]
        quote_thr = rp["quote_threshold"]
        signal_boost = rp["max_signal_size_boost"]
        trend_guard = rp["trend_guard"]
        pos_gate = rp["signal_pos_gate"]
        reduce_per = rp["inventory_reduce_per_unit"]
        unwind_per = rp["inventory_unwind_per_unit"]
        unwind_boost = rp["max_unwind_boost"]

        bid_size = maker
        ask_size = maker

        if abs(trend) < trend_guard:
            if deviation > quote_thr and position > -pos_gate:
                bid_size = 0
                ask_size = maker + min(signal_boost, int(abs(deviation) // 4))
            elif deviation < -quote_thr and position < pos_gate:
                ask_size = 0
                bid_size = maker + min(signal_boost, int(abs(deviation) // 4))

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

    def _session_drift_bias(self, state: TradingState, p: Dict[str, Any]) -> int:
        bias = int(p.get("session_drift_bias", 0))
        if bias == 0:
            return 0
        ts = int(state.timestamp)
        early = int(p["session_bias_strong_until_ts"])
        fade = int(p["session_bias_fade_until_ts"])
        if ts < early:
            return bias
        elif ts < fade:
            return int(bias * (1.0 - (ts - early) / (fade - early)))
        return 0

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
        rp: Dict[str, Any],
    ) -> Optional[Order]:
        threshold = rp["take_threshold"]
        trend_guard = rp["trend_guard"]
        pos_gate = rp["signal_pos_gate"]
        cooldown = rp["take_cooldown_ts"]
        size = rp["take_size"]
        last_ts = int(memory.get("last_take_ts", -10 ** 9))
        if int(state.timestamp) - last_ts < cooldown:
            return None
        if abs(trend) >= trend_guard:
            return None
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

    def _read_params(self) -> Dict[str, Any]:
        p = self.params
        return {
            # Common
            "ema_alpha": float(p.get("ema_alpha", 0.008)),
            "fast_ema_alpha": float(p.get("fast_ema_alpha", 0.03)),
            "min_maker_size": int(p.get("min_maker_size", 3)),
            "tighten_ticks": int(p.get("tighten_ticks", 1)),
            "inventory_reduce_per_unit": float(p.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(p.get("inventory_unwind_per_unit", 0.30)),
            "max_unwind_boost": int(p.get("max_unwind_boost", 20)),
            "take_size": int(p.get("take_size", 1)),
            "take_cooldown_ts": int(p.get("take_cooldown_ts", 2000)),
            # Regime detector
            "range_threshold": float(p.get("range_threshold", 70.0)),
            # Aggressive params (default mode — old r3_hydrogel_mean_rev style)
            "agg_maker_size": int(p.get("agg_maker_size", 30)),
            "agg_quote_threshold": float(p.get("agg_quote_threshold", 4.0)),
            "agg_max_signal_size_boost": int(p.get("agg_max_signal_size_boost", 24)),
            "agg_trend_guard": float(p.get("agg_trend_guard", 8.0)),
            "agg_signal_pos_gate": int(p.get("agg_signal_pos_gate", 12)),
            "agg_take_threshold": float(p.get("agg_take_threshold", 8.0)),
            # Defensive params (Theo's exact values)
            "def_maker_size": int(p.get("def_maker_size", 24)),
            "def_quote_threshold": float(p.get("def_quote_threshold", 6.0)),
            "def_max_signal_size_boost": int(p.get("def_max_signal_size_boost", 12)),
            "def_trend_guard": float(p.get("def_trend_guard", 6.0)),
            "def_signal_pos_gate": int(p.get("def_signal_pos_gate", 12)),
            "def_take_threshold": float(p.get("def_take_threshold", 12.0)),
            # Drift bias (aggressive only)
            "session_drift_bias": int(p.get("session_drift_bias", 4)),
            "session_bias_strong_until_ts": int(p.get("session_bias_strong_until_ts", 100_000)),
            "session_bias_fade_until_ts": int(p.get("session_bias_fade_until_ts", 300_000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("ema", "fast_ema", "_dev", "_trend", "_cum_range", "_session_bias"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        if (r := memory.get("_regime")) is not None:
            out["regime_code"] = {"aggressive": 0, "defensive": 1}.get(r, -1)
        return out
