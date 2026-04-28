"""LiveAlphaProbeExtreme — 5-phase provocative probe to surface hidden interactions.

GOAL: in LIVE IMC (D3 first 10% = 1000 ticks), provoke the market with extreme
asymmetric quotes and observe HOW each Mark reacts. The 5 phases are:

  Phase 1 (ticks 0-199):     DARK MODE — no quotes posted
                              → baseline of who trades naturally
  Phase 2 (ticks 200-399):   TIGHT MM — penny-improve both sides, size 30
                              → MM regime, see who fills us as MM
  Phase 3 (ticks 400-599):   MEGA BID — bid at mid+2 size 100, NO ASK
                              → provoke sellers; who dumps to us?
  Phase 4 (ticks 600-799):   MEGA ASK — ask at mid-2 size 100, NO BID
                              → provoke buyers; who lifts us?
  Phase 5 (ticks 800-999):   NORMAL MM — penny-improve both sides, size 30
                              → did the participants change after provocation?

Logs per-phase per-counterparty fill stats in feature_prices.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


PHASE_BOUNDARIES = [200, 400, 600, 800, 1000]  # tick boundaries
PHASE_NAMES = ["P1_DARK", "P2_TIGHT_MM", "P3_MEGA_BID", "P4_MEGA_ASK", "P5_NORMAL_MM"]


def _phase_for_tick(intra_tick: int) -> int:
    for i, b in enumerate(PHASE_BOUNDARIES):
        if intra_tick < b:
            return i
    return len(PHASE_BOUNDARIES) - 1  # if tick >= 1000, stay in last


class LiveAlphaProbeExtremeStrategy(BaseStrategy):
    """Phase-based provocative probe."""

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
        phase = _phase_for_tick(intra_tick)
        phase_name = PHASE_NAMES[phase]
        memory["_phase"] = phase
        memory["_phase_name"] = phase_name

        # Track our fills per counterparty per phase
        cp_log = memory.setdefault("_cp_per_phase", {p: {} for p in PHASE_NAMES})
        for f in state.own_trades.get(self.product, []):
            buyer = getattr(f, "buyer", None) or ""
            seller = getattr(f, "seller", None) or ""
            qty = getattr(f, "quantity", 0)
            # Determine counterparty (the one who is NOT us)
            for cp in (buyer, seller):
                if not cp:
                    continue
                cp_log_phase = cp_log.setdefault(phase_name, {})
                cp_data = cp_log_phase.setdefault(cp, {"n": 0, "buy_qty": 0, "sell_qty": 0})
                cp_data["n"] += 1
                if buyer == cp:
                    cp_data["buy_qty"] += qty
                elif seller == cp:
                    cp_data["sell_qty"] += qty

        # Phase logic
        bid_p = int(book.best_bid)
        ask_p = int(book.best_ask)
        mid = int((bid_p + ask_p) / 2)
        orders: List[Order] = []
        limit = self.position_limit()
        buy_cap = max(0, limit - position)
        sell_cap = max(0, limit + position)

        if phase == 0:
            # P1: DARK MODE — no orders
            pass

        elif phase == 1 or phase == 4:
            # P2 / P5: TIGHT MM — penny improve both sides, size 30
            tight_bid = bid_p + 1 if bid_p + 1 < ask_p else bid_p
            tight_ask = ask_p - 1 if ask_p - 1 > bid_p else ask_p
            qty = 30
            bq = min(qty, buy_cap)
            aq = min(qty, sell_cap)
            if bq > 0:
                orders.append(Order(self.product, tight_bid, bq))
            if aq > 0:
                orders.append(Order(self.product, tight_ask, -aq))

        elif phase == 2:
            # P3: MEGA BID — bid HIGH, no ask
            mega_bid_p = ask_p - 1  # AT the ask (stop just below to be passive)
            # Cap at +2 above current best_bid to avoid running too high
            target_p = min(mega_bid_p, bid_p + 2)
            mega_qty = min(100, buy_cap)
            if mega_qty > 0:
                orders.append(Order(self.product, target_p, mega_qty))

        elif phase == 3:
            # P4: MEGA ASK — ask LOW, no bid
            mega_ask_p = bid_p + 1
            target_p = max(mega_ask_p, ask_p - 2)
            mega_qty = min(100, sell_cap)
            if mega_qty > 0:
                orders.append(Order(self.product, target_p, -mega_qty))

        memory["_position"] = position
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        out["Phase"] = float(memory.get("_phase", 0))
        # Surface counterparty fills per phase (top 3 per phase)
        cp_log = memory.get("_cp_per_phase", {})
        for pname, cps in cp_log.items():
            for cp, stats in sorted(cps.items(), key=lambda kv: -kv[1]["n"])[:3]:
                cp_safe = cp.replace(" ", "_")
                key = f"{pname}_{cp_safe}_n"
                out[key] = float(stats["n"])
                out[f"{pname}_{cp_safe}_buyq"] = float(stats["buy_qty"])
                out[f"{pname}_{cp_safe}_sellq"] = float(stats["sell_qty"])
        return out
