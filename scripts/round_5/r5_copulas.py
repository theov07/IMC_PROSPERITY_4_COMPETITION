"""R5 proper copula analysis — going beyond the lower-tail proxy.

For each pair of interest (within-SNACKPACK, within-PEBBLES, inter-group):
  1. Compute pseudo-observations (rank/(n+1) -> uniform marginals)
  2. Estimate lambda_L (lower-tail) AND lambda_U (upper-tail) at multiple thresholds
  3. Asymmetry test : |lambda_L - lambda_U| -> Clayton-like vs Gumbel-like vs symmetric
  4. Kendall's tau -> implied parametric copula parameter
  5. Compare empirical to Gaussian copula at the same Pearson correlation
     (Gaussian has lambda_L = lambda_U = 0 -> any non-zero empirical tail = non-Gaussian)

What we want to know practically:
  - Do the SNACKPACK inverse pairs share a TAIL risk? (i.e. when CHOC crashes,
    does VAN crash too in the +Y direction? Or are they truly independent in tails?)
  - Does the SNACKPACK shock to OXYGEN_SHAKE happen specifically in tails or always?
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "round_5"
OUT = ROOT / "artifacts" / "analysis" / "round_5"
OUT.mkdir(parents=True, exist_ok=True)


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
    rets = np.log(pivot.replace(0, np.nan)).diff()
    return rets


def pseudo_obs(s: pd.Series) -> pd.Series:
    """rank/(n+1) -> uniform pseudo-observations. NaN-safe."""
    r = s.rank(method="average")
    n = s.notna().sum()
    return r / (n + 1)


def tail_dep(u: pd.Series, v: pd.Series, q: float, side: str = "lower") -> float:
    """Empirical tail dependence at threshold q (in [0,1]).

    Lower : P(V <= q | U <= q)
    Upper : P(V >= 1-q | U >= 1-q)
    """
    common = pd.concat([u, v], axis=1).dropna()
    if len(common) < 200:
        return float("nan")
    u, v = common.iloc[:, 0], common.iloc[:, 1]
    if side == "lower":
        cond = u <= q
        if cond.sum() == 0:
            return 0.0
        return float((v[cond] <= q).mean())
    else:
        cond = u >= 1 - q
        if cond.sum() == 0:
            return 0.0
        return float((v[cond] >= 1 - q).mean())


def kendall_tau(x: pd.Series, y: pd.Series) -> float:
    """Kendall's tau via Spearman approx (faster, similar)."""
    common = pd.concat([x, y], axis=1).dropna()
    if len(common) < 50:
        return float("nan")
    return float(common.corr(method="kendall").iloc[0, 1])


def clayton_lambda_l(tau: float) -> float:
    """Clayton copula parameter theta = 2*tau/(1-tau), lambda_L = 2^(-1/theta)."""
    if tau <= 0 or tau >= 1:
        return 0.0
    theta = 2 * tau / (1 - tau)
    if theta <= 0:
        return 0.0
    return 2 ** (-1 / theta)


def gumbel_lambda_u(tau: float) -> float:
    """Gumbel copula parameter theta = 1/(1-tau), lambda_U = 2 - 2^(1/theta)."""
    if tau <= 0 or tau >= 1:
        return 0.0
    theta = 1 / (1 - tau)
    if theta <= 1:
        return 0.0
    return 2 - 2 ** (1 / theta)


def analyze_pair(name_a: str, name_b: str, ra: pd.Series, rb: pd.Series) -> dict:
    common = pd.concat([ra, rb], axis=1).dropna()
    if len(common) < 200:
        return {}
    common.columns = ["a", "b"]
    n = len(common)
    # Pseudo obs
    ua = pseudo_obs(common["a"])
    ub = pseudo_obs(common["b"])
    # Pearson + Spearman + Kendall
    p_corr = float(common.corr(method="pearson").iloc[0, 1])
    s_corr = float(common.corr(method="spearman").iloc[0, 1])
    tau = kendall_tau(common["a"], common["b"])
    # Tail deps at multiple q (lower, upper)
    qs = [0.01, 0.025, 0.05, 0.10]
    lower = {f"lambda_L@q={q}": tail_dep(ua, ub, q, "lower") for q in qs}
    upper = {f"lambda_U@q={q}": tail_dep(ua, ub, q, "upper") for q in qs}
    # Implied params from parametric copulas (positive tau only)
    cl_lL = clayton_lambda_l(tau) if tau > 0 else 0.0
    gb_lU = gumbel_lambda_u(tau) if tau > 0 else 0.0
    # Gaussian copula has lambda = 0 always - so any non-zero empirical tail
    # is evidence of non-Gaussian
    asym = lower.get("lambda_L@q=0.05", 0) - upper.get("lambda_U@q=0.05", 0)
    return dict(
        a=name_a, b=name_b, n=n,
        pearson=p_corr, spearman=s_corr, kendall=tau,
        **lower, **upper,
        clayton_implied_lL=cl_lL,
        gumbel_implied_lU=gb_lU,
        asymmetry_q05=asym,
    )


