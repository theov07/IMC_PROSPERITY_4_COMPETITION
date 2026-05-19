"""Targeted sweep for the three V7 quoting ideas.

Runs a fixed set of candidate configurations for one product while keeping the
other product on the current V7 baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prosperity.config import MEMBER_OVERRIDES, ProductConfig, get_round_config
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode


SILENT_PARAMS = {
    "log_flush_ts": 0,
    "total_ticks": 600000,
}

BASELINE_TARGET = {
    "EMERALDS": {"qty_join_threshold": 5},
    "TOMATOES": {"qty_join_threshold": 0},
}


def _proposal_candidates() -> Dict[str, List[Dict[str, float]]]:
    join_small: List[Dict[str, float]] = []
    for threshold in (0, 1, 2, 5, 10):
        for frac in (1.0, 0.5, 0.25):
            join_small.append({
                "qty_join_threshold": float(threshold),
                "join_size_frac": float(frac),
                "pj_detect": 0.0,
                "pj_size_frac": 1.0,
                "pj_qty_threshold": 0.0,
                "level2_ticks": 0.0,
                "level2_frac": 0.0,
            })

    jump_penny = [
        {"pj_detect": 0.0, "pj_size_frac": 1.0, "pj_qty_threshold": 0.0, "qty_join_threshold": 0.0, "join_size_frac": 1.0, "level2_ticks": 0.0, "level2_frac": 0.0},
        {"pj_detect": 1.0, "pj_size_frac": 1.0, "pj_qty_threshold": 0.0, "qty_join_threshold": 0.0, "join_size_frac": 1.0, "level2_ticks": 0.0, "level2_frac": 0.0},
        {"pj_detect": 1.0, "pj_size_frac": 0.5, "pj_qty_threshold": 0.0, "qty_join_threshold": 0.0, "join_size_frac": 1.0, "level2_ticks": 0.0, "level2_frac": 0.0},
        {"pj_detect": 1.0, "pj_size_frac": 0.25, "pj_qty_threshold": 0.0, "qty_join_threshold": 0.0, "join_size_frac": 1.0, "level2_ticks": 0.0, "level2_frac": 0.0},
    ]
    for threshold in (1, 2, 5):
        jump_penny.append({
            "pj_detect": 1.0,
            "pj_size_frac": 1.0,
            "pj_qty_threshold": float(threshold),
            "qty_join_threshold": 0.0,
            "join_size_frac": 1.0,
            "level2_ticks": 0.0,
            "level2_frac": 0.0,
        })
        for frac in (0.5, 0.25):
            jump_penny.append({
                "pj_detect": 1.0,
                "pj_size_frac": float(frac),
                "pj_qty_threshold": float(threshold),
                "qty_join_threshold": 0.0,
                "join_size_frac": 1.0,
                "level2_ticks": 0.0,
                "level2_frac": 0.0,
            })

    two_level = []
    for frac in (0.0, 0.1, 0.25, 0.5, 0.75):
        two_level.append({
            "qty_join_threshold": 0.0,
            "join_size_frac": 1.0,
            "pj_detect": 0.0,
            "pj_size_frac": 1.0,
            "pj_qty_threshold": 0.0,
            "level2_ticks": 2.0,
            "level2_frac": float(frac),
        })

    return {
        "join_small": join_small,
        "jump_penny": jump_penny,
        "two_level": two_level,
    }


def _patch_member(round_num: int, member: str, product: str, overrides: Dict[str, float]) -> None:
    base = get_round_config(round_num, member)
    patched: Dict[str, ProductConfig] = {}
    for sym, pc in base.items():
        params = dict(pc.params)
        params.update(SILENT_PARAMS)
        if sym == product:
            params.update(overrides)
        else:
            params.update(BASELINE_TARGET[sym])
        patched[sym] = ProductConfig(
            symbol=pc.symbol,
            strategy=pc.strategy,
            position_limit=pc.position_limit,
            params=params,
        )
    MEMBER_OVERRIDES.setdefault(member, {})[round_num] = patched


def _run_candidate(
    product: str,
    proposal: str,
    overrides: Dict[str, float],
    round_num: int,
    days: List[str],
    member: str,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "proposal": proposal,
        "params": overrides,
        "queue_total": 0.0,
        "queue_product": 0.0,
        "worse_total": 0.0,
        "worse_product": 0.0,
    }

    for mode in (TradeMatchingMode.queue, TradeMatchingMode.worse):
        _patch_member(round_num, member, product, overrides)
        engine = BacktestEngine("data", member, round_num=round_num)
        total = 0.0
        product_total = 0.0
        for day in days:
            summary = engine.run_day(day, mode=mode)
            total += summary.pnl
            product_total += summary.product_summaries[product].pnl
        row[f"{mode.value}_total"] = total
        row[f"{mode.value}_product"] = product_total

    return row


def run_sweep(product: str, round_num: int, days: List[str], member: str) -> List[Dict[str, Any]]:
    all_results: List[Dict[str, Any]] = []
    for proposal, candidates in _proposal_candidates().items():
        for overrides in candidates:
            all_results.append(_run_candidate(product, proposal, overrides, round_num, days, member))
    return all_results


def _sort_key(row: Dict[str, Any]) -> tuple[float, float]:
    return (row["worse_product"], row["queue_product"])


def _summarize(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    results = list(results)
    by_proposal: Dict[str, List[Dict[str, Any]]] = {}
    for row in results:
        by_proposal.setdefault(row["proposal"], []).append(row)

    summary: Dict[str, Any] = {"overall_best": None, "proposal_best": {}}
    summary["overall_best"] = max(results, key=_sort_key)
    for proposal, rows in by_proposal.items():
        summary["proposal_best"][proposal] = max(rows, key=_sort_key)
    return summary


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sweep V7 quoting ideas for one product")
    parser.add_argument("--product", required=True, choices=["EMERALDS", "TOMATOES"])
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--days", nargs="*", default=["-2", "-1"])
    parser.add_argument("--member", default="leo_naive_v7")
    parser.add_argument("--json-out", required=True)
    args = parser.parse_args(argv)

    original_member = MEMBER_OVERRIDES.get(args.member, {}).get(args.round)
    try:
        results = run_sweep(args.product, args.round, list(args.days), args.member)
        payload = {
            "product": args.product,
            "results": results,
            "summary": _summarize(results),
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    finally:
        if original_member is None:
            MEMBER_OVERRIDES.get(args.member, {}).pop(args.round, None)
        else:
            MEMBER_OVERRIDES.setdefault(args.member, {})[args.round] = original_member

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
