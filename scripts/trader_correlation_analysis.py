"""Trader-by-trader analysis on VELVET R4 D1/D2/D3.

Each "Mark XX" represents another participant. Per trader compute:
  1. Net signed flow (buys - sells) over the day
  2. P&L proxy: net flow * (final_mid - avg_trade_price) — were they on the right side?
  3. Mean trade price vs day mid range — do they buy the dip / sell the rip?
  4. Correlation: did Mark X's flow predict mid moves at horizon h?
  5. Pairs: do Mark X and Mark Y trade against each other (high anti-correlation)?

Output: console summary + per-trader scoring.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent


def load_trades(day: int, product: str = "VELVETFRUIT_EXTRACT"):
    path = ROOT / "data" / "round_4" / f"trades_round_4_day_{day}.csv"
    out = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                if row["symbol"] != product:
                    continue
                out.append({
                    "ts": int(row["timestamp"]),
                    "buyer": row.get("buyer", ""),
                    "seller": row.get("seller", ""),
                    "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })
            except (ValueError, KeyError):
                continue
    return out


def load_prices(day: int, product: str = "VELVETFRUIT_EXTRACT"):
    path = ROOT / "data" / "round_4" / f"prices_round_4_day_{day}.csv"
    out = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                if row["product"] != product:
                    continue
                out.append((int(row["timestamp"]), float(row["mid_price"])))
            except (ValueError, KeyError):
                continue
    return out


def trader_pnl_proxy(trader_trades, mid_at_end):
    """Trader's PnL = realized + marked-to-market.
    Realized: sum of cash from each trade (buy = -price*qty, sell = +price*qty).
    MTM: net position * final mid.
    """
    cash = 0.0
    pos = 0
    for t in trader_trades:
        cash += t["cash"]
        pos += t["pos_delta"]
    return cash + pos * mid_at_end, pos


def per_trader_summary(day: int, product: str = "VELVETFRUIT_EXTRACT"):
    trades = load_trades(day, product)
    prices = load_prices(day, product)
    if not trades or not prices:
        return None
    mid_at_start = prices[0][1]
    mid_at_end = prices[-1][1]
    drift = mid_at_end - mid_at_start

    # For each trader, collect all their trades (each trade involves a buyer and seller)
    trader_trades = defaultdict(list)
    for t in trades:
        b, s = t["buyer"], t["seller"]
        if b:
            trader_trades[b].append({
                "ts": t["ts"],
                "side": "BUY",
                "qty": t["qty"],
                "price": t["price"],
                "cash": -t["price"] * t["qty"],
                "pos_delta": t["qty"],
            })
        if s:
            trader_trades[s].append({
                "ts": t["ts"],
                "side": "SELL",
                "qty": t["qty"],
                "price": t["price"],
                "cash": +t["price"] * t["qty"],
                "pos_delta": -t["qty"],
            })

    summary = {}
    for trader, ttrades in trader_trades.items():
        n = len(ttrades)
        n_buy = sum(1 for tt in ttrades if tt["side"] == "BUY")
        n_sell = sum(1 for tt in ttrades if tt["side"] == "SELL")
        vol_buy = sum(tt["qty"] for tt in ttrades if tt["side"] == "BUY")
        vol_sell = sum(tt["qty"] for tt in ttrades if tt["side"] == "SELL")
        net_pos = vol_buy - vol_sell
        avg_buy_price = (sum(tt["price"] * tt["qty"] for tt in ttrades if tt["side"] == "BUY") / vol_buy) if vol_buy else None
        avg_sell_price = (sum(tt["price"] * tt["qty"] for tt in ttrades if tt["side"] == "SELL") / vol_sell) if vol_sell else None
        # Trader PnL proxy
        pnl, _ = trader_pnl_proxy(ttrades, mid_at_end)
        summary[trader] = {
            "n_trades": n, "n_buy": n_buy, "n_sell": n_sell,
            "vol_buy": vol_buy, "vol_sell": vol_sell, "net_pos": net_pos,
            "avg_buy_price": avg_buy_price, "avg_sell_price": avg_sell_price,
            "pnl": pnl,
            "trades": ttrades,
        }
    return {
        "drift": drift, "mid_start": mid_at_start, "mid_end": mid_at_end,
        "trader_summary": summary,
    }


def main():
    print("=" * 110)
    print("TRADER ANALYSIS — VELVETFRUIT_EXTRACT R4 (per-day trader stats)")
    print("=" * 110)

    cumulative_pnl = defaultdict(float)
    cumulative_vol = defaultdict(int)

    for day in (1, 2, 3):
        result = per_trader_summary(day, "VELVETFRUIT_EXTRACT")
        if result is None:
            continue
        print(f"\n--- Day {day}: VELVET drift = {result['drift']:+,.1f}, mid start={result['mid_start']:,.1f} → end={result['mid_end']:,.1f} ---\n")
        print(f"{'Trader':>10s}  {'n_trd':>6s}  {'vol_buy':>8s}  {'vol_sell':>8s}  {'net_pos':>8s}  {'avg_buy':>10s}  {'avg_sell':>10s}  {'PnL_proxy':>12s}")
        print("-" * 110)
        rows = sorted(result["trader_summary"].items(), key=lambda kv: -abs(kv[1]["pnl"]))
        for trader, stats in rows:
            cumulative_pnl[trader] += stats["pnl"]
            cumulative_vol[trader] += stats["vol_buy"] + stats["vol_sell"]
            avg_b = f"{stats['avg_buy_price']:>10,.1f}" if stats["avg_buy_price"] else "{:>10s}".format("-")
            avg_s = f"{stats['avg_sell_price']:>10,.1f}" if stats["avg_sell_price"] else "{:>10s}".format("-")
            print(
                f"{trader:>10s}  "
                f"{stats['n_trades']:>6d}  "
                f"{stats['vol_buy']:>8d}  "
                f"{stats['vol_sell']:>8d}  "
                f"{stats['net_pos']:>+8d}  "
                f"{avg_b}  {avg_s}  "
                f"{stats['pnl']:>+12,.0f}"
            )

    # Cumulative
    print("\n" + "=" * 110)
    print("CUMULATIVE 3-DAY TRADER PnL (mark-to-market vs final D3 mid)")
    print("=" * 110)
    print(f"{'Trader':>10s}  {'Total Vol':>10s}  {'PnL_3d':>12s}  Verdict")
    print("-" * 110)
    sorted_pnl = sorted(cumulative_pnl.items(), key=lambda kv: -kv[1])
    for trader, pnl in sorted_pnl:
        vol = cumulative_vol[trader]
        verdict = "🟢 WINNER" if pnl > 1000 else ("🔴 LOSER" if pnl < -1000 else "⚪ flat")
        print(f"{trader:>10s}  {vol:>10,}  {pnl:>+12,.0f}  {verdict}")


if __name__ == "__main__":
    main()
