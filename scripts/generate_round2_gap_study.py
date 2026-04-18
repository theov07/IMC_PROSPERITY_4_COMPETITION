import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import json

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from prosperity.tooling.logs import (
    load_official_log,
    official_position_path,
    plot_symbol_review_plotly,
)


SYMBOL = "INTARIAN_PEPPER_ROOT"

CASE_SPECS = [
    {
        "variant": "v2",
        "label": "Gap Mid Sell",
        "slug": "v2_mid_sell_gap",
        "log_path": Path("logs/round_2/theo/278804.json"),
        "focus_ts": 57000,
        "window_pre": 1200,
        "window_post": 1200,
        "expected": "SELL 13149x4 puis BUY 13064x4",
    },
    {
        "variant": "v4",
        "label": "Gap Early Sell",
        "slug": "v4_early_sell_gap",
        "log_path": Path("logs/round_2/theo/279664.json"),
        "focus_ts": 4400,
        "window_pre": 1200,
        "window_post": 1600,
        "expected": "SELL 13096x5 puis BUY 13002/13001",
    },
    {
        "variant": "v6",
        "label": "Gap Early Buy",
        "slug": "v6_early_buy_gap",
        "log_path": Path("logs/round_2/theo/281821.json"),
        "focus_ts": 5000,
        "window_pre": 1200,
        "window_post": 1600,
        "expected": "BUY 12913x5",
    },
    {
        "variant": "v7",
        "label": "Gap Late Sell",
        "slug": "v7_late_sell_gap",
        "log_path": Path("logs/round_2/theo/282144.json"),
        "focus_ts": 92500,
        "window_pre": 1200,
        "window_post": 1200,
        "expected": "SELL 13184x7 puis BUY 13100x7",
    },
]


def _submission_trades(log, symbol: str) -> pd.DataFrame:
    trades = log.trades.copy()
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "symbol",
                "side",
                "price",
                "quantity",
                "signed_quantity",
                "position_before",
                "position_after",
            ]
        )
    mask = (
        (trades["symbol"] == symbol)
        & ((trades["buyer"] == "SUBMISSION") | (trades["seller"] == "SUBMISSION"))
    )
    filtered = trades.loc[mask].copy().sort_values("timestamp")
    if filtered.empty:
        return filtered
    filtered["side"] = filtered["buyer"].eq("SUBMISSION").map({True: "BUY", False: "SELL"})
    filtered["signed_quantity"] = filtered["quantity"] * filtered["side"].map({"BUY": 1, "SELL": -1})
    filtered["position_after"] = filtered["signed_quantity"].cumsum()
    filtered["position_before"] = filtered["position_after"] - filtered["signed_quantity"]
    return filtered


def _prepare_activities(log, symbol: str) -> pd.DataFrame:
    act = log.activities.loc[log.activities["product"] == symbol].copy().sort_values("timestamp")
    if act.empty:
        return act
    top_total = (act["bid_volume_1"] + act["ask_volume_1"]).clip(lower=1)
    act["microprice"] = (
        act["bid_price_1"] * act["ask_volume_1"] + act["ask_price_1"] * act["bid_volume_1"]
    ) / top_total
    act["fair"] = act["microprice"].ewm(span=25, adjust=False).mean()
    act["bid_levels"] = act[["bid_price_1", "bid_price_2", "bid_price_3"]].notna().sum(axis=1)
    act["ask_levels"] = act[["ask_price_1", "ask_price_2", "ask_price_3"]].notna().sum(axis=1)
    act["bid_gap_12"] = act["bid_price_1"] - act["bid_price_2"]
    act["ask_gap_12"] = act["ask_price_2"] - act["ask_price_1"]
    act["one_sided_kind"] = "NONE"
    act.loc[(act["bid_levels"] == 0) & (act["ask_levels"] > 0), "one_sided_kind"] = "BID_EMPTY"
    act.loc[(act["ask_levels"] == 0) & (act["bid_levels"] > 0), "one_sided_kind"] = "ASK_EMPTY"
    act.loc[(act["ask_levels"] == 0) & (act["bid_levels"] == 0), "one_sided_kind"] = "BOTH_EMPTY"
    return act


