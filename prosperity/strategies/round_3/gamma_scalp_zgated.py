"""GammaScalpZGated — gamma_scalp + Tibo's VELVET z-score gate on entries.

Same accumulation thesis as `gamma_scalp` (BUY ATM calls when realized vol >
implied vol → long-gamma profit). New: ENTRY is gated by VELVET z-score.

Rationale (from Tibo's velvet_v3):
  When VELVET is "expensive" (z > +threshold), the underlying is over-extended
  → riskier moment to add long-vol exposure (option price has S-richness baked
  in, mean-reversion of S could hurt our long delta).
  When VELVET is "cheap" (z < -threshold), the underlying is over-sold → we
  want to BUY into the dip (option price has S-cheapness baked in, mean-revert
  to higher S helps our long delta).
  When neutral: standard gamma_scalp behavior.

Per-tick:
  1. Update rolling VELVET spot buffer (each strike maintains its own).
  2. Compute z = (S - mean) / std.
  3. If z > +z_skip_threshold AND skip_when_expensive=True: NO entries
     (no taker, no passive bid). Still allow exit/unwind.
  4. If z < -z_boost_threshold AND boost_when_cheap=True: scale entry sizes
     by entry_size_boost (e.g. 1.5x) to load up.
  5. Otherwise: standard gamma_scalp accumulation.

Params (additions to gamma_scalp params):
  zscore_window         : VELVET buffer length (default 500)
  zscore_skip_threshold : z > this → skip entries (default 1.0)
  zscore_boost_threshold: z < -this → boost entry size (default 1.0)
  skip_when_expensive   : enable expensive gate (default True)
  boost_when_cheap      : enable cheap boost (default False — already at IMC cap)
  entry_size_boost      : multiplier when boost fires (default 1.5)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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


class GammaScalpZGatedStrategy(BaseStrategy):
    """GammaScalp + VELVET z-score gating on entries (Tibo's idea)."""

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

        # Update VELVET spot buffer + compute z
        z = self._update_zscore(S, memory, p)
        memory["_velvet_z"] = z

        # Standard BS pricing (same as gamma_scalp)
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

        # Unwind mode (unchanged from gamma_scalp)
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

        # ── Z-GATE: skip entries when VELVET expensive ───────────────────────
        skip_entries = False
        if p["skip_when_expensive"] and z is not None and z > p["zscore_skip_threshold"]:
            skip_entries = True
            memory["_mode"] = "z_skipped_expensive"
        else:
            memory["_mode"] = "accumulate"

        if skip_entries:
            # No new bids; we still hold what we have (no auto-unwind)
            return orders, 0

        # ── Z-BOOST: scale entry size when VELVET cheap ──────────────────────
        size_mult = 1.0
        if p["boost_when_cheap"] and z is not None and z < -p["zscore_boost_threshold"]:
            size_mult = p["entry_size_boost"]
            memory["_mode"] = "z_boost_cheap"

        eff_entry_size = max(1, int(round(p["entry_size"] * size_mult)))
        eff_passive_size = max(1, int(round(p["passive_bid_size"] * size_mult)))

        # Standard accumulation (taker + passive bid)
        if buy_cap > 0 and position < p["target_qty"]:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty = -order_depth.sell_orders.get(ask, 0)
                headroom = p["target_qty"] - position
                take_qty = min(ask_qty, buy_cap, eff_entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty

        if buy_cap > 0 and position < p["target_qty"]:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(eff_passive_size, buy_cap, p["target_qty"] - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0

    # ── Z-score on VELVET spot, per-strike memory ────────────────────────────

    def _update_zscore(self, S: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Optional[float]:
        window = p["zscore_window"]
        buf: List[float] = memory.setdefault("_velvet_buf", [])
        buf.append(S)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (S - mean) / std

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
            # New z-gate params
            "zscore_window": int(params.get("zscore_window", 500)),
            "zscore_skip_threshold": float(params.get("zscore_skip_threshold", 1.0)),
            "zscore_boost_threshold": float(params.get("zscore_boost_threshold", 1.0)),
            "skip_when_expensive": bool(params.get("skip_when_expensive", True)),
            "boost_when_cheap": bool(params.get("boost_when_cheap", False)),
            "entry_size_boost": float(params.get("entry_size_boost", 1.5)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (g := memory.get("_gamma")) is not None: out["gamma"] = g
        if (d := memory.get("_delta")) is not None: out["delta"] = d
        if (f := memory.get("_fair_iv")) is not None: out["fair_iv"] = f
        if (z := memory.get("_velvet_z")) is not None: out["velvet_z"] = z
        if (m := memory.get("_mode")) is not None:
            out["mode"] = {"accumulate": 1.0, "unwind": 0.0,
                           "z_skipped_expensive": -1.0, "z_boost_cheap": 2.0}.get(m, 0.5)
        return out
