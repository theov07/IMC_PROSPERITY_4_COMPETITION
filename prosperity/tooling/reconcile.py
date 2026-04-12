"""Reconcile a local backtest JSON against an official IMC submission log.

Usage:
  python -m prosperity.tooling.reconcile --log logs/leo_round0_naiveV8/84616.json --backtest-json artifacts/backtest_results.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable

import pandas as pd

from prosperity.tooling.logs import OfficialLog, load_official_log


REPO_ROOT = Path(__file__).resolve().parents[2]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_text(value: str) -> str:
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value or "")
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value)
    return value.lower().strip()


def _tokenize(value: str) -> set[str]:
    stop = {"json", "log", "logs", "artifacts", "backtest", "results", "round"}
    return {
        token
        for token in _normalize_text(value).split()
        if token and token not in stop
    }


def _extract_strategy_tokens(official_log: OfficialLog) -> set[str]:
    tokens = set()
    tokens |= _tokenize(official_log.analysis_group)

    if official_log.submission_source_path and official_log.submission_source_path.exists():
        try:
            text = official_log.submission_source_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        for strategy_name in re.findall(r"""['"]strategy['"]\s*:\s*['"]([^'"]+)['"]""", text):
            tokens |= _tokenize(strategy_name)

    return tokens


def _load_backtest_candidate(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict) and "strategy" in payload and "days" in payload:
        return payload
    return None


def discover_backtest_json(official_log: OfficialLog, search_root: str | Path | None = None) -> Path | None:
    """Best-effort discovery of a local backtest JSON matching an official log.

    The matcher is intentionally conservative: it prefers explicit version/member
    matches and returns ``None`` when the local artifacts are ambiguous.
    """
    root = Path(search_root) if search_root is not None else REPO_ROOT
    artifacts_dir = root / "artifacts"
    if not artifacts_dir.exists():
        return None

    candidate_paths: list[Path] = []
    standard_paths = [
        artifacts_dir / "backtest_results.json",
        artifacts_dir / "backtest_results" / f"{official_log.analysis_group}.json",
        artifacts_dir / f"backtest_{official_log.analysis_group}.json",
    ]
    for candidate in standard_paths:
        if candidate.exists():
            candidate_paths.append(candidate)

    candidate_paths.extend(sorted(artifacts_dir.glob("backtest_*.json")))
    candidate_paths.extend(sorted((artifacts_dir / "backtest_results").glob("*.json")) if (artifacts_dir / "backtest_results").exists() else [])
    candidate_paths = list(dict.fromkeys(candidate_paths))

    query_tokens = _extract_strategy_tokens(official_log)
    query_versions = {token for token in query_tokens if re.fullmatch(r"v\d+", token)}
    query_members = query_tokens & {"champion", "leo", "theo", "pietro", "tibo"}

    scored: list[tuple[int, float, Path]] = []
    for candidate_path in candidate_paths:
        payload = _load_backtest_candidate(candidate_path)
        if payload is None:
            continue

        candidate_tokens = _tokenize(candidate_path.stem)
        candidate_tokens |= _tokenize(str(payload.get("strategy") or ""))
        candidate_versions = {token for token in candidate_tokens if re.fullmatch(r"v\d+", token)}
        candidate_members = candidate_tokens & {"champion", "leo", "theo", "pietro", "tibo"}

        overlap = query_tokens & candidate_tokens
        version_overlap = query_versions & candidate_versions
        member_overlap = query_members & candidate_members

        if query_versions and not version_overlap:
            continue

        score = 10 * len(overlap)
        score += 25 * len(version_overlap)
        score += 15 * len(member_overlap)
        if candidate_path.name == "backtest_results.json":
            score += 1

        if score <= 0:
            continue

        try:
            mtime = candidate_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        scored.append((score, mtime, candidate_path))

    if not scored:
        return None

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top_score = scored[0][0]
    top_paths = [path for score, _, path in scored if score == top_score]
    if len(top_paths) > 1:
        return None
    return top_paths[0]


def _official_product_pnl(log: OfficialLog) -> Dict[str, float]:
    if log.activities.empty:
        return {}

    frame = log.activities.sort_values(["product", "timestamp"]).copy()
    latest = frame.groupby("product", as_index=False).tail(1)
    return {
        str(row["product"]): _safe_float(row.get("profit_and_loss"))
        for _, row in latest.iterrows()
    }


def _official_positions(log: OfficialLog) -> Dict[str, int]:
    if log.positions.empty:
        return {}

    result: Dict[str, int] = {}
    for _, row in log.positions.iterrows():
        symbol = str(row.get("symbol") or "")
        if not symbol or symbol == "XIRECS":
            continue
        result[symbol] = _safe_int(row.get("quantity"))
    return result


def _official_trade_summary(log: OfficialLog) -> Dict[str, Dict[str, float | int]]:
    if log.trades.empty:
        return {}

    buyer_submission = log.trades.get("buyer", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    seller_submission = log.trades.get("seller", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    submission_trades = log.trades.loc[buyer_submission | seller_submission].copy()
    if submission_trades.empty:
        return {}

    summary: Dict[str, Dict[str, float | int]] = {}
    for _, row in submission_trades.iterrows():
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        side = "BUY" if str(row.get("buyer") or "") == "SUBMISSION" else "SELL"
        quantity = _safe_int(row.get("quantity"))
        price = _safe_float(row.get("price"))
        bucket = summary.setdefault(
            symbol,
            {
                "trade_count": 0,
                "buy_count": 0,
                "sell_count": 0,
                "buy_qty": 0,
                "sell_qty": 0,
                "net_qty": 0,
                "turnover": 0.0,
            },
        )
        bucket["trade_count"] += 1
        bucket["turnover"] += price * quantity
        if side == "BUY":
            bucket["buy_count"] += 1
            bucket["buy_qty"] += quantity
            bucket["net_qty"] += quantity
        else:
            bucket["sell_count"] += 1
            bucket["sell_qty"] += quantity
            bucket["net_qty"] -= quantity
    return summary


def _backtest_trade_summary(backtest_data: dict) -> Dict[str, Dict[str, float | int]]:
    summary: Dict[str, Dict[str, float | int]] = {}
    for day in backtest_data.get("days", []):
        for fill in day.get("fills", []):
            symbol = str(fill.get("symbol") or "")
            if not symbol:
                continue
            side = str(fill.get("side") or "")
            quantity = _safe_int(fill.get("quantity"))
            price = _safe_float(fill.get("price"))
            bucket = summary.setdefault(
                symbol,
                {
                    "trade_count": 0,
                    "buy_count": 0,
                    "sell_count": 0,
                    "buy_qty": 0,
                    "sell_qty": 0,
                    "net_qty": 0,
                    "turnover": 0.0,
                },
            )
            bucket["trade_count"] += 1
            bucket["turnover"] += price * quantity
            if side == "BUY":
                bucket["buy_count"] += 1
                bucket["buy_qty"] += quantity
                bucket["net_qty"] += quantity
            elif side == "SELL":
                bucket["sell_count"] += 1
                bucket["sell_qty"] += quantity
                bucket["net_qty"] -= quantity
    return summary


def _backtest_product_summary(backtest_data: dict) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    days = backtest_data.get("days", [])
    single_day = len(days) == 1

    for day in days:
        day_label = str(day.get("day"))
        for symbol, product in day.get("product_summaries", {}).items():
            bucket = summary.setdefault(
                symbol,
                {
                    "pnl": 0.0,
                    "trades": 0,
                    "traded_volume": 0,
                    "turnover": 0.0,
                    "max_abs_position": 0,
                    "ending_positions": [],
                },
            )
            bucket["pnl"] += _safe_float(product.get("pnl"))
            bucket["trades"] += _safe_int(product.get("trades"))
            bucket["traded_volume"] += _safe_int(product.get("traded_volume"))
            bucket["turnover"] += _safe_float(product.get("turnover"))
            bucket["max_abs_position"] = max(bucket["max_abs_position"], _safe_int(product.get("max_abs_position")))
            bucket["ending_positions"].append({"day": day_label, "position": _safe_int(product.get("ending_position"))})

    for product in summary.values():
        if single_day and product["ending_positions"]:
            product["ending_position"] = product["ending_positions"][0]["position"]
        else:
            product["ending_position"] = None
    return summary


def reconcile_backtest_to_official(backtest_data: dict, official_log: OfficialLog) -> dict:
    official_pnl_by_product = _official_product_pnl(official_log)
    official_positions = _official_positions(official_log)
    official_trades = _official_trade_summary(official_log)

    backtest_products = _backtest_product_summary(backtest_data)
    backtest_trades = _backtest_trade_summary(backtest_data)

    products = sorted(
        set(backtest_products)
        | set(official_pnl_by_product)
        | set(official_positions)
        | set(backtest_trades)
        | set(official_trades)
    )
    products = [symbol for symbol in products if symbol != "XIRECS"]

    total_backtest_pnl = sum(_safe_float(day.get("pnl")) for day in backtest_data.get("days", []))
    total_official_pnl = _safe_float(official_log.profit)

    per_product: Dict[str, Dict[str, Any]] = {}
    for symbol in products:
        bt_product = backtest_products.get(symbol, {})
        bt_trade = backtest_trades.get(symbol, {})
        off_trade = official_trades.get(symbol, {})

        per_product[symbol] = {
            "backtest": {
                "pnl": _safe_float(bt_product.get("pnl")),
                "ending_position": bt_product.get("ending_position"),
                "max_abs_position": _safe_int(bt_product.get("max_abs_position")),
                "trade_count": _safe_int(bt_trade.get("trade_count")),
                "buy_qty": _safe_int(bt_trade.get("buy_qty")),
                "sell_qty": _safe_int(bt_trade.get("sell_qty")),
                "net_qty": _safe_int(bt_trade.get("net_qty")),
                "turnover": _safe_float(bt_trade.get("turnover")),
                "ending_positions": bt_product.get("ending_positions", []),
            },
            "official": {
                "pnl": _safe_float(official_pnl_by_product.get(symbol)),
                "ending_position": official_positions.get(symbol),
                "trade_count": _safe_int(off_trade.get("trade_count")),
                "buy_qty": _safe_int(off_trade.get("buy_qty")),
                "sell_qty": _safe_int(off_trade.get("sell_qty")),
                "net_qty": _safe_int(off_trade.get("net_qty")),
                "turnover": _safe_float(off_trade.get("turnover")),
            },
        }
        per_product[symbol]["delta"] = {
            "pnl": per_product[symbol]["backtest"]["pnl"] - per_product[symbol]["official"]["pnl"],
            "trade_count": per_product[symbol]["backtest"]["trade_count"] - per_product[symbol]["official"]["trade_count"],
            "buy_qty": per_product[symbol]["backtest"]["buy_qty"] - per_product[symbol]["official"]["buy_qty"],
            "sell_qty": per_product[symbol]["backtest"]["sell_qty"] - per_product[symbol]["official"]["sell_qty"],
            "net_qty": per_product[symbol]["backtest"]["net_qty"] - per_product[symbol]["official"]["net_qty"],
            "turnover": per_product[symbol]["backtest"]["turnover"] - per_product[symbol]["official"]["turnover"],
            "ending_position": (
                None
                if per_product[symbol]["backtest"]["ending_position"] is None
                or per_product[symbol]["official"]["ending_position"] is None
                else per_product[symbol]["backtest"]["ending_position"] - per_product[symbol]["official"]["ending_position"]
            ),
        }

    return {
        "backtest": {
            "strategy": backtest_data.get("strategy"),
            "round": backtest_data.get("round"),
            "execution_rule": backtest_data.get("execution_rule"),
            "days": [str(day.get("day")) for day in backtest_data.get("days", [])],
            "total_pnl": total_backtest_pnl,
        },
        "official": {
            "submission_id": official_log.submission_id,
            "round": official_log.round_label,
            "status": official_log.status,
            "profit": total_official_pnl,
            "loaded_paths": [str(path) for path in official_log.loaded_paths],
        },
        "delta": {
            "total_pnl": total_backtest_pnl - total_official_pnl,
        },
        "per_product": per_product,
    }


def _format_money(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{_safe_float(value):+.2f}"


def _format_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(_safe_int(value))


def _print_report(report: dict) -> None:
    bt = report["backtest"]
    off = report["official"]

    print(
        f"Backtest: strategy={bt.get('strategy')} round={bt.get('round')} "
        f"execution_rule={bt.get('execution_rule') or 'unknown'} days={bt.get('days')}"
    )
    print(
        f"Official: submission={off.get('submission_id')} round={off.get('round')} "
        f"status={off.get('status')} profit={_format_money(off.get('profit'))}"
    )
    print(
        f"Total PnL delta: backtest={_format_money(bt.get('total_pnl'))} "
        f"official={_format_money(off.get('profit'))} "
        f"delta={_format_money(report['delta'].get('total_pnl'))}"
    )
    print()

    header = (
        f"{'Product':<12} {'BT PnL':>10} {'OFF PnL':>10} {'Delta':>10} "
        f"{'BT Trades':>10} {'OFF Trades':>10} {'BT End':>8} {'OFF End':>8}"
    )
    print(header)
    print("-" * len(header))

    for symbol, data in report["per_product"].items():
        bt_product = data["backtest"]
        off_product = data["official"]
        delta = data["delta"]
        print(
            f"{symbol:<12} "
            f"{_format_money(bt_product.get('pnl')):>10} "
            f"{_format_money(off_product.get('pnl')):>10} "
            f"{_format_money(delta.get('pnl')):>10} "
            f"{_format_int(bt_product.get('trade_count')):>10} "
            f"{_format_int(off_product.get('trade_count')):>10} "
            f"{_format_int(bt_product.get('ending_position')):>8} "
            f"{_format_int(off_product.get('ending_position')):>8}"
        )

    print()
    print("Volume / turnover deltas:")
    for symbol, data in report["per_product"].items():
        bt_product = data["backtest"]
        off_product = data["official"]
        delta = data["delta"]
        print(
            f"- {symbol}: "
            f"buy_qty {bt_product.get('buy_qty')} vs {off_product.get('buy_qty')}, "
            f"sell_qty {bt_product.get('sell_qty')} vs {off_product.get('sell_qty')}, "
            f"turnover {_format_money(bt_product.get('turnover'))} vs {_format_money(off_product.get('turnover'))}, "
            f"delta={_format_money(delta.get('turnover'))}"
        )


def summarize_reconcile_report(report: dict) -> str:
    delta_total = _format_money(report.get("delta", {}).get("total_pnl"))
    bt = report.get("backtest", {})
    per_product = report.get("per_product", {})

    product_parts = []
    for symbol, data in per_product.items():
        delta = data.get("delta", {})
        product_parts.append(
            f"{symbol}: pnl {_format_money(delta.get('pnl'))}, trades {delta.get('trade_count', 0):+d}"
        )

    details = " | ".join(product_parts)
    return (
        f"Reconcile: strategy={bt.get('strategy')} execution={bt.get('execution_rule') or 'unknown'} "
        f"total_delta={delta_total}"
        + (f" | {details}" if details else "")
    )


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile local backtest output with an official IMC submission log")
    parser.add_argument("--log", required=True, help="Path to official IMC JSON or LOG file")
    parser.add_argument("--backtest-json", required=True, help="Path to local backtest JSON")
    parser.add_argument("--json-out", help="Optional JSON report output path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    official_log = load_official_log(args.log)
    backtest_data = json.loads(Path(args.backtest_json).read_text(encoding="utf-8"))
    report = reconcile_backtest_to_official(backtest_data, official_log)
    _print_report(report)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nSaved report to {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
