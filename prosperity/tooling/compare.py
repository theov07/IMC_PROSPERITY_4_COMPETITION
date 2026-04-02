"""Compare multiple strategies side-by-side.

Usage:
  python -m prosperity.tooling.compare \
    --strategies champion leo theo pietro \
    --round 0 --days -2 -1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prosperity.tooling.backtest import BacktestEngine, DaySummary
from prosperity.tooling.data import MarketDataLoader


def compare_strategies(
    strategies: List[str],
    round_num: int,
    data_dir: str,
    days: List[str],
) -> Dict[str, Dict]:
    results: Dict[str, Dict] = {}

    for strat in strategies:
        engine = BacktestEngine(data_dir, strat, round_num=round_num)
        total_pnl = 0.0
        day_pnls = []
        product_pnls: Dict[str, float] = {}
        product_trades: Dict[str, int] = {}
        product_max_pos: Dict[str, int] = {}

        for day in days:
            summary = engine.run_day(day)
            total_pnl += summary.pnl
            day_pnls.append({"day": day, "pnl": summary.pnl})
            for sym, ps in summary.product_summaries.items():
                product_pnls[sym] = product_pnls.get(sym, 0.0) + ps.pnl
                product_trades[sym] = product_trades.get(sym, 0) + ps.trades
                product_max_pos[sym] = max(product_max_pos.get(sym, 0), ps.max_abs_position)

        results[strat] = {
            "total_pnl": total_pnl,
            "days": day_pnls,
            "per_product_pnl": product_pnls,
            "per_product_trades": product_trades,
            "per_product_max_pos": product_max_pos,
        }

    return results


def _print_table(results: Dict[str, Dict]):
    strategies = list(results.keys())
    all_products = sorted(set(p for r in results.values() for p in r["per_product_pnl"]))

    # Header
    col_w = 14
    header = f"{'Strategy':<12}"
    for prod in all_products:
        header += f"  {prod:>{col_w}}"
    header += f"  {'TOTAL':>{col_w}}"
    print(header)
    print("-" * len(header))

    # Rows sorted by total PnL
    ranked = sorted(strategies, key=lambda s: results[s]["total_pnl"], reverse=True)
    for strat in ranked:
        r = results[strat]
        row = f"{strat:<12}"
        for prod in all_products:
            pnl = r["per_product_pnl"].get(prod, 0.0)
            row += f"  {pnl:>{col_w}.2f}"
        row += f"  {r['total_pnl']:>{col_w}.2f}"
        print(row)

    print()
    # Trades row
    print(f"{'-- trades --':<12}", end="")
    for prod in all_products:
        trades = " / ".join(str(results[s]["per_product_trades"].get(prod, 0)) for s in ranked)
        print(f"  {trades:>{col_w}}", end="")
    print()


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare strategies head-to-head")
    parser.add_argument("--strategies", nargs="+", required=True)
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--days", nargs="*")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--json-out", help="Save results as JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    loader = MarketDataLoader(args.data_dir)
    days = args.days or loader.available_days(args.round)

    results = compare_strategies(args.strategies, args.round, args.data_dir, days)
    _print_table(results)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
