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
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy

_DEFAULT_VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


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

        # ── IV residual gate (NEW v32) — passive momentum exploitation ──────
        # If iv_residual_gate enabled: compute LOO-smile residual + EWMA delta.
        # When residual is decreasing rapidly (option getting cheaper momentum),
        # SKIP entries — same direction as VELVET overbought but for IV signal.
        # When residual is increasing (rich getting richer), BOOST entry size.
        if p["iv_residual_gate"]:
            iv_resid, iv_resid_delta = self._update_iv_residual(state, book, S, p, memory)
            memory["_iv_resid"] = iv_resid
            memory["_iv_resid_delta"] = iv_resid_delta
            if iv_resid is not None and iv_resid_delta is not None:
                # Skip when residual is cheap AND getting cheaper (price falling momentum)
                if iv_resid < -p["iv_skip_threshold"] and iv_resid_delta < -p["iv_delta_threshold"]:
                    memory["_mode"] = "iv_skip_falling"
                    return [], 0
                # Boost size when residual is rich AND getting richer (price rising momentum)
                if iv_resid > p["iv_boost_threshold"] and iv_resid_delta > p["iv_delta_threshold"]:
                    memory["_iv_boost"] = True
                else:
                    memory["_iv_boost"] = False

        # ── Z-PROFIT-TAKE: actively sell longs when VELVET very expensive ────
        # Tibo-inspired: lock in directional gains at the peak instead of
        # waiting for TTE-based unwind. Only fires when |z| above sell threshold.
        if (p["sell_when_very_expensive"] and z is not None
                and z > p["zscore_sell_threshold"] and position > 0
                and sell_cap > 0):
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            sell_qty = max(1, int(round(position * p["sell_size_pct"])))
            qty = min(sell_qty, sell_cap, position, p["passive_bid_size"])
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
                sell_cap -= qty
            memory["_mode"] = "z_profit_take"
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

        # Apply IV momentum boost (passive, no taker)
        if memory.get("_iv_boost", False):
            eff_passive_size = int(round(eff_passive_size * p["iv_passive_boost"]))

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

    def _update_iv_residual(self, state, book, S, p, memory):
        """Compute IV residual = own_iv - LOO-smile-predicted iv. Track EWMA delta."""
        own_mid = 0.5 * (book.best_bid + book.best_ask)
        own_iv = call_implied_vol(own_mid, S, p["K"], p["T"], sigma_init=p["implied_vol_prior"])
        if own_iv is None:
            return None, None
        # LOO smile fit
        ks, ivs = [], []
        for strike in _DEFAULT_VEV_STRIKES:
            if float(strike) == p["K"]:
                continue
            od = state.order_depths.get(f"VEV_{strike}")
            if not od or not od.buy_orders or not od.sell_orders:
                continue
            bid = max(od.buy_orders); ask = min(od.sell_orders)
            mid = 0.5 * (bid + ask)
            iv = call_implied_vol(mid, S, float(strike), p["T"], sigma_init=p["implied_vol_prior"])
            if iv is None or iv < 0.005 or iv > 0.10: continue
            ks.append(float(strike)); ivs.append(iv)
        if len(ks) < 3:
            return None, None
        coeffs = fit_smile_poly(ks, ivs, S, p["T"], degree=2)
        if coeffs is None:
            return None, None
        loo_iv = smile_predict(p["K"], coeffs, S, p["T"])
        residual = own_iv - loo_iv
        # EWMA on residual
        slow = memory.get("_iv_resid_slow")
        fast = memory.get("_iv_resid_fast")
        if slow is None:
            slow = residual; fast = residual
        else:
            slow = (1 - p["iv_ewma_slow_alpha"]) * slow + p["iv_ewma_slow_alpha"] * residual
            fast = (1 - p["iv_ewma_fast_alpha"]) * fast + p["iv_ewma_fast_alpha"] * residual
        memory["_iv_resid_slow"] = slow
        memory["_iv_resid_fast"] = fast
        delta = fast - slow
        return residual, delta

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
            # Profit-take when very expensive (asymmetric ASK timing à la Tibo)
            "sell_when_very_expensive": bool(params.get("sell_when_very_expensive", False)),
            "zscore_sell_threshold": float(params.get("zscore_sell_threshold", 1.5)),
            "sell_size_pct": float(params.get("sell_size_pct", 0.10)),
            # IV residual gate (NEW v32 — passive momentum exploitation)
            "iv_residual_gate": bool(params.get("iv_residual_gate", False)),
            "iv_skip_threshold": float(params.get("iv_skip_threshold", 0.0010)),
            "iv_boost_threshold": float(params.get("iv_boost_threshold", 0.0010)),
            "iv_delta_threshold": float(params.get("iv_delta_threshold", 0.0003)),
            "iv_ewma_fast_alpha": float(params.get("iv_ewma_fast_alpha", 0.10)),
            "iv_ewma_slow_alpha": float(params.get("iv_ewma_slow_alpha", 0.02)),
            "iv_passive_boost": float(params.get("iv_passive_boost", 1.5)),
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
