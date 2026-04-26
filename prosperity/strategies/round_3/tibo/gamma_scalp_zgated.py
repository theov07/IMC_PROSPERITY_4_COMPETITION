"""GammaScalpZGatedStrategy — z-score-gated long-call accumulation with unwind.

Ported from r3_velvet_options_v24.py (friend's merged strategy).

Logic per tick:
  1. Compute VELVETFRUIT z-score (500-tick rolling window).
  2. Compute BS fair value using fixed implied_vol_prior (1.25% daily).
  3. Accumulate phase (position < target_qty, TTE > unwind_tte_threshold):
     - Active taker: buy at ask if ask <= fair + edge_ticks
     - Passive maker: penny-improve bid (best_bid + 1)
     - Skip entirely when z > zscore_skip_threshold (expensive)
     - Boost size when z < -zscore_boost_threshold (cheap, if boost_when_cheap=True)
  4. Unwind phase (position >= target_qty OR TTE < unwind_tte_threshold):
     - Sell penny-improve ask to exit
  5. Profit-take: sell fraction when z > zscore_sell_threshold (if sell_when_very_expensive=True)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_delta, call_gamma, call_price
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


class GammaScalpZGatedStrategy(BaseStrategy):
    """Z-score-gated long-call accumulation with BS fair value and unwind logic."""

    def _get_spot(self, state: TradingState) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if not od or not od.buy_orders or not od.sell_orders:
            return None
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        return 0.5 * (bb + ba)

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
            "K":                    float(params["strike"]),
            "T":                    max(0.01, T),
            "implied_vol_prior":    float(params.get("implied_vol_prior", 0.0125)),
            "edge_ticks":           float(params.get("edge_ticks", 0.0)),
            "target_qty":           int(params.get("target_qty", 100)),
            "entry_size":           int(params.get("entry_size", 10)),
            "passive_bid_size":     int(params.get("passive_bid_size", 10)),
            "unwind_tte_threshold": float(params.get("unwind_tte_threshold", 1.5)),
            "min_quote_price":      float(params.get("min_quote_price", 2.0)),
            "underlying_symbol":    params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
            "zscore_window":        int(params.get("zscore_window", 500)),
            "zscore_skip_threshold":  float(params.get("zscore_skip_threshold", 1.0)),
            "zscore_boost_threshold": float(params.get("zscore_boost_threshold", 1.0)),
            "skip_when_expensive":  bool(params.get("skip_when_expensive", True)),
            "boost_when_cheap":     bool(params.get("boost_when_cheap", False)),
            "entry_size_boost":     float(params.get("entry_size_boost", 1.5)),
            "sell_when_very_expensive": bool(params.get("sell_when_very_expensive", False)),
            "zscore_sell_threshold":    float(params.get("zscore_sell_threshold", 1.5)),
            "sell_size_pct":            float(params.get("sell_size_pct", 0.10)),
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
        memory["_spot"]    = S
        memory["_T"]       = p["T"]

        if fair < p["min_quote_price"]:
            return [], 0

        orders:   List[Order] = []
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── Unwind phase ──────────────────────────────────────────────────────
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

        # ── Profit-take on extreme z ──────────────────────────────────────────
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

        # ── Skip when expensive ───────────────────────────────────────────────
        if p["skip_when_expensive"] and z is not None and z > p["zscore_skip_threshold"]:
            memory["_mode"] = "z_skipped_expensive"
            return orders, 0

        # ── Accumulate phase ──────────────────────────────────────────────────
        size_mult = 1.0
        if p["boost_when_cheap"] and z is not None and z < -p["zscore_boost_threshold"]:
            size_mult = p["entry_size_boost"]
            memory["_mode"] = "z_boost_cheap"
        else:
            memory["_mode"] = "accumulate"

        eff_entry_size  = max(1, int(round(p["entry_size"]      * size_mult)))
        eff_passive_size = max(1, int(round(p["passive_bid_size"] * size_mult)))

        # Active taker: buy if ask is at or below fair + edge_ticks
        if buy_cap > 0 and position < p["target_qty"]:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty  = -order_depth.sell_orders.get(ask, 0)
                headroom = p["target_qty"] - position
                take_qty = min(ask_qty, buy_cap, eff_entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty

        # Passive maker: penny-improve bid
        if buy_cap > 0 and position < p["target_qty"]:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(eff_passive_size, buy_cap, p["target_qty"] - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (g := memory.get("_gamma"))   is not None: out["gamma"]   = g
        if (d := memory.get("_delta"))   is not None: out["delta"]   = d
        if (f := memory.get("_fair_iv")) is not None: out["fair_iv"] = f
        if (z := memory.get("_velvet_z")) is not None: out["velvet_z"] = z
        if (m := memory.get("_mode")) is not None:
            out["mode"] = {"accumulate": 1.0, "unwind": 0.0,
                           "z_skipped_expensive": -1.0, "z_boost_cheap": 2.0}.get(m, 0.5)
        return out
