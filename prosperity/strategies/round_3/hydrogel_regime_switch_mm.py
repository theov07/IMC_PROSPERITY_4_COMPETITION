"""HydrogelRegimeSwitchMM — adaptive regime detection on live realized vol.

Lessons from live tests:
  - theo_drift_only LIVE: +1,077 (validated baseline)
  - reversion_v2 LIVE: +982 — bypass trend_guard taker covered TOO EARLY,
    missing the bottom of the day-2 drop. Live differs from backtest.

Léo's insight: early mean-rev algos crushed it on days 0/1 (mean-reverting)
but failed on day 2 (high-vol drift). Build a strategy that detects regime
LIVE and adapts:

  Track rolling realized vol over last vol_window ticks. Classify:
    LOW_VOL:    vol < vol_low_thr  (mean-reverting day, like 0/1)
                → AGGRESSIVE mean-rev: bigger signal_boost, lower take_threshold
    HIGH_VOL:   vol > vol_high_thr (trending/volatile day, like 2)
                → DEFENSIVE: smaller maker_size, keep takers but small
    NORMAL:                          (default Theo+drift)

Regime detection cannot work in first 200 ticks (all days look identical
there — vol ~2.15 across all 3). By ts ~50000 (500 ticks) day 2's bigger
range becomes apparent (79 vs 48-57 for days 0/1). Strategy adapts mid-session.

Same trend_guard, same drift_bias as theo_drift_only — this just modulates
the AGGRESSION dial based on realized vol regime.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelRegimeSwitchMMStrategy(BaseStrategy):
    """Theo's strategy with regime-adaptive aggression based on realized vol."""

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

        # ── Dual EMA + trend (Theo's) ────────────────────────────────────
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

        # ── Realized vol over rolling window ─────────────────────────────
        vol_window = p["vol_window"]
        prev_mid = memory.get("_prev_mid", mid)
        ret = mid - prev_mid
        memory["_prev_mid"] = mid
        ret_history: List[float] = memory.get("_ret_history", [])
        ret_history.append(ret)
        if len(ret_history) > vol_window:
            ret_history = ret_history[-vol_window:]
        memory["_ret_history"] = ret_history
        if len(ret_history) >= p["min_vol_samples"]:
            mu = sum(ret_history) / len(ret_history)
            var = sum((r - mu) ** 2 for r in ret_history) / len(ret_history)
            realized_vol = var ** 0.5
        else:
            realized_vol = p["vol_baseline"]
        memory["_realized_vol"] = realized_vol

        # Classify regime
        if realized_vol < p["vol_low_thr"]:
            regime = "low_vol"
        elif realized_vol > p["vol_high_thr"]:
            regime = "high_vol"
        else:
            regime = "normal"
        memory["_regime"] = regime

        # ── Get regime-adjusted params ───────────────────────────────────
        rp = self._regime_params(regime, p)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._quote_sizes(position, deviation, trend, rp, p)

        # Léo's session-drift bias (always applied, scaled to regime)
        bias = self._session_drift_bias(state, p)
        if bias > 0:
            bid_size = max(0, bid_size - bias)
            ask_size = ask_size + bias if ask_size > 0 else ask_size
        elif bias < 0:
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

        # Taker (regime-adjusted)
        take = self._take_order(state, book, position, deviation, trend, memory, buy_cap, sell_cap, rp, p)
        if take is not None:
            orders.append(take)

        return orders, 0

    # ── Regime → param adjustment ────────────────────────────────────────

    @staticmethod
    def _regime_params(regime: str, p: Dict[str, Any]) -> Dict[str, Any]:
        """Return adjusted params per regime. Multipliers applied to base."""
        if regime == "low_vol":
            return {
                "maker_size_mult": p["low_vol_maker_mult"],         # 1.25 = +25% size
                "signal_boost_mult": p["low_vol_signal_mult"],      # 1.5  = +50% boost
                "take_threshold_mult": p["low_vol_take_thr_mult"],  # 0.8  = lower threshold (fire more)
                "take_size_mult": p["low_vol_take_size_mult"],      # 1.5  = bigger takers
            }
        elif regime == "high_vol":
            return {
                "maker_size_mult": p["high_vol_maker_mult"],        # 0.75 = -25% size
                "signal_boost_mult": p["high_vol_signal_mult"],     # 0.75 = -25% boost
                "take_threshold_mult": p["high_vol_take_thr_mult"], # 1.5  = higher threshold
                "take_size_mult": p["high_vol_take_size_mult"],     # 1.0  = same size
            }
        else:  # normal
            return {
                "maker_size_mult": 1.0,
                "signal_boost_mult": 1.0,
                "take_threshold_mult": 1.0,
                "take_size_mult": 1.0,
            }

    # ── Theo's quote sizing (regime-adjusted) ────────────────────────────

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
        p: Dict[str, Any],
    ) -> Tuple[int, int]:
        maker = int(p["maker_size"] * rp["maker_size_mult"])
        min_size = p["min_maker_size"]
        quote_thr = p["quote_threshold"]
        signal_boost = int(p["max_signal_size_boost"] * rp["signal_boost_mult"])
        trend_guard = p["trend_guard"]
        pos_gate = p["signal_pos_gate"]

        bid_size = maker
        ask_size = maker

        if abs(trend) < trend_guard:
            if deviation > quote_thr and position > -pos_gate:
                bid_size = 0
                ask_size = maker + min(signal_boost, int(abs(deviation) // 4))
            elif deviation < -quote_thr and position < pos_gate:
                ask_size = 0
                bid_size = maker + min(signal_boost, int(abs(deviation) // 4))

        # Inventory skew (always)
        reduce_per = p["inventory_reduce_per_unit"]
        unwind_per = p["inventory_unwind_per_unit"]
        unwind_boost = p["max_unwind_boost"]
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

    # ── Taker (regime-adjusted threshold + size, NO bypass) ──────────────

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
        p: Dict[str, Any],
    ) -> Optional[Order]:
        threshold = p["take_threshold"] * rp["take_threshold_mult"]
        trend_guard = p["trend_guard"]
        pos_gate = p["signal_pos_gate"]
        cooldown = p["take_cooldown_ts"]
        size_base = max(1, int(p["take_size"] * rp["take_size_mult"]))
        last_ts = int(memory.get("last_take_ts", -10 ** 9))
        if int(state.timestamp) - last_ts < cooldown:
            return None
        if abs(trend) >= trend_guard:
            return None  # NO bypass — trend_guard always honored
        if deviation > threshold and position > -pos_gate and sell_cap > 0:
            qty = min(size_base, sell_cap, pos_gate + position)
            if qty > 0:
                memory["last_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_bid), -qty)
        if deviation < -threshold and position < pos_gate and buy_cap > 0:
            qty = min(size_base, buy_cap, pos_gate - position)
            if qty > 0:
                memory["last_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_ask), qty)
        return None

    def _read_params(self) -> Dict[str, Any]:
        p = self.params
        return {
            # Theo's HYDRO base
            "ema_alpha": float(p.get("ema_alpha", 0.008)),
            "fast_ema_alpha": float(p.get("fast_ema_alpha", 0.03)),
            "maker_size": int(p.get("maker_size", 24)),
            "min_maker_size": int(p.get("min_maker_size", 3)),
            "quote_threshold": float(p.get("quote_threshold", 6.0)),
            "max_signal_size_boost": int(p.get("max_signal_size_boost", 12)),
            "trend_guard": float(p.get("trend_guard", 6.0)),
            "signal_pos_gate": int(p.get("signal_pos_gate", 12)),
            "inventory_reduce_per_unit": float(p.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(p.get("inventory_unwind_per_unit", 0.30)),
            "max_unwind_boost": int(p.get("max_unwind_boost", 20)),
            "tighten_ticks": int(p.get("tighten_ticks", 1)),
            "take_threshold": float(p.get("take_threshold", 12.0)),
            "take_size": int(p.get("take_size", 1)),
            "take_cooldown_ts": int(p.get("take_cooldown_ts", 2000)),
            # Realized-vol regime detector
            "vol_window": int(p.get("vol_window", 200)),
            "min_vol_samples": int(p.get("min_vol_samples", 100)),
            "vol_baseline": float(p.get("vol_baseline", 2.15)),
            "vol_low_thr": float(p.get("vol_low_thr", 1.8)),
            "vol_high_thr": float(p.get("vol_high_thr", 2.6)),
            # Regime multipliers
            "low_vol_maker_mult": float(p.get("low_vol_maker_mult", 1.25)),
            "low_vol_signal_mult": float(p.get("low_vol_signal_mult", 1.5)),
            "low_vol_take_thr_mult": float(p.get("low_vol_take_thr_mult", 0.8)),
            "low_vol_take_size_mult": float(p.get("low_vol_take_size_mult", 1.5)),
            "high_vol_maker_mult": float(p.get("high_vol_maker_mult", 0.75)),
            "high_vol_signal_mult": float(p.get("high_vol_signal_mult", 0.75)),
            "high_vol_take_thr_mult": float(p.get("high_vol_take_thr_mult", 1.5)),
            "high_vol_take_size_mult": float(p.get("high_vol_take_size_mult", 1.0)),
            # Léo's session drift bias
            "session_drift_bias": int(p.get("session_drift_bias", 4)),
            "session_bias_strong_until_ts": int(p.get("session_bias_strong_until_ts", 100_000)),
            "session_bias_fade_until_ts": int(p.get("session_bias_fade_until_ts", 300_000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("ema", "fast_ema", "_dev", "_trend", "_realized_vol", "_session_bias"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        if (r := memory.get("_regime")) is not None:
            out["regime_code"] = {"low_vol": 0, "normal": 1, "high_vol": 2}.get(r, -1)
        return out
