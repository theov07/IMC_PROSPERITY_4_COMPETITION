"""VelvetDeltaHedger — MM on VELVETFRUIT_EXTRACT with option delta overlay.

This strategy layers on top of a standard book-following MM for the underlying.
On each tick it:
  1. Reads published option positions from `prosperity.options.coordinator`.
  2. Computes portfolio delta using the smile cached by the coordinator.
  3. Adjusts the underlying quotes (or emits a taker order) to move the net
     delta toward zero.

Why ``after`` an MM cycle?
  We don't want to replace the existing spread capture with purely hedging
  trades. The MM already posts tight bid/ask; we just shift sizes or post an
  extra hedge order so the *aggregate* position targets delta_neutral.

Design:
  - Hedging happens via a **taker** order when the delta imbalance exceeds
    `hedge_taker_edge` × 1 tick (move now, can't wait).
  - Otherwise we bias our passive MM sizes: if long delta, post a bigger ask
    (sell more) and a smaller bid (buy less).

Params:
  underlying_symbol       : "VELVETFRUIT_EXTRACT" (used as self.product implicitly)
  hedge_strikes           : list of option strikes to poll (default R3 VEV set)
  strike_prefix           : "VEV_" (default)
  tte_days_initial        : TTE at session start (needed for greeks)
  timestamp_units_per_day : for TTE decay
  historical_tte_by_day   : optional backtest override
  target_delta            : delta we want to maintain (default 0)
  hedge_taker_edge        : delta imbalance threshold to fire a taker (default 15)
  max_hedge_size          : max qty per hedge taker tick (default 30)
  passive_base_size       : base size on each side of MM quotes (default 30)
  passive_skew_per_delta  : per-unit delta skew applied to passive sizes (default 0.3)
  quote_inside_book       : True = penny-improve; False = join at best (default True)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.coordinator import (
    get_smile,
    get_spot,
    publish_position,
    get_positions,
)
from prosperity.options.hedging import portfolio_greeks, recommend_delta_hedge
from prosperity.options.smile import smile_predict
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy

_DEFAULT_VEV_STRIKES: List[int] = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


class VelvetDeltaHedgerStrategy(BaseStrategy):
    """MM on the underlying with option delta offset."""

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

        # Publish our own position for the coordinator (so option strategies can
        # see our hedge inventory if they ever want to cross-reference).
        publish_position(ts, self.product, position)

        # 1. Compute option portfolio delta from coordinator-published positions.
        portfolio_delta = self._compute_portfolio_delta(state, p, ts)
        memory["_option_delta"] = portfolio_delta

        # 2. Decide whether to hedge now (taker) or bias passive quotes.
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        imbalance = portfolio_delta + position  # total net delta including our hedge
        hedge_taker = self._maybe_taker_hedge(
            imbalance=imbalance,
            book=book,
            order_depth=order_depth,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            params=p,
            position=position,
            memory=memory,
            ts=ts,
        )
        if hedge_taker is not None:
            orders.append(hedge_taker)
            memory["_last_hedge_ts"] = ts
            if hedge_taker.quantity > 0:
                buy_cap -= hedge_taker.quantity
            else:
                sell_cap -= -hedge_taker.quantity

        # 3. Passive MM quotes with delta-skewed sizes.
        passive = self._post_passive_biased(
            book=book,
            portfolio_delta=portfolio_delta + position,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            params=p,
        )
        orders.extend(passive)

        memory["_net_delta_after_hedge"] = portfolio_delta + position
        return orders, 0

    # ── Params ───────────────────────────────────────────────────────────────

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
            "tte0": tte0,
            "T": max(0.01, T),
            "underlying_symbol": params.get("underlying_symbol", self.product),
            "hedge_strikes": list(params.get("hedge_strikes") or _DEFAULT_VEV_STRIKES),
            "strike_prefix": str(params.get("strike_prefix", "VEV_")),
            "target_delta": float(params.get("target_delta", 0.0)),
            "hedge_taker_edge": float(params.get("hedge_taker_edge", 15.0)),
            "max_hedge_size": int(params.get("max_hedge_size", 30)),
            "passive_base_size": int(params.get("passive_base_size", 30)),
            "passive_skew_per_delta": float(params.get("passive_skew_per_delta", 0.3)),
            "quote_inside_book": bool(params.get("quote_inside_book", True)),
            "sigma_floor": float(params.get("sigma_floor", 0.005)),
            "sigma_cap": float(params.get("sigma_cap", 0.10)),
            "prior_vol": float(params.get("prior_vol", 0.02)),
        }

    # ── Option portfolio delta ───────────────────────────────────────────────

    def _compute_portfolio_delta(
        self, state: TradingState, params: Dict[str, Any], ts: int,
    ) -> float:
        """Read published option positions and compute delta using smile sigma."""
        # Use the authoritative start-of-tick positions first.  The coordinator
        # publication is still useful for older local experiments, but relying
        # on it alone makes the hedge depend on product iteration order.
        positions = dict(getattr(state, "position", {}) or {})
        positions.update(get_positions(ts))
        # Keep only option products (by prefix).
        prefix = params["strike_prefix"]
        option_positions: List[Tuple[float, int]] = []
        for product, qty in positions.items():
            if not product.startswith(prefix):
                continue
            try:
                K = float(product.replace(prefix, ""))
            except ValueError:
                continue
            option_positions.append((K, qty))

        if not option_positions:
            return 0.0

        S = get_spot(state, underlying=params["underlying_symbol"])
        if S is None:
            return 0.0
        T = params["T"]

        smile = get_smile(
            state,
            strikes=params["hedge_strikes"],
            strike_prefix=params["strike_prefix"],
            S=S,
            T=T,
            sigma_floor=params["sigma_floor"],
            sigma_cap=params["sigma_cap"],
            prior_vol=params["prior_vol"],
        )
        if smile is None:
            sigma_fn = lambda K: params["prior_vol"]  # noqa: E731
        else:
            def sigma_fn(K: float) -> float:
                s = smile_predict(K, smile, S, T)
                return max(params["sigma_floor"], min(params["sigma_cap"], s))

        g = portfolio_greeks(option_positions, S, T, sigma_fn)
        return g["delta"]

    # ── Taker hedge ──────────────────────────────────────────────────────────

    def _maybe_taker_hedge(
        self,
        *,
        imbalance: float,
        book: BookSnapshot,
        order_depth: OrderDepth,
        buy_cap: int,
        sell_cap: int,
        params: Dict[str, Any],
        position: int,
        memory: Optional[Dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> Optional[Order]:
        """Fire a taker order if |imbalance| > hedge_taker_edge.
        Optionally enforce min_ticks_between_hedges throttle."""
        if abs(imbalance) < params["hedge_taker_edge"]:
            return None
        # Throttle: only allow taker if enough ticks since last hedge
        min_gap_ts = params.get("min_ticks_between_hedges", 0) * 100
        if min_gap_ts > 0 and memory is not None and ts is not None:
            last_hedge_ts = memory.get("_last_hedge_ts", -10**9)
            if ts - last_hedge_ts < min_gap_ts:
                return None
        trade_qty = recommend_delta_hedge(
            current_underlying_pos=position,
            option_portfolio_delta=imbalance - position,  # option delta only
            target_delta=params["target_delta"],
            position_limit=self.position_limit(),
            max_trade_size=params["max_hedge_size"],
        )
        if trade_qty == 0:
            return None
        if trade_qty > 0:
            if buy_cap <= 0 or book.best_ask is None:
                return None
            qty = min(trade_qty, buy_cap, -order_depth.sell_orders.get(book.best_ask, 0))
            if qty <= 0:
                return None
            return Order(self.product, book.best_ask, qty)
        else:
            if sell_cap <= 0 or book.best_bid is None:
                return None
            qty = min(-trade_qty, sell_cap, order_depth.buy_orders.get(book.best_bid, 0))
            if qty <= 0:
                return None
            return Order(self.product, book.best_bid, -qty)

    # ── Passive MM quotes with delta bias ────────────────────────────────────

    def _post_passive_biased(
        self,
        *,
        book: BookSnapshot,
        portfolio_delta: float,
        buy_cap: int,
        sell_cap: int,
        params: Dict[str, Any],
    ) -> List[Order]:
        """Post one passive bid + ask, biased by current net delta.

        If we're long delta (>0), shrink bid size / grow ask size (sell more).
        If we're short delta, do the opposite.
        """
        if params["quote_inside_book"]:
            bid_px = book.best_bid + 1
            ask_px = book.best_ask - 1
        else:
            bid_px = book.best_bid
            ask_px = book.best_ask
        # Never cross
        if bid_px >= book.best_ask:
            bid_px = book.best_ask - 1
        if ask_px <= book.best_bid:
            ask_px = book.best_bid + 1

        base = params["passive_base_size"]
        skew = params["passive_skew_per_delta"] * portfolio_delta
        bid_size = max(0, int(round(base - skew)))
        ask_size = max(0, int(round(base + skew)))

        orders: List[Order] = []
        bq = min(bid_size, buy_cap)
        if bq > 0:
            orders.append(Order(self.product, bid_px, bq))
        aq = min(ask_size, sell_cap)
        if aq > 0:
            orders.append(Order(self.product, ask_px, -aq))
        return orders

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (d := memory.get("_option_delta")) is not None:
            out["option_delta"] = float(d)
        if (nd := memory.get("_net_delta_after_hedge")) is not None:
            out["net_delta"] = float(nd)
        return out
