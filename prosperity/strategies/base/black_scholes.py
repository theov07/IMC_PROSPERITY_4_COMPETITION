"""Black-Scholes based options/voucher trading strategy.

Computes theoretical option price from the underlying, then trades
mispriced options.  Also supports implied-vol mean reversion.

Config params:
  underlying: symbol of the underlying product (e.g. "VOLCANIC_ROCK")
  strike: option strike price
  risk_free_rate: annualized risk-free rate (default 0.0)
  total_ticks: total ticks in the simulation (default 10000)
  ticks_per_year: how many ticks map to 1 year of vol (default 252*10000)
  vol_window: lookback for realized vol estimation (default 100)
  vol_default: default vol if not enough data (default 0.2)
  iv_mean_reversion: whether to also trade IV mean reversion (default False)
  iv_window: window for IV mean/std tracking (default 50)
  iv_entry_z: z-threshold for IV trades (default 1.5)
  edge_threshold: min edge in price to trade (default 1.0)
  maker_size: order size (default 5)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot, snapshot_from_order_depth
from prosperity.strategies.base import BaseStrategy


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erfc (available in stdlib)."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _bs_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _bs_delta(S: float, K: float, T: float, r: float, sigma: float, is_call: bool = True) -> float:
    if T <= 0 or sigma <= 0:
        return 1.0 if (S > K) == is_call else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0


def _implied_vol(market_price: float, S: float, K: float, T: float, r: float, is_call: bool = True) -> float:
    """Newton-Raphson IV solver."""
    if T <= 0:
        return 0.0
    sigma = 0.3
    for _ in range(50):
        price = _bs_call(S, K, T, r, sigma) if is_call else _bs_put(S, K, T, r, sigma)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        vega = S * math.sqrt(T) * math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        if vega < 1e-10:
            break
        sigma = sigma - (price - market_price) / vega
        sigma = max(sigma, 0.01)
    return sigma


class BlackScholesStrategy(BaseStrategy):

    def _get_underlying_mid(self, state: TradingState) -> float | None:
        underlying = self.params.get("underlying")
        if not underlying:
            return None
        od = state.order_depths.get(underlying)
        if od is None:
            return None
        ub = snapshot_from_order_depth(underlying, od)
        return ub.mid_price

    def _update_vol(self, mid: float, memory: Dict[str, Any]) -> float:
        window = self.params.get("vol_window", 100)
        prices = memory.setdefault("underlying_history", [])
        prices.append(mid)
        if len(prices) > window + 1:
            prices[:] = prices[-(window + 1):]
        if len(prices) < 5:
            return self.params.get("vol_default", 0.2)

        returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i - 1] > 0]
        if len(returns) < 2:
            return self.params.get("vol_default", 0.2)

        n = len(returns)
        mean_r = sum(returns) / n
        var_r = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)

        # Annualize: multiply by sqrt(ticks_per_year)
        tpy = self.params.get("ticks_per_year", 252 * 10000)
        annual_vol = math.sqrt(var_r * tpy) if var_r > 0 else self.params.get("vol_default", 0.2)
        return max(annual_vol, 0.05)

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        underlying_mid = self._get_underlying_mid(state)
        if underlying_mid is None or book.mid_price is None:
            return [], 0

        strike = self.params.get("strike", underlying_mid)
        r = self.params.get("risk_free_rate", 0.0)
        total_ticks = self.params.get("total_ticks", 10000)
        tpy = self.params.get("ticks_per_year", 252 * 10000)
        tick = memory.get("tick_count", 0)
        memory["tick_count"] = tick + 1

        T = max((total_ticks - tick) / tpy, 1e-6)
        sigma = self._update_vol(underlying_mid, memory)

        is_call = self.params.get("is_call", True)
        theo = _bs_call(underlying_mid, strike, T, r, sigma) if is_call else _bs_put(underlying_mid, strike, T, r, sigma)
        delta = _bs_delta(underlying_mid, strike, T, r, sigma, is_call)

        # Compute IV from market price for tracking
        iv = _implied_vol(book.mid_price, underlying_mid, strike, T, r, is_call)

        memory["theo"] = theo
        memory["sigma"] = sigma
        memory["iv"] = iv
        memory["delta"] = delta

        edge_threshold = self.params.get("edge_threshold", 1.0)
        maker_size = self.params.get("maker_size", 5)
        orders: List[Order] = []

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Trade if market price differs significantly from theo
        if book.best_ask is not None and book.best_ask < theo - edge_threshold and buy_cap > 0:
            qty = min(maker_size, buy_cap)
            orders.append(Order(self.product, book.best_ask, qty))

        if book.best_bid is not None and book.best_bid > theo + edge_threshold and sell_cap > 0:
            qty = min(maker_size, sell_cap)
            orders.append(Order(self.product, book.best_bid, -qty))

        # ── IV mean reversion (optional) ──
        if self.params.get("iv_mean_reversion", False):
            iv_history = memory.setdefault("iv_history", [])
            iv_history.append(iv)
            iv_window = self.params.get("iv_window", 50)
            if len(iv_history) > iv_window:
                iv_history[:] = iv_history[-iv_window:]

            if len(iv_history) >= 10:
                iv_mean = sum(iv_history) / len(iv_history)
                iv_std = math.sqrt(sum((v - iv_mean) ** 2 for v in iv_history) / (len(iv_history) - 1))
                if iv_std > 0:
                    iv_z = (iv - iv_mean) / iv_std
                    iv_entry = self.params.get("iv_entry_z", 1.5)

                    if iv_z > iv_entry and sell_cap > 0 and not orders:
                        # IV is high → option overpriced → sell
                        qty = min(maker_size, sell_cap)
                        if book.best_bid is not None:
                            orders.append(Order(self.product, book.best_bid, -qty))
                    elif iv_z < -iv_entry and buy_cap > 0 and not orders:
                        # IV is low → option underpriced → buy
                        qty = min(maker_size, buy_cap)
                        if book.best_ask is not None:
                            orders.append(Order(self.product, book.best_ask, qty))

        return orders, 0
