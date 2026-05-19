"""Diagnose: why did R3 LIVE options underperform / get stuck at +300?

Hypotheses:
  1. Strategy `option_mm_bs` accumulates long without unwinding (no takers, only passive bids)
  2. Mid price rallied → our long position gained MTM PnL but we couldn't rebalance
  3. Spread on options is wide → we get adverse-filled
  4. Position limit hit early → we stop being able to capture spread
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict


def main():
    parser = argparse.ArgumentParser(description="Diagnose an R3 live options run from its JSON and .log files.")
    parser.add_argument("--json", required=True, help="Path to the live result JSON file.")
    parser.add_argument("--log", required=True, help="Path to the companion .log file.")
    args = parser.parse_args()

    with open(args.json, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Parse activities log
    log = data["activitiesLog"]
    rows = []
    for line in log.strip().split("\n")[1:]:
        parts = line.split(";")
        if len(parts) < 17:
            continue
        try:
            rows.append({
                "ts": int(parts[1]),
                "product": parts[2],
                "bid_p": float(parts[3]) if parts[3] else None,
                "ask_p": float(parts[9]) if parts[9] else None,
                "mid": float(parts[15]) if parts[15] else None,
                "pnl": float(parts[16]) if parts[16] else 0.0,
            })
        except Exception:
            continue

    # Per option, get start/end mid + spread + final pnl
    print("=" * 110)
    print("R3 LIVE OPTIONS DIAGNOSIS")
    print("=" * 110)
    products = sorted(set(r["product"] for r in rows))
    options = [p for p in products if p.startswith("VEV_")]

    print(f"\n{'Product':>14s}  {'mid_start':>10s}  {'mid_end':>10s}  {'mid_drift':>10s}  {'avg_spread':>10s}  {'final_pnl':>10s}")
    print("-" * 110)
    for prod in options:
        prod_rows = [r for r in rows if r["product"] == prod]
        if not prod_rows:
            continue
        mid_start = prod_rows[0]["mid"]
        mid_end = prod_rows[-1]["mid"]
        spreads = [r["ask_p"] - r["bid_p"] for r in prod_rows if r["bid_p"] and r["ask_p"]]
        avg_spread = sum(spreads) / len(spreads) if spreads else 0
        final_pnl = prod_rows[-1]["pnl"]
        drift = (mid_end - mid_start) if (mid_end and mid_start) else 0
        print(f"{prod:>14s}  {mid_start:>10.2f}  {mid_end:>10.2f}  {drift:>+10.2f}  {avg_spread:>10.2f}  {final_pnl:>+10,.0f}")

    # Position trajectory: extract from trades
    print("\n" + "=" * 110)
    print("POSITION ACCUMULATION TIMELINE per option (when did we reach max?)")
    print("=" * 110)

    # Need to parse tradeHistory from log file
    with open(args.log, "r", encoding="utf-8") as f:
        raw = f.read()
    start_ix = raw.find('"tradeHistory":[')
    if start_ix < 0:
        return
    start_ix += len('"tradeHistory":')
    depth = 0
    end_ix = start_ix
    for i, ch in enumerate(raw[start_ix:]):
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end_ix = start_ix + i + 1
                break
    trades = json.loads(raw[start_ix:end_ix])

    print(f"\n{'Product':>14s}  {'reached_+300':>14s}  {'reached_-300':>14s}  {'final_pos':>10s}  {'n_buy':>8s}  {'n_sell':>8s}")
    print("-" * 110)
    for prod in options:
        prod_trades = sorted([t for t in trades if t["symbol"] == prod], key=lambda x: x["timestamp"])
        pos = 0
        reached_max = None
        reached_min = None
        n_buy = 0
        n_sell = 0
        for t in prod_trades:
            if t["buyer"] == "SUBMISSION":
                pos += t["quantity"]
                n_buy += 1
            elif t["seller"] == "SUBMISSION":
                pos -= t["quantity"]
                n_sell += 1
            if pos >= 300 and reached_max is None:
                reached_max = t["timestamp"]
            if pos <= -300 and reached_min is None:
                reached_min = t["timestamp"]
        rmax = f"@ts={reached_max}" if reached_max else "-"
        rmin = f"@ts={reached_min}" if reached_min else "-"
        print(f"{prod:>14s}  {rmax:>14s}  {rmin:>14s}  {pos:>+10d}  {n_buy:>8d}  {n_sell:>8d}")

    # Sweet spot: when did we accumulate fastest, and was it during a price rally?
    print("\n" + "=" * 110)
    print("VEV_5200 (-2,514 worst) detailed analysis: pos vs price")
    print("=" * 110)
    prod = "VEV_5200"
    pos = 0
    samples = []  # (ts, position, mid, pnl)
    prod_trades = sorted([t for t in trades if t["symbol"] == prod], key=lambda x: x["timestamp"])
    prod_rows = [r for r in rows if r["product"] == prod]
    mid_by_ts = {r["ts"]: r["mid"] for r in prod_rows}
    pnl_by_ts = {r["ts"]: r["pnl"] for r in prod_rows}

    for t in prod_trades:
        if t["buyer"] == "SUBMISSION":
            pos += t["quantity"]
        elif t["seller"] == "SUBMISSION":
            pos -= t["quantity"]
        ts = t["timestamp"]
        mid = mid_by_ts.get(ts) or mid_by_ts.get(ts - 100, 0)
        pnl = pnl_by_ts.get(ts) or pnl_by_ts.get(ts - 100, 0)
        samples.append((ts, pos, mid, pnl))

    # Print key checkpoints
    print(f"\n  Key moments on VEV_5200:")
    print(f"  {'ts':>10s}  {'position':>10s}  {'mid':>8s}  {'pnl':>10s}")
    for sample in samples[:5] + samples[len(samples)//2-2:len(samples)//2+2] + samples[-5:]:
        ts, p, mid, pnl = sample
        print(f"  {ts:>10d}  {p:>+10d}  {mid:>8.2f}  {pnl:>+10,.0f}")


if __name__ == "__main__":
    main()
