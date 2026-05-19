"""Compare LIVE alpha probe + v5 vs backtest first 10% of D3.

Identifies:
  - Trades only present in live (= participants reacting to OUR quotes)
  - Volume differences (we get more/less filled)
  - Mark behavior differences
  - Hidden info: do specific Marks change behavior when we trade vs not?
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BACKTEST_D3_TRADES = ROOT / "data" / "round_4" / "trades_round_4_day_3.csv"


def parse_live_trade_history(log_path: Path):
    """Extract tradeHistory from live log."""
    with open(log_path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Find tradeHistory
    start = raw.find('"tradeHistory":[')
    if start < 0:
        return []
    start += len('"tradeHistory":')
    depth = 0
    for i, ch in enumerate(raw[start:]):
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:start + i + 1])
    return []


def load_backtest_d3_trades_first10pct(backtest_path: Path):
    """Load D3 historical trades for ts 0 → 99900 (first 10%)."""
    out = []
    with open(backtest_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                ts = int(row["timestamp"])
                if ts > 99900:
                    continue
                out.append({
                    "timestamp": ts,
                    "buyer": row.get("buyer", "") or "",
                    "seller": row.get("seller", "") or "",
                    "symbol": row["symbol"],
                    "price": float(row["price"]),
                    "quantity": int(row["quantity"]),
                })
            except Exception:
                continue
    return out


def summarize_trades(trades, label):
    """Per-symbol per-trader summary."""
    symbols = defaultdict(lambda: defaultdict(lambda: {"buy": 0, "sell": 0}))
    for t in trades:
        sym = t["symbol"]
        b = t.get("buyer", "")
        s = t.get("seller", "")
        q = t["quantity"]
        if b:
            symbols[sym][b]["buy"] += q
        if s:
            symbols[sym][s]["sell"] += q
    return symbols


def main():
    parser = argparse.ArgumentParser(description="Compare two live R4 logs against D3 backtest trades.")
    parser.add_argument("--live-probe", required=True, help="Path to the probe live .log file.")
    parser.add_argument("--live-v5", required=True, help="Path to the comparison live .log file.")
    parser.add_argument(
        "--backtest-trades",
        default=str(DEFAULT_BACKTEST_D3_TRADES),
        help="Path to trades_round_4_day_3.csv.",
    )
    args = parser.parse_args()

    print("=" * 110)
    print("LIVE vs BACKTEST FIRST 10% D3 — counterparty + flow comparison")
    print("=" * 110)

    print("\nLoading backtest D3 first 10% trades (no SUBMISSION)...")
    bt = load_backtest_d3_trades_first10pct(Path(args.backtest_trades))
    print(f"  {len(bt)} trades")

    print("\nLoading live ALPHA PROBE trades...")
    probe = parse_live_trade_history(Path(args.live_probe))
    print(f"  {len(probe)} trades")

    print("\nLoading live v5 trades...")
    v5 = parse_live_trade_history(Path(args.live_v5))
    print(f"  {len(v5)} trades")

    # Filter live for "external only" (not involving SUBMISSION)
    probe_external = [t for t in probe if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION"]
    v5_external = [t for t in v5 if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION"]

    print(f"\n  Probe external trades (Mark vs Mark): {len(probe_external)}")
    print(f"  v5 external trades (Mark vs Mark): {len(v5_external)}")

    # ============== VELVET comparison ==============
    print("\n" + "=" * 110)
    print("VELVET — total volume per Mark — BACKTEST vs PROBE LIVE vs V5 LIVE")
    print("=" * 110)
    bt_velvet = [t for t in bt if t["symbol"] == "VELVETFRUIT_EXTRACT"]
    probe_velvet = [t for t in probe if t["symbol"] == "VELVETFRUIT_EXTRACT"]
    v5_velvet = [t for t in v5 if t["symbol"] == "VELVETFRUIT_EXTRACT"]

    def per_mark(trades):
        d = defaultdict(lambda: {"buy": 0, "sell": 0, "buy_n": 0, "sell_n": 0})
        for t in trades:
            b = t.get("buyer", "") or ""
            s = t.get("seller", "") or ""
            q = t["quantity"]
            if b:
                d[b]["buy"] += q
                d[b]["buy_n"] += 1
            if s:
                d[s]["sell"] += q
                d[s]["sell_n"] += 1
        return d

    bt_marks = per_mark(bt_velvet)
    probe_marks = per_mark(probe_velvet)
    v5_marks = per_mark(v5_velvet)

    all_traders = sorted(set(list(bt_marks) + list(probe_marks) + list(v5_marks)))
    print(f"\n  {'Trader':>15s}  {'BT_buy':>8s}  {'BT_sell':>8s}  {'PROBE_buy':>10s}  {'PROBE_sell':>10s}  {'V5_buy':>8s}  {'V5_sell':>8s}")
    print("-" * 110)
    for tr in all_traders:
        bt_v = bt_marks.get(tr, {"buy": 0, "sell": 0})
        pr_v = probe_marks.get(tr, {"buy": 0, "sell": 0})
        v5_v = v5_marks.get(tr, {"buy": 0, "sell": 0})
        print(f"  {tr:>15s}  {bt_v['buy']:>8d}  {bt_v['sell']:>8d}  {pr_v['buy']:>10d}  {pr_v['sell']:>10d}  {v5_v['buy']:>8d}  {v5_v['sell']:>8d}")

    # ============== Mark-vs-Mark interactions ==============
    print("\n" + "=" * 110)
    print("MARK ↔ MARK trades (excluding SUBMISSION) — VELVET only")
    print("=" * 110)
    print("Format: buyer × seller → total qty\n")
    for label, trades_list in [("BACKTEST D3 first 10%", bt_velvet),
                                ("PROBE LIVE", [t for t in probe_velvet if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION"]),
                                ("V5 LIVE", [t for t in v5_velvet if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION"])]:
        pairs = defaultdict(int)
        for t in trades_list:
            if t["buyer"] and t["seller"]:
                pairs[(t["buyer"], t["seller"])] += t["quantity"]
        print(f"  --- {label} ({len(trades_list)} trades) ---")
        for (b, s), q in sorted(pairs.items(), key=lambda kv: -kv[1])[:8]:
            print(f"    {b:>10s} -> {s:<10s}: {q}")

    # ============== Volume increase due to OUR presence ==============
    print("\n" + "=" * 110)
    print("VOLUME ANALYSIS — does our presence (PROBE / V5) increase total VELVET volume?")
    print("=" * 110)
    bt_total = sum(t["quantity"] for t in bt_velvet)
    pr_total = sum(t["quantity"] for t in probe_velvet)
    v5_total = sum(t["quantity"] for t in v5_velvet)
    print(f"  Backtest D3 first 10% (no us):  {bt_total} contracts in {len(bt_velvet)} trades")
    print(f"  Probe live (us as passive MM):  {pr_total} contracts in {len(probe_velvet)} trades")
    print(f"  v5 live (us with full strat):   {v5_total} contracts in {len(v5_velvet)} trades")

    # Trades where we're INVOLVED:
    pr_us = [t for t in probe_velvet if t["buyer"] == "SUBMISSION" or t["seller"] == "SUBMISSION"]
    v5_us = [t for t in v5_velvet if t["buyer"] == "SUBMISSION" or t["seller"] == "SUBMISSION"]
    print(f"  Probe trades involving US:      {len(pr_us)} ({sum(t['quantity'] for t in pr_us)} contracts)")
    print(f"  v5 trades involving US:         {len(v5_us)} ({sum(t['quantity'] for t in v5_us)} contracts)")
    print(f"  Probe trades EXTERNAL only:     {len(probe_velvet) - len(pr_us)}")
    print(f"  v5 trades EXTERNAL only:        {len(v5_velvet) - len(v5_us)}")

    # ============== Tick-by-tick correlation: do Marks REACT after OUR trades? ==============
    print("\n" + "=" * 110)
    print("REACTIVITY: when WE buy/sell at ts T, who shows up at ts T+100..500?")
    print("=" * 110)
    for label, trades_list in [("PROBE LIVE", probe_velvet), ("V5 LIVE", v5_velvet)]:
        # Find our buy timestamps
        our_buys = [t["timestamp"] for t in trades_list if t["buyer"] == "SUBMISSION"]
        our_sells = [t["timestamp"] for t in trades_list if t["seller"] == "SUBMISSION"]
        # For each Mark, count how often they trade right AFTER our buy/sell
        per_mark_after_buy = defaultdict(int)
        per_mark_after_sell = defaultdict(int)
        for ts in our_buys:
            for t in trades_list:
                if t["buyer"] == "SUBMISSION" or t["seller"] == "SUBMISSION":
                    continue
                if 0 < t["timestamp"] - ts <= 500:
                    if t["buyer"]:
                        per_mark_after_buy[t["buyer"] + "_buys"] += 1
                    if t["seller"]:
                        per_mark_after_buy[t["seller"] + "_sells"] += 1
        for ts in our_sells:
            for t in trades_list:
                if t["buyer"] == "SUBMISSION" or t["seller"] == "SUBMISSION":
                    continue
                if 0 < t["timestamp"] - ts <= 500:
                    if t["buyer"]:
                        per_mark_after_sell[t["buyer"] + "_buys"] += 1
                    if t["seller"]:
                        per_mark_after_sell[t["seller"] + "_sells"] += 1

        print(f"\n  --- {label} ---")
        print(f"  Our BUYS: {len(our_buys)}, Our SELLS: {len(our_sells)}")
        print(f"  After OUR BUY (next 5 ticks), Mark activity:")
        for k, v in sorted(per_mark_after_buy.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {k}: {v}")
        print(f"  After OUR SELL (next 5 ticks), Mark activity:")
        for k, v in sorted(per_mark_after_sell.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
