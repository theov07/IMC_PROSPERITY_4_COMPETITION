"""Final comparison of all R5 strategy variants.

Aggregates all backtest results + live-extrapolated PnL into a unified table.
Helps decide final submission choice.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
COMP = ROOT / "artifacts" / "r5_compare"
LIVE = ROOT / "artifacts" / "r5_live" / "analysis" / "live_per_product_pnl.csv"
OUT = ROOT / "artifacts" / "analysis" / "round_5"


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
                pm = re.search(r'([-]?[\d,]+)', parts[2])
                if pm:
                    out[cur] = int(pm.group(1).replace(',',''))
            cur = None
    return out


def main():
    df_live = pd.read_csv(LIVE, index_col=0)
    live_pnl = df_live.iloc[:, 0].to_dict()
    live_3day = {k: v * 30 for k, v in live_pnl.items()}

    # All variant files
    variants = sorted(COMP.glob("v*.txt"))
    rows = []
    for fp in variants:
        per_prod = parse_per_product(fp)
        if not per_prod:
            continue
        bt_total = sum(per_prod.values())
        active = {k for k, v in per_prod.items() if v != 0}
        live_3d_active = sum(live_3day.get(k, 0) for k in active)
        ev_50 = 0.5 * bt_total + 0.5 * live_3d_active
        rows.append((fp.stem, bt_total, len(active), live_3d_active, ev_50))

    df = pd.DataFrame(rows, columns=["variant", "bt_pnl", "n_active", "live_3d_x30", "ev_50_50"])
    df = df.sort_values("ev_50_50", ascending=False)
    print(f"\n=== FINAL COMPARISON (sorted by EV 50/50) ===")
    print(f"{'variant':<35s} {'bt':>10s} {'n':>4s} {'live_3d':>12s} {'EV':>11s}")
    print("-" * 75)
    for r in df.itertuples():
        print(f"{r.variant:<35s} {r.bt_pnl:>10,} {r.n_active:>4d} {r.live_3d_x30:>12,.0f} {r.ev_50_50:>11,.0f}")

    df.to_csv(OUT / "final_comparison.csv", index=False)


if __name__ == "__main__":
    main()
