"""Deep book signal analysis on OSMIUM.

Tests orthogonal features beyond L1 imbalance:
 - I1, I2, I3: imbalance at levels 1, 2, 3
 - I_full: weighted multi-level imbalance
 - dI1: delta L1 imbalance (tick change)
 - dL2_bid_vol, dL2_ask_vol: L2 pressure change
 - L2_spread: gap from L1 to L2 (thin-book proxy)

Target: fwd_return at h in {1, 5, 20}.
"""
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

# Level imbalances
def imb(b, a):
    s = b + a
    return np.where(s > 0, (b - a) / s, 0.0)

df["I1"] = imb(df["bid_volume_1"].fillna(0), df["ask_volume_1"].fillna(0))
df["I2"] = imb(df["bid_volume_2"].fillna(0), df["ask_volume_2"].fillna(0))
df["I3"] = imb(df["bid_volume_3"].fillna(0), df["ask_volume_3"].fillna(0))

# Multi-level with decay weights (top gets more weight)
bv_all = df["bid_volume_1"].fillna(0) + 0.5 * df["bid_volume_2"].fillna(0) + 0.25 * df["bid_volume_3"].fillna(0)
av_all = df["ask_volume_1"].fillna(0) + 0.5 * df["ask_volume_2"].fillna(0) + 0.25 * df["ask_volume_3"].fillna(0)
df["I_full"] = imb(bv_all, av_all)

# Delta imbalance
df["dI1"] = df.groupby("day")["I1"].diff()
df["dI_full"] = df.groupby("day")["I_full"].diff()

# L2 gap from L1 (thin book signal)
df["L2_bid_gap"] = df["bid_price_1"] - df["bid_price_2"].fillna(df["bid_price_1"])
df["L2_ask_gap"] = df["ask_price_2"].fillna(df["ask_price_1"]) - df["ask_price_1"]

# Depth asymmetry (L2+L3 - L1)
df["deep_b"] = df["bid_volume_2"].fillna(0) + df["bid_volume_3"].fillna(0)
df["deep_a"] = df["ask_volume_2"].fillna(0) + df["ask_volume_3"].fillna(0)
df["deep_imb"] = imb(df["deep_b"], df["deep_a"])

# Targets
for h in [1, 5, 20, 100]:
    df[f"fwd_{h}"] = df.groupby("day")["mid"].shift(-h) - df["mid"]

features = ["I1", "I2", "I3", "I_full", "dI1", "dI_full",
            "L2_bid_gap", "L2_ask_gap", "deep_imb"]

print("=== corr(feature, fwd_return_h) ===")
print(f"{'feature':<12} " + " ".join(f"h={h:<4}" for h in [1, 5, 20, 100]))
for f in features:
    row = [f"{f:<12}"]
    for h in [1, 5, 20, 100]:
        sub = df.dropna(subset=[f, f"fwd_{h}"])
        c = sub[f].corr(sub[f"fwd_{h}"])
        row.append(f"{c:+.3f}")
    print(" ".join(row))

# Compare to baseline: just ret_lag
df["ret"] = df["mid"].diff()
sub = df.dropna(subset=["ret", "fwd_1"])
print(f"\n  baseline ret_lag1 to fwd_1: {sub['ret'].corr(sub['fwd_1']):+.3f}")

# Check incremental R2 of combined model
print("\n=== OLS: fwd_1 ~ I1 + dI1 + I_full + deep_imb ===")
cols = ["I1", "I2", "I3", "L2_bid_gap", "L2_ask_gap"]
d = df.dropna(subset=cols + ["fwd_1"])
X = np.column_stack([d[c] for c in cols] + [np.ones(len(d))])
y = d["fwd_1"].values
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
pred = X @ coef
r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
print(f"  N={len(d)}  R2={r2:.4f}")
for c, k in zip(cols + ["const"], coef):
    print(f"    {c:<12} {k:+.4f}")

# Just I1 baseline
X1 = np.column_stack([d["I1"], np.ones(len(d))])
c1, *_ = np.linalg.lstsq(X1, y, rcond=None)
r2_1 = 1 - ((y - X1 @ c1) ** 2).sum() / ((y - y.mean()) ** 2).sum()
print(f"  I1-only R2={r2_1:.4f}  incremental = {r2 - r2_1:+.4f}")
