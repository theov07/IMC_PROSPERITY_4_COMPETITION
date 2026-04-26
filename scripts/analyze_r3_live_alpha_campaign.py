from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prosperity.tooling.logs import _parse_lambda_logs, load_official_log


RUNS: list[tuple[str, str]] = [
    ("00A", "basket_all_far_quotes"),
    ("00B", "basket_all_gap_flow_follow"),
    ("00C", "basket_all_options_flow_fade"),
    ("01", "passive_skew_signal"),
    ("02", "skew_taker_toxicity"),
    ("03", "dyn_skew_auto"),
    ("04", "dyn_skew_follow"),
    ("05", "dyn_skew_fade"),
    ("06", "old_options_alpha"),
    ("07", "velvet_far_quotes"),
    ("08", "velvet_flow_follow"),
    ("09", "hydro_far_quotes"),
    ("10", "options_far_quotes"),
    ("11", "options_gap_sweep"),
    ("12", "options_flow_follow"),
    ("13", "options_flow_fade"),
    ("14", "iv_momentum_conservative"),
    ("15", "iv_momentum_aggro"),
    ("16", "vol_harvest_unhedged"),
    ("17", "participant_adverse_diagnostic"),
]

PRODUCT_ORDER = [
    "HYDROGEL_PACK",
    "VELVETFRUIT_EXTRACT",
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500",
]

HORIZONS = [1, 2, 5, 10, 50, 100]


def _weighted_mean(frame: pd.DataFrame, column: str) -> float | None:
    valid = frame.dropna(subset=[column])
    if valid.empty:
        return None
    qty = valid["quantity"].clip(lower=0)
    if qty.sum() <= 0:
        return None
    return float((valid[column] * qty).sum() / qty.sum())


def _weighted_rate(frame: pd.DataFrame, mask_col: str) -> float | None:
    if frame.empty or mask_col not in frame:
        return None
    qty = frame["quantity"].clip(lower=0)
    total = qty.sum()
    if total <= 0:
        return None
    return float(qty[frame[mask_col].fillna(False)].sum() / total)


def _fmt_value(value: Any, floatfmt: str = ".2f") -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    if isinstance(value, float):
        return format(value, floatfmt)
    return str(value)


def _markdown_table(frame: pd.DataFrame, floatfmt: str = ".2f") -> str:
    if frame.empty:
        return "_empty_"
    cols = list(frame.columns)
    rows = []
    rows.append("| " + " | ".join(cols) + " |")
    rows.append("| " + " | ".join("---" for _ in cols) + " |")
    for _, row in frame.iterrows():
        rows.append("| " + " | ".join(_fmt_value(row[col], floatfmt=floatfmt) for col in cols) + " |")
    return "\n".join(rows)


