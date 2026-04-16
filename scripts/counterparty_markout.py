"""Markout per counterparty on OSMIUM trades.

For each trade (buyer, seller, price, ts), compute the mid-price move
over horizons h ticks ahead. If a participant systematically buys before
the price rises and sells before it falls, they carry information.
"""
import pandas as pd
import numpy as np

days = [-2, -1, 0]
sym = "ASH_COATED_OSMIUM"

mids_list = []
trades_list = []
for d in days:
    pr = pd.read_csv(f"data/round_1/prices_round_1_day_{d}.csv", sep=";")
    pr = pr[pr["product"] == sym][["timestamp", "bid_price_1", "ask_price_1"]].copy()
    pr["mid"] = (pr["bid_price_1"] + pr["ask_price_1"]) / 2
    pr["day"] = d
    mids_list.append(pr[["day", "timestamp", "mid"]])

    tr = pd.read_csv(f"data/round_1/trades_round_1_day_{d}.csv", sep=";")
    tr = tr[tr["symbol"] == sym].copy()
    tr["day"] = d
    trades_list.append(tr)

mid = pd.concat(mids_list, ignore_index=True)
trades = pd.concat(trades_list, ignore_index=True)

# Map (day, ts) -> mid; forward-fill for horizons
mid = mid.sort_values(["day", "timestamp"]).reset_index(drop=True)
mid_lookup = {(r.day, r.timestamp): r.mid for r in mid.itertuples()}

horizons = [5, 20, 100]
for h in horizons:
    mid[f"mid_p{h}"] = mid.groupby("day")["mid"].shift(-h)
lookups = {h: {(r.day, r.timestamp): getattr(r, f"mid_p{h}") for r in mid.itertuples()} for h in horizons}

def get_mid_at(d, ts, h):
    return lookups[h].get((d, ts), np.nan)

# Markout per trade: (mid_{t+h} - price) * side_sign
# A known counterparty might buy informed: if they're buyer, their markout = mid - price.
rows = []
for t in trades.itertuples():
    m0 = mid_lookup.get((t.day, t.timestamp))
    if m0 is None:
        continue
    for h in horizons:
        mh = get_mid_at(t.day, t.timestamp, h)
        if pd.isna(mh):
            continue
        rows.append({"buyer": t.buyer or "?", "seller": t.seller or "?",
                     "h": h, "buyer_mkt": mh - t.price, "seller_mkt": t.price - mh,
                     "qty": t.quantity})

df = pd.DataFrame(rows)

print("=== TOP BUYERS by avg markout (positive = info advantage) ===")
for h in horizons:
    sub = df[df["h"] == h]
    g = sub.groupby("buyer").agg(n=("buyer_mkt", "size"), mk=("buyer_mkt", "mean"), qty=("qty", "sum"))
    g = g[g["n"] >= 50].sort_values("mk", ascending=False)
    print(f"\n  h={h}")
    print(g.head(10).to_string())

print("\n=== TOP SELLERS by avg markout ===")
for h in horizons:
    sub = df[df["h"] == h]
    g = sub.groupby("seller").agg(n=("seller_mkt", "size"), mk=("seller_mkt", "mean"), qty=("qty", "sum"))
    g = g[g["n"] >= 50].sort_values("mk", ascending=False)
    print(f"\n  h={h}")
    print(g.head(10).to_string())
