"""Theo round 3 option strategy.

Core idea:
  - keep HYDROGEL outside of this file; it can stay on the stable naive MM
  - treat VELVETFRUIT_EXTRACT as the hedge leg
  - trade a selected subset of VEV strikes with a long-vol bias
  - price options with a blend of market smile IV and realized-vol anchor
  - delta-hedge the option inventory back through VELVETFRUIT_EXTRACT

The strategy is intentionally conservative:
  - no naked short-vol inventory from flat
  - only selected strikes are enabled in config
  - underlying mainly hedges; any MM on the hedge leg stays small
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_delta, call_price
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


class TheoR3VolArbV1Strategy(BaseStrategy):
    """Round 3 Theo strategy for VELVET hedge + selected VEV long-vol trades."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        role = str(self.params.get("role", "option"))
        if role == "underlying":
            return self._compute_underlying(state, book, order_depth, position, memory)
        return self._compute_option(state, book, order_depth, position, memory)

    # ------------------------------------------------------------------
    # Shared state
    # ------------------------------------------------------------------
    def _shared(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        shared = memory.get("_shared")
        if not isinstance(shared, dict):
            shared = {}
            memory["_shared"] = shared
        return shared

    def _option_symbol(self, strike: int | float) -> str:
        return f"VEV_{int(strike)}"

    def _option_strike(self, symbol: str) -> Optional[int]:
        if not symbol.startswith("VEV_"):
            return None
        try:
            return int(symbol.replace("VEV_", ""))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Market context
    # ------------------------------------------------------------------
    def _resolve_underlying_mid(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        ts: int,
    ) -> Optional[float]:
        shared = self._shared(memory)
        if shared.get("velvet_mid_ts") == ts:
            return shared.get("velvet_mid")

        symbol = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(symbol)
        if not od or not od.buy_orders or not od.sell_orders:
            return None

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        mid = 0.5 * (best_bid + best_ask)
        shared["velvet_mid_ts"] = ts
        shared["velvet_mid"] = mid
        return mid

    def _resolve_market_sigma(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        *,
        S: float,
        K: float,
        T: float,
        own_mid: float,
        ts: int,
    ) -> float:
        floor = float(self.params.get("sigma_floor", 0.005))
        cap = float(self.params.get("sigma_cap", 0.10))
        prior = float(self.params.get("prior_vol", 0.0125))

        own_iv = call_implied_vol(own_mid, S, K, T, sigma_init=prior)
        if own_iv is None or not (floor <= own_iv <= cap):
            own_iv = prior

        shared = self._shared(memory)
        coeffs = self._get_or_fit_smile(state, memory, S, T, ts)
        if coeffs is None:
            return max(floor, min(cap, own_iv))
        sigma = smile_predict(K, coeffs, S, T)
        return max(floor, min(cap, sigma))

    def _get_or_fit_smile(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        S: float,
        T: float,
        ts: int,
    ) -> Optional[List[float]]:
        shared = self._shared(memory)
        if shared.get("vev_smile_ts") == ts:
            return shared.get("vev_smile_coeffs")

        floor = float(self.params.get("sigma_floor", 0.005))
        cap = float(self.params.get("sigma_cap", 0.10))
        prior = float(self.params.get("prior_vol", 0.0125))

        strikes: List[float] = []
        vols: List[float] = []
        for symbol, od in state.order_depths.items():
            strike = self._option_strike(symbol)
            if strike is None or not od.buy_orders or not od.sell_orders:
                continue
            mid = 0.5 * (max(od.buy_orders) + min(od.sell_orders))
            iv = call_implied_vol(mid, S, strike, T, sigma_init=prior)
            if iv is not None and floor <= iv <= cap:
                strikes.append(float(strike))
                vols.append(iv)

        coeffs = fit_smile_poly(strikes, vols, S, T, degree=2) if len(strikes) >= 3 else None
        shared["vev_smile_ts"] = ts
        shared["vev_smile_coeffs"] = coeffs
        return coeffs

    def _resolve_realized_sigma(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        ts: int,
    ) -> float:
        shared = self._shared(memory)
        if shared.get("realized_sigma_ts") == ts:
            return float(shared.get("realized_sigma", self.params.get("realized_vol_default", 0.0215)))

        sigma = float(self.params.get("realized_vol_default", 0.0215))
        S = self._resolve_underlying_mid(state, memory, ts)
        prev = shared.get("velvet_mid_prev")

        if S is not None and prev is not None and prev > 0 and S > 0:
            ret = math.log(S / prev)
            alpha = float(self.params.get("realized_var_alpha", 0.06))
            var_prev = shared.get("velvet_var_tick")
            ret_sq = ret * ret
            var_tick = ret_sq if var_prev is None else alpha * ret_sq + (1.0 - alpha) * float(var_prev)
            shared["velvet_var_tick"] = var_tick

            ticks_per_day = float(self.params.get("ticks_per_day", 10000))
            sigma_raw = math.sqrt(max(var_tick, 0.0)) * math.sqrt(ticks_per_day)
            sigma = max(
                float(self.params.get("realized_vol_floor", 0.0100)),
                min(float(self.params.get("realized_vol_cap", 0.0500)), sigma_raw),
            )

        if S is not None:
            shared["velvet_mid_prev"] = S

        shared["realized_sigma_ts"] = ts
        shared["realized_sigma"] = sigma
        return sigma

    def _resolve_tte(self, state: TradingState) -> Tuple[float, float]:
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(self.params.get("tte_days_initial", 5.0)),
            self.params.get("historical_tte_by_day"),
        )
        ts_units = timestamp_units_per_day_from_params(self.params)
        T = time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_units)
        return tte0, max(0.01, T)

    def _target_sigma(self, market_sigma: float, realized_sigma: float) -> float:
        floor = float(self.params.get("sigma_floor", 0.005))
        cap = float(self.params.get("sigma_cap", 0.10))
        weight = float(self.params.get("realized_anchor_weight", 0.55))
        uplift = max(0.0, realized_sigma - market_sigma)
        sigma = market_sigma + weight * uplift
        sigma = max(sigma, float(self.params.get("target_sigma_floor", market_sigma)))
        return max(floor, min(cap, sigma))

    def _portfolio_option_delta(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        *,
        S: float,
        T: float,
        ts: int,
    ) -> float:
        shared = self._shared(memory)
        if shared.get("portfolio_option_delta_ts") == ts:
            return float(shared.get("portfolio_option_delta", 0.0))

        coeffs = self._get_or_fit_smile(state, memory, S, T, ts)
        prior = float(self.params.get("prior_vol", 0.0125))
        floor = float(self.params.get("sigma_floor", 0.005))
        cap = float(self.params.get("sigma_cap", 0.10))

        total = 0.0
        for symbol, pos in state.position.items():
            strike = self._option_strike(symbol)
            if strike is None or pos == 0:
                continue
            od = state.order_depths.get(symbol)
            if not od or not od.buy_orders or not od.sell_orders:
                continue
            mid = 0.5 * (max(od.buy_orders) + min(od.sell_orders))
            sigma = None
            if coeffs is not None:
                sigma = smile_predict(float(strike), coeffs, S, T)
            if sigma is None:
                sigma = call_implied_vol(mid, S, strike, T, sigma_init=prior)
            if sigma is None:
                sigma = prior
            sigma = max(floor, min(cap, sigma))
            total += int(pos) * call_delta(S, strike, T, sigma)

        shared["portfolio_option_delta_ts"] = ts
        shared["portfolio_option_delta"] = total
        return total

    # ------------------------------------------------------------------
    # Underlying hedge leg
    # ------------------------------------------------------------------
    def _compute_underlying(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.spread is None:
            return [], 0

        _, T = self._resolve_tte(state)
        ts = int(state.timestamp)
        S = self._resolve_underlying_mid(state, memory, ts)
        if S is None:
            return [], 0

        option_delta = self._portfolio_option_delta(state, memory, S=S, T=T, ts=ts)
        target = int(round(-float(self.params.get("hedge_ratio", 1.0)) * option_delta))

        max_abs = int(self.params.get("hedge_abs_position_limit", self.position_limit()))
        target = max(-max_abs, min(max_abs, target))

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        aggressive_band = int(self.params.get("hedge_aggressive_band", 18))
        passive_band = int(self.params.get("hedge_passive_band", 6))
        clip = int(self.params.get("hedge_clip_size", 24))
        maker_size = int(self.params.get("neutral_mm_size", 10))
        gap = target - position

        if gap > aggressive_band and buy_cap > 0:
            qty = min(gap, buy_cap, clip, max(1, book.best_ask_volume))
            if qty > 0:
                orders.append(Order(self.product, book.best_ask, qty))
                position += qty
                buy_cap -= qty
                gap = target - position
        elif gap < -aggressive_band and sell_cap > 0:
            qty = min(-gap, sell_cap, clip, max(1, book.best_bid_volume))
            if qty > 0:
                orders.append(Order(self.product, book.best_bid, -qty))
                position -= qty
                sell_cap -= qty
                gap = target - position

        improve_bid = 1 if book.spread >= 2 else 0
        improve_ask = 1 if book.spread >= 2 else 0

        bid_px = None
        ask_px = None

        if gap > passive_band and buy_cap > 0:
            bid_px = min(book.best_bid + improve_bid, book.best_ask - 1)
            qty = min(gap, buy_cap, maker_size)
            if qty > 0:
                orders.append(Order(self.product, bid_px, qty))
        elif gap < -passive_band and sell_cap > 0:
            ask_px = max(book.best_ask - improve_ask, book.best_bid + 1)
            qty = min(-gap, sell_cap, maker_size)
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
        elif abs(position) <= int(self.params.get("neutral_mm_position_cap", 20)):
            if buy_cap > 0:
                bid_px = min(book.best_bid + improve_bid, book.best_ask - 1)
                orders.append(Order(self.product, bid_px, min(maker_size, buy_cap)))
            if sell_cap > 0:
                ask_px = max(book.best_ask - improve_ask, book.best_bid + 1)
                orders.append(Order(self.product, ask_px, -min(maker_size, sell_cap)))

        memory["_target_hedge_pos"] = target
        memory["_portfolio_option_delta"] = option_delta
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_px,
            ask_price=ask_px,
            extras={
                "target_pos": target,
                "opt_delta": round(option_delta, 2),
            },
        )
        return orders, 0

    # ------------------------------------------------------------------
    # Option leg
    # ------------------------------------------------------------------
    def _compute_option(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        strike = self._option_strike(self.product)
        if strike is None:
            return [], 0

        _, T = self._resolve_tte(state)
        ts = int(state.timestamp)
        S = self._resolve_underlying_mid(state, memory, ts)
        if S is None:
            return [], 0

        own_mid = 0.5 * (book.best_bid + book.best_ask)
        market_sigma = self._resolve_market_sigma(
            state,
            memory,
            S=S,
            K=float(strike),
            T=T,
            own_mid=own_mid,
            ts=ts,
        )
        realized_sigma = self._resolve_realized_sigma(state, memory, ts)
        target_sigma = self._target_sigma(market_sigma, realized_sigma)
        fair = call_price(S, float(strike), T, target_sigma)
        delta = call_delta(S, float(strike), T, market_sigma)

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        trade_enabled = bool(self.params.get("trade_enabled", True))
        take_size = int(self.params.get("take_size", 12))
        maker_size = int(self.params.get("maker_size", 8))
        soft_limit = int(self.params.get("soft_position_limit", 80))
        hedge_limit = float(self.params.get("hedge_abs_position_limit", 180))
        take_edge = float(self.params.get("take_edge", 6.0))
        reduce_edge = float(self.params.get("reduce_edge", 2.0))
        maker_edge = float(self.params.get("maker_edge", 6.0))
        min_quote_price = float(self.params.get("min_quote_price", 4.0))
        inv_skew = float(self.params.get("inventory_skew", 4.0))
        enable_takers = bool(self.params.get("enable_takers", True))

        option_delta = self._portfolio_option_delta(state, memory, S=S, T=T, ts=ts)

        if enable_takers and trade_enabled and position < soft_limit and buy_cap > 0:
            edge_buy = fair - book.best_ask
            if edge_buy >= take_edge:
                hedge_room = max(0.0, hedge_limit - abs(option_delta))
                hedge_cap = max(0, int(hedge_room / max(delta, 1e-6)))
                size = max(2, int(edge_buy // take_edge) * 4)
                qty = min(take_size, buy_cap, hedge_cap, max(1, book.best_ask_volume), size)
                if qty > 0:
                    orders.append(Order(self.product, book.best_ask, qty))
                    position += qty
                    buy_cap -= qty

        if enable_takers and position > 0 and sell_cap > 0:
            edge_sell = book.best_bid - fair
            if edge_sell >= reduce_edge or position > soft_limit:
                qty = min(position, sell_cap, take_size, max(1, book.best_bid_volume))
                if qty > 0:
                    orders.append(Order(self.product, book.best_bid, -qty))
                    position -= qty
                    sell_cap -= qty

        bid_px = None
        ask_px = None
        if fair >= min_quote_price and trade_enabled and buy_cap > 0 and position < soft_limit:
            raw_bid = int(round(fair - maker_edge - inv_skew * max(position, 0) / max(soft_limit, 1)))
            join_bid = book.best_bid + (1 if (book.spread or 0) >= 2 else 0)
            cap_bid = book.best_ask - 1
            bid_px = max(1, min(cap_bid, max(join_bid, raw_bid)))
            if bid_px <= book.best_bid and (book.spread or 0) >= 2:
                bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                orders.append(Order(self.product, bid_px, min(maker_size, buy_cap)))

        if position > 0 and sell_cap > 0:
            raw_ask = int(round(fair + maker_edge - inv_skew * position / max(soft_limit, 1)))
            join_ask = book.best_ask - (1 if (book.spread or 0) >= 2 else 0)
            floor_ask = book.best_bid + 1
            ask_px = max(floor_ask, min(join_ask, raw_ask))
            if ask_px > book.best_bid:
                orders.append(Order(self.product, ask_px, -min(maker_size, sell_cap, max(position, 1))))

        memory["_fair"] = fair
        memory["_market_sigma"] = market_sigma
        memory["_realized_sigma"] = realized_sigma
        memory["_target_sigma"] = target_sigma
        memory["_delta"] = delta

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_px,
            ask_price=ask_px,
            extras={
                "fair": round(fair, 2),
                "sigma_mkt_bps": round(market_sigma * 10000, 1),
                "sigma_target_bps": round(target_sigma * 10000, 1),
            },
        )
        return orders, 0

    # ------------------------------------------------------------------
    # Dashboard hooks
    # ------------------------------------------------------------------
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (fair := memory.get("_fair")) is not None:
            out["Theo_fair"] = float(fair)
        if (target_sigma := memory.get("_target_sigma")) is not None:
            out["Theo_sigma_target_pct"] = float(target_sigma) * 100.0
        if (delta := memory.get("_delta")) is not None:
            out["Theo_delta"] = float(delta)
        if (target_pos := memory.get("_target_hedge_pos")) is not None:
            out["Theo_target_hedge_pos"] = float(target_pos)
        return out
