"""HydrogelComboMM — HYDRO-only multi-level MM with 3-signal regime detector.

Combines Léo's three insights into one strategy:

  1. **Level quoting** (volume amplification): ladder inside spread, multiple
     price levels per side, pyramid sizing. Backtest shows 4-5x more fills
     than single-level on full-day sessions.

  2. **EWM cross frequency** (regime detection): track the last N ticks. Each
     tick contributes +1 if `bid > ewm` (aggressive buying), -1 if `ask < ewm`
     (aggressive selling), 0 otherwise. Average over the window gives a
     directional score in [-1, +1]. This is descriptive of the current regime,
     equivalent to Theo's `trend_guard` but expressed as a discrete count.

  3. **Daily-trend phase** (statistical bias): HYDROGEL drifts -37 ticks on
     average over the first 1000 ticks (live window) across day 0/1/2. Mean-
     reverts to ~0 by ts ~5M, then can rebound up by ts ~7M. Use timestamp
     as a feature: bearish bias in first session_bias_strong_until_ts, fade
     out, optional bullish late-session.

Combined regime score (in approximately [-1, +1]):

  score = w_trend  * clip(trend / trend_guard, -1, +1)
        + w_cross  * cross_score
        + w_daily  * daily_phase

  trend = fast_ema - slow_ema  (positive = up)
  cross_score in [-1, +1]      (positive = up, more bid>EWM than ask<EWM)
  daily_phase in {-1, 0, +1}    (-1 early, 0 mid, +1 late)

  score > +regime_threshold  → up regime    → BID-heavy ladder, smaller ASK
  score < -regime_threshold  → down regime  → ASK-heavy ladder, smaller BID
  else                        → flat regime  → symmetric full ladder

Quoting:
  Each regime has (n_bid_levels, n_ask_levels, total_bid_size, total_ask_size).
  Levels are placed at best+1, best+2, ... (BID) and best-1, best-2, ... (ASK)
  inside the spread, clipped to not cross mid. Pyramid sizes (more inner).
  Inventory skew shrinks wrong side, grows unwind side.
  Hard position cap blocks new growth past ±cap.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelComboMMStrategy(BaseStrategy):
    """HYDRO-only ladder MM with 3-signal regime: trend + cross + daily phase."""

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
        spread = book.spread or 0
        if spread < p["min_spread_for_ladder"]:
            return self._narrow_fallback(book, position, p), 0

        mid = float(book.mid_price)
        best_bid = int(book.best_bid)
        best_ask = int(book.best_ask)

        # ── Signal 1: Dual EMA trend ─────────────────────────────────────
        slow_a = p["ema_alpha"]
        fast_a = p["fast_ema_alpha"]
        ema = memory.get("_ema", mid)
        fast_ema = memory.get("_fast_ema", mid)
        ema = slow_a * mid + (1 - slow_a) * ema
        fast_ema = fast_a * mid + (1 - fast_a) * fast_ema
        trend = fast_ema - ema  # raw ticks, positive = up
        memory["_ema"] = ema
        memory["_fast_ema"] = fast_ema
        memory["_trend"] = trend

        # ── Signal 2: EWM cross frequency over last N ticks ──────────────
        cross_window = p["cross_window"]
        history: List[int] = memory.get("_cross_history", [])
        # Tick contribution: +1 if bid > ewm (bullish), -1 if ask < ewm (bearish)
        if best_bid > ema:
            tick_signal = +1
        elif best_ask < ema:
            tick_signal = -1
        else:
            tick_signal = 0
        history.append(tick_signal)
        if len(history) > cross_window:
            history = history[-cross_window:]
        memory["_cross_history"] = history
        cross_score = sum(history) / max(1, len(history))  # in [-1, +1]
        memory["_cross_score"] = cross_score

        # ── Signal 3: Daily-trend phase ──────────────────────────────────
        daily_phase = self._daily_phase(int(state.timestamp), p)
        memory["_daily_phase"] = daily_phase

        # ── Aggregate regime score ───────────────────────────────────────
        trend_guard = p["trend_guard"]
        # Normalize trend to [-1, +1] using trend_guard as scale
        trend_norm = max(-1.0, min(1.0, trend / max(1e-9, trend_guard)))
        score = (
            p["w_trend"] * trend_norm
            + p["w_cross"] * cross_score
            + p["w_daily"] * daily_phase
        )
        memory["_score"] = score

        # Warmup: don't fire regime until enough cross history
        warmup = len(history) < p["min_samples"]
        regime_thr = p["regime_threshold"]
        if warmup or abs(score) < regime_thr:
            regime = "flat"
        elif score > 0:
            regime = "up_trend"
        else:
            regime = "down_trend"
        memory["_regime"] = regime

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        hard_cap = p["hard_pos_cap"]
        block_bid = position >= hard_cap
        block_ask = position <= -hard_cap

        # ── Build ladder by regime ───────────────────────────────────────
        bid_prices, ask_prices = self._build_ladder_prices(
            best_bid, best_ask, mid, regime, p
        )
        bid_sizes, ask_sizes = self._level_sizes_for_regime(
            len(bid_prices), len(ask_prices), regime, p
        )

        # ── Inventory skew ───────────────────────────────────────────────
        reduce_per = p["inventory_reduce_per_unit"]
        unwind_per = p["inventory_unwind_per_unit"]
        unwind_max = p["unwind_boost_max"]
        if position > 0:
            shrink = int(position * reduce_per)
            grow = min(unwind_max, int(position * unwind_per))
            n_b = max(1, len(bid_sizes))
            n_a = max(1, len(ask_sizes))
            bid_sizes = [max(0, s - shrink // n_b) for s in bid_sizes]
            ask_sizes = [s + grow // n_a for s in ask_sizes]
        elif position < 0:
            shrink = int(-position * reduce_per)
            grow = min(unwind_max, int(-position * unwind_per))
            n_b = max(1, len(bid_sizes))
            n_a = max(1, len(ask_sizes))
            ask_sizes = [max(0, s - shrink // n_a) for s in ask_sizes]
            bid_sizes = [s + grow // n_b for s in bid_sizes]

        if block_bid:
            bid_sizes = [0] * len(bid_sizes)
        if block_ask:
            ask_sizes = [0] * len(ask_sizes)

        orders: List[Order] = []
        for price, size in zip(bid_prices, bid_sizes):
            if size <= 0 or buy_cap <= 0:
                continue
            qty = min(size, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, price, qty))
                buy_cap -= qty
        for price, size in zip(ask_prices, ask_sizes):
            if size <= 0 or sell_cap <= 0:
                continue
            qty = min(size, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, price, -qty))
                sell_cap -= qty

        memory["_n_bid"] = len(bid_prices)
        memory["_n_ask"] = len(ask_prices)
        return orders, 0

    # ── Daily-phase encoding ─────────────────────────────────────────────

    def _daily_phase(self, ts: int, p: Dict[str, Any]) -> float:
        """Return daily-phase signal in [-1, +1].

        Backtest finding: HYDROGEL drifts -37 ticks avg in first 100k ts
        of session, mean-reverts to 0 by ts ~500k, can rebound up by ts ~700k.

        Phase encoding (linear interpolation between knots):
          ts <= 0           → -1.0  (strong bearish)
          ts == bias_decay_ts → -bias_decay_value (still bearish but weaker)
          ts == neutral_ts    →  0.0  (neutral)
          ts == bullish_ts    → +bullish_value (late-session up bias)
          ts >= bullish_ts    → +bullish_value
        """
        decay_ts = p["daily_phase_decay_ts"]            # ~300_000
        neutral_ts = p["daily_phase_neutral_ts"]        # ~500_000
        bullish_ts = p["daily_phase_bullish_ts"]        # ~700_000
        bullish_val = p["daily_phase_bullish_val"]      # 0.5 by default
        if ts <= 0:
            return -1.0
        if ts <= decay_ts:
            # Linear from -1.0 at 0 to -0.5 at decay_ts
            frac = ts / max(1, decay_ts)
            return -1.0 + 0.5 * frac
        if ts <= neutral_ts:
            frac = (ts - decay_ts) / max(1, neutral_ts - decay_ts)
            return -0.5 + 0.5 * frac
        if ts <= bullish_ts:
            frac = (ts - neutral_ts) / max(1, bullish_ts - neutral_ts)
            return 0.0 + bullish_val * frac
        return bullish_val

    # ── Regime-dependent ladder construction ─────────────────────────────

    def _build_ladder_prices(
        self,
        best_bid: int,
        best_ask: int,
        mid: float,
        regime: str,
        p: Dict[str, Any],
    ) -> Tuple[List[int], List[int]]:
        if regime == "up_trend":
            n_bid = p["num_levels_follow"]      # bigger bid (follow up)
            n_ask = p["num_levels_against"]
        elif regime == "down_trend":
            n_bid = p["num_levels_against"]
            n_ask = p["num_levels_follow"]      # bigger ask (follow down)
        else:
            n_bid = p["num_levels_flat"]
            n_ask = p["num_levels_flat"]
        step = p["level_step"]

        bid_prices: List[int] = []
        ask_prices: List[int] = []
        for i in range(n_bid):
            bp = best_bid + 1 + i * step
            if bp < mid - 0.5:
                bid_prices.append(bp)
        for i in range(n_ask):
            ap = best_ask - 1 - i * step
            if ap > mid + 0.5:
                ask_prices.append(ap)
        # Avoid crossing
        while bid_prices and ask_prices and max(bid_prices) >= min(ask_prices):
            bid_prices = [pp for pp in bid_prices if pp < min(ask_prices)]
            if not bid_prices:
                break
            ask_prices = [pp for pp in ask_prices if pp > max(bid_prices)]
        return bid_prices, ask_prices

    def _level_sizes_for_regime(
        self,
        n_bid: int,
        n_ask: int,
        regime: str,
        p: Dict[str, Any],
    ) -> Tuple[List[int], List[int]]:
        if regime == "flat":
            bid_total = p["total_size_flat"]
            ask_total = p["total_size_flat"]
        elif regime == "up_trend":
            bid_total = p["total_size_follow"]
            ask_total = p["total_size_against"]
        else:  # down_trend
            ask_total = p["total_size_follow"]
            bid_total = p["total_size_against"]
        return self._pyramid(n_bid, bid_total), self._pyramid(n_ask, ask_total)

    def _pyramid(self, n: int, total: int) -> List[int]:
        if n <= 0:
            return []
        if n == 1:
            return [total]
        weights = list(range(n, 0, -1))
        tot_w = sum(weights)
        sizes = [int(total * w / tot_w) for w in weights]
        diff = total - sum(sizes)
        for i in range(diff):
            sizes[i % n] += 1
        return sizes

    def _narrow_fallback(
        self, book: BookSnapshot, position: int, p: Dict[str, Any]
    ) -> List[Order]:
        size = p["fallback_size"]
        bid_price = int(book.best_bid) + 1 if book.spread and book.spread >= 2 else int(book.best_bid)
        ask_price = int(book.best_ask) - 1 if book.spread and book.spread >= 2 else int(book.best_ask)
        if bid_price >= ask_price:
            bid_price = int(book.best_bid)
            ask_price = int(book.best_ask)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        hard_cap = p["hard_pos_cap"]
        out: List[Order] = []
        if position < hard_cap and buy_cap > 0:
            out.append(Order(self.product, bid_price, min(size, buy_cap)))
        if position > -hard_cap and sell_cap > 0:
            out.append(Order(self.product, ask_price, -min(size, sell_cap)))
        return out

    # ── Params ───────────────────────────────────────────────────────────

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            # Signal 1: dual EMA
            "ema_alpha": float(params.get("ema_alpha", 0.008)),
            "fast_ema_alpha": float(params.get("fast_ema_alpha", 0.03)),
            "trend_guard": float(params.get("trend_guard", 6.0)),
            # Signal 2: cross frequency
            "cross_window": int(params.get("cross_window", 200)),
            "min_samples": int(params.get("min_samples", 100)),
            # Signal 3: daily-phase knots
            "daily_phase_decay_ts": int(params.get("daily_phase_decay_ts", 300_000)),
            "daily_phase_neutral_ts": int(params.get("daily_phase_neutral_ts", 500_000)),
            "daily_phase_bullish_ts": int(params.get("daily_phase_bullish_ts", 700_000)),
            "daily_phase_bullish_val": float(params.get("daily_phase_bullish_val", 0.5)),
            # Aggregate weights
            "w_trend": float(params.get("w_trend", 0.5)),
            "w_cross": float(params.get("w_cross", 0.3)),
            "w_daily": float(params.get("w_daily", 0.2)),
            "regime_threshold": float(params.get("regime_threshold", 0.30)),
            # Ladder geometry
            "num_levels_flat": int(params.get("num_levels_flat", 3)),
            "num_levels_follow": int(params.get("num_levels_follow", 4)),
            "num_levels_against": int(params.get("num_levels_against", 1)),
            "level_step": int(params.get("level_step", 1)),
            "min_spread_for_ladder": int(params.get("min_spread_for_ladder", 4)),
            # Sizes
            "total_size_flat": int(params.get("total_size_flat", 30)),
            "total_size_follow": int(params.get("total_size_follow", 40)),
            "total_size_against": int(params.get("total_size_against", 5)),
            "fallback_size": int(params.get("fallback_size", 8)),
            # Inventory + cap
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.50)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.30)),
            "unwind_boost_max": int(params.get("unwind_boost_max", 30)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 30)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ema", "_fast_ema", "_trend", "_cross_score", "_daily_phase", "_score"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        if (r := memory.get("_regime")) is not None:
            out["regime_code"] = {"flat": 0, "up_trend": 1, "down_trend": 2}.get(r, -1)
        return out
