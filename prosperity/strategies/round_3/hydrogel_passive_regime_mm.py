"""HYDROGEL passive MM with cross-asset regime risk throttles.

This is deliberately not an anchor/mean-reversion strategy.  The discovered
HYDROGEL edge is passive spread capture inside a wide book; VELVET/HYDROGEL
regimes are only used as risk controls.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base.base import BaseStrategy


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"

REGIME_CODES = {
    "WARMUP": 0,
    "NODE": 1,
    "NEG_COUPLED": 2,
    "POS_COUPLED": 3,
    "DECOUPLED": 4,
    "MIXED": 5,
}


def _mid_from_state(state: TradingState, symbol: str) -> float | None:
    depth = state.order_depths.get(symbol)
    if depth is None:
        return None
    return snapshot_from_order_depth(symbol, depth).mid_price


def _rolling_corr(xs: List[float], ys: List[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    x = xs[-n:]
    y = ys[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    vx = 0.0
    vy = 0.0
    cov = 0.0
    for xv, yv in zip(x, y):
        dx = xv - mx
        dy = yv - my
        vx += dx * dx
        vy += dy * dy
        cov += dx * dy
    denom = math.sqrt(vx * vy)
    return cov / denom if denom > 1e-12 else 0.0


class HydrogelPassiveRegimeMMStrategy(BaseStrategy):
    """Passive-only HYDROGEL MM with dynamic caps and wrong-side inventory guard."""

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

        spread = book.best_ask - book.best_bid
        if spread < int(self.params.get("min_spread", 3)):
            return [], 0

        mid = float(book.mid_price)
        regime = self._regime(state, memory, mid)
        fast, slow, momentum = self._trend_state(memory, mid)

        cap = self._dynamic_cap(regime["name"])
        buy_cap = max(0, cap - position)
        sell_cap = max(0, cap + position)

        bid_price, ask_price = self._base_quotes(book)
        bid_mult, ask_mult = self._base_multipliers(regime["name"])
        bid_mult, ask_mult = self._apply_inventory_aversion(
            bid_mult=bid_mult,
            ask_mult=ask_mult,
            position=position,
            cap=max(1, cap),
        )

        kill = self._wrong_side_kill(position=position, mid=mid, slow=slow, momentum=momentum)
        if kill == "LONG":
            bid_mult = 0.0
            ask_mult = max(ask_mult, float(self.params.get("kill_exit_mult", 2.0)))
            ask_price = self._exit_ask(book)
        elif kill == "SHORT":
            ask_mult = 0.0
            bid_mult = max(bid_mult, float(self.params.get("kill_exit_mult", 2.0)))
            bid_price = self._exit_bid(book)

        base_size = int(self.params.get("maker_size", 60))
        bid_size = min(buy_cap, self._scaled_size(base_size, bid_mult))
        ask_size = min(sell_cap, self._scaled_size(base_size, ask_mult))

        orders: List[Order] = []
        if bid_price is not None and bid_size > 0:
            orders.append(Order(self.product, bid_price, bid_size))
        if ask_price is not None and ask_size > 0:
            orders.append(Order(self.product, ask_price, -ask_size))

        memory["_hpr_mid"] = mid
        memory["_hpr_fast"] = fast
        memory["_hpr_slow"] = slow
        memory["_hpr_momentum"] = momentum
        memory["_hpr_cap"] = float(cap)
        memory["_hpr_bid_mult"] = bid_mult
        memory["_hpr_ask_mult"] = ask_mult
        memory["_hpr_kill"] = 1.0 if kill else 0.0
        memory["_hpr_regime_code"] = float(REGIME_CODES[regime["name"]])
        memory["_hpr_corr"] = float(regime["corr"])
        memory["_hpr_spread_norm"] = float(regime["spread"])

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "regime": REGIME_CODES[regime["name"]],
                "corr": round(float(regime["corr"]), 4),
                "spread_norm": round(float(regime["spread"]), 4),
                "cap": cap,
                "bid_mult": round(bid_mult, 3),
                "ask_mult": round(ask_mult, 3),
                "kill": kill or "",
            },
        )
        return orders, 0

    def _base_quotes(self, book: BookSnapshot) -> Tuple[int | None, int | None]:
        improve = int(self.params.get("improve_ticks", 1))
        bid = int(min(book.best_bid + improve, book.best_ask - 1))
        ask = int(max(book.best_ask - improve, book.best_bid + 1))
        if bid >= ask:
            return None, None
        return bid, ask

    def _exit_bid(self, book: BookSnapshot) -> int:
        improve = int(self.params.get("kill_exit_improve_ticks", 3))
        return int(min(book.best_bid + improve, book.best_ask - 1))

    def _exit_ask(self, book: BookSnapshot) -> int:
        improve = int(self.params.get("kill_exit_improve_ticks", 3))
        return int(max(book.best_ask - improve, book.best_bid + 1))

    def _regime(self, state: TradingState, memory: Dict[str, Any], h_mid: float) -> Dict[str, Any]:
        v_mid = _mid_from_state(state, VELVET)
        ts = int(state.timestamp)
        if v_mid is None or v_mid <= 0 or h_mid <= 0:
            return {"timestamp": ts, "name": "WARMUP", "corr": 0.0, "spread": 0.0}

        h0 = float(memory.setdefault("_hpr_h0", h_mid))
        v0 = float(memory.setdefault("_hpr_v0", v_mid))
        h_norm = 100.0 * h_mid / h0
        v_norm = 100.0 * v_mid / v0
        spread = h_norm - v_norm

        window = int(self.params.get("regime_window", 120))
        min_samples = int(self.params.get("regime_min_samples", 60))
        keep = max(window, min_samples) + 5
        h_hist = memory.setdefault("_hpr_h_norm_hist", [])
        v_hist = memory.setdefault("_hpr_v_norm_hist", [])
        h_hist.append(round(h_norm, 4))
        v_hist.append(round(v_norm, 4))
        if len(h_hist) > keep:
            del h_hist[:-keep]
        if len(v_hist) > keep:
            del v_hist[:-keep]

        samples = min(len(h_hist), len(v_hist))
        corr_window = min(window, samples)
        corr = _rolling_corr(h_hist[-corr_window:], v_hist[-corr_window:])
        if samples < min_samples:
            name = "WARMUP"
        elif abs(spread) <= float(self.params.get("node_threshold", 0.10)):
            name = "NODE"
        elif corr <= float(self.params.get("neg_corr_threshold", -0.55)):
            name = "NEG_COUPLED"
        elif corr >= float(self.params.get("pos_corr_threshold", 0.55)):
            name = "POS_COUPLED"
        elif abs(corr) <= float(self.params.get("decorr_threshold", 0.15)):
            name = "DECOUPLED"
        else:
            name = "MIXED"

        return {"timestamp": ts, "name": name, "corr": round(corr, 4), "spread": round(spread, 4)}

    def _dynamic_cap(self, regime_name: str) -> int:
        limit = min(int(self.params.get("max_position", self.position_limit())), self.position_limit())
        ratios = {
            "WARMUP": float(self.params.get("cap_warmup", 0.55)),
            "NODE": float(self.params.get("cap_node", 0.45)),
            "NEG_COUPLED": float(self.params.get("cap_neg", 0.35)),
            "POS_COUPLED": float(self.params.get("cap_pos", 0.60)),
            "DECOUPLED": float(self.params.get("cap_decoupled", 0.85)),
            "MIXED": float(self.params.get("cap_mixed", 0.65)),
        }
        ratio = max(0.05, min(1.0, ratios.get(regime_name, 0.55)))
        return max(1, int(round(limit * ratio)))

    def _base_multipliers(self, regime_name: str) -> Tuple[float, float]:
        mult = {
            "WARMUP": float(self.params.get("size_warmup", 0.75)),
            "NODE": float(self.params.get("size_node", 0.55)),
            "NEG_COUPLED": float(self.params.get("size_neg", 0.35)),
            "POS_COUPLED": float(self.params.get("size_pos", 0.70)),
            "DECOUPLED": float(self.params.get("size_decoupled", 1.15)),
            "MIXED": float(self.params.get("size_mixed", 0.85)),
        }.get(regime_name, 0.75)
        return mult, mult

    def _apply_inventory_aversion(
        self,
        *,
        bid_mult: float,
        ask_mult: float,
        position: int,
        cap: int,
    ) -> Tuple[float, float]:
        pressure = min(1.0, abs(position) / float(max(1, cap)))
        power = float(self.params.get("inventory_power", 2.0))
        cut = max(0.0, 1.0 - pressure) ** power
        min_worsen = float(self.params.get("min_worsen_mult", 0.0))
        exit_boost = float(self.params.get("inventory_exit_boost", 1.4))
        soft = float(self.params.get("soft_inventory_ratio", 0.55))

        if position > 0:
            bid_mult *= max(min_worsen, cut)
            ask_mult *= 1.0 + exit_boost * pressure
            if pressure >= soft:
                bid_mult *= float(self.params.get("soft_worsen_mult", 0.15))
        elif position < 0:
            ask_mult *= max(min_worsen, cut)
            bid_mult *= 1.0 + exit_boost * pressure
            if pressure >= soft:
                ask_mult *= float(self.params.get("soft_worsen_mult", 0.15))
        return bid_mult, ask_mult

    def _trend_state(self, memory: Dict[str, Any], mid: float) -> Tuple[float, float, float]:
        fast_alpha = float(self.params.get("fast_alpha", 0.25))
        slow_alpha = float(self.params.get("slow_alpha", 0.03))
        fast_prev = float(memory.get("_hpr_fast", mid))
        slow_prev = float(memory.get("_hpr_slow", mid))
        fast = fast_alpha * mid + (1.0 - fast_alpha) * fast_prev
        slow = slow_alpha * mid + (1.0 - slow_alpha) * slow_prev

        lookback = int(self.params.get("momentum_lookback", 40))
        hist = memory.setdefault("_hpr_mid_hist", [])
        hist.append(round(mid, 2))
        if len(hist) > lookback + 1:
            del hist[: -(lookback + 1)]
        ref = hist[0] if len(hist) <= lookback else hist[-lookback - 1]
        momentum = mid - float(ref)
        return fast, slow, momentum

    def _wrong_side_kill(self, *, position: int, mid: float, slow: float, momentum: float) -> str | None:
        threshold = int(self.params.get("kill_position", 120))
        if abs(position) < threshold:
            return None
        dist = mid - slow
        dist_trigger = float(self.params.get("kill_dist_ticks", 8.0))
        mom_trigger = float(self.params.get("kill_momentum_ticks", 12.0))
        if position > 0 and (dist <= -dist_trigger or momentum <= -mom_trigger):
            return "LONG"
        if position < 0 and (dist >= dist_trigger or momentum >= mom_trigger):
            return "SHORT"
        return None

    def _scaled_size(self, base_size: int, mult: float) -> int:
        if base_size <= 0 or mult <= 0.0:
            return 0
        return max(1, int(round(base_size * mult)))

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key, label in [
            ("_hpr_fast", "HPR_fast"),
            ("_hpr_slow", "HPR_slow"),
            ("_hpr_cap", "HPR_cap"),
            ("_hpr_regime_code", "HPR_regime"),
            ("_hpr_corr", "HPR_corr"),
            ("_hpr_spread_norm", "HPR_spread"),
            ("_hpr_bid_mult", "HPR_bid_mult"),
            ("_hpr_ask_mult", "HPR_ask_mult"),
            ("_hpr_kill", "HPR_kill"),
        ]:
            if (value := memory.get(key)) is not None:
                out[label] = float(value)
        return out
