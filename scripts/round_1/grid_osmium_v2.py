"""Grid search osmium_mr_v2 new params (abs thresholds + gap exploit)."""

from __future__ import annotations

import itertools
from pathlib import Path

from prosperity import config as cfg
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode

MEMBER = "leo_osmium_v2"
ROUND = 1
DAYS = ["-2", "-1", "0"]

GRID = {
    "take_abs_buy":  [None, 9995, 9990, 9985],
    "take_abs_sell": [None, 10005, 10010, 10015],
    "gap_trigger_min": [0, 8, 12],
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
        print(f"[{i+1:3d}/{len(combos)}] osm={p:8.0f}  {combo}")
    results.sort(key=lambda t: -t[0])
    print("\nTop 10:")
    for p, c in results[:10]:
        print(f"  osm={p:.0f}  {c}")


if __name__ == "__main__":
    main()
