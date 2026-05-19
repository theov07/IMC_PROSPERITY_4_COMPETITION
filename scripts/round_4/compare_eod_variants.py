"""Compare EOD variants vs baseline.

Variants:
  - baseline (no EOD)
  - eod_v1 (start=0.85, agg=0.93, full=0.99)
  - eod_aggressive (start=0.75, agg=0.88, full=0.97)
  - eod_conservative (start=0.92, agg=0.96, full=0.995)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "artifacts" / "analysis" / "round_4"

VARIANTS = [
    ("baseline (no EOD)", "r4_velvet_options_only_3d.json"),
    ("eod_v1 (0.85/0.93/0.99)", "r4_velvet_eod_v1_3d.json"),
    ("eod_aggressive (0.75/0.88)", "r4_velvet_eod_aggressive_3d.json"),
    ("eod_conservative (0.92/0.96)", "r4_velvet_eod_conservative_3d.json"),
    ("eod_v4 (0.95/0.97/0.995)", "r4_velvet_eod_v4_3d.json"),
    ("eod_v5 (0.97/0.985/0.998)", "r4_velvet_eod_v5_3d.json"),
    ("eod_v1+trend_gate", "r4_velvet_eod_v1_trend_3d.json"),
]


def load(name, fname):
    path = ANALYSIS_DIR / fname
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    days = d["days"]
    return {
        "name": name,
        "total_pnl": d["summary"]["total_pnl"],
        "max_dd": d["summary"]["robustness"]["max_drawdown"],
        "ratio": d["summary"]["total_pnl"] / d["summary"]["robustness"]["max_drawdown"],
        "daily_pnls": [day["pnl"] for day in days],
        "per_product_pnl": d["summary"]["per_product_pnl"],
        "per_day_per_product": {
            f"D{day['day']}": {sym: stats["pnl"] for sym, stats in day["product_summaries"].items()}
            for day in days
        },
        "per_product_max_pos": d["summary"]["per_product_max_pos"],
        # Last 5% PnL on D3
        "d3_last5_pnl_lost": _d3_last5_pnl_lost(days[2]),
    }


def _d3_last5_pnl_lost(day3):
    ec = day3["equity_curve"]
    by_ts = {row[0]: row[1] for row in ec}
    if not by_ts:
        return None
    # Closest tick to 950k
    keys = list(by_ts.keys())
    t_950 = min(keys, key=lambda x: abs(x - 950000))
    t_end = max(keys)
    pnl_at_950 = by_ts[t_950]
    pnl_at_end = by_ts[t_end]
    # Peak between 950k and end
    peak = max(by_ts[t] for t in keys if 950000 <= t <= t_end)
    return {
        "pnl_at_950k": pnl_at_950,
        "peak_after_950k": peak,
        "pnl_at_end": pnl_at_end,
        "lost_from_peak": peak - pnl_at_end,
    }


def main():
    results = []
    for name, fname in VARIANTS:
        r = load(name, fname)
        if r is None:
            print(f"MISSING: {fname}")
            continue
        results.append(r)

    if not results:
        return

    # Summary
    print("=" * 110)
    print("EOD VARIANTS — 3-DAY BACKTEST SUMMARY (R4 baseline = r4_velvet_options_only)")
    print("=" * 110)
    print(f"{'Variant':>40s}  {'PnL_3d':>10s}  {'DD':>10s}  {'Ratio':>6s}  {'D1':>8s}  {'D2':>8s}  {'D3':>8s}")
    print("-" * 110)
    base_pnl = results[0]["total_pnl"] if results else 0
    base_dd = results[0]["max_dd"] if results else 0
    for r in results:
        delta_pnl = r["total_pnl"] - base_pnl
        delta_dd = r["max_dd"] - base_dd
        d1, d2, d3 = r["daily_pnls"]
        print(
            f"{r['name']:>40s}  "
            f"{r['total_pnl']:>+10,.0f}  "
            f"{r['max_dd']:>10,.0f}  "
            f"{r['ratio']:>6.2f}  "
            f"{d1:>+8,.0f}  {d2:>+8,.0f}  {d3:>+8,.0f}"
        )
        if r is not results[0]:
            print(
                f"{'':>40s}  "
                f"{('d=' + ('+' if delta_pnl >= 0 else '')):>10s}{delta_pnl:+,.0f}  "
                f"d={('+' if delta_dd >= 0 else '')}{delta_dd:+,.0f}"
            )

    # D3 last 5% drill
    print("\n" + "=" * 110)
    print("D3 LAST 5% (tick 950k -> end): peak vs end, how much PnL we held onto")
    print("=" * 110)
    print(f"{'Variant':>40s}  {'PnL@950k':>10s}  {'peak after':>12s}  {'PnL@end':>10s}  {'lost from peak':>14s}")
    print("-" * 110)
    for r in results:
        d = r["d3_last5_pnl_lost"]
        if d is None:
            continue
        print(
            f"{r['name']:>40s}  "
            f"{d['pnl_at_950k']:>+10,.0f}  "
            f"{d['peak_after_950k']:>+12,.0f}  "
            f"{d['pnl_at_end']:>+10,.0f}  "
            f"{d['lost_from_peak']:>14,.0f}"
        )

    # Per-product 3-day PnL
    print("\n" + "=" * 110)
    print("PER-PRODUCT 3-DAY PnL")
    print("=" * 110)
    all_prods = sorted(results[0]["per_product_pnl"].keys())
    relevant = [p for p in all_prods if any(r["per_product_pnl"].get(p, 0) for r in results)]
    print(f"{'Product':>22s}" + "".join(f"{r['name'][:18]:>20s}" for r in results))
    print("-" * 110)
    for p in relevant:
        row = f"{p:>22s}"
        for r in results:
            row += f"{r['per_product_pnl'].get(p, 0):>20,.0f}"
        print(row)

    # Per-product D3 PnL
    print("\n" + "=" * 110)
    print("PER-PRODUCT D3 PnL (the day where EOD should bite)")
    print("=" * 110)
    print(f"{'Product':>22s}" + "".join(f"{r['name'][:18]:>20s}" for r in results))
    print("-" * 110)
    for p in relevant:
        row = f"{p:>22s}"
        for r in results:
            v = r["per_day_per_product"]["D3"].get(p, 0)
            row += f"{v:>+20,.0f}"
        print(row)


if __name__ == "__main__":
    main()
