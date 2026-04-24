"""HydrogelFollowMM — trend-follow MM with aggressive mean-revert unwind.

Rationale (from v2 live log 384749):
  Day 2 HYDRO drifted 10011 → 9960 (~51 ticks down) over the full day.
  Our asym_mm v2 caught the direction (short -23 at close, +672 PnL) but
  the mean-rev logic fought it: bought back -11→-16→-11 in the middle of
  the downtrend, missing the follow-through.

  A trend-follower with aggressive unwind would:
    1. Detect trend early (slow EMA slope).
    2. SIZE-UP same direction (one-side aggressive).
    3. Hold/add through pullbacks (no mean-rev cover-back).
    4. Take profit aggressively via taker when z-score extends against
       position direction (mean-revert exhaustion signal).

Regime logic:
  trend_score = (fast_EMA - slow_EMA) / std_fast
    > +T  → up_trend: grow BID, minimise ASK (follow up)
    < -T  → down_trend: grow ASK, minimise BID (follow down)
    else  → flat: fallback to classic asym_mm (z-score one-sided mean-rev)

Taker overlay — "aggressive unwind" has three triggers:
  A. Trend-flip: position > 0 AND trend < -flip_thr → aggressive SELL
                 position < 0 AND trend > +flip_thr → aggressive BUY
     (catches regime change before mean-rev shows up)

  B. Mean-revert take-profit: position > 0 AND z > +tp_z → SELL (rich)
                              position < 0 AND z < -tp_z → BUY (cheap)
     (we overshot with the trend, price now extended, lock gains)

  C. Stop-loss (wide): only when position adverse to trend sign
     (basic loss-cut; controlled by stop_z)

Params summary:
  ema_fast / ema_slow       : fast=500 (ACF-optimal), slow=2000 (day-level)
  trend_threshold           : |trend| > this → trend regime (default 1.0)
  flat_z_threshold          : z one-sided quote in flat regime (default 1.5)
  follow_boost_max/per      : size boost per |trend| unit (cap 10, /trend 4)
  hard_pos_cap              : max |position| build-up (default 35, wider
                              than asym_mm's 15 because we WANT follow size)
  flip_threshold            : trend flip magnitude for taker (default 0.8)
  tp_z                      : mean-revert z for take-profit (default 1.2)
  stop_z                    : wider z for stop-loss (default 2.5)
  unwind_take_size          : taker qty per firing (default 4)
  take_cooldown_ts          : min ts between takers (default 500 — faster
                              than asym_mm since unwind is primary job)
  min_samples               : warmup ticks (default 200)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelFollowMMStrategy(BaseStrategy):
    """Trend-follow MM with aggressive mean-revert unwind."""

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

        # ── Dual EMA + variance on fast residual ─────────────────────────
        alpha_f = 2.0 / (p["ema_fast"] + 1)
        alpha_s = 2.0 / (p["ema_slow"] + 1)
        ema_fast_prev = memory.get("_ema_fast", mid)
        ema_slow_prev = memory.get("_ema_slow", mid)
        var_prev = memory.get("_ewma_var", 0.0)
        tick_count = memory.get("_tick_count", 0) + 1

        delta_f = mid - ema_fast_prev
        new_fast = ema_fast_prev + alpha_f * delta_f
        new_slow = ema_slow_prev + alpha_s * (mid - ema_slow_prev)
        new_var = (1 - alpha_f) * (var_prev + alpha_f * delta_f * delta_f)
        std = (new_var ** 0.5) if new_var > 0 else 0.0

        z = (mid - new_fast) / std if std > 1e-6 else 0.0
        trend = (new_fast - new_slow) / std if std > 1e-6 else 0.0

        memory["_ema_fast"] = new_fast
        memory["_ema_slow"] = new_slow
        memory["_ewma_var"] = new_var
        memory["_tick_count"] = tick_count
        memory["_z"] = z
        memory["_trend"] = trend

        warmup = (tick_count < p["min_samples"]) or (std < 1e-6)
        effective_trend = 0.0 if warmup else trend
        effective_z = 0.0 if warmup else z

        # ── Regime ──────────────────────────────────────────────────────
        t_thr = p["trend_threshold"]
        if effective_trend > t_thr:
            regime = "up_trend"
        elif effective_trend < -t_thr:
            regime = "down_trend"
        else:
            regime = "flat"
        memory["_regime"] = regime

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        # ── Quote prices (penny-improve inside the spread) ──────────────
        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])

        # ── Sizing by regime ────────────────────────────────────────────
        bid_size, ask_size = self._quote_sizes(
            regime, effective_trend, effective_z, position, p
        )

        # ── Hard position cap ───────────────────────────────────────────
        hard_cap = p["hard_pos_cap"]
        if position >= hard_cap:
            bid_size = 0
        if position <= -hard_cap:
            ask_size = 0

        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            sell_cap -= qty

        # ── Aggressive unwind taker ─────────────────────────────────────
        # Only fires when we have an established position (|pos| > min_pos_for_take)
        # AND one of: trend flipped, z extreme take-profit, z extreme stop-loss.
        # Flat regime with small position = no takers (avoid whipsaw).
        min_pos_take = p["min_pos_for_take"]
        if p["enable_taker"] and not warmup and abs(position) >= min_pos_take:
            take = self._take_order(
                state, book, position, effective_z, effective_trend, regime,
                memory, buy_cap, sell_cap, p,
            )
            if take is not None:
                orders.append(take)

        return orders, 0

    # ── Quote prices (penny-improve) ────────────────────────────────────

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, book.best_bid + 1)
        return bid, ask

    # ── Regime-based sizing ─────────────────────────────────────────────

    def _quote_sizes(
        self,
        regime: str,
        trend: float,
        z: float,
        position: int,
        p: Dict[str, Any],
    ) -> Tuple[int, int]:
        maker = p["maker_size"]
        min_m = p["min_maker_size"]
        boost_max = p["follow_boost_max"]
        boost_per = p["follow_boost_per_trend"]

        bid_size = maker
        ask_size = maker

        if regime == "up_trend":
            # Follow up: grow BID, minimise ASK (but keep tiny for accidental rip)
            bid_size = maker + min(boost_max, int(abs(trend) * boost_per))
            ask_size = min_m
        elif regime == "down_trend":
            ask_size = maker + min(boost_max, int(abs(trend) * boost_per))
            bid_size = min_m
        else:
            # Flat → pure passive MM (symmetric). NO one-side z-mean-rev here
            # because on slow drift days (e.g. day 2), fast_EMA lags and z
            # persistently signals "cheap" while mid keeps dropping — we'd
            # keep buying into the drop. Let inventory skew handle recentering.
            bid_size = maker
            ask_size = maker

        # ── Inventory skew ONLY in flat regime ──────────────────────────
        # In trend regime we WANT to grow inventory with the trend.
        if regime == "flat":
            reduce = p["inventory_reduce_per_unit"]
            unwind = p["inventory_unwind_per_unit"]
            unwind_boost = p["unwind_boost_max"]
            if position > 0:
                bid_size = max(0, bid_size - int(position * reduce))
                ask_size += min(unwind_boost, int(position * unwind))
            elif position < 0:
                ask_size = max(0, ask_size - int(-position * reduce))
                bid_size += min(unwind_boost, int(-position * unwind))

        if 0 < bid_size < min_m:
            bid_size = min_m
        if 0 < ask_size < min_m:
            ask_size = min_m
        return max(0, bid_size), max(0, ask_size)

    # ── Aggressive unwind taker ─────────────────────────────────────────

    def _take_order(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        z: float,
        trend: float,
        regime: str,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        cooldown = p["take_cooldown_ts"]
        last_ts = int(memory.get("_last_take_ts", -10 ** 9))
        if int(state.timestamp) - last_ts < cooldown:
            return None

        flip_thr = p["flip_threshold"]
        tp_z = p["tp_z"]
        stop_z = p["stop_z"]
        unwind_size = p["unwind_take_size"]

        # (A) Trend-flip stop: position adverse to trend direction
        if position > 0 and trend < -flip_thr and sell_cap > 0:
            qty = min(unwind_size, position, sell_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "flip_stop_long"
                return Order(self.product, int(book.best_bid), -qty)
        if position < 0 and trend > flip_thr and buy_cap > 0:
            qty = min(unwind_size, -position, buy_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "flip_stop_short"
                return Order(self.product, int(book.best_ask), qty)

        # (B) Mean-revert take-profit: position extended, z signals reversion
        # If long and price rich (z>+tp_z) → take profit via hitting bid.
        # If short and price cheap (z<-tp_z) → take profit via hitting ask.
        if position > 0 and z > tp_z and sell_cap > 0:
            qty = min(unwind_size, position, sell_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "tp_long"
                return Order(self.product, int(book.best_bid), -qty)
        if position < 0 and z < -tp_z and buy_cap > 0:
            qty = min(unwind_size, -position, buy_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "tp_short"
                return Order(self.product, int(book.best_ask), qty)

        # (C) Stop-loss on extreme adverse z (position wrong side very far)
        # long and z < -stop_z → price collapsed below EMA → cut losses
        if position > 0 and z < -stop_z and sell_cap > 0:
            qty = min(unwind_size, position, sell_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "stop_long"
                return Order(self.product, int(book.best_bid), -qty)
        if position < 0 and z > stop_z and buy_cap > 0:
            qty = min(unwind_size, -position, buy_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "stop_short"
                return Order(self.product, int(book.best_ask), qty)
        return None

    # ── Params ──────────────────────────────────────────────────────────

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "ema_fast": int(params.get("ema_fast", 500)),
            "ema_slow": int(params.get("ema_slow", 2000)),
            "trend_threshold": float(params.get("trend_threshold", 1.0)),
            "flat_z_threshold": float(params.get("flat_z_threshold", 1.5)),
            "maker_size": int(params.get("maker_size", 20)),
            "min_maker_size": int(params.get("min_maker_size", 2)),
            "follow_boost_max": int(params.get("follow_boost_max", 10)),
            "follow_boost_per_trend": int(params.get("follow_boost_per_trend", 4)),
            "flat_boost_max": int(params.get("flat_boost_max", 8)),
            "flat_boost_per_z": int(params.get("flat_boost_per_z", 3)),
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.30)),
            "unwind_boost_max": int(params.get("unwind_boost_max", 20)),
            "tighten_ticks": int(params.get("tighten_ticks", 1)),
            "enable_taker": bool(params.get("enable_taker", True)),
            "flip_threshold": float(params.get("flip_threshold", 0.8)),
            "tp_z": float(params.get("tp_z", 1.2)),
            "stop_z": float(params.get("stop_z", 2.5)),
            "unwind_take_size": int(params.get("unwind_take_size", 4)),
            "take_cooldown_ts": int(params.get("take_cooldown_ts", 500)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 35)),
            "min_pos_for_take": int(params.get("min_pos_for_take", 8)),
            "min_samples": int(params.get("min_samples", 200)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ema_fast", "_ema_slow", "_z", "_trend"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = v
        if (r := memory.get("_regime")) is not None:
            out["regime_code"] = {"flat": 0, "up_trend": 1, "down_trend": 2}.get(r, -1)
        return out
