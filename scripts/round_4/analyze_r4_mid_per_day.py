"""Analyze VELVET + VEV mid price stats per day to detect regime shift on D3."""
from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "round_4"


def load_prices(day: int):
    """Yield (ts, product, mid) from prices CSV."""
    path = DATA_DIR / f"prices_round_4_day_{day}.csv"
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                mid = float(row["mid_price"])
                ts = int(row["timestamp"])
                yield ts, row["product"], mid
            except (ValueError, KeyError):
                continue


def per_product_stats(day: int):
    """Returns dict {product: list of mids}."""
    prods = defaultdict(list)
    for ts, prod, mid in load_prices(day):
        prods[prod].append(mid)
    return prods


def realized_vol(mids):
    """Tick-by-tick log returns std (annualized: 1 day = 10000 ticks)."""
    if len(mids) < 2:
        return float("nan")
    rets = []
    for i in range(1, len(mids)):
        if mids[i - 1] <= 0:
            continue
        rets.append(math.log(mids[i] / mids[i - 1]))
    if len(rets) < 2:
        return float("nan")
    return statistics.stdev(rets)  # per-tick


def main():
    print("Analyzing R4 mid prices per day per product...\n")

    days_data = {}
    for day in (1, 2, 3):
        try:
            days_data[day] = per_product_stats(day)
            print(f"D{day}: loaded {sum(len(v) for v in days_data[day].values()):,} mid points across {len(days_data[day])} products")
        except Exception as e:
            print(f"D{day}: {e}")
    print()

    # Get common products
    products = set(days_data[1].keys()) & set(days_data[2].keys()) & set(days_data[3].keys())
    products = sorted(p for p in products if p)

    # Header
    print("=" * 110)
    print("MID PRICE STATISTICS PER PRODUCT PER DAY")
    print("=" * 110)
    print(f"{'Product':>22s}  {'metric':>12s}  {'D1':>12s}  {'D2':>12s}  {'D3':>12s}  {'D3/D1':>8s}")
    print("-" * 110)

    for prod in products:
        d1 = days_data[1][prod]
        d2 = days_data[2][prod]
        d3 = days_data[3][prod]
        if not d1 or not d2 or not d3:
            continue

        # Realized vol (per tick stdev of log returns)
        v1 = realized_vol(d1) * 1e4
        v2 = realized_vol(d2) * 1e4
        v3 = realized_vol(d3) * 1e4

        # Range (max - min)
        r1 = max(d1) - min(d1)
        r2 = max(d2) - min(d2)
        r3 = max(d3) - min(d3)

        # Drift (end - start)
        dr1 = d1[-1] - d1[0]
        dr2 = d2[-1] - d2[0]
        dr3 = d3[-1] - d3[0]

        # Mean mid
        m1 = sum(d1) / len(d1)
        m2 = sum(d2) / len(d2)
        m3 = sum(d3) / len(d3)

        v_ratio = v3 / v1 if v1 else 0
        r_ratio = r3 / r1 if r1 else 0

        print(
            f"{prod:>22s}  {'mean_mid':>12s}  "
            f"{m1:>12,.1f}  {m2:>12,.1f}  {m3:>12,.1f}  "
            f"{m3/m1:>8.3f}"
        )
        print(
            f"{'':>22s}  {'realized_vol(bp/tick)':>22s}  "
            f"{v1:>2,.2f}  {v2:>12,.2f}  {v3:>12,.2f}  "
            f"{v_ratio:>8.2f}x"
        )
        print(
            f"{'':>22s}  {'range':>12s}  "
            f"{r1:>12,.1f}  {r2:>12,.1f}  {r3:>12,.1f}  "
            f"{r_ratio:>8.2f}x"
        )
        print(
            f"{'':>22s}  {'drift(end-start)':>22s}  "
            f"{dr1:>+2,.1f}  {dr2:>+12,.1f}  {dr3:>+12,.1f}"
        )
        print()


if __name__ == "__main__":
    main()
