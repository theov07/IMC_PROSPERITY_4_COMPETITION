"""LiveAlphaProbeSize — cycle through different SIZE buckets to detect size-conditional Marks.

GOAL: some Marks may only respond to specific size quotes (e.g. small retail-like
flow vs big institutional). By varying our quote SIZE while keeping prices
identical, we identify Marks who only fill at certain size brackets.

Phase structure (1000 ticks):
  Each phase = 200 ticks. Penny-improve quotes, varying SIZE only:
  P1: size 1   (zero impact, see who responds to small)
  P2: size 5
  P3: size 30  (normal MM)
  P4: size 100 (institutional-size)
  P5: size 200 (max — full position limit)

Hypothesis: small Marks (Mark 67 buys ~10/trade) ignore mega-size; big traders
(Mark 14 with 30+ trades) only show up in P3+. Reveals scale-conditional flows.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from datamodel import Order, OrderDepth, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy

PHASE_SIZES = [1, 5, 30, 100, 200]
PHASE_NAMES = [f"P{i+1}_SIZE_{s}" for i, s in enumerate(PHASE_SIZES)]


class LiveAlphaProbeSizeStrategy(BaseStrategy):
    """Cycle quote SIZE while keeping price constant."""

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
        # Phase: each 200 ticks = one size
        phase = min(intra_tick // 200, 4)
        size = PHASE_SIZES[phase]
        memory["_phase"] = phase
        memory["_size"] = size

        # Per-phase counterparty log
        cp_log = memory.setdefault("_cp_per_phase", {p: {} for p in PHASE_NAMES})
        for f in state.own_trades.get(self.product, []):
            buyer = getattr(f, "buyer", None) or ""
            seller = getattr(f, "seller", None) or ""
            qty = getattr(f, "quantity", 0)
            for cp in (buyer, seller):
                if not cp:
                    continue
                pname = PHASE_NAMES[phase]
                cps = cp_log.setdefault(pname, {})
                d = cps.setdefault(cp, {"n": 0, "buy_qty": 0, "sell_qty": 0})
                d["n"] += 1
                if buyer == cp:
                    d["buy_qty"] += qty
                elif seller == cp:
                    d["sell_qty"] += qty

        # Quote at penny-improve, varying size
        bid_p = int(book.best_bid) + 1 if int(book.best_bid) + 1 < int(book.best_ask) else int(book.best_bid)
        ask_p = int(book.best_ask) - 1 if int(book.best_ask) - 1 > int(book.best_bid) else int(book.best_ask)

        buy_cap = max(0, self.position_limit() - position)
        sell_cap = max(0, self.position_limit() + position)

        orders: List[Order] = []
        bq = min(size, buy_cap)
        aq = min(size, sell_cap)
        if bq > 0:
            orders.append(Order(self.product, bid_p, bq))
        if aq > 0:
            orders.append(Order(self.product, ask_p, -aq))

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        out["Phase"] = float(memory.get("_phase", 0))
        out["Size"] = float(memory.get("_size", 0))
        cp_log = memory.get("_cp_per_phase", {})
        for pname, cps in cp_log.items():
            for cp, stats in sorted(cps.items(), key=lambda kv: -kv[1]["n"])[:3]:
                cp_safe = cp.replace(" ", "_")
                out[f"{pname}_{cp_safe}_n"] = float(stats["n"])
                out[f"{pname}_{cp_safe}_buyq"] = float(stats["buy_qty"])
                out[f"{pname}_{cp_safe}_sellq"] = float(stats["sell_qty"])
        return out