def _position_plot(log, symbol: str, act: pd.DataFrame) -> pd.DataFrame:
    pos = official_position_path(log, symbol).sort_values("timestamp")
    if act.empty:
        return pd.DataFrame(columns=["timestamp", "position"])
    if pos.empty:
        return pd.DataFrame({"timestamp": act["timestamp"], "position": 0})
    merged = pd.merge_asof(
        act[["timestamp"]].sort_values("timestamp"),
        pos.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )
    merged["position"] = merged["position"].fillna(0).astype(int)
    return merged


def _event_trade_text(trades: pd.DataFrame, focus_ts: int) -> str:
    event_trades = trades.loc[(trades["timestamp"] >= focus_ts) & (trades["timestamp"] <= focus_ts + 100)]
    if event_trades.empty:
        return "-"
    parts = []
    for row in event_trades.itertuples(index=False):
        parts.append(f"{row.side} {int(row.price)}x{int(row.quantity)}")
    return " ; ".join(parts)


def _threshold_hit_summary(trades: pd.DataFrame) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for target in (20, 40, 60, 75, 80):
        hit = trades.loc[trades["position_after"] >= target]
        result[f"t{target}"] = int(hit.iloc[0]["timestamp"]) if not hit.empty else None
    return result


def _case_summary(spec: dict, log, act: pd.DataFrame, trades: pd.DataFrame) -> dict[str, object]:
    focus_ts = int(spec["focus_ts"])
    event_row = act.loc[act["timestamp"] == focus_ts].iloc[0]
    prev_rows = act.loc[act["timestamp"] < focus_ts].tail(3).reset_index(drop=True)
    event_trades = trades.loc[(trades["timestamp"] >= focus_ts) & (trades["timestamp"] <= focus_ts + 100)]
    trade_text = _event_trade_text(trades, focus_ts)
    summary: dict[str, object] = {
        "variant": spec["variant"],
        "label": spec["label"],
        "log_id": spec["log_path"].stem,
        "profit": log.profit,
        "focus_ts": focus_ts,
        "expected": spec["expected"],
        "event_kind": str(event_row["one_sided_kind"]),
        "bid_levels": int(event_row["bid_levels"]),
        "ask_levels": int(event_row["ask_levels"]),
        "bid1": None if pd.isna(event_row["bid_price_1"]) else int(event_row["bid_price_1"]),
        "ask1": None if pd.isna(event_row["ask_price_1"]) else int(event_row["ask_price_1"]),
        "trade_text": trade_text,
        "position_before": None,
        "position_after": None,
        "prev_kinds": " -> ".join(str(value) for value in prev_rows["one_sided_kind"].tolist()) if not prev_rows.empty else "",
        "prev_ask_levels": " / ".join(str(int(value)) for value in prev_rows["ask_levels"].tolist()) if not prev_rows.empty else "",
        "prev_bid_levels": " / ".join(str(int(value)) for value in prev_rows["bid_levels"].tolist()) if not prev_rows.empty else "",
    }
    if not event_trades.empty:
        summary["position_before"] = int(event_trades.iloc[0]["position_before"])
        summary["position_after"] = int(event_trades.iloc[-1]["position_after"])
    summary.update(_threshold_hit_summary(trades))
    return summary


def _windowed_frames(spec: dict, act: pd.DataFrame, trades: pd.DataFrame, pos_plot: pd.DataFrame):
    start_ts = int(spec["focus_ts"]) - int(spec["window_pre"])
    end_ts = int(spec["focus_ts"]) + int(spec["window_post"])
    act_win = act.loc[(act["timestamp"] >= start_ts) & (act["timestamp"] <= end_ts)].copy()
    trades_win = trades.loc[(trades["timestamp"] >= start_ts) & (trades["timestamp"] <= end_ts)].copy()
    pos_win = pos_plot.loc[(pos_plot["timestamp"] >= start_ts) & (pos_plot["timestamp"] <= end_ts)].copy()
    return act_win, trades_win, pos_win


