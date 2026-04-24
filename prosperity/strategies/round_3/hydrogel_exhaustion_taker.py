"""HYDROGEL exhaustion taker.

This strategy is the generalizable version of the HYDROGEL lesson from the
day-2 oracle: do not quote passively into adverse selection; take the other side
after a large prior displacement and hold for a medium-horizon reversal.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelExhaustionTakerStrategy(BaseStrategy):
    """Contrarian taker on large HYDROGEL displacements."""

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
        ts = int(state.timestamp)
        self._update_mid_history(memory, ts, mid, p["history_keep_ts"])

        disp_fast = self._displacement(memory, ts, mid, p["fast_lookback_ts"])
        disp_slow = self._displacement(memory, ts, mid, p["slow_lookback_ts"])
        warm = disp_fast is not None and disp_slow is not None

        mode = "warmup"
        signal = 0
        if warm:
            signal = self._entry_signal(float(disp_fast), float(disp_slow), p)
            mode = {1: "long_exhaustion", -1: "short_exhaustion", 0: "hold"}.get(signal, "hold")

        orders: List[Order] = []
        tranches: List[Dict[str, int]] = memory.setdefault("_het_tranches", [])
        self._clean_tranches(tranches)

        if warm:
            exit_order = self._matured_exit_order(book, order_depth, position, tranches, ts, p)
            if exit_order is not None:
                orders.append(exit_order)
                mode = "horizon_exit"
            else:
                next_entry_ts = int(memory.get("_het_next_entry_ts", -1))
                if signal != 0 and ts >= next_entry_ts and not (position and position * signal < 0):
                    entry_order = self._entry_order(book, order_depth, position, signal, ts, tranches, p, mode)
                    if entry_order is not None:
                        orders.append(entry_order)
                        memory["_het_next_entry_ts"] = ts + p["cooldown_ts"]

        memory["_het_mid"] = mid
        memory["_het_disp_fast"] = float(disp_fast) if disp_fast is not None else 0.0
        memory["_het_disp_slow"] = float(disp_slow) if disp_slow is not None else 0.0
        memory["_het_signal"] = float(signal)
        memory["_het_tranche_qty"] = float(sum(int(t.get("qty", 0)) for t in tranches))
        memory["_het_mode_code"] = float(
            {
                "warmup": 0,
                "hold": 1,
                "long_exhaustion": 2,
                "short_exhaustion": 3,
                "horizon_exit": 4,
            }.get(mode, -1)
        )
        return orders, 0

    @staticmethod
    def _entry_signal(disp_fast: float, disp_slow: float, params: Dict[str, Any]) -> int:
        if disp_fast <= -params["entry_fast_ticks"] or disp_slow <= -params["entry_slow_ticks"]:
            return 1
        if disp_fast >= params["entry_fast_ticks"] or disp_slow >= params["entry_slow_ticks"]:
            return -1
        return 0

    def _entry_order(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        signal: int,
        ts: int,
        tranches: List[Dict[str, int]],
        params: Dict[str, Any],
        mode: str,
    ) -> Order | None:
        max_pos = min(params["max_position"], self.position_limit())
        size = params["taker_size"]
        if signal > 0:
            qty_needed = max(0, max_pos - position)
            orders = self._buy_orders(book, order_depth, position, qty_needed, size, params, mode)
            if not orders:
                return None
            qty = int(orders[0].quantity)
            tranches.append({"side": 1, "qty": qty, "exit_ts": ts + params["hold_ts"]})
            return orders[0]
        qty_needed = max(0, max_pos + position)
        orders = self._sell_orders(book, order_depth, position, qty_needed, size, params, mode)
        if not orders:
            return None
        qty = int(-orders[0].quantity)
        tranches.append({"side": -1, "qty": qty, "exit_ts": ts + params["hold_ts"]})
        return orders[0]

    def _matured_exit_order(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        tranches: List[Dict[str, int]],
        ts: int,
        params: Dict[str, Any],
    ) -> Order | None:
        matured_long = sum(int(t["qty"]) for t in tranches if int(t.get("side", 0)) > 0 and int(t.get("exit_ts", 0)) <= ts)
        matured_short = sum(int(t["qty"]) for t in tranches if int(t.get("side", 0)) < 0 and int(t.get("exit_ts", 0)) <= ts)
        if matured_long > 0 and position > 0:
            orders = self._sell_orders(book, order_depth, position, min(matured_long, position), params["exit_size"], params, "horizon_exit")
            if orders:
                self._consume_tranches(tranches, side=1, qty=int(-orders[0].quantity))
                return orders[0]
        if matured_short > 0 and position < 0:
            orders = self._buy_orders(book, order_depth, position, min(matured_short, -position), params["exit_size"], params, "horizon_exit")
            if orders:
                self._consume_tranches(tranches, side=-1, qty=int(orders[0].quantity))
                return orders[0]
        return None

    def _buy_orders(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        qty_needed: int,
        max_size: int,
        params: Dict[str, Any],
        mode: str,
    ) -> List[Order]:
        buy_cap = self.buy_capacity(position)
        if buy_cap <= 0:
            return []
        price, available = self._take_price_and_available(order_depth.sell_orders, is_buy=True, params=params, mode=mode)
        qty = min(qty_needed, buy_cap, max_size, available)
        if price is None or qty <= 0:
            return []
        return [Order(self.product, price, qty)]

    def _sell_orders(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        qty_needed: int,
        max_size: int,
        params: Dict[str, Any],
        mode: str,
    ) -> List[Order]:
        sell_cap = self.sell_capacity(position)
        if sell_cap <= 0:
            return []
        price, available = self._take_price_and_available(order_depth.buy_orders, is_buy=False, params=params, mode=mode)
        qty = min(qty_needed, sell_cap, max_size, available)
        if price is None or qty <= 0:
            return []
        return [Order(self.product, price, -qty)]

    def _take_price_and_available(
        self,
        side_book: Dict[int, int],
        *,
        is_buy: bool,
        params: Dict[str, Any],
        mode: str,
    ) -> Tuple[int | None, int]:
        if not side_book:
            return None, 0
        allow_l2 = bool(params["allow_l2"]) and mode in {"long_exhaustion", "short_exhaustion"}
        levels = sorted(side_book.items(), key=lambda item: item[0], reverse=not is_buy)
        selected = levels[:2] if allow_l2 and len(levels) > 1 else levels[:1]
        if not selected:
            return None, 0
        price = selected[-1][0]
        available = 0
        for _, qty in selected:
            available += abs(int(qty))
        return int(price), int(available)

    @staticmethod
    def _update_mid_history(memory: Dict[str, Any], ts: int, mid: float, keep_ts: int) -> None:
        hist: List[Tuple[int, float]] = memory.setdefault("_het_mid_hist", [])
        hist.append((ts, mid))
        min_ts = ts - keep_ts
        while hist and hist[0][0] < min_ts:
            del hist[0]

    @staticmethod
    def _displacement(memory: Dict[str, Any], ts: int, mid: float, lookback_ts: int) -> float | None:
        target_ts = ts - lookback_ts
        hist: List[Tuple[int, float]] = memory.get("_het_mid_hist", [])
        if not hist or hist[0][0] > target_ts:
            return None
        past = hist[0][1]
        for h_ts, h_mid in hist:
            if h_ts <= target_ts:
                past = h_mid
            else:
                break
        return mid - past

    @staticmethod
    def _clean_tranches(tranches: List[Dict[str, int]]) -> None:
        tranches[:] = [t for t in tranches if int(t.get("qty", 0)) > 0 and int(t.get("side", 0)) != 0]

    @staticmethod
    def _consume_tranches(tranches: List[Dict[str, int]], *, side: int, qty: int) -> None:
        remaining = qty
        for tranche in tranches:
            if remaining <= 0:
                break
            if int(tranche.get("side", 0)) != side:
                continue
            take = min(remaining, int(tranche.get("qty", 0)))
            tranche["qty"] = int(tranche.get("qty", 0)) - take
            remaining -= take
        HydrogelExhaustionTakerStrategy._clean_tranches(tranches)

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        slow_lookback = int(params.get("slow_lookback_ts", 20000))
        return {
            "fast_lookback_ts": int(params.get("fast_lookback_ts", 10000)),
            "slow_lookback_ts": slow_lookback,
            "history_keep_ts": int(params.get("history_keep_ts", slow_lookback + 1000)),
            "entry_fast_ticks": float(params.get("entry_fast_ticks", 40.0)),
            "entry_slow_ticks": float(params.get("entry_slow_ticks", 40.0)),
            "max_position": int(params.get("max_position", 120)),
            "taker_size": int(params.get("taker_size", 15)),
            "exit_size": int(params.get("exit_size", params.get("taker_size", 15))),
            "cooldown_ts": int(params.get("cooldown_ts", 1000)),
            "hold_ts": int(params.get("hold_ts", 20000)),
            "allow_l2": bool(params.get("allow_l2", False)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key in (
            "_het_mid",
            "_het_disp_fast",
            "_het_disp_slow",
            "_het_signal",
            "_het_tranche_qty",
            "_het_mode_code",
        ):
            if (value := memory.get(key)) is not None:
                out[key.removeprefix("_het_")] = float(value)
        return out
