"""Audit each product for ALL signal types we have:
  - rev_ratio (mean reversion)
  - AR1 (return autocorrelation)
  - day-by-day stability (which days were good?)
  - intra-day trend strength (Hurst)
  - inventory carry pattern (from MM perspective)

Output: per-product recommendation (best strategy class) and key stats.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
DATA = ROOT / "data" / "round_5"
OUT = ROOT / "artifacts" / "analysis" / "round_5"
OUT.mkdir(parents=True, exist_ok=True)


def load_pivot():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    p = pd.concat(dfs, ignore_index=True)
    p["mid"] = (p["bid_price_1"].fillna(0) + p["ask_price_1"].fillna(0)) / 2
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p


def hurst(series: np.ndarray) -> float:
    s = np.asarray(series)
    s = s[~np.isnan(s)]
    if len(s) < 100: return float("nan")
    lags = [10, 20, 50, 100, 200, 500]
    rs = []
    for lag in lags:
        if lag >= len(s): continue
        n = len(s) // lag
        if n < 1: continue
        rs_vals = []
        for i in range(n):
            sub = s[i*lag:(i+1)*lag]
            mean = sub.mean()
            cum = np.cumsum(sub - mean)
            r = cum.max() - cum.min()
            sd = sub.std()
            if sd > 0: rs_vals.append(r/sd)
        if rs_vals: rs.append((lag, np.mean(rs_vals)))
    if len(rs) < 3: return float("nan")
    log_lag = np.log([x[0] for x in rs])
    log_rs = np.log([x[1] for x in rs])
    return float(np.polyfit(log_lag, log_rs, 1)[0])


def main():
    p = load_pivot()
    products = sorted(p["product"].unique())

    rows = []
    for prod in products:
        sub = p[p["product"] == prod].copy()
        sub = sub.sort_values(["day", "timestamp"]).reset_index(drop=True)
        mid = sub["mid"].values
        ret = np.diff(mid)
        spread_avg = float(sub["spread"].mean())

        # AR1 of returns
        if len(ret) > 10 and ret.std() > 1e-9:
            ar1 = float(np.corrcoef(ret[:-1], ret[1:])[0, 1])
        else:
            ar1 = 0.0

        # Hurst exponent
        h = hurst(mid)

        # Mean reversion ratio (range vs std of changes)
        if len(mid) > 100 and ret.std() > 1e-9:
            rev_ratio = (mid.max() - mid.min()) / ret.std()
        else:
            rev_ratio = 0.0

        # Per-day total moves (start to end)
        days = sub["day"].unique()
        day_moves = []
        for d in days:
            day_data = sub[sub["day"] == d]["mid"].values
            if len(day_data) > 10:
                day_moves.append(day_data[-1] - day_data[0])

        # Intra-day max swing
        day_max_swings = []
        for d in days:
            day_data = sub[sub["day"] == d]["mid"].values
            if len(day_data) > 10:
                start = day_data[0]
                day_max_swings.append(max(abs(day_data.max() - start), abs(day_data.min() - start)))

        # Day consistency: all same direction?
        day_signs = [1 if x > 0 else (-1 if x < 0 else 0) for x in day_moves]
        consistent = all(s == day_signs[0] for s in day_signs) if day_signs else False

        # Product std
        ret_std = float(ret.std()) if len(ret) > 0 else 0.0

        rows.append(dict(
            product=prod, ar1=ar1, hurst=h, rev_ratio=rev_ratio,
            avg_spread=spread_avg, ret_std=ret_std,
            day_moves=day_moves, max_intraday_swing=float(np.max(day_max_swings)) if day_max_swings else 0.0,
            consistent_direction=consistent,
        ))

    df = pd.DataFrame(rows)

    # === Recommendations per product ===
    def recommend(r):
        if r["ar1"] < -0.15:
            return "ar1_mean_rev"
        if r["consistent_direction"] and abs(np.mean(r["day_moves"])) > 200 and r["max_intraday_swing"] / max(abs(np.mean(r["day_moves"])), 1) < 1.5:
            # Consistent direction, intraday swings moderate vs daily move
            return "trend_follow"
        if r["rev_ratio"] > 5 and r["hurst"] < 0.5:
            return "zscore_mr"
        if r["max_intraday_swing"] / max(abs(np.mean(r["day_moves"])), 1) > 3:
            return "carry_aware_mm"  # large noise vs signal → need carry protection
        return "naive_mm"

    df["recommended"] = df.apply(recommend, axis=1)
    df["mean_day_move"] = df["day_moves"].apply(lambda x: float(np.mean(x)) if x else 0.0)

    print("=== Per-product strategy recommendations ===")
    print(f"{'product':<35} {'ar1':>7} {'hurst':>6} {'rev_r':>6} {'spread':>7} {'mean_day':>8} {'max_sw':>7} {'recom':<20}")
    print("-" * 110)
    for r in df.sort_values("recommended").itertuples():
        print(f"{r.product:<35} {r.ar1:>7.3f} {r.hurst:>6.2f} {r.rev_ratio:>6.1f} {r.avg_spread:>7.1f} "
              f"{r.mean_day_move:>8.0f} {r.max_intraday_swing:>7.0f}  {r.recommended:<20}")

    # Group by recommendation
    print("\n=== Counts by recommendation ===")
    print(df["recommended"].value_counts())

    df.drop(columns=["day_moves"]).to_csv(OUT / "product_signal_audit.csv", index=False)


if __name__ == "__main__":
    main()
