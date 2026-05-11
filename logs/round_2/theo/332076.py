from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Optional, Set, Tuple
from typing import Any, Dict, List, Optional, Tuple
from typing import Any, Dict, List, Tuple
from typing import List, Tuple
from typing import Optional
from typing import Optional, Set, Tuple
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


# ── prosperity/strategies/base/base.py ────────────────────────────────────────────

class BaseStrategy(ABC):

    def __init__(self, product: str, params: Dict[str, Any]):
        self.product = product
        self.params = params

    def on_tick(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        self._memory = memory  # available to all helper methods via self._memory

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
        ...

    def _microprice(self, book: "BookSnapshot") -> float:
        bid_total = sum(v for _, v in book.bid_levels)
        ask_total = sum(v for _, v in book.ask_levels)

        prev = self._memory.get("_microprice_last", 0.0)

        if bid_total == 0 or ask_total == 0:
            return float(prev)

        bid_vwap = sum(p * v for p, v in book.bid_levels) / bid_total
        ask_vwap = sum(p * v for p, v in book.ask_levels) / ask_total
        result = (bid_vwap * ask_total + ask_vwap * bid_total) / (bid_total + ask_total)

        self._memory["_microprice_last"] = result
        return result

    def _smooth_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        window = int(self.params.get("mid_smooth_window", 20))
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

    def _update_volatility(self, mid: float, memory: Dict[str, Any]) -> float:
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

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        return {}

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
        if not self.params.get("quote_trace_enabled", False) or not self.runtime_trace_enabled():
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
        gap_exploit: bool = False,
    ) -> None:
        if not self.runtime_trace_enabled():
            return

        taker_log = memory.setdefault("_taker_log", [])
        entry = [int(state.timestamp), side, price, quantity]
        if gap_exploit:
            entry.append(1)
        taker_log.append(entry)

        flush_ts = int(self.params.get("log_flush_ts", 10000))
        ts_increment = int(self.params.get("ts_increment", 100))
        last_ts = int(self.params.get("last_ts_value", 199900))
        second_to_last = last_ts - ts_increment

        is_quote_flush = flush_ts > 0 and (int(state.timestamp) % flush_ts) == (flush_ts - 100)
        deferred = memory.get("_taker_flush_deferred", False)

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


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized.py ─────────────

StrategyBase = BaseStrategy

