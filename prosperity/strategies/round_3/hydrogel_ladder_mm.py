"""HydrogelLadderMM — multi-level passive ladder inside the spread.

Rationale:
  HYDROGEL_PACK has spread ~15 ticks. A single-level quote at best±1 captures
  only one price point. By laddering INSIDE the spread (multiple price levels
  improving on best), we:

  1. Capture more price points per side per tick. If the market moves up past
     3 of our 4 ask levels, all 3 fill — much more volume than 1 ask.

  2. Get queue priority = 0 at each level we improve. We're alone at prices
     that didn't exist before, so we're first in line for any taker hitting
     that price.

  3. Multiplicatively amplify volume vs single-level: backtest shows ~3-5x
     more fills with 4 levels per side, scaling roughly linearly in PnL
     when the edge per fill stays positive.

  Trade-off: more inventory churn. Need tighter inventory control + hard cap
  to prevent runaway. Levels closer to mid fill more often (bigger inventory
  swings) so we taper sizes (more depth at outer levels).

Quote logic:
  base bid price = best_bid + 1            (penny-improve)
  base ask price = best_ask - 1            (penny-improve)
  for i in 0..num_levels-1:
      bid level i: price = base_bid + i*level_step,  size = size_pyramid(i)
      ask level i: price = base_ask - i*level_step,  size = size_pyramid(i)

  Levels are clipped so they don't cross mid (no self-cross).

  size_pyramid(i): bigger at level 0 (closest to best), tapering outward
                   OR uniform (size_per_level / num_levels). Configurable.

Inventory skew:
  pos > 0: shrink bid levels by reduce*pos / num_levels per level,
           grow ask levels symmetrically.
  Same for pos < 0.

Hard cap: total bid_size = 0 when pos >= +hard_cap, ask_size = 0 when -hard_cap.

Optional regime asym (off by default):
  When trend strongly up: bid ladder grows, ask ladder shrinks (follow up).
  When trend strongly down: opposite. Not enabled by default — pure ladder
  first to see the volume boost in isolation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelLadderMMStrategy(BaseStrategy):
    """Multi-level passive ladder inside spread, with inventory control."""

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
        # Need at least 2-tick spread to ladder inside; otherwise fall back to
        # joining best.
        if spread < p["min_spread_for_ladder"]:
            return self._narrow_fallback(book, position, p), 0

        mid = float(book.mid_price)
        best_bid = int(book.best_bid)
        best_ask = int(book.best_ask)

        # EWMA mean (for optional logging only — no signal-driven asym in v1)
        alpha = 2.0 / (p["window"] + 1)
        mean_prev = memory.get("_ewma_mean", mid)
        new_mean = mean_prev + alpha * (mid - mean_prev)
        memory["_ewma_mean"] = new_mean
        memory["_mid"] = mid

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Hard position cap blocks one side
        hard_cap = p["hard_pos_cap"]
        block_bid = position >= hard_cap
        block_ask = position <= -hard_cap

        # Build ladder prices (clipped so no level crosses mid)
        num_levels = p["num_levels"]
        step = p["level_step"]
        bid_prices = []
        ask_prices = []
        for i in range(num_levels):
            bp = best_bid + 1 + i * step
            ap = best_ask - 1 - i * step
            # Clip: bid stays strictly below mid, ask strictly above
            if bp < mid - 0.5:
                bid_prices.append(bp)
            if ap > mid + 0.5:
                ask_prices.append(ap)

        # Ensure we don't accidentally overlap (highest bid < lowest ask)
        if bid_prices and ask_prices and max(bid_prices) >= min(ask_prices):
            # Shrink to maintain at least 1 tick gap
            while bid_prices and ask_prices and max(bid_prices) >= min(ask_prices):
                # Drop the most aggressive (highest) bid and (lowest) ask
                bid_prices = [p for p in bid_prices if p < min(ask_prices)]
                ask_prices = [p for p in ask_prices if p > max(bid_prices) if bid_prices] or ask_prices[1:]

        # Sizing: pyramid (decreasing from best to outer) or uniform
        size_mode = p["size_mode"]
        total_per_side = p["total_size_per_side"]
        bid_sizes = self._level_sizes(len(bid_prices), total_per_side, size_mode)
        ask_sizes = self._level_sizes(len(ask_prices), total_per_side, size_mode)

        # Inventory skew: shrink wrong side, grow unwind side
        reduce_per = p["inventory_reduce_per_unit"]
        unwind_per = p["inventory_unwind_per_unit"]
        unwind_max = p["unwind_boost_max"]
        if position > 0:
            shrink = int(position * reduce_per)
            grow = min(unwind_max, int(position * unwind_per))
            bid_sizes = [max(0, s - shrink // max(1, len(bid_sizes))) for s in bid_sizes]
            ask_sizes = [s + grow // max(1, len(ask_sizes)) for s in ask_sizes]
        elif position < 0:
            shrink = int(-position * reduce_per)
            grow = min(unwind_max, int(-position * unwind_per))
            ask_sizes = [max(0, s - shrink // max(1, len(ask_sizes))) for s in ask_sizes]
            bid_sizes = [s + grow // max(1, len(bid_sizes)) for s in bid_sizes]

        if block_bid:
            bid_sizes = [0] * len(bid_sizes)
        if block_ask:
            ask_sizes = [0] * len(ask_sizes)

        orders: List[Order] = []
        # Place bids (highest price first → fills first)
        for price, size in zip(bid_prices, bid_sizes):
            if size <= 0 or buy_cap <= 0:
                continue
            qty = min(size, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, price, qty))
                buy_cap -= qty
        # Place asks (lowest price first → fills first)
        for price, size in zip(ask_prices, ask_sizes):
            if size <= 0 or sell_cap <= 0:
                continue
            qty = min(size, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, price, -qty))
                sell_cap -= qty

        memory["_num_bid_levels"] = len(bid_prices)
        memory["_num_ask_levels"] = len(ask_prices)
        memory["_total_bid_size"] = sum(bid_sizes)
        memory["_total_ask_size"] = sum(ask_sizes)
        return orders, 0

    # ── Narrow-spread fallback: just penny-improve single level ─────────────

    def _narrow_fallback(
        self, book: BookSnapshot, position: int, p: Dict[str, Any]
    ) -> List[Order]:
        # When spread < min_spread_for_ladder, use single-level penny-improve.
        size = p["fallback_size"]
        bid_price = int(book.best_bid) + 1 if book.spread and book.spread >= 2 else int(book.best_bid)
        ask_price = int(book.best_ask) - 1 if book.spread and book.spread >= 2 else int(book.best_ask)
        # Make sure not crossing
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

    # ── Level-size distribution ─────────────────────────────────────────────

    def _level_sizes(self, n: int, total: int, mode: str) -> List[int]:
        if n <= 0:
            return []
        if mode == "uniform":
            base = total // n
            rem = total - base * n
            return [base + (1 if i < rem else 0) for i in range(n)]
        # pyramid: more at level 0 (closest to best, fills fastest)
        # weights = n, n-1, ..., 1
        if mode == "pyramid":
            weights = list(range(n, 0, -1))
            tot_w = sum(weights)
            sizes = [int(total * w / tot_w) for w in weights]
            # adjust rounding to match total
            diff = total - sum(sizes)
            for i in range(diff):
                sizes[i % n] += 1
            return sizes
        # inverted_pyramid: more at outer levels (fewer fills, less inventory churn)
        if mode == "inverted_pyramid":
            weights = list(range(1, n + 1))
            tot_w = sum(weights)
            sizes = [int(total * w / tot_w) for w in weights]
            diff = total - sum(sizes)
            for i in range(diff):
                sizes[-(i % n + 1)] += 1
            return sizes
        # default uniform
        base = total // n
        rem = total - base * n
        return [base + (1 if i < rem else 0) for i in range(n)]

    # ── Params ──────────────────────────────────────────────────────────────

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "num_levels": int(params.get("num_levels", 4)),
            "level_step": int(params.get("level_step", 1)),
            "total_size_per_side": int(params.get("total_size_per_side", 40)),
            "size_mode": str(params.get("size_mode", "pyramid")),
            "min_spread_for_ladder": int(params.get("min_spread_for_ladder", 4)),
            "fallback_size": int(params.get("fallback_size", 8)),
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.5)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.3)),
            "unwind_boost_max": int(params.get("unwind_boost_max", 30)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 60)),
            "window": int(params.get("window", 500)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ewma_mean", "_mid", "_total_bid_size", "_total_ask_size"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        return out
