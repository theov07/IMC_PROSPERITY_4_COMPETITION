"""Regime-adaptive AR(1) analysis — clean per-day.

Key finding from GARCH: AR(1) = -0.71 in lo-vol vs -0.39 in hi-vol.
Question: can we detect the regime in real-time and adapt ar_gain?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DATA = [
    ("data/round_1/prices_round_1_day_-2.csv", "-2"),
    ("data/round_1/prices_round_1_day_-1.csv", "-1"),
    ("data/round_1/prices_round_1_day_0.csv", "0"),
]
PRODUCT = "ASH_COATED_OSMIUM"


def main():
    for path, day in DATA:
        df = pd.read_csv(path, sep=";")
        df.columns = [c.strip() for c in df.columns]
        p = df[df["product"] == PRODUCT].copy().sort_values("timestamp").reset_index(drop=True)
        mid = p["mid_price"].dropna().values.astype(float)
        ret = np.diff(mid)
        n = len(ret)

        print(f"\n=== Day {day} ({n} returns) ===")

        # rolling vol (EMA) with different windows
        for win in [10, 20, 50]:
            alpha = 2.0 / (win + 1)
            ema_sq = np.zeros(n)
            ema_sq[0] = ret[0] ** 2
            for i in range(1, n):
                ema_sq[i] = alpha * ret[i] ** 2 + (1 - alpha) * ema_sq[i - 1]
            vol = np.sqrt(ema_sq)

            med_vol = np.median(vol)
            hi = vol > med_vol
            lo = ~hi

            # AR(1) per regime (use lagged values to avoid lookahead)
            valid_hi = np.where(hi[:-1])[0]
            valid_lo = np.where(lo[:-1])[0]
            valid_hi = valid_hi[valid_hi + 1 < n]
            valid_lo = valid_lo[valid_lo + 1 < n]

            ar1_hi = np.corrcoef(ret[valid_hi], ret[valid_hi + 1])[0, 1] if len(valid_hi) > 10 else float("nan")
            ar1_lo = np.corrcoef(ret[valid_lo], ret[valid_lo + 1])[0, 1] if len(valid_lo) > 10 else float("nan")

            # Optimal ar_gain per regime (since reversal = -ar1, gain ~ |ar1|)
            print(f"  vol_window={win:>2}: hi_n={len(valid_hi):>5} AR1_hi={ar1_hi:+.4f}  lo_n={len(valid_lo):>5} AR1_lo={ar1_lo:+.4f}  gap={ar1_lo - ar1_hi:+.4f}")

        # Asymmetry: per-day clean
        dev = mid - 10000.0
        print(f"\n  Asymmetry (clean, per-day):")
        print(f"  {'bucket':>12} {'n':>5} {'E[fwd_1]':>10} {'E[fwd_5]':>10} {'E[fwd_10]':>10}")
        for lo_b in range(-10, 11, 2):
            hi_b = lo_b + 2
            m = (dev[:-1] >= lo_b) & (dev[:-1] < hi_b)
            cnt = m.sum()
            if cnt < 10:
                continue
            e1 = ret[m].mean()
            idxs = np.where(m)[0]
            fwd5 = [mid[i + 5] - mid[i] for i in idxs if i + 5 < len(mid)]
            fwd10 = [mid[i + 10] - mid[i] for i in idxs if i + 10 < len(mid)]
            e5 = np.mean(fwd5) if fwd5 else float("nan")
            e10 = np.mean(fwd10) if fwd10 else float("nan")
            print(f"  [{lo_b:>3},{hi_b:>3}) {cnt:>5} {e1:>+10.3f} {e5:>+10.3f} {e10:>+10.3f}")

        # Correlations: vol vs |fwd|
        for win in [10, 20]:
            alpha = 2.0 / (win + 1)
            ema_sq = np.zeros(n)
            ema_sq[0] = ret[0] ** 2
            for i in range(1, n):
                ema_sq[i] = alpha * ret[i] ** 2 + (1 - alpha) * ema_sq[i - 1]
            vol = np.sqrt(ema_sq)
            corr = np.corrcoef(vol[:-1], np.abs(ret[1:]))[0, 1]
            print(f"\n  corr(vol_ema{win}, |fwd_1|) = {corr:+.4f}")


main()
