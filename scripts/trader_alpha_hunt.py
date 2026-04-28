"""Trader alpha hunt — find informed traders + cross-asset signals.

For each trader (Mark XX), in R4 historical 3-day data:
  1. Per-product net flow + total volume
  2. Implied PnL: did they BUY before price went UP? SELL before DOWN?
  3. Cross-asset: when trader X trades hydrogel/options, what happens to other products?
  4. Specifically: who SELLS our problematic options on Day 3 (when we lose)?
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
DATA = ROOT / "data" / "round_4"


def load_day(d):
    trades = pd.read_csv(DATA / f"trades_round_4_day_{d}.csv", sep=";")
    prices = pd.read_csv(DATA / f"prices_round_4_day_{d}.csv", sep=";")
    trades["day"] = d
    prices["day"] = d
    return trades, prices


def main():
    dfs = [load_day(d) for d in [1, 2, 3]]
    trades_all = pd.concat([t for t, _ in dfs], ignore_index=True)
    prices_all = pd.concat([p for _, p in dfs], ignore_index=True)

    print(f"Total trades: {len(trades_all):,}")
    print(f"Symbols: {sorted(trades_all['symbol'].unique())}")
    traders_set = set(trades_all["buyer"].dropna().unique()) | set(trades_all["seller"].dropna().unique())
    print(f"Traders: {sorted(traders_set)}")
    print()

    prices_all["mid"] = (prices_all["bid_price_1"].fillna(0) + prices_all["ask_price_1"].fillna(0)) / 2

    # Build mid series per (day, symbol) for fast lookup
    mid_series = {}
    for (day, sym), grp in prices_all.groupby(["day", "product"]):
        grp = grp.sort_values("timestamp").reset_index(drop=True)
        mid_series[(day, sym)] = (grp["timestamp"].values, grp["mid"].values)

    def future_mid(day, ts, sym, horizon=5000):
        key = (day, sym)
        if key not in mid_series:
            return None
        ts_arr, mid_arr = mid_series[key]
        target = ts + horizon
        idx = int(np.searchsorted(ts_arr, target))
        if idx >= len(ts_arr):
            idx = len(ts_arr) - 1
        v = mid_arr[idx]
        return float(v) if not np.isnan(v) else None

    # === ANALYSIS 1: Per-trader implied PnL (informed score) ===
    print("=" * 100)
    print("ANALYSIS 1 -- Per-trader IMPLIED PnL (50-tick = 5000 ts horizon)")
    print("Positive PnL/trade  => trader is INFORMED (anticipates moves)")
    print("Negative PnL/trade  => trader is NOISE/LOSES (gets run over)")
    print("=" * 100)

    trader_pnl = {}
    for _, row in trades_all.iterrows():
        day, ts, sym = row["day"], row["timestamp"], row["symbol"]
        price, qty = row["price"], row["quantity"]
        fm = future_mid(day, ts, sym, horizon=5000)
        if fm is None or np.isnan(fm):
            continue
        pnl_per_unit = fm - price
        for trader, sign in [(row["buyer"], +1), (row["seller"], -1)]:
            if pd.isna(trader) or not trader:
                continue
            key = (trader, sym)
            if key not in trader_pnl:
                trader_pnl[key] = {"pnl": 0.0, "vol": 0, "n": 0}
            trader_pnl[key]["pnl"] += sign * qty * pnl_per_unit
            trader_pnl[key]["vol"] += qty
            trader_pnl[key]["n"] += 1

    per_trader_total = {}
    for (trader, sym), v in trader_pnl.items():
        if trader not in per_trader_total:
            per_trader_total[trader] = {"pnl": 0.0, "vol": 0, "n": 0}
        per_trader_total[trader]["pnl"] += v["pnl"]
        per_trader_total[trader]["vol"] += v["vol"]
        per_trader_total[trader]["n"] += v["n"]

    print()
    print(f"{'Trader':>15s}  {'Implied PnL':>13s}  {'PnL/trade':>10s}  {'Volume':>10s}  {'N trades':>10s}  Type")
    print("-" * 100)
    sorted_traders = sorted(per_trader_total.items(), key=lambda x: x[1]["pnl"], reverse=True)
    for trader, v in sorted_traders:
        if v["n"] < 50:
            continue
        avg = v["pnl"] / v["n"]
        if avg > 1.5:
            typ = "INFORMED++++ (top)"
        elif avg > 0.5:
            typ = "INFORMED+    (good)"
        elif abs(avg) <= 0.5:
            typ = "NOISE        (random)"
        elif avg > -1.5:
            typ = "ANTI-INFO-   (loses)"
        else:
            typ = "ANTI-INFO--- (BAD)"
        print(f"{trader:>15s}  {v['pnl']:>+13,.0f}  {avg:>+10.2f}  {v['vol']:>10,d}  {v['n']:>10d}  {typ}")

    # === ANALYSIS 2: Per-trader on OPTIONS only ===
    print()
    print("=" * 100)
    print("ANALYSIS 2 -- Per-trader implied PnL on OPTIONS ONLY")
    print("=" * 100)
    options = [s for s in trades_all["symbol"].unique() if s.startswith("VEV_")]
    print(f"Options: {sorted(options)}")
    print()
    print(f"{'Trader':>15s}  {'Opt Implied PnL':>16s}  {'PnL/trade':>10s}  {'Vol':>8s}  {'N':>6s}  Direction")
    print("-" * 100)
    opt_per_trader = {}
    opt_net_flow = {}
    for (trader, sym), v in trader_pnl.items():
        if not sym.startswith("VEV_"):
            continue
        if trader not in opt_per_trader:
            opt_per_trader[trader] = {"pnl": 0.0, "vol": 0, "n": 0}
        opt_per_trader[trader]["pnl"] += v["pnl"]
        opt_per_trader[trader]["vol"] += v["vol"]
        opt_per_trader[trader]["n"] += v["n"]
    # Net flow per trader on options
    for _, row in trades_all[trades_all["symbol"].isin(options)].iterrows():
        for tr, sign in [(row["buyer"], +1), (row["seller"], -1)]:
            if pd.isna(tr) or not tr:
                continue
            opt_net_flow[tr] = opt_net_flow.get(tr, 0) + sign * row["quantity"]
    sorted_opt = sorted(opt_per_trader.items(), key=lambda x: x[1]["pnl"], reverse=True)
    for trader, v in sorted_opt:
        if v["n"] < 30:
            continue
        avg = v["pnl"] / v["n"]
        nf = opt_net_flow.get(trader, 0)
        direction = "NET LONG  +" if nf > 50 else ("NET SHORT -" if nf < -50 else "balanced  =")
        print(f"{trader:>15s}  {v['pnl']:>+16,.0f}  {avg:>+10.2f}  {v['vol']:>8,d}  {v['n']:>6d}  {direction} ({nf:+,d})")

    # === ANALYSIS 3: WHO is on the OTHER side of OUR (Mark 49 fade etc) trades ===
    print()
    print("=" * 100)
    print("ANALYSIS 3 -- OPTIONS net flow MATRIX per trader (3-day total)")
    print("Positive = trader is NET BUYER, Negative = NET SELLER")
    print("=" * 100)
    flow_matrix = {}
    for _, row in trades_all[trades_all["symbol"].isin(options)].iterrows():
        sym = row["symbol"]
        for tr, sign in [(row["buyer"], +1), (row["seller"], -1)]:
            if pd.isna(tr) or not tr:
                continue
            flow_matrix[(tr, sym)] = flow_matrix.get((tr, sym), 0) + sign * row["quantity"]

    opt_sorted = sorted(options)
    all_tr = sorted(set(t for t, _ in flow_matrix.keys()))
    print(f"\n{'Trader':>14s}  ", end="")
    for o in opt_sorted:
        print(f"{o[-4:]:>7s}  ", end="")
    print(f"{'TOTAL':>8s}")
    print("-" * (14 + len(opt_sorted) * 9 + 10))
    for tr in all_tr:
        print(f"{tr:>14s}  ", end="")
        total = 0
        for o in opt_sorted:
            v = flow_matrix.get((tr, o), 0)
            total += v
            if v == 0:
                print(f"{'.':>7s}  ", end="")
            else:
                print(f"{v:>+7d}  ", end="")
        print(f"{total:>+8d}")

    # === ANALYSIS 4: Day 3 specifically (the bad day) ===
    print()
    print("=" * 100)
    print("ANALYSIS 4 -- DAY 3 OPTIONS flow (where we lose)")
    print("=" * 100)
    d3_options = trades_all[(trades_all["day"] == 3) & (trades_all["symbol"].isin(options))]
    print(f"Day 3 options trades: {len(d3_options):,}")
    flow_d3 = {}
    for _, row in d3_options.iterrows():
        sym = row["symbol"]
        for tr, sign in [(row["buyer"], +1), (row["seller"], -1)]:
            if pd.isna(tr) or not tr:
                continue
            flow_d3[(tr, sym)] = flow_d3.get((tr, sym), 0) + sign * row["quantity"]

    print(f"\n{'Trader':>14s}  ", end="")
    for o in opt_sorted:
        print(f"{o[-4:]:>7s}  ", end="")
    print(f"{'TOTAL':>8s}")
    for tr in all_tr:
        if not any((tr, o) in flow_d3 for o in opt_sorted):
            continue
        print(f"{tr:>14s}  ", end="")
        total = 0
        for o in opt_sorted:
            v = flow_d3.get((tr, o), 0)
            total += v
            if v == 0:
                print(f"{'.':>7s}  ", end="")
            else:
                print(f"{v:>+7d}  ", end="")
        print(f"{total:>+8d}")

    # === ANALYSIS 5: Cross-asset signals ===
    print()
    print("=" * 100)
    print("ANALYSIS 5 -- Cross-asset: trader flow on X predicts Y's 50-tick return?")
    print("Top |corr| = trader trades X gives signal on Y. Use to trade Y.")
    print("=" * 100)

    relevant_targets = ["VELVETFRUIT_EXTRACT", "VEV_5100", "VEV_5200", "VEV_4500"]
    sources = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_5200", "VEV_5100", "VEV_4500"]

    def build_flow_series(trader, sym):
        flows = {}
        sub = trades_all[(trades_all["symbol"] == sym) & ((trades_all["buyer"] == trader) | (trades_all["seller"] == trader))]
        for _, row in sub.iterrows():
            day, ts = row["day"], row["timestamp"]
            sign = +1 if row["buyer"] == trader else -1
            flows[(day, ts)] = flows.get((day, ts), 0) + sign * row["quantity"]
        return flows

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

    top_traders_by_vol = sorted(per_trader_total.keys(), key=lambda t: per_trader_total[t]["vol"], reverse=True)[:8]
    print()
    print(f"{'Trader':>14s}  {'Source flow':>22s}  {'Target return':>20s}  {'corr':>8s}  {'N pts':>6s}")
    print("-" * 100)

    rets_cache = {tgt: returns_50(tgt) for tgt in relevant_targets}
    findings = []
    for tr in top_traders_by_vol:
        for src in sources:
            flows = build_flow_series(tr, src)
            if len(flows) < 30:
                continue
            for tgt in relevant_targets:
                if tgt == src:
                    continue
                rets = rets_cache[tgt]
                common = sorted(set(flows.keys()) & set(rets.keys()))
                if len(common) < 30:
                    continue
                f_arr = np.array([flows[k] for k in common])
                r_arr = np.array([rets[k] for k in common])
                if f_arr.std() == 0 or r_arr.std() == 0:
                    continue
                corr = float(np.corrcoef(f_arr, r_arr)[0, 1])
                findings.append((abs(corr), corr, tr, src, tgt, len(common)))

    findings.sort(reverse=True)
    for _, corr, tr, src, tgt, n in findings[:25]:
        marker = "  <<< STRONG" if abs(corr) > 0.15 else ""
        print(f"{tr:>14s}  {src:>22s}  {tgt:>20s}  {corr:>+8.3f}  {n:>6d}{marker}")


if __name__ == "__main__":
    main()
