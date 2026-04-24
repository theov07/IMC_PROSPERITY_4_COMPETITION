"""Round 3 regime-switching layer for HYDROGEL / VELVET / VEV options.

The signal is intentionally conservative: it does not pair-trade HYDROGEL
against VELVET.  It classifies the current cross-asset state, then uses that
state as a sizing/skew overlay on top of simple passive market making.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base.base import BaseStrategy
from prosperity.strategies.round_3.option_mm_bs import OptionMMBSStrategy


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"

REGIME_WARMUP = 0
REGIME_NODE = 1
REGIME_NEG_COUPLED = 2
REGIME_POS_COUPLED = 3
REGIME_DECOUPLED = 4
REGIME_MIXED = 5

_REGIME_CODES = {
    "WARMUP": REGIME_WARMUP,
    "NODE": REGIME_NODE,
    "NEG_COUPLED": REGIME_NEG_COUPLED,
    "POS_COUPLED": REGIME_POS_COUPLED,
    "DECOUPLED": REGIME_DECOUPLED,
    "MIXED": REGIME_MIXED,
}


def _mid_from_state(state: TradingState, symbol: str) -> float | None:
    order_depth = state.order_depths.get(symbol)
    if order_depth is None:
        return None
    book = snapshot_from_order_depth(symbol, order_depth)
    return book.mid_price


def _rolling_corr(xs: List[float], ys: List[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    x = xs[-n:]
    y = ys[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    cov = 0.0
    vx = 0.0
    vy = 0.0
    for xv, yv in zip(x, y):
        dx = xv - mx
        dy = yv - my
        cov += dx * dy
        vx += dx * dx
        vy += dy * dy
    denom = math.sqrt(vx * vy)
    if denom <= 1e-12:
        return 0.0
    return cov / denom


def _round4(value: float) -> float:
    return round(float(value), 4)


class _MSRegimeMixin:
    """Shared HYDROGEL/VELVET regime detection."""

    def _ms_shared(self, memory: Dict[str, Any]) -> Dict[str, Any] | None:
        shared = memory.get("_shared")
        return shared if isinstance(shared, dict) else None

    def _ms_regime(self, state: TradingState, memory: Dict[str, Any]) -> Dict[str, Any]:
        ts = int(state.timestamp)
        shared = self._ms_shared(memory)
        if shared is not None:
            cached = shared.get("_ms_regime")
            if isinstance(cached, dict) and cached.get("timestamp") == ts:
                self._write_regime_features(memory, cached)
                return cached

        owner = bool(self.params.get("ms_history_owner", False))
        use_shared_only = bool(self.params.get("ms_use_shared_only", False))
        if use_shared_only and not owner:
            fallback = self._neutral_regime(ts)
            self._write_regime_features(memory, fallback)
            return fallback

        regime = self._compute_regime_from_books(state, memory, ts)
        if shared is not None:
            shared["_ms_regime"] = regime
        self._write_regime_features(memory, regime)
        return regime

    def _compute_regime_from_books(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        ts: int,
    ) -> Dict[str, Any]:
        h_mid = _mid_from_state(state, HYDROGEL)
        v_mid = _mid_from_state(state, VELVET)
        if h_mid is None or v_mid is None or h_mid <= 0 or v_mid <= 0:
            return self._neutral_regime(ts)

        h0 = float(memory.setdefault("_ms_h0", h_mid))
        v0 = float(memory.setdefault("_ms_v0", v_mid))
        h_norm = 100.0 * h_mid / h0
        v_norm = 100.0 * v_mid / v0
        spread = h_norm - v_norm

        window = int(self.params.get("ms_window", 120))
        min_samples = int(self.params.get("ms_min_samples", 60))
        keep = max(window, min_samples) + 5
        h_hist = memory.setdefault("_ms_h_norm_hist", [])
        v_hist = memory.setdefault("_ms_v_norm_hist", [])
        h_hist.append(_round4(h_norm))
        v_hist.append(_round4(v_norm))
        if len(h_hist) > keep:
            del h_hist[:-keep]
        if len(v_hist) > keep:
            del v_hist[:-keep]

        sample_count = min(len(h_hist), len(v_hist))
        corr_window = min(window, sample_count)
        corr = _rolling_corr(h_hist[-corr_window:], v_hist[-corr_window:])
        regime_name = self._classify_regime(corr, spread, sample_count, min_samples)
        return {
            "timestamp": ts,
            "name": regime_name,
            "code": _REGIME_CODES[regime_name],
            "corr": _round4(corr),
            "spread": _round4(spread),
            "h_norm": _round4(h_norm),
            "v_norm": _round4(v_norm),
            "samples": sample_count,
        }

    def _classify_regime(self, corr: float, spread: float, samples: int, min_samples: int) -> str:
        if samples < min_samples:
            return "WARMUP"
        node_threshold = float(self.params.get("ms_node_threshold", 0.10))
        pos_threshold = float(self.params.get("ms_pos_corr_threshold", 0.55))
        neg_threshold = float(self.params.get("ms_neg_corr_threshold", -0.55))
        decorr_threshold = float(self.params.get("ms_decorr_threshold", 0.15))
        if abs(spread) <= node_threshold:
            return "NODE"
        if corr <= neg_threshold:
            return "NEG_COUPLED"
        if corr >= pos_threshold:
            return "POS_COUPLED"
        if abs(corr) <= decorr_threshold:
            return "DECOUPLED"
        return "MIXED"

    def _neutral_regime(self, ts: int) -> Dict[str, Any]:
        return {
            "timestamp": ts,
            "name": "WARMUP",
            "code": REGIME_WARMUP,
            "corr": 0.0,
            "spread": 0.0,
            "h_norm": 100.0,
            "v_norm": 100.0,
            "samples": 0,
        }

    def _write_regime_features(self, memory: Dict[str, Any], regime: Dict[str, Any]) -> None:
        memory["_ms_regime_code"] = float(regime["code"])
        memory["_ms_corr"] = float(regime["corr"])
        memory["_ms_spread"] = float(regime["spread"])
        memory["_ms_h_norm_last"] = regime.get("h_norm", 100.0)
        memory["_ms_v_norm_last"] = regime.get("v_norm", 100.0)

    def _regime_feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (code := memory.get("_ms_regime_code")) is not None:
            out["MS_regime"] = float(code)
        if (corr := memory.get("_ms_corr")) is not None:
            out["MS_corr"] = float(corr)
        if (spread := memory.get("_ms_spread")) is not None:
            out["MS_spread"] = float(spread)
        return out


class MSRegimeDeltaOneStrategy(_MSRegimeMixin, BaseStrategy):
    """Passive MM with regime-conditioned sizing for delta-one products."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None and book.best_ask is None:
            return [], 0

        regime = self._ms_regime(state, memory)
        maker_size = int(self.params.get("maker_size", 30))
        tighten_ticks = int(self.params.get("tighten_ticks", 1))

        bid_price, ask_price = self._base_quotes(book, tighten_ticks)
        bid_mult, ask_mult = self._delta_size_multipliers(regime["name"], position)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        bid_size = min(buy_cap, self._scaled_size(maker_size, bid_mult))
        ask_size = min(sell_cap, self._scaled_size(maker_size, ask_mult))

        orders: List[Order] = []
        if bid_price is not None and bid_size > 0:
            orders.append(Order(self.product, bid_price, bid_size))
        if ask_price is not None and ask_size > 0:
            orders.append(Order(self.product, ask_price, -ask_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        memory["_ms_bid_mult"] = bid_mult
        memory["_ms_ask_mult"] = ask_mult
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "ms_regime": regime["code"],
                "ms_corr": regime["corr"],
                "ms_spread": regime["spread"],
                "ms_bid_mult": round(bid_mult, 3),
                "ms_ask_mult": round(ask_mult, 3),
            },
        )
        return orders, 0

    def _base_quotes(self, book: BookSnapshot, tighten_ticks: int) -> Tuple[int | None, int | None]:
        bid_price = book.best_bid
        ask_price = book.best_ask
        if book.best_bid is not None and book.best_ask is not None:
            spread = book.best_ask - book.best_bid
            if spread >= 2:
                bid_price = int(min(book.best_bid + tighten_ticks, book.best_ask - 1))
                ask_price = int(max(book.best_ask - tighten_ticks, book.best_bid + 1))
        return bid_price, ask_price

    def _delta_size_multipliers(self, regime_name: str, position: int) -> Tuple[float, float]:
        role = str(self.params.get("ms_role", "neutral"))
        if role != "velvet":
            bid_mult = float(self.params.get("ms_neutral_bid_mult", 1.0))
            ask_mult = float(self.params.get("ms_neutral_ask_mult", 1.0))
        elif regime_name in {"NEG_COUPLED", "MIXED"}:
            bid_mult = float(self.params.get("ms_velvet_fav_bid_mult", 1.45))
            ask_mult = float(self.params.get("ms_velvet_fav_ask_mult", 0.35))
        elif regime_name == "POS_COUPLED":
            bid_mult = float(self.params.get("ms_velvet_bad_bid_mult", 0.35))
            ask_mult = float(self.params.get("ms_velvet_bad_ask_mult", 1.30))
        elif regime_name == "NODE":
            bid_mult = float(self.params.get("ms_velvet_node_mult", 0.45))
            ask_mult = float(self.params.get("ms_velvet_node_mult", 0.45))
        elif regime_name == "DECOUPLED":
            bid_mult = float(self.params.get("ms_velvet_decoupled_mult", 0.75))
            ask_mult = float(self.params.get("ms_velvet_decoupled_mult", 0.75))
        else:
            bid_mult = float(self.params.get("ms_velvet_warmup_mult", 1.0))
            ask_mult = float(self.params.get("ms_velvet_warmup_mult", 1.0))

        limit = max(1, self.position_limit())
        soft = float(self.params.get("ms_soft_position_ratio", 0.70)) * limit
        if position >= soft:
            bid_mult *= float(self.params.get("ms_inventory_cut_mult", 0.25))
            ask_mult = max(ask_mult, float(self.params.get("ms_inventory_exit_mult", 1.0)))
        elif position <= -soft:
            ask_mult *= float(self.params.get("ms_inventory_cut_mult", 0.25))
            bid_mult = max(bid_mult, float(self.params.get("ms_inventory_exit_mult", 1.0)))
        return bid_mult, ask_mult

    def _scaled_size(self, base_size: int, mult: float) -> int:
        if mult <= 0.0 or base_size <= 0:
            return 0
        return max(1, int(round(base_size * mult)))

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = self._regime_feature_prices(memory)
        if (bid_mult := memory.get("_ms_bid_mult")) is not None:
            out["MS_bid_mult"] = float(bid_mult)
        if (ask_mult := memory.get("_ms_ask_mult")) is not None:
            out["MS_ask_mult"] = float(ask_mult)
        return out


