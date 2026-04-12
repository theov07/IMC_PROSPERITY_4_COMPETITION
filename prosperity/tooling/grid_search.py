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
import copy
import itertools
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# Ensure project root is on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prosperity.config import ProductConfig, get_round_config, MEMBER_OVERRIDES
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode


@dataclass
class SweepResult:
    params: Dict[str, Any]
    total_pnl: float
    per_day: List[float]
    per_product: Dict[str, float]


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
    """Temporarily patch ROUNDS config with overrides and return the modified round dict."""
    base = get_round_config(round_num, member)
    patched: Dict[str, ProductConfig] = {}
    for sym, pc in base.items():
        if sym in overrides:
            new_params = {**pc.params, **overrides[sym]}
            patched[sym] = ProductConfig(symbol=pc.symbol, strategy=pc.strategy, position_limit=pc.position_limit, params=new_params)
        else:
            patched[sym] = pc
    return patched


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
    parsed = [_parse_param_spec(s) for s in param_specs]

    # Build cartesian product
    param_names = [(sym, param) for sym, param, _ in parsed]
    value_lists = [values for _, _, values in parsed]
    combos = list(itertools.product(*value_lists))

    print(f"Grid search: {len(combos)} combinations, {len(days)} day(s)")
    results: List[SweepResult] = []

    for i, combo in enumerate(combos):
        overrides: Dict[str, Dict[str, float]] = {}
        combo_desc: Dict[str, Any] = {}
        for (sym, param), val in zip(param_names, combo):
            overrides.setdefault(sym, {})[param] = val
            combo_desc[f"{sym}.{param}"] = val

        # Patch MEMBER_OVERRIDES so get_round_config sees the combo params.
        # Patching ROUNDS is insufficient: get_round_config applies member
        # overrides on top of ROUNDS, which would silently undo any ROUNDS patch.
        patched = _apply_overrides(round_num, overrides, member)
        member_rounds = MEMBER_OVERRIDES.setdefault(member, {})
        original_member = member_rounds.get(round_num)
        member_rounds[round_num] = patched

        try:
            engine = BacktestEngine(data_dir, strategy, round_num=round_num)
            day_pnls = []
            product_pnls: Dict[str, float] = {}
            for day in days:
                summary = engine.run_day(day, mode=mode)
                day_pnls.append(summary.pnl)
                for sym, ps in summary.product_summaries.items():
                    product_pnls[sym] = product_pnls.get(sym, 0.0) + ps.pnl
            total = sum(day_pnls)
            results.append(SweepResult(params=combo_desc, total_pnl=total, per_day=day_pnls, per_product=product_pnls))
        finally:
            if original_member is None:
                member_rounds.pop(round_num, None)
            else:
                member_rounds[round_num] = original_member

        if (i + 1) % 10 == 0 or i + 1 == len(combos):
            print(f"  [{i + 1}/{len(combos)}] last_pnl={results[-1].total_pnl:.2f}")

    results.sort(key=lambda r: r.total_pnl, reverse=True)
    return results


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grid search parameter optimizer")
    valid_members = sorted(MEMBER_OVERRIDES.keys())
    parser.add_argument("--strategy", required=True, choices=valid_members)
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--days", nargs="*")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--param", action="append", required=True, help="SYMBOL.param=v1,v2,v3")
    parser.add_argument(
        "--execution-rule",
        "--match-trades",
        dest="execution_rule",
        default="queue",
        choices=["queue", "all", "worse", "none"],
        help="Passive fill rule to use during the sweep.",
    )
    parser.add_argument("--top", type=int, default=10, help="Show top N results")
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
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"Grid search complete in {elapsed:.1f}s — top {args.top} results:")
    print(f"{'='*60}")
    for i, r in enumerate(results[:args.top]):
        params_str = ", ".join(f"{k}={v}" for k, v in r.params.items())
        products_str = ", ".join(f"{k}={v:.1f}" for k, v in r.per_product.items())
        print(f"  #{i+1}: pnl={r.total_pnl:>10.2f}  [{products_str}]  {params_str}")

    if args.json_out:
        payload = [{"params": r.params, "total_pnl": r.total_pnl, "per_day": r.per_day, "per_product": r.per_product} for r in results]
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Saved to {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
