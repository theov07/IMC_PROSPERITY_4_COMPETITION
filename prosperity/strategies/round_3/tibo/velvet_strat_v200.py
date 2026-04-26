"""Round 3 v200 — faithful port of friend's strategy.

VelvetMMV200: thin wrapper on R3GuardedAnchorMMStrategy (anchor=5250).
GammaScalpV200: friend's GammaScalpZGatedStrategy with iv_residual_gate support.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_delta, call_gamma, call_price
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy
from prosperity.strategies.round_3.tibo.mm_first_v4_combo import R3GuardedAnchorMMStrategy

_DEFAULT_VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


class VelvetMMV200(R3GuardedAnchorMMStrategy):
    pass


class GammaScalpV200(BaseStrategy):
    """Faithful port of friend's GammaScalpZGatedStrategy including iv_residual_gate."""

    def _get_spot(self, state: TradingState) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if not od or not od.buy_orders or not od.sell_orders:
            return None
        return 0.5 * (max(od.buy_orders) + min(od.sell_orders))

    def _update_zscore(self, S: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Optional[float]:
        window = p["zscore_window"]
        buf: List[float] = memory.setdefault("_velvet_buf", [])
        buf.append(S)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (S - mean) / std

    def _update_iv_residual(
        self,
        state: TradingState,
        book: BookSnapshot,
        S: float,
        p: Dict[str, Any],
        memory: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[float]]:
        own_mid = 0.5 * (book.best_bid + book.best_ask)
        own_iv = call_implied_vol(own_mid, S, p["K"], p["T"], sigma_init=p["implied_vol_prior"])
        if own_iv is None:
            return None, None

        ks: List[float] = []
        ivs: List[float] = []
        for strike in _DEFAULT_VEV_STRIKES:
            if float(strike) == p["K"]:
                continue
            od = state.order_depths.get(f"VEV_{strike}")
            if not od or not od.buy_orders or not od.sell_orders:
                continue
            mid = 0.5 * (max(od.buy_orders) + min(od.sell_orders))
            iv = call_implied_vol(mid, S, float(strike), p["T"], sigma_init=p["implied_vol_prior"])
            if iv is None or iv < 0.005 or iv > 0.10:
                continue
            ks.append(float(strike))
            ivs.append(iv)

        if len(ks) < 3:
            return None, None
        coeffs = fit_smile_poly(ks, ivs, S, p["T"], degree=2)
        if coeffs is None:
            return None, None

        loo_iv = smile_predict(p["K"], coeffs, S, p["T"])
        residual = own_iv - loo_iv

        slow = memory.get("_iv_resid_slow")
        fast = memory.get("_iv_resid_fast")
        if slow is None:
            slow = residual
            fast = residual
        else:
            slow = (1 - p["iv_ewma_slow_alpha"]) * slow + p["iv_ewma_slow_alpha"] * residual
            fast = (1 - p["iv_ewma_fast_alpha"]) * fast + p["iv_ewma_fast_alpha"] * residual
        memory["_iv_resid_slow"] = slow
        memory["_iv_resid_fast"] = fast
        return residual, fast - slow

    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        params = self.params
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(params.get("tte_days_initial", 5.0)),
            params.get("historical_tte_by_day"),
        )
        ts_per_day = timestamp_units_per_day_from_params(params)
        T = time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_per_day)
        return {
            "K":                       float(params["strike"]),
            "T":                       max(0.01, T),
            "implied_vol_prior":       float(params.get("implied_vol_prior", 0.0125)),
            "edge_ticks":              float(params.get("edge_ticks", 0.0)),
            "target_qty":              int(params.get("target_qty", 100)),
            "entry_size":              int(params.get("entry_size", 10)),
            "passive_bid_size":        int(params.get("passive_bid_size", 10)),
            "unwind_tte_threshold":    float(params.get("unwind_tte_threshold", 1.5)),
            "min_quote_price":         float(params.get("min_quote_price", 2.0)),
            "underlying_symbol":       params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
            "zscore_window":           int(params.get("zscore_window", 500)),
            "zscore_skip_threshold":   float(params.get("zscore_skip_threshold", 1.0)),
            "zscore_boost_threshold":  float(params.get("zscore_boost_threshold", 1.0)),
            "skip_when_expensive":     bool(params.get("skip_when_expensive", True)),
            "boost_when_cheap":        bool(params.get("boost_when_cheap", False)),
            "entry_size_boost":        float(params.get("entry_size_boost", 1.5)),
            "sell_when_very_expensive": bool(params.get("sell_when_very_expensive", False)),
            "zscore_sell_threshold":   float(params.get("zscore_sell_threshold", 1.5)),
            "sell_size_pct":           float(params.get("sell_size_pct", 0.10)),
            "iv_residual_gate":        bool(params.get("iv_residual_gate", False)),
            "iv_skip_threshold":       float(params.get("iv_skip_threshold", 0.001)),
            "iv_boost_threshold":      float(params.get("iv_boost_threshold", 0.001)),
            "iv_delta_threshold":      float(params.get("iv_delta_threshold", 0.0003)),
            "iv_ewma_fast_alpha":      float(params.get("iv_ewma_fast_alpha", 0.10)),
            "iv_ewma_slow_alpha":      float(params.get("iv_ewma_slow_alpha", 0.02)),
            "iv_passive_boost":        float(params.get("iv_passive_boost", 1.5)),
        }

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        p = self._read_params(state)
        S = self._get_spot(state)
        if S is None:
            return [], 0

        z = self._update_zscore(S, memory, p)
        memory["_velvet_z"] = z

        fair  = call_price(S, p["K"], p["T"], p["implied_vol_prior"])
        gamma = call_gamma(S, p["K"], p["T"], p["implied_vol_prior"])
        delta = call_delta(S, p["K"], p["T"], p["implied_vol_prior"])
        memory["_gamma"]   = gamma
        memory["_delta"]   = delta
        memory["_fair_iv"] = fair

        if fair < p["min_quote_price"]:
            return [], 0

        orders:   List[Order] = []
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Unwind
        if p["T"] < p["unwind_tte_threshold"] or position >= p["target_qty"]:
            if sell_cap > 0 and position > 0:
                ask_px = book.best_ask - 1
                if ask_px <= book.best_bid:
                    ask_px = book.best_bid + 1
                qty = min(p["passive_bid_size"], sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "unwind"
            return orders, 0

        # IV residual gate
        if p["iv_residual_gate"]:
            iv_resid, iv_resid_delta = self._update_iv_residual(state, book, S, p, memory)
            memory["_iv_resid"] = iv_resid
            memory["_iv_resid_delta"] = iv_resid_delta
            if iv_resid is not None and iv_resid_delta is not None:
                if iv_resid < -p["iv_skip_threshold"] and iv_resid_delta < -p["iv_delta_threshold"]:
                    memory["_mode"] = "iv_skip_falling"
                    return [], 0
                memory["_iv_boost"] = (
                    iv_resid > p["iv_boost_threshold"]
                    and iv_resid_delta > p["iv_delta_threshold"]
                )
            else:
                memory["_iv_boost"] = False

        # Z-profit take
        if (p["sell_when_very_expensive"] and z is not None
                and z > p["zscore_sell_threshold"] and position > 0 and sell_cap > 0):
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            sell_qty = max(1, int(round(position * p["sell_size_pct"])))
            qty = min(sell_qty, sell_cap, position, p["passive_bid_size"])
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "z_profit_take"
            return orders, 0

        # Z-gate
        if p["skip_when_expensive"] and z is not None and z > p["zscore_skip_threshold"]:
            memory["_mode"] = "z_skipped_expensive"
            return orders, 0

        # Accumulate
        size_mult = 1.0
        if p["boost_when_cheap"] and z is not None and z < -p["zscore_boost_threshold"]:
            size_mult = p["entry_size_boost"]
            memory["_mode"] = "z_boost_cheap"
        else:
            memory["_mode"] = "accumulate"

        eff_entry_size  = max(1, int(round(p["entry_size"]      * size_mult)))
        eff_passive_size = max(1, int(round(p["passive_bid_size"] * size_mult)))

        if memory.get("_iv_boost", False):
            eff_passive_size = int(round(eff_passive_size * p["iv_passive_boost"]))

        if buy_cap > 0 and position < p["target_qty"]:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty  = -order_depth.sell_orders.get(ask, 0)
                headroom = p["target_qty"] - position
                take_qty = min(ask_qty, buy_cap, eff_entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty

        if buy_cap > 0 and position < p["target_qty"]:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(eff_passive_size, buy_cap, p["target_qty"] - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (g := memory.get("_gamma"))    is not None: out["gamma"]    = g
        if (d := memory.get("_delta"))    is not None: out["delta"]    = d
        if (f := memory.get("_fair_iv")) is not None: out["fair_iv"]  = f
        if (z := memory.get("_velvet_z")) is not None: out["velvet_z"] = z
        if (m := memory.get("_mode"))    is not None:
            out["mode"] = {"accumulate": 1.0, "unwind": 0.0,
                           "z_skipped_expensive": -1.0, "z_boost_cheap": 2.0,
                           "iv_skip_falling": -2.0}.get(m, 0.5)
        return out
