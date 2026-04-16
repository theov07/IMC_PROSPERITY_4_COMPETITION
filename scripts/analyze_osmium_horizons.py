"""Multi-horizon dev-from-10000 + AR(2) analysis for OSMIUM."""
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
df["ret"] = df["mid"].diff()

horizons = [1, 5, 10, 20, 50, 100, 200]
for h in horizons:
    df[f"fwd_{h}"] = df["mid"].shift(-h) - df["mid"]

print("=== corr(dev_from_10000, fwd_return_h) ===")
for h in horizons:
    sub = df.dropna(subset=["dev", f"fwd_{h}"])
    c = sub["dev"].corr(sub[f"fwd_{h}"])
    print(f"  h={h:4d}  N={len(sub):6d}  corr={c:+.4f}")

print("\n=== E[fwd_20 | |dev| bucket] ===")
df["abs_dev"] = df["dev"].abs()
buckets = [0, 2, 5, 10, 20, 50, 1e9]
labels = ["0-2", "2-5", "5-10", "10-20", "20-50", "50+"]
df["dev_bucket"] = pd.cut(df["abs_dev"], bins=buckets, labels=labels)
for h in [5, 20, 50, 100]:
    print(f"\n  horizon={h}")
    sub = df.dropna(subset=[f"fwd_{h}", "dev_bucket"])
    # signed: fwd in direction of reversion = -sign(dev)*fwd
    sub = sub.copy()
    sub["rev"] = -np.sign(sub["dev"]) * sub[f"fwd_{h}"]
    g = sub.groupby("dev_bucket", observed=True)["rev"].agg(["mean", "count"])
    print(g.to_string())

print("\n=== AR(2): ret_{t+1} = a*ret_t + b*ret_{t-1} + c ===")
df["ret_l1"] = df["ret"].shift(1)
df["ret_next"] = df["ret"].shift(-1)
sub = df.dropna(subset=["ret", "ret_l1", "ret_next"])
X = np.column_stack([sub["ret"], sub["ret_l1"], np.ones(len(sub))])
y = sub["ret_next"].values
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
pred = X @ coef
ss_res = ((y - pred) ** 2).sum()
ss_tot = ((y - y.mean()) ** 2).sum()
r2 = 1 - ss_res / ss_tot
print(f"  N={len(sub)}  a(ret_t)={coef[0]:+.4f}  b(ret_t-1)={coef[1]:+.4f}  c={coef[2]:+.4f}  R2={r2:.4f}")

# AR(1) baseline
X1 = np.column_stack([sub["ret"], np.ones(len(sub))])
c1, *_ = np.linalg.lstsq(X1, y, rcond=None)
p1 = X1 @ c1
r2_1 = 1 - ((y - p1) ** 2).sum() / ss_tot
print(f"  AR(1):            a={c1[0]:+.4f}  c={c1[1]:+.4f}  R2={r2_1:.4f}")
print(f"  AR(2) incremental R2: {r2 - r2_1:+.5f}")
