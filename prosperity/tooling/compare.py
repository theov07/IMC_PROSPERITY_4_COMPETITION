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

from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode, aggregate_day_summaries
from prosperity.tooling.data import MarketDataLoader


def compare_strategies(
    strategies: List[str],
    round_num: int,
    data_dir: str,
    days: List[str],
    mode: TradeMatchingMode = TradeMatchingMode.queue,
) -> Dict[str, Dict]:
    results: Dict[str, Dict] = {}

    for strat in strategies:
        engine = BacktestEngine(data_dir, strat, round_num=round_num)
        summaries = []
        day_pnls = []

        for day in days:
            summary = engine.run_day(day, mode=mode)
            summaries.append(summary)
            day_pnls.append({"day": day, "pnl": summary.pnl})

        aggregate = aggregate_day_summaries(summaries)

        results[strat] = {
            "days": day_pnls,
            **aggregate,
        }

    return results


def _result_sort_key(result: Dict, rank_by: str) -> tuple:
    robustness = result.get("robustness", {})
    passive_adverse_rate = robustness.get("passive_adverse_rate")

    if rank_by == "drawdown":
        return (
            robustness.get("max_drawdown", float("inf")),
            -(result.get("total_pnl") or 0.0),
        )
    if rank_by == "fill_efficiency":
        return (
            -(robustness.get("fill_efficiency") or 0.0),
            -(result.get("total_pnl") or 0.0),
        )
    if rank_by == "inventory_pressure":
        return (
            robustness.get("avg_abs_position_ratio", float("inf")),
            -(result.get("total_pnl") or 0.0),
        )
    if rank_by == "passive_adverse_rate":
        return (
            passive_adverse_rate if passive_adverse_rate is not None else float("inf"),
            -(result.get("total_pnl") or 0.0),
        )
    return (-(result.get("total_pnl") or 0.0),)


def _print_table(results: Dict[str, Dict], rank_by: str):
    strategies = list(results.keys())
    all_products = sorted(set(p for r in results.values() for p in r["per_product_pnl"]))

    col_w = 12
    header = (
        f"{'Strategy':<12}"
        f"  {'TOTAL':>{col_w}}"
        f"  {'DD':>{col_w}}"
        f"  {'FillEff':>{col_w}}"
        f"  {'Inv':>{col_w}}"
        f"  {'Adverse':>{col_w}}"
    )
    for prod in all_products:
        header += f"  {prod:>{col_w}}"
    print(header)
    print("-" * len(header))

    ranked = sorted(strategies, key=lambda s: _result_sort_key(results[s], rank_by))
    for strat in ranked:
        r = results[strat]
        robustness = r.get("robustness", {})
        adverse = robustness.get("passive_adverse_rate")
        row = f"{strat:<12}"
        row += f"  {r['total_pnl']:>{col_w}.2f}"
        row += f"  {(robustness.get('max_drawdown') or 0.0):>{col_w}.2f}"
        row += f"  {(robustness.get('fill_efficiency') or 0.0):>{col_w}.3f}"
        row += f"  {(robustness.get('avg_abs_position_ratio') or 0.0):>{col_w}.3f}"
        row += f"  {('n/a' if adverse is None else f'{adverse:.3f}'):>{col_w}}"
        for prod in all_products:
            pnl = r["per_product_pnl"].get(prod, 0.0)
            row += f"  {pnl:>{col_w}.2f}"
        print(row)

    print()
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
    parser.add_argument(
        "--execution-rule",
        "--match-trades",
        dest="execution_rule",
        default="queue",
        choices=["queue", "all", "worse", "none", "realistic"],
        help="Passive fill rule to use during comparison runs.",
    )
    parser.add_argument("--json-out", help="Save results as JSON")
    parser.add_argument(
        "--rank-by",
        default="pnl",
        choices=["pnl", "drawdown", "fill_efficiency", "inventory_pressure", "passive_adverse_rate"],
        help="Ranking metric for the comparison table.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    loader = MarketDataLoader(args.data_dir)
    days = args.days or loader.available_days(args.round)

    results = compare_strategies(
        args.strategies,
        args.round,
        args.data_dir,
        days,
        mode=TradeMatchingMode(args.execution_rule),
    )
    _print_table(results, args.rank_by)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
