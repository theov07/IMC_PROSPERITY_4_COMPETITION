"""IVMomentumMM — exploit POSITIVE IV residual autocorrelation (momentum).

Round 3 IV residual autocorrelation: ρ_1 = +0.10 à +0.20 (positive momentum).
Unlike last year's negative ρ_1 (mean-reversion → IV scalping), our signal
says: when residual is rich, it stays rich. When cheap, stays cheap.

Strategy:
  residual_t = own_iv_t - smile_loo_iv_t (in IV space)
  residual_t > +threshold (rich + persisting):
    → BUY (option mid is rising, will keep rising) → enter long aggressively
  residual_t < -threshold (cheap + persisting):
    → SELL (option mid is dropping, will keep dropping) → enter short aggressively

Magnitude check: ρ_1 × residual_std ≈ 0.14 × 0.001 (= 10bp std) = 1.4bp expected
move on next tick. With vega ~5500 ATM, that's ~$8/unit per tick. Spread cost
is ~1 tick = larger. So entry must be selective — only trade when residual
is large (>2σ) AND has a clear directional momentum (delta_residual > 0).

Params:
  strike, smile_strikes, strike_prefix, underlying_symbol — std
  signal_threshold        : |residual| trigger (default 0.0015 = 15bp)
  delta_threshold         : |delta(residual)| over EWMA (default 0.0003)
  ewma_fast_alpha         : 0.10 (~7-tick half-life)
  ewma_slow_alpha         : 0.02 (~35-tick)
  maker_size              : passive entry size (default 20)
  exit_size               : exit size when signal reverts (default 15)
  max_long, max_short     : position caps (default 100/40)
  enable_takers           : opt-in taker on strong momentum (default True)
  take_size               : taker size (default 10)
  take_threshold_mult     : multiplier for taker (default 1.5×signal)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.coordinator import get_spot, publish_position
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy

_DEFAULT_VEV_STRIKES: List[int] = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


class IVMomentumMMStrategy(BaseStrategy):
    """Trade IV residual momentum (BUY rich, SELL cheap)."""

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
        ts = int(state.timestamp)
        publish_position(ts, self.product, position)

        S = get_spot(state, underlying=p["underlying_symbol"])
        if S is None:
            return [], 0

        own_mid = 0.5 * (book.best_bid + book.best_ask)
        own_iv = call_implied_vol(own_mid, S, p["K"], p["T"], sigma_init=p["prior_vol"])
        loo_iv = self._leave_one_out_sigma(state, S, p)
        if own_iv is None or loo_iv is None:
            return [], 0

        residual = own_iv - loo_iv  # > 0 → market option RICH (own IV high vs smile)

        # Update fast/slow EWMAs of residual
        slow = memory.get("_resid_slow")
        fast = memory.get("_resid_fast")
        if slow is None:
            slow = residual; fast = residual
        else:
            slow = (1 - p["ewma_slow_alpha"]) * slow + p["ewma_slow_alpha"] * residual
            fast = (1 - p["ewma_fast_alpha"]) * fast + p["ewma_fast_alpha"] * residual
        memory["_resid_slow"] = slow
        memory["_resid_fast"] = fast
        memory["_resid_now"] = residual
        delta_resid = fast - slow  # >0 = increasing rich, <0 = becoming cheaper
        memory["_resid_delta"] = delta_resid

        # ── Signal classifier (MOMENTUM logic)
        # If residual > threshold AND increasing (delta > 0) → MOMENTUM bullish on option price
        #   → BUY (follow upward IV move)
        # If residual < -threshold AND decreasing → MOMENTUM bearish → SELL
        sig = p["signal_threshold"]
        dthr = p["delta_threshold"]

        signal = "neutral"
        if residual > sig and delta_resid > -dthr:    # rich + not reverting
            signal = "buy"   # option momentum up → buy
        elif residual < -sig and delta_resid < dthr:  # cheap + not reverting
            signal = "sell"  # option momentum down → sell
        # Exits: when residual returns to neutral
        elif abs(residual) < sig * 0.3:
            signal = "exit"  # close existing position

        memory["_signal"] = signal

        buy_cap = min(self.buy_capacity(position), max(0, p["max_long"] - position))
        sell_cap = min(self.sell_capacity(position), max(0, p["max_short"] + position))

        orders: List[Order] = []
        bid_inside = book.best_bid + 1 if book.best_bid + 1 < book.best_ask else book.best_bid
        ask_inside = book.best_ask - 1 if book.best_ask - 1 > book.best_bid else book.best_ask

        if signal == "buy":
            # Optional taker on strong signal
            if p["enable_takers"] and abs(residual) > sig * p["take_threshold_mult"] and buy_cap > 0:
                qty = min(p["take_size"], buy_cap, -order_depth.sell_orders.get(book.best_ask, 0))
                if qty > 0:
                    orders.append(Order(self.product, book.best_ask, qty))
                    buy_cap -= qty
            if buy_cap > 0:
                orders.append(Order(self.product, bid_inside, min(p["maker_size"], buy_cap)))
        elif signal == "sell":
            if p["enable_takers"] and abs(residual) > sig * p["take_threshold_mult"] and sell_cap > 0:
                qty = min(p["take_size"], sell_cap, order_depth.buy_orders.get(book.best_bid, 0))
                if qty > 0:
                    orders.append(Order(self.product, book.best_bid, -qty))
                    sell_cap -= qty
            if sell_cap > 0:
                orders.append(Order(self.product, ask_inside, -min(p["maker_size"], sell_cap)))
        elif signal == "exit":
            # Close existing position passively
            if position > 0 and sell_cap > 0:
                orders.append(Order(self.product, ask_inside, -min(p["exit_size"], sell_cap, position)))
            elif position < 0 and buy_cap > 0:
                orders.append(Order(self.product, bid_inside, min(p["exit_size"], buy_cap, -position)))
        # else neutral: do nothing

        return orders, 0

    def _leave_one_out_sigma(self, state: TradingState, S: float, p: Dict[str, Any]) -> Optional[float]:
        strikes: List[float] = []
        vols: List[float] = []
        for strike in p["smile_strikes"]:
            if float(strike) == p["K"]:
                continue
            od = state.order_depths.get(f"{p['strike_prefix']}{strike}")
            if not od or not od.buy_orders or not od.sell_orders:
                continue
            bid = max(od.buy_orders); ask = min(od.sell_orders)
            mid = 0.5 * (bid + ask)
            iv = call_implied_vol(mid, S, float(strike), p["T"], sigma_init=p["prior_vol"])
            if iv is None or iv < p["sigma_floor"] or iv > p["sigma_cap"]:
                continue
            strikes.append(float(strike)); vols.append(iv)
        if len(strikes) < 3: return None
        coeffs = fit_smile_poly(strikes, vols, S, p["T"], degree=2)
        if coeffs is None: return None
        sigma = smile_predict(p["K"], coeffs, S, p["T"])
        return max(p["sigma_floor"], min(p["sigma_cap"], sigma))

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
            "K": float(params["strike"]),
            "T": max(0.01, T),
            "underlying_symbol": str(params.get("underlying_symbol", "VELVETFRUIT_EXTRACT")),
            "strike_prefix": str(params.get("strike_prefix", "VEV_")),
            "smile_strikes": list(params.get("smile_strikes") or _DEFAULT_VEV_STRIKES),
            "prior_vol": float(params.get("prior_vol", 0.0125)),
            "sigma_floor": float(params.get("sigma_floor", 0.005)),
            "sigma_cap": float(params.get("sigma_cap", 0.10)),
            "signal_threshold": float(params.get("signal_threshold", 0.0015)),
            "delta_threshold": float(params.get("delta_threshold", 0.0003)),
            "ewma_fast_alpha": float(params.get("ewma_fast_alpha", 0.10)),
            "ewma_slow_alpha": float(params.get("ewma_slow_alpha", 0.02)),
            "maker_size": int(params.get("maker_size", 20)),
            "exit_size": int(params.get("exit_size", 15)),
            "max_long": int(params.get("max_long", 100)),
            "max_short": int(params.get("max_short", 40)),
            "enable_takers": bool(params.get("enable_takers", True)),
            "take_size": int(params.get("take_size", 10)),
            "take_threshold_mult": float(params.get("take_threshold_mult", 1.5)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if (v := memory.get("_resid_now")) is not None: out["resid_bp"] = v * 1e4
        if (v := memory.get("_resid_slow")) is not None: out["resid_slow_bp"] = v * 1e4
        if (v := memory.get("_resid_fast")) is not None: out["resid_fast_bp"] = v * 1e4
        if (v := memory.get("_resid_delta")) is not None: out["resid_delta_bp"] = v * 1e4
        return out
