"""Cross-correlation IPR -> OSMIUM."""
import pandas as pd
import numpy as np

frames = {"ASH_COATED_OSMIUM": [], "INTARIAN_PEPPER_ROOT": []}
for d in [-2, -1, 0]:
    df = pd.read_csv(f"data/round_1/prices_round_1_day_{d}.csv", sep=";")
    for p in frames:
        sub = df[df["product"] == p][["timestamp"]].copy()
        sub["mid"] = (df[df["product"] == p]["bid_price_1"].values
                      + df[df["product"] == p]["ask_price_1"].values) / 2
        sub["day"] = d
        frames[p].append(sub)

osm = pd.concat(frames["ASH_COATED_OSMIUM"]).sort_values(["day", "timestamp"]).reset_index(drop=True)
ipr = pd.concat(frames["INTARIAN_PEPPER_ROOT"]).sort_values(["day", "timestamp"]).reset_index(drop=True)

m = osm.merge(ipr, on=["day", "timestamp"], suffixes=("_osm", "_ipr"))
m["ret_osm"] = m.groupby("day")["mid_osm"].diff()
m["ret_ipr"] = m.groupby("day")["mid_ipr"].diff()
m["dev_osm"] = m["mid_osm"] - 10000
m["dev_ipr"] = m["mid_ipr"] - m.groupby("day")["mid_ipr"].transform("first")

# IPR trends, OSMIUM mean-reverts. Check lagged effects.
for h in [1, 5, 20, 50, 100]:
    m[f"fwd_osm_{h}"] = m.groupby("day")["mid_osm"].shift(-h) - m["mid_osm"]

print("=== Lead-lag: does IPR lead OSMIUM? ===")
print("feature         -> fwd_osm_h")
print(f"{'feature':<18} " + " ".join(f"h={h:<4}" for h in [1, 5, 20, 50, 100]))

features = {
    "ret_ipr (t)": m["ret_ipr"],
    "ret_ipr_l5 (sum 5)": m.groupby("day")["ret_ipr"].rolling(5).sum().reset_index(level=0, drop=True),
    "ret_ipr_l20 (sum 20)": m.groupby("day")["ret_ipr"].rolling(20).sum().reset_index(level=0, drop=True),
    "dev_ipr": m["dev_ipr"],
    "ret_ipr_l100 (sum 100)": m.groupby("day")["ret_ipr"].rolling(100).sum().reset_index(level=0, drop=True),
}
for name, feat in features.items():
    row = [f"{name:<18}"]
    for h in [1, 5, 20, 50, 100]:
        s = pd.DataFrame({"f": feat, "y": m[f"fwd_osm_{h}"]}).dropna()
        c = s["f"].corr(s["y"]) if len(s) > 10 else np.nan
        row.append(f"{c:+.3f}" if not np.isnan(c) else "nan   ")
    print(" ".join(row))

print("\n=== Contemporaneous corr ret_ipr vs ret_osm ===")
s = m.dropna(subset=["ret_ipr", "ret_osm"])
print(f"  N={len(s)}  corr={s['ret_ipr'].corr(s['ret_osm']):+.4f}")

print("\n=== Lead-lag scan ret_ipr (t-k) -> ret_osm (t) ===")
for k in [-10, -5, -2, -1, 0, 1, 2, 5, 10]:
    sh = m.groupby("day")["ret_ipr"].shift(k)
    s = pd.DataFrame({"f": sh, "y": m["ret_osm"]}).dropna()
    c = s["f"].corr(s["y"])
    print(f"  k={k:+3d}  corr={c:+.4f}  N={len(s)}")
