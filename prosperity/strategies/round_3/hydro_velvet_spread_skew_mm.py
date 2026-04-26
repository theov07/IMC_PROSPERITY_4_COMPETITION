"""HYDRO/VELVET spread-skew market maker.

This is a conservative implementation of the Round 3 spread idea:

* compute the visual dashboard spread: normalized HYDROGEL minus normalized
  VELVET;
* treat large spread z-scores as a one-sided quoting signal, not as an
  aggressive pair-trade by default;
* keep Theo's dual-EMA trend guard so we do not fade a strong move blindly;
* block the side that would increase wrong-side inventory when the spread and
  trend disagree.

The class can trade HYDROGEL or, with tiny size, the VELVET hedge leg.  The
default config uses it on HYDRO only and keeps VELVET on the proven passive MM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base.base import BaseStrategy


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"


class HydroVelvetSpreadSkewMMStrategy(BaseStrategy):
    """Theo-style MM with a normalized HYDRO/VELVET spread overlay."""

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

        ema, fast_ema = self._update_emas(mid, memory, p)
        deviation = mid - ema
        trend = fast_ema - ema

        spread_info = self._update_spread_signal(state, memory, p)
        spread_z = spread_info["z"]
        spread_value = spread_info["spread"]

        direction, mode, confidence = self._choose_direction(
            product=self.product,
            deviation=deviation,
            trend=trend,
            spread_z=spread_z,
            p=p,
        )

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._quote_sizes(
            direction=direction,
            mode=mode,
            confidence=confidence,
            position=position,
            p=p,
        )

        bias = self._session_bias(state, p)
        if bias and self.product == HYDROGEL:
            bid_size = max(0, bid_size - bias)
            ask_size += bias

        bid_size, ask_size = self._apply_inventory_controls(
            bid_size=bid_size,
            ask_size=ask_size,
            direction=direction,
            mode=mode,
            position=position,
            p=p,
        )

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            sell_cap -= qty

        take = self._wrong_side_taker(
            state=state,
            book=book,
            position=position,
            direction=direction,
            confidence=confidence,
            memory=memory,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            p=p,
        )
        if take is not None:
            orders.append(take)

        memory["_ema"] = ema
        memory["_fast_ema"] = fast_ema
        memory["_dev"] = deviation
        memory["_trend"] = trend
        memory["_spread_z"] = spread_z
        memory["_spread_value"] = spread_value
        memory["_mode"] = mode
        memory["_direction"] = direction

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price if bid_size > 0 else None,
            ask_price=ask_price if ask_size > 0 else None,
            extras={
                "mode": self._mode_code(mode),
                "direction": direction,
                "spread_z": round(spread_z, 4),
                "spread": round(spread_value, 4),
                "trend": round(trend, 4),
                "deviation": round(deviation, 4),
                "bid_size": bid_size,
                "ask_size": ask_size,
            },
        )

        return orders, 0

    def _update_emas(self, mid: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Tuple[float, float]:
        slow_a = p["ema_alpha"]
        fast_a = p["fast_ema_alpha"]
        ema = memory.get("ema")
        fast_ema = memory.get("fast_ema")
        ema = mid if ema is None else slow_a * mid + (1.0 - slow_a) * float(ema)
        fast_ema = mid if fast_ema is None else fast_a * mid + (1.0 - fast_a) * float(fast_ema)
        memory["ema"] = ema
        memory["fast_ema"] = fast_ema
        return ema, fast_ema

    def _mid_from_state(self, state: TradingState, symbol: str) -> Optional[float]:
        depth = state.order_depths.get(symbol)
        if depth is None:
            return None
        snap = snapshot_from_order_depth(symbol, depth)
        return float(snap.mid_price) if snap.mid_price is not None else None

    def _update_spread_signal(self, state: TradingState, memory: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, float]:
        hydro_mid = self._mid_from_state(state, HYDROGEL)
        velvet_mid = self._mid_from_state(state, VELVET)
        if hydro_mid is None or velvet_mid is None or hydro_mid <= 0 or velvet_mid <= 0:
            return {
                "spread": float(memory.get("_spread_value", 0.0)),
                "z": 0.0,
            }

        hydro_anchor = float(memory.get("_hydro_anchor") or p.get("hydro_anchor_price") or hydro_mid)
        velvet_anchor = float(memory.get("_velvet_anchor") or p.get("velvet_anchor_price") or velvet_mid)
        memory["_hydro_anchor"] = hydro_anchor
        memory["_velvet_anchor"] = velvet_anchor

        hydro_norm = 100.0 * hydro_mid / hydro_anchor
        velvet_norm = 100.0 * velvet_mid / velvet_anchor
        spread = hydro_norm - velvet_norm

        count = int(memory.get("_spread_count", 0)) + 1
        alpha = p["spread_alpha"]
        mean_prev = float(memory.get("_spread_mean", spread))
        var_prev = float(memory.get("_spread_var", 0.0))
        delta = spread - mean_prev
        mean = mean_prev + alpha * delta
        var = (1.0 - alpha) * (var_prev + alpha * delta * delta)
        std = var ** 0.5 if var > 0 else 0.0
        z = (spread - mean) / std if count >= p["spread_min_samples"] and std > p["spread_std_floor"] else 0.0

        memory["_spread_count"] = count
        memory["_spread_mean"] = mean
        memory["_spread_var"] = var
        memory["_spread_std"] = std
        return {"spread": spread, "z": z}

    def _choose_direction(
        self,
        *,
        product: str,
        deviation: float,
        trend: float,
        spread_z: float,
        p: Dict[str, Any],
    ) -> Tuple[int, str, float]:
        spread_dir = self._spread_direction(product, spread_z, p)
        trend_dir = 0
        if abs(trend) >= p["trend_follow_threshold"]:
            trend_dir = 1 if trend > 0 else -1

        mean_revert_dir = 0
        if abs(trend) < p["trend_guard"]:
            if deviation > p["quote_threshold"]:
                mean_revert_dir = -1
            elif deviation < -p["quote_threshold"]:
                mean_revert_dir = 1

        confidence = max(abs(spread_z) / max(p["spread_hard_z"], 1e-9), abs(trend) / max(p["trend_guard"], 1e-9))

        if spread_dir and trend_dir and spread_dir != trend_dir:
            if abs(spread_z) >= p["spread_extreme_z"] and abs(trend) < p["trend_extreme_block"]:
                return spread_dir, "spread_extreme", confidence
            return 0, "conflict", confidence

        if spread_dir:
            if abs(spread_z) >= p["spread_hard_z"]:
                return spread_dir, "spread_hard", confidence
            return spread_dir, "spread_skew", confidence

        if trend_dir and p["enable_trend_follow"]:
            return trend_dir, "trend_follow", confidence

        if mean_revert_dir:
            return mean_revert_dir, "ema_revert", abs(deviation) / max(p["quote_threshold"], 1e-9)

        return 0, "neutral", 0.0

    def _spread_direction(self, product: str, spread_z: float, p: Dict[str, Any]) -> int:
        if abs(spread_z) < p["spread_skew_z"]:
            return 0
        if product == HYDROGEL:
            return -1 if spread_z > 0 else 1
        if product == VELVET:
            return 1 if spread_z > 0 else -1
        return 0

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, bid + 1)
        return bid, ask

    def _quote_sizes(
        self,
        *,
        direction: int,
        mode: str,
        confidence: float,
        position: int,
        p: Dict[str, Any],
    ) -> Tuple[int, int]:
        maker = p["maker_size"]
        min_size = p["min_maker_size"]
        boost = min(p["max_signal_size_boost"], int(confidence * p["signal_boost_per_unit"]))

        bid_size = maker
        ask_size = maker

        if mode == "conflict":
            bid_size = p["conflict_quote_size"]
            ask_size = p["conflict_quote_size"]
        elif direction > 0:
            bid_size = maker + boost
            ask_size = p["counter_quote_size"] if mode in {"spread_hard", "trend_follow", "spread_extreme"} else max(min_size, maker - boost)
        elif direction < 0:
            ask_size = maker + boost
            bid_size = p["counter_quote_size"] if mode in {"spread_hard", "trend_follow", "spread_extreme"} else max(min_size, maker - boost)

        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size
        return max(0, bid_size), max(0, ask_size)

    def _apply_inventory_controls(
        self,
        *,
        bid_size: int,
        ask_size: int,
        direction: int,
        mode: str,
        position: int,
        p: Dict[str, Any],
    ) -> Tuple[int, int]:
        hard_cap = p["hard_pos_cap"]
        if position >= hard_cap:
            bid_size = 0
        if position <= -hard_cap:
            ask_size = 0

        wrong_gate = p["wrong_side_pos_gate"]
        if direction > 0 and position <= -wrong_gate:
            ask_size = 0
            bid_size += p["wrong_side_unwind_boost"]
        elif direction < 0 and position >= wrong_gate:
            bid_size = 0
            ask_size += p["wrong_side_unwind_boost"]
        elif mode == "conflict":
            if position > 0:
                bid_size = 0
                ask_size += min(p["max_unwind_boost"], int(position * p["inventory_unwind_per_unit"]))
            elif position < 0:
                ask_size = 0
                bid_size += min(p["max_unwind_boost"], int(-position * p["inventory_unwind_per_unit"]))

        if position > 0:
            bid_size = max(0, bid_size - int(position * p["inventory_reduce_per_unit"]))
            ask_size += min(p["max_unwind_boost"], int(position * p["inventory_unwind_per_unit"]))
        elif position < 0:
            ask_size = max(0, ask_size - int(-position * p["inventory_reduce_per_unit"]))
            bid_size += min(p["max_unwind_boost"], int(-position * p["inventory_unwind_per_unit"]))

        return max(0, bid_size), max(0, ask_size)

    def _wrong_side_taker(
        self,
        *,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        direction: int,
        confidence: float,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        if not p["enable_wrong_side_taker"] or direction == 0:
            return None
        if confidence < p["wrong_side_take_confidence"]:
            return None
        last_ts = int(memory.get("_last_wrong_side_take_ts", -10**9))
        if int(state.timestamp) - last_ts < p["wrong_side_take_cooldown_ts"]:
            return None

        gate = p["wrong_side_take_pos_gate"]
        size = p["wrong_side_take_size"]
        if direction > 0 and position <= -gate and buy_cap > 0:
            qty = min(size, buy_cap, -position)
            if qty > 0:
                memory["_last_wrong_side_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_ask), qty)
        if direction < 0 and position >= gate and sell_cap > 0:
            qty = min(size, sell_cap, position)
            if qty > 0:
                memory["_last_wrong_side_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_bid), -qty)
        return None

    def _session_bias(self, state: TradingState, p: Dict[str, Any]) -> int:
        bias = int(p.get("session_drift_bias", 0))
        if bias <= 0:
            return 0
        ts = int(state.timestamp)
        strong_until = int(p.get("session_bias_strong_until_ts", 100_000))
        fade_until = int(p.get("session_bias_fade_until_ts", 300_000))
        if ts <= strong_until:
            return bias
        if ts >= fade_until:
            return 0
        frac = 1.0 - (ts - strong_until) / max(1, fade_until - strong_until)
        return int(bias * frac)

    def _mode_code(self, mode: str) -> int:
        return {
            "neutral": 0,
            "ema_revert": 1,
            "trend_follow": 2,
            "spread_skew": 3,
            "spread_hard": 4,
            "spread_extreme": 5,
            "conflict": 6,
        }.get(mode, -1)

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        spread_window = int(params.get("spread_window", 500))
        return {
            "ema_alpha": float(params.get("ema_alpha", 0.008)),
            "fast_ema_alpha": float(params.get("fast_ema_alpha", 0.03)),
            "quote_threshold": float(params.get("quote_threshold", 6.0)),
            "trend_guard": float(params.get("trend_guard", 6.0)),
            "trend_follow_threshold": float(params.get("trend_follow_threshold", 6.0)),
            "trend_extreme_block": float(params.get("trend_extreme_block", 10.0)),
            "enable_trend_follow": bool(params.get("enable_trend_follow", True)),
            "maker_size": int(params.get("maker_size", 24)),
            "min_maker_size": int(params.get("min_maker_size", 3)),
            "counter_quote_size": int(params.get("counter_quote_size", 0)),
            "conflict_quote_size": int(params.get("conflict_quote_size", 0)),
            "max_signal_size_boost": int(params.get("max_signal_size_boost", 12)),
            "signal_boost_per_unit": int(params.get("signal_boost_per_unit", 8)),
            "tighten_ticks": int(params.get("tighten_ticks", 1)),
            "spread_window": spread_window,
            "spread_alpha": float(params.get("spread_alpha", 2.0 / (spread_window + 1))),
            "spread_min_samples": int(params.get("spread_min_samples", 150)),
            "spread_std_floor": float(params.get("spread_std_floor", 0.01)),
            "spread_skew_z": float(params.get("spread_skew_z", 1.5)),
            "spread_hard_z": float(params.get("spread_hard_z", 2.0)),
            "spread_extreme_z": float(params.get("spread_extreme_z", 2.7)),
            "hydro_anchor_price": params.get("hydro_anchor_price"),
            "velvet_anchor_price": params.get("velvet_anchor_price"),
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.30)),
            "max_unwind_boost": int(params.get("max_unwind_boost", 20)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 20)),
            "wrong_side_pos_gate": int(params.get("wrong_side_pos_gate", 8)),
            "wrong_side_unwind_boost": int(params.get("wrong_side_unwind_boost", 12)),
            "enable_wrong_side_taker": bool(params.get("enable_wrong_side_taker", False)),
            "wrong_side_take_confidence": float(params.get("wrong_side_take_confidence", 1.0)),
            "wrong_side_take_pos_gate": int(params.get("wrong_side_take_pos_gate", 12)),
            "wrong_side_take_size": int(params.get("wrong_side_take_size", 1)),
            "wrong_side_take_cooldown_ts": int(params.get("wrong_side_take_cooldown_ts", 2000)),
            "session_drift_bias": int(params.get("session_drift_bias", 0)),
            "session_bias_strong_until_ts": int(params.get("session_bias_strong_until_ts", 100_000)),
            "session_bias_fade_until_ts": int(params.get("session_bias_fade_until_ts", 300_000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        ema = memory.get("_ema")
        fast = memory.get("_fast_ema")
        if ema is not None:
            out["ema"] = float(ema)
        if fast is not None:
            out["fast_ema"] = float(fast)
        return out
