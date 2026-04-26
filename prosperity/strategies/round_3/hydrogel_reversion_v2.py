"""HydrogelReversionV2 — Theo's strategy + dynamic taker (exhaustion-style).

Live result motivation (theo_drift_only log 403647):
  - Final +1,077, peak +2,307 (at ts ~91k when mid hit 9927)
  - But mid rebounded to 9960 by close, eating 1,230 of mtm
  - We held -27 short and Theo's tiny taker (size=1, cooldown 2000ts) was
    too slow to cover the rebound

Exhaustion-strategy lesson: when displacement is large (mid dropped 40-50
ticks from EMA), aggressive taker locks profit before reversion. This
strategy adds a dynamic-size taker on top of Theo's R3HydroReversionMM:

  base size:  1 (Theo's value, fires at |dev| >= take_threshold = 12)
  scaled:     1 + max(0, (|dev| - take_threshold) / take_size_scale_div)
  cap:        take_size_max (default 12)

  cooldown:   shorter when extreme (|dev| >= take_extreme_threshold, default 30)

Rest of logic identical to hydrogel_reversion_mm (Theo's clone with
trend_guard=6 + Léo's session_drift_bias=4 in first 1000 ticks).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelReversionV2Strategy(BaseStrategy):
    """Theo's strategy + dynamic taker size scaling with |dev|."""

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

        # Dual EMA + trend
        slow_a = p["ema_alpha"]
        fast_a = p["fast_ema_alpha"]
        ema = memory.get("ema", mid)
        fast_ema = memory.get("fast_ema", mid)
        ema = slow_a * mid + (1 - slow_a) * ema
        fast_ema = fast_a * mid + (1 - fast_a) * fast_ema
        deviation = mid - ema
        trend = fast_ema - ema
        memory["ema"] = ema
        memory["fast_ema"] = fast_ema
        memory["_dev"] = deviation
        memory["_trend"] = trend

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._quote_sizes(position, deviation, trend, p)

        # Léo's session-drift bias (lean short in first 1000 ticks)
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

        # Dynamic taker (NEW vs Theo)
        take = self._dynamic_take_order(state, book, position, deviation, trend, memory, buy_cap, sell_cap, p)
        if take is not None:
            orders.append(take)

        return orders, 0

    # ── Quote prices / sizes (Theo's logic) ─────────────────────────────

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

    # ── Session drift bias ─────────────────────────────────────────────

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

    # ── Dynamic taker (NEW: size scales with |dev|) ─────────────────────

    def _dynamic_take_order(
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
        size_max = p["take_size_max"]
        size_div = p["take_size_scale_div"]
        normal_cd = p["take_cooldown_ts"]
        extreme_cd = p["take_extreme_cooldown_ts"]
        extreme_thr = p["take_extreme_threshold"]
        last_ts = int(memory.get("last_take_ts", -10 ** 9))
        ts_now = int(state.timestamp)

        # Choose cooldown based on |dev| extremity
        cooldown = extreme_cd if abs(deviation) >= extreme_thr else normal_cd
        if ts_now - last_ts < cooldown:
            return None

        # CRITICAL: bypass trend_guard when |dev| is extreme. The whole point of
        # exhaustion taker is to mean-revert AT extremes — which by definition
        # means trend is high (mid moved fast). Original trend_guard would block.
        bypass_thr = p["bypass_trend_guard_dev"]
        if abs(deviation) < bypass_thr and abs(trend) >= trend_guard:
            return None

        # Dynamic size: 1 base + (|dev| - threshold) / scale_div, capped
        excess = max(0.0, abs(deviation) - threshold)
        base_size = p["take_size_base"]
        dyn_size = base_size + int(excess / size_div)
        dyn_size = min(size_max, dyn_size)
        if dyn_size <= 0:
            return None

        if deviation > threshold and position > -pos_gate and sell_cap > 0:
            qty = min(dyn_size, sell_cap, pos_gate + position)
            if qty > 0:
                memory["last_take_ts"] = ts_now
                memory["_last_take_dev"] = deviation
                memory["_last_take_size"] = qty
                return Order(self.product, int(book.best_bid), -qty)
        if deviation < -threshold and position < pos_gate and buy_cap > 0:
            qty = min(dyn_size, buy_cap, pos_gate - position)
            if qty > 0:
                memory["last_take_ts"] = ts_now
                memory["_last_take_dev"] = deviation
                memory["_last_take_size"] = qty
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
            # Dynamic taker (NEW)
            "take_threshold": float(p.get("take_threshold", 12.0)),
            "take_size_base": int(p.get("take_size_base", 1)),
            "take_size_max": int(p.get("take_size_max", 12)),
            "take_size_scale_div": float(p.get("take_size_scale_div", 4.0)),
            "take_cooldown_ts": int(p.get("take_cooldown_ts", 2000)),
            "take_extreme_threshold": float(p.get("take_extreme_threshold", 30.0)),
            "take_extreme_cooldown_ts": int(p.get("take_extreme_cooldown_ts", 500)),
            "bypass_trend_guard_dev": float(p.get("bypass_trend_guard_dev", 20.0)),
            # Léo's session drift bias
            "session_drift_bias": int(p.get("session_drift_bias", 4)),
            "session_bias_strong_until_ts": int(p.get("session_bias_strong_until_ts", 100_000)),
            "session_bias_fade_until_ts": int(p.get("session_bias_fade_until_ts", 300_000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("ema", "fast_ema", "_dev", "_trend", "_session_bias", "_last_take_dev", "_last_take_size"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        return out
