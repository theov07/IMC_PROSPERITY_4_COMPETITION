"""Deep counterparty analysis on VELVET R4 D1/D2/D3.

Per Rook-E1 advisor: classify each Mark as MM / Taker / Big participant.
Find: time patterns, volume bursts, direction-condition correlation.

Outputs:
  1. Per-trader classification (MM/taker/directional)
  2. Per-trader time-of-day distribution
  3. Per-trader volume burst detection
  4. Lead-lag: does Mark X's net flow predict next-N-tick mid move?
  5. Same-tick aggressor analysis: does Mark X tend to take or provide?
"""
from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_velvet_trades_with_offset(days=(1, 2, 3)):
    """Load all trades, compute global timestamp (day*1M + intraday ts)."""
    out = []
    for d in days:
        path = ROOT / "data" / "round_4" / f"trades_round_4_day_{d}.csv"
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                try:
                    if row["symbol"] != "VELVETFRUIT_EXTRACT":
                        continue
                    ts = int(row["timestamp"])
                    out.append({
                        "day": d,
                        "ts_intra": ts,
                        "ts_global": (d - 1) * 1_000_000 + ts,
                        "buyer": row.get("buyer", ""),
                        "seller": row.get("seller", ""),
                        "price": float(row["price"]),
                        "qty": int(row["quantity"]),
                    })
                except (ValueError, KeyError):
                    continue
    return out


def load_velvet_mid_with_offset(days=(1, 2, 3)):
    out = []
    for d in days:
        path = ROOT / "data" / "round_4" / f"prices_round_4_day_{d}.csv"
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                try:
                    if row["product"] != "VELVETFRUIT_EXTRACT":
                        continue
                    ts = int(row["timestamp"])
                    out.append({
                        "day": d,
                        "ts_intra": ts,
                        "ts_global": (d - 1) * 1_000_000 + ts,
                        "mid": float(row["mid_price"]),
                        "bb": float(row["bid_price_1"]) if row.get("bid_price_1") else None,
                        "ba": float(row["ask_price_1"]) if row.get("ask_price_1") else None,
                    })
                except (ValueError, KeyError):
                    continue
    return out


def classify_aggressor(trade, prev_mid):
    """Tick rule: trade above mid = aggressive BUY, below = aggressive SELL."""
    if prev_mid is None:
        return None
    if trade["price"] > prev_mid:
        return "buyer_aggressive"
    if trade["price"] < prev_mid:
        return "seller_aggressive"
    return "at_mid"


