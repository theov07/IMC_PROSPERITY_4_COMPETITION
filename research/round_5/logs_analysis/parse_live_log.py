"""Parse IMC live log (JSON + .log) for round 5 r5_v2_winners_only submission.

Key questions:
  1. What's the per-product PnL distribution?
  2. How many fills per product? At what prices?
  3. Compare live-fill rate to backtest realistic-fill rate.
  4. Where is PnL coming from / leaking?

Inputs : artifacts/r5_live/550081.{json,log}
Outputs: artifacts/r5_live/analysis/
"""
from __future__ import annotations

import io
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "artifacts" / "r5_live"
OUT = LIVE / "analysis"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    print("Loading 550081.json...")
    with open(LIVE / "550081.json", "rb") as f:
        data = json.load(f)

    print(f"Submission: round={data['round']}, status={data['status']}, profit={data['profit']:,.2f}")

    # === 1. Activities log -> per-tick prices snapshot ===
    print("\n=== Parsing activitiesLog (price snapshots) ===")
    activities = data["activitiesLog"]
    # CSV with ; sep
    df_prices = pd.read_csv(io.StringIO(activities), sep=";")
    print(f"Rows: {len(df_prices)}")
    print(f"Days: {sorted(df_prices['day'].unique())}")
    print(f"Timestamps range: {df_prices['timestamp'].min()} .. {df_prices['timestamp'].max()}")
    print(f"Products: {df_prices['product'].nunique()}")
    print(f"PnL column total per product: ")
    last_pnl = df_prices.sort_values("timestamp").groupby("product")["profit_and_loss"].last()
    print(last_pnl.sort_values(ascending=False).to_string())
    last_pnl.to_csv(OUT / "live_per_product_pnl.csv")
    total = last_pnl.sum()
    print(f"\nLive total per-product PnL sum: {total:,.2f}")
    print(f"JSON-reported profit:           {data['profit']:,.2f}")

    # === 2. Graph log -> equity curve ===
    print("\n=== Parsing graphLog (equity curve) ===")
    graph = data["graphLog"]
    df_eq = pd.read_csv(io.StringIO(graph), sep=";")
    df_eq.columns = ["timestamp", "equity"]
    print(f"Equity ticks: {len(df_eq)}")
    print(f"Equity start: {df_eq.iloc[0]['equity']:.2f}")
    print(f"Equity end:   {df_eq.iloc[-1]['equity']:.2f}")
    print(f"Equity max:   {df_eq['equity'].max():.2f}")
    print(f"Equity min:   {df_eq['equity'].min():.2f}")
    rolling_dd = (df_eq['equity'].cummax() - df_eq['equity']).max()
    print(f"Max drawdown: {rolling_dd:.2f}")
    df_eq.to_csv(OUT / "live_equity.csv", index=False)

    # === 3. Positions ===
    print("\n=== Final positions ===")
    pos_df = pd.DataFrame(data["positions"])
    print(pos_df.to_string(index=False))
    pos_df.to_csv(OUT / "live_final_positions.csv", index=False)

    # === 4. .log file -> trader logs (output from print() in submission) ===
    print("\n=== Parsing .log file ===")
    with open(LIVE / "550081.log", "rb") as f:
        log_raw = f.read()
    print(f".log size: {len(log_raw):,} bytes")
    # The .log usually contains the full TradingState dump per tick
    # Parse it line by line
    text = log_raw.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    print(f".log lines: {len(lines):,}")
    # Look at first non-empty lines
    first_nonempty = [l for l in lines[:20] if l.strip()][:5]
    for l in first_nonempty:
        print("  ", l[:200])

    # === 5. Per-product summary table for backtest comparison ===
    print("\n=== Per-product summary ===")
    summary = pd.DataFrame({
        "live_pnl": last_pnl,
    }).sort_values("live_pnl", ascending=False)
    print(summary.head(20).to_string())
    print("\n--- BOTTOM 20 ---")
    print(summary.tail(20).to_string())

    summary.to_csv(OUT / "live_per_product_pnl_sorted.csv")
    print(f"\nDone. Outputs in {OUT}")


if __name__ == "__main__":
    main()
