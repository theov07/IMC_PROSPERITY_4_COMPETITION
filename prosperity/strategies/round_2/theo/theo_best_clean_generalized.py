"""Theo round-2 clean generalized reference strategy for INTARIAN_PEPPER_ROOT.

This is the canonical raw-framework source corresponding to the exported
`artifacts/submissions/round_2/theo/theo_best_clean_generalized.py` reference.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.strategies.base.base import BaseStrategy

StrategyBase = BaseStrategy


def _ewma(previous: Optional[float], current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


# ── TestTheo Strategy ─────────────────────────────────────────────────────────────

class TheoBestCleanGeneralizedStrategy(StrategyBase):
    """Hybrid: Full Leo fusion for buys + v34-style passive sells when at max position."""

    # ── helpers ──────────────────────────────────────────────────────────

    def _update_regression(
        self,
        *,
        state: TradingState,
        mid: float,
        memory: Dict[str, Any],
    ) -> Dict[str, float]:
        ts_increment = max(1, int(self.params.get("ts_increment", 100)))
        seed_slope = float(self.params.get("seed_slope", 0.1015))
        block_size = max(1, int(self.params.get("block_size", 100)))
        min_completed_blocks = max(1, int(self.params.get("min_completed_blocks", 5)))
        horizon = int(self.params.get("reg_horizon", 25))
        r2_floor = float(self.params.get("reg_r2_floor", 0.85))
        r2_cap = float(self.params.get("reg_r2_cap", 0.98))
        rmse_floor = float(self.params.get("reg_rmse_floor", 1.0))
        mean_revert_weight = float(self.params.get("reg_residual_reversion", 0.25))

        anchor_ts = memory.setdefault("line_anchor_ts", int(state.timestamp))
        anchor_mid = memory.setdefault("line_anchor_mid", mid)
        tick_index = max(0, int(round((int(state.timestamp) - anchor_ts) / ts_increment)))

        completed_means = memory.setdefault("block_means", [])
        completed_centers = memory.setdefault("block_centers", [])
        current_block_index = int(memory.get("current_block_index", 0))
        block_sum = float(memory.get("current_block_sum", 0.0))
        block_count = int(memory.get("current_block_count", 0))

        target_block_index = tick_index // block_size
        if target_block_index != current_block_index and block_count > 0:
            start_tick = current_block_index * block_size
            end_tick = start_tick + block_count - 1
            completed_means.append(block_sum / block_count)
            completed_centers.append((start_tick + end_tick) / 2.0)
            current_block_index = target_block_index
            block_sum = 0.0
            block_count = 0

        block_sum += mid
        block_count += 1
        memory["current_block_index"] = current_block_index
        memory["current_block_sum"] = block_sum
        memory["current_block_count"] = block_count

        current_block_mean = block_sum / max(1, block_count)
        current_block_start = current_block_index * block_size
        current_block_center = current_block_start + (block_count - 1) / 2.0

        xs: List[float] = list(completed_centers)
        ys: List[float] = list(completed_means)
        if block_count > 0:
            xs.append(current_block_center)
            ys.append(current_block_mean)

        if len(completed_means) < min_completed_blocks:
            slope = seed_slope
            intercept = anchor_mid
            fit_r2 = 0.0
            fitted_now = anchor_mid + slope * tick_index
            residual = mid - fitted_now
            rmse = max(abs(residual), rmse_floor)
            confidence = float(self.params.get("bootstrap_confidence", 0.55))
        else:
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n

            ss_xx = 0.0
            ss_xy = 0.0
            for x, y in zip(xs, ys):
                dx = x - mean_x
                dy = y - mean_y
                ss_xx += dx * dx
                ss_xy += dx * dy

            slope = ss_xy / ss_xx if ss_xx > 0 else seed_slope
            intercept = mean_y - slope * mean_x
            fitted_points = [intercept + slope * x for x in xs]
            fitted_now = intercept + slope * tick_index
            residual = mid - fitted_now

            ss_tot = sum((y - mean_y) ** 2 for y in ys)
            ss_res = sum((y - fit) ** 2 for y, fit in zip(ys, fitted_points))
            fit_r2 = 0.0 if ss_tot <= 1e-9 else max(0.0, 1.0 - ss_res / ss_tot)
            rmse = max(math.sqrt(ss_res / max(1, n)), rmse_floor)

            if r2_cap <= r2_floor:
                confidence = 1.0 if fit_r2 > r2_floor else 0.0
            else:
                confidence = max(0.0, min(1.0, (fit_r2 - r2_floor) / (r2_cap - r2_floor)))

        trend_ticks = slope * horizon * confidence
        residual_z = residual / rmse if rmse > 0 else 0.0
        forecast = intercept + slope * (tick_index + horizon)
        fair_value = forecast - mean_revert_weight * residual

        stats = {
            "slope": slope,
            "intercept": intercept,
            "fitted_now": fitted_now,
            "forecast": forecast,
            "residual": residual,
            "rmse": rmse,
            "r2": fit_r2,
            "confidence": confidence,
            "trend_ticks": trend_ticks,
            "fair_value": fair_value,
            "residual_z": residual_z,
            "block_count": float(len(completed_means)),
            "current_block_mean": current_block_mean,
        }
        memory["regression_stats"] = stats
        return stats

    def _inventory_target(
        self,
        *,
        state: TradingState,
        stats: Dict[str, float],
        position: int,
    ) -> int:
        trend_inv_per_tick = float(self.params.get("trend_inv_per_tick", 26.0))
        resid_inv_per_z = float(self.params.get("resid_inv_per_z", 7.0))
        inv_cap = int(self.params.get("trend_inventory_cap", 74))

        target = stats["trend_ticks"] * trend_inv_per_tick
        target -= stats["residual_z"] * resid_inv_per_z

        startup_target = int(self.params.get("startup_target", 40))
        startup_end_ts = int(self.params.get("startup_end_ts", 30000))
        if int(state.timestamp) <= startup_end_ts and stats["trend_ticks"] >= 0.0:
            target = max(target, startup_target)

        target = max(-inv_cap, min(inv_cap, target))
        return int(round(target))

    def _size_from_target(
        self,
        *,
        position: int,
        inv_target: int,
        stats: Dict[str, float],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        min_quote_size = int(self.params.get("min_quote_size", 1))
        base_buy = min(buy_cap, maker_size)
        base_sell = min(sell_cap, maker_size)

        if base_buy <= 0 and base_sell <= 0:
            return 0, 0

        gap = inv_target - position
        gap_scale = max(1.0, float(self.params.get("target_gap_scale", 26.0)))
        bullish_boost = max(0.0, stats["trend_ticks"]) * float(self.params.get("trend_buy_boost_per_tick", 0.24))
        bearish_boost = max(0.0, -stats["trend_ticks"]) * float(self.params.get("trend_sell_boost_per_tick", 0.20))
        cheap_boost = max(0.0, -stats["residual_z"]) * float(self.params.get("cheap_buy_boost_per_z", 0.18))
        rich_boost = max(0.0, stats["residual_z"]) * float(self.params.get("rich_sell_boost_per_z", 0.14))

        buy_mult = 1.0 + max(0.0, gap) / gap_scale + bullish_boost + cheap_boost
        sell_mult = 1.0 + max(0.0, -gap) / gap_scale + bearish_boost + rich_boost

        aggravate_cut = float(self.params.get("aggravate_cut", 0.04))
        if gap > 0:
            sell_mult *= aggravate_cut
        elif gap < 0:
            buy_mult *= aggravate_cut

        one_sided_gap = int(self.params.get("one_sided_target_gap", 24))
        strong_trend = float(self.params.get("strong_trend_ticks", 1.1))
        if gap >= one_sided_gap and stats["trend_ticks"] >= strong_trend:
            sell_mult = 0.0
        elif gap <= -one_sided_gap and stats["trend_ticks"] <= -strong_trend:
            buy_mult = 0.0

        buy_size = 0 if buy_mult <= 0.0 else min(buy_cap, max(min_quote_size, int(round(base_buy * buy_mult))))
        sell_size = 0 if sell_mult <= 0.0 else min(sell_cap, max(min_quote_size, int(round(base_sell * sell_mult))))
        return buy_size, sell_size

    def _process_premium_fills(
        self,
        state:  TradingState,
        memory: Dict[str, Any],
    ) -> None:
        """Detect gap fills from own_trades and promote them into rebuy state.

        Checks each own trade against last tick's active gap quote prices and
        against a minimum premium threshold vs the last known market price.
        Avoids assuming a posted gap quote was filled — only marks state when
        there is confirmed trade evidence.

        Params:
          empty_side_shift  — used to compute gap_fill_min_premium default
          gap_fill_min_premium — min price offset from last known market price
                                 to classify a fill as a gap fill (default max(30, shift//2))

        Side effects on memory:
          _last_gap_sell_ts, _last_gap_sell_price, _last_gap_sell_qty
          _last_gap_buy_ts,  _last_gap_buy_price,  _last_gap_buy_qty
        """
        empty_side_shift      = int(self.params.get("empty_side_shift", 85))
        gap_fill_min_premium  = int(self.params.get("gap_fill_min_premium", max(30, empty_side_shift // 2)))
        last_best_bid         = memory.get("_last_best_bid")
        last_best_ask         = memory.get("_last_best_ask")
        prev_gap_sell_quotes  = {int(p) for p in memory.get("_active_gap_sell_quotes", [])}
        prev_gap_buy_quotes   = {int(p) for p in memory.get("_active_gap_buy_quotes", [])}

        for trade in state.own_trades.get(self.product, []):
            trade_price = int(trade.price)
            if trade.seller == "SUBMISSION":
                is_gap_fill = trade_price in prev_gap_sell_quotes
                if not is_gap_fill and last_best_ask is not None:
                    is_gap_fill = trade_price >= int(last_best_ask) + gap_fill_min_premium
                if is_gap_fill:
                    memory["_last_gap_sell_ts"]    = int(trade.timestamp)
                    memory["_last_gap_sell_price"] = trade_price
                    memory["_last_gap_sell_qty"]   = int(trade.quantity)
            elif trade.buyer == "SUBMISSION":
                is_gap_fill = trade_price in prev_gap_buy_quotes
                if not is_gap_fill and last_best_bid is not None:
                    is_gap_fill = trade_price <= int(last_best_bid) - gap_fill_min_premium
                if is_gap_fill:
                    memory["_last_gap_buy_ts"]    = int(trade.timestamp)
                    memory["_last_gap_buy_price"] = trade_price
                    memory["_last_gap_buy_qty"]   = int(trade.quantity)

    def _handle_onesided_book(
        self,
        book:            BookSnapshot,
        position:        int,
        memory:          Dict[str, Any],
        gap_sell_quotes: List[int],
        gap_buy_quotes:  List[int],
    ) -> Optional[Tuple[List[Order], int]]:
        """Handle one-sided or fully empty order book by posting wide quotes.

        When both sides are absent, post a buy at last_known - shift and a sell
        at last_known + shift (if position allows). Returns early with those orders.
        When only one side is absent, post a single wide quote on the missing side.
        When both sides are present, returns None so normal logic continues.

        Also updates memory with last known best bid/ask and recent ask history
        before returning early.

        Params:
          empty_side_shift             — tick offset for wide quotes (default 85)
          ask_gap_sell_enable_position — min position to post a gap sell (default position_limit)
          ask_gap_quote_size           — max size for a gap sell quote (default 8)

        Returns (orders, 0) if the book is one-sided/empty, else None.
        """
        orders: List[Order] = []
        empty_side_shift          = int(self.params.get("empty_side_shift", 85))
        ask_gap_sell_enable_pos   = int(self.params.get("ask_gap_sell_enable_position", self.position_limit()))
        ask_gap_quote_size        = int(self.params.get("ask_gap_quote_size", 8))
        last_best_bid             = memory.get("_last_best_bid")
        last_best_ask             = memory.get("_last_best_ask")

        # Fully empty book
        if book.best_bid is None and book.best_ask is None:
            if last_best_bid is None and last_best_ask is None:
                return orders, 0
            ref           = last_best_bid if last_best_bid is not None else last_best_ask
            gap_buy_price = ref - empty_side_shift
            gap_sell_price = ref + empty_side_shift
            orders.append(Order(self.product, gap_buy_price, self.buy_capacity(position)))
            gap_buy_quotes.append(gap_buy_price)
            if position >= ask_gap_sell_enable_pos:
                gap_sell_qty = min(self.sell_capacity(position), ask_gap_quote_size)
                if gap_sell_qty > 0:
                    orders.append(Order(self.product, gap_sell_price, -gap_sell_qty))
                    gap_sell_quotes.append(gap_sell_price)
            memory["_active_gap_sell_quotes"] = gap_sell_quotes[:]
            memory["_active_gap_buy_quotes"]  = gap_buy_quotes[:]
            memory["_gap_sell_px"]            = gap_sell_quotes[:]
            memory["_gap_buy_px"]             = gap_buy_quotes[:]
            return orders, 0

        # Only asks visible — post a wide bid below last known bid
        if book.best_bid is None:
            ref           = last_best_bid if last_best_bid is not None else book.best_ask - 1
            gap_buy_price = ref - empty_side_shift
            orders.append(Order(self.product, gap_buy_price, self.buy_capacity(position)))
            gap_buy_quotes.append(gap_buy_price)

        # Only bids visible — post a wide ask above last known ask
        elif book.best_ask is None:
            ref            = last_best_ask if last_best_ask is not None else book.best_bid + 1
            gap_sell_price = ref + empty_side_shift
            if position >= ask_gap_sell_enable_pos:
                gap_sell_qty = min(self.sell_capacity(position), ask_gap_quote_size)
                if gap_sell_qty > 0:
                    orders.append(Order(self.product, gap_sell_price, -gap_sell_qty))
                    gap_sell_quotes.append(gap_sell_price)

        # Update last known prices and recent ask history
        if book.best_bid is not None:
            memory["_last_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_best_ask"] = book.best_ask
            recent_best_asks             = memory.setdefault("_recent_best_asks", [])
            gap_scout_recent_ask_window  = int(self.params.get("gap_scout_recent_ask_window", 6))
            recent_best_asks.append(int(book.best_ask))
            if len(recent_best_asks) > gap_scout_recent_ask_window:
                del recent_best_asks[:-gap_scout_recent_ask_window]

        # One side is still missing: flush trackers and return
        if book.best_bid is None or book.best_ask is None:
            memory["_active_gap_sell_quotes"] = gap_sell_quotes[:]
            memory["_active_gap_buy_quotes"]  = gap_buy_quotes[:]
            memory["_gap_sell_px"]            = gap_sell_quotes[:]
            memory["_gap_buy_px"]             = gap_buy_quotes[:]
            return orders, 0

        return None

    def _update_ewma_signals(
        self,
        spot:   float,
        fv:     float,
        memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float, float, float]:
        """Update slow/fast EWMAs, slope window, and derived stretch signals.

        ewma_fv    — slow EWMA of microprice (tracks the long-run trend level)
        short_ema  — fast EWMA of microprice (tracks short-term momentum)
        ewma_slope — change of ewma_fv over the last slope_window ticks
        stretch    — spot minus short_ema (positive = price running above MA)
        trim_reference — ewma_fv nudged forward by slope (signals for trimming)
        entry_reference — min(fv, trim_reference) used as bid anchor price

        Params:
          fv_alpha                  — slow EWMA alpha (default 0.05)
          short_alpha               — fast EWMA alpha (default 0.22)
          slope_window              — window for EWMA slope (default 20)
          trim_reference_slope_weight — weight applied to slope (default 0.15)

        Returns (ewma_fv, short_ema, ewma_slope, stretch, trim_reference, entry_reference).
        """
        fv_alpha     = float(self.params.get("fv_alpha", 0.05))
        short_alpha  = float(self.params.get("short_alpha", 0.22))
        slope_window = int(self.params.get("slope_window", 20))

        ewma_fv   = _ewma(memory.get("ewma_fv"), spot, fv_alpha)
        short_ema = _ewma(memory.get("short_ema"), spot, short_alpha)
        memory["ewma_fv"]   = ewma_fv
        memory["short_ema"] = short_ema

        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(ewma_fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[:-(slope_window + 1)]

        ewma_slope = 0.0
        if len(fv_hist) >= slope_window:
            ewma_slope = fv_hist[-1] - fv_hist[-slope_window]

        stretch         = spot - short_ema
        trim_reference  = ewma_fv + float(self.params.get("trim_reference_slope_weight", 0.15)) * max(0.0, ewma_slope)
        entry_reference = min(fv, trim_reference)

        return ewma_fv, short_ema, ewma_slope, stretch, trim_reference, entry_reference

    def _compute_regime(
        self,
        state:           TradingState,
        stats:           Dict[str, float],
        spot:            float,
        stretch:         float,
        book:            BookSnapshot,
        position: int,
        memory:   Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute all per-tick regime flags, inventory targets, and taker limits.

        Covers: bullish/build_phase/on_dip/chasing flags, startup sub-phases
        (fast/cold/chase/anchor), pullback tracking, gap_rebuy_mode, trim mode,
        and rebuy_blocked. Also derives buy_edge and buy_take_cap so that
        _buy_takers receives a fully resolved policy without re-reading params.

        Returns a dict with all flags needed downstream by _compute_quote_prices,
        _buy_takers, _sell_takers, _compute_passive_sizes, and _gap_trap_quotes.
        """
        trend_ticks = stats["trend_ticks"]
        residual_z  = stats["residual_z"]
        ts          = int(state.timestamp)

        # ── direction and build phase ──────────────────────────────────
        bull_threshold  = float(self.params.get("bull_threshold", 1.0))
        bullish         = trend_ticks > bull_threshold
        fastfill_target = int(self.params.get("fastfill_target", self.position_limit()))
        fastfill_end_ts = int(self.params.get("fastfill_end_ts", 15000))
        build_phase     = bullish and (position < fastfill_target or ts <= fastfill_end_ts)
        base_target     = self._inventory_target(state=state, stats=stats, position=position)
        inv_target      = max(base_target, fastfill_target) if build_phase else base_target

        # ── dip / chase signals ────────────────────────────────────────
        dip_threshold   = float(self.params.get("dip_threshold", 1.0))
        chase_threshold = float(self.params.get("chase_threshold", 1.25))
        cheap_z         = float(self.params.get("cheap_residual_z", 0.9))
        rich_z          = float(self.params.get("rich_residual_z", 1.0))
        on_dip          = bullish and (stretch <= -dip_threshold or residual_z <= -cheap_z)

        # ── startup sub-phases ─────────────────────────────────────────
        startup_fast_target           = int(self.params.get("startup_fast_target", min(fastfill_target, 32)))
        startup_fast_take_cap         = int(self.params.get("startup_fast_take_cap", 12))
        startup_fast_passive_buy      = int(self.params.get("startup_fast_passive_buy", 8))
        startup_cold_take_cap         = int(self.params.get("startup_cold_take_cap", 4))
        startup_cold_passive_buy      = int(self.params.get("startup_cold_passive_buy", 3))
        startup_cold_join_ticks       = int(self.params.get("startup_cold_join_ticks", 0))
        startup_cold_take_edge        = float(self.params.get("startup_cold_take_edge", 3.0))
        startup_chase_take_cap        = int(self.params.get("startup_chase_take_cap", 1))
        startup_chase_passive_buy     = int(self.params.get("startup_chase_passive_buy", 1))
        startup_chase_take_edge       = float(self.params.get("startup_chase_take_edge", 4.0))
        startup_pullback_ticks        = float(self.params.get("startup_pullback_ticks", 2.0))
        startup_pre_pullback_target   = int(self.params.get("startup_pre_pullback_target", 48))
        startup_post_pullback_target  = int(self.params.get("startup_post_pullback_target", 64))
        startup_delayed_finish_ts     = int(self.params.get("startup_delayed_finish_ts", 3000))
        startup_release_stretch       = float(self.params.get("startup_release_stretch", 1.0))
        startup_release_take_cap      = int(self.params.get("startup_release_take_cap", 8))
        startup_dip_take_edge_boost   = float(self.params.get("startup_dip_take_edge_boost", 1.0))
        startup_anchor_bid_spread     = float(self.params.get("startup_anchor_bid_spread", 1.0))
        startup_anchor_gap_ticks      = int(self.params.get("startup_anchor_gap_ticks", 1))
        startup_anchor_size           = int(self.params.get("startup_anchor_size", 4))

        startup_window_active = build_phase and ts <= fastfill_end_ts
        startup_fast_loading  = startup_window_active and position < startup_fast_target
        startup_cold_loading  = (
            startup_window_active
            and startup_fast_target <= position < inv_target
            and not on_dip
        )

        startup_peak_spot = float(memory.get("startup_peak_spot", spot))
        if startup_window_active:
            startup_peak_spot = max(startup_peak_spot, float(spot))
            memory["startup_peak_spot"] = startup_peak_spot
        else:
            memory["startup_peak_spot"] = float(spot)

        current_pullback_ready = startup_peak_spot - float(spot) >= startup_pullback_ticks
        pullback_seen          = bool(memory.get("startup_pullback_seen", False)) or current_pullback_ready
        memory["startup_pullback_seen"] = int(pullback_seen) if startup_window_active else 0

        build_release_ready = pullback_seen and stretch <= -startup_release_stretch

        active_build_target = inv_target
        if startup_window_active and ts <= startup_delayed_finish_ts and not build_release_ready:
            if not pullback_seen:
                active_build_target = min(active_build_target, startup_pre_pullback_target)
            else:
                active_build_target = min(active_build_target, startup_post_pullback_target)

        # ── gap rebuy mode ─────────────────────────────────────────────
        last_gap_sell_ts    = int(memory.get("_last_gap_sell_ts", -(10 ** 9)))
        last_gap_sell_price = memory.get("_last_gap_sell_price")
        gap_rebuy_window      = int(self.params.get("gap_rebuy_window", 2500))
        gap_rebuy_min_discount = float(self.params.get("gap_rebuy_min_discount", 20.0))
        gap_rebuy_age         = ts - last_gap_sell_ts
        gap_rebuy_discount    = 0.0
        if last_gap_sell_price is not None:
            gap_rebuy_discount = float(last_gap_sell_price) - float(book.best_ask)
        gap_rebuy_mode = (
            bullish
            and last_gap_sell_price is not None
            and 0 <= gap_rebuy_age <= gap_rebuy_window
            and position < inv_target
            and gap_rebuy_discount >= gap_rebuy_min_discount
        )
        if gap_rebuy_mode:
            active_build_target = inv_target

        chasing = bullish and not on_dip and (
            stretch >= chase_threshold
            or (startup_cold_loading and not pullback_seen)
        )

        # ── trim mode ──────────────────────────────────────────────────
        trim_start_position      = int(self.params.get("trim_start_position", 79))
        trim_extension_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        trim_quote_mode = (
            bullish
            and not build_phase
            and position >= trim_start_position
            and stretch >= trim_extension_threshold
        )
        trim_take_mode = False
        trim_take_qty  = 0

        # ── rebuy block ────────────────────────────────────────────────
        rebuy_block_until = int(memory.get("rebuy_block_until", -(10 ** 9)))
        rebuy_blocked     = bullish and ts < rebuy_block_until

        # ── buy edge ──────────────────────────────────────────────────
        take_buy_edge_bull      = float(self.params.get("take_buy_edge_bull", -8.0))
        take_buy_edge_neut      = float(self.params.get("take_buy_edge_neut", 2.0))
        fastfill_buy_edge_boost = float(self.params.get("fastfill_buy_edge_boost", 0.0))

        if bullish:
            buy_edge = take_buy_edge_bull
            if build_phase:
                buy_edge -= fastfill_buy_edge_boost
            elif residual_z >= rich_z:
                buy_edge = take_buy_edge_neut
            if on_dip:
                buy_edge -= startup_dip_take_edge_boost
            if startup_cold_loading:
                buy_edge = max(buy_edge, startup_cold_take_edge)
            if chasing:
                buy_edge = max(buy_edge, startup_chase_take_edge)
        else:
            buy_edge = take_buy_edge_neut

        buy_cap_initial = self.buy_capacity(position)
        buy_take_cap    = buy_cap_initial
        if build_phase:
            if startup_fast_loading:
                buy_take_cap = min(buy_take_cap, startup_fast_take_cap)
            if startup_cold_loading:
                buy_take_cap = min(buy_take_cap, startup_cold_take_cap)
            if chasing:
                buy_take_cap = min(buy_take_cap, startup_chase_take_cap)
            if build_release_ready:
                buy_take_cap = min(buy_take_cap, startup_release_take_cap)

        if rebuy_blocked:
            buy_edge     = 1_000_000.0
            buy_take_cap = 0
        elif gap_rebuy_mode:
            gap_rebuy_buy_edge  = float(self.params.get("gap_rebuy_buy_edge", -10.0))
            gap_rebuy_take_cap  = int(self.params.get("gap_rebuy_take_cap", 8))
            buy_edge     = min(buy_edge, gap_rebuy_buy_edge)
            buy_take_cap = min(buy_cap_initial, max(buy_take_cap, gap_rebuy_take_cap))

        return {
            "timestamp":              ts,
            "bullish":                bullish,
            "build_phase":            build_phase,
            "inv_target":             inv_target,
            "active_build_target":    active_build_target,
            "on_dip":                 on_dip,
            "startup_window_active":  startup_window_active,
            "startup_fast_loading":   startup_fast_loading,
            "startup_cold_loading":   startup_cold_loading,
            "startup_fast_passive_buy":  startup_fast_passive_buy,
            "startup_cold_passive_buy":  startup_cold_passive_buy,
            "startup_chase_passive_buy": startup_chase_passive_buy,
            "startup_anchor_bid_spread": startup_anchor_bid_spread,
            "startup_anchor_gap_ticks":  startup_anchor_gap_ticks,
            "startup_anchor_size":       startup_anchor_size,
            "startup_cold_join_ticks":   startup_cold_join_ticks,
            "pullback_seen":          pullback_seen,
            "current_pullback_ready": current_pullback_ready,
            "build_release_ready":    build_release_ready,
            "gap_rebuy_mode":         gap_rebuy_mode,
            "gap_rebuy_discount":     gap_rebuy_discount,
            "chasing":                chasing,
            "rebuy_blocked":          rebuy_blocked,
            "buy_edge":               buy_edge,
            "buy_take_cap":           buy_take_cap,
            "trim_quote_mode":        trim_quote_mode,
            "trim_take_mode":         trim_take_mode,
            "trim_take_qty":          trim_take_qty,
            "rich_z":                 rich_z,
            "cheap_z":                cheap_z,
        }

    def _compute_quote_prices(
        self,
        book:            BookSnapshot,
        fv:              float,
        stats:           Dict[str, float],
        regime:          Dict[str, Any],
        entry_reference: float,
    ) -> Tuple[int, int]:
        """Compute passive bid and ask quote prices.

        Base prices are derived from fair value ± spread (bull or neutral).
        bid_extra ticks are added based on trend strength and residual cheapness.
        During build phase, bid_price is nudged up toward entry_reference to
        capture more of the trend move in cold/chase sub-phases.

        Returns (bid_price, ask_price) — both sides guaranteed non-None here
        since _handle_onesided_book has already filtered the one-sided case.
        """
        bullish             = regime["bullish"]
        build_phase         = regime["build_phase"]
        startup_cold_loading = regime["startup_cold_loading"]
        chasing             = regime["chasing"]
        trend_ticks         = stats["trend_ticks"]
        residual_z          = stats["residual_z"]
        cheap_z             = regime["cheap_z"]

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))

        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)

        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # Trend / residual bid extras
        bid_extra   = 0
        strong      = float(self.params.get("strong_trend_ticks", 1.1))
        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        if trend_ticks >= strong:
            bid_extra += 1
        if trend_ticks >= very_strong:
            bid_extra += 1
        if residual_z <= -cheap_z:
            bid_extra += 1

        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        bid_extra     = max(0, min(max_bid_extra, bid_extra))
        bid_price     = min(book.best_ask - 1, bid_price + bid_extra)

        # Build-phase bid anchoring
        startup_anchor_bid_spread = regime["startup_anchor_bid_spread"]
        startup_cold_join_ticks   = regime["startup_cold_join_ticks"]
        if build_phase:
            if startup_cold_loading or chasing:
                raw_entry_bid = round(entry_reference - startup_anchor_bid_spread)
                bid_price     = min(book.best_ask - 1, max(raw_entry_bid, 1))
                bid_price     = max(bid_price, min(book.best_bid + startup_cold_join_ticks, book.best_ask - 1))
            else:
                bid_price = max(bid_price, min(book.best_bid + 1, book.best_ask - 1))

        return bid_price, ask_price

    def _buy_takers(
        self,
        order_depth: OrderDepth,
        fv:          float,
        position:    int,
        buy_cap:     int,
        regime:      Dict[str, Any],
    ) -> Tuple[List[Order], int, int, Set[int]]:
        """Emit aggressive buy orders when ask price is below the fair-value edge.

        Iterates sell_orders from cheapest upward, buying each level while:
          - ask_p <= fv - buy_edge  (fair-value condition)
          - buy_cap and buy_take_cap > 0  (capacity guards)
          - During build phase: room to active_build_target is not exhausted

        deep_take_guard restricts multi-level taker sweeps during early ticks
        to avoid paying too far through the market.

        Returns (orders, remaining_buy_cap, pending_buy, swept_ask_prices).
        """
        orders:         List[Order] = []
        swept_prices:   Set[int]    = set()
        pending_buy     = 0
        buy_take_cap    = regime["buy_take_cap"]

        build_phase         = regime["build_phase"]
        active_build_target = regime["active_build_target"]
        buy_edge            = regime["buy_edge"]
        ts                  = regime["timestamp"]

        deep_take_guard_end_ts = int(self.params.get("fastfill_deep_take_guard_end_ts", 0))
        deep_take_max_gap      = int(self.params.get("fastfill_deep_take_max_gap_ticks", 999999))
        deep_take_guard        = build_phase and ts <= deep_take_guard_end_ts
        first_take_ask: Optional[int] = None

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0 or buy_take_cap <= 0:
                break
            room = max(0, active_build_target - position - pending_buy)
            if build_phase and room <= 0:
                break
            if first_take_ask is None:
                first_take_ask = ask_p
            elif deep_take_guard and ask_p - first_take_ask > deep_take_max_gap:
                break
            qty = min(
                -order_depth.sell_orders[ask_p],
                buy_cap,
                buy_take_cap,
                room if build_phase else buy_cap,
            )
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            swept_prices.add(ask_p)
            buy_cap     -= qty
            buy_take_cap -= qty
            pending_buy  += qty

        return orders, buy_cap, pending_buy, swept_prices

    def _sell_takers(
        self,
        order_depth: OrderDepth,
        fv:          float,
        position:    int,
        sell_cap:    int,
        regime:      Dict[str, Any],
    ) -> Tuple[List[Order], int, int]:
        """Emit aggressive sell orders for neutral unwind (non-bullish, non-trim regimes).

        Only fires when: not build_phase AND not trim_quote_mode AND not bullish.
        Sell edge is tightened proportionally when position is above inv_target
        to accelerate unwind under inventory pressure.

        Returns (orders, remaining_sell_cap, pending_sell).
        """
        orders:      List[Order] = []
        pending_sell = 0

        build_phase     = regime["build_phase"]
        trim_quote_mode = regime["trim_quote_mode"]
        bullish         = regime["bullish"]
        inv_target      = regime["inv_target"]

        if not build_phase and not trim_quote_mode and not bullish:
            sell_edge = float(self.params.get("take_sell_edge_neut", 2.0))
            if position > inv_target:
                pressure  = min(1.0, (position - inv_target) / max(1.0, float(self.position_limit())))
                sell_edge = sell_edge - float(self.params.get("unwind_take_edge", 10.0)) * pressure
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fv + sell_edge or sell_cap <= 0:
                    break
                qty = min(order_depth.buy_orders[bid_p], sell_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap     -= qty
                pending_sell += qty

        return orders, sell_cap, pending_sell

    def _compute_passive_sizes(
        self,
        position:         int,
        buy_cap:          int,
        sell_cap:         int,
        pending_buy:      int,
        pending_sell:     int,
        stats:            Dict[str, float],
        regime:           Dict[str, Any],
        entry_reference:  float,
        book:             BookSnapshot,
        bid_price:        int,
        ask_price:        int,
        buy_taker_prices: Set[int],
    ) -> Tuple[int, int, Optional[int], int, int, bool]:
        """Compute passive bid/ask sizes, anchor order, and final ask_price.

        Sizing via _size_from_target; then adjusted for:
          - build_phase overrides (suppress sells, cap/floor buys by sub-phase)
          - anchor bid in cold/chase sub-phases (secondary bid at entry_reference)
          - gap_rebuy_mode (boost passive buy, cap to inv_target room)
          - hold_sell_size logic (passive sell at top of book when near max position)
          - rebuy_block (zero buys while blocked)
          - crossing prevention (ask_price = bid_price + 1 if crossed)

        Returns (buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode).
        """
        build_phase         = regime["build_phase"]
        gap_rebuy_mode      = regime["gap_rebuy_mode"]
        bullish             = regime["bullish"]
        rebuy_blocked       = regime["rebuy_blocked"]
        inv_target          = regime["inv_target"]
        active_build_target = regime["active_build_target"]
        on_dip              = regime["on_dip"]
        chasing             = regime["chasing"]
        startup_fast_loading     = regime["startup_fast_loading"]
        startup_cold_loading     = regime["startup_cold_loading"]
        startup_fast_passive_buy = regime["startup_fast_passive_buy"]
        startup_cold_passive_buy = regime["startup_cold_passive_buy"]
        startup_chase_passive_buy = regime["startup_chase_passive_buy"]
        startup_anchor_bid_spread = regime["startup_anchor_bid_spread"]
        startup_anchor_gap_ticks  = regime["startup_anchor_gap_ticks"]
        startup_anchor_size       = regime["startup_anchor_size"]

        # Effective best ask after filtering taker-swept levels
        real_best_bid = book.best_bid
        real_best_ask = book.best_ask
        for ap, _ in book.ask_levels:
            if ap not in buy_taker_prices:
                real_best_ask = ap
                break

        buy_size, sell_size = self._size_from_target(
            position=position + pending_buy - pending_sell,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        anchor_buy_price: Optional[int] = None
        anchor_buy_size                 = 0
        anchor_mode                     = False

        if build_phase:
            sell_size = 0
            if startup_fast_loading:
                buy_size = min(buy_size, min(buy_cap, startup_fast_passive_buy))
            elif startup_cold_loading:
                buy_size = min(buy_size, min(buy_cap, startup_cold_passive_buy))
            else:
                buy_size = max(buy_size, min(buy_cap, int(self.params.get("fastfill_min_passive_buy", 20))))
            if chasing:
                buy_size = min(buy_size, min(buy_cap, startup_chase_passive_buy))
            buy_size = min(buy_size, max(0, active_build_target - position - pending_buy))

            anchor_mode = bullish and not on_dip and (startup_cold_loading or chasing)
            if anchor_mode and buy_cap > buy_size:
                raw_anchor_bid       = round(entry_reference - startup_anchor_bid_spread)
                candidate_anchor_bid = min(max(raw_anchor_bid, 1), real_best_ask - 1)
                candidate_anchor_bid = min(candidate_anchor_bid, bid_price - startup_anchor_gap_ticks)
                if candidate_anchor_bid >= 1:
                    anchor_buy_price = candidate_anchor_bid
                    anchor_buy_size  = min(max(1, startup_anchor_size), max(0, buy_cap - buy_size))

        if gap_rebuy_mode:
            gap_rebuy_passive_buy = int(self.params.get("gap_rebuy_passive_buy", 6))
            buy_size = max(buy_size, min(buy_cap, gap_rebuy_passive_buy))
            buy_size = min(buy_size, max(0, inv_target - position - pending_buy))

        hold_sell_size   = int(self.params.get("hold_sell_size", 1))
        hold_sell_offset = int(self.params.get("hold_sell_offset", 0))
        if not build_phase and bullish and position >= self.position_limit() - hold_sell_size + 1:
            sell_size = min(sell_cap, hold_sell_size)
            ask_price = max(real_best_bid + 1, real_best_ask + hold_sell_offset)
        elif not build_phase and bullish:
            sell_size = 0

        if rebuy_blocked:
            buy_size = 0

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        return buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode

    def _gap_trap_quotes(
        self,
        book:           BookSnapshot,
        position:       int,
        memory:         Dict[str, Any],
        sell_cap:       int,
        ask_price:      int,
        trend_ticks:    float,
        gap_rebuy_mode: bool,
    ) -> Tuple[List[Order], List[int]]:
        """Arm and post gap-trap sell orders when the ask side is persistently fragile.

        Fragility is defined as: only one ask level, OR the gap to the second ask
        level exceeds gap_trap_min_gap, OR top-of-book volume is thin AND imbalance
        supports the bull case.

        Once the ask side has been fragile for gap_trap_arm_streak consecutive ticks
        and position >= gap_trap_floor_position, the trap is armed. A passive SELL is
        posted at anchor_ask + empty_side_shift. An optional premium order is added
        at peak_ask + empty_side_shift + premium_extra after gap_trap_premium_streak.

        The trap is cleared when position drops below the floor, gap_rebuy_mode is
        active, or gap_trap_clear_after consecutive non-fragile ticks occur.

        Params:
          gap_trap_arm_streak, gap_trap_clear_after, gap_trap_floor_position
          gap_trap_min_gap, gap_trap_top_ask_max, gap_trap_min_imbalance
          gap_trap_recent_ask_window, gap_trap_fragile_ask_window
          gap_trap_base_size, gap_trap_premium_size, gap_trap_premium_streak
          gap_trap_premium_extra, empty_side_shift

        Returns (orders, gap_sell_prices_list).
        """
        orders:              List[Order] = []
        gap_sell_prices:     List[int]   = []
        empty_side_shift     = int(self.params.get("empty_side_shift", 85))

        # Restore persisted trap state
        gap_trap_fragile_streak = int(memory.get("_gap_trap_fragile_streak", 0))
        gap_trap_clear_streak   = int(memory.get("_gap_trap_clear_streak", 0))
        gap_trap_anchor_ask     = memory.get("_gap_trap_anchor_ask")
        gap_trap_peak_ask       = memory.get("_gap_trap_peak_ask")

        gap_trap_floor_position   = int(self.params.get("gap_trap_floor_position", 78))
        gap_trap_arm_streak       = int(self.params.get("gap_trap_arm_streak", 2))
        gap_trap_clear_after      = int(self.params.get("gap_trap_clear_after", 2))
        gap_trap_min_trend        = float(self.params.get("gap_trap_min_trend", 0.0))
        gap_trap_min_gap          = int(self.params.get("gap_trap_min_gap", 3))
        gap_trap_top_ask_max      = int(self.params.get("gap_trap_top_ask_max", 10))
        gap_trap_min_imbalance    = float(self.params.get("gap_trap_min_imbalance", 0.05))
        gap_trap_recent_ask_window  = int(self.params.get("gap_trap_recent_ask_window", 8))
        gap_trap_fragile_ask_window = int(self.params.get("gap_trap_fragile_ask_window", 4))
        gap_trap_base_size          = int(self.params.get("gap_trap_base_size", 3))
        gap_trap_premium_size_limit = int(self.params.get("gap_trap_premium_size", 2))
        gap_trap_premium_streak     = int(self.params.get("gap_trap_premium_streak", 3))
        gap_trap_premium_extra      = int(self.params.get("gap_trap_premium_extra", 2))

        # Fragility detection
        ask_gap_fragile      = len(book.ask_levels) == 1
        if len(book.ask_levels) >= 2:
            ask_gap_fragile  = ask_gap_fragile or (book.ask_levels[1][0] - book.ask_levels[0][0] >= gap_trap_min_gap)
        ask_size_fragile     = book.best_ask_volume > 0 and book.best_ask_volume <= gap_trap_top_ask_max
        imbalance_supportive = book.imbalance is None or book.imbalance >= gap_trap_min_imbalance
        ask_side_fragile     = ask_gap_fragile or (ask_size_fragile and imbalance_supportive)

        # Rolling ask history for anchor and peak tracking
        trap_recent_asks = memory.setdefault("_gap_trap_recent_asks", [])
        trap_recent_asks.append(int(book.best_ask))
        if len(trap_recent_asks) > gap_trap_recent_ask_window:
            del trap_recent_asks[:-gap_trap_recent_ask_window]

        trap_fragile_asks = memory.setdefault("_gap_trap_fragile_asks", [])
        if ask_side_fragile:
            trap_fragile_asks.append(int(book.best_ask))
            if len(trap_fragile_asks) > gap_trap_fragile_ask_window:
                del trap_fragile_asks[:-gap_trap_fragile_ask_window]
        else:
            trap_fragile_asks[:] = []

        # Streak update
        trap_armable = trend_ticks >= gap_trap_min_trend and not gap_rebuy_mode and position >= gap_trap_floor_position
        if trap_armable and ask_side_fragile:
            gap_trap_fragile_streak += 1
            gap_trap_clear_streak    = 0
        elif gap_trap_anchor_ask is not None:
            gap_trap_clear_streak   += 1
            gap_trap_fragile_streak  = max(0, gap_trap_fragile_streak - 1)
        else:
            gap_trap_fragile_streak  = 0
            gap_trap_clear_streak    = 0

        # Arm trap
        if gap_trap_anchor_ask is None and trap_armable and gap_trap_fragile_streak >= gap_trap_arm_streak and trap_recent_asks:
            gap_trap_anchor_ask = min(trap_recent_asks)
            gap_trap_peak_ask   = max(trap_fragile_asks) if trap_fragile_asks else int(book.best_ask)

        # Update or disarm trap
        if gap_trap_anchor_ask is not None:
            if not trap_armable or gap_trap_clear_streak >= gap_trap_clear_after:
                gap_trap_anchor_ask = None
                gap_trap_peak_ask   = None
                gap_trap_fragile_streak = 0
                gap_trap_clear_streak   = 0
            else:
                if trap_recent_asks:
                    gap_trap_anchor_ask = min(int(gap_trap_anchor_ask), min(trap_recent_asks))
                if trap_fragile_asks:
                    latest_peak       = max(trap_fragile_asks)
                    gap_trap_peak_ask = max(int(gap_trap_peak_ask or latest_peak), latest_peak)

        # Build trap orders
        gap_trap_sell_price    = None
        gap_trap_sell_size     = 0
        gap_trap_premium_price = None
        gap_trap_premium_size  = 0
        gap_trap_active        = False
        gap_trap_armed         = False

        if gap_trap_anchor_ask is not None:
            gap_trap_armed          = True
            candidate_gap_trap_sell = int(gap_trap_anchor_ask) + empty_side_shift
            if candidate_gap_trap_sell > ask_price:
                gap_trap_sell_price = candidate_gap_trap_sell
                gap_trap_sell_size  = min(
                    sell_cap,
                    gap_trap_base_size,
                    max(0, position - gap_trap_floor_position + 1),
                )
                gap_trap_active = gap_trap_sell_size > 0

            if (
                gap_trap_peak_ask is not None
                and gap_trap_fragile_streak >= gap_trap_premium_streak
                and sell_cap > gap_trap_sell_size
            ):
                candidate_gap_trap_premium = max(
                    (gap_trap_sell_price or ask_price) + gap_trap_premium_extra,
                    int(gap_trap_peak_ask) + empty_side_shift + gap_trap_premium_extra,
                )
                if candidate_gap_trap_premium > (gap_trap_sell_price or ask_price):
                    gap_trap_premium_price = candidate_gap_trap_premium
                    gap_trap_premium_size  = min(
                        max(0, sell_cap - gap_trap_sell_size),
                        gap_trap_premium_size_limit,
                        max(0, position - gap_trap_floor_position),
                    )
                    gap_trap_active = gap_trap_active or gap_trap_premium_size > 0

        if gap_trap_sell_size > 0 and gap_trap_sell_price is not None:
            orders.append(Order(self.product, gap_trap_sell_price, -gap_trap_sell_size))
            gap_sell_prices.append(gap_trap_sell_price)
        if gap_trap_premium_size > 0 and gap_trap_premium_price is not None:
            orders.append(Order(self.product, gap_trap_premium_price, -gap_trap_premium_size))
            gap_sell_prices.append(gap_trap_premium_price)

        # Persist updated trap state
        memory["_gap_trap_fragile_streak"] = gap_trap_fragile_streak
        memory["_gap_trap_clear_streak"]   = gap_trap_clear_streak
        memory["_gap_trap_anchor_ask"]     = gap_trap_anchor_ask
        memory["_gap_trap_peak_ask"]       = gap_trap_peak_ask
        memory["gap_trap_active"]          = int(gap_trap_active)
        memory["gap_trap_armed"]           = int(gap_trap_armed)

        return orders, gap_sell_prices

    # ── order construction ───────────────────────────────────────────────

    def compute_orders(
        self,
        state:       TradingState,
        book:        BookSnapshot,
        order_depth: OrderDepth,
        position:    int,
        memory:      Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        # ── PREMIUM FILL DETECTION ─────────────────────────────────────
        self._process_premium_fills(state, memory)

        # ── RESET QUOTE TRACKERS ───────────────────────────────────────
        gap_sell_quotes: List[int] = []
        gap_buy_quotes:  List[int] = []
        memory["_active_gap_sell_quotes"] = []
        memory["_active_gap_buy_quotes"]  = []
        memory["_gap_sell_px"]            = []
        memory["_gap_buy_px"]             = []

        # ── ONE-SIDED / EMPTY BOOK ─────────────────────────────────────
        onesided = self._handle_onesided_book(book, position, memory, gap_sell_quotes, gap_buy_quotes)
        if onesided is not None:
            return onesided

        # Update last known prices and recent ask window (normal book path)
        if book.best_bid is not None:
            memory["_last_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_best_ask"] = book.best_ask
            recent_best_asks            = memory.setdefault("_recent_best_asks", [])
            gap_scout_recent_ask_window = int(self.params.get("gap_scout_recent_ask_window", 6))
            recent_best_asks.append(int(book.best_ask))
            if len(recent_best_asks) > gap_scout_recent_ask_window:
                del recent_best_asks[:-gap_scout_recent_ask_window]

        # ── REGRESSION + FAIR VALUE ────────────────────────────────────
        mid   = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        fv    = stats["fair_value"]

        # ── EWMA SIGNALS ───────────────────────────────────────────────
        spot = book.microprice if book.microprice is not None else mid
        _, _, _, stretch, trim_reference, entry_reference = (
            self._update_ewma_signals(spot, fv, memory)
        )

        # ── REGIME FLAGS ───────────────────────────────────────────────
        regime = self._compute_regime(state, stats, spot, stretch, book, position, memory)

        # ── QUOTE PRICES ───────────────────────────────────────────────
        bid_price, ask_price = self._compute_quote_prices(book, fv, stats, regime, entry_reference)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── BUY TAKERS ─────────────────────────────────────────────────
        buy_orders, buy_cap, pending_buy, swept_ask_prices = self._buy_takers(
            order_depth, fv, position, buy_cap, regime
        )

        # ── SELL TAKERS ────────────────────────────────────────────────
        sell_orders, sell_cap, pending_sell = self._sell_takers(
            order_depth, fv, position, sell_cap, regime
        )

        # ── PASSIVE SIZING ─────────────────────────────────────────────
        buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode = (
            self._compute_passive_sizes(
                position, buy_cap, sell_cap, pending_buy, pending_sell,
                stats, regime, entry_reference, book, bid_price, ask_price, swept_ask_prices,
            )
        )

        # ── GAP TRAP ───────────────────────────────────────────────────
        gap_trap_orders, gap_trap_sell_prices = self._gap_trap_quotes(
            book, position, memory, sell_cap, ask_price,
            stats["trend_ticks"], regime["gap_rebuy_mode"],
        )
        gap_sell_quotes.extend(gap_trap_sell_prices)

        # ── ASSEMBLE ORDERS ────────────────────────────────────────────
        orders: List[Order] = buy_orders + sell_orders
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if anchor_buy_size > 0 and anchor_buy_price is not None:
            orders.append(Order(self.product, anchor_buy_price, anchor_buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))
        orders.extend(gap_trap_orders)

        # ── MEMORY WRITES ──────────────────────────────────────────────
        memory["last_bid_price"]       = bid_price
        memory["last_ask_price"]       = ask_price
        memory["entry_reference"]      = entry_reference
        memory["inv_target"]           = regime["inv_target"]
        memory["active_build_target"]  = regime["active_build_target"]
        memory["bullish"]              = int(regime["bullish"])
        memory["build_phase"]          = int(regime["build_phase"])
        memory["on_dip"]               = int(regime["on_dip"])
        memory["chasing"]              = int(regime["chasing"])
        memory["anchor_mode"]          = int(anchor_mode)
        memory["startup_fast_loading"] = int(regime["startup_fast_loading"])
        memory["startup_cold_loading"] = int(regime["startup_cold_loading"])
        memory["pullback_ready"]       = int(regime["current_pullback_ready"])
        memory["pullback_seen"]        = int(regime["pullback_seen"])
        memory["build_release_ready"]  = int(regime["build_release_ready"])
        memory["gap_rebuy_mode"]       = int(regime["gap_rebuy_mode"])
        memory["gap_rebuy_discount"]   = regime["gap_rebuy_discount"]
        memory["trim_quote_mode"]      = int(regime["trim_quote_mode"])
        memory["trim_take_mode"]       = int(regime["trim_take_mode"])
        memory["rebuy_blocked"]        = int(regime["rebuy_blocked"])
        memory["stretch"]              = stretch
        memory["_active_gap_sell_quotes"] = sorted(set(gap_sell_quotes))
        memory["_active_gap_buy_quotes"]  = sorted(set(gap_buy_quotes))
        memory["_gap_sell_px"]            = memory["_active_gap_sell_quotes"]
        memory["_gap_buy_px"]             = memory["_active_gap_buy_quotes"]

        # ── LOGGING ────────────────────────────────────────────────────
        trend_ticks = stats["trend_ticks"]
        gap_trap_armed          = bool(memory.get("gap_trap_armed", 0))
        gap_trap_active         = bool(memory.get("gap_trap_active", 0))
        gap_trap_fragile_streak = int(memory.get("_gap_trap_fragile_streak", 0))
        gap_trap_anchor_ask     = memory.get("_gap_trap_anchor_ask")
        gap_trap_peak_ask       = memory.get("_gap_trap_peak_ask")
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position":              position,
                "trend_ticks":           round(trend_ticks, 2),
                "fair_value":            round(fv, 2),
                "stretch":               round(stretch, 2),
                "trim_ref":              round(trim_reference, 2),
                "entry_ref":             round(entry_reference, 2),
                "inv_target":            regime["inv_target"],
                "active_build_target":   regime["active_build_target"],
                "bullish":               int(regime["bullish"]),
                "build_phase":           int(regime["build_phase"]),
                "on_dip":                int(regime["on_dip"]),
                "chasing":               int(regime["chasing"]),
                "pullback_ready":        int(regime["current_pullback_ready"]),
                "pullback_seen":         int(regime["pullback_seen"]),
                "build_release_ready":   int(regime["build_release_ready"]),
                "gap_rebuy_mode":        int(regime["gap_rebuy_mode"]),
                "gap_rebuy_discount":    round(regime["gap_rebuy_discount"], 2),
                "anchor_mode":           int(anchor_mode),
                "startup_fast_loading":  int(regime["startup_fast_loading"]),
                "startup_cold_loading":  int(regime["startup_cold_loading"]),
                "buy_size":              buy_size,
                "sell_size":             sell_size,
                "anchor_buy_price":      anchor_buy_price,
                "anchor_buy_size":       anchor_buy_size,
                "gap_trap_active":       int(gap_trap_active),
                "gap_trap_armed":        int(gap_trap_armed),
                "gap_trap_fragile_streak": gap_trap_fragile_streak,
                "gap_trap_anchor_ask":   gap_trap_anchor_ask,
                "gap_trap_peak_ask":     gap_trap_peak_ask,
                "trim_quote_mode":       int(regime["trim_quote_mode"]),
                "trim_take_mode":        int(regime["trim_take_mode"]),
                "trim_take_qty":         regime["trim_take_qty"],
                "rebuy_blocked":         int(regime["rebuy_blocked"]),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        stats = memory.get("regression_stats")
        if stats:
            out["reg_fair_value"] = float(stats["fair_value"])
        if memory.get("ewma_fv") is not None:
            out["ewma_fv"] = memory["ewma_fv"]
        if memory.get("short_ema") is not None:
            out["short_ema"] = memory["short_ema"]
        if memory.get("entry_reference") is not None:
            out["entry_reference"] = memory["entry_reference"]
        return out

# ── Config ────────────────────────────────────────────────────────────────────
