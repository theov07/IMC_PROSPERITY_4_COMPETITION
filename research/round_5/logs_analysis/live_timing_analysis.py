"""Per-product timing analysis of live PnL — when do losses happen?

For each product, plot/analyze:
  - Cumulative PnL over the 999 ticks
  - Max drawdown timestamp
  - Are losses front-loaded (warmup), back-loaded (end-of-day), or constant?

This addresses the overfit concern: if losses are ONLY at warmup, they may resolve.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "artifacts" / "r5_live"
OUT = ROOT / "artifacts" / "analysis" / "round_5"


def main():
    with open(LIVE / "550081.json", "rb") as f:
        data = json.load(f)
    df = pd.read_csv(io.StringIO(data["activitiesLog"]), sep=";")
    print(f"Live log: {len(df)} rows, ts range {df['timestamp'].min()}-{df['timestamp'].max()}")

    # For each product, get cumulative PnL trajectory (column profit_and_loss)
    print("\n=== Per-product PnL trajectory (5 worst live + 5 best) ===\n")

    final_pnl = df.sort_values("timestamp").groupby("product")["profit_and_loss"].last().sort_values()

    print("WORST 8 in live:")
    for prod in final_pnl.index[:8]:
        sub = df[df["product"] == prod].sort_values("timestamp")
        if len(sub) == 0: continue
        pnl = sub["profit_and_loss"].values
        ts = sub["timestamp"].values
        # When did the worst PnL happen?
        min_idx = pnl.argmin()
        # Quartile analysis
        q1_pnl = pnl[len(pnl)//4]
        q2_pnl = pnl[len(pnl)//2]
        q3_pnl = pnl[3*len(pnl)//4]
        final = pnl[-1]
        # Is it front-loaded (worst PnL in first quartile)?
        front_loaded = min_idx < len(pnl) // 4
        print(f"  {prod:<35} final={final:>8.0f}  q1={q1_pnl:>8.0f}  q2={q2_pnl:>8.0f}  q3={q3_pnl:>8.0f}  worst_at={ts[min_idx]}  front_loaded={front_loaded}")

    print("\nBEST 8 in live:")
    for prod in final_pnl.index[-8:]:
        sub = df[df["product"] == prod].sort_values("timestamp")
        if len(sub) == 0: continue
        pnl = sub["profit_and_loss"].values
        ts = sub["timestamp"].values
        max_idx = pnl.argmax()
        q1_pnl = pnl[len(pnl)//4]
        q2_pnl = pnl[len(pnl)//2]
        q3_pnl = pnl[3*len(pnl)//4]
        final = pnl[-1]
        print(f"  {prod:<35} final={final:>8.0f}  q1={q1_pnl:>8.0f}  q2={q2_pnl:>8.0f}  q3={q3_pnl:>8.0f}  peak_at={ts[max_idx]}  ")

    # Aggregated: what was the equity at each quartile?
    print("\n=== Aggregated equity at quartile timestamps ===")
    eq = pd.read_csv(io.StringIO(data["graphLog"]), sep=";")
    eq.columns = ["timestamp", "equity"]
    print(f"Equity at ts=25000: {eq[eq['timestamp']<=25000]['equity'].iloc[-1]:.0f}")
    print(f"Equity at ts=50000: {eq[eq['timestamp']<=50000]['equity'].iloc[-1]:.0f}")
    print(f"Equity at ts=75000: {eq[eq['timestamp']<=75000]['equity'].iloc[-1]:.0f}")
    print(f"Equity at end:      {eq['equity'].iloc[-1]:.0f}")

    # Per-product PnL by quartile
    rows = []
    for prod in df["product"].unique():
        sub = df[df["product"] == prod].sort_values("timestamp")
        if len(sub) < 4: continue
        pnl_ts = sub.set_index("timestamp")["profit_and_loss"]
        q_levels = [0, 25000, 50000, 75000, 100000]
        q_pnls = []
        for q in q_levels:
            in_range = pnl_ts[pnl_ts.index <= q]
            q_pnls.append(in_range.iloc[-1] if len(in_range) > 0 else 0)
        rows.append([prod] + q_pnls)
    df_q = pd.DataFrame(rows, columns=["product", "q0", "q1", "q2", "q3", "final"])
    df_q.to_csv(OUT / "live_pnl_quartiles.csv", index=False)
    print(f"\nSaved per-product quartile data to {OUT}/live_pnl_quartiles.csv")


if __name__ == "__main__":
    main()
