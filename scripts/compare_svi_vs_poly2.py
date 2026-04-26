"""Direct SVI vs poly2 smile fit comparison.

For each tick across 3 days, fit BOTH SVI and poly2 smile, compute fair value
per strike, and check:
  - Where do they DIFFER significantly (>1 tick)?
  - Would SVI fair trigger different taker decisions vs poly2?

If SVI rarely differs from poly2 in our market → confirms SVI test moot.
If SVI differs significantly → worth implementing.
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

from prosperity.options.black_scholes import call_price
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.svi import fit_svi, svi_iv

DATA = ROOT / "data" / "round_3"
OUT = ROOT / "artifacts" / "analysis" / "round_3_option_velvet" / "svi"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
TTE_BY_DAY = {0: 8.0, 1: 7.0, 2: 6.0}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sample_per_day = 100   # sample N timestamps per day (fitting is expensive)

    summary_rows = []
    for day in [0, 1, 2]:
        df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
        velvet = df[df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"]

        # Sample timestamps
        all_ts = sorted(velvet.index)
        step = len(all_ts) // sample_per_day
        sample_ts = all_ts[::max(step, 1)][:sample_per_day]

        T0 = TTE_BY_DAY[day]
        for ts in sample_ts:
            spot = velvet.get(ts)
            if spot is None: continue
            T = max(0.01, T0 - ts / 1_000_000.0)
            # Compute IV per strike
            ks_log, ivs_per_day, mids = [], [], []
            for K in STRIKES:
                sub = df[(df["product"] == f"VEV_{K}") & (df["timestamp"] == ts)]
                if sub.empty: continue
                opt_mid = sub.iloc[0]["mid_price"]
                iv = call_implied_vol(opt_mid, spot, K, T, sigma_init=0.0125)
                if iv is None or iv < 0.005 or iv > 0.10: continue
                ks_log.append(math.log(K / spot))
                ivs_per_day.append(iv)
                mids.append((K, opt_mid))
            if len(ks_log) < 5: continue

            # Fit poly2 (in log-moneyness, IV space)
            poly_coeffs = np.polyfit(ks_log, ivs_per_day, deg=2)

            # Fit SVI (note: SVI takes T in same units as iv squared)
            svi_params = fit_svi(ks_log, ivs_per_day, T)

            for K, mid in mids:
                k = math.log(K / spot)
                poly_iv = np.polyval(poly_coeffs, k)
                poly_fair = call_price(spot, K, T, max(poly_iv, 0.001))
                if svi_params:
                    svi_iv_val = svi_iv(k, T, *svi_params)
                    svi_fair = call_price(spot, K, T, max(svi_iv_val, 0.001))
                else:
                    svi_iv_val = poly_iv
                    svi_fair = poly_fair
                diff = svi_fair - poly_fair
                summary_rows.append({
                    "day": day, "ts": ts, "K": K,
                    "spot": round(spot, 2), "mid": round(mid, 2),
                    "poly_iv": round(poly_iv, 5), "svi_iv": round(svi_iv_val, 5),
                    "poly_fair": round(poly_fair, 2), "svi_fair": round(svi_fair, 2),
                    "fair_diff": round(diff, 2),
                })

    df_summary = pd.DataFrame(summary_rows)
    print(f"Total samples: {len(df_summary)}")
    print()
    print("=== Per-strike comparison (mean abs SVI - poly2 fair) ===")
    agg = df_summary.groupby("K").agg(
        n=("fair_diff", "count"),
        mean_abs_diff=("fair_diff", lambda s: round(s.abs().mean(), 2)),
        max_abs_diff=("fair_diff", lambda s: round(s.abs().max(), 2)),
        mean_diff=("fair_diff", lambda s: round(s.mean(), 2)),
    )
    print(agg.to_string())
    print()
    print("=== How often does |SVI-poly| > 1 tick? ===")
    for K in STRIKES:
        sub = df_summary[df_summary.K == K]
        if sub.empty: continue
        gt_1 = (sub.fair_diff.abs() > 1).sum()
        pct = gt_1 / len(sub) * 100
        print(f"  K={K}: {gt_1}/{len(sub)} ticks ({pct:.1f}%) have fair diff > 1 tick")

    df_summary.to_csv(OUT / "svi_vs_poly2_per_tick.csv", index=False)
    print(f"\n→ {OUT / 'svi_vs_poly2_per_tick.csv'}")

    # Verdict
    print()
    print("VERDICT:")
    overall_mean = df_summary.fair_diff.abs().mean()
    print(f"  Overall mean |SVI - poly2| fair value diff: {overall_mean:.2f} ticks")
    if overall_mean < 0.5:
        print("  → SVI fair ≈ poly2 fair on average. SVI doesn't add new info.")
    else:
        print("  → SVI differs meaningfully. Worth testing in option_mm_bs takers.")


if __name__ == "__main__":
    main()
