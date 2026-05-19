"""Smile residual signal — per-strike IV deviation from polynomial fit.

For each tick:
  1. Compute IV per strike using BS solver
  2. Fit a polynomial (degree=2) of IV vs log-moneyness
  3. Compute residual per strike = actual_IV - smile_fit_IV
  4. Test: does the residual SIGN predict next-N-tick mid return for that strike?

If yes: per-strike residual arb — buy when underpriced, sell when overpriced.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# We need BS implied vol — use a simple bisection solver
def bs_call_price(S, K, T, sigma, r=0):
    """Black-Scholes call option price (no dividends, r=0 by default)."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    n_d1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    n_d2 = 0.5 * (1 + math.erf(d2 / math.sqrt(2)))
    return S * n_d1 - K * math.exp(-r * T) * n_d2


def bs_implied_vol(market_price, S, K, T, sigma_init=0.0125):
    """Bisection BS IV solver."""
    if T <= 0 or market_price <= 0:
        return None
    intrinsic = max(S - K, 0)
    if market_price < intrinsic - 0.5:  # below intrinsic
        return None
    lo, hi = 1e-4, 5.0
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        p = bs_call_price(S, K, T, mid)
        if p > market_price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-5:
            break
    return 0.5 * (lo + hi)


def fit_quad(xs, ys):
    """Fit y = a + b*x + c*x^2. Return (a, b, c)."""
    n = len(xs)
    if n < 3:
        return None
    # Solve normal equations: [n, Sx, Sxx; Sx, Sxx, Sxxx; Sxx, Sxxx, Sxxxx] [a,b,c] = [Sy, Sxy, Sxxy]
    Sx = sum(xs)
    Sy = sum(ys)
    Sxx = sum(x*x for x in xs)
    Sxxx = sum(x**3 for x in xs)
    Sxxxx = sum(x**4 for x in xs)
    Sxy = sum(x*y for x, y in zip(xs, ys))
    Sxxy = sum(x*x*y for x, y in zip(xs, ys))

    # 3x3 matrix inverse via Cramer
    A = [[n, Sx, Sxx], [Sx, Sxx, Sxxx], [Sxx, Sxxx, Sxxxx]]
    B = [Sy, Sxy, Sxxy]
    detA = (A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1])
            - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0])
            + A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0]))
    if abs(detA) < 1e-10:
        return None
    def replace_col(M, col, vec):
        return [[vec[i] if j == col else M[i][j] for j in range(3)] for i in range(3)]
    def det3(M):
        return (M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
                - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
                + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]))
    a = det3(replace_col(A, 0, B)) / detA
    b = det3(replace_col(A, 1, B)) / detA
    c = det3(replace_col(A, 2, B)) / detA
    return (a, b, c)


def main():
    print("=" * 100)
    print("SMILE RESIDUAL PREDICTIVE TEST — per-strike IV deviation from poly fit")
    print("=" * 100)

    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400]
    tte_by_day = {1: 7.0, 2: 6.0, 3: 5.0}

    # Load all relevant prices per day
    print("Loading prices...")
    velvet_mid_by_ts = {}
    option_mid_by_ts = defaultdict(dict)  # ts → {K: mid}
    for d in (1, 2, 3):
        offset = (d - 1) * 1_000_000
        path = ROOT / "data" / "round_4" / f"prices_round_4_day_{d}.csv"
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                try:
                    sym = row["product"]
                    ts = int(row["timestamp"]) + offset
                    mid = float(row["mid_price"])
                    if sym == "VELVETFRUIT_EXTRACT":
                        velvet_mid_by_ts[ts] = mid
                    elif sym.startswith("VEV_"):
                        K = int(sym.split("_")[1])
                        if K in strikes:
                            option_mid_by_ts[ts][K] = mid
                except Exception:
                    continue

    # For each tick, compute IVs and residuals
    # Sample every 50 ticks to keep computation manageable
    sample_step = 50 * 100  # 50 ticks
    sorted_ts = sorted(velvet_mid_by_ts.keys())
    sample_ts = sorted_ts[::50]
    print(f"Computing residuals for {len(sample_ts):,} sampled ticks...")

    # Track per-strike residual time series
    residuals = defaultdict(list)  # K → [(ts, resid)]

    for ts in sample_ts:
        S = velvet_mid_by_ts[ts]
        # Day from ts
        day = (ts // 1_000_000) + 1
        T_days = tte_by_day.get(day, 5)
        # Subtract elapsed within day
        intra_ts = ts % 1_000_000
        T_remaining = T_days - intra_ts / 1_000_000
        T = max(T_remaining, 0.01) / 365.0

        # Compute IVs
        ivs = {}
        for K in strikes:
            opt_mid = option_mid_by_ts.get(ts, {}).get(K)
            if opt_mid is None or opt_mid <= 0:
                continue
            iv = bs_implied_vol(opt_mid, S, K, T)
            if iv is None or iv < 0.001 or iv > 1.0:
                continue
            ivs[K] = iv

        if len(ivs) < 4:
            continue

        # Fit poly in log-moneyness
        log_m = [math.log(K / S) for K in ivs.keys()]
        ys = list(ivs.values())
        coeffs = fit_quad(log_m, ys)
        if coeffs is None:
            continue
        a, b, c = coeffs

        for K, iv in ivs.items():
            x = math.log(K / S)
            fit_iv = a + b * x + c * x * x
            resid = iv - fit_iv
            residuals[K].append((ts, resid, iv, fit_iv))

    # Test: does residual sign predict next-N-tick mid return for that option?
    print("\n" + "=" * 100)
    print("RESIDUAL → NEXT-N-TICK OPTION MID RETURN (per strike)")
    print("=" * 100)

    for K in strikes:
        rs = residuals[K]
        if len(rs) < 100:
            continue
        # For each (ts, resid), find option mid at ts and ts+horizon
        for horizon in (50, 100, 200):
            pairs = []
            for ts, resid, _, _ in rs:
                future_ts = ts + horizon * 100
                opt_now = option_mid_by_ts.get(ts, {}).get(K)
                opt_fut = option_mid_by_ts.get(future_ts, {}).get(K)
                if opt_now is None or opt_fut is None:
                    continue
                ret = opt_fut - opt_now
                pairs.append((resid, ret))

            if len(pairs) < 50:
                continue

            # Quintile
            pairs.sort()
            n = len(pairs)
            q_size = n // 5
            print(f"\n  VEV_{K} horizon={horizon} ticks ({n} samples):")
            print(f"    {'Quintile':>20s}  {'n':>5s}  {'avg_resid':>10s}  {'avg_ret':>10s}  {'hit_dir%':>10s}")
            for q in range(5):
                slc = pairs[q*q_size:(q+1)*q_size]
                if not slc:
                    continue
                avg_r = sum(p[0] for p in slc) / len(slc)
                avg_ret = sum(p[1] for p in slc) / len(slc)
                # Hit dir: if resid<0 (underpriced), expect ret>0
                hit = sum(1 for p in slc if (p[0] < 0 and p[1] > 0) or (p[0] > 0 and p[1] < 0)) / len(slc)
                # That's "fade residual" direction
                print(f"    Q{q+1} (resid={avg_r:+.4f})  {len(slc):>5d}  {avg_r:>+10.4f}  {avg_ret:>+10.3f}  {hit*100:>9.1f}%")


if __name__ == "__main__":
    main()