class MSRegimeOptionMMStrategy(_MSRegimeMixin, OptionMMBSStrategy):
    """Black-Scholes option MM with regime-conditioned passive sizes."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        regime = self._ms_regime(state, memory)
        orders, conversions = super().compute_orders(state, book, order_depth, position, memory)
        if not orders:
            memory["_ms_bid_mult"] = 0.0
            memory["_ms_ask_mult"] = 0.0
            return orders, conversions

        bid_mult, ask_mult = self._option_size_multipliers(regime["name"], position)
        memory["_ms_bid_mult"] = bid_mult
        memory["_ms_ask_mult"] = ask_mult
        return self._scale_orders(orders, position, bid_mult, ask_mult), conversions

    def _option_size_multipliers(self, regime_name: str, position: int) -> Tuple[float, float]:
        if regime_name in {"NEG_COUPLED", "MIXED"}:
            bid_mult = float(self.params.get("ms_option_fav_bid_mult", 1.60))
            ask_mult = float(self.params.get("ms_option_fav_ask_mult", 0.30))
        elif regime_name == "POS_COUPLED":
            bid_mult = float(self.params.get("ms_option_bad_bid_mult", 0.25))
            ask_mult = float(self.params.get("ms_option_bad_ask_mult", 1.25))
        elif regime_name == "NODE":
            mult = float(self.params.get("ms_option_node_mult", 0.35))
            bid_mult = mult
            ask_mult = mult
        elif regime_name == "DECOUPLED":
            mult = float(self.params.get("ms_option_decoupled_mult", 0.70))
            bid_mult = mult
            ask_mult = mult
        else:
            mult = float(self.params.get("ms_option_warmup_mult", 1.0))
            bid_mult = mult
            ask_mult = mult

        strike = float(self.params.get("strike", 0.0))
        focus_low = float(self.params.get("ms_option_focus_low", 5000.0))
        focus_high = float(self.params.get("ms_option_focus_high", 5500.0))
        if strike < focus_low or strike > focus_high:
            outer_mult = float(self.params.get("ms_option_outer_mult", 0.50))
            bid_mult *= outer_mult
            ask_mult *= outer_mult

        limit = max(1, self.position_limit())
        soft = float(self.params.get("ms_soft_position_ratio", 0.70)) * limit
        if position >= soft:
            bid_mult *= float(self.params.get("ms_inventory_cut_mult", 0.25))
            ask_mult = max(ask_mult, float(self.params.get("ms_inventory_exit_mult", 1.0)))
        elif position <= -soft:
            ask_mult *= float(self.params.get("ms_inventory_cut_mult", 0.25))
            bid_mult = max(bid_mult, float(self.params.get("ms_inventory_exit_mult", 1.0)))
        return bid_mult, ask_mult

    def _scale_orders(
        self,
        orders: List[Order],
        position: int,
        bid_mult: float,
        ask_mult: float,
    ) -> List[Order]:
        scaled: List[Order] = []
        buy_left = self.buy_capacity(position)
        sell_left = self.sell_capacity(position)
        for order in orders:
            if order.quantity > 0:
                qty = int(round(order.quantity * bid_mult))
                qty = min(max(0, qty), buy_left)
                if qty > 0:
                    scaled.append(Order(order.symbol, order.price, qty))
                    buy_left -= qty
            elif order.quantity < 0:
                qty = int(round((-order.quantity) * ask_mult))
                qty = min(max(0, qty), sell_left)
                if qty > 0:
                    scaled.append(Order(order.symbol, order.price, -qty))
                    sell_left -= qty
        return scaled

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        out.update(self._regime_feature_prices(memory))
        if (bid_mult := memory.get("_ms_bid_mult")) is not None:
            out["MS_bid_mult"] = float(bid_mult)
        if (ask_mult := memory.get("_ms_ask_mult")) is not None:
            out["MS_ask_mult"] = float(ask_mult)
        return out
