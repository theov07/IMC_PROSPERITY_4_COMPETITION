"""Generate synthetic enriched R2 data with +25% extra quotes.

The wiki says: "you can bid for 25% more quotes in the order book. The volumes
and prices of these quotes fit perfectly in the distribution of the already
available quotes."

Strategy for Monte Carlo synthetic generation:
  1. For each tick, identify gaps between L1 and L2 on each side
  2. Inject additional quotes inside those gaps at random prices (uniform within gap)
  3. Draw volumes from the empirical distribution of existing volumes
  4. Also occasionally inject quotes BELOW L1 bid or ABOVE L1 ask (rare — represents
     deeper book levels that the MAF reveals)
  5. Target: 25% more total volume across all levels per tick

Produces CSVs in data/round_2_synthetic_X/ where X is the seed number.

Usage:
    python research/round_2_MAF/01_generate_synthetic_data.py --seed 42 --n_seeds 5
"""
from __future__ import annotations
import argparse
import random
import sys
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "round_2"
OUT_BASE = ROOT / "data"


PRODUCTS = ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]
DAYS = [-1, 0, 1]


def parse_levels(row, side: str):
    """Extract populated levels [(price, vol), ...] for bid or ask."""
    out = []
    for i in (1, 2, 3):
        p = row.get(f"{side}_price_{i}")
        v = row.get(f"{side}_volume_{i}")
        if pd.notna(p) and pd.notna(v):
            out.append((int(p), int(v)))
    return out


def build_volume_distribution(df: pd.DataFrame):
    """Build empirical distribution of quote volumes for each product/side."""
    all_bid_vols = []
    all_ask_vols = []
    for _, row in df.iterrows():
        for (p, v) in parse_levels(row, "bid"):
            all_bid_vols.append(v)
        for (p, v) in parse_levels(row, "ask"):
            all_ask_vols.append(v)
    return np.array(all_bid_vols), np.array(all_ask_vols)


def enrich_row(row, bid_vol_dist, ask_vol_dist, rng: random.Random, target_extra_ratio: float = 0.25):
    """Inject additional quotes into a single tick's book.

    Strategy:
      - Compute current total volume
      - Target: add ~target_extra_ratio × current_total
      - Inject quotes between existing levels (fill gaps)
      - Draw volumes from empirical distribution
      - Probabilistic inclusion to avoid systematic overshoot
    """
    bid_levels = parse_levels(row, "bid")
    ask_levels = parse_levels(row, "ask")

    current_vol = sum(v for (_, v) in bid_levels) + sum(v for (_, v) in ask_levels)
    if current_vol == 0:
        return row  # nothing to enrich

    target_extra = current_vol * target_extra_ratio
    if target_extra <= 0:
        return row

    # Probabilistic gate to avoid systematic overshoot: only add a quote with
    # probability proportional to how far we still are from the target.
    mean_vol = (len(bid_vol_dist) and bid_vol_dist.mean() or 14) + (len(ask_vol_dist) and ask_vol_dist.mean() or 14)
    mean_vol = mean_vol / 2
    expected_quotes = target_extra / mean_vol   # how many quotes per side on average
    accept_prob = min(1.0, expected_quotes)

    # Create new quotes that fit in the gaps
    new_bids = []
    new_asks = []
    added = 0

    # Decide how many quotes to try adding this tick (Poisson-ish)
    max_quotes_per_side = 2 if rng.random() < accept_prob else (1 if rng.random() < accept_prob else 0)

    # Bid side: fill gaps between L1 and L2, or L2 and L3
    for _ in range(max_quotes_per_side):
        if added >= target_extra / 2:
            break
        # Choose a gap to fill
        if len(bid_levels) >= 2:
            # Pick a random pair and place a quote in between
            idx = rng.randrange(len(bid_levels) - 1)
            p_high, _ = bid_levels[idx]
            p_low, _ = bid_levels[idx + 1]
            if p_high - p_low >= 2:
                new_p = rng.randint(p_low + 1, p_high - 1)
                new_v = int(bid_vol_dist[rng.randrange(len(bid_vol_dist))])
                new_bids.append((new_p, new_v))
                added += new_v
            else:
                break
        elif len(bid_levels) == 1:
            # Only L1 present — add one below
            p1, _ = bid_levels[0]
            new_p = p1 - rng.randint(1, 5)
            new_v = int(bid_vol_dist[rng.randrange(len(bid_vol_dist))])
            new_bids.append((new_p, new_v))
            added += new_v
            break
        else:
            break

    # Ask side: symmetric
    for _ in range(max_quotes_per_side):
        if added >= target_extra:
            break
        if len(ask_levels) >= 2:
            idx = rng.randrange(len(ask_levels) - 1)
            p_low, _ = ask_levels[idx]
            p_high, _ = ask_levels[idx + 1]
            if p_high - p_low >= 2:
                new_p = rng.randint(p_low + 1, p_high - 1)
                new_v = int(ask_vol_dist[rng.randrange(len(ask_vol_dist))])
                new_asks.append((new_p, new_v))
                added += new_v
            else:
                break
        elif len(ask_levels) == 1:
            p1, _ = ask_levels[0]
            new_p = p1 + rng.randint(1, 5)
            new_v = int(ask_vol_dist[rng.randrange(len(ask_vol_dist))])
            new_asks.append((new_p, new_v))
            added += new_v
            break
        else:
            break

    # Merge: combine original + new, re-sort, keep top 3 on each side
    all_bids = sorted(bid_levels + new_bids, key=lambda x: -x[0])[:3]
    all_asks = sorted(ask_levels + new_asks, key=lambda x: x[0])[:3]

    # Pad with None if fewer than 3
    while len(all_bids) < 3:
        all_bids.append((None, None))
    while len(all_asks) < 3:
        all_asks.append((None, None))

    new_row = row.copy()
    for i, (p, v) in enumerate(all_bids, 1):
        new_row[f"bid_price_{i}"] = p
        new_row[f"bid_volume_{i}"] = v
    for i, (p, v) in enumerate(all_asks, 1):
        new_row[f"ask_price_{i}"] = p
        new_row[f"ask_volume_{i}"] = v

    # Recompute mid (if needed)
    best_bid = all_bids[0][0]
    best_ask = all_asks[0][0]
    if best_bid is not None and best_ask is not None:
        new_row["mid_price"] = (best_bid + best_ask) / 2.0

    return new_row


