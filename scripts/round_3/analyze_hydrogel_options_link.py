"""Test if HYDROGEL_PACK price/z-score predicts VELVET or option IVs.

Maybe HYDROGEL flow leads VELVET, or HYDROGEL z-score predicts vol regime.

Tests:
  1. Correlation HYDROGEL mid vs VELVET mid (per day)
  2. HYDROGEL z-score → next-tick VELVET return (lead-lag)
  3. HYDROGEL z-score → options ATM IV (vol regime indicator)
  4. HYDROGEL returns correlation with VEV options
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
DAYS = [0, 1, 2]
TTE_BY_DAY = {0: 8.0, 1: 7.0, 2: 6.0}


def main():
    rows = []
    for day in DAYS:
        df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
        velvet = df[df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"].sort_index()
        hydro = df[df["product"] == "HYDROGEL_PACK"].set_index("timestamp")["mid_price"].sort_index()

        aligned = pd.DataFrame({"velvet": velvet, "hydro": hydro}).dropna()
        v_ret = aligned.velvet.pct_change()
        h_ret = aligned.hydro.pct_change()

        # 1. Mid-level correlation
        mid_corr = aligned.corr().iloc[0, 1]
        ret_corr = pd.DataFrame({"v": v_ret, "h": h_ret}).corr().iloc[0, 1]

        # 2. HYDROGEL z-score → next-tick VELVET return
        h_zmean = aligned.hydro.rolling(500).mean()
        h_zstd = aligned.hydro.rolling(500).std()
        h_z = (aligned.hydro - h_zmean) / h_zstd
        # Predict next velvet return from hydro z
        valid = h_z.shift(1).notna() & v_ret.notna()
        if valid.sum() > 100:
            sub = pd.DataFrame({"hz_prev": h_z.shift(1), "v_ret": v_ret})[valid]
            lead_corr = sub.corr().iloc[0, 1]
        else:
            lead_corr = float("nan")

        # 3. HYDROGEL z-score → ATM (K=5200) IV
        atm_strike = 5200
        sub_atm = df[df["product"] == f"VEV_{atm_strike}"].set_index("timestamp")["mid_price"]
        T0 = TTE_BY_DAY[day]
        ivs = []
        for ts in sub_atm.index:
            spot = aligned.velvet.get(ts)
            if spot is None: continue
            T = max(0.01, T0 - ts / 1_000_000.0)
            iv = call_implied_vol(sub_atm.loc[ts], spot, atm_strike, T, sigma_init=0.0125)
            if iv is None: continue
            ivs.append((ts, iv))
        if ivs:
            iv_df = pd.DataFrame(ivs, columns=["timestamp", "iv"]).set_index("timestamp")
            iv_z_mean = iv_df.iv.rolling(500).mean()
            iv_z_std = iv_df.iv.rolling(500).std()
            iv_z = (iv_df.iv - iv_z_mean) / iv_z_std
            # Correlation hydro_z vs iv_z
            hz_aligned = h_z.reindex(iv_z.index)
            valid_iv = hz_aligned.notna() & iv_z.notna()
            iv_corr = pd.DataFrame({"hz": hz_aligned, "ivz": iv_z})[valid_iv].corr().iloc[0, 1]
        else:
            iv_corr = float("nan")

        # 4. Lag-1 cross-correlation (predictive power)
        # Returns: hydro_t-1 → velvet_t
        cross_corrs = {}
        for lag in [1, 5, 10, 50]:
            valid = h_ret.shift(lag).notna() & v_ret.notna()
            if valid.sum() > 100:
                cross_corrs[lag] = pd.DataFrame({
                    "hr_lag": h_ret.shift(lag),
                    "vr": v_ret,
                })[valid].corr().iloc[0, 1]
            else:
                cross_corrs[lag] = float("nan")

        print(f"\n=== Day {day} HYDROGEL vs VELVET/options ===")
        print(f"  Mid correlation:                {mid_corr:+.4f}")
        print(f"  Return correlation:             {ret_corr:+.4f}")
        print(f"  HYDRO_z(t-1) → VELVET_ret(t):   {lead_corr:+.4f}")
        print(f"  HYDRO_z → ATM IV_z (concurrent): {iv_corr:+.4f}")
        print(f"  Lagged HYDRO_ret → VELVET_ret:")
        for lag, c in cross_corrs.items():
            print(f"    lag {lag:>2}: {c:+.4f}")

        rows.append(dict(
            day=day,
            mid_corr=round(mid_corr, 4),
            ret_corr=round(ret_corr, 4),
            hydroz_to_velvet_ret=round(lead_corr, 4) if not math.isnan(lead_corr) else None,
            hydroz_to_atm_iv=round(iv_corr, 4) if not math.isnan(iv_corr) else None,
            **{f"lag{l}": round(c, 4) if not math.isnan(c) else None for l, c in cross_corrs.items()},
        ))

        # Plot HYDRO + VELVET overlay
        fig, axes = plt.subplots(2, 1, figsize=(15, 8), sharex=True)
        ax1 = axes[0]; ax2 = axes[1]
        ax1.plot(aligned.index, aligned.velvet, lw=0.5, color="orange", label="VELVET")
        ax1b = ax1.twinx()
        ax1b.plot(aligned.index, aligned.hydro, lw=0.5, color="blue", alpha=0.6, label="HYDRO")
        ax1.set_title(f"Day {day}: VELVET (orange, left) + HYDRO (blue, right)")
        ax1.legend(loc="upper left"); ax1b.legend(loc="upper right"); ax1.grid(alpha=0.3)

        # Z-scores
        ax2.plot(h_z.index, h_z.values, lw=0.4, color="blue", label=f"HYDRO z (corr-mid {mid_corr:+.2f})")
        v_z = (aligned.velvet - aligned.velvet.rolling(500).mean()) / aligned.velvet.rolling(500).std()
        ax2.plot(v_z.index, v_z.values, lw=0.4, color="orange", alpha=0.6, label="VELVET z")
        ax2.axhline(0, color="k", lw=0.5)
        ax2.axhline(2, color="r", lw=0.4, ls="--")
        ax2.axhline(-2, color="r", lw=0.4, ls="--")
        ax2.set_title("Z-scores (rolling 500-tick)")
        ax2.legend(); ax2.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(OUT / "velvet" / f"hydrogel_velvet_day_{day}.png", dpi=110)
        plt.close(fig)

    print("\n\n=== Summary table ===")
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    df.to_csv(OUT / "hydrogel_options_link.csv", index=False)
    print(f"\n→ CSV: {OUT / 'hydrogel_options_link.csv'}")

    # Verdict
    avg_lead = df["hydroz_to_velvet_ret"].mean()
    avg_concur_iv = df["hydroz_to_atm_iv"].mean()
    print(f"\nVerdict:")
    print(f"  avg HYDRO_z(t-1) → VELVET_ret(t): {avg_lead:+.4f}")
    if abs(avg_lead) > 0.05:
        print(f"    → Predictive! Could trade VELVET on HYDRO signal.")
    else:
        print(f"    → No predictive power (corr near 0)")
    print(f"  avg HYDRO_z → ATM IV_z:           {avg_concur_iv:+.4f}")
    if abs(avg_concur_iv) > 0.10:
        print(f"    → HYDRO state correlates with vol regime")
    else:
        print(f"    → No vol-regime link")


if __name__ == "__main__":
    main()
