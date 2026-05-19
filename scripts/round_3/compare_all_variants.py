"""Final comparison table across all velvet+options max3d variants.

Sorted by: PnL/DD ratio (risk-adjusted leader) and absolute PnL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANA = ROOT / "artifacts" / "analysis" / "round_3"

VARIANTS = [
    "v11_optimal", "v20_z_skip_strict",
    "v24_r2velvet_zskip", "v32_iv_gate", "v33_per_strike_z",
    "v34_combined", "v35_per_strike_z_rev", "v36_ultimate",
    "v37_best_combo", "v38_drop_bad", "v39_drop_5400_only",
    "v40_4000_boost", "v41_combo_best",
]


def lw_pnl(equity_curve, ts_threshold=99900):
    last = 0.0
    for ts, p in equity_curve:
        if ts > ts_threshold:
            break
        last = p
    return last


def main():
    rows = []
    for v in VARIANTS:
        fp = ANA / f"r3_velvet_options_max3d_{v}_3d.json"
        if not fp.exists():
            continue
        with fp.open() as fh:
            d = json.load(fh)
        summ = d["summary"]
        days = d["days"]
        pnl = summ["total_pnl"]
        dd = abs(summ["robustness"]["max_drawdown"])
        d2_lw = lw_pnl(days[2]["equity_curve"]) if len(days) > 2 else 0
        ratio = pnl / dd if dd > 0 else 0
        # Per-strike presence
        strikes = sorted([k for k, v in summ["per_product_pnl"].items() if v != 0])
        rows.append({
            "variant": v,
            "pnl": int(pnl),
            "dd": int(dd),
            "ratio": round(ratio, 3),
            "d2_lw": int(d2_lw),
            "n_strikes": sum(1 for s in strikes if s.startswith("VEV_")),
        })

    print(f"\n{'='*95}")
    print("ALL VARIANTS — sorted by PnL/DD ratio (risk-adjusted)")
    print('='*95)
    rows_by_ratio = sorted(rows, key=lambda r: -r["ratio"])
    print(f"{'Variant':<32} {'PnL':>10} {'DD':>10} {'Ratio':>7} {'D2 LW':>8} {'#strikes':>9}")
    print("-" * 95)
    for r in rows_by_ratio:
        print(f"{r['variant']:<32} {r['pnl']:>10,} {r['dd']:>10,} {r['ratio']:>7.3f} {r['d2_lw']:>8,} {r['n_strikes']:>9}")

    print(f"\n{'='*95}")
    print("ALL VARIANTS — sorted by absolute PnL")
    print('='*95)
    rows_by_pnl = sorted(rows, key=lambda r: -r["pnl"])
    print(f"{'Variant':<32} {'PnL':>10} {'DD':>10} {'Ratio':>7} {'D2 LW':>8} {'#strikes':>9}")
    print("-" * 95)
    for r in rows_by_pnl:
        print(f"{r['variant']:<32} {r['pnl']:>10,} {r['dd']:>10,} {r['ratio']:>7.3f} {r['d2_lw']:>8,} {r['n_strikes']:>9}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
