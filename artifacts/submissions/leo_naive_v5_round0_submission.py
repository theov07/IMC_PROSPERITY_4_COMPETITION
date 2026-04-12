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


# ── prosperity/strategies/naive_tight_mm_v5.py ────────────────────────────────────

class NaiveTightMarketMakerV5Strategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        # ── params ──
        base_tighten = int(self.params.get("tighten_ticks", 1))
        inv_skew_ticks = int(self.params.get("inv_skew_ticks", 0))
        spread_extra_threshold = int(self.params.get("spread_extra_threshold", 0))
        size_reduce_ratio = float(self.params.get("size_reduce_ratio", 1.0))
        imb_threshold = float(self.params.get("imb_threshold", 0.0))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        spread = book.best_ask - book.best_bid

        # ── 2. Adaptive tighten ──
        tighten = base_tighten
        if spread_extra_threshold > 0 and spread >= spread_extra_threshold:
            tighten = base_tighten + 1

        # ── 4. Imbalance filter: asymmetric tighten ──
        tighten_bid = tighten
        tighten_ask = tighten
        if imb_threshold > 0.0 and book.imbalance is not None:
            if book.imbalance > imb_threshold:
                # More bid volume → price likely to rise → safe to tighten ask, cautious on bid
                tighten_bid = max(0, tighten - 1)
            elif book.imbalance < -imb_threshold:
                # More ask volume → price likely to fall → safe to tighten bid, cautious on ask
                tighten_ask = max(0, tighten - 1)

        # ── Price logic ──
        if spread >= 2:
            bid_price = min(book.best_bid + tighten_bid, book.best_ask - 1)
            ask_price = max(book.best_ask - tighten_ask, book.best_bid + 1)
        else:
            bid_price = book.best_bid
            ask_price = book.best_ask

        # ── 1. Inventory skew ──
        limit = self.position_limit()
        inv_ratio = position / limit if limit > 0 else 0.0
        skew = round(inv_ratio * inv_skew_ticks)

        bid_price = bid_price - skew
        ask_price = ask_price - skew

        # safety: never cross
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── 3. Size scaling near position limit ──
        buy_size = buy_cap
        sell_size = sell_cap

        if size_reduce_ratio < 1.0 and limit > 0:
            abs_ratio = abs(position) / limit
            if abs_ratio >= size_reduce_ratio:
                if position > 0:
                    # Long → cut buy size (don't add more), keep sell full
                    buy_size = max(1, buy_cap // 3)
                elif position < 0:
                    # Short → cut sell size, keep buy full
                    sell_size = max(1, sell_cap // 3)

        # ── Orders ──
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        # ── memory / logging ──
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        memory["last_skew"] = skew

        flush_ts = int(self.params.get("log_flush_ts", 10000))
        last_tick_ts = int(self.params.get("total_ticks", 199900) - 100)

        log = memory.setdefault("_log", [])
        log.append([state.timestamp, bid_price, ask_price, skew, position])

        end_of_sim = state.timestamp >= last_tick_ts
        checkpoint = flush_ts > 0 and (state.timestamp % flush_ts) == (flush_ts - 100)
        if end_of_sim or checkpoint:
            print(json.dumps({
                "product": self.product,
                "chunk_end": state.timestamp,
                "log": log,
            }))
            memory["_log"] = []

        return orders, 0

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'EMERALDS': {'anchor_price': 10000.0,
              'anchor_weight': 0.92,
              'ema_alpha': 0.08,
              'fair_mode': 'anchored_microprice',
              'imb_threshold': 0.2,
              'improve_ticks': 1,
              'inv_skew_ticks': 0,
              'inventory_aversion': 1.2,
              'join_best': True,
              'log_flush_ts': 1000,
              'maker_size': 16,
              'max_inventory_bias_ticks': 4,
              'position_limit': 80,
              'quote_half_spread': 2,
              'size_reduce_ratio': 1.0,
              'spread_extra_threshold': 0,
              'strategy': 'naive_tight_mm_v5',
              'take_edge': 1.0,
              'tighten_ticks': 1,
              'total_ticks': 200000},
 'TOMATOES': {'anchor_price': None,
              'anchor_weight': 0.0,
              'ema_alpha': 0.18,
              'fair_mode': 'microprice_ema',
              'imb_threshold': 0.0,
              'improve_ticks': 1,
              'inv_skew_ticks': 4,
              'inventory_aversion': 1.5,
              'join_best': True,
              'log_flush_ts': 1000,
              'maker_size': 14,
              'max_inventory_bias_ticks': 5,
              'position_limit': 80,
              'quote_half_spread': 2,
              'size_reduce_ratio': 1.0,
              'spread_extra_threshold': 0,
              'strategy': 'naive_tight_mm_v5',
              'take_edge': 1.0,
              'tighten_ticks': 1,
              'total_ticks': 200000}}

STRATEGY_CLASSES = {"naive_tight_mm_v5": NaiveTightMarketMakerV5Strategy}

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
