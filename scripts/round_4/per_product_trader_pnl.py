"""Per-(trader, product) implied PnL analysis.

For each (trader, product) pair, compute implied PnL on 50-tick horizon.
Show full matrix so we can pick per-product weights.

Output: artifacts/analysis/round_4/per_product_trader_pnl.csv
        + console table (sorted by absolute PnL/trade per product)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "round_4"
OUT_CSV = ROOT / "artifacts" / "analysis" / "round_4" / "per_product_trader_pnl.csv"


def main():
    dfs = []
    for d in [1, 2, 3]:
        trades = pd.read_csv(DATA / f"trades_round_4_day_{d}.csv", sep=";")
        prices = pd.read_csv(DATA / f"prices_round_4_day_{d}.csv", sep=";")
        trades["day"] = d
        prices["day"] = d
        dfs.append((trades, prices))
    trades_all = pd.concat([t for t, _ in dfs], ignore_index=True)
    prices_all = pd.concat([p for _, p in dfs], ignore_index=True)
    prices_all["mid"] = (prices_all["bid_price_1"].fillna(0) + prices_all["ask_price_1"].fillna(0)) / 2

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

    # Per (trader, sym, day): compute implied PnL on multiple horizons
    HORIZONS = [1000, 5000, 20000]  # 10t, 50t, 200t
    results = {}  # (trader, sym, horizon) -> {pnl, vol, n}

    for _, row in trades_all.iterrows():
        day, ts, sym = row["day"], row["timestamp"], row["symbol"]
        price, qty = row["price"], row["quantity"]
        for h in HORIZONS:
            fm = future_mid(day, ts, sym, horizon=h)
            if fm is None or np.isnan(fm):
                continue
            pnl_per_unit = fm - price
            for trader, sign in [(row["buyer"], +1), (row["seller"], -1)]:
                if pd.isna(trader) or not trader:
                    continue
                key = (trader, sym, h)
                if key not in results:
                    results[key] = {"pnl": 0.0, "vol": 0, "n": 0, "buy_qty": 0, "sell_qty": 0}
                results[key]["pnl"] += sign * qty * pnl_per_unit
                results[key]["vol"] += qty
                results[key]["n"] += 1
                if sign > 0:
                    results[key]["buy_qty"] += qty
                else:
                    results[key]["sell_qty"] += qty

    # Build flat dataframe
    rows = []
    for (trader, sym, h), v in results.items():
        if v["n"] < 10:
            continue
        rows.append({
            "trader": trader, "product": sym, "horizon": h,
            "pnl": round(v["pnl"], 1),
            "pnl_per_trade": round(v["pnl"] / v["n"], 3),
            "vol": v["vol"], "n_trades": v["n"],
            "buy_qty": v["buy_qty"], "sell_qty": v["sell_qty"],
            "net_flow": v["buy_qty"] - v["sell_qty"],
        })
    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"Saved {len(df)} rows to {OUT_CSV.name}")
    print()

    # Pretty print: per product, list traders with their 50-tick PnL/trade
    print("=" * 100)
    print("PER-PRODUCT TRADER SCORECARD (horizon=50 ticks = 5000 ts)")
    print("Sort by abs(PnL/trade): biggest signals first")
    print("=" * 100)

    products = sorted(df["product"].unique())
    for prod in products:
        sub = df[(df["product"] == prod) & (df["horizon"] == 5000)].copy()
        if len(sub) == 0:
            continue
        sub["abs_pnl_per_trade"] = sub["pnl_per_trade"].abs()
        sub = sub.sort_values("abs_pnl_per_trade", ascending=False)
        print(f"\n{prod}  ({sub['n_trades'].sum()} trades)")
        print(f"  {'Trader':>10s}  {'PnL/trade':>10s}  {'Tot PnL':>10s}  {'N':>5s}  {'BuyQ':>6s}  {'SellQ':>6s}  {'Type':<25s}  {'Suggested weight'}")
        for _, r in sub.iterrows():
            avg = r["pnl_per_trade"]
            if avg > 1.5:
                typ = "INFORMED++ (FOLLOW)"
                w = "+0.5"
            elif avg > 0.5:
                typ = "informed (follow)"
                w = "+0.3"
            elif avg > -0.5:
                typ = "noise (skip)"
                w = "0"
            elif avg > -1.5:
                typ = "ANTI-INFO (FADE)"
                w = "-0.3"
            else:
                typ = "ANTI-INFO-- (FADE HARD)"
                w = "-0.5"
            print(f"  {r['trader']:>10s}  {avg:>+10.2f}  {r['pnl']:>+10,.0f}  {r['n_trades']:>5d}  {r['buy_qty']:>6d}  {r['sell_qty']:>6d}  {typ:<25s}  {w}")

    # Special focus: VELVET only with all 3 horizons
    print()
    print("=" * 100)
    print("VELVETFRUIT_EXTRACT — same trader across HORIZONS (10t/50t/200t)")
    print("Are signals consistent across horizons?")
    print("=" * 100)
    velvet = df[df["product"] == "VELVETFRUIT_EXTRACT"].copy()
    pivot = velvet.pivot(index="trader", columns="horizon", values="pnl_per_trade").round(2)
    pivot.columns = [f"h={h//100}t" for h in pivot.columns]
    print(pivot.to_string())


if __name__ == "__main__":
    main()
