"""Run a backtest and emit an IMC-format JSON log (activitiesLog + trades).

Output is consumable by `prosperity.tooling.dashboard`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd

from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode


ACTIVITY_COLUMNS = [
    "day", "timestamp", "product",
    "bid_price_1", "bid_volume_1", "bid_price_2", "bid_volume_2", "bid_price_3", "bid_volume_3",
    "ask_price_1", "ask_volume_1", "ask_price_2", "ask_volume_2", "ask_price_3", "ask_volume_3",
    "mid_price", "profit_and_loss",
]


def _running_pnl(day_df: pd.DataFrame, fills_df: pd.DataFrame) -> pd.DataFrame:
    """Replace profit_and_loss with running (cash + pos*mid) per product per tick."""
    out_rows: List[Dict] = []
    cash: Dict[str, float] = {}
    pos: Dict[str, int] = {}

    fills_by_ts: Dict[int, List[Dict]] = {}
    for _, f in fills_df.iterrows():
        fills_by_ts.setdefault(int(f["timestamp"]), []).append(f.to_dict())

    for ts in sorted(day_df["timestamp"].unique()):
        for f in fills_by_ts.get(int(ts), []):
            sym = f["symbol"]
            qty = int(f["quantity"])
            px = float(f["price"])
            if f["side"] == "BUY":
                cash[sym] = cash.get(sym, 0.0) - px * qty
                pos[sym] = pos.get(sym, 0) + qty
            else:
                cash[sym] = cash.get(sym, 0.0) + px * qty
                pos[sym] = pos.get(sym, 0) - qty

        tick_rows = day_df[day_df["timestamp"] == ts]
        for _, r in tick_rows.iterrows():
            row = r.to_dict()
            sym = row["product"]
            mid = row.get("mid_price")
            if pd.notna(mid):
                row["profit_and_loss"] = cash.get(sym, 0.0) + pos.get(sym, 0) * float(mid)
            out_rows.append(row)

    return pd.DataFrame(out_rows, columns=ACTIVITY_COLUMNS)


def _df_to_semicolon(df: pd.DataFrame) -> str:
    lines = [";".join(df.columns)]
    for _, row in df.iterrows():
        cells = []
        for col in df.columns:
            v = row[col]
            if pd.isna(v):
                cells.append("")
            else:
                cells.append(str(v))
        lines.append(";".join(cells))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--member", required=True, help="e.g. leo_osmium_only")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--days", nargs="+", default=["-2", "-1", "0"])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--output", required=True)
    ap.add_argument("--execution-rule", default="realistic")
    args = ap.parse_args()

    eng = BacktestEngine(Path(args.data_dir), f"submissions.{args.member}", round_num=args.round)
    mode = TradeMatchingMode(args.execution_rule)

    all_activities: List[pd.DataFrame] = []
    all_trades: List[Dict] = []

    for d in args.days:
        summary = eng.run_day(d, mode=mode)
        csv_path = Path(args.data_dir) / f"round_{args.round}" / f"prices_round_{args.round}_day_{d}.csv"
        day_df = pd.read_csv(csv_path, sep=";")
        for col in ACTIVITY_COLUMNS:
            if col not in day_df.columns:
                day_df[col] = None
        day_df = day_df[ACTIVITY_COLUMNS]

        fills_df = pd.DataFrame([
            {"timestamp": f.timestamp, "symbol": f.symbol, "side": f.side,
             "price": f.price, "quantity": f.quantity, "aggressive": f.aggressive}
            for f in summary.fills
        ])

        enriched = _running_pnl(day_df, fills_df) if not fills_df.empty else day_df
        all_activities.append(enriched)

        for f in summary.fills:
            all_trades.append({
                "timestamp": int(f.timestamp),
                "buyer": "SUBMISSION" if f.side == "BUY" else "",
                "seller": "SUBMISSION" if f.side == "SELL" else "",
                "symbol": f.symbol,
                "currency": "SEASHELLS",
                "price": float(f.price),
                "quantity": int(f.quantity),
            })

        print(f"day {d}: pnl={summary.pnl:.0f} fills={len(summary.fills)}", flush=True)

    activities_df = pd.concat(all_activities, ignore_index=True)
    activities_text = _df_to_semicolon(activities_df)

    payload = {
        "submissionId": f"local-backtest-{args.member}",
        "activitiesLog": activities_text,
        "trades": all_trades,
        "graphLog": "",
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload), encoding="utf-8")
    print(f"\nWrote IMC-format log: {args.output} ({len(activities_df)} rows, {len(all_trades)} trades)")


if __name__ == "__main__":
    main()
