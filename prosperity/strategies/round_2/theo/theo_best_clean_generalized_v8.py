"""Theo round-2 clean generalized v8.

Keeps a hard inventory reserve throughout the simulation and lets only the
buy-gap mirror consume that reserve.
"""

from __future__ import annotations

from typing import Optional

from prosperity.strategies.round_2.theo.theo_best_clean_generalized_v7 import (
    TheoBestCleanGeneralizedV7Strategy,
)


class TheoBestCleanGeneralizedV8Strategy(TheoBestCleanGeneralizedV7Strategy):
    """V8: hold a fixed reserve and disable the normal dump-release path."""

    def _hard_reserve_release_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        del position, best_ask, fair_value
        self._memory["dump_reserve_release_active"] = 0
        self._memory["dump_reserve_release_ref"] = None
        self._memory["dump_reserve_normal_cap"] = self._reserve_normal_inventory_cap()
        return False

    def _dump_reserve_release_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        return self._hard_reserve_release_active(
            position=position,
            best_ask=best_ask,
            fair_value=fair_value,
        )
