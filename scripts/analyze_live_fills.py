"""Extract real fill metrics from an official IMC log.

Goal: calibrate a realistic fill model. For each SUBMISSION trade, classify:
  - aggressive (price crosses opposite top-of-book at fill tick) vs passive
  - edge vs mid at fill time
  - markout: mid(t+k) - fill_price, signed by side (positive = profitable)
  - inter-arrival gap, size vs position-limit
Also aggregates per-side, per-product, and compares vs book turnover.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from io import StringIO

import pandas as pd

LOG_PATH = "logs/round_1/leo/best_osmium_log/170620.log"
PRODUCT = "ASH_COATED_OSMIUM"
POS_LIMIT = 80
MARKOUT_HORIZONS = [1, 5, 10, 20, 50, 100]


def load(path: str):
    with open(path, "r") as f:
        d = json.load(f)
    prices = pd.read_csv(StringIO(d["activitiesLog"]), sep=";")
    trades = pd.DataFrame(d["tradeHistory"])
    return prices, trades


def main():
    prices, trades = load(LOG_PATH)
    p = prices[prices["product"] == PRODUCT].copy().sort_values("timestamp").reset_index(drop=True)
    mid_by_ts = dict(zip(p["timestamp"], p["mid_price"]))
    bid1 = dict(zip(p["timestamp"], p["bid_price_1"]))
    ask1 = dict(zip(p["timestamp"], p["ask_price_1"]))
    bvol1 = dict(zip(p["timestamp"], p["bid_volume_1"]))
    avol1 = dict(zip(p["timestamp"], p["ask_volume_1"]))

    ours = trades[(trades["symbol"] == PRODUCT) & ((trades["buyer"] == "SUBMISSION") | (trades["seller"] == "SUBMISSION"))].copy()
    ours["side"] = ours["buyer"].apply(lambda b: "BUY" if b == "SUBMISSION" else "SELL")

    n_buys = (ours["side"] == "BUY").sum()
    n_sells = (ours["side"] == "SELL").sum()
    total_qty = ours["quantity"].sum()
    buy_qty = ours.loc[ours["side"] == "BUY", "quantity"].sum()
    sell_qty = ours.loc[ours["side"] == "SELL", "quantity"].sum()

    print(f"=== {PRODUCT} | {LOG_PATH} ===")
    print(f"ticks                : {len(p)}")
    print(f"our fills            : {len(ours)}  ({n_buys} buys, {n_sells} sells)")
    print(f"qty filled           : {total_qty}  (buy={buy_qty}, sell={sell_qty})")
    print(f"avg fill size        : {ours['quantity'].mean():.2f}  (median={ours['quantity'].median()})")
    print(f"max fill size        : {ours['quantity'].max()}")
    print(f"fills per 1000 ticks : {len(ours) / (len(p)/1000):.1f}")
    print(f"qty / (2*limit*day)  : {total_qty / (2*POS_LIMIT):.1f} turnover units")

    # Classify aggressive vs passive at fill tick
    agg = 0
    passive = 0
    inside = 0  # we filled inside the spread (improving)
    at_best = 0
    edge_stats = []  # edge vs mid at fill
    markouts = {h: [] for h in MARKOUT_HORIZONS}
    ts_list = sorted(mid_by_ts.keys())
    for _, r in ours.iterrows():
        ts = int(r["timestamp"])
        side = r["side"]
        px = float(r["price"])
        mid = mid_by_ts.get(ts)
        bb = bid1.get(ts)
        aa = ask1.get(ts)
        if mid is None or bb is None or aa is None or pd.isna(bb) or pd.isna(aa):
            continue
        signed_edge = (mid - px) if side == "BUY" else (px - mid)
        edge_stats.append(signed_edge)
        # aggressive: we crossed book
        if side == "BUY" and px >= aa:
            agg += 1
        elif side == "SELL" and px <= bb:
            agg += 1
        else:
            passive += 1
            if side == "BUY" and px > bb:
                inside += 1
            elif side == "BUY" and px == bb:
                at_best += 1
            elif side == "SELL" and px < aa:
                inside += 1
            elif side == "SELL" and px == aa:
                at_best += 1
        # markout
        for h in MARKOUT_HORIZONS:
            mt = mid_by_ts.get(ts + 100 * h)
            if mt is None:
                continue
            mo = (mt - px) if side == "BUY" else (px - mt)
            markouts[h].append(mo)

    total_cls = agg + passive
    print()
    print("--- aggression classification ---")
    print(f"aggressive (cross)   : {agg}  ({100*agg/total_cls:.1f}%)")
    print(f"passive              : {passive}  ({100*passive/total_cls:.1f}%)")
    print(f"  of passive: inside : {inside}")
    print(f"  of passive: at best: {at_best}")
    print()
    print("--- edge at fill (signed, positive = profitable vs mid) ---")
    s = pd.Series(edge_stats)
    print(f"mean={s.mean():+.3f}  median={s.median():+.2f}  std={s.std():.2f}  min={s.min():+.1f}  max={s.max():+.1f}")
    print()
    print("--- markout vs mid (signed per side, + = profit) ---")
    print(f"{'h':>4} {'n':>5} {'mean':>8} {'median':>8} {'std':>8}")
    for h in MARKOUT_HORIZONS:
        m = pd.Series(markouts[h])
        print(f"{h:>4} {len(m):>5} {m.mean():>+8.3f} {m.median():>+8.2f} {m.std():>8.2f}")

    # Fill rate vs book turnover
    p["bid_vol_top"] = p["bid_volume_1"].fillna(0)
    p["ask_vol_top"] = p["ask_volume_1"].fillna(0)
    total_market_qty = (p["bid_vol_top"].sum() + p["ask_vol_top"].sum())
    print()
    print("--- our share of flow ---")
    print(f"top-of-book vol sum  : {int(total_market_qty)}")
    print(f"our filled qty       : {int(total_qty)}")
    print(f"our share of L1 vol  : {100*total_qty/total_market_qty:.2f}%")

    # Inter-arrival
    dts = ours["timestamp"].diff().dropna()
    print()
    print("--- inter-arrival (ticks between our fills) ---")
    print(f"mean={dts.mean():.0f}  median={dts.median():.0f}  p10={dts.quantile(.1):.0f}  p90={dts.quantile(.9):.0f}")

    # PnL estimate from fills (realized only if flat)
    signed = ours.apply(lambda r: r["quantity"] * (1 if r["side"] == "BUY" else -1), axis=1)
    net = signed.sum()
    cash = -(signed * ours["price"]).sum()
    last_mid = p["mid_price"].iloc[-1]
    mtm = net * last_mid
    print()
    print(f"--- PnL check ---")
    print(f"net position end     : {net}")
    print(f"cash                 : {cash:+.0f}")
    print(f"mtm final            : {mtm:+.0f}")
    print(f"total                : {cash + mtm:+.0f}")


if __name__ == "__main__":
    main()
