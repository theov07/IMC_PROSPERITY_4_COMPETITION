"""Trend carry market maker — modular refactor of V34.

Same logic as V34, reorganised into focused helper methods:

    _update_signals        — EWMA FV, slope, stretch, price references
    _detect_regime         — bullish / on_dip / chasing / startup flags
    _compute_inv_target    — dynamic inventory target from trend strength
    _taker_edges_and_caps  — per-regime taker edge and size limits
    _taker_reference       — fair-value reference used for taker thresholds
    _take_orders           — execute aggressive orders against the book
    _real_best_after_sweeps— best bid/ask after removing swept levels
    _eval_trim_modes       — trim_quote_mode and trim_take_mode flags
    _size_quotes           — base quote sizes with inventory-pressure skew
    _adjust_sizes_for_regime — per-regime size multipliers
    _compute_bid_price     — final passive bid price
    _compute_ask_price     — final passive ask price
    _apply_suppress_and_override — sell suppression / trim override / rebuy block
    _compute_anchor_bid    — V18-style cold anchor bid
    compute_orders         — orchestrates all stages, returns orders
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


# ---------------------------------------------------------------------------
# State containers (lightweight, no validation overhead)
# ---------------------------------------------------------------------------

@dataclass
class _Signals:
    """Price signals computed each tick."""
    spot: float
    fv: float
    short_ema: float
    slope: float
    stretch: float
    fair: float
    trim_reference: float
    entry_reference: float


@dataclass
class _Regime:
    """Discrete market regime flags."""
    bullish: bool
    on_dip: bool
    chasing: bool
    startup_loading: bool


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class TrendCarryWindowStrategy(BaseStrategy):

    # ------------------------------------------------------------------
    # Stage 1 — price signal computation
    # ------------------------------------------------------------------

    def _update_signals(self, spot: float, memory: Dict[str, Any]) -> _Signals:
        """EWMA fair value, short EMA, slope, stretch, and derived price references.

        Writes to memory: ``fv``, ``short_ema``, ``fv_hist``.
        """
        fv_alpha = float(self.params.get("fv_alpha", 0.05))
        short_alpha = float(self.params.get("short_alpha", 0.22))
        slope_window = int(self.params.get("slope_window", 20))
        trend_weight = float(self.params.get("trend_weight", 0.55))
        stretch_weight = float(self.params.get("stretch_weight", 0.75))
        trim_slope_w = float(self.params.get("trim_reference_slope_weight", 0.15))
        entry_slope_w = float(self.params.get("entry_reference_slope_weight", 0.18))

        fv = _ewma(memory.get("fv"), spot, fv_alpha)
        short_ema = _ewma(memory.get("short_ema"), spot, short_alpha)
        memory["fv"] = fv
        memory["short_ema"] = short_ema

        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[:-(slope_window + 1)]

        slope = fv_hist[-1] - fv_hist[-slope_window] if len(fv_hist) >= slope_window else 0.0
        stretch = spot - short_ema

        fair = fv + trend_weight * slope - stretch_weight * stretch
        trim_reference = fv + trim_slope_w * max(0.0, slope)
        entry_reference = min(fair, fv + entry_slope_w * max(0.0, slope))

        return _Signals(
            spot=spot, fv=fv, short_ema=short_ema, slope=slope, stretch=stretch,
            fair=fair, trim_reference=trim_reference, entry_reference=entry_reference,
        )

    # ------------------------------------------------------------------
    # Stage 2 — regime detection
    # ------------------------------------------------------------------

    def _detect_regime(self, sig: _Signals, timestamp: int) -> _Regime:
        """Classify the current market environment into discrete flags."""
        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        dip_threshold = float(self.params.get("dip_threshold", 1.5))
        chase_threshold = float(self.params.get("chase_threshold", 2.5))
        startup_ticks = int(self.params.get("startup_ticks", 15000))

        bullish = sig.slope > bull_threshold
        on_dip = bullish and sig.stretch <= -dip_threshold
        chasing = bullish and sig.stretch >= chase_threshold and not on_dip
        startup_loading = bullish and timestamp <= startup_ticks

        return _Regime(bullish=bullish, on_dip=on_dip, chasing=chasing, startup_loading=startup_loading)

    # ------------------------------------------------------------------
    # Stage 3 — inventory target
    # ------------------------------------------------------------------

    def _compute_inv_target(self, regime: _Regime, sig: _Signals) -> int:
        """Dynamic long inventory target scaled to trend strength.

        Returns 0 (neutral) when not bullish.
        """
        if not regime.bullish:
            return int(self.params.get("neutral_target", 0))

        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        target_base = int(self.params.get("target_bull_base", 64))
        target_min = int(self.params.get("target_bull_min", 56))
        target_max = int(self.params.get("target_bull_max", 78))
        per_tick = float(self.params.get("target_bull_per_tick", 2.0))
        startup_target = int(self.params.get("startup_target", 78))
        dip_target = int(self.params.get("dip_target", 80))

        dyn = target_base + per_tick * max(0.0, sig.slope - bull_threshold)
        inv_target = int(round(max(target_min, min(target_max, dyn))))

        if regime.startup_loading:
            inv_target = max(inv_target, startup_target)
        if regime.on_dip:
            inv_target = max(inv_target, dip_target)

        return min(self.position_limit(), inv_target)

    # ------------------------------------------------------------------
    # Stage 4 — pre-trim signal (needed before taker caps)
    # ------------------------------------------------------------------

    def _is_pre_trim_signal(
        self,
        regime: _Regime,
        sig: _Signals,
        position: int,
        best_bid: int,
    ) -> bool:
        """True when inventory is elevated and price action suggests an imminent trim."""
        trim_start = int(self.params.get("trim_start_position", 76))
        trim_floor = int(self.params.get("trim_floor_position", 72))
        ext_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        signal_edge = float(self.params.get("trim_signal_edge", 0.75))

        return (
            regime.bullish
            and position > trim_floor
            and position >= trim_start
            and sig.stretch >= ext_threshold
            and best_bid >= sig.trim_reference + signal_edge
        )

    # ------------------------------------------------------------------
    # Stage 5 — taker parameters
    # ------------------------------------------------------------------

    def _taker_edges_and_caps(
        self,
        regime: _Regime,
        position: int,
        inv_target: int,
        rebuy_blocked: bool,
        pre_trim_signal: bool,
    ) -> Tuple[float, float, int, int]:
        """Return (buy_edge, sell_edge, buy_take_cap, sell_take_cap).

        Edge semantics: buy if ask <= fair - buy_edge (negative = more aggressive).
        """
        max_buy = int(self.params.get("max_take_buy_size", 12))
        max_sell = int(self.params.get("max_take_sell_size", 8))

        if regime.bullish:
            buy_edge = float(self.params.get("take_buy_edge_bull", -6.0))
            if position < inv_target:
                buy_edge -= float(self.params.get("take_buy_edge_under_boost", 2.0))
            if regime.on_dip:
                buy_edge -= float(self.params.get("take_buy_edge_dip_boost", 1.5))
            elif regime.chasing:
                buy_edge += float(self.params.get("take_buy_edge_chase_penalty", 2.0))

            sell_edge = 1_000_000.0  # effectively disabled

            buy_take_cap = max_buy
            under_mult = float(self.params.get("under_target_buy_mult", 1.50))
            startup_mult = float(self.params.get("startup_buy_mult", 1.35))
            dip_mult = float(self.params.get("dip_buy_mult", 1.35))
            chase_frac = float(self.params.get("chase_buy_frac", 0.60))

            if position < inv_target:
                buy_take_cap = max(buy_take_cap, int(round(max_buy * under_mult)))
            if regime.startup_loading:
                buy_take_cap = max(buy_take_cap, int(round(max_buy * startup_mult)))
            if regime.on_dip:
                buy_take_cap = max(buy_take_cap, int(round(max_buy * dip_mult)))
            if regime.chasing:
                buy_take_cap = max(1, int(round(buy_take_cap * chase_frac)))
            if pre_trim_signal or rebuy_blocked:
                buy_take_cap = 0

            sell_take_cap = 0

        else:
            buy_edge = float(self.params.get("take_buy_edge_neut", 2.0))
            sell_edge = float(self.params.get("take_sell_edge_neut", 2.0))
            if position > inv_target:
                pressure = min(1.0, (position - inv_target) / max(1.0, float(self.position_limit())))
                sell_edge -= float(self.params.get("unwind_take_edge", 8.0)) * pressure
            buy_take_cap = max_buy
            sell_take_cap = max_sell

        return buy_edge, sell_edge, buy_take_cap, sell_take_cap

    def _taker_reference(self, regime: _Regime, position: int, sig: _Signals) -> float:
        """Fair-value reference for taker thresholds.

        Uses ``entry_reference`` (colder) when inventory is elevated, to avoid
        chasing takes at an already-stretched price.
        """
        trim_floor = int(self.params.get("trim_floor_position", 72))
        if regime.bullish and position >= trim_floor and not regime.on_dip:
            return sig.entry_reference
        return sig.fair

    # ------------------------------------------------------------------
    # Stage 5b — execute taker orders (shared with V34)
    # ------------------------------------------------------------------

    def _take_orders(
        self,
        order_depth: OrderDepth,
        fair: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
        buy_take_cap: int,
        sell_take_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        """Fill aggressively against the book up to take caps."""
        orders: List[Order] = []
        take_count = 0
        buy_remaining = min(buy_cap, max(0, buy_take_cap))
        sell_remaining = min(sell_cap, max(0, sell_take_cap))

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > fair - buy_edge or buy_remaining <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap, buy_remaining)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            buy_remaining -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < fair + sell_edge or sell_remaining <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap, sell_remaining)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            sell_remaining -= qty
            take_count += 1

        return orders, buy_cap, sell_cap, take_count

    # ------------------------------------------------------------------
    # Stage 6 — book state after sweeps
    # ------------------------------------------------------------------

    def _real_best_after_sweeps(
        self,
        book: BookSnapshot,
        take_orders: List[Order],
    ) -> Tuple[int, int]:
        """Return (real_best_bid, real_best_ask) after removing levels swept by takers."""
        swept_asks = {o.price for o in take_orders if o.quantity > 0}
        real_best_ask = book.best_ask
        for price, _ in book.ask_levels:
            if price not in swept_asks:
                real_best_ask = price
                break

        swept_bids = {o.price for o in take_orders if o.quantity < 0}
        real_best_bid = book.best_bid
        for price, _ in book.bid_levels:
            if price not in swept_bids:
                real_best_bid = price
                break

        return real_best_bid, real_best_ask

    # ------------------------------------------------------------------
    # Stage 7 — trim mode evaluation
    # ------------------------------------------------------------------

    def _eval_trim_modes(
        self,
        regime: _Regime,
        sig: _Signals,
        position: int,
        real_best_bid: int,
        last_trim_ts: int,
        timestamp: int,
    ) -> Tuple[bool, bool]:
        """Evaluate trim_quote_mode and trim_take_mode.

        trim_quote_mode: narrow ask quote + small sell size to offload inventory.
        trim_take_mode:  aggressive market sell when stretch and bid are extreme.
        """
        trim_start = int(self.params.get("trim_start_position", 76))
        trim_floor = int(self.params.get("trim_floor_position", 72))
        ext_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        signal_edge = float(self.params.get("trim_signal_edge", 0.75))
        take_position = int(self.params.get("trim_take_position", 78))
        take_edge = float(self.params.get("trim_take_edge", 1.25))
        take_stretch = float(self.params.get("trim_take_stretch", 1.25))
        cooldown_ticks = int(self.params.get("trim_cooldown_ticks", 10))

        trim_quote_mode = (
            regime.bullish
            and position > trim_floor
            and position >= trim_start
            and sig.stretch >= ext_threshold
            and real_best_bid >= sig.trim_reference + signal_edge
        )
        trim_take_mode = (
            trim_quote_mode
            and position >= take_position
            and sig.stretch >= take_stretch
            and real_best_bid >= sig.trim_reference + take_edge
            and timestamp - last_trim_ts >= cooldown_ticks * 100
        )
        return trim_quote_mode, trim_take_mode

    # ------------------------------------------------------------------
    # Stage 8 — base quote sizing + inventory-pressure skew
    # ------------------------------------------------------------------

    def _size_quotes(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        """Base quote sizes, reduced on the side that increases inventory pressure."""
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.45))
        aggravate_min = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost = float(self.params.get("unwind_boost_frac", 0.35))
        limit = float(self.position_limit())

        pressure = abs(position - inv_target) / max(1.0, limit)
        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        agg_frac = 1.0 - (1.0 - aggravate_min) * scaled
        boost = 1.0 + unwind_boost * scaled

        if position > inv_target:
            buy_size = max(1, int(round(buy_size * agg_frac)))
            sell_size = min(sell_cap, max(1, int(round(sell_size * boost))))
        elif position < inv_target:
            sell_size = max(1, int(round(sell_size * agg_frac)))
            buy_size = min(buy_cap, max(1, int(round(buy_size * boost))))

        return buy_size, sell_size

    def _adjust_sizes_for_regime(
        self,
        regime: _Regime,
        position: int,
        inv_target: int,
        buy_size: int,
        sell_size: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        """Apply per-regime multipliers: under-target, startup, dip, chase."""
        under_buy_mult = float(self.params.get("under_target_buy_mult", 1.50))
        under_sell_frac = float(self.params.get("under_target_sell_frac", 0.0))
        startup_mult = float(self.params.get("startup_buy_mult", 1.35))
        dip_mult = float(self.params.get("dip_buy_mult", 1.35))
        chase_frac = float(self.params.get("chase_buy_frac", 0.60))
        hold_buy_frac = float(self.params.get("hold_buy_frac", 0.75))
        hold_sell_frac = float(self.params.get("hold_sell_frac", 0.25))

        if regime.bullish and position < inv_target:
            buy_size = min(buy_cap, max(1, int(round(buy_size * under_buy_mult))))
            sell_size = int(round(sell_size * under_sell_frac))
        elif regime.bullish:
            buy_size = min(buy_cap, max(1, int(round(buy_size * hold_buy_frac)))) if buy_size > 0 else 0
            sell_size = min(sell_cap, max(0, int(round(sell_size * hold_sell_frac))))

        if regime.startup_loading and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * startup_mult))))
        if regime.on_dip and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * dip_mult))))
        elif regime.chasing and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * chase_frac))))

        return buy_size, sell_size

    # ------------------------------------------------------------------
    # Stage 9 — quote prices
    # ------------------------------------------------------------------

    def _compute_bid_price(
        self,
        regime: _Regime,
        sig: _Signals,
        position: int,
        inv_target: int,
        real_best_bid: int,
        real_best_ask: int,
        buy_size: int,
    ) -> int:
        """Passive bid: reference minus spread, optionally joined to best bid."""
        trim_floor = int(self.params.get("trim_floor_position", 72))
        spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        spread_under = float(self.params.get("bid_spread_bull_under", 0.0))
        spread_neut = float(self.params.get("bid_spread_neut", 2.0))
        join_ticks = int(self.params.get("bid_join_ticks", 1))

        if regime.bullish and position < inv_target:
            spread = spread_under
        elif regime.bullish:
            spread = spread_bull
        else:
            spread = spread_neut

        # Use entry_reference (colder) when inventory is above floor
        bid_reference = sig.fair
        if regime.bullish and position >= trim_floor and not regime.on_dip:
            bid_reference = sig.entry_reference

        raw_bid = round(bid_reference - spread)
        bid_price = min(max(raw_bid, 1), real_best_ask - 1)

        # Join the best bid to stay competitive
        if regime.bullish and buy_size > 0:
            bid_price = max(bid_price, min(real_best_bid + join_ticks, real_best_ask - 1))

        return bid_price

    def _compute_ask_price(
        self,
        regime: _Regime,
        sig: _Signals,
        trim_quote_mode: bool,
        real_best_bid: int,
        real_best_ask: int,
    ) -> int:
        """Passive ask: wide when holding, narrow when trimming."""
        spread_hold = float(self.params.get("ask_spread_bull_hold", 8.0))
        spread_trim = float(self.params.get("ask_spread_bull_trim", 2.0))
        spread_neut = float(self.params.get("ask_spread_neut", 4.0))
        improve_ticks = int(self.params.get("trim_ask_improve_ticks", 1))
        local_edge = float(self.params.get("trim_ask_local_edge", 1.0))

        ask_edge = (spread_trim if trim_quote_mode else spread_hold) if regime.bullish else spread_neut
        raw_ask = round(sig.fair + ask_edge)
        ask_price = max(raw_ask, real_best_bid + 1)

        if trim_quote_mode:
            trim_ask_target = round(sig.trim_reference + local_edge)
            ask_price = max(real_best_bid + 1, min(real_best_ask - improve_ticks, trim_ask_target))

        return ask_price

    # ------------------------------------------------------------------
    # Stage 10 — sell suppression, trim override, rebuy block
    # ------------------------------------------------------------------

    def _apply_suppress_and_override(
        self,
        regime: _Regime,
        position: int,
        buy_size: int,
        sell_size: int,
        buy_cap: int,
        sell_cap: int,
        trim_quote_mode: bool,
        rebuy_blocked: bool,
        timestamp: int,
    ) -> Tuple[int, int]:
        """Apply final size overrides in priority order.

        1. Warmup / startup / below-floor → suppress sells.
        2. Trim mode → override sizes to trim-only config.
        3. Rebuy block → zero out buys (unless on dip).
        """
        warmup_ticks = int(self.params.get("warmup_no_sell_ticks", 3000))
        trim_floor = int(self.params.get("trim_floor_position", 72))
        trim_sell_size = int(self.params.get("trim_sell_size", 2))

        warmup_sell_suppressed = timestamp <= warmup_ticks and position <= 0
        if warmup_sell_suppressed or regime.startup_loading or (regime.bullish and position < trim_floor):
            sell_size = 0

        if trim_quote_mode:
            allowed_sell = max(0, position - trim_floor)
            sell_size = min(sell_cap, allowed_sell, max(1, trim_sell_size))
            buy_size = 0

        if rebuy_blocked and not regime.on_dip:
            buy_size = 0

        return buy_size, sell_size

    # ------------------------------------------------------------------
    # Stage 11 — anchor bid
    # ------------------------------------------------------------------

    def _compute_anchor_bid(
        self,
        regime: _Regime,
        sig: _Signals,
        trim_quote_mode: bool,
        rebuy_blocked: bool,
        bid_price: int,
        real_best_ask: int,
        buy_cap: int,
        buy_size: int,
    ) -> Tuple[Optional[int], int]:
        """V18-style cold anchor bid — lower reference for patient re-entry.

        Active when rebuy_blocked, trim_quote_mode, or chasing (and not on dip).
        Returns (None, 0) when inactive.
        """
        anchor_mode = regime.bullish and not regime.on_dip and (
            rebuy_blocked or trim_quote_mode or regime.chasing
        )
        if not anchor_mode or buy_cap <= buy_size:
            return None, 0

        spread = float(self.params.get("v18_anchor_bid_spread", 1.0))
        gap_ticks = int(self.params.get("v18_anchor_gap_ticks", 1))
        anchor_size_param = int(self.params.get("v18_anchor_buy_size", 2))

        raw = round(sig.fv - spread)
        candidate = min(max(raw, 1), real_best_ask - 1)
        candidate = min(candidate, bid_price - gap_ticks)

        if candidate < 1:
            return None, 0

        anchor_size = min(max(1, anchor_size_param), max(0, buy_cap - buy_size))
        return candidate, anchor_size

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        spot = book.microprice if book.microprice is not None else ( #TODO peut changer pour mid_price - tester les fonctions de la class mere
            book.mid_price or (book.best_bid + book.best_ask) / 2.0
        )

        # 1. Price signals
        sig = self._update_signals(spot, memory)

        # 2. Regime
        regime = self._detect_regime(sig, state.timestamp)

        # 3. Inventory target
        inv_target = self._compute_inv_target(regime, sig)

        # 4. Trim / rebuy state
        last_trim_ts = int(memory.get("last_trim_ts", -(10**9)))
        rebuy_block_until = int(memory.get("rebuy_block_until", -(10**9)))
        rebuy_blocked = regime.bullish and not regime.on_dip and state.timestamp < rebuy_block_until
        pre_trim_signal = self._is_pre_trim_signal(regime, sig, position, book.best_bid)

        # 5. Taker orders
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        buy_edge, sell_edge, buy_take_cap, sell_take_cap = self._taker_edges_and_caps(
            regime=regime, position=position, inv_target=inv_target,
            rebuy_blocked=rebuy_blocked, pre_trim_signal=pre_trim_signal,
        )
        take_ref = self._taker_reference(regime, position, sig)

        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth, fair=take_ref,
            buy_edge=buy_edge, sell_edge=sell_edge,
            buy_cap=buy_cap, sell_cap=sell_cap,
            buy_take_cap=buy_take_cap, sell_take_cap=sell_take_cap,
        )
        orders.extend(take_orders)

        # 6. Real best bid/ask after sweeps
        real_best_bid, real_best_ask = self._real_best_after_sweeps(book, take_orders)

        # 7. Trim modes
        trim_quote_mode, trim_take_mode = self._eval_trim_modes(
            regime=regime, sig=sig, position=position,
            real_best_bid=real_best_bid, last_trim_ts=last_trim_ts,
            timestamp=state.timestamp,
        )

        # 8. Trim taker (aggressive sell to shed inventory)
        trim_take_qty = 0
        trim_floor = int(self.params.get("trim_floor_position", 72))
        rebuy_block_ticks = int(self.params.get("rebuy_block_ticks", 15))
        trim_take_sell_size = int(self.params.get("trim_take_sell_size", 2))

        if trim_take_mode:
            trim_take_qty = min(sell_cap, max(0, position - trim_floor), max(1, trim_take_sell_size))
            if trim_take_qty > 0:
                orders.append(Order(self.product, real_best_bid, -trim_take_qty))
                sell_cap -= trim_take_qty
                memory["last_trim_ts"] = state.timestamp
                memory["rebuy_block_until"] = state.timestamp + rebuy_block_ticks * 100
                rebuy_blocked = True
                take_count += 1

        # 9. Quote sizes
        buy_size, sell_size = self._size_quotes(
            position=position, inv_target=inv_target,
            buy_cap=buy_cap, sell_cap=sell_cap,
        )
        buy_size, sell_size = self._adjust_sizes_for_regime(
            regime=regime, position=position, inv_target=inv_target,
            buy_size=buy_size, sell_size=sell_size,
            buy_cap=buy_cap, sell_cap=sell_cap,
        )

        # 10. Quote prices
        bid_price = self._compute_bid_price(
            regime=regime, sig=sig, position=position, inv_target=inv_target,
            real_best_bid=real_best_bid, real_best_ask=real_best_ask, buy_size=buy_size,
        )
        ask_price = self._compute_ask_price(
            regime=regime, sig=sig, trim_quote_mode=trim_quote_mode,
            real_best_bid=real_best_bid, real_best_ask=real_best_ask,
        )

        # 11. Sell suppression, trim override, rebuy block
        buy_size, sell_size = self._apply_suppress_and_override(
            regime=regime, position=position,
            buy_size=buy_size, sell_size=sell_size,
            buy_cap=buy_cap, sell_cap=sell_cap,
            trim_quote_mode=trim_quote_mode, rebuy_blocked=rebuy_blocked,
            timestamp=state.timestamp,
        )

        # 12. Crossing guard
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # 13. Anchor bid
        anchor_buy_price, anchor_buy_size = self._compute_anchor_bid(
            regime=regime, sig=sig, trim_quote_mode=trim_quote_mode,
            rebuy_blocked=rebuy_blocked, bid_price=bid_price,
            real_best_ask=real_best_ask, buy_cap=buy_cap, buy_size=buy_size,
        )
        anchor_mode = anchor_buy_price is not None

        # 14. Emit orders
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if anchor_buy_size > 0 and anchor_buy_price is not None:
            orders.append(Order(self.product, anchor_buy_price, anchor_buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        # 15. Persist state
        memory.update({
            "last_bid_price": bid_price,
            "last_ask_price": ask_price,
            "fair": sig.fair,
            "trim_reference": sig.trim_reference,
            "entry_reference": sig.entry_reference,
            "slope": sig.slope,
            "stretch": sig.stretch,
            "inv_target": inv_target,
            "bullish": int(regime.bullish),
            "on_dip": int(regime.on_dip),
            "chasing": int(regime.chasing),
            "trim_quote_mode": int(trim_quote_mode),
            "trim_take_mode": int(trim_take_mode),
            "rebuy_blocked": int(rebuy_blocked),
            "anchor_mode": int(anchor_mode),
        })

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "fair": round(sig.fair, 2),
                "fv": round(sig.fv, 2),
                "trim_reference": round(sig.trim_reference, 2),
                "entry_reference": round(sig.entry_reference, 2),
                "slope": round(sig.slope, 2),
                "stretch": round(sig.stretch, 2),
                "bullish": int(regime.bullish),
                "inv_target": inv_target,
                "on_dip": int(regime.on_dip),
                "chasing": int(regime.chasing),
                "trim_quote_mode": int(trim_quote_mode),
                "trim_take_mode": int(trim_take_mode),
                "rebuy_blocked": int(rebuy_blocked),
                "anchor_mode": int(anchor_mode),
                "anchor_buy_price": anchor_buy_price,
                "anchor_buy_size": anchor_buy_size,
                "trim_take_qty": trim_take_qty,
                "takes": take_count,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key in ("fv", "fair", "short_ema", "trim_reference", "entry_reference"):
            if memory.get(key) is not None:
                out[key] = memory[key]
        return out
