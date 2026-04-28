from __future__ import annotations

from typing import Dict

from prosperity.strategies.round_4.theo.hydro_mv_v6_invaware import R4HydroMVV6InvAwareStrategy


class R4HydroMVV11MarkOracleStrategy(R4HydroMVV6InvAwareStrategy):
    """HYDRO v11: Non-hardcoded oracle anchor — v9's adaptive confidence against a
    drifting reference instead of the fixed price 10000.

    Problem with v9: `anchor_fixed = 10000` is hardcoded.  If HYDROGEL genuinely
    re-anchors to a different level in the live competition, v9 will fight the trend
    indefinitely (its confidence stays at the min floor, and `0.45 × 10000` keeps
    pulling fair toward 10000 even when the true fair has moved).

    v11 fix — minimal, surgical:
    - A very slow EWMA of the observed mid (half-life `oracle_hl`, default 20 000
      ticks ≈ 33 min) becomes the "oracle anchor" — effectively a drift-free
      background estimate of where HYDROGEL actually lives.
    - The SAME adaptive-confidence formula from v9 is applied, but against
      `oracle_anchor` instead of the literal `10000`.
    - On back-test, `oracle_anchor` barely moves from 10000 (half-life 20 000 ticks
      >> 10 000 ticks per day), so the strategy is essentially identical to v9.
    - In live trading, if HYDROGEL drifts to 9800 for days, the oracle slowly
      follows and the strategy re-anchors rather than fighting indefinitely.

    Key invariant: on historical data this strategy should reproduce v9's PnL
    within a few percent; any deviation is a tuning opportunity, not a regression.
    """

    def _update_ar(
        self,
        raw_mid: float,
        memory: Dict[str, object],
    ) -> tuple[float, float, float]:
        # ── Mid smoother (identical to v9) ────────────────────────────────
        ms_hl = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s = (
            raw_mid
            if prev_ms is None
            else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        )
        memory["_mid_smooth"] = mid_s

        # ── AR momentum (identical to v9) ─────────────────────────────────
        ar_hl = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        ar_mom = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        # ── Oracle anchor: very slow EWMA of mid ──────────────────────────
        # Replaces the literal `10000` in v9.  Half-life of 20 000 ticks
        # (≈ 33 min) means the anchor barely moves during a single 10 000-tick
        # day, but over weeks of live trading it genuinely tracks the regime.
        oracle_hl = float(self.params.get("oracle_hl", 20000.0))
        oracle_alpha = 1.0 - 0.5 ** (1.0 / oracle_hl)
        prev_oracle = memory.get("_oracle_anchor")
        if prev_oracle is None:
            # Initialise to anchor_price param (default 10000) as the best prior.
            init = float(self.params.get("anchor_price", 10000.0))
            oracle_anchor = init
        else:
            oracle_anchor = oracle_alpha * mid_s + (1.0 - oracle_alpha) * float(prev_oracle)
        memory["_oracle_anchor"] = oracle_anchor

        # ── Adaptive confidence (identical structure to v9, but vs oracle) ─
        drift = mid_s - oracle_anchor
        drift_alpha = float(self.params.get("adaptive_drift_alpha", 0.004))
        prev_drift = float(memory.get("_anchor_drift_ewma", 0.0))
        drift_ewma = drift_alpha * drift + (1.0 - drift_alpha) * prev_drift
        memory["_anchor_drift_ewma"] = drift_ewma

        mean_rev = float(self.params.get("adaptive_mean_rev", 4.0))
        trend = float(self.params.get("adaptive_trend", 50.0))
        abs_drift = abs(drift_ewma)
        if abs_drift <= mean_rev:
            confidence = 1.0
        elif abs_drift >= trend:
            confidence = 0.0
        else:
            confidence = 1.0 - (abs_drift - mean_rev) / max(1e-9, trend - mean_rev)

        confidence = max(
            float(self.params.get("adaptive_conf_min", 0.45)),
            min(float(self.params.get("adaptive_conf_max", 1.0)), confidence),
        )
        memory["_anchor_confidence"] = confidence

        # fair_base is the blended anchor — same formula as v9, just oracle-relative
        fair_base = confidence * oracle_anchor + (1.0 - confidence) * mid_s
        memory["_anchor_ema"] = fair_base
        memory["_fair_base"] = fair_base

        # ── Fair value = fair_base + AR correction (identical to v9) ──────
        ar_gain = float(self.params.get("ar_gain", 7.0))
        fair_value = fair_base - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        # ── Deviation smoothing (identical to v9) ─────────────────────────
        raw_dev = mid_s - fair_value
        dev_hl = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s = float(memory.get("_dev_smooth", raw_dev))
        dev_s = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s
        memory["_dev_raw"] = raw_dev

        return mid_s, fair_value, dev_s

    def feature_prices(self, memory: Dict[str, object]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (v := memory.get("_oracle_anchor")) is not None:
            out["OracleAnchor"] = float(v)
        return out
