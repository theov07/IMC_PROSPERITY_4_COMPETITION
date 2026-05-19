"""TICK rule signal — recent N trades' aggressor direction predicts next return.

Classify each trade as aggressive BUY (price > prev mid) or aggressive SELL.
Compute net_aggressor_volume over last K ticks. Test if it predicts next return.

This is a classic momentum signal — institutional flow leaves a footprint.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from collections import deque

ROOT = Path(__file__).resolve().parents[2]


def load_velvet_with_offsets(days=(1, 2, 3)):
    trades, mids = [], []
    for d in days:
        offset = (d - 1) * 1_000_000
        path_t = ROOT / "data" / "round_4" / f"trades_round_4_day_{d}.csv"
        with open(path_t, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row["symbol"] != "VELVETFRUIT_EXTRACT":
                    continue
                try:
                    trades.append({
                        "ts": int(row["timestamp"]) + offset,
                        "price": float(row["price"]),
                        "qty": int(row["quantity"]),
                    })
                except Exception:
                    continue
        path_p = ROOT / "data" / "round_4" / f"prices_round_4_day_{d}.csv"
        with open(path_p, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row["product"] != "VELVETFRUIT_EXTRACT":
                    continue
                try:
                    mids.append({
                        "ts": int(row["timestamp"]) + offset,
                        "mid": float(row["mid_price"]),
                    })
                except Exception:
                    continue
    return trades, mids


def main():
    trades, mids = load_velvet_with_offsets()
    print(f"Loaded {len(trades):,} trades, {len(mids):,} mids")

    # Index mids by ts
    mid_ts = sorted(m["ts"] for m in mids)
    mid_by_ts = {m["ts"]: m["mid"] for m in mids}
    from bisect import bisect_left

    def closest_mid_before(ts):
        idx = bisect_left(mid_ts, ts)
        if idx == 0:
            return mid_by_ts[mid_ts[0]]
        return mid_by_ts[mid_ts[idx - 1]]

    # Classify each trade
    for t in trades:
        prev_mid = closest_mid_before(t["ts"])
        if t["price"] > prev_mid:
            t["aggressor"] = "BUY"
            t["signed_qty"] = t["qty"]
        elif t["price"] < prev_mid:
            t["aggressor"] = "SELL"
            t["signed_qty"] = -t["qty"]
        else:
            t["aggressor"] = "MID"
            t["signed_qty"] = 0

    # For each tick, compute net signed flow over last K-tick window (in timestamp units)
    # Test multiple K and forward horizons
    for window_ts in (5000, 10000, 20000, 50000):
        for horizon_ticks in (10, 50, 100):
            print(f"\n--- Window={window_ts/100:.0f} ticks, Horizon={horizon_ticks} ticks ---")
            pairs = []
            for m in mids[::100]:  # sample every 100 ticks
                ts = m["ts"]
                # Net flow in past window_ts
                net = 0
                for t in trades:
                    if t["ts"] < ts - window_ts or t["ts"] >= ts:
                        continue
                    net += t["signed_qty"]
                # Forward return
                future_ts = ts + horizon_ticks * 100
                if future_ts > mid_ts[-1]:
                    continue
                future_mid = mid_by_ts.get(future_ts)
                if future_mid is None:
                    # Find closest
                    idx = bisect_left(mid_ts, future_ts)
                    if idx >= len(mid_ts):
                        continue
                    future_mid = mid_by_ts[mid_ts[idx]]
                ret = future_mid - m["mid"]
                pairs.append((net, ret))

            if len(pairs) < 100:
                continue
            # Quintile
            pairs.sort()
            n = len(pairs)
            q_size = n // 5
            print(f"{'Quintile':>20s}  {'n':>6s}  {'avg_ret':>10s}  {'hit_up%':>10s}")
            for q in range(5):
                slc = pairs[q*q_size:(q+1)*q_size]
                if not slc:
                    continue
                avg_net = sum(p[0] for p in slc) / len(slc)
                avg_ret = sum(p[1] for p in slc) / len(slc)
                hit_up = sum(1 for p in slc if p[1] > 0) / len(slc)
                print(f"  Q{q+1} (net={avg_net:+8.1f})  {len(slc):>6d}  {avg_ret:>+10.3f}  {hit_up*100:>9.1f}%")


if __name__ == "__main__":
    main()
