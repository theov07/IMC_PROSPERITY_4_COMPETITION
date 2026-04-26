"""HYDRO day2 oracle + anchor — slim version (no guarded fallback).

Stripped from hydrogel_day2_selector_mm to reduce inlined submission size.
Used by r3_hydro_anchor_oracle_hybrid.

Logic:
  - day2 fingerprint detected → use L1 oracle replay
  - otherwise → use anchor v4 profile

Skips the guarded Theo profile entirely (saves ~24 KB on inlined submission).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy
from prosperity.strategies.round_2.leo.mm_first_v4_combo import MMFirstV4ComboStrategy
from prosperity.strategies.round_3.oracle_day2_l1_replay_hydro import ORACLE_L1_SCHEDULE


class HydrogelDay2OracleAnchorStrategy(BaseStrategy):
    """day2 fingerprint → L1 oracle replay; otherwise → anchor v4."""

    ROUTE_CODES = {"anchor": 1, "oracle_day2": 2, "blocked_oracle": 3}

    def __init__(self, product: str, params: Dict[str, Any]):
        super().__init__(product, params)
        limit = int(params.get("position_limit", 200))
        self._anchor = MMFirstV4ComboStrategy(
            product=product,
            params=self._child_params(params, "anchor_params", limit),
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
        day2_like = self._is_day2_like(state, book, memory, p)
        if day2_like:
            orders = self._oracle_orders(state, book, position, p, memory)
            if orders:
                memory["_route"] = "oracle_day2"
                return orders, 0
            # No oracle entry at this ts AND day 2 detected → SKIP (no anchor fallback,
            # otherwise anchor would lose on the day 2 drift between oracle ticks).
            memory["_route"] = "blocked_oracle"
            return [], 0
        # Not day 2 → use anchor
        memory["_route"] = "anchor"
        child_mem = memory.setdefault("_anchor_mem", {})
        return self._anchor.on_tick(state, child_mem)

    # ── Day 2 fingerprint ────────────────────────────────────────────────

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
        return abs(start_mid - p["day2_start_mid"]) <= p["day2_start_mid_tolerance"]

    # ── Oracle L1 replay ─────────────────────────────────────────────────

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
        side, qty, price = action
        if not p.get("oracle_use_live_l1", True):
            target_price = price
        else:
            tolerance = p["oracle_price_tolerance"]
            if side == "BUY":
                live_p = book.best_ask
                if live_p is None or abs(int(live_p) - price) > tolerance:
                    return []
                target_price = int(live_p)
            elif side == "SELL":
                live_p = book.best_bid
                if live_p is None or abs(int(live_p) - price) > tolerance:
                    return []
                target_price = int(live_p)
            else:
                return []
        if side == "BUY":
            return [Order(self.product, target_price, qty)]
        elif side == "SELL":
            return [Order(self.product, target_price, -qty)]
        return []

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "day2_start_mid": float(params.get("day2_start_mid", 10011.0)),
            "day2_start_mid_tolerance": float(params.get("day2_start_mid_tolerance", 0.25)),
            "oracle_price_tolerance": int(params.get("oracle_price_tolerance", 2)),
            "oracle_use_live_l1": bool(params.get("oracle_use_live_l1", True)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (r := memory.get("_route")) is not None:
            out["route_code"] = float(self.ROUTE_CODES.get(r, -1))
        return out
