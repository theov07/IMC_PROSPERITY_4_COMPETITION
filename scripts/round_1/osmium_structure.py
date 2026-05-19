"""OSMIUM microstructure probe.

Questions:
1. Is the 'anchor' of 10000 correct? Compute true rolling mean.
2. Autocorrelation of mid returns: mean-revert or random walk?
3. Distribution of (mid - anchor). If it's narrow Gaussian, quoting at
   anchor±k with size scaling by distance gives an analytical optimum.
4. Spread stability: is it really always 16? What about deeper levels?
5. Trade flow: do trades tend to arrive in the direction of the deviation
   (i.e. buys when price is low)? That would be GOOD — adverse selection low.
6. Half-life of mean reversion (AR(1) coefficient).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path("data/round_1")
SYM = "ASH_COATED_OSMIUM"


def analyze(day: int) -> None:
    p = pd.read_csv(DATA / f"prices_round_1_day_{day}.csv", sep=";")
    p = p[p["product"] == SYM].reset_index(drop=True)
    p = p[(p["mid_price"] > 1000) & p["bid_price_1"].notna() & p["ask_price_1"].notna()].reset_index(drop=True)
    mid = p["mid_price"].to_numpy()
    bid = p["bid_price_1"].to_numpy()
    ask = p["ask_price_1"].to_numpy()
    spread = ask - bid

    t = pd.read_csv(DATA / f"trades_round_1_day_{day}.csv", sep=";")
    t = t[t["symbol"] == SYM].reset_index(drop=True)

    print(f"\n{'='*60}\nDAY {day}")
    print(f"mid: mean={mid.mean():.3f} std={mid.std():.3f} "
          f"min={mid.min():.0f} max={mid.max():.0f}")
    print(f"spread: unique={sorted(set(spread))[:10]} mean={spread.mean():.1f}")

    # Deviation distribution
    dev = mid - 10000
    print(f"dev from 10000: mean={dev.mean():+.3f} std={dev.std():.3f}")
    for q in [1, 5, 25, 50, 75, 95, 99]:
        print(f"  p{q}: {np.percentile(dev, q):+.1f}")

    # AR(1) on mid — half life
    dm = np.diff(mid)
    x = mid[:-1] - mid.mean()
    y = dm
    if x.std() > 0:
        beta = np.sum(x * y) / np.sum(x * x)
        half_life = -np.log(2) / np.log(1 + beta) if -2 < beta < 0 else float("inf")
        print(f"AR(1) beta on centered mid: {beta:+.5f}  half_life~{half_life:.0f} ticks")

    # Trade direction vs deviation
    t["mid_at_trade"] = np.interp(t["timestamp"], p["timestamp"], mid)
    t["dev_at_trade"] = t["mid_at_trade"] - 10000
    t["trade_dev"] = t["price"] - t["mid_at_trade"]
    buys = t[t["trade_dev"] > 0]  # trade above mid = aggressive buy
    sells = t[t["trade_dev"] < 0]
    print(f"aggressive buys: n={len(buys)}  mean dev_mid={buys['dev_at_trade'].mean():+.2f}")
    print(f"aggressive sells: n={len(sells)}  mean dev_mid={sells['dev_at_trade'].mean():+.2f}")
    # if buys happen when dev < 0 → they're buying CHEAP → bad for us trying to buy
    # if buys happen when dev > 0 → chasing → good for us selling

    # Return autocorr
    r = np.diff(mid)
    if len(r) > 100:
        ac1 = np.corrcoef(r[:-1], r[1:])[0, 1]
        print(f"return autocorr lag1: {ac1:+.4f}")


def main() -> None:
    for d in (-2, -1, 0):
        analyze(d)


if __name__ == "__main__":
    main()
