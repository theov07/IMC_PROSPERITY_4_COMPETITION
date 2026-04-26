"""Generic backtester — works for any round, any strategy configuration."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from datamodel import Order, OrderDepth, Trade, TradingState

from prosperity.config import MEMBER_OVERRIDES, get_round_config
from prosperity.tooling.data import MarketDataLoader


def _resolve_strategy_alias(name: str) -> str:
    # After round 1 refactor, round 1 dispatchers live in submissions/round_1/.
    # Round 2 per-member dispatchers live in submissions/round_2/<member>/.
    candidates = [
        f"submissions.{name}",
        f"submissions.round_1.{name}",
        f"submissions.round_2.{name}",
        f"submissions.round_2.leo.{name}",
        f"submissions.round_2.theo.{name}",
        f"submissions.round_2.tibo.{name}",
        f"submissions.round_3.{name}",
        f"submissions.round_3.leo.{name}",
        f"submissions.round_3.theo.{name}",
        f"submissions.round_3.tibo.{name}",
    ]
    for candidate in candidates:
        try:
            importlib.import_module(candidate)
            return candidate
        except ModuleNotFoundError:
            continue
    return f"submissions.{name}"


STRATEGY_ALIASES = {name: _resolve_strategy_alias(name) for name in MEMBER_OVERRIDES}


class TradeMatchingMode(str, Enum):
    """Controls how resting (passive) limit orders are matched against market trades.

    queue    — one-iteration queue heuristic. If you join an existing price, the displayed
               resting size at that level is treated as queue ahead. Exact-price trades must
               first clear that queue; any trade through your price implies your remaining
               quantity at that level was reached during the iteration.
    all      — fill if the market trade price is <= buy order price (or >= sell order price).
               Optimistic: assumes you have queue priority at your exact price level.
    worse    — fill only if the market trade price is strictly worse for the aggressor
               (< buy order price, > sell order price). More conservative: only fills you
               if someone traded through your price, not just at it.
    none     — no passive fills via market trades; only aggressive (book-crossing) fills fire.
    realistic — most accurate model:
               - Exact-price trades: queue_ahead is subtracted first (same as queue mode).
               - Through trades: fill min(remaining, trade.quantity) per trade, not the full
                 remaining qty. Models the real sweep mechanics where each trade in the CSV
                 is a single match event and its quantity bounds how much we can fill.
               - Multiple through-trades in the same tick accumulate independently.
    """
    queue    = "queue"
    all      = "all"
    worse    = "worse"
    none     = "none"
    realistic = "realistic"


@dataclass
class _MarketTradeSlot:
    """Tracks remaining fill capacity for one market trade at a given price."""
    price: int
    buy_avail: int   # units available to fill our passive sell orders
    sell_avail: int  # units available to fill our passive buy orders


@dataclass
class Fill:
    timestamp: int
    symbol: str
    side: str
    price: int
    quantity: int
    aggressive: bool
    gap_exploit: bool = False


@dataclass
class _PendingPassiveOrder:
    order: Order
    remaining: int


@dataclass
class ProductSummary:
    symbol: str
    pnl: float
    ending_position: int
    trades: int
    traded_volume: int
    turnover: float
    max_abs_position: int
    robustness: "RobustnessSummary"


@dataclass
class RobustnessSummary:
    submitted_volume: int
    traded_volume: int
    aggressive_qty: int
    passive_qty: int
    aggressive_trades: int
    passive_trades: int
    tick_count: int
    avg_abs_position_ratio: float
    near_limit_tick_count: int
    near_limit_tick_ratio: float
    fill_efficiency: float
    aggressive_share: float
    passive_eval_qty: int
    passive_adverse_qty: int
    passive_adverse_rate: float | None
    passive_post_fill_edge: float | None
    max_drawdown: float | None = None
    bid_submitted_volume: int = 0
    ask_submitted_volume: int = 0
    buy_filled_qty: int = 0
    sell_filled_qty: int = 0
    bid_fill_efficiency: float = 0.0
    ask_fill_efficiency: float = 0.0
    quote_metrics: Dict[str, float | int | None] = field(default_factory=dict)
    inventory_episode_metrics: Dict[str, float | int | None] = field(default_factory=dict)
    markout_mean_by_horizon: Dict[str, float | None] = field(default_factory=dict)
    passive_markout_mean_by_horizon: Dict[str, float | None] = field(default_factory=dict)
    aggressive_markout_mean_by_horizon: Dict[str, float | None] = field(default_factory=dict)
    markout_eval_qty_by_horizon: Dict[str, int] = field(default_factory=dict)
    passive_markout_eval_qty_by_horizon: Dict[str, int] = field(default_factory=dict)
    aggressive_markout_eval_qty_by_horizon: Dict[str, int] = field(default_factory=dict)
    pnl_attribution: Dict[str, float] = field(default_factory=dict)
    conversions_requested: int = 0


@dataclass
class Quote:
    timestamp: int
    symbol: str
    bid: float | None   # best buy order price submitted (None if no buy orders)
    ask: float | None   # best sell order price submitted (None if no sell orders)
    bid_size: int = 0
    ask_size: int = 0


@dataclass
class FeatureTick:
    timestamp: int
    symbol: str
    features: Dict[str, float]   # e.g. {"Reservation": 10001.5}


@dataclass
class ObservationTick:
    timestamp: int
    symbol: str
    values: Dict[str, float]


@dataclass
class ConversionTick:
    timestamp: int
    conversions: int


@dataclass
class DaySummary:
    day: str
    pnl: float
    fills: List[Fill]
    product_summaries: Dict[str, ProductSummary]
    equity_curve: List[Tuple[int, float]]
    robustness: RobustnessSummary
    quotes: List[Quote] = field(default_factory=list)
    feature_ticks: List[FeatureTick] = field(default_factory=list)
    observation_ticks: List[ObservationTick] = field(default_factory=list)
    conversion_ticks: List[ConversionTick] = field(default_factory=list)


class BacktestEngine:
    def __init__(self, data_dir: str | Path, strategy_module: str, round_num: int = 0):
        self.loader = MarketDataLoader(data_dir)
        self.strategy_name = strategy_module
        resolved = STRATEGY_ALIASES.get(strategy_module)
        if resolved is None:
            resolved = _resolve_strategy_alias(strategy_module)
        self.strategy_module = resolved
        self.round_num = round_num

    def _load_trader(self):
        module = importlib.import_module(self.strategy_module)
        if not hasattr(module, "Trader"):
            raise ValueError(f"Strategy module {self.strategy_module} does not expose Trader")
        return module.Trader()

    def _get_position_limits(self) -> Dict[str, int]:
        member = self.strategy_name if self.strategy_name in MEMBER_OVERRIDES else "champion"
        config = get_round_config(self.round_num, member)
        return {sym: pc.position_limit for sym, pc in config.items()}

    @staticmethod
    def _mid_price(order_depth: OrderDepth) -> float:
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        return float(best_bid or best_ask or 0.0)

    def _respect_exchange_limits(self, product: str, position: int, orders: List[Order]) -> List[Order]:
        limits = self._get_position_limits()
        limit = limits.get(product, 20)

        total_buy = sum(max(order.quantity, 0) for order in orders)
        total_sell = sum(max(-order.quantity, 0) for order in orders)

        if position + total_buy > limit:
            return []
        if position - total_sell < -limit:
            return []
        return orders

    @staticmethod
    def _simulate_fills(
        order_depth: OrderDepth,
        orders: List[Order],
        current_market_trades: List[Trade],
        timestamp: int,
        mode: TradeMatchingMode = TradeMatchingMode.queue,
    ) -> List[Fill]:
        fills: List[Fill] = []
        available_bids = [[price, volume] for price, volume in sorted(order_depth.buy_orders.items(), key=lambda item: item[0], reverse=True)]
        available_asks = [[price, -volume] for price, volume in sorted(order_depth.sell_orders.items(), key=lambda item: item[0])]
        pending_passive: List[_PendingPassiveOrder] = []

        for order in orders:
            if order.quantity == 0:
                continue

            remaining = abs(order.quantity)
            if order.quantity > 0:
                for level in available_asks:
                    ask_price, ask_volume = level
                    if ask_price > order.price or remaining <= 0:
                        break
                    traded = min(remaining, ask_volume)
                    if traded <= 0:
                        continue
                    fills.append(Fill(timestamp=timestamp, symbol=order.symbol, side="BUY", price=ask_price, quantity=traded, aggressive=True))
                    level[1] -= traded
                    remaining -= traded
                if remaining > 0:
                    pending_passive.append(_PendingPassiveOrder(order=order, remaining=remaining))
            else:
                for level in available_bids:
                    bid_price, bid_volume = level
                    if bid_price < order.price or remaining <= 0:
                        break
                    traded = min(remaining, bid_volume)
                    if traded <= 0:
                        continue
                    fills.append(Fill(timestamp=timestamp, symbol=order.symbol, side="SELL", price=bid_price, quantity=traded, aggressive=True))
                    level[1] -= traded
                    remaining -= traded
                if remaining > 0:
                    pending_passive.append(_PendingPassiveOrder(order=order, remaining=remaining))

        if mode == TradeMatchingMode.none or not pending_passive:
            return fills

        fills.extend(
            BacktestEngine._simulate_passive_fills(
                order_depth=order_depth,
                pending_passive=pending_passive,
                current_market_trades=current_market_trades,
                timestamp=timestamp,
                mode=mode,
            )
        )
        return fills

    @staticmethod
    def _simulate_passive_fills(
        order_depth: OrderDepth,
        pending_passive: List[_PendingPassiveOrder],
        current_market_trades: List[Trade],
        timestamp: int,
        mode: TradeMatchingMode,
    ) -> List[Fill]:
        if mode == TradeMatchingMode.queue:
            return BacktestEngine._simulate_passive_fills_queue(
                order_depth=order_depth,
                pending_passive=pending_passive,
                current_market_trades=current_market_trades,
                timestamp=timestamp,
            )
        if mode == TradeMatchingMode.realistic:
            return BacktestEngine._simulate_passive_fills_realistic(
                order_depth=order_depth,
                pending_passive=pending_passive,
                current_market_trades=current_market_trades,
                timestamp=timestamp,
            )
        return BacktestEngine._simulate_passive_fills_price_match(
            pending_passive=pending_passive,
            current_market_trades=current_market_trades,
            timestamp=timestamp,
            strict_through=(mode == TradeMatchingMode.worse),
        )

    @staticmethod
    def _simulate_passive_fills_price_match(
        pending_passive: List[_PendingPassiveOrder],
        current_market_trades: List[Trade],
        timestamp: int,
        strict_through: bool,
    ) -> List[Fill]:
        fills: List[Fill] = []
        slots: List[_MarketTradeSlot] = [
            _MarketTradeSlot(price=t.price, buy_avail=t.quantity, sell_avail=t.quantity)
            for t in current_market_trades
        ]

        for pending in BacktestEngine._sorted_pending_passive_orders(pending_passive):
            order = pending.order
            remaining = pending.remaining
            if remaining <= 0:
                continue

            is_buy = order.quantity > 0
            for slot in slots:
                if remaining <= 0:
                    break
                if is_buy:
                    price_ok = (slot.price < order.price) if strict_through else (slot.price <= order.price)
                    if not price_ok or slot.sell_avail <= 0:
                        continue
                    traded = min(remaining, slot.sell_avail)
                    fills.append(Fill(timestamp=timestamp, symbol=order.symbol, side="BUY", price=order.price, quantity=traded, aggressive=False))
                    slot.sell_avail -= traded
                    remaining -= traded
                else:
                    price_ok = (slot.price > order.price) if strict_through else (slot.price >= order.price)
                    if not price_ok or slot.buy_avail <= 0:
                        continue
                    traded = min(remaining, slot.buy_avail)
                    fills.append(Fill(timestamp=timestamp, symbol=order.symbol, side="SELL", price=order.price, quantity=traded, aggressive=False))
                    slot.buy_avail -= traded
                    remaining -= traded

        return fills

    @staticmethod
    def _simulate_passive_fills_queue(
        order_depth: OrderDepth,
        pending_passive: List[_PendingPassiveOrder],
        current_market_trades: List[Trade],
        timestamp: int,
    ) -> List[Fill]:
        fills: List[Fill] = []
        trade_volume_by_price: Dict[int, int] = {}
        for trade in current_market_trades:
            trade_volume_by_price[trade.price] = trade_volume_by_price.get(trade.price, 0) + trade.quantity

        exact_fillable_by_key: Dict[Tuple[bool, int], int] = {}
        through_by_key: Dict[Tuple[bool, int], bool] = {}

        for pending in BacktestEngine._sorted_pending_passive_orders(pending_passive):
            order = pending.order
            remaining = pending.remaining
            if remaining <= 0:
                continue

            is_buy = order.quantity > 0
            key = (is_buy, order.price)
            if key not in exact_fillable_by_key:
                queue_ahead = BacktestEngine._queue_ahead_at_price(order_depth, order)
                exact_fillable_by_key[key] = max(0, trade_volume_by_price.get(order.price, 0) - queue_ahead)
                through_by_key[key] = BacktestEngine._trade_through_price(current_market_trades, order)

            if through_by_key[key]:
                traded = remaining
            else:
                traded = min(remaining, exact_fillable_by_key[key])
                exact_fillable_by_key[key] -= traded

            if traded <= 0:
                continue

            fills.append(
                Fill(
                    timestamp=timestamp,
                    symbol=order.symbol,
                    side="BUY" if is_buy else "SELL",
                    price=order.price,
                    quantity=traded,
                    aggressive=False,
                )
            )

        return fills

    @staticmethod
    def _simulate_passive_fills_realistic(
        order_depth: OrderDepth,
        pending_passive: List[_PendingPassiveOrder],
        current_market_trades: List[Trade],
        timestamp: int,
    ) -> List[Fill]:
        """Realistic fill model:
        - Exact-price trades: deduct queue_ahead first, then fill min(remaining, leftover).
        - Through trades: each trade contributes min(remaining, trade.quantity) — no free
          full-remaining fill. Multiple through-trades accumulate independently.
        Orders are processed best-price-first so the most aggressive passive orders get
        first access to each trade's volume.
        """
        fills: List[Fill] = []

        # Pre-compute queue ahead per (is_buy, price) key
        queue_ahead_cache: Dict[Tuple[bool, int], int] = {}

        # Track remaining volume per trade (indexed by position in list)
        trade_remaining = [t.quantity for t in current_market_trades]

        for pending in BacktestEngine._sorted_pending_passive_orders(pending_passive):
            order = pending.order
            remaining = pending.remaining
            if remaining <= 0:
                continue

            is_buy = order.quantity > 0
            key = (is_buy, order.price)

            if key not in queue_ahead_cache:
                queue_ahead_cache[key] = BacktestEngine._queue_ahead_at_price(order_depth, order)

            queue_ahead = queue_ahead_cache[key]

            for i, trade in enumerate(current_market_trades):
                if remaining <= 0:
                    break
                if trade_remaining[i] <= 0:
                    continue

                if is_buy:
                    if trade.price > order.price:
                        continue
                    at_price = (trade.price == order.price)
                else:
                    if trade.price < order.price:
                        continue
                    at_price = (trade.price == order.price)

                if at_price:
                    # Exact price: consume queue_ahead from this trade first
                    consumed_by_queue = min(queue_ahead, trade_remaining[i])
                    queue_ahead -= consumed_by_queue
                    queue_ahead_cache[key] = queue_ahead
                    avail = trade_remaining[i] - consumed_by_queue
                    traded = min(remaining, avail)
                else:
                    # Through trade: fill proportional to trade volume, no free full fill
                    traded = min(remaining, trade_remaining[i])

                if traded <= 0:
                    continue

                trade_remaining[i] -= traded
                remaining -= traded
                fills.append(Fill(
                    timestamp=timestamp,
                    symbol=order.symbol,
                    side="BUY" if is_buy else "SELL",
                    price=order.price,
                    quantity=traded,
                    aggressive=False,
                ))

        return fills

    @staticmethod
    def _sorted_pending_passive_orders(pending_passive: List[_PendingPassiveOrder]) -> List[_PendingPassiveOrder]:
        buys = sorted((pending for pending in pending_passive if pending.order.quantity > 0), key=lambda pending: pending.order.price, reverse=True)
        sells = sorted((pending for pending in pending_passive if pending.order.quantity < 0), key=lambda pending: pending.order.price)
        return buys + sells

    @staticmethod
    def _queue_ahead_at_price(order_depth: OrderDepth, order: Order) -> int:
        if order.quantity > 0:
            return max(order_depth.buy_orders.get(order.price, 0), 0)
        return max(-order_depth.sell_orders.get(order.price, 0), 0)

    @staticmethod
    def _trade_through_price(current_market_trades: List[Trade], order: Order) -> bool:
        if order.quantity > 0:
            return any(trade.price < order.price for trade in current_market_trades)
        return any(trade.price > order.price for trade in current_market_trades)

    @staticmethod
    def _max_drawdown(equity_curve: List[Tuple[int, float]]) -> float:
        peak: float | None = None
        max_drawdown = 0.0
        for _, value in equity_curve:
            peak = value if peak is None else max(peak, value)
            max_drawdown = max(max_drawdown, peak - value)
        return max_drawdown

    @staticmethod
    def _max_drawdown_full(equity_curve: List[Tuple[int, float]]) -> tuple[float, float]:
        """Return (max_drawdown_abs, peak_at_max_drawdown)."""
        peak: float | None = None
        max_drawdown = 0.0
        peak_at_dd = 0.0
        for _, value in equity_curve:
            peak = value if peak is None else max(peak, value)
            dd = peak - value
            if dd > max_drawdown:
                max_drawdown = dd
                peak_at_dd = peak
        return max_drawdown, peak_at_dd

    @staticmethod
    def _build_robustness_summary(
        *,
        submitted_volume: int,
        traded_volume: int,
        aggressive_qty: int,
        passive_qty: int,
        aggressive_trades: int,
        passive_trades: int,
        tick_count: int,
        position_ratio_sum: float,
        near_limit_tick_count: int,
        passive_eval_qty: int,
        passive_adverse_qty: int,
        passive_edge_sum: float,
        max_drawdown: float | None = None,
        bid_submitted_volume: int = 0,
        ask_submitted_volume: int = 0,
        buy_filled_qty: int = 0,
        sell_filled_qty: int = 0,
        quote_metrics: Dict[str, float | int | None] | None = None,
        inventory_episode_metrics: Dict[str, float | int | None] | None = None,
        markout_mean_by_horizon: Dict[str, float | None] | None = None,
        passive_markout_mean_by_horizon: Dict[str, float | None] | None = None,
        aggressive_markout_mean_by_horizon: Dict[str, float | None] | None = None,
        markout_eval_qty_by_horizon: Dict[str, int] | None = None,
        passive_markout_eval_qty_by_horizon: Dict[str, int] | None = None,
        aggressive_markout_eval_qty_by_horizon: Dict[str, int] | None = None,
        pnl_attribution: Dict[str, float] | None = None,
        conversions_requested: int = 0,
    ) -> RobustnessSummary:
        avg_abs_position_ratio = (position_ratio_sum / tick_count) if tick_count else 0.0
        near_limit_tick_ratio = (near_limit_tick_count / tick_count) if tick_count else 0.0
        fill_efficiency = (traded_volume / submitted_volume) if submitted_volume else 0.0
        aggressive_share = (aggressive_qty / traded_volume) if traded_volume else 0.0
        passive_adverse_rate = (passive_adverse_qty / passive_eval_qty) if passive_eval_qty else None
        passive_post_fill_edge = (passive_edge_sum / passive_eval_qty) if passive_eval_qty else None
        bid_fill_efficiency = (buy_filled_qty / bid_submitted_volume) if bid_submitted_volume else 0.0
        ask_fill_efficiency = (sell_filled_qty / ask_submitted_volume) if ask_submitted_volume else 0.0
        return RobustnessSummary(
            submitted_volume=submitted_volume,
            traded_volume=traded_volume,
            aggressive_qty=aggressive_qty,
            passive_qty=passive_qty,
            aggressive_trades=aggressive_trades,
            passive_trades=passive_trades,
            tick_count=tick_count,
            avg_abs_position_ratio=avg_abs_position_ratio,
            near_limit_tick_count=near_limit_tick_count,
            near_limit_tick_ratio=near_limit_tick_ratio,
            fill_efficiency=fill_efficiency,
            aggressive_share=aggressive_share,
            passive_eval_qty=passive_eval_qty,
            passive_adverse_qty=passive_adverse_qty,
            passive_adverse_rate=passive_adverse_rate,
            passive_post_fill_edge=passive_post_fill_edge,
            max_drawdown=max_drawdown,
            bid_submitted_volume=bid_submitted_volume,
            ask_submitted_volume=ask_submitted_volume,
            buy_filled_qty=buy_filled_qty,
            sell_filled_qty=sell_filled_qty,
            bid_fill_efficiency=bid_fill_efficiency,
            ask_fill_efficiency=ask_fill_efficiency,
            quote_metrics=quote_metrics or {},
            inventory_episode_metrics=inventory_episode_metrics or {},
            markout_mean_by_horizon=markout_mean_by_horizon or {},
            passive_markout_mean_by_horizon=passive_markout_mean_by_horizon or {},
            aggressive_markout_mean_by_horizon=aggressive_markout_mean_by_horizon or {},
            markout_eval_qty_by_horizon=markout_eval_qty_by_horizon or {},
            passive_markout_eval_qty_by_horizon=passive_markout_eval_qty_by_horizon or {},
            aggressive_markout_eval_qty_by_horizon=aggressive_markout_eval_qty_by_horizon or {},
            pnl_attribution=pnl_attribution or {},
            conversions_requested=conversions_requested,
        )

    @staticmethod
    def _markout_horizons() -> List[int]:
        return [1, 2, 5, 10]

    @staticmethod
    def _side_sign(side: str) -> int:
        return 1 if str(side).upper() == "BUY" else -1

    @staticmethod
    def _build_markout_summary(
        fills: List[Fill],
        timestamps: List[int],
        mid_by_timestamp: Dict[int, float],
    ) -> tuple[
        Dict[str, float | None],
        Dict[str, float | None],
        Dict[str, float | None],
        Dict[str, int],
        Dict[str, int],
        Dict[str, int],
    ]:
        horizons = BacktestEngine._markout_horizons()
        totals = {str(h): 0.0 for h in horizons}
        passive_totals = {str(h): 0.0 for h in horizons}
        aggressive_totals = {str(h): 0.0 for h in horizons}
        qtys = {str(h): 0 for h in horizons}
        passive_qtys = {str(h): 0 for h in horizons}
        aggressive_qtys = {str(h): 0 for h in horizons}

        timestamp_index = {timestamp: index for index, timestamp in enumerate(timestamps)}

        for fill in fills:
            fill_index = timestamp_index.get(fill.timestamp)
            if fill_index is None:
                continue
            sign = BacktestEngine._side_sign(fill.side)
            for horizon in horizons:
                future_index = fill_index + horizon
                if future_index >= len(timestamps):
                    continue
                future_mid = mid_by_timestamp.get(timestamps[future_index])
                if future_mid is None:
                    continue
                key = str(horizon)
                markout = (future_mid - fill.price) * sign
                weighted = markout * fill.quantity
                totals[key] += weighted
                qtys[key] += fill.quantity
                if fill.aggressive:
                    aggressive_totals[key] += weighted
                    aggressive_qtys[key] += fill.quantity
                else:
                    passive_totals[key] += weighted
                    passive_qtys[key] += fill.quantity

        def _to_mean(weighted_totals: Dict[str, float], weighted_qtys: Dict[str, int]) -> Dict[str, float | None]:
            return {
                key: (weighted_totals[key] / weighted_qtys[key]) if weighted_qtys[key] else None
                for key in weighted_totals
            }

        return (
            _to_mean(totals, qtys),
            _to_mean(passive_totals, passive_qtys),
            _to_mean(aggressive_totals, aggressive_qtys),
            qtys,
            passive_qtys,
            aggressive_qtys,
        )

    @staticmethod
    def _build_quote_metrics(quotes: List[Quote], stale_after_ticks: int = 3) -> Dict[str, float | int | None]:
        if not quotes:
            return {
                "active_tick_count": 0,
                "avg_quote_age_ticks": 0.0,
                "max_quote_age_ticks": 0,
                "refresh_count": 0,
                "bid_refresh_count": 0,
                "ask_refresh_count": 0,
                "stale_tick_count": 0,
                "stale_tick_ratio": 0.0,
                "stale_submitted_volume": 0,
            }

        ordered_quotes = sorted(quotes, key=lambda quote: quote.timestamp)
        bid_state: tuple[float | None, int] | None = None
        ask_state: tuple[float | None, int] | None = None
        bid_age = 0
        ask_age = 0
        age_sum = 0.0
        max_age = 0
        active_tick_count = 0
        refresh_count = 0
        bid_refresh_count = 0
        ask_refresh_count = 0
        stale_tick_count = 0
        stale_submitted_volume = 0

        for quote in ordered_quotes:
            tick_ages: List[int] = []
            tick_refreshed = False

            if quote.bid is not None and quote.bid_size > 0:
                bid_key = (quote.bid, quote.bid_size)
                if bid_key != bid_state:
                    bid_refresh_count += 1
                    tick_refreshed = True
                    bid_age = 1
                else:
                    bid_age += 1
                bid_state = bid_key
                tick_ages.append(bid_age)
            else:
                bid_state = None
                bid_age = 0

            if quote.ask is not None and quote.ask_size > 0:
                ask_key = (quote.ask, quote.ask_size)
                if ask_key != ask_state:
                    ask_refresh_count += 1
                    tick_refreshed = True
                    ask_age = 1
                else:
                    ask_age += 1
                ask_state = ask_key
                tick_ages.append(ask_age)
            else:
                ask_state = None
                ask_age = 0

            if not tick_ages:
                continue

            active_tick_count += 1
            age_sum += sum(tick_ages) / len(tick_ages)
            max_age = max(max_age, max(tick_ages))
            if tick_refreshed:
                refresh_count += 1

            stale_sizes = 0
            if quote.bid is not None and quote.bid_size > 0 and bid_age >= stale_after_ticks:
                stale_sizes += quote.bid_size
            if quote.ask is not None and quote.ask_size > 0 and ask_age >= stale_after_ticks:
                stale_sizes += quote.ask_size
            if stale_sizes > 0:
                stale_tick_count += 1
                stale_submitted_volume += stale_sizes

        return {
            "active_tick_count": active_tick_count,
            "avg_quote_age_ticks": (age_sum / active_tick_count) if active_tick_count else 0.0,
            "max_quote_age_ticks": max_age,
            "refresh_count": refresh_count,
            "bid_refresh_count": bid_refresh_count,
            "ask_refresh_count": ask_refresh_count,
            "stale_tick_count": stale_tick_count,
            "stale_tick_ratio": (stale_tick_count / active_tick_count) if active_tick_count else 0.0,
            "stale_submitted_volume": stale_submitted_volume,
        }

    @staticmethod
    def _build_inventory_episode_metrics(positions: List[int]) -> Dict[str, float | int | None]:
        if not positions:
            return {
                "positive_tick_count": 0,
                "negative_tick_count": 0,
                "flat_tick_count": 0,
                "one_sided_tick_ratio": 0.0,
                "sign_flip_count": 0,
                "episode_count": 0,
                "avg_unwind_ticks": None,
                "max_unwind_ticks": None,
                "total_unwind_ticks": 0,
                "open_episode_ticks": 0,
            }

        positive_tick_count = sum(1 for position in positions if position > 0)
        negative_tick_count = sum(1 for position in positions if position < 0)
        flat_tick_count = sum(1 for position in positions if position == 0)

        last_nonzero_sign = 0
        sign_flip_count = 0
        episode_start: int | None = None
        unwind_ticks: List[int] = []

        for index, position in enumerate(positions):
            sign = 1 if position > 0 else -1 if position < 0 else 0
            if sign != 0 and last_nonzero_sign != 0 and sign != last_nonzero_sign:
                sign_flip_count += 1
            if sign != 0:
                last_nonzero_sign = sign

            if position != 0 and episode_start is None:
                episode_start = index
            elif position == 0 and episode_start is not None:
                unwind_ticks.append(index - episode_start)
                episode_start = None

        open_episode_ticks = (len(positions) - episode_start) if episode_start is not None else 0
        total_ticks = len(positions)
        total_unwind_ticks = sum(unwind_ticks)

        return {
            "positive_tick_count": positive_tick_count,
            "negative_tick_count": negative_tick_count,
            "flat_tick_count": flat_tick_count,
            "one_sided_tick_ratio": ((positive_tick_count + negative_tick_count) / total_ticks) if total_ticks else 0.0,
            "sign_flip_count": sign_flip_count,
            "episode_count": len(unwind_ticks),
            "avg_unwind_ticks": (total_unwind_ticks / len(unwind_ticks)) if unwind_ticks else None,
            "max_unwind_ticks": max(unwind_ticks) if unwind_ticks else None,
            "total_unwind_ticks": total_unwind_ticks,
            "open_episode_ticks": open_episode_ticks,
        }

    @staticmethod
    def _build_pnl_attribution(
        fills: List[Fill],
        timestamps: List[int],
        mid_by_timestamp: Dict[int, float],
    ) -> Dict[str, float]:
        fills_by_timestamp: Dict[int, List[Fill]] = {}
        for fill in fills:
            fills_by_timestamp.setdefault(fill.timestamp, []).append(fill)

        inventory_drift = 0.0
        execution_edge_total = 0.0
        make_edge = 0.0
        take_edge = 0.0
        passive_adverse_selection_1 = 0.0
        aggressive_adverse_selection_1 = 0.0

        current_position = 0
        previous_mid: float | None = None

        for index, timestamp in enumerate(timestamps):
            current_mid = mid_by_timestamp.get(timestamp)
            if current_mid is None:
                continue
            if previous_mid is not None:
                inventory_drift += current_position * (current_mid - previous_mid)

            next_mid = None
            if index + 1 < len(timestamps):
                next_mid = mid_by_timestamp.get(timestamps[index + 1])

            for fill in fills_by_timestamp.get(timestamp, []):
                sign = BacktestEngine._side_sign(fill.side)
                execution_edge = (current_mid - fill.price) * sign * fill.quantity
                execution_edge_total += execution_edge
                if fill.aggressive:
                    take_edge += execution_edge
                else:
                    make_edge += execution_edge

                if next_mid is not None:
                    post_fill_move = (next_mid - current_mid) * sign * fill.quantity
                    if fill.aggressive:
                        aggressive_adverse_selection_1 += post_fill_move
                    else:
                        passive_adverse_selection_1 += post_fill_move

                current_position += sign * fill.quantity

            previous_mid = current_mid

        return {
            "spread_capture": execution_edge_total,
            "execution_edge_total": execution_edge_total,
            "make_edge": make_edge,
            "take_edge": take_edge,
            "inventory_drift": inventory_drift,
            "passive_adverse_selection_1": passive_adverse_selection_1,
            "aggressive_adverse_selection_1": aggressive_adverse_selection_1,
            "adverse_selection_1": passive_adverse_selection_1 + aggressive_adverse_selection_1,
            "residual_vs_final_pnl": 0.0,
        }

    @staticmethod
    def _merge_mean_dict(
        left_mean: Dict[str, float | None],
        left_qty: Dict[str, int],
        right_mean: Dict[str, float | None],
        right_qty: Dict[str, int],
    ) -> tuple[Dict[str, float | None], Dict[str, int]]:
        keys = set(left_mean) | set(left_qty) | set(right_mean) | set(right_qty)
        merged_mean: Dict[str, float | None] = {}
        merged_qty: Dict[str, int] = {}
        for key in keys:
            left_count = int(left_qty.get(key, 0))
            right_count = int(right_qty.get(key, 0))
            total_count = left_count + right_count
            merged_qty[key] = total_count
            if total_count <= 0:
                merged_mean[key] = None
                continue
            weighted_sum = 0.0
            if left_count > 0 and left_mean.get(key) is not None:
                weighted_sum += float(left_mean[key]) * left_count
            if right_count > 0 and right_mean.get(key) is not None:
                weighted_sum += float(right_mean[key]) * right_count
            merged_mean[key] = weighted_sum / total_count
        return merged_mean, merged_qty

    @staticmethod
    def _merge_robustness_summaries(
        left: RobustnessSummary | None,
        right: RobustnessSummary,
        *,
        max_drawdown: float | None = None,
    ) -> RobustnessSummary:
        if left is None:
            return RobustnessSummary(**asdict(right))

        quote_metrics = {
            "active_tick_count": int(left.quote_metrics.get("active_tick_count", 0)) + int(right.quote_metrics.get("active_tick_count", 0)),
            "avg_quote_age_ticks": 0.0,
            "max_quote_age_ticks": max(
                int(left.quote_metrics.get("max_quote_age_ticks", 0)),
                int(right.quote_metrics.get("max_quote_age_ticks", 0)),
            ),
            "refresh_count": int(left.quote_metrics.get("refresh_count", 0)) + int(right.quote_metrics.get("refresh_count", 0)),
            "bid_refresh_count": int(left.quote_metrics.get("bid_refresh_count", 0)) + int(right.quote_metrics.get("bid_refresh_count", 0)),
            "ask_refresh_count": int(left.quote_metrics.get("ask_refresh_count", 0)) + int(right.quote_metrics.get("ask_refresh_count", 0)),
            "stale_tick_count": int(left.quote_metrics.get("stale_tick_count", 0)) + int(right.quote_metrics.get("stale_tick_count", 0)),
            "stale_tick_ratio": 0.0,
            "stale_submitted_volume": int(left.quote_metrics.get("stale_submitted_volume", 0)) + int(right.quote_metrics.get("stale_submitted_volume", 0)),
        }
        active_tick_count = int(quote_metrics["active_tick_count"])
        quote_age_weighted_sum = (
            float(left.quote_metrics.get("avg_quote_age_ticks", 0.0)) * int(left.quote_metrics.get("active_tick_count", 0))
            + float(right.quote_metrics.get("avg_quote_age_ticks", 0.0)) * int(right.quote_metrics.get("active_tick_count", 0))
        )
        quote_metrics["avg_quote_age_ticks"] = (quote_age_weighted_sum / active_tick_count) if active_tick_count else 0.0
        quote_metrics["stale_tick_ratio"] = (
            float(quote_metrics["stale_tick_count"]) / active_tick_count
            if active_tick_count else 0.0
        )

        inventory_metrics = {
            "positive_tick_count": int(left.inventory_episode_metrics.get("positive_tick_count", 0)) + int(right.inventory_episode_metrics.get("positive_tick_count", 0)),
            "negative_tick_count": int(left.inventory_episode_metrics.get("negative_tick_count", 0)) + int(right.inventory_episode_metrics.get("negative_tick_count", 0)),
            "flat_tick_count": int(left.inventory_episode_metrics.get("flat_tick_count", 0)) + int(right.inventory_episode_metrics.get("flat_tick_count", 0)),
            "one_sided_tick_ratio": 0.0,
            "sign_flip_count": int(left.inventory_episode_metrics.get("sign_flip_count", 0)) + int(right.inventory_episode_metrics.get("sign_flip_count", 0)),
            "episode_count": int(left.inventory_episode_metrics.get("episode_count", 0)) + int(right.inventory_episode_metrics.get("episode_count", 0)),
            "avg_unwind_ticks": None,
            "max_unwind_ticks": None,
            "total_unwind_ticks": int(left.inventory_episode_metrics.get("total_unwind_ticks", 0)) + int(right.inventory_episode_metrics.get("total_unwind_ticks", 0)),
            "open_episode_ticks": int(left.inventory_episode_metrics.get("open_episode_ticks", 0)) + int(right.inventory_episode_metrics.get("open_episode_ticks", 0)),
        }
        total_ticks = inventory_metrics["positive_tick_count"] + inventory_metrics["negative_tick_count"] + inventory_metrics["flat_tick_count"]
        inventory_metrics["one_sided_tick_ratio"] = (
            (inventory_metrics["positive_tick_count"] + inventory_metrics["negative_tick_count"]) / total_ticks
            if total_ticks else 0.0
        )
        episode_count = int(inventory_metrics["episode_count"])
        if episode_count > 0:
            inventory_metrics["avg_unwind_ticks"] = float(inventory_metrics["total_unwind_ticks"]) / episode_count
            max_candidates = [
                left.inventory_episode_metrics.get("max_unwind_ticks"),
                right.inventory_episode_metrics.get("max_unwind_ticks"),
            ]
            max_candidates = [int(value) for value in max_candidates if value is not None]
            inventory_metrics["max_unwind_ticks"] = max(max_candidates) if max_candidates else None

        markout_mean_by_horizon, markout_eval_qty_by_horizon = BacktestEngine._merge_mean_dict(
            left.markout_mean_by_horizon,
            left.markout_eval_qty_by_horizon,
            right.markout_mean_by_horizon,
            right.markout_eval_qty_by_horizon,
        )
        passive_markout_mean_by_horizon, passive_markout_eval_qty_by_horizon = BacktestEngine._merge_mean_dict(
            left.passive_markout_mean_by_horizon,
            left.passive_markout_eval_qty_by_horizon,
            right.passive_markout_mean_by_horizon,
            right.passive_markout_eval_qty_by_horizon,
        )
        aggressive_markout_mean_by_horizon, aggressive_markout_eval_qty_by_horizon = BacktestEngine._merge_mean_dict(
            left.aggressive_markout_mean_by_horizon,
            left.aggressive_markout_eval_qty_by_horizon,
            right.aggressive_markout_mean_by_horizon,
            right.aggressive_markout_eval_qty_by_horizon,
        )

        pnl_attribution = {
            key: float(left.pnl_attribution.get(key, 0.0)) + float(right.pnl_attribution.get(key, 0.0))
            for key in set(left.pnl_attribution) | set(right.pnl_attribution)
        }

        return BacktestEngine._build_robustness_summary(
            submitted_volume=left.submitted_volume + right.submitted_volume,
            traded_volume=left.traded_volume + right.traded_volume,
            aggressive_qty=left.aggressive_qty + right.aggressive_qty,
            passive_qty=left.passive_qty + right.passive_qty,
            aggressive_trades=left.aggressive_trades + right.aggressive_trades,
            passive_trades=left.passive_trades + right.passive_trades,
            tick_count=left.tick_count + right.tick_count,
            position_ratio_sum=(
                left.avg_abs_position_ratio * left.tick_count
                + right.avg_abs_position_ratio * right.tick_count
            ),
            near_limit_tick_count=left.near_limit_tick_count + right.near_limit_tick_count,
            passive_eval_qty=left.passive_eval_qty + right.passive_eval_qty,
            passive_adverse_qty=left.passive_adverse_qty + right.passive_adverse_qty,
            passive_edge_sum=(
                (left.passive_post_fill_edge or 0.0) * left.passive_eval_qty
                + (right.passive_post_fill_edge or 0.0) * right.passive_eval_qty
            ),
            max_drawdown=max_drawdown,
            bid_submitted_volume=left.bid_submitted_volume + right.bid_submitted_volume,
            ask_submitted_volume=left.ask_submitted_volume + right.ask_submitted_volume,
            buy_filled_qty=left.buy_filled_qty + right.buy_filled_qty,
            sell_filled_qty=left.sell_filled_qty + right.sell_filled_qty,
            quote_metrics=quote_metrics,
            inventory_episode_metrics=inventory_metrics,
            markout_mean_by_horizon=markout_mean_by_horizon,
            passive_markout_mean_by_horizon=passive_markout_mean_by_horizon,
            aggressive_markout_mean_by_horizon=aggressive_markout_mean_by_horizon,
            markout_eval_qty_by_horizon=markout_eval_qty_by_horizon,
            passive_markout_eval_qty_by_horizon=passive_markout_eval_qty_by_horizon,
            aggressive_markout_eval_qty_by_horizon=aggressive_markout_eval_qty_by_horizon,
            pnl_attribution=pnl_attribution,
            conversions_requested=left.conversions_requested + right.conversions_requested,
        )

    def run_day(self, day: str, mode: TradeMatchingMode = TradeMatchingMode.queue) -> DaySummary:
        price_file = f"prices_round_{self.round_num}_day_{day}.csv"
        trade_file = f"trades_round_{self.round_num}_day_{day}.csv"

        prices_df = self.loader.load_prices(price_file)
        order_history = self.loader.order_depth_history(prices_df)
        observation_history = self.loader.observation_history(prices_df)
        market_trades = self.loader.load_trade_objects(trade_file)
        market_by_timestamp = self.loader.group_trades_by_timestamp(market_trades)
        price_rows = {
            (int(row["timestamp"]), str(row["product"])): row
            for _, row in prices_df.iterrows()
        }

        products = sorted(prices_df["product"].unique())
        listings = self.loader.build_listings(products)
        trader = self._load_trader()

        cash_by_product = {product: 0.0 for product in products}
        turnover_by_product = {product: 0.0 for product in products}
        positions = {product: 0 for product in products}
        max_abs_position = {product: 0 for product in products}
        limits = self._get_position_limits()
        submitted_volume_by_product = {product: 0 for product in products}
        bid_submitted_volume_by_product = {product: 0 for product in products}
        ask_submitted_volume_by_product = {product: 0 for product in products}
        position_ratio_sum_by_product = {product: 0.0 for product in products}
        near_limit_tick_count_by_product = {product: 0 for product in products}
        tick_count_by_product = {product: 0 for product in products}
        position_path_by_product = {product: [] for product in products}

        recent_own_trades: Dict[str, List[Trade]] = {product: [] for product in products}
        all_fills: List[Fill] = []
        all_quotes: List[Quote] = []
        all_feature_ticks: List[FeatureTick] = []
        all_observation_ticks: List[ObservationTick] = []
        all_conversion_ticks: List[ConversionTick] = []
        equity_curve: List[Tuple[int, float]] = []
        try:
            day_value: int | str = int(day)
        except ValueError:
            day_value = day
        trader_data = json.dumps(
            {"_backtest": {"round": self.round_num, "day": day_value}},
            separators=(",", ":"),
        )
        total_conversions_requested = 0

        timestamps = sorted(order_history.keys())

        os.environ["INTERNAL_BACKTEST"] = "1"
        try:
            for timestamp in timestamps:
                order_depths = order_history[timestamp]
                current_market_trades_by_product = market_by_timestamp.get(timestamp, {})
                observations = observation_history.get(timestamp, self.loader.empty_observation())

                for product in products:
                    row = price_rows.get((timestamp, product))
                    if row is None:
                        continue
                    values = self.loader.row_to_observation_values(row)
                    if values:
                        all_observation_ticks.append(ObservationTick(timestamp=timestamp, symbol=product, values=values))

                state = TradingState(
                    traderData=trader_data,
                    timestamp=timestamp,
                    listings=listings,
                    order_depths=order_depths,
                    own_trades=recent_own_trades,
                    market_trades=market_by_timestamp.get(timestamp, {}),
                    position=positions,
                    observations=observations,
                )

                run_out = trader.run(state)
                trader_result = run_out[0] if len(run_out) > 0 and run_out[0] is not None else {}
                conversions_requested_raw = run_out[1] if len(run_out) > 1 else 0
                trader_data = run_out[2] if len(run_out) > 2 else trader_data
                try:
                    conversions_requested = int(conversions_requested_raw or 0)
                except (TypeError, ValueError):
                    conversions_requested = 0
                total_conversions_requested += abs(conversions_requested)
                all_conversion_ticks.append(ConversionTick(timestamp=timestamp, conversions=conversions_requested))
                # 4th return value is optional: {product: {feature_name: value}}
                strategy_features: Dict[str, Dict[str, float]] = run_out[3] if len(run_out) > 3 else {}
                for sym, feats in strategy_features.items():
                    if feats:
                        all_feature_ticks.append(FeatureTick(timestamp=timestamp, symbol=sym, features=feats))

                # Parse gap exploit prices from trader_data to annotate fills.
                # Strategy stores _gap_buy_px / _gap_sell_px in product memory this tick.
                _gap_prices: Dict[str, Dict[str, set]] = {}
                try:
                    _td_parsed = json.loads(trader_data) if trader_data else {}
                    _prod_mems = _td_parsed.get("products", {}) if isinstance(_td_parsed, dict) else {}
                    for _prod, _mem in _prod_mems.items():
                        if isinstance(_mem, dict):
                            _gap_prices[_prod] = {
                                "buy":  set(_mem.get("_gap_buy_px",  [])),
                                "sell": set(_mem.get("_gap_sell_px", [])),
                            }
                except Exception:
                    pass

                next_own_trades: Dict[str, List[Trade]] = {product: [] for product in products}

                for product in products:
                    orders = trader_result.get(product, [])
                    safe_orders = self._respect_exchange_limits(product, positions.get(product, 0), orders)
                    submitted_volume_by_product[product] += sum(abs(order.quantity) for order in safe_orders)
                    bid_submitted_volume_by_product[product] += sum(order.quantity for order in safe_orders if order.quantity > 0)
                    ask_submitted_volume_by_product[product] += sum(-order.quantity for order in safe_orders if order.quantity < 0)

                    buy_orders = [order for order in safe_orders if order.quantity > 0]
                    sell_orders = [order for order in safe_orders if order.quantity < 0]
                    best_bid = max((order.price for order in buy_orders), default=None)
                    best_ask = min((order.price for order in sell_orders), default=None)
                    all_quotes.append(Quote(
                        timestamp=timestamp,
                        symbol=product,
                        bid=best_bid,
                        ask=best_ask,
                        bid_size=sum(order.quantity for order in buy_orders if order.price == best_bid) if best_bid is not None else 0,
                        ask_size=sum(-order.quantity for order in sell_orders if order.price == best_ask) if best_ask is not None else 0,
                    ))

                    fills = self._simulate_fills(
                        order_depths.get(product, OrderDepth()),
                        safe_orders,
                        current_market_trades_by_product.get(product, []),
                        timestamp,
                        mode,
                    )

                    _gap_buy  = _gap_prices.get(product, {}).get("buy",  set())
                    _gap_sell = _gap_prices.get(product, {}).get("sell", set())
                    for fill in fills:
                        if fill.aggressive:
                            fill.gap_exploit = (
                                (fill.side == "BUY"  and fill.price in _gap_buy) or
                                (fill.side == "SELL" and fill.price in _gap_sell)
                            )

                    for fill in fills:
                        all_fills.append(fill)
                        signed_quantity = fill.quantity if fill.side == "BUY" else -fill.quantity
                        positions[product] += signed_quantity
                        turnover_by_product[product] += fill.quantity * fill.price
                        max_abs_position[product] = max(max_abs_position[product], abs(positions[product]))

                        if fill.side == "BUY":
                            cash_by_product[product] -= fill.quantity * fill.price
                            own_trade = Trade(symbol=fill.symbol, price=fill.price, quantity=fill.quantity, buyer="SUBMISSION", seller=None, timestamp=timestamp)
                        else:
                            cash_by_product[product] += fill.quantity * fill.price
                            own_trade = Trade(symbol=fill.symbol, price=fill.price, quantity=fill.quantity, buyer=None, seller="SUBMISSION", timestamp=timestamp)

                        next_own_trades[product].append(own_trade)

                recent_own_trades = next_own_trades
                marked_equity = 0.0
                for product in products:
                    marked_equity += cash_by_product[product]
                    limit = limits.get(product, 0)
                    position_ratio = (abs(positions[product]) / float(limit)) if limit else 0.0
                    position_ratio_sum_by_product[product] += position_ratio
                    tick_count_by_product[product] += 1
                    if position_ratio >= 0.75:
                        near_limit_tick_count_by_product[product] += 1
                    order_depth = order_depths.get(product)
                    if order_depth is not None:
                        marked_equity += positions[product] * self._mid_price(order_depth)
                    position_path_by_product[product].append(positions[product])
                equity_curve.append((timestamp, marked_equity))

        finally:
            os.environ.pop("INTERNAL_BACKTEST", None)

        product_summaries: Dict[str, ProductSummary] = {}
        total_pnl = 0.0
        last_timestamp = timestamps[-1]
        next_timestamp_by_current = {
            timestamps[index]: timestamps[index + 1]
            for index in range(len(timestamps) - 1)
        }
        mid_by_product_and_timestamp = {
            product: {
                timestamp: self._mid_price(order_history[timestamp][product])
                for timestamp in timestamps
            }
            for product in products
        }

        aggressive_qty_by_product = {product: 0 for product in products}
        passive_qty_by_product = {product: 0 for product in products}
        aggressive_trades_by_product = {product: 0 for product in products}
        passive_trades_by_product = {product: 0 for product in products}
        passive_eval_qty_by_product = {product: 0 for product in products}
        passive_adverse_qty_by_product = {product: 0 for product in products}
        passive_edge_sum_by_product = {product: 0.0 for product in products}
        buy_filled_qty_by_product = {product: 0 for product in products}
        sell_filled_qty_by_product = {product: 0 for product in products}

        for fill in all_fills:
            if fill.side == "BUY":
                buy_filled_qty_by_product[fill.symbol] += fill.quantity
            else:
                sell_filled_qty_by_product[fill.symbol] += fill.quantity

            if fill.aggressive:
                aggressive_qty_by_product[fill.symbol] += fill.quantity
                aggressive_trades_by_product[fill.symbol] += 1
            else:
                passive_qty_by_product[fill.symbol] += fill.quantity
                passive_trades_by_product[fill.symbol] += 1
                next_timestamp = next_timestamp_by_current.get(fill.timestamp)
                if next_timestamp is None:
                    continue
                next_mid = mid_by_product_and_timestamp.get(fill.symbol, {}).get(next_timestamp)
                if next_mid is None:
                    continue
                signed_edge = (next_mid - fill.price) * (1 if fill.side == "BUY" else -1)
                passive_eval_qty_by_product[fill.symbol] += fill.quantity
                passive_edge_sum_by_product[fill.symbol] += signed_edge * fill.quantity
                if signed_edge < 0:
                    passive_adverse_qty_by_product[fill.symbol] += fill.quantity

        day_drawdown = self._max_drawdown(equity_curve)
        total_robustness: RobustnessSummary | None = None

        for product in products:
            ending_cash = cash_by_product[product]
            final_mid = self._mid_price(order_history[last_timestamp][product])
            pnl = ending_cash + positions[product] * final_mid
            total_pnl += pnl
            product_fills = [fill for fill in all_fills if fill.symbol == product]
            product_quotes = [quote for quote in all_quotes if quote.symbol == product]
            quote_metrics = self._build_quote_metrics(product_quotes)
            inventory_episode_metrics = self._build_inventory_episode_metrics(position_path_by_product[product])
            (
                markout_mean_by_horizon,
                passive_markout_mean_by_horizon,
                aggressive_markout_mean_by_horizon,
                markout_eval_qty_by_horizon,
                passive_markout_eval_qty_by_horizon,
                aggressive_markout_eval_qty_by_horizon,
            ) = self._build_markout_summary(
                product_fills,
                timestamps,
                mid_by_product_and_timestamp[product],
            )
            pnl_attribution = self._build_pnl_attribution(
                product_fills,
                timestamps,
                mid_by_product_and_timestamp[product],
            )
            pnl_attribution["residual_vs_final_pnl"] = pnl - (
                pnl_attribution.get("execution_edge_total", 0.0)
                + pnl_attribution.get("inventory_drift", 0.0)
            )

            robustness = self._build_robustness_summary(
                submitted_volume=submitted_volume_by_product[product],
                traded_volume=sum(fill.quantity for fill in product_fills),
                aggressive_qty=aggressive_qty_by_product[product],
                passive_qty=passive_qty_by_product[product],
                aggressive_trades=aggressive_trades_by_product[product],
                passive_trades=passive_trades_by_product[product],
                tick_count=tick_count_by_product[product],
                position_ratio_sum=position_ratio_sum_by_product[product],
                near_limit_tick_count=near_limit_tick_count_by_product[product],
                passive_eval_qty=passive_eval_qty_by_product[product],
                passive_adverse_qty=passive_adverse_qty_by_product[product],
                passive_edge_sum=passive_edge_sum_by_product[product],
                bid_submitted_volume=bid_submitted_volume_by_product[product],
                ask_submitted_volume=ask_submitted_volume_by_product[product],
                buy_filled_qty=buy_filled_qty_by_product[product],
                sell_filled_qty=sell_filled_qty_by_product[product],
                quote_metrics=quote_metrics,
                inventory_episode_metrics=inventory_episode_metrics,
                markout_mean_by_horizon=markout_mean_by_horizon,
                passive_markout_mean_by_horizon=passive_markout_mean_by_horizon,
                aggressive_markout_mean_by_horizon=aggressive_markout_mean_by_horizon,
                markout_eval_qty_by_horizon=markout_eval_qty_by_horizon,
                passive_markout_eval_qty_by_horizon=passive_markout_eval_qty_by_horizon,
                aggressive_markout_eval_qty_by_horizon=aggressive_markout_eval_qty_by_horizon,
                pnl_attribution=pnl_attribution,
                conversions_requested=0,
            )
            product_summaries[product] = ProductSummary(
                symbol=product, pnl=pnl, ending_position=positions[product],
                trades=len(product_fills), traded_volume=sum(fill.quantity for fill in product_fills),
                turnover=turnover_by_product[product], max_abs_position=max_abs_position[product],
                robustness=robustness,
            )
            total_robustness = self._merge_robustness_summaries(total_robustness, robustness)

        if total_robustness is None:
            total_robustness = self._build_robustness_summary(
                submitted_volume=0,
                traded_volume=0,
                aggressive_qty=0,
                passive_qty=0,
                aggressive_trades=0,
                passive_trades=0,
                tick_count=0,
                position_ratio_sum=0.0,
                near_limit_tick_count=0,
                passive_eval_qty=0,
                passive_adverse_qty=0,
                passive_edge_sum=0.0,
                max_drawdown=day_drawdown,
                conversions_requested=total_conversions_requested,
            )
        else:
            total_robustness.max_drawdown = day_drawdown
            total_robustness.conversions_requested = total_conversions_requested

        return DaySummary(
            day=day,
            pnl=total_pnl,
            fills=all_fills,
            product_summaries=product_summaries,
            equity_curve=equity_curve,
            robustness=total_robustness,
            quotes=all_quotes,
            feature_ticks=all_feature_ticks,
            observation_ticks=all_observation_ticks,
            conversion_ticks=all_conversion_ticks,
        )


def _result_to_jsonable(summary: DaySummary) -> Dict[str, object]:
    return {
        "day": summary.day,
        "pnl": summary.pnl,
        "fills": [asdict(fill) for fill in summary.fills],
        "product_summaries": {product: asdict(ps) for product, ps in summary.product_summaries.items()},
        "equity_curve": summary.equity_curve,
        "robustness": asdict(summary.robustness),
        "quotes": [asdict(q) for q in summary.quotes],
        "feature_ticks": [{"timestamp": ft.timestamp, "symbol": ft.symbol, **ft.features}
                          for ft in summary.feature_ticks],
        "observation_ticks": [{"timestamp": ot.timestamp, "symbol": ot.symbol, **ot.values}
                              for ot in summary.observation_ticks],
        "conversion_ticks": [asdict(ct) for ct in summary.conversion_ticks],
    }


def _chain_equity_curves(summaries: List[DaySummary]) -> List[Tuple[int, float]]:
    chained: List[Tuple[int, float]] = []
    ts_offset = 0
    pnl_carry = 0.0

    for summary in summaries:
        curve = summary.equity_curve
        if curve:
            for timestamp, value in curve:
                chained.append((timestamp + ts_offset, value + pnl_carry))
            tick = (curve[1][0] - curve[0][0]) if len(curve) >= 2 else 100
            ts_offset += curve[-1][0] + tick
        pnl_carry += summary.pnl

    return chained


def aggregate_day_summaries(summaries: List[DaySummary]) -> Dict[str, object]:
    total_pnl = sum(summary.pnl for summary in summaries)
    chained_equity = _chain_equity_curves(summaries)
    total_drawdown = BacktestEngine._max_drawdown(chained_equity)

    per_product_pnl: Dict[str, float] = {}
    per_product_trades: Dict[str, int] = {}
    per_product_max_pos: Dict[str, int] = {}
    per_product_robustness: Dict[str, RobustnessSummary] = {}

    for summary in summaries:
        for symbol, product_summary in summary.product_summaries.items():
            per_product_pnl[symbol] = per_product_pnl.get(symbol, 0.0) + product_summary.pnl
            per_product_trades[symbol] = per_product_trades.get(symbol, 0) + product_summary.trades
            per_product_max_pos[symbol] = max(per_product_max_pos.get(symbol, 0), product_summary.max_abs_position)
            per_product_robustness[symbol] = BacktestEngine._merge_robustness_summaries(
                per_product_robustness.get(symbol),
                product_summary.robustness,
            )

    total_robustness: RobustnessSummary | None = None
    for summary in summaries:
        total_robustness = BacktestEngine._merge_robustness_summaries(total_robustness, summary.robustness)
    if total_robustness is None:
        total_robustness = BacktestEngine._build_robustness_summary(
            submitted_volume=0,
            traded_volume=0,
            aggressive_qty=0,
            passive_qty=0,
            aggressive_trades=0,
            passive_trades=0,
            tick_count=0,
            position_ratio_sum=0.0,
            near_limit_tick_count=0,
            passive_eval_qty=0,
            passive_adverse_qty=0,
            passive_edge_sum=0.0,
            max_drawdown=total_drawdown,
        )
    else:
        total_robustness.max_drawdown = total_drawdown

    return {
        "total_pnl": total_pnl,
        "per_product_pnl": per_product_pnl,
        "per_product_trades": per_product_trades,
        "per_product_max_pos": per_product_max_pos,
        "robustness": asdict(total_robustness),
        "per_product_robustness": {symbol: asdict(metrics) for symbol, metrics in per_product_robustness.items()},
    }


def _format_results_table(summaries: List[DaySummary], aggregate: Dict[str, object],
                          display_product: str | None = None) -> str:
    """Format backtest results as a compact table grouped by product.

    display_product — if set, only rows for that symbol are shown (TOTAL row still
    shows the single-product subtotal rather than the multi-product aggregate).
    """
    COLS   = ["pnl", "trades", "volume", "max_pos", "end_pos", "make", "take", "inv"]
    HEADS  = ["pnl", "trades", "vol", "max", "end", "make", "take", "inv"]

    def ps_cells(ps: ProductSummary) -> List[str]:
        return [
            f"{ps.pnl:,.0f}",
            str(ps.trades),
            str(ps.traded_volume),
            str(ps.max_abs_position),
            str(ps.ending_position),
            str(ps.robustness.passive_qty),
            str(ps.robustness.aggressive_qty),
            f"{ps.robustness.avg_abs_position_ratio:.3f}",
        ]

    def sub_cells(pss: List[ProductSummary]) -> List[str]:
        """Aggregate a list of per-day ProductSummaries for one product."""
        return [
            f"{sum(p.pnl for p in pss):,.0f}",
            str(sum(p.trades for p in pss)),
            str(sum(p.traded_volume for p in pss)),
            str(max(p.max_abs_position for p in pss)),
            str(pss[-1].ending_position),
            str(sum(p.robustness.passive_qty for p in pss)),
            str(sum(p.robustness.aggressive_qty for p in pss)),
            f"{sum(p.robustness.avg_abs_position_ratio for p in pss) / len(pss):.3f}",
        ]

    def total_cells(agg: Dict) -> List[str]:
        r = agg["robustness"]
        return [
            f"{agg['total_pnl']:,.0f}",
            str(r["passive_trades"] + r["aggressive_trades"]),
            str(r["traded_volume"]),
            "-",
            "-",
            str(r["passive_qty"]),
            str(r["aggressive_qty"]),
            f"{r['avg_abs_position_ratio']:.3f}",
        ]

    # Collect all symbols in order (optionally filtered)
    symbols = list(dict.fromkeys(
        sym for s in summaries for sym in s.product_summaries
    ))
    if display_product is not None:
        symbols = [s for s in symbols if s == display_product]

    # Build display rows: (label_col, day_col, cells, is_subtotal)
    rows: List[tuple] = []
    for sym in symbols:
        per_day = [s.product_summaries[sym] for s in summaries if sym in s.product_summaries]
        for i, (summary, ps) in enumerate(
            [(s, s.product_summaries[sym]) for s in summaries if sym in s.product_summaries]
        ):
            label = sym if i == 0 else ""
            rows.append((label, f"day {summary.day}", ps_cells(ps), False))
        rows.append(("subtotal", "", sub_cells(per_day), True))

    if display_product is not None and symbols:
        # Show per-product total instead of multi-product aggregate
        sym = symbols[0]
        per_day_all = [s.product_summaries[sym] for s in summaries if sym in s.product_summaries]
        rows.append(("TOTAL", f"{len(summaries)} day(s)", sub_cells(per_day_all), True))
    else:
        rows.append(("TOTAL", f"{len(summaries)} day(s)", total_cells(aggregate), True))

    # Column widths
    lbl_w  = max(len(r[0]) for r in rows)
    day_w  = max(len(r[1]) for r in rows)
    col_ws = [max(len(HEADS[i]), max(len(r[2][i]) for r in rows)) for i in range(len(COLS))]

    def sep(char="─", mid="┼") -> str:
        parts = [char * (lbl_w + 2), char * (day_w + 2)]
        parts += [char * (w + 2) for w in col_ws]
        return "┼".join(parts) if mid == "┼" else "╪".join(parts)

    def fmt_row(label, day, cells, bold=False) -> str:
        parts = [f" {label:<{lbl_w}} ", f" {day:<{day_w}} "]
        parts += [f" {c:>{w}} " for c, w in zip(cells, col_ws)]
        return "│".join(parts)

    lines: List[str] = []
    # header
    lines.append(sep())
    lines.append(fmt_row("product", "day", HEADS))
    lines.append(sep("═", "╪"))

    prev_sym = None
    for label, day, cells, is_sub in rows:
        cur_sym = label if label not in ("", "subtotal", "TOTAL") else prev_sym
        # separator between products (before subtotal of previous group)
        if is_sub and label == "subtotal":
            lines.append(fmt_row("  └ subtotal", "", cells))
            lines.append(sep())
            prev_sym = None
            continue
        if label == "TOTAL":
            lines.append(fmt_row("TOTAL", day, cells))
            continue
        prev_sym = cur_sym or prev_sym
        lines.append(fmt_row(label, day, cells))

    return "\n".join(lines)


def _format_drawdown_summary(summaries: List[DaySummary], aggregate: Dict[str, object]) -> str:
    """Format max-drawdown lines (absolute + %) for each day and overall."""
    lines: list[str] = []
    width = 62

    lines.append("─" * width)
    lines.append(f"  {'Drawdown summary':30s}  {'abs':>10}   {'%':>7}")
    lines.append("─" * width)

    for s in summaries:
        dd_abs, peak = BacktestEngine._max_drawdown_full(s.equity_curve)
        pct = (dd_abs / peak * 100) if peak > 0 else float("nan")
        pct_str = f"{pct:6.1f}%" if not (pct != pct) else "   n/a"
        lines.append(f"  Day {s.day}  {'':24s}  {dd_abs:>10,.0f}   {pct_str}")

    # Total drawdown on chained equity curve (peak-to-trough across all days)
    chained = _chain_equity_curves(summaries)
    total_dd, total_peak = BacktestEngine._max_drawdown_full(chained)
    total_pct = (total_dd / total_peak * 100) if total_peak > 0 else float("nan")
    total_pct_str = f"{total_pct:6.1f}%" if not (total_pct != total_pct) else "   n/a"
    lines.append("─" * width)
    lines.append(f"  {'TOTAL (chained equity)':30s}  {total_dd:>10,.0f}   {total_pct_str}")
    lines.append("─" * width)

    return "\n".join(lines)


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prosperity backtest runner (any round)")
    parser.add_argument("--strategy", required=True, help="Module or alias: champion/leo/theo/pietro")
    parser.add_argument("--round", type=int, default=0, help="Round number (default 0)")
    parser.add_argument("--days", nargs="*", help="Days to run, e.g. -2 -1")
    parser.add_argument("--data-dir", default="data", help="Data root or per-round directory with CSV files")
    parser.add_argument("--json-out", help="Optional JSON output file")
    parser.add_argument("--display-product", default=None,
                        help="Only show this product's rows in the results table (e.g. ASH_COATED_OSMIUM)")
    parser.add_argument(
        "--execution-rule",
        "--match-trades",
        dest="execution_rule",
        default="queue",
        choices=["queue", "all", "worse", "none", "realistic"],
        help=(
            "Passive fill mode against same-tick market trades. "
            "queue=one-iteration queue heuristic using displayed size ahead at your price, "
            "all=fill at or better than your price (optimistic), "
            "worse=fill only if trade went strictly through your price (conservative), "
            "realistic=most accurate: queue-ahead at exact price, proportional fill on through-trades, "
            "none=no passive fills at all."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    mode = TradeMatchingMode(args.execution_rule)
    engine = BacktestEngine(args.data_dir, args.strategy, round_num=args.round)
    days = args.days or engine.loader.available_days(args.round)
    if not days:
        raise RuntimeError("No price files found in the selected data directory.")
    days = sorted(days, key=lambda d: int(d))

    summaries = [engine.run_day(day, mode=mode) for day in days]

    aggregate = aggregate_day_summaries(summaries)
    print(_format_results_table(summaries, aggregate, display_product=args.display_product))
    print(_format_drawdown_summary(summaries, aggregate))

    if args.json_out:
        payload = {
            "strategy": args.strategy,
            "round": args.round,
            "execution_rule": args.execution_rule,
            "summary": aggregate,
            "days": [_result_to_jsonable(s) for s in summaries],
        }
        output_path = Path(args.json_out)
        # If a directory is provided, create it and generate a default filename
        if str(output_path).endswith('/') or output_path.is_dir():
            output_path.mkdir(parents=True, exist_ok=True)
            output_path = output_path / f"{args.strategy}_round{args.round}.json"
        else:
            # Ensure parent directory exists for file paths
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
