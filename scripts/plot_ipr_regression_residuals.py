"""Plot IPR mid - block-OLS regression residuals across rolling windows.

For each day of round 1, finds the rolling OLS window that maximizes in-sample
R^2 on the mid-price series, then plots (mid - fitted) residuals over time.
Outputs to artifacts/analysis/round_1/theo/Leo.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

DATA_DIR = Path("data/round_1")
OUT_DIR = Path("artifacts/analysis/round_1/theo/Leo")
PRODUCT = "INTARIAN_PEPPER_ROOT"
WINDOWS = [50, 100, 200, 500, 1000, 2000, 5000]


def rolling_ols_residuals(y: np.ndarray, window: int) -> tuple[np.ndarray, float]:
    n = len(y)
    resid = np.full(n, np.nan)
    r2s = []
    for i in range(window, n + 1):
        seg = y[i - window : i]
        x = np.arange(window, dtype=float)
        slope, intercept = np.polyfit(x, seg, 1)
        fitted = slope * x + intercept
        ss_res = np.sum((seg - fitted) ** 2)
        ss_tot = np.sum((seg - seg.mean()) ** 2)
        r2s.append(1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0)
        resid[i - 1] = seg[-1] - fitted[-1]
    return resid, float(np.mean(r2s))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for day in (-2, -1, 0):
        csv = DATA_DIR / f"prices_round_1_day_{day}.csv"
        df = pd.read_csv(csv, sep=";")
        df = df[df["product"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)
        mid = df["mid_price"].to_numpy()
        ts = df["timestamp"].to_numpy()

        r2_by_w = {}
        resid_by_w = {}
        for w in WINDOWS:
            if w >= len(mid):
                continue
            resid, r2 = rolling_ols_residuals(mid, w)
            r2_by_w[w] = r2
            resid_by_w[w] = resid

        best_w = max(r2_by_w, key=r2_by_w.get)
        print(f"day {day}: mean R^2 per window:")
        for w, r2 in sorted(r2_by_w.items()):
            marker = "  <- best" if w == best_w else ""
            print(f"  w={w:5d}: R^2={r2:.4f}{marker}")

        fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
        axes[0].plot(ts, mid, color="black", linewidth=0.7, label="mid")
        fitted_best = mid - resid_by_w[best_w]
        axes[0].plot(ts, fitted_best, color="red", linewidth=0.8,
                     label=f"rolling OLS fit (w={best_w}, R^2={r2_by_w[best_w]:.3f})")
        axes[0].set_ylabel("price")
        axes[0].set_title(f"IPR day {day}: mid vs rolling OLS (best window = {best_w})")
        axes[0].legend(loc="upper left")
        axes[0].grid(alpha=0.3)

        for w, resid in resid_by_w.items():
            lw = 1.3 if w == best_w else 0.6
            alpha = 1.0 if w == best_w else 0.4
            axes[1].plot(ts, resid, linewidth=lw, alpha=alpha,
                         label=f"w={w} (R^2={r2_by_w[w]:.3f})")
        axes[1].axhline(0, color="black", linewidth=0.5)
        axes[1].set_ylabel("mid - fitted")
        axes[1].set_xlabel("timestamp")
        axes[1].set_title("Residuals (price - regression) across windows")
        axes[1].legend(loc="upper left", ncol=2, fontsize=8)
        axes[1].grid(alpha=0.3)

        fig.tight_layout()
        out_path = OUT_DIR / f"ipr_regression_residuals_day_{day}.png"
        fig.savefig(out_path, dpi=120)
        plt.close(fig)
        print(f"  -> saved {out_path}")


if __name__ == "__main__":
    main()
