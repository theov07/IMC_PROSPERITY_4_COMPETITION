"""Theo round-2 clean generalized v3.

Adds a max-inventory sell guard without touching the gap-exploit engine.
"""

from __future__ import annotations

from typing import Optional, Set, Tuple

from prosperity.strategies.round_2.theo.theo_best_clean_generalized_v2 import (
    TheoBestCleanGeneralizedV2Strategy,
)


class TheoBestCleanGeneralizedV3Strategy(TheoBestCleanGeneralizedV2Strategy):
    """V3: suppress regular sells at max inventory when the ask is not rich enough."""

    def _max_inventory_sell_guard_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        guard_position = int(
            self.params.get("max_inventory_sell_guard_position", self.position_limit())
        )
        guard_threshold = float(self.params.get("max_inventory_sell_guard_threshold", 8.0))

        active = (
            best_ask is not None
            and position >= guard_position
            and float(best_ask) < fair_value + guard_threshold
        )

        self._memory["max_inventory_sell_guard_active"] = int(active)
        self._memory["max_inventory_sell_guard_ref"] = fair_value + guard_threshold
        return active

    def _compute_passive_sizes(
        self,
        position: int,
        buy_cap: int,
        sell_cap: int,
        pending_buy: int,
        pending_sell: int,
        stats,
        regime,
        entry_reference: float,
        book,
        bid_price: int,
        ask_price: int,
        buy_taker_prices: Set[int],
    ) -> Tuple[int, int, Optional[int], int, int, bool]:
        buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode = super()._compute_passive_sizes(
            position,
            buy_cap,
            sell_cap,
            pending_buy,
            pending_sell,
            stats,
            regime,
            entry_reference,
            book,
            bid_price,
            ask_price,
            buy_taker_prices,
        )

        if self._max_inventory_sell_guard_active(
            position=position,
            best_ask=book.best_ask,
            fair_value=float(stats["fair_value"]),
        ):
            sell_size = 0

        return buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode
