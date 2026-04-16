"""Refined fill-condition analysis: split passive vs aggressive,
look at recent flow, book state, and what actually differentiates
fill-ticks from base."""
from __future__ import annotations

import json
from io import StringIO

import pandas as pd

LOG = "logs/round_1/leo/best_osmium_log/170620.log"
PRODUCT = "ASH_COATED_OSMIUM"
ANCHOR = 10000.0


def main():
    with open(LOG) as f:
        d = json.load(f)
    prices = pd.read_csv(StringIO(d["activitiesLog"]), sep=";")
    p = prices[prices["product"] == PRODUCT].copy().sort_values("timestamp").reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    p["mid"] = p["mid_price"]
    p["dev"] = p["mid"] - ANCHOR
    p["ret"] = p["mid"].diff()
    p["abs_ret"] = p["ret"].abs()

    # imbalance
    p["bv"] = p["bid_volume_1"].fillna(0)
    p["av"] = p["ask_volume_1"].fillna(0)
    p["imb"] = (p["bv"] - p["av"]) / (p["bv"] + p["av"]).replace(0, 1)

    trades = pd.DataFrame(d["tradeHistory"])
    t_all = trades[trades["symbol"] == PRODUCT].copy()
    ours = t_all[(t_all["buyer"] == "SUBMISSION") | (t_all["seller"] == "SUBMISSION")].copy()
    ours["side"] = ours["buyer"].apply(lambda b: "BUY" if b == "SUBMISSION" else "SELL")

    by_ts = p.set_index("timestamp")

    # Classify each fill aggressive vs passive
    rows = []
    for _, r in ours.iterrows():
        ts = int(r["timestamp"])
        if ts not in by_ts.index:
            continue
        row = by_ts.loc[ts]
        bb = row["bid_price_1"]
        aa = row["ask_price_1"]
        if pd.isna(bb) or pd.isna(aa):
            continue
        px = float(r["price"])
        side = r["side"]
        if (side == "BUY" and px >= aa) or (side == "SELL" and px <= bb):
            kind = "AGG"
        else:
            kind = "PAS"
        signed_dev = -row["dev"] if side == "BUY" else row["dev"]
        signed_imb = row["imb"] if side == "BUY" else -row["imb"]
        rows.append({
            "ts": ts, "kind": kind, "side": side,
            "spread": row["spread"], "dev": row["dev"], "signed_dev": signed_dev,
            "bv": row["bv"], "av": row["av"], "imb": row["imb"], "signed_imb": signed_imb,
            "abs_ret": row["abs_ret"],
        })
    df = pd.DataFrame(rows)
    agg = df[df["kind"] == "AGG"]
    pas = df[df["kind"] == "PAS"]

    base = p.dropna(subset=["spread", "dev"]).copy()

    def q(s, qs=(.1, .5, .9)):
        return " ".join(f"p{int(x*100)}={s.quantile(x):.1f}" for x in qs)

    print(f"passive fills: {len(pas)}   aggressive fills: {len(agg)}")
    print()
    print("--- spread ---")
    print(f"  passive : {q(pas['spread'])}")
    print(f"  aggr    : {q(agg['spread'])}")
    print(f"  base    : {q(base['spread'])}")
    print()
    print("--- |dev| ---")
    print(f"  passive : {q(pas['dev'].abs())}")
    print(f"  aggr    : {q(agg['dev'].abs())}")
    print(f"  base    : {q(base['dev'].abs())}")
    print()
    print("--- signed_dev (favourable) ---")
    print(f"  passive : {q(pas['signed_dev'])}")
    print(f"  aggr    : {q(agg['signed_dev'])}")
    print()
    print("--- book imbalance (signed for fill side, positive=supporting) ---")
    print(f"  passive : {q(pas['signed_imb'])}")
    print(f"  aggr    : {q(agg['signed_imb'])}")
    print(f"  base    : {q(base['imb'])}")
    print()
    print("--- total top-of-book volume bv+av ---")
    pas_vol = pas['bv'] + pas['av']
    agg_vol = agg['bv'] + agg['av']
    base_vol = base['bv'].fillna(0) + base['av'].fillna(0)
    print(f"  passive : {q(pas_vol)}")
    print(f"  aggr    : {q(agg_vol)}")
    print(f"  base    : {q(base_vol)}")
    print()
    print("--- abs return at fill tick ---")
    print(f"  passive : {q(pas['abs_ret'].fillna(0))}")
    print(f"  aggr    : {q(agg['abs_ret'].fillna(0))}")
    print(f"  base    : {q(base['abs_ret'].fillna(0).abs())}")


main()
