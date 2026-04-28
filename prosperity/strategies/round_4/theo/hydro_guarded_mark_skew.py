from __future__ import annotations

from prosperity.strategies.round_3.guarded_anchor_mm import R3GuardedAnchorMMStrategy


class R4HydroGuardedMarkSkewStrategy(R3GuardedAnchorMMStrategy):
    """Guarded-anchor HYDRO MM with conservative counterparty-driven size skew.

    The existing guarded-anchor overlay already uses named traders to shift the
    anchor. This extension adds a small passive size skew so that when the mark
    signal is directional we lean inventory acquisition toward that side and
    shrink the adverse side.
    """

    def _compute_sizes(self, position: int, limit: int):
        bid_size, ask_size = super()._compute_sizes(position, limit)

        signal = float(getattr(self, "_memory", {}).get("_mark_signal", 0.0))
        skew = float(self.params.get("mark_size_skew", 0.0))
        clip = max(1e-9, float(self.params.get("mark_size_clip", 6.0)))
        if skew <= 0.0 or abs(signal) < 1e-9:
            return bid_size, ask_size

        strength = min(1.0, abs(signal) / clip)
        mult = 1.0 + skew * strength
        if signal > 0.0:
            bid_size *= mult
            ask_size /= mult
        else:
            ask_size *= mult
            bid_size /= mult
        return bid_size, ask_size
