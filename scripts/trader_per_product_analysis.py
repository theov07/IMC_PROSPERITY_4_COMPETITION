"""Per-product trader analysis on R4.

For each tradeable product (VELVET + 10 VEV options):
  1. Who are the active Marks?
  2. Per Mark: classification (MM / DirectionalBuyer / DirectionalSeller)
  3. Per Mark: net PnL on this product over 3 days
  4. Per Mark: lead-lag with that product's mid

Output: a big matrix of trader behaviors per product.
"""
from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRODUCTS = ["VELVETFRUIT_EXTRACT"] + [f"VEV_{k}" for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]]


def load_trades_per_product(days=(1, 2, 3)):
    """Returns: {product: [trade_dict, ...]}"""
    out = defaultdict(list)
    for d in days:
        offset = (d - 1) * 1_000_000
        path = ROOT / "data" / "round_4" / f"trades_round_4_day_{d}.csv"
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                try:
                    sym = row["symbol"]
                    out[sym].append({
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
    """Returns: {product: [(ts_global, mid), ...]}"""
    out = defaultdict(list)
    for d in days:
        offset = (d - 1) * 1_000_000
        path = ROOT / "data" / "round_4" / f"prices_round_4_day_{d}.csv"
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                try:
                    sym = row["product"]
                    out[sym].append((int(row["timestamp"]) + offset, float(row["mid_price"])))
                except Exception:
                    continue
    return out


def classify_trader(buy_vol, sell_vol):
    if buy_vol + sell_vol == 0:
        return "INACTIVE"
    ratio = buy_vol / sell_vol if sell_vol else float("inf")
    if 0.7 <= ratio <= 1.4:
        return "MM"
    elif ratio > 5 or ratio == float("inf"):
        return "BUYER"
    elif ratio < 0.2:
        return "SELLER"
    elif ratio > 1.5:
        return "biased_BUY"
    else:
        return "biased_SELL"


def compute_pnl(trades_for_trader, mid_at_end):
    cash, pos = 0.0, 0
    for t in trades_for_trader:
        cash += t["cash"]
        pos += t["pos_delta"]
    return cash + pos * mid_at_end


def main():
    print("Loading 3-day data...")
    trades_per_prod = load_trades_per_product()
    mids_per_prod = load_mids_per_product()

    # Per-product per-trader analysis
    print("\n" + "=" * 130)
    print("PER-PRODUCT PER-TRADER 3-DAY SUMMARY")
    print("=" * 130)
    print(f"{'Product':>22s}  {'Trader':>10s}  {'n_tr':>5s}  {'vol_buy':>8s}  {'vol_sell':>8s}  {'class':>12s}  {'PnL_3d':>12s}  {'avg_qty':>8s}")
    print("-" * 130)

    for prod in PRODUCTS:
        trades = trades_per_prod.get(prod, [])
        if not trades:
            continue
        mids = mids_per_prod.get(prod, [])
        mid_at_end = mids[-1][1] if mids else 0

        # Aggregate per trader
        per_trader = defaultdict(list)
        for t in trades:
            if t["buyer"]:
                per_trader[t["buyer"]].append({
                    "ts": t["ts"], "side": "BUY", "qty": t["qty"], "price": t["price"],
                    "cash": -t["price"] * t["qty"], "pos_delta": t["qty"],
                })
            if t["seller"]:
                per_trader[t["seller"]].append({
                    "ts": t["ts"], "side": "SELL", "qty": t["qty"], "price": t["price"],
                    "cash": +t["price"] * t["qty"], "pos_delta": -t["qty"],
                })

        if not per_trader:
            continue
        # Sort by total volume desc
        sorted_traders = sorted(per_trader.items(), key=lambda kv: -sum(t["qty"] for t in kv[1]))
        for trader, ts in sorted_traders:
            n = len(ts)
            buy_vol = sum(t["qty"] for t in ts if t["side"] == "BUY")
            sell_vol = sum(t["qty"] for t in ts if t["side"] == "SELL")
            cls = classify_trader(buy_vol, sell_vol)
            pnl = compute_pnl(ts, mid_at_end)
            avg_qty = (buy_vol + sell_vol) / n if n else 0
            print(f"{prod:>22s}  {trader:>10s}  {n:>5d}  {buy_vol:>8d}  {sell_vol:>8d}  "
                  f"{cls:>12s}  {pnl:>+12,.0f}  {avg_qty:>8.1f}")
        print()

    # Cross-trader correlation matrix on VELVET (do they buy/sell at same time?)
    print("\n" + "=" * 100)
    print("CROSS-TRADER CORRELATION on VELVET (do Marks buy/sell at same time?)")
    print("=" * 100)
    velvet_trades = trades_per_prod.get("VELVETFRUIT_EXTRACT", [])
    if velvet_trades:
        # Bucket by 100-tick (10000 ts) window
        bucket_size = 10000
        bucket_traders = defaultdict(lambda: defaultdict(int))  # bucket -> trader -> net_qty
        for t in velvet_trades:
            b = t["ts"] // bucket_size
            if t["buyer"]:
                bucket_traders[b][t["buyer"]] += t["qty"]
            if t["seller"]:
                bucket_traders[b][t["seller"]] -= t["qty"]

        # Get all traders
        all_traders = set()
        for buckets in bucket_traders.values():
            all_traders.update(buckets.keys())
        traders_sorted = sorted(all_traders)

        # Build vectors per trader
        bucket_keys = sorted(bucket_traders.keys())
        vectors = {t: [bucket_traders[b].get(t, 0) for b in bucket_keys] for t in traders_sorted}

        # Pairwise Pearson
        print(f"\n{'Pair':>22s}  {'rho':>8s}  {'interpretation':>25s}")
        print("-" * 70)
        for i in range(len(traders_sorted)):
            for j in range(i + 1, len(traders_sorted)):
                t1, t2 = traders_sorted[i], traders_sorted[j]
                xs, ys = vectors[t1], vectors[t2]
                n = len(xs)
                mean_x, mean_y = sum(xs) / n, sum(ys) / n
                num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
                den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
                den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
                if den_x * den_y == 0:
                    continue
                rho = num / (den_x * den_y)
                if abs(rho) < 0.1:
                    continue  # skip insignificant
                interp = "🟢 SAME side" if rho > 0.3 else ("🔴 OPPOSITE" if rho < -0.3 else "weak")
                print(f"{t1+' vs '+t2:>22s}  {rho:>+8.3f}  {interp:>25s}")


if __name__ == "__main__":
    main()
