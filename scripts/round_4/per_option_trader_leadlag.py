"""Per-option trader lead-lag analysis.

For EACH product (VELVET + 10 VEV options), compute which Marks' net flow over
the past 100 ticks predicts that product's mid return over the next 50 ticks.

Outputs:
  - Per-product correlation matrix per Mark
  - Best follow/fade signal per product
  - Recommended weights per product
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PRODUCTS = ["VELVETFRUIT_EXTRACT"] + [f"VEV_{k}" for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]]


def load_trades_per_product(days=(1, 2, 3)):
    out = defaultdict(list)
    for d in days:
        offset = (d - 1) * 1_000_000
        path = ROOT / "data" / "round_4" / f"trades_round_4_day_{d}.csv"
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                try:
                    out[row["symbol"]].append({
                        "ts": int(row["timestamp"]) + offset,
                        "buyer": row.get("buyer", "") or "",
                        "seller": row.get("seller", "") or "",
                        "price": float(row["price"]),
                        "qty": int(row["quantity"]),
                    })
                except Exception:
                    continue
    return out


def load_mids_per_product(days=(1, 2, 3)):
    out = defaultdict(list)
    for d in days:
        offset = (d - 1) * 1_000_000
        path = ROOT / "data" / "round_4" / f"prices_round_4_day_{d}.csv"
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                try:
                    out[row["product"]].append((int(row["timestamp"]) + offset, float(row["mid_price"])))
                except Exception:
                    continue
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 30:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx * dy == 0:
        return None
    return num / (dx * dy)


def main():
    print("Loading 3-day data per product...")
    trades_per = load_trades_per_product()
    mids_per = load_mids_per_product()

    # Window settings
    flow_window = 10000  # 100 ticks past
    return_horizon = 5000  # 50 ticks ahead

    print("\n" + "=" * 130)
    print("PER-PRODUCT TRADER LEAD-LAG (100-tick net flow → 50-tick forward return)")
    print("=" * 130)

    for prod in PRODUCTS:
        trades = trades_per.get(prod, [])
        mids = mids_per.get(prod, [])
        if len(trades) < 50 or len(mids) < 100:
            continue

        # Build mid lookup
        mid_by_ts = dict(mids)
        sorted_mid_ts = sorted(mid_by_ts.keys())
        from bisect import bisect_left

        def mid_at(ts):
            idx = bisect_left(sorted_mid_ts, ts)
            if idx == 0:
                return mid_by_ts[sorted_mid_ts[0]]
            if idx >= len(sorted_mid_ts):
                return mid_by_ts[sorted_mid_ts[-1]]
            return mid_by_ts[sorted_mid_ts[idx - 1]]

        # Sample at every-100-tick checkpoints
        sample_ts = sorted_mid_ts[::100]

        # Identify all traders for this product
        traders = set()
        for t in trades:
            if t["buyer"]:
                traders.add(t["buyer"])
            if t["seller"]:
                traders.add(t["seller"])
        traders = sorted(traders)

        # Per-trader net flow vectors + return vectors
        per_trader_pairs = {tr: [] for tr in traders}
        for ts in sample_ts:
            mid_now = mid_at(ts)
            future_ts = ts + return_horizon
            if future_ts > sorted_mid_ts[-1]:
                continue
            mid_future = mid_at(future_ts)
            ret = mid_future - mid_now

            # Net flow per trader in past flow_window
            window_start = ts - flow_window
            net_flow = defaultdict(int)
            for t in trades:
                if t["ts"] < window_start or t["ts"] >= ts:
                    continue
                if t["buyer"]:
                    net_flow[t["buyer"]] += t["qty"]
                if t["seller"]:
                    net_flow[t["seller"]] -= t["qty"]

            for tr in traders:
                per_trader_pairs[tr].append((net_flow.get(tr, 0), ret))

        # Compute correlations + hit rates
        print(f"\n--- {prod} ({len(trades):,} trades, {len(sample_ts):,} samples) ---")
        print(f"{'Trader':>10s}  {'rho':>8s}  {'n_buy':>6s}  {'buy_hit%':>10s}  {'n_sell':>6s}  {'sell_hit%':>10s}  Action")
        print("-" * 100)
        rows = []
        for tr in traders:
            pairs = per_trader_pairs[tr]
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            rho = pearson(xs, ys)
            if rho is None:
                continue
            # Hit rates: when net flow > +5, did mid go up?
            buy_signals = [(x, y) for x, y in pairs if x > 5]
            sell_signals = [(x, y) for x, y in pairs if x < -5]
            buy_hit = (sum(1 for _, y in buy_signals if y > 0) / len(buy_signals)) if buy_signals else None
            sell_hit = (sum(1 for _, y in sell_signals if y < 0) / len(sell_signals)) if sell_signals else None

            action = ""
            if abs(rho) > 0.10:
                if rho > 0:
                    action = f"FOLLOW (rho={rho:+.2f})"
                else:
                    action = f"FADE (rho={rho:+.2f})"
            else:
                action = "weak"
            rows.append((tr, rho, buy_signals, sell_signals, buy_hit, sell_hit, action))

        # Sort by abs(rho) desc
        rows.sort(key=lambda r: -abs(r[1]))
        for tr, rho, bs, ss, bh, sh, action in rows:
            bh_str = f"{bh*100:>9.1f}%" if bh is not None else "n/a".rjust(10)
            sh_str = f"{sh*100:>9.1f}%" if sh is not None else "n/a".rjust(10)
            print(f"{tr:>10s}  {rho:>+8.3f}  {len(bs):>6d}  {bh_str:>10s}  {len(ss):>6d}  {sh_str:>10s}  {action}")

    # Final recommendations
    print("\n" + "=" * 130)
    print("RECOMMENDED PER-PRODUCT WEIGHTS (rho-based, only signals with |rho| > 0.10 and n_signals > 30)")
    print("=" * 130)
    for prod in PRODUCTS:
        trades = trades_per.get(prod, [])
        mids = mids_per.get(prod, [])
        if len(trades) < 50 or len(mids) < 100:
            continue
        # Re-do the analysis briefly for output
        mid_by_ts = dict(mids)
        sorted_mid_ts = sorted(mid_by_ts.keys())
        from bisect import bisect_left
        def mid_at(ts):
            idx = bisect_left(sorted_mid_ts, ts)
            if idx == 0:
                return mid_by_ts[sorted_mid_ts[0]]
            if idx >= len(sorted_mid_ts):
                return mid_by_ts[sorted_mid_ts[-1]]
            return mid_by_ts[sorted_mid_ts[idx - 1]]
        sample_ts = sorted_mid_ts[::100]

        traders = set()
        for t in trades:
            if t["buyer"]: traders.add(t["buyer"])
            if t["seller"]: traders.add(t["seller"])

        weights = {}
        for tr in sorted(traders):
            pairs = []
            for ts in sample_ts:
                future_ts = ts + return_horizon
                if future_ts > sorted_mid_ts[-1]:
                    continue
                window_start = ts - flow_window
                net = 0
                for t in trades:
                    if t["ts"] < window_start or t["ts"] >= ts:
                        continue
                    if t["buyer"] == tr: net += t["qty"]
                    if t["seller"] == tr: net -= t["qty"]
                pairs.append((net, mid_at(future_ts) - mid_at(ts)))
            if len(pairs) < 30:
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            rho = pearson(xs, ys)
            n_signal = sum(1 for x in xs if abs(x) > 5)
            if rho is None or abs(rho) < 0.10 or n_signal < 30:
                continue
            # Weight = rho (negative for fade, positive for follow), capped at +/- 1
            weights[tr] = round(max(-1.0, min(1.0, rho * 5)), 2)  # rho usually 0.1-0.3 → weight 0.5-1.5
        if weights:
            print(f"\n  {prod}: {weights}")


if __name__ == "__main__":
    main()
