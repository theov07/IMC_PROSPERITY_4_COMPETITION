"""Theo round-2 clean generalized v4.

Keeps a small inventory reserve for deep-dump buys without rewriting the
existing gap-exploit engine.
"""

from __future__ import annotations

from typing import Optional, Set, Tuple

from prosperity.strategies.round_2.theo.theo_best_clean_generalized_v3 import (
    TheoBestCleanGeneralizedV3Strategy,
)


class TheoBestCleanGeneralizedV4Strategy(TheoBestCleanGeneralizedV3Strategy):
    """V4: keep 3 slots of reserve unless a deep dump unlocks the reserve."""

    def _reserve_inventory_size(self) -> int:
        return max(0, int(self.params.get("dump_reserve_inventory", 3)))

    def _reserve_normal_inventory_cap(self) -> int:
        return max(0, self.position_limit() - self._reserve_inventory_size())

    def _dump_reserve_release_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        reserve_size = self._reserve_inventory_size()
        reserve_threshold = float(self.params.get("dump_reserve_release_threshold", 3.0))
        reserve_min_position = int(
            self.params.get(
                "dump_reserve_release_min_position",
                self._reserve_normal_inventory_cap(),
            )
        )

        active = (
            reserve_size > 0
            and best_ask is not None
            and position >= reserve_min_position
            and float(best_ask) <= fair_value - reserve_threshold
        )

        self._memory["dump_reserve_release_active"] = int(active)
        self._memory["dump_reserve_release_ref"] = fair_value - reserve_threshold
        self._memory["dump_reserve_normal_cap"] = self._reserve_normal_inventory_cap()
        return active

    def _reserve_buy_room(
        self,
        *,
        position: int,
        pending_buy: int,
        release_active: bool,
    ) -> int:
        target_cap = self.position_limit() if release_active else self._reserve_normal_inventory_cap()
        return max(0, target_cap - position - pending_buy)

    def _buy_takers(
        self,
        order_depth,
        fv: float,
        position: int,
        buy_cap: int,
        regime,
    ):
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        release_active = self._dump_reserve_release_active(
            position=position,
            best_ask=best_ask,
            fair_value=float(fv),
        )
        capped_buy_cap = min(
            buy_cap,
            self._reserve_buy_room(
                position=position,
                pending_buy=0,
                release_active=release_active,
            ),
        )
        if capped_buy_cap <= 0:
            return [], 0, 0, set()

        capped_regime = dict(regime)
        capped_regime["buy_take_cap"] = min(int(regime["buy_take_cap"]), capped_buy_cap)
        return super()._buy_takers(order_depth, fv, position, capped_buy_cap, capped_regime)

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
        release_active = self._dump_reserve_release_active(
            position=position,
            best_ask=book.best_ask,
            fair_value=float(stats["fair_value"]),
        )
        capped_buy_cap = min(
            buy_cap,
            self._reserve_buy_room(
                position=position,
                pending_buy=pending_buy,
                release_active=release_active,
            ),
        )

        return super()._compute_passive_sizes(
            position,
            capped_buy_cap,
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
