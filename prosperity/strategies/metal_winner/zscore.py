"""Z-score market maker — inventory-adaptive sizing tilted by price deviation.

Philosophy:
  Same penny-improve quoting structure as mm_first, but the bid/ask sizes
  are further tilted by the z-score of the smoothed mid price relative to
  its own rolling history:

    z = (mid_smooth - rolling_mean(W)) / rolling_std(W)

  When z > threshold  → price is high → boost ask_size, shrink bid_size
  When z < -threshold → price is low  → boost bid_size, shrink ask_size
  |z| <= threshold    → no z-score adjustment; pure inventory-adaptive sizing

  Size adjustment (proportional to excess z beyond the threshold):
    excess = max(0, |z| - threshold)
    scale  = min(zscore_max_scale, 1 + zscore_size_scale * excess)
    z > threshold  → ask_size *= scale,  bid_size  /= scale
    z < -threshold → bid_size *= scale,  ask_size  /= scale

  The z-score tilt is applied ON TOP of the existing inventory-adaptive
  dynamic sizing (bid_size shrinks when long, ask_size shrinks when short).
  Both effects compound: a long position + high z-score pushes ask_size up
  and bid_size down from two independent sources.

Key params (all configurable via config.py):
  zscore_window      — rolling window W for mean/std (default 100)
  zscore_threshold   — |z| must exceed this to trigger scaling (default 1.0)
  zscore_size_scale  — slope of scale vs excess z (default 0.5)
  zscore_max_scale   — cap on the multiplier (default 3.0)
  inv_step_threshold — fraction of limit at which bid/ask steps to L2 (default 0.8)
  take_edge          — min edge vs mid_smooth to trigger a taker order (default 1.0)
  maker_size_base_pct — base passive quote size as % of position limit (default 0.5)
  pct_kept_for_takers — fraction of remaining capacity reserved for takers (default 0.2)
  mid_smooth_window, mid_smooth_half_life — EWMA smoother params (inherited from base)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class ZScoreStrategy(BaseStrategy):

    # ── z-score computation ──────────────────────────────────────────
    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> float | None:
        """Append mid to rolling buffer; return z-score or None if not enough data.
        """
        window = int(self.params.get("zscore_window", 100))

        buf = memory.setdefault("_zs_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]

        if len(buf) < max(3, window // 4):
            return None

        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = math.sqrt(var) if var > 0 else None

        if std is None or std < 1e-9:
            return None

        z = (mid - mean) / std
        memory["_zs_mean"] = mean
        memory["_zs_std"] = std
        memory["_zs_z"] = z
        return z

    def _zscore_size_factors(self, z: float | None) -> tuple[float, float]:
        """Return (bid_factor, ask_factor) multipliers given the current z-score.

        Neutral (no signal): both 1.0.
        z > threshold: ask_factor > 1, bid_factor < 1 (lean short).
        z < -threshold: bid_factor > 1, ask_factor < 1 (lean long).
        """
        if z is None:
            return 1.0, 1.0

        threshold  = float(self.params.get("zscore_threshold", 1.0))
        size_scale = float(self.params.get("zscore_size_scale", 0.5))
        max_scale  = float(self.params.get("zscore_max_scale", 3.0))

        excess = max(0.0, abs(z) - threshold)
        scale  = min(max_scale, 1.0 + size_scale * excess)

        if z > threshold:
            return 1.0 / scale, scale      # (bid_factor, ask_factor)
        if z < -threshold:
            return scale, 1.0 / scale      # (bid_factor, ask_factor)
        return 1.0, 1.0

    # ── order construction ───────────────────────────────────────────
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        if book.best_bid is None and book.best_ask is None:
            return [], 0

        mid = book.mid_price or float(book.best_bid or book.best_ask or 0)
        mid_smooth = self._smooth_mid(mid, memory)

        z = self._compute_zscore(mid_smooth, memory)

        limit = self.position_limit()
        inventory_ratio = position / float(limit)
        step_threshold = float(self.params.get("inv_step_threshold", 0.8))

        # ── QUOTE LEVEL SELECTION (same as mm_first) ──────────────────
        bid_price: int | None = (book.best_bid + 1) if book.best_bid is not None else memory.get("_last_bid_price")
        ask_price: int | None = (book.best_ask - 1) if book.best_ask is not None else memory.get("_last_ask_price")
        quote_level = "L1"

        if inventory_ratio >= step_threshold:
            if book.best_bid is not None:
                bid_price = book.best_bid
            quote_level = "L2"
        elif inventory_ratio <= -step_threshold:
            if book.best_ask is not None:
                ask_price = book.best_ask
            quote_level = "L2"

        # Crossing prevention  (mid_smooth is float → cast to int before arithmetic)
        if bid_price is not None and book.best_ask is not None:
            bid_price = min(bid_price, int(mid_smooth) - 1)
        if ask_price is not None and book.best_bid is not None:
            ask_price = max(ask_price, math.ceil(mid_smooth) + 1)
        if bid_price is not None and ask_price is not None and ask_price <= bid_price:
            ask_price = bid_price + 1

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── DYNAMIC SIZING with z-score tilt ──────────────────────────
        # Step 1: inventory-adaptive base sizes (same as mm_first)
        base_size = float(self.params.get("maker_size_base_pct", 0.5)) * limit
        bid_size  = base_size * (1.0 - position / limit) if limit else base_size
        ask_size  = base_size * (1.0 + position / limit) if limit else base_size

        # Step 2: z-score tilt on top
        bid_factor, ask_factor = self._zscore_size_factors(z)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)

        # Persist for feature_prices() → dashboard
        memory["_zs_bid_factor"] = bid_factor
        memory["_zs_ask_factor"] = ask_factor

        orders: List[Order] = []

        # ── TAKER ORDERS ───────────────────────────────────────────────
        take_edge            = float(self.params.get("take_edge", 1.0))
        taker_buy_threshold  = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")

        this_taker_buy_px: set  = set()
        this_taker_sell_px: set = set()

        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= mid_smooth - take_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, max(1, int(bid_size * 0.3)))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                this_taker_buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume     = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= mid_smooth + take_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, max(1, int(ask_size * 0.3)))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                this_taker_sell_px.add(bid_p)
                sell_cap -= qty

        # ── TAKER RE-ANCHOR ────────────────────────────────────────────
        if this_taker_buy_px:
            new_best_ask = next(
                (p for p in sorted(order_depth.sell_orders) if p not in this_taker_buy_px),
                None,
            )
            if new_best_ask is not None:
                ask_price = new_best_ask - 1

        if this_taker_sell_px:
            new_best_bid = next(
                (p for p in sorted(order_depth.buy_orders, reverse=True) if p not in this_taker_sell_px),
                None,
            )
            if new_best_bid is not None:
                bid_price = new_best_bid + 1

        # ── PASSIVE ORDERS ─────────────────────────────────────────────
        quote_buy  = min(buy_cap,  int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))

        # Hard stop: reserve capacity for takers at extreme inventory
        inv_abs = abs(position) / float(limit) if limit else 0.0
        if inv_abs >= 1.0 - float(self.params.get("pct_kept_for_takers", 0.2)):
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0

        if bid_price is not None:
            memory["_last_bid_price"] = bid_price
        if ask_price is not None:
            memory["_last_ask_price"] = ask_price

        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position":   position,
                "mid_smooth": round(mid_smooth, 2),
                "z":          round(z, 3) if z is not None else None,
                "bid_factor": round(bid_factor, 3),
                "ask_factor": round(ask_factor, 3),
                "level":      quote_level,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        # Price-level overlays on the price chart
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        if (mean := memory.get("_zs_mean")) is not None and (std := memory.get("_zs_std")) is not None:
            threshold = float(self.params.get("zscore_threshold", 1.0))
            out["ZBandUp"] = mean + std * threshold
            out["ZBandLo"] = mean - std * threshold
        # Z-score panel: feeds the dedicated dashboard subplot
        if (z := memory.get("_zs_z")) is not None:
            out["Z"] = round(z, 4)
        if (bf := memory.get("_zs_bid_factor")) is not None:
            out["BidFactor"] = round(bf, 4)
        if (af := memory.get("_zs_ask_factor")) is not None:
            out["AskFactor"] = round(af, 4)
        return out
