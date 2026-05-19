"""Quantify trade-off between aggressive (v14b) vs defensive (v40/v41/v32) submissions.

Hypothesis: live regime continues for the regime-flipped products.
Estimate live impact under multiple regime assumptions.

For each variant, compute:
  bt_pnl_3day              (from backtest)
  expected_live_alpha      (live PnL extrapolated to 3 days, adjusting for products dropped)
  worst_case_live          (assume regime worsens 2x)
  best_case_live           (assume regime reverts)
  expected_value           (50/50 between continue and revert)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import re

ROOT = Path(__file__).resolve().parents[3]
COMP = ROOT / "artifacts" / "r5_compare"
LIVE = ROOT / "artifacts" / "r5_live" / "analysis" / "live_per_product_pnl.csv"


def parse_per_product(filepath: Path) -> dict:
    if not filepath.exists():
        return {}
    with open(filepath, encoding='utf-8', errors='replace') as f:
        txt = f.read()
    out = {}
    cur = None
    for line in txt.splitlines():
        m = re.match(r'\s+([A-Z][A-Z0-9_]+)\s+\│\s*day\s+\d', line)
        if m: cur = m.group(1)
        if 'subtotal' in line and cur:
            parts = re.split(r'[│|]', line)
            if len(parts) > 2:
                pnl_match = re.search(r'([-]?[\d,]+)', parts[2])
                if pnl_match:
                    out[cur] = int(pnl_match.group(1).replace(',',''))
            cur = None
    return out


def main():
    # Load live PnL
    df_live = pd.read_csv(LIVE, index_col=0)
    live_pnl = df_live.iloc[:, 0].to_dict()
    # Live is 999 ticks ~ 1/30 of full 30k-tick backtest, so live * 30 = "live extrapolated 3-day"
    live_3day = {k: v * 30 for k, v in live_pnl.items()}

    # Variants to compare
    variants = {
        "v14b": "v14b.txt",
        "v28_drop_4": "v28_drop_flipped.txt",
        "v32_def_4":  "v32_live_aware.txt",
        "v33_def_10": "v33_live_aware_broad.txt",
    }
    if (COMP / "v40_drop_planetary.txt").exists():
        variants["v40_drop_1"] = "v40_drop_planetary.txt"
    if (COMP / "v41_drop_top2.txt").exists():
        variants["v41_drop_2"] = "v41_drop_top2.txt"
    if (COMP / "v42_size_dampen.txt").exists():
        variants["v42_dampen"] = "v42_size_dampen.txt"

    print("Live regime continues — what's the expected value per variant?")
    print(f"\n{'variant':<14s} {'bt_pnl':>10s} {'live_active':>12s} {'live_3d_x30':>13s} {'EV_50/50':>11s}")

    for name, fp in variants.items():
        bt_per_product = parse_per_product(COMP / fp)
        if not bt_per_product:
            continue
        bt_total = sum(bt_per_product.values())
        # Active products = those with non-zero PnL in this variant
        active = {k for k, v in bt_per_product.items() if v != 0}
        # Live impact: sum of live_3day for active products only
        live_active_sum = sum(live_3day.get(k, 0) for k in active)

        # EV: assume 50% live regime continues, 50% live reverts to backtest
        # If regime continues -> live takes over
        # If reverts -> backtest pace
        ev = 0.5 * live_active_sum + 0.5 * bt_total

        n_active = len(active)
        print(f"{name:<14s} {bt_total:>10,} {n_active:>12d} {live_active_sum:>13,} {ev:>11,.0f}")


if __name__ == "__main__":
    main()
