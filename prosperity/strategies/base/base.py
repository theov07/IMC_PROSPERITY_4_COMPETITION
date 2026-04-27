"""Base strategy interface for all trading strategies."""

from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot, snapshot_from_order_depth


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
        self._memory = memory  # available to all helper methods via self._memory

        order_depth = state.order_depths.get(self.product)
        if order_depth is None:
            return [], 0

        position = state.position.get(self.product, 0)
        book = snapshot_from_order_depth(self.product, order_depth)

        orders, conversions = self.compute_orders(
            state=state,
            book=book,
            order_depth=order_depth,
            position=position,
            memory=memory,
        )

        # Alpha overlays (opt-in via params; no-op when params absent):
        # 1a. OBI passive bias (shift quote prices based on L3 OBI — captures alpha without spread cost)
        orders = self._apply_obi_passive_bias(state, position, orders, book, memory)
        # 1b. OBI taker overlay (directional alpha from L3 book imbalance, 88% hit rate)
        orders = self._apply_obi_taker_overlay(state, position, orders, book, memory)

        # Risk management filters (all opt-in via params; no-op when params absent):
        # 2. Intraday stop-loss (PnL drawdown trigger — robust, not time-based)
        orders = self._apply_intraday_stop_loss(state, position, orders, book, memory)
        # 3. Conditional aggressive unwind (VWAP signal trigger — robust, not time-based).
        orders = self._apply_conditional_unwind(state, position, orders, book, memory)
        # 4. End-of-day inventory unwind (time-based — DISABLED by default, overfits)
        orders = self._apply_eod_unwind(state, position, orders, book)

        return orders, conversions

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
    # Shared price utilities (call from any strategy)
    # ------------------------------------------------------------------
    def _microprice(self, book: "BookSnapshot") -> float:
        """Volume-weighted microprice using all available book levels.

        bid_vwap = Σ(price × vol) / Σvol  across all bid levels
        ask_vwap = same for asks
        microprice = (bid_vwap × ask_total + ask_vwap × bid_total) / (bid_total + ask_total)

        One side empty OR both sides empty → returns the previous microprice
        stored in self._memory["_microprice_last"] (or 0.0 on the very first tick).

        Stores result in self._memory["_microprice_last"].
        Requires self._memory to be set (done automatically by on_tick).
        """
        bid_total = sum(v for _, v in book.bid_levels)
        ask_total = sum(v for _, v in book.ask_levels)

        prev = self._memory.get("_microprice_last", 0.0)

        if bid_total == 0 or ask_total == 0:
            # One or both sides empty: can't compute a meaningful cross-side price
            return float(prev)

        bid_vwap = sum(p * v for p, v in book.bid_levels) / bid_total
        ask_vwap = sum(p * v for p, v in book.ask_levels) / ask_total
        result = (bid_vwap * ask_total + ask_vwap * bid_total) / (bid_total + ask_total)

        self._memory["_microprice_last"] = result
        return result

    def _smooth_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        """EWMA smoother for any price series (mid, microprice, etc.).

        Params read from self.params:
          mid_smooth_window    — rolling window size (default 20; 0 = disabled)
          mid_smooth_half_life — EMA half-life in ticks (default window/2)

        Stores in memory: ``mid_smooth_buf``, ``mid_smoothed``.
        Returns the smoothed value (or the raw input when window <= 0 or too few samples).
        """
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
        return not bool(os.environ.get("INTERNAL_BACKTEST"))

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
        """Accumulate a taker fill and flush when the buffer is full enough.

        Flush conditions (in priority order):
          1. Deferred flag was set last tick → flush now.
          2. Timestamp is the second-to-last of the day → flush as end-of-day cleanup.
          3. Buffer reached 20 fills AND we are NOT at a quote-flush timestamp → flush.
          4. Buffer reached 20 fills AND we ARE at a quote-flush timestamp → set deferred
             flag; the flush will fire on the very next tick instead.

        Log format emitted to stdout:
          {"product": "...", "trace": "taker_fills", "chunk_end": ts,
           "log": [[ts, side, price, qty], ...]}           # regular taker
           "log": [[ts, side, price, qty, 1], ...]}         # gap exploit (5th element=1)
        """
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

    # ------------------------------------------------------------------
    # End-of-day inventory unwind (R4 D3 crash protection)
    # ------------------------------------------------------------------
    def _apply_eod_unwind(
        self,
        state: TradingState,
        position: int,
        orders: List[Order],
        book: BookSnapshot,
    ) -> List[Order]:
        """Force inventory toward 0 in the last X% of the day.

        Params (read from self.params; all optional, defaults disable behavior):
          eod_unwind_start_pct      : start unwinding at this fraction of day (0.85 = last 15%)
          eod_unwind_aggressive_pct : at this fraction, switch to aggressive taker (0.95)
          eod_unwind_full_flat_pct  : at this fraction, force position toward 0 (0.99)
          last_ts_value             : last timestamp of the day (default 999900)

        Behavior:
          - progress < eod_unwind_start_pct: no change to orders.
          - eod_start <= progress < eod_aggressive: drop orders that increase |position|.
          - eod_aggressive <= progress: drop increasing orders + add taker to reduce position
            toward target (target shrinks linearly to 0 by eod_full_flat).
        """
        eod_start = float(self.params.get("eod_unwind_start_pct", 0.0))
        if eod_start <= 0 or eod_start >= 1.0:
            return orders  # disabled

        last_ts = float(self.params.get("last_ts_value", 999900))
        progress = float(state.timestamp) / max(last_ts, 1.0)
        if progress < eod_start:
            return orders

        eod_agg = float(self.params.get("eod_unwind_aggressive_pct", 0.95))
        eod_full = float(self.params.get("eod_unwind_full_flat_pct", 0.99))

        # Target position: linear ramp from `position` at progress=eod_start
        # down to 0 at progress=eod_full.
        if progress >= eod_full:
            target_pos = 0
        else:
            ramp = (progress - eod_start) / max(eod_full - eod_start, 1e-9)
            target_pos = int(round(position * (1.0 - ramp)))

        # Filter: drop any order that grows |position| (we always want to shrink in EOD)
        filtered: List[Order] = []
        for o in orders:
            new_pos = position + o.quantity
            if abs(new_pos) > abs(position):
                continue  # would grow inventory — drop
            filtered.append(o)

        # Aggressive phase: if position is still away from target, add a taker order
        delta = target_pos - position
        if progress >= eod_agg and delta != 0:
            if delta > 0 and book.best_ask is not None:
                # Need to BUY — take the ask
                avail = book.best_ask_volume or abs(delta)
                qty = min(int(delta), int(avail))
                if qty > 0:
                    filtered.append(Order(self.product, int(book.best_ask), qty))
            elif delta < 0 and book.best_bid is not None:
                # Need to SELL — take the bid
                avail = book.best_bid_volume or abs(delta)
                qty = max(int(delta), -int(avail))
                if qty < 0:
                    filtered.append(Order(self.product, int(book.best_bid), qty))

        return filtered

    # ------------------------------------------------------------------
    # Intraday stop-loss (flatten when peak-to-current PnL drawdown exceeds threshold)
    # Activates ONLY on outlier days — robust, not time-based.
    # ------------------------------------------------------------------
    def _apply_intraday_stop_loss(
        self,
        state: TradingState,
        position: int,
        orders: List[Order],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> List[Order]:
        """Flatten position when intraday PnL drawdown from peak exceeds limit.

        Params:
          stop_loss_drawdown_pnl  : if (peak_pnl - current_pnl) > this, flatten (default 0 = disabled)
          stop_loss_min_peak      : minimum peak PnL before stop-loss can fire (default 5000)

        Approximate per-product PnL using mark-to-market with mid price.
        Stop-loss state stored in memory: _peak_pnl, _stop_triggered.
        """
        threshold = float(self.params.get("stop_loss_drawdown_pnl", 0.0))
        if threshold <= 0:
            return orders  # disabled

        min_peak = float(self.params.get("stop_loss_min_peak", 5000.0))

        # Approximate current PnL from cumulative trade history
        # We don't have direct PnL access here, so use a proxy:
        # cumulative cash flow + current position * mid
        cum_cash = memory.get("_stop_cum_cash", 0.0)
        # Track prior position to compute realized P&L from fills
        prev_pos = memory.get("_stop_prev_pos", 0)
        # Use last mid as fill price proxy (approximate; actual fills aren't available here)
        mid = book.mid_price
        if mid is None:
            mid = book.best_bid or book.best_ask or 0
        # Compute fill cash since last tick
        if prev_pos != position:
            # Approximation: assume fills happened at current mid
            cum_cash -= float(position - prev_pos) * float(mid)
        # Current marked PnL = cum_cash + position * mid
        current_pnl = cum_cash + float(position) * float(mid)
        memory["_stop_cum_cash"] = cum_cash
        memory["_stop_prev_pos"] = position
        memory["_stop_current_pnl"] = current_pnl

        peak_pnl = float(memory.get("_stop_peak_pnl", 0.0))
        if current_pnl > peak_pnl:
            peak_pnl = current_pnl
        memory["_stop_peak_pnl"] = peak_pnl

        # Already triggered? Stay flattened for the rest of the day
        triggered = bool(memory.get("_stop_triggered", False))

        if not triggered:
            drawdown = peak_pnl - current_pnl
            if peak_pnl >= min_peak and drawdown >= threshold:
                triggered = True
                memory["_stop_triggered"] = True

        if not triggered:
            return orders

        # Flatten: drop orders that grow |position|, force taker to flatten
        filtered: List[Order] = []
        for o in orders:
            new_pos = position + o.quantity
            if abs(new_pos) > abs(position):
                continue
            filtered.append(o)
        # Force flatten via taker
        if position > 0 and book.best_bid is not None:
            avail = book.best_bid_volume or position
            qty = min(position, avail)
            if qty > 0:
                filtered.append(Order(self.product, int(book.best_bid), -qty))
        elif position < 0 and book.best_ask is not None:
            avail = book.best_ask_volume or abs(position)
            qty = min(abs(position), avail)
            if qty > 0:
                filtered.append(Order(self.product, int(book.best_ask), qty))

        return filtered

    # ------------------------------------------------------------------
    # Conditional aggressive unwind (e.g. trigger when VWAP signal = -1 + long).
    # Different from EOD: only fires when market state says "danger" — not on a clock.
    # ------------------------------------------------------------------
    def _apply_conditional_unwind(
        self,
        state: TradingState,
        position: int,
        orders: List[Order],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> List[Order]:
        """Active unwind when market condition signals adversity.

        Reads VWAP signal (or other) and, if conditions met:
          - Drop orders that grow |position|
          - Add taker order to reduce position by `cond_unwind_chunk_pct` of current position

        Params:
          cond_unwind_enabled         : turn on (default False)
          cond_unwind_min_pos         : abs(position) threshold to fire (default 50)
          cond_unwind_chunk_pct       : fraction of current pos to unwind per tick (default 0.05)
          cond_unwind_use_vwap        : use VWAP signal as trigger (default True)
        """
        if not bool(self.params.get("cond_unwind_enabled", False)):
            return orders

        min_pos = int(self.params.get("cond_unwind_min_pos", 50))
        if abs(position) < min_pos:
            return orders

        # Determine signal direction
        signal = 0
        mid = book.mid_price
        if mid is not None and bool(self.params.get("cond_unwind_use_vwap", True)):
            signal = self._vwap_signal(state, float(mid), memory)

        # Only unwind if market signals adversity FOR our current position direction
        # signal = -1 (mid below VWAP, bearish) + long position → unwind long
        # signal = +1 (mid above VWAP, bullish) + short position → unwind short
        unwind_now = (signal == -1 and position > 0) or (signal == +1 and position < 0)
        if not unwind_now:
            return orders

        # Mark memory for diagnostics
        memory["_cond_unwind_active"] = 1

        chunk_pct = float(self.params.get("cond_unwind_chunk_pct", 0.05))
        chunk_size = max(1, int(round(abs(position) * chunk_pct)))

        # Filter: drop orders that grow |position|
        filtered: List[Order] = []
        for o in orders:
            new_pos = position + o.quantity
            if abs(new_pos) > abs(position):
                continue
            filtered.append(o)

        # Add taker chunk to flatten
        if position > 0 and book.best_bid is not None:
            avail = book.best_bid_volume or chunk_size
            qty = min(chunk_size, avail, position)
            if qty > 0:
                filtered.append(Order(self.product, int(book.best_bid), -qty))
        elif position < 0 and book.best_ask is not None:
            avail = book.best_ask_volume or chunk_size
            qty = min(chunk_size, avail, abs(position))
            if qty > 0:
                filtered.append(Order(self.product, int(book.best_ask), qty))

        return filtered

    # ------------------------------------------------------------------
    # Trend gate (skip mean-rev BUY in downtrend, mean-rev SELL in uptrend)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Order Book Imbalance (OBI) PASSIVE bias — adjust own quote PRICES
    # to capture directional flow without paying spread.
    # ------------------------------------------------------------------
    def _apply_obi_passive_bias(
        self,
        state: TradingState,
        position: int,
        orders: List[Order],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> List[Order]:
        """When L3 OBI is extreme, shift our PASSIVE quotes (in/out the book).

        Bullish OBI (>+threshold):
          - Raise bid by `obi_passive_tick_offset` ticks (more aggressive bid → fills faster)
          - Lower ask by 0 ticks (keep where it was; we want to KEEP long, not sell cheap)
            Actually shift ask UP (raise) → less likely to be hit → we keep longs

        Bearish OBI (<-threshold):
          - Lower ask by `obi_passive_tick_offset` ticks (more aggressive ask)
          - Raise bid (less aggressive bid → don't catch falling knife)

        Params:
          obi_passive_enabled       : turn on (default False)
          obi_passive_levels        : aggregation levels (default 3)
          obi_passive_threshold     : abs OBI to fire (default 0.005)
          obi_passive_tick_offset   : ticks to shift on the favored side (default 1)
          obi_passive_anti_offset   : ticks to shift on the opposed side (default 1)
        """
        if not bool(self.params.get("obi_passive_enabled", False)):
            return orders

        levels = int(self.params.get("obi_passive_levels", 3))
        threshold = float(self.params.get("obi_passive_threshold", 0.005))
        tick_pro = int(self.params.get("obi_passive_tick_offset", 1))
        tick_anti = int(self.params.get("obi_passive_anti_offset", 1))

        bid_total = sum(v for _, v in (book.bid_levels or [])[:levels])
        ask_total = sum(v for _, v in (book.ask_levels or [])[:levels])
        total = bid_total + ask_total
        if total == 0:
            return orders
        obi = (bid_total - ask_total) / total
        memory["_obi_passive"] = obi

        if abs(obi) < threshold:
            return orders

        bullish = obi > 0
        # Apply per-order price shift
        adjusted: List[Order] = []
        for o in orders:
            if o.quantity > 0:  # BUY (passive bid or taker buy)
                # Shift bid: bullish → up by tick_pro (more aggressive); bearish → down by tick_anti (less aggressive)
                shift = +tick_pro if bullish else -tick_anti
                new_price = int(o.price) + shift
                adjusted.append(Order(self.product, new_price, o.quantity))
            elif o.quantity < 0:  # SELL (passive ask or taker sell)
                # Shift ask: bullish → up by tick_anti (less aggressive); bearish → down by tick_pro (more aggressive)
                shift = +tick_anti if bullish else -tick_pro
                new_price = int(o.price) + shift
                adjusted.append(Order(self.product, new_price, o.quantity))
            else:
                adjusted.append(o)

        memory["_obi_passive_dir"] = "BULL" if bullish else "BEAR"
        return adjusted

    # ------------------------------------------------------------------
    # Order Book Imbalance (OBI) taker overlay — directional alpha from L3 imbalance
    # ------------------------------------------------------------------
    def _apply_obi_taker_overlay(
        self,
        state: TradingState,
        position: int,
        orders: List[Order],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> List[Order]:
        """When L3 book imbalance is extreme, fire a small taker order in the predicted direction.

        Predictive analysis on R4 VELVET D1+D2+D3 found:
          L3 OBI > 0 → next 50 ticks avg ret +7.82 (hit_up 88.5%, n=5990)
          L3 OBI < 0 → next 50 ticks avg ret -7.64 (hit_up 11%, n=5990)

        Params:
          obi_taker_enabled    : turn on (default False)
          obi_taker_levels     : how many book levels to aggregate (default 3)
          obi_taker_threshold  : abs OBI threshold to fire (default 0.005)
          obi_taker_size       : qty per taker order (default 5)
          obi_taker_cooldown_ticks : min ticks between fires (default 10)
        """
        if not bool(self.params.get("obi_taker_enabled", False)):
            return orders

        levels = int(self.params.get("obi_taker_levels", 3))
        threshold = float(self.params.get("obi_taker_threshold", 0.005))
        size = int(self.params.get("obi_taker_size", 5))
        cooldown = int(self.params.get("obi_taker_cooldown_ticks", 10))

        # Cooldown
        ts_now = int(getattr(state, "timestamp", 0))
        last_fire_ts = memory.get("_obi_last_fire_ts", -10**9)
        if ts_now - last_fire_ts < cooldown * 100:
            return orders

        # Compute OBI from book levels
        bid_total = sum(v for _, v in (book.bid_levels or [])[:levels])
        ask_total = sum(v for _, v in (book.ask_levels or [])[:levels])
        total = bid_total + ask_total
        if total == 0:
            return orders
        obi = (bid_total - ask_total) / total
        memory["_obi"] = obi

        # Bullish OBI → BUY taker at ask
        if obi > threshold and book.best_ask is not None:
            cap = max(0, self.position_limit() - position)
            qty = min(size, cap, book.best_ask_volume or size)
            if qty > 0:
                orders.append(Order(self.product, int(book.best_ask), int(qty)))
                memory["_obi_last_fire_ts"] = ts_now
                memory["_obi_last_dir"] = "BUY"

        # Bearish OBI → SELL taker at bid
        elif obi < -threshold and book.best_bid is not None:
            cap = max(0, self.position_limit() + position)
            qty = min(size, cap, book.best_bid_volume or size)
            if qty > 0:
                orders.append(Order(self.product, int(book.best_bid), -int(qty)))
                memory["_obi_last_fire_ts"] = ts_now
                memory["_obi_last_dir"] = "SELL"

        return orders

    def _counterparty_signal(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> float:
        """Counterparty-flow weighted signal.

        Maintains a rolling buffer of (timestamp, trader_id, signed_qty) for the last
        `cp_window_ts` timestamp units. Signed qty = +qty when trader is buyer, -qty
        when trader is seller. Aggregates per trader, applies a per-trader weight,
        returns weighted sum.

        Default weights (from R4 D1+D2+D3 lead-lag analysis on VELVET):
          Mark 55 = +1.0  (high-vol MM, +0.14 rho with next-50-tick return, 60% hit rate)
          Mark 67 = +1.0  (directional buyer, +0.12 rho, 54% hit rate)
          Mark 01 = -1.0  (MM, -0.17 rho — FADE its flow)
          Mark 14 = -1.0  (MM, -0.15 rho — FADE)
        Other traders default to 0 weight.

        Params:
          cp_window_ts        : rolling window in timestamp units (default 10000 = 100 ticks)
          cp_trader_weights   : dict trader_id -> weight (default = R4 VELVET weights)

        Returns: weighted signed signal (units = contracts).
        """
        window_ts = int(self.params.get("cp_window_ts", 10000))
        weights = self.params.get("cp_trader_weights", {
            "Mark 55": +1.0, "Mark 67": +1.0,
            "Mark 01": -1.0, "Mark 14": -1.0,
        })

        ts_now = int(getattr(state, "timestamp", 0))

        # Append this tick's trades to rolling buffer
        buf = memory.setdefault("_cp_buf", [])  # list of [ts, trader, signed_qty]
        try:
            mt = state.market_trades
            trades = (mt or {}).get(self.product, []) or []
        except Exception:
            trades = []
        for t in trades:
            buyer = getattr(t, "buyer", None) or ""
            seller = getattr(t, "seller", None) or ""
            qty = float(getattr(t, "quantity", 0))
            if qty <= 0:
                continue
            if buyer:
                buf.append([ts_now, buyer, qty])
            if seller:
                buf.append([ts_now, seller, -qty])

        # Drop old entries
        cutoff = ts_now - window_ts
        if buf and buf[0][0] < cutoff:
            i = 0
            while i < len(buf) and buf[i][0] < cutoff:
                i += 1
            del buf[:i]

        # Aggregate per trader, apply weights
        signal = 0.0
        per_trader = {}
        for _, trader, signed in buf:
            per_trader[trader] = per_trader.get(trader, 0.0) + signed
        for trader, net in per_trader.items():
            w = weights.get(trader, 0.0)
            signal += w * net

        memory["_cp_signal"] = signal
        memory["_cp_per_trader"] = per_trader
        return signal

    def _vwap_signal(
        self,
        state: TradingState,
        mid: float,
        memory: Dict[str, Any],
    ) -> int:
        """Compute rolling-window VWAP-based trend signal from market_trades.

        Maintains a deque of recent trades (within window_ts of current timestamp).
        VWAP = sum(price * qty) / sum(qty) over the window.

        Returns:
            +1 if mid > VWAP + threshold (mid premium, market frothy)
            -1 if mid < VWAP - threshold (mid discount, trend down — caution)
             0 if neutral or insufficient data

        Params:
          vwap_threshold      : minimum |mid - vwap| to fire (default 8.0)
          vwap_min_volume     : minimum cumulative volume before VWAP fires (default 20)
          vwap_window_ts      : rolling window in timestamp units (default 100000 = 10% of day)
        """
        threshold = float(self.params.get("vwap_threshold", 8.0))
        min_vol = float(self.params.get("vwap_min_volume", 20.0))
        window_ts = int(self.params.get("vwap_window_ts", 100000))

        # Get current timestamp
        ts_now = int(getattr(state, "timestamp", 0))

        # Get this-tick trades for our product
        trades = []
        try:
            mt = state.market_trades
            if mt:
                trades = mt.get(self.product, []) or []
        except Exception:
            pass

        # Maintain rolling buffer of (ts, price*qty, qty)
        buf = memory.setdefault("_vwap_buf", [])  # list of [ts, dollars, qty]
        for t in trades:
            qty = float(getattr(t, "quantity", 0))
            price = float(getattr(t, "price", 0))
            if qty > 0 and price > 0:
                buf.append([ts_now, price * qty, qty])

        # Drop entries older than window_ts
        cutoff = ts_now - window_ts
        if buf and buf[0][0] < cutoff:
            i = 0
            while i < len(buf) and buf[i][0] < cutoff:
                i += 1
            del buf[:i]

        # Compute VWAP from buffer
        total_qty = sum(b[2] for b in buf)
        total_dol = sum(b[1] for b in buf)
        if total_qty < min_vol or total_qty <= 0:
            return 0

        vwap = total_dol / total_qty
        memory["_vwap"] = vwap

        diff = mid - vwap
        memory["_vwap_diff"] = diff
        if diff > threshold:
            return 1
        if diff < -threshold:
            return -1
        return 0

    def _trend_direction(self, mid: float, memory: Dict[str, Any]) -> int:
        """Compute trend direction using EMA-fast vs EMA-slow.

        Returns:
            +1 if uptrend (EMA_fast > EMA_slow + threshold)
            -1 if downtrend (EMA_fast < EMA_slow - threshold)
             0 if neutral / not enough data

        Params:
          trend_ema_fast_alpha : default 0.05 (~half-life 14 ticks)
          trend_ema_slow_alpha : default 0.005 (~half-life 138 ticks)
          trend_threshold      : minimum |fast - slow| to declare trend (default 0.5)
        """
        fast_alpha = float(self.params.get("trend_ema_fast_alpha", 0.05))
        slow_alpha = float(self.params.get("trend_ema_slow_alpha", 0.005))
        threshold = float(self.params.get("trend_threshold", 0.5))

        ema_fast = memory.get("_trend_ema_fast")
        ema_slow = memory.get("_trend_ema_slow")
        if ema_fast is None:
            ema_fast = mid
            ema_slow = mid
        else:
            ema_fast = fast_alpha * mid + (1.0 - fast_alpha) * ema_fast
            ema_slow = slow_alpha * mid + (1.0 - slow_alpha) * ema_slow
        memory["_trend_ema_fast"] = ema_fast
        memory["_trend_ema_slow"] = ema_slow

        # Wait for slow EMA to warm up
        n_seen = memory.get("_trend_n_seen", 0) + 1
        memory["_trend_n_seen"] = n_seen
        warmup = int(self.params.get("trend_warmup_ticks", 200))
        if n_seen < warmup:
            return 0

        diff = ema_fast - ema_slow
        if diff > threshold:
            return 1
        elif diff < -threshold:
            return -1
        return 0
