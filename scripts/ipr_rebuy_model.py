"""Probabilistic rebuy model for IPR.

For each tick where we could hit best_bid and sell, simulate: given we sold
at price P, what is the distribution of time-to-refill at price P - delta?
Refill = an ask in the book at price <= P - delta (crossable) OR a market
trade printed at price <= P - delta (passive fill).

We try several deltas (0, 1, 2, 5, 10) and report:
  - fill rate within horizon H (e.g. 1000, 5000, 20000 ticks)
  - mean / median / p95 fill time
  - expected PnL per trade cycle = delta * fill_rate - penalty * (1-fill_rate)
    where penalty = mean drift of mid during horizon when unfilled

Also: fit exponential to inter-arrival of cheap trades, compute CV to detect
clustering (CV > 1 = bursty, CV ~ 1 = Poisson, CV < 1 = regular).
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path("data/round_1")
PRODUCT = "INTARIAN_PEPPER_ROOT"
DELTAS = [0, 1, 2, 5, 10]
HORIZONS = [1000, 3000, 10000, 30000]
SAMPLE_EVERY = 100  # subsample sell opportunities to keep it tractable


def load_day(day: int):
    p = pd.read_csv(DATA / f"prices_round_1_day_{day}.csv", sep=";")
    t = pd.read_csv(DATA / f"trades_round_1_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)
    t = t[t["symbol"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)
    return p, t


def poisson_check(intervals: np.ndarray) -> tuple[float, float]:
    if len(intervals) < 5:
        return float("nan"), float("nan")
    mean = intervals.mean()
    std = intervals.std()
    cv = std / mean if mean > 0 else float("nan")
    return mean, cv


def simulate_rebuy(prices: pd.DataFrame, trades: pd.DataFrame,
                   delta: int, horizon: int) -> dict:
    """For each sampled tick, pretend we sold at best_bid and try to rebuy
    at (sell_price - delta). Look forward up to `horizon` ticks. Rebuy fills
    if any future best_ask <= target OR any trade price <= target."""
    ts = prices["timestamp"].to_numpy()
    bid = prices["bid_price_1"].to_numpy()
    ask = prices["ask_price_1"].to_numpy()
    mid = prices["mid_price"].to_numpy()
    trade_ts = trades["timestamp"].to_numpy()
    trade_px = trades["price"].to_numpy()

    n_fills = 0
    n_total = 0
    fill_times = []
    drift_unfilled = []

    for i in range(0, len(ts), SAMPLE_EVERY):
        sell_price = bid[i]
        target = sell_price - delta
        t0 = ts[i]
        t_end = t0 + horizon

        # Look forward in prices
        j_end = np.searchsorted(ts, t_end, side="right")
        future_asks = ask[i + 1:j_end]
        future_ts = ts[i + 1:j_end]

        fill_idx_ask = np.where(future_asks <= target)[0]
        fill_t_ask = future_ts[fill_idx_ask[0]] if len(fill_idx_ask) else None

        # Look forward in trades
        k0 = np.searchsorted(trade_ts, t0, side="right")
        k_end = np.searchsorted(trade_ts, t_end, side="right")
        fut_trade_px = trade_px[k0:k_end]
        fut_trade_ts = trade_ts[k0:k_end]
        fill_idx_tr = np.where(fut_trade_px <= target)[0]
        fill_t_tr = fut_trade_ts[fill_idx_tr[0]] if len(fill_idx_tr) else None

        candidates = [x for x in (fill_t_ask, fill_t_tr) if x is not None]
        n_total += 1
        if candidates:
            fill_t = min(candidates)
            fill_times.append(fill_t - t0)
            n_fills += 1
        else:
            # Drift: how much did mid move by horizon end
            if j_end > i + 1:
                drift_unfilled.append(mid[j_end - 1] - mid[i])

    rate = n_fills / n_total if n_total else 0.0
    mean_fill = float(np.mean(fill_times)) if fill_times else float("nan")
    med_fill = float(np.median(fill_times)) if fill_times else float("nan")
    p95_fill = float(np.percentile(fill_times, 95)) if fill_times else float("nan")
    mean_drift = float(np.mean(drift_unfilled)) if drift_unfilled else float("nan")

    # Expected PnL per cycle
    # filled: gain = delta
    # unfilled: we're short, market drifted up by mean_drift, loss ~ mean_drift
    # (forced buyback at worse price at end of horizon)
    exp_pnl = rate * delta - (1 - rate) * (mean_drift if not np.isnan(mean_drift) else 0)

    return dict(n_total=n_total, n_fills=n_fills, fill_rate=rate,
                mean_fill=mean_fill, med_fill=med_fill, p95_fill=p95_fill,
                mean_drift_unfilled=mean_drift, exp_pnl=exp_pnl)


def main() -> None:
    for day in (-2, -1, 0):
        prices, trades = load_day(day)
        print(f"\n{'='*72}")
        print(f"DAY {day}  |  {len(prices)} ticks  {len(trades)} trades")
        print(f"{'='*72}")

        # Poisson check on raw trade arrivals
        tt = trades["timestamp"].to_numpy()
        intervals = np.diff(tt)
        mean, cv = poisson_check(intervals)
        print(f"\nAll trades inter-arrival: mean={mean:.0f}  CV={cv:.2f}  "
              f"({'Poisson' if 0.8 < cv < 1.2 else 'clustered' if cv > 1.2 else 'regular'})")

        # Cheap trades (below mid) inter-arrival
        mid = prices.set_index("timestamp")["mid_price"]
        trade_mid = mid.reindex(trades["timestamp"]).ffill().to_numpy()
        cheap_mask = trades["price"].to_numpy() < trade_mid
        cheap_ts = tt[cheap_mask]
        cheap_intervals = np.diff(cheap_ts)
        m2, cv2 = poisson_check(cheap_intervals)
        print(f"Cheap trades (<mid) : n={len(cheap_ts):4d}  mean_wait={m2:.0f}  CV={cv2:.2f}")

        # Rebuy simulation grid
        print(f"\n{'delta':>6} {'horizon':>8} {'fill%':>7} {'mean_fill':>10} "
              f"{'med':>7} {'p95':>7} {'drift_unfill':>13} {'E[pnl]':>9}")
        print("-" * 72)
        for delta in DELTAS:
            for H in HORIZONS:
                r = simulate_rebuy(prices, trades, delta, H)
                print(f"{delta:>6} {H:>8} {r['fill_rate']*100:>6.1f}% "
                      f"{r['mean_fill']:>10.0f} {r['med_fill']:>7.0f} "
                      f"{r['p95_fill']:>7.0f} {r['mean_drift_unfilled']:>13.1f} "
                      f"{r['exp_pnl']:>9.2f}")


if __name__ == "__main__":
    main()
