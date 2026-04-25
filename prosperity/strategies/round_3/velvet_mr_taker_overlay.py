"""VelvetMRTakerOverlay — explicit z-score taker on VELVET extremes.

The data shows ρ_1 = -0.16 on VELVET 1-tick returns (mean-reverting). When
|z| > threshold, fire a taker that bets on mean-reversion:
  z > +threshold (rich)   → SELL at best_bid (crosses spread, expects revert down)
  z < -threshold (cheap)  → BUY at best_ask (crosses spread, expects revert up)

This is an OVERLAY on top of any underlying VELVET MM — the MM stays as-is,
this just adds taker orders when the signal fires. Designed to be combined
with R2/v4 anchor MM (v24) or naive_tight_mm.

NOTE: this strategy needs to be the SOLE strategy on VELVET, otherwise the
config can't have two strategies on one product. So we run it via:
  - VELVET = naive_tight_mm + this overlay logic baked in (via subclass-style
    call), OR
  - Add the logic as a fallback within the existing strat.

For now, this strategy IS a complete VELVET MM that includes both the passive
side AND the taker overlay. The passive side mimics R2/v4 anchor MM lite.

Params:
  position_limit, maker_size_base_pct, mid_smooth_window, etc. — passive MM
  zscore_window           : VELVET z buffer (default 500)
  zscore_taker_threshold  : |z| trigger (default 2.0)
  taker_size              : qty per taker tick (default 5)
  taker_cooldown_ticks    : block re-fire for N ticks after taker (default 100)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class VelvetMRTakerOverlayStrategy(BaseStrategy):
    """VELVET MM (penny-improve) + z-score mean-reversion taker overlay."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        p = self._read_params()
        ts = int(state.timestamp)
        mid = 0.5 * (book.best_bid + book.best_ask)

        # Update z-score buffer
        z = self._update_z(mid, memory, p)
        memory["_z"] = z

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── Z-score taker overlay (mean-reversion)
        cooldown = int(memory.get("_taker_cooldown_until", 0))
        if z is not None and ts >= cooldown:
            if z > p["zscore_taker_threshold"] and sell_cap > 0:
                # Rich → SELL at best_bid (cross spread for active sell)
                qty = min(p["taker_size"], sell_cap, order_depth.buy_orders.get(book.best_bid, 0))
                if qty > 0:
                    orders.append(Order(self.product, book.best_bid, -qty))
                    sell_cap -= qty
                    memory["_taker_cooldown_until"] = ts + p["taker_cooldown_ticks"] * 100
                    memory["_last_taker"] = "sell"
            elif z < -p["zscore_taker_threshold"] and buy_cap > 0:
                qty = min(p["taker_size"], buy_cap, -order_depth.sell_orders.get(book.best_ask, 0))
                if qty > 0:
                    orders.append(Order(self.product, book.best_ask, qty))
                    buy_cap -= qty
                    memory["_taker_cooldown_until"] = ts + p["taker_cooldown_ticks"] * 100
                    memory["_last_taker"] = "buy"

        # ── Passive penny-improve MM with inventory skew
        bid_px = book.best_bid + 1
        ask_px = book.best_ask - 1
        if bid_px >= book.best_ask: bid_px = book.best_bid
        if ask_px <= book.best_bid: ask_px = book.best_ask

        limit = self.position_limit()
        base = p["maker_size_base_pct"] * limit
        bid_size = int(max(0, base * (1.0 - position / limit)))
        ask_size = int(max(0, base * (1.0 + position / limit)))

        # Hard stop: when |pos| near limit, stop adding bias side
        hard_stop = 1.0 - p["pct_kept_for_takers"]
        inv_abs = abs(position) / limit if limit else 0.0
        if inv_abs >= hard_stop:
            if position > 0: bid_size = 0
            elif position < 0: ask_size = 0

        if bid_size > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(bid_size, buy_cap)))
        if ask_size > 0 and sell_cap > 0:
            orders.append(Order(self.product, ask_px, -min(ask_size, sell_cap)))

        return orders, 0

    def _update_z(self, mid: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Optional[float]:
        window = p["zscore_window"]
        buf: List[float] = memory.setdefault("_z_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (mid - mean) / std

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "zscore_window": int(params.get("zscore_window", 500)),
            "zscore_taker_threshold": float(params.get("zscore_taker_threshold", 2.0)),
            "taker_size": int(params.get("taker_size", 5)),
            "taker_cooldown_ticks": int(params.get("taker_cooldown_ticks", 100)),
            "maker_size_base_pct": float(params.get("maker_size_base_pct", 0.30)),
            "pct_kept_for_takers": float(params.get("pct_kept_for_takers", 0.15)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if (z := memory.get("_z")) is not None: out["z_velvet"] = z
        return out
