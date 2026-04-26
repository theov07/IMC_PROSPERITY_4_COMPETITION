"""HydrogelAsymMM — combine Theo's asymmetric MM + ACF z-score window.

Design synthesis (what works from each approach):

Theo's R3HydroReversionMM (live +587, drawdown -246, 0.42x ratio — SAFEST):
  - Asymmetric one-sided quoting on EMA deviation
  - Size boost when signal strong: min(12, |dev|/4)
  - Inventory control: reduce wrong side by 0.4*pos, boost unwind by 0.3*pos
  - Tiny taker: size=1, cooldown=2000 ts

Our ACF/PACF finding:
  - Tick returns AR(1) φ=-0.13 (bid-ask noise)
  - 500-tick window = best mean-reversion horizon (ACF=-0.199)
  - z-score of mid vs rolling EMA is our signal

Codex's exhaustion (live +2,294, drawdown -3,454, 1.5x ratio — HIGH RISK):
  - Pure taker, long holds, aggressive size
  - Not integrated here (different risk profile)

This strategy keeps Theo's excellent drawdown profile while upgrading the
signal from simple EMA-deviation to z-score (|dev| / rolling_std). Rolling
std means the threshold auto-adapts to volatility regime.

Quote logic (one-sided when |z| > quote_threshold_z, symmetric otherwise):
  z > +quote_threshold_z  (mid rich):  bid_size = 0, ask_size = maker + signal_boost * f(|z|)
  z < -quote_threshold_z  (mid cheap): ask_size = 0, bid_size = maker + signal_boost * f(|z|)
  |z| <= threshold:                    symmetric at maker_size

Inventory skew (applied on top):
  pos > 0: bid -= 0.4 * pos, ask += min(unwind_boost, 0.3 * pos)
  pos < 0: symmetric

Taker overlay (minimal, Theo's design):
  |z| > take_z  AND cooldown elapsed  -> size=take_size at best (opposite of signal)

Params (all with Theo-inspired defaults):
  window              : EWMA window for mean & std (default 500, from ACF analysis)
  quote_threshold_z   : |z| where we go one-sided (default 1.5)
  maker_size          : base quote size (default 24)
  min_maker_size      : floor when boost=0 (default 3)
  signal_boost_max    : cap on signal-based size boost (default 12)
  inventory_reduce_per_unit   : shrink wrong side per unit (default 0.40)
  inventory_unwind_per_unit   : grow unwind side per unit (default 0.30)
  unwind_boost_max    : cap on unwind boost (default 20)
  tighten_ticks       : how deep into spread to quote (default 1)
  enable_taker        : Theo-style minimal taker (default True)
  take_z              : |z| to fire taker (default 2.5)
  take_size           : taker size (default 1)
  take_cooldown_ts    : min ts between takers (default 2000)
  soft_position_limit : stop taker when |pos| > this (default 60)
  min_samples         : warmup ticks before signal (default 100)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelAsymMMStrategy(BaseStrategy):
    """Asymmetric passive MM gated by z-score (Theo's design on ACF-tuned signal)."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.mid_price is None:
            return [], 0

        p = self._read_params()
        mid = float(book.mid_price)

        # EWMA mean + variance, z-score (ACF-tuned window=500)
        alpha = 2.0 / (p["window"] + 1)
        mean_prev = memory.get("_ewma_mean", mid)
        var_prev = memory.get("_ewma_var", 0.0)
        tick_count = memory.get("_tick_count", 0) + 1
        delta = mid - mean_prev
        new_mean = mean_prev + alpha * delta
        new_var = (1 - alpha) * (var_prev + alpha * delta * delta)
        memory["_ewma_mean"] = new_mean
        memory["_ewma_var"] = new_var
        memory["_tick_count"] = tick_count
        std = (new_var ** 0.5) if new_var > 0 else 0.0
        z = (mid - new_mean) / std if std > 1e-6 else 0.0
        memory["_z"] = z
        memory["_ewma_std"] = std

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        # Quoting prices (penny-improve inside the spread)
        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])

        # Sizing: asymmetric on z, then inventory skew
        warmup = (tick_count < p["min_samples"]) or (std < 1e-6)
        effective_z = 0.0 if warmup else z
        bid_size, ask_size = self._quote_sizes(effective_z, position, p)

        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            sell_cap -= qty

        # Minimal taker overlay (Theo-style)
        if p["enable_taker"] and not warmup:
            take = self._take_order(state, book, position, z, memory, buy_cap, sell_cap, p)
            if take is not None:
                orders.append(take)

        memory["_mode"] = (
            "warmup" if warmup else
            "one_sided_short" if effective_z > p["quote_threshold_z"] else
            "one_sided_long" if effective_z < -p["quote_threshold_z"] else
            "symmetric"
        )
        return orders, 0

    # ── Quote prices (penny-improve) ─────────────────────────────────────────

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, book.best_bid + 1)
        return bid, ask

    # ── Asymmetric sizing based on z-score + inventory ───────────────────────

    def _quote_sizes(self, z: float, position: int, p: Dict[str, Any]) -> Tuple[int, int]:
        maker = p["maker_size"]
        min_size = p["min_maker_size"]
        threshold = p["quote_threshold_z"]
        boost_max = p["signal_boost_max"]

        bid_size = maker
        ask_size = maker

        abs_z = abs(z)
        if z > threshold:
            # Rich → skip bid, grow ask
            bid_size = 0
            ask_size = maker + min(boost_max, int(abs_z * p["signal_boost_per_z"]))
        elif z < -threshold:
            # Cheap → skip ask, grow bid
            ask_size = 0
            bid_size = maker + min(boost_max, int(abs_z * p["signal_boost_per_z"]))

        # HARD cap on directional position build-up.
        # If already at hard_pos_cap on one side, block the side that grows it.
        # This prevents inventory runaway when signal persists against the market
        # (e.g. short in a downtrend that turns around).
        hard_cap = p["hard_pos_cap"]
        if position >= hard_cap:
            bid_size = 0  # block further buying
        if position <= -hard_cap:
            ask_size = 0  # block further selling

        # Inventory skew (always applied)
        reduce = p["inventory_reduce_per_unit"]
        unwind = p["inventory_unwind_per_unit"]
        unwind_boost = p["unwind_boost_max"]
        if position > 0:
            bid_size = max(0, bid_size - int(position * reduce))
            ask_size += min(unwind_boost, int(position * unwind))
        elif position < 0:
            ask_size = max(0, ask_size - int(-position * reduce))
            bid_size += min(unwind_boost, int(-position * unwind))

        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size
        return max(0, bid_size), max(0, ask_size)

    # ── Minimal taker (Theo's approach) ──────────────────────────────────────

    def _take_order(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        z: float,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        take_z = p["take_z"]
        cooldown = p["take_cooldown_ts"]
        size = p["take_size"]
        soft = p["soft_position_limit"]
        last_ts = int(memory.get("_last_take_ts", -10 ** 9))
        if int(state.timestamp) - last_ts < cooldown:
            return None

        if z > take_z and position > -soft and sell_cap > 0:
            qty = min(size, sell_cap, soft + position)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_bid), -qty)
        if z < -take_z and position < soft and buy_cap > 0:
            qty = min(size, buy_cap, soft - position)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_ask), qty)
        return None

    # ── Params ───────────────────────────────────────────────────────────────

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "window": int(params.get("window", 500)),
            "quote_threshold_z": float(params.get("quote_threshold_z", 1.5)),
            "maker_size": int(params.get("maker_size", 24)),
            "min_maker_size": int(params.get("min_maker_size", 3)),
            "signal_boost_max": int(params.get("signal_boost_max", 12)),
            "signal_boost_per_z": int(params.get("signal_boost_per_z", 6)),
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.30)),
            "unwind_boost_max": int(params.get("unwind_boost_max", 20)),
            "tighten_ticks": int(params.get("tighten_ticks", 1)),
            "enable_taker": bool(params.get("enable_taker", True)),
            "take_z": float(params.get("take_z", 2.5)),
            "take_size": int(params.get("take_size", 1)),
            "take_cooldown_ts": int(params.get("take_cooldown_ts", 2000)),
            "soft_position_limit": int(params.get("soft_position_limit", 60)),
            "min_samples": int(params.get("min_samples", 100)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 15)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ewma_mean", "_ewma_std", "_z"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = v
        if (m := memory.get("_mode")) is not None:
            out["mode_code"] = {"warmup":0,"symmetric":1,"one_sided_long":2,"one_sided_short":3}.get(m, -1)
        return out
