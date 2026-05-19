"""Inter-arrival analysis of IPR trades above/below block-OLS fair value.

For each tick, compute fv via block-OLS (block=200) on mid history. Then
classify observed market trades by (price - fv). For each threshold k,
compute:
  - Count of trades with price >= fv + k  (rich sells we could passively sell into)
  - Count of trades with price <= fv - k  (cheap asks we could passively buy from)
  - Inter-arrival times (in ticks) of these events
  - Empirical CDF to see if it's exponential / heavy-tailed

Output: stdout summary + plots in artifacts/analysis/round_1/arrival.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

DATA = Path("data/round_1")
OUT = Path("artifacts/analysis/round_1/arrival")
PRODUCT = "INTARIAN_PEPPER_ROOT"
BLOCK = 200
THRESHOLDS = [0, 2, 5, 10, 15]


def block_ols_fv(mid: np.ndarray, ts: np.ndarray, block: int) -> np.ndarray:
    """Rolling block-OLS fv at each tick, using all blocks completed so far."""
    n = len(mid)
    fv = np.full(n, np.nan)
    block_means = []
    block_centers = []
    for i in range(n):
        if (i + 1) % block == 0:
            start = i + 1 - block
            block_means.append(mid[start:i + 1].mean())
            block_centers.append((start + i) / 2.0)
        if len(block_means) >= 3:
            x = np.array(block_centers)
            y = np.array(block_means)
            slope, intercept = np.polyfit(x, y, 1)
            fv[i] = slope * i + intercept
    return fv


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 2, figsize=(14, 10))

    for row, day in enumerate((-2, -1, 0)):
        prices = pd.read_csv(DATA / f"prices_round_1_day_{day}.csv", sep=";")
        trades = pd.read_csv(DATA / f"trades_round_1_day_{day}.csv", sep=";")
        prices = prices[prices["product"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)
        trades = trades[trades["symbol"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)

        mid = prices["mid_price"].to_numpy()
        ts = prices["timestamp"].to_numpy()
        fv = block_ols_fv(mid, ts, BLOCK)

        # Interpolate fv at trade timestamps
        valid = ~np.isnan(fv)
        fv_at_trade = np.interp(trades["timestamp"].to_numpy(),
                                ts[valid], fv[valid])
        trade_dev = trades["price"].to_numpy() - fv_at_trade  # signed dev from fv
        trade_ts = trades["timestamp"].to_numpy()

        print(f"\n=== day {day} ===")
        print(f"trades total: {len(trades)}  mean_dev={trade_dev.mean():+.2f}  "
              f"std={trade_dev.std():.2f}  min={trade_dev.min():+.1f}  max={trade_dev.max():+.1f}")

        for k in THRESHOLDS:
            rich_mask = trade_dev >= k
            cheap_mask = trade_dev <= -k
            n_rich = int(rich_mask.sum())
            n_cheap = int(cheap_mask.sum())
            if n_rich >= 2:
                rich_intervals = np.diff(trade_ts[rich_mask])
                mean_wait = rich_intervals.mean()
                med_wait = np.median(rich_intervals)
                p95 = np.percentile(rich_intervals, 95)
            else:
                mean_wait = med_wait = p95 = float("nan")
            print(f"  k=+{k:<3d}  rich sells: n={n_rich:5d}  "
                  f"mean_wait={mean_wait:7.0f}  med={med_wait:7.0f}  p95={p95:7.0f}  "
                  f"|  cheap buys: n={n_cheap:5d}")

        # Scatter: deviation vs time
        ax_left = axes[row, 0]
        ax_left.scatter(trade_ts, trade_dev, s=2, alpha=0.4, c="#7048e8")
        ax_left.axhline(0, color="black", lw=0.5)
        for k in [5, 10]:
            ax_left.axhline(k, color="red", lw=0.5, ls="--")
            ax_left.axhline(-k, color="green", lw=0.5, ls="--")
        ax_left.set_title(f"day {day}: trade price - fv")
        ax_left.set_xlabel("timestamp")
        ax_left.set_ylabel("price - fv")
        ax_left.grid(alpha=0.3)

        # Histogram of rich inter-arrivals (k=5)
        ax_right = axes[row, 1]
        rich_mask5 = trade_dev >= 5
        if rich_mask5.sum() >= 2:
            intervals = np.diff(trade_ts[rich_mask5])
            ax_right.hist(intervals, bins=50, color="#e03131", alpha=0.7)
            ax_right.set_title(f"day {day}: inter-arrival of trades with dev >= +5")
            ax_right.set_xlabel("ticks between events")
            ax_right.set_ylabel("count")
            ax_right.grid(alpha=0.3)

    fig.tight_layout()
    out = OUT / "ipr_arrival_analysis.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
