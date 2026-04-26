"""GammaScalp — long gamma position via ATM options + continuous delta hedging.

Thesis (Round 3 specific):
  Roll-corrected realized daily vol ≈ 1.76-1.88% on VELVETFRUIT.
  Implied vol (ATM strikes 5000-5300) ≈ 1.22% daily.
  Gap: ~45% under-pricing of options.

  Long gamma captures this: holding a call option + delta-hedging via the
  underlying creates a P&L ≈ 0.5 * gamma * (ΔS)² summed over the hedging
  interval. If market realizes more vol than implied, we profit. Theta is
  the cost (premium decay).

  Net expected P&L per tick:
    dPnL ≈ 0.5 * gamma * (ΔS)² - theta * dt
         = 0.5 * gamma * σ_realized² * S² * dt - theta * dt
         = (σ_realized² - σ_implied²) / 2 * gamma * S² * dt
    So if σ_realized > σ_implied → positive expected P&L.

Design:
  - Build position in ATM strikes by taking market asks slightly above our
    reservation BS price. Stop once target_vega is reached.
  - Hedge delta continuously via VELVETFRUIT: this is delegated to the existing
    `velvet_delta_hedger` which reads our option positions from the coordinator.
  - Unwind if gamma pay-off has exceeded a target (lock in profit) OR if
    time decay accelerates near expiry (TTE < 1.5 day).

Per-tick flow:
  1. Read underlying spot + TTE
  2. Publish position
  3. Compute reservation BS price using IMPLIED vol (conservative, near
     market price) — we want to enter when market ask is close to our fair.
  4. If position < target_qty AND market ask ≤ BS_reservation + edge_ticks:
       BUY at market ask (scale up gradually, entry_size per tick)
  5. If TTE_days < unwind_tte_threshold OR position hits max:
       SELL passively at best_bid+1 to unwind.
  6. Otherwise: passive pose at best_bid+1 (cheap accumulation), no takers.

Params:
  strike                : option K (required)
  tte_days_initial / timestamp_units_per_day / historical_tte_by_day
  implied_vol_prior     : our best IV estimate for pricing (default 0.0125)
  edge_ticks            : how far above BS fair we're willing to pay (default 0.0)
  target_qty            : max long position per strike (default 100)
  entry_size            : qty per taker tick (default 10)
  passive_bid_size      : qty on passive bid (default 10)
  unwind_tte_threshold  : start unwinding below this TTE (default 1.5 days)
  min_quote_price       : skip if BS fair < this (default 2.0)
  underlying_symbol     : "VELVETFRUIT_EXTRACT"
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_delta, call_gamma, call_price
from prosperity.options.coordinator import get_spot, publish_position
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


class GammaScalpStrategy(BaseStrategy):
    """Accumulate long-gamma position via ATM options; hedger offsets delta."""

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

        # BS fair at implied vol (reservation price — we want to buy at or below)
        fair = call_price(S, p["K"], p["T"], p["implied_vol_prior"])
        gamma = call_gamma(S, p["K"], p["T"], p["implied_vol_prior"])
        delta = call_delta(S, p["K"], p["T"], p["implied_vol_prior"])
        memory["_gamma"] = gamma
        memory["_delta"] = delta
        memory["_fair_iv"] = fair
        memory["_spot"] = S
        memory["_T"] = p["T"]

        if fair < p["min_quote_price"]:
            return [], 0

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Unwinding mode: TTE too short or position at max → sell passively
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

        memory["_mode"] = "accumulate"

        # Accumulation mode — takers when market ask ≤ fair + edge
        if buy_cap > 0 and position < p["target_qty"]:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty = -order_depth.sell_orders.get(ask, 0)
                headroom = p["target_qty"] - position
                take_qty = min(ask_qty, buy_cap, p["entry_size"], headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty

        # Passive bid one inside the book for cheap accumulation
        if buy_cap > 0 and position < p["target_qty"]:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(p["passive_bid_size"], buy_cap, p["target_qty"] - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0

    def _read_params(self, state: TradingState) -> Dict[str, Any]:
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
            "T": max(0.01, T),
            "implied_vol_prior": float(params.get("implied_vol_prior", 0.0125)),
            "edge_ticks": float(params.get("edge_ticks", 0.0)),
            "target_qty": int(params.get("target_qty", 100)),
            "entry_size": int(params.get("entry_size", 10)),
            "passive_bid_size": int(params.get("passive_bid_size", 10)),
            "unwind_tte_threshold": float(params.get("unwind_tte_threshold", 1.5)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "underlying_symbol": params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (g := memory.get("_gamma")) is not None:
            out["gamma"] = g
        if (d := memory.get("_delta")) is not None:
            out["delta"] = d
        if (f := memory.get("_fair_iv")) is not None:
            out["fair_iv"] = f
        if (m := memory.get("_mode")) is not None:
            out["mode"] = {"accumulate": 1.0, "unwind": 0.0}.get(m, 0.5)
        return out
