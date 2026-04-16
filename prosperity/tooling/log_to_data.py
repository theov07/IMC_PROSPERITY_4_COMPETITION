"""Reverse-engineer IMC official logs into backtest-ready CSV data.

Usage:
    python -m prosperity.tooling.log_to_data --log logs/round_1/leo/best_osmium_log/170620.json --round 1 --day live
    python -m prosperity.tooling.log_to_data --log-dir C:/Users/.../tibo_best_osmium --round 1 --day live

This produces:
    data/round_{round}/prices_round_{round}_day_{day}.csv
    data/round_{round}/trades_round_{round}_day_{day}.csv

The prices CSV is extracted directly from the activitiesLog field in the JSON.
The trades CSV is empty (no market trade data in logs), so backtest will run
with --match-trades none (taker-only) or queue/realistic with 0 passive fills.

Multiple logs can be combined: if --log-dir is used, all .json files in the
directory are merged. If logs from the same submission have different books
at the same timestamp (because our orders changed the book), the FIRST log's
book is used (they should all be identical since the market state is the same
for all submissions in the same round).
"""
from __future__ import annotations

import argparse
import json
import sys
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


def parse_activities_log(raw: str) -> pd.DataFrame:
    """Parse the activitiesLog semicolon-delimited string into a DataFrame."""
    df = pd.read_csv(StringIO(raw), sep=";")
    df.columns = [c.strip() for c in df.columns]
    return df


def load_log(path: Path) -> dict:
    """Load a single IMC log JSON file."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        # Handle both .json and .log files (same format, .log is single-line JSON)
        content = f.read().strip()
        return json.loads(content)


def extract_prices_df(data: dict) -> pd.DataFrame:
    """Extract the prices DataFrame from a parsed log."""
    raw = data.get("activitiesLog", "")
    if not raw:
        raise ValueError("No activitiesLog found in log file")
    return parse_activities_log(raw)


def merge_prices(dfs: List[pd.DataFrame]) -> pd.DataFrame:
    """Merge multiple price DataFrames, keeping first occurrence per (timestamp, product)."""
    if len(dfs) == 1:
        return dfs[0]
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp", "product"], keep="first")
    return combined.sort_values(["timestamp", "product"]).reset_index(drop=True)


def create_empty_trades_df() -> pd.DataFrame:
    """Create an empty trades DataFrame with the correct columns."""
    return pd.DataFrame(columns=["timestamp", "buyer", "seller", "symbol", "currency", "price", "quantity"])


def write_data(prices_df: pd.DataFrame, round_num: int, day: str, data_dir: Path):
    """Write prices and trades CSVs to the data directory."""
    round_dir = data_dir / f"round_{round_num}"
    round_dir.mkdir(parents=True, exist_ok=True)

    prices_path = round_dir / f"prices_round_{round_num}_day_{day}.csv"
    trades_path = round_dir / f"trades_round_{round_num}_day_{day}.csv"

    prices_df.to_csv(prices_path, sep=";", index=False)
    trades_df = create_empty_trades_df()
    trades_df.to_csv(trades_path, sep=";", index=False)

    products = prices_df["product"].unique()
    timestamps = sorted(prices_df["timestamp"].unique())
    n_ticks = len(timestamps)

    print(f"Wrote {prices_path} ({len(prices_df)} rows, {len(products)} products, {n_ticks} ticks)")
    print(f"  Products: {', '.join(sorted(products))}")
    print(f"  Timestamps: {timestamps[0]} -> {timestamps[-1]} (step={timestamps[1]-timestamps[0] if n_ticks > 1 else '?'})")
    print(f"Wrote {trades_path} (empty — no market trades in logs)")

    # Print profit info if available
    for p in products:
        sub = prices_df[prices_df["product"] == p]
        if "profit_and_loss" in sub.columns:
            final_pnl = sub.iloc[-1]["profit_and_loss"]
            print(f"  {p}: final PnL from log = {final_pnl}")


def print_summary(data: dict):
    """Print a summary of the log file."""
    print(f"  Status: {data.get('status', '?')}")
    print(f"  Profit: {data.get('profit', '?')}")
    if "positions" in data:
        for pos in data["positions"]:
            print(f"  Position: {pos.get('symbol', '?')} = {pos.get('quantity', '?')}")


def main():
    parser = argparse.ArgumentParser(description="Convert IMC logs to backtest data")
    parser.add_argument("--log", type=str, nargs="*", help="Path(s) to .json or .log file(s)")
    parser.add_argument("--log-dir", type=str, help="Directory containing .json/.log files")
    parser.add_argument("--round", type=int, required=True, help="Round number")
    parser.add_argument("--day", type=str, required=True, help="Day label for output files (e.g. 'live', 'live1')")
    parser.add_argument("--data-dir", type=str, default="data", help="Output data directory (default: data)")
    args = parser.parse_args()

    log_paths: List[Path] = []
    if args.log:
        log_paths.extend(Path(p) for p in args.log)
    if args.log_dir:
        log_dir = Path(args.log_dir)
        log_paths.extend(sorted(log_dir.glob("*.json")))
        log_paths.extend(sorted(log_dir.glob("*.log")))

    if not log_paths:
        print("Error: provide --log or --log-dir", file=sys.stderr)
        sys.exit(1)

    # Deduplicate (in case .json and .log have same content)
    seen_stems: set = set()
    unique_paths: List[Path] = []
    for p in log_paths:
        if p.stem not in seen_stems:
            seen_stems.add(p.stem)
            unique_paths.append(p)
    log_paths = unique_paths

    print(f"Loading {len(log_paths)} log file(s)...")
    all_dfs: List[pd.DataFrame] = []
    for path in log_paths:
        print(f"\n  {path.name}:")
        data = load_log(path)
        print_summary(data)
        df = extract_prices_df(data)
        all_dfs.append(df)

    prices_df = merge_prices(all_dfs)
    print()
    write_data(prices_df, args.round, args.day, Path(args.data_dir))
    print(f"\nBacktest with: python backtest.py --strategy <name> --round {args.round} --days {args.day} --match-trades none")


if __name__ == "__main__":
    main()
