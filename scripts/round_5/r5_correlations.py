"""R5 advanced correlation analysis: lead-lag, copules, regime correlations.

1. Pairwise correlations (Pearson + Spearman) on returns + on mid levels
2. Lead-lag : does product X return at t predict product Y return at t+k?
3. Copules : empirical joint distribution of return pairs (rank-based)
4. Cross-group cointegration patterns
5. Day-by-day regime check (correlations stable?)

Outputs CSVs to artifacts/analysis/round_5/ for downstream use.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "round_5"
OUT = ROOT / "artifacts" / "analysis" / "round_5"
OUT.mkdir(parents=True, exist_ok=True)


def load_prices():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    p = pd.concat(dfs, ignore_index=True)
    p["mid"] = (p["bid_price_1"].fillna(0) + p["ask_price_1"].fillna(0)) / 2
    return p


def main():
    prices = load_prices()
    # Build pivot: index=(day, ts), columns=product, values=mid
    print("Building pivot table...")
    pivot = prices.pivot_table(
        index=["day", "timestamp"], columns="product", values="mid", aggfunc="first"
    )
    products = pivot.columns.tolist()
    print(f"Products: {len(products)}, ticks: {len(pivot)}")

    # === 1) Pearson + Spearman on LEVELS and RETURNS ===
    print()
    print("=" * 90)
    print("Computing returns (1-tick log diff)...")
    rets = np.log(pivot).diff().dropna(how="all")

    print()
    print("=" * 90)
    print("PEARSON corr on LEVELS")
    print("Already computed in previous script, top inverse pairs were:")
    print("  SLEEP_POD_POLYESTER ↔ UV_VISOR_AMBER: -0.941")
    print("  SNACKPACK_CHOCOLATE ↔ VANILLA: -0.926")
    print()

    print("PEARSON corr on RETURNS (more meaningful — high-freq comovement)")
    ret_corr = rets.corr(method="pearson")
    # Find top pairs
    pairs = []
    for i, p1 in enumerate(products):
        for p2 in products[i+1:]:
            if p1 in ret_corr and p2 in ret_corr.columns:
                c = ret_corr.loc[p1, p2]
                if abs(c) > 0.05 and not np.isnan(c):
                    pairs.append((c, p1, p2))
    pairs.sort()
    print("\nTop 15 NEGATIVE return correlations (anti-comovement = pair trade):")
    for c, p1, p2 in pairs[:15]:
        print(f"  {c:>+8.3f}  {p1:<35s}  {p2}")
    print("\nTop 15 POSITIVE return correlations (synchro moves = basket spread):")
    for c, p1, p2 in sorted(pairs, reverse=True)[:15]:
        print(f"  {c:>+8.3f}  {p1:<35s}  {p2}")

    # Save full corr matrix
    ret_corr.to_csv(OUT / "correlations_returns_pearson.csv")
    pivot.corr().to_csv(OUT / "correlations_levels_pearson.csv")
    rets.corr(method="spearman").to_csv(OUT / "correlations_returns_spearman.csv")
    print(f"\nSaved corr matrices to {OUT}/correlations_*.csv")

    # === 2) Lead-lag analysis ===
    print()
    print("=" * 90)
    print("LEAD-LAG analysis: does X return at t predict Y return at t+k?")
    print("Looking for k=10 ticks ahead (1 sec)")
    print("=" * 90)

    rets_arr = rets.values
    ts_arr = rets.index.to_list()
    # For top winners, compute lead-lag with all others
    target_lags = [5, 10, 20, 50]
    findings = []
    for k in target_lags:
        # Shift Y by -k (so Y[t+k] aligns with X[t])
        rets_shifted = rets.shift(-k).dropna(how="all")
        rets_aligned = rets.iloc[:len(rets_shifted)]
        for i, p1 in enumerate(products):
            for p2 in products:
                if p1 == p2:
                    continue
                # corr(X[t], Y[t+k])
                x = rets_aligned[p1].dropna()
                y = rets_shifted[p2].dropna()
                common = x.index.intersection(y.index)
                if len(common) < 100:
                    continue
                cx = x.loc[common].values
                cy = y.loc[common].values
                if cx.std() == 0 or cy.std() == 0:
                    continue
                c = np.corrcoef(cx, cy)[0, 1]
                if abs(c) > 0.05:
                    findings.append((abs(c), c, p1, p2, k))
    findings.sort(reverse=True)
    print(f"\nTop 25 lead-lag (X@t -> Y@t+k):")
    print(f"  {'|corr|':>7s}  {'corr':>7s}  {'k':>3s}  {'X (predictor)':<35s}  {'Y (target)'}")
    for ac, c, p1, p2, k in findings[:25]:
        print(f"  {ac:>7.3f}  {c:>+7.3f}  {k:>3d}  {p1:<35s}  {p2}")

    # Save findings
    df = pd.DataFrame(findings, columns=["abs_corr", "corr", "predictor", "target", "lag"])
    df.to_csv(OUT / "lead_lag.csv", index=False)
    print(f"\nSaved lead-lag to {OUT}/lead_lag.csv")

    # === 3) Copules : tail dependence ===
    print()
    print("=" * 90)
    print("COPULAS / RANK-BASED tail dependence on top inverse pairs")
    print("=" * 90)

    def empirical_tail_dep(x, y, q=0.05):
        """Lower tail: P(Y < q | X < q). Upper: P(Y > 1-q | X > 1-q)."""
        rx = x.rank(pct=True)
        ry = y.rank(pct=True)
        n = len(rx)
        lower = ((rx < q) & (ry < q)).sum() / max(1, (rx < q).sum())
        upper = ((rx > 1-q) & (ry > 1-q)).sum() / max(1, (rx > 1-q).sum())
        return lower, upper

    top_pairs = pairs[:8] + sorted(pairs, reverse=True)[:8]
    print(f"\n  {'Corr':>7s}  {'Lower':>6s}  {'Upper':>6s}  {'Pair'}")
    for c, p1, p2 in top_pairs:
        x = rets[p1].dropna()
        y = rets[p2].dropna()
        common = x.index.intersection(y.index)
        if len(common) < 100:
            continue
        l, u = empirical_tail_dep(x.loc[common], y.loc[common], q=0.10)
        sign = "+" if c > 0 else "-"
        print(f"  {c:>+7.3f}  {l:>6.3f}  {u:>6.3f}  {p1[:28]:<28s} ↔ {p2[:28]}")

    # === 4) Day-by-day stability ===
    print()
    print("=" * 90)
    print("PER-DAY return correlations stability (top 5 pairs)")
    print("=" * 90)
    for c, p1, p2 in pairs[:5]:
        print(f"\n{p1} ↔ {p2} (overall {c:+.3f}):")
        for d in [2, 3, 4]:
            r_d = rets.loc[(d,)] if (d,) in rets.index.get_level_values(0).unique() else None
            try:
                day_rets = rets.xs(d, level="day")
                cd = day_rets[[p1, p2]].corr().iloc[0, 1]
                print(f"  Day {d}: {cd:+.3f}")
            except (KeyError, IndexError) as e:
                pass


if __name__ == "__main__":
    main()
