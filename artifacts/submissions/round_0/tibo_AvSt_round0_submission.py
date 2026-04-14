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
    # Shared volatility estimation (call from any strategy)
    # ------------------------------------------------------------------
    def _update_volatility(self, mid: float, memory: Dict[str, Any]) -> float:
        """Estimate realised volatility from mid-price returns with EWMA smoothing.

        Params read from self.params:
          sigma_window   — rolling window size for returns (default 50)
          sigma_default  — fallback when too few prices (default 1.0)
          sigma_half_life — EWMA half-life for smoothing (default 60)
          sigma_floor    — minimum returned value (default 0.5)

        Stores in memory: ``mid_history``, ``sigma_smoothed``.
        Returns the floored, smoothed sigma.
        """
        window = int(self.params.get("sigma_window", 50))
        prices = memory.setdefault("mid_history", [])
        prices.append(mid)
        if len(prices) > window + 1:
            prices[:] = prices[-(window + 1):]

        if len(prices) < 3:
            return float(self.params.get("sigma_default", 1.0))

        returns = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        n = len(returns)
        mean_r = sum(returns) / n
        var = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
        sigma_raw = math.sqrt(var) if var > 0 else float(self.params.get("sigma_default", 1.0))

        half_life = float(self.params.get("sigma_half_life", 60))
        alpha = 2.0 / (half_life + 1.0)
        sigma_prev = memory.get("sigma_smoothed", sigma_raw)
        sigma_smoothed = alpha * sigma_raw + (1.0 - alpha) * sigma_prev
        memory["sigma_smoothed"] = sigma_smoothed

        return max(sigma_smoothed, float(self.params.get("sigma_floor", 0.5)))

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
    def runtime_trace_enabled(self) -> bool:
        enabled = self.params.get("runtime_trace_enabled")
        if enabled is not None:
            return bool(enabled)
        return not bool(False)

    def log_quote_snapshot(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        bid_price: int | float | None,
        ask_price: int | float | None,
        extras: Dict[str, Any] | None = None,
    ) -> None:
        """Accumulate and flush a lightweight quote trace for official IMC logs.

        The trace format is intentionally small and common across quoting
        strategies so the dashboard can render our own bid/ask from runtime logs:
          {
            "product": "...",
            "trace": "quote_trace",
            "chunk_end": 49900,
            "columns": ["timestamp", "bid_price", "ask_price", ...],
            "log": [[...], [...]]
          }

        Strategies may append extra per-tick diagnostics through ``extras`` as
        long as they keep a stable schema across ticks.
        """
        if not self.runtime_trace_enabled():
            return

        row: Dict[str, Any] = {
            "timestamp": int(state.timestamp),
            "bid_price": bid_price,
            "ask_price": ask_price,
        }
        if extras:
            row.update(extras)

        columns = memory.setdefault("_quote_trace_columns", list(row.keys()))
        for key in row.keys():
            if key not in columns:
                columns.append(key)

        rows = memory.setdefault("_quote_trace_rows", [])
        rows.append(row)

        flush_ts = int(self.params.get("log_flush_ts", 10000))
        last_tick_ts = self.params.get("last_ts_value")
        if last_tick_ts is None:
            last_tick_ts = int(self.params.get("total_ticks", 200000)) - 100
        else:
            last_tick_ts = int(last_tick_ts)

        end_of_sim = int(state.timestamp) >= last_tick_ts
        checkpoint = flush_ts > 0 and (int(state.timestamp) % flush_ts) == (flush_ts - 100)
        if not (end_of_sim or checkpoint):
            return

        print(json.dumps({
            "product": self.product,
            "trace": "quote_trace",
            "chunk_end": int(state.timestamp),
            "columns": columns,
            "log": [[row.get(column) for column in columns] for row in rows],
        }))
        memory["_quote_trace_rows"] = []

    def log_taker_fill(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        side: str,
        price: int,
        quantity: int,
    ) -> None:
        """Accumulate a taker fill and flush when the buffer is full enough.

        Flush conditions (in priority order):
          1. Deferred flag was set last tick → flush now.
          2. Timestamp is the second-to-last of the day → flush as end-of-day cleanup.
          3. Buffer reached 20 fills AND we are NOT at a quote-flush timestamp → flush.
          4. Buffer reached 20 fills AND we ARE at a quote-flush timestamp → set deferred
             flag; the flush will fire on the very next tick instead.

        Log format emitted to stdout:
          {"product": "...", "trace": "taker_fills", "chunk_end": ts,
           "log": [[ts, side, price, qty], ...]}
        """
        if not self.runtime_trace_enabled():
            return

        taker_log = memory.setdefault("_taker_log", [])
        taker_log.append([int(state.timestamp), side, price, quantity])

        flush_ts = int(self.params.get("log_flush_ts", 10000))
        ts_increment = int(self.params.get("ts_increment", 100))
        last_ts = int(self.params.get("last_ts_value", 199900))
        second_to_last = last_ts - ts_increment

        is_quote_flush = flush_ts > 0 and (int(state.timestamp) % flush_ts) == (flush_ts - 100)
        deferred = memory.get("_taker_flush_deferred", False)

        # If threshold hit exactly on a quote-flush ts, defer to the next tick.
        if len(taker_log) >= 20 and is_quote_flush and not deferred:
            memory["_taker_flush_deferred"] = True
            return

        should_flush = (
            deferred
            or int(state.timestamp) >= second_to_last
            or (len(taker_log) >= 20 and not is_quote_flush)
        )
        if not should_flush:
            return

        print(json.dumps({
            "product": self.product,
            "trace": "taker_fills",
            "chunk_end": int(state.timestamp),
            "log": taker_log,
        }))
        memory["_taker_log"] = []
        memory["_taker_flush_deferred"] = False

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

    # ── core A-S computation ─────────────────────────────────────────
    def _compute_as_quotes(
        self, mid: float, position: int, sigma: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:

        # Not using tau for now since open position are still automatically liquidated at the end of the day using fair value
        """ ts_increment = int(self.params.get("ts_increment", 100))
        last_ts_key = "bt_last_ts_value" if False else "last_ts_value"
        last_ts = int(self.params.get(last_ts_key, self.params.get("last_ts_value", 199900)))
        memory["tick_count"] = tick_num + 1
        num_ticks = last_ts // ts_increment + 1
        tick_num = memory.get("tick_count", 0)
        tau = max((num_ticks - tick_num) / num_ticks, 0.001) """

        
        gamma = float(self.params.get("gamma", 0.1))
        kappa = float(self.params.get("kappa", 1.5))

        #  # Reservation price
        reservation = mid - position * gamma * sigma * sigma # * tau 

        # Optimal half-spread
        #half_spread = (gamma * sigma * sigma * tau) / 2.0 + math.log(1.0 + gamma / kappa) / gamma
        half_spread = 5 * ((gamma * sigma * sigma) + math.log(1.0 + gamma / kappa) / gamma)

        # Apply min spread from params
        min_half_spread = float(self.params.get("min_half_spread", 1.0))
        half_spread = max(half_spread, min_half_spread)

        return reservation, half_spread

    # ── order construction ───────────────────────────────────────────
    def compute_orders(self, state: TradingState, book: BookSnapshot, order_depth: OrderDepth, position: int, memory: Dict[str, Any]) -> Tuple[List[Order], int]:
        
        if book.mid_price is None:
            return [], 0

        mid = book.mid_price
        mid_smooth = self._smooth_mid(mid, memory)
        sigma = self._update_volatility(mid, memory)


        # ─-----------------------─ QUOTE PRICING -------------------------------

        reservation, half_spread = self._compute_as_quotes(mid_smooth, position, sigma, memory)

        bid_price = int(math.floor(reservation - half_spread))
        ask_price = int(math.ceil(reservation + half_spread))

        # Join-best cap: never improve the market, only join or post behind.
        # If our computed price is inside the best bid/ask we cap it there —
        # we still get filled (tied for best price) but capture more edge.
        if book.best_bid is not None:
            bid_price = min(bid_price, book.best_bid+1)
        if book.best_ask is not None:
            ask_price = max(ask_price, book.best_ask-1)

        # Ensure we don't cross the book
        # if book.best_ask is not None:
        #     bid_price = min(bid_price, book.best_ask - 1)
        # if book.best_bid is not None:
        #     ask_price = max(ask_price, book.best_bid + 1)
        # if ask_price <= bid_price:
        #     ask_price = bid_price + 1

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)


        # ─--------------─ Taker orders, when edge is clear ---------------------

        # Track which prices we send as taker this tick so own_trades can be
        # classified next tick (fills arrive one tick later via state.own_trades).
        this_taker_buy_px: set = set()
        this_taker_sell_px: set = set()

        take_edge = float(self.params.get("take_edge", 0.5))
        for ask_p in sorted(order_depth.sell_orders):
            available = -order_depth.sell_orders[ask_p]
            if ask_p > reservation - take_edge or buy_cap <= 0:
                break
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                this_taker_buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume = order_depth.buy_orders[bid_p]
            if bid_p < reservation + take_edge or sell_cap <= 0:
                break
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                this_taker_sell_px.add(bid_p)
                sell_cap -= qty


        # ─--------------------─ Passive quoting ──------------------------------

        #  ORDER SIZING
        limit = self.position_limit()

        base_size = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base_size * (1 - position/limit)
        ask_size = base_size * (1 + position/limit)

        quote_buy = min(buy_cap, int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))

        # ─-----------─ Reduce quote -> keep capacity for takers ---------------------

        inv_ratio = abs(position) / float(limit) if limit else 0.0

        if inv_ratio >= 1 - float(self.params.get("pct_kept_for_takers", 0.2)):
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

        # ── Taker-fill classification and logging ────────────────────────────────
        # own_trades contains fills from LAST tick's orders; classify using the
        # taker prices we stored at the end of last tick.
        prev_taker_buy_px = set(memory.get("_taker_buy_px", []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        memory["_taker_buy_px"] = list(this_taker_buy_px)
        memory["_taker_sell_px"] = list(this_taker_sell_px)

        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY", trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                )

        # ── Quote snapshot (live only, suppressed during internal backtest) ──────
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "reservation": round(reservation, 2),
                "sigma": round(sigma, 6),
                "half_spread": round(half_spread, 6),
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (r := memory.get("reservation")) is not None:
            out["Reservation"] = r
        if (s := memory.get("sigma")) is not None:
            out["Sigma"] = s
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'EMERALDS': {'anchor_price': 10000.0,
              'anchor_weight': 0.92,
              'bt_last_ts_value': 999900,
              'ema_alpha': 0.08,
              'fair_mode': 'anchored_microprice',
              'gamma': 0.001,
              'improve_ticks': 1,
              'inventory_aversion': 1.2,
              'join_best': True,
              'kappa': 0.8,
              'last_ts_value': 199900,
              'log_flush_ts': 1000,
              'maker_size': 16,
              'maker_size_base_pct': 0.5,
              'max_inventory_bias_ticks': 4,
              'mid_smooth_half_life': 25,
              'mid_smooth_window': 50,
              'min_half_spread': 1.0,
              'pct_kept_for_takers': 0.15,
              'position_limit': 80,
              'quote_half_spread': 2,
              'sigma_floor': 0.5,
              'sigma_half_life': 60,
              'sigma_window': 200,
              'strategy': 'avellaneda_stoikov',
              'take_edge': 2,
              'ts_increment': 100},
 'TOMATOES': {'anchor_price': None,
              'anchor_weight': 0.0,
              'bt_last_ts_value': 199900,
              'ema_alpha': 0.18,
              'fair_mode': 'microprice_ema',
              'gamma': 0.05,
              'improve_ticks': 1,
              'inventory_aversion': 1.5,
              'join_best': True,
              'kappa': 2.0,
              'last_ts_value': 199900,
              'log_flush_ts': 1000,
              'maker_size': 14,
              'maker_size_base_pct': 0.3,
              'max_inventory_bias_ticks': 5,
              'mid_smooth_half_life': 8,
              'mid_smooth_window': 50,
              'min_half_spread': 1.0,
              'pct_kept_for_takers': 0.25,
              'position_limit': 80,
              'quote_half_spread': 2,
              'sigma_floor': 0.5,
              'sigma_half_life': 50,
              'sigma_window': 150,
              'strategy': 'avellaneda_stoikov',
              'take_edge': 2,
              'ts_increment': 100}}

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
