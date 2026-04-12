"""Avellaneda-Stoikov optimal market making strategy.

The model computes:
  - reservation price:  r = s - q * gamma * sigma^2 * tau
  - optimal spread:     delta = gamma * sigma^2 * tau + (2/gamma) * ln(1 + gamma/kappa)

Where:
  s     = mid price
  q     = current inventory (signed)
  gamma = risk aversion parameter
  sigma = estimated volatility
  tau   = time remaining (fraction of total horizon)
  kappa = order arrival intensity parameter

References:
  - Avellaneda & Stoikov (2008) "High-frequency trading in a limit order book"
  - Guéant, Lehalle, Fernandez-Tapia (2012) optimal market making extensions
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class AvellanedaStoikovStrategy(BaseStrategy):

    # ── mid price smoothing ──────────────────────────────────────────
    def _smooth_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        window = int(self.params.get("mid_smooth_window", 0))
        if window <= 0:
            return mid
        half_life = float(self.params.get("mid_smooth_half_life", window / 2.0))
        buf = memory.setdefault("mid_smooth_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < 2:
            return mid
        alpha = 1.0 - 2.0 ** (-1.0 / half_life) if half_life > 0 else 1.0
        smoothed = buf[0]
        for p in buf[1:]:
            smoothed = alpha * p + (1.0 - alpha) * smoothed
        memory["mid_smoothed"] = smoothed
        return smoothed

    # ── volatility estimation ────────────────────────────────────────
    def _update_volatility(self, mid: float, memory: Dict[str, Any]) -> float:
        window = int(self.params.get("sigma_window", 50))
        prices = memory.setdefault("mid_history", [])
        prices.append(mid)
        if len(prices) > window + 1:
            prices[:] = prices[-(window + 1):]

        if len(prices) < 3:
            return self.params.get("sigma_default", 1.0)

        # Realized volatility from mid returns
        returns = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        n = len(returns)
        mean_r = sum(returns) / n
        var = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
        sigma_raw = math.sqrt(var) if var > 0 else self.params.get("sigma_default", 1.0)

        # Apply exponential smoothing with parametrizable half-life
        half_life = float(self.params.get("sigma_half_life", 60))
        alpha = 2.0 / (half_life + 1.0)
        sigma_prev = memory.get("sigma_smoothed", sigma_raw)
        sigma_smoothed = alpha * sigma_raw + (1.0 - alpha) * sigma_prev
        memory["sigma_smoothed"] = sigma_smoothed

        # Floor to prevent degenerate spreads
        return max(sigma_smoothed, self.params.get("sigma_floor", 0.5))

    # ── core A-S computation ─────────────────────────────────────────
    def _compute_as_quotes(
        self, mid: float, position: int, sigma: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:

        # Not using tau for now since open position are still automatically liquidated at the end of the day using fair value
        """ ts_increment = int(self.params.get("ts_increment", 100))
        last_ts_key = "bt_last_ts_value" if os.environ.get("INTERNAL_BACKTEST") else "last_ts_value"
        last_ts = int(self.params.get(last_ts_key, self.params.get("last_ts_value", 199900)))
        memory["tick_count"] = tick_num + 1
        num_ticks = last_ts // ts_increment + 1
        tick_num = memory.get("tick_count", 0)
        tau = max((num_ticks - tick_num) / num_ticks, 0.001) """

        
        gamma = float(self.params.get("gamma", 0.1))
        kappa = float(self.params.get("kappa", 1.5))

        #  # Reservation price
        reservation = mid - position * gamma * sigma * sigma # * tau 

        # Optimal half-spread
        #half_spread = (gamma * sigma * sigma * tau) / 2.0 + math.log(1.0 + gamma / kappa) / gamma
        half_spread = 5 * ((gamma * sigma * sigma) + math.log(1.0 + gamma / kappa) / gamma)

        # Apply min spread from params
        min_half_spread = float(self.params.get("min_half_spread", 1.0))
        half_spread = max(half_spread, min_half_spread)

        return reservation, half_spread

    # ── order construction ───────────────────────────────────────────
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0

        mid = book.mid_price
        mid_smooth = self._smooth_mid(mid, memory)
        sigma = self._update_volatility(mid, memory)
        reservation, half_spread = self._compute_as_quotes(mid_smooth, position, sigma, memory)

        bid_price = int(math.floor(reservation - half_spread))
        ask_price = int(math.ceil(reservation + half_spread))

        # Ensure we don't cross the book
        if book.best_ask is not None:
            bid_price = min(bid_price, book.best_ask - 1)
        if book.best_bid is not None:
            ask_price = max(ask_price, book.best_bid + 1)
        if ask_price <= bid_price:
            ask_price = bid_price + 1

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        maker_size = int(self.params.get("maker_size", 10))
        orders: List[Order] = []

        # ── Aggressive taking when edge is clear ──
        take_edge = float(self.params.get("take_edge", 0.5))
        for ask_p in sorted(order_depth.sell_orders):
            available = -order_depth.sell_orders[ask_p]
            if ask_p > reservation - take_edge or buy_cap <= 0:
                break
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume = order_depth.buy_orders[bid_p]
            if bid_p < reservation + take_edge or sell_cap <= 0:
                break
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap -= qty

        # ── Passive quoting ──
        limit = self.position_limit()
        inv_ratio = abs(position) / float(limit) if limit else 0.0

        quote_buy = min(buy_cap, maker_size)
        quote_sell = min(sell_cap, maker_size)

        # Reduce quoting when inventory is heavy # TODO: wtf is that
        if inv_ratio >= 0.75:
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0

        if quote_buy > 0:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0:
            orders.append(Order(self.product, ask_price, -quote_sell))

        memory["reservation"] = reservation
        memory["sigma"] = sigma
        memory["half_spread"] = half_spread

        # ── Per-tick log accumulation (live only, suppressed during internal backtest) ──
        if not os.environ.get("INTERNAL_BACKTEST"):
            flush_ts = int(self.params.get("log_flush_ts", 10000))
            last_ts = int(self.params.get("last_ts_value", 199900))

            log = memory.setdefault("_log", [])
            log.append([state.timestamp, round(reservation, 2), bid_price, ask_price])

            end_of_sim = state.timestamp >= last_ts
            checkpoint = flush_ts > 0 and (state.timestamp % flush_ts) == (flush_ts - 100)
            if end_of_sim or checkpoint:
                print(json.dumps({
                    "product": self.product,
                    "chunk_end": state.timestamp,
                    "log": log,  # [[timestamp, reservation, bid, ask], ...]
                }))
                memory["_log"] = []

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (r := memory.get("reservation")) is not None:
            out["Reservation"] = r
        return out
