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


# ── prosperity/strategies/round_1/regression_mm_v4.py ─────────────────────────────

class Round1RegressionMMV4Strategy(BaseStrategy):
    def _update_regression(
        self,
        *,
        state: TradingState,
        mid: float,
        memory: Dict[str, Any],
    ) -> Dict[str, float]:
        ts_increment = max(1, int(self.params.get("ts_increment", 100)))
        fixed_slope = float(self.params.get("fixed_slope", 0.1015))
        horizon = int(self.params.get("reg_horizon", 25))
        residual_window = int(self.params.get("residual_window", 160))
        residual_rmse_floor = float(self.params.get("reg_rmse_floor", 1.0))
        confidence_floor = float(self.params.get("trend_confidence_floor", 0.60))
        confidence_cap_rmse = float(self.params.get("trend_confidence_cap_rmse", 4.0))
        mean_revert_weight = float(self.params.get("reg_residual_reversion", 0.35))
        freeze_after_points = int(self.params.get("freeze_after_points", 0))
        freeze_min_points = int(self.params.get("freeze_min_points", max(60, freeze_after_points // 3 if freeze_after_points > 0 else 60)))
        freeze_r2_min = float(self.params.get("freeze_r2_min", 0.70))
        r2_floor = float(self.params.get("reg_r2_floor", 0.30))
        r2_cap = float(self.params.get("reg_r2_cap", 0.85))

        anchor_ts = memory.setdefault("line_anchor_ts", int(state.timestamp))
        anchor_mid = memory.setdefault("line_anchor_mid", mid)
        tick_index = max(0, int(round((int(state.timestamp) - anchor_ts) / ts_increment)))

        estimation_history = memory.setdefault("slope_estimation_history", [])
        frozen_slope = memory.get("frozen_slope")
        frozen_intercept = memory.get("frozen_intercept")
        frozen_r2 = memory.get("frozen_r2")

        def _fit_ols(series: List[float]) -> Tuple[float, float, float]:
            n = len(series)
            if n <= 1:
                return fixed_slope, anchor_mid, 0.0
            mean_x = (n - 1) / 2.0
            mean_y = sum(series) / n
            ss_xx = 0.0
            ss_xy = 0.0
            for idx, price in enumerate(series):
                dx = idx - mean_x
                dy = price - mean_y
                ss_xx += dx * dx
                ss_xy += dx * dy
            slope = ss_xy / ss_xx if ss_xx > 0 else fixed_slope
            intercept = mean_y - slope * mean_x
            fitted = [intercept + slope * idx for idx in range(n)]
            ss_tot = sum((price - mean_y) ** 2 for price in series)
            ss_res = sum((price - fit) ** 2 for price, fit in zip(series, fitted))
            r2 = 0.0 if ss_tot <= 1e-9 else max(0.0, 1.0 - ss_res / ss_tot)
            return slope, intercept, r2

        if frozen_slope is None or frozen_intercept is None:
            estimation_history.append(mid)
            if len(estimation_history) >= freeze_min_points:
                slope, intercept, fit_r2 = _fit_ols(estimation_history)
            else:
                slope = fixed_slope
                intercept = anchor_mid
                fit_r2 = 0.0

            if freeze_after_points > 0 and len(estimation_history) >= freeze_after_points and fit_r2 >= freeze_r2_min:
                memory["frozen_slope"] = slope
                memory["frozen_intercept"] = intercept
                memory["frozen_r2"] = fit_r2
                memory["frozen_at_tick"] = tick_index
                frozen_slope = slope
                frozen_intercept = intercept
                frozen_r2 = fit_r2
        else:
            slope = float(frozen_slope)
            intercept = float(frozen_intercept)
            fit_r2 = float(frozen_r2) if frozen_r2 is not None else 1.0

        fitted_now = intercept + slope * tick_index
        raw_residual = mid - fitted_now

        residuals = memory.setdefault("residual_history", [])
        residuals.append(raw_residual)
        if len(residuals) > residual_window:
            del residuals[:-residual_window]

        residual_mean = sum(residuals) / max(1, len(residuals))
        centered_residuals = [r - residual_mean for r in residuals]
        residual = raw_residual - residual_mean

        residual_var = sum(r * r for r in centered_residuals) / max(1, len(centered_residuals))
        rmse = max(math.sqrt(residual_var), residual_rmse_floor)

        if r2_cap <= r2_floor:
            r2_conf = 1.0 if fit_r2 > r2_floor else 0.0
        else:
            r2_conf = max(0.0, min(1.0, (fit_r2 - r2_floor) / (r2_cap - r2_floor)))
        if confidence_cap_rmse <= 0:
            rmse_conf = 1.0
        else:
            rmse_conf = max(
                confidence_floor,
                min(1.0, 1.0 - (rmse / confidence_cap_rmse) * (1.0 - confidence_floor)),
            )
        confidence = max(confidence_floor, min(1.0, max(confidence_floor, r2_conf) * rmse_conf))

        local_intercept = intercept + residual_mean
        fitted_now_adj = local_intercept + slope * tick_index
        forecast = local_intercept + slope * (tick_index + horizon)
        trend_ticks = slope * horizon * confidence
        residual_z = residual / rmse
        fair_value = forecast - mean_revert_weight * residual

        stats = {
            "slope": slope,
            "intercept": local_intercept,
            "fitted_now": fitted_now_adj,
            "forecast": forecast,
            "residual": residual,
            "residual_mean": residual_mean,
            "rmse": rmse,
            "r2": fit_r2,
            "confidence": confidence,
            "trend_ticks": trend_ticks,
            "fair_value": fair_value,
            "residual_z": residual_z,
            "tick_index": float(tick_index),
            "slope_frozen": 1.0 if frozen_slope is not None and frozen_intercept is not None else 0.0,
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
        trend_inv_per_tick = float(self.params.get("trend_inv_per_tick", 24.0))
        resid_inv_per_z = float(self.params.get("resid_inv_per_z", 8.0))
        inv_cap = int(self.params.get("trend_inventory_cap", 70))

        target = stats["trend_ticks"] * trend_inv_per_tick
        target -= stats["residual_z"] * resid_inv_per_z

        startup_target = int(self.params.get("startup_target", 32))
        startup_end_ts = int(self.params.get("startup_end_ts", 25000))
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
        gap_scale = max(1.0, float(self.params.get("target_gap_scale", 30.0)))
        bullish_boost = max(0.0, stats["trend_ticks"]) * float(self.params.get("trend_buy_boost_per_tick", 0.20))
        bearish_boost = max(0.0, -stats["trend_ticks"]) * float(self.params.get("trend_sell_boost_per_tick", 0.20))
        cheap_boost = max(0.0, -stats["residual_z"]) * float(self.params.get("cheap_buy_boost_per_z", 0.12))
        rich_boost = max(0.0, stats["residual_z"]) * float(self.params.get("rich_sell_boost_per_z", 0.12))

        buy_mult = 1.0 + max(0.0, gap) / gap_scale + bullish_boost + cheap_boost
        sell_mult = 1.0 + max(0.0, -gap) / gap_scale + bearish_boost + rich_boost

        aggravate_cut = float(self.params.get("aggravate_cut", 0.08))
        if gap > 0:
            sell_mult *= aggravate_cut
        elif gap < 0:
            buy_mult *= aggravate_cut

        one_sided_gap = int(self.params.get("one_sided_target_gap", 28))
        strong_trend = float(self.params.get("strong_trend_ticks", 0.8))
        if gap >= one_sided_gap and stats["trend_ticks"] >= strong_trend:
            sell_mult = 0.0
        elif gap <= -one_sided_gap and stats["trend_ticks"] <= -strong_trend:
            buy_mult = 0.0

        buy_size = 0 if buy_mult <= 0.0 else min(buy_cap, max(min_quote_size, int(round(base_buy * buy_mult))))
        sell_size = 0 if sell_mult <= 0.0 else min(sell_cap, max(min_quote_size, int(round(base_sell * sell_mult))))
        return buy_size, sell_size

    def _quote_prices(
        self,
        *,
        book: BookSnapshot,
        stats: Dict[str, float],
        position: int,
        inv_target: int,
    ) -> Tuple[int, int, int, int]:
        best_bid = int(book.best_bid)
        best_ask = int(book.best_ask)
        tighten_ticks = int(self.params.get("tighten_ticks", 1))

        spread = best_ask - best_bid
        if spread >= 2:
            bid_price = min(best_bid + tighten_ticks, best_ask - 1)
            ask_price = max(best_ask - tighten_ticks, best_bid + 1)
        else:
            bid_price = best_bid
            ask_price = best_ask

        bid_extra = 0
        ask_relax = 0
        if stats["trend_ticks"] >= float(self.params.get("strong_trend_ticks", 0.8)):
            bid_extra += 1
            ask_relax += 1
        if stats["residual_z"] <= -float(self.params.get("cheap_residual_z", 0.8)):
            bid_extra += 1
        if stats["residual_z"] >= float(self.params.get("rich_residual_z", 0.8)):
            ask_relax = max(0, ask_relax - 1)

        if position < inv_target:
            ask_relax = max(ask_relax, 1)
        elif position > inv_target:
            bid_extra = max(0, bid_extra - 1)

        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        max_ask_relax = int(self.params.get("max_ask_relax_ticks", 2))
        bid_extra = max(0, min(max_bid_extra, bid_extra))
        ask_relax = max(0, min(max_ask_relax, ask_relax))

        bid_price = min(best_ask - 1, bid_price + bid_extra)
        ask_price = min(best_ask, ask_price + ask_relax)
        ask_price = max(ask_price, best_bid + 1)

        if bid_price >= ask_price:
            bid_price = min(best_ask - 1, best_bid + 1)
            ask_price = max(best_bid + 1, bid_price + 1)

        return bid_price, ask_price, bid_extra, ask_relax

    def _selective_take(
        self,
        *,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []

        take_edge = float(self.params.get("take_edge", 6.0))
        max_take = int(self.params.get("max_take_size", 10))
        take_only_toward_target = bool(self.params.get("take_only_toward_target", True))

        if buy_cap > 0:
            for ask_price in sorted(order_depth.sell_orders):
                if ask_price > fair_value - take_edge:
                    break
                if take_only_toward_target and position >= inv_target:
                    break
                qty = min(-order_depth.sell_orders[ask_price], buy_cap, max_take)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty
                position += qty
                if buy_cap <= 0:
                    break

        if sell_cap > 0:
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                if bid_price < fair_value + take_edge:
                    break
                if take_only_toward_target and position <= inv_target:
                    break
                qty = min(order_depth.buy_orders[bid_price], sell_cap, max_take)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_price, -qty))
                sell_cap -= qty
                position -= qty
                if sell_cap <= 0:
                    break

        return orders, buy_cap, sell_cap

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

        mid = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        inv_target = self._inventory_target(state=state, stats=stats, position=position)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if bool(self.params.get("enable_selective_take", False)):
            take_orders, buy_cap, sell_cap = self._selective_take(
                order_depth=order_depth,
                fair_value=stats["fair_value"],
                position=position,
                inv_target=inv_target,
                buy_cap=buy_cap,
                sell_cap=sell_cap,
            )
            orders.extend(take_orders)

        bid_price, ask_price, bid_extra, ask_relax = self._quote_prices(
            book=book,
            stats=stats,
            position=position,
            inv_target=inv_target,
        )
        buy_size, sell_size = self._size_from_target(
            position=position,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["inv_target"] = inv_target
        memory["last_spread"] = book.spread

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "reg_slope": round(stats["slope"], 4),
                "reg_conf": round(stats["confidence"], 3),
                "trend_ticks": round(stats["trend_ticks"], 2),
                "residual_z": round(stats["residual_z"], 2),
                "residual_mean": round(stats["residual_mean"], 2),
                "slope_frozen": int(stats["slope_frozen"]),
                "fair_value": round(stats["fair_value"], 2),
                "inv_target": inv_target,
                "bid_extra": bid_extra,
                "ask_relax": ask_relax,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        stats = memory.get("regression_stats")
        if not stats:
            return {}
        return {
            "reg_fitted_now": float(stats["fitted_now"]),
            "reg_forecast": float(stats["forecast"]),
            "reg_fair_value": float(stats["fair_value"]),
        }

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'INTARIAN_PEPPER_ROOT': {'aggravate_cut': 0.05,
                          'cheap_buy_boost_per_z': 0.15,
                          'cheap_residual_z': 0.9,
                          'enable_selective_take': False,
                          'fixed_slope': 0.1015,
                          'freeze_after_points': 1000,
                          'freeze_min_points': 300,
                          'freeze_r2_min': 0.8,
                          'last_ts_value': 999900,
                          'log_flush_ts': 1000,
                          'maker_size': 80,
                          'max_ask_relax_ticks': 2,
                          'max_bid_extra_ticks': 2,
                          'max_take_size': 8,
                          'one_sided_target_gap': 26,
                          'position_limit': 80,
                          'reg_horizon': 25,
                          'reg_r2_cap': 0.85,
                          'reg_r2_floor': 0.3,
                          'reg_residual_reversion': 0.35,
                          'reg_rmse_floor': 1.0,
                          'resid_inv_per_z': 8.0,
                          'residual_window': 160,
                          'rich_residual_z': 0.9,
                          'rich_sell_boost_per_z': 0.15,
                          'startup_end_ts': 25000,
                          'startup_target': 36,
                          'strategy': 'round1_regression_mm_v4',
                          'strong_trend_ticks': 0.75,
                          'take_edge': 6.0,
                          'take_only_toward_target': True,
                          'target_gap_scale': 28.0,
                          'tighten_ticks': 1,
                          'trend_buy_boost_per_tick': 0.22,
                          'trend_confidence_cap_rmse': 4.0,
                          'trend_confidence_floor': 0.65,
                          'trend_inv_per_tick': 24.0,
                          'trend_inventory_cap': 72,
                          'trend_sell_boost_per_tick': 0.18,
                          'ts_increment': 100}}

STRATEGY_CLASSES = {"round1_regression_mm_v4": Round1RegressionMMV4Strategy}

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
