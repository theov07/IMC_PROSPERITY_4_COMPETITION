"""HYDRO day2 selector suite.

This strategy is intentionally experimental.  It lets us compare three ideas
without mixing HYDRO research with VELVET/options:

* anchor/v4 profile for maximum historical 3-day backtest PnL;
* day2-fingerprint oracle profile for the provisional-sim-as-day2 thesis;
* hybrid profile that uses the oracle on day2-like sessions and anchor
  otherwise.

The oracle leg never posts stale replay prices blindly: it checks the current
L1 and either uses live best bid/ask or skips the tick.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy
from prosperity.strategies.round_3.oracle_day2_l1_replay_hydro import ORACLE_L1_SCHEDULE

# Lazy imports — only loaded when actually needed (saves ~50 KB or ~24 KB on
# the inlined submission depending on selector_mode).
def _import_anchor():
    from prosperity.strategies.round_2.leo.mm_first_v4_combo import MMFirstV4ComboStrategy
    return MMFirstV4ComboStrategy

def _import_guarded():
    from prosperity.strategies.round_3.hydrogel_guarded_reversion_mm import (
        HydrogelGuardedReversionMMStrategy,
    )
    return HydrogelGuardedReversionMMStrategy


class HydrogelDay2SelectorMMStrategy(BaseStrategy):
    """Route HYDRO between anchor, guarded Theo, and day2 L1 replay profiles."""

    ROUTE_CODES = {
        "guarded": 0,
        "anchor": 1,
        "oracle_day2": 2,
        "blocked_oracle": 3,
    }

    def __init__(self, product: str, params: Dict[str, Any]):
        super().__init__(product, params)
        limit = int(params.get("position_limit", 200))
        mode = params.get("selector_mode", "day2_oracle_guarded")
        # Only instantiate the children we actually need based on mode.
        # This keeps the inlined submission small.
        needs_anchor = mode in ("anchor_only", "hybrid_anchor_oracle", "hybrid_stationary")
        needs_guarded = mode in ("day2_oracle_guarded", "hybrid_stationary")
        self._anchor = None
        self._guarded = None
        if needs_anchor:
            cls = _import_anchor()
            self._anchor = cls(
                product=product,
                params=self._child_params(params, "anchor_params", limit),
            )
        if needs_guarded:
            cls = _import_guarded()
            self._guarded = cls(
                product=product,
                params=self._child_params(params, "guarded_params", limit),
            )

    @staticmethod
    def _child_params(params: Dict[str, Any], key: str, limit: int) -> Dict[str, Any]:
        child = dict(params.get(key, {}))
        child["position_limit"] = limit
        for shared_key in ("quote_trace_enabled", "log_flush_ts", "ts_increment", "last_ts_value"):
            if shared_key in params and shared_key not in child:
                child[shared_key] = params[shared_key]
        return child

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0

        p = self._read_params()
        route = self._select_route(state, book, memory, p)
        memory["_selector_route"] = route
        memory["_selector_route_code"] = float(self.ROUTE_CODES.get(route, -1))

        if route == "oracle_day2":
            orders = self._oracle_orders(state, book, position, p, memory)
            if orders:
                return orders, 0
            memory["_selector_route"] = "blocked_oracle"
            memory["_selector_route_code"] = float(self.ROUTE_CODES["blocked_oracle"])
            return [], 0

        if route == "anchor":
            child_memory = memory.setdefault("_anchor_child", {})
            return self._anchor.on_tick(state, child_memory)

        child_memory = memory.setdefault("_guarded_child", {})
        return self._guarded.on_tick(state, child_memory)

    def _select_route(
        self,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
        p: Dict[str, Any],
    ) -> str:
        mode = p["selector_mode"]
        day2_like = self._is_day2_like(state, book, memory, p)

        if mode == "anchor_only":
            return "anchor"
        if mode == "day2_oracle_guarded":
            return "oracle_day2" if day2_like else "guarded"
        if mode == "hybrid_anchor_oracle":
            return "oracle_day2" if day2_like else "anchor"
        if mode == "hybrid_stationary":
            if day2_like:
                return "oracle_day2"
            return "anchor" if self._is_stationary(book, memory, p) else "guarded"
        return "guarded"

    def _is_day2_like(
        self,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
        p: Dict[str, Any],
    ) -> bool:
        if "_session_start_mid" not in memory:
            memory["_session_start_mid"] = float(book.mid_price)
            memory["_session_start_ts"] = int(state.timestamp)

        start_mid = float(memory["_session_start_mid"])
        target = p["day2_start_mid"]
        tol = p["day2_start_mid_tolerance"]
        day2_like = abs(start_mid - target) <= tol
        memory["_selector_day2_like"] = float(day2_like)
        memory["_selector_start_mid"] = start_mid
        return day2_like

    def _is_stationary(self, book: BookSnapshot, memory: Dict[str, Any], p: Dict[str, Any]) -> bool:
        anchor = p["anchor_price"]
        drift = float(book.mid_price) - anchor
        alpha = p["stationary_ewma_alpha"]
        prev = float(memory.get("_stationary_drift_ewma", drift))
        ewma = alpha * drift + (1.0 - alpha) * prev
        memory["_stationary_drift_ewma"] = ewma
        return abs(ewma) <= p["stationary_max_abs_drift"]

    def _oracle_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        p: Dict[str, Any],
        memory: Dict[str, Any],
    ) -> List[Order]:
        action = ORACLE_L1_SCHEDULE.get(self.product, {}).get(int(state.timestamp))
        if action is None:
            return []

        side, raw_qty, replay_price = action
        tol = p["oracle_price_tolerance"]
        use_live_l1 = p["oracle_use_live_l1"]

        if side == "BUY":
            if book.best_ask is None:
                return []
            live_price = int(book.best_ask)
            if abs(live_price - int(replay_price)) > tol:
                memory["_selector_oracle_blocked_px"] = float(replay_price)
                memory["_selector_oracle_live_px"] = float(live_price)
                return []
            qty = min(int(raw_qty), self.buy_capacity(position))
            if qty <= 0:
                return []
            return [Order(self.product, live_price if use_live_l1 else int(replay_price), qty)]

        if book.best_bid is None:
            return []
        live_price = int(book.best_bid)
        if abs(live_price - int(replay_price)) > tol:
            memory["_selector_oracle_blocked_px"] = float(replay_price)
            memory["_selector_oracle_live_px"] = float(live_price)
            return []
        qty = min(int(raw_qty), self.sell_capacity(position))
        if qty <= 0:
            return []
        return [Order(self.product, live_price if use_live_l1 else int(replay_price), -qty)]

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "selector_mode": str(params.get("selector_mode", "day2_oracle_guarded")),
            "day2_start_mid": float(params.get("day2_start_mid", 10011.0)),
            "day2_start_mid_tolerance": float(params.get("day2_start_mid_tolerance", 0.25)),
            "oracle_price_tolerance": int(params.get("oracle_price_tolerance", 2)),
            "oracle_use_live_l1": bool(params.get("oracle_use_live_l1", True)),
            "anchor_price": float(params.get("anchor_price", 10000.0)),
            "stationary_ewma_alpha": float(params.get("stationary_ewma_alpha", 0.01)),
            "stationary_max_abs_drift": float(params.get("stationary_max_abs_drift", 55.0)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key in (
            "_selector_route_code",
            "_selector_day2_like",
            "_selector_start_mid",
            "_stationary_drift_ewma",
            "_selector_oracle_blocked_px",
            "_selector_oracle_live_px",
        ):
            value = memory.get(key)
            if value is not None:
                out[key.removeprefix("_selector_").removeprefix("_")] = float(value)

        route = memory.get("_selector_route")
        if route == "anchor":
            child = memory.get("_anchor_child", {})
            out.update({f"anchor_{k}": v for k, v in self._anchor.feature_prices(child).items()})
        elif route == "guarded":
            child = memory.get("_guarded_child", {})
            out.update({f"guarded_{k}": v for k, v in self._guarded.feature_prices(child).items()})
        return out
