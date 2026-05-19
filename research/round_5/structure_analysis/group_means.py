"""R5 group means analysis (user idea: "moyennes intéressantes qui font lignes droites").

For each of 10 groups :
  1. Compute equal-weighted mean of mids (raw + z-scored per product)
  2. Plot/check if the mean is :
     - LINEAR (drift) -> stable index, can serve as ETF
     - OSCILLATING -> mean reversion target
     - RANDOM-WALK -> no signal
  3. Check intra-group variance (members spread around mean)
  4. Identify which groups have "interesting" means (low slope + bounded oscillation)

Outputs:
  - artifacts/analysis/round_5/group_mean_stats.csv
  - artifacts/analysis/round_5/group_mean_diag.csv (per-group: linearity_R2, hurst, etc.)
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "round_5"
OUT = ROOT / "artifacts" / "analysis" / "round_5"
OUT.mkdir(parents=True, exist_ok=True)

GROUPS = {
    "GALAXY_SOUNDS": ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                      "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                      "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "SLEEP_POD": ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                  "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "MICROCHIP": ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                  "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "PEBBLES": ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "ROBOT": ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES", "ROBOT_LAUNDRY",
              "ROBOT_IRONING"],
    "UV_VISOR": ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                 "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "TRANSLATOR": ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                   "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                   "TRANSLATOR_VOID_BLUE"],
    "PANEL": ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "OXYGEN_SHAKE": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                     "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE",
                     "OXYGEN_SHAKE_GARLIC"],
    "SNACKPACK": ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                  "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
}


def load_pivot():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    p = pd.concat(dfs, ignore_index=True)
    p["mid"] = (p["bid_price_1"].fillna(0) + p["ask_price_1"].fillna(0)) / 2
    pivot = p.pivot_table(index=["day", "timestamp"], columns="product",
                          values="mid", aggfunc="first")
    return pivot


def hurst_exponent(series: np.ndarray) -> float:
    """Approx Hurst exponent via R/S analysis. ~0.5 = random walk, <0.5 = mean-reverting, >0.5 = trending."""
    series = np.asarray(series)
    series = series[~np.isnan(series)]
    if len(series) < 100:
        return float("nan")
    lags = [10, 20, 50, 100, 200, 500]
    rs = []
    for lag in lags:
        if lag >= len(series):
            continue
        n = len(series) // lag
        if n < 1:
            continue
        rs_vals = []
        for i in range(n):
            sub = series[i * lag:(i + 1) * lag]
            mean = sub.mean()
            cum = np.cumsum(sub - mean)
            r = cum.max() - cum.min()
            s = sub.std()
            if s > 0:
                rs_vals.append(r / s)
        if rs_vals:
            rs.append((lag, np.mean(rs_vals)))
    if len(rs) < 3:
        return float("nan")
    log_lag = np.log([x[0] for x in rs])
    log_rs = np.log([x[1] for x in rs])
    slope = np.polyfit(log_lag, log_rs, 1)[0]
    return float(slope)


def linear_r2(series: np.ndarray) -> tuple:
    """Return (slope, R²) of OLS fit of series vs t."""
    series = np.asarray(series)
    valid = ~np.isnan(series)
    if valid.sum() < 100:
        return float("nan"), float("nan")
    y = series[valid]
    x = np.arange(len(series))[valid]
    p = np.polyfit(x, y, 1)
    slope = p[0]
    yhat = np.polyval(p, x)
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return float(slope), float(r2)


def adf_lite(series: np.ndarray) -> dict:
    """Lightweight ADF proxy : AR(1) coef + variance ratio.

    AR(1) close to 1 = unit root (random walk).
    Variance ratio < 1 = mean-reversion.
    """
    s = np.asarray(series)
    s = s[~np.isnan(s)]
    if len(s) < 100:
        return {}
    diff = np.diff(s)
    # AR(1) on level
    s0 = s[:-1]
    s1 = s[1:]
    if s0.std() < 1e-9:
        return {}
    ar = float(np.corrcoef(s0, s1)[0, 1])
    # Variance ratio (var of 5-period diff vs 5x var of 1-period)
    if len(diff) > 10:
        d5 = s[5:] - s[:-5]
        var_ratio = float(d5.var() / (5 * diff.var())) if diff.var() > 0 else float("nan")
    else:
        var_ratio = float("nan")
    return dict(ar1=ar, var_ratio_5=var_ratio, mean=float(s.mean()), std=float(s.std()))


def main():
    print("Loading R5 prices...")
    pivot = load_pivot()
    print(f"Shape: {pivot.shape}")

    rows_by_member = []  # per-product diagnostics
    rows_by_group_mean = []  # group-mean diagnostics
    rows_by_group_member_dev = []  # member deviation from group mean

    for g, members in GROUPS.items():
        members = [m for m in members if m in pivot.columns]
        if not members:
            continue
        # Group equal-weight mean (raw mids)
        gmean_raw = pivot[members].mean(axis=1)
        gmean_z = ((pivot[members] - pivot[members].mean()) / pivot[members].std()).mean(axis=1)

        slope_raw, r2_raw = linear_r2(gmean_raw.values)
        adf_raw = adf_lite(gmean_raw.values)
        adf_z = adf_lite(gmean_z.values)
        h_raw = hurst_exponent(gmean_raw.values)
        h_z = hurst_exponent(gmean_z.values)

        rows_by_group_mean.append(dict(
            group=g, n_members=len(members),
            mean_raw=float(gmean_raw.mean()),
            std_raw=float(gmean_raw.std()),
            slope_raw=slope_raw, R2_raw=r2_raw,
            ar1_raw=adf_raw.get("ar1", float("nan")),
            var_ratio5_raw=adf_raw.get("var_ratio_5", float("nan")),
            hurst_raw=h_raw,
            ar1_z=adf_z.get("ar1", float("nan")),
            var_ratio5_z=adf_z.get("var_ratio_5", float("nan")),
            hurst_z=h_z,
        ))

        for m in members:
            mid = pivot[m].dropna()
            slope_m, r2_m = linear_r2(mid.values)
            adf_m = adf_lite(mid.values)
            h_m = hurst_exponent(mid.values)
            # Deviation from group mean (raw)
            dev = (pivot[m] - gmean_raw).dropna()
            d_std = float(dev.std())
            d_h = hurst_exponent(dev.values)
            d_ar1 = adf_lite(dev.values).get("ar1", float("nan"))
            rows_by_member.append(dict(
                product=m, group=g,
                std=float(mid.std()),
                slope=slope_m, R2=r2_m, ar1=adf_m.get("ar1", float("nan")),
                var_ratio5=adf_m.get("var_ratio_5", float("nan")),
                hurst=h_m,
                dev_std_from_groupmean=d_std,
                dev_hurst=d_h,
                dev_ar1=d_ar1,
            ))

    df_g = pd.DataFrame(rows_by_group_mean)
    df_m = pd.DataFrame(rows_by_member)
    print("\n=== GROUP MEAN diagnostics ===")
    print("Hurst < 0.5 = mean-reverting, > 0.5 = trending")
    print("var_ratio < 1 = mean-reverting, > 1 = trending")
    print(df_g.round(4).to_string(index=False))
    df_g.to_csv(OUT / "group_mean_diag.csv", index=False)

    print("\n=== Per-MEMBER diagnostics, sorted by dev_ar1 (= mean reversion of dev from group mean) ===")
    print("dev_ar1 close to 0 = strong mean-reversion of deviation -> good for ETF tracking error trade")
    print(df_m.sort_values("dev_ar1").round(4).to_string(index=False))
    df_m.to_csv(OUT / "member_diag.csv", index=False)

    # === Highlight: group means that are LINEAR (high R²) ===
    print("\n=== GROUPS WITH LINEAR MEAN (high R² of mean vs t) ===")
    print(df_g.sort_values("R2_raw", ascending=False)[["group", "slope_raw", "R2_raw", "hurst_raw"]].to_string(index=False))

    # === Best ETF tracking error candidates ===
    print("\n=== BEST PRODUCTS for tracking-error trade (low dev_ar1, high dev_std) ===")
    df_m["te_score"] = (1 - df_m["dev_ar1"]) * df_m["dev_std_from_groupmean"]
    print(df_m.sort_values("te_score", ascending=False).head(15)[["product", "group", "dev_std_from_groupmean", "dev_ar1", "dev_hurst", "te_score"]].to_string(index=False))


if __name__ == "__main__":
    main()
