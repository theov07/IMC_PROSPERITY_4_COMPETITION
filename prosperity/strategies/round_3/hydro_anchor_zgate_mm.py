"""HYDRO anchor MM with VELVET-style z-score mean-reversion gates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_2.leo.mm_first_v4_combo import MMFirstV4ComboStrategy


class HydroAnchorZGateMMStrategy(MMFirstV4ComboStrategy):
    """R2/v4 anchor MM plus z-score gates/takers on HYDRO itself."""

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

        p = self._z_params()
        ts = int(state.timestamp)
        mid = float(book.mid_price)
        z = self._update_z(mid, memory, p["zscore_window"])
        memory["_hzg_z"] = z

        orders, conversions = super().compute_orders(state, book, order_depth, position, memory)
        if z is None:
            return orders, conversions

        side = 0
        if z > p["skip_threshold"]:
            # HYDRO expensive: keep sells, block buys that add wrong-way long.
            orders = [order for order in orders if order.quantity < 0]
            side = -1
        elif z < -p["skip_threshold"]:
            # HYDRO cheap: keep buys, block sells that add wrong-way short.
            orders = [order for order in orders if order.quantity > 0]
            side = 1

        if p["enable_taker"] and abs(z) >= p["taker_threshold"]:
            if ts >= int(memory.get("_hzg_cooldown_until", 0)):
                used_buy = sum(max(order.quantity, 0) for order in orders)
                used_sell = sum(max(-order.quantity, 0) for order in orders)
                buy_cap = max(0, self.buy_capacity(position) - used_buy)
                sell_cap = max(0, self.sell_capacity(position) - used_sell)
                if side > 0 and buy_cap > 0:
                    available = -order_depth.sell_orders.get(book.best_ask, 0)
                    qty = min(p["taker_size"], buy_cap, available)
                    if qty > 0:
                        orders.append(Order(self.product, int(book.best_ask), qty))
                        memory["_hzg_cooldown_until"] = ts + p["cooldown_ts"]
                elif side < 0 and sell_cap > 0:
                    available = order_depth.buy_orders.get(book.best_bid, 0)
                    qty = min(p["taker_size"], sell_cap, available)
                    if qty > 0:
                        orders.append(Order(self.product, int(book.best_bid), -qty))
                        memory["_hzg_cooldown_until"] = ts + p["cooldown_ts"]

        memory["_hzg_side"] = float(side)
        return orders, conversions

    @staticmethod
    def _update_z(mid: float, memory: Dict[str, Any], window: int) -> Optional[float]:
        buf: List[float] = memory.setdefault("_hzg_zbuf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(20, window // 4):
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(1, n - 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (mid - mean) / std

    def _z_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "zscore_window": int(params.get("hzg_zscore_window", 500)),
            "skip_threshold": float(params.get("hzg_skip_threshold", 0.5)),
            "enable_taker": bool(params.get("hzg_enable_taker", False)),
            "taker_threshold": float(params.get("hzg_taker_threshold", 1.5)),
            "taker_size": int(params.get("hzg_taker_size", 6)),
            "cooldown_ts": int(params.get("hzg_cooldown_ts", 1000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (z := memory.get("_hzg_z")) is not None:
            out["HZG_Z"] = float(z)
        if (s := memory.get("_hzg_side")) is not None:
            out["HZG_Side"] = float(s)
        return out
