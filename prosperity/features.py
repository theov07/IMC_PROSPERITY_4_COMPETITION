from typing import Dict, Tuple

from prosperity.config import ProductProfile
from prosperity.market import BookSnapshot


def ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


def estimate_fair_value(
    snapshot: BookSnapshot,
    profile: ProductProfile,
    product_state: Dict[str, float],
) -> Tuple[float, Dict[str, float | str | None]]:
    previous_fair = product_state.get("fair")
    reference = snapshot.microprice or snapshot.mid_price or profile.anchor_price or previous_fair or 0.0

    if profile.fair_mode == "fixed":
        fair = profile.anchor_price if profile.anchor_price is not None else reference
    elif profile.fair_mode == "anchored_microprice":
        anchor = profile.anchor_price if profile.anchor_price is not None else reference
        blended = profile.anchor_weight * anchor + (1.0 - profile.anchor_weight) * reference
        fair = ewma(previous_fair, blended, profile.ema_alpha)
    elif profile.fair_mode == "mid_ema":
        spot = snapshot.mid_price if snapshot.mid_price is not None else reference
        fair = ewma(previous_fair, spot, profile.ema_alpha)
    else:
        fair = ewma(previous_fair, reference, profile.ema_alpha)

    product_state["fair"] = fair
    product_state["last_mid"] = snapshot.mid_price if snapshot.mid_price is not None else fair

    diagnostics: Dict[str, float | str | None] = {
        "fair_mode": profile.fair_mode,
        "fair": fair,
        "reference": reference,
        "microprice": snapshot.microprice,
        "mid_price": snapshot.mid_price,
        "imbalance": snapshot.imbalance,
    }
    return fair, diagnostics