def main():
    print("Loading R5 returns...")
    rets = load_returns()
    products = rets.columns.tolist()
    print(f"Products: {len(products)}, ticks: {len(rets)}")

    # === 1. Within-SNACKPACK pairs ===
    print("\n" + "=" * 100)
    print("WITHIN-SNACKPACK COPULAS")
    print("=" * 100)
    sp = ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
          "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]
    sp = [s for s in sp if s in rets.columns]
    rows = []
    for i, a in enumerate(sp):
        for b in sp[i + 1:]:
            r = analyze_pair(a, b, rets[a], rets[b])
            if r:
                rows.append(r)
    df_sp = pd.DataFrame(rows)
    print(df_sp[["a", "b", "pearson", "kendall",
                 "lambda_L@q=0.05", "lambda_U@q=0.05",
                 "asymmetry_q05",
                 "clayton_implied_lL", "gumbel_implied_lU"]].round(3).to_string(index=False))
    df_sp.to_csv(OUT / "copulas_snackpack.csv", index=False)

    # === 2. Within-PEBBLES pairs ===
    print("\n" + "=" * 100)
    print("WITHIN-PEBBLES COPULAS")
    print("=" * 100)
    pb = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"]
    pb = [s for s in pb if s in rets.columns]
    rows = []
    for i, a in enumerate(pb):
        for b in pb[i + 1:]:
            r = analyze_pair(a, b, rets[a], rets[b])
            if r:
                rows.append(r)
    df_pb = pd.DataFrame(rows)
    print(df_pb[["a", "b", "pearson", "kendall",
                 "lambda_L@q=0.05", "lambda_U@q=0.05",
                 "asymmetry_q05",
                 "clayton_implied_lL", "gumbel_implied_lU"]].round(3).to_string(index=False))
    df_pb.to_csv(OUT / "copulas_pebbles.csv", index=False)

    # === 3. SNACKPACK index vs others (impulse leader) ===
    print("\n" + "=" * 100)
    print("SNACKPACK INDEX vs OTHER GROUPS COPULAS")
    print("=" * 100)
    GROUPS = {
        "SNACKPACK": ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                      "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
        "OXYGEN_SHAKE": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                         "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE",
                         "OXYGEN_SHAKE_GARLIC"],
        "GALAXY_SOUNDS": ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                          "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                          "GALAXY_SOUNDS_SOLAR_FLAMES"],
        "UV_VISOR": ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                     "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
        "SLEEP_POD": ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                      "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
        "TRANSLATOR": ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                       "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                       "TRANSLATOR_VOID_BLUE"],
        "PANEL": ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
        "ROBOT": ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
                  "ROBOT_LAUNDRY", "ROBOT_IRONING"],
        "MICROCHIP": ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                      "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
        "PEBBLES": ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    }
    grp_idx = {}
    for g, members in GROUPS.items():
        m = [x for x in members if x in rets.columns]
        if m:
            # Equal-weighted return = mean
            grp_idx[g] = rets[m].mean(axis=1)
    grp_idx_df = pd.DataFrame(grp_idx)
    rows = []
    cols = list(grp_idx_df.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            r = analyze_pair(a, b, grp_idx_df[a], grp_idx_df[b])
            if r:
                rows.append(r)
    df_g = pd.DataFrame(rows)
    df_g["abs_pearson"] = df_g["pearson"].abs()
    df_g = df_g.sort_values("abs_pearson", ascending=False)
    print("Top 15 by |Pearson| with copula info:")
    print(df_g[["a", "b", "pearson", "kendall",
                "lambda_L@q=0.05", "lambda_U@q=0.05",
                "asymmetry_q05"]].head(15).round(3).to_string(index=False))
    df_g.to_csv(OUT / "copulas_intergroup.csv", index=False)

    # === 4. Summary : where is non-Gaussian behaviour the strongest? ===
    print("\n" + "=" * 100)
    print("NON-GAUSSIAN SIGNAL = max(lambda_L, lambda_U) at q=0.05")
    print("(Gaussian copula at any rho has lambda=0 in both tails)")
    print("=" * 100)
    for label, df in [("SNACKPACK", df_sp), ("PEBBLES", df_pb), ("INTER-GROUP", df_g)]:
        df = df.copy()
        df["max_tail"] = df[["lambda_L@q=0.05", "lambda_U@q=0.05"]].max(axis=1)
        df["min_tail"] = df[["lambda_L@q=0.05", "lambda_U@q=0.05"]].min(axis=1)
        top = df.sort_values("max_tail", ascending=False).head(5)
        print(f"\n{label} top 5 by max_tail:")
        print(top[["a", "b", "pearson", "kendall",
                   "lambda_L@q=0.05", "lambda_U@q=0.05",
                   "asymmetry_q05"]].round(3).to_string(index=False))

    print(f"\nDone. Outputs in {OUT}")


if __name__ == "__main__":
    main()
