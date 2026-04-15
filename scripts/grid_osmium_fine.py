"""Narrower grid around 55917 candidate."""

from __future__ import annotations

import itertools
from pathlib import Path

from prosperity import config as cfg
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode

MEMBER = "leo_osmium_only"
ROUND = 1
DAYS = ["-2", "-1", "0"]

GRID = {
    "ar_gain":                    [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    "take_edge":                  [1.5, 1.75, 2.0, 2.25],
    "trend_inv_target_per_tick":  [10.0, 12.0, 14.0, 16.0, 20.0],
    "trend_sensitivity":          [0.6, 0.7, 0.8, 0.9, 1.0],
}


def run(combo):
    osm = cfg.MEMBER_OVERRIDES[MEMBER][1]["ASH_COATED_OSMIUM"]
    osm.params["tighten_ticks"] = 1
    osm.params["anchor_alpha"] = 0.0
    for k, v in combo.items():
        osm.params[k] = v
    eng = BacktestEngine(Path("data"), f"submissions.{MEMBER}", round_num=ROUND)
    total = 0.0
    for d in DAYS:
        s = eng.run_day(d, mode=TradeMatchingMode.realistic)
        ps = s.product_summaries.get("ASH_COATED_OSMIUM")
        if ps:
            total += float(ps.pnl)
    return total


def main():
    keys = list(GRID.keys())
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    print(f"Running {len(combos)} combos", flush=True)
    results = []
    for i, vals in enumerate(combos):
        combo = dict(zip(keys, vals))
        p = run(combo)
        results.append((p, combo))
        print(f"[{i+1:3d}/{len(combos)}] osm={p:8.0f}  {combo}", flush=True)
    results.sort(key=lambda t: -t[0])
    print("\nTop 15:", flush=True)
    for p, c in results[:15]:
        print(f"  osm={p:.0f}  {c}", flush=True)


if __name__ == "__main__":
    main()
