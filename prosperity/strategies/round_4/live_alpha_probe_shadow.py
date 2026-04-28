"""LiveAlphaProbeShadow — quote BEHIND the best price (queue position 2 or 3).

GOAL: observe Mark 14/01 (queue followers) IN ACTION without competing with them.
By quoting at best_bid (= same as Mark X's bid, but they got there first), we
sit BEHIND them in queue. We only fill when their queue is exhausted.

This lets us:
  - See Mark 14/01 trading naturally (they win queue against external takers)
  - Track which counterparties hit their quotes (= our queue ahead trades)
  - Catch overflow when their size is exhausted
  - Identify whether they're filled by informed flow

Phase structure (1000 ticks):
  P1 (0-499):   bid AT best_bid, ask AT best_ask (queue 2)
  P2 (500-999): bid 1 tick BELOW best_bid, ask 1 tick ABOVE (queue inactive)
                 → only filled by sweep through the book → identifies aggressive takers

Logs: per-Mark fills, who's_at_best (track who's posted L1), overflow events.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from datamodel import Order, OrderDepth, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class LiveAlphaProbeShadowStrategy(BaseStrategy):
    """Sit BEHIND best — observe queue leaders."""

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

        ts = int(state.timestamp)
        intra_tick = ts // 100
        # Phase split: 0-499 = AT best (queue 2nd), 500-999 = BELOW best
        phase = 0 if intra_tick < 500 else 1
        memory["_phase"] = phase

        # Track our fills with counterparty
        cp_log = memory.setdefault("_cp_per_phase", {0: {}, 1: {}})
        for f in state.own_trades.get(self.product, []):
            buyer = getattr(f, "buyer", None) or ""
            seller = getattr(f, "seller", None) or ""
            qty = getattr(f, "quantity", 0)
            for cp in (buyer, seller):
                if not cp:
                    continue
                cps = cp_log.setdefault(phase, {})
                d = cps.setdefault(cp, {"n": 0, "buy_qty": 0, "sell_qty": 0})
                d["n"] += 1
                if buyer == cp:
                    d["buy_qty"] += qty
                elif seller == cp:
                    d["sell_qty"] += qty

        # Track L1 size (gauge of Mark queue activity)
        memory.setdefault("_l1_bid_v_sum", 0)
        memory.setdefault("_l1_ask_v_sum", 0)
        memory["_l1_bid_v_sum"] += book.best_bid_volume
        memory["_l1_ask_v_sum"] += book.best_ask_volume

        bid_p, ask_p = int(book.best_bid), int(book.best_ask)
        size = 30
        buy_cap = max(0, self.position_limit() - position)
        sell_cap = max(0, self.position_limit() + position)

        orders: List[Order] = []
        if phase == 0:
            # AT best (queue 2nd)
            bid_q = min(size, buy_cap)
            ask_q = min(size, sell_cap)
            if bid_q > 0:
                orders.append(Order(self.product, bid_p, bid_q))
            if ask_q > 0:
                orders.append(Order(self.product, ask_p, -ask_q))
        else:
            # BELOW best — only get filled on book sweeps
            bid_q = min(size, buy_cap)
            ask_q = min(size, sell_cap)
            if bid_q > 0:
                orders.append(Order(self.product, bid_p - 1, bid_q))
            if ask_q > 0:
                orders.append(Order(self.product, ask_p + 1, -ask_q))

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        out["Phase"] = float(memory.get("_phase", 0))
        cp_log = memory.get("_cp_per_phase", {})
        for ph, cps in cp_log.items():
            phn = "P1_AT_BEST" if ph == 0 else "P2_BELOW_BEST"
            for cp, stats in sorted(cps.items(), key=lambda kv: -kv[1]["n"])[:3]:
                cp_safe = cp.replace(" ", "_")
                out[f"{phn}_{cp_safe}_n"] = float(stats["n"])
                out[f"{phn}_{cp_safe}_buyq"] = float(stats["buy_qty"])
                out[f"{phn}_{cp_safe}_sellq"] = float(stats["sell_qty"])
        return out
