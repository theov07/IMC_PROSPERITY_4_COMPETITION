"""EV under different P(regime continue) priors.

Uses parsed bt + live data to compute EV under different assumptions about
how much weight to give live vs backtest.
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

    variants = ["v25_thresh125", "v14b", "v28_drop_flipped", "v29_drop_broad",
                "v32_live_aware", "v33_live_aware_broad"]

    rows = []
    for v in variants:
        fp = COMP / f"{v}.txt"
        per_prod = parse_per_product(fp)
        if not per_prod:
            continue
        bt_total = sum(per_prod.values())
        active = {k for k, vv in per_prod.items() if vv != 0}
        live_3d = sum(live_3day.get(k, 0) for k in active)
        rows.append((v, bt_total, live_3d, len(active)))

    print(f"\n{'variant':<25s} {'bt':>10s} {'live':>12s} {'P=0':>10s} {'P=0.3':>10s} {'P=0.5':>10s} {'P=0.7':>10s} {'P=1.0':>10s}")
    print("-" * 100)
    for v, bt, live, n in rows:
        evs = []
        for p in [0.0, 0.3, 0.5, 0.7, 1.0]:
            ev = (1-p) * bt + p * live
            evs.append(ev)
        print(f"{v:<25s} {bt:>10,} {live:>12,.0f} {evs[0]:>10,.0f} {evs[1]:>10,.0f} {evs[2]:>10,.0f} {evs[3]:>10,.0f} {evs[4]:>10,.0f}")

    print("\nAt P(continue)=0.5: best = highest EV variant")
    print("At P(continue)=0.7: more weight on live. Better defensive variants win.")
    print("At P(continue)=0.3: less weight on live. v25 (highest bt) wins.")
    print("\nGiven live data showed clear trend losses (PLANETARY -7k in 999 ticks isn't noise),")
    print("P(regime continues) >= 0.6. Recommended: pick variant maximizing EV at P=0.6-0.7.")


if __name__ == "__main__":
    main()
