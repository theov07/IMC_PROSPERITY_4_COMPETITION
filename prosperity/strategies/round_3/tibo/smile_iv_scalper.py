"""_VelvetOptionMixin and SmileIVScalerStrategy — smile-based IV scalper.

Ported and adapted from Theo's velvettuned_v6.py.

Core idea:
  1. Each tick, compute implied vol for every live VEV strike from market mids.
  2. Fit a polynomial smile (LOO: leave-one-out cross-validation per strike).
  3. Compute residual = market_iv - fair_iv.
  4. Track EWMA baseline of residual (mean + variance) → z-score.
  5. BUY aggressively when option is cheap vs smile (resid_z <= -take_zscore).
  6. SELL when IV mean-reverts (resid_z >= reduce_zscore or price edge met).
  7. PASSIVE MAKER around smile-adjusted reference price.

Strategy is "active" only for the N closest-to-spot strikes (configurable).
When a strike becomes inactive (too far OTM), it force-unwinds.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_delta, call_gamma, call_price
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


class _VelvetOptionMixin:
    """Shared option helpers: spot caching, IV chain snapshot, LOO smile fit.

    Uses memory["_shared"] (injected by Trader.run()) for cross-product caching:
    - velvet_spot: computed once per tick for all option strategies
    - vev_chain:   IV for all strikes, also computed once per tick
    - vev_chain_loo: per-strike LOO fair IV, also cached per tick

    Falls back gracefully if _shared is not injected (stores in local memory).
    """

    def _shared(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        shared = memory.get("_shared")
        if not isinstance(shared, dict):
            shared = {}
            memory["_shared"] = shared
        return shared

    def _option_strike(self, symbol: Optional[str] = None) -> Optional[int]:
        raw = symbol or self.product  # type: ignore[attr-defined]
        if not raw.startswith("VEV_"):
            return None
        try:
            return int(raw.replace("VEV_", ""))
        except ValueError:
            return None

    def _resolve_tte(self, state: TradingState) -> Tuple[float, float]:
        params = self.params  # type: ignore[attr-defined]
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(params.get("tte_days_initial", 5.0)),
            params.get("historical_tte_by_day"),
        )
        ts_per_day = timestamp_units_per_day_from_params(params)
        T = time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_per_day)
        return tte0, max(0.01, T)

    def _resolve_spot(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        ts: int,
    ) -> Optional[float]:
        shared = self._shared(memory)
        if shared.get("velvet_spot_ts") == ts:
            return shared.get("velvet_spot")
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))  # type: ignore[attr-defined]
        od = state.order_depths.get(underlying)
        if not od or not od.buy_orders or not od.sell_orders:
            return None
        spot = 0.5 * (max(od.buy_orders) + min(od.sell_orders))
        shared["velvet_spot_ts"] = ts
        shared["velvet_spot"] = spot
        return spot

    def _build_chain_snapshot(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        S: float,
        T: float,
        ts: int,
    ) -> Dict[int, Dict[str, Any]]:
        """Compute IV for all live VEV strikes; cached once per tick in shared."""
        shared = self._shared(memory)
        if shared.get("vev_chain_ts") == ts:
            cached = shared.get("vev_chain")
            if isinstance(cached, dict):
                return cached
        params = self.params  # type: ignore[attr-defined]
        prior = float(params.get("prior_vol", params.get("implied_vol_prior", 0.0125)))
        sigma_floor = float(params.get("sigma_floor", 0.005))
        sigma_cap = float(params.get("sigma_cap", 0.10))
        chain: Dict[int, Dict[str, Any]] = {}
        for symbol, od in state.order_depths.items():
            strike = self._option_strike(symbol)
            if strike is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = 0.5 * (best_bid + best_ask)
            iv = call_implied_vol(mid, S, float(strike), T, sigma_init=prior)
            iv_valid: Optional[float] = (
                float(iv) if iv is not None and sigma_floor <= iv <= sigma_cap else None
            )
            chain[strike] = {
                "best_bid": float(best_bid),
                "best_ask": float(best_ask),
                "mid": float(mid),
                "iv": iv_valid,
            }
        shared["vev_chain_ts"] = ts
        shared["vev_chain"] = chain
        shared["vev_chain_loo_ts"] = None
        shared["vev_chain_loo"] = {}
        return chain

    def _fit_leave_one_out_iv(
        self,
        memory: Dict[str, Any],
        *,
        strike: int,
        chain: Dict[int, Dict[str, Any]],
        S: float,
        T: float,
        ts: int,
    ) -> Optional[float]:
        """Leave-one-out smile fit: predict fair IV for `strike` using all other strikes."""
        shared = self._shared(memory)
        if shared.get("vev_chain_loo_ts") != ts:
            shared["vev_chain_loo_ts"] = ts
            shared["vev_chain_loo"] = {}
        cache = shared.setdefault("vev_chain_loo", {})
        if strike in cache:
            return cache[strike]
        params = self.params  # type: ignore[attr-defined]
        smile_degree = int(params.get("smile_degree", 2))
        min_points = int(params.get("smile_min_points", 4))
        prior = float(params.get("prior_vol", params.get("implied_vol_prior", 0.0125)))
        sigma_floor = float(params.get("sigma_floor", 0.005))
        sigma_cap = float(params.get("sigma_cap", 0.10))
        strikes_list: List[float] = []
        vols_list: List[float] = []
        for other_strike, row in chain.items():
            if other_strike == strike:
                continue
            iv = row.get("iv")
            if iv is None:
                continue
            strikes_list.append(float(other_strike))
            vols_list.append(float(iv))
        fair_iv: Optional[float] = None
        if len(strikes_list) >= max(min_points, smile_degree + 1):
            coeffs = fit_smile_poly(strikes_list, vols_list, S, T, degree=smile_degree, min_points=min_points)
            if coeffs is not None:
                fair_iv = smile_predict(float(strike), coeffs, S, T)
        if fair_iv is None:
            own_iv = chain.get(strike, {}).get("iv")
            fair_iv = float(own_iv) if own_iv is not None else prior
        fair_iv = max(sigma_floor, min(sigma_cap, float(fair_iv)))
        cache[strike] = fair_iv
        return fair_iv

    def _nearest_chain_iv(
        self,
        chain: Dict[int, Dict[str, Any]],
        spot: float,
    ) -> Optional[float]:
        best_iv: Optional[float] = None
        best_dist: Optional[float] = None
        for strike, row in chain.items():
            iv = row.get("iv")
            if iv is None:
                continue
            dist = abs(float(strike) - float(spot))
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_iv = float(iv)
        return best_iv

    def _update_realized_vol(
        self,
        spot: float,
        memory: Dict[str, Any],
        params: Dict[str, Any],
    ) -> Optional[float]:
        prev_spot = memory.get("_rv_prev_spot")
        memory["_rv_prev_spot"] = float(spot)
        if prev_spot is None or prev_spot <= 0.0 or spot <= 0.0:
            return memory.get("_realized_vol_daily")
        ret = math.log(float(spot) / float(prev_spot))
        window = max(2, int(params["realized_vol_window"]))
        min_obs = max(2, min(window, int(params["realized_vol_min_obs"])))
        buf: List[float] = memory.setdefault("_rv_logret_buf", [])
        buf.append(ret)
        if len(buf) > window:
            del buf[:-window]
        if len(buf) < min_obs:
            return memory.get("_realized_vol_daily")
        mean = sum(buf) / len(buf)
        var_tick = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        ts_per_day = timestamp_units_per_day_from_params(self.params)  # type: ignore[attr-defined]
        ts_increment = max(float(self.params.get("ts_increment", 100.0)), 1.0)  # type: ignore[attr-defined]
        ticks_per_day = max(ts_per_day / ts_increment, 1.0)
        sigma_daily = math.sqrt(max(var_tick, 0.0) * ticks_per_day)
        prev_sigma = memory.get("_realized_vol_daily")
        alpha = float(params["realized_vol_smooth_alpha"])
        if prev_sigma is not None:
            sigma_daily = alpha * sigma_daily + (1.0 - alpha) * float(prev_sigma)
        sigma_daily = max(float(params["fair_vol_floor"]), min(float(params["fair_vol_cap"]), sigma_daily))
        memory["_realized_vol_daily"] = sigma_daily
        return sigma_daily

    def _active_rank(
        self,
        *,
        strike: int,
        chain: Dict[int, Dict[str, Any]],
        S: float,
    ) -> Tuple[bool, int, Optional[int]]:
        """Return (is_active, active_count, rank) based on proximity to spot.

        The N closest-to-spot strikes are "active". N expands when spot drifts
        far from reference_spot (captures new ATM strikes).
        """
        if strike not in chain:
            return False, 0, None
        ordered = sorted(chain.keys(), key=lambda k: (abs(k - S), k))
        params = self.params  # type: ignore[attr-defined]
        reference = float(params.get("active_reference_spot", 5250.0))
        expand_every = float(params.get("active_expand_every", 120.0))
        base_count = int(params.get("active_base_count", 6))
        max_extra = int(params.get("active_max_extra_count", 2))
        if expand_every > 0:
            extra = min(max_extra, int(abs(S - reference) // expand_every))
        else:
            extra = max_extra
        active_count = min(len(ordered), max(0, base_count + extra))
        rank = ordered.index(strike) + 1
        return rank <= active_count, active_count, rank


class GammaScalpZGatedMixinStrategy(_VelvetOptionMixin, BaseStrategy):
    """GammaScalpZGatedStrategy using _VelvetOptionMixin for spot/TTE resolution.

    Logic identical to gamma_scalp_zgated.py, but uses the mixin's
    _resolve_spot() (shared tick-level cache) and _resolve_tte().
    This matches Theo's velvettuned_v7 GammaScalpZGatedStrategy exactly when
    the optional IV residual gate parameters are left at their defaults.
    """

    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        _, T = self._resolve_tte(state)
        params = self.params
        return {
            "K":                        float(params["strike"]),
            "T":                        max(0.01, T),
            "implied_vol_prior":        float(params.get("implied_vol_prior", 0.0125)),
            "edge_ticks":               float(params.get("edge_ticks", 0.0)),
            "target_qty":               int(params.get("target_qty", 100)),
            "entry_size":               int(params.get("entry_size", 10)),
            "passive_bid_size":         int(params.get("passive_bid_size", 10)),
            "unwind_tte_threshold":     float(params.get("unwind_tte_threshold", 1.5)),
            "min_quote_price":          float(params.get("min_quote_price", 2.0)),
            "zscore_window":            int(params.get("zscore_window", 500)),
            "zscore_skip_threshold":    float(params.get("zscore_skip_threshold", 1.0)),
            "zscore_boost_threshold":   float(params.get("zscore_boost_threshold", 1.0)),
            "skip_when_expensive":      bool(params.get("skip_when_expensive", True)),
            "boost_when_cheap":         bool(params.get("boost_when_cheap", False)),
            "entry_size_boost":         float(params.get("entry_size_boost", 1.5)),
            "sell_when_very_expensive": bool(params.get("sell_when_very_expensive", False)),
            "zscore_sell_threshold":    float(params.get("zscore_sell_threshold", 1.5)),
            "sell_size_pct":            float(params.get("sell_size_pct", 0.10)),
            "iv_residual_gate":         bool(params.get("iv_residual_gate", False)),
            "iv_skip_threshold":        float(params.get("iv_skip_threshold", 0.0010)),
            "iv_boost_threshold":       float(params.get("iv_boost_threshold", 0.0010)),
            "iv_delta_threshold":       float(params.get("iv_delta_threshold", 0.0003)),
            "iv_ewma_fast_alpha":       float(params.get("iv_ewma_fast_alpha", 0.10)),
            "iv_ewma_slow_alpha":       float(params.get("iv_ewma_slow_alpha", 0.02)),
            "iv_passive_boost":         float(params.get("iv_passive_boost", 1.5)),
            "fair_vol_mode":            str(params.get("fair_vol_mode", "fixed")),
            "fair_vol_floor":           float(params.get("fair_vol_floor", params.get("sigma_floor", 0.005))),
            "fair_vol_cap":             float(params.get("fair_vol_cap", params.get("sigma_cap", 0.10))),
            "realized_vol_window":      int(params.get("realized_vol_window", 600)),
            "realized_vol_min_obs":     int(params.get("realized_vol_min_obs", 60)),
            "realized_vol_smooth_alpha": float(params.get("realized_vol_smooth_alpha", 0.15)),
            "fair_vol_weight_prior":    float(params.get("fair_vol_weight_prior", 1.0)),
            "fair_vol_weight_realized": float(params.get("fair_vol_weight_realized", 0.0)),
            "fair_vol_weight_atm":      float(params.get("fair_vol_weight_atm", 0.0)),
            "fair_vol_weight_smile":    float(params.get("fair_vol_weight_smile", 0.0)),
            "fair_vol_scale":           float(params.get("fair_vol_scale", 1.0)),
            "fair_vol_shift":           float(params.get("fair_vol_shift", 0.0)),
            "fair_time_scale":          float(params.get("fair_time_scale", 1.0)),
            "fair_price_scale":         float(params.get("fair_price_scale", 1.0)),
        }

    def _update_zscore(self, S: float, memory: Dict[str, Any], params: Dict[str, Any]) -> Optional[float]:
        window = params["zscore_window"]
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

    def _update_iv_residual(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        spot: float,
        params: Dict[str, Any],
        ts: int,
    ) -> Tuple[Optional[float], Optional[float]]:
        strike = int(params["K"])
        chain = self._build_chain_snapshot(state, memory, spot, params["T"], ts)
        own_iv = chain.get(strike, {}).get("iv")
        if own_iv is None:
            return None, None
        fair_iv = self._fit_leave_one_out_iv(
            memory,
            strike=strike,
            chain=chain,
            S=spot,
            T=params["T"],
            ts=ts,
        )
        if fair_iv is None:
            return None, None
        residual = float(own_iv) - float(fair_iv)
        slow = memory.get("_iv_resid_slow")
        fast = memory.get("_iv_resid_fast")
        if slow is None or fast is None:
            slow = residual
            fast = residual
        else:
            slow = (1.0 - params["iv_ewma_slow_alpha"]) * float(slow) + params["iv_ewma_slow_alpha"] * residual
            fast = (1.0 - params["iv_ewma_fast_alpha"]) * float(fast) + params["iv_ewma_fast_alpha"] * residual
        memory["_iv_resid_slow"] = slow
        memory["_iv_resid_fast"] = fast
        return residual, float(fast) - float(slow)

    def _compute_fair_value(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        spot: float,
        params: Dict[str, Any],
        ts: int,
    ) -> Tuple[float, float, float]:
        prior = float(params["implied_vol_prior"])
        floor = float(params["fair_vol_floor"])
        cap = float(params["fair_vol_cap"])
        mode = str(params["fair_vol_mode"])
        realized_vol: Optional[float] = None
        atm_iv: Optional[float] = None
        smile_iv: Optional[float] = None
        chain: Optional[Dict[int, Dict[str, Any]]] = None

        if mode in {"realized", "blend"} or params["fair_vol_weight_realized"] > 0.0:
            realized_vol = self._update_realized_vol(spot, memory, params)

        if mode in {"atm_iv", "smile_iv", "blend"} or (
            params["fair_vol_weight_atm"] > 0.0 or params["fair_vol_weight_smile"] > 0.0
        ):
            chain = self._build_chain_snapshot(state, memory, spot, params["T"], ts)

        if chain is not None:
            if mode in {"atm_iv", "blend"} or params["fair_vol_weight_atm"] > 0.0:
                atm_iv = self._nearest_chain_iv(chain, spot)
            if mode in {"smile_iv", "blend"} or params["fair_vol_weight_smile"] > 0.0:
                smile_iv = self._fit_leave_one_out_iv(
                    memory,
                    strike=int(params["K"]),
                    chain=chain,
                    S=spot,
                    T=params["T"],
                    ts=ts,
                )

        if mode == "realized":
            sigma = realized_vol if realized_vol is not None else prior
        elif mode == "atm_iv":
            sigma = atm_iv if atm_iv is not None else prior
        elif mode == "smile_iv":
            sigma = smile_iv if smile_iv is not None else prior
        elif mode == "blend":
            weighted_sum = 0.0
            total_weight = 0.0
            components = (
                (prior, float(params["fair_vol_weight_prior"])),
                (realized_vol, float(params["fair_vol_weight_realized"])),
                (atm_iv, float(params["fair_vol_weight_atm"])),
                (smile_iv, float(params["fair_vol_weight_smile"])),
            )
            for value, weight in components:
                if value is None or weight <= 0.0:
                    continue
                weighted_sum += float(value) * weight
                total_weight += weight
            sigma = (weighted_sum / total_weight) if total_weight > 0.0 else prior
        else:
            sigma = prior

        sigma = sigma * float(params["fair_vol_scale"]) + float(params["fair_vol_shift"])
        sigma = max(floor, min(cap, sigma))
        model_T = max(0.01, float(params["T"]) * float(params["fair_time_scale"]))
        fair = call_price(spot, params["K"], model_T, sigma) * float(params["fair_price_scale"])
        fair = max(max(0.0, float(spot) - float(params["K"])), fair)

        memory["_fair_sigma"] = sigma
        memory["_fair_T_model"] = model_T
        memory["_fair_prior_sigma"] = prior
        memory["_fair_realized_sigma"] = realized_vol
        memory["_fair_atm_sigma"] = atm_iv
        memory["_fair_smile_sigma"] = smile_iv
        return fair, sigma, model_T

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
        S = self._resolve_spot(state, memory, ts)
        if S is None:
            return [], 0
        z = self._update_zscore(S, memory, p)
        fair, fair_sigma, fair_T = self._compute_fair_value(state, memory, S, p, ts)
        memory["_velvet_z"] = z
        memory["_gamma"]   = call_gamma(S, p["K"], fair_T, fair_sigma)
        memory["_delta"]   = call_delta(S, p["K"], fair_T, fair_sigma)
        memory["_fair_iv"] = fair
        memory["_spot"]    = S
        memory["_T"]       = fair_T
        if fair < p["min_quote_price"]:
            return [], 0
        orders:   List[Order] = []
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
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
        memory["_iv_boost"] = False
        if p["iv_residual_gate"]:
            iv_resid, iv_resid_delta = self._update_iv_residual(state, memory, S, p, ts)
            memory["_iv_resid"] = iv_resid
            memory["_iv_resid_delta"] = iv_resid_delta
            if iv_resid is not None and iv_resid_delta is not None:
                if iv_resid < -p["iv_skip_threshold"] and iv_resid_delta < -p["iv_delta_threshold"]:
                    memory["_mode"] = "iv_skip_falling"
                    return orders, 0
                if iv_resid > p["iv_boost_threshold"] and iv_resid_delta > p["iv_delta_threshold"]:
                    memory["_iv_boost"] = True
        else:
            memory.pop("_iv_resid", None)
            memory.pop("_iv_resid_delta", None)
        if (p["sell_when_very_expensive"] and z is not None
                and z > p["zscore_sell_threshold"] and position > 0 and sell_cap > 0):
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            sell_qty = max(1, int(round(position * p["sell_size_pct"])))
            qty = min(sell_qty, sell_cap, position, p["passive_bid_size"])
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "z_profit_take"
            return orders, 0
        if p["skip_when_expensive"] and z is not None and z > p["zscore_skip_threshold"]:
            memory["_mode"] = "z_skipped_expensive"
            return orders, 0
        size_mult = 1.0
        if p["boost_when_cheap"] and z is not None and z < -p["zscore_boost_threshold"]:
            size_mult = p["entry_size_boost"]
            memory["_mode"] = "z_boost_cheap"
        else:
            memory["_mode"] = "accumulate"
        eff_entry_size   = max(1, int(round(p["entry_size"]      * size_mult)))
        eff_passive_size = max(1, int(round(p["passive_bid_size"] * size_mult)))
        if memory.get("_iv_boost", False):
            eff_passive_size = max(1, int(round(eff_passive_size * p["iv_passive_boost"])))
        if buy_cap > 0 and position < p["target_qty"]:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty  = -order_depth.sell_orders.get(ask, 0)
                headroom = p["target_qty"] - position
                take_qty = min(ask_qty, buy_cap, eff_entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty
                    position += take_qty
        if buy_cap > 0 and position < p["target_qty"]:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(eff_passive_size, buy_cap, p["target_qty"] - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (f := memory.get("_fair_iv"))   is not None: out["fair_iv"]   = float(f)
        if (z := memory.get("_velvet_z"))  is not None: out["velvet_z"]  = float(z)
        if (s := memory.get("_fair_sigma")) is not None: out["fair_sigma"] = float(s)
        if (s := memory.get("_fair_realized_sigma")) is not None: out["realized_sigma"] = float(s)
        if (s := memory.get("_fair_atm_sigma")) is not None: out["atm_sigma"] = float(s)
        if (s := memory.get("_fair_smile_sigma")) is not None: out["smile_sigma"] = float(s)
        if (r := memory.get("_iv_resid")) is not None: out["iv_resid"] = float(r)
        if (d := memory.get("_iv_resid_delta")) is not None: out["iv_resid_delta"] = float(d)
        if (m := memory.get("_mode"))      is not None:
            out["mode"] = {"accumulate": 1.0, "unwind": 0.0,
                           "z_skipped_expensive": -1.0, "z_boost_cheap": 2.0,
                           "z_profit_take": 0.5, "iv_skip_falling": -1.5}.get(str(m), 0.5)
        return out


class SmileIVScalerStrategy(_VelvetOptionMixin, BaseStrategy):
    """Smile-based IV scalper: buy when cheap vs LOO smile, exit when it reverts.

    Entry logic (taker):
      - Only fires when resid_z <= -take_zscore (cheap regime first cross)
      - Scaled size: base_take_size * (1 + edge // take_price_edge)
      - Cooldown: take_cooldown_ts between taker entries
      - Gate: position <= entry_position_cap

    Exit logic (taker):
      - Sell when edge_sell >= reduce_price_edge OR resid_z >= reduce_zscore
      - Also sell passively via ask maker

    Passive maker:
      - Bid around (reference_px - maker_edge), skewed by inventory
      - Ask around (reference_px + maker_edge) when long

    Baseline tracking:
      - EWMA mean/variance of residual (market_iv - fair_iv)
      - resid_z = (residual - EWMA_mean) / EWMA_std
      - Cheap regime: resid_z dips below -take_zscore once, stays cheap
        until it crosses back above -cheap_reset_z
    """

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
        strike = self._option_strike()
        if strike is None:
            return [], 0
        ts = int(state.timestamp)
        _, T = self._resolve_tte(state)
        S = self._resolve_spot(state, memory, ts)
        if S is None:
            return [], 0

        chain = self._build_chain_snapshot(state, memory, S, T, ts)
        row = chain.get(strike)
        market_iv = None if row is None else row.get("iv")
        if row is None or market_iv is None:
            return [], 0

        fair_iv = self._fit_leave_one_out_iv(memory, strike=strike, chain=chain, S=S, T=T, ts=ts)
        if fair_iv is None:
            return [], 0

        active, _active_count, _rank = self._active_rank(strike=strike, chain=chain, S=S)
        residual = float(market_iv) - float(fair_iv)
        baseline_mean, baseline_std, resid_z, obs = self._residual_signal(memory, residual)
        reference_iv = self._clamp_sigma(float(fair_iv) + baseline_mean)
        reference_px = call_price(S, float(strike), T, reference_iv)

        p = self.params
        soft_limit = int(p.get("soft_position_limit", 150))
        take_size = int(p.get("take_size", 20))
        maker_size = max(0, int(p.get("maker_size", 10)))
        maker_edge = float(p.get("maker_edge", 2.0))
        take_edge = float(p.get("take_price_edge", 2.0))
        reduce_edge = float(p.get("reduce_price_edge", 1.0))
        take_z = float(p.get("take_zscore", 0.9))
        reduce_z = float(p.get("reduce_zscore", 0.6))
        cheap_reset_z = float(p.get("cheap_reset_z", 0.35))
        inventory_skew = float(p.get("inventory_skew", 3.0))
        min_quote_price = float(p.get("min_quote_price", 1.0))
        warmup_ticks = int(p.get("resid_warmup_ticks", 60))
        maker_join = bool(p.get("maker_join_best", True))
        inactive_unwind_bias = int(p.get("inactive_unwind_bias", 1))
        entry_position_cap = int(p.get("entry_position_cap", soft_limit))
        take_cooldown_ts = int(p.get("take_cooldown_ts", 0))

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        headroom = max(0, soft_limit - position)
        edge_buy = reference_px - book.best_ask
        edge_sell = book.best_bid - reference_px
        warmed = obs >= warmup_ticks

        # Track cheap regime (avoid re-entering after initial fill)
        if resid_z >= -cheap_reset_z:
            memory["_cheap_regime"] = False
        last_take_ts = memory.get("_last_take_ts")
        cooled = (
            last_take_ts is None
            or take_cooldown_ts <= 0
            or (ts - int(last_take_ts)) >= take_cooldown_ts
        )
        cheap_cross = resid_z <= -take_z and not bool(memory.get("_cheap_regime", False))

        # ── Aggressive entry: buy when cheap vs smile ──────────────────────────
        if (
            active
            and warmed
            and reference_px >= min_quote_price
            and buy_cap > 0
            and headroom > 0
            and position <= entry_position_cap
        ):
            if edge_buy >= take_edge and cheap_cross and cooled:
                scale = 1 + int(edge_buy // max(take_edge, 1.0))
                qty = min(take_size * scale, buy_cap, headroom, max(1, book.best_ask_volume))
                if qty > 0:
                    orders.append(Order(self.product, book.best_ask, qty))
                    position += qty
                    buy_cap -= qty
                    sell_cap = self.sell_capacity(position)
                    headroom = max(0, soft_limit - position)
                    memory["_cheap_regime"] = True
                    memory["_last_take_ts"] = ts

        # ── Exit: sell when IV reverts to fair ────────────────────────────────
        if position > 0 and sell_cap > 0:
            should_reduce = edge_sell >= reduce_edge or resid_z >= reduce_z
            if not active and book.best_bid >= max(1, int(round(reference_px)) - inactive_unwind_bias):
                should_reduce = True
            if should_reduce:
                qty = min(position, sell_cap, max(1, book.best_bid_volume), take_size)
                if qty > 0:
                    orders.append(Order(self.product, book.best_bid, -qty))
                    position -= qty
                    sell_cap -= qty
                    buy_cap = self.buy_capacity(position)
                    headroom = max(0, soft_limit - position)

        # ── Passive maker around smile reference price ─────────────────────────
        if active and warmed and maker_size > 0 and reference_px >= min_quote_price and buy_cap > 0 and headroom > 0:
            raw_bid = int(round(reference_px - maker_edge - inventory_skew * max(position, 0) / max(soft_limit, 1)))
            join_bid = book.best_bid + (1 if maker_join and (book.spread or 0) >= 2 else 0)
            bid_px = max(1, min(book.best_ask - 1, max(join_bid, raw_bid)))
            if bid_px < book.best_ask:
                qty = min(maker_size, buy_cap, headroom)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        if position > 0 and sell_cap > 0 and maker_size > 0 and active and warmed:
            raw_ask = int(round(reference_px + maker_edge - inventory_skew * position / max(soft_limit, 1)))
            join_ask = book.best_ask - (1 if maker_join and (book.spread or 0) >= 2 else 0)
            ask_px = max(book.best_bid + 1, min(join_ask, raw_ask))
            if ask_px > book.best_bid:
                qty = min(maker_size, sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))

        self._update_residual_baseline(memory, residual)
        memory["_fair_iv_smile"] = fair_iv
        memory["_residual_iv"] = residual
        memory["_residual_z"] = resid_z
        memory["_reference_iv"] = reference_iv
        memory["_reference_px"] = reference_px
        return orders, 0

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _clamp_sigma(self, sigma: float) -> float:
        floor = float(self.params.get("sigma_floor", 0.005))
        cap = float(self.params.get("sigma_cap", 0.10))
        return max(floor, min(cap, sigma))

    def _residual_signal(
        self, memory: Dict[str, Any], residual: float
    ) -> Tuple[float, float, float, int]:
        """Return (baseline_mean, baseline_std, resid_z, obs_count)."""
        mean_prev = memory.get("_resid_mean_ewma")
        if mean_prev is None:
            init_std = float(self.params.get("resid_std_init", 0.0015))
            return float(residual), max(init_std, 1e-6), 0.0, 0
        var_prev = float(
            memory.get("_resid_var_ewma", float(self.params.get("resid_std_init", 0.0015)) ** 2)
        )
        std_floor = float(self.params.get("resid_std_floor", 0.0005))
        std_prev = max(std_floor, math.sqrt(max(var_prev, 0.0)))
        resid_z = (residual - float(mean_prev)) / std_prev
        return float(mean_prev), std_prev, resid_z, int(memory.get("_resid_obs", 0))

    def _update_residual_baseline(self, memory: Dict[str, Any], residual: float) -> None:
        alpha = float(self.params.get("resid_ewma_alpha", 0.03))
        if "_resid_mean_ewma" not in memory:
            memory["_resid_mean_ewma"] = float(residual)
            memory["_resid_var_ewma"] = float(self.params.get("resid_std_init", 0.0015)) ** 2
            memory["_resid_obs"] = 1
            return
        mean_prev = float(memory["_resid_mean_ewma"])
        var_prev = float(
            memory.get("_resid_var_ewma", float(self.params.get("resid_std_init", 0.0015)) ** 2)
        )
        delta = residual - mean_prev
        mean_new = mean_prev + alpha * delta
        var_new = (1.0 - alpha) * var_prev + alpha * (delta ** 2)
        std_floor = float(self.params.get("resid_std_floor", 0.0005))
        memory["_resid_mean_ewma"] = mean_new
        memory["_resid_var_ewma"] = max(var_new, std_floor ** 2)
        memory["_resid_obs"] = int(memory.get("_resid_obs", 0)) + 1

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_iv_smile")) is not None:
            out["smile_fair_iv_pct"] = float(v) * 100.0
        if (v := memory.get("_reference_iv")) is not None:
            out["reference_iv_pct"] = float(v) * 100.0
        if (v := memory.get("_reference_px")) is not None:
            out["reference_px"] = float(v)
        if (v := memory.get("_residual_iv")) is not None:
            out["iv_resid_bps"] = float(v) * 10000.0
        if (v := memory.get("_residual_z")) is not None:
            out["iv_resid_z"] = float(v)
        return out
