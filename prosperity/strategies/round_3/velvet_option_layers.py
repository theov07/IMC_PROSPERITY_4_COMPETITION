"""Round 3 velvet option layers.

This file keeps the profitable directional option accumulator from the v24
submission and adds a conservative IV smile residual scalper that can be
plugged on selected strikes without disturbing the rest of the stack.
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


DEFAULT_VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


class _VelvetOptionMixin:
    def _shared(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        shared = memory.get("_shared")
        if not isinstance(shared, dict):
            shared = {}
            memory["_shared"] = shared
        return shared

    def _option_strike(self, symbol: Optional[str] = None) -> Optional[int]:
        raw = symbol or self.product
        if not raw.startswith("VEV_"):
            return None
        try:
            return int(raw.replace("VEV_", ""))
        except ValueError:
            return None

    def _resolve_tte(self, state: TradingState) -> Tuple[float, float]:
        params = self.params
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

        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
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
    ) -> Dict[int, Dict[str, float | None]]:
        shared = self._shared(memory)
        if shared.get("vev_chain_ts") == ts:
            cached = shared.get("vev_chain")
            if isinstance(cached, dict):
                return cached

        prior = float(self.params.get("prior_vol", self.params.get("implied_vol_prior", 0.0125)))
        sigma_floor = float(self.params.get("sigma_floor", 0.005))
        sigma_cap = float(self.params.get("sigma_cap", 0.10))
        chain: Dict[int, Dict[str, float | None]] = {}

        for symbol, od in state.order_depths.items():
            strike = self._option_strike(symbol)
            if strike is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)
            mid = 0.5 * (best_bid + best_ask)
            iv = call_implied_vol(mid, S, float(strike), T, sigma_init=prior)
            iv_valid = float(iv) if iv is not None and sigma_floor <= iv <= sigma_cap else None
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
        chain: Dict[int, Dict[str, float | None]],
        S: float,
        T: float,
        ts: int,
    ) -> Optional[float]:
        shared = self._shared(memory)
        if shared.get("vev_chain_loo_ts") != ts:
            shared["vev_chain_loo_ts"] = ts
            shared["vev_chain_loo"] = {}
        cache = shared.setdefault("vev_chain_loo", {})
        if strike in cache:
            return cache[strike]

        smile_degree = int(self.params.get("smile_degree", 2))
        min_points = int(self.params.get("smile_min_points", 4))
        prior = float(self.params.get("prior_vol", self.params.get("implied_vol_prior", 0.0125)))
        sigma_floor = float(self.params.get("sigma_floor", 0.005))
        sigma_cap = float(self.params.get("sigma_cap", 0.10))

        strikes: List[float] = []
        vols: List[float] = []
        for other_strike, row in chain.items():
            if other_strike == strike:
                continue
            iv = row.get("iv")
            if iv is None:
                continue
            strikes.append(float(other_strike))
            vols.append(float(iv))

        fair_iv: Optional[float] = None
        if len(strikes) >= max(min_points, smile_degree + 1):
            coeffs = fit_smile_poly(strikes, vols, S, T, degree=smile_degree, min_points=min_points)
            if coeffs is not None:
                fair_iv = smile_predict(float(strike), coeffs, S, T)

        if fair_iv is None:
            own_iv = chain.get(strike, {}).get("iv")
            fair_iv = float(own_iv) if own_iv is not None else prior

        fair_iv = max(sigma_floor, min(sigma_cap, float(fair_iv)))
        cache[strike] = fair_iv
        return fair_iv

    def _active_rank(
        self,
        *,
        strike: int,
        chain: Dict[int, Dict[str, float | None]],
        S: float,
    ) -> Tuple[bool, int, Optional[int]]:
        if strike not in chain:
            return False, 0, None

        ordered = sorted(chain.keys(), key=lambda k: (abs(k - S), k))
        reference = float(self.params.get("active_reference_spot", 5250.0))
        expand_every = float(self.params.get("active_expand_every", 120.0))
        base_count = int(self.params.get("active_base_count", 4))
        max_extra = int(self.params.get("active_max_extra_count", 2))
        if expand_every > 0:
            extra = min(max_extra, int(abs(S - reference) // expand_every))
        else:
            extra = max_extra
        active_count = min(len(ordered), max(0, base_count + extra))
        rank = ordered.index(strike) + 1
        return rank <= active_count, active_count, rank

    def _counterparty_signal(self, state: TradingState, memory: Dict[str, Any]) -> float:
        if not bool(self.params.get("mark_signal_enabled", False)):
            memory["_mark_signal"] = 0.0
            return 0.0

        buy_weights = self.params.get("mark_buy_weights", {})
        sell_weights = self.params.get("mark_sell_weights", {})
        alpha = float(self.params.get("mark_signal_alpha", 0.45))
        decay = float(self.params.get("mark_signal_decay", 0.75))
        qty_norm = max(1.0, float(self.params.get("mark_qty_norm", 4.0)))
        clip = max(0.0, float(self.params.get("mark_signal_clip", 4.0)))

        raw = 0.0
        for trade in state.market_trades.get(self.product, []):
            raw += float(buy_weights.get(getattr(trade, "buyer", None), 0.0)) * float(trade.quantity)
            raw += float(sell_weights.get(getattr(trade, "seller", None), 0.0)) * float(trade.quantity)
        raw /= qty_norm

        prev = float(memory.get("_mark_signal", 0.0))
        signal = (prev * decay) if abs(raw) < 1e-9 else (alpha * raw + (1.0 - alpha) * prev)
        if clip > 0.0:
            signal = max(-clip, min(clip, signal))
        memory["_mark_signal"] = signal
        return signal


class GammaScalpZGatedStrategy(_VelvetOptionMixin, BaseStrategy):
    """Directional long-call accumulator from the v24 velvet option stack."""

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
        fair = call_price(S, p["K"], p["T"], p["implied_vol_prior"])
        gamma = call_gamma(S, p["K"], p["T"], p["implied_vol_prior"])
        delta = call_delta(S, p["K"], p["T"], p["implied_vol_prior"])
        mark_signal = self._counterparty_signal(state, memory)
        fair += self._mark_fair_shift(mark_signal)

        memory["_velvet_z"] = z
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
        target_qty = p["target_qty"] + self._mark_target_bonus(mark_signal)

        if p["T"] < p["unwind_tte_threshold"] or position >= target_qty:
            if sell_cap > 0 and position > 0:
                ask_px = book.best_ask - 1
                if ask_px <= book.best_bid:
                    ask_px = book.best_bid + 1
                qty = min(p["passive_bid_size"], sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "unwind"
            return orders, 0

        if (
            p["sell_when_very_expensive"]
            and z is not None
            and z > p["zscore_sell_threshold"]
            and position > 0
            and sell_cap > 0
        ):
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            sell_qty = max(1, int(round(position * p["sell_size_pct"])))
            qty = min(sell_qty, sell_cap, position, p["passive_bid_size"])
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "z_profit_take"
            return orders, 0

        effective_zskip = p["zscore_skip_threshold"] + self._mark_skip_relax(mark_signal)
        if p["skip_when_expensive"] and z is not None and z > effective_zskip:
            memory["_mode"] = "z_skipped_expensive"
            return orders, 0

        if self._mark_should_unwind(mark_signal) and position > 0 and sell_cap > 0:
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            qty = min(p["passive_bid_size"], sell_cap, position)
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "mark_unwind"
            return orders, 0

        size_mult = self._mark_entry_multiplier(mark_signal)
        memory["_mode"] = "accumulate"
        if p["boost_when_cheap"] and z is not None and z < -p["zscore_boost_threshold"]:
            size_mult = p["entry_size_boost"]
            memory["_mode"] = "z_boost_cheap"

        eff_entry_size = max(1, int(round(p["entry_size"] * size_mult)))
        eff_passive_size = max(1, int(round(p["passive_bid_size"] * size_mult)))

        if buy_cap > 0 and position < target_qty:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty = -order_depth.sell_orders.get(ask, 0)
                headroom = target_qty - position
                take_qty = min(ask_qty, buy_cap, eff_entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty
                    position += take_qty

        if buy_cap > 0 and position < target_qty:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(eff_passive_size, buy_cap, target_qty - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0

    def _mark_fair_shift(self, mark_signal: float) -> float:
        per_unit = float(self.params.get("mark_fair_shift_per_unit", 0.0))
        max_shift = float(self.params.get("mark_max_fair_shift", 0.0))
        if per_unit == 0.0 or max_shift <= 0.0:
            return 0.0
        shift = mark_signal * per_unit
        return max(-max_shift, min(max_shift, shift))

    def _mark_entry_multiplier(self, mark_signal: float) -> float:
        boost = float(self.params.get("mark_entry_size_boost", 0.0))
        clip = max(1e-9, float(self.params.get("mark_signal_clip", 4.0)))
        if boost <= 0.0 or mark_signal <= 0.0:
            return 1.0
        return 1.0 + boost * min(1.0, mark_signal / clip)

    def _mark_target_bonus(self, mark_signal: float) -> int:
        bonus = int(self.params.get("mark_target_bonus", 0))
        clip = max(1e-9, float(self.params.get("mark_signal_clip", 4.0)))
        if bonus <= 0 or mark_signal <= 0.0:
            return 0
        return int(round(bonus * min(1.0, mark_signal / clip)))

    def _mark_skip_relax(self, mark_signal: float) -> float:
        relax = float(self.params.get("mark_skip_relax", 0.0))
        clip = max(1e-9, float(self.params.get("mark_signal_clip", 4.0)))
        if relax <= 0.0 or mark_signal <= 0.0:
            return 0.0
        return relax * min(1.0, mark_signal / clip)

    def _mark_should_unwind(self, mark_signal: float) -> bool:
        threshold = float(self.params.get("mark_unwind_threshold", 0.0))
        return threshold > 0.0 and mark_signal <= -threshold

    def _update_zscore(self, S: float, memory: Dict[str, Any], params: Dict[str, Any]) -> Optional[float]:
        window = params["zscore_window"]
        buf: List[float] = memory.setdefault("_velvet_buf", [])
        buf.append(S)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None

        mean = sum(buf) / len(buf)
        var = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return None
        return (S - mean) / std

    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        _, T = self._resolve_tte(state)
        params = self.params
        return {
            "K": float(params["strike"]),
            "T": T,
            "implied_vol_prior": float(params.get("implied_vol_prior", 0.0125)),
            "edge_ticks": float(params.get("edge_ticks", 0.0)),
            "target_qty": int(params.get("target_qty", 100)),
            "entry_size": int(params.get("entry_size", 10)),
            "passive_bid_size": int(params.get("passive_bid_size", 10)),
            "unwind_tte_threshold": float(params.get("unwind_tte_threshold", 1.5)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "zscore_window": int(params.get("zscore_window", 500)),
            "zscore_skip_threshold": float(params.get("zscore_skip_threshold", 1.0)),
            "zscore_boost_threshold": float(params.get("zscore_boost_threshold", 1.0)),
            "skip_when_expensive": bool(params.get("skip_when_expensive", True)),
            "boost_when_cheap": bool(params.get("boost_when_cheap", False)),
            "entry_size_boost": float(params.get("entry_size_boost", 1.5)),
            "sell_when_very_expensive": bool(params.get("sell_when_very_expensive", False)),
            "zscore_sell_threshold": float(params.get("zscore_sell_threshold", 1.5)),
            "sell_size_pct": float(params.get("sell_size_pct", 0.10)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (gamma := memory.get("_gamma")) is not None:
            out["gamma"] = float(gamma)
        if (delta := memory.get("_delta")) is not None:
            out["delta"] = float(delta)
        if (fair := memory.get("_fair_iv")) is not None:
            out["fair_iv"] = float(fair)
        if (z := memory.get("_velvet_z")) is not None:
            out["velvet_z"] = float(z)
        if (mark_signal := memory.get("_mark_signal")) is not None:
            out["mark_signal"] = float(mark_signal)
        if (mode := memory.get("_mode")) is not None:
            out["mode"] = {
                "accumulate": 1.0,
                "unwind": 0.0,
                "z_skipped_expensive": -1.0,
                "z_boost_cheap": 2.0,
                "z_profit_take": 0.5,
                "mark_unwind": -0.5,
            }.get(str(mode), 0.5)
        return out


class SmileIVScalperStrategy(_VelvetOptionMixin, BaseStrategy):
    """Conservative long-biased IV smile residual scalper for selected strikes."""

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

        active, active_count, active_rank = self._active_rank(strike=strike, chain=chain, S=S)
        residual = float(market_iv) - float(fair_iv)
        baseline_mean, baseline_std, resid_z, obs = self._residual_signal(memory, residual)
        reference_iv = self._clamp_sigma(float(fair_iv) + baseline_mean)
        reference_px = call_price(S, float(strike), T, reference_iv)

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        soft_limit = int(self.params.get("soft_position_limit", 60))
        take_size = int(self.params.get("take_size", 6))
        maker_size = max(0, int(self.params.get("maker_size", 4)))
        maker_edge = float(self.params.get("maker_edge", 1.5))
        take_edge = float(self.params.get("take_price_edge", 2.0))
        reduce_edge = float(self.params.get("reduce_price_edge", 1.0))
        take_z = float(self.params.get("take_zscore", 0.9))
        reduce_z = float(self.params.get("reduce_zscore", 0.6))
        cheap_reset_z = float(self.params.get("cheap_reset_z", 0.35))
        inventory_skew = float(self.params.get("inventory_skew", 4.0))
        min_quote_price = float(self.params.get("min_quote_price", 1.0))
        warmup_ticks = int(self.params.get("resid_warmup_ticks", 60))
        maker_join = bool(self.params.get("maker_join_best", True))
        inactive_unwind_bias = int(self.params.get("inactive_unwind_bias", 1))
        entry_position_cap = int(self.params.get("entry_position_cap", 0))
        take_cooldown_ts = int(self.params.get("take_cooldown_ts", 0))

        headroom = max(0, soft_limit - position)
        edge_buy = reference_px - book.best_ask
        edge_sell = book.best_bid - reference_px
        warmed = obs >= warmup_ticks

        if resid_z >= -cheap_reset_z:
            memory["_cheap_regime"] = False
        last_take_ts = memory.get("_last_take_ts")
        cooled = last_take_ts is None or take_cooldown_ts <= 0 or (ts - int(last_take_ts)) >= take_cooldown_ts
        cheap_cross = resid_z <= -take_z and not bool(memory.get("_cheap_regime", False))

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

        bid_px = None
        ask_px = None

        if active and warmed and maker_size > 0 and reference_px >= min_quote_price and buy_cap > 0 and headroom > 0:
            raw_bid = int(round(reference_px - maker_edge - inventory_skew * max(position, 0) / max(soft_limit, 1)))
            join_bid = book.best_bid + (1 if maker_join and (book.spread or 0) >= 2 else 0)
            bid_px = max(1, min(book.best_ask - 1, max(join_bid, raw_bid)))
            if bid_px < book.best_ask:
                qty = min(maker_size, buy_cap, headroom)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        if position > 0 and sell_cap > 0 and maker_size > 0:
            raw_ask = int(round(reference_px + maker_edge - inventory_skew * position / max(soft_limit, 1)))
            if active:
                join_ask = book.best_ask - (1 if maker_join and (book.spread or 0) >= 2 else 0)
                ask_px = max(book.best_bid + 1, min(join_ask, raw_ask))
            else:
                ask_px = max(book.best_bid + 1, min(book.best_ask - inactive_unwind_bias, raw_ask))
            if ask_px > book.best_bid:
                qty = min(maker_size, sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))

        self._update_residual_baseline(memory, residual)

        memory["_fair_iv_smile"] = fair_iv
        memory["_residual_iv"] = residual
        memory["_residual_z"] = resid_z
        memory["_residual_mean"] = baseline_mean
        memory["_residual_std"] = baseline_std
        memory["_reference_iv"] = reference_iv
        memory["_reference_px"] = reference_px
        memory["_active_rank"] = float(active_rank or 0)
        memory["_active_count"] = float(active_count)
        memory["_active_flag"] = 1.0 if active else 0.0

        return orders, 0

    def _clamp_sigma(self, sigma: float) -> float:
        floor = float(self.params.get("sigma_floor", 0.005))
        cap = float(self.params.get("sigma_cap", 0.10))
        return max(floor, min(cap, sigma))

    def _residual_signal(self, memory: Dict[str, Any], residual: float) -> Tuple[float, float, float, int]:
        mean_prev = memory.get("_resid_mean_ewma")
        if mean_prev is None:
            init_std = float(self.params.get("resid_std_init", 0.0015))
            return float(residual), max(init_std, 1e-6), 0.0, 0

        var_prev = float(memory.get("_resid_var_ewma", float(self.params.get("resid_std_init", 0.0015)) ** 2))
        std_prev = max(float(self.params.get("resid_std_floor", 0.0005)), math.sqrt(max(var_prev, 0.0)))
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
        var_prev = float(memory.get("_resid_var_ewma", float(self.params.get("resid_std_init", 0.0015)) ** 2))
        delta = residual - mean_prev
        mean_new = mean_prev + alpha * delta
        var_new = (1.0 - alpha) * var_prev + alpha * (delta ** 2)
        memory["_resid_mean_ewma"] = mean_new
        memory["_resid_var_ewma"] = max(var_new, float(self.params.get("resid_std_floor", 0.0005)) ** 2)
        memory["_resid_obs"] = int(memory.get("_resid_obs", 0)) + 1

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (fair_iv := memory.get("_fair_iv_smile")) is not None:
            out["smile_fair_iv_pct"] = float(fair_iv) * 100.0
        if (reference_iv := memory.get("_reference_iv")) is not None:
            out["reference_iv_pct"] = float(reference_iv) * 100.0
        if (reference_px := memory.get("_reference_px")) is not None:
            out["reference_px"] = float(reference_px)
        if (residual := memory.get("_residual_iv")) is not None:
            out["iv_resid_bps"] = float(residual) * 10000.0
        if (resid_z := memory.get("_residual_z")) is not None:
            out["iv_resid_z"] = float(resid_z)
        if (active := memory.get("_active_flag")) is not None:
            out["active"] = float(active)
        if (active_rank := memory.get("_active_rank")) is not None:
            out["active_rank"] = float(active_rank)
        return out
