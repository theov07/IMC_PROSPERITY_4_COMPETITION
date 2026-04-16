"""Trend carry market maker v2.

Same trading logic as ``trend_carry_window.py``, rewritten in a more linear,
debug-friendly style inspired by ``mm_first_v2.py``:

- sequential ``compute_orders`` flow
- fewer cross-method jumps while keeping pure helpers for repeated math
- identical params, memory keys, order sequencing, and runtime logging

The goal of this file is readability, not strategy changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


def _ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


@dataclass
class _Signals:
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
    bullish: bool
    on_dip: bool
    chasing: bool
    startup_loading: bool


@dataclass
class _TakerPlan:
    buy_edge: float
    sell_edge: float
    buy_take_cap: int
    sell_take_cap: int
    reference: float


class TrendCarryWindowV2Strategy(BaseStrategy):
    def _spot_price(self, book: BookSnapshot) -> float:
        return book.microprice if book.microprice is not None else (
            book.mid_price or (book.best_bid + book.best_ask) / 2.0
        )

    def _compute_signals(self, spot: float, memory: Dict[str, Any]) -> _Signals:
        fv_alpha = float(self.params.get("fv_alpha", 0.05))
        short_alpha = float(self.params.get("short_alpha", 0.22))
        slope_window = int(self.params.get("slope_window", 20))
        trend_weight = float(self.params.get("trend_weight", 0.55))
        stretch_weight = float(self.params.get("stretch_weight", 0.75))
        trim_slope_weight = float(self.params.get("trim_reference_slope_weight", 0.15))
        entry_slope_weight = float(self.params.get("entry_reference_slope_weight", 0.18))

        fv = _ewma(memory.get("fv"), spot, fv_alpha)
        short_ema = _ewma(memory.get("short_ema"), spot, short_alpha)
        memory["fv"] = fv
        memory["short_ema"] = short_ema

        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[: -(slope_window + 1)]

        slope = fv_hist[-1] - fv_hist[-slope_window] if len(fv_hist) >= slope_window else 0.0
        stretch = spot - short_ema

        fair = fv + trend_weight * slope - stretch_weight * stretch
        trim_reference = fv + trim_slope_weight * max(0.0, slope)
        entry_reference = min(fair, fv + entry_slope_weight * max(0.0, slope))

        return _Signals(
            spot=spot,
            fv=fv,
            short_ema=short_ema,
            slope=slope,
            stretch=stretch,
            fair=fair,
            trim_reference=trim_reference,
            entry_reference=entry_reference,
        )

    def _compute_regime(self, signals: _Signals, timestamp: int) -> _Regime:
        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        dip_threshold = float(self.params.get("dip_threshold", 1.5))
        chase_threshold = float(self.params.get("chase_threshold", 2.5))
        startup_ticks = int(self.params.get("startup_ticks", 15000))

        bullish = signals.slope > bull_threshold
        on_dip = bullish and signals.stretch <= -dip_threshold
        chasing = bullish and signals.stretch >= chase_threshold and not on_dip
        startup_loading = bullish and timestamp <= startup_ticks

        return _Regime(
            bullish=bullish,
            on_dip=on_dip,
            chasing=chasing,
            startup_loading=startup_loading,
        )

    def _compute_inventory_target(self, regime: _Regime, signals: _Signals) -> int:
        if not regime.bullish:
            return int(self.params.get("neutral_target", 0))

        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        target_base = int(self.params.get("target_bull_base", 64))
        target_min = int(self.params.get("target_bull_min", 56))
        target_max = int(self.params.get("target_bull_max", 78))
        target_per_tick = float(self.params.get("target_bull_per_tick", 2.0))
        startup_target = int(self.params.get("startup_target", 78))
        dip_target = int(self.params.get("dip_target", 80))

        dynamic_target = target_base + target_per_tick * max(0.0, signals.slope - bull_threshold)
        inventory_target = int(round(max(target_min, min(target_max, dynamic_target))))

        if regime.startup_loading:
            inventory_target = max(inventory_target, startup_target)
        if regime.on_dip:
            inventory_target = max(inventory_target, dip_target)

        return min(self.position_limit(), inventory_target)

    def _pre_trim_signal(self, regime: _Regime, signals: _Signals, position: int, best_bid: int) -> bool:
        trim_start = int(self.params.get("trim_start_position", 76))
        trim_floor = int(self.params.get("trim_floor_position", 72))
        extension_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        signal_edge = float(self.params.get("trim_signal_edge", 0.75))

        return (
            regime.bullish
            and position > trim_floor
            and position >= trim_start
            and signals.stretch >= extension_threshold
            and best_bid >= signals.trim_reference + signal_edge
        )

    def _build_taker_plan(
        self,
        regime: _Regime,
        signals: _Signals,
        position: int,
        inventory_target: int,
        rebuy_blocked: bool,
        pre_trim_signal: bool,
    ) -> _TakerPlan:
        max_take_buy_size = int(self.params.get("max_take_buy_size", 12))
        max_take_sell_size = int(self.params.get("max_take_sell_size", 8))

        trim_floor = int(self.params.get("trim_floor_position", 72))
        if regime.bullish and position >= trim_floor and not regime.on_dip:
            taker_reference = signals.entry_reference
        else:
            taker_reference = signals.fair

        if regime.bullish:
            buy_edge = float(self.params.get("take_buy_edge_bull", -6.0))
            if position < inventory_target:
                buy_edge -= float(self.params.get("take_buy_edge_under_boost", 2.0))
            if regime.on_dip:
                buy_edge -= float(self.params.get("take_buy_edge_dip_boost", 1.5))
            elif regime.chasing:
                buy_edge += float(self.params.get("take_buy_edge_chase_penalty", 2.0))

            buy_take_cap = max_take_buy_size
            if position < inventory_target:
                buy_take_cap = max(
                    buy_take_cap,
                    int(round(max_take_buy_size * float(self.params.get("under_target_buy_mult", 1.50)))),
                )
            if regime.startup_loading:
                buy_take_cap = max(
                    buy_take_cap,
                    int(round(max_take_buy_size * float(self.params.get("startup_buy_mult", 1.35)))),
                )
            if regime.on_dip:
                buy_take_cap = max(
                    buy_take_cap,
                    int(round(max_take_buy_size * float(self.params.get("dip_buy_mult", 1.35)))),
                )
            if regime.chasing:
                buy_take_cap = max(
                    1,
                    int(round(buy_take_cap * float(self.params.get("chase_buy_frac", 0.60)))),
                )
            if pre_trim_signal or rebuy_blocked:
                buy_take_cap = 0

            return _TakerPlan(
                buy_edge=buy_edge,
                sell_edge=1_000_000.0,
                buy_take_cap=buy_take_cap,
                sell_take_cap=0,
                reference=taker_reference,
            )

        sell_edge = float(self.params.get("take_sell_edge_neut", 2.0))
        if position > inventory_target:
            pressure = min(1.0, (position - inventory_target) / max(1.0, float(self.position_limit())))
            sell_edge -= float(self.params.get("unwind_take_edge", 8.0)) * pressure

        return _TakerPlan(
            buy_edge=float(self.params.get("take_buy_edge_neut", 2.0)),
            sell_edge=sell_edge,
            buy_take_cap=max_take_buy_size,
            sell_take_cap=max_take_sell_size,
            reference=taker_reference,
        )

    def _sweep_takers(
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

    def _best_after_sweeps(self, book: BookSnapshot, take_orders: List[Order]) -> Tuple[int, int]:
        swept_asks = {order.price for order in take_orders if order.quantity > 0}
        real_best_ask = book.best_ask
        for price, _ in book.ask_levels:
            if price not in swept_asks:
                real_best_ask = price
                break

        swept_bids = {order.price for order in take_orders if order.quantity < 0}
        real_best_bid = book.best_bid
        for price, _ in book.bid_levels:
            if price not in swept_bids:
                real_best_bid = price
                break

        return real_best_bid, real_best_ask

    def _compute_trim_modes(
        self,
        regime: _Regime,
        signals: _Signals,
        position: int,
        real_best_bid: int,
        last_trim_ts: int,
        timestamp: int,
    ) -> Tuple[bool, bool]:
        trim_start = int(self.params.get("trim_start_position", 76))
        trim_floor = int(self.params.get("trim_floor_position", 72))
        extension_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        signal_edge = float(self.params.get("trim_signal_edge", 0.75))
        trim_take_position = int(self.params.get("trim_take_position", 78))
        trim_take_edge = float(self.params.get("trim_take_edge", 1.25))
        trim_take_stretch = float(self.params.get("trim_take_stretch", 1.25))
        trim_cooldown_ticks = int(self.params.get("trim_cooldown_ticks", 10))

        trim_quote_mode = (
            regime.bullish
            and position > trim_floor
            and position >= trim_start
            and signals.stretch >= extension_threshold
            and real_best_bid >= signals.trim_reference + signal_edge
        )
        trim_take_mode = (
            trim_quote_mode
            and position >= trim_take_position
            and signals.stretch >= trim_take_stretch
            and real_best_bid >= signals.trim_reference + trim_take_edge
            and timestamp - last_trim_ts >= trim_cooldown_ticks * 100
        )
        return trim_quote_mode, trim_take_mode

    def _base_quote_sizes(self, position: int, inventory_target: int, buy_cap: int, sell_cap: int) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        inventory_soft_ratio = float(self.params.get("inventory_soft_ratio", 0.45))
        aggravate_min_frac = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost_frac = float(self.params.get("unwind_boost_frac", 0.35))

        limit = float(self.position_limit())
        pressure = abs(position - inventory_target) / max(1.0, limit)
        if pressure <= inventory_soft_ratio or inventory_soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - inventory_soft_ratio) / max(1e-9, 1.0 - inventory_soft_ratio))
        aggravate_fraction = 1.0 - (1.0 - aggravate_min_frac) * scaled
        boost_fraction = 1.0 + unwind_boost_frac * scaled

        if position > inventory_target:
            buy_size = max(1, int(round(buy_size * aggravate_fraction)))
            sell_size = min(sell_cap, max(1, int(round(sell_size * boost_fraction))))
        elif position < inventory_target:
            sell_size = max(1, int(round(sell_size * aggravate_fraction)))
            buy_size = min(buy_cap, max(1, int(round(buy_size * boost_fraction))))

        return buy_size, sell_size

    def _regime_quote_sizes(
        self,
        regime: _Regime,
        position: int,
        inventory_target: int,
        buy_size: int,
        sell_size: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        under_target_buy_mult = float(self.params.get("under_target_buy_mult", 1.50))
        under_target_sell_frac = float(self.params.get("under_target_sell_frac", 0.0))
        startup_buy_mult = float(self.params.get("startup_buy_mult", 1.35))
        dip_buy_mult = float(self.params.get("dip_buy_mult", 1.35))
        chase_buy_frac = float(self.params.get("chase_buy_frac", 0.60))
        hold_buy_frac = float(self.params.get("hold_buy_frac", 0.75))
        hold_sell_frac = float(self.params.get("hold_sell_frac", 0.25))

        if regime.bullish and position < inventory_target:
            buy_size = min(buy_cap, max(1, int(round(buy_size * under_target_buy_mult))))
            sell_size = int(round(sell_size * under_target_sell_frac))
        elif regime.bullish:
            buy_size = min(buy_cap, max(1, int(round(buy_size * hold_buy_frac)))) if buy_size > 0 else 0
            sell_size = min(sell_cap, max(0, int(round(sell_size * hold_sell_frac))))

        if regime.startup_loading and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * startup_buy_mult))))
        if regime.on_dip and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * dip_buy_mult))))
        elif regime.chasing and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * chase_buy_frac))))

        return buy_size, sell_size

    def _bid_price(
        self,
        regime: _Regime,
        signals: _Signals,
        position: int,
        inventory_target: int,
        real_best_bid: int,
        real_best_ask: int,
        buy_size: int,
    ) -> int:
        trim_floor = int(self.params.get("trim_floor_position", 72))
        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        bid_spread_under = float(self.params.get("bid_spread_bull_under", 0.0))
        bid_spread_neut = float(self.params.get("bid_spread_neut", 2.0))
        bid_join_ticks = int(self.params.get("bid_join_ticks", 1))

        if regime.bullish and position < inventory_target:
            spread = bid_spread_under
        elif regime.bullish:
            spread = bid_spread_bull
        else:
            spread = bid_spread_neut

        bid_reference = signals.fair
        if regime.bullish and position >= trim_floor and not regime.on_dip:
            bid_reference = signals.entry_reference

        raw_bid = round(bid_reference - spread)
        bid_price = min(max(raw_bid, 1), real_best_ask - 1)

        if regime.bullish and buy_size > 0:
            bid_price = max(bid_price, min(real_best_bid + bid_join_ticks, real_best_ask - 1))

        return bid_price

    def _ask_price(
        self,
        regime: _Regime,
        signals: _Signals,
        trim_quote_mode: bool,
        real_best_bid: int,
        real_best_ask: int,
    ) -> int:
        ask_spread_bull_hold = float(self.params.get("ask_spread_bull_hold", 8.0))
        ask_spread_bull_trim = float(self.params.get("ask_spread_bull_trim", 2.0))
        ask_spread_neut = float(self.params.get("ask_spread_neut", 4.0))
        trim_ask_improve_ticks = int(self.params.get("trim_ask_improve_ticks", 1))
        trim_ask_local_edge = float(self.params.get("trim_ask_local_edge", 1.0))

        ask_edge = (
            ask_spread_bull_trim if trim_quote_mode else ask_spread_bull_hold
        ) if regime.bullish else ask_spread_neut
        raw_ask = round(signals.fair + ask_edge)
        ask_price = max(raw_ask, real_best_bid + 1)

        if trim_quote_mode:
            trim_target = round(signals.trim_reference + trim_ask_local_edge)
            ask_price = max(real_best_bid + 1, min(real_best_ask - trim_ask_improve_ticks, trim_target))

        return ask_price

    def _final_quote_sizes(
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
        warmup_no_sell_ticks = int(self.params.get("warmup_no_sell_ticks", 3000))
        trim_floor = int(self.params.get("trim_floor_position", 72))
        trim_sell_size = int(self.params.get("trim_sell_size", 2))

        warmup_sell_suppressed = timestamp <= warmup_no_sell_ticks and position <= 0
        if warmup_sell_suppressed or regime.startup_loading or (regime.bullish and position < trim_floor):
            sell_size = 0

        if trim_quote_mode:
            allowed_sell = max(0, position - trim_floor)
            sell_size = min(sell_cap, allowed_sell, max(1, trim_sell_size))
            buy_size = 0

        if rebuy_blocked and not regime.on_dip:
            buy_size = 0

        return buy_size, sell_size

    def _anchor_bid(
        self,
        regime: _Regime,
        signals: _Signals,
        trim_quote_mode: bool,
        rebuy_blocked: bool,
        bid_price: int,
        real_best_ask: int,
        buy_cap: int,
        buy_size: int,
    ) -> Tuple[Optional[int], int]:
        anchor_mode = regime.bullish and not regime.on_dip and (
            rebuy_blocked or trim_quote_mode or regime.chasing
        )
        if not anchor_mode or buy_cap <= buy_size:
            return None, 0

        anchor_spread = float(self.params.get("v18_anchor_bid_spread", 1.0))
        anchor_gap_ticks = int(self.params.get("v18_anchor_gap_ticks", 1))
        anchor_size_param = int(self.params.get("v18_anchor_buy_size", 2))

        raw_anchor = round(signals.fv - anchor_spread)
        anchor_price = min(max(raw_anchor, 1), real_best_ask - 1)
        anchor_price = min(anchor_price, bid_price - anchor_gap_ticks)
        if anchor_price < 1:
            return None, 0

        anchor_size = min(max(1, anchor_size_param), max(0, buy_cap - buy_size))
        return anchor_price, anchor_size

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

        # ─────────────── PRICE STATE ────────────────────────────────
        spot = self._spot_price(book)
        signals = self._compute_signals(spot, memory)
        regime = self._compute_regime(signals, state.timestamp)
        inventory_target = self._compute_inventory_target(regime, signals)

        # ─────────────── TRIM / REBUY STATE ─────────────────────────
        last_trim_ts = int(memory.get("last_trim_ts", -(10**9)))
        rebuy_block_until = int(memory.get("rebuy_block_until", -(10**9)))
        rebuy_blocked = regime.bullish and not regime.on_dip and state.timestamp < rebuy_block_until
        pre_trim_signal = self._pre_trim_signal(regime, signals, position, book.best_bid)

        # ─────────────── TAKER ORDERS ───────────────────────────────
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        taker_plan = self._build_taker_plan(
            regime=regime,
            signals=signals,
            position=position,
            inventory_target=inventory_target,
            rebuy_blocked=rebuy_blocked,
            pre_trim_signal=pre_trim_signal,
        )
        take_orders, buy_cap, sell_cap, take_count = self._sweep_takers(
            order_depth=order_depth,
            fair=taker_plan.reference,
            buy_edge=taker_plan.buy_edge,
            sell_edge=taker_plan.sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            buy_take_cap=taker_plan.buy_take_cap,
            sell_take_cap=taker_plan.sell_take_cap,
        )
        orders.extend(take_orders)

        # ─────────────── BOOK AFTER TAKER SWEEPS ────────────────────
        real_best_bid, real_best_ask = self._best_after_sweeps(book, take_orders)

        # ─────────────── TRIM MODES ─────────────────────────────────
        trim_quote_mode, trim_take_mode = self._compute_trim_modes(
            regime=regime,
            signals=signals,
            position=position,
            real_best_bid=real_best_bid,
            last_trim_ts=last_trim_ts,
            timestamp=state.timestamp,
        )

        trim_take_qty = 0
        trim_floor = int(self.params.get("trim_floor_position", 72))
        trim_take_sell_size = int(self.params.get("trim_take_sell_size", 2))
        rebuy_block_ticks = int(self.params.get("rebuy_block_ticks", 15))

        if trim_take_mode:
            trim_take_qty = min(sell_cap, max(0, position - trim_floor), max(1, trim_take_sell_size))
            if trim_take_qty > 0:
                orders.append(Order(self.product, real_best_bid, -trim_take_qty))
                sell_cap -= trim_take_qty
                memory["last_trim_ts"] = state.timestamp
                memory["rebuy_block_until"] = state.timestamp + rebuy_block_ticks * 100
                rebuy_blocked = True
                take_count += 1

        # ─────────────── PASSIVE QUOTES: SIZE THEN PRICE ────────────
        buy_size, sell_size = self._base_quote_sizes(
            position=position,
            inventory_target=inventory_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )
        buy_size, sell_size = self._regime_quote_sizes(
            regime=regime,
            position=position,
            inventory_target=inventory_target,
            buy_size=buy_size,
            sell_size=sell_size,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        bid_price = self._bid_price(
            regime=regime,
            signals=signals,
            position=position,
            inventory_target=inventory_target,
            real_best_bid=real_best_bid,
            real_best_ask=real_best_ask,
            buy_size=buy_size,
        )
        ask_price = self._ask_price(
            regime=regime,
            signals=signals,
            trim_quote_mode=trim_quote_mode,
            real_best_bid=real_best_bid,
            real_best_ask=real_best_ask,
        )

        buy_size, sell_size = self._final_quote_sizes(
            regime=regime,
            position=position,
            buy_size=buy_size,
            sell_size=sell_size,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            trim_quote_mode=trim_quote_mode,
            rebuy_blocked=rebuy_blocked,
            timestamp=state.timestamp,
        )

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        anchor_buy_price, anchor_buy_size = self._anchor_bid(
            regime=regime,
            signals=signals,
            trim_quote_mode=trim_quote_mode,
            rebuy_blocked=rebuy_blocked,
            bid_price=bid_price,
            real_best_ask=real_best_ask,
            buy_cap=buy_cap,
            buy_size=buy_size,
        )
        anchor_mode = anchor_buy_price is not None

        # ─────────────── FINAL ORDER EMISSION ───────────────────────
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if anchor_buy_size > 0 and anchor_buy_price is not None:
            orders.append(Order(self.product, anchor_buy_price, anchor_buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        # ─────────────── MEMORY + DEBUG TRACE ───────────────────────
        memory.update({
            "last_bid_price": bid_price,
            "last_ask_price": ask_price,
            "fair": signals.fair,
            "trim_reference": signals.trim_reference,
            "entry_reference": signals.entry_reference,
            "slope": signals.slope,
            "stretch": signals.stretch,
            "inv_target": inventory_target,
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
                "fair": round(signals.fair, 2),
                "fv": round(signals.fv, 2),
                "trim_reference": round(signals.trim_reference, 2),
                "entry_reference": round(signals.entry_reference, 2),
                "slope": round(signals.slope, 2),
                "stretch": round(signals.stretch, 2),
                "bullish": int(regime.bullish),
                "inv_target": inventory_target,
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
