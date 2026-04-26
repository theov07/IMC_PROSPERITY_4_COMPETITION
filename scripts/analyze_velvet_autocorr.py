"""VELVET return autocorrelation test.
Last year's team had VELVET (or its equivalent) mean-reverting → z-score
trading worked. We test this for round 3.

For VELVET mid returns, compute:
  - 1-tick return: r_t = (mid_t - mid_{t-1}) / mid_{t-1}
  - ρ_1 of returns: corr(r_t, r_{t-1})
  - 1-tick deviation from EMA(N): (mid_t - ema_N) / sigma → z-score

Mean-reversion thesis valid IF ρ_1 < 0 on returns.
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data" / "round_3"
OUT = ROOT / "artifacts" / "analysis" / "round_3_option_velvet"
DAYS = [0, 1, 2]


def autocorr(s: pd.Series, lag: int = 1) -> float:
    s = s.dropna().values
    if len(s) <= lag: return float("nan")
    x = s[:-lag]; y = s[lag:]
    return np.corrcoef(x, y)[0, 1]


def main():
    rows = []
    for day in DAYS:
        df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
        velvet = df[df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"].sort_index()
        rets = velvet.pct_change().dropna()

        rho_1 = autocorr(rets, 1)
        rho_5 = autocorr(rets, 5)
        rho_10 = autocorr(rets, 10)
        rho_50 = autocorr(rets, 50)
        path_return = (velvet.iloc[-1] - velvet.iloc[0]) / velvet.iloc[0]
        ann_vol = rets.std() * math.sqrt(252.0 * 10000)

        print(f"=== Day {day} VELVET ===")
        print(f"  start={velvet.iloc[0]:.2f}  end={velvet.iloc[-1]:.2f}  path return={path_return*100:+.3f}%")
        print(f"  realized vol (annualized): {ann_vol:.4f}")
        print(f"  ρ_1={rho_1:+.4f}  ρ_5={rho_5:+.4f}  ρ_10={rho_10:+.4f}  ρ_50={rho_50:+.4f}")
        rows.append(dict(day=day, rho_1=rho_1, rho_5=rho_5, rho_10=rho_10, rho_50=rho_50,
                          path_return_pct=path_return*100, ann_vol=ann_vol))

        # Z-score test: deviation from rolling 500-tick mean
        roll_mean = velvet.rolling(500).mean()
        roll_std = velvet.rolling(500).std()
        z = (velvet - roll_mean) / roll_std
        # Mean-reversion test: when |z| > 1, does the next return point back toward zero?
        mask = z.shift(1).abs() > 1.0
        sign_z = np.sign(z.shift(1))   # +1 if mid above mean, -1 if below
        ret_aligned = rets.reindex(z.index)
        # If mean-reverting: when sign_z = +1 (rich), next return should be NEGATIVE
        # → corr(sign_z, return) should be NEGATIVE
        valid = mask & sign_z.notna() & ret_aligned.notna()
        if valid.sum() > 100:
            sz = sign_z[valid].values
            r_next = ret_aligned[valid].values
            mean_r_when_rich = r_next[sz > 0].mean() * 1e4
            mean_r_when_cheap = r_next[sz < 0].mean() * 1e4
            print(f"  z>1 events: {valid.sum()}")
            print(f"    Mean next return when rich (z>1):   {mean_r_when_rich:+.2f} bp/tick")
            print(f"    Mean next return when cheap (z<-1): {mean_r_when_cheap:+.2f} bp/tick")
            print(f"    {'(MEAN-REV: rich→neg, cheap→pos)' if mean_r_when_rich < 0 < mean_r_when_cheap else '(NOT mean-reverting at z=1 threshold)'}")

        # Plot
        fig, axes = plt.subplots(1, 3, figsize=(15, 4))
        axes[0].plot(velvet.index, velvet.values, lw=0.5)
        axes[0].plot(roll_mean.index, roll_mean.values, lw=1, color="r", alpha=0.7, label="500-tick mean")
        axes[0].set_title(f"VELVET mid + rolling mean — Day {day}")
        axes[0].legend(); axes[0].grid(alpha=0.3)
        axes[1].plot(z.index, z.values, lw=0.4)
        axes[1].axhline(0, color="k", lw=0.5)
        axes[1].axhline(1, color="orange", lw=0.5, ls="--", label="±1σ")
        axes[1].axhline(-1, color="orange", lw=0.5, ls="--")
        axes[1].set_title(f"VELVET z-score (500-tick) — Day {day}")
        axes[1].legend(); axes[1].grid(alpha=0.3)
        # Multi-lag autocorrelation
        lags = list(range(1, 51))
        ac = [autocorr(rets, l) for l in lags]
        axes[2].bar(lags, ac, alpha=0.7)
        axes[2].axhline(0, color="k", lw=0.5)
        axes[2].axhline(0.02, color="r", lw=0.5, ls="--", label="±0.02")
        axes[2].axhline(-0.02, color="r", lw=0.5, ls="--")
        axes[2].set_title(f"Return autocorrelation (lag 1-50) — Day {day}")
        axes[2].set_xlabel("lag"); axes[2].set_ylabel("autocorr")
        axes[2].legend(); axes[2].grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(OUT / "velvet" / f"velvet_autocorr_day_{day}.png", dpi=120)
        plt.close(fig)

    print("\n=== Aggregate ===")
    df = pd.DataFrame(rows)
    print(df.round(4).to_string(index=False))
    df.to_csv(OUT / "velvet_autocorr.csv", index=False)
    print(f"\n→ CSV: {OUT / 'velvet_autocorr.csv'}")

    # Verdict
    avg_rho1 = df["rho_1"].mean()
    print(f"\nVerdict: avg ρ_1 = {avg_rho1:+.4f}")
    if avg_rho1 < -0.05:
        print("  → STRONG mean-reversion in returns. z-score trading WORKS.")
    elif avg_rho1 < -0.01:
        print("  → weak mean-reversion. Marginal.")
    elif avg_rho1 > 0.05:
        print("  → MOMENTUM in returns. Trend-following preferred.")
    else:
        print("  → no clear signal in returns. z-score trading marginal.")


if __name__ == "__main__":
    main()
