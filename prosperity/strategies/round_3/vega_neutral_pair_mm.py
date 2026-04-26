"""VegaNeutralPairMM — long-ATM + short-other-ATM with vega-neutralized ratio.

Thesis (Rook-E1 inspired): if there's a SYSTEMATIC IV difference between two
strikes with similar vega, capture the spread without taking vol level risk.

Per-tick:
  1. Compute spot S, TTE T, sigma per strike.
  2. Compute vega per strike using BS at the strike's own implied vol.
  3. Determine pair ratio: long_size / short_size = vega_short / vega_long
     (so total vega ≈ 0).
  4. Long the cheaper-IV strike, short the richer-IV strike.

For Round 3:
  - K=5200 / K=5300: similar vegas (~5500 each), IVs ~0.199 / 0.199.
  - K=5100 / K=5500: vegas 4071 / 2405, IVs 0.203 / 0.205.

The strategy posts:
  - Bid at penny-improve on the cheaper-IV strike (target_long)
  - Ask at penny-improve on the richer-IV strike (target_short, sized by ratio)

Risk: SAME directional risk as v11 if our long ≠ vega-balanced short. But the
vega cancels so we don't directly bet on vol level — only on the IV-pair gap.

Note: this strategy is run on EACH leg separately (long_strike and short_strike
are config params). The pair logic is naturally distributed.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_vega
from prosperity.options.coordinator import get_spot, publish_position
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


class VegaNeutralPairMMStrategy(BaseStrategy):
    """One leg of a vega-neutral pair: this strike trades long OR short with
    sizes scaled to neutralize total vega vs the partner strike."""

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

        # Compute IVs for this strike + partner
        own_iv = self._iv_for_strike(state, S, p["K"], p["T"], p["prior_vol"])
        partner_iv = self._iv_for_strike(state, S, p["partner_K"], p["T"], p["prior_vol"])
        if own_iv is None or partner_iv is None:
            return [], 0

        # Vegas
        own_vega = call_vega(S, p["K"], p["T"], own_iv)
        partner_vega = call_vega(S, p["partner_K"], p["T"], partner_iv)
        if own_vega <= 0 or partner_vega <= 0:
            return [], 0

        memory["_own_iv"] = own_iv
        memory["_partner_iv"] = partner_iv
        memory["_own_vega"] = own_vega
        memory["_partner_vega"] = partner_vega
        memory["_iv_diff"] = own_iv - partner_iv

        # Decide our role: long if our IV is lower (cheaper); short if higher
        we_are_long = own_iv < partner_iv

        # Vega-neutral size: long_size * own_vega = short_size * partner_vega
        # If we_are_long: we hold long, sized so long_vega = partner_short_vega
        #   our_size / partner_size = partner_vega / own_vega
        # We don't know partner_size at runtime — use config base size + ratio.
        base_size = p["base_size"]
        if we_are_long:
            target_size = base_size  # long is the reference unit
            our_target = base_size
        else:
            # Short side: scaled so our short vega = base_size * partner_vega
            # Per-unit-share: our_size = base_size * partner_vega / own_vega
            our_target = max(1, int(round(base_size * partner_vega / own_vega)))

        memory["_we_are_long"] = we_are_long
        memory["_our_target"] = our_target

        # Pair-trade gate: only act if IV gap above threshold
        if abs(own_iv - partner_iv) < p["iv_gap_threshold"]:
            return [], 0

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if we_are_long:
            # We want LONG. Build position toward our_target via passive bid.
            if position < our_target and buy_cap > 0:
                bid_px = book.best_bid + 1
                if bid_px >= book.best_ask:
                    bid_px = book.best_bid
                qty = min(p["maker_size"], buy_cap, our_target - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))
            # Exit longs when IV gap closes
            if position > 0 and abs(own_iv - partner_iv) < p["exit_threshold"] and sell_cap > 0:
                ask_px = book.best_ask - 1
                if ask_px <= book.best_bid:
                    ask_px = book.best_bid + 1
                orders.append(Order(self.product, ask_px, -min(p["exit_size"], sell_cap, position)))
        else:
            # We want SHORT. Build short position via passive ask.
            target_short = -our_target
            if position > target_short and sell_cap > 0:
                ask_px = book.best_ask - 1
                if ask_px <= book.best_bid:
                    ask_px = book.best_bid + 1
                qty = min(p["maker_size"], sell_cap, position - target_short)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))
            if position < 0 and abs(own_iv - partner_iv) < p["exit_threshold"] and buy_cap > 0:
                bid_px = book.best_bid + 1
                if bid_px >= book.best_ask:
                    bid_px = book.best_bid
                orders.append(Order(self.product, bid_px, min(p["exit_size"], buy_cap, -position)))

        return orders, 0

    def _iv_for_strike(self, state: TradingState, S: float, K: float, T: float, prior: float) -> Optional[float]:
        od = state.order_depths.get(f"VEV_{int(K)}")
        if od is None or not od.buy_orders or not od.sell_orders:
            return None
        bid = max(od.buy_orders); ask = min(od.sell_orders)
        mid = 0.5 * (bid + ask)
        return call_implied_vol(mid, S, K, T, sigma_init=prior)

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
            "partner_K": float(params["partner_strike"]),
            "T": max(0.01, T),
            "underlying_symbol": str(params.get("underlying_symbol", "VELVETFRUIT_EXTRACT")),
            "prior_vol": float(params.get("prior_vol", 0.0125)),
            "base_size": int(params.get("base_size", 50)),
            "maker_size": int(params.get("maker_size", 10)),
            "exit_size": int(params.get("exit_size", 10)),
            "iv_gap_threshold": float(params.get("iv_gap_threshold", 0.0005)),
            "exit_threshold": float(params.get("exit_threshold", 0.0001)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if (v := memory.get("_own_iv")) is not None: out["own_iv"] = v
        if (v := memory.get("_partner_iv")) is not None: out["partner_iv"] = v
        if (v := memory.get("_iv_diff")) is not None: out["iv_diff_bp"] = v * 1e4
        if (v := memory.get("_own_vega")) is not None: out["own_vega"] = v
        if (v := memory.get("_we_are_long")) is not None: out["is_long"] = 1.0 if v else -1.0
        return out