def _ewma(previous: Optional[float], current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous

class TheoBestCleanGeneralizedStrategy(StrategyBase):

    def _update_regression(
        self,
        *,
        state: TradingState,
        mid: float,
        memory: Dict[str, Any],
    ) -> Dict[str, float]:
        ts_increment = max(1, int(self.params.get("ts_increment", 100)))
        seed_slope = float(self.params.get("seed_slope", 0.1015))
        block_size = max(1, int(self.params.get("block_size", 100)))
        min_completed_blocks = max(1, int(self.params.get("min_completed_blocks", 5)))
        horizon = int(self.params.get("reg_horizon", 25))
        r2_floor = float(self.params.get("reg_r2_floor", 0.85))
        r2_cap = float(self.params.get("reg_r2_cap", 0.98))
        rmse_floor = float(self.params.get("reg_rmse_floor", 1.0))
        mean_revert_weight = float(self.params.get("reg_residual_reversion", 0.25))

        anchor_ts = memory.setdefault("line_anchor_ts", int(state.timestamp))
        anchor_mid = memory.setdefault("line_anchor_mid", mid)
        tick_index = max(0, int(round((int(state.timestamp) - anchor_ts) / ts_increment)))

        completed_means = memory.setdefault("block_means", [])
        completed_centers = memory.setdefault("block_centers", [])
        current_block_index = int(memory.get("current_block_index", 0))
        block_sum = float(memory.get("current_block_sum", 0.0))
        block_count = int(memory.get("current_block_count", 0))

        target_block_index = tick_index // block_size
        if target_block_index != current_block_index and block_count > 0:
            start_tick = current_block_index * block_size
            end_tick = start_tick + block_count - 1
            completed_means.append(block_sum / block_count)
            completed_centers.append((start_tick + end_tick) / 2.0)
            current_block_index = target_block_index
            block_sum = 0.0
            block_count = 0

        block_sum += mid
        block_count += 1
        memory["current_block_index"] = current_block_index
        memory["current_block_sum"] = block_sum
        memory["current_block_count"] = block_count

        current_block_mean = block_sum / max(1, block_count)
        current_block_start = current_block_index * block_size
        current_block_center = current_block_start + (block_count - 1) / 2.0

        xs: List[float] = list(completed_centers)
        ys: List[float] = list(completed_means)
        if block_count > 0:
            xs.append(current_block_center)
            ys.append(current_block_mean)

        if len(completed_means) < min_completed_blocks:
            slope = seed_slope
            intercept = anchor_mid
            fit_r2 = 0.0
            fitted_now = anchor_mid + slope * tick_index
            residual = mid - fitted_now
            rmse = max(abs(residual), rmse_floor)
            confidence = float(self.params.get("bootstrap_confidence", 0.55))
        else:
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n

            ss_xx = 0.0
            ss_xy = 0.0
            for x, y in zip(xs, ys):
                dx = x - mean_x
                dy = y - mean_y
                ss_xx += dx * dx
                ss_xy += dx * dy

            slope = ss_xy / ss_xx if ss_xx > 0 else seed_slope
            intercept = mean_y - slope * mean_x
            fitted_points = [intercept + slope * x for x in xs]
            fitted_now = intercept + slope * tick_index
            residual = mid - fitted_now

            ss_tot = sum((y - mean_y) ** 2 for y in ys)
            ss_res = sum((y - fit) ** 2 for y, fit in zip(ys, fitted_points))
            fit_r2 = 0.0 if ss_tot <= 1e-9 else max(0.0, 1.0 - ss_res / ss_tot)
            rmse = max(math.sqrt(ss_res / max(1, n)), rmse_floor)

            if r2_cap <= r2_floor:
                confidence = 1.0 if fit_r2 > r2_floor else 0.0
            else:
                confidence = max(0.0, min(1.0, (fit_r2 - r2_floor) / (r2_cap - r2_floor)))

        trend_ticks = slope * horizon * confidence
        residual_z = residual / rmse if rmse > 0 else 0.0
        forecast = intercept + slope * (tick_index + horizon)
        fair_value = forecast - mean_revert_weight * residual

        stats = {
            "slope": slope,
            "intercept": intercept,
            "fitted_now": fitted_now,
            "forecast": forecast,
            "residual": residual,
            "rmse": rmse,
            "r2": fit_r2,
            "confidence": confidence,
            "trend_ticks": trend_ticks,
            "fair_value": fair_value,
            "residual_z": residual_z,
            "block_count": float(len(completed_means)),
            "current_block_mean": current_block_mean,
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
        trend_inv_per_tick = float(self.params.get("trend_inv_per_tick", 26.0))
        resid_inv_per_z = float(self.params.get("resid_inv_per_z", 7.0))
        inv_cap = int(self.params.get("trend_inventory_cap", 74))

        target = stats["trend_ticks"] * trend_inv_per_tick
        target -= stats["residual_z"] * resid_inv_per_z

        startup_target = int(self.params.get("startup_target", 40))
        startup_end_ts = int(self.params.get("startup_end_ts", 30000))
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
        gap_scale = max(1.0, float(self.params.get("target_gap_scale", 26.0)))
        bullish_boost = max(0.0, stats["trend_ticks"]) * float(self.params.get("trend_buy_boost_per_tick", 0.24))
        bearish_boost = max(0.0, -stats["trend_ticks"]) * float(self.params.get("trend_sell_boost_per_tick", 0.20))
        cheap_boost = max(0.0, -stats["residual_z"]) * float(self.params.get("cheap_buy_boost_per_z", 0.18))
        rich_boost = max(0.0, stats["residual_z"]) * float(self.params.get("rich_sell_boost_per_z", 0.14))

        buy_mult = 1.0 + max(0.0, gap) / gap_scale + bullish_boost + cheap_boost
        sell_mult = 1.0 + max(0.0, -gap) / gap_scale + bearish_boost + rich_boost

        aggravate_cut = float(self.params.get("aggravate_cut", 0.04))
        if gap > 0:
            sell_mult *= aggravate_cut
        elif gap < 0:
            buy_mult *= aggravate_cut

        one_sided_gap = int(self.params.get("one_sided_target_gap", 24))
        strong_trend = float(self.params.get("strong_trend_ticks", 1.1))
        if gap >= one_sided_gap and stats["trend_ticks"] >= strong_trend:
            sell_mult = 0.0
        elif gap <= -one_sided_gap and stats["trend_ticks"] <= -strong_trend:
            buy_mult = 0.0

        buy_size = 0 if buy_mult <= 0.0 else min(buy_cap, max(min_quote_size, int(round(base_buy * buy_mult))))
        sell_size = 0 if sell_mult <= 0.0 else min(sell_cap, max(min_quote_size, int(round(base_sell * sell_mult))))
        return buy_size, sell_size

    def _process_premium_fills(
        self,
        state:  TradingState,
        memory: Dict[str, Any],
    ) -> None:
        empty_side_shift      = int(self.params.get("empty_side_shift", 85))
        gap_fill_min_premium  = int(self.params.get("gap_fill_min_premium", max(30, empty_side_shift // 2)))
        last_best_bid         = memory.get("_last_best_bid")
        last_best_ask         = memory.get("_last_best_ask")
        prev_gap_sell_quotes  = {int(p) for p in memory.get("_active_gap_sell_quotes", [])}
        prev_gap_buy_quotes   = {int(p) for p in memory.get("_active_gap_buy_quotes", [])}

        for trade in state.own_trades.get(self.product, []):
            trade_price = int(trade.price)
            if trade.seller == "SUBMISSION":
                is_gap_fill = trade_price in prev_gap_sell_quotes
                if not is_gap_fill and last_best_ask is not None:
                    is_gap_fill = trade_price >= int(last_best_ask) + gap_fill_min_premium
                if is_gap_fill:
                    memory["_last_gap_sell_ts"]    = int(trade.timestamp)
                    memory["_last_gap_sell_price"] = trade_price
                    memory["_last_gap_sell_qty"]   = int(trade.quantity)
            elif trade.buyer == "SUBMISSION":
                is_gap_fill = trade_price in prev_gap_buy_quotes
                if not is_gap_fill and last_best_bid is not None:
                    is_gap_fill = trade_price <= int(last_best_bid) - gap_fill_min_premium
                if is_gap_fill:
                    memory["_last_gap_buy_ts"]    = int(trade.timestamp)
                    memory["_last_gap_buy_price"] = trade_price
                    memory["_last_gap_buy_qty"]   = int(trade.quantity)

    def _handle_onesided_book(
        self,
        book:            BookSnapshot,
        position:        int,
        memory:          Dict[str, Any],
        gap_sell_quotes: List[int],
        gap_buy_quotes:  List[int],
    ) -> Optional[Tuple[List[Order], int]]:
        orders: List[Order] = []
        empty_side_shift          = int(self.params.get("empty_side_shift", 85))
        ask_gap_sell_enable_pos   = int(self.params.get("ask_gap_sell_enable_position", self.position_limit()))
        ask_gap_quote_size        = int(self.params.get("ask_gap_quote_size", 8))
        last_best_bid             = memory.get("_last_best_bid")
        last_best_ask             = memory.get("_last_best_ask")

        if book.best_bid is None and book.best_ask is None:
            if last_best_bid is None and last_best_ask is None:
                return orders, 0
            ref           = last_best_bid if last_best_bid is not None else last_best_ask
            gap_buy_price = ref - empty_side_shift
            gap_sell_price = ref + empty_side_shift
            orders.append(Order(self.product, gap_buy_price, self.buy_capacity(position)))
            gap_buy_quotes.append(gap_buy_price)
            if position >= ask_gap_sell_enable_pos:
                gap_sell_qty = min(self.sell_capacity(position), ask_gap_quote_size)
                if gap_sell_qty > 0:
                    orders.append(Order(self.product, gap_sell_price, -gap_sell_qty))
                    gap_sell_quotes.append(gap_sell_price)
            memory["_active_gap_sell_quotes"] = gap_sell_quotes[:]
            memory["_active_gap_buy_quotes"]  = gap_buy_quotes[:]
            memory["_gap_sell_px"]            = gap_sell_quotes[:]
            memory["_gap_buy_px"]             = gap_buy_quotes[:]
            return orders, 0

        if book.best_bid is None:
            ref           = last_best_bid if last_best_bid is not None else book.best_ask - 1
            gap_buy_price = ref - empty_side_shift
            orders.append(Order(self.product, gap_buy_price, self.buy_capacity(position)))
            gap_buy_quotes.append(gap_buy_price)

        elif book.best_ask is None:
            ref            = last_best_ask if last_best_ask is not None else book.best_bid + 1
            gap_sell_price = ref + empty_side_shift
            if position >= ask_gap_sell_enable_pos:
                gap_sell_qty = min(self.sell_capacity(position), ask_gap_quote_size)
                if gap_sell_qty > 0:
                    orders.append(Order(self.product, gap_sell_price, -gap_sell_qty))
                    gap_sell_quotes.append(gap_sell_price)

        if book.best_bid is not None:
            memory["_last_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_best_ask"] = book.best_ask
            recent_best_asks             = memory.setdefault("_recent_best_asks", [])
            gap_scout_recent_ask_window  = int(self.params.get("gap_scout_recent_ask_window", 6))
            recent_best_asks.append(int(book.best_ask))
            if len(recent_best_asks) > gap_scout_recent_ask_window:
                del recent_best_asks[:-gap_scout_recent_ask_window]

        if book.best_bid is None or book.best_ask is None:
            memory["_active_gap_sell_quotes"] = gap_sell_quotes[:]
            memory["_active_gap_buy_quotes"]  = gap_buy_quotes[:]
            memory["_gap_sell_px"]            = gap_sell_quotes[:]
            memory["_gap_buy_px"]             = gap_buy_quotes[:]
            return orders, 0

        return None

    def _update_ewma_signals(
        self,
        spot:   float,
        fv:     float,
        memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float, float, float]:
        fv_alpha     = float(self.params.get("fv_alpha", 0.05))
        short_alpha  = float(self.params.get("short_alpha", 0.22))
        slope_window = int(self.params.get("slope_window", 20))

        ewma_fv   = _ewma(memory.get("ewma_fv"), spot, fv_alpha)
        short_ema = _ewma(memory.get("short_ema"), spot, short_alpha)
        memory["ewma_fv"]   = ewma_fv
        memory["short_ema"] = short_ema

        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(ewma_fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[:-(slope_window + 1)]

        ewma_slope = 0.0
        if len(fv_hist) >= slope_window:
            ewma_slope = fv_hist[-1] - fv_hist[-slope_window]

        stretch         = spot - short_ema
        trim_reference  = ewma_fv + float(self.params.get("trim_reference_slope_weight", 0.15)) * max(0.0, ewma_slope)
        entry_reference = min(fv, trim_reference)

        return ewma_fv, short_ema, ewma_slope, stretch, trim_reference, entry_reference

    def _compute_regime(
        self,
        state:           TradingState,
        stats:           Dict[str, float],
        spot:            float,
        stretch:         float,
        book:            BookSnapshot,
        position: int,
        memory:   Dict[str, Any],
    ) -> Dict[str, Any]:
        trend_ticks = stats["trend_ticks"]
        residual_z  = stats["residual_z"]
        ts          = int(state.timestamp)

        bull_threshold  = float(self.params.get("bull_threshold", 1.0))
        bullish         = trend_ticks > bull_threshold
        fastfill_target = int(self.params.get("fastfill_target", self.position_limit()))
        fastfill_end_ts = int(self.params.get("fastfill_end_ts", 15000))
        build_phase     = bullish and (position < fastfill_target or ts <= fastfill_end_ts)
        base_target     = self._inventory_target(state=state, stats=stats, position=position)
        inv_target      = max(base_target, fastfill_target) if build_phase else base_target

        dip_threshold   = float(self.params.get("dip_threshold", 1.0))
        chase_threshold = float(self.params.get("chase_threshold", 1.25))
        cheap_z         = float(self.params.get("cheap_residual_z", 0.9))
        rich_z          = float(self.params.get("rich_residual_z", 1.0))
        on_dip          = bullish and (stretch <= -dip_threshold or residual_z <= -cheap_z)

        startup_fast_target           = int(self.params.get("startup_fast_target", min(fastfill_target, 32)))
        startup_fast_take_cap         = int(self.params.get("startup_fast_take_cap", 12))
        startup_fast_passive_buy      = int(self.params.get("startup_fast_passive_buy", 8))
        startup_cold_take_cap         = int(self.params.get("startup_cold_take_cap", 4))
        startup_cold_passive_buy      = int(self.params.get("startup_cold_passive_buy", 3))
        startup_cold_join_ticks       = int(self.params.get("startup_cold_join_ticks", 0))
        startup_cold_take_edge        = float(self.params.get("startup_cold_take_edge", 3.0))
        startup_chase_take_cap        = int(self.params.get("startup_chase_take_cap", 1))
        startup_chase_passive_buy     = int(self.params.get("startup_chase_passive_buy", 1))
        startup_chase_take_edge       = float(self.params.get("startup_chase_take_edge", 4.0))
        startup_pullback_ticks        = float(self.params.get("startup_pullback_ticks", 2.0))
        startup_pre_pullback_target   = int(self.params.get("startup_pre_pullback_target", 48))
        startup_post_pullback_target  = int(self.params.get("startup_post_pullback_target", 64))
        startup_delayed_finish_ts     = int(self.params.get("startup_delayed_finish_ts", 3000))
        startup_release_stretch       = float(self.params.get("startup_release_stretch", 1.0))
        startup_release_take_cap      = int(self.params.get("startup_release_take_cap", 8))
        startup_dip_take_edge_boost   = float(self.params.get("startup_dip_take_edge_boost", 1.0))
        startup_anchor_bid_spread     = float(self.params.get("startup_anchor_bid_spread", 1.0))
        startup_anchor_gap_ticks      = int(self.params.get("startup_anchor_gap_ticks", 1))
        startup_anchor_size           = int(self.params.get("startup_anchor_size", 4))

        startup_window_active = build_phase and ts <= fastfill_end_ts
        startup_fast_loading  = startup_window_active and position < startup_fast_target
        startup_cold_loading  = (
            startup_window_active
            and startup_fast_target <= position < inv_target
            and not on_dip
        )

        startup_peak_spot = float(memory.get("startup_peak_spot", spot))
        if startup_window_active:
            startup_peak_spot = max(startup_peak_spot, float(spot))
            memory["startup_peak_spot"] = startup_peak_spot
        else:
            memory["startup_peak_spot"] = float(spot)

        current_pullback_ready = startup_peak_spot - float(spot) >= startup_pullback_ticks
        pullback_seen          = bool(memory.get("startup_pullback_seen", False)) or current_pullback_ready
        memory["startup_pullback_seen"] = int(pullback_seen) if startup_window_active else 0

        build_release_ready = pullback_seen and stretch <= -startup_release_stretch

        active_build_target = inv_target
        if startup_window_active and ts <= startup_delayed_finish_ts and not build_release_ready:
            if not pullback_seen:
                active_build_target = min(active_build_target, startup_pre_pullback_target)
            else:
                active_build_target = min(active_build_target, startup_post_pullback_target)

        last_gap_sell_ts    = int(memory.get("_last_gap_sell_ts", -(10 ** 9)))
        last_gap_sell_price = memory.get("_last_gap_sell_price")
        gap_rebuy_window      = int(self.params.get("gap_rebuy_window", 2500))
        gap_rebuy_min_discount = float(self.params.get("gap_rebuy_min_discount", 20.0))
        gap_rebuy_age         = ts - last_gap_sell_ts
        gap_rebuy_discount    = 0.0
        if last_gap_sell_price is not None:
            gap_rebuy_discount = float(last_gap_sell_price) - float(book.best_ask)
        gap_rebuy_mode = (
            bullish
            and last_gap_sell_price is not None
            and 0 <= gap_rebuy_age <= gap_rebuy_window
            and position < inv_target
            and gap_rebuy_discount >= gap_rebuy_min_discount
        )
        if gap_rebuy_mode:
            active_build_target = inv_target

        chasing = bullish and not on_dip and (
            stretch >= chase_threshold
            or (startup_cold_loading and not pullback_seen)
        )

        trim_start_position      = int(self.params.get("trim_start_position", 79))
        trim_extension_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        trim_quote_mode = (
            bullish
            and not build_phase
            and position >= trim_start_position
            and stretch >= trim_extension_threshold
        )
        trim_take_mode = False
        trim_take_qty  = 0

        rebuy_block_until = int(memory.get("rebuy_block_until", -(10 ** 9)))
        rebuy_blocked     = bullish and ts < rebuy_block_until

        take_buy_edge_bull      = float(self.params.get("take_buy_edge_bull", -8.0))
        take_buy_edge_neut      = float(self.params.get("take_buy_edge_neut", 2.0))
        fastfill_buy_edge_boost = float(self.params.get("fastfill_buy_edge_boost", 0.0))

        if bullish:
            buy_edge = take_buy_edge_bull
            if build_phase:
                buy_edge -= fastfill_buy_edge_boost
            elif residual_z >= rich_z:
                buy_edge = take_buy_edge_neut
            if on_dip:
                buy_edge -= startup_dip_take_edge_boost
            if startup_cold_loading:
                buy_edge = max(buy_edge, startup_cold_take_edge)
            if chasing:
                buy_edge = max(buy_edge, startup_chase_take_edge)
        else:
            buy_edge = take_buy_edge_neut

        buy_cap_initial = self.buy_capacity(position)
        buy_take_cap    = buy_cap_initial
        if build_phase:
            if startup_fast_loading:
                buy_take_cap = min(buy_take_cap, startup_fast_take_cap)
            if startup_cold_loading:
                buy_take_cap = min(buy_take_cap, startup_cold_take_cap)
            if chasing:
                buy_take_cap = min(buy_take_cap, startup_chase_take_cap)
            if build_release_ready:
                buy_take_cap = min(buy_take_cap, startup_release_take_cap)

        if rebuy_blocked:
            buy_edge     = 1_000_000.0
            buy_take_cap = 0
        elif gap_rebuy_mode:
            gap_rebuy_buy_edge  = float(self.params.get("gap_rebuy_buy_edge", -10.0))
            gap_rebuy_take_cap  = int(self.params.get("gap_rebuy_take_cap", 8))
            buy_edge     = min(buy_edge, gap_rebuy_buy_edge)
            buy_take_cap = min(buy_cap_initial, max(buy_take_cap, gap_rebuy_take_cap))

        return {
            "timestamp":              ts,
            "bullish":                bullish,
            "build_phase":            build_phase,
            "inv_target":             inv_target,
            "active_build_target":    active_build_target,
            "on_dip":                 on_dip,
            "startup_window_active":  startup_window_active,
            "startup_fast_loading":   startup_fast_loading,
            "startup_cold_loading":   startup_cold_loading,
            "startup_fast_passive_buy":  startup_fast_passive_buy,
            "startup_cold_passive_buy":  startup_cold_passive_buy,
            "startup_chase_passive_buy": startup_chase_passive_buy,
            "startup_anchor_bid_spread": startup_anchor_bid_spread,
            "startup_anchor_gap_ticks":  startup_anchor_gap_ticks,
            "startup_anchor_size":       startup_anchor_size,
            "startup_cold_join_ticks":   startup_cold_join_ticks,
            "pullback_seen":          pullback_seen,
            "current_pullback_ready": current_pullback_ready,
            "build_release_ready":    build_release_ready,
            "gap_rebuy_mode":         gap_rebuy_mode,
            "gap_rebuy_discount":     gap_rebuy_discount,
            "chasing":                chasing,
            "rebuy_blocked":          rebuy_blocked,
            "buy_edge":               buy_edge,
            "buy_take_cap":           buy_take_cap,
            "trim_quote_mode":        trim_quote_mode,
            "trim_take_mode":         trim_take_mode,
            "trim_take_qty":          trim_take_qty,
            "rich_z":                 rich_z,
            "cheap_z":                cheap_z,
        }

    def _compute_quote_prices(
        self,
        book:            BookSnapshot,
        fv:              float,
        stats:           Dict[str, float],
        regime:          Dict[str, Any],
        entry_reference: float,
    ) -> Tuple[int, int]:
        bullish             = regime["bullish"]
        build_phase         = regime["build_phase"]
        startup_cold_loading = regime["startup_cold_loading"]
        chasing             = regime["chasing"]
        trend_ticks         = stats["trend_ticks"]
        residual_z          = stats["residual_z"]
        cheap_z             = regime["cheap_z"]

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))

        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)

        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        bid_extra   = 0
        strong      = float(self.params.get("strong_trend_ticks", 1.1))
        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        if trend_ticks >= strong:
            bid_extra += 1
        if trend_ticks >= very_strong:
            bid_extra += 1
        if residual_z <= -cheap_z:
            bid_extra += 1

        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        bid_extra     = max(0, min(max_bid_extra, bid_extra))
        bid_price     = min(book.best_ask - 1, bid_price + bid_extra)

        startup_anchor_bid_spread = regime["startup_anchor_bid_spread"]
        startup_cold_join_ticks   = regime["startup_cold_join_ticks"]
        if build_phase:
            if startup_cold_loading or chasing:
                raw_entry_bid = round(entry_reference - startup_anchor_bid_spread)
                bid_price     = min(book.best_ask - 1, max(raw_entry_bid, 1))
                bid_price     = max(bid_price, min(book.best_bid + startup_cold_join_ticks, book.best_ask - 1))
            else:
                bid_price = max(bid_price, min(book.best_bid + 1, book.best_ask - 1))

        return bid_price, ask_price

    def _buy_takers(
        self,
        order_depth: OrderDepth,
        fv:          float,
        position:    int,
        buy_cap:     int,
        regime:      Dict[str, Any],
    ) -> Tuple[List[Order], int, int, Set[int]]:
        orders:         List[Order] = []
        swept_prices:   Set[int]    = set()
        pending_buy     = 0
        buy_take_cap    = regime["buy_take_cap"]

        build_phase         = regime["build_phase"]
        active_build_target = regime["active_build_target"]
        buy_edge            = regime["buy_edge"]
        ts                  = regime["timestamp"]

        deep_take_guard_end_ts = int(self.params.get("fastfill_deep_take_guard_end_ts", 0))
        deep_take_max_gap      = int(self.params.get("fastfill_deep_take_max_gap_ticks", 999999))
        deep_take_guard        = build_phase and ts <= deep_take_guard_end_ts
        first_take_ask: Optional[int] = None

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0 or buy_take_cap <= 0:
                break
            room = max(0, active_build_target - position - pending_buy)
            if build_phase and room <= 0:
                break
            if first_take_ask is None:
                first_take_ask = ask_p
            elif deep_take_guard and ask_p - first_take_ask > deep_take_max_gap:
                break
            qty = min(
                -order_depth.sell_orders[ask_p],
                buy_cap,
                buy_take_cap,
                room if build_phase else buy_cap,
            )
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            swept_prices.add(ask_p)
            buy_cap     -= qty
            buy_take_cap -= qty
            pending_buy  += qty

        return orders, buy_cap, pending_buy, swept_prices

    def _sell_takers(
        self,
        order_depth: OrderDepth,
        fv:          float,
        position:    int,
        sell_cap:    int,
        regime:      Dict[str, Any],
    ) -> Tuple[List[Order], int, int]:
        orders:      List[Order] = []
        pending_sell = 0

        build_phase     = regime["build_phase"]
        trim_quote_mode = regime["trim_quote_mode"]
        bullish         = regime["bullish"]
        inv_target      = regime["inv_target"]

        if not build_phase and not trim_quote_mode and not bullish:
            sell_edge = float(self.params.get("take_sell_edge_neut", 2.0))
            if position > inv_target:
                pressure  = min(1.0, (position - inv_target) / max(1.0, float(self.position_limit())))
                sell_edge = sell_edge - float(self.params.get("unwind_take_edge", 10.0)) * pressure
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fv + sell_edge or sell_cap <= 0:
                    break
                qty = min(order_depth.buy_orders[bid_p], sell_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap     -= qty
                pending_sell += qty

        return orders, sell_cap, pending_sell

    def _compute_passive_sizes(
        self,
        position:         int,
        buy_cap:          int,
        sell_cap:         int,
        pending_buy:      int,
        pending_sell:     int,
        stats:            Dict[str, float],
        regime:           Dict[str, Any],
        entry_reference:  float,
        book:             BookSnapshot,
        bid_price:        int,
        ask_price:        int,
        buy_taker_prices: Set[int],
    ) -> Tuple[int, int, Optional[int], int, int, bool]:
        build_phase         = regime["build_phase"]
        gap_rebuy_mode      = regime["gap_rebuy_mode"]
        bullish             = regime["bullish"]
        rebuy_blocked       = regime["rebuy_blocked"]
        inv_target          = regime["inv_target"]
        active_build_target = regime["active_build_target"]
        on_dip              = regime["on_dip"]
        chasing             = regime["chasing"]
        startup_fast_loading     = regime["startup_fast_loading"]
        startup_cold_loading     = regime["startup_cold_loading"]
        startup_fast_passive_buy = regime["startup_fast_passive_buy"]
        startup_cold_passive_buy = regime["startup_cold_passive_buy"]
        startup_chase_passive_buy = regime["startup_chase_passive_buy"]
        startup_anchor_bid_spread = regime["startup_anchor_bid_spread"]
        startup_anchor_gap_ticks  = regime["startup_anchor_gap_ticks"]
        startup_anchor_size       = regime["startup_anchor_size"]

        real_best_bid = book.best_bid
        real_best_ask = book.best_ask
        for ap, _ in book.ask_levels:
            if ap not in buy_taker_prices:
                real_best_ask = ap
                break

        buy_size, sell_size = self._size_from_target(
            position=position + pending_buy - pending_sell,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        anchor_buy_price: Optional[int] = None
        anchor_buy_size                 = 0
        anchor_mode                     = False

        if build_phase:
            sell_size = 0
            if startup_fast_loading:
                buy_size = min(buy_size, min(buy_cap, startup_fast_passive_buy))
            elif startup_cold_loading:
                buy_size = min(buy_size, min(buy_cap, startup_cold_passive_buy))
            else:
                buy_size = max(buy_size, min(buy_cap, int(self.params.get("fastfill_min_passive_buy", 20))))
            if chasing:
                buy_size = min(buy_size, min(buy_cap, startup_chase_passive_buy))
            buy_size = min(buy_size, max(0, active_build_target - position - pending_buy))

            anchor_mode = bullish and not on_dip and (startup_cold_loading or chasing)
            if anchor_mode and buy_cap > buy_size:
                raw_anchor_bid       = round(entry_reference - startup_anchor_bid_spread)
                candidate_anchor_bid = min(max(raw_anchor_bid, 1), real_best_ask - 1)
                candidate_anchor_bid = min(candidate_anchor_bid, bid_price - startup_anchor_gap_ticks)
                if candidate_anchor_bid >= 1:
                    anchor_buy_price = candidate_anchor_bid
                    anchor_buy_size  = min(max(1, startup_anchor_size), max(0, buy_cap - buy_size))

        if gap_rebuy_mode:
            gap_rebuy_passive_buy = int(self.params.get("gap_rebuy_passive_buy", 6))
            buy_size = max(buy_size, min(buy_cap, gap_rebuy_passive_buy))
            buy_size = min(buy_size, max(0, inv_target - position - pending_buy))

        hold_sell_size   = int(self.params.get("hold_sell_size", 1))
        hold_sell_offset = int(self.params.get("hold_sell_offset", 0))
        if not build_phase and bullish and position >= self.position_limit() - hold_sell_size + 1:
            sell_size = min(sell_cap, hold_sell_size)
            ask_price = max(real_best_bid + 1, real_best_ask + hold_sell_offset)
        elif not build_phase and bullish:
            sell_size = 0

        if rebuy_blocked:
            buy_size = 0

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        return buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode

    def _gap_trap_quotes(
        self,
        book:           BookSnapshot,
        position:       int,
        memory:         Dict[str, Any],
        sell_cap:       int,
        ask_price:      int,
        trend_ticks:    float,
        gap_rebuy_mode: bool,
    ) -> Tuple[List[Order], List[int]]:
        orders:              List[Order] = []
        gap_sell_prices:     List[int]   = []
        empty_side_shift     = int(self.params.get("empty_side_shift", 85))

        gap_trap_fragile_streak = int(memory.get("_gap_trap_fragile_streak", 0))
        gap_trap_clear_streak   = int(memory.get("_gap_trap_clear_streak", 0))
        gap_trap_anchor_ask     = memory.get("_gap_trap_anchor_ask")
        gap_trap_peak_ask       = memory.get("_gap_trap_peak_ask")

        gap_trap_floor_position   = int(self.params.get("gap_trap_floor_position", 78))
        gap_trap_arm_streak       = int(self.params.get("gap_trap_arm_streak", 2))
        gap_trap_clear_after      = int(self.params.get("gap_trap_clear_after", 2))
        gap_trap_min_trend        = float(self.params.get("gap_trap_min_trend", 0.0))
        gap_trap_min_gap          = int(self.params.get("gap_trap_min_gap", 3))
        gap_trap_top_ask_max      = int(self.params.get("gap_trap_top_ask_max", 10))
        gap_trap_min_imbalance    = float(self.params.get("gap_trap_min_imbalance", 0.05))
        gap_trap_recent_ask_window  = int(self.params.get("gap_trap_recent_ask_window", 8))
        gap_trap_fragile_ask_window = int(self.params.get("gap_trap_fragile_ask_window", 4))
        gap_trap_base_size          = int(self.params.get("gap_trap_base_size", 3))
        gap_trap_premium_size_limit = int(self.params.get("gap_trap_premium_size", 2))
        gap_trap_premium_streak     = int(self.params.get("gap_trap_premium_streak", 3))
        gap_trap_premium_extra      = int(self.params.get("gap_trap_premium_extra", 2))

        ask_gap_fragile      = len(book.ask_levels) == 1
        if len(book.ask_levels) >= 2:
            ask_gap_fragile  = ask_gap_fragile or (book.ask_levels[1][0] - book.ask_levels[0][0] >= gap_trap_min_gap)
        ask_size_fragile     = book.best_ask_volume > 0 and book.best_ask_volume <= gap_trap_top_ask_max
        imbalance_supportive = book.imbalance is None or book.imbalance >= gap_trap_min_imbalance
        ask_side_fragile     = ask_gap_fragile or (ask_size_fragile and imbalance_supportive)

        trap_recent_asks = memory.setdefault("_gap_trap_recent_asks", [])
        trap_recent_asks.append(int(book.best_ask))
        if len(trap_recent_asks) > gap_trap_recent_ask_window:
            del trap_recent_asks[:-gap_trap_recent_ask_window]

        trap_fragile_asks = memory.setdefault("_gap_trap_fragile_asks", [])
        if ask_side_fragile:
            trap_fragile_asks.append(int(book.best_ask))
            if len(trap_fragile_asks) > gap_trap_fragile_ask_window:
                del trap_fragile_asks[:-gap_trap_fragile_ask_window]
        else:
            trap_fragile_asks[:] = []

        trap_armable = trend_ticks >= gap_trap_min_trend and not gap_rebuy_mode and position >= gap_trap_floor_position
        if trap_armable and ask_side_fragile:
            gap_trap_fragile_streak += 1
            gap_trap_clear_streak    = 0
        elif gap_trap_anchor_ask is not None:
            gap_trap_clear_streak   += 1
            gap_trap_fragile_streak  = max(0, gap_trap_fragile_streak - 1)
        else:
            gap_trap_fragile_streak  = 0
            gap_trap_clear_streak    = 0

        if gap_trap_anchor_ask is None and trap_armable and gap_trap_fragile_streak >= gap_trap_arm_streak and trap_recent_asks:
            gap_trap_anchor_ask = min(trap_recent_asks)
            gap_trap_peak_ask   = max(trap_fragile_asks) if trap_fragile_asks else int(book.best_ask)

        if gap_trap_anchor_ask is not None:
            if not trap_armable or gap_trap_clear_streak >= gap_trap_clear_after:
                gap_trap_anchor_ask = None
                gap_trap_peak_ask   = None
                gap_trap_fragile_streak = 0
                gap_trap_clear_streak   = 0
            else:
                if trap_recent_asks:
                    gap_trap_anchor_ask = min(int(gap_trap_anchor_ask), min(trap_recent_asks))
                if trap_fragile_asks:
                    latest_peak       = max(trap_fragile_asks)
                    gap_trap_peak_ask = max(int(gap_trap_peak_ask or latest_peak), latest_peak)

        gap_trap_sell_price    = None
        gap_trap_sell_size     = 0
        gap_trap_premium_price = None
        gap_trap_premium_size  = 0
        gap_trap_active        = False
        gap_trap_armed         = False

        if gap_trap_anchor_ask is not None:
            gap_trap_armed          = True
            candidate_gap_trap_sell = int(gap_trap_anchor_ask) + empty_side_shift
            if candidate_gap_trap_sell > ask_price:
                gap_trap_sell_price = candidate_gap_trap_sell
                gap_trap_sell_size  = min(
                    sell_cap,
                    gap_trap_base_size,
                    max(0, position - gap_trap_floor_position + 1),
                )
                gap_trap_active = gap_trap_sell_size > 0

            if (
                gap_trap_peak_ask is not None
                and gap_trap_fragile_streak >= gap_trap_premium_streak
                and sell_cap > gap_trap_sell_size
            ):
                candidate_gap_trap_premium = max(
                    (gap_trap_sell_price or ask_price) + gap_trap_premium_extra,
                    int(gap_trap_peak_ask) + empty_side_shift + gap_trap_premium_extra,
                )
                if candidate_gap_trap_premium > (gap_trap_sell_price or ask_price):
                    gap_trap_premium_price = candidate_gap_trap_premium
                    gap_trap_premium_size  = min(
                        max(0, sell_cap - gap_trap_sell_size),
                        gap_trap_premium_size_limit,
                        max(0, position - gap_trap_floor_position),
                    )
                    gap_trap_active = gap_trap_active or gap_trap_premium_size > 0

        if gap_trap_sell_size > 0 and gap_trap_sell_price is not None:
            orders.append(Order(self.product, gap_trap_sell_price, -gap_trap_sell_size))
            gap_sell_prices.append(gap_trap_sell_price)
        if gap_trap_premium_size > 0 and gap_trap_premium_price is not None:
            orders.append(Order(self.product, gap_trap_premium_price, -gap_trap_premium_size))
            gap_sell_prices.append(gap_trap_premium_price)

        memory["_gap_trap_fragile_streak"] = gap_trap_fragile_streak
        memory["_gap_trap_clear_streak"]   = gap_trap_clear_streak
        memory["_gap_trap_anchor_ask"]     = gap_trap_anchor_ask
        memory["_gap_trap_peak_ask"]       = gap_trap_peak_ask
        memory["gap_trap_active"]          = int(gap_trap_active)
        memory["gap_trap_armed"]           = int(gap_trap_armed)

        return orders, gap_sell_prices

    def compute_orders(
        self,
        state:       TradingState,
        book:        BookSnapshot,
        order_depth: OrderDepth,
        position:    int,
        memory:      Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        self._process_premium_fills(state, memory)

        gap_sell_quotes: List[int] = []
        gap_buy_quotes:  List[int] = []
        memory["_active_gap_sell_quotes"] = []
        memory["_active_gap_buy_quotes"]  = []
        memory["_gap_sell_px"]            = []
        memory["_gap_buy_px"]             = []

        onesided = self._handle_onesided_book(book, position, memory, gap_sell_quotes, gap_buy_quotes)
        if onesided is not None:
            return onesided

        if book.best_bid is not None:
            memory["_last_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_best_ask"] = book.best_ask
            recent_best_asks            = memory.setdefault("_recent_best_asks", [])
            gap_scout_recent_ask_window = int(self.params.get("gap_scout_recent_ask_window", 6))
            recent_best_asks.append(int(book.best_ask))
            if len(recent_best_asks) > gap_scout_recent_ask_window:
                del recent_best_asks[:-gap_scout_recent_ask_window]

        mid   = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        fv    = stats["fair_value"]

        spot = book.microprice if book.microprice is not None else mid
        _, _, _, stretch, trim_reference, entry_reference = (
            self._update_ewma_signals(spot, fv, memory)
        )

        regime = self._compute_regime(state, stats, spot, stretch, book, position, memory)

        bid_price, ask_price = self._compute_quote_prices(book, fv, stats, regime, entry_reference)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        buy_orders, buy_cap, pending_buy, swept_ask_prices = self._buy_takers(
            order_depth, fv, position, buy_cap, regime
        )

        sell_orders, sell_cap, pending_sell = self._sell_takers(
            order_depth, fv, position, sell_cap, regime
        )

        buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode = (
            self._compute_passive_sizes(
                position, buy_cap, sell_cap, pending_buy, pending_sell,
                stats, regime, entry_reference, book, bid_price, ask_price, swept_ask_prices,
            )
        )

        gap_trap_orders, gap_trap_sell_prices = self._gap_trap_quotes(
            book, position, memory, sell_cap, ask_price,
            stats["trend_ticks"], regime["gap_rebuy_mode"],
        )
        gap_sell_quotes.extend(gap_trap_sell_prices)

        orders: List[Order] = buy_orders + sell_orders
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if anchor_buy_size > 0 and anchor_buy_price is not None:
            orders.append(Order(self.product, anchor_buy_price, anchor_buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))
        orders.extend(gap_trap_orders)

        memory["last_bid_price"]       = bid_price
        memory["last_ask_price"]       = ask_price
        memory["entry_reference"]      = entry_reference
        memory["inv_target"]           = regime["inv_target"]
        memory["active_build_target"]  = regime["active_build_target"]
        memory["bullish"]              = int(regime["bullish"])
        memory["build_phase"]          = int(regime["build_phase"])
        memory["on_dip"]               = int(regime["on_dip"])
        memory["chasing"]              = int(regime["chasing"])
        memory["anchor_mode"]          = int(anchor_mode)
        memory["startup_fast_loading"] = int(regime["startup_fast_loading"])
        memory["startup_cold_loading"] = int(regime["startup_cold_loading"])
        memory["pullback_ready"]       = int(regime["current_pullback_ready"])
        memory["pullback_seen"]        = int(regime["pullback_seen"])
        memory["build_release_ready"]  = int(regime["build_release_ready"])
        memory["gap_rebuy_mode"]       = int(regime["gap_rebuy_mode"])
        memory["gap_rebuy_discount"]   = regime["gap_rebuy_discount"]
        memory["trim_quote_mode"]      = int(regime["trim_quote_mode"])
        memory["trim_take_mode"]       = int(regime["trim_take_mode"])
        memory["rebuy_blocked"]        = int(regime["rebuy_blocked"])
        memory["stretch"]              = stretch
        memory["_active_gap_sell_quotes"] = sorted(set(gap_sell_quotes))
        memory["_active_gap_buy_quotes"]  = sorted(set(gap_buy_quotes))
        memory["_gap_sell_px"]            = memory["_active_gap_sell_quotes"]
        memory["_gap_buy_px"]             = memory["_active_gap_buy_quotes"]

        trend_ticks = stats["trend_ticks"]
        gap_trap_armed          = bool(memory.get("gap_trap_armed", 0))
        gap_trap_active         = bool(memory.get("gap_trap_active", 0))
        gap_trap_fragile_streak = int(memory.get("_gap_trap_fragile_streak", 0))
        gap_trap_anchor_ask     = memory.get("_gap_trap_anchor_ask")
        gap_trap_peak_ask       = memory.get("_gap_trap_peak_ask")
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position":              position,
                "trend_ticks":           round(trend_ticks, 2),
                "fair_value":            round(fv, 2),
                "stretch":               round(stretch, 2),
                "trim_ref":              round(trim_reference, 2),
                "entry_ref":             round(entry_reference, 2),
                "inv_target":            regime["inv_target"],
                "active_build_target":   regime["active_build_target"],
                "bullish":               int(regime["bullish"]),
                "build_phase":           int(regime["build_phase"]),
                "on_dip":                int(regime["on_dip"]),
                "chasing":               int(regime["chasing"]),
                "pullback_ready":        int(regime["current_pullback_ready"]),
                "pullback_seen":         int(regime["pullback_seen"]),
                "build_release_ready":   int(regime["build_release_ready"]),
                "gap_rebuy_mode":        int(regime["gap_rebuy_mode"]),
                "gap_rebuy_discount":    round(regime["gap_rebuy_discount"], 2),
                "anchor_mode":           int(anchor_mode),
                "startup_fast_loading":  int(regime["startup_fast_loading"]),
                "startup_cold_loading":  int(regime["startup_cold_loading"]),
                "buy_size":              buy_size,
                "sell_size":             sell_size,
                "anchor_buy_price":      anchor_buy_price,
                "anchor_buy_size":       anchor_buy_size,
                "gap_trap_active":       int(gap_trap_active),
                "gap_trap_armed":        int(gap_trap_armed),
                "gap_trap_fragile_streak": gap_trap_fragile_streak,
                "gap_trap_anchor_ask":   gap_trap_anchor_ask,
                "gap_trap_peak_ask":     gap_trap_peak_ask,
                "trim_quote_mode":       int(regime["trim_quote_mode"]),
                "trim_take_mode":        int(regime["trim_take_mode"]),
                "trim_take_qty":         regime["trim_take_qty"],
                "rebuy_blocked":         int(regime["rebuy_blocked"]),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        stats = memory.get("regression_stats")
        if stats:
            out["reg_fair_value"] = float(stats["fair_value"])
        if memory.get("ewma_fv") is not None:
            out["ewma_fv"] = memory["ewma_fv"]
        if memory.get("short_ema") is not None:
            out["short_ema"] = memory["short_ema"]
        if memory.get("entry_reference") is not None:
            out["entry_reference"] = memory["entry_reference"]
        return out


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v2.py ──────────

class TheoBestCleanGeneralizedV2Strategy(TheoBestCleanGeneralizedStrategy):

    pass


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v3.py ──────────

class TheoBestCleanGeneralizedV3Strategy(TheoBestCleanGeneralizedV2Strategy):

    def _max_inventory_sell_guard_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        guard_position = int(
            self.params.get("max_inventory_sell_guard_position", self.position_limit())
        )
        guard_threshold = float(self.params.get("max_inventory_sell_guard_threshold", 8.0))

        active = (
            best_ask is not None
            and position >= guard_position
            and float(best_ask) < fair_value + guard_threshold
        )

        self._memory["max_inventory_sell_guard_active"] = int(active)
        self._memory["max_inventory_sell_guard_ref"] = fair_value + guard_threshold
        return active

    def _compute_passive_sizes(
        self,
        position: int,
        buy_cap: int,
        sell_cap: int,
        pending_buy: int,
        pending_sell: int,
        stats,
        regime,
        entry_reference: float,
        book,
        bid_price: int,
        ask_price: int,
        buy_taker_prices: Set[int],
    ) -> Tuple[int, int, Optional[int], int, int, bool]:
        buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode = super()._compute_passive_sizes(
            position,
            buy_cap,
            sell_cap,
            pending_buy,
            pending_sell,
            stats,
            regime,
            entry_reference,
            book,
            bid_price,
            ask_price,
            buy_taker_prices,
        )

        if self._max_inventory_sell_guard_active(
            position=position,
            best_ask=book.best_ask,
            fair_value=float(stats["fair_value"]),
        ):
            sell_size = 0

        return buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v4.py ──────────

class TheoBestCleanGeneralizedV4Strategy(TheoBestCleanGeneralizedV3Strategy):

    def _reserve_inventory_size(self) -> int:
        return max(0, int(self.params.get("dump_reserve_inventory", 3)))

    def _reserve_normal_inventory_cap(self) -> int:
        return max(0, self.position_limit() - self._reserve_inventory_size())

    def _dump_reserve_release_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        reserve_size = self._reserve_inventory_size()
        reserve_threshold = float(self.params.get("dump_reserve_release_threshold", 3.0))
        reserve_min_position = int(
            self.params.get(
                "dump_reserve_release_min_position",
                self._reserve_normal_inventory_cap(),
            )
        )

        active = (
            reserve_size > 0
            and best_ask is not None
            and position >= reserve_min_position
            and float(best_ask) <= fair_value - reserve_threshold
        )

        self._memory["dump_reserve_release_active"] = int(active)
        self._memory["dump_reserve_release_ref"] = fair_value - reserve_threshold
        self._memory["dump_reserve_normal_cap"] = self._reserve_normal_inventory_cap()
        return active

    def _reserve_buy_room(
        self,
        *,
        position: int,
        pending_buy: int,
        release_active: bool,
    ) -> int:
        target_cap = self.position_limit() if release_active else self._reserve_normal_inventory_cap()
        return max(0, target_cap - position - pending_buy)

    def _buy_takers(
        self,
        order_depth,
        fv: float,
        position: int,
        buy_cap: int,
        regime,
    ):
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        release_active = self._dump_reserve_release_active(
            position=position,
            best_ask=best_ask,
            fair_value=float(fv),
        )
        capped_buy_cap = min(
            buy_cap,
            self._reserve_buy_room(
                position=position,
                pending_buy=0,
                release_active=release_active,
            ),
        )
        if capped_buy_cap <= 0:
            return [], 0, 0, set()

        capped_regime = dict(regime)
        capped_regime["buy_take_cap"] = min(int(regime["buy_take_cap"]), capped_buy_cap)
        return super()._buy_takers(order_depth, fv, position, capped_buy_cap, capped_regime)

    def _compute_passive_sizes(
        self,
        position: int,
        buy_cap: int,
        sell_cap: int,
        pending_buy: int,
        pending_sell: int,
        stats,
        regime,
        entry_reference: float,
        book,
        bid_price: int,
        ask_price: int,
        buy_taker_prices: Set[int],
    ) -> Tuple[int, int, Optional[int], int, int, bool]:
        release_active = self._dump_reserve_release_active(
            position=position,
            best_ask=book.best_ask,
            fair_value=float(stats["fair_value"]),
        )
        capped_buy_cap = min(
            buy_cap,
            self._reserve_buy_room(
                position=position,
                pending_buy=pending_buy,
                release_active=release_active,
            ),
        )

        return super()._compute_passive_sizes(
            position,
            capped_buy_cap,
            sell_cap,
            pending_buy,
            pending_sell,
            stats,
            regime,
            entry_reference,
            book,
            bid_price,
            ask_price,
            buy_taker_prices,
        )


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v5.py ──────────

class TheoBestCleanGeneralizedV5Strategy(TheoBestCleanGeneralizedV4Strategy):

    def _buy_gap_trap_quotes(
        self,
        book,
        position: int,
        memory: Dict[str, Any],
        buy_cap: int,
        active_bid_price: int,
        trend_ticks: float,
        gap_rebuy_mode: bool,
    ) -> Tuple[List[Order], List[int]]:
        orders: List[Order] = []
        gap_buy_prices: List[int] = []
        if buy_cap <= 0 or book.best_bid is None:
            memory["buy_gap_trap_active"] = 0
            return orders, gap_buy_prices

        empty_side_shift = int(self.params.get("empty_side_shift", 85))

        buy_gap_trap_fragile_streak = int(memory.get("_buy_gap_trap_fragile_streak", 0))
        buy_gap_trap_clear_streak = int(memory.get("_buy_gap_trap_clear_streak", 0))
        buy_gap_trap_anchor_bid = memory.get("_buy_gap_trap_anchor_bid")
        buy_gap_trap_trough_bid = memory.get("_buy_gap_trap_trough_bid")

        buy_gap_trap_floor_position = int(
            self.params.get(
                "buy_gap_trap_floor_position",
                self._reserve_normal_inventory_cap(),
            )
        )
        buy_gap_trap_arm_streak = int(self.params.get("buy_gap_trap_arm_streak", 2))
        buy_gap_trap_clear_after = int(self.params.get("buy_gap_trap_clear_after", 4))
        buy_gap_trap_min_trend = float(self.params.get("buy_gap_trap_min_trend", 0.0))
        buy_gap_trap_min_gap = int(self.params.get("buy_gap_trap_min_gap", 3))
        buy_gap_trap_top_bid_max = int(self.params.get("buy_gap_trap_top_bid_max", 12))
        buy_gap_trap_max_imbalance = float(self.params.get("buy_gap_trap_max_imbalance", 0.05))
        buy_gap_trap_recent_bid_window = int(self.params.get("buy_gap_trap_recent_bid_window", 12))
        buy_gap_trap_fragile_bid_window = int(self.params.get("buy_gap_trap_fragile_bid_window", 6))
        buy_gap_trap_base_size = int(
            self.params.get(
                "buy_gap_trap_base_size",
                max(1, min(2, self._reserve_inventory_size())),
            )
        )
        buy_gap_trap_premium_size_limit = int(
            self.params.get(
                "buy_gap_trap_premium_size",
                max(0, self._reserve_inventory_size() - buy_gap_trap_base_size),
            )
        )
        buy_gap_trap_premium_streak = int(self.params.get("buy_gap_trap_premium_streak", 2))
        buy_gap_trap_premium_extra = int(self.params.get("buy_gap_trap_premium_extra", 2))

        bid_gap_fragile = len(book.bid_levels) == 1
        if len(book.bid_levels) >= 2:
            bid_gap_fragile = bid_gap_fragile or (
                book.bid_levels[0][0] - book.bid_levels[1][0] >= buy_gap_trap_min_gap
            )
        bid_size_fragile = book.best_bid_volume > 0 and book.best_bid_volume <= buy_gap_trap_top_bid_max
        imbalance_supportive = book.imbalance is None or book.imbalance <= buy_gap_trap_max_imbalance
        bid_side_fragile = bid_gap_fragile or (bid_size_fragile and imbalance_supportive)

        trap_recent_bids = memory.setdefault("_buy_gap_trap_recent_bids", [])
        trap_recent_bids.append(int(book.best_bid))
        if len(trap_recent_bids) > buy_gap_trap_recent_bid_window:
            del trap_recent_bids[:-buy_gap_trap_recent_bid_window]

        trap_fragile_bids = memory.setdefault("_buy_gap_trap_fragile_bids", [])
        if bid_side_fragile:
            trap_fragile_bids.append(int(book.best_bid))
            if len(trap_fragile_bids) > buy_gap_trap_fragile_bid_window:
                del trap_fragile_bids[:-buy_gap_trap_fragile_bid_window]
        else:
            trap_fragile_bids[:] = []

        trap_armable = (
            trend_ticks >= buy_gap_trap_min_trend
            and not gap_rebuy_mode
            and position >= buy_gap_trap_floor_position
            and buy_cap > 0
        )

        if trap_armable and bid_side_fragile:
            buy_gap_trap_fragile_streak += 1
            buy_gap_trap_clear_streak = 0
        elif buy_gap_trap_anchor_bid is not None:
            buy_gap_trap_clear_streak += 1
            buy_gap_trap_fragile_streak = max(0, buy_gap_trap_fragile_streak - 1)
        else:
            buy_gap_trap_fragile_streak = 0
            buy_gap_trap_clear_streak = 0

        if (
            buy_gap_trap_anchor_bid is None
            and trap_armable
            and buy_gap_trap_fragile_streak >= buy_gap_trap_arm_streak
            and trap_recent_bids
        ):
            buy_gap_trap_anchor_bid = max(trap_recent_bids)
            buy_gap_trap_trough_bid = min(trap_fragile_bids) if trap_fragile_bids else int(book.best_bid)

        if buy_gap_trap_anchor_bid is not None:
            if not trap_armable or buy_gap_trap_clear_streak >= buy_gap_trap_clear_after:
                buy_gap_trap_anchor_bid = None
                buy_gap_trap_trough_bid = None
                buy_gap_trap_fragile_streak = 0
                buy_gap_trap_clear_streak = 0
            else:
                if trap_recent_bids:
                    buy_gap_trap_anchor_bid = max(int(buy_gap_trap_anchor_bid), max(trap_recent_bids))
                if trap_fragile_bids:
                    latest_trough = min(trap_fragile_bids)
                    buy_gap_trap_trough_bid = min(
                        int(buy_gap_trap_trough_bid or latest_trough),
                        latest_trough,
                    )

        buy_gap_trap_buy_price = None
        buy_gap_trap_buy_size = 0
        buy_gap_trap_premium_price = None
        buy_gap_trap_premium_size = 0
        buy_gap_trap_active = False
        buy_gap_trap_armed = False

        if buy_gap_trap_anchor_bid is not None:
            buy_gap_trap_armed = True
            candidate_buy_gap_trap = int(buy_gap_trap_anchor_bid) - empty_side_shift
            if candidate_buy_gap_trap < active_bid_price:
                buy_gap_trap_buy_price = candidate_buy_gap_trap
                buy_gap_trap_buy_size = min(buy_cap, buy_gap_trap_base_size)
                buy_gap_trap_active = buy_gap_trap_buy_size > 0

            if (
                buy_gap_trap_trough_bid is not None
                and buy_gap_trap_fragile_streak >= buy_gap_trap_premium_streak
                and buy_cap > buy_gap_trap_buy_size
            ):
                candidate_buy_gap_premium = min(
                    (buy_gap_trap_buy_price or active_bid_price) - buy_gap_trap_premium_extra,
                    int(buy_gap_trap_trough_bid) - empty_side_shift - buy_gap_trap_premium_extra,
                )
                if candidate_buy_gap_premium < (buy_gap_trap_buy_price or active_bid_price):
                    buy_gap_trap_premium_price = candidate_buy_gap_premium
                    buy_gap_trap_premium_size = min(
                        max(0, buy_cap - buy_gap_trap_buy_size),
                        buy_gap_trap_premium_size_limit,
                    )
                    buy_gap_trap_active = buy_gap_trap_active or buy_gap_trap_premium_size > 0

        if buy_gap_trap_buy_size > 0 and buy_gap_trap_buy_price is not None:
            orders.append(Order(self.product, buy_gap_trap_buy_price, buy_gap_trap_buy_size))
            gap_buy_prices.append(buy_gap_trap_buy_price)
        if buy_gap_trap_premium_size > 0 and buy_gap_trap_premium_price is not None:
            orders.append(Order(self.product, buy_gap_trap_premium_price, buy_gap_trap_premium_size))
            gap_buy_prices.append(buy_gap_trap_premium_price)

        memory["_buy_gap_trap_fragile_streak"] = buy_gap_trap_fragile_streak
        memory["_buy_gap_trap_clear_streak"] = buy_gap_trap_clear_streak
        memory["_buy_gap_trap_anchor_bid"] = buy_gap_trap_anchor_bid
        memory["_buy_gap_trap_trough_bid"] = buy_gap_trap_trough_bid
        memory["buy_gap_trap_active"] = int(buy_gap_trap_active)
        memory["buy_gap_trap_armed"] = int(buy_gap_trap_armed)

        return orders, gap_buy_prices

    def compute_orders(
        self,
        state: TradingState,
        book,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders, conversions = super().compute_orders(state, book, order_depth, position, memory)

        if book.best_bid is None or book.best_ask is None:
            return orders, conversions

        buy_cap_remaining = self.buy_capacity(position) - sum(max(order.quantity, 0) for order in orders)
        if buy_cap_remaining <= 0:
            return orders, conversions

        stats = memory.get("regression_stats", {})
        trend_ticks = float(stats.get("trend_ticks", 0.0))
        active_bid_price = int(memory.get("last_bid_price", book.best_bid))
        gap_rebuy_mode = bool(memory.get("gap_rebuy_mode", 0))

        buy_gap_orders, buy_gap_prices = self._buy_gap_trap_quotes(
            book=book,
            position=position,
            memory=memory,
            buy_cap=buy_cap_remaining,
            active_bid_price=active_bid_price,
            trend_ticks=trend_ticks,
            gap_rebuy_mode=gap_rebuy_mode,
        )
        if not buy_gap_orders:
            return orders, conversions

        orders.extend(buy_gap_orders)
        active_gap_buy_quotes = {int(p) for p in memory.get("_active_gap_buy_quotes", [])}
        active_gap_buy_quotes.update(buy_gap_prices)
        memory["_active_gap_buy_quotes"] = sorted(active_gap_buy_quotes)
        memory["_gap_buy_px"] = memory["_active_gap_buy_quotes"]
        return orders, conversions


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v6.py ──────────

class TheoBestCleanGeneralizedV6Strategy(TheoBestCleanGeneralizedV5Strategy):

    def _apply_startup_price_improvement(
        self,
        *,
        state,
        stats: Dict[str, float],
        stretch: float,
        book,
        position: int,
        memory: Dict[str, Any],
        regime: Dict[str, Any],
    ) -> Dict[str, Any]:
        tuned = dict(regime)

        reserve_normal_cap = self._reserve_normal_inventory_cap()
        improvement_start_position = int(
            self.params.get(
                "startup_price_improve_start_position",
                max(0, reserve_normal_cap - 21),
            )
        )
        improvement_holdback = int(self.params.get("startup_price_improve_holdback", 8))
        improvement_hot_threshold = float(self.params.get("startup_price_improve_hot_threshold", 4.0))
        improvement_release_threshold = float(
            self.params.get("startup_price_improve_release_threshold", 1.5)
        )
        improvement_hot_stretch = float(self.params.get("startup_price_improve_hot_stretch", 0.75))
        improvement_take_cap = int(self.params.get("startup_price_improve_take_cap", 3))
        improvement_passive_buy_cap = int(
            self.params.get("startup_price_improve_passive_buy_cap", 4)
        )
        improvement_anchor_extra_spread = float(
            self.params.get("startup_price_improve_anchor_extra_spread", 1.0)
        )
        improvement_end_ts = int(
            self.params.get(
                "startup_price_improve_end_ts",
                self.params.get("startup_delayed_finish_ts", 3000),
            )
        )

        best_ask = book.best_ask
        ask_richness = 0.0 if best_ask is None else float(best_ask) - float(stats["fair_value"])
        release_ready = (
            tuned["on_dip"]
            or tuned["current_pullback_ready"]
            or ask_richness <= improvement_release_threshold
            or float(stats["residual_z"]) <= 0.0
        )

        improvement_active = (
            tuned["build_phase"]
            and tuned["startup_window_active"]
            and not tuned["gap_rebuy_mode"]
            and int(state.timestamp) <= improvement_end_ts
            and position >= improvement_start_position
            and best_ask is not None
            and ask_richness >= improvement_hot_threshold
            and stretch >= improvement_hot_stretch
            and not release_ready
        )

        if improvement_active:
            improved_target_cap = max(
                improvement_start_position,
                reserve_normal_cap - improvement_holdback,
            )
            tuned["active_build_target"] = min(
                int(tuned["active_build_target"]),
                improved_target_cap,
            )
            tuned["buy_take_cap"] = min(int(tuned["buy_take_cap"]), improvement_take_cap)
            tuned["startup_fast_passive_buy"] = min(
                int(tuned["startup_fast_passive_buy"]),
                improvement_passive_buy_cap,
            )
            tuned["startup_cold_passive_buy"] = min(
                int(tuned["startup_cold_passive_buy"]),
                improvement_passive_buy_cap,
            )
            tuned["startup_anchor_bid_spread"] = float(tuned["startup_anchor_bid_spread"]) + improvement_anchor_extra_spread

        memory["startup_price_improve_active"] = int(improvement_active)
        memory["startup_price_improve_richness"] = ask_richness
        memory["startup_price_improve_release_ready"] = int(release_ready)
        memory["startup_price_improve_cap"] = (
            max(improvement_start_position, reserve_normal_cap - improvement_holdback)
            if improvement_active
            else int(tuned["active_build_target"])
        )
        return tuned

    def _compute_regime(
        self,
        state,
        stats: Dict[str, float],
        spot: float,
        stretch: float,
        book,
        position: int,
        memory: Dict[str, Any],
    ) -> Dict[str, Any]:
        regime = super()._compute_regime(state, stats, spot, stretch, book, position, memory)
        return self._apply_startup_price_improvement(
            state=state,
            stats=stats,
            stretch=stretch,
            book=book,
            position=position,
            memory=memory,
            regime=regime,
        )


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v7.py ──────────

class TheoBestCleanGeneralizedV7Strategy(TheoBestCleanGeneralizedV6Strategy):

    def _apply_startup_recent_low_patience(
        self,
        *,
        state,
        stats: Dict[str, float],
        stretch: float,
        book,
        position: int,
        memory: Dict[str, Any],
        regime: Dict[str, Any],
    ) -> Dict[str, Any]:
        tuned = dict(regime)

        best_ask = book.best_ask
        recent_window = int(self.params.get("startup_recent_low_window", 12))
        recent_asks = memory.setdefault("startup_recent_best_asks", [])
        if best_ask is not None:
            recent_asks.append(int(best_ask))
            if len(recent_asks) > recent_window:
                del recent_asks[:-recent_window]

        recent_low = min(recent_asks) if recent_asks else best_ask
        if recent_low is None or best_ask is None:
            memory["startup_recent_low_patience_active"] = 0
            return tuned

        reserve_normal_cap = self._reserve_normal_inventory_cap()
        patience_start_position = int(
            self.params.get("startup_recent_low_start_position", max(0, reserve_normal_cap - 29))
        )
        patience_holdback = int(self.params.get("startup_recent_low_holdback", 6))
        patience_gap_threshold = float(self.params.get("startup_recent_low_gap_threshold", 2.0))
        patience_release_gap = float(self.params.get("startup_recent_low_release_gap", 0.5))
        patience_hot_stretch = float(self.params.get("startup_recent_low_hot_stretch", 0.4))
        patience_take_cap = int(self.params.get("startup_recent_low_take_cap", 2))
        patience_passive_buy_cap = int(self.params.get("startup_recent_low_passive_buy_cap", 3))
        patience_anchor_extra_spread = float(
            self.params.get("startup_recent_low_anchor_extra_spread", 1.0)
        )
        patience_buy_edge_floor = float(self.params.get("startup_recent_low_buy_edge_floor", 1.0))
        patience_end_ts = int(
            self.params.get(
                "startup_recent_low_end_ts",
                self.params.get("startup_delayed_finish_ts", 3000),
            )
        )

        recent_gap = float(best_ask) - float(recent_low)
        release_ready = (
            tuned["on_dip"]
            or tuned["current_pullback_ready"]
            or recent_gap <= patience_release_gap
            or float(stats["residual_z"]) <= 0.0
        )
        patience_active = (
            tuned["build_phase"]
            and tuned["startup_window_active"]
            and not tuned["gap_rebuy_mode"]
            and int(state.timestamp) <= patience_end_ts
            and position >= patience_start_position
            and recent_gap >= patience_gap_threshold
            and stretch >= patience_hot_stretch
            and not release_ready
        )

        if patience_active:
            patience_cap = max(patience_start_position, reserve_normal_cap - patience_holdback)
            tuned["active_build_target"] = min(int(tuned["active_build_target"]), patience_cap)
            tuned["buy_take_cap"] = min(int(tuned["buy_take_cap"]), patience_take_cap)
            tuned["buy_edge"] = max(float(tuned["buy_edge"]), patience_buy_edge_floor)
            tuned["startup_fast_passive_buy"] = min(
                int(tuned["startup_fast_passive_buy"]),
                patience_passive_buy_cap,
            )
            tuned["startup_cold_passive_buy"] = min(
                int(tuned["startup_cold_passive_buy"]),
                patience_passive_buy_cap,
            )
            tuned["startup_anchor_bid_spread"] = float(tuned["startup_anchor_bid_spread"]) + patience_anchor_extra_spread

        memory["startup_recent_low_patience_active"] = int(patience_active)
        memory["startup_recent_low_gap"] = recent_gap
        memory["startup_recent_low_value"] = int(recent_low)
        memory["startup_recent_low_release_ready"] = int(release_ready)
        return tuned

    def _compute_regime(
        self,
        state,
        stats: Dict[str, float],
        spot: float,
        stretch: float,
        book,
        position: int,
        memory: Dict[str, Any],
    ) -> Dict[str, Any]:
        regime = super()._compute_regime(state, stats, spot, stretch, book, position, memory)
        return self._apply_startup_recent_low_patience(
            state=state,
            stats=stats,
            stretch=stretch,
            book=book,
            position=position,
            memory=memory,
            regime=regime,
        )


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v8.py ──────────

class TheoBestCleanGeneralizedV8Strategy(TheoBestCleanGeneralizedV7Strategy):

    def _hard_reserve_release_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        del position, best_ask, fair_value
        self._memory["dump_reserve_release_active"] = 0
        self._memory["dump_reserve_release_ref"] = None
        self._memory["dump_reserve_normal_cap"] = self._reserve_normal_inventory_cap()
        return False

    def _dump_reserve_release_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        return self._hard_reserve_release_active(
            position=position,
            best_ask=best_ask,
            fair_value=fair_value,
        )

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'INTARIAN_PEPPER_ROOT': {'aggravate_cut': 0.04,
                          'ask_gap_quote_size': 8,
                          'ask_gap_sell_enable_position': 75,
                          'ask_spread_bull': 9.0,
                          'bid_spread_bull': 1.0,
                          'block_size': 200,
                          'bootstrap_confidence': 0.55,
                          'bull_threshold': 1.0,
                          'buy_gap_trap_arm_streak': 2,
                          'buy_gap_trap_base_size': 3,
                          'buy_gap_trap_clear_after': 4,
                          'buy_gap_trap_floor_position': 75,
                          'buy_gap_trap_fragile_bid_window': 6,
                          'buy_gap_trap_max_imbalance': 0.05,
                          'buy_gap_trap_min_gap': 3,
                          'buy_gap_trap_min_trend': 0.0,
                          'buy_gap_trap_premium_extra': 2,
                          'buy_gap_trap_premium_size': 2,
                          'buy_gap_trap_premium_streak': 2,
                          'buy_gap_trap_recent_bid_window': 12,
                          'buy_gap_trap_top_bid_max': 12,
                          'chase_threshold': 1.25,
                          'cheap_buy_boost_per_z': 0.18,
                          'cheap_residual_z': 0.9,
                          'dip_threshold': 1.0,
                          'dump_reserve_inventory': 5,
                          'dump_reserve_release_min_position': 77,
                          'dump_reserve_release_threshold': 3.0,
                          'empty_side_shift': 85,
                          'fastfill_buy_edge_boost': 0.0,
                          'fastfill_deep_take_guard_end_ts': 1000,
                          'fastfill_deep_take_max_gap_ticks': 1,
                          'fastfill_end_ts': 12000,
                          'fastfill_min_passive_buy': 10,
                          'fastfill_target': 80,
                          'fv_alpha': 0.05,
                          'gap_fill_min_premium': 35,
                          'gap_rebuy_buy_edge': -10.0,
                          'gap_rebuy_min_discount': 20.0,
                          'gap_rebuy_passive_buy': 6,
                          'gap_rebuy_take_cap': 8,
                          'gap_rebuy_window': 2500,
                          'gap_trap_arm_streak': 2,
                          'gap_trap_base_size': 4,
                          'gap_trap_clear_after': 4,
                          'gap_trap_floor_position': 73,
                          'gap_trap_fragile_ask_window': 6,
                          'gap_trap_min_gap': 3,
                          'gap_trap_min_imbalance': -0.05,
                          'gap_trap_min_trend': 0.0,
                          'gap_trap_premium_extra': 2,
                          'gap_trap_premium_size': 3,
                          'gap_trap_premium_streak': 2,
                          'gap_trap_recent_ask_window': 12,
                          'gap_trap_top_ask_max': 12,
                          'hold_sell_offset': 0,
                          'hold_sell_size': 0,
                          'last_ts_value': 999900,
                          'log_flush_ts': 1000,
                          'maker_size': 80,
                          'max_bid_extra_ticks': 2,
                          'max_inventory_sell_guard_position': 80,
                          'max_inventory_sell_guard_threshold': 0.0,
                          'min_completed_blocks': 5,
                          'neut_spread_ask': 5.0,
                          'neut_spread_bid': 2.0,
                          'one_sided_target_gap': 24,
                          'position_limit': 80,
                          'rebuy_block_ticks': 25,
                          'reg_horizon': 25,
                          'reg_r2_cap': 0.98,
                          'reg_r2_floor': 0.85,
                          'reg_residual_reversion': 0.25,
                          'reg_rmse_floor': 1.0,
                          'resid_inv_per_z': 14.0,
                          'rich_residual_z': 1.0,
                          'rich_sell_boost_per_z': 0.14,
                          'seed_slope': 0.1015,
                          'short_alpha': 0.22,
                          'slope_window': 20,
                          'startup_anchor_bid_spread': 1.0,
                          'startup_anchor_gap_ticks': 1,
                          'startup_anchor_size': 4,
                          'startup_chase_passive_buy': 1,
                          'startup_chase_take_cap': 1,
                          'startup_chase_take_edge': 4.0,
                          'startup_cold_join_ticks': 0,
                          'startup_cold_passive_buy': 3,
                          'startup_cold_take_cap': 4,
                          'startup_cold_take_edge': 3.0,
                          'startup_delayed_finish_ts': 3000,
                          'startup_dip_take_edge_boost': 1.0,
                          'startup_end_ts': 30000,
                          'startup_fast_passive_buy': 8,
                          'startup_fast_take_cap': 12,
                          'startup_fast_target': 64,
                          'startup_post_pullback_target': 72,
                          'startup_pre_pullback_target': 48,
                          'startup_price_improve_anchor_extra_spread': 1.0,
                          'startup_price_improve_end_ts': 3000,
                          'startup_price_improve_holdback': 8,
                          'startup_price_improve_hot_stretch': 0.75,
                          'startup_price_improve_hot_threshold': 4.0,
                          'startup_price_improve_passive_buy_cap': 4,
                          'startup_price_improve_release_threshold': 1.5,
                          'startup_price_improve_start_position': 56,
                          'startup_price_improve_take_cap': 3,
                          'startup_pullback_ticks': 2.0,
                          'startup_recent_low_anchor_extra_spread': 1.0,
                          'startup_recent_low_buy_edge_floor': 1.0,
                          'startup_recent_low_end_ts': 3000,
                          'startup_recent_low_gap_threshold': 2.0,
                          'startup_recent_low_holdback': 6,
                          'startup_recent_low_hot_stretch': 0.4,
                          'startup_recent_low_passive_buy_cap': 3,
                          'startup_recent_low_release_gap': 0.5,
                          'startup_recent_low_start_position': 48,
                          'startup_recent_low_take_cap': 2,
                          'startup_recent_low_window': 12,
                          'startup_release_stretch': 1.0,
                          'startup_release_take_cap': 8,
                          'startup_target': 80,
                          'strategy': 'theo_best_clean_generalized_v8',
                          'strong_trend_ticks': 0.9,
                          'take_buy_edge_bull': -8.0,
                          'take_buy_edge_neut': 2.0,
                          'take_sell_edge_neut': 2.0,
                          'target_gap_scale': 26.0,
                          'tighten_ticks': 1,
                          'trend_buy_boost_per_tick': 0.24,
                          'trend_inv_per_tick': 16.0,
                          'trend_inventory_cap': 80,
                          'trend_sell_boost_per_tick': 0.2,
                          'trim_ask_local_edge': 0.0,
                          'trim_cooldown_ticks': 20,
                          'trim_extension_threshold': 0.75,
                          'trim_floor_position': 78,
                          'trim_reference_slope_weight': 0.15,
                          'trim_sell_size': 1,
                          'trim_signal_edge': 1.0,
                          'trim_start_position': 79,
                          'trim_take_edge': 2.0,
                          'trim_take_position': 80,
                          'trim_take_sell_size': 1,
                          'trim_take_stretch': 999.0,
                          'ts_increment': 100,
                          'unwind_take_edge': 10.0,
                          'very_strong_trend_ticks': 1.6}}

STRATEGY_CLASSES = {"theo_best_clean_generalized_v8": TheoBestCleanGeneralizedV8Strategy}

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