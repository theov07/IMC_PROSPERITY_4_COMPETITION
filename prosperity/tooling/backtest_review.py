from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

from prosperity.tooling.backtest import BacktestEngine, DaySummary, TradeMatchingMode
from prosperity.tooling.data import MarketDataLoader
from prosperity.tooling.logs import OfficialLog, load_official_log, plot_symbol_review_plotly


_ROUND_RE = re.compile(r"round_(\d+)")


class FileBacktestEngine(BacktestEngine):
    def __init__(self, data_dir: str | Path, strategy_file: str | Path, round_num: int = 0):
        self.strategy_file = Path(strategy_file).resolve()
        super().__init__(data_dir=data_dir, strategy_module=str(self.strategy_file), round_num=round_num)

    def _load_trader(self):
        module_name = f"_backtest_submission_{hashlib.md5(str(self.strategy_file).encode('utf-8')).hexdigest()}"
        spec = importlib.util.spec_from_file_location(module_name, self.strategy_file)
        if spec is None or spec.loader is None:
            raise ValueError(f"Could not load strategy file: {self.strategy_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        if not hasattr(module, "Trader"):
            raise ValueError(f"Strategy file {self.strategy_file} does not expose Trader")
        return module.Trader()


def _infer_round_num(log: OfficialLog, explicit_round: int | None) -> int:
    if explicit_round is not None:
        return explicit_round

    for part in log.source_path.parts:
        match = _ROUND_RE.fullmatch(part)
        if match:
            return int(match.group(1))

    round_label = log.round_label
    if round_label is not None and str(round_label).isdigit():
        return int(round_label)

    return 1


def _resolve_backtest_day(day_arg: str, available_days: list[str]) -> str:
    available_days = sorted(available_days, key=lambda value: int(value), reverse=True)
    if day_arg in available_days:
        return day_arg

    try:
        index = int(day_arg)
    except ValueError as exc:
        raise ValueError(f"Invalid --day value {day_arg!r}. Use one of {available_days} or an index 0..{len(available_days)-1}.") from exc

    if day_arg.startswith("-"):
        if day_arg in available_days:
            return day_arg
        raise ValueError(f"Day {day_arg} not available. Choices: {available_days}")

    if not (0 <= index < len(available_days)):
        raise ValueError(f"Day index {index} out of range. Choices: 0..{len(available_days)-1} -> {available_days}")
    return available_days[index]


def _fills_to_trades_frame(summary: DaySummary) -> pd.DataFrame:
    rows = []
    for fill in summary.fills:
        rows.append(
            {
                "timestamp": int(fill.timestamp),
                "symbol": fill.symbol,
                "price": int(fill.price),
                "quantity": int(fill.quantity),
                "buyer": "SUBMISSION" if fill.side == "BUY" else "MARKET",
                "seller": "MARKET" if fill.side == "BUY" else "SUBMISSION",
                "aggressive": bool(fill.aggressive),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "symbol", "price", "quantity", "buyer", "seller", "aggressive"])
    return pd.DataFrame(rows).sort_values(["timestamp", "symbol", "price"]).reset_index(drop=True)


def _equity_curve_frame(summary: DaySummary) -> pd.DataFrame:
    if not summary.equity_curve:
        return pd.DataFrame(columns=["timestamp", "value"])
    return pd.DataFrame(summary.equity_curve, columns=["timestamp", "value"])


def _activities_frame(
    loader: MarketDataLoader,
    round_num: int,
    day: str,
    summary: DaySummary,
) -> pd.DataFrame:
    prices_file = f"prices_round_{round_num}_day_{day}.csv"
    activities = loader.load_prices(prices_file).copy()

    if summary.feature_ticks:
        feature_frame = pd.DataFrame(
            [{"timestamp": tick.timestamp, "product": tick.symbol, **tick.features} for tick in summary.feature_ticks]
        )
        activities = activities.merge(feature_frame, on=["timestamp", "product"], how="left")

    if summary.quotes:
        quote_frame = pd.DataFrame(
            [
                {
                    "timestamp": quote.timestamp,
                    "product": quote.symbol,
                    "quote_bid": quote.bid,
                    "quote_ask": quote.ask,
                    "quote_bid_size": quote.bid_size,
                    "quote_ask_size": quote.ask_size,
                }
                for quote in summary.quotes
            ]
        )
        activities = activities.merge(quote_frame, on=["timestamp", "product"], how="left")

    return activities.sort_values(["product", "timestamp"]).reset_index(drop=True)


def _build_backtest_log(
    official_log: OfficialLog,
    summary: DaySummary,
    round_num: int,
    day: str,
    data_dir: str | Path,
) -> OfficialLog:
    loader = MarketDataLoader(data_dir)
    activities = _activities_frame(loader, round_num, day, summary)
    trades = _fills_to_trades_frame(summary)
    graph = _equity_curve_frame(summary)
    payload = {
        "submissionId": f"{official_log.submission_id}_backtest_day_{day}",
        "profit": float(summary.pnl),
        "status": "BACKTEST",
        "round": str(round_num),
        "day": str(day),
    }
    return OfficialLog(
        source_path=official_log.source_path,
        payload=payload,
        summary_payload=payload,
        detail_payload=None,
        companion_path=None,
        submission_source_path=official_log.submission_source_path,
        activities=activities,
        trades=trades,
        graph=graph,
        positions=pd.DataFrame(),
        runtime_logs=pd.DataFrame(),
    )


def summarize_backtest_review(log: OfficialLog, summary: DaySummary, requested_day: str, resolved_day: str) -> str:
    traded_symbols = {fill.symbol for fill in summary.fills}
    return (
        f"submission={log.submission_id} backtest_day_request={requested_day} resolved_day={resolved_day} "
        f"pnl={summary.pnl} fills={len(summary.fills)} symbols={sorted(traded_symbols)}"
    )


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local backtest for the submission tied to an official log, then generate an HTML review")
    parser.add_argument("--log", required=True, help="Path to an official JSON or LOG file")
    parser.add_argument("--day", required=True, help="Backtest day choice. Use 0/1/2 for recent ordering, or a raw day like -1")
    parser.add_argument("--symbol", action="append", help="Product symbol to plot, can be passed multiple times")
    parser.add_argument("--outdir", default="artifacts/analysis", help="Directory that will receive generated plots")
    parser.add_argument("--group", default=None, help="Override subfolder name under --outdir (default: parent folder of log)")
    parser.add_argument("--edge", type=float, default=1.0, help="Opportunity threshold around fair value")
    parser.add_argument("--data-dir", default="data/round_1", help="Directory that contains the round CSV files")
    parser.add_argument("--round", type=int, default=None, help="Override round number (auto-detected by default)")
    parser.add_argument(
        "--execution-rule",
        default="realistic",
        choices=[mode.value for mode in TradeMatchingMode],
        help="Backtest matching rule",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    official_log = load_official_log(args.log)
    if official_log.submission_source_path is None:
        raise ValueError(f"No .py companion found next to {official_log.source_path}")

    round_num = _infer_round_num(official_log, args.round)
    loader = MarketDataLoader(args.data_dir)
    available_days = loader.available_days(round_num)
    if not available_days:
        raise ValueError(f"No backtest day found under {args.data_dir} for round {round_num}")

    resolved_day = _resolve_backtest_day(args.day, available_days)
    engine = FileBacktestEngine(
        data_dir=args.data_dir,
        strategy_file=official_log.submission_source_path,
        round_num=round_num,
    )
    summary = engine.run_day(resolved_day, mode=TradeMatchingMode(args.execution_rule))
    backtest_log = _build_backtest_log(official_log, summary, round_num, resolved_day, args.data_dir)

    symbols = args.symbol or sorted(backtest_log.activities["product"].dropna().unique())
    print(summarize_backtest_review(official_log, summary, args.day, resolved_day))
    for symbol in symbols:
        output_path = plot_symbol_review_plotly(backtest_log, symbol, args.outdir, edge=args.edge, group=args.group)
        print(f"saved {output_path}")
    return 0
