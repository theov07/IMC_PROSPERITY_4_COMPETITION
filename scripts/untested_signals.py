"""4 untested signals: microprice, signed trade flow, half-life, time-of-day."""
import pandas as pd
import numpy as np

days = [-2, -1, 0]
# Prices
pframes = []
for d in days:
    df = pd.read_csv(f"data/round_1/prices_round_1_day_{d}.csv", sep=";")
    df = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
    df["day"] = d
    pframes.append(df)
prices = pd.concat(pframes).sort_values(["day", "timestamp"]).reset_index(drop=True)
prices["mid"] = (prices["bid_price_1"] + prices["ask_price_1"]) / 2

# Trades (market trades)
tframes = []
for d in days:
    tr = pd.read_csv(f"data/round_1/trades_round_1_day_{d}.csv", sep=";")
    tr = tr[tr["symbol"] == "ASH_COATED_OSMIUM"].copy()
    tr["day"] = d
    tframes.append(tr)
trades = pd.concat(tframes).sort_values(["day", "timestamp"]).reset_index(drop=True)

# ==========================================================================
# 1. MICROPRICE deviation
# ==========================================================================
print("=" * 60)
print("1. MICROPRICE DEVIATION")
print("=" * 60)
bv = prices["bid_volume_1"].fillna(0)
av = prices["ask_volume_1"].fillna(0)
tot = bv + av
prices["microprice"] = np.where(tot > 0,
    (prices["bid_price_1"] * av + prices["ask_price_1"] * bv) / tot,
    prices["mid"])
prices["micro_dev"] = prices["microprice"] - prices["mid"]
for h in [1, 5, 20, 100]:
    prices[f"fwd_{h}"] = prices.groupby("day")["mid"].shift(-h) - prices["mid"]
print(f"{'h':<6} {'N':<8} {'corr(micro_dev, fwd_h)':<25}")
for h in [1, 5, 20, 100]:
    sub = prices.dropna(subset=["micro_dev", f"fwd_{h}"])
    c = sub["micro_dev"].corr(sub[f"fwd_{h}"])
    print(f"{h:<6} {len(sub):<8} {c:+.4f}")

# vs I1 (already tested)
bv2 = prices["bid_volume_1"].fillna(0)
av2 = prices["ask_volume_1"].fillna(0)
prices["I1"] = np.where(bv2 + av2 > 0, (bv2 - av2) / (bv2 + av2), 0)
# incremental R2
d = prices.dropna(subset=["micro_dev", "I1", "fwd_1"])
X1 = np.column_stack([d["I1"], np.ones(len(d))])
y = d["fwd_1"].values
c1, *_ = np.linalg.lstsq(X1, y, rcond=None)
r2_1 = 1 - ((y - X1 @ c1) ** 2).sum() / ((y - y.mean()) ** 2).sum()
Xm = np.column_stack([d["I1"], d["micro_dev"], np.ones(len(d))])
cm, *_ = np.linalg.lstsq(Xm, y, rcond=None)
r2_m = 1 - ((y - Xm @ cm) ** 2).sum() / ((y - y.mean()) ** 2).sum()
print(f"\nR2 I1-only={r2_1:.4f}  +microprice={r2_m:.4f}  incremental={r2_m-r2_1:+.4f}")

# ==========================================================================
# 2. SIGNED TRADE FLOW (lag 1)
# ==========================================================================
print("\n" + "=" * 60)
print("2. SIGNED TRADE FLOW")
print("=" * 60)
# Classify each trade: aggressor side based on whether price >= current ask (buy aggressor) or <= current bid (sell aggressor)
# Join trades with prices at their tick
prices_idx = prices.set_index(["day", "timestamp"])[["bid_price_1", "ask_price_1"]]
trades_j = trades.join(prices_idx, on=["day", "timestamp"])
# Sign: +1 if at ask (buy aggressor), -1 if at bid, 0 if mid
trades_j["sign"] = 0
trades_j.loc[trades_j["price"] >= trades_j["ask_price_1"], "sign"] = 1
trades_j.loc[trades_j["price"] <= trades_j["bid_price_1"], "sign"] = -1
trades_j["signed_qty"] = trades_j["sign"] * trades_j["quantity"]
flow = trades_j.groupby(["day", "timestamp"])["signed_qty"].sum().reset_index()
flow = flow.rename(columns={"signed_qty": "flow"})
prices_f = prices.merge(flow, on=["day", "timestamp"], how="left")
prices_f["flow"] = prices_f["flow"].fillna(0)
# Rolling flow
prices_f["flow_5"] = prices_f.groupby("day")["flow"].rolling(5, min_periods=1).sum().reset_index(level=0, drop=True)
prices_f["flow_20"] = prices_f.groupby("day")["flow"].rolling(20, min_periods=1).sum().reset_index(level=0, drop=True)

for h in [1, 5, 20, 100]:
    prices_f[f"fwd_{h}"] = prices_f.groupby("day")["mid"].shift(-h) - prices_f["mid"]
print(f"{'feature':<12} " + " ".join(f"h={h:<4}" for h in [1, 5, 20, 100]))
for f in ["flow", "flow_5", "flow_20"]:
    row = [f"{f:<12}"]
    for h in [1, 5, 20, 100]:
        s = prices_f.dropna(subset=[f, f"fwd_{h}"])
        c = s[f].corr(s[f"fwd_{h}"]) if len(s) > 10 else np.nan
        row.append(f"{c:+.3f}")
    print(" ".join(row))

# ==========================================================================
# 3. AR(1) HALF-LIFE on returns
# ==========================================================================
print("\n" + "=" * 60)
print("3. AR(1) HALF-LIFE ON RETURNS")
print("=" * 60)
prices["ret"] = prices.groupby("day")["mid"].diff()
prices["ret_l1"] = prices.groupby("day")["ret"].shift(1)
sub = prices.dropna(subset=["ret", "ret_l1"])
X = np.column_stack([sub["ret_l1"], np.ones(len(sub))])
y = sub["ret"].values
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
phi = coef[0]
print(f"  AR(1) coefficient phi = {phi:+.4f}")
if abs(phi) < 1:
    hl = np.log(0.5) / np.log(abs(phi))
    print(f"  Half-life = {hl:.2f} ticks")
else:
    print("  Non-stationary")

# ==========================================================================
# 4. TIME-OF-DAY edge
# ==========================================================================
print("\n" + "=" * 60)
print("4. TIME-OF-DAY: does PnL/edge vary by timestamp?")
print("=" * 60)
# Bucket by timestamp (10 buckets)
prices["ts_bucket"] = pd.cut(prices["timestamp"], 10, labels=False)
prices["abs_fwd20"] = prices.groupby("day")["mid"].shift(-20).sub(prices["mid"]).abs()
prices["spread"] = prices["ask_price_1"] - prices["bid_price_1"]
g = prices.groupby("ts_bucket").agg(
    n=("mid", "size"),
    abs_fwd20=("abs_fwd20", "mean"),
    spread=("spread", "mean"),
    ret_std=("ret", "std"),
)
print(g.to_string())
