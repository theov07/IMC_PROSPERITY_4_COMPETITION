"""VELVET R2/v4 MM with a small exhaustion reversion overlay."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_2.leo.mm_first_v4_combo import MMFirstV4ComboStrategy


class VelvetR2ExhaustionMMStrategy(MMFirstV4ComboStrategy):
    """Keep the R2/v4 anchor MM and add a tiny L1 mean-reversion taker.

    This ports the HYDRO lesson: if a reversion taker is armed, do not leave the
    opposite passive quote live on the same tick.
    """

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.mid_price is None:
            return super().compute_orders(state, book, order_depth, position, memory)

        p = self._overlay_params()
        ts = int(state.timestamp)
        mid = float(book.mid_price)
        z, displacement, short_mom = self._update_overlay_state(ts, mid, memory, p)
        side, reason = self._signal_side(z, displacement, short_mom, memory, ts, p)

        base_orders, conversions = super().compute_orders(state, book, order_depth, position, memory)
        orders = list(base_orders)

        if side == 0:
            self._save_overlay_features(memory, z, displacement, short_mom, 0, "none")
            return orders, conversions

        if p["suppress_opposite_orders"]:
            if side > 0:
                orders = [order for order in orders if order.quantity > 0]
            else:
                orders = [order for order in orders if order.quantity < 0]

        used_buy = sum(max(order.quantity, 0) for order in orders)
        used_sell = sum(max(-order.quantity, 0) for order in orders)
        buy_cap = max(0, self.buy_capacity(position) - used_buy)
        sell_cap = max(0, self.sell_capacity(position) - used_sell)

        if side > 0 and buy_cap > 0:
            available = -order_depth.sell_orders.get(book.best_ask, 0)
            qty = min(p["taker_size"], buy_cap, available)
            if qty > 0:
                orders.append(Order(self.product, int(book.best_ask), qty))
                memory["_vex_cooldown_until"] = ts + p["cooldown_ts"]
        elif side < 0 and sell_cap > 0:
            available = order_depth.buy_orders.get(book.best_bid, 0)
            qty = min(p["taker_size"], sell_cap, available)
            if qty > 0:
                orders.append(Order(self.product, int(book.best_bid), -qty))
                memory["_vex_cooldown_until"] = ts + p["cooldown_ts"]

        self._save_overlay_features(memory, z, displacement, short_mom, side, reason)
        return orders, conversions

    def _update_overlay_state(
        self,
        ts: int,
        mid: float,
        memory: Dict[str, Any],
        p: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        hist: List[List[float]] = memory.setdefault("_vex_hist", [])
        hist.append([float(ts), mid])
        keep_from = ts - max(p["lookback_ts"], p["short_lookback_ts"]) - 1000
        while hist and hist[0][0] < keep_from:
            hist.pop(0)

        zbuf: List[float] = memory.setdefault("_vex_zbuf", [])
        zbuf.append(mid)
        if len(zbuf) > p["zscore_window"]:
            zbuf[:] = zbuf[-p["zscore_window"]:]
        z = self._zscore(zbuf)

        displacement = self._displacement(hist, ts - p["lookback_ts"], mid)
        short_mom = self._displacement(hist, ts - p["short_lookback_ts"], mid)
        return z, displacement, short_mom

    @staticmethod
    def _zscore(buf: List[float]) -> Optional[float]:
        if len(buf) < max(3, len(buf) // 4):
            return None
        n = len(buf)
        if n < 20:
            return None
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(1, n - 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (buf[-1] - mean) / std

    @staticmethod
    def _displacement(hist: List[List[float]], target_ts: int, mid: float) -> Optional[float]:
        ref = None
        for row_ts, row_mid in reversed(hist):
            if row_ts <= target_ts:
                ref = row_mid
                break
        if ref is None:
            return None
        return mid - float(ref)

    def _signal_side(
        self,
        z: Optional[float],
        displacement: Optional[float],
        short_mom: Optional[float],
        memory: Dict[str, Any],
        ts: int,
        p: Dict[str, Any],
    ) -> Tuple[int, str]:
        if ts < int(memory.get("_vex_cooldown_until", 0)):
            return 0, "cooldown"

        side = 0
        reason = "none"
        if z is not None and abs(z) >= p["z_threshold"]:
            side = -1 if z > 0 else 1
            reason = "z"

        if displacement is not None and abs(displacement) >= p["displacement_threshold"]:
            disp_side = -1 if displacement > 0 else 1
            if side and side != disp_side and not p["allow_conflict"]:
                return 0, "conflict"
            side = disp_side
            reason = "disp" if reason == "none" else "both"

        if side == 0:
            return 0, reason

        if short_mom is not None and p["cascade_threshold"] > 0:
            if side > 0 and short_mom <= -p["cascade_threshold"]:
                return 0, "cascade_down"
            if side < 0 and short_mom >= p["cascade_threshold"]:
                return 0, "cascade_up"

        return side, reason

    def _overlay_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "zscore_window": int(params.get("overlay_zscore_window", 500)),
            "z_threshold": float(params.get("overlay_z_threshold", 2.0)),
            "lookback_ts": int(params.get("overlay_lookback_ts", 10000)),
            "short_lookback_ts": int(params.get("overlay_short_lookback_ts", 1000)),
            "displacement_threshold": float(params.get("overlay_displacement_threshold", 30.0)),
            "cascade_threshold": float(params.get("overlay_cascade_threshold", 8.0)),
            "taker_size": int(params.get("overlay_taker_size", 6)),
            "cooldown_ts": int(params.get("overlay_cooldown_ts", 1000)),
            "allow_conflict": bool(params.get("overlay_allow_conflict", False)),
            "suppress_opposite_orders": bool(params.get("overlay_suppress_opposite_orders", True)),
        }

    @staticmethod
    def _save_overlay_features(
        memory: Dict[str, Any],
        z: Optional[float],
        displacement: Optional[float],
        short_mom: Optional[float],
        side: int,
        reason: str,
    ) -> None:
        memory["_vex_z"] = z
        memory["_vex_displacement"] = displacement
        memory["_vex_short_mom"] = short_mom
        memory["_vex_side"] = float(side)
        memory["_vex_reason_code"] = {"none": 0.0, "z": 1.0, "disp": 2.0, "both": 3.0}.get(reason, -1.0)

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (z := memory.get("_vex_z")) is not None:
            out["VEX_Z"] = float(z)
        if (d := memory.get("_vex_displacement")) is not None:
            out["VEX_Disp"] = float(d)
        if (s := memory.get("_vex_side")) is not None:
            out["VEX_Side"] = float(s)
        return out
