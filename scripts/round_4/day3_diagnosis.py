"""Day 3 diagnosis."""
from __future__ import annotations
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "round_4"


def main():
    prices = pd.read_csv(DATA / "prices_round_4_day_3.csv", sep=";")
    products = sorted(prices["product"].unique())
    print("DAY 3 PRICE DRIFT (start vs end)")
    print(f"{'Product':>22s}  {'Start':>10s}  {'End':>10s}  {'Drift':>10s}  {'%':>8s}  {'Max':>10s}  {'Min':>10s}")
    for p in products:
        sub = prices[prices["product"] == p].sort_values("timestamp").copy()
        sub["mid"] = (sub["bid_price_1"].fillna(0) + sub["ask_price_1"].fillna(0)) / 2
        sub = sub[sub["mid"] > 0]
        if len(sub) == 0:
            continue
        s, e, m, mi = sub.iloc[0]["mid"], sub.iloc[-1]["mid"], sub["mid"].max(), sub["mid"].min()
        pct = (e - s) / s * 100 if s else 0
        print(f"{p:>22s}  {s:>10.2f}  {e:>10.2f}  {e-s:>+10.2f}  {pct:>+7.2f}%  {m:>10.2f}  {mi:>10.2f}")

    print()
    print("INTRA-DAY DRIFT — options (4 quartiles of Day 3)")
    options = [p for p in products if p.startswith("VEV_")]
    print(f"{'Product':>10s}  {'Q1 mid':>10s}  {'Q2 mid':>10s}  {'Q3 mid':>10s}  {'Q4 mid':>10s}  {'Q4-Q1':>10s}")
    for p in options:
        sub = prices[prices["product"] == p].sort_values("timestamp").copy()
        sub["mid"] = (sub["bid_price_1"].fillna(0) + sub["ask_price_1"].fillna(0)) / 2
        sub = sub[sub["mid"] > 0]
        if len(sub) < 10:
            continue
        n = len(sub)
        avgs = [sub.iloc[n * i // 4 : n * (i + 1) // 4]["mid"].mean() for i in range(4)]
        print(f"{p:>10s}  {avgs[0]:>10.2f}  {avgs[1]:>10.2f}  {avgs[2]:>10.2f}  {avgs[3]:>10.2f}  {avgs[3]-avgs[0]:>+10.2f}")


if __name__ == "__main__":
    main()
