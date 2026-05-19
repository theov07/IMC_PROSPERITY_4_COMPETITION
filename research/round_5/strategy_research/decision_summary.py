"""Final decision summary for R5 submission.

Provides ranking under different P(regime continue) priors.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
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

    rows = []
    for fp in sorted(COMP.glob("v*.txt")):
        per_prod = parse_per_product(fp)
        if not per_prod:
            continue
        bt = sum(per_prod.values())
        active = {k for k, v in per_prod.items() if v != 0}
        live = sum(live_3day.get(k, 0) for k in active)
        rows.append((fp.stem, bt, live, len(active)))

    df = pd.DataFrame(rows, columns=["variant", "bt", "live_3d", "n_active"])

    # Rank under different priors
    print(f"\n{'variant':<32s} {'bt':>10s} {'live_3d':>12s} {'n':>3s} {'EV@P=.3':>10s} {'EV@P=.5':>10s} {'EV@P=.7':>10s}")
    print("-" * 100)

    df["EV_30"] = 0.7 * df["bt"] + 0.3 * df["live_3d"]
    df["EV_50"] = 0.5 * df["bt"] + 0.5 * df["live_3d"]
    df["EV_70"] = 0.3 * df["bt"] + 0.7 * df["live_3d"]
    df = df.sort_values("EV_50", ascending=False).head(20)
    for r in df.itertuples():
        print(f"{r.variant:<32s} {r.bt:>10,} {r.live_3d:>12,.0f} {r.n_active:>3d} {r.EV_30:>10,.0f} {r.EV_50:>10,.0f} {r.EV_70:>10,.0f}")

    print("\n=== RECOMMENDATIONS ===")
    print(f"Best at P=0 (pure bt):    {df.sort_values('bt', ascending=False).iloc[0]['variant']}")
    print(f"Best at P=0.3 (skeptical):  {df.sort_values('EV_30', ascending=False).iloc[0]['variant']}")
    print(f"Best at P=0.5 (neutral):    {df.sort_values('EV_50', ascending=False).iloc[0]['variant']}")
    print(f"Best at P=0.7 (live likely):{df.sort_values('EV_70', ascending=False).iloc[0]['variant']}")
    print(f"Best at P=1.0 (pure live):  {df.sort_values('live_3d', ascending=False).iloc[0]['variant']}")


if __name__ == "__main__":
    main()
