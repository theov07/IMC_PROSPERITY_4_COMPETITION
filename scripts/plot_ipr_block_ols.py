"""IPR block-OLS residuals (V5-style): OLS on block means, several block sizes.

Computes R^2 of OLS fit on block-mean series (not raw ticks). Block means
smooth noise, so R^2 is much higher than rolling raw-tick OLS.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

DATA_DIR = Path("data/round_1")
OUT_DIR = Path("artifacts/analysis/round_1/theo/Leo")
PRODUCT = "INTARIAN_PEPPER_ROOT"
BLOCK_SIZES = [50, 100, 150, 200, 300, 500]


def block_means(y: np.ndarray, block: int) -> np.ndarray:
    n = (len(y) // block) * block
    return y[:n].reshape(-1, block).mean(axis=1)


def ols_r2(means: np.ndarray) -> tuple[float, np.ndarray]:
    x = np.arange(len(means), dtype=float)
    slope, intercept = np.polyfit(x, means, 1)
    fitted = slope * x + intercept
    ss_res = np.sum((means - fitted) ** 2)
    ss_tot = np.sum((means - means.mean()) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(r2), fitted


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for day in (-2, -1, 0):
        df = pd.read_csv(DATA_DIR / f"prices_round_1_day_{day}.csv", sep=";")
        df = df[df["product"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)
        mid = df["mid_price"].to_numpy()
        ts = df["timestamp"].to_numpy()

        print(f"day {day}:")
        results = {}
        for b in BLOCK_SIZES:
            if b >= len(mid):
                continue
            means = block_means(mid, b)
            r2, fitted = ols_r2(means)
            results[b] = (r2, means, fitted)
            print(f"  block={b:4d}: R^2={r2:.4f}  (n_blocks={len(means)})")

        best_b = max(results, key=lambda k: results[k][0])
        fig, axes = plt.subplots(2, 1, figsize=(14, 8))
        axes[0].plot(ts, mid, color="grey", linewidth=0.4, alpha=0.6, label="mid (raw)")
        for b, (r2, means, fitted) in results.items():
            x_blk = np.arange(len(means)) * b + b / 2
            ts_blk = ts[x_blk.astype(int).clip(max=len(ts) - 1)]
            if b == best_b:
                axes[0].plot(ts_blk, means, "o", markersize=3, label=f"block mean b={b}")
                axes[0].plot(ts_blk, fitted, "-", linewidth=1.5,
                             label=f"OLS fit b={b} (R^2={r2:.3f}) <- best")
        axes[0].set_title(f"IPR day {day}: block-mean OLS (best block={best_b})")
        axes[0].legend(loc="upper left")
        axes[0].grid(alpha=0.3)

        for b, (r2, means, fitted) in results.items():
            x_blk = np.arange(len(means)) * b + b / 2
            ts_blk = ts[x_blk.astype(int).clip(max=len(ts) - 1)]
            resid = means - fitted
            lw = 1.5 if b == best_b else 0.7
            alpha = 1.0 if b == best_b else 0.4
            axes[1].plot(ts_blk, resid, linewidth=lw, alpha=alpha,
                         label=f"b={b} R^2={r2:.3f}")
        axes[1].axhline(0, color="black", linewidth=0.5)
        axes[1].set_xlabel("timestamp")
        axes[1].set_ylabel("block_mean - fitted")
        axes[1].set_title("Residuals across block sizes")
        axes[1].legend(loc="upper left", ncol=2, fontsize=8)
        axes[1].grid(alpha=0.3)

        fig.tight_layout()
        out = OUT_DIR / f"ipr_block_ols_day_{day}.png"
        fig.savefig(out, dpi=120)
        plt.close(fig)
        print(f"  -> {out}")


if __name__ == "__main__":
    main()
