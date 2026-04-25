"""HydrogelSmartMM — Theo + confirmed-reversal exit (robust, no overfit).

The day-2 profit-leak diagnosis:
  theo_drift_only LIVE: held -27 short into mid 9927→9960 rebound, lost
  ~890 mtm. The tiny taker (size=1) couldn't cover fast enough.

  reversion_v2 + bypass: fired aggressive taker at |dev|≥22, covered too
  early on transient |dev| spikes during the descent. Live -95 vs theo_drift.

The robust fix: fire AGGRESSIVE COVER only at confirmed trend reversal,
not at every transient extreme. A "confirmed reversal" requires:

  1. Position is established and adverse (e.g. short while mid below mean)
  2. |dev| is extreme (≥ extreme_dev_threshold)
  3. Mid has REVERSED direction for >= reversal_persist_ticks consecutive
     ticks. This is the "bottom signal" — we wait until the descent
     visibly stops AND starts climbing.

The directionality check is the key insight:
  - Pure |dev| extreme: fires repeatedly during descent (false positives)
  - |dev| extreme AND reversing: fires only at the V-bottom (the moment
    we want to cover). Robust because we can't predict the exact bottom,
    but we CAN detect that the reversal has started.

Other layers (all from Theo's base):
  - Dual EMA (alpha=0.008, 0.03) + trend_guard=6
  - One-sided mean-rev quoting (|dev|>6, signal_boost up to 12)
  - Inventory skew (reduce wrong, grow unwind)
  - Tiny passive taker (size=1, |dev|>12)
  - Léo's session_drift_bias=4 in first 1000 ticks

NEW: confirmed-reversal taker
  - Fires when |dev| > extreme_thr AND mid has reversed direction
  - Size scales with |dev| (1 + (|dev|-12)/4, cap = max_extreme_size)
  - Faster cooldown than passive taker (500 ts when extreme)
  - DOES bypass trend_guard (because reversal IS the trend flip)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelSmartMMStrategy(BaseStrategy):
    """Theo's base + confirmed-reversal exit at extreme |dev|."""

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
        prev_mid = memory.get("_prev_mid", mid)
        memory["_prev_mid"] = mid

        # Track mid direction: +1 if mid > prev, -1 if <, 0 if flat
        if mid > prev_mid:
            tick_dir = 1
        elif mid < prev_mid:
            tick_dir = -1
        else:
            tick_dir = 0

        # Track consecutive same-direction ticks (used for reversal confirmation)
        prev_dir = int(memory.get("_dir", 0))
        if tick_dir != 0 and tick_dir == prev_dir:
            memory["_dir_streak"] = int(memory.get("_dir_streak", 0)) + 1
        elif tick_dir != 0 and tick_dir != prev_dir:
            memory["_dir_streak"] = 1
            memory["_dir"] = tick_dir
        # else flat tick, don't update streak
        if tick_dir != 0:
            memory["_dir"] = tick_dir
        dir_streak = int(memory.get("_dir_streak", 0))
        cur_dir = int(memory.get("_dir", 0))

        # Dual EMA + trend (Theo's)
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

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._quote_sizes(position, deviation, trend, p)

        # Léo's session-drift bias
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

        # Theo's tiny passive taker (always available, fires on |dev|>=12)
        passive_take = self._passive_take_order(state, book, position, deviation, trend, memory, buy_cap, sell_cap, p)
        if passive_take is not None:
            orders.append(passive_take)
            # update buy_cap/sell_cap for confirmed-reversal taker below
            if passive_take.quantity > 0:
                buy_cap -= passive_take.quantity
            else:
                sell_cap += passive_take.quantity  # quantity is negative

        # Confirmed-reversal taker (NEW: only at extreme + reversing)
        cr_take = self._confirmed_reversal_take(
            state, book, position, deviation, trend, cur_dir, dir_streak,
            memory, buy_cap, sell_cap, p,
        )
        if cr_take is not None:
            orders.append(cr_take)

        memory["_dir_streak_log"] = dir_streak
        return orders, 0

    # ── Theo's quoting (unchanged) ───────────────────────────────────────

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

    # ── Theo's passive taker (size=1 base, fires on |dev|>=12) ───────────

    def _passive_take_order(
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

    # ── NEW: Confirmed-reversal taker ────────────────────────────────────

    def _confirmed_reversal_take(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        deviation: float,
        trend: float,
        cur_dir: int,
        dir_streak: int,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        """Fires when:
          - position is large enough to matter
          - |dev| is extreme (>= extreme_dev_threshold)
          - mid has reversed direction OPPOSITE to the position bias
            (mid going up while we're short → cover trigger)
          - dir_streak >= reversal_persist_ticks (confirmed, not transient)

        Bypasses trend_guard because reversal IS the trend flip.
        """
        if abs(position) < p["min_pos_for_reversal_take"]:
            return None

        extreme_thr = p["extreme_dev_threshold"]
        if abs(deviation) < extreme_thr:
            return None

        persist = p["reversal_persist_ticks"]
        if dir_streak < persist:
            return None

        cooldown = p["reversal_cooldown_ts"]
        last_ts = int(memory.get("_last_reversal_ts", -10 ** 9))
        ts_now = int(state.timestamp)
        if ts_now - last_ts < cooldown:
            return None

        # Reversal direction must be OPPOSITE to position bias
        # (long position + mid going DOWN → sell to cover) - but that's
        # the wrong direction for mean-rev. We want:
        # short position + mid going UP for 3+ ticks AND |dev|>extreme
        #   → fire BUY taker (cover the short before further rebound)
        # long position + mid going DOWN for 3+ ticks AND |dev|>extreme
        #   → fire SELL taker (close the long)
        size_max = p["reversal_take_max"]
        size_div = p["reversal_take_scale_div"]
        excess = abs(deviation) - extreme_thr
        size = min(size_max, p["reversal_take_base"] + int(excess / size_div))

        if position < 0 and cur_dir > 0 and deviation < -extreme_thr and buy_cap > 0:
            # Short + mid going UP at extreme low: rebound starting → COVER
            qty = min(size, buy_cap, -position)
            if qty > 0:
                memory["_last_reversal_ts"] = ts_now
                memory["_last_reversal_size"] = qty
                memory["_last_reversal_side"] = "BUY"
                return Order(self.product, int(book.best_ask), qty)
        if position > 0 and cur_dir < 0 and deviation > extreme_thr and sell_cap > 0:
            # Long + mid going DOWN at extreme high: drop starting → SELL
            qty = min(size, sell_cap, position)
            if qty > 0:
                memory["_last_reversal_ts"] = ts_now
                memory["_last_reversal_size"] = qty
                memory["_last_reversal_side"] = "SELL"
                return Order(self.product, int(book.best_bid), -qty)
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
            # Confirmed-reversal taker (NEW)
            "extreme_dev_threshold": float(p.get("extreme_dev_threshold", 20.0)),
            "reversal_persist_ticks": int(p.get("reversal_persist_ticks", 3)),
            "min_pos_for_reversal_take": int(p.get("min_pos_for_reversal_take", 10)),
            "reversal_take_base": int(p.get("reversal_take_base", 3)),
            "reversal_take_max": int(p.get("reversal_take_max", 12)),
            "reversal_take_scale_div": float(p.get("reversal_take_scale_div", 4.0)),
            "reversal_cooldown_ts": int(p.get("reversal_cooldown_ts", 1000)),
            # Léo's session drift bias
            "session_drift_bias": int(p.get("session_drift_bias", 4)),
            "session_bias_strong_until_ts": int(p.get("session_bias_strong_until_ts", 100_000)),
            "session_bias_fade_until_ts": int(p.get("session_bias_fade_until_ts", 300_000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("ema", "fast_ema", "_dev", "_trend", "_session_bias",
                  "_dir_streak_log", "_last_reversal_size"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        return out
