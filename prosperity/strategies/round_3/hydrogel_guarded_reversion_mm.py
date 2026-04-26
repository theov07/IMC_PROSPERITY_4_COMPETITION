"""HYDROGEL guarded Theo reversion MM.

This is a HYDRO-only strategy: it never sends orders on VELVET or vouchers.
It only reads their books to avoid quoting into toxic HYDRO regimes.

Core idea:
* keep Theo's stable dual-EMA reversion MM;
* build a small forward-direction score from HYDRO/VELVET and voucher-shape
  features;
* block or shrink the side that would increase wrong-way inventory;
* allow a small L1 exhaustion taker only when the cross-signal does not
  contradict the reversal.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base.base import BaseStrategy


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
ATM_VOUCHERS = ("VEV_5200", "VEV_5300")


class HydrogelGuardedReversionMMStrategy(BaseStrategy):
    """Theo-style HYDRO MM with toxic-regime gates and tiny exhaustion overlay."""

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
        ts = int(state.timestamp)
        mid = float(book.mid_price)

        self._update_mid_history(memory, ts, mid, p["history_keep_ts"])
        ema, fast_ema = self._update_emas(mid, memory, p)
        deviation = mid - ema
        trend = fast_ema - ema

        hydro_mom_1000 = self._displacement(memory, ts, mid, 1000)
        hydro_mom_5000 = self._displacement(memory, ts, mid, 5000)
        hydro_mom_10000 = self._displacement(memory, ts, mid, 10000)
        hydro_mom_20000 = self._displacement(memory, ts, mid, 20000)

        signal = self._cross_signal(
            state=state,
            memory=memory,
            ts=ts,
            hydro_mid=mid,
            hydro_mom_5000=hydro_mom_5000,
            hydro_mom_10000=hydro_mom_10000,
            p=p,
        )
        direction_score = signal["score"]  # >0 favors future up, <0 favors future down

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._theo_quote_sizes(position, deviation, trend, p)
        bid_size, ask_size, mode = self._apply_directional_gates(
            bid_size=bid_size,
            ask_size=ask_size,
            position=position,
            direction_score=direction_score,
            p=p,
        )
        exhaustion_side = self._exhaustion_side(
            state=state,
            position=position,
            direction_score=direction_score,
            hydro_mom_1000=hydro_mom_1000,
            hydro_mom_10000=hydro_mom_10000,
            hydro_mom_20000=hydro_mom_20000,
            memory=memory,
            p=p,
        )
        if exhaustion_side > 0:
            ask_size = 0
            mode = "exhaustion_buy_armed"
        elif exhaustion_side < 0:
            bid_size = 0
            mode = "exhaustion_sell_armed"

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

        take = self._theo_taker(
            state=state,
            book=book,
            position=position,
            deviation=deviation,
            trend=trend,
            direction_score=direction_score,
            memory=memory,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            p=p,
        )
        if take is not None:
            orders.append(take)
        else:
            exhaustion = self._exhaustion_taker(
                state=state,
                book=book,
                order_depth=order_depth,
                position=position,
                direction_score=direction_score,
                hydro_mom_1000=hydro_mom_1000,
                hydro_mom_10000=hydro_mom_10000,
                hydro_mom_20000=hydro_mom_20000,
                memory=memory,
                buy_cap=buy_cap,
                sell_cap=sell_cap,
                p=p,
            )
            if exhaustion is not None:
                orders.append(exhaustion)

        memory["_hgr_ema"] = ema
        memory["_hgr_fast_ema"] = fast_ema
        memory["_hgr_dev"] = deviation
        memory["_hgr_trend"] = trend
        memory["_hgr_score"] = direction_score
        memory["_hgr_mode_code"] = float(self._mode_code(mode))
        memory["_hgr_hydro_mom_10000"] = float(hydro_mom_10000 or 0.0)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price if bid_size > 0 else None,
            ask_price=ask_price if ask_size > 0 else None,
            extras={
                "mode": self._mode_code(mode),
                "score": round(direction_score, 4),
                "trend": round(trend, 4),
                "deviation": round(deviation, 4),
                "spread_z": round(signal["spread_z"], 4),
                "vertical_z": round(signal["vertical_z"], 4),
                "velvet_mom": round(signal["velvet_mom_5000"], 4),
                "bid_size": bid_size,
                "ask_size": ask_size,
            },
        )

        return orders, 0

    def _update_emas(self, mid: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Tuple[float, float]:
        slow_a = p["ema_alpha"]
        fast_a = p["fast_ema_alpha"]
        ema = memory.get("_hgr_ema_state")
        fast_ema = memory.get("_hgr_fast_ema_state")
        ema = mid if ema is None else slow_a * mid + (1.0 - slow_a) * float(ema)
        fast_ema = mid if fast_ema is None else fast_a * mid + (1.0 - fast_a) * float(fast_ema)
        memory["_hgr_ema_state"] = ema
        memory["_hgr_fast_ema_state"] = fast_ema
        return ema, fast_ema

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, book.best_bid + 1)
        return bid, ask

    def _theo_quote_sizes(
        self,
        position: int,
        deviation: float,
        trend: float,
        p: Dict[str, Any],
    ) -> Tuple[int, int]:
        maker = p["maker_size"]
        min_size = p["min_maker_size"]
        bid_size = maker
        ask_size = maker

        if abs(trend) < p["trend_guard"]:
            if deviation > p["quote_threshold"] and position > -p["signal_pos_gate"]:
                bid_size = 0
                ask_size = maker + min(p["max_signal_size_boost"], int(abs(deviation) // 4))
            elif deviation < -p["quote_threshold"] and position < p["signal_pos_gate"]:
                ask_size = 0
                bid_size = maker + min(p["max_signal_size_boost"], int(abs(deviation) // 4))

        if position > 0:
            bid_size = max(0, bid_size - int(position * p["inventory_reduce_per_unit"]))
            ask_size += min(p["max_unwind_boost"], int(position * p["inventory_unwind_per_unit"]))
        elif position < 0:
            ask_size = max(0, ask_size - int(-position * p["inventory_reduce_per_unit"]))
            bid_size += min(p["max_unwind_boost"], int(-position * p["inventory_unwind_per_unit"]))

        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size
        return max(0, bid_size), max(0, ask_size)

    def _apply_directional_gates(
        self,
        *,
        bid_size: int,
        ask_size: int,
        position: int,
        direction_score: float,
        p: Dict[str, Any],
    ) -> Tuple[int, int, str]:
        mode = "neutral"
        soft = p["soft_score"]
        hard = p["hard_score"]
        reduce_mult = p["soft_reduce_mult"]
        boost = min(p["gate_boost_max"], int(abs(direction_score) * p["gate_boost_per_score"]))

        if position >= p["hard_pos_cap"]:
            bid_size = 0
        if position <= -p["hard_pos_cap"]:
            ask_size = 0

        if direction_score <= -hard:
            mode = "hard_bear"
            bid_size = 0
            ask_size += boost
        elif direction_score >= hard:
            mode = "hard_bull"
            ask_size = 0
            bid_size += boost
        elif direction_score <= -soft:
            mode = "soft_bear"
            bid_size = int(bid_size * reduce_mult)
            ask_size += boost
        elif direction_score >= soft:
            mode = "soft_bull"
            ask_size = int(ask_size * reduce_mult)
            bid_size += boost

        wrong_gate = p["wrong_side_pos_gate"]
        if direction_score <= -soft and position > wrong_gate:
            bid_size = 0
            ask_size += p["wrong_side_unwind_boost"]
            mode = "wrong_long"
        elif direction_score >= soft and position < -wrong_gate:
            ask_size = 0
            bid_size += p["wrong_side_unwind_boost"]
            mode = "wrong_short"

        return max(0, bid_size), max(0, ask_size), mode

    def _theo_taker(
        self,
        *,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        deviation: float,
        trend: float,
        direction_score: float,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        if not p["enable_theo_taker"]:
            return None
        if abs(trend) >= p["trend_guard"]:
            return None
        last_ts = int(memory.get("_hgr_last_theo_take_ts", -10**9))
        if int(state.timestamp) - last_ts < p["take_cooldown_ts"]:
            return None

        if deviation > p["take_threshold"] and direction_score <= p["take_contra_score"] and position > -p["signal_pos_gate"] and sell_cap > 0:
            qty = min(p["take_size"], sell_cap, p["signal_pos_gate"] + position)
            if qty > 0:
                memory["_hgr_last_theo_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_bid), -qty)
        if deviation < -p["take_threshold"] and direction_score >= -p["take_contra_score"] and position < p["signal_pos_gate"] and buy_cap > 0:
            qty = min(p["take_size"], buy_cap, p["signal_pos_gate"] - position)
            if qty > 0:
                memory["_hgr_last_theo_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_ask), qty)
        return None

    def _exhaustion_taker(
        self,
        *,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        direction_score: float,
        hydro_mom_1000: Optional[float],
        hydro_mom_10000: Optional[float],
        hydro_mom_20000: Optional[float],
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        signal = self._exhaustion_side(
            state=state,
            position=position,
            direction_score=direction_score,
            hydro_mom_1000=hydro_mom_1000,
            hydro_mom_10000=hydro_mom_10000,
            hydro_mom_20000=hydro_mom_20000,
            memory=memory,
            p=p,
        )
        if signal == 0:
            return None
        ts = int(state.timestamp)

        max_pos = min(p["exhaustion_max_position"], self.position_limit())
        if signal > 0 and position < max_pos and buy_cap > 0:
            price, available = self._best_take(order_depth.sell_orders, is_buy=True)
            qty = min(p["exhaustion_size"], buy_cap, max_pos - position, available)
            if price is not None and qty > 0:
                memory["_hgr_last_exhaustion_take_ts"] = ts
                return Order(self.product, price, qty)
        if signal < 0 and position > -max_pos and sell_cap > 0:
            price, available = self._best_take(order_depth.buy_orders, is_buy=False)
            qty = min(p["exhaustion_size"], sell_cap, max_pos + position, available)
            if price is not None and qty > 0:
                memory["_hgr_last_exhaustion_take_ts"] = ts
                return Order(self.product, price, -qty)
        return None

    def _exhaustion_side(
        self,
        *,
        state: TradingState,
        position: int,
        direction_score: float,
        hydro_mom_1000: Optional[float],
        hydro_mom_10000: Optional[float],
        hydro_mom_20000: Optional[float],
        memory: Dict[str, Any],
        p: Dict[str, Any],
    ) -> int:
        if not p["enable_exhaustion_taker"]:
            return 0
        if hydro_mom_10000 is None or hydro_mom_20000 is None or hydro_mom_1000 is None:
            return 0
        ts = int(state.timestamp)
        last_ts = int(memory.get("_hgr_last_exhaustion_take_ts", -10**9))
        if ts - last_ts < p["exhaustion_cooldown_ts"]:
            return 0

        max_pos = min(p["exhaustion_max_position"], self.position_limit())
        buy_signal = (
            (hydro_mom_10000 <= -p["exhaustion_fast_ticks"] or hydro_mom_20000 <= -p["exhaustion_slow_ticks"])
            and hydro_mom_1000 >= -p["exhaustion_max_recent_against"]
            and direction_score >= p["exhaustion_buy_min_score"]
            and position < max_pos
            and self.buy_capacity(position) > 0
        )
        if buy_signal:
            return 1

        sell_signal = (
            (hydro_mom_10000 >= p["exhaustion_fast_ticks"] or hydro_mom_20000 >= p["exhaustion_slow_ticks"])
            and hydro_mom_1000 <= p["exhaustion_max_recent_against"]
            and direction_score <= -p["exhaustion_sell_min_score"]
            and position > -max_pos
            and self.sell_capacity(position) > 0
        )
        return -1 if sell_signal else 0

    @staticmethod
    def _best_take(side_book: Dict[int, int], *, is_buy: bool) -> Tuple[Optional[int], int]:
        if not side_book:
            return None, 0
        price = min(side_book) if is_buy else max(side_book)
        return int(price), abs(int(side_book[price]))

    def _cross_signal(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        ts: int,
        hydro_mid: float,
        hydro_mom_5000: Optional[float],
        hydro_mom_10000: Optional[float],
        p: Dict[str, Any],
    ) -> Dict[str, float]:
        velvet_mid = self._mid_from_state(state, VELVET)
        velvet_mom_5000 = 0.0
        if velvet_mid is not None:
            self._update_symbol_history(memory, "_hgr_velvet_hist", ts, velvet_mid, p["history_keep_ts"])
            velvet_mom_5000 = self._symbol_displacement(memory, "_hgr_velvet_hist", ts, velvet_mid, 5000) or 0.0

        spread_z = self._spread_z(memory, hydro_mid, velvet_mid, p)
        vertical_z = self._vertical_z(state, memory, p)

        hydro_10k = hydro_mom_10000 or 0.0
        hydro_5k = hydro_mom_5000 or 0.0
        hydro_reversal_score = -self._clip(hydro_10k / p["hydro_mom_scale"], -p["score_clip"], p["score_clip"])
        hydro_fast_score = -self._clip(hydro_5k / p["hydro_fast_mom_scale"], -p["score_clip"], p["score_clip"])
        velvet_score = -self._clip(velvet_mom_5000 / p["velvet_mom_scale"], -p["score_clip"], p["score_clip"])

        score = (
            p["w_vertical"] * (-vertical_z)
            + p["w_spread"] * spread_z
            + p["w_hydro_reversal"] * hydro_reversal_score
            + p["w_hydro_fast"] * hydro_fast_score
            + p["w_velvet"] * velvet_score
        )

        return {
            "score": self._clip(score, -p["score_hard_clip"], p["score_hard_clip"]),
            "spread_z": spread_z,
            "vertical_z": vertical_z,
            "velvet_mom_5000": velvet_mom_5000,
        }

    def _mid_from_state(self, state: TradingState, symbol: str) -> Optional[float]:
        depth = state.order_depths.get(symbol)
        if depth is None:
            return None
        snap = snapshot_from_order_depth(symbol, depth)
        if snap.mid_price is None:
            return None
        return float(snap.mid_price)

    def _spread_z(
        self,
        memory: Dict[str, Any],
        hydro_mid: float,
        velvet_mid: Optional[float],
        p: Dict[str, Any],
    ) -> float:
        if velvet_mid is None or hydro_mid <= 0 or velvet_mid <= 0:
            return float(memory.get("_hgr_spread_z", 0.0))
        hydro_anchor = float(memory.get("_hgr_hydro_anchor") or p.get("hydro_anchor_price") or hydro_mid)
        velvet_anchor = float(memory.get("_hgr_velvet_anchor") or p.get("velvet_anchor_price") or velvet_mid)
        memory["_hgr_hydro_anchor"] = hydro_anchor
        memory["_hgr_velvet_anchor"] = velvet_anchor
        spread = 100.0 * hydro_mid / hydro_anchor - 100.0 * velvet_mid / velvet_anchor
        z = self._ew_z(memory, "_hgr_spread", spread, p["cross_alpha"], p["cross_min_samples"], p["std_floor"])
        memory["_hgr_spread_z"] = z
        return z

    def _vertical_z(self, state: TradingState, memory: Dict[str, Any], p: Dict[str, Any]) -> float:
        mids = [self._mid_from_state(state, symbol) for symbol in ATM_VOUCHERS]
        if mids[0] is None or mids[1] is None:
            return float(memory.get("_hgr_vertical_z", 0.0))
        vertical = float(mids[0]) - float(mids[1])
        z = self._ew_z(memory, "_hgr_vertical", vertical, p["cross_alpha"], p["cross_min_samples"], p["std_floor"])
        memory["_hgr_vertical_z"] = z
        return z

    @staticmethod
    def _ew_z(
        memory: Dict[str, Any],
        key: str,
        value: float,
        alpha: float,
        min_samples: int,
        std_floor: float,
    ) -> float:
        count_key = key + "_count"
        mean_key = key + "_mean"
        var_key = key + "_var"
        count = int(memory.get(count_key, 0)) + 1
        mean_prev = float(memory.get(mean_key, value))
        var_prev = float(memory.get(var_key, 0.0))
        delta = value - mean_prev
        mean = mean_prev + alpha * delta
        var = (1.0 - alpha) * (var_prev + alpha * delta * delta)
        std = var ** 0.5 if var > 0 else 0.0
        memory[count_key] = count
        memory[mean_key] = mean
        memory[var_key] = var
        if count < min_samples or std <= std_floor:
            return 0.0
        return (value - mean) / std

    @staticmethod
    def _update_mid_history(memory: Dict[str, Any], ts: int, mid: float, keep_ts: int) -> None:
        HydrogelGuardedReversionMMStrategy._update_symbol_history(memory, "_hgr_mid_hist", ts, mid, keep_ts)

    @staticmethod
    def _update_symbol_history(memory: Dict[str, Any], key: str, ts: int, mid: float, keep_ts: int) -> None:
        hist: List[Tuple[int, float]] = memory.setdefault(key, [])
        hist.append((ts, mid))
        min_ts = ts - keep_ts
        while hist and hist[0][0] < min_ts:
            del hist[0]

    @staticmethod
    def _displacement(memory: Dict[str, Any], ts: int, mid: float, lookback_ts: int) -> Optional[float]:
        return HydrogelGuardedReversionMMStrategy._symbol_displacement(memory, "_hgr_mid_hist", ts, mid, lookback_ts)

    @staticmethod
    def _symbol_displacement(memory: Dict[str, Any], key: str, ts: int, mid: float, lookback_ts: int) -> Optional[float]:
        target_ts = ts - lookback_ts
        hist: List[Tuple[int, float]] = memory.get(key, [])
        if not hist or hist[0][0] > target_ts:
            return None
        past = hist[0][1]
        for hist_ts, hist_mid in hist:
            if hist_ts <= target_ts:
                past = hist_mid
            else:
                break
        return mid - past

    @staticmethod
    def _clip(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    @staticmethod
    def _mode_code(mode: str) -> int:
        return {
            "neutral": 0,
            "soft_bull": 1,
            "soft_bear": 2,
            "hard_bull": 3,
            "hard_bear": 4,
            "wrong_short": 5,
            "wrong_long": 6,
            "exhaustion_buy_armed": 7,
            "exhaustion_sell_armed": 8,
        }.get(mode, -1)

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        cross_window = int(params.get("cross_window", 500))
        slow_lookback = int(params.get("exhaustion_slow_lookback_ts", 20000))
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
            "hard_pos_cap": int(params.get("hard_pos_cap", 80)),
            "wrong_side_pos_gate": int(params.get("wrong_side_pos_gate", 18)),
            "wrong_side_unwind_boost": int(params.get("wrong_side_unwind_boost", 10)),
            "soft_score": float(params.get("soft_score", 0.75)),
            "hard_score": float(params.get("hard_score", 1.25)),
            "soft_reduce_mult": float(params.get("soft_reduce_mult", 0.35)),
            "gate_boost_max": int(params.get("gate_boost_max", 12)),
            "gate_boost_per_score": int(params.get("gate_boost_per_score", 8)),
            "cross_window": cross_window,
            "cross_alpha": float(params.get("cross_alpha", 2.0 / (cross_window + 1))),
            "cross_min_samples": int(params.get("cross_min_samples", 120)),
            "std_floor": float(params.get("std_floor", 0.01)),
            "hydro_anchor_price": params.get("hydro_anchor_price"),
            "velvet_anchor_price": params.get("velvet_anchor_price"),
            "w_vertical": float(params.get("w_vertical", 0.45)),
            "w_spread": float(params.get("w_spread", 0.25)),
            "w_hydro_reversal": float(params.get("w_hydro_reversal", 0.25)),
            "w_hydro_fast": float(params.get("w_hydro_fast", 0.10)),
            "w_velvet": float(params.get("w_velvet", 0.20)),
            "hydro_mom_scale": float(params.get("hydro_mom_scale", 40.0)),
            "hydro_fast_mom_scale": float(params.get("hydro_fast_mom_scale", 18.0)),
            "velvet_mom_scale": float(params.get("velvet_mom_scale", 18.0)),
            "score_clip": float(params.get("score_clip", 2.0)),
            "score_hard_clip": float(params.get("score_hard_clip", 3.0)),
            "enable_theo_taker": bool(params.get("enable_theo_taker", True)),
            "take_threshold": float(params.get("take_threshold", 12.0)),
            "take_size": int(params.get("take_size", 1)),
            "take_cooldown_ts": int(params.get("take_cooldown_ts", 2000)),
            "take_contra_score": float(params.get("take_contra_score", 1.0)),
            "enable_exhaustion_taker": bool(params.get("enable_exhaustion_taker", True)),
            "exhaustion_fast_ticks": float(params.get("exhaustion_fast_ticks", 42.0)),
            "exhaustion_slow_ticks": float(params.get("exhaustion_slow_ticks", 55.0)),
            "exhaustion_slow_lookback_ts": slow_lookback,
            "history_keep_ts": int(params.get("history_keep_ts", slow_lookback + 1000)),
            "exhaustion_size": int(params.get("exhaustion_size", 4)),
            "exhaustion_max_position": int(params.get("exhaustion_max_position", 50)),
            "exhaustion_cooldown_ts": int(params.get("exhaustion_cooldown_ts", 3000)),
            "exhaustion_max_recent_against": float(params.get("exhaustion_max_recent_against", 8.0)),
            "exhaustion_buy_min_score": float(params.get("exhaustion_buy_min_score", -0.10)),
            "exhaustion_sell_min_score": float(params.get("exhaustion_sell_min_score", -0.10)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key in (
            "_hgr_ema",
            "_hgr_fast_ema",
            "_hgr_dev",
            "_hgr_trend",
            "_hgr_score",
            "_hgr_mode_code",
            "_hgr_spread_z",
            "_hgr_vertical_z",
            "_hgr_hydro_mom_10000",
        ):
            value = memory.get(key)
            if value is not None:
                out[key.removeprefix("_hgr_")] = float(value)
        return out
