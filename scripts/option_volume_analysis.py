"""Volume + buy/sell skew analysis per VEV option strike across the 3 R4 days.

User's note: "sur les options y'a très peu de trade en backtest sur 4500-5200, et
dans les options à gros strike y'a que des ventes"

Test:
  - Total volume per strike per day
  - Buy vs Sell ratio per strike
  - For high strikes (5400+): how often is bid empty / how often is ask empty?
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_trades(day: int):
    path = ROOT / "data" / "round_4" / f"trades_round_4_day_{day}.csv"
    out = defaultdict(list)
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                sym = row["symbol"]
                out[sym].append({
                    "ts": int(row["timestamp"]),
                    "buyer": row.get("buyer", ""),
                    "seller": row.get("seller", ""),
                    "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })
            except (ValueError, KeyError):
                continue
    return out


def main():
    print("=" * 100)
    print("VEV OPTION VOLUME / BUY-SELL SKEW per day (R4 trades CSVs)")
    print("=" * 100)

    days = {}
    for d in (1, 2, 3):
        days[d] = load_trades(d)

    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]

    # Volume per strike per day
    print(f"\n{'Strike':>8s}  {'D1 trades':>10s}  {'D1 vol':>9s}  {'D2 trades':>10s}  {'D2 vol':>9s}  {'D3 trades':>10s}  {'D3 vol':>9s}")
    print("-" * 100)
    for K in strikes:
        sym = f"VEV_{K}"
        row_data = []
        for d in (1, 2, 3):
            trades = days[d].get(sym, [])
            n = len(trades)
            vol = sum(t["qty"] for t in trades)
            row_data.extend([n, vol])
        print(
            f"{K:>8d}  "
            f"{row_data[0]:>10,}  {row_data[1]:>9,}  "
            f"{row_data[2]:>10,}  {row_data[3]:>9,}  "
            f"{row_data[4]:>10,}  {row_data[5]:>9,}"
        )

    # Buy vs sell skew (proxy: trades with buyer="" are aggressive sells, seller="" are aggressive buys)
    print("\n" + "=" * 100)
    print("BUY/SELL FLOW per strike per day (counts of trades where buyer='' or seller='')")
    print("=" * 100)
    print(f"{'Strike':>8s}  {'day':>4s}  {'N':>6s}  {'noBuyer (=aggSells)':>22s}  {'noSeller (=aggBuys)':>22s}  {'matched':>8s}")
    print("-" * 100)
    for K in strikes:
        sym = f"VEV_{K}"
        for d in (1, 2, 3):
            trades = days[d].get(sym, [])
            if not trades:
                continue
            n = len(trades)
            no_buyer = sum(1 for t in trades if not t["buyer"])
            no_seller = sum(1 for t in trades if not t["seller"])
            matched = sum(1 for t in trades if t["buyer"] and t["seller"])
            print(
                f"{K:>8d}  D{d:>3d}  {n:>6d}  "
                f"{no_buyer:>22d}  {no_seller:>22d}  {matched:>8d}"
            )

    # Top counterparties per VEV strike (combined 3-day)
    print("\n" + "=" * 100)
    print("TOP COUNTERPARTIES per VEV strike (volume across 3 days; buyer/seller IDs)")
    print("=" * 100)
    for K in strikes:
        sym = f"VEV_{K}"
        all_trades = []
        for d in (1, 2, 3):
            all_trades.extend(days[d].get(sym, []))
        if not all_trades:
            continue

        buyer_vol = defaultdict(int)
        seller_vol = defaultdict(int)
        for t in all_trades:
            if t["buyer"]:
                buyer_vol[t["buyer"]] += t["qty"]
            if t["seller"]:
                seller_vol[t["seller"]] += t["qty"]

        top_buyers = sorted(buyer_vol.items(), key=lambda kv: -kv[1])[:5]
        top_sellers = sorted(seller_vol.items(), key=lambda kv: -kv[1])[:5]
        print(f"\n{sym}:")
        if top_buyers:
            print(f"  TOP BUYERS:  " + ", ".join(f"{n}={v}" for n, v in top_buyers))
        if top_sellers:
            print(f"  TOP SELLERS: " + ", ".join(f"{n}={v}" for n, v in top_sellers))


if __name__ == "__main__":
    main()
