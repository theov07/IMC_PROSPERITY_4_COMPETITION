from __future__ import annotations

from prosperity.strategies.round_4.theo.hydro_mv_v11_early_kill_fairsoft import (
    R4HydroMVV11EarlyKillFairSoftStrategy,
)


class R4HydroMVV12VolTailKillStrategy(R4HydroMVV11EarlyKillFairSoftStrategy):
    """HYDRO v12: high-vol tail fair softening plus earlier taker airbag.

    Most volatility defenses were too blunt and hurt PnL. The best compromise
    was to keep the v11 core intact, then activate slightly more fair-following
    and a slightly earlier same-side taker kill only in the upper sigma tail.
    """
