from __future__ import annotations

from prosperity.strategies.round_4.theo.hydro_mv_v9_adaptive_fair import R4HydroMVV9AdaptiveFairStrategy


class R4HydroMVV10LiveDefensiveStrategy(R4HydroMVV9AdaptiveFairStrategy):
    """HYDRO v10: v9 adaptive fair plus a very late same-side taker airbag.

    Research finding:
    - The dominant live failure mode was not passive quoting itself, but
      aggressive same-side takers that kept pressing inventory into a trend.
    - Fully reactive fair-following kills the historical edge.
    - The best compromise is therefore:
      - keep the v9 adaptive anchor/fair engine,
      - add a modest inventory-triggered fair pull,
      - and only disable same-side takers at near-limit inventory in an
        adverse-trend regime.

    v10 is intentionally conservative: the taker kill-switch should behave like
    an airbag, not like a primary signal.
    """

