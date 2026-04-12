from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Tuple
from typing import List, Tuple
import json

# ── prosperity/market.py ──────────────────────────────────────────────────────────

PriceLevel = Tuple[int, int]


@dataclass(frozen=True)
class BookSnapshot:
    symbol: str
    bid_levels: List[PriceLevel]
    ask_levels: List[PriceLevel]
    best_bid: int | None
    best_bid_volume: int
    best_ask: int | None
    best_ask_volume: int
    mid_price: float | None
    microprice: float | None
    spread: int | None
    imbalance: float | None


def _sorted_bid_levels(order_depth: OrderDepth) -> List[PriceLevel]:
    return sorted(order_depth.buy_orders.items(), key=lambda item: item[0], reverse=True)


def _sorted_ask_levels(order_depth: OrderDepth) -> List[PriceLevel]:
    return sorted(((price, -volume) for price, volume in order_depth.sell_orders.items()), key=lambda item: item[0])


def snapshot_from_order_depth(symbol: str, order_depth: OrderDepth) -> BookSnapshot:
    bid_levels = _sorted_bid_levels(order_depth)
    ask_levels = _sorted_ask_levels(order_depth)

    best_bid = bid_levels[0][0] if bid_levels else None
    best_bid_volume = bid_levels[0][1] if bid_levels else 0
    best_ask = ask_levels[0][0] if ask_levels else None
    best_ask_volume = ask_levels[0][1] if ask_levels else 0

    mid_price = None
    microprice = None
    spread = None
    imbalance = None

    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2.0

        total_top = best_bid_volume + best_ask_volume
        if total_top > 0:
            microprice = (
                best_bid * best_ask_volume + best_ask * best_bid_volume
            ) / total_top
            imbalance = (best_bid_volume - best_ask_volume) / total_top

    return BookSnapshot(
        symbol=symbol,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        best_bid=best_bid,
        best_bid_volume=best_bid_volume,
        best_ask=best_ask,
        best_ask_volume=best_ask_volume,
        mid_price=mid_price,
        microprice=microprice,
        spread=spread,
        imbalance=imbalance,
    )


# ── prosperity/persistence.py ─────────────────────────────────────────────────────

def load_state(raw_state: str) -> Dict[str, Any]:
    if not raw_state:
        return {}
    try:
        loaded = json.loads(raw_state)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def dump_state(state: Dict[str, Any]) -> str:
    return json.dumps(state, separators=(",", ":"))


# ── prosperity/strategies/base.py ─────────────────────────────────────────────────

