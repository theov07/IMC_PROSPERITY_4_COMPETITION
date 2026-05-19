"""Find mathematically optimal drop set at given P(regime continues).

For each product:
  decision = "drop" if (1-P)*bt + P*live < 0
  i.e. drop iff P > bt / (bt - live)  (when bt - live > 0)

Output: which products to drop at different P thresholds.
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
                pm = re.search(r'([-]?[\d,]+)', parts[2])
                if pm:
                    out[cur] = int(pm.group(1).replace(',',''))
            cur = None
    return out


def main():
    bt = parse_per_product(COMP / "v14b.txt")
    df_live = pd.read_csv(LIVE, index_col=0)
    live_pnl = df_live.iloc[:, 0].to_dict()
    live_3day = {k: v * 30 for k, v in live_pnl.items()}

    # For each product, compute break-even P: drop iff P > bt/(bt-live)
    rows = []
    for p, b in bt.items():
        if b == 0:
            continue
        l = live_3day.get(p, 0)
        if b - l == 0:
            be = float("inf")
        else:
            be = b / (b - l)
        rows.append((p, b, l, be))

    df = pd.DataFrame(rows, columns=["product", "bt", "live_3d", "break_even_P"])
    df = df.sort_values("break_even_P")
    print("Break-even probability for DROP (drop iff P > break_even_P):\n")
    print(f"{'product':<35s} {'bt':>10s} {'live_3d':>12s} {'break_even_P':>13s}")
    print("-" * 75)
    for r in df.itertuples():
        marker = ""
        if r.bt > 0 and r.live_3d > 0:
            marker = "ALWAYS KEEP"
        elif r.bt < 0 and r.live_3d < 0:
            marker = "ALWAYS DROP"
        print(f"{r.product:<35s} {r.bt:>10,} {r.live_3d:>12,.0f} {r.break_even_P:>13.3f}  {marker}")

    print("\n=== Drop sets at different P levels ===")
    for P in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        drop = df[df["break_even_P"] < P]["product"].tolist()
        # Filter only products with bt > 0 (otherwise "drop" doesn't gain anything)
        keep_drops = [p for p in drop if bt.get(p, 0) > 0]
        print(f"\nP={P}: drop {len(keep_drops)} products: {keep_drops}")

    # Also compute optimal at P=0.5
    df_p50 = df.copy()
    df_p50["should_drop_at_p50"] = df_p50["break_even_P"] < 0.5
    df_p50["should_drop_at_p50"] &= df_p50["bt"] > 0  # only drop if bt was positive
    drops_p50 = df_p50[df_p50["should_drop_at_p50"]]["product"].tolist()
    print(f"\n=== OPTIMAL DROP SET at P=0.5 ===")
    print(f"Drop {len(drops_p50)} products: {drops_p50}")

    df.to_csv(ROOT / "artifacts" / "analysis" / "round_5" / "optimal_drop.csv", index=False)


if __name__ == "__main__":
    main()
