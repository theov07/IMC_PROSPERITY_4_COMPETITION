"""R5 PCA — within-group + inter-group + global.

For each group:
  - Run PCA on the 5 members (returns)
  - First eigenvector = group factor (the "ETF basket weights")
  - Second eigenvector = orthogonal contrast (e.g. SNACKPACK A vs B)
  - Variance explained per component

Inter-group (using group mean indices):
  - PCA on 10 group indices
  - Identify macro factors

Global (50 products):
  - PCA on all 50 returns
  - Top eigen-portfolios
  - Residuals (last few PCs) = noise/idiosyncratic = mean-reversion candidates

Outputs:
  - artifacts/analysis/round_5/pca_<group>.csv (loadings + explained var)
  - artifacts/analysis/round_5/pca_intergroup.csv
  - artifacts/analysis/round_5/pca_global_top.csv
"""
from __future__ import annotations

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


def load_returns():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    p = pd.concat(dfs, ignore_index=True)
    p["mid"] = (p["bid_price_1"].fillna(0) + p["ask_price_1"].fillna(0)) / 2
    pivot = p.pivot_table(index=["day", "timestamp"], columns="product",
                          values="mid", aggfunc="first")
    rets = np.log(pivot.replace(0, np.nan)).diff().fillna(0)
    return pivot, rets


def pca(X: np.ndarray):
    """Numpy PCA. Returns (eigvals, eigvecs, expvar_ratio).

    X: T x N matrix. Centers and computes covariance, sorts by eigenvalue.
    """
    Xc = X - X.mean(axis=0)
    C = np.cov(Xc.T)
    evals, evecs = np.linalg.eigh(C)
    # sort descending
    idx = np.argsort(evals)[::-1]
    evals = evals[idx]
    evecs = evecs[:, idx]
    total = evals.sum()
    expvar = evals / total if total > 0 else evals
    return evals, evecs, expvar


