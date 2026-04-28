"""Cached backtest runner — never re-run the same variant.

Usage:
  python scripts/cached_backtest.py --variant r4_v9_M22cond_z15_w04 --days 1 2 3
  python scripts/cached_backtest.py --variant r4_v9_M22cond_z15_w04 --days 3 --force

Saves to: artifacts/backtest_cache/round_4/{variant}_{days_tag}.json
Prints:   PnL summary (per-product + drawdown)

Skips run if cache exists, unless --force.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
CACHE_DIR = ROOT / "artifacts" / "backtest_cache" / "round_4"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def days_tag(days):
    if len(days) == 1:
        return f"d{days[0]}"
    return f"{len(days)}d"


def cache_path(variant, days):
    return CACHE_DIR / f"{variant}_{days_tag(days)}.json"


def run_backtest(variant, days, json_out):
    cmd = [
        sys.executable, "backtest.py",
        "--strategy", variant,
        "--round", "4",
        "--days", *[str(d) for d in days],
        "--data-dir", "data/round_4",
        "--execution-rule", "realistic",
        "--json-out", str(json_out),
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[-500:]}")
        return False
    return True


def summarize(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    summary = d.get("summary", {})
    total = summary.get("total_pnl", 0)
    pp = summary.get("per_product_pnl", {})
    rob = summary.get("robustness", {})
    dd = rob.get("max_drawdown", 0)
    print(f"  TOTAL PnL: {total:+,.0f}  |  Drawdown: {dd:,.0f}  |  Ratio: {total/max(1,dd):.2f}")
    print("  Per-product:")
    for prod in sorted(pp.keys()):
        v = pp[prod]
        if v != 0:
            print(f"    {prod:>22s}: {v:+,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True)
    ap.add_argument("--days", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--force", action="store_true", help="Re-run even if cache exists")
    args = ap.parse_args()

    out = cache_path(args.variant, args.days)
    if out.exists() and not args.force:
        print(f"[CACHED] {out.name}")
        summarize(out)
        return

    print(f"[RUNNING] {args.variant} on days {args.days}")
    if run_backtest(args.variant, args.days, out):
        print(f"[OK] Saved {out.name}")
        summarize(out)


if __name__ == "__main__":
    main()
