"""HydrogelLadderV2 — ladder with trend-aware regime switching.

Insight from v1 backtest:
  Pure ladder works on mean-reverting days (day 0 +6,355, day 1 +9,341)
  but LOSES on trending day 2 (-486). The 4 ask levels keep filling as
  mid drops, accumulating long positions while market moves further down.

v2: regime-switching ladder
  Compute trend via dual EMA (same as follow_mm):
    trend = (EMA_fast - EMA_slow) / std

  Regime:
    |trend| < trend_threshold     → flat: full ladder (max volume)
    trend > +trend_threshold      → up_trend: ladder BID only, single ASK
    trend < -trend_threshold      → down_trend: ladder ASK only, single BID

  This way:
    - mean-reverting periods → maximum volume capture (ladder both sides)
    - trending periods → follow direction, don't fight (single side ladder)

  Same inventory skew + hard cap as v1.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelLadderV2Strategy(BaseStrategy):
    """Ladder with trend-regime switching."""

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
        spread = book.spread or 0
        if spread < p["min_spread_for_ladder"]:
            return self._narrow_fallback(book, position, p), 0

        mid = float(book.mid_price)
        best_bid = int(book.best_bid)
        best_ask = int(book.best_ask)

        # ── Dual EMA + variance for trend detection ─────────────────────
        alpha_f = 2.0 / (p["ema_fast"] + 1)
        alpha_s = 2.0 / (p["ema_slow"] + 1)
        ema_f_prev = memory.get("_ema_fast", mid)
        ema_s_prev = memory.get("_ema_slow", mid)
        var_prev = memory.get("_ewma_var", 0.0)
        tick_count = memory.get("_tick_count", 0) + 1

        delta_f = mid - ema_f_prev
        new_fast = ema_f_prev + alpha_f * delta_f
        new_slow = ema_s_prev + alpha_s * (mid - ema_s_prev)
        new_var = (1 - alpha_f) * (var_prev + alpha_f * delta_f * delta_f)
        std = (new_var ** 0.5) if new_var > 0 else 0.0
        trend = (new_fast - new_slow) / std if std > 1e-6 else 0.0

        memory["_ema_fast"] = new_fast
        memory["_ema_slow"] = new_slow
        memory["_ewma_var"] = new_var
        memory["_tick_count"] = tick_count
        memory["_trend"] = trend

        warmup = (tick_count < p["min_samples"]) or (std < 1e-6)
        effective_trend = 0.0 if warmup else trend

        t_thr = p["trend_threshold"]
        if effective_trend > t_thr:
            regime = "up_trend"
        elif effective_trend < -t_thr:
            regime = "down_trend"
        else:
            regime = "flat"
        memory["_regime"] = regime

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        hard_cap = p["hard_pos_cap"]
        block_bid = position >= hard_cap
        block_ask = position <= -hard_cap

        # ── Build ladder per regime ─────────────────────────────────────
        bid_prices, ask_prices = self._build_ladder_prices(
            best_bid, best_ask, mid, regime, p
        )
        bid_sizes, ask_sizes = self._level_sizes_for_regime(
            len(bid_prices), len(ask_prices), regime, p
        )

        # Inventory skew
        reduce_per = p["inventory_reduce_per_unit"]
        unwind_per = p["inventory_unwind_per_unit"]
        unwind_max = p["unwind_boost_max"]
        if position > 0:
            shrink = int(position * reduce_per)
            grow = min(unwind_max, int(position * unwind_per))
            n_b = max(1, len(bid_sizes))
            n_a = max(1, len(ask_sizes))
            bid_sizes = [max(0, s - shrink // n_b) for s in bid_sizes]
            ask_sizes = [s + grow // n_a for s in ask_sizes]
        elif position < 0:
            shrink = int(-position * reduce_per)
            grow = min(unwind_max, int(-position * unwind_per))
            n_b = max(1, len(bid_sizes))
            n_a = max(1, len(ask_sizes))
            ask_sizes = [max(0, s - shrink // n_a) for s in ask_sizes]
            bid_sizes = [s + grow // n_b for s in bid_sizes]

        if block_bid:
            bid_sizes = [0] * len(bid_sizes)
        if block_ask:
            ask_sizes = [0] * len(ask_sizes)

        orders: List[Order] = []
        for price, size in zip(bid_prices, bid_sizes):
            if size <= 0 or buy_cap <= 0:
                continue
            qty = min(size, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, price, qty))
                buy_cap -= qty
        for price, size in zip(ask_prices, ask_sizes):
            if size <= 0 or sell_cap <= 0:
                continue
            qty = min(size, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, price, -qty))
                sell_cap -= qty

        memory["_n_bid"] = len(bid_prices)
        memory["_n_ask"] = len(ask_prices)
        return orders, 0

    # ── Regime-dependent ladder construction ────────────────────────────

    def _build_ladder_prices(
        self,
        best_bid: int,
        best_ask: int,
        mid: float,
        regime: str,
        p: Dict[str, Any],
    ) -> Tuple[List[int], List[int]]:
        flat_levels = p["num_levels_flat"]
        trend_levels = p["num_levels_trend_follow"]
        single_level = p["num_levels_trend_against"]
        step = p["level_step"]

        if regime == "up_trend":
            n_bid = trend_levels      # follow up: more bid levels
            n_ask = single_level      # against trend: minimal asks
        elif regime == "down_trend":
            n_bid = single_level
            n_ask = trend_levels
        else:
            n_bid = flat_levels
            n_ask = flat_levels

        bid_prices: List[int] = []
        ask_prices: List[int] = []
        for i in range(n_bid):
            bp = best_bid + 1 + i * step
            if bp < mid - 0.5:
                bid_prices.append(bp)
        for i in range(n_ask):
            ap = best_ask - 1 - i * step
            if ap > mid + 0.5:
                ask_prices.append(ap)

        # Avoid crossing
        while bid_prices and ask_prices and max(bid_prices) >= min(ask_prices):
            bid_prices = [pp for pp in bid_prices if pp < min(ask_prices)]
            if not bid_prices:
                break
            ask_prices = [pp for pp in ask_prices if pp > max(bid_prices)]
        return bid_prices, ask_prices

    def _level_sizes_for_regime(
        self,
        n_bid: int,
        n_ask: int,
        regime: str,
        p: Dict[str, Any],
    ) -> Tuple[List[int], List[int]]:
        if regime == "flat":
            total = p["total_size_flat"]
            bid_total = total
            ask_total = total
        elif regime == "up_trend":
            bid_total = p["total_size_trend_follow"]
            ask_total = p["total_size_trend_against"]
        else:  # down_trend
            ask_total = p["total_size_trend_follow"]
            bid_total = p["total_size_trend_against"]
        return (
            self._pyramid_sizes(n_bid, bid_total),
            self._pyramid_sizes(n_ask, ask_total),
        )

    def _pyramid_sizes(self, n: int, total: int) -> List[int]:
        if n <= 0:
            return []
        if n == 1:
            return [total]
        weights = list(range(n, 0, -1))
        tot_w = sum(weights)
        sizes = [int(total * w / tot_w) for w in weights]
        diff = total - sum(sizes)
        for i in range(diff):
            sizes[i % n] += 1
        return sizes

    def _narrow_fallback(
        self, book: BookSnapshot, position: int, p: Dict[str, Any]
    ) -> List[Order]:
        size = p["fallback_size"]
        bid_price = int(book.best_bid) + 1 if book.spread and book.spread >= 2 else int(book.best_bid)
        ask_price = int(book.best_ask) - 1 if book.spread and book.spread >= 2 else int(book.best_ask)
        if bid_price >= ask_price:
            bid_price = int(book.best_bid)
            ask_price = int(book.best_ask)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        hard_cap = p["hard_pos_cap"]
        out: List[Order] = []
        if position < hard_cap and buy_cap > 0:
            out.append(Order(self.product, bid_price, min(size, buy_cap)))
        if position > -hard_cap and sell_cap > 0:
            out.append(Order(self.product, ask_price, -min(size, sell_cap)))
        return out

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            # Trend detection
            "ema_fast": int(params.get("ema_fast", 500)),
            "ema_slow": int(params.get("ema_slow", 2000)),
            "trend_threshold": float(params.get("trend_threshold", 1.0)),
            "min_samples": int(params.get("min_samples", 200)),
            # Ladder geometry
            "num_levels_flat": int(params.get("num_levels_flat", 3)),
            "num_levels_trend_follow": int(params.get("num_levels_trend_follow", 3)),
            "num_levels_trend_against": int(params.get("num_levels_trend_against", 1)),
            "level_step": int(params.get("level_step", 1)),
            "min_spread_for_ladder": int(params.get("min_spread_for_ladder", 4)),
            # Sizes
            "total_size_flat": int(params.get("total_size_flat", 30)),
            "total_size_trend_follow": int(params.get("total_size_trend_follow", 30)),
            "total_size_trend_against": int(params.get("total_size_trend_against", 5)),
            "fallback_size": int(params.get("fallback_size", 8)),
            # Inventory + cap
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.5)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.3)),
            "unwind_boost_max": int(params.get("unwind_boost_max", 30)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 30)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ema_fast", "_ema_slow", "_trend"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        if (r := memory.get("_regime")) is not None:
            out["regime_code"] = {"flat": 0, "up_trend": 1, "down_trend": 2}.get(r, -1)
        return out
