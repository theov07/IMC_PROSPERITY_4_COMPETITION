"""Compare R4 3-day backtests: v52, v57, v58, v55, baseline.

Reads 5 JSON dumps; emits:
  1. Summary table (PnL, DD, Ratio, CV, daily PnL)
  2. Per-product PnL across 3 days
  3. Per-product per-day PnL grid
  4. Per-product DD proxy (min cumulative PnL across days, per product)
  5. Final recommendation for 3-day submission
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "artifacts" / "analysis" / "round_4"

VARIANTS: List[Tuple[str, str]] = [
    ("v52_minimal", "r4_v52_minimal_3d.json"),
    ("v57_best_ratio", "r4_v57_best_ratio_3d.json"),
    ("v58_balanced", "r4_v58_balanced_3d.json"),
    ("v55_full_strikes", "r4_v55_full_strikes_3d.json"),
    ("baseline", "r4_velvet_options_only_3d.json"),
]

# Compute per-product DD proxy from equity curve diffs across days?
# JSON stores `equity_curve` only at portfolio level per day → no per-product DD.
# Fallback: use per-day per-product PnL series to compute "worst single day" per product.


def load_summary(name: str, json_path: Path) -> Dict[str, Any]:
    print(f"  Loading {name} ({json_path.stat().st_size / 1e6:.1f} MB)...", flush=True)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary = data["summary"]
    days = data["days"]

    total_pnl = summary["total_pnl"]
    total_dd = summary["robustness"]["max_drawdown"]
    per_product_pnl = summary["per_product_pnl"]

    daily_pnls = [d["pnl"] for d in days]

    # per-day per-product PnL
    per_day_per_product = {}
    for d in days:
        day_label = f"D{d['day']}"
        per_day_per_product[day_label] = {
            sym: stats["pnl"] for sym, stats in d["product_summaries"].items()
        }

    # Per-product worst-day PnL = DD proxy at product level
    per_product_worst_day = {}
    for sym in per_product_pnl:
        worst = min(per_day_per_product[d][sym] for d in per_day_per_product)
        per_product_worst_day[sym] = worst

    return {
        "name": name,
        "total_pnl": total_pnl,
        "total_dd": total_dd,
        "ratio": total_pnl / total_dd if total_dd else float("inf"),
        "daily_pnls": daily_pnls,
        "per_product_pnl": per_product_pnl,
        "per_day_per_product": per_day_per_product,
        "per_product_worst_day": per_product_worst_day,
    }


def cv_pct(daily: List[float]) -> float:
    if len(daily) < 2:
        return float("nan")
    mean = sum(daily) / len(daily)
    if mean == 0:
        return float("nan")
    var = sum((x - mean) ** 2 for x in daily) / (len(daily) - 1)
    return math.sqrt(var) / abs(mean) * 100


def print_summary_table(results: List[Dict[str, Any]]):
    print("\n" + "=" * 105)
    print("R4 3-DAY BACKTEST SUMMARY (realistic fill, HYDROGEL OFF, 3 days = 30k ticks total)")
    print("=" * 105)
    print(f"{'Variant':22s} {'PnL_3d':>10s} {'DD':>8s} {'Ratio':>6s} {'CV%':>6s}  {'Daily PnL (D1, D2, D3)':>40s}")
    print("-" * 105)
    for r in results:
        cv = cv_pct(r["daily_pnls"])
        daily_str = ", ".join(f"{d:>+8,.0f}" for d in r["daily_pnls"][:3])
        cv_str = f"{cv:.1f}" if not math.isnan(cv) else "n/a"
        print(
            f"{r['name']:22s} "
            f"{r['total_pnl']:>10,.0f} "
            f"{r['total_dd']:>8,.0f} "
            f"{r['ratio']:>6.2f} "
            f"{cv_str:>6s}  "
            f"  {daily_str}"
        )


def print_per_product_pnl(results: List[Dict[str, Any]]):
    all_products = sorted(set().union(*(r["per_product_pnl"].keys() for r in results)))
    # Skip products that are 0 across all variants
    relevant = [s for s in all_products if any(r["per_product_pnl"].get(s, 0) for r in results)]

    print("\n" + "=" * 105)
    print("PER-PRODUCT PnL (3-day total)")
    print("=" * 105)
    header = f"{'Product':22s}" + "".join(f"{r['name']:>15s}" for r in results)
    print(header)
    print("-" * 105)
    for sym in relevant:
        row = f"{sym:22s}"
        for r in results:
            pnl = r["per_product_pnl"].get(sym, 0)
            row += f"{pnl:>15,.0f}"
        print(row)
    # Total row
    print("-" * 105)
    row = f"{'TOTAL':22s}"
    for r in results:
        row += f"{r['total_pnl']:>15,.0f}"
    print(row)


def print_per_product_worst_day(results: List[Dict[str, Any]]):
    all_products = sorted(set().union(*(r["per_product_worst_day"].keys() for r in results)))
    relevant = [s for s in all_products if any(r["per_product_worst_day"].get(s, 0) for r in results)]

    print("\n" + "=" * 105)
    print("PER-PRODUCT WORST DAY PnL (DD-proxy: most negative single-day PnL across the 3 days)")
    print("=" * 105)
    header = f"{'Product':22s}" + "".join(f"{r['name']:>15s}" for r in results)
    print(header)
    print("-" * 105)
    for sym in relevant:
        row = f"{sym:22s}"
        for r in results:
            wd = r["per_product_worst_day"].get(sym, 0)
            # Show worst-day if negative, else dash
            if wd < 0:
                row += f"{wd:>15,.0f}"
            else:
                row += f"{'-':>15s}"
        print(row)


def print_decision(results: List[Dict[str, Any]]):
    print("\n" + "=" * 105)
    print("DECISION — 3-DAY SUBMISSION")
    print("=" * 105)

    by_pnl = sorted(results, key=lambda r: -r["total_pnl"])
    by_ratio = sorted(results, key=lambda r: -r["ratio"])
    by_dd = sorted(results, key=lambda r: r["total_dd"])

    print(f"\nMAX PnL    : {by_pnl[0]['name']:22s}  PnL={by_pnl[0]['total_pnl']:>10,.0f}  DD={by_pnl[0]['total_dd']:>8,.0f}  ratio={by_pnl[0]['ratio']:.2f}")
    print(f"BEST RATIO : {by_ratio[0]['name']:22s}  PnL={by_ratio[0]['total_pnl']:>10,.0f}  DD={by_ratio[0]['total_dd']:>8,.0f}  ratio={by_ratio[0]['ratio']:.2f}")
    print(f"MIN DD     : {by_dd[0]['name']:22s}  PnL={by_dd[0]['total_pnl']:>10,.0f}  DD={by_dd[0]['total_dd']:>8,.0f}  ratio={by_dd[0]['ratio']:.2f}")

    max_pnl = by_pnl[0]
    best_ratio = by_ratio[0]

    print("\n--- For 3-day total PnL submission ---")
    if max_pnl["name"] == best_ratio["name"]:
        print(f"DOMINANT WINNER: {max_pnl['name']} — best on both PnL and ratio")
    else:
        pnl_gap = max_pnl["total_pnl"] - best_ratio["total_pnl"]
        dd_gap = max_pnl["total_dd"] - best_ratio["total_dd"]
        ratio_gap = best_ratio["ratio"] - max_pnl["ratio"]
        print(f"Tradeoff: max-PnL ({max_pnl['name']}) gives +{pnl_gap:,.0f} PnL but +{dd_gap:,.0f} DD")
        print(f"          best-ratio ({best_ratio['name']}) loses {pnl_gap:,.0f} PnL, saves {dd_gap:,.0f} DD, +{ratio_gap:.2f} ratio")
        print()
        # User said "TOTAL 3-day PnL" matters → favor max PnL
        print(f">>> RECOMMENDATION (user wants TOTAL 3-day PnL): {max_pnl['name']} <<<")
        print(f"    Submit: PnL={max_pnl['total_pnl']:,.0f}  DD={max_pnl['total_dd']:,.0f}  ratio={max_pnl['ratio']:.2f}")
        print(f"    Backup if DD too risky: {best_ratio['name']} ({best_ratio['total_pnl']:,.0f} / {best_ratio['total_dd']:,.0f} / {best_ratio['ratio']:.2f})")


def main():
    print("Loading 5 R4 3-day backtest JSONs...")
    results = []
    for name, fname in VARIANTS:
        path = ANALYSIS_DIR / fname
        if not path.exists():
            print(f"  MISSING: {path}")
            continue
        try:
            results.append(load_summary(name, path))
        except Exception as e:
            print(f"  ERROR loading {name}: {e}")
            raise

    if not results:
        print("No results loaded.")
        return

    print_summary_table(results)
    print_per_product_pnl(results)
    print_per_product_worst_day(results)
    print_decision(results)


if __name__ == "__main__":
    main()
