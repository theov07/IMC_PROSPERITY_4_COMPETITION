"""OptionMMBS — European call market-maker using Black-Scholes fair value.

Architecture (senior-eng style):
  compute_orders() is a thin orchestrator. All computation is factored into
  single-purpose private helpers:

    _read_params()            → strategy params as a NamedTuple-like dict
    _resolve_spot(state, ts)  → spot price of underlying
    _resolve_sigma(...)       → sigma to use for pricing (smile / own IV / prior)
    _compute_fair(...)        → BS call price + inventory skew
    _compute_quotes(...)      → (bid_px, ask_px)
    _fire_takers(...)         → optional taker orders when market mispriced
    _post_passive(...)        → passive bid / ask orders
    _fit_smile(state, ...)    → self-contained smile fit from state.order_depths

  Shared-state coordination via `memory["_shared"]` is opportunistic: if the
  harness injects a per-tick shared dict we reuse per-tick computations (spot,
  smile) once; otherwise we self-compute.

Params (all `self.params["X"]`):
  strike                : option strike K (required)
  tte_days_initial      : TTE at session start, in days (default 5.0)
  timestamp_units_per_day: raw timestamp units per day (default from ticks_per_day * ts_increment)
  historical_tte_by_day : optional backtest map, e.g. {0: 8, 1: 7, 2: 6}
  underlying_symbol     : e.g. "VELVETFRUIT_EXTRACT"
  prior_vol             : initial sigma guess (default 0.02 = 2%/day)
  maker_edge            : ticks around BS fair for passive quotes (default 2)
  maker_size            : target size per passive quote (default 20)
  take_edge             : take if market mispriced by this many ticks vs fair (default 3)
  take_size             : max qty per taker tick (default 40)
  use_smile             : True = smile-fitted sigma; False = own iv (default True)
  iv_ewma_alpha         : EWMA on per-strike IV (default 0.3)
  sigma_floor / sigma_cap: bounds on sigma (default 0.005 / 0.10 = 0.5% / 10% daily)
  enable_takers         : opt-in aggressive crossing (default True)
  penny_improve_around_mkt: True = quote at best_bid+1 / best_ask-1 (stable naive MM)
                           False = quote at round(fair ± maker_edge) (BS-driven)
  min_quote_price       : skip quoting when BS fair < this (default 2.0, guards deep OTM)
  inv_bias_per_unit     : skew fair by -this × position (default 0.02)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_price
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


class OptionMMBSStrategy(BaseStrategy):
    """European call market-maker using Black-Scholes + volatility smile."""

    # ── Entry point ──────────────────────────────────────────────────────────

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

        # 1. Resolve underlying spot (shared across all VEV_xxxx this tick).
        S = self._resolve_spot(state, memory, ts)
        if S is None:
            return [], 0

        # 2. Choose sigma to price this option: smile-fit / own IV / EWMA'd.
        own_mid = 0.5 * (book.best_bid + book.best_ask)
        sigma = self._resolve_sigma(
            state=state, memory=memory, own_mid=own_mid,
            S=S, K=p["K"], T=p["T"], ts=ts, params=p,
        )

        # 3. Compute BS fair value + inventory skew.
        fair = call_price(S, p["K"], p["T"], sigma)
        self._record_diagnostics(memory, fair=fair, sigma=sigma, T=p["T"], S=S, tte0=p["tte0"])
        if fair < p["min_quote_price"]:
            memory["_skipped"] = 1
            return [], 0
        fair_skewed = fair - p["inv_bias_per_unit"] * position

        # 4. Determine quote prices (two modes: penny-improve vs BS-edged).
        bid_px, ask_px = self._compute_quotes(book, fair_skewed, p)

        # 5. Taker + passive orders.
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        if p["enable_takers"]:
            taker_orders, buy_cap, sell_cap = self._fire_takers(
                fair_skewed, book, order_depth, buy_cap, sell_cap, p,
            )
            orders.extend(taker_orders)

        orders.extend(self._post_passive(bid_px, ask_px, buy_cap, sell_cap, p["maker_size"]))
        return orders, 0

    # ── Param loading ────────────────────────────────────────────────────────

    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        """Read + normalize all params once per tick."""
        params = self.params
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(params.get("tte_days_initial", 5.0)),
            params.get("historical_tte_by_day"),
        )
        ts = int(state.timestamp)
        ts_per_day = timestamp_units_per_day_from_params(params)
        T = time_to_expiry_days(ts, tte0, timestamp_units_per_day=ts_per_day)
        return {
            "K": float(params["strike"]),
            "tte0": tte0,
            "T": max(0.01, T),
            "prior_vol": float(params.get("prior_vol", 0.02)),
            "maker_edge": int(params.get("maker_edge", 2)),
            "maker_size": int(params.get("maker_size", 20)),
            "take_edge": float(params.get("take_edge", 3.0)),
            "take_size": int(params.get("take_size", 40)),
            "use_smile": bool(params.get("use_smile", True)),
            "iv_ewma_alpha": float(params.get("iv_ewma_alpha", 0.3)),
            "sigma_floor": float(params.get("sigma_floor", 0.005)),
            "sigma_cap": float(params.get("sigma_cap", 0.10)),
            "enable_takers": bool(params.get("enable_takers", True)),
            "penny_improve_around_mkt": bool(params.get("penny_improve_around_mkt", False)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "inv_bias_per_unit": float(params.get("inv_bias_per_unit", 0.02)),
            "underlying_symbol": params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
        }

    # ── Spot resolution ──────────────────────────────────────────────────────

    def _resolve_spot(
        self, state: TradingState, memory: Dict[str, Any], ts: int,
    ) -> Optional[float]:
        """Return mid-price of the underlying, reading from per-tick shared cache."""
        shared = self._shared(memory)
        # Per-tick cache hit
        if shared.get("underlying_spot_ts") == ts:
            return shared.get("underlying_spot")
        # Compute from order_depths
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        u_od = state.order_depths.get(underlying)
        if not u_od or not u_od.buy_orders or not u_od.sell_orders:
            return None
        ub = max(u_od.buy_orders.keys())
        ua = min(u_od.sell_orders.keys())
        S = 0.5 * (ub + ua)
        shared["underlying_spot"] = S
        shared["underlying_spot_ts"] = ts
        return S

    # ── Sigma resolution ─────────────────────────────────────────────────────

    def _resolve_sigma(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        own_mid: float,
        S: float,
        K: float,
        T: float,
        ts: int,
        params: Dict[str, Any],
    ) -> float:
        """Return sigma to use for BS pricing of this option at this tick."""
        # 1. EWMA-smooth our own implied vol (always compute, for diagnostics / fallback).
        iv_smooth = self._update_iv_ewma(own_mid, S, K, T, memory, params)
        # Share our IV for smile coordinator / observability.
        shared = self._shared(memory)
        shared.setdefault("vev_iv", {})[K] = iv_smooth

        # 2. Prefer smile-predicted sigma when enabled.
        if not params["use_smile"]:
            return iv_smooth
        smile = self._get_or_fit_smile(state, shared, S, T, ts, params)
        if smile is None:
            return iv_smooth
        sigma = smile_predict(K, smile, S, T)
        return max(params["sigma_floor"], min(params["sigma_cap"], sigma))

    def _update_iv_ewma(
        self,
        own_mid: float,
        S: float,
        K: float,
        T: float,
        memory: Dict[str, Any],
        params: Dict[str, Any],
    ) -> float:
        """Invert BS for our own option mid and EWMA-smooth it."""
        iv = call_implied_vol(own_mid, S, K, T, sigma_init=params["prior_vol"])
        prev = memory.get("_iv_ewma")
        valid = iv is not None and params["sigma_floor"] <= iv <= params["sigma_cap"]
        if not valid:
            return prev if prev is not None else params["prior_vol"]
        if prev is None:
            memory["_iv_ewma"] = iv
            return iv
        alpha = params["iv_ewma_alpha"]
        iv_new = alpha * iv + (1.0 - alpha) * prev
        memory["_iv_ewma"] = iv_new
        return iv_new

    def _get_or_fit_smile(
        self,
        state: TradingState,
        shared: Dict[str, Any],
        S: float,
        T: float,
        ts: int,
        params: Dict[str, Any],
    ) -> Optional[List[float]]:
        """Return smile coefficients, using per-tick shared cache when possible."""
        if shared.get("vev_smile_ts") == ts:
            return shared.get("vev_smile_coeffs")
        coeffs = self._fit_smile(
            state, S, T,
            params["sigma_floor"], params["sigma_cap"], params["prior_vol"],
        )
        shared["vev_smile_coeffs"] = coeffs
        shared["vev_smile_ts"] = ts
        return coeffs

    def _fit_smile(
        self,
        state: TradingState,
        S: float,
        T: float,
        sigma_floor: float,
        sigma_cap: float,
        prior_vol: float,
    ) -> Optional[List[float]]:
        """Fit a quadratic smile from all VEV_xxxx mid-prices in state.order_depths."""
        strikes: List[float] = []
        vols: List[float] = []
        for sym, od in state.order_depths.items():
            if not sym.startswith("VEV_"):
                continue
            try:
                K = float(sym.replace("VEV_", ""))
            except ValueError:
                continue
            if not od.buy_orders or not od.sell_orders:
                continue
            bb = max(od.buy_orders.keys())
            ba = min(od.sell_orders.keys())
            mid = 0.5 * (bb + ba)
            iv = call_implied_vol(mid, S, K, T, sigma_init=prior_vol)
            if iv is not None and sigma_floor <= iv <= sigma_cap:
                strikes.append(K)
                vols.append(iv)
        if len(strikes) < 3:
            return None
        return fit_smile_poly(strikes, vols, S, T, degree=2)

    # ── Quote pricing ────────────────────────────────────────────────────────

    def _compute_quotes(
        self,
        book: BookSnapshot,
        fair_skewed: float,
        params: Dict[str, Any],
    ) -> Tuple[int, int]:
        """Return (bid_px, ask_px). Return -1 for a side to signal 'skip'."""
        if params["penny_improve_around_mkt"]:
            bid_px = book.best_bid + 1
            ask_px = book.best_ask - 1
        else:
            bid_px = int(round(fair_skewed - params["maker_edge"]))
            ask_px = int(round(fair_skewed + params["maker_edge"]))

        # Never post inside own book or cross the market
        if bid_px >= book.best_ask:
            bid_px = book.best_ask - 1
        if ask_px <= book.best_bid:
            ask_px = book.best_bid + 1
        bid_px = max(1, bid_px)       # floor (call options can't price below 1)
        ask_px = max(bid_px + 1, ask_px)

        # Skip markers if our theoretical quote would cross the market
        if bid_px > book.best_ask:
            bid_px = -1
        if ask_px < book.best_bid:
            ask_px = -1
        return bid_px, ask_px

    # ── Taker orders ─────────────────────────────────────────────────────────

    def _fire_takers(
        self,
        fair_skewed: float,
        book: BookSnapshot,
        order_depth: OrderDepth,
        buy_cap: int,
        sell_cap: int,
        params: Dict[str, Any],
    ) -> Tuple[List[Order], int, int]:
        """Aggressive buy/sell when market ask/bid is mispriced vs fair."""
        orders: List[Order] = []
        take_edge = params["take_edge"]
        take_size = params["take_size"]
        # Buy under fair: market ask < fair - take_edge
        if book.best_ask is not None and buy_cap > 0:
            if (fair_skewed - book.best_ask) >= take_edge:
                qty = -order_depth.sell_orders[book.best_ask]
                take_qty = min(qty, buy_cap, take_size)
                if take_qty > 0:
                    orders.append(Order(self.product, book.best_ask, take_qty))
                    buy_cap -= take_qty
        # Sell over fair: market bid > fair + take_edge
        if book.best_bid is not None and sell_cap > 0:
            if (book.best_bid - fair_skewed) >= take_edge:
                qty = order_depth.buy_orders[book.best_bid]
                take_qty = min(qty, sell_cap, take_size)
                if take_qty > 0:
                    orders.append(Order(self.product, book.best_bid, -take_qty))
                    sell_cap -= take_qty
        return orders, buy_cap, sell_cap

    # ── Passive orders ───────────────────────────────────────────────────────

    def _post_passive(
        self,
        bid_px: int,
        ask_px: int,
        buy_cap: int,
        sell_cap: int,
        maker_size: int,
    ) -> List[Order]:
        """Post one passive bid + one passive ask within remaining capacity."""
        orders: List[Order] = []
        if bid_px > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(maker_size, buy_cap)))
        if ask_px > 0 and sell_cap > 0:
            orders.append(Order(self.product, ask_px, -min(maker_size, sell_cap)))
        return orders

    # ── Utilities ────────────────────────────────────────────────────────────

    def _shared(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        """Return (creating if needed) the cross-product shared dict."""
        shared = memory.get("_shared")
        if not isinstance(shared, dict):
            shared = {}
            memory["_shared"] = shared
        return shared

    def _record_diagnostics(
        self,
        memory: Dict[str, Any],
        *,
        fair: float,
        sigma: float,
        T: float,
        S: float,
        tte0: float,
    ) -> None:
        """Write per-tick diagnostics to memory (consumed by feature_prices)."""
        memory["_bs_fair"] = fair
        memory["_sigma_use"] = sigma
        memory["_tte_days"] = T
        memory["_tte_initial_days"] = tte0
        memory["_spot"] = S

    # ── Dashboard feature hooks ──────────────────────────────────────────────

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (f := memory.get("_bs_fair")) is not None:
            out["BS_fair"] = f
        if (s := memory.get("_sigma_use")) is not None:
            out["sigma_pct"] = s * 100
        if (T := memory.get("_tte_days")) is not None:
            out["TTE_days"] = T
        return out