def main():
    print("Loading 3-day VELVET data with global timestamps...")
    trades = load_velvet_trades_with_offset()
    mids = load_velvet_mid_with_offset()
    print(f"  {len(trades):,} trades, {len(mids):,} mid points")

    # Build mid lookup by global ts
    mid_by_ts = {m["ts_global"]: m["mid"] for m in mids}
    sorted_ts = sorted(mid_by_ts.keys())

    def closest_mid(ts):
        from bisect import bisect_left
        idx = bisect_left(sorted_ts, ts)
        if idx == 0:
            return mid_by_ts[sorted_ts[0]]
        if idx >= len(sorted_ts):
            return mid_by_ts[sorted_ts[-1]]
        return mid_by_ts[sorted_ts[idx - 1]]

    def mid_at_offset(ts, offset_ticks):
        """Mid at ts + offset_ticks * 100. Returns None if past end."""
        target = ts + offset_ticks * 100
        if target > sorted_ts[-1]:
            return None
        from bisect import bisect_left
        idx = bisect_left(sorted_ts, target)
        if idx >= len(sorted_ts):
            return mid_by_ts[sorted_ts[-1]]
        return mid_by_ts[sorted_ts[idx]]

    # ===== Per-trader summary =====
    traders = set()
    for t in trades:
        if t["buyer"]:
            traders.add(t["buyer"])
        if t["seller"]:
            traders.add(t["seller"])

    print("\n" + "=" * 110)
    print("PER-TRADER CLASSIFICATION (MM / Taker / Big participant)")
    print("=" * 110)
    print(f"{'Trader':>10s}  {'n_trades':>8s}  {'vol_buy':>8s}  {'vol_sell':>8s}  {'buy/sell ratio':>14s}  {'avg_qty':>8s}  {'qty_std':>8s}  {'class':>20s}")
    print("-" * 110)

    classifications = {}
    for trader in sorted(traders):
        t_trades = []
        for t in trades:
            if t["buyer"] == trader:
                t_trades.append({"side": "BUY", "qty": t["qty"], "price": t["price"], "ts": t["ts_global"]})
            if t["seller"] == trader:
                t_trades.append({"side": "SELL", "qty": t["qty"], "price": t["price"], "ts": t["ts_global"]})
        if not t_trades:
            continue
        n = len(t_trades)
        vol_buy = sum(tt["qty"] for tt in t_trades if tt["side"] == "BUY")
        vol_sell = sum(tt["qty"] for tt in t_trades if tt["side"] == "SELL")
        ratio = vol_buy / vol_sell if vol_sell else float("inf")
        qtys = [tt["qty"] for tt in t_trades]
        avg_qty = statistics.mean(qtys)
        qty_std = statistics.stdev(qtys) if len(qtys) > 1 else 0

        # Classification heuristic:
        if 0.7 < ratio < 1.4:
            cls = "MARKET MAKER"
        elif ratio == float("inf") or ratio > 5:
            cls = "DIRECTIONAL BUYER"
        elif ratio < 0.2:
            cls = "DIRECTIONAL SELLER"
        elif ratio > 1.5:
            cls = "biased BUYER"
        else:
            cls = "biased SELLER"

        classifications[trader] = {
            "n": n, "vol_buy": vol_buy, "vol_sell": vol_sell,
            "ratio": ratio, "avg_qty": avg_qty, "class": cls,
        }
        print(
            f"{trader:>10s}  {n:>8d}  {vol_buy:>8d}  {vol_sell:>8d}  "
            f"{ratio:>14.2f}  {avg_qty:>8.1f}  {qty_std:>8.1f}  {cls:>20s}"
        )

    # ===== Lead-lag: does trader's NET FLOW in last K ticks predict next-N-tick return? =====
    print("\n" + "=" * 110)
    print("LEAD-LAG: trader's net flow in past 100 ticks → predicts return in next 50 ticks?")
    print("=" * 110)

    # For each tick (sample every 1000), compute trader net flow over past 100 ticks
    # and mid return over next 50 ticks. Then correlate per trader.
    sample_ticks = []
    for ts_global in sorted_ts[::100]:  # sample every 100 ticks
        sample_ticks.append(ts_global)

    # For each trader, compute (net_flow_past_100, return_next_50) pairs
    correlations = {}
    for trader in sorted(classifications.keys()):
        pairs = []
        for ts in sample_ticks:
            # Net flow past 100 ticks (10000 timestamp units)
            window_start = ts - 10000
            window_end = ts
            net = 0
            for t in trades:
                if t["ts_global"] < window_start or t["ts_global"] >= window_end:
                    continue
                if t["buyer"] == trader:
                    net += t["qty"]
                if t["seller"] == trader:
                    net -= t["qty"]
            # Return next 50 ticks
            mid_now = closest_mid(ts)
            mid_future = mid_at_offset(ts, 50)
            if mid_future is None or mid_now is None:
                continue
            ret = mid_future - mid_now
            if abs(net) > 5:  # only consider meaningful flow signals
                pairs.append((net, ret))

        if len(pairs) < 30:
            continue

        # Pearson correlation
        n_p = len(pairs)
        mean_x = sum(p[0] for p in pairs) / n_p
        mean_y = sum(p[1] for p in pairs) / n_p
        num = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pairs)
        den_x = math.sqrt(sum((p[0] - mean_x) ** 2 for p in pairs))
        den_y = math.sqrt(sum((p[1] - mean_y) ** 2 for p in pairs))
        if den_x * den_y == 0:
            continue
        rho = num / (den_x * den_y)

        # Hit rate: when |net|>10 and net>0, what % of the time does mid go up next 50 ticks?
        signal_buy = [p for p in pairs if p[0] > 10]
        signal_sell = [p for p in pairs if p[0] < -10]
        buy_hit = sum(1 for p in signal_buy if p[1] > 0) / len(signal_buy) if signal_buy else None
        sell_hit = sum(1 for p in signal_sell if p[1] < 0) / len(signal_sell) if signal_sell else None

        correlations[trader] = {
            "rho": rho, "n_pairs": n_p,
            "buy_signal_hit": buy_hit, "buy_signal_n": len(signal_buy),
            "sell_signal_hit": sell_hit, "sell_signal_n": len(signal_sell),
        }

    print(f"{'Trader':>10s}  {'rho':>8s}  {'n':>6s}  {'BUY signal hit%':>18s}  {'SELL signal hit%':>18s}  Class")
    print("-" * 110)
    for trader in sorted(correlations.keys(), key=lambda t: -abs(correlations[t]["rho"])):
        c = correlations[trader]
        cls = classifications[trader]["class"]
        bh = f"{c['buy_signal_hit']*100:.1f}% (n={c['buy_signal_n']})" if c["buy_signal_hit"] is not None else "n/a"
        sh = f"{c['sell_signal_hit']*100:.1f}% (n={c['sell_signal_n']})" if c["sell_signal_hit"] is not None else "n/a"
        print(f"{trader:>10s}  {c['rho']:>+8.3f}  {c['n_pairs']:>6d}  {bh:>18s}  {sh:>18s}  {cls}")

    # ===== Volume burst detection: do traders trade in bursts? =====
    print("\n" + "=" * 110)
    print("VOLUME BURST DETECTION: per-trader peak intensity (max trades per 1000-tick window)")
    print("=" * 110)
    print(f"{'Trader':>10s}  {'max trades/1000-tick':>22s}  {'avg trades/1000-tick':>22s}  {'burst factor':>14s}")
    print("-" * 110)
    for trader in sorted(classifications.keys()):
        # Bucket by 1000-tick (100k timestamp) windows
        buckets = defaultdict(int)
        for t in trades:
            if t["buyer"] != trader and t["seller"] != trader:
                continue
            bucket = t["ts_global"] // 100000  # 1000-tick bucket
            buckets[bucket] += 1
        if not buckets:
            continue
        max_trades = max(buckets.values())
        avg_trades = sum(buckets.values()) / len(buckets)
        burst = max_trades / avg_trades if avg_trades else 0
        print(f"{trader:>10s}  {max_trades:>22d}  {avg_trades:>22.1f}  {burst:>14.2f}x")

    # ===== Same-day directional bias: check Mark 67 specifically =====
    print("\n" + "=" * 110)
    print("MARK 67 specifically — does buy volume correlate with NEXT day return?")
    print("=" * 110)
    for d in (1, 2, 3):
        m67_trades = [t for t in trades if t["day"] == d and (t["buyer"] == "Mark 67" or t["seller"] == "Mark 67")]
        m67_buy = sum(t["qty"] for t in m67_trades if t["buyer"] == "Mark 67")
        m67_sell = sum(t["qty"] for t in m67_trades if t["seller"] == "Mark 67")
        # Day return
        day_mids = [m for m in mids if m["day"] == d]
        if day_mids:
            day_drift = day_mids[-1]["mid"] - day_mids[0]["mid"]
        else:
            day_drift = None
        print(f"  D{d}: Mark 67 BUY {m67_buy} / SELL {m67_sell} | day drift = {day_drift:+,.1f}")


if __name__ == "__main__":
    main()
