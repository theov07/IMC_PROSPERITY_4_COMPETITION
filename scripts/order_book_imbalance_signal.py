"""Order book imbalance (OBI) predictive analysis on VELVET R4 D1/D2/D3.

OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol) at L1, L2, L3.
Test:
  - Does OBI at tick T predict return at T+1, T+5, T+10, T+50 ticks?
  - Per-quintile of OBI, what's the average forward return?

If OBI > 0 strong (bid heavy) → market about to move UP, buy now.
If OBI < 0 (ask heavy) → market about to move DOWN.

This is well-known in HFT (microstructure literature, Cont/de Larrard model).
"""
from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import List, Dict

ROOT = Path(__file__).resolve().parent.parent


def load_prices_with_book(day: int, product: str = "VELVETFRUIT_EXTRACT"):
    """Load prices CSV with full L1 book."""
    path = ROOT / "data" / "round_4" / f"prices_round_4_day_{day}.csv"
    out = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                if row["product"] != product:
                    continue
                ts = int(row["timestamp"])
                mid = float(row["mid_price"])
                bv1 = int(float(row.get("bid_volume_1", 0) or 0))
                av1 = int(float(row.get("ask_volume_1", 0) or 0))
                bv2 = int(float(row.get("bid_volume_2", 0) or 0))
                av2 = int(float(row.get("ask_volume_2", 0) or 0))
                bv3 = int(float(row.get("bid_volume_3", 0) or 0))
                av3 = int(float(row.get("ask_volume_3", 0) or 0))
                out.append({"day": d_offset + ts // 1, "ts": ts, "mid": mid,
                            "bv1": bv1, "av1": av1,
                            "bv2": bv2, "av2": av2,
                            "bv3": bv3, "av3": av3,
                            "bv_total": bv1 + bv2 + bv3,
                            "av_total": av1 + av2 + av3})
            except (ValueError, KeyError):
                continue
    return out


def compute_obi(rec, levels=1):
    """OBI for a single book record."""
    bv = sum(rec[f"bv{i}"] for i in range(1, levels + 1))
    av = sum(rec[f"av{i}"] for i in range(1, levels + 1))
    total = bv + av
    if total == 0:
        return 0.0
    return (bv - av) / total


def predictive_test(records, levels=1, horizon_ticks=5):
    """For each record, OBI at T → return T+horizon. Bucket by quintile.

    Returns: dict of { quintile_label: {n, avg_return, hit_up_rate} }
    """
    pairs = []
    for i, r in enumerate(records):
        if i + horizon_ticks >= len(records):
            break
        obi = compute_obi(r, levels=levels)
        ret = records[i + horizon_ticks]["mid"] - r["mid"]
        pairs.append((obi, ret))

    # Sort by obi, split into 5 quintiles
    pairs.sort()
    n = len(pairs)
    if n < 100:
        return None
    q_size = n // 5
    quintiles = {}
    for q in range(5):
        slice_pairs = pairs[q * q_size: (q + 1) * q_size]
        if not slice_pairs:
            continue
        avg_obi = sum(p[0] for p in slice_pairs) / len(slice_pairs)
        avg_ret = sum(p[1] for p in slice_pairs) / len(slice_pairs)
        hit_up = sum(1 for p in slice_pairs if p[1] > 0) / len(slice_pairs)
        quintiles[f"Q{q+1} (OBI={avg_obi:+.2f})"] = {
            "n": len(slice_pairs), "avg_ret": avg_ret, "hit_up": hit_up,
            "avg_obi": avg_obi,
        }
    return quintiles


def main():
    print("=" * 100)
    print("ORDER BOOK IMBALANCE (OBI) PREDICTIVE TEST — VELVET R4 D1+D2+D3")
    print("=" * 100)

    all_records = []
    for d in (1, 2, 3):
        global d_offset
        d_offset = (d - 1) * 1_000_000
        all_records.extend(load_prices_with_book(d))
    print(f"Total records: {len(all_records):,}")

    for levels in (1, 3):
        for horizon in (1, 5, 10, 50):
            print(f"\n--- L{levels} OBI → return next {horizon} ticks ---")
            q = predictive_test(all_records, levels=levels, horizon_ticks=horizon)
            if q is None:
                continue
            print(f"{'Quintile':>20s}  {'n':>6s}  {'avg_ret':>10s}  {'hit_up%':>10s}")
            print("-" * 60)
            for label, stats in q.items():
                print(f"{label:>20s}  {stats['n']:>6d}  {stats['avg_ret']:>+10.3f}  {stats['hit_up']*100:>9.1f}%")


if __name__ == "__main__":
    main()
