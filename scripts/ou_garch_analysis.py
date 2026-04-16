"""OU process fit + GARCH volatility clustering + asymmetric return analysis.

Three untested signals on OSMIUM:
1. OU fit: theta (mean-reversion speed), mu (anchor), sigma -> optimal entry/exit
2. GARCH(1,1) on returns: does vol cluster? Is vol predictive of fwd returns?
3. Asymmetry: are dips below 10k more exploitable than spikes above?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DATA = [
    "data/round_1/prices_round_1_day_-2.csv",
    "data/round_1/prices_round_1_day_-1.csv",
    "data/round_1/prices_round_1_day_0.csv",
]
PRODUCT = "ASH_COATED_OSMIUM"
ANCHOR = 10000.0


def load():
    frames = []
    for path in DATA:
        df = pd.read_csv(path, sep=";")
        df.columns = [c.strip() for c in df.columns]
        frames.append(df[df["product"] == PRODUCT])
    return pd.concat(frames, ignore_index=True).sort_values(["day", "timestamp"]).reset_index(drop=True)


def ou_fit(mid: np.ndarray, dt: float = 1.0):
    """MLE for OU: dX = theta*(mu - X)*dt + sigma*dW."""
    x = mid[:-1]
    y = mid[1:]
    n = len(x)
    sx = x.sum()
    sy = y.sum()
    sxx = (x * x).sum()
    sxy = (x * y).sum()
    syy = (y * y).sum()

    mu_hat = (sy * sxx - sx * sxy) / (n * (sxx - sxy) - (sx**2 - sx * sy))
    denom = sxx - 2 * mu_hat * sx + n * mu_hat**2
    if abs(denom) < 1e-10:
        return 0.0, mu_hat, 0.0
    a = (sxy - mu_hat * sx - mu_hat * sy + n * mu_hat**2) / denom
    if a <= 0 or a >= 1:
        # fallback: use autocorrelation of deviations
        dev = mid - mu_hat
        a = np.corrcoef(dev[:-1], dev[1:])[0, 1]
    theta_hat = -np.log(max(a, 1e-10)) / dt
    sigma_sq = (2 * theta_hat / (n * (1 - a**2))) * (syy - 2 * a * sxy + a**2 * sxx
        - 2 * mu_hat * (1 - a) * (sy - a * sx) + n * mu_hat**2 * (1 - a)**2)
    sigma_hat = np.sqrt(max(sigma_sq, 1e-10))
    return theta_hat, mu_hat, sigma_hat


def garch11(returns: np.ndarray, omega: float = 0.01, alpha: float = 0.1, beta: float = 0.85, n_iter: int = 200):
    """Simple GARCH(1,1) fit via moment matching. Returns conditional vol series."""
    r = returns - returns.mean()
    n = len(r)
    h = np.zeros(n)
    h[0] = r.var()
    for t in range(1, n):
        h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
    return np.sqrt(h)


def main():
    df = load()
    mid = df["mid_price"].dropna().values.astype(float)
    ret = np.diff(mid)

    print("=" * 60)
    print("1. OU PROCESS FIT")
    print("=" * 60)
    theta, mu, sigma = ou_fit(mid)
    half_life = np.log(2) / theta if theta > 0 else float("inf")
    eq_std = sigma / np.sqrt(2 * theta) if theta > 0 else float("inf")
    print(f"  theta (reversion speed) = {theta:.4f}")
    print(f"  mu    (long-run mean)   = {mu:.2f}")
    print(f"  sigma (diffusion)       = {sigma:.4f}")
    print(f"  half-life               = {half_life:.2f} ticks")
    print(f"  equilibrium std         = {eq_std:.2f} ticks")
    print()
    print(f"  -> Optimal entry: |mid - {mu:.0f}| > {1.5*eq_std:.1f} (1.5 sigma)")
    print(f"  -> Optimal exit:  |mid - {mu:.0f}| < {0.5*eq_std:.1f} (0.5 sigma)")
    print(f"  -> Current take_edge=1.75 vs OU-optimal = {1.5*eq_std:.2f}")

    print()
    print("=" * 60)
    print("2. GARCH(1,1) VOLATILITY CLUSTERING")
    print("=" * 60)
    cond_vol = garch11(ret)
    vol_q = np.percentile(cond_vol, [10, 25, 50, 75, 90])
    print(f"  cond vol percentiles: p10={vol_q[0]:.3f} p25={vol_q[1]:.3f} p50={vol_q[2]:.3f} p75={vol_q[3]:.3f} p90={vol_q[4]:.3f}")

    # does high vol predict bigger |fwd returns|?
    fwd1 = np.append(ret[1:], np.nan)
    mask = ~np.isnan(fwd1)
    corr_vol_absfwd = np.corrcoef(cond_vol[:-1][mask[:-1]], np.abs(fwd1[:-1][mask[:-1]]))[0, 1]
    print(f"  corr(cond_vol, |fwd_1|) = {corr_vol_absfwd:.4f}")

    # does high vol predict direction?
    corr_vol_fwd = np.corrcoef(cond_vol[:-1][mask[:-1]], fwd1[:-1][mask[:-1]])[0, 1]
    print(f"  corr(cond_vol, fwd_1)   = {corr_vol_fwd:.4f}")

    # split into regimes
    hi_vol = cond_vol > np.median(cond_vol)
    lo_vol = ~hi_vol
    print(f"  hi-vol ticks: {hi_vol.sum()}  lo-vol: {lo_vol.sum()}")
    fwd_abs = np.abs(ret)
    n_ret = len(ret)
    if hi_vol[:n_ret].sum() > 0 and lo_vol[:n_ret].sum() > 0:
        print(f"  mean |ret| hi-vol: {fwd_abs[hi_vol[:n_ret]].mean():.3f}  lo-vol: {fwd_abs[lo_vol[:n_ret]].mean():.3f}")
        # AR(1) in each regime
        for label, m in [("hi-vol", hi_vol), ("lo-vol", lo_vol)]:
            idx = np.where(m[:-1])[0]
            if len(idx) > 10:
                r0 = ret[idx]
                r1 = ret[idx + 1] if (idx + 1 < len(ret)).all() else ret[np.minimum(idx+1, len(ret)-1)]
                valid = idx + 1 < len(ret)
                r0 = ret[idx[valid]]
                r1 = ret[idx[valid] + 1]
                ar1 = np.corrcoef(r0, r1)[0, 1]
                print(f"  AR(1) {label}: {ar1:.4f}")

    print()
    print("=" * 60)
    print("3. ASYMMETRY: DIPS vs SPIKES")
    print("=" * 60)
    dev = mid - ANCHOR
    # when dev < 0 (below anchor): what is E[fwd_1]?
    # when dev > 0 (above anchor): what is E[fwd_1]?
    for thr in [0, 2, 4, 6]:
        below = dev[:-1] < -thr
        above = dev[:-1] > thr
        if below.sum() > 0:
            e_fwd_below = ret[below].mean()
            std_below = ret[below].std()
        else:
            e_fwd_below = std_below = float("nan")
        if above.sum() > 0:
            e_fwd_above = ret[above].mean()
            std_above = ret[above].std()
        else:
            e_fwd_above = std_above = float("nan")
        print(f"  |dev|>{thr}: below={below.sum():>5} E[fwd]={e_fwd_below:+.4f} std={std_below:.3f} | above={above.sum():>5} E[fwd]={e_fwd_above:+.4f} std={std_above:.3f}")

    # are dips below anchor sharper reversions?
    print()
    for bucket_sz in [2]:
        print(f"  dev bucket (sz={bucket_sz})  n     E[fwd_1]  E[fwd_5]  E[fwd_10]")
        for lo in range(-10, 11, bucket_sz):
            hi = lo + bucket_sz
            mask_b = (dev[:-1] >= lo) & (dev[:-1] < hi)
            n = mask_b.sum()
            if n < 20:
                continue
            e1 = ret[mask_b].mean()
            fwd5 = []
            fwd10 = []
            idxs = np.where(mask_b)[0]
            for i in idxs:
                if i + 5 < len(mid):
                    fwd5.append(mid[i+5] - mid[i])
                if i + 10 < len(mid):
                    fwd10.append(mid[i+10] - mid[i])
            e5 = np.mean(fwd5) if fwd5 else float("nan")
            e10 = np.mean(fwd10) if fwd10 else float("nan")
            print(f"  [{lo:>3},{hi:>3})  {n:>5}  {e1:+.4f}   {e5:+.4f}   {e10:+.4f}")


main()
