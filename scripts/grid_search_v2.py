"""Grid search leo_fusion_b_v2 params, realistic mode, round 1.

Varies take_buy_edge_bull, startup_target, trend_inventory_cap, block_size.
Reuses BacktestEngine in-process (no subprocess overhead). Patches the
member override dict before each run and reloads the submissions.trader
module so the patched params are picked up.
"""

from __future__ import annotations

import importlib
import itertools
from pathlib import Path

from prosperity import config as cfg
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode


DATA_DIR = Path("data")
ROUND = 1
MEMBER = "leo_fusion_b_v2"
DAYS = ["-2", "-1", "0"]

# Grid
GRID = {
    "take_buy_edge_bull": [-8.0, -10.0, -12.0, -15.0],
    "startup_target":     [40, 55, 70],
    "trend_inventory_cap":[74, 78, 80],
    "block_size":         [100, 150, 200],
}


def patch_and_run(combo: dict) -> float:
    ipr = cfg.MEMBER_OVERRIDES[MEMBER][1]["INTARIAN_PEPPER_ROOT"]
    for k, v in combo.items():
        ipr.params[k] = v

    # Reload submission module so Trader picks up fresh config
    import submissions.leo_fusion_b_v2 as sub_mod
    importlib.reload(sub_mod)

    engine = BacktestEngine(DATA_DIR, f"submissions.{MEMBER}", round_num=ROUND)
    total = 0.0
    for day in DAYS:
        summary = engine.run_day(day, mode=TradeMatchingMode.realistic)
        total += float(summary.pnl)
    return total


def main() -> None:
    keys = list(GRID.keys())
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    print(f"Running {len(combos)} combinations...")

    results: list[tuple[float, dict]] = []
    baseline_params = {
        "take_buy_edge_bull": -8.0,
        "startup_target": 40,
        "trend_inventory_cap": 74,
        "block_size": 200,
    }

    for i, values in enumerate(combos):
        combo = dict(zip(keys, values))
        pnl = patch_and_run(combo)
        results.append((pnl, combo))
        marker = " <- baseline" if combo == baseline_params else ""
        print(f"[{i+1:3d}/{len(combos)}] pnl={pnl:10.0f}  {combo}{marker}")

    results.sort(key=lambda t: -t[0])
    print("\nTop 10:")
    for pnl, combo in results[:10]:
        print(f"  {pnl:10.0f}  {combo}")


if __name__ == "__main__":
    main()
