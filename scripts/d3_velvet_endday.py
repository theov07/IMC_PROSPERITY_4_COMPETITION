"""Look at VELVET mid + bid/ask + traded volume in D3 last 5% (tick 950k-999.9k).

Hypothesis: VELVET drops sharply in the last 5%, dragging long option positions
down with it.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    path = ROOT / "data" / "round_4" / "prices_round_4_day_3.csv"
    print(f"Loading {path.name}...")

    # Track only VELVET + key options
    targets = ["VELVETFRUIT_EXTRACT", "VEV_4000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400"]
    rows = {t: [] for t in targets}

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            sym = row["product"]
            if sym not in targets:
                continue
            try:
                ts = int(row["timestamp"])
                mid = float(row["mid_price"])
                bid = float(row["bid_price_1"]) if row.get("bid_price_1") else None
                ask = float(row["ask_price_1"]) if row.get("ask_price_1") else None
                rows[sym].append((ts, mid, bid, ask))
            except (ValueError, KeyError):
                continue

    print()
    for sym in targets:
        data = rows[sym]
        if not data:
            continue
        # Sample at 950k, 960k, 970k, 980k, 990k, 995k, 999k, 999.9k
        targets_ts = [950000, 960000, 970000, 980000, 990000, 995000, 999000, 999900]
        # Index closest
        by_ts = {ts: (mid, bid, ask) for ts, mid, bid, ask in data}
        all_ts = sorted(by_ts.keys())

        print("=" * 80)
        print(f"{sym} D3 LAST 5% mid trajectory")
        print("=" * 80)
        baseline_idx = max(0, all_ts.index(min(all_ts, key=lambda t: abs(t - 950000))))
        baseline_ts = all_ts[baseline_idx]
        baseline_mid = by_ts[baseline_ts][0]
        print(f"Baseline at tick {baseline_ts}: mid = {baseline_mid:,.1f}")
        print(f"\n{'tick':>10s}  {'mid':>10s}  {'delta vs 950k':>14s}  {'delta %':>10s}  {'bid/ask':>15s}")
        for t in targets_ts:
            if not all_ts:
                continue
            closest = min(all_ts, key=lambda x: abs(x - t))
            if abs(closest - t) > 200:
                continue
            mid, bid, ask = by_ts[closest]
            delta = mid - baseline_mid
            pct = delta / baseline_mid * 100 if baseline_mid else 0
            ba = f"{bid:.0f}/{ask:.0f}" if (bid and ask) else "n/a"
            print(f"{closest:>10,}  {mid:>10,.1f}  {delta:>+14,.1f}  {pct:>+9.2f}%  {ba:>15s}")

        # Min/max in last 5%
        last5 = [(ts, mid) for ts, mid, _, _ in data if ts >= 950000]
        if last5:
            min_t, min_m = min(last5, key=lambda x: x[1])
            max_t, max_m = max(last5, key=lambda x: x[1])
            print(f"\nLast 5% min mid: {min_m:,.1f} at tick {min_t:,}")
            print(f"Last 5% max mid: {max_m:,.1f} at tick {max_t:,}")
            print(f"Last 5% range: {max_m - min_m:,.1f} ({(max_m-min_m)/min_m*100:.2f}%)")
        print()


if __name__ == "__main__":
    main()
