"""ForcedLongBuyer — buy taker until reaching `target_long` position, then idle.

Use case: cheap deep-OTM hedge. Buy 100 long VEV_6000 at price 0.5 (cost ~50)
in the first N ticks of each day. Asymmetric payoff:
  - Normal day: option expires worthless, lose ~50 (negligible vs baseline 157k).
  - Crash day: VELVET drops 5%+, option spikes to 5+, gain +500.

Params:
  target_long           : long position to reach (default 100)
  buy_chunk_size        : max qty per tick to buy (default 5)
  max_entry_ticks       : stop trying after this many ticks (default 1000 = 10% of day)
  cancel_offset_ticks   : also post a passive bid this many ticks below mid (default 0 = no passive)
  log_flush_ts          : trace flush interval
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class ForcedLongBuyerStrategy(BaseStrategy):
    """Buy at ask aggressively until target_long reached."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        target = int(self.params.get("target_long", 100))
        chunk = int(self.params.get("buy_chunk_size", 5))
        max_entry_ticks = int(self.params.get("max_entry_ticks", 1000))
        ts = int(state.timestamp)

        # Compute intraday tick (each day starts at ts=0 after engine reset)
        intra_ticks = ts // 100  # ts increments by 100 per tick

        # Already at target → idle
        if position >= target:
            memory["_flb_state"] = "REACHED"
            return [], 0

        # Past entry window → idle (give up)
        if intra_ticks > max_entry_ticks:
            memory["_flb_state"] = "TIMEOUT"
            return [], 0

        # Compute taker buy
        if book.best_ask is None:
            return [], 0

        avail = book.best_ask_volume or chunk
        need = target - position
        qty = min(chunk, avail, need)
        if qty <= 0:
            return [], 0

        memory["_flb_state"] = "BUYING"
        memory["_flb_position"] = position
        memory["_flb_target"] = target

        return [Order(self.product, int(book.best_ask), int(qty))], 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (s := memory.get("_flb_state")) is not None:
            # Map state to numeric for plotting
            mapping = {"REACHED": 1.0, "TIMEOUT": 0.5, "BUYING": 0.0}
            out["FLB_state"] = mapping.get(s, 0.0)
        return out
