"""Compare per-product PnL across days 2/3/4 to identify regime-dependent products.

Goal: products that are big winners in some days but losers in others = unstable.
Stable winners across 3 days = high confidence.

Compares to LIVE log too if available.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
COMP = ROOT / "artifacts" / "r5_compare"
LIVE = ROOT / "artifacts" / "r5_live" / "analysis"
OUT = ROOT / "artifacts" / "analysis" / "round_5"


def parse_per_day(filepath: Path) -> pd.DataFrame:
    """Parse backtest output: per-product per-day PnL + subtotal."""
    if not filepath.exists():
        return pd.DataFrame()
    with open(filepath, encoding='utf-8', errors='replace') as f:
        txt = f.read()
    rows = []
    cur_product = None
    cur_pnls = {}  # day -> pnl
    for line in txt.splitlines():
        m = re.match(r'\s+([A-Z][A-Z0-9_]+)\s+\│\s*day\s+(\d+)\s+\│\s*([-]?[\d,]+)', line)
        if m:
            cur_product = m.group(1)
            cur_pnls[(cur_product, int(m.group(2)))] = int(m.group(3).replace(',',''))
            continue
        # cont line
        m2 = re.match(r'\s+\│\s*day\s+(\d+)\s+\│\s*([-]?[\d,]+)', line)
        if m2 and cur_product:
            cur_pnls[(cur_product, int(m2.group(1)))] = int(m2.group(2).replace(',',''))
    rows = [{"product": p, "day": d, "pnl": v} for (p, d), v in cur_pnls.items()]
    return pd.DataFrame(rows)


def main():
    # Parse v2 (champion)
    df_v2 = parse_per_day(COMP / "v2.txt")
    df_v14b = parse_per_day(COMP / "v14b.txt")

    if df_v2.empty:
        print(f"ERROR: {COMP/'v2.txt'} not parseable")
        return

    pivot_v2 = df_v2.pivot_table(index="product", columns="day", values="pnl", aggfunc="first")
    pivot_v14b = df_v14b.pivot_table(index="product", columns="day", values="pnl", aggfunc="first")

    # Add total
    pivot_v2["total_v2"] = pivot_v2[[2, 3, 4]].sum(axis=1) if all(c in pivot_v2.columns for c in [2,3,4]) else 0
    pivot_v14b["total_v14b"] = pivot_v14b[[2, 3, 4]].sum(axis=1) if all(c in pivot_v14b.columns for c in [2,3,4]) else 0

    # Stability metric: std of per-day PnL relative to mean
    pivot_v2["std_d234"] = pivot_v2[[2,3,4]].std(axis=1)
    pivot_v2["min_day"] = pivot_v2[[2,3,4]].min(axis=1)
    pivot_v2["worst_day_negative"] = pivot_v2[[2,3,4]].apply(lambda s: int((s < 0).sum()), axis=1)

    # === Identify regime-unstable winners ===
    # A product where 2 of 3 days are winners but one is big loser
    print("\n=== REGIME-UNSTABLE products (worst_day < -2000 but total > 5000) ===")
    unstable = pivot_v2[(pivot_v2["min_day"] < -2000) & (pivot_v2["total_v2"] > 5000)]
    print(unstable[[2,3,4,"total_v2","std_d234"]].sort_values("total_v2", ascending=False).to_string())

    # === Identify rock-solid winners ===
    print("\n=== STABLE WINNERS (min_day > 0 and total > 5000) ===")
    stable = pivot_v2[(pivot_v2["min_day"] > 0) & (pivot_v2["total_v2"] > 5000)]
    print(stable[[2,3,4,"total_v2"]].sort_values("total_v2", ascending=False).to_string())

    # === LIVE LOG comparison ===
    live_csv = LIVE / "live_per_product_pnl.csv"
    if live_csv.exists():
        df_live = pd.read_csv(live_csv, index_col=0)
        df_live.columns = ["live_pnl"]
        # Merge
        merged = pivot_v2[[2,3,4,"total_v2"]].copy()
        merged = merged.join(df_live, how="outer").fillna(0)
        # Live PnL on 999 ticks ≈ 1/10 of a day, so multiply by 10 for fair comparison
        merged["live_extrapolated"] = merged["live_pnl"] * 10
        merged["bt_avg_per_day"] = merged["total_v2"] / 3
        merged["live_vs_bt_ratio"] = merged["live_extrapolated"] / merged["bt_avg_per_day"].replace(0, 1)

        print("\n=== LIVE vs BACKTEST (top 15 winners by total_v2) ===")
        merged_sorted = merged.sort_values("total_v2", ascending=False)
        print(merged_sorted[[2,3,4,"total_v2","live_pnl","live_extrapolated","live_vs_bt_ratio"]].head(15).round(2).to_string())

        print("\n=== Backtest WINNERS that LIVE LOSE ===")
        regime_change = merged[(merged["total_v2"] > 5000) & (merged["live_pnl"] < 0)]
        print(regime_change[[2,3,4,"total_v2","live_pnl"]].sort_values("live_pnl").to_string())

        merged.to_csv(OUT / "live_vs_backtest.csv")


if __name__ == "__main__":
    main()
