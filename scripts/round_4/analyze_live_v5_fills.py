"""Analyze our LIVE v5 fills: who filled our quotes? Did fade signals work as expected?"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Analyze counterparties filling our live round-4 quotes.")
    parser.add_argument("--log", required=True, help="Path to the live .log file.")
    args = parser.parse_args()

    log_path = Path(args.log)
    with open(log_path, "r", encoding="utf-8") as f:
        raw = f.read()

    m = re.search(r'"tradeHistory":\s*(\[.*?\])', raw, re.DOTALL)
    if not m:
        print("No tradeHistory found")
        raise SystemExit(1)

    start = raw.find('"tradeHistory":[') + len('"tradeHistory":')
    depth = 0
    end = start
    for i, ch in enumerate(raw[start:]):
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = start + i + 1
                break
    trades = json.loads(raw[start:end])
    print(f"Loaded {len(trades)} trades from live log")

    our = [t for t in trades if t["buyer"] == "SUBMISSION" or t["seller"] == "SUBMISSION"]
    print(f"Our trades: {len(our)}")

    print("\n" + "=" * 100)
    print("OUR FILLS PER COUNTERPARTY × PRODUCT (LIVE D3 first 10%)")
    print("=" * 100)

    per_prod = defaultdict(lambda: defaultdict(lambda: {"we_buy_qty": 0, "we_sell_qty": 0}))
    for t in our:
        sym = t["symbol"]
        qty = t["quantity"]
        if t["buyer"] == "SUBMISSION":
            cp = t["seller"]
            per_prod[sym][cp]["we_buy_qty"] += qty
        else:
            cp = t["buyer"]
            per_prod[sym][cp]["we_sell_qty"] += qty

    for sym in sorted(per_prod):
        print(f"\n  {sym}:")
        print(f"    {'Counterparty':>15s}  {'we_buy':>10s}  {'we_sell':>10s}  {'net_us':>10s}")
        cps = per_prod[sym]
        for cp in sorted(cps, key=lambda c: -(cps[c]["we_buy_qty"] + cps[c]["we_sell_qty"])):
            v = cps[cp]
            net = v["we_buy_qty"] - v["we_sell_qty"]
            print(f"    {cp:>15s}  {v['we_buy_qty']:>10d}  {v['we_sell_qty']:>10d}  {net:>+10d}")

    print("\n" + "=" * 100)
    print("VELVET LIVE: Did Mark 49 fade signal work?")
    print("=" * 100)
    velvet_trades = [t for t in trades if t["symbol"] == "VELVETFRUIT_EXTRACT"]
    print(f"Total VELVET trades (incl. external): {len(velvet_trades)}")

    m49_trades = [t for t in velvet_trades if t["seller"] == "Mark 49" or t["buyer"] == "Mark 49"]
    print(f"  Mark 49 trades on VELVET: {len(m49_trades)}")
    m49_buy = sum(t["quantity"] for t in m49_trades if t["buyer"] == "Mark 49")
    m49_sell = sum(t["quantity"] for t in m49_trades if t["seller"] == "Mark 49")
    print(f"  Mark 49 BUY: {m49_buy}, SELL: {m49_sell}, NET: {m49_buy - m49_sell:+}")

    m14_trades = [t for t in velvet_trades if t["seller"] == "Mark 14" or t["buyer"] == "Mark 14"]
    m14_buy = sum(t["quantity"] for t in m14_trades if t["buyer"] == "Mark 14")
    m14_sell = sum(t["quantity"] for t in m14_trades if t["seller"] == "Mark 14")
    print(f"  Mark 14 BUY: {m14_buy}, SELL: {m14_sell}, NET: {m14_buy - m14_sell:+}")

    m01_trades = [t for t in velvet_trades if t["seller"] == "Mark 01" or t["buyer"] == "Mark 01"]
    m01_buy = sum(t["quantity"] for t in m01_trades if t["buyer"] == "Mark 01")
    m01_sell = sum(t["quantity"] for t in m01_trades if t["seller"] == "Mark 01")
    print(f"  Mark 01 BUY: {m01_buy}, SELL: {m01_sell}, NET: {m01_buy - m01_sell:+}")

    print("\n  Compare to 3-day historical:")
    print("  Mark 49: 1071 sells / 115 buys (95% sell). LIVE first 10%: should be similar pattern.")
    print("  Mark 14: 1761/1763 (50/50 MM)")
    print("  Mark 01: 1417/1375 (50/50 MM)")


if __name__ == "__main__":
    main()
