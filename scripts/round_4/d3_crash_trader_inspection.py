"""Could we have predicted the D3 crash by watching trader behavior?

D3 baseline crash: VELVET drops -45 in last 5% (tick 950k-999.9k).
Goal: identify if any specific Mark behavior CHANGES in the crash window
that we could detect IN ADVANCE.

Look at:
  - Trade volume patterns by Mark in the 5% before the crash (945k-995k)
  - Price aggression: who's hitting bids/asks
  - Net flow per Mark in 50-tick rolling windows
  - Compare D2 last 10% (similar drawdown, different outcome) vs D3 last 10%
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_velvet_trades(day: int):
    out = []
    path = ROOT / "data" / "round_4" / f"trades_round_4_day_{day}.csv"
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                if row["symbol"] != "VELVETFRUIT_EXTRACT":
                    continue
                out.append({
                    "ts": int(row["timestamp"]),
                    "buyer": row.get("buyer", "") or "",
                    "seller": row.get("seller", "") or "",
                    "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })
            except Exception:
                continue
    return out


def load_velvet_mids(day: int):
    out = []
    path = ROOT / "data" / "round_4" / f"prices_round_4_day_{day}.csv"
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                if row["product"] != "VELVETFRUIT_EXTRACT":
                    continue
                out.append((int(row["timestamp"]), float(row["mid_price"])))
            except Exception:
                continue
    return out


def main():
    print("=" * 100)
    print("D3 CRASH FORENSICS — Could we have seen it via trader IDs?")
    print("=" * 100)

    for day in (2, 3):
        trades = load_velvet_trades(day)
        mids = load_velvet_mids(day)
        if not trades or not mids:
            continue

        print(f"\n--- Day {day}: VELVET ---")
        # Mid trajectory
        mid_at = dict(mids)
        ts_sorted = sorted(mid_at.keys())
        print(f"  Mid start: {mid_at[ts_sorted[0]]:.1f}")
        print(f"  Mid end: {mid_at[ts_sorted[-1]]:.1f}")
        print(f"  Mid drift: {mid_at[ts_sorted[-1]] - mid_at[ts_sorted[0]]:+.1f}")

        # Identify "crash window" or last 10% for D3
        last10_start = 900000
        last10_trades = [t for t in trades if t["ts"] >= last10_start]
        before_last10 = [t for t in trades if t["ts"] < last10_start]

        print(f"\n  TRADES BEFORE last 10% ({len(before_last10)} trades):")
        per_trader_b = defaultdict(lambda: {"buy": 0, "sell": 0})
        for t in before_last10:
            if t["buyer"]:
                per_trader_b[t["buyer"]]["buy"] += t["qty"]
            if t["seller"]:
                per_trader_b[t["seller"]]["sell"] += t["qty"]
        for tr, v in sorted(per_trader_b.items()):
            net = v["buy"] - v["sell"]
            print(f"    {tr}: BUY {v['buy']} / SELL {v['sell']} / NET {net:+}")

        print(f"\n  TRADES IN last 10% ({len(last10_trades)} trades):")
        per_trader_a = defaultdict(lambda: {"buy": 0, "sell": 0})
        for t in last10_trades:
            if t["buyer"]:
                per_trader_a[t["buyer"]]["buy"] += t["qty"]
            if t["seller"]:
                per_trader_a[t["seller"]]["sell"] += t["qty"]
        for tr, v in sorted(per_trader_a.items()):
            net = v["buy"] - v["sell"]
            print(f"    {tr}: BUY {v['buy']} / SELL {v['sell']} / NET {net:+}")

        # 50-tick rolling windows in the last 10% — does any Mark's flow shift?
        print(f"\n  50-TICK NET FLOW per trader in 5%-buckets (50000 ts each) of last 10%:")
        buckets = defaultdict(lambda: defaultdict(int))
        for t in last10_trades:
            b = (t["ts"] - last10_start) // 25000  # 25k ts buckets = ~250 ticks
            if t["buyer"]:
                buckets[b][t["buyer"]] += t["qty"]
            if t["seller"]:
                buckets[b][t["seller"]] -= t["qty"]
        for b in sorted(buckets.keys()):
            ts_start = last10_start + b * 25000
            print(f"    bucket {b} (ts {ts_start}-{ts_start+25000}):")
            for tr, net in sorted(buckets[b].items()):
                if abs(net) > 0:
                    print(f"      {tr}: NET {net:+}")

    # ======== COMPARISON: which Mark's behavior diverges most D2 vs D3 in last 10% ========
    print("\n" + "=" * 100)
    print("DIVERGENCE: D3 last 10% net flow vs D2 last 10% net flow per trader")
    print("=" * 100)
    d2_trades = [t for t in load_velvet_trades(2) if t["ts"] >= 900000]
    d3_trades = [t for t in load_velvet_trades(3) if t["ts"] >= 900000]

    d2_net = defaultdict(int)
    d3_net = defaultdict(int)
    for t in d2_trades:
        if t["buyer"]: d2_net[t["buyer"]] += t["qty"]
        if t["seller"]: d2_net[t["seller"]] -= t["qty"]
    for t in d3_trades:
        if t["buyer"]: d3_net[t["buyer"]] += t["qty"]
        if t["seller"]: d3_net[t["seller"]] -= t["qty"]

    all_traders = sorted(set(d2_net.keys()) | set(d3_net.keys()))
    print(f"  {'Trader':>10s}  {'D2 net':>10s}  {'D3 net':>10s}  {'D3-D2':>10s}")
    print("-" * 60)
    for tr in all_traders:
        d2 = d2_net.get(tr, 0)
        d3 = d3_net.get(tr, 0)
        delta = d3 - d2
        print(f"  {tr:>10s}  {d2:>+10d}  {d3:>+10d}  {delta:>+10d}")


if __name__ == "__main__":
    main()
