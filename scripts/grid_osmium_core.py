"""Grid search core osmium_mr params around current champion."""

from __future__ import annotations

import itertools
from pathlib import Path

from prosperity import config as cfg
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode

MEMBER = "leo_osmium_only"
ROUND = 1
DAYS = ["-2", "-1", "0"]

GRID = {
    "ar_gain":                    [0.6, 1.0, 1.2, 1.5, 2.0, 3.0],
    "take_edge":                  [1.5, 2.0, 2.5],
    "tighten_ticks":              [0, 1, 2],
    "trend_inv_target_per_tick":  [8.0, 10.0, 14.0, 20.0],
    "trend_sensitivity":          [0.5, 0.8, 1.2],
    "anchor_alpha":               [0.0, 0.002, 0.01],
}


def run(combo):
    osm = cfg.MEMBER_OVERRIDES[MEMBER][1]["ASH_COATED_OSMIUM"]
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
    print(f"Running {len(combos)} combos")
    results = []
    for i, vals in enumerate(combos):
        combo = dict(zip(keys, vals))
        p = run(combo)
        results.append((p, combo))
        if p >= 54000:
            print(f"[{i+1:4d}/{len(combos)}] osm={p:8.0f}  {combo}")
        elif (i+1) % 50 == 0:
            print(f"[{i+1:4d}/{len(combos)}] best so far={max(r[0] for r in results):.0f}")
    results.sort(key=lambda t: -t[0])
    print("\nTop 15:")
    for p, c in results[:15]:
        print(f"  osm={p:.0f}  {c}")


if __name__ == "__main__":
    main()