def enrich_day(day: int, seed: int, target_ratio: float = 0.25):
    """Enrich prices + trades CSVs for one day."""
    rng = random.Random(seed + day * 1000)

    prices_path = DATA_DIR / f"prices_round_2_day_{day}.csv"
    trades_path = DATA_DIR / f"trades_round_2_day_{day}.csv"

    if not prices_path.exists():
        print(f"WARN: {prices_path} not found, skipping day {day}")
        return None, None

    df_prices = pd.read_csv(prices_path, sep=";")
    df_trades = pd.read_csv(trades_path, sep=";") if trades_path.exists() else pd.DataFrame()

    # Build empirical volume distributions (per product)
    enriched_rows = []
    for product in PRODUCTS:
        df_prod = df_prices[df_prices["product"] == product].copy()
        bid_vol_dist, ask_vol_dist = build_volume_distribution(df_prod)
        if len(bid_vol_dist) == 0 or len(ask_vol_dist) == 0:
            enriched_rows.append(df_prod)
            continue
        enriched = df_prod.apply(
            lambda row: enrich_row(row, bid_vol_dist, ask_vol_dist, rng, target_ratio),
            axis=1,
        )
        enriched_rows.append(enriched)

    df_enriched = pd.concat(enriched_rows).sort_values(["timestamp", "product"]).reset_index(drop=True)
    return df_enriched, df_trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n_seeds", type=int, default=1, help="Generate N replicas with seeds [seed, seed+1, ...]")
    parser.add_argument("--ratio", type=float, default=0.25, help="Extra volume ratio (default 25%)")
    args = parser.parse_args()

    for s in range(args.n_seeds):
        seed = args.seed + s
        out_dir = OUT_BASE / f"round_2_synthetic_s{seed}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Generating seed={seed} → {out_dir} ===")
        for day in DAYS:
            df_prices, df_trades = enrich_day(day, seed=seed, target_ratio=args.ratio)
            if df_prices is None:
                continue
            prices_out = out_dir / f"prices_round_2_day_{day}.csv"
            trades_out = out_dir / f"trades_round_2_day_{day}.csv"
            df_prices.to_csv(prices_out, sep=";", index=False)
            if not df_trades.empty:
                df_trades.to_csv(trades_out, sep=";", index=False)

            # Stats
            orig = pd.read_csv(DATA_DIR / f"prices_round_2_day_{day}.csv", sep=";")
            orig_vol = 0
            new_vol = 0
            for _, row in orig.iterrows():
                for side in ("bid", "ask"):
                    for (p, v) in parse_levels(row, side):
                        orig_vol += v
            for _, row in df_prices.iterrows():
                for side in ("bid", "ask"):
                    for (p, v) in parse_levels(row, side):
                        new_vol += v
            ratio = new_vol / orig_vol if orig_vol else 0
            print(f"  day {day}: orig vol={orig_vol:,}, enriched vol={new_vol:,} (ratio={ratio:.3f}, target=1.25)")


if __name__ == "__main__":
    main()
