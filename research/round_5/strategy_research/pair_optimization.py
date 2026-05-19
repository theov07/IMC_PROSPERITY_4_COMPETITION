"""Find optimal pair partner per product based on backtest of pair_skip_mm.

For each candidate pair-able product (high cohesion or strong anti-corr),
compute the expected improvement from skip when partner_z is extreme.

Method:
  1. For each pair (a, b) in PEBBLES + SNACKPACK + cross-group strong-anti pairs:
     - Compute z(a) - sign * z(b) signal over rolling 300 ticks
     - Identify ticks where |signal| > thresh
     - Measure cumulative return of a in next 5/20/50 ticks AFTER the signal
     - Compare to: cumulative return without filter
     - The "edge" = mean response × magnitude of signal

  2. Pick the partner with the highest predictive edge.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "round_5"
OUT = ROOT / "artifacts" / "analysis" / "round_5"
OUT.mkdir(parents=True, exist_ok=True)


def load_pivot():
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        dfs.append(df)
    p = pd.concat(dfs, ignore_index=True)
    p["mid"] = (p["bid_price_1"].fillna(0) + p["ask_price_1"].fillna(0)) / 2
    pivot = p.pivot_table(index=["timestamp"], columns="product",
                          values="mid", aggfunc="first")
    return pivot


def evaluate_pair(a: str, b: str, pivot: pd.DataFrame, sign: float = -1.0,
                  z_window: int = 300, thresh: float = 1.5,
                  forward: int = 5):
    """Test if z(a) - sign*z(b) > thresh predicts a's next-N-tick return.

    Returns the average forward-N return of a AFTER triggering events (and the
    average AFTER -triggering events, for symmetry).
    """
    if a not in pivot.columns or b not in pivot.columns:
        return None
    pa = pivot[a].dropna()
    pb = pivot[b].dropna()
    common = pd.concat([pa, pb], axis=1, join="inner")
    common.columns = ["a", "b"]
    if len(common) < 1000:
        return None
    # Rolling z
    za = (common["a"] - common["a"].rolling(z_window).mean()) / common["a"].rolling(z_window).std()
    zb = (common["b"] - common["b"].rolling(z_window).mean()) / common["b"].rolling(z_window).std()
    signal = za - sign * zb  # if sign=-1, signal = za + zb
    fwd_ret = common["a"].shift(-forward) - common["a"]  # in price units
    valid = signal.notna() & fwd_ret.notna()

    pos_mask = (signal > thresh) & valid
    neg_mask = (signal < -thresh) & valid
    n_pos = int(pos_mask.sum())
    n_neg = int(neg_mask.sum())
    if n_pos < 50 or n_neg < 50:
        return None
    mu_pos = float(fwd_ret[pos_mask].mean())  # if signal high (a rich), do we expect a to drop?
    mu_neg = float(fwd_ret[neg_mask].mean())  # if signal low (a cheap), do we expect a to rise?
    # Predictive edge = -mu_pos + mu_neg (negative response to + signal, positive to - signal)
    edge = -mu_pos + mu_neg
    return dict(a=a, b=b, n_pos=n_pos, n_neg=n_neg, mu_pos=mu_pos, mu_neg=mu_neg, edge=edge)


def main():
    pivot = load_pivot()
    products = pivot.columns.tolist()
    PEBBLES = [p for p in products if p.startswith("PEBBLES_")]
    SNACKPACKS = [p for p in products if p.startswith("SNACKPACK_")]

    rows = []
    print("=== Pair optimization: PEBBLES candidates ===")
    print(f"{'a':<22s} {'b':<22s} {'n_pos':>6s} {'n_neg':>6s} {'mu_pos':>9s} {'mu_neg':>9s} {'edge':>9s}")
    for a in PEBBLES:
        for b in PEBBLES:
            if a == b: continue
            for sign in [-1.0, +1.0]:
                r = evaluate_pair(a, b, pivot, sign=sign)
                if r:
                    r["sign"] = sign
                    rows.append(r)
                    print(f"{a:<22s} {b:<22s} {r['n_pos']:>6d} {r['n_neg']:>6d} {r['mu_pos']:>9.3f} {r['mu_neg']:>9.3f} {r['edge']:>9.3f}  sign={sign:+.0f}")

    print("\n=== SNACKPACK candidates ===")
    for a in SNACKPACKS:
        for b in SNACKPACKS:
            if a == b: continue
            for sign in [-1.0, +1.0]:
                r = evaluate_pair(a, b, pivot, sign=sign)
                if r:
                    r["sign"] = sign
                    rows.append(r)
                    print(f"{a:<22s} {b:<22s} {r['n_pos']:>6d} {r['n_neg']:>6d} {r['mu_pos']:>9.3f} {r['mu_neg']:>9.3f} {r['edge']:>9.3f}  sign={sign:+.0f}")

    df = pd.DataFrame(rows)
    df_top = df.sort_values("edge", ascending=False).head(20)
    print("\n=== TOP 20 pairs by edge ===")
    print(df_top.to_string(index=False))
    df.to_csv(OUT / "pair_optimization_PEBBLES_SNACKPACK.csv", index=False)


if __name__ == "__main__":
    main()
