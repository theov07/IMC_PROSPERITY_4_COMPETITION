"""Grid search OSMIUM params on theo_round1_v24 base (naive_tight_mm_v10 mean_rev).

Keeps IPR config fixed (already matching leo_fusion_b_v2 at 238k).
Varies take_edge, tighten_ticks, trend_inv_target_per_tick, trend_sensitivity.
"""

from __future__ import annotations

import importlib
import itertools
from pathlib import Path

from prosperity import config as cfg
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode

MEMBER = "theo_round1_v24"
ROUND = 1
DAYS = ["-2", "-1", "0"]

GRID = {
    "take_edge":                  [0.5, 1.0, 2.0, 3.0],
    "tighten_ticks":              [1, 2, 3, 5],
    "trend_inv_target_per_tick":  [4.0, 6.0, 10.0],
    "trend_sensitivity":          [0.3, 0.5, 0.8],
}


def patch_and_run(combo: dict) -> tuple[float, float]:
    osm = cfg.MEMBER_OVERRIDES[MEMBER][1]["ASH_COATED_OSMIUM"]
    for k, v in combo.items():
        osm.params[k] = v
    import submissions.theo_round1_v24 as sm
    importlib.reload(sm)
    engine = BacktestEngine(Path("data"), f"submissions.{MEMBER}", round_num=ROUND)
    total = 0.0
    osm_total = 0.0
    for d in DAYS:
        s = engine.run_day(d, mode=TradeMatchingMode.realistic)
        total += float(s.pnl)
        ps = s.product_summaries.get("ASH_COATED_OSMIUM")
        if ps:
            osm_total += float(ps.pnl)
    return total, osm_total


def main() -> None:
    keys = list(GRID.keys())
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    print(f"Running {len(combos)} combinations...")
    results = []
    for i, vals in enumerate(combos):
        combo = dict(zip(keys, vals))
        tot, osm = patch_and_run(combo)
        results.append((tot, osm, combo))
        print(f"[{i+1:3d}/{len(combos)}] total={tot:.0f}  osm={osm:.0f}  {combo}")
    results.sort(key=lambda t: -t[1])
    print("\nTop 10 by OSMIUM PnL:")
    for tot, osm, combo in results[:10]:
        print(f"  osm={osm:.0f}  total={tot:.0f}  {combo}")


if __name__ == "__main__":
    main()
