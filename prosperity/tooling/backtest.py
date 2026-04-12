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


STRATEGY_ALIASES = {name: f"submissions.{name}" for name in MEMBER_OVERRIDES}


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


@dataclass
class Quote:
    timestamp: int
    symbol: str
    bid: float | None   # best buy order price submitted (None if no buy orders)
    ask: float | None   # best sell order price submitted (None if no sell orders)


@dataclass
class FeatureTick:
    timestamp: int
    symbol: str
    features: Dict[str, float]   # e.g. {"Reservation": 10001.5}


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


class BacktestEngine:
    def __init__(self, data_dir: str | Path, strategy_module: str, round_num: int = 0):
        self.loader = MarketDataLoader(data_dir)
        self.strategy_module = STRATEGY_ALIASES.get(strategy_module, strategy_module)
        self.round_num = round_num

    def _load_trader(self):
        module = importlib.import_module(self.strategy_module)
        if not hasattr(module, "Trader"):
            raise ValueError(f"Strategy module {self.strategy_module} does not expose Trader")
        return module.Trader()

    def _get_position_limits(self) -> Dict[str, int]:
        config = get_round_config(self.round_num)
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
    ) -> RobustnessSummary:
        avg_abs_position_ratio = (position_ratio_sum / tick_count) if tick_count else 0.0
        near_limit_tick_ratio = (near_limit_tick_count / tick_count) if tick_count else 0.0
        fill_efficiency = (traded_volume / submitted_volume) if submitted_volume else 0.0
        aggressive_share = (aggressive_qty / traded_volume) if traded_volume else 0.0
        passive_adverse_rate = (passive_adverse_qty / passive_eval_qty) if passive_eval_qty else None
        passive_post_fill_edge = (passive_edge_sum / passive_eval_qty) if passive_eval_qty else None
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
        )

    def run_day(self, day: str, mode: TradeMatchingMode = TradeMatchingMode.queue) -> DaySummary:
        price_file = f"prices_round_{self.round_num}_day_{day}.csv"
        trade_file = f"trades_round_{self.round_num}_day_{day}.csv"

        prices_df = self.loader.load_prices(price_file)
        order_history = self.loader.order_depth_history(prices_df)
        market_trades = self.loader.load_trade_objects(trade_file)
        market_by_timestamp = self.loader.group_trades_by_timestamp(market_trades)

        products = sorted(prices_df["product"].unique())
        listings = self.loader.build_listings(products)
        observations = self.loader.empty_observation()
        trader = self._load_trader()

        cash_by_product = {product: 0.0 for product in products}
        turnover_by_product = {product: 0.0 for product in products}
        positions = {product: 0 for product in products}
        max_abs_position = {product: 0 for product in products}
        limits = self._get_position_limits()
        submitted_volume_by_product = {product: 0 for product in products}
        position_ratio_sum_by_product = {product: 0.0 for product in products}
        near_limit_tick_count_by_product = {product: 0 for product in products}
        tick_count_by_product = {product: 0 for product in products}

        recent_own_trades: Dict[str, List[Trade]] = {product: [] for product in products}
        all_fills: List[Fill] = []
        all_quotes: List[Quote] = []
        all_feature_ticks: List[FeatureTick] = []
        equity_curve: List[Tuple[int, float]] = []
        trader_data = ""

        timestamps = sorted(order_history.keys())

        os.environ["INTERNAL_BACKTEST"] = "1"
        try:
            for index, timestamp in enumerate(timestamps):
                order_depths = order_history[timestamp]
                current_market_trades_by_product = market_by_timestamp.get(timestamp, {})
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
                trader_result, _, trader_data = run_out[0], run_out[1], run_out[2]
                # 4th return value is optional: {product: {feature_name: value}}
                strategy_features: Dict[str, Dict[str, float]] = run_out[3] if len(run_out) > 3 else {}
                for sym, feats in strategy_features.items():
                    if feats:
                        all_feature_ticks.append(FeatureTick(timestamp=timestamp, symbol=sym, features=feats))

                next_own_trades: Dict[str, List[Trade]] = {product: [] for product in products}

                for product, orders in trader_result.items():
                    safe_orders = self._respect_exchange_limits(product, positions.get(product, 0), orders)
                    submitted_volume_by_product[product] += sum(abs(order.quantity) for order in safe_orders)

                    buy_prices = [o.price for o in safe_orders if o.quantity > 0]
                    sell_prices = [o.price for o in safe_orders if o.quantity < 0]
                    all_quotes.append(Quote(
                        timestamp=timestamp,
                        symbol=product,
                        bid=max(buy_prices) if buy_prices else None,
                        ask=min(sell_prices) if sell_prices else None,
                    ))

                    fills = self._simulate_fills(
                        order_depths.get(product, OrderDepth()),
                        safe_orders,
                        current_market_trades_by_product.get(product, []),
                        timestamp,
                        mode,
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

        for fill in all_fills:
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

        for product in products:
            ending_cash = cash_by_product[product]
            final_mid = self._mid_price(order_history[last_timestamp][product])
            pnl = ending_cash + positions[product] * final_mid
            total_pnl += pnl
            product_fills = [fill for fill in all_fills if fill.symbol == product]
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
            )
            product_summaries[product] = ProductSummary(
                symbol=product, pnl=pnl, ending_position=positions[product],
                trades=len(product_fills), traded_volume=sum(fill.quantity for fill in product_fills),
                turnover=turnover_by_product[product], max_abs_position=max_abs_position[product],
                robustness=robustness,
            )

        total_robustness = self._build_robustness_summary(
            submitted_volume=sum(submitted_volume_by_product.values()),
            traded_volume=sum(fill.quantity for fill in all_fills),
            aggressive_qty=sum(aggressive_qty_by_product.values()),
            passive_qty=sum(passive_qty_by_product.values()),
            aggressive_trades=sum(aggressive_trades_by_product.values()),
            passive_trades=sum(passive_trades_by_product.values()),
            tick_count=sum(tick_count_by_product.values()),
            position_ratio_sum=sum(position_ratio_sum_by_product.values()),
            near_limit_tick_count=sum(near_limit_tick_count_by_product.values()),
            passive_eval_qty=sum(passive_eval_qty_by_product.values()),
            passive_adverse_qty=sum(passive_adverse_qty_by_product.values()),
            passive_edge_sum=sum(passive_edge_sum_by_product.values()),
            max_drawdown=day_drawdown,
        )

        return DaySummary(
            day=day,
            pnl=total_pnl,
            fills=all_fills,
            product_summaries=product_summaries,
            equity_curve=equity_curve,
            robustness=total_robustness,
            quotes=all_quotes,
            feature_ticks=all_feature_ticks,
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

            existing = per_product_robustness.get(symbol)
            current = product_summary.robustness
            if existing is None:
                per_product_robustness[symbol] = RobustnessSummary(
                    submitted_volume=current.submitted_volume,
                    traded_volume=current.traded_volume,
                    aggressive_qty=current.aggressive_qty,
                    passive_qty=current.passive_qty,
                    aggressive_trades=current.aggressive_trades,
                    passive_trades=current.passive_trades,
                    tick_count=current.tick_count,
                    avg_abs_position_ratio=current.avg_abs_position_ratio,
                    near_limit_tick_count=current.near_limit_tick_count,
                    near_limit_tick_ratio=current.near_limit_tick_ratio,
                    fill_efficiency=current.fill_efficiency,
                    aggressive_share=current.aggressive_share,
                    passive_eval_qty=current.passive_eval_qty,
                    passive_adverse_qty=current.passive_adverse_qty,
                    passive_adverse_rate=current.passive_adverse_rate,
                    passive_post_fill_edge=current.passive_post_fill_edge,
                    max_drawdown=None,
                )
                continue

            merged = BacktestEngine._build_robustness_summary(
                submitted_volume=existing.submitted_volume + current.submitted_volume,
                traded_volume=existing.traded_volume + current.traded_volume,
                aggressive_qty=existing.aggressive_qty + current.aggressive_qty,
                passive_qty=existing.passive_qty + current.passive_qty,
                aggressive_trades=existing.aggressive_trades + current.aggressive_trades,
                passive_trades=existing.passive_trades + current.passive_trades,
                tick_count=existing.tick_count + current.tick_count,
                position_ratio_sum=(
                    existing.avg_abs_position_ratio * existing.tick_count
                    + current.avg_abs_position_ratio * current.tick_count
                ),
                near_limit_tick_count=existing.near_limit_tick_count + current.near_limit_tick_count,
                passive_eval_qty=existing.passive_eval_qty + current.passive_eval_qty,
                passive_adverse_qty=existing.passive_adverse_qty + current.passive_adverse_qty,
                passive_edge_sum=(
                    (existing.passive_post_fill_edge or 0.0) * existing.passive_eval_qty
                    + (current.passive_post_fill_edge or 0.0) * current.passive_eval_qty
                ),
                max_drawdown=None,
            )
            per_product_robustness[symbol] = merged

    total_robustness = BacktestEngine._build_robustness_summary(
        submitted_volume=sum(summary.robustness.submitted_volume for summary in summaries),
        traded_volume=sum(summary.robustness.traded_volume for summary in summaries),
        aggressive_qty=sum(summary.robustness.aggressive_qty for summary in summaries),
        passive_qty=sum(summary.robustness.passive_qty for summary in summaries),
        aggressive_trades=sum(summary.robustness.aggressive_trades for summary in summaries),
        passive_trades=sum(summary.robustness.passive_trades for summary in summaries),
        tick_count=sum(summary.robustness.tick_count for summary in summaries),
        position_ratio_sum=sum(
            summary.robustness.avg_abs_position_ratio * summary.robustness.tick_count
            for summary in summaries
        ),
        near_limit_tick_count=sum(summary.robustness.near_limit_tick_count for summary in summaries),
        passive_eval_qty=sum(summary.robustness.passive_eval_qty for summary in summaries),
        passive_adverse_qty=sum(summary.robustness.passive_adverse_qty for summary in summaries),
        passive_edge_sum=sum(
            (summary.robustness.passive_post_fill_edge or 0.0) * summary.robustness.passive_eval_qty
            for summary in summaries
        ),
        max_drawdown=total_drawdown,
    )

    return {
        "total_pnl": total_pnl,
        "per_product_pnl": per_product_pnl,
        "per_product_trades": per_product_trades,
        "per_product_max_pos": per_product_max_pos,
        "robustness": asdict(total_robustness),
        "per_product_robustness": {symbol: asdict(metrics) for symbol, metrics in per_product_robustness.items()},
    }


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prosperity backtest runner (any round)")
    parser.add_argument("--strategy", required=True, help="Module or alias: champion/leo/theo/pietro")
    parser.add_argument("--round", type=int, default=0, help="Round number (default 0)")
    parser.add_argument("--days", nargs="*", help="Days to run, e.g. -2 -1")
    parser.add_argument("--data-dir", default="data", help="Directory with CSV files")
    parser.add_argument("--json-out", help="Optional JSON output file")
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

    summaries = [engine.run_day(day, mode=mode) for day in days]

    for summary in summaries:
        print(
            f"day {summary.day}: pnl={summary.pnl:.2f} "
            f"dd={summary.robustness.max_drawdown or 0.0:.2f} "
            f"fill_eff={summary.robustness.fill_efficiency:.3f}"
        )
        for ps in summary.product_summaries.values():
            print(
                f"  {ps.symbol}: pnl={ps.pnl:.2f}, trades={ps.trades}, volume={ps.traded_volume}, "
                f"max_pos={ps.max_abs_position}, end_pos={ps.ending_position}, "
                f"make={ps.robustness.passive_qty}, take={ps.robustness.aggressive_qty}, "
                f"inv={ps.robustness.avg_abs_position_ratio:.3f}"
            )

    aggregate = aggregate_day_summaries(summaries)
    robustness = aggregate["robustness"]
    print(
        f"TOTAL pnl={aggregate['total_pnl']:.2f} over {len(summaries)} day(s) "
        f"dd={robustness['max_drawdown'] or 0.0:.2f} "
        f"fill_eff={robustness['fill_efficiency']:.3f} "
        f"inv={robustness['avg_abs_position_ratio']:.3f}"
    )

    if args.json_out:
        payload = {
            "strategy": args.strategy,
            "round": args.round,
            "execution_rule": args.execution_rule,
            "summary": aggregate,
            "days": [_result_to_jsonable(s) for s in summaries],
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
