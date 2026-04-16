"""Tail reversion analysis: does E[reversion] exceed half-spread in extreme dev buckets?"""
import pandas as pd
import numpy as np

days = [-2, -1, 0]
frames = []
for d in days:
    df = pd.read_csv(f"data/round_1/prices_round_1_day_{d}.csv", sep=";")
    df = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
    df["day"] = d
    frames.append(df)
df = pd.concat(frames, ignore_index=True).sort_values(["day", "timestamp"]).reset_index(drop=True)

df["mid"] = (df["bid_price_1"] + df["ask_price_1"]) / 2
df["dev"] = df["mid"] - 10000
df["abs_dev"] = df["dev"].abs()
df["half_spread"] = (df["ask_price_1"] - df["bid_price_1"]) / 2

for h in [5, 20, 50, 100, 200, 500]:
    df[f"fwd_{h}"] = df.groupby("day")["mid"].shift(-h) - df["mid"]

# Signed reversion: positive means price moved back toward 10000
df["rev_20"] = -np.sign(df["dev"]) * df["fwd_20"]
df["rev_100"] = -np.sign(df["dev"]) * df["fwd_100"]
df["rev_200"] = -np.sign(df["dev"]) * df["fwd_200"]
df["rev_500"] = -np.sign(df["dev"]) * df["fwd_500"]

buckets = [0, 2, 5, 10, 20, 35, 50, 100, 1e9]
labels = ["0-2", "2-5", "5-10", "10-20", "20-35", "35-50", "50-100", "100+"]
df["bucket"] = pd.cut(df["abs_dev"], bins=buckets, labels=labels)

print("=== E[signed reversion | |dev| bucket] — target: exceed half_spread ~8 ===")
print(f"{'bucket':<10} {'N':<8} {'half_sp':<8} {'rev_20':<9} {'rev_100':<9} {'rev_200':<9} {'rev_500':<9}")
for b in labels:
    sub = df[df["bucket"] == b]
    if len(sub) < 20:
        continue
    hs = sub["half_spread"].mean()
    r20 = sub["rev_20"].mean()
    r100 = sub["rev_100"].mean()
    r200 = sub["rev_200"].mean()
    r500 = sub["rev_500"].mean()
    print(f"{b:<10} {len(sub):<8} {hs:<8.2f} {r20:<+9.2f} {r100:<+9.2f} {r200:<+9.2f} {r500:<+9.2f}")

print("\n=== Edge = rev - half_spread (positive = taker profitable) ===")
print(f"{'bucket':<10} {'rev_100_edge':<14} {'rev_200_edge':<14} {'rev_500_edge':<14}")
for b in labels:
    sub = df[df["bucket"] == b]
    if len(sub) < 20:
        continue
    hs = sub["half_spread"].mean()
    print(f"{b:<10} {sub['rev_100'].mean() - hs:<+14.2f} {sub['rev_200'].mean() - hs:<+14.2f} {sub['rev_500'].mean() - hs:<+14.2f}")

print("\n=== Hit rate: P(signed reversion > 0) in bucket ===")
for b in labels:
    sub = df[df["bucket"] == b]
    if len(sub) < 20:
        continue
    p100 = (sub["rev_100"] > 0).mean()
    p200 = (sub["rev_200"] > 0).mean()
    print(f"  {b:<10} N={len(sub):<6} P(rev100>0)={p100:.2f}  P(rev200>0)={p200:.2f}")
