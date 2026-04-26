"""Round 3 cross-asset regime and node analysis.

This tool turns the "Cross-Asset Evolution" dashboard intuition into tables:

* rolling correlation between normalized HYDROGEL and VELVET paths
* node detection where the normalized paths converge
* forward markouts after each regime/node

It is intentionally read-only with respect to strategies/config. Outputs live
under artifacts/analysis/round_3_cross_asset by default.

Example:
    python -m prosperity.tooling.r3_cross_asset_patterns
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, List

import numpy as np
import pandas as pd


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
DEFAULT_TARGETS = [
    VELVET,
    HYDROGEL,
    "VEV_5000",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
]


def _load_day(data_dir: Path, day: int) -> pd.DataFrame:
    path = data_dir / f"prices_round_3_day_{day}.csv"
    df = pd.read_csv(path, sep=";")
    return (
        df.pivot(index="timestamp", columns="product", values="mid_price")
        .sort_index()
        .astype(float)
    )


def _timestamp_step(index: pd.Index) -> int:
    values = np.asarray(index, dtype=float)
    if len(values) < 2:
        return 100
    diffs = np.diff(values)
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        return 100
    return int(np.median(diffs))


def _horizon_to_steps(horizon: int, step: int) -> int:
    return max(1, int(round(horizon / max(step, 1))))


def _zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=max(20, window // 5)).mean()
    std = series.rolling(window, min_periods=max(20, window // 5)).std()
    return (series - mean) / std.replace(0, np.nan)


def _classify_regime(
    corr: float,
    spread_abs: float,
    *,
    node_threshold: float,
    pos_threshold: float,
    neg_threshold: float,
    decorr_threshold: float,
) -> str:
    if pd.isna(corr):
        return "WARMUP"
    if spread_abs <= node_threshold:
        return "NODE"
    if corr >= pos_threshold:
        return "POS_COUPLED"
    if corr <= -neg_threshold:
        return "NEG_COUPLED"
    if abs(corr) <= decorr_threshold:
        return "DECOUPLED"
    return "MIXED"


def _safe_hit_rate(values: pd.Series) -> float | None:
    clean = values.dropna()
    if clean.empty:
        return None
    return float((clean > 0).mean())


def _safe_tstat(values: pd.Series) -> float | None:
    clean = values.dropna()
    if len(clean) < 3:
        return None
    std = clean.std()
    if std == 0 or pd.isna(std):
        return None
    return float(clean.mean() / (std / math.sqrt(len(clean))))


def _node_runs(events: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    rows = []
    for day, day_df in events.groupby("day"):
        node = day_df["is_node"].fillna(False).to_numpy()
        if len(node) == 0:
            continue
        timestamps = day_df["timestamp"].to_numpy()
        spread = day_df["spread_norm"].to_numpy()
        start_idx = None
        for idx, is_node in enumerate(node):
            if is_node and start_idx is None:
                start_idx = idx
            if (not is_node or idx == len(node) - 1) and start_idx is not None:
                end_idx = idx if is_node and idx == len(node) - 1 else idx - 1
                if end_idx >= start_idx:
                    row = {
                        "day": int(day),
                        "start_ts": int(timestamps[start_idx]),
                        "end_ts": int(timestamps[end_idx]),
                        "duration_ts": int(timestamps[end_idx] - timestamps[start_idx]),
                        "ticks": int(end_idx - start_idx + 1),
                        "mean_abs_spread": float(np.nanmean(np.abs(spread[start_idx : end_idx + 1]))),
                    }
                    end_ts = int(timestamps[end_idx])
                    end_row = day_df[day_df["timestamp"] == end_ts]
                    if not end_row.empty:
                        first = end_row.iloc[0]
                        for horizon in horizons:
                            for col in [
                                f"fwd_{VELVET}_{horizon}_bps",
                                f"fwd_{HYDROGEL}_{horizon}_bps",
                                f"fwd_abs_spread_change_{horizon}",
                            ]:
                                if col in first:
                                    row[col] = first[col]
                    rows.append(row)
                start_idx = None
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["ticks", "duration_ts"], ascending=False)


def analyze_cross_asset_patterns(
    *,
    data_dir: str | Path = "data/round_3",
    days: List[int] | None = None,
    window: int = 1000,
    return_step: int = 100,
    sample_every: int = 10,
    node_threshold: float = 0.10,
    pos_threshold: float = 0.55,
    neg_threshold: float = 0.55,
    decorr_threshold: float = 0.15,
    horizons: List[int] | None = None,
    targets: List[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    data_dir = Path(data_dir)
    days = days or [0, 1, 2]
    horizons = horizons or [1000, 5000, 10000, 50000]
    targets = targets or DEFAULT_TARGETS

    event_frames = []
    for day in days:
        piv = _load_day(data_dir, day)
        if HYDROGEL not in piv or VELVET not in piv:
            continue
        step = _timestamp_step(piv.index)
        hv = piv[[HYDROGEL, VELVET]].dropna()
        norm = hv / hv.iloc[0] * 100.0

        spread = norm[HYDROGEL] - norm[VELVET]
        level_corr = norm[HYDROGEL].rolling(window, min_periods=max(50, window // 5)).corr(norm[VELVET])
        moves = norm.diff(return_step)
        move_corr = moves[HYDROGEL].rolling(window, min_periods=max(50, window // 5)).corr(moves[VELVET])

        events = pd.DataFrame(
            {
                "day": day,
                "timestamp": norm.index.astype(int),
                "hydro_norm": norm[HYDROGEL],
                "velvet_norm": norm[VELVET],
                "spread_norm": spread,
                "abs_spread_norm": spread.abs(),
                "spread_z": _zscore(spread, window),
                "rolling_level_corr": level_corr,
                "rolling_move_corr": move_corr,
            },
            index=norm.index,
        )
        events["is_node"] = events["abs_spread_norm"] <= node_threshold
        events["regime"] = [
            _classify_regime(
                corr,
                spread_abs,
                node_threshold=node_threshold,
                pos_threshold=pos_threshold,
                neg_threshold=neg_threshold,
                decorr_threshold=decorr_threshold,
            )
            for corr, spread_abs in zip(events["rolling_level_corr"], events["abs_spread_norm"])
        ]

        for horizon in horizons:
            steps = _horizon_to_steps(horizon, step)
            future_spread = spread.shift(-steps)
            events[f"fwd_spread_change_{horizon}"] = future_spread - spread
            events[f"fwd_abs_spread_change_{horizon}"] = future_spread.abs() - spread.abs()
            for target in targets:
                if target not in piv:
                    continue
                px = piv[target].astype(float)
                fwd = px.shift(-steps)
                events[f"fwd_{target}_{horizon}_bps"] = (fwd / px - 1.0) * 10000.0

        if sample_every > 1:
            events = events.iloc[::sample_every].copy()
        event_frames.append(events.reset_index(drop=True))

    if not event_frames:
        raise RuntimeError("No usable R3 HYDROGEL/VELVET data found.")

    all_events = pd.concat(event_frames, ignore_index=True)

    summary_rows = []

    def add_summary_row(regime: str, day_label, group: pd.DataFrame) -> None:
        base = {
            "regime": regime,
            "day": day_label,
            "samples": int(len(group)),
            "mean_level_corr": float(group["rolling_level_corr"].mean()),
            "mean_move_corr": float(group["rolling_move_corr"].mean()),
            "mean_abs_spread_norm": float(group["abs_spread_norm"].mean()),
        }
        for horizon in horizons:
            for target in targets:
                col = f"fwd_{target}_{horizon}_bps"
                if col not in group:
                    continue
                values = group[col]
                summary_rows.append(
                    {
                        **base,
                        "horizon": horizon,
                        "target": target,
                        "mean_bps": float(values.mean()),
                        "median_bps": float(values.median()),
                        "hit_rate": _safe_hit_rate(values),
                        "tstat": _safe_tstat(values),
                    }
                )
            spread_col = f"fwd_abs_spread_change_{horizon}"
            if spread_col in group:
                summary_rows.append(
                    {
                        **base,
                        "horizon": horizon,
                        "target": "ABS_SPREAD",
                        "mean_bps": float(group[spread_col].mean()),
                        "median_bps": float(group[spread_col].median()),
                        "hit_rate": _safe_hit_rate(group[spread_col]),
                        "tstat": _safe_tstat(group[spread_col]),
                    }
                )

    for (regime, day), group in all_events.groupby(["regime", "day"], dropna=False):
        add_summary_row(str(regime), int(day), group)
    for regime, group in all_events.groupby("regime", dropna=False):
        add_summary_row(str(regime), "ALL", group)

    summary = pd.DataFrame(summary_rows)
    pooled_summary = (
        all_events.assign(day="ALL")
        .groupby(["regime"], dropna=False)
        .size()
        .rename("samples")
        .reset_index()
    )

    node_runs = _node_runs(all_events, horizons)
    metadata = {
        "data_dir": str(data_dir),
        "days": days,
        "window": window,
        "return_step": return_step,
        "sample_every": sample_every,
        "node_threshold": node_threshold,
        "pos_threshold": pos_threshold,
        "neg_threshold": neg_threshold,
        "decorr_threshold": decorr_threshold,
        "horizons": horizons,
        "targets": targets,
        "pooled_regime_counts": dict(zip(pooled_summary["regime"], pooled_summary["samples"])),
    }
    return all_events, summary, node_runs, metadata


def _fmt(value: float | int | None, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return f"{float(value):.{digits}f}"


def _markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(out)


def _build_markdown(summary: pd.DataFrame, node_runs: pd.DataFrame, metadata: dict) -> str:
    lines = [
        "# Round 3 Cross-Asset Pattern Report",
        "",
        "Signals are measured on normalized HYDROGEL/VELVET paths, matching the dashboard's Cross-Asset Evolution view.",
        "",
        "## Regime Counts",
    ]
    count_rows = [[str(k), str(v)] for k, v in sorted(metadata["pooled_regime_counts"].items())]
    lines.append(_markdown_table(["Regime", "Samples"], count_rows))

    for horizon in metadata["horizons"]:
        target = VELVET
        subset = summary[(summary["day"] == "ALL") & (summary["horizon"] == horizon) & (summary["target"] == target)]
        if subset.empty:
            continue
        pooled = subset.sort_values("mean_bps", ascending=False)
        lines.extend(
            [
                "",
                f"## VELVET Forward Markout +{horizon}",
                _markdown_table(
                    ["Regime", "Samples", "Mean bps", "Median bps", "Hit", "Avg t", "Abs spread"],
                    [
                        [
                            str(row["regime"]),
                            str(int(row["samples"])),
                            _fmt(row["mean_bps"], 2),
                            _fmt(row["median_bps"], 2),
                            _fmt(row["hit_rate"], 3),
                            _fmt(row["tstat"], 2),
                            _fmt(row["mean_abs_spread_norm"], 3),
                        ]
                        for _, row in pooled.iterrows()
                    ],
                ),
            ]
        )

    if not node_runs.empty:
        top = node_runs.head(12)
        lines.extend(
            [
                "",
                "## Longest Nodes",
                _markdown_table(
                    ["Day", "Start", "End", "Ticks", "Mean abs spread"],
                    [
                        [
                            str(int(row["day"])),
                            str(int(row["start_ts"])),
                            str(int(row["end_ts"])),
                            str(int(row["ticks"])),
                            _fmt(row["mean_abs_spread"], 3),
                        ]
                        for _, row in top.iterrows()
                    ],
                ),
            ]
        )

    lines.extend(
        [
            "",
            "## Parameters",
            "```json",
            json.dumps(metadata, indent=2),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R3 HYDROGEL/VELVET cross-asset pattern analysis")
    parser.add_argument("--data-dir", default="data/round_3")
    parser.add_argument("--days", nargs="*", type=int, default=[0, 1, 2])
    parser.add_argument("--window", type=int, default=1000, help="Rolling window in observations")
    parser.add_argument("--return-step", type=int, default=100, help="Difference step in observations for move corr")
    parser.add_argument("--sample-every", type=int, default=10, help="Keep one event row every N observations")
    parser.add_argument("--node-threshold", type=float, default=0.10, help="Normalized path distance for node regime")
    parser.add_argument("--pos-threshold", type=float, default=0.55)
    parser.add_argument("--neg-threshold", type=float, default=0.55)
    parser.add_argument("--decorr-threshold", type=float, default=0.15)
    parser.add_argument("--horizons", nargs="*", type=int, default=[1000, 5000, 10000, 50000])
    parser.add_argument("--targets", nargs="*", default=DEFAULT_TARGETS)
    parser.add_argument("--outdir", default="artifacts/analysis/round_3_cross_asset")
    args = parser.parse_args(list(argv) if argv is not None else None)

    events, summary, node_runs, metadata = analyze_cross_asset_patterns(
        data_dir=args.data_dir,
        days=args.days,
        window=args.window,
        return_step=args.return_step,
        sample_every=args.sample_every,
        node_threshold=args.node_threshold,
        pos_threshold=args.pos_threshold,
        neg_threshold=args.neg_threshold,
        decorr_threshold=args.decorr_threshold,
        horizons=args.horizons,
        targets=args.targets,
    )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    events_path = outdir / "events.csv"
    summary_path = outdir / "regime_markouts.csv"
    nodes_path = outdir / "node_runs.csv"
    report_path = outdir / "report.md"
    metadata_path = outdir / "metadata.json"

    events.to_csv(events_path, index=False)
    summary.to_csv(summary_path, index=False)
    node_runs.to_csv(nodes_path, index=False)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    report_path.write_text(_build_markdown(summary, node_runs, metadata), encoding="utf-8")

    print(f"Wrote {events_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {nodes_path}")
    print(f"Wrote {report_path}")
    print("Regime counts:", metadata["pooled_regime_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
