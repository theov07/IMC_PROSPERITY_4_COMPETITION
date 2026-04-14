"""Grid search / parameter sweep for strategy optimization.

Usage:
  python -m prosperity.tooling.grid_search \
    --strategy champion --round 0 --days -2 -1 \
    --param "EMERALDS.ema_alpha=0.05,0.10,0.15,0.20" \
    --param "EMERALDS.take_edge=0.5,1.0,1.5" \
    --param "TOMATOES.quote_half_spread=1,2,3"

Runs all combinations and produces a ranked table.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prosperity.config import ProductConfig, MEMBER_OVERRIDES, get_round_config
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode, aggregate_day_summaries


@dataclass
class SweepResult:
    params: Dict[str, Any]
    total_pnl: float
    per_day: List[float]
    per_product: Dict[str, float]
    robustness: Dict[str, Any]


def _parse_param_spec(spec: str) -> Tuple[str, str, List[float]]:
    """Parse 'SYMBOL.param_name=v1,v2,v3' into (symbol, param, values)."""
    lhs, rhs = spec.split("=", 1)
    parts = lhs.split(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Param spec must be SYMBOL.param=values, got: {spec}")
    symbol, param = parts
    values = [float(v) for v in rhs.split(",")]
    return symbol, param, values


def _apply_overrides(round_num: int, overrides: Dict[str, Dict[str, float]], member: str = "champion"):
    """Return a member-override mapping with param overrides applied.

    Important: we patch the override mapping itself, not the fully-resolved round config.
    This preserves explicit product removals such as {"ASH_COATED_OSMIUM": None}.
    """
    effective = get_round_config(round_num, member)
    original_overrides = MEMBER_OVERRIDES.get(member, {}).get(round_num, {})
    patched: Dict[str, ProductConfig | None] = dict(original_overrides)

    for sym, params in overrides.items():
        if sym not in effective:
            raise ValueError(
                f"Cannot override {sym} for member={member!r}, round={round_num}: "
                "product is not active in the effective config."
            )

        pc = effective[sym]
        new_params = {**pc.params, **params}
        patched[sym] = ProductConfig(
            symbol=pc.symbol,
            strategy=pc.strategy,
            position_limit=pc.position_limit,
            params=new_params,
        )

    return patched


def _result_sort_key(result: SweepResult, rank_by: str) -> tuple:
    adverse = result.robustness.get("passive_adverse_rate")

    if rank_by == "drawdown":
        return (result.robustness.get("max_drawdown", float("inf")), -result.total_pnl)
    if rank_by == "fill_efficiency":
        return (-(result.robustness.get("fill_efficiency") or 0.0), -result.total_pnl)
    if rank_by == "inventory_pressure":
        return (result.robustness.get("avg_abs_position_ratio", float("inf")), -result.total_pnl)
    if rank_by == "passive_adverse_rate":
        return (adverse if adverse is not None else float("inf"), -result.total_pnl)
    return (-result.total_pnl,)


def run_grid_search(
    strategy: str,
    round_num: int,
    data_dir: str,
    days: List[str],
    param_specs: List[str],
    member: str = "champion",
    mode: TradeMatchingMode = TradeMatchingMode.queue,
) -> List[SweepResult]:
    """Run all parameter combinations and return ranked results."""
    parsed = [_parse_param_spec(spec) for spec in param_specs]
    param_names = [(sym, param) for sym, param, _ in parsed]
    value_lists = [values for _, _, values in parsed]
    combos = list(itertools.product(*value_lists))

    print(f"Grid search: {len(combos)} combinations, {len(days)} day(s)")
    results: List[SweepResult] = []

    for index, combo in enumerate(combos):
        overrides: Dict[str, Dict[str, float]] = {}
        combo_desc: Dict[str, Any] = {}
        for (sym, param), value in zip(param_names, combo):
            overrides.setdefault(sym, {})[param] = value
            combo_desc[f"{sym}.{param}"] = value

        patched = _apply_overrides(round_num, overrides, member)
        member_rounds = MEMBER_OVERRIDES.setdefault(member, {})
        original_member = member_rounds.get(round_num)
        member_rounds[round_num] = patched

        try:
            engine = BacktestEngine(data_dir, strategy, round_num=round_num)
            summaries = []
            day_pnls = []
            for day in days:
                summary = engine.run_day(day, mode=mode)
                summaries.append(summary)
                day_pnls.append(summary.pnl)

            aggregate = aggregate_day_summaries(summaries)
            results.append(
                SweepResult(
                    params=combo_desc,
                    total_pnl=aggregate["total_pnl"],
                    per_day=day_pnls,
                    per_product=aggregate["per_product_pnl"],
                    robustness=aggregate["robustness"],
                )
            )
        finally:
            if original_member is None:
                member_rounds.pop(round_num, None)
            else:
                member_rounds[round_num] = original_member

        if (index + 1) % 10 == 0 or index + 1 == len(combos):
            print(f"  [{index + 1}/{len(combos)}] last_pnl={results[-1].total_pnl:.2f}")

    return results


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grid search parameter optimizer")
    valid_members = sorted(MEMBER_OVERRIDES.keys())
    parser.add_argument("--strategy", required=True, choices=valid_members)
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--days", nargs="*")
    parser.add_argument("--data-dir", default="data", help="Data root or per-round directory with CSV files")
    parser.add_argument("--param", action="append", required=True, help="SYMBOL.param=v1,v2,v3")
    parser.add_argument(
        "--execution-rule",
        "--match-trades",
        dest="execution_rule",
        default="queue",
        choices=["queue", "all", "worse", "none", "realistic"],
        help="Passive fill rule to use during the sweep.",
    )
    parser.add_argument("--top", type=int, default=10, help="Show top N results")
    parser.add_argument(
        "--rank-by",
        default="pnl",
        choices=["pnl", "drawdown", "fill_efficiency", "inventory_pressure", "passive_adverse_rate"],
        help="Ranking metric for the sweep results.",
    )
    parser.add_argument("--json-out", help="Save full results to JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from prosperity.tooling.data import MarketDataLoader

    loader = MarketDataLoader(args.data_dir)
    days = args.days or loader.available_days(args.round)

    t0 = time.time()
    results = run_grid_search(
        args.strategy,
        args.round,
        args.data_dir,
        days,
        args.param,
        member=args.strategy,
        mode=TradeMatchingMode(args.execution_rule),
    )
    results.sort(key=lambda result: _result_sort_key(result, args.rank_by))
    elapsed = time.time() - t0

    print(f"\n{'=' * 60}")
    print(f"Grid search complete in {elapsed:.1f}s - top {args.top} results (rank_by={args.rank_by}):")
    print(f"{'=' * 60}")
    for index, result in enumerate(results[:args.top], start=1):
        params_str = ", ".join(f"{key}={value}" for key, value in result.params.items())
        products_str = ", ".join(f"{key}={value:.1f}" for key, value in result.per_product.items())
        print(
            f"  #{index}: pnl={result.total_pnl:>10.2f} "
            f"dd={(result.robustness.get('max_drawdown') or 0.0):>8.2f} "
            f"fill_eff={(result.robustness.get('fill_efficiency') or 0.0):>6.3f} "
            f"inv={(result.robustness.get('avg_abs_position_ratio') or 0.0):>6.3f} "
            f"[{products_str}]  {params_str}"
        )

    if args.json_out:
        payload = [
            {
                "params": result.params,
                "total_pnl": result.total_pnl,
                "per_day": result.per_day,
                "per_product": result.per_product,
                "robustness": result.robustness,
            }
            for result in results
        ]
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Saved to {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
