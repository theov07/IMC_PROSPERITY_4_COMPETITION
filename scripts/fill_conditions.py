"""Extract the pre-fill conditions around each live fill.

For each SUBMISSION fill in the official log, log:
  spread, dev = mid - 10000, side volumes, recent opposite-side flow,
  time since last fill. Then compare distributions vs all non-fill ticks.
Goal: derive data-driven thresholds for a v13 "sniper" strategy that
quotes only when these conditions match.
"""
from __future__ import annotations

import json
from io import StringIO
from statistics import median, quantiles

import pandas as pd

LOGS = [
    "logs/round_1/leo/best_osmium_log/170620.log",
    "logs/round_1/leo/drawndown_reduit/176188.log",
]
PRODUCT = "ASH_COATED_OSMIUM"
ANCHOR = 10000.0
LOOKBACK = 5


def analyze(path: str):
    print(f"\n=== {path} ===")
    with open(path) as f:
        d = json.load(f)
    prices = pd.read_csv(StringIO(d["activitiesLog"]), sep=";")
    p = prices[prices["product"] == PRODUCT].copy().sort_values("timestamp").reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    p["mid"] = p["mid_price"]
    p["dev"] = p["mid"] - ANCHOR

    trades = pd.DataFrame(d["tradeHistory"])
    t_all = trades[trades["symbol"] == PRODUCT].copy()
    ours = t_all[(t_all["buyer"] == "SUBMISSION") | (t_all["seller"] == "SUBMISSION")].copy()
    ours["side"] = ours["buyer"].apply(lambda b: "BUY" if b == "SUBMISSION" else "SELL")

    # build per-tick index
    by_ts = p.set_index("timestamp")
    all_ts = sorted(by_ts.index)

    # map market (non-our) trades per ts
    mkt = t_all[(t_all["buyer"] != "SUBMISSION") & (t_all["seller"] != "SUBMISSION")].copy()
    mkt_by_ts = mkt.groupby("timestamp").agg(qty=("quantity", "sum")).to_dict()["qty"]

    # for each fill, record context at ts (and LOOKBACK before)
    rows = []
    for _, r in ours.iterrows():
        ts = int(r["timestamp"])
        if ts not in by_ts.index:
            continue
        row = by_ts.loc[ts]
        rows.append({
            "ts": ts,
            "side": r["side"],
            "price": float(r["price"]),
            "qty": int(r["quantity"]),
            "spread": float(row["spread"]) if pd.notna(row["spread"]) else None,
            "mid": float(row["mid"]),
            "dev": float(row["dev"]),
            "bid_vol": float(row.get("bid_volume_1", 0) or 0),
            "ask_vol": float(row.get("ask_volume_1", 0) or 0),
        })
    df = pd.DataFrame(rows).dropna(subset=["spread"])
    df["signed_dev"] = df.apply(lambda r: -r["dev"] if r["side"] == "BUY" else r["dev"], axis=1)

    # baseline: all ticks
    base = p.dropna(subset=["spread", "dev"]).copy()
    print(f"all ticks: n={len(base)}  spread p50={base['spread'].median():.0f} p10={base['spread'].quantile(.1):.0f} p90={base['spread'].quantile(.9):.0f}")
    print(f"           |dev| p50={base['dev'].abs().median():.1f} p90={base['dev'].abs().quantile(.9):.1f}")
    print(f"fills    : n={len(df)}")
    print()
    print("--- spread distribution ---")
    print(f"fill ticks : p10={df['spread'].quantile(.1):.0f} p50={df['spread'].median():.0f} p90={df['spread'].quantile(.9):.0f}")
    print(f"all ticks  : p10={base['spread'].quantile(.1):.0f} p50={base['spread'].median():.0f} p90={base['spread'].quantile(.9):.0f}")
    print()
    print("--- |dev| at fill time ---")
    print(f"fill ticks : p10={df['dev'].abs().quantile(.1):.1f} p50={df['dev'].abs().median():.1f} p90={df['dev'].abs().quantile(.9):.1f}")
    print(f"all ticks  : p10={base['dev'].abs().quantile(.1):.1f} p50={base['dev'].abs().median():.1f} p90={base['dev'].abs().quantile(.9):.1f}")
    print()
    print("--- signed dev (favourable direction) ---")
    print(f"mean={df['signed_dev'].mean():+.2f} median={df['signed_dev'].median():+.1f} p10={df['signed_dev'].quantile(.1):+.1f} p90={df['signed_dev'].quantile(.9):+.1f}")
    print()

    # How often does (spread >= 10 AND signed_dev >= 4) fire at fill ticks vs all?
    for sp_min in [8, 10, 12]:
        for dev_min in [2, 4, 6]:
            fill_hits = ((df['spread'] >= sp_min) & (df['signed_dev'] >= dev_min)).sum()
            # on base, same-side logic needs direction; use either side
            base_hits_pos = ((base['spread'] >= sp_min) & (-base['dev'] >= dev_min)).sum()  # buy side
            base_hits_neg = ((base['spread'] >= sp_min) & (base['dev'] >= dev_min)).sum()   # sell side
            base_hits = base_hits_pos + base_hits_neg
            print(f"  spread>={sp_min}, signed_dev>={dev_min}: fills {fill_hits}/{len(df)} ({100*fill_hits/len(df):.0f}%)  base_ticks {base_hits}/{2*len(base)} ({100*base_hits/(2*len(base)):.1f}%)")


for log in LOGS:
    analyze(log)
