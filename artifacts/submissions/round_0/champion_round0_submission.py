from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from math import ceil, floor
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
    # Helpers available to all strategies
    # ------------------------------------------------------------------
    def position_limit(self) -> int:
        return self.params.get("position_limit", 20)

    def buy_capacity(self, position: int) -> int:
        return max(0, self.position_limit() - position)

    def sell_capacity(self, position: int) -> int:
        return max(0, self.position_limit() + position)


# ── prosperity/strategies/market_maker.py ─────────────────────────────────────────

def _ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


class MarketMakerStrategy(BaseStrategy):

    # ── fair value ───────────────────────────────────────────────────
    def _estimate_fair(self, book: BookSnapshot, memory: Dict[str, Any]) -> float:
        p = self.params
        previous_fair = memory.get("fair")
        reference = book.microprice or book.mid_price or p.get("anchor_price") or previous_fair or 0.0

        mode = p.get("fair_mode", "microprice_ema")
        alpha = p.get("ema_alpha", 0.15)

        if mode == "fixed":
            fair = p.get("anchor_price") or reference
        elif mode == "anchored_microprice":
            anchor = p.get("anchor_price") or reference
            w = p.get("anchor_weight", 0.9)
            blended = w * anchor + (1.0 - w) * reference
            fair = _ewma(previous_fair, blended, alpha)
        elif mode == "mid_ema":
            spot = book.mid_price if book.mid_price is not None else reference
            fair = _ewma(previous_fair, spot, alpha)
        else:  # microprice_ema (default)
            fair = _ewma(previous_fair, reference, alpha)

        memory["fair"] = fair
        return fair

    # ── aggressive taking ────────────────────────────────────────────
    def _take_opportunities(
        self, order_depth: OrderDepth, fair: float, buy_cap: int, sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        edge = self.params.get("take_edge", 1.0)

        for ask_price in sorted(order_depth.sell_orders):
            available = -order_depth.sell_orders[ask_price]
            if ask_price > fair - edge or buy_cap <= 0:
                break
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            volume = order_depth.buy_orders[bid_price]
            if bid_price < fair + edge or sell_cap <= 0:
                break
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_price, -qty))
                sell_cap -= qty

        return orders, buy_cap, sell_cap

    # ── inventory bias ───────────────────────────────────────────────
    def _inventory_bias(self, position: int) -> int:
        limit = self.position_limit()
        if limit <= 0:
            return 0
        aversion = self.params.get("inventory_aversion", 1.0)
        max_ticks = self.params.get("max_inventory_bias_ticks", 3)
        raw = (position / float(limit)) * aversion * max_ticks
        return int(round(max(-max_ticks, min(max_ticks, raw))))

    # ── passive quoting ──────────────────────────────────────────────
    def _quote(
        self, book: BookSnapshot, fair: float, position: int, buy_cap: int, sell_cap: int,
    ) -> List[Order]:
        orders: List[Order] = []
        p = self.params
        half_spread = p.get("quote_half_spread", 2)
        maker_size = p.get("maker_size", 12)

        bias = self._inventory_bias(position)
        adj_fair = fair - bias

        target_bid = floor(adj_fair - half_spread)
        target_ask = ceil(adj_fair + half_spread)

        if p.get("join_best", True) and book.best_bid is not None and book.best_ask is not None:
            improve = p.get("improve_ticks", 1)
            inside_bid = min(book.best_bid + improve, book.best_ask - 1)
            inside_ask = max(book.best_ask - improve, book.best_bid + 1)
            target_bid = max(target_bid, inside_bid)
            target_ask = min(target_ask, inside_ask)

        if book.best_ask is not None:
            target_bid = min(target_bid, book.best_ask - 1)
        if book.best_bid is not None:
            target_ask = max(target_ask, book.best_bid + 1)
        if target_ask <= target_bid:
            target_ask = target_bid + 1

        # Size logic
        quote_buy = min(buy_cap, maker_size)
        quote_sell = min(sell_cap, maker_size)

        limit = self.position_limit()
        inv_ratio = abs(position) / float(limit) if limit else 0.0

        if inv_ratio >= 0.85:
            quote_buy = max(1, quote_buy // 2)
            quote_sell = max(1, quote_sell // 2)

        # Lean harder on unwind side
        if position > 0:
            quote_sell = min(sell_cap, max(quote_sell, min(maker_size * 2, abs(position) // 4 + 1)))
        elif position < 0:
            quote_buy = min(buy_cap, max(quote_buy, min(maker_size * 2, abs(position) // 4 + 1)))

        # Cut quoting on overloaded side
        if inv_ratio >= 0.75:
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0

        if quote_buy > 0:
            orders.append(Order(self.product, target_bid, quote_buy))
        if quote_sell > 0:
            orders.append(Order(self.product, target_ask, -quote_sell))

        return orders

    # ── main entry ───────────────────────────────────────────────────
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        fair = self._estimate_fair(book, memory)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        take_orders, buy_cap, sell_cap = self._take_opportunities(order_depth, fair, buy_cap, sell_cap)
        quote_orders = self._quote(book, fair, position, buy_cap, sell_cap)

        return take_orders + quote_orders, 0

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'EMERALDS': {'anchor_price': 10000.0,
              'anchor_weight': 0.92,
              'ema_alpha': 0.08,
              'fair_mode': 'anchored_microprice',
              'improve_ticks': 1,
              'inventory_aversion': 1.2,
              'join_best': True,
              'maker_size': 16,
              'max_inventory_bias_ticks': 4,
              'position_limit': 80,
              'quote_half_spread': 2,
              'strategy': 'market_maker',
              'take_edge': 1.0},
 'TOMATOES': {'anchor_price': None,
              'anchor_weight': 0.0,
              'ema_alpha': 0.18,
              'fair_mode': 'microprice_ema',
              'improve_ticks': 1,
              'inventory_aversion': 1.5,
              'join_best': True,
              'maker_size': 14,
              'max_inventory_bias_ticks': 5,
              'position_limit': 80,
              'quote_half_spread': 2,
              'strategy': 'market_maker',
              'take_edge': 1.0}}

STRATEGY_CLASSES = {"market_maker": MarketMakerStrategy}

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
