"""VPIN + VWAP analysis on VELVET R4 D1/D2/D3.

VPIN (Volume-Synchronized Probability of Informed Trading):
  Bucket trades by equal volume. For each bucket, compute |buy_vol - sell_vol| / total_vol.
  EWMA the result. High VPIN = informed/toxic flow regime.

VWAP:
  Compute volume-weighted average price.
  Track distance: mid - vwap.
  Plot trajectory.

Output: console summary + per-day stats. Identifies regime windows.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_velvet_trades(day: int):
    path = ROOT / "data" / "round_4" / f"trades_round_4_day_{day}.csv"
    out = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                if row["symbol"] != "VELVETFRUIT_EXTRACT":
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


def load_velvet_prices(day: int):
    path = ROOT / "data" / "round_4" / f"prices_round_4_day_{day}.csv"
    out = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                if row["product"] != "VELVETFRUIT_EXTRACT":
                    continue
                out.append({
                    "ts": int(row["timestamp"]),
                    "mid": float(row["mid_price"]),
                    "bb": float(row["bid_price_1"]) if row.get("bid_price_1") else None,
                    "ba": float(row["ask_price_1"]) if row.get("ask_price_1") else None,
                })
            except (ValueError, KeyError):
                continue
    return out


def classify_aggressor(trade, prev_mid):
    """Lee-Ready: trade above mid → aggressive BUY (taker), below → aggressive SELL."""
    if prev_mid is None:
        return 0  # unknown
    if trade["price"] > prev_mid:
        return 1  # aggressive buy
    if trade["price"] < prev_mid:
        return -1  # aggressive sell
    return 0  # at-mid (use buyer/seller heuristic)


def compute_vpin(trades, prices, bucket_volume=200, ewma_alpha=0.05):
    """Compute VPIN trajectory. Returns list of (ts, vpin)."""
    # Build mid lookup
    mid_by_ts = {p["ts"]: p["mid"] for p in prices}
    sorted_ts = sorted(mid_by_ts.keys())

    def closest_mid(ts):
        # Find closest tick (Lee-Ready uses prev quote, but here mids are at trade ticks)
        idx = max(0, min(len(sorted_ts) - 1, _bisect_left(sorted_ts, ts) - 1))
        return mid_by_ts[sorted_ts[idx]]

    bucket_buy = 0
    bucket_sell = 0
    vpin_traj = []
    vpin_ewma = None
    prev_mid = None
    for t in sorted(trades, key=lambda x: x["ts"]):
        prev_mid = closest_mid(t["ts"])
        side = classify_aggressor(t, prev_mid)
        qty = t["qty"]
        if side > 0:
            bucket_buy += qty
        elif side < 0:
            bucket_sell += qty
        else:
            # split 50/50
            bucket_buy += qty / 2
            bucket_sell += qty / 2

        total = bucket_buy + bucket_sell
        if total >= bucket_volume:
            vpin_inst = abs(bucket_buy - bucket_sell) / total
            vpin_ewma = vpin_inst if vpin_ewma is None else (
                ewma_alpha * vpin_inst + (1 - ewma_alpha) * vpin_ewma
            )
            vpin_traj.append((t["ts"], vpin_ewma))
            bucket_buy = 0
            bucket_sell = 0
    return vpin_traj


def _bisect_left(arr, x):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def compute_vwap(trades, window_ts=50000):
    """Rolling VWAP over `window_ts` timestamp window. Returns list of (ts, vwap)."""
    out = []
    for i, t in enumerate(trades):
        # Look back window_ts ticks
        cutoff = t["ts"] - window_ts
        relevant = [u for u in trades[:i+1] if u["ts"] >= cutoff]
        if not relevant:
            continue
        total_qty = sum(u["qty"] for u in relevant)
        if total_qty == 0:
            continue
        vwap = sum(u["price"] * u["qty"] for u in relevant) / total_qty
        out.append((t["ts"], vwap))
    return out


def main():
    print("=" * 100)
    print("VPIN + VWAP ANALYSIS — VELVETFRUIT_EXTRACT R4 D1/D2/D3")
    print("=" * 100)

    for day in (1, 2, 3):
        print(f"\n--- Day {day} ---")
        trades = load_velvet_trades(day)
        prices = load_velvet_prices(day)
        if not trades:
            print(f"  No trades")
            continue
        print(f"  {len(trades):,} trades, {len(prices):,} mid points")

        # VPIN
        vpin_traj = compute_vpin(trades, prices, bucket_volume=200, ewma_alpha=0.05)
        if vpin_traj:
            mean_vpin = sum(v for _, v in vpin_traj) / len(vpin_traj)
            max_vpin = max(v for _, v in vpin_traj)
            min_vpin = min(v for _, v in vpin_traj)
            # When did max VPIN occur?
            max_ts = max(vpin_traj, key=lambda x: x[1])[0]
            print(f"  VPIN buckets: {len(vpin_traj)}, mean={mean_vpin:.3f}, max={max_vpin:.3f} (at ts={max_ts:,})")
            # Sample at key checkpoints
            sample_pcts = [10, 25, 50, 75, 90, 95, 99]
            sample_str = []
            for pct in sample_pcts:
                if vpin_traj:
                    idx = min(int(len(vpin_traj) * pct / 100), len(vpin_traj) - 1)
                    sample_str.append(f"{pct}%={vpin_traj[idx][1]:.3f}")
            print(f"  VPIN trajectory: " + ", ".join(sample_str))

        # VWAP analysis
        vwap_traj = compute_vwap(trades, window_ts=50000)
        if vwap_traj and prices:
            mid_at_end = prices[-1]["mid"]
            vwap_at_end = vwap_traj[-1][1] if vwap_traj else None
            # Distance mid - vwap at end
            print(f"  Final mid: {mid_at_end:,.1f}, final VWAP(50k): {vwap_at_end:,.1f}, mid-vwap: {mid_at_end - vwap_at_end:+,.1f}")

            # Daily price range
            prices_only = [p["mid"] for p in prices]
            print(f"  Day mid range: {min(prices_only):,.1f} - {max(prices_only):,.1f} (drift: {prices[-1]['mid'] - prices[0]['mid']:+,.1f})")


if __name__ == "__main__":
    main()
