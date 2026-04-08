from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Tuple
from typing import List, Tuple
import json
import math

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


# ── prosperity/strategies/avellaneda_stoikov.py ───────────────────────────────────

class AvellanedaStoikovStrategy(BaseStrategy):

    # ── mid price smoothing ──────────────────────────────────────────
    def _smooth_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        window = int(self.params.get("mid_smooth_window", 0))
        if window <= 0:
            return mid
        half_life = float(self.params.get("mid_smooth_half_life", window / 2.0))
        buf = memory.setdefault("mid_smooth_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < 2:
            return mid
        alpha = 1.0 - 2.0 ** (-1.0 / half_life) if half_life > 0 else 1.0
        smoothed = buf[0]
        for p in buf[1:]:
            smoothed = alpha * p + (1.0 - alpha) * smoothed
        memory["mid_smoothed"] = smoothed
        return smoothed

    # ── volatility estimation ────────────────────────────────────────
    def _update_volatility(self, mid: float, memory: Dict[str, Any]) -> float:
        window = int(self.params.get("sigma_window", 50))
        prices = memory.setdefault("mid_history", [])
        prices.append(mid)
        if len(prices) > window + 1:
            prices[:] = prices[-(window + 1):]

        if len(prices) < 3:
            return self.params.get("sigma_default", 1.0)

        # Realized volatility from mid returns
        returns = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        n = len(returns)
        mean_r = sum(returns) / n
        var = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
        sigma_raw = math.sqrt(var) if var > 0 else self.params.get("sigma_default", 1.0)

        # Apply exponential smoothing with parametrizable half-life
        half_life = float(self.params.get("sigma_half_life", 60))
        alpha = 2.0 / (half_life + 1.0)
        sigma_prev = memory.get("sigma_smoothed", sigma_raw)
        sigma_smoothed = alpha * sigma_raw + (1.0 - alpha) * sigma_prev
        memory["sigma_smoothed"] = sigma_smoothed

        # Floor to prevent degenerate spreads
        return max(sigma_smoothed, self.params.get("sigma_floor", 0.5))

    # ── core A-S computation ─────────────────────────────────────────
    def _compute_as_quotes(
        self, mid: float, position: int, sigma: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        gamma = float(self.params.get("gamma", 0.1))
        kappa = float(self.params.get("kappa", 1.5))
        total_ticks = int(self.params.get("total_ticks", 10000))
        tick_num = memory.get("tick_count", 0)
        memory["tick_count"] = tick_num + 1

        tau = max((total_ticks - tick_num) / total_ticks, 0.001)

        # Reservation price
        reservation = mid - position * gamma * sigma * sigma * tau 

        # Optimal half-spread
        half_spread = (gamma * sigma * sigma * tau) / 2.0 + math.log(1.0 + gamma / kappa) / gamma

        # Apply min spread from params
        min_half_spread = float(self.params.get("min_half_spread", 1.0))
        half_spread = max(half_spread, min_half_spread)

        return reservation, half_spread, tau

    # ── order construction ───────────────────────────────────────────
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0

        mid = book.mid_price
        mid_smooth = self._smooth_mid(mid, memory)
        sigma = self._update_volatility(mid_smooth, memory)
        reservation, half_spread, tau = self._compute_as_quotes(mid_smooth, position, sigma, memory)

        bid_price = int(math.floor(reservation - half_spread))
        ask_price = int(math.ceil(reservation + half_spread))

        # Ensure we don't cross the book
        if book.best_ask is not None:
            bid_price = min(bid_price, book.best_ask - 1)
        if book.best_bid is not None:
            ask_price = max(ask_price, book.best_bid + 1)
        if ask_price <= bid_price:
            ask_price = bid_price + 1

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        maker_size = int(self.params.get("maker_size", 10))
        orders: List[Order] = []

        # ── Aggressive taking when edge is clear ──
        take_edge = float(self.params.get("take_edge", 0.5))
        for ask_p in sorted(order_depth.sell_orders):
            available = -order_depth.sell_orders[ask_p]
            if ask_p > reservation - take_edge or buy_cap <= 0:
                break
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume = order_depth.buy_orders[bid_p]
            if bid_p < reservation + take_edge or sell_cap <= 0:
                break
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap -= qty

        # ── Passive quoting ──
        limit = self.position_limit()
        inv_ratio = abs(position) / float(limit) if limit else 0.0

        quote_buy = min(buy_cap, maker_size)
        quote_sell = min(sell_cap, maker_size)

        # Reduce quoting when inventory is heavy
        if inv_ratio >= 0.75:
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0

        if quote_buy > 0:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0:
            orders.append(Order(self.product, ask_price, -quote_sell))

        memory["reservation"] = reservation
        memory["sigma"] = sigma
        memory["half_spread"] = half_spread

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (r := memory.get("reservation")) is not None:
            out["Reservation"] = r
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'EMERALDS': {'anchor_price': 10000.0,
              'anchor_weight': 0.92,
              'ema_alpha': 0.08,
              'fair_mode': 'anchored_microprice',
              'gamma': 0.1,
              'improve_ticks': 1,
              'inventory_aversion': 1.2,
              'join_best': True,
              'kappa': 1.0,
              'maker_size': 8,
              'max_inventory_bias_ticks': 4,
              'mid_smooth_half_life': 25,
              'mid_smooth_window': 50,
              'min_half_spread': 1.0,
              'position_limit': 80,
              'quote_half_spread': 2,
              'sigma_default': 1.0,
              'sigma_floor': 0.5,
              'sigma_half_life': 60,
              'sigma_window': 200,
              'strategy': 'avellaneda_stoikov',
              'take_edge': 1.5,
              'total_ticks': 10000},
 'TOMATOES': {'anchor_price': None,
              'anchor_weight': 0.0,
              'ema_alpha': 0.18,
              'fair_mode': 'microprice_ema',
              'gamma': 0.2,
              'improve_ticks': 1,
              'inventory_aversion': 1.5,
              'join_best': True,
              'kappa': 1.0,
              'maker_size': 8,
              'max_inventory_bias_ticks': 5,
              'mid_smooth_half_life': 25,
              'mid_smooth_window': 50,
              'min_half_spread': 1.0,
              'position_limit': 80,
              'quote_half_spread': 2,
              'sigma_default': 1.0,
              'sigma_floor': 0.5,
              'sigma_half_life': 60,
              'sigma_window': 200,
              'strategy': 'avellaneda_stoikov',
              'take_edge': 0.5,
              'total_ticks': 10000}}

STRATEGY_CLASSES = {"avellaneda_stoikov": AvellanedaStoikovStrategy}

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
