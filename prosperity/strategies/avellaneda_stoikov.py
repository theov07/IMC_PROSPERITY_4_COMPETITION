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
    def compute_orders(self, state: TradingState, book: BookSnapshot, order_depth: OrderDepth, position: int, memory: Dict[str, Any]) -> Tuple[List[Order], int]:
        
        if book.mid_price is None:
            return [], 0

        mid = book.mid_price
        mid_smooth = self._smooth_mid(mid, memory)
        sigma = self._update_volatility(mid, memory)


        # ─-----------------------─ QUOTE PRICING -------------------------------

        reservation, half_spread = self._compute_as_quotes(mid_smooth, position, sigma, memory)

        bid_price = int(math.floor(reservation - half_spread))
        ask_price = int(math.ceil(reservation + half_spread))

        # Ensure we don't cross the book ---------- could be reviewed -----------
        if book.best_ask is not None:
            bid_price = min(bid_price, book.best_ask - 1)
        if book.best_bid is not None:
            ask_price = max(ask_price, book.best_bid + 1)
        if ask_price <= bid_price:
            ask_price = bid_price + 1

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)


        # ─--------------─ Taker orders, when edge is clear ---------------------

        # Track which prices we send as taker this tick so own_trades can be
        # classified next tick (fills arrive one tick later via state.own_trades).
        this_taker_buy_px: set = set()
        this_taker_sell_px: set = set()

        take_edge = float(self.params.get("take_edge", 0.5))
        for ask_p in sorted(order_depth.sell_orders):
            available = -order_depth.sell_orders[ask_p]
            if ask_p > reservation - take_edge or buy_cap <= 0:
                break
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                this_taker_buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume = order_depth.buy_orders[bid_p]
            if bid_p < reservation + take_edge or sell_cap <= 0:
                break
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                this_taker_sell_px.add(bid_p)
                sell_cap -= qty


        # ─--------------------─ Passive quoting ──------------------------------

        #  ORDER SIZING
        limit = self.position_limit()

        base_size = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base_size * (1 - position/limit)
        ask_size = base_size * (1 + position/limit)

        quote_buy = min(buy_cap, int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))

        # ─-----------─ Reduce quote -> keep capacity for takers ---------------------

        inv_ratio = abs(position) / float(limit) if limit else 0.0

        if inv_ratio >= 1 - float(self.params.get("pct_kept_for_takers", 0.2)):
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

        # ── Taker-fill classification and logging ────────────────────────────────
        # own_trades contains fills from LAST tick's orders; classify using the
        # taker prices we stored at the end of last tick.
        prev_taker_buy_px = set(memory.get("_taker_buy_px", []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        memory["_taker_buy_px"] = list(this_taker_buy_px)
        memory["_taker_sell_px"] = list(this_taker_sell_px)

        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY", trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                )

        # ── Quote snapshot (live only, suppressed during internal backtest) ──────
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "reservation": round(reservation, 2),
                "sigma": round(sigma, 6),
                "half_spread": round(half_spread, 6),
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (r := memory.get("reservation")) is not None:
            out["Reservation"] = r
        if (s := memory.get("sigma")) is not None:
            out["Sigma"] = s
        return out
