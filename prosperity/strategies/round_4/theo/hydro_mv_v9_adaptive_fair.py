from __future__ import annotations

from typing import Dict

from prosperity.strategies.round_4.theo.hydro_mv_v6_invaware import R4HydroMVV6InvAwareStrategy


class R4HydroMVV9AdaptiveFairStrategy(R4HydroMVV6InvAwareStrategy):
    """HYDRO v9: v8 core + confidence-weighted fair that tracks persistent drift.

    The baseline v8 fair stays tightly anchored near 10000, which is great when
    HYDRO mean-reverts around the anchor but can become too directional when the
    market trends away for a long time. v9 keeps the same MM core and trader
    overlays, but makes the anchor "softer":

    - when smoothed drift versus 10000 is small, fair stays mostly anchored
    - when drift persists, fair partially follows the market
    - a floor on anchor confidence preserves the profitable mean-reversion core
    """

    def _update_ar(
        self,
        raw_mid: float,
        memory: Dict[str, object],
    ) -> tuple[float, float, float]:
        ms_hl = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        ar_hl = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        ar_mom = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        anchor_fixed = float(self.params.get("anchor_price", 10000.0))
        drift = mid_s - anchor_fixed
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

        fair_base = confidence * anchor_fixed + (1.0 - confidence) * mid_s
        memory["_anchor_ema"] = fair_base
        memory["_fair_base"] = fair_base

        ar_gain = float(self.params.get("ar_gain", 7.0))
        fair_value = fair_base - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

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
        if (v := memory.get("_fair_base")) is not None:
            out["FairBase"] = float(v)
        if (v := memory.get("_anchor_confidence")) is not None:
            out["AnchorConfidence"] = float(v)
        if (v := memory.get("_anchor_drift_ewma")) is not None:
            out["AnchorDriftEwma"] = float(v)
        return out