def main():
    print("Loading R5 prices...")
    pivot, rets = load_returns()
    print(f"Shape returns: {rets.shape}")

    # === 1. Per-group PCA ===
    print("\n" + "=" * 90)
    print("PER-GROUP PCA (on returns)")
    print("=" * 90)
    summary_rows = []
    for g, members in GROUPS.items():
        members = [m for m in members if m in rets.columns]
        if len(members) < 2:
            continue
        X = rets[members].values
        evals, evecs, expvar = pca(X)
        # First component (PC1) = group factor
        pc1_loadings = pd.Series(evecs[:, 0], index=members)
        pc2_loadings = pd.Series(evecs[:, 1], index=members)
        pc3_loadings = pd.Series(evecs[:, 2], index=members) if evecs.shape[1] > 2 else None

        print(f"\n--- {g} ---")
        print(f"Explained variance: PC1={expvar[0]:.1%}  PC2={expvar[1]:.1%}  PC3={expvar[2]:.1%}  PC4={expvar[3]:.1%}  PC5={expvar[4]:.1%}")
        print("PC1 loadings (group factor):")
        print(pc1_loadings.round(3).to_string())
        print("PC2 loadings (orthogonal contrast):")
        print(pc2_loadings.round(3).to_string())

        for i, m in enumerate(members):
            summary_rows.append(dict(
                group=g, product=m,
                pc1=float(evecs[i, 0]), pc2=float(evecs[i, 1]),
                pc3=float(evecs[i, 2]) if evecs.shape[1] > 2 else 0,
                pc4=float(evecs[i, 3]) if evecs.shape[1] > 3 else 0,
                pc5=float(evecs[i, 4]) if evecs.shape[1] > 4 else 0,
                pc1_var=float(expvar[0]),
                pc2_var=float(expvar[1]),
            ))

        # Save group-specific PCA
        df_g = pd.DataFrame({
            "product": members,
            "PC1": evecs[:, 0],
            "PC2": evecs[:, 1],
            "PC3": evecs[:, 2] if evecs.shape[1] > 2 else 0,
            "PC4": evecs[:, 3] if evecs.shape[1] > 3 else 0,
            "PC5": evecs[:, 4] if evecs.shape[1] > 4 else 0,
        })
        df_g.to_csv(OUT / f"pca_group_{g}.csv", index=False)

    pd.DataFrame(summary_rows).to_csv(OUT / "pca_per_group_summary.csv", index=False)

    # === 2. Inter-group PCA (using group equal-weight indices) ===
    print("\n" + "=" * 90)
    print("INTER-GROUP PCA (10 group indices on returns)")
    print("=" * 90)
    grp_rets = pd.DataFrame(index=rets.index)
    for g, members in GROUPS.items():
        members = [m for m in members if m in rets.columns]
        if members:
            grp_rets[g] = rets[members].mean(axis=1)
    X = grp_rets.dropna().values
    evals, evecs, expvar = pca(X)
    cols = grp_rets.columns.tolist()
    print(f"Explained variance: {[f'{e:.1%}' for e in expvar[:5]]}")
    print("\nPC1 loadings (macro factor):")
    pc1 = pd.Series(evecs[:, 0], index=cols)
    print(pc1.round(3).sort_values(ascending=False).to_string())
    print("\nPC2 loadings (macro contrast):")
    pc2 = pd.Series(evecs[:, 1], index=cols)
    print(pc2.round(3).sort_values(ascending=False).to_string())
    print("\nPC3 loadings:")
    pc3 = pd.Series(evecs[:, 2], index=cols)
    print(pc3.round(3).sort_values(ascending=False).to_string())

    df_ig = pd.DataFrame({
        "group": cols,
        "PC1": evecs[:, 0],
        "PC2": evecs[:, 1],
        "PC3": evecs[:, 2],
        "PC4": evecs[:, 3] if evecs.shape[1] > 3 else 0,
    })
    df_ig.to_csv(OUT / "pca_intergroup.csv", index=False)

    # === 3. Global PCA on all 50 ===
    print("\n" + "=" * 90)
    print("GLOBAL PCA (all 50 products on returns)")
    print("=" * 90)
    X_all = rets.dropna().values
    evals, evecs, expvar = pca(X_all)
    products = rets.columns.tolist()
    print(f"Total cum var: PC1-5={[f'{e:.1%}' for e in expvar[:5]]}  PC1-10={sum(expvar[:10]):.1%}  PC1-20={sum(expvar[:20]):.1%}")

    # Save loadings of top 10 PCs
    pc_data = {"product": products}
    for i in range(min(10, evecs.shape[1])):
        pc_data[f"PC{i+1}"] = evecs[:, i]
    pc_data["expvar_PC1"] = [expvar[0]] * len(products)
    df_global = pd.DataFrame(pc_data)
    df_global.to_csv(OUT / "pca_global_top10.csv", index=False)

    print("\nTop 10 |PC1 loadings| (most explained by macro factor):")
    pc1g = pd.Series(np.abs(evecs[:, 0]), index=products)
    print(pc1g.sort_values(ascending=False).head(10).to_string())

    print("\nTop 10 |PC2 loadings|:")
    pc2g = pd.Series(np.abs(evecs[:, 1]), index=products)
    print(pc2g.sort_values(ascending=False).head(10).to_string())

    # === 4. Compute PC1 residuals for top-loaded products ===
    print("\n" + "=" * 90)
    print("Residuals from PC1 (= deviation from macro factor)")
    print("=" * 90)
    pc1_factor = (rets - rets.mean()).fillna(0).values @ evecs[:, 0:1]  # T x 1
    residuals = pd.DataFrame(index=rets.index, columns=products, dtype=float)
    for i, p in enumerate(products):
        beta = evecs[i, 0]
        residuals[p] = rets[p] - beta * pc1_factor[:, 0]
    # AR(1) of residuals (mean-reversion?)
    ar1_resids = {}
    for p in products:
        s = residuals[p].dropna().values
        if len(s) > 100:
            r0 = s[:-1]
            r1 = s[1:]
            if r0.std() > 1e-9:
                ar1_resids[p] = float(np.corrcoef(r0, r1)[0, 1])
    df_resid = pd.DataFrame({"product": list(ar1_resids.keys()),
                             "ar1_resid": list(ar1_resids.values())})
    print("\nProducts with most mean-reverting PC1 residuals (low AR1):")
    print(df_resid.sort_values("ar1_resid").head(15).round(4).to_string(index=False))
    df_resid.to_csv(OUT / "pca_global_residuals.csv", index=False)


if __name__ == "__main__":
    main()
