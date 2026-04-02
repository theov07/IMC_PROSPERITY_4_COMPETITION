"""Data analysis utilities for exploring round CSV data before coding strategies.

Usage:
  python research/analysis.py --data-dir data --round 0 --day -2

Produces:
  - Per-product summary: mean/std/min/max price, avg spread, avg volume
  - Bot activity report (most active traders, directional bias)
  - Price distribution plots
  - Correlation matrix between products
  - Volatility analysis
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from prosperity.tooling.data import MarketDataLoader
from prosperity.signals.bot_detector import BotDetector


def product_summary(prices_df: pd.DataFrame) -> Dict[str, Dict]:
    """Compute per-product statistics from prices CSV."""
    summaries = {}
    for product, group in prices_df.groupby("product"):
        mid = (group["bid_price_1"] + group["ask_price_1"]) / 2
        spread = group["ask_price_1"] - group["bid_price_1"]
        vol_bid = group["bid_volume_1"]
        vol_ask = group["ask_volume_1"]

        returns = mid.diff().dropna()
        realized_vol = returns.std() if len(returns) > 1 else 0.0

        summaries[str(product)] = {
            "ticks": len(group),
            "mid_mean": round(mid.mean(), 2),
            "mid_std": round(mid.std(), 2),
            "mid_min": round(mid.min(), 2),
            "mid_max": round(mid.max(), 2),
            "avg_spread": round(spread.mean(), 2),
            "min_spread": int(spread.min()),
            "max_spread": int(spread.max()),
            "avg_bid_vol": round(vol_bid.mean(), 1),
            "avg_ask_vol": round(vol_ask.mean(), 1),
            "realized_vol_per_tick": round(realized_vol, 4),
            "total_price_range": round(mid.max() - mid.min(), 2),
        }
    return summaries


def bot_report(trades_df: pd.DataFrame) -> Dict[str, List[Dict]]:
    """Analyze bot trading behavior per product."""
    detector = BotDetector()

    for _, row in trades_df.iterrows():
        from datamodel import Trade
        t = Trade(
            symbol=str(row["symbol"]),
            price=int(float(row["price"])),
            quantity=int(row["quantity"]),
            buyer=str(row["buyer"]) if pd.notna(row.get("buyer")) and row.get("buyer", "") != "" else None,
            seller=str(row["seller"]) if pd.notna(row.get("seller")) and row.get("seller", "") != "" else None,
            timestamp=int(row["timestamp"]),
        )
        detector.process_trades(str(row["symbol"]), [t])

    report = {}
    for symbol in detector.profiles:
        report[symbol] = detector.rank_bots(symbol)
    return report


def correlation_matrix(prices_df: pd.DataFrame) -> pd.DataFrame | None:
    """Compute correlation between product mid prices."""
    products = sorted(prices_df["product"].unique())
    if len(products) < 2:
        return None

    pivot = pd.DataFrame()
    for product in products:
        group = prices_df[prices_df["product"] == product].sort_values("timestamp")
        mid = ((group["bid_price_1"] + group["ask_price_1"]) / 2).reset_index(drop=True)
        pivot[product] = mid

    return pivot.corr()


def run_analysis(data_dir: str, round_num: int, day: str, output_dir: str = "artifacts/analysis"):
    loader = MarketDataLoader(data_dir)
    price_file = f"prices_round_{round_num}_day_{day}.csv"
    trade_file = f"trades_round_{round_num}_day_{day}.csv"

    prices_df = loader.load_prices(price_file)
    trades_df = loader.load_trades(trade_file)

    print(f"=== Round {round_num} Day {day} Analysis ===\n")

    # Product summaries
    summaries = product_summary(prices_df)
    print("--- Product Summary ---")
    for product, stats in summaries.items():
        print(f"\n  {product}:")
        for k, v in stats.items():
            print(f"    {k}: {v}")

    # Correlation
    corr = correlation_matrix(prices_df)
    if corr is not None:
        print("\n--- Correlation Matrix ---")
        print(corr.to_string())

    # Bot report
    report = bot_report(trades_df)
    print("\n--- Bot Activity ---")
    for symbol, bots in report.items():
        print(f"\n  {symbol} ({len(bots)} bots):")
        for b in bots[:10]:  # Top 10
            print(f"    {b['name']}: trades={b['total_trades']}, net_vol={b['net_volume']}, "
                  f"avg_buy={b['avg_buy_price']}, avg_sell={b['avg_sell_price']}")

    # Save JSON
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    result = {
        "round": round_num,
        "day": day,
        "product_summary": summaries,
        "bot_report": report,
    }
    json_path = out_path / f"analysis_round_{round_num}_day_{day}.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nSaved analysis to {json_path}")


def main():
    parser = argparse.ArgumentParser(description="Analyze round data")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--day", default="-2")
    parser.add_argument("--output-dir", default="artifacts/analysis")
    args = parser.parse_args()
    run_analysis(args.data_dir, args.round, args.day, args.output_dir)


if __name__ == "__main__":
    main()
