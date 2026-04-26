"""OptionSkewSignalMM - trade voucher distortions versus a leave-one-out smile.

For each VEV option, this strategy fits the volatility smile using the other
strikes, then compares the current option to that leave-one-out fair value.

Positive price_edge = fair_without_this_strike - market_mid:
  option looks cheap versus the rest of the surface, bias long.

Negative price_edge:
  option looks rich versus the rest of the surface, bias short or trim long.
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


class OptionSkewSignalMMStrategy(BaseStrategy):
    """One-option skew-arb MM using a leave-one-out smile as fair value."""

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
        pred_iv = self._leave_one_out_sigma(state, S, p)
        if pred_iv is None:
            return self._neutral_quotes(book, position, p), 0

        fair = call_price(S, p["K"], p["T"], pred_iv)
        price_edge = fair - own_mid
        iv_residual = None if own_iv is None else own_iv - pred_iv
        self._record(memory, S, p["T"], own_iv, pred_iv, fair, price_edge, iv_residual)

        if fair < p["min_quote_price"]:
            return [], 0

        buy_cap = min(self.buy_capacity(position), max(0, p["max_long"] - position))
        sell_cap = min(self.sell_capacity(position), max(0, p["max_short"] + position))
        orders: List[Order] = []

        cheap = price_edge >= p["entry_edge"]
        rich = price_edge <= -p["entry_edge"]

        if p["enable_takers"]:
            takers, buy_cap, sell_cap = self._takers(
                fair, book, order_depth, buy_cap, sell_cap, p
            )
            orders.extend(takers)

        if cheap:
            orders.extend(self._cheap_quotes(book, position, buy_cap, sell_cap, p))
        elif rich:
            orders.extend(self._rich_quotes(book, position, buy_cap, sell_cap, p))
        elif p["quote_neutral"]:
            orders.extend(self._neutral_quotes(book, position, p, buy_cap=buy_cap, sell_cap=sell_cap))

        return orders, 0

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
            "entry_edge": float(params.get("entry_edge", 2.0)),
            "take_edge": float(params.get("take_edge", 4.0)),
            "maker_size": int(params.get("maker_size", 16)),
            "neutral_size": int(params.get("neutral_size", 4)),
            "exit_size": int(params.get("exit_size", 10)),
            "take_size": int(params.get("take_size", 12)),
            "max_long": int(params.get("max_long", 80)),
            "max_short": int(params.get("max_short", 40)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "enable_takers": bool(params.get("enable_takers", False)),
            "quote_neutral": bool(params.get("quote_neutral", False)),
            "allow_new_shorts": bool(params.get("allow_new_shorts", True)),
        }

    def _leave_one_out_sigma(
        self,
        state: TradingState,
        S: float,
        p: Dict[str, Any],
    ) -> Optional[float]:
        strikes: List[float] = []
        vols: List[float] = []
        for strike in p["smile_strikes"]:
            if float(strike) == p["K"]:
                continue
            od = state.order_depths.get(f"{p['strike_prefix']}{strike}")
            if not od or not od.buy_orders or not od.sell_orders:
                continue
            bid = max(od.buy_orders)
            ask = min(od.sell_orders)
            mid = 0.5 * (bid + ask)
            iv = call_implied_vol(mid, S, float(strike), p["T"], sigma_init=p["prior_vol"])
            if iv is None or iv < p["sigma_floor"] or iv > p["sigma_cap"]:
                continue
            strikes.append(float(strike))
            vols.append(iv)

        if len(strikes) < 3:
            return None
        coeffs = fit_smile_poly(strikes, vols, S, p["T"], degree=2)
        if coeffs is None:
            return None
        sigma = smile_predict(p["K"], coeffs, S, p["T"])
        return max(p["sigma_floor"], min(p["sigma_cap"], sigma))

    def _inside_bid(self, book: BookSnapshot) -> int:
        if book.best_bid + 1 < book.best_ask:
            return book.best_bid + 1
        return book.best_bid

    def _inside_ask(self, book: BookSnapshot) -> int:
        if book.best_ask - 1 > book.best_bid:
            return book.best_ask - 1
        return book.best_ask

    def _takers(
        self,
        fair: float,
        book: BookSnapshot,
        order_depth: OrderDepth,
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        if buy_cap > 0 and fair - book.best_ask >= p["take_edge"]:
            qty = min(-order_depth.sell_orders.get(book.best_ask, 0), buy_cap, p["take_size"])
            if qty > 0:
                orders.append(Order(self.product, book.best_ask, qty))
                buy_cap -= qty
        if sell_cap > 0 and book.best_bid - fair >= p["take_edge"]:
            qty = min(order_depth.buy_orders.get(book.best_bid, 0), sell_cap, p["take_size"])
            if qty > 0:
                orders.append(Order(self.product, book.best_bid, -qty))
                sell_cap -= qty
        return orders, buy_cap, sell_cap

    def _cheap_quotes(
        self,
        book: BookSnapshot,
        position: int,
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> List[Order]:
        orders: List[Order] = []
        if buy_cap > 0:
            orders.append(Order(self.product, self._inside_bid(book), min(p["maker_size"], buy_cap)))
        if position > 0 and sell_cap > 0:
            orders.append(Order(self.product, self._inside_ask(book), -min(p["exit_size"], sell_cap, position)))
        return orders

    def _rich_quotes(
        self,
        book: BookSnapshot,
        position: int,
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> List[Order]:
        orders: List[Order] = []
        can_sell = p["allow_new_shorts"] or position > 0
        if can_sell and sell_cap > 0:
            orders.append(Order(self.product, self._inside_ask(book), -min(p["maker_size"], sell_cap)))
        if position < 0 and buy_cap > 0:
            orders.append(Order(self.product, self._inside_bid(book), min(p["exit_size"], buy_cap, -position)))
        return orders

    def _neutral_quotes(
        self,
        book: BookSnapshot,
        position: int,
        p: Dict[str, Any],
        *,
        buy_cap: Optional[int] = None,
        sell_cap: Optional[int] = None,
    ) -> List[Order]:
        buy_cap = self.buy_capacity(position) if buy_cap is None else buy_cap
        sell_cap = self.sell_capacity(position) if sell_cap is None else sell_cap
        orders: List[Order] = []
        size = p["neutral_size"]
        if size <= 0:
            return orders
        if buy_cap > 0:
            orders.append(Order(self.product, self._inside_bid(book), min(size, buy_cap)))
        if sell_cap > 0:
            orders.append(Order(self.product, self._inside_ask(book), -min(size, sell_cap)))
        return orders

    def _record(
        self,
        memory: Dict[str, Any],
        S: float,
        T: float,
        own_iv: Optional[float],
        pred_iv: float,
        fair: float,
        price_edge: float,
        iv_residual: Optional[float],
    ) -> None:
        memory["_spot"] = S
        memory["_T"] = T
        memory["_own_iv"] = own_iv
        memory["_loo_iv"] = pred_iv
        memory["_loo_fair"] = fair
        memory["_price_edge"] = price_edge
        memory["_iv_residual"] = iv_residual

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_own_iv")) is not None:
            out["own_iv_pct"] = float(v) * 100.0
        if (v := memory.get("_loo_iv")) is not None:
            out["loo_iv_pct"] = float(v) * 100.0
        if (v := memory.get("_price_edge")) is not None:
            out["loo_price_edge"] = float(v)
        if (v := memory.get("_iv_residual")) is not None:
            out["loo_iv_resid_bps"] = float(v) * 10000.0
        return out
