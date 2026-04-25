"""HydrogelSuperMM — Theo's R3HydroReversionMM + informed-flow gate + daily bias.

Built on Léo's pattern analysis of market_trades (round 3 historical):

  Streak analysis (consecutive same-side aggressive trades within 1000ts):
    BUY  ≥2 trades: markout +10.35 at H=1000, **63% wr** → INFORMED BUYING
    SELL ≥2 trades: markout  -2.34 at H=1000,  40% wr → not informed (mean-rev)
    Single trades:  markout +1-5 ticks, mostly noise

  Conclusion: aggressive buyers crossing in clusters HAVE INFORMATION about
  upcoming price rise. Sellers crossing don't (mean-rev).

  We can't profitably FOLLOW (spread cost ~7 > markout 5-10), but we CAN
  defensively avoid being adverse-selected by KILLING our ASK quote when
  informed buying is detected. Same for ASK side.

Logic added to Theo's base strategy:

  Each tick, monitor state.market_trades. Classify each trade as BUY (price
  >= recent ask) or SELL (price <= recent bid). Track in memory:

    informed_buy_until_ts:  if 2+ BUY trades in last `streak_window` ts,
                            extend until last_buy_ts + `gate_duration_ts`
    informed_sell_until_ts: same for SELL streaks

  When informed_buy is active:
    - Suppress passive ASK quote (don't get adversely-selected short)
    - Allow BID quote normally (we want to catch the rally)

  When informed_sell is active:
    - SELL streaks have weaker signal (40% wr) — apply weaker gate:
      reduce ASK size (rather than kill) and keep BID normal

Plus all of Theo's signals (trend_guard=6, dual EMA, mean-rev one-side
quoting) and Léo's session_drift_bias for first 1000 ticks of session.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, Trade, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelSuperMMStrategy(BaseStrategy):
    """Theo's R3HydroReversionMM + informed-flow gate + daily bias."""

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

        # ── Theo's dual EMA + trend ──────────────────────────────────────
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
        memory["_trend"] = trend

        # ── Informed-flow detection from market_trades ───────────────────
        gate = self._update_informed_gate(state, book, memory, p)
        memory["_gate"] = gate  # 'buy' | 'sell' | 'none'

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._quote_sizes(position, deviation, trend, p)

        # ── Apply informed-flow gate ─────────────────────────────────────
        if gate == "buy":
            # Informed buying detected → kill ASK (don't sell into rally)
            ask_size = 0
        elif gate == "sell":
            # Weaker signal → reduce ASK size by half (not kill)
            # Actually SELL streak has 40% wr, so the trade is bullish on
            # average → BID side might get adversely-selected. Reduce BID.
            bid_size = max(0, bid_size // 2)

        # ── Léo's session-drift bias ─────────────────────────────────────
        bias = self._session_drift_bias(state, p)
        if bias > 0:  # lean short
            bid_size = max(0, bid_size - bias)
            ask_size = ask_size + bias if ask_size > 0 else ask_size  # don't un-suppress
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

        # Theo's tiny taker overlay
        take = self._take_order(state, book, position, deviation, trend, memory, buy_cap, sell_cap, p)
        if take is not None:
            orders.append(take)

        return orders, 0

    # ── Informed-flow gate logic ─────────────────────────────────────────

    def _update_informed_gate(
        self,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
        p: Dict[str, Any],
    ) -> str:
        """Classify recent market_trades, detect 2+-trade streaks per side.

        Returns 'buy' | 'sell' | 'none'.
        """
        ts_now = int(state.timestamp)
        # Pull market trades for our product
        trades_dict = getattr(state, "market_trades", {}) or {}
        new_trades: List[Trade] = trades_dict.get(self.product, []) or []

        # Maintain rolling buffer of recent crossing trades (last `streak_window` ts)
        history: List[Tuple[int, str]] = memory.get("_recent_crossings", [])

        bid = book.best_bid
        ask = book.best_ask
        for t in new_trades:
            t_ts = int(getattr(t, "timestamp", ts_now))
            t_price = float(getattr(t, "price", 0))
            # Classify: hits ask = BUY, hits bid = SELL, else neither
            if ask is not None and t_price >= ask:
                history.append((t_ts, "BUY"))
            elif bid is not None and t_price <= bid:
                history.append((t_ts, "SELL"))
            # else mid-trade, ignore

        # Trim history to within streak_window ts
        streak_w = p["streak_window_ts"]
        history = [(t, s) for (t, s) in history if t >= ts_now - streak_w]
        memory["_recent_crossings"] = history

        # Count buys / sells in window
        n_buy = sum(1 for _, s in history if s == "BUY")
        n_sell = sum(1 for _, s in history if s == "SELL")

        # Gate active duration: extend by gate_duration_ts past the trigger
        last_buy_until = int(memory.get("_buy_gate_until_ts", 0))
        last_sell_until = int(memory.get("_sell_gate_until_ts", 0))
        gate_dur = p["gate_duration_ts"]

        if n_buy >= p["streak_min_count"]:
            # Find latest BUY ts and extend gate
            last_buy_ts = max((t for t, s in history if s == "BUY"), default=ts_now)
            memory["_buy_gate_until_ts"] = max(last_buy_until, last_buy_ts + gate_dur)
        if n_sell >= p["streak_min_count"]:
            last_sell_ts = max((t for t, s in history if s == "SELL"), default=ts_now)
            memory["_sell_gate_until_ts"] = max(last_sell_until, last_sell_ts + gate_dur)

        if ts_now < int(memory.get("_buy_gate_until_ts", 0)):
            return "buy"
        if ts_now < int(memory.get("_sell_gate_until_ts", 0)):
            return "sell"
        return "none"

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
            frac = 1.0 - (ts - early) / (fade - early)
            return int(bias * frac)
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

    def _read_params(self) -> Dict[str, Any]:
        p = self.params
        return {
            # Theo's HYDRO params
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
            # Informed-flow gate
            "streak_window_ts": int(p.get("streak_window_ts", 1000)),
            "streak_min_count": int(p.get("streak_min_count", 2)),
            "gate_duration_ts": int(p.get("gate_duration_ts", 50000)),  # 500 ticks ahead
            # Léo's session drift bias
            "session_drift_bias": int(p.get("session_drift_bias", 4)),
            "session_bias_strong_until_ts": int(p.get("session_bias_strong_until_ts", 100_000)),
            "session_bias_fade_until_ts": int(p.get("session_bias_fade_until_ts", 300_000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("ema", "fast_ema", "_trend", "_session_bias"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        if (g := memory.get("_gate")) is not None:
            out["gate_code"] = {"none": 0, "buy": 1, "sell": 2}.get(g, -1)
        return out
