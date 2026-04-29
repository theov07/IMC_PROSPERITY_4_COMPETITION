"""R5 variance decomposition: intra vs inter group.

User question: "chercher aussi sur la variance intra et intergroupe"

For each group:
  - Intra-group variance = mean of var(member_returns) within the group
  - Inter-product variance = var(returns) of the 5 members at each tick (cross-section)
  - Group factor variance = var(equal-weight basket return)

Cross-group:
  - Sum of group factor variances vs total cross-product variance -> tells us how
    much variance is captured by the group structure.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
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


def load_returns():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        dfs.append(df)
    p = pd.concat(dfs, ignore_index=True)
    p["mid"] = (p["bid_price_1"].fillna(0) + p["ask_price_1"].fillna(0)) / 2
    pivot = p.pivot_table(index=["timestamp"], columns="product",
                          values="mid", aggfunc="first")
    rets = np.log(pivot.replace(0, np.nan)).diff()
    return pivot, rets


def main():
    pivot, rets = load_returns()
    rows = []
    print("Variance decomposition per group:")
    print(f"{'group':<14s} {'intra_var':>12s} {'factor_var':>12s} {'r_intra/total':>14s} {'cohesion':>10s}")
    for g, members in GROUPS.items():
        members = [m for m in members if m in rets.columns]
        if not members:
            continue
        sub = rets[members]
        # Intra-product (time-series) variances mean
        intra = sub.var().mean()
        # Group factor (equal-weight)
        factor_ret = sub.mean(axis=1)
        factor_var = factor_ret.var()
        # Cohesion (avg pairwise corr)
        corr = sub.corr().values
        n = len(members)
        mask = np.triu(np.ones(n), k=1).astype(bool)
        cohesion = corr[mask].mean()
        # Variance ratio intra / factor 5x means full common factor; <5x means independent
        ratio = intra / max(factor_var, 1e-12) / n  # normalize by n
        rows.append((g, float(intra), float(factor_var), float(ratio), float(cohesion)))
        print(f"{g:<14s} {intra:>12.6e} {factor_var:>12.6e} {ratio:>14.3f} {cohesion:>10.3f}")
    df = pd.DataFrame(rows, columns=["group", "intra_var", "factor_var", "intra_to_factor_ratio", "cohesion"])
    df.to_csv(OUT / "variance_decomp.csv", index=False)

    # === Cross-section variance (at each tick, var across all 50 prods) ===
    print("\nCross-section (over 50 products) at each tick:")
    cs_var = rets.var(axis=1)
    print(f"  Mean cross-section var: {cs_var.mean():.6e}")
    print(f"  Std of cross-section var: {cs_var.std():.6e}")
    print(f"  Max: {cs_var.max():.6e}, Min: {cs_var.min():.6e}")

    # === Per-tick group factor returns ===
    print("\nGroup factor variance ranking:")
    g_factor_vars = {g: rets[[m for m in members if m in rets.columns]].mean(axis=1).var()
                     for g, members in GROUPS.items()}
    s = pd.Series(g_factor_vars).sort_values(ascending=False)
    print(s.to_string())
    s.to_csv(OUT / "group_factor_variances.csv")

    # === High intra-var, low factor-var groups = independent members ===
    print("\nIntra/Factor ratio (high = members are independent within group):")
    df_sorted = df.sort_values("intra_to_factor_ratio", ascending=False)
    print(df_sorted.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