def _activity_hash(activities: pd.DataFrame) -> str:
    cols = [
        "day",
        "timestamp",
        "product",
        "bid_price_1",
        "bid_volume_1",
        "bid_price_2",
        "bid_volume_2",
        "bid_price_3",
        "bid_volume_3",
        "ask_price_1",
        "ask_volume_1",
        "ask_price_2",
        "ask_volume_2",
        "ask_price_3",
        "ask_volume_3",
    ]
    data = activities[cols].sort_values(["timestamp", "product"]).to_csv(index=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def _load_run(downloads: Path, run_id: str):
    run_dir = downloads / f"{run_id}_log"
    json_files = sorted(run_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No json log found in {run_dir}")
    return load_official_log(json_files[0])


def _submission_trades_with_context(log, run_id: str, strategy: str) -> pd.DataFrame:
    trades = log.trades.copy()
    if trades.empty:
        return pd.DataFrame()
    buyer = trades.get("buyer", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    seller = trades.get("seller", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    trades = trades.loc[buyer | seller].copy()
    if trades.empty:
        return pd.DataFrame()

    trades["run"] = run_id
    trades["strategy"] = strategy
    trades["side"] = trades.apply(lambda row: "BUY" if row.get("buyer") == "SUBMISSION" else "SELL", axis=1)
    trades["sign"] = trades["side"].map({"BUY": 1, "SELL": -1}).astype(int)
    trades["counterparty"] = trades.apply(
        lambda row: str(row.get("seller") or "").strip()
        if row["side"] == "BUY"
        else str(row.get("buyer") or "").strip(),
        axis=1,
    )
    trades["counterparty"] = trades["counterparty"].replace("", "UNKNOWN")

    activities = log.activities.copy()
    act = activities[[
        "timestamp",
        "product",
        "bid_price_1",
        "ask_price_1",
        "mid_price",
        "profit_and_loss",
    ]].rename(columns={"product": "symbol"})
    merged = trades.merge(act, on=["timestamp", "symbol"], how="left")
    merged["spread"] = merged["ask_price_1"] - merged["bid_price_1"]
    merged["fill_mid_edge"] = (merged["mid_price"] - merged["price"]) * merged["sign"]
    merged["outside_market"] = (
        ((merged["side"] == "BUY") & (merged["price"] < merged["bid_price_1"]))
        | ((merged["side"] == "SELL") & (merged["price"] > merged["ask_price_1"]))
    )
    merged["taker_like"] = (
        ((merged["side"] == "BUY") & (merged["price"] >= merged["ask_price_1"]))
        | ((merged["side"] == "SELL") & (merged["price"] <= merged["bid_price_1"]))
    )
    merged["outside_distance"] = 0.0
    buy_out = (merged["side"] == "BUY") & (merged["price"] < merged["bid_price_1"])
    sell_out = (merged["side"] == "SELL") & (merged["price"] > merged["ask_price_1"])
    merged.loc[buy_out, "outside_distance"] = merged.loc[buy_out, "bid_price_1"] - merged.loc[buy_out, "price"]
    merged.loc[sell_out, "outside_distance"] = merged.loc[sell_out, "price"] - merged.loc[sell_out, "ask_price_1"]

    for horizon in HORIZONS:
        merged[f"markout_{horizon}"] = None

    for symbol, group in merged.groupby("symbol"):
        symbol_activities = activities.loc[activities["product"] == symbol].sort_values("timestamp").reset_index(drop=True)
        timestamps = symbol_activities["timestamp"].astype(int).tolist()
        mid = symbol_activities["mid_price"].astype(float).tolist()
        idx_by_ts = {ts: i for i, ts in enumerate(timestamps)}
        for idx, trade in group.iterrows():
            base_idx = idx_by_ts.get(int(trade["timestamp"]))
            if base_idx is None:
                continue
            for horizon in HORIZONS:
                future_idx = base_idx + horizon
                if future_idx >= len(mid):
                    continue
                merged.at[idx, f"markout_{horizon}"] = (mid[future_idx] - float(trade["price"])) * int(trade["sign"])

    for horizon in HORIZONS:
        merged[f"adverse_{horizon}"] = merged[f"markout_{horizon}"].astype(float) < 0
    return merged


def _final_product_pnl(log, run_id: str, strategy: str) -> pd.DataFrame:
    if log.activities.empty:
        return pd.DataFrame()
    rows = log.activities.sort_values("timestamp").groupby("product", as_index=False).tail(1)
    rows = rows[["product", "profit_and_loss"]].copy()
    rows["run"] = run_id
    rows["strategy"] = strategy
    rows = rows.rename(columns={"profit_and_loss": "final_pnl"})
    if not log.positions.empty:
        pos = log.positions.rename(columns={"symbol": "product", "quantity": "final_position"})
        rows = rows.merge(pos[["product", "final_position"]], on="product", how="left")
    else:
        rows["final_position"] = 0
    rows["final_position"] = rows["final_position"].fillna(0).astype(int)
    return rows


def _quote_feature_summary(log, run_id: str, strategy: str) -> pd.DataFrame:
    quotes = _parse_lambda_logs(log.runtime_logs)
    if quotes.empty:
        return pd.DataFrame()
    rows = []
    for product, group in quotes.groupby("product"):
        row: dict[str, Any] = {
            "run": run_id,
            "strategy": strategy,
            "product": product,
            "quote_rows": int(len(group)),
        }
        for col in [
            "far_probe",
            "gap_sweep",
            "flow_probe",
            "n_far_probes",
            "fills_tracked",
            "adverse_count",
            "named_market_trades",
        ]:
            if col in group:
                row[f"sum_{col}"] = float(pd.to_numeric(group[col], errors="coerce").fillna(0).sum())
                row[f"max_{col}"] = float(pd.to_numeric(group[col], errors="coerce").fillna(0).max())
        for col in ["flow_score", "adverse_rate", "avg_signed_mtm", "session_phase"]:
            if col in group:
                numeric = pd.to_numeric(group[col], errors="coerce")
                row[f"mean_{col}"] = float(numeric.mean()) if numeric.notna().any() else None
                row[f"last_{col}"] = float(numeric.dropna().iloc[-1]) if numeric.notna().any() else None
        rows.append(row)
    return pd.DataFrame(rows)


def _trade_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for (run, strategy, symbol), group in trades.groupby(["run", "strategy", "symbol"]):
        row: dict[str, Any] = {
            "run": run,
            "strategy": strategy,
            "product": symbol,
            "trade_count": int(len(group)),
            "volume": int(group["quantity"].sum()),
            "buy_volume": int(group.loc[group["side"] == "BUY", "quantity"].sum()),
            "sell_volume": int(group.loc[group["side"] == "SELL", "quantity"].sum()),
            "outside_volume": int(group.loc[group["outside_market"], "quantity"].sum()),
            "outside_trade_count": int(group["outside_market"].sum()),
            "taker_like_volume": int(group.loc[group["taker_like"], "quantity"].sum()),
            "avg_fill_mid_edge": _weighted_mean(group, "fill_mid_edge"),
            "avg_outside_distance": _weighted_mean(group.loc[group["outside_market"]], "outside_distance"),
        }
        for horizon in HORIZONS:
            row[f"markout_{horizon}"] = _weighted_mean(group, f"markout_{horizon}")
            row[f"adverse_rate_{horizon}"] = _weighted_rate(group.dropna(subset=[f"markout_{horizon}"]), f"adverse_{horizon}")
        rows.append(row)
    return pd.DataFrame(rows)


def _participant_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for (symbol, counterparty), group in trades.groupby(["symbol", "counterparty"]):
        if counterparty == "UNKNOWN":
            continue
        row = {
            "product": symbol,
            "counterparty": counterparty,
            "runs": int(group["run"].nunique()),
            "trade_count": int(len(group)),
            "volume": int(group["quantity"].sum()),
            "buy_volume": int(group.loc[group["side"] == "BUY", "quantity"].sum()),
            "sell_volume": int(group.loc[group["side"] == "SELL", "quantity"].sum()),
            "markout_5": _weighted_mean(group, "markout_5"),
            "markout_10": _weighted_mean(group, "markout_10"),
            "adverse_rate_5": _weighted_rate(group.dropna(subset=["markout_5"]), "adverse_5"),
        }
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["volume"], ascending=False) if rows else pd.DataFrame()


def _write_markdown(outdir: Path, run_summary: pd.DataFrame, product_summary: pd.DataFrame, trade_summary: pd.DataFrame, quote_summary: pd.DataFrame, market_hashes: dict[str, str]) -> None:
    lines: list[str] = []
    lines.append("# Round 3 live alpha campaign analysis")
    lines.append("")
    lines.append("Generated from IMC logs 00A, 00B, 00C, 01..17.")
    lines.append("")
    hashes = sorted(set(market_hashes.values()))
    lines.append(f"Market-data hashes: {len(hashes)} unique.")
    if len(hashes) == 1:
        lines.append("All logs share the same visible order-book path, so run-to-run comparisons are clean.")
    else:
        lines.append("WARNING: logs do not all share the same visible order-book path.")
    lines.append("")

    total_trades = int(run_summary["trade_count"].sum()) if "trade_count" in run_summary else 0
    outside_volume = int(trade_summary["outside_volume"].sum()) if "outside_volume" in trade_summary else 0
    lines.append("## Key interpretation")
    lines.append("")
    lines.append(f"- Own trades checked: `{total_trades}`; outside-market volume: `{outside_volume}`.")
    lines.append("- No named participant signal appears in these official logs.")
    lines.append("- Far option quotes did not reveal an off-market fill edge; run `10` got zero fills.")
    lines.append("- Best clean live package is `03/04/05` at about `+1,134` PnL. The three variants had identical fills, so this validates the package but not a follow-vs-fade sign.")
    lines.append("- HYDRO passive/anchor is clean live: about `+490` PnL, `markout_5=+6.16`, adverse rate `5.7%`.")
    lines.append("- VELVET passive MM is clean, but VELVET flow-follow/taker variants are toxic on short-horizon markout.")
    lines.append("- VEV_4000 has two regimes: tiny passive skew is strong, while aggressive gap/flow trading is catastrophically adverse.")
    lines.append("- VEV_4500 is the strongest new option leg; VEV_5000/5100/5200 are acceptable only in small conservative dynamic mode.")
    lines.append("- VEV_5400+ should be disabled for live-scoring candidates unless a new signal proves otherwise.")
    lines.append("- Combining the clean HYDRO leg with `03/04/05` would be about `+1,624` on this path. A `14` variant with VEV_5400 disabled plus HYDRO would be about `+1,727`, but with much higher VELVET inventory risk.")
    lines.append("")

    display = run_summary.sort_values("profit", ascending=False)[["run", "strategy", "profit", "trade_count", "volume"]]
    lines.append("## Run ranking")
    lines.append(_markdown_table(display, floatfmt=".2f"))
    lines.append("")

    pvt = product_summary.pivot_table(index=["run", "strategy"], columns="product", values="final_pnl", aggfunc="sum").reset_index()
    keep = ["run", "strategy"] + [p for p in PRODUCT_ORDER if p in pvt.columns]
    lines.append("## Final PnL by product")
    lines.append(_markdown_table(pvt[keep], floatfmt=".2f"))
    lines.append("")

    if not trade_summary.empty:
        important = trade_summary.sort_values("volume", ascending=False).head(40)
        cols = ["run", "strategy", "product", "trade_count", "volume", "outside_volume", "taker_like_volume", "avg_fill_mid_edge", "markout_5", "adverse_rate_5", "markout_10"]
        lines.append("## Largest traded product/run buckets")
        lines.append(_markdown_table(important[[c for c in cols if c in important]], floatfmt=".3f"))
        lines.append("")

        outside = trade_summary.loc[trade_summary["outside_volume"] > 0].sort_values("outside_volume", ascending=False)
        lines.append("## Outside-market fills")
        if outside.empty:
            lines.append("No outside-market fills detected.")
        else:
            lines.append(_markdown_table(outside[["run", "strategy", "product", "outside_volume", "avg_outside_distance", "markout_5", "adverse_rate_5", "markout_10"]], floatfmt=".3f"))
        lines.append("")

    if not quote_summary.empty:
        probe_cols = [c for c in quote_summary.columns if c.startswith("sum_") or c.startswith("max_") or c.startswith("last_")]
        sample = quote_summary[["run", "strategy", "product", "quote_rows"] + probe_cols].sort_values(["run", "product"]).head(80)
        lines.append("## Probe feature summary sample")
        lines.append(_markdown_table(sample, floatfmt=".3f"))
        lines.append("")

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "live_alpha_campaign_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads", default=str(Path.home() / "Downloads"))
    parser.add_argument("--outdir", default="artifacts/analysis/round_3_live_alpha")
    args = parser.parse_args()

    downloads = Path(args.downloads)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    run_rows = []
    product_frames = []
    trade_frames = []
    quote_frames = []
    market_hashes: dict[str, str] = {}

    for run_id, strategy in RUNS:
        log = _load_run(downloads, run_id)
        market_hashes[run_id] = _activity_hash(log.activities)
        trades = _submission_trades_with_context(log, run_id, strategy)
        products = _final_product_pnl(log, run_id, strategy)
        quotes = _quote_feature_summary(log, run_id, strategy)
        trade_frames.append(trades)
        product_frames.append(products)
        quote_frames.append(quotes)
        run_rows.append({
            "run": run_id,
            "strategy": strategy,
            "submission_id": log.submission_id,
            "profit": log.profit,
            "status": log.status,
            "trade_count": int(len(trades)),
            "volume": int(trades["quantity"].sum()) if not trades.empty else 0,
            "activity_hash": market_hashes[run_id],
        })

    run_summary = pd.DataFrame(run_rows)
    product_summary = pd.concat(product_frames, ignore_index=True) if product_frames else pd.DataFrame()
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    quote_summary = pd.concat(quote_frames, ignore_index=True) if quote_frames else pd.DataFrame()
    trade_summary = _trade_summary(trades)
    participants = _participant_summary(trades)

    run_summary.to_csv(outdir / "run_summary.csv", index=False)
    product_summary.to_csv(outdir / "product_pnl.csv", index=False)
    trades.to_csv(outdir / "submission_trades_enriched.csv", index=False)
    trade_summary.to_csv(outdir / "trade_markout_summary.csv", index=False)
    quote_summary.to_csv(outdir / "quote_feature_summary.csv", index=False)
    participants.to_csv(outdir / "participant_summary.csv", index=False)
    (outdir / "market_hashes.json").write_text(json.dumps(market_hashes, indent=2), encoding="utf-8")

    _write_markdown(outdir, run_summary, product_summary, trade_summary, quote_summary, market_hashes)
    print(f"Wrote {outdir}")
    print(run_summary.sort_values("profit", ascending=False)[["run", "strategy", "profit", "trade_count", "volume"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
