"""VolHarvest — systematically BUY options when market IV < realized vol prior.

Thesis (Round 3 specific):
  Realized vol of VELVETFRUIT_EXTRACT = 2.15%/day.
  Implied vol from ATM options ≈ 1.25%/day.
  → 70% mispricing: options are structurally cheap vs actual move distribution.
  → Long vol = buy calls at market ask whenever BS(market) < BS(realized_vol).
  → Delta-hedge via underlying (`velvet_delta_hedger` reads positions from coordinator).

Per-tick flow:
  1. Read underlying spot + smile from coordinator (cached).
  2. Compute BS fair price at *realized-vol prior* (config param, not smile).
  3. If market ask < BS_realized_fair - entry_edge → BUY at ask (aggressive).
  4. Post passive bid one tick inside the book for additional accumulation.
  5. If position ≥ target_position, stop adding (hold vol exposure).
  6. If market bid > BS_realized_fair + exit_edge → SELL aggressively (rare).

Design notes:
  - `entry_edge` in TICKS of option price (default 1) → we require the market
    to be at least 1 tick below our realized-vol fair estimate.
  - `target_position` caps how much we accumulate per strike (default 40).
  - `strikes_enabled` lets us focus on high-vega strikes (ATM-ish 5000-5500).
  - Deep OTM (VEV_6000/6500) skipped by default (near-zero fair → noise).

Params:
  strike                : option strike K (required)
  tte_days_initial      : TTE at session start (default 5.0)
  timestamp_units_per_day : for TTE decay (default 1_000_000)
  historical_tte_by_day : e.g. {0:8, 1:7, 2:6}
  realized_vol_prior    : daily vol we use for fair (default 0.0215 = 2.15%)
  entry_edge            : ticks below BS fair to trigger a BUY (default 1.0)
  exit_edge             : ticks above BS fair to trigger a SELL (default 2.0)
  target_position       : max long position per strike (default 40)
  entry_size            : max qty per buy trigger (default 10)
  exit_size             : max qty per sell trigger (default 20)
  passive_bid_size      : qty on passive bid at best_bid+1 (default 5)
  post_passive          : whether to post passive bid (default True)
  min_quote_price       : skip if BS fair < this (default 2.0)
  underlying_symbol     : "VELVETFRUIT_EXTRACT"
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_price
from prosperity.options.coordinator import get_spot, publish_position
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


class VolHarvestStrategy(BaseStrategy):
    """Long-vol harvester: buy calls when market < BS at realized_vol prior."""

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

        fair = call_price(S, p["K"], p["T"], p["realized_vol_prior"])
        memory["_bs_fair_rv"] = fair
        memory["_spot"] = S
        memory["_T"] = p["T"]

        if fair < p["min_quote_price"]:
            return [], 0

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # 1. Aggressive BUY when market ask < fair - entry_edge, up to target position
        if buy_cap > 0 and position < p["target_position"]:
            ask = book.best_ask
            if ask is not None and (fair - ask) >= p["entry_edge"]:
                ask_qty = -order_depth.sell_orders.get(ask, 0)
                headroom = p["target_position"] - position
                take_qty = min(ask_qty, buy_cap, p["entry_size"], headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty

        # 2. Aggressive SELL when market bid > fair + exit_edge (profit take or trim long)
        if sell_cap > 0 and position > 0:
            bid = book.best_bid
            if bid is not None and (bid - fair) >= p["exit_edge"]:
                bid_qty = order_depth.buy_orders.get(bid, 0)
                take_qty = min(bid_qty, sell_cap, p["exit_size"], position)
                if take_qty > 0:
                    orders.append(Order(self.product, bid, -take_qty))
                    sell_cap -= take_qty

        # 3. Passive bid one inside the book to accumulate cheaply
        if p["post_passive"] and buy_cap > 0 and position < p["target_position"]:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(p["passive_bid_size"], buy_cap, p["target_position"] - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0

    # ── Param loading ────────────────────────────────────────────────────────

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
            "realized_vol_prior": float(params.get("realized_vol_prior", 0.0215)),
            "entry_edge": float(params.get("entry_edge", 1.0)),
            "exit_edge": float(params.get("exit_edge", 2.0)),
            "target_position": int(params.get("target_position", 40)),
            "entry_size": int(params.get("entry_size", 10)),
            "exit_size": int(params.get("exit_size", 20)),
            "passive_bid_size": int(params.get("passive_bid_size", 5)),
            "post_passive": bool(params.get("post_passive", True)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "underlying_symbol": params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (f := memory.get("_bs_fair_rv")) is not None:
            out["BS_fair_realized"] = f
        if (S := memory.get("_spot")) is not None:
            out["S"] = S
        return out
