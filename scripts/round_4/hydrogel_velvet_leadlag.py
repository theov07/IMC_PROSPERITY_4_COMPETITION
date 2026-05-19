"""HYDROGEL → VELVET lead-lag analysis.

Hypothesis: HYDROGEL_PACK and VELVETFRUIT_EXTRACT may share economic drivers
(e.g., both consumer goods in Intarian economy). If HYDROGEL's mid moves
LEAD VELVET's mid moves, that's a usable signal even if we don't trade HYDRO.

Test:
  - Cross-correlation between HYDRO returns at lag K and VELVET returns
  - For each lag K (1, 5, 10, 50 ticks), compute correlation
  - If correlation peaks at positive lag K → HYDRO leads VELVET
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]


def load_mid_series(day: int, product: str):
    path = ROOT / "data" / "round_4" / f"prices_round_4_day_{day}.csv"
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                if row["product"] != product:
                    continue
                out.append((int(row["timestamp"]), float(row["mid_price"])))
            except Exception:
                continue
    return out


def main():
    print("=" * 100)
    print("HYDROGEL → VELVET LEAD-LAG ANALYSIS")
    print("=" * 100)

    for d in (1, 2, 3):
        h = load_mid_series(d, "HYDROGEL_PACK")
        v = load_mid_series(d, "VELVETFRUIT_EXTRACT")
        # Align by timestamp (both should be at same ticks)
        h_by_ts = dict(h)
        v_by_ts = dict(v)
        common_ts = sorted(set(h_by_ts.keys()) & set(v_by_ts.keys()))
        if not common_ts:
            continue

        h_mid = [h_by_ts[t] for t in common_ts]
        v_mid = [v_by_ts[t] for t in common_ts]

        # Compute log returns
        h_ret = [math.log(h_mid[i] / h_mid[i-1]) for i in range(1, len(h_mid))]
        v_ret = [math.log(v_mid[i] / v_mid[i-1]) for i in range(1, len(v_mid))]

        # Compute correlation at various lags
        # lag = 0: same tick. lag = +K: HYDRO at t predicts VELVET at t+K
        print(f"\n--- Day {d} (HYDRO vs VELVET, {len(h_ret):,} return pairs) ---")
        print(f"{'lag (ticks)':>12s}  {'corr':>10s}  {'predictor → predicted':>30s}")
        print("-" * 60)
        for lag in (-50, -10, -5, -1, 0, 1, 5, 10, 50):
            if lag >= 0:
                # HYDRO at t predicts VELVET at t+lag
                xs = h_ret[:len(h_ret) - lag]
                ys = v_ret[lag:]
            else:
                # VELVET at t predicts HYDRO at t-lag
                xs = h_ret[-lag:]
                ys = v_ret[:len(v_ret) + lag]

            n = min(len(xs), len(ys))
            if n < 100:
                continue
            xs, ys = xs[:n], ys[:n]
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
            den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
            den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
            if den_x * den_y == 0:
                continue
            rho = num / (den_x * den_y)
            print(f"{lag:>+12d}  {rho:>+10.4f}  {'HYDRO → VELVET' if lag > 0 else ('SAME tick' if lag == 0 else 'VELVET → HYDRO'):>30s}")


if __name__ == "__main__":
    main()
