"""Compare per-day breakdown across cached variants.

Usage:
  python scripts/round_4/compare_per_day.py r4_v9_M22cond_z15_w04 r4_v17_passive_70_50_pi r4_v16_unwind_90_70_5

For each variant, prints per-(product, day) PnL, position end, and intra-day max DD.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "artifacts" / "backtest_cache" / "round_4"


def load(variant):
    p = CACHE / f"{variant}_3d.json"
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def per_day_summary(d):
    days = d["days"]
    rows = []
    for day in days:
        day_num = day.get("day", "?")
        ps = day.get("product_summaries", {})
        ec = day.get("equity_curve", [])
        # Compute intra-day DD
        max_pnl = 0
        max_dd = 0
        for ts, pnl in ec:
            if pnl > max_pnl:
                max_pnl = pnl
            dd = max_pnl - pnl
            if dd > max_dd:
                max_dd = dd
        end_pnl = ec[-1][1] if ec else 0
        rows.append({"day": day_num, "end_pnl": end_pnl, "intra_dd": max_dd, "products": ps})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("variants", nargs="+")
    args = ap.parse_args()

    variants_data = []
    for v in args.variants:
        d = load(v)
        if d is None:
            print(f"  [MISSING] {v} (run cached_backtest first)")
            continue
        variants_data.append((v, per_day_summary(d), d["summary"]))

    # Per-day comparison table
    print()
    print("=" * 100)
    print("PER-DAY EQUITY + INTRA-DAY DRAWDOWN")
    print("=" * 100)
    print(f"{'Variant':>30s}  {'D1 PnL':>10s}  {'D1 DD':>8s}  {'D2 PnL':>10s}  {'D2 DD':>8s}  {'D3 PnL':>10s}  {'D3 DD':>8s}  {'Total':>10s}  {'Ratio':>6s}")
    print("-" * 100)
    for v, rows, summ in variants_data:
        cells = []
        for r in rows:
            cells.append(f"{r['end_pnl']:>+10,.0f}  {r['intra_dd']:>8,.0f}")
        total = summ.get("total_pnl", 0)
        dd = summ.get("robustness", {}).get("max_drawdown", 0)
        ratio = total / dd if dd else 0
        print(f"{v:>30s}  {'  '.join(cells)}  {total:>+10,.0f}  {ratio:>6.2f}")

    # Per-(product, day) PnL detail for the worst day across variants
    print()
    print("=" * 100)
    print("DAY 3 PRODUCT-LEVEL PnL (where most strategies lose)")
    print("=" * 100)
    print(f"{'Variant':>30s}  ", end="")
    sample_products = sorted(variants_data[0][1][2]["products"].keys()) if variants_data else []
    rel = [p for p in sample_products if p == "VELVETFRUIT_EXTRACT" or p.startswith("VEV_")]
    rel = [p for p in rel if variants_data[0][1][2]["products"].get(p, {}).get("pnl", 0) != 0 or variants_data[0][1][0]["products"].get(p, {}).get("pnl", 0) != 0]
    for p in rel:
        print(f"{p[-8:]:>9s}  ", end="")
    print(f"{'D3 sum':>9s}")
    print("-" * (32 + len(rel) * 11 + 10))
    for v, rows, _ in variants_data:
        print(f"{v:>30s}  ", end="")
        d3 = rows[2]
        s = 0
        for p in rel:
            pnl = d3["products"].get(p, {}).get("pnl", 0)
            s += pnl
            if pnl == 0:
                print(f"{'.':>9s}  ", end="")
            else:
                print(f"{pnl:>+9,.0f}  ", end="")
        print(f"{s:>+9,.0f}")

    # Per-day sum of options PnL (HOW MUCH OPTIONS DRAGGED EACH DAY)
    print()
    print("=" * 100)
    print("OPTIONS-ONLY PER-DAY (sum of all VEV_* PnL)")
    print("=" * 100)
    print(f"{'Variant':>30s}  {'D1 opts':>10s}  {'D2 opts':>10s}  {'D3 opts':>10s}  {'D3-D2':>10s}")
    print("-" * 100)
    for v, rows, _ in variants_data:
        cells = []
        d3_opts = 0
        d2_opts = 0
        for i, r in enumerate(rows):
            opts_pnl = sum(p["pnl"] for sym, p in r["products"].items() if sym.startswith("VEV_"))
            cells.append(f"{opts_pnl:>+10,.0f}")
            if i == 1:
                d2_opts = opts_pnl
            if i == 2:
                d3_opts = opts_pnl
        print(f"{v:>30s}  {'  '.join(cells)}  {d3_opts - d2_opts:>+10,.0f}")


if __name__ == "__main__":
    main()
