"""Theo round-2 clean generalized v6.

Adds a generalized early-build price-improvement layer on top of v5.
"""

from __future__ import annotations

from typing import Any, Dict

from prosperity.strategies.round_2.theo.theo_best_clean_generalized_v5 import (
    TheoBestCleanGeneralizedV5Strategy,
)


class TheoBestCleanGeneralizedV6Strategy(TheoBestCleanGeneralizedV5Strategy):
    """V6: keep the strategy intact and improve startup fills when the ask runs hot."""

    def _apply_startup_price_improvement(
        self,
        *,
        state,
        stats: Dict[str, float],
        stretch: float,
        book,
        position: int,
        memory: Dict[str, Any],
        regime: Dict[str, Any],
    ) -> Dict[str, Any]:
        tuned = dict(regime)

        reserve_normal_cap = self._reserve_normal_inventory_cap()
        improvement_start_position = int(
            self.params.get(
                "startup_price_improve_start_position",
                max(0, reserve_normal_cap - 21),
            )
        )
        improvement_holdback = int(self.params.get("startup_price_improve_holdback", 8))
        improvement_hot_threshold = float(self.params.get("startup_price_improve_hot_threshold", 4.0))
        improvement_release_threshold = float(
            self.params.get("startup_price_improve_release_threshold", 1.5)
        )
        improvement_hot_stretch = float(self.params.get("startup_price_improve_hot_stretch", 0.75))
        improvement_take_cap = int(self.params.get("startup_price_improve_take_cap", 3))
        improvement_passive_buy_cap = int(
            self.params.get("startup_price_improve_passive_buy_cap", 4)
        )
        improvement_anchor_extra_spread = float(
            self.params.get("startup_price_improve_anchor_extra_spread", 1.0)
        )
        improvement_end_ts = int(
            self.params.get(
                "startup_price_improve_end_ts",
                self.params.get("startup_delayed_finish_ts", 3000),
            )
        )

        best_ask = book.best_ask
        ask_richness = 0.0 if best_ask is None else float(best_ask) - float(stats["fair_value"])
        release_ready = (
            tuned["on_dip"]
            or tuned["current_pullback_ready"]
            or ask_richness <= improvement_release_threshold
            or float(stats["residual_z"]) <= 0.0
        )

        improvement_active = (
            tuned["build_phase"]
            and tuned["startup_window_active"]
            and not tuned["gap_rebuy_mode"]
            and int(state.timestamp) <= improvement_end_ts
            and position >= improvement_start_position
            and best_ask is not None
            and ask_richness >= improvement_hot_threshold
            and stretch >= improvement_hot_stretch
            and not release_ready
        )

        if improvement_active:
            improved_target_cap = max(
                improvement_start_position,
                reserve_normal_cap - improvement_holdback,
            )
            tuned["active_build_target"] = min(
                int(tuned["active_build_target"]),
                improved_target_cap,
            )
            tuned["buy_take_cap"] = min(int(tuned["buy_take_cap"]), improvement_take_cap)
            tuned["startup_fast_passive_buy"] = min(
                int(tuned["startup_fast_passive_buy"]),
                improvement_passive_buy_cap,
            )
            tuned["startup_cold_passive_buy"] = min(
                int(tuned["startup_cold_passive_buy"]),
                improvement_passive_buy_cap,
            )
            tuned["startup_anchor_bid_spread"] = float(tuned["startup_anchor_bid_spread"]) + improvement_anchor_extra_spread

        memory["startup_price_improve_active"] = int(improvement_active)
        memory["startup_price_improve_richness"] = ask_richness
        memory["startup_price_improve_release_ready"] = int(release_ready)
        memory["startup_price_improve_cap"] = (
            max(improvement_start_position, reserve_normal_cap - improvement_holdback)
            if improvement_active
            else int(tuned["active_build_target"])
        )
        return tuned

    def _compute_regime(
        self,
        state,
        stats: Dict[str, float],
        spot: float,
        stretch: float,
        book,
        position: int,
        memory: Dict[str, Any],
    ) -> Dict[str, Any]:
        regime = super()._compute_regime(state, stats, spot, stretch, book, position, memory)
        return self._apply_startup_price_improvement(
            state=state,
            stats=stats,
            stretch=stretch,
            book=book,
            position=position,
            memory=memory,
            regime=regime,
        )
