"""Why does VEV_6000 / VEV_6500 trade at price 0.5 with Mark 01 buying / Mark 22 selling?

Mid mid_price = 0.5 across 3 days for both.
But trades happen at price 0.5 ALL THE TIME — Mark 01 BUYS 1105, Mark 22 SELLS 1105.

It's bizarre because:
  - These options are deep OTM (S~5240, K=6000/6500 → far above strike)
  - BS price ~ 0 (truly worthless)
  - Yet 317 trades on each over 3 days at exactly 0.5 each

Investigate:
  - Are they at exactly 0.5 always? Or does the price vary?
  - What's the SPREAD on these strikes (bid/ask gap)?
  - When trades happen, what's the timing pattern?
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_full_book(day, products):
    """Returns: {sym: [(ts, mid, bid_p, ask_p, bid_v, ask_v), ...]}"""
    out = defaultdict(list)
    path = ROOT / "data" / "round_4" / f"prices_round_4_day_{day}.csv"
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                if row["product"] not in products:
                    continue
                out[row["product"]].append({
                    "ts": int(row["timestamp"]),
                    "mid": float(row["mid_price"]),
                    "bid_p": float(row["bid_price_1"]) if row.get("bid_price_1") else None,
                    "ask_p": float(row["ask_price_1"]) if row.get("ask_price_1") else None,
                    "bid_v": int(row.get("bid_volume_1", 0) or 0),
                    "ask_v": int(row.get("ask_volume_1", 0) or 0),
                })
            except Exception:
                continue
    return out


def load_trades(day, products):
    out = defaultdict(list)
    path = ROOT / "data" / "round_4" / f"trades_round_4_day_{day}.csv"
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                if row["symbol"] not in products:
                    continue
                out[row["symbol"]].append({
                    "ts": int(row["timestamp"]),
                    "buyer": row.get("buyer", ""),
                    "seller": row.get("seller", ""),
                    "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })
            except Exception:
                continue
    return out


def main():
    products = ["VEV_6000", "VEV_6500", "VEV_5500", "VEV_5400"]

    print("=" * 100)
    print("DEEP OTM MYSTERY — VEV_6000 / VEV_6500 (and 5500/5400 for comparison)")
    print("=" * 100)

    for d in (1, 2, 3):
        books = load_full_book(d, products)
        trades = load_trades(d, products)

        for sym in products:
            book = books.get(sym, [])
            tr = trades.get(sym, [])
            if not book:
                continue

            print(f"\n--- Day {d}: {sym} ---")

            # Mid distribution
            mids = [b["mid"] for b in book]
            unique_mids = sorted(set(mids))
            print(f"  Mids seen: {unique_mids[:10]}{' ...' if len(unique_mids) > 10 else ''}")
            print(f"  Mid range: {min(mids):.2f} to {max(mids):.2f}")

            # Spread distribution
            spreads = [b["ask_p"] - b["bid_p"] for b in book if b["bid_p"] and b["ask_p"]]
            if spreads:
                print(f"  Spreads: min={min(spreads):.0f}, max={max(spreads):.0f}, avg={sum(spreads)/len(spreads):.2f}")

            # Trades
            if tr:
                trade_prices = sorted(set(t["price"] for t in tr))
                print(f"  Trade prices: {trade_prices[:10]}")
                print(f"  Total trades: {len(tr)}, total qty: {sum(t['qty'] for t in tr)}")

                # Per trader
                per_trader_trades = defaultdict(lambda: {"buy": 0, "sell": 0, "trades": 0})
                for t in tr:
                    if t["buyer"]:
                        per_trader_trades[t["buyer"]]["buy"] += t["qty"]
                        per_trader_trades[t["buyer"]]["trades"] += 1
                    if t["seller"]:
                        per_trader_trades[t["seller"]]["sell"] += t["qty"]

                # Trade timing — bursts?
                # Group trades by minute (10000 ts blocks)
                by_minute = defaultdict(int)
                for t in tr:
                    by_minute[t["ts"] // 10000] += 1
                if by_minute:
                    max_burst = max(by_minute.values())
                    avg_burst = sum(by_minute.values()) / len(by_minute)
                    print(f"  Trade timing: avg {avg_burst:.1f} trades/100tick, max burst {max_burst} trades/100tick")

    # Final hypothesis check: are bid/ask volumes balanced or one-sided?
    print("\n" + "=" * 100)
    print("BID/ASK VOLUMES on VEV_6000 / VEV_6500 — one-sided book?")
    print("=" * 100)
    for d in (1, 2, 3):
        books = load_full_book(d, ["VEV_6000", "VEV_6500"])
        for sym in ["VEV_6000", "VEV_6500"]:
            b = books.get(sym, [])
            if not b:
                continue
            avg_bid_v = sum(x["bid_v"] for x in b) / len(b)
            avg_ask_v = sum(x["ask_v"] for x in b) / len(b)
            zero_bid = sum(1 for x in b if x["bid_v"] == 0)
            zero_ask = sum(1 for x in b if x["ask_v"] == 0)
            print(f"  D{d} {sym}: avg bid_v={avg_bid_v:.1f}, avg ask_v={avg_ask_v:.1f}, "
                  f"empty bid={zero_bid}/{len(b)}, empty ask={zero_ask}/{len(b)}")


if __name__ == "__main__":
    main()
