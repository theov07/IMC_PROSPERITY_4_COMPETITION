"""Combined 3-day smile plot (similar to user's reference image).

Uses moneyness in YEARS (T = days/252) to match the typical option market
convention (and user's referenced image).
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
OUT = ROOT / "artifacts" / "analysis" / "round_3_option_velvet" / "smiles"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
DAYS = [0, 1, 2]
TTE_BY_DAY = {0: 8.0, 1: 7.0, 2: 6.0}


def main():
    all_m = []   # log-moneyness in YEARS
    all_iv_ann = []
    color_map = {}
    cmap = plt.cm.tab10
    for i, K in enumerate(STRIKES):
        color_map[K] = cmap(i % 10)

    fig, ax = plt.subplots(figsize=(13, 7.5))

    points_by_strike: dict[int, tuple[list[float], list[float]]] = {K: ([], []) for K in STRIKES}

    for day in DAYS:
        df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
        velvet = df[df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"]
        T0 = TTE_BY_DAY[day]
        for K in STRIKES:
            sub = df[df["product"] == f"VEV_{K}"].set_index("timestamp")
            if sub.empty: continue
            for ts in sub.index:
                spot = velvet.get(ts)
                if spot is None: continue
                T_days = max(0.01, T0 - ts / 1_000_000.0)
                T_years = T_days / 252.0
                iv_per_day = call_implied_vol(sub.loc[ts, "mid_price"], spot, K, T_days, sigma_init=0.0125)
                if iv_per_day is None or iv_per_day <= 0: continue
                iv_ann = iv_per_day * math.sqrt(252.0)
                m = math.log(K / spot) / math.sqrt(T_years)   # standard moneyness
                points_by_strike[K][0].append(m)
                points_by_strike[K][1].append(iv_ann)
                all_m.append(m); all_iv_ann.append(iv_ann)

    # Plot scatter per strike
    for K in STRIKES:
        m_pts, iv_pts = points_by_strike[K]
        if not m_pts: continue
        ax.scatter(m_pts, iv_pts, s=4, alpha=0.4, label=f"K={K}", color=color_map[K])

    # Polynomial degree 2 fit
    if len(all_m) >= 3:
        coeffs = np.polyfit(all_m, all_iv_ann, deg=2)
        x_grid = np.linspace(min(all_m), max(all_m), 300)
        y_fit = np.polyval(coeffs, x_grid)
        ax.plot(x_grid, y_fit, "k-", lw=2.5,
                label=f"fit: {coeffs[0]:.3f}m² + {coeffs[1]:.3f}m + {coeffs[2]:.3f}")
        # R²
        residuals = np.array(all_iv_ann) - np.polyval(coeffs, all_m)
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((np.array(all_iv_ann) - np.mean(all_iv_ann)) ** 2)
        r2 = 1 - ss_res / ss_tot
        # Append R² to label
        ax.legend_text = f"R²={r2:.3f}"
        # Re-do with R² text
        new_label = f"fit: {coeffs[0]:.3f}m² + {coeffs[1]:.3f}m + {coeffs[2]:.3f}  (R²={r2:.3f})"
        # remove and re-add
        # Easier: just keep, R² shown in title
        ax.set_title(f"Volatility smile — Round 3 vouchers ({len(DAYS)} day(s))\nPolynomial poly2 fit  R² = {r2:.3f}")

    ax.set_xlabel("moneyness  m = log(K/S) / √T")
    ax.set_ylabel("implied vol (annualized)")
    ax.legend(loc="upper center", ncol=5, fontsize=8)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    out_path = OUT / "smile_3day_combined.png"
    plt.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"→ {out_path}")

    # Same with strikes ≤ 5500 only (matches user's image filter)
    fig, ax = plt.subplots(figsize=(13, 7.5))
    filtered_m = []
    filtered_iv = []
    for K in STRIKES:
        if K > 5500: continue
        m_pts, iv_pts = points_by_strike[K]
        if not m_pts: continue
        ax.scatter(m_pts, iv_pts, s=4, alpha=0.4, label=f"K={K}", color=color_map[K])
        filtered_m.extend(m_pts); filtered_iv.extend(iv_pts)
    if len(filtered_m) >= 3:
        coeffs = np.polyfit(filtered_m, filtered_iv, deg=2)
        x_grid = np.linspace(min(filtered_m), max(filtered_m), 300)
        y_fit = np.polyval(coeffs, x_grid)
        residuals = np.array(filtered_iv) - np.polyval(coeffs, filtered_m)
        r2 = 1 - np.sum(residuals**2) / np.sum((np.array(filtered_iv) - np.mean(filtered_iv))**2)
        ax.plot(x_grid, y_fit, "k-", lw=2.5,
                label=f"fit: {coeffs[0]:.3f}m² + {coeffs[1]:.3f}m + {coeffs[2]:.3f}  (R²={r2:.3f})")
    ax.set_title("Volatility smile — Round 3 vouchers (strikes ≤ 5500, 3 day(s))")
    ax.set_xlabel("moneyness  m = log(K/S) / √T")
    ax.set_ylabel("implied vol (annualized)")
    ax.legend(loc="upper center", ncol=5, fontsize=8)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    out_path2 = OUT / "smile_3day_strikes_le_5500.png"
    plt.savefig(out_path2, dpi=130)
    plt.close(fig)
    print(f"→ {out_path2}")


if __name__ == "__main__":
    main()