def _build_case_figure(spec: dict, act: pd.DataFrame, trades: pd.DataFrame, pos_plot: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.56, 0.22, 0.22],
        specs=[[{}], [{"secondary_y": True}], [{"secondary_y": True}]],
    )

    fig.add_trace(
        go.Scatter(
            x=act["timestamp"],
            y=act["bid_price_1"],
            mode="lines",
            name="Best bid",
            line={"color": "#0b7285", "width": 2, "shape": "hv"},
            hovertemplate="t=%{x}<br>bid=%{y}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=act["timestamp"],
            y=act["ask_price_1"],
            mode="lines",
            name="Best ask",
            line={"color": "#c92a2a", "width": 2, "shape": "hv"},
            hovertemplate="t=%{x}<br>ask=%{y}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=act["timestamp"],
            y=act["fair"],
            mode="lines",
            name="Fair value",
            line={"color": "#2b8a3e", "width": 2, "shape": "hv"},
            hovertemplate="t=%{x}<br>fair=%{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    one_sided = act.loc[act["one_sided_kind"] != "NONE"]
    if not one_sided.empty:
        fig.add_trace(
            go.Scatter(
                x=one_sided["timestamp"],
                y=one_sided["mid_price"],
                mode="markers",
                name="One-sided ticks",
                marker={"size": 8, "color": "#f59f00", "symbol": "x"},
                customdata=one_sided[["one_sided_kind", "bid_levels", "ask_levels"]],
                hovertemplate="t=%{x}<br>%{customdata[0]}<br>bid levels=%{customdata[1]}<br>ask levels=%{customdata[2]}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    buy_trades = trades.loc[trades["side"] == "BUY"]
    sell_trades = trades.loc[trades["side"] == "SELL"]
    if not buy_trades.empty:
        fig.add_trace(
            go.Scatter(
                x=buy_trades["timestamp"],
                y=buy_trades["price"],
                mode="markers+text",
                name="Submission buys",
                marker={"symbol": "triangle-up", "size": buy_trades["quantity"] * 1.8 + 8, "color": "#2f9e44"},
                text=buy_trades["quantity"].astype(int).astype(str),
                textposition="top center",
                customdata=buy_trades[["position_before", "position_after"]],
                hovertemplate="t=%{x}<br>buy=%{y}<br>qty=%{text}<br>pos before=%{customdata[0]}<br>pos after=%{customdata[1]}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if not sell_trades.empty:
        fig.add_trace(
            go.Scatter(
                x=sell_trades["timestamp"],
                y=sell_trades["price"],
                mode="markers+text",
                name="Submission sells",
                marker={"symbol": "triangle-down", "size": sell_trades["quantity"] * 1.8 + 8, "color": "#f03e3e"},
                text=sell_trades["quantity"].astype(int).astype(str),
                textposition="bottom center",
                customdata=sell_trades[["position_before", "position_after"]],
                hovertemplate="t=%{x}<br>sell=%{y}<br>qty=%{text}<br>pos before=%{customdata[0]}<br>pos after=%{customdata[1]}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    if not trades.empty:
        fig.add_trace(
            go.Bar(
                x=trades["timestamp"],
                y=trades["signed_quantity"],
                name="Signed exec qty",
                marker_color=trades["side"].map({"BUY": "#2f9e44", "SELL": "#f03e3e"}),
                opacity=0.75,
                hovertemplate="t=%{x}<br>signed qty=%{y}<extra></extra>",
            ),
            row=2,
            col=1,
            secondary_y=False,
        )

    fig.add_trace(
        go.Scatter(
            x=pos_plot["timestamp"],
            y=pos_plot["position"],
            mode="lines",
            name="Position",
            line={"color": "#6741d9", "width": 2, "shape": "hv"},
            hovertemplate="t=%{x}<br>pos=%{y}<extra></extra>",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    fig.add_trace(
        go.Scatter(
            x=act["timestamp"],
            y=act["bid_levels"],
            mode="lines",
            name="Bid levels visible",
            line={"color": "#1864ab", "width": 2, "shape": "hv"},
            hovertemplate="t=%{x}<br>bid levels=%{y}<extra></extra>",
        ),
        row=3,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=act["timestamp"],
            y=act["ask_levels"],
            mode="lines",
            name="Ask levels visible",
            line={"color": "#e03131", "width": 2, "shape": "hv"},
            hovertemplate="t=%{x}<br>ask levels=%{y}<extra></extra>",
        ),
        row=3,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=act["timestamp"],
            y=act["bid_gap_12"],
            mode="lines",
            name="Bid gap 1-2",
            line={"color": "#4dabf7", "width": 1.5, "dash": "dot", "shape": "hv"},
            hovertemplate="t=%{x}<br>bid gap 1-2=%{y}<extra></extra>",
        ),
        row=3,
        col=1,
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=act["timestamp"],
            y=act["ask_gap_12"],
            mode="lines",
            name="Ask gap 1-2",
            line={"color": "#ff8787", "width": 1.5, "dash": "dot", "shape": "hv"},
            hovertemplate="t=%{x}<br>ask gap 1-2=%{y}<extra></extra>",
        ),
        row=3,
        col=1,
        secondary_y=True,
    )

    focus_ts = int(spec["focus_ts"])
    for row in (1, 2, 3):
        fig.add_vline(x=focus_ts, line_width=1.5, line_dash="dash", line_color="#f59f00", row=row, col=1)

    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Signed qty", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Position", row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Visible levels", row=3, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Gap 1-2", row=3, col=1, secondary_y=True)
    fig.update_xaxes(title_text="Timestamp", row=3, col=1)

    fig.update_layout(
        title={
            "text": f"{spec['variant']} - {spec['label']} - t={focus_ts}",
            "x": 0.01,
            "xanchor": "left",
        },
        template="plotly_dark",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        height=980,
        margin={"l": 60, "r": 60, "t": 60, "b": 60},
    )
    return fig


def _one_sided_capture_matrix(base_act: pd.DataFrame, case_data: list[dict]) -> pd.DataFrame:
    one_sided = base_act.loc[base_act["one_sided_kind"] != "NONE", ["timestamp", "one_sided_kind", "bid_levels", "ask_levels"]].copy()
    for data in case_data:
        trades = data["trades"]
        actions = []
        for row in one_sided.itertuples(index=False):
            event_trades = trades.loc[(trades["timestamp"] >= row.timestamp) & (trades["timestamp"] <= row.timestamp + 100)]
            if event_trades.empty:
                actions.append("-")
            else:
                parts = [f"{trade.side}@{int(trade.price)}x{int(trade.quantity)}" for trade in event_trades.itertuples(index=False)]
                actions.append(" ; ".join(parts))
        one_sided[data["variant"]] = actions
    return one_sided


def _variant_summary_table(case_data: list[dict]) -> pd.DataFrame:
    rows = []
    for data in case_data:
        summary = data["summary"]
        rows.append(
            {
                "variant": summary["variant"],
                "log_id": summary["log_id"],
                "profit": summary["profit"],
                "event": summary["label"],
                "focus_ts": summary["focus_ts"],
                "event_kind": summary["event_kind"],
                "trade_text": summary["trade_text"],
                "position_before": summary["position_before"],
                "position_after": summary["position_after"],
                "t20": summary["t20"],
                "t40": summary["t40"],
                "t60": summary["t60"],
                "t75": summary["t75"],
                "t80": summary["t80"],
            }
        )
    return pd.DataFrame(rows)


def _event_summary_table(case_data: list[dict]) -> pd.DataFrame:
    rows = []
    for data in case_data:
        summary = data["summary"]
        rows.append(
            {
                "variant": summary["variant"],
                "event": summary["label"],
                "expected": summary["expected"],
                "focus_ts": summary["focus_ts"],
                "one_sided_kind": summary["event_kind"],
                "trade_text": summary["trade_text"],
                "position_before": summary["position_before"],
                "position_after": summary["position_after"],
                "bid1": summary["bid1"],
                "ask1": summary["ask1"],
                "prev_kinds": summary["prev_kinds"],
                "prev_bid_levels": summary["prev_bid_levels"],
                "prev_ask_levels": summary["prev_ask_levels"],
            }
        )
    return pd.DataFrame(rows)


def _report_html(
    outdir: Path,
    case_data: list[dict],
    variant_df: pd.DataFrame,
    event_df: pd.DataFrame,
    matrix_df: pd.DataFrame,
    one_sided_counts: dict[str, int],
) -> str:
    insight_items = [
        f"La journee contient {one_sided_counts['total']} ticks one-sided sur {SYMBOL}: {one_sided_counts['ask_empty']} `ASK_EMPTY`, {one_sided_counts['bid_empty']} `BID_EMPTY`, {one_sided_counts['both_empty']} `BOTH_EMPTY`.",
        "Les trois sells gap reussis (`v4`, `v2`, `v7`) arrivent avec une position deja tres longue, entre 75 et 80, et un trou cote ask.",
        "Le low buy gap `v6` n'existe que parce que la strategie est encore a 41 au timestamp 5000: si on remplit trop vite a 80, on tue ce coup-la.",
        "Les versions qui captent les sells gap chargent tres vite l'inventaire; la version qui capte le buy gap garde de la capacite plus longtemps. C'est la contradiction centrale a resoudre.",
        "Les trous de carnet sont nombreux, mais une strategie n'en capture qu'une petite fraction: le bon etat d'inventaire compte autant que le signal de carnet.",
    ]

    case_links = []
    for data in case_data:
        case_rel = data["case_plot"].relative_to(outdir)
        full_rel = data["full_review"].relative_to(outdir)
        case_links.append(
            f"<tr><td>{escape(data['variant'])}</td><td>{escape(data['summary']['label'])}</td>"
            f"<td><a href=\"{escape(case_rel.as_posix())}\">zoom event</a></td>"
            f"<td><a href=\"{escape(full_rel.as_posix())}\">full review</a></td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Round 2 Gap Study</title>
  <style>
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f172a;
      color: #e2e8f0;
    }}
    .page {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1, h2 {{
      margin: 0 0 12px;
    }}
    p {{
      color: #cbd5e1;
      line-height: 1.5;
    }}
    .card {{
      background: #111827;
      border: 1px solid #334155;
      border-radius: 18px;
      padding: 18px 20px;
      margin-bottom: 18px;
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.25);
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
    }}
    li {{
      margin-bottom: 8px;
      color: #dbe4f0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid #334155;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: #f8fafc;
      background: #0b1220;
      position: sticky;
      top: 0;
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 520px;
    }}
    a {{
      color: #7dd3fc;
    }}
    code {{
      background: #0b1220;
      border: 1px solid #334155;
      padding: 1px 5px;
      border-radius: 6px;
      color: #bfdbfe;
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="card">
      <h1>Round 2 Gap Study</h1>
      <p>Etude officielle comparee sur <code>{escape(SYMBOL)}</code> a partir des logs <code>v2</code>, <code>v4</code>, <code>v6</code> et <code>v7</code>.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Variant</th><th>Event</th><th>Zoom</th><th>Full review</th></tr>
          </thead>
          <tbody>
            {''.join(case_links)}
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h2>Key Insights</h2>
      <ul>
        {''.join(f"<li>{escape(item)}</li>" for item in insight_items)}
      </ul>
    </div>

    <div class="card">
      <h2>Variant Summary</h2>
      <div class="table-wrap">
        {variant_df.to_html(index=False, border=0, classes='summary-table')}
      </div>
    </div>

    <div class="card">
      <h2>Event Summary</h2>
      <div class="table-wrap">
        {event_df.to_html(index=False, border=0, classes='event-table')}
      </div>
    </div>

    <div class="card">
      <h2>One-sided Capture Matrix</h2>
      <p>Chaque ligne est un timestamp one-sided sur la journee. Les colonnes <code>v2/v4/v6/v7</code> disent s'il y a eu une execution submission au tick ou au tick suivant.</p>
      <div class="table-wrap">
        {matrix_df.to_html(index=False, border=0, classes='matrix-table')}
      </div>
    </div>
  </div>
</body>
</html>
"""


def _write_case_plot(path: Path, fig: go.Figure) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(path, include_plotlyjs=True, full_html=True)


def generate_study(outdir: Path) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    case_dir = outdir / "cases"
    full_dir = outdir / "full_reviews"
    table_dir = outdir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)

    case_data: list[dict] = []
    for spec in CASE_SPECS:
        log = load_official_log(spec["log_path"])
        act = _prepare_activities(log, SYMBOL)
        trades = _submission_trades(log, SYMBOL)
        pos_plot = _position_plot(log, SYMBOL, act)
        act_win, trades_win, pos_win = _windowed_frames(spec, act, trades, pos_plot)

        full_review = plot_symbol_review_plotly(log, SYMBOL, full_dir, edge=1.0, group=spec["variant"])
        case_plot = case_dir / f"{spec['slug']}.html"
        fig = _build_case_figure(spec, act_win, trades_win, pos_win)
        _write_case_plot(case_plot, fig)

        case_data.append(
            {
                "variant": spec["variant"],
                "log": log,
                "activities": act,
                "trades": trades,
                "summary": _case_summary(spec, log, act, trades),
                "case_plot": case_plot,
                "full_review": full_review,
            }
        )

    variant_df = _variant_summary_table(case_data)
    event_df = _event_summary_table(case_data)
    base_act = case_data[1]["activities"]
    matrix_df = _one_sided_capture_matrix(base_act, case_data)

    variant_csv = table_dir / "variant_summary.csv"
    event_csv = table_dir / "event_summary.csv"
    matrix_csv = table_dir / "one_sided_capture_matrix.csv"
    variant_df.to_csv(variant_csv, index=False)
    event_df.to_csv(event_csv, index=False)
    matrix_df.to_csv(matrix_csv, index=False)

    one_sided_counts = {
        "total": int(len(matrix_df)),
        "ask_empty": int((matrix_df["one_sided_kind"] == "ASK_EMPTY").sum()),
        "bid_empty": int((matrix_df["one_sided_kind"] == "BID_EMPTY").sum()),
        "both_empty": int((matrix_df["one_sided_kind"] == "BOTH_EMPTY").sum()),
    }
    report_path = outdir / "index.html"
    report_path.write_text(
        _report_html(outdir, case_data, variant_df, event_df, matrix_df, one_sided_counts),
        encoding="utf-8",
    )

    manifest = {
        "report": report_path,
        "variant_csv": variant_csv,
        "event_csv": event_csv,
        "matrix_csv": matrix_csv,
    }
    manifest_path = outdir / "manifest.json"
    manifest_path.write_text(
        json.dumps({key: str(value) for key, value in manifest.items()}, indent=2),
        encoding="utf-8",
    )
    manifest["manifest"] = manifest_path
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an official-log gap study for Theo round 2")
    parser.add_argument(
        "--outdir",
        default="artifacts/analysis/round_2/theo/gap_study_official",
        help="Directory that will receive the report, plots, and CSV tables",
    )
    args = parser.parse_args()

    manifest = generate_study(Path(args.outdir))
    print(json.dumps({key: str(value) for key, value in manifest.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
