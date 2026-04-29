"""R5 GROUP-LEVEL analysis — advisor's request: cluster filtering + group ETF baskets.

The 10 wiki-defined groups become the unit of analysis (Level 1 abstraction).
For each group:
  1. Compute group index = equal-weighted mean mid-price (z-scored)
  2. Group-level statistics : avg mid, std, total volume, avg spread
  3. Within-group cohesion : how correlated are the 5 members?
  4. Group PnL contribution under r5_v2_winners_only (from prior backtest)

Inter-group:
  5. Pearson + Spearman correlations between group indices (LEVELS + RETURNS)
  6. Empirical tail dependence (copula proxy) between group indices
  7. Lead-lag at GROUP level (lags 1, 5, 10, 50, 200, 1000 ticks)
  8. Cointegration (Engle-Granger residual stationarity proxy)

Outputs CSVs + a summary printed to stdout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
DATA = ROOT / "data" / "round_5"
OUT = ROOT / "artifacts" / "analysis" / "round_5"
OUT.mkdir(parents=True, exist_ok=True)

GROUPS = {
    "GALAXY_SOUNDS": [
        "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
        "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
        "GALAXY_SOUNDS_SOLAR_FLAMES",
    ],
    "SLEEP_POD": [
        "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
        "SLEEP_POD_NYLON", "SLEEP_POD_COTTON",
    ],
    "MICROCHIP": [
        "MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
        "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE",
    ],
    "PEBBLES": [
        "PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL",
    ],
    "ROBOT": [
        "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
        "ROBOT_LAUNDRY", "ROBOT_IRONING",
    ],
    "UV_VISOR": [
        "UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
        "UV_VISOR_RED", "UV_VISOR_MAGENTA",
    ],
    "TRANSLATOR": [
        "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_VOID_BLUE",
    ],
    "PANEL": [
        "PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4",
    ],
    "OXYGEN_SHAKE": [
        "OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
        "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE",
        "OXYGEN_SHAKE_GARLIC",
    ],
    "SNACKPACK": [
        "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY",
    ],
}

LOSERS = {
    "OXYGEN_SHAKE_MINT", "TRANSLATOR_GRAPHITE_MIST", "PEBBLES_XS",
    "ROBOT_VACUUMING", "PANEL_4X4", "TRANSLATOR_SPACE_GRAY",
    "GALAXY_SOUNDS_SOLAR_FLAMES", "UV_VISOR_MAGENTA", "ROBOT_MOPPING",
    "PANEL_1X2", "PEBBLES_M", "SLEEP_POD_LAMB_WOOL",
}


def load_prices():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    p = pd.concat(dfs, ignore_index=True)
    p["mid"] = (p["bid_price_1"].fillna(0) + p["ask_price_1"].fillna(0)) / 2
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p


def build_group_indices(pivot_mid: pd.DataFrame) -> pd.DataFrame:
    """Group index = z-scored equal-weight average of group members.

    Z-scoring per-product first ensures different price scales don't dominate.
    """
    cols = {}
    for g, members in GROUPS.items():
        members_in_pivot = [m for m in members if m in pivot_mid.columns]
        if not members_in_pivot:
            continue
        # z-score each member, then average
        sub = pivot_mid[members_in_pivot]
        zsub = (sub - sub.mean()) / sub.std()
        cols[g] = zsub.mean(axis=1)
    return pd.DataFrame(cols, index=pivot_mid.index)


def empirical_tail_dependence(x: pd.Series, y: pd.Series, q: float = 0.05) -> float:
    """Lower-tail dependence: P(Y < q-quantile | X < q-quantile)."""
    common = pd.concat([x, y], axis=1).dropna()
    if len(common) < 100:
        return 0.0
    xq = common.iloc[:, 0].quantile(q)
    yq = common.iloc[:, 1].quantile(q)
    cond = common.iloc[:, 0] <= xq
    if cond.sum() == 0:
        return 0.0
    return float((common.iloc[:, 1][cond] <= yq).mean())


def cointegration_eg(x: pd.Series, y: pd.Series):
    """Engle-Granger 2-step: regress x on y, test residual stationarity (proxy via ADF).

    Without statsmodels we do a simple proxy: residual std + AR(1) coefficient.
    Stationary <=> ar_coef < 1 (definitively below) and residual std small relative to scale.
    Returns (beta, ar_coef, resid_std, score). High score = more cointegrated.
    """
    common = pd.concat([x, y], axis=1).dropna()
    if len(common) < 100:
        return None
    xv = common.iloc[:, 0].values
    yv = common.iloc[:, 1].values
    # OLS x = a + b*y
    b = np.cov(xv, yv, ddof=0)[0, 1] / np.var(yv)
    a = xv.mean() - b * yv.mean()
    resid = xv - (a + b * yv)
    if len(resid) < 10:
        return None
    # AR(1) on resid
    r0 = resid[:-1]
    r1 = resid[1:]
    ar = np.cov(r0, r1, ddof=0)[0, 1] / max(np.var(r0), 1e-9)
    resid_std = float(np.std(resid))
    score = max(0.0, 1.0 - abs(ar))  # closer to 0 => more stationary
    return dict(beta=float(b), ar=float(ar), resid_std=resid_std, score=float(score),
                a=float(a), n=int(len(common)))


def main():
    print("Loading R5 prices...")
    prices = load_prices()
    pivot = prices.pivot_table(
        index=["day", "timestamp"], columns="product", values="mid", aggfunc="first"
    )
    spread_pivot = prices.pivot_table(
        index=["day", "timestamp"], columns="product", values="spread", aggfunc="first"
    )
    products = pivot.columns.tolist()
    print(f"Products: {len(products)}, ticks: {len(pivot)}")

    # === 1. Group indices ===
    print("\n=== Group Indices ===")
    group_idx = build_group_indices(pivot)
    print(group_idx.describe().T[["mean", "std", "min", "max"]].round(3))
    group_idx.to_csv(OUT / "group_indices.csv")

    # === 2. Within-group cohesion ===
    print("\n=== Within-group cohesion (avg pairwise corr of members) ===")
    rets = np.log(pivot.replace(0, np.nan)).diff()
    cohesion = {}
    for g, members in GROUPS.items():
        m = [x for x in members if x in pivot.columns]
        if len(m) < 2:
            continue
        sub = rets[m].corr()
        # Average upper triangle
        mask = np.triu(np.ones(len(m)), k=1).astype(bool)
        avg = sub.values[mask].mean()
        cohesion[g] = avg
    coh_s = pd.Series(cohesion).sort_values(ascending=False)
    print(coh_s.round(3))
    coh_s.to_csv(OUT / "group_cohesion.csv")

    # === 3. Inter-group correlations (Pearson on group index) ===
    print("\n=== Inter-group correlation (Pearson, LEVELS) ===")
    inter_lvl = group_idx.corr(method="pearson")
    print(inter_lvl.round(2))
    inter_lvl.to_csv(OUT / "intergroup_pearson_levels.csv")

    print("\n=== Inter-group correlation (Pearson, RETURNS) ===")
    grp_rets = group_idx.diff()
    inter_ret = grp_rets.corr(method="pearson")
    print(inter_ret.round(2))
    inter_ret.to_csv(OUT / "intergroup_pearson_returns.csv")

    print("\n=== Inter-group correlation (Spearman, RETURNS) ===")
    inter_ret_sp = grp_rets.corr(method="spearman")
    inter_ret_sp.to_csv(OUT / "intergroup_spearman_returns.csv")

    # === 4. Top inter-group pairs ===
    print("\n=== Top inter-group |corr| pairs (returns) ===")
    pairs = []
    cols = inter_ret.columns.tolist()
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            r = inter_ret.loc[a, b]
            s = inter_ret_sp.loc[a, b]
            pairs.append((a, b, r, s, abs(r)))
    pairs.sort(key=lambda x: x[4], reverse=True)
    print(f"{'group_a':<14s}{'group_b':<14s}{'pearson':>9s}{'spearman':>10s}")
    for a, b, r, s, _ in pairs[:15]:
        print(f"{a:<14s}{b:<14s}{r:>9.3f}{s:>10.3f}")
    pd.DataFrame(pairs, columns=["group_a", "group_b", "pearson", "spearman", "abs_pearson"]).to_csv(
        OUT / "intergroup_pairs.csv", index=False
    )

    # === 5. Tail dependence (copula proxy) ===
    print("\n=== Inter-group lower-tail dependence (q=0.05) ===")
    tail = pd.DataFrame(index=cols, columns=cols, dtype=float)
    for a in cols:
        for b in cols:
            tail.loc[a, b] = empirical_tail_dependence(grp_rets[a], grp_rets[b], q=0.05)
    print(tail.round(2))
    tail.to_csv(OUT / "intergroup_tail_dep.csv")

    # === 6. Lead-lag at GROUP level ===
    print("\n=== Inter-group LEAD-LAG (returns) ===")
    print("Cell = max |corr(group_a(t), group_b(t+lag))| across lags 1, 5, 10, 50, 200")
    lags = [1, 5, 10, 50, 200]
    lead = []
    for a in cols:
        for b in cols:
            if a == b:
                continue
            best_corr = 0.0
            best_lag = 0
            for k in lags:
                # group_a(t) vs group_b(t+k) => shift b by -k
                joined = pd.concat([grp_rets[a], grp_rets[b].shift(-k)], axis=1).dropna()
                if len(joined) < 100:
                    continue
                c = joined.corr().iloc[0, 1]
                if abs(c) > abs(best_corr):
                    best_corr = c
                    best_lag = k
            lead.append((a, b, best_lag, best_corr))
    lead.sort(key=lambda x: abs(x[3]), reverse=True)
    print(f"{'leader':<14s}{'follower':<14s}{'lag':>5s}{'corr':>9s}")
    for a, b, k, c in lead[:20]:
        print(f"{a:<14s}{b:<14s}{k:>5d}{c:>9.3f}")
    pd.DataFrame(lead, columns=["leader", "follower", "lag", "corr"]).to_csv(
        OUT / "intergroup_leadlag.csv", index=False
    )

    # === 7. Cointegration at GROUP level (Engle-Granger proxy) ===
    print("\n=== Inter-group cointegration (EG proxy on LEVELS) ===")
    coint = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            r = cointegration_eg(group_idx[a], group_idx[b])
            if r:
                coint.append((a, b, r["beta"], r["ar"], r["resid_std"], r["score"]))
    coint.sort(key=lambda x: x[5], reverse=True)
    print(f"{'group_a':<14s}{'group_b':<14s}{'beta':>8s}{'ar':>8s}{'resid_std':>11s}{'score':>8s}")
    for a, b, beta, ar, rs, sc in coint[:15]:
        print(f"{a:<14s}{b:<14s}{beta:>8.3f}{ar:>8.3f}{rs:>11.3f}{sc:>8.3f}")
    pd.DataFrame(coint, columns=["group_a", "group_b", "beta", "ar", "resid_std", "score"]).to_csv(
        OUT / "intergroup_coint.csv", index=False
    )

    # === 8. Group profile: avg spread, mean rev, etc. ===
    print("\n=== Group profile (member-averaged) ===")
    profile = []
    for g, members in GROUPS.items():
        m = [x for x in members if x in pivot.columns]
        if not m:
            continue
        avg_spread = float(spread_pivot[m].mean().mean())
        avg_std = float(pivot[m].std().mean())
        n_losers = sum(1 for x in m if x in LOSERS)
        n_winners = len(m) - n_losers
        profile.append(dict(
            group=g, n=len(m), n_winners=n_winners, n_losers=n_losers,
            avg_spread=avg_spread, avg_std=avg_std, cohesion=cohesion.get(g, 0),
        ))
    prof_df = pd.DataFrame(profile).sort_values("cohesion", ascending=False)
    print(prof_df.round(3).to_string(index=False))
    prof_df.to_csv(OUT / "group_profile.csv", index=False)

    print(f"\nAll output written to {OUT}")


if __name__ == "__main__":
    main()