class BaseStrategy(ABC):
    """Abstract base for all product strategies.

    Each strategy receives the full TradingState but is responsible for
    producing orders for ONE product at a time.
    """

    def __init__(self, product: str, params: Dict[str, Any]):
        self.product = product
        self.params = params

    # ------------------------------------------------------------------
    def on_tick(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        """Called every iteration for this product.

        Returns:
            orders: list of Order objects to send
            conversions: integer conversion request (0 if none)
        """
        order_depth = state.order_depths.get(self.product)
        if order_depth is None:
            return [], 0

        position = state.position.get(self.product, 0)
        book = snapshot_from_order_depth(self.product, order_depth)

        return self.compute_orders(
            state=state,
            book=book,
            order_depth=order_depth,
            position=position,
            memory=memory,
        )

    @abstractmethod
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        """Produce orders and conversion request for this product."""
        ...

    # ------------------------------------------------------------------
    # Optional: expose named price features for the dashboard
    # ------------------------------------------------------------------
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        """Return a dict of named price-level features at the current tick.

        Override in concrete strategies to surface prices like reservation price,
        fair value, etc.  Keys become trace names in the dashboard.
        Default: no features.
        """
        return {}

    # ------------------------------------------------------------------
    # Helpers available to all strategies
    # ------------------------------------------------------------------
    def position_limit(self) -> int:
        return self.params.get("position_limit", 20)

    def buy_capacity(self, position: int) -> int:
        return max(0, self.position_limit() - position)

    def sell_capacity(self, position: int) -> int:
        return max(0, self.position_limit() + position)


# ── prosperity/strategies/naive_tight_mm_v9.py ────────────────────────────────────

class NaiveTightMarketMakerV9Strategy(BaseStrategy):
    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _signal_sign(value: float, threshold: float) -> int:
        if value > threshold:
            return 1
        if value < -threshold:
            return -1
        return 0

    def _inventory_pressure(self, position: int) -> float:
        limit = self.position_limit()
        if limit <= 0:
            return 0.0
        return abs(position) / float(limit)

    def _compute_trend_signal(
        self,
        book: BookSnapshot,
        mid: float,
        flow_score: float,
        memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float, float, float]:
        micro_weight = float(self.params.get("trend_micro_weight", 0.0))
        imbalance_weight = float(self.params.get("trend_imbalance_weight", 0.0))
        flow_weight = float(self.params.get("trend_flow_weight", 0.0))
        current_weight_sum = abs(micro_weight) + abs(imbalance_weight) + abs(flow_weight)

        microprice = book.microprice if book.microprice is not None else mid
        micro_scale = float(self.params.get("trend_microprice_scale", 1.0))
        if micro_scale <= 0.0:
            micro_edge = 0.0
        else:
            micro_edge = self._clip((microprice - mid) / micro_scale, -1.0, 1.0)

        imbalance = float(book.imbalance or 0.0)
        clipped_flow = self._clip(flow_score, -1.0, 1.0)

        current_pressure = 0.0
        if current_weight_sum > 0.0:
            current_pressure = (
                micro_weight * micro_edge
                + imbalance_weight * imbalance
                + flow_weight * clipped_flow
            ) / current_weight_sum

        ema_alpha = self._clip(float(self.params.get("trend_pressure_ema_alpha", 0.4)), 0.0, 1.0)
        prev_pressure_ema = float(memory.get("trend_pressure_ema", 0.0))
        if ema_alpha <= 0.0:
            pressure_ema = prev_pressure_ema
        elif ema_alpha >= 1.0:
            pressure_ema = current_pressure
        else:
            pressure_ema = ema_alpha * current_pressure + (1.0 - ema_alpha) * prev_pressure_ema

        prev_mid = memory.get("prev_mid")
        price_scale = float(self.params.get("trend_price_scale", 2.0))
        if prev_mid is None or price_scale <= 0.0:
            price_trend = 0.0
        else:
            price_trend = self._clip((mid - float(prev_mid)) / price_scale, -1.0, 1.0)

        streak_threshold = float(self.params.get("trend_streak_threshold", 0.08))
        current_sign = self._signal_sign(current_pressure, streak_threshold)
        prev_sign = int(memory.get("trend_pressure_sign", 0))
        prev_streak = int(memory.get("trend_pressure_streak", 0))
        if current_sign == 0:
            streak = 0
        elif current_sign == prev_sign:
            streak = prev_streak + 1
        else:
            streak = 1

        streak_cap = max(1, int(self.params.get("trend_streak_cap", 4)))
        streak_factor = min(1.0, streak / float(streak_cap))

        ema_sign = self._signal_sign(pressure_ema, max(1e-9, streak_threshold * 0.5))
        aligned = current_sign != 0 and current_sign == ema_sign
        alignment_signal = current_sign * streak_factor if aligned else 0.0
        price_confirm = price_trend if (current_sign != 0 and price_trend * current_sign > 0.0) else 0.0

        current_weight = float(self.params.get("trend_current_weight", 0.7))
        ema_weight = float(self.params.get("trend_pressure_ema_weight", 0.9))
        streak_weight = float(self.params.get("trend_streak_weight", 0.5))
        price_weight = float(self.params.get("trend_price_confirm_weight", 0.2))
        total_weight = abs(current_weight) + abs(ema_weight) + abs(streak_weight) + abs(price_weight)
        if total_weight <= 0.0:
            raw_signal = pressure_ema
        else:
            raw_signal = (
                current_weight * current_pressure
                + ema_weight * pressure_ema
                + streak_weight * alignment_signal
                + price_weight * price_confirm
            ) / total_weight

        signal_alpha = self._clip(float(self.params.get("trend_signal_alpha", 0.5)), 0.0, 1.0)
        prev_signal = float(memory.get("trend_signal", 0.0))
        if signal_alpha <= 0.0:
            trend_signal = prev_signal
        elif signal_alpha >= 1.0:
            trend_signal = raw_signal
        else:
            trend_signal = signal_alpha * raw_signal + (1.0 - signal_alpha) * prev_signal

        return (
            self._clip(trend_signal, -1.0, 1.0),
            current_pressure,
            pressure_ema,
            float(streak),
            micro_edge,
            price_trend,
        )

    def _take_selective_orders(
        self,
        order_depth: OrderDepth,
        mid: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
    ) -> Tuple[List[Order], int, int, int]:
        orders: List[Order] = []
        take_edge = float(self.params.get("take_edge", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 0.0))
        pressure = self._inventory_pressure(position)

        buy_edge = take_edge
        sell_edge = take_edge
        if position < 0:
            buy_edge = max(0.0, take_edge - unwind_take_edge * pressure)
        elif position > 0:
            sell_edge = max(0.0, take_edge - unwind_take_edge * pressure)

        take_count = 0

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > mid - buy_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < mid + sell_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            take_count += 1

        return orders, buy_cap, sell_cap, take_count

    def _apply_inventory_sizing(
        self,
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.35))
        aggravate_min_frac = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost_frac = float(self.params.get("unwind_boost_frac", 0.25))

        pressure = self._inventory_pressure(position)
        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        aggravate_frac = 1.0 - (1.0 - aggravate_min_frac) * scaled
        unwind_mult = 1.0 + unwind_boost_frac * scaled

        if position > 0:
            if buy_size > 0:
                buy_size = max(1, int(round(buy_size * aggravate_frac)))
            if sell_size > 0:
                sell_size = min(sell_cap, max(1, int(round(sell_size * unwind_mult))))
        elif position < 0:
            if sell_size > 0:
                sell_size = max(1, int(round(sell_size * aggravate_frac)))
            if buy_size > 0:
                buy_size = min(buy_cap, max(1, int(round(buy_size * unwind_mult))))

        return buy_size, sell_size

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_threshold = float(self.params.get("toxic_threshold", 0.6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.5))
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")

        flow_history = memory.setdefault("flow_history", [])
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None and trades:
            for trade in trades:
                if trade.price >= prev_best_ask:
                    flow_history.append(trade.quantity)
                elif trade.price <= prev_best_bid:
                    flow_history.append(-trade.quantity)
            if len(flow_history) > toxic_window:
                del flow_history[:-toxic_window]

        flow_score = 0.0
        if flow_history:
            signed = sum(flow_history)
            total = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total

        trend_signal, current_pressure, pressure_ema, streak, micro_edge, price_trend = self._compute_trend_signal(
            book=book,
            mid=mid,
            flow_score=flow_score,
            memory=memory,
        )
        directional_take_shift = float(self.params.get("directional_take_shift", 0.0))
        directional_mid = mid + trend_signal * directional_take_shift

        take_orders, buy_cap, sell_cap, take_count = self._take_selective_orders(
            order_depth=order_depth,
            mid=directional_mid,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            position=position,
        )
        orders.extend(take_orders)

        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}

        real_best_ask = book.best_ask
        for ask_price, _ in book.ask_levels:
            if ask_price not in swept_ask_prices:
                real_best_ask = ask_price
                break

        real_best_bid = book.best_bid
        for bid_price, _ in book.bid_levels:
            if bid_price not in swept_bid_prices:
                real_best_bid = bid_price
                break

        spread = real_best_ask - real_best_bid
        if spread >= 2:
            bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1)
            ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1)
        else:
            bid_price = real_best_bid
            ask_price = real_best_ask

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        buy_size, sell_size = self._apply_inventory_sizing(
            position=position,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        bid_jumped = bool(prev_best_bid is not None and real_best_bid == prev_best_bid + 1)
        ask_jumped = bool(prev_best_ask is not None and real_best_ask == prev_best_ask - 1)

        if flow_score > toxic_threshold and sell_size > 0:
            sell_size = max(1, int(round(sell_size * toxic_size_frac)))
        elif flow_score < -toxic_threshold and buy_size > 0:
            buy_size = max(1, int(round(buy_size * toxic_size_frac)))

        if bid_jumped and sell_size > 0:
            sell_size = max(1, int(round(sell_size * jump_size_frac)))
        if ask_jumped and buy_size > 0:
            buy_size = max(1, int(round(buy_size * jump_size_frac)))

        directional_size_skew = float(self.params.get("directional_size_skew", 0.0))
        if directional_size_skew > 0.0 and abs(trend_signal) > 0.0:
            skew = directional_size_skew * abs(trend_signal)
            if trend_signal > 0:
                if buy_size > 0:
                    buy_size = min(buy_cap, max(1, int(round(buy_size * (1.0 + skew)))))
                if sell_size > 0:
                    sell_size = max(1, int(round(sell_size * (1.0 - skew))))
            else:
                if sell_size > 0:
                    sell_size = min(sell_cap, max(1, int(round(sell_size * (1.0 + skew)))))
                if buy_size > 0:
                    buy_size = max(1, int(round(buy_size * (1.0 - skew))))

        max_quote_bias_ticks = int(self.params.get("directional_max_quote_bias_ticks", 0))
        if max_quote_bias_ticks > 0 and abs(trend_signal) > 0.0:
            quote_bias = int(round(trend_signal * max_quote_bias_ticks))
            if quote_bias > 0:
                bid_price = min(bid_price + quote_bias, real_best_ask - 1)
                ask_price = min(real_best_ask, ask_price + quote_bias)
            elif quote_bias < 0:
                bid_price = max(real_best_bid, bid_price + quote_bias)
                ask_price = max(real_best_bid + 1, ask_price + quote_bias)

            if bid_price >= ask_price:
                ask_price = min(real_best_ask, max(bid_price + 1, ask_price))

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["prev_best_bid"] = real_best_bid
        memory["prev_best_ask"] = real_best_ask
        memory["prev_mid"] = mid
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_flow_score"] = flow_score
        memory["last_take_count"] = take_count
        memory["trend_pressure_ema"] = pressure_ema
        memory["trend_pressure_sign"] = self._signal_sign(current_pressure, float(self.params.get("trend_streak_threshold", 0.08)))
        memory["trend_pressure_streak"] = int(streak)
        memory["trend_signal"] = trend_signal
        memory["last_trend_signal"] = trend_signal
        memory["last_trend_pressure"] = current_pressure
        memory["last_trend_micro_edge"] = micro_edge
        memory["last_trend_price_confirm"] = price_trend
        memory["last_directional_mid"] = directional_mid

        flush_ts = int(self.params.get("log_flush_ts", 0))
        last_tick_ts = int(self.params.get("total_ticks", 10_000_000)) - 100
        end_of_sim = state.timestamp >= last_tick_ts
        checkpoint = flush_ts > 0 and (state.timestamp % flush_ts) == (flush_ts - 100)
        if flush_ts > 0 or end_of_sim:
            log = memory.setdefault("_log", [])
            log.append([
                state.timestamp,
                bid_price,
                ask_price,
                position,
                buy_size,
                sell_size,
                flow_score,
                trend_signal,
                take_count,
            ])

        if end_of_sim or checkpoint:
            print(json.dumps({
                "product": self.product,
                "chunk_end": state.timestamp,
                "columns": [
                    "timestamp",
                    "bid",
                    "ask",
                    "position",
                    "buy_size",
                    "sell_size",
                    "flow_score",
                    "trend_signal",
                    "takes",
                ],
                "log": log,
            }))
            memory["_log"] = []

        return orders, 0

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'EMERALDS': {'aggravate_min_frac': 0.2,
              'anchor_price': 10000.0,
              'anchor_weight': 0.92,
              'ema_alpha': 0.08,
              'fair_mode': 'anchored_microprice',
              'improve_ticks': 1,
              'inventory_aversion': 1.2,
              'inventory_soft_ratio': 0.6,
              'join_best': True,
              'jump_size_frac': 0.5,
              'log_flush_ts': 0,
              'maker_size': 80,
              'max_inventory_bias_ticks': 4,
              'position_limit': 80,
              'quote_half_spread': 2,
              'strategy': 'naive_tight_mm_v9',
              'take_edge': 1.0,
              'tighten_ticks': 1,
              'total_ticks': 10000000,
              'toxic_size_frac': 0.75,
              'toxic_threshold': 0.6,
              'toxic_window': 6,
              'unwind_boost_frac': 0.3,
              'unwind_take_edge': 0.5},
 'TOMATOES': {'aggravate_min_frac': 0.2,
              'anchor_price': None,
              'anchor_weight': 0.0,
              'directional_max_quote_bias_ticks': 2,
              'directional_size_skew': 0.0,
              'directional_take_shift': 0.0,
              'ema_alpha': 0.18,
              'fair_mode': 'microprice_ema',
              'improve_ticks': 1,
              'inventory_aversion': 1.5,
              'inventory_soft_ratio': 0.55,
              'join_best': True,
              'jump_size_frac': 0.5,
              'log_flush_ts': 0,
              'maker_size': 80,
              'max_inventory_bias_ticks': 5,
              'position_limit': 80,
              'quote_half_spread': 2,
              'strategy': 'naive_tight_mm_v9',
              'take_edge': 1.0,
              'tighten_ticks': 1,
              'total_ticks': 10000000,
              'toxic_size_frac': 0.75,
              'toxic_threshold': 0.6,
              'toxic_window': 6,
              'trend_current_weight': 0.75,
              'trend_flow_weight': 0.35,
              'trend_imbalance_weight': 0.55,
              'trend_micro_weight': 1.0,
              'trend_microprice_scale': 1.0,
              'trend_pressure_ema_alpha': 0.4,
              'trend_pressure_ema_weight': 0.95,
              'trend_price_confirm_weight': 0.0,
              'trend_price_scale': 2.0,
              'trend_signal_alpha': 0.6,
              'trend_streak_cap': 4,
              'trend_streak_threshold': 0.08,
              'trend_streak_weight': 0.55,
              'unwind_boost_frac': 0.3,
              'unwind_take_edge': 0.5}}

STRATEGY_CLASSES = {"naive_tight_mm_v9": NaiveTightMarketMakerV9Strategy}

# ── Trader ────────────────────────────────────────────────────────────────────

class Trader:
    def __init__(self):
        self.strategies = {}
        for symbol, cfg in PRODUCTS.items():
            strat_name = cfg["strategy"]
            params = {k: v for k, v in cfg.items() if k != "strategy"}
            cls = STRATEGY_CLASSES[strat_name]
            self.strategies[symbol] = cls(product=symbol, params=params)

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        product_memories = saved.setdefault("products", {})
        result = {}
        total_conversions = 0
        for product, strategy in self.strategies.items():
            if product not in state.order_depths:
                continue
            memory = product_memories.setdefault(product, {})
            orders, conversions = strategy.on_tick(state, memory)
            result[product] = orders
            total_conversions += conversions
        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)
