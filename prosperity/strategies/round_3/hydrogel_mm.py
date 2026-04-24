"""HydrogelMM — single-asset MM tuned for Round 3's wide-spread HYDROGEL_PACK.

Microstructure discovery:
  Spread on HYDROGEL_PACK = ~15-17 ticks (vs 2-4 on R1/R2 OSM).
  Bid/ask L1 volumes = 12 units each.
  Return autocorrelation = -0.12 to -0.14 (mild mean-reversion).

Live diagnostic (1erSubmit log):
  - 176/192 fills adverse (92%) because v4_F5 anchor triggered taker crosses.
  - naive_tight_mm in live: only 20 fills, avg penny-improve = +610 PnL.

Key insight: the spread is huge → each passive fill captures ~6-7 ticks.
The bottleneck is VOLUME, not edge per trade. To boost volume we need:
  1. Post at MULTIPLE levels inside the spread (ladder)
  2. Larger size aggregate (use more of the 200 position limit)
  3. Inventory-aware: shrink the side that worsens inventory
  4. NO aggressive takers (they lose against drift)

Quote structure (each side, symmetric by default):
  Level 1: best_bid + 1                 size = l1_size
  Level 2: best_bid + level2_inside     size = l2_size
  Level 3: best_bid + level3_inside     size = l3_size
  (similarly on ask side)

All levels must stay STRICTLY inside the spread (bid_level_N < best_ask).

Inventory aversion (AS-style):
  When position > 0, shrink bid sizes by (1 - position/limit * aversion)
  When position < 0, shrink ask sizes symmetrically.

Params:
  l1_size            : qty at best_bid+1 / best_ask-1 (default 30)
  level2_inside      : ticks inside best for level 2 (default 3)
  l2_size            : qty at level 2 (default 30)
  level3_inside      : ticks inside best for level 3 (default 6)
  l3_size            : qty at level 3 (default 20)
  inventory_aversion : 0..1 — how much to shrink worsening side (default 0.5)
  min_spread_for_l2  : only post level 2 if spread ≥ this (default 6)
  min_spread_for_l3  : only post level 3 if spread ≥ this (default 12)
  max_position       : defensive cap (default = position_limit)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelMMStrategy(BaseStrategy):
    """Multi-level passive MM for wide-spread assets (HYDROGEL_PACK)."""

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
        spread = book.best_ask - book.best_bid
        if spread <= 0:
            return [], 0

        limit = self.position_limit()
        max_pos = min(p["max_position"], limit)
        buy_cap = max(0, max_pos - position)
        sell_cap = max(0, max_pos + position)

        # Inventory-aversion multipliers (shrink the side that worsens inventory)
        inv_aversion = p["inventory_aversion"]
        pos_ratio = position / float(max_pos) if max_pos else 0.0
        # If long, bid is the "worsening" side → shrink it
        bid_size_mult = max(0.0, 1.0 - max(0.0, pos_ratio) * inv_aversion)
        ask_size_mult = max(0.0, 1.0 - max(0.0, -pos_ratio) * inv_aversion)

        orders: List[Order] = []

        # Level 1: penny-improve inside the best
        bid_l1 = book.best_bid + 1
        ask_l1 = book.best_ask - 1
        if bid_l1 < book.best_ask:
            q = int(round(p["l1_size"] * bid_size_mult))
            q = min(q, buy_cap)
            if q > 0:
                orders.append(Order(self.product, bid_l1, q))
                buy_cap -= q
        if ask_l1 > book.best_bid:
            q = int(round(p["l1_size"] * ask_size_mult))
            q = min(q, sell_cap)
            if q > 0:
                orders.append(Order(self.product, ask_l1, -q))
                sell_cap -= q

        # Level 2: deeper inside the spread
        if spread >= p["min_spread_for_l2"]:
            bid_l2 = book.best_bid + p["level2_inside"]
            ask_l2 = book.best_ask - p["level2_inside"]
            if bid_l2 < book.best_ask and bid_l2 != bid_l1:
                q = int(round(p["l2_size"] * bid_size_mult))
                q = min(q, buy_cap)
                if q > 0:
                    orders.append(Order(self.product, bid_l2, q))
                    buy_cap -= q
            if ask_l2 > book.best_bid and ask_l2 != ask_l1:
                q = int(round(p["l2_size"] * ask_size_mult))
                q = min(q, sell_cap)
                if q > 0:
                    orders.append(Order(self.product, ask_l2, -q))
                    sell_cap -= q

        # Level 3: near-mid (only very wide spreads)
        if spread >= p["min_spread_for_l3"]:
            bid_l3 = book.best_bid + p["level3_inside"]
            ask_l3 = book.best_ask - p["level3_inside"]
            if bid_l3 < book.best_ask and bid_l3 not in (bid_l1, bid_l3):
                q = int(round(p["l3_size"] * bid_size_mult))
                q = min(q, buy_cap)
                if q > 0:
                    orders.append(Order(self.product, bid_l3, q))
                    buy_cap -= q
            if ask_l3 > book.best_bid and ask_l3 not in (ask_l1, ask_l3):
                q = int(round(p["l3_size"] * ask_size_mult))
                q = min(q, sell_cap)
                if q > 0:
                    orders.append(Order(self.product, ask_l3, -q))
                    sell_cap -= q

        # Log metrics
        mid = 0.5 * (book.best_bid + book.best_ask)
        memory["_spread"] = spread
        memory["_mid"] = mid
        memory["_position"] = position
        memory["_bid_mult"] = bid_size_mult
        memory["_ask_mult"] = ask_size_mult

        return orders, 0

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "l1_size": int(params.get("l1_size", 30)),
            "level2_inside": int(params.get("level2_inside", 3)),
            "l2_size": int(params.get("l2_size", 30)),
            "level3_inside": int(params.get("level3_inside", 6)),
            "l3_size": int(params.get("l3_size", 20)),
            "inventory_aversion": float(params.get("inventory_aversion", 0.5)),
            "min_spread_for_l2": int(params.get("min_spread_for_l2", 6)),
            "min_spread_for_l3": int(params.get("min_spread_for_l3", 12)),
            "max_position": int(params.get("max_position", self.position_limit())),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (s := memory.get("_spread")) is not None:
            out["spread"] = s
        if (m := memory.get("_mid")) is not None:
            out["mid"] = m
        if (bm := memory.get("_bid_mult")) is not None:
            out["bid_mult"] = bm
        if (am := memory.get("_ask_mult")) is not None:
            out["ask_mult"] = am
        return out
