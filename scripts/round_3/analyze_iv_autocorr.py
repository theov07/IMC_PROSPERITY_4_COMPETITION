"""IV residual autocorrelation test — last year's team validated IV scalping
because 1-lag autocorrelation of IV residuals (vs smile fit) was NEGATIVE
(=mean-reverting). If we have this property, IV scalping has alpha.

For each strike, compute:
  - residual_t = own_iv_t - smile_predicted_iv_t
  - rho_1 = corr(residual_t, residual_{t-1})

Expected:
  - rho_1 < 0  → mean-reverting → BUY when residual_t > 0 (rich, will revert)
  - rho_1 > 0  → momentum → FOLLOW direction
  - rho_1 ≈ 0 → no signal

Output: artifacts/analysis/round_3_option_velvet/iv_residual_autocorr.csv
        + plots in iv_timeseries/
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from prosperity.options.implied_vol import call_implied_vol

DATA = ROOT / "data" / "round_3"
OUT = ROOT / "artifacts" / "analysis" / "round_3_option_velvet"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
DAYS = [0, 1, 2]
TTE_BY_DAY = {0: 8.0, 1: 7.0, 2: 6.0}


def compute_residuals_for_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
    velvet = df[df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"]
    T0 = TTE_BY_DAY[day]

    # Compute IV per strike per timestamp
    all_ivs: dict[int, pd.Series] = {}
    for K in STRIKES:
        sub = df[df["product"] == f"VEV_{K}"].set_index("timestamp")
        if sub.empty: continue
        rows = []
        for ts in sub.index:
            spot = velvet.get(ts)
            if spot is None: continue
            T = max(0.01, T0 - ts / 1_000_000.0)
            iv = call_implied_vol(sub.loc[ts, "mid_price"], spot, K, T, sigma_init=0.0125)
            if iv is None or iv <= 0: continue
            rows.append((ts, iv))
        if rows:
            df_iv = pd.DataFrame(rows, columns=["timestamp", "iv"]).set_index("timestamp")
            all_ivs[K] = df_iv["iv"]

    # Align by timestamp + compute polynomial smile fit per tick
    all_ts = sorted(set.intersection(*[set(s.index) for s in all_ivs.values()]))
    if not all_ts: return pd.DataFrame()

    residuals = {K: [] for K in all_ivs}
    timestamps = []
    for ts in all_ts:
        ks, ivs = [], []
        for K in all_ivs:
            iv = all_ivs[K].get(ts)
            if iv is None: continue
            spot = velvet.get(ts)
            if spot is None: continue
            T = max(0.01, T0 - ts / 1_000_000.0)
            m = math.log(K / spot) / math.sqrt(T)
            ks.append(m); ivs.append(iv)
        if len(ks) < 6: continue
        coeffs = np.polyfit(ks, ivs, deg=2)
        for K, m, iv in zip(list(all_ivs.keys()), ks, ivs):
            fitted = np.polyval(coeffs, m)
            residuals[K].append(iv - fitted)
        timestamps.append(ts)

    rdf = pd.DataFrame(residuals, index=timestamps)
    return rdf


def autocorr_lag1(series: pd.Series) -> float:
    s = series.dropna().values
    if len(s) < 50: return float("nan")
    x = s[:-1]; y = s[1:]
    return np.corrcoef(x, y)[0, 1]


def autocorr_multi_lags(series: pd.Series, max_lag: int = 20) -> list[float]:
    s = series.dropna().values
    if len(s) < 50: return [float("nan")] * max_lag
    out = []
    for lag in range(1, max_lag + 1):
        if len(s) <= lag: out.append(float("nan")); continue
        x = s[:-lag]; y = s[lag:]
        out.append(np.corrcoef(x, y)[0, 1])
    return out


def main():
    print("Computing IV residuals + 1-lag autocorrelation per strike per day...\n")
    rows = []
    for day in DAYS:
        print(f"=== Day {day} ===")
        rdf = compute_residuals_for_day(day)
        if rdf.empty: continue
        for K in rdf.columns:
            ac1 = autocorr_lag1(rdf[K])
            std = rdf[K].std()
            mean = rdf[K].mean()
            n = rdf[K].count()
            print(f"  K={K}: n={n:>5}  mean={mean:+.5f}  std={std:.5f}  ρ_1={ac1:+.4f}")
            rows.append(dict(
                day=day, K=K, n=int(n),
                mean_residual=round(mean, 6), std_residual=round(std, 6),
                rho_1=round(ac1, 4),
            ))

        # Plot autocorrelation function (multi-lag) for each strike
        fig, axes = plt.subplots(3, 3, figsize=(15, 9))
        plot_strikes = [K for K in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000] if K in rdf.columns]
        for ax, K in zip(axes.flatten(), plot_strikes):
            ac = autocorr_multi_lags(rdf[K], max_lag=20)
            ax.bar(range(1, 21), ac, alpha=0.7)
            ax.axhline(0, color="k", lw=0.5)
            ax.axhline(0.05, color="r", ls="--", lw=0.5, label="±0.05")
            ax.axhline(-0.05, color="r", ls="--", lw=0.5)
            ax.set_title(f"VEV_{K} — IV residual ACF (Day {day})")
            ax.set_xlabel("lag"); ax.set_ylabel("autocorr")
            ax.grid(alpha=0.3); ax.tick_params(labelsize=8)
        plt.suptitle(f"IV residual autocorrelation function — Day {day}\n(negative ρ_1 = mean-reverting → IV scalping has alpha)")
        plt.tight_layout()
        plt.savefig(OUT / "iv_timeseries" / f"iv_residual_acf_day_{day}.png", dpi=110)
        plt.close(fig)

    # Aggregate table per-strike across all days
    print("\n\n=== Aggregate (mean ρ_1 across 3 days) ===")
    df = pd.DataFrame(rows)
    if not df.empty:
        agg = df.groupby("K").agg(mean_rho1=("rho_1", "mean"),
                                  std_rho1=("rho_1", "std"),
                                  mean_residual=("mean_residual", "mean"),
                                  std_residual=("std_residual", "mean")).round(4)
        print(agg.to_string())
        agg.to_csv(OUT / "iv_residual_autocorr.csv")
        print(f"\n→ CSV: {OUT / 'iv_residual_autocorr.csv'}")
        # Verdict per strike
        print("\nVerdict per strike (rho_1 sign + magnitude):")
        for K in agg.index:
            r = agg.loc[K, "mean_rho1"]
            if r < -0.1:
                v = "STRONG mean-reversion (IV scalping has alpha)"
            elif r < -0.02:
                v = "weak mean-reversion (marginal)"
            elif r > 0.1:
                v = "STRONG momentum (follow direction)"
            elif r > 0.02:
                v = "weak momentum"
            else:
                v = "no signal (rho ≈ 0)"
            print(f"  K={K}: ρ_1={r:+.4f}  → {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
