"""OptionMMBS — naive options market-maker using Black-Scholes fair value.

Per-tick flow:
  1. Read shared underlying spot (S) + current TTE from params / shared state
  2. Compute implied vol from our own option mid price
  3. Post bid/ask around BS_fair_value with configurable edge
  4. Aggressive take if market ask < BS_fair - take_edge (or bid > BS_fair + take_edge)

Design:
  - One instance per voucher (10 total). Each computes its own IV.
  - Shares a smile-fitting coordinator via a shared_memory dict (injected by
    harness or computed per-tick from a dict of per-strike IVs).
  - Bootstrap: first tick uses prior_vol (param). Subsequent ticks use the
    smile-predicted vol at this strike or the per-strike IV.

Params:
  strike                : option strike price K (required)
  tte_days_initial      : TTE at the first tick of the session (required)
  ticks_per_day         : how many ticks = 1 day for TTE decay (default 10000)
  prior_vol             : initial sigma guess before enough data (default 0.02)
  maker_edge            : ticks to post around BS fair (default 2)
  maker_size            : target size per quote (default 20)
  take_edge             : take when market px deviates this much from BS fair (default 3)
  take_size             : max qty per taker tick (default 40)
  use_smile             : if True, use smile-fitted sigma; else use own iv (default True)
  iv_ewma_alpha         : EWMA on per-strike iv for stability (default 0.3)
  sigma_floor           : floor for sigma (default 0.005 = 0.5% daily)
  sigma_cap             : cap for sigma (default 0.10 = 10% daily)
  position_limit        : option position limit (300 per IMC)

Shared coordination (optional; see option_coordinator.py):
  If memory contains "_shared" (a dict shared across products), this strategy
  writes its {K: iv} to "_shared['vev_iv'][K]" and reads the full smile coeffs
  from "_shared['vev_smile_coeffs']" if present. Caller can orchestrate.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_price, call_delta
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.strategies.base.base import BaseStrategy


class OptionMMBSStrategy(BaseStrategy):
    """Naive option MM quoting around BS fair value."""

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

        K = float(self.params["strike"])
        tte0 = float(self.params.get("tte_days_initial", 5.0))
        ticks_per_day = float(self.params.get("ticks_per_day", 10000.0))
        prior_vol = float(self.params.get("prior_vol", 0.02))
        maker_edge = int(self.params.get("maker_edge", 2))
        maker_size = int(self.params.get("maker_size", 20))
        take_edge = float(self.params.get("take_edge", 3.0))
        take_size = int(self.params.get("take_size", 40))
        use_smile = bool(self.params.get("use_smile", True))
        iv_ewma_alpha = float(self.params.get("iv_ewma_alpha", 0.3))
        sigma_floor = float(self.params.get("sigma_floor", 0.005))
        sigma_cap = float(self.params.get("sigma_cap", 0.10))
        enable_takers = bool(self.params.get("enable_takers", True))
        penny_improve_around_mkt = bool(self.params.get("penny_improve_around_mkt", False))
        limit = self.position_limit()

        # TTE decay: at ts=0 → tte0, linearly decreases at 1/ticks_per_day per tick
        ts = int(state.timestamp)
        T = max(0.01, tte0 - ts / ticks_per_day)

        # Underlying spot — read from shared memory set by coordinator, or fall
        # back to listing_info lookup
        shared = memory.get("_shared") or {}
        S = shared.get("underlying_spot")
        if S is None:
            # Fallback: look for underlying in state.order_depths
            underlying = self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT")
            u_od = state.order_depths.get(underlying)
            if u_od and u_od.buy_orders and u_od.sell_orders:
                ub = max(u_od.buy_orders.keys())
                ua = min(u_od.sell_orders.keys())
                S = 0.5 * (ub + ua)
        if S is None:
            return [], 0

        # Own mid price
        own_mid = 0.5 * (book.best_bid + book.best_ask)

        # Implied vol from own mid
        iv = call_implied_vol(own_mid, S, K, T, sigma_init=prior_vol)
        # EWMA smoothing of IV
        prev_iv = memory.get("_iv_ewma")
        if iv is not None and sigma_floor <= iv <= sigma_cap:
            if prev_iv is None:
                iv_smooth = iv
            else:
                iv_smooth = iv_ewma_alpha * iv + (1.0 - iv_ewma_alpha) * prev_iv
            memory["_iv_ewma"] = iv_smooth
        else:
            iv_smooth = prev_iv if prev_iv is not None else prior_vol

        # Share our IV for smile coordinator
        if "vev_iv" not in shared:
            shared["vev_iv"] = {}
        shared["vev_iv"][K] = iv_smooth

        # Choose sigma for pricing
        if use_smile:
            smile_coeffs = shared.get("vev_smile_coeffs")
            if smile_coeffs is None:
                # Fallback: self-compute smile from state.order_depths
                smile_coeffs = self._fit_smile_selfcontained(state, S, T, sigma_floor, sigma_cap, prior_vol)
            if smile_coeffs:
                sigma_use = smile_predict(K, smile_coeffs, S, T)
                sigma_use = max(sigma_floor, min(sigma_cap, sigma_use))
            else:
                sigma_use = iv_smooth
        else:
            sigma_use = iv_smooth

        # BS fair value
        fair = call_price(S, K, T, sigma_use)

        # Guard: skip quoting when option is near-worthless (fair < min_price)
        # Prevents nonsensical rounding for deep OTM options at mid~0.5
        min_quote_price = float(self.params.get("min_quote_price", 2.0))
        if fair < min_quote_price:
            memory["_bs_fair"] = fair
            memory["_sigma_use"] = sigma_use
            memory["_tte_days"] = T
            memory["_spot"] = S
            memory["_skipped"] = 1
            return [], 0

        # Skew fair toward inventory target 0 (linear bias)
        inv_bias = float(self.params.get("inv_bias_per_unit", 0.02))
        fair_skewed = fair - inv_bias * position

        # Log for diagnostics
        memory["_bs_fair"] = fair
        memory["_sigma_use"] = sigma_use
        memory["_tte_days"] = T
        memory["_spot"] = S

        # Quoting — two modes:
        #  (a) penny_improve_around_mkt: bid = best_bid+1, ask = best_ask-1 (classic MM)
        #      but skew sizing toward BS fair (fade if market is above fair, etc.)
        #  (b) default: quote around BS fair ± maker_edge (options-aware MM)
        if penny_improve_around_mkt:
            bid_px = book.best_bid + 1
            ask_px = book.best_ask - 1
        else:
            bid_px = int(round(fair_skewed - maker_edge))
            ask_px = int(round(fair_skewed + maker_edge))

        # Never cross own book
        if book.best_bid is not None and bid_px >= book.best_ask:
            bid_px = book.best_ask - 1
        if book.best_ask is not None and ask_px <= book.best_bid:
            ask_px = book.best_bid + 1
        # Floor at 1 for call options (no negative price)
        bid_px = max(1, bid_px)
        ask_px = max(bid_px + 1, ask_px)

        # Skip asymmetric quotes when edge is negative (bid > ask impossible after floor)
        # and skip crossing if our theoretical bid/ask cross best market
        if book.best_bid is not None and bid_px > book.best_ask:
            bid_px = -1  # signal skip
        if book.best_ask is not None and ask_px < book.best_bid:
            ask_px = -1  # signal skip

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        orders: List[Order] = []

        # Aggressive takers — fade large dislocations (opt-in)
        if enable_takers:
            if book.best_ask is not None and buy_cap > 0:
                edge_buy = fair_skewed - book.best_ask
                if edge_buy >= take_edge:
                    qty = -order_depth.sell_orders[book.best_ask]
                    take_qty = min(qty, buy_cap, take_size)
                    if take_qty > 0:
                        orders.append(Order(self.product, book.best_ask, take_qty))
                        buy_cap -= take_qty
            if book.best_bid is not None and sell_cap > 0:
                edge_sell = book.best_bid - fair_skewed
                if edge_sell >= take_edge:
                    qty = order_depth.buy_orders[book.best_bid]
                    take_qty = min(qty, sell_cap, take_size)
                    if take_qty > 0:
                        orders.append(Order(self.product, book.best_bid, -take_qty))
                        sell_cap -= take_qty

        # Passive maker quotes (skip if bid/ask prices are -1 = invalid)
        if buy_cap > 0 and bid_px > 0:
            orders.append(Order(self.product, bid_px, min(maker_size, buy_cap)))
        if sell_cap > 0 and ask_px > 0:
            orders.append(Order(self.product, ask_px, -min(maker_size, sell_cap)))

        return orders, 0

    def _fit_smile_selfcontained(
        self,
        state: TradingState,
        S: float,
        T: float,
        sigma_floor: float,
        sigma_cap: float,
        prior_vol: float,
    ):
        """Fit smile from all VEV_xxxx books in state.order_depths."""
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

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (f := memory.get("_bs_fair")) is not None:
            out["BS_fair"] = f
        if (s := memory.get("_sigma_use")) is not None:
            out["sigma"] = s * 100
        return out
