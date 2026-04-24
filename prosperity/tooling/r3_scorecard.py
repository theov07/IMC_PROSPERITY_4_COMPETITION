"""Round 3 decision scorecard.

This is intentionally separate from ``r3_analysis.py`` so agents can keep the
visual research notebook/plotting work independent from the upload gate.

Run:
    python -m prosperity.tooling.r3_scorecard --strategy r3_naive_champion
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd

from prosperity.options.black_scholes import call_delta, call_gamma, call_price, call_vega
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.time import time_to_expiry_days
from prosperity.tooling.backtest import BacktestEngine, DaySummary, TradeMatchingMode, aggregate_day_summaries
from prosperity.tooling.data import MarketDataLoader


ROUND_3_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
ROUND_3_HISTORICAL_TTE = {0: 8.0, 1: 7.0, 2: 6.0}
ROUND_3_TIMESTAMP_UNITS_PER_DAY = 1_000_000
ROUND_3_UNDERLYING = "VELVETFRUIT_EXTRACT"
ROUND_3_DELTA_ONE = {"HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"}
SIGMA_FLOOR = 0.005
SIGMA_CAP = 0.10


def _option_symbol(strike: int) -> str:
    return f"VEV_{strike}"


def _option_strike(symbol: str) -> int | None:
    if not symbol.startswith("VEV_"):
        return None
    try:
        return int(symbol.replace("VEV_", ""))
    except ValueError:
        return None


def _is_valid_number(value) -> bool:
    try:
        return not pd.isna(value) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _fmt(value, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(value_f):
        return "n/a"
    return f"{value_f:,.{digits}f}"


def _markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _run_backtests(
    *,
    strategy: str,
    round_num: int,
    data_dir: str,
    days: List[str],
    mode: TradeMatchingMode,
) -> List[DaySummary]:
    engine = BacktestEngine(data_dir, strategy, round_num=round_num)
    return [engine.run_day(day, mode=mode) for day in days]


def _product_rows(aggregate: Dict[str, object]) -> List[Dict[str, object]]:
    pnl_by_product = aggregate.get("per_product_pnl", {})
    trades_by_product = aggregate.get("per_product_trades", {})
    max_pos_by_product = aggregate.get("per_product_max_pos", {})
    robust_by_product = aggregate.get("per_product_robustness", {})

    def sort_key(symbol: str) -> tuple:
        strike = _option_strike(symbol)
        if symbol in ROUND_3_DELTA_ONE:
            return (0, symbol)
        if strike is not None:
            return (1, strike)
        return (2, symbol)

    rows: List[Dict[str, object]] = []
    for product in sorted(pnl_by_product, key=sort_key):
        robust = robust_by_product.get(product, {})
        markouts = robust.get("markout_mean_by_horizon", {}) if isinstance(robust, dict) else {}
        rows.append(
            {
                "product": product,
                "pnl": pnl_by_product.get(product, 0.0),
                "trades": trades_by_product.get(product, 0),
                "max_abs_position": max_pos_by_product.get(product, 0),
                "fill_efficiency": robust.get("fill_efficiency") if isinstance(robust, dict) else None,
                "avg_abs_position_ratio": robust.get("avg_abs_position_ratio") if isinstance(robust, dict) else None,
                "passive_adverse_rate": robust.get("passive_adverse_rate") if isinstance(robust, dict) else None,
                "markout_1": markouts.get("1") if isinstance(markouts, dict) else None,
            }
        )
    return rows


def _load_mid_table(loader: MarketDataLoader, round_num: int, day: str) -> pd.DataFrame:
    prices = loader.load_prices(f"prices_round_{round_num}_day_{day}.csv")
    return prices.pivot_table(index="timestamp", columns="product", values="mid_price", aggfunc="last")


def _fill_value(fill, name: str):
    if isinstance(fill, dict):
        return fill.get(name)
    return getattr(fill, name)


def _fills_by_timestamp(summary) -> Dict[int, List]:
    out: Dict[int, List] = {}
    fills = summary.get("fills", []) if isinstance(summary, dict) else summary.fills
    for fill in fills:
        out.setdefault(int(_fill_value(fill, "timestamp")), []).append(fill)
    return out


def _update_positions(positions: Dict[str, int], fills: List) -> None:
    for fill in fills:
        sign = 1 if str(_fill_value(fill, "side")).upper() == "BUY" else -1
        symbol = str(_fill_value(fill, "symbol"))
        positions[symbol] = positions.get(symbol, 0) + sign * int(_fill_value(fill, "quantity"))


def _portfolio_greeks(
    *,
    loader: MarketDataLoader,
    round_num: int,
    days: List[str],
    summaries: List[DaySummary | Dict],
    sample_step: int,
) -> Dict[str, float | int | None]:
    samples = 0
    abs_delta_sum = 0.0
    abs_gamma_sum = 0.0
    abs_vega_sum = 0.0
    gross_option_pos_sum = 0.0
    max_abs_delta = 0.0
    max_abs_gamma = 0.0
    max_abs_vega = 0.0
    max_gross_option_pos = 0

    for day, summary in zip(days, summaries):
        mid_table = _load_mid_table(loader, round_num, day)
        fills_at = _fills_by_timestamp(summary)
        positions: Dict[str, int] = {}
        tte0 = ROUND_3_HISTORICAL_TTE.get(int(day), 5.0)

        for timestamp, row in mid_table.sort_index().iterrows():
            _update_positions(positions, fills_at.get(int(timestamp), []))
            timestamp_i = int(timestamp)
            if sample_step > 0 and timestamp_i % sample_step != 0:
                continue

            spot_raw = row.get(ROUND_3_UNDERLYING)
            if not _is_valid_number(spot_raw):
                continue
            spot = float(spot_raw)
            tte = time_to_expiry_days(
                timestamp_i,
                tte0,
                timestamp_units_per_day=ROUND_3_TIMESTAMP_UNITS_PER_DAY,
            )

            net_delta = float(positions.get(ROUND_3_UNDERLYING, 0))
            net_gamma = 0.0
            net_vega = 0.0
            gross_option_pos = 0

            for strike in ROUND_3_STRIKES:
                symbol = _option_symbol(strike)
                pos = int(positions.get(symbol, 0))
                gross_option_pos += abs(pos)
                if pos == 0:
                    continue
                mid_raw = row.get(symbol)
                if not _is_valid_number(mid_raw):
                    continue
                iv = call_implied_vol(float(mid_raw), spot, strike, tte)
                if iv is None:
                    continue
                sigma = max(SIGMA_FLOOR, min(SIGMA_CAP, iv))
                net_delta += pos * call_delta(spot, strike, tte, sigma)
                net_gamma += pos * call_gamma(spot, strike, tte, sigma)
                net_vega += pos * call_vega(spot, strike, tte, sigma)

            samples += 1
            abs_delta_sum += abs(net_delta)
            abs_gamma_sum += abs(net_gamma)
            abs_vega_sum += abs(net_vega)
            gross_option_pos_sum += gross_option_pos
            max_abs_delta = max(max_abs_delta, abs(net_delta))
            max_abs_gamma = max(max_abs_gamma, abs(net_gamma))
            max_abs_vega = max(max_abs_vega, abs(net_vega))
            max_gross_option_pos = max(max_gross_option_pos, gross_option_pos)

    if samples == 0:
        return {
            "samples": 0,
            "avg_abs_net_delta": None,
            "max_abs_net_delta": None,
            "avg_abs_net_gamma": None,
            "max_abs_net_gamma": None,
            "avg_abs_net_vega": None,
            "max_abs_net_vega": None,
            "avg_gross_option_position": None,
            "max_gross_option_position": None,
        }

    return {
        "samples": samples,
        "avg_abs_net_delta": abs_delta_sum / samples,
        "max_abs_net_delta": max_abs_delta,
        "avg_abs_net_gamma": abs_gamma_sum / samples,
        "max_abs_net_gamma": max_abs_gamma,
        "avg_abs_net_vega": abs_vega_sum / samples,
        "max_abs_net_vega": max_abs_vega,
        "avg_gross_option_position": gross_option_pos_sum / samples,
        "max_gross_option_position": max_gross_option_pos,
    }


def _edge_stats(
    *,
    loader: MarketDataLoader,
    round_num: int,
    days: List[str],
    sample_step: int,
) -> Dict[str, Dict[str, float | int | None]]:
    accum = {
        strike: {"count": 0, "sum_edge": 0.0, "sum_abs_edge": 0.0, "positive": 0, "max_abs_edge": 0.0}
        for strike in ROUND_3_STRIKES
    }

    for day in days:
        mid_table = _load_mid_table(loader, round_num, day)
        tte0 = ROUND_3_HISTORICAL_TTE.get(int(day), 5.0)

        for timestamp, row in mid_table.sort_index().iterrows():
            timestamp_i = int(timestamp)
            if sample_step > 0 and timestamp_i % sample_step != 0:
                continue

            spot_raw = row.get(ROUND_3_UNDERLYING)
            if not _is_valid_number(spot_raw):
                continue
            spot = float(spot_raw)
            tte = time_to_expiry_days(
                timestamp_i,
                tte0,
                timestamp_units_per_day=ROUND_3_TIMESTAMP_UNITS_PER_DAY,
            )

            strikes: List[float] = []
            vols: List[float] = []
            mids: Dict[int, float] = {}
            for strike in ROUND_3_STRIKES:
                mid_raw = row.get(_option_symbol(strike))
                if not _is_valid_number(mid_raw):
                    continue
                mid = float(mid_raw)
                iv = call_implied_vol(mid, spot, strike, tte)
                if iv is None or not (SIGMA_FLOOR <= iv <= SIGMA_CAP):
                    continue
                strikes.append(float(strike))
                vols.append(iv)
                mids[strike] = mid

            coeffs = fit_smile_poly(strikes, vols, spot, tte, degree=2) if len(strikes) >= 3 else None
            if not coeffs:
                continue

            for strike, mid in mids.items():
                sigma = max(SIGMA_FLOOR, min(SIGMA_CAP, smile_predict(strike, coeffs, spot, tte)))
                fair = call_price(spot, strike, tte, sigma)
                edge = fair - mid
                bucket = accum[strike]
                bucket["count"] += 1
                bucket["sum_edge"] += edge
                bucket["sum_abs_edge"] += abs(edge)
                bucket["positive"] += 1 if edge > 0 else 0
                bucket["max_abs_edge"] = max(float(bucket["max_abs_edge"]), abs(edge))

    stats: Dict[str, Dict[str, float | int | None]] = {}
    for strike, bucket in accum.items():
        count = int(bucket["count"])
        if count == 0:
            stats[str(strike)] = {
                "count": 0,
                "mean_edge": None,
                "mean_abs_edge": None,
                "pct_fair_above_market": None,
                "max_abs_edge": None,
            }
            continue
        stats[str(strike)] = {
            "count": count,
            "mean_edge": float(bucket["sum_edge"]) / count,
            "mean_abs_edge": float(bucket["sum_abs_edge"]) / count,
            "pct_fair_above_market": float(bucket["positive"]) / count,
            "max_abs_edge": float(bucket["max_abs_edge"]),
        }
    return stats


def _build_markdown(payload: Dict[str, object]) -> str:
    strategy = payload["strategy"]
    days = ", ".join(payload["days"])
    headline = payload["headline"]
    greeks = payload["portfolio_greeks"]
    product_rows = payload["product_rows"]
    edge_stats = payload["edge_stats"]

    lines = [
        f"# Round 3 Scorecard - {strategy}",
        "",
        f"Days: `{days}`  |  execution rule: `{payload['execution_rule']}`",
        "",
        "## Headline",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Total PnL", _fmt(headline["total_pnl"])],
                ["Delta-1 PnL", _fmt(headline["delta_one_pnl"])],
                ["Options PnL", _fmt(headline["options_pnl"])],
                ["Max drawdown", _fmt(headline["max_drawdown"])],
                ["Fill efficiency", _fmt(headline["fill_efficiency"], 3)],
                ["Avg abs net delta", _fmt(greeks["avg_abs_net_delta"], 1)],
                ["Max abs net delta", _fmt(greeks["max_abs_net_delta"], 1)],
                ["Avg abs net vega", _fmt(greeks["avg_abs_net_vega"], 1)],
                ["Max gross option pos", _fmt(greeks["max_gross_option_position"])],
            ],
        ),
        "",
        "## Product PnL",
        _markdown_table(
            ["Product", "PnL", "Trades", "Max Pos", "Fill Eff", "Inv", "Adverse", "M1"],
            [
                [
                    str(row["product"]),
                    _fmt(row["pnl"]),
                    _fmt(row["trades"]),
                    _fmt(row["max_abs_position"]),
                    _fmt(row["fill_efficiency"], 3),
                    _fmt(row["avg_abs_position_ratio"], 3),
                    _fmt(row["passive_adverse_rate"], 3),
                    _fmt(row["markout_1"], 2),
                ]
                for row in product_rows
            ],
        ),
        "",
        "## Smile Residuals",
        _markdown_table(
            ["Strike", "Mean Edge", "Mean Abs Edge", "Fair > Mkt", "Max Abs Edge", "Samples"],
            [
                [
                    strike,
                    _fmt(stats["mean_edge"], 3),
                    _fmt(stats["mean_abs_edge"], 3),
                    _fmt(stats["pct_fair_above_market"], 3),
                    _fmt(stats["max_abs_edge"], 2),
                    _fmt(stats["count"]),
                ]
                for strike, stats in edge_stats.items()
            ],
        ),
        "",
        "## Notes",
        "- TTE in strategy backtests now uses historical day metadata: day 0 = 8d, day 1 = 7d, day 2 = 6d.",
        "- Live R3 still defaults to TTE = 5d when no backtest metadata is present.",
        "- Smile residuals compare market mids to a same-timestamp quadratic smile fit; they are a triage signal, not a standalone trading rule.",
    ]
    return "\n".join(lines) + "\n"


def build_scorecard(
    *,
    strategy: str,
    round_num: int,
    data_dir: str,
    days: List[str],
    execution_rule: str,
    sample_step: int,
    greek_step: int,
    backtest_json: str | None = None,
) -> Dict[str, object]:
    mode = TradeMatchingMode(execution_rule)
    loader = MarketDataLoader(data_dir)
    if backtest_json:
        backtest_payload = json.loads(Path(backtest_json).read_text(encoding="utf-8"))
        aggregate = backtest_payload.get("summary", backtest_payload)
        summaries = backtest_payload.get("days", [])
    else:
        summaries = _run_backtests(
            strategy=strategy,
            round_num=round_num,
            data_dir=data_dir,
            days=days,
            mode=mode,
        )
        aggregate = aggregate_day_summaries(summaries)
    product_rows = _product_rows(aggregate)

    options_pnl = sum(row["pnl"] for row in product_rows if _option_strike(str(row["product"])) is not None)
    delta_one_pnl = sum(row["pnl"] for row in product_rows if row["product"] in ROUND_3_DELTA_ONE)
    robustness = aggregate.get("robustness", {})

    greeks = _portfolio_greeks(
        loader=loader,
        round_num=round_num,
        days=days,
        summaries=summaries,
        sample_step=greek_step,
    )
    edges = _edge_stats(loader=loader, round_num=round_num, days=days, sample_step=sample_step)

    return {
        "strategy": strategy,
        "round": round_num,
        "days": days,
        "execution_rule": execution_rule,
        "headline": {
            "total_pnl": aggregate["total_pnl"],
            "delta_one_pnl": delta_one_pnl,
            "options_pnl": options_pnl,
            "max_drawdown": robustness.get("max_drawdown") if isinstance(robustness, dict) else None,
            "fill_efficiency": robustness.get("fill_efficiency") if isinstance(robustness, dict) else None,
        },
        "product_rows": product_rows,
        "portfolio_greeks": greeks,
        "edge_stats": edges,
        "backtest_summary": aggregate,
    }


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Round 3 upload/readiness scorecard")
    parser.add_argument("--strategy", default="r3_naive_champion")
    parser.add_argument("--round", type=int, default=3)
    parser.add_argument("--days", nargs="*")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--execution-rule",
        "--match-trades",
        dest="execution_rule",
        default="realistic",
        choices=["queue", "all", "worse", "none", "realistic"],
    )
    parser.add_argument("--sample-step", type=int, default=5000, help="Raw timestamp step for smile residual sampling")
    parser.add_argument("--greek-step", type=int, default=5000, help="Raw timestamp step for portfolio greek sampling")
    parser.add_argument("--backtest-json", help="Reuse an existing backtest.py JSON output instead of rerunning")
    parser.add_argument("--outdir", default="artifacts/scorecards/round_3")
    args = parser.parse_args(list(argv) if argv is not None else None)

    loader = MarketDataLoader(args.data_dir)
    days = args.days or loader.available_days(args.round)
    days = sorted(days, key=lambda d: int(d))

    payload = build_scorecard(
        strategy=args.strategy,
        round_num=args.round,
        data_dir=args.data_dir,
        days=days,
        execution_rule=args.execution_rule,
        sample_step=args.sample_step,
        greek_step=args.greek_step,
        backtest_json=args.backtest_json,
    )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.strategy}_round{args.round}_scorecard"
    json_path = outdir / f"{stem}.json"
    md_path = outdir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(_build_markdown(payload), encoding="utf-8")

    headline = payload["headline"]
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print(
        "Headline: "
        f"total={_fmt(headline['total_pnl'])}, "
        f"delta1={_fmt(headline['delta_one_pnl'])}, "
        f"options={_fmt(headline['options_pnl'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
