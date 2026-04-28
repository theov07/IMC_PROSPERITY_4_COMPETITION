"""R5 deep analysis: spreads, stability, mean reversion vs trending."""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
DATA = ROOT / "data" / "round_5"


def main():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    prices = pd.concat(dfs, ignore_index=True)
    prices["mid"] = (prices["bid_price_1"].fillna(0) + prices["ask_price_1"].fillna(0)) / 2
    prices["spread"] = prices["ask_price_1"].fillna(0) - prices["bid_price_1"].fillna(0)
    prices["bv1"] = prices["bid_volume_1"].fillna(0)
    prices["av1"] = prices["ask_volume_1"].fillna(0)

    # === ANALYSIS 1: Mean reversion vs trending ===
    print("=" * 100)
    print("MEAN REVERSION vs TRENDING (per product)")
    print("Products with low |drift| / high std = mean reverting (good for MM/MR)")
    print("Products with high |drift| = trending (need directional)")
    print("=" * 100)

    profile = []
    for prod in sorted(prices["product"].unique()):
        sub = prices[prices["product"] == prod].sort_values(["day", "timestamp"])
        sub = sub[sub["mid"] > 0]
        if len(sub) < 100:
            continue
        s = sub.iloc[0]["mid"]
        e = sub.iloc[-1]["mid"]
        drift = abs(e - s)
        std = sub["mid"].std()
        # Spread stats
        sub_sp = sub[sub["spread"] > 0]
        avg_spread = sub_sp["spread"].mean()
        avg_vol = (sub["bv1"] + sub["av1"]).mean()
        # Reversion ratio
        rev_ratio = std / max(drift, 1)  # higher = more mean reverting
        profile.append({
            "product": prod, "drift_abs": drift, "std": std,
            "spread": avg_spread, "vol_at_top": avg_vol,
            "rev_ratio": rev_ratio,
        })

    df = pd.DataFrame(profile).sort_values("rev_ratio", ascending=False)
    print(f"\n{'Product':<35s}  {'|Drift|':>8s}  {'Std':>8s}  {'Spread':>8s}  {'Top vol':>9s}  {'Rev ratio':>10s}  Type")
    print("-" * 110)
    for _, r in df.iterrows():
        if r['rev_ratio'] > 5:
            typ = "MEAN REVERT (great MM/MR)"
        elif r['rev_ratio'] > 2:
            typ = "moderately reverting"
        elif r['rev_ratio'] > 1:
            typ = "mixed"
        else:
            typ = "TRENDING (directional)"
        print(f"{r['product']:<35s}  {r['drift_abs']:>8.1f}  {r['std']:>8.1f}  {r['spread']:>8.2f}  {r['vol_at_top']:>9.0f}  {r['rev_ratio']:>10.2f}  {typ}")

    # === ANALYSIS 2: Spreads — MM viability ===
    print()
    print("=" * 100)
    print("MM VIABILITY (spread x volume)")
    print("Wider spreads + high volume = best for MM. Position limit 10 → small captures.")
    print("=" * 100)
    df2 = df.sort_values("spread", ascending=False).head(15)
    print(f"\n{'Product':<35s}  {'Spread':>8s}  {'Top vol':>9s}  {'PnL/trade est':>14s}")
    print("-" * 80)
    for _, r in df2.iterrows():
        # Conservative est: spread * 0.5 * pos_limit (penny improve, 50% fill)
        est_pnl = r['spread'] * 0.5 * 10  # 10 = pos_limit per trade
        print(f"{r['product']:<35s}  {r['spread']:>8.2f}  {r['vol_at_top']:>9.0f}  {est_pnl:>14.2f}")

    # === ANALYSIS 3: Best inverse pairs ===
    print()
    print("=" * 100)
    print("INVERSE PAIRS (spread trading candidates)")
    print("=" * 100)
    pivot = prices.pivot_table(index=["day", "timestamp"], columns="product", values="mid", aggfunc="first")
    products_list = sorted(prices["product"].unique())
    pairs = []
    for i, p1 in enumerate(products_list):
        for p2 in products_list[i+1:]:
            try:
                c = pivot[[p1, p2]].dropna().corr().iloc[0, 1]
                if abs(c) > 0.5:
                    pairs.append((c, p1, p2))
            except Exception:
                pass
    pairs.sort()
    print(f"\nTop 15 most NEGATIVE pairs (inverse — good for spread trading):")
    print(f"{'Corr':>8s}  {'Product 1':<35s}  {'Product 2':<35s}")
    for c, p1, p2 in pairs[:15]:
        print(f"{c:>+8.3f}  {p1:<35s}  {p2:<35s}")

    print(f"\nTop 10 most POSITIVE pairs (cointegrated — basket spread):")
    for c, p1, p2 in sorted(pairs, reverse=True)[:10]:
        print(f"{c:>+8.3f}  {p1:<35s}  {p2:<35s}")

    # === ANALYSIS 4: Day-to-day pattern (regime change?) ===
    print()
    print("=" * 100)
    print("DAY-BY-DAY MID PRICE EVOLUTION (sample products)")
    print("=" * 100)
    samples = ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "PEBBLES_XL",
               "GALAXY_SOUNDS_BLACK_HOLES", "MICROCHIP_OVAL", "UV_VISOR_YELLOW"]
    for p in samples:
        print(f"\n{p}")
        for d in [2, 3, 4]:
            sub = prices[(prices["product"] == p) & (prices["day"] == d) & (prices["mid"] > 0)]
            if len(sub) == 0:
                continue
            print(f"  Day {d}: start {sub['mid'].iloc[0]:.0f}, end {sub['mid'].iloc[-1]:.0f}, "
                  f"min {sub['mid'].min():.0f}, max {sub['mid'].max():.0f}, std {sub['mid'].std():.0f}")


if __name__ == "__main__":
    main()
