"""LiveAlphaProbeOnOff — alternating ON / OFF cycles to capture natural Mark↔Mark flow.

GOAL: in v5 LIVE we found that our quotes phagocytose 80% of flow → Mark↔Mark
trades drop dramatically. To OBSERVE NATURAL Mark↔Mark patterns, we need to be
absent periodically. This probe cycles 50 ticks ON / 50 ticks OFF for 1000 ticks
total = 10 ON cycles + 10 OFF cycles.

In OFF periods (no quote): observe who trades with whom naturally
In ON periods (penny improve): observe who fills us

Comparing: are the SAME Marks active in OFF vs ON? If yes, Mark X is omni-present
(an MM). If they only show in OFF, they avoid us when we quote.

Logs:
  - per cycle, our fills vs Mark↔Mark trades (visible to our memory)
  - per Mark, # times appearing in ON vs OFF cycles
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from datamodel import Order, OrderDepth, TradingState
from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class LiveAlphaProbeOnOffStrategy(BaseStrategy):
    """50-tick ON/OFF alternation."""

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
        # ON when (tick // 50) is even, OFF when odd
        cycle = intra_tick // 50
        is_on = (cycle % 2 == 0)
        memory["_cycle"] = cycle
        memory["_is_on"] = int(is_on)

        # Track market_trades = external Mark↔Mark trades visible to us
        try:
            market_trades = state.market_trades.get(self.product, []) or []
        except Exception:
            market_trades = []

        m2m_log = memory.setdefault("_m2m_log", {"ON": {}, "OFF": {}})
        for t in market_trades:
            buyer = getattr(t, "buyer", None) or ""
            seller = getattr(t, "seller", None) or ""
            qty = getattr(t, "quantity", 0)
            phase = "ON" if is_on else "OFF"
            for cp in (buyer, seller):
                if not cp or cp == "SUBMISSION":
                    continue
                d = m2m_log[phase].setdefault(cp, {"n": 0, "buy_qty": 0, "sell_qty": 0})
                d["n"] += 1
                if buyer == cp:
                    d["buy_qty"] += qty
                elif seller == cp:
                    d["sell_qty"] += qty

        # Track our own fills
        cp_log = memory.setdefault("_cp_log", {})
        for f in state.own_trades.get(self.product, []):
            buyer = getattr(f, "buyer", None) or ""
            seller = getattr(f, "seller", None) or ""
            qty = getattr(f, "quantity", 0)
            for cp in (buyer, seller):
                if not cp or cp == "SUBMISSION":
                    continue
                d = cp_log.setdefault(cp, {"n": 0, "buy_qty": 0, "sell_qty": 0})
                d["n"] += 1
                if buyer == cp:
                    d["buy_qty"] += qty
                elif seller == cp:
                    d["sell_qty"] += qty

        # Trading
        if not is_on:
            return [], 0  # OFF: no quotes

        bid_p = int(book.best_bid) + 1 if int(book.best_bid) + 1 < int(book.best_ask) else int(book.best_bid)
        ask_p = int(book.best_ask) - 1 if int(book.best_ask) - 1 > int(book.best_bid) else int(book.best_ask)
        size = 30
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
        out["IsOn"] = float(memory.get("_is_on", 0))
        # Log differential Mark presence between ON and OFF
        m2m = memory.get("_m2m_log", {})
        on = m2m.get("ON", {})
        off = m2m.get("OFF", {})
        for cp in set(list(on.keys()) + list(off.keys())):
            cp_safe = cp.replace(" ", "_")
            out[f"M2M_{cp_safe}_ON_n"] = float(on.get(cp, {}).get("n", 0))
            out[f"M2M_{cp_safe}_OFF_n"] = float(off.get(cp, {}).get("n", 0))
        return out
