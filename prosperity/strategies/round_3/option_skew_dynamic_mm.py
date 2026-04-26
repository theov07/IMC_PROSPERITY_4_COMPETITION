"""OptionSkewDynamicMM — react to DYNAMICS of leave-one-out smile residual.

Static residual is unreliable (skew_taker blew up -45k). The hypothesis here:
the dynamics of the residual carry information about whether the deformation
is from an informed trader (persists / grows → follow direction) or from
order anomaly / random flow (reverts → fade).

Per-tick:
  1. Compute current iv_residual = own_iv - leave_one_out_smile_iv.
  2. Maintain EWMA of residual (half-life ~50 ticks) and short window EWMA
     (half-life ~10 ticks).
  3. delta_residual = residual_fast - residual_slow.
  4. Decision:
     - If residual << 0 (rich) and delta_residual << 0 (getting richer fast):
       informed seller pushing → follow → SELL the rich option.
     - If residual << 0 but delta_residual >> 0 (rich but reverting):
       OA exhausted → fade → BUY back the rich option.
     - Mirror for residual > 0 (cheap).

Default mode is `mode="follow"` (most empirically supported by gamma_scalp's
+58k inventory_drift). Set `mode="fade"` to test the reverse, or `mode="auto"`
to switch based on delta_residual sign.

Params:
  strike, smile_strikes, strike_prefix, underlying_symbol — same as base
  signal_threshold     : |residual| trigger threshold (default 0.001 IV units = 10 bps)
  delta_threshold      : |delta_residual| trigger (default 0.0005 = 5 bps)
  ewma_slow_alpha      : EWMA alpha for slow line (default 0.02 ≈ half-life 35)
  ewma_fast_alpha      : EWMA alpha for fast line (default 0.10 ≈ half-life 7)
  mode                 : "follow" | "fade" | "auto" (default "auto")
  maker_size           : passive fill size when signal fires (default 16)
  neutral_size         : passive size when no signal (default 6)
  enable_takers        : opt-in taker on strong signals (default False)
  take_size            : taker size cap (default 8)
  take_threshold_mult  : multiply signal_threshold for taker (default 2.0)
  max_long, max_short, allow_new_shorts : same convention as base skew strat
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_price
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


class OptionSkewDynamicMMStrategy(BaseStrategy):
    """Skew-MM that uses residual DYNAMICS (informed/OA discrimination)."""

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
        if loo_iv is None or own_iv is None:
            return self._neutral_quotes(book, position, p), 0

        residual = own_iv - loo_iv  # > 0 → our IV high vs smile, market RICH

        # EWMA dynamics
        slow = memory.get("_resid_slow")
        fast = memory.get("_resid_fast")
        if slow is None:
            slow = residual
            fast = residual
        else:
            slow = (1 - p["ewma_slow_alpha"]) * slow + p["ewma_slow_alpha"] * residual
            fast = (1 - p["ewma_fast_alpha"]) * fast + p["ewma_fast_alpha"] * residual
        memory["_resid_slow"] = slow
        memory["_resid_fast"] = fast
        memory["_resid_now"] = residual
        delta_resid = fast - slow
        memory["_resid_delta"] = delta_resid

        fair = call_price(S, p["K"], p["T"], loo_iv)
        if fair < p["min_quote_price"]:
            return [], 0

        # Decide signal
        signal = self._classify_signal(residual, delta_resid, p)
        memory["_signal"] = signal

        buy_cap = min(self.buy_capacity(position), max(0, p["max_long"] - position))
        sell_cap = min(self.sell_capacity(position), max(0, p["max_short"] + position))
        orders: List[Order] = []

        # Optional takers on strong + persistent signal
        if p["enable_takers"] and signal in ("buy", "sell"):
            takers, buy_cap, sell_cap = self._takers(
                signal, fair, book, order_depth, buy_cap, sell_cap, p,
            )
            orders.extend(takers)

        # Passive quotes biased by signal
        orders.extend(self._passive_quotes(book, position, signal, buy_cap, sell_cap, p))

        return orders, 0

    # ── Signal classifier ────────────────────────────────────────────────────

    def _classify_signal(
        self, residual: float, delta_resid: float, p: Dict[str, Any],
    ) -> str:
        """Return 'buy', 'sell', 'fade_buy', 'fade_sell', or 'neutral'."""
        sig = p["signal_threshold"]
        dsig = p["delta_threshold"]

        if abs(residual) < sig:
            return "neutral"

        rich = residual < 0   # mid > fair → option rich
        cheap = residual > 0  # mid < fair → option cheap

        # delta_resid > 0 → residual rising (more cheap / less rich)
        # delta_resid < 0 → residual falling (less cheap / more rich)
        getting_richer = (rich and delta_resid < -dsig)   # residual ↓ further into negative
        getting_cheaper = (cheap and delta_resid > dsig)  # residual ↑ further into positive
        rich_reverting = (rich and delta_resid > dsig)    # residual ↑, returning to 0
        cheap_reverting = (cheap and delta_resid < -dsig) # residual ↓, returning to 0

        mode = p["mode"]
        if mode == "follow":
            if cheap and (delta_resid >= 0 or abs(delta_resid) < dsig):
                return "buy"
            if rich and (delta_resid <= 0 or abs(delta_resid) < dsig):
                return "sell"
            return "neutral"
        if mode == "fade":
            if rich and rich_reverting:
                return "buy"
            if cheap and cheap_reverting:
                return "sell"
            return "neutral"
        # mode == "auto": split by dynamics
        if getting_richer:    return "sell"        # informed seller persisting → follow
        if getting_cheaper:   return "buy"         # informed buyer persisting → follow
        if rich_reverting:    return "buy"         # OA exhausted → fade rich
        if cheap_reverting:   return "sell"        # OA exhausted → fade cheap
        return "neutral"

    # ── Quote helpers ────────────────────────────────────────────────────────

    def _passive_quotes(
        self, book: BookSnapshot, position: int, signal: str,
        buy_cap: int, sell_cap: int, p: Dict[str, Any],
    ) -> List[Order]:
        bid_px = book.best_bid + 1 if book.best_bid + 1 < book.best_ask else book.best_bid
        ask_px = book.best_ask - 1 if book.best_ask - 1 > book.best_bid else book.best_ask
        ms = p["maker_size"]
        ns = p["neutral_size"]
        es = p["exit_size"]
        orders: List[Order] = []
        if signal in ("buy",):
            if buy_cap > 0:
                orders.append(Order(self.product, bid_px, min(ms, buy_cap)))
            if position < 0 and buy_cap > 0:  # exit short
                orders.append(Order(self.product, bid_px, min(es, buy_cap, -position)))
        elif signal in ("sell",):
            if sell_cap > 0:
                orders.append(Order(self.product, ask_px, -min(ms, sell_cap)))
            if position > 0 and sell_cap > 0:  # exit long
                orders.append(Order(self.product, ask_px, -min(es, sell_cap, position)))
        else:
            if buy_cap > 0:
                orders.append(Order(self.product, bid_px, min(ns, buy_cap)))
            if sell_cap > 0:
                orders.append(Order(self.product, ask_px, -min(ns, sell_cap)))
        return orders

    def _neutral_quotes(self, book, position, p):
        ns = p["neutral_size"]
        if ns <= 0: return []
        bid_px = book.best_bid + 1 if book.best_bid + 1 < book.best_ask else book.best_bid
        ask_px = book.best_ask - 1 if book.best_ask - 1 > book.best_bid else book.best_ask
        bcap = self.buy_capacity(position); scap = self.sell_capacity(position)
        out = []
        if bcap > 0: out.append(Order(self.product, bid_px, min(ns, bcap)))
        if scap > 0: out.append(Order(self.product, ask_px, -min(ns, scap)))
        return out

    def _takers(self, signal: str, fair: float, book, order_depth,
                buy_cap: int, sell_cap: int, p: Dict[str, Any]):
        ts = p["take_size"]
        orders: List[Order] = []
        if signal == "buy" and buy_cap > 0 and book.best_ask is not None:
            qty = min(-order_depth.sell_orders.get(book.best_ask, 0), buy_cap, ts)
            if qty > 0:
                orders.append(Order(self.product, book.best_ask, qty))
                buy_cap -= qty
        if signal == "sell" and sell_cap > 0 and book.best_bid is not None:
            qty = min(order_depth.buy_orders.get(book.best_bid, 0), sell_cap, ts)
            if qty > 0:
                orders.append(Order(self.product, book.best_bid, -qty))
                sell_cap -= qty
        return orders, buy_cap, sell_cap

    # ── LOO smile ────────────────────────────────────────────────────────────

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
        if len(strikes) < 3:
            return None
        coeffs = fit_smile_poly(strikes, vols, S, p["T"], degree=2)
        if coeffs is None:
            return None
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
            "min_quote_price": float(params.get("min_quote_price", 1.0)),
            "signal_threshold": float(params.get("signal_threshold", 0.001)),
            "delta_threshold": float(params.get("delta_threshold", 0.0005)),
            "ewma_slow_alpha": float(params.get("ewma_slow_alpha", 0.02)),
            "ewma_fast_alpha": float(params.get("ewma_fast_alpha", 0.10)),
            "mode": str(params.get("mode", "auto")),
            "maker_size": int(params.get("maker_size", 16)),
            "neutral_size": int(params.get("neutral_size", 6)),
            "exit_size": int(params.get("exit_size", 10)),
            "take_size": int(params.get("take_size", 8)),
            "max_long": int(params.get("max_long", 80)),
            "max_short": int(params.get("max_short", 40)),
            "allow_new_shorts": bool(params.get("allow_new_shorts", True)),
            "enable_takers": bool(params.get("enable_takers", False)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if (v := memory.get("_resid_now")) is not None: out["resid_bps"] = v * 10000
        if (v := memory.get("_resid_slow")) is not None: out["resid_slow_bps"] = v * 10000
        if (v := memory.get("_resid_fast")) is not None: out["resid_fast_bps"] = v * 10000
        if (v := memory.get("_resid_delta")) is not None: out["resid_delta_bps"] = v * 10000
        if (v := memory.get("_signal")): out["signal_str"] = 0  # dashboard string handled separately
        return out
