"""R5 impulse response analysis (advisor's "Same but Slower" tip).

Question: when product/group X has a SHOCK (return > 2 sigma), how does
product/group Y respond at lags 1..50?

Different from intra-tick correlation : this conditions on a tail event.

Method:
  1. Define shock threshold per series (return > 2 std)
  2. For each pair, compute mean(Y return at t+k | X shock at t) for k=0..50
  3. If mean is significantly non-zero with consistent sign, X→Y is an impulse path
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
    "ROBOT": ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
              "ROBOT_LAUNDRY", "ROBOT_IRONING"],
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


def load_prices():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    p = pd.concat(dfs, ignore_index=True)
    p["mid"] = (p["bid_price_1"].fillna(0) + p["ask_price_1"].fillna(0)) / 2
    return p


def build_group_indices(pivot_mid: pd.DataFrame) -> pd.DataFrame:
    cols = {}
    for g, members in GROUPS.items():
        m = [x for x in members if x in pivot_mid.columns]
        if not m:
            continue
        sub = pivot_mid[m]
        z = (sub - sub.mean()) / sub.std()
        cols[g] = z.mean(axis=1)
    return pd.DataFrame(cols, index=pivot_mid.index)


def impulse_response(x_ret: pd.Series, y_ret: pd.Series, sigma_thresh: float = 2.0,
                     lags: int = 50) -> dict:
    """Mean response of Y at t+1..t+lags conditional on a shock in X at t.

    Returns dict with per-lag conditional mean of y_ret normalized to y_std.
    """
    common = pd.concat([x_ret, y_ret], axis=1).dropna()
    common.columns = ["x", "y"]
    if len(common) < 200:
        return {}
    x_std = common["x"].std()
    y_std = common["y"].std()
    if x_std < 1e-9 or y_std < 1e-9:
        return {}
    pos_thresh = sigma_thresh * x_std
    neg_thresh = -sigma_thresh * x_std
    out = {}
    for k in range(0, lags + 1):
        # y at t+k given x at t
        if k == 0:
            y_shifted = common["y"]
        else:
            y_shifted = common["y"].shift(-k)
        valid = y_shifted.notna()
        cond_pos = (common["x"] >= pos_thresh) & valid
        cond_neg = (common["x"] <= neg_thresh) & valid
        n_pos = int(cond_pos.sum())
        n_neg = int(cond_neg.sum())
        m_pos = float(y_shifted[cond_pos].mean()) / y_std if n_pos > 5 else 0.0
        m_neg = float(y_shifted[cond_neg].mean()) / y_std if n_neg > 5 else 0.0
        out[k] = dict(n_pos=n_pos, n_neg=n_neg, mu_pos=m_pos, mu_neg=m_neg)
    return out


def main():
    print("Loading R5 prices...")
    prices = load_prices()
    pivot = prices.pivot_table(
        index=["day", "timestamp"], columns="product", values="mid", aggfunc="first"
    )
    grp = build_group_indices(pivot)
    grp_ret = grp.diff()
    print(f"Group indices: {grp.shape}")

    # === GROUP-LEVEL impulse response ===
    print("\n=== GROUP impulse response (shock @ 2 sigma) ===")
    print("Cell = mean response (in y-sigma units) at lag k after a +2 sigma shock in X")
    cols = grp.columns.tolist()
    rows = []
    for x in cols:
        for y in cols:
            if x == y:
                continue
            ir = impulse_response(grp_ret[x], grp_ret[y], sigma_thresh=2.0, lags=50)
            if not ir:
                continue
            # Sum lags 1..5 (immediate response window)
            mu_5 = sum(ir[k]["mu_pos"] for k in range(1, 6)) / 5
            mu_20 = sum(ir[k]["mu_pos"] for k in range(1, 21)) / 20
            mu_50 = sum(ir[k]["mu_pos"] for k in range(1, 51)) / 50
            rows.append((x, y, ir[1]["mu_pos"], mu_5, mu_20, mu_50, ir[1]["n_pos"]))
    df = pd.DataFrame(rows, columns=["leader", "follower", "lag1_mu", "lags1_5_avg", "lags1_20_avg", "lags1_50_avg", "n_shocks"])
    df["abs_5"] = df["lags1_5_avg"].abs()
    df = df.sort_values("abs_5", ascending=False)
    print("\nTop 15 by |mean response in lags 1..5|:")
    print(df.head(15).to_string(index=False))
    df.to_csv(OUT / "impulse_groups.csv", index=False)

    # === Within-group impulse: SNACKPACK & PEBBLES (anti-corr) ===
    print("\n=== Within-group impulse: SNACKPACK ===")
    sp_members = [m for m in GROUPS["SNACKPACK"] if m in pivot.columns]
    sp_rets = np.log(pivot[sp_members].replace(0, np.nan)).diff()
    rows = []
    for x in sp_members:
        for y in sp_members:
            if x == y:
                continue
            ir = impulse_response(sp_rets[x], sp_rets[y], sigma_thresh=2.0, lags=20)
            if ir:
                mu_5 = sum(ir[k]["mu_pos"] for k in range(1, 6)) / 5
                rows.append((x, y, ir[1]["mu_pos"], mu_5, ir[1]["n_pos"]))
    df_sp = pd.DataFrame(rows, columns=["leader", "follower", "lag1_mu", "lags1_5_avg", "n_shocks"])
    df_sp["abs_1"] = df_sp["lag1_mu"].abs()
    print(df_sp.sort_values("abs_1", ascending=False).head(15).to_string(index=False))
    df_sp.to_csv(OUT / "impulse_snackpack.csv", index=False)

    print("\n=== Within-group impulse: PEBBLES ===")
    pb_members = [m for m in GROUPS["PEBBLES"] if m in pivot.columns]
    pb_rets = np.log(pivot[pb_members].replace(0, np.nan)).diff()
    rows = []
    for x in pb_members:
        for y in pb_members:
            if x == y:
                continue
            ir = impulse_response(pb_rets[x], pb_rets[y], sigma_thresh=2.0, lags=20)
            if ir:
                mu_5 = sum(ir[k]["mu_pos"] for k in range(1, 6)) / 5
                rows.append((x, y, ir[1]["mu_pos"], mu_5, ir[1]["n_pos"]))
    df_pb = pd.DataFrame(rows, columns=["leader", "follower", "lag1_mu", "lags1_5_avg", "n_shocks"])
    df_pb["abs_1"] = df_pb["lag1_mu"].abs()
    print(df_pb.sort_values("abs_1", ascending=False).head(15).to_string(index=False))
    df_pb.to_csv(OUT / "impulse_pebbles.csv", index=False)

    print(f"\nDone. Outputs in {OUT}")


if __name__ == "__main__":
    main()
