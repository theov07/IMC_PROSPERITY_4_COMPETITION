"""Find ALL strongly anti-correlated pairs across ALL 50 R5 products (not just within groups).

Method:
  1. Compute pairwise return correlations on full 30k-tick data
  2. Filter |corr| > 0.40
  3. Sort by abs(corr) descending
  4. Output for use in pair_skip_mm config

This identifies CROSS-GROUP pairs that might be exploitable but were missed
by within-group analysis.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "round_5"
OUT = ROOT / "artifacts" / "analysis" / "round_5"
OUT.mkdir(parents=True, exist_ok=True)

LOSERS = {
    "OXYGEN_SHAKE_MINT", "TRANSLATOR_GRAPHITE_MIST", "PEBBLES_XS",
    "ROBOT_VACUUMING", "PANEL_4X4", "TRANSLATOR_SPACE_GRAY",
    "GALAXY_SOUNDS_SOLAR_FLAMES", "UV_VISOR_MAGENTA", "ROBOT_MOPPING",
    "PANEL_1X2", "PEBBLES_M", "SLEEP_POD_LAMB_WOOL",
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
    return rets


def main():
    rets = load_returns()
    products = [p for p in rets.columns if p not in LOSERS]
    rets = rets[products]
    print(f"Computing correlation matrix for {len(products)} products...")
    corr = rets.corr()

    # Build flat list
    rows = []
    for i, a in enumerate(products):
        for b in products[i+1:]:
            r = corr.loc[a, b]
            if abs(r) > 0.30:
                rows.append((a, b, r, abs(r)))
    rows.sort(key=lambda x: x[3], reverse=True)
    df = pd.DataFrame(rows, columns=["a", "b", "corr", "abs_corr"])

    print("\n=== Top 30 strongest |corr| pairs (returns, |corr|>0.30) ===")
    print(df.head(30).round(4).to_string(index=False))

    print("\n=== Top 15 ANTI-correlated (corr < -0.30) ===")
    df_neg = df[df["corr"] < -0.30].sort_values("corr").head(15)
    print(df_neg.round(4).to_string(index=False))

    print("\n=== Top 15 POSITIVELY correlated (corr > +0.30) ===")
    df_pos = df[df["corr"] > 0.30].sort_values("corr", ascending=False).head(15)
    print(df_pos.round(4).to_string(index=False))

    df.to_csv(OUT / "all_strong_pairs.csv", index=False)


if __name__ == "__main__":
    main()
