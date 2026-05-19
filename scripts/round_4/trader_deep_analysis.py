"""Deep trader analysis — answer all open questions WITHOUT running backtests.

Outputs:
  1. Trader sizes / conviction (mean qty per trade by trader & product)
  2. MM detection: 2-sided ratio (do they post both bid+ask?) → MM signature
  3. Per-day trader behavior (Day 1 vs 2 vs 3) → regime change?
  4. Trader-trader correlation (who follows whom?)
  5. Cross-asset trader flow → return predictions (extended)
  6. Bull/bear spread arbitrage opportunities (price relationships)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "round_4"


def load_all():
    dfs = []
    pdfs = []
    for d in [1, 2, 3]:
        t = pd.read_csv(DATA / f"trades_round_4_day_{d}.csv", sep=";")
        p = pd.read_csv(DATA / f"prices_round_4_day_{d}.csv", sep=";")
        t["day"] = d
        p["day"] = d
        dfs.append(t)
        pdfs.append(p)
    return pd.concat(dfs, ignore_index=True), pd.concat(pdfs, ignore_index=True)


def main():
    trades, prices = load_all()
    prices["mid"] = (prices["bid_price_1"].fillna(0) + prices["ask_price_1"].fillna(0)) / 2

    print("=" * 100)
    print("1. TRADER SIZES / CONVICTION (mean qty per trade)")
    print("=" * 100)
    print(f"\n{'Trader':>10s}  {'Product':>22s}  {'N trades':>10s}  {'Mean qty':>10s}  {'Max qty':>10s}  {'Std qty':>10s}  {'Conviction':<12s}")
    print("-" * 100)
    for trader in sorted(set(trades["buyer"].dropna()) | set(trades["seller"].dropna())):
        for prod in sorted(trades["symbol"].unique()):
            sub = trades[(trades["symbol"] == prod) & ((trades["buyer"] == trader) | (trades["seller"] == trader))]
            if len(sub) < 30:
                continue
            mean_q = sub["quantity"].mean()
            max_q = sub["quantity"].max()
            std_q = sub["quantity"].std()
            cv = std_q / mean_q if mean_q else 0  # coefficient of variation
            conv = "HIGH" if mean_q > 5 and cv < 0.5 else ("low" if mean_q < 2 else "med")
            if prod in ("VELVETFRUIT_EXTRACT", "HYDROGEL_PACK") or prod.startswith("VEV_5"):
                print(f"{trader:>10s}  {prod:>22s}  {len(sub):>10d}  {mean_q:>10.2f}  {max_q:>10d}  {std_q:>10.2f}  {conv:<12s}")

    print()
    print("=" * 100)
    print("2. MM SIGNATURE — 2-sided ratio (proportion of trades on each side)")
    print("=" * 100)
    print(f"\n{'Trader':>10s}  {'Product':>22s}  {'%Buy':>7s}  {'%Sell':>7s}  {'Balance':>10s}  {'Type'}")
    print("-" * 100)
    for trader in sorted(set(trades["buyer"].dropna()) | set(trades["seller"].dropna())):
        for prod in sorted(trades["symbol"].unique()):
            sub = trades[(trades["symbol"] == prod) & ((trades["buyer"] == trader) | (trades["seller"] == trader))]
            if len(sub) < 50:
                continue
            buys = (sub["buyer"] == trader).sum()
            sells = (sub["seller"] == trader).sum()
            total = buys + sells
            pct_buy = buys / total * 100
            pct_sell = sells / total * 100
            balance = abs(pct_buy - 50)
            if balance < 10:
                typ = "MM (2-sided)"
            elif pct_buy > 80:
                typ = "PURE BUYER"
            elif pct_sell > 80:
                typ = "PURE SELLER"
            else:
                typ = "biased"
            if prod in ("VELVETFRUIT_EXTRACT", "HYDROGEL_PACK") or prod.startswith("VEV_5"):
                print(f"{trader:>10s}  {prod:>22s}  {pct_buy:>7.1f}  {pct_sell:>7.1f}  {balance:>10.1f}  {typ}")

    print()
    print("=" * 100)
    print("3. PER-DAY TRADER BEHAVIOR (Day 1 vs 2 vs 3) — regime change?")
    print("=" * 100)
    print(f"\n{'Trader':>10s}  {'Product':>22s}  {'D1 net':>10s}  {'D2 net':>10s}  {'D3 net':>10s}  {'Day3 shift'}")
    print("-" * 100)
    for trader in sorted(set(trades["buyer"].dropna()) | set(trades["seller"].dropna())):
        for prod in ("VELVETFRUIT_EXTRACT", "VEV_5100", "VEV_5200", "VEV_4000", "HYDROGEL_PACK"):
            sub = trades[(trades["symbol"] == prod) & ((trades["buyer"] == trader) | (trades["seller"] == trader))]
            if len(sub) < 30:
                continue
            day_nets = []
            for d in [1, 2, 3]:
                d_sub = sub[sub["day"] == d]
                buys = d_sub[d_sub["buyer"] == trader]["quantity"].sum()
                sells = d_sub[d_sub["seller"] == trader]["quantity"].sum()
                day_nets.append(buys - sells)
            d3_shift = day_nets[2] - (day_nets[0] + day_nets[1]) / 2
            shift_marker = "<<< BIG" if abs(d3_shift) > 100 else ""
            print(f"{trader:>10s}  {prod:>22s}  {day_nets[0]:>+10d}  {day_nets[1]:>+10d}  {day_nets[2]:>+10d}  {d3_shift:>+10.0f} {shift_marker}")

    print()
    print("=" * 100)
    print("4. CROSS-ASSET CORRELATIONS — TRADER FLOW → 50-tick RETURN")
    print("=" * 100)
    print("Top |corr| signals (>0.10 with N>50 samples)")

    # Build mid_series for cross-asset
    mid_series = {}
    for (day, sym), grp in prices.groupby(["day", "product"]):
        grp = grp.sort_values("timestamp").reset_index(drop=True)
        mid_series[(day, sym)] = (grp["timestamp"].values, grp["mid"].values)

    def returns_50(target):
        out = {}
        for (day, sym), (ts_arr, mid_arr) in mid_series.items():
            if sym != target:
                continue
            for i, ts in enumerate(ts_arr):
                if i + 50 >= len(ts_arr):
                    break
                r = mid_arr[i + 50] - mid_arr[i]
                if not np.isnan(r):
                    out[(day, int(ts))] = float(r)
        return out

    def trader_flow_series(trader, sym):
        flows = {}
        sub = trades[(trades["symbol"] == sym) & ((trades["buyer"] == trader) | (trades["seller"] == trader))]
        for _, row in sub.iterrows():
            day, ts = row["day"], row["timestamp"]
            sign = +1 if row["buyer"] == trader else -1
            flows[(day, int(ts))] = flows.get((day, int(ts)), 0) + sign * row["quantity"]
        return flows

    relevant_targets = ["VELVETFRUIT_EXTRACT", "VEV_5100", "VEV_5200", "VEV_4500"]
    sources = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_5200", "VEV_5100"]
    rets_cache = {tgt: returns_50(tgt) for tgt in relevant_targets}

    findings = []
    traders = ["Mark 01", "Mark 14", "Mark 22", "Mark 38", "Mark 49", "Mark 55", "Mark 67"]
    for tr in traders:
        for src in sources:
            flows = trader_flow_series(tr, src)
            if len(flows) < 50:
                continue
            for tgt in relevant_targets:
                if tgt == src:
                    continue
                rets = rets_cache[tgt]
                common = sorted(set(flows.keys()) & set(rets.keys()))
                if len(common) < 50:
                    continue
                f_arr = np.array([flows[k] for k in common])
                r_arr = np.array([rets[k] for k in common])
                if f_arr.std() == 0 or r_arr.std() == 0:
                    continue
                corr = float(np.corrcoef(f_arr, r_arr)[0, 1])
                findings.append((abs(corr), corr, tr, src, tgt, len(common)))

    findings.sort(reverse=True)
    print(f"\n{'Trader':>10s}  {'Source':>22s}  {'Target':>20s}  {'Corr':>8s}  {'N':>6s}")
    for _, corr, tr, src, tgt, n in findings[:15]:
        marker = "  <<< STRONG" if abs(corr) > 0.10 else ""
        print(f"{tr:>10s}  {src:>22s}  {tgt:>20s}  {corr:>+8.3f}  {n:>6d}{marker}")

    # 5. Bull/bear spread opportunities
    print()
    print("=" * 100)
    print("5. SPREAD OPPORTUNITIES — option price relationships")
    print("=" * 100)
    options = sorted([p for p in prices["product"].unique() if p.startswith("VEV_")])
    velvet_mid = prices[prices["product"] == "VELVETFRUIT_EXTRACT"].set_index(["day", "timestamp"])["mid"]
    print(f"\n{'Option':>10s}  {'Strike':>7s}  {'Mean mid':>10s}  {'Min':>10s}  {'Max':>10s}  {'Mid std':>10s}  {'Theoretical (intrinsic)':<25s}")
    for opt in options:
        if opt == "VEV_5500":
            print()  # break
        strike = int(opt.split("_")[1])
        sub = prices[prices["product"] == opt]
        sub = sub[sub["mid"] > 0]
        if len(sub) == 0:
            print(f"{opt:>10s}  {strike:>7d}  {'-':>10s}")
            continue
        # Theoretical intrinsic = max(0, spot - strike)
        spot_at = velvet_mid.reindex(sub.set_index(["day", "timestamp"]).index)
        intrinsic = (spot_at - strike).clip(lower=0).mean()
        print(f"{opt:>10s}  {strike:>7d}  {sub['mid'].mean():>10.2f}  {sub['mid'].min():>10.2f}  {sub['mid'].max():>10.2f}  {sub['mid'].std():>10.2f}  ~{intrinsic:.1f}")


if __name__ == "__main__":
    main()
