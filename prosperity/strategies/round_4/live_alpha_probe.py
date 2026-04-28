"""LiveAlphaProbe — passive MM with extensive trade-flow logging for LIVE analysis.

GOAL: in the LIVE round, observe HOW each Mark interacts with our quotes.
Specifically:
  - Who fills our bids? (buyer = Mark X) → these are participants we sell TO
  - Who fills our asks? (seller = Mark X) → these are participants who buy FROM us
  - Do specific Marks consistently lift our asks (= they think we're cheap)?
  - Do specific Marks consistently hit our bids (= they think we're rich)?

Strategy is INTENTIONALLY PASSIVE and SLIGHTLY EXAGGERATED to maximize signal:
  - Tight passive bid + tight passive ask (penny improve)
  - Slightly bigger size than baseline (more fill volume to study)
  - Logs every fill with counterparty for post-run analysis

Use this only as a research probe — not as our main upload.

Data captured:
  - per_counterparty_fills: {Mark X: {buy_count, sell_count, buy_qty, sell_qty}}
  - per_tick_position: rolling position trajectory
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class LiveAlphaProbeStrategy(BaseStrategy):
    """Passive MM with detailed counterparty trace for LIVE alpha discovery."""

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

        # Track our own fills (recently completed trades)
        own_fills = state.own_trades.get(self.product, [])
        cp_log = memory.setdefault("_cp_fills", {})
        for f in own_fills:
            buyer = getattr(f, "buyer", None) or ""
            seller = getattr(f, "seller", None) or ""
            qty = getattr(f, "quantity", 0)
            # Determine which side WE were on by checking if our identifier matches
            # In live, "SUBMISSION" or our team name could be in buyer or seller field
            # For probe: log all interaction
            for cp in (buyer, seller):
                if not cp:
                    continue
                if cp not in cp_log:
                    cp_log[cp] = {"count": 0, "buy_qty": 0, "sell_qty": 0}
                cp_log[cp]["count"] += 1
                if buyer == cp:
                    cp_log[cp]["buy_qty"] += qty
                elif seller == cp:
                    cp_log[cp]["sell_qty"] += qty

        # Posting strategy: penny-improved passive on both sides
        size = int(self.params.get("probe_size", 30))
        bid_price = int(book.best_bid + 1) if book.best_bid + 1 < book.best_ask else int(book.best_bid)
        ask_price = int(book.best_ask - 1) if book.best_ask - 1 > book.best_bid else int(book.best_ask)

        # Don't overbuild (respect position limit)
        buy_cap = max(0, self.position_limit() - position)
        sell_cap = max(0, self.position_limit() + position)

        bid_qty = min(size, buy_cap)
        ask_qty = min(size, sell_cap)

        orders: List[Order] = []
        if bid_qty > 0:
            orders.append(Order(self.product, bid_price, bid_qty))
        if ask_qty > 0:
            orders.append(Order(self.product, ask_price, -ask_qty))

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        cp_log = memory.get("_cp_fills", {})
        # Surface top counterparty interaction counts
        for cp, stats in sorted(cp_log.items(), key=lambda kv: -kv[1]["count"])[:5]:
            safe = cp.replace(" ", "_")
            out[f"CP_{safe}_n"] = float(stats["count"])
            out[f"CP_{safe}_buyqty"] = float(stats["buy_qty"])
            out[f"CP_{safe}_sellqty"] = float(stats["sell_qty"])
        return out
