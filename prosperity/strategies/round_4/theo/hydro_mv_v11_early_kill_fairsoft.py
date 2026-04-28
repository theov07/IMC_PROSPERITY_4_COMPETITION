from __future__ import annotations

from prosperity.strategies.round_4.theo.hydro_mv_v10_live_defensive import R4HydroMVV10LiveDefensiveStrategy


class R4HydroMVV11EarlyKillFairSoftStrategy(R4HydroMVV10LiveDefensiveStrategy):
    """HYDRO v11: v10 with earlier taker airbag and a slightly softer fair.

    Design goal:
    - v10 was too late to matter in the problematic live regime; the first real
      order-level behavior change happened only once inventory was already very
      short.
    - v11 keeps the same core engine, but activates the same-side taker airbag
      earlier and lets fair follow persistent drift a bit more when inventory is
      already loaded.

    This remains intentionally conservative:
    - no hard inventory clamp,
    - no full fair-following,
    - no timestamp-specific behavior.
    """

