"""Theo round-2 clean generalized v7.

Adds a recent-low patience layer to avoid late startup fills that are
meaningfully above the best asks seen just beforehand.
"""

from __future__ import annotations

from typing import Any, Dict

from prosperity.strategies.round_2.theo.theo_best_clean_generalized_v6 import (
    TheoBestCleanGeneralizedV6Strategy,
)


class TheoBestCleanGeneralizedV7Strategy(TheoBestCleanGeneralizedV6Strategy):
    """V7: keep v6 intact and slow the last startup buys when price runs above recent lows."""

    def _apply_startup_recent_low_patience(
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

        best_ask = book.best_ask
        recent_window = int(self.params.get("startup_recent_low_window", 12))
        recent_asks = memory.setdefault("startup_recent_best_asks", [])
        if best_ask is not None:
            recent_asks.append(int(best_ask))
            if len(recent_asks) > recent_window:
                del recent_asks[:-recent_window]

        recent_low = min(recent_asks) if recent_asks else best_ask
        if recent_low is None or best_ask is None:
            memory["startup_recent_low_patience_active"] = 0
            return tuned

        reserve_normal_cap = self._reserve_normal_inventory_cap()
        patience_start_position = int(
            self.params.get("startup_recent_low_start_position", max(0, reserve_normal_cap - 29))
        )
        patience_holdback = int(self.params.get("startup_recent_low_holdback", 6))
        patience_gap_threshold = float(self.params.get("startup_recent_low_gap_threshold", 2.0))
        patience_release_gap = float(self.params.get("startup_recent_low_release_gap", 0.5))
        patience_hot_stretch = float(self.params.get("startup_recent_low_hot_stretch", 0.4))
        patience_take_cap = int(self.params.get("startup_recent_low_take_cap", 2))
        patience_passive_buy_cap = int(self.params.get("startup_recent_low_passive_buy_cap", 3))
        patience_anchor_extra_spread = float(
            self.params.get("startup_recent_low_anchor_extra_spread", 1.0)
        )
        patience_buy_edge_floor = float(self.params.get("startup_recent_low_buy_edge_floor", 1.0))
        patience_end_ts = int(
            self.params.get(
                "startup_recent_low_end_ts",
                self.params.get("startup_delayed_finish_ts", 3000),
            )
        )

        recent_gap = float(best_ask) - float(recent_low)
        release_ready = (
            tuned["on_dip"]
            or tuned["current_pullback_ready"]
            or recent_gap <= patience_release_gap
            or float(stats["residual_z"]) <= 0.0
        )
        patience_active = (
            tuned["build_phase"]
            and tuned["startup_window_active"]
            and not tuned["gap_rebuy_mode"]
            and int(state.timestamp) <= patience_end_ts
            and position >= patience_start_position
            and recent_gap >= patience_gap_threshold
            and stretch >= patience_hot_stretch
            and not release_ready
        )

        if patience_active:
            patience_cap = max(patience_start_position, reserve_normal_cap - patience_holdback)
            tuned["active_build_target"] = min(int(tuned["active_build_target"]), patience_cap)
            tuned["buy_take_cap"] = min(int(tuned["buy_take_cap"]), patience_take_cap)
            tuned["buy_edge"] = max(float(tuned["buy_edge"]), patience_buy_edge_floor)
            tuned["startup_fast_passive_buy"] = min(
                int(tuned["startup_fast_passive_buy"]),
                patience_passive_buy_cap,
            )
            tuned["startup_cold_passive_buy"] = min(
                int(tuned["startup_cold_passive_buy"]),
                patience_passive_buy_cap,
            )
            tuned["startup_anchor_bid_spread"] = float(tuned["startup_anchor_bid_spread"]) + patience_anchor_extra_spread

        memory["startup_recent_low_patience_active"] = int(patience_active)
        memory["startup_recent_low_gap"] = recent_gap
        memory["startup_recent_low_value"] = int(recent_low)
        memory["startup_recent_low_release_ready"] = int(release_ready)
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
        return self._apply_startup_recent_low_patience(
            state=state,
            stats=stats,
            stretch=stretch,
            book=book,
            position=position,
            memory=memory,
            regime=regime,
        )
