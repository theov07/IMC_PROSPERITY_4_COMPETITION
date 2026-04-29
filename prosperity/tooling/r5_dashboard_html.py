"""R5 backtest HTML dashboard — per-group + per-asset views.

Usage:
    python -m prosperity.tooling.r5_dashboard_html \
        --json artifacts/r5_compare/best_v1610.json \
        --prices-dir data/round_5 \
        --out artifacts/analysis/round_5/v1610_dashboard.html

Provides:
  - Equity curve (full + per-day)
  - Per-group aggregated PnL + position chart
  - Per-asset detail (price + position + PnL)
  - Strategy mix table
  - Drawdown analysis
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[2]

GROUPS = {
    "GALAXY_SOUNDS": ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                      "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                      "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "SLEEP_POD": ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                  "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "MICROCHIP": ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                  "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "PEBBLES": ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "ROBOT": ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES", "ROBOT_LAUNDRY",
              "ROBOT_IRONING"],
    "UV_VISOR": ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                 "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "TRANSLATOR": ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                   "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                   "TRANSLATOR_VOID_BLUE"],
    "PANEL": ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "OXYGEN_SHAKE": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                     "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE",
                     "OXYGEN_SHAKE_GARLIC"],
    "SNACKPACK": ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                  "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
}
PRODUCT_GROUP = {p: g for g, ms in GROUPS.items() for p in ms}

GROUP_COLORS = {
    "GALAXY_SOUNDS": "#9b59b6", "SLEEP_POD": "#3498db", "MICROCHIP": "#e74c3c",
    "PEBBLES": "#f39c12", "ROBOT": "#2ecc71", "UV_VISOR": "#f1c40f",
    "TRANSLATOR": "#1abc9c", "PANEL": "#95a5a6", "OXYGEN_SHAKE": "#e67e22",
    "SNACKPACK": "#34495e",
}


def load_backtest_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_per_product_pnl(data: dict) -> dict:
    """Extract per-product per-day PnL.

    JSON structure: data['days'] = [{day, product_summaries: {prod: {pnl, ...}}}, ...]
    """
    out = defaultdict(dict)  # product -> {day: pnl}
    days = data.get("days", [])
    for day_data in days:
        day = day_data.get("day")
        ps = day_data.get("product_summaries", {})
        for prod, pdata in ps.items():
            pnl = pdata.get("pnl", 0)
            out[prod][day] = pnl
    return dict(out)


def extract_equity_per_day(data: dict) -> dict:
    """Returns {day: list of (timestamp, cumulative_pnl)}"""
    out = {}
    days = data.get("days", [])
    for day_data in days:
        day = day_data.get("day")
        eq = day_data.get("equity_curve", [])
        out[day] = eq
    return out


def extract_per_product_summary(data: dict) -> dict:
    """Returns {product: aggregate stats across days}"""
    agg = defaultdict(lambda: {"pnl": 0, "trades": 0, "traded_volume": 0,
                               "ending_position": 0, "max_abs_position": 0,
                               "passive_adverse_rate": 0, "fill_efficiency": 0,
                               "n_days": 0})
    days = data.get("days", [])
    for day_data in days:
        ps = day_data.get("product_summaries", {})
        for prod, pdata in ps.items():
            agg[prod]["pnl"] += pdata.get("pnl", 0)
            agg[prod]["trades"] += pdata.get("trades", 0)
            agg[prod]["traded_volume"] += pdata.get("traded_volume", 0)
            agg[prod]["ending_position"] = pdata.get("ending_position", 0)
            agg[prod]["max_abs_position"] = max(
                agg[prod]["max_abs_position"], pdata.get("max_abs_position", 0))
            agg[prod]["passive_adverse_rate"] += pdata.get("robustness", {}).get("passive_adverse_rate", 0) or 0
            agg[prod]["fill_efficiency"] += pdata.get("robustness", {}).get("fill_efficiency", 0) or 0
            agg[prod]["n_days"] += 1
    for prod in agg:
        if agg[prod]["n_days"]:
            agg[prod]["passive_adverse_rate"] /= agg[prod]["n_days"]
            agg[prod]["fill_efficiency"] /= agg[prod]["n_days"]
    return dict(agg)


def extract_position_traces(data: dict, products: list[str] | None = None):
    """Compute position over time per product per day from fills.

    Returns dict {product: {day: [(timestamp, position), ...]}}.
    Position is built up by accumulating fill quantities (BUY=+, SELL=-).
    """
    days = data.get("days", [])
    pos_trace: dict[str, dict[int, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))

    for day_data in days:
        day = day_data.get("day")
        fills = day_data.get("fills", [])
        # Sort by timestamp to ensure chronological order
        fills_sorted = sorted(fills, key=lambda f: f.get("timestamp", 0))

        # Per-product running position
        running = defaultdict(int)
        # Sample every N fills to avoid huge arrays
        for f in fills_sorted:
            sym = f.get("symbol")
            ts = f.get("timestamp", 0)
            qty = f.get("quantity", 0)
            side = f.get("side", "BUY")
            if products and sym not in products:
                continue
            delta = qty if side == "BUY" else -qty
            running[sym] += delta
            pos_trace[sym][day].append((ts, running[sym]))
    return dict(pos_trace)


def extract_equity_curve(data: dict, product: str | None = None):
    """Extract per-tick equity (PnL) over time per product or aggregate."""
    summaries = data.get("summaries", [])
    if product:
        # Per-product equity from per_tick_pnl
        tick_pnl = []
        for s in summaries:
            if s.get("product") == product:
                day = s.get("day")
                ticks = s.get("ticks", [])
                pnls = s.get("per_tick_pnl", [])
                for i, p in enumerate(pnls):
                    ts = ticks[i] if i < len(ticks) else i * 100
                    tick_pnl.append((day, ts, p))
        return pd.DataFrame(tick_pnl, columns=["day", "timestamp", "pnl"])
    else:
        # Aggregate equity
        all_pnl = defaultdict(list)
        for s in summaries:
            day = s.get("day")
            ticks = s.get("ticks", [])
            pnls = s.get("per_tick_pnl", [])
            for i, p in enumerate(pnls):
                ts = ticks[i] if i < len(ticks) else i * 100
                all_pnl[(day, ts)].append(p)
        rows = [(d, t, sum(ps)) for (d, t), ps in sorted(all_pnl.items())]
        return pd.DataFrame(rows, columns=["day", "timestamp", "pnl"])


def build_html(data: dict, title: str = "R5 Backtest Dashboard") -> str:
    """Build a self-contained HTML dashboard."""
    summary = data.get("summary", {})

    # Per-product PnL
    pp_pnl = extract_per_product_pnl(data)

    # Total PnL
    total_pnl = summary.get("total_pnl", sum(sum(d.values()) for d in pp_pnl.values()))

    # Per-group aggregated PnL
    group_pnl = defaultdict(lambda: defaultdict(float))  # group -> day -> pnl
    for prod, days in pp_pnl.items():
        g = PRODUCT_GROUP.get(prod, "OTHER")
        for d, p in days.items():
            group_pnl[g][d] += p

    # Build figure 1: Group breakdown bar chart
    groups_sorted = sorted(group_pnl.keys(), key=lambda g: -sum(group_pnl[g].values()))
    days_all = sorted({d for prods in group_pnl.values() for d in prods.keys()})
    fig_groups = go.Figure()
    for d in days_all:
        fig_groups.add_trace(go.Bar(
            name=f"Day {d}",
            x=groups_sorted,
            y=[group_pnl[g].get(d, 0) for g in groups_sorted],
            text=[f"{group_pnl[g].get(d, 0):,.0f}" for g in groups_sorted],
            textposition="auto",
        ))
    fig_groups.update_layout(
        title=f"PnL per group per day (Total: {total_pnl:,.0f})",
        barmode="group", height=500,
        xaxis_tickangle=-30,
    )

    # Figure 2: Per-product treemap (sized by |pnl|, colored by sign)
    products = sorted(pp_pnl.keys())
    pp_total = {p: sum(pp_pnl[p].values()) for p in products}
    treemap_labels = []
    treemap_parents = []
    treemap_values = []
    treemap_colors = []
    for g, ms in GROUPS.items():
        ms_active = [m for m in ms if pp_total.get(m, 0) != 0]
        if not ms_active:
            continue
        treemap_labels.append(g)
        treemap_parents.append("")
        treemap_values.append(sum(abs(pp_total.get(m, 0)) for m in ms_active))
        treemap_colors.append(0)
        for m in ms_active:
            v = pp_total.get(m, 0)
            treemap_labels.append(m)
            treemap_parents.append(g)
            treemap_values.append(abs(v))
            treemap_colors.append(v)
    fig_treemap = go.Figure(go.Treemap(
        labels=treemap_labels, parents=treemap_parents, values=treemap_values,
        marker=dict(colors=treemap_colors, colorscale="RdYlGn", cmid=0,
                    line=dict(width=1)),
        text=[f"{v:+,.0f}" if i > 0 and treemap_parents[i] else "" for i, v in enumerate(treemap_colors)],
        textinfo="label+value+text",
    ))
    fig_treemap.update_layout(
        title="Per-product PnL treemap (size=|PnL|, color=sign)",
        height=600,
    )

    # Figure 3: Top contributors / detractors bar
    sorted_products = sorted(pp_total.items(), key=lambda x: x[1], reverse=True)
    top10 = sorted_products[:10]
    bot10 = sorted_products[-10:]
    fig_topbot = make_subplots(rows=1, cols=2, subplot_titles=("Top 10 Contributors", "Worst 10"))
    fig_topbot.add_trace(go.Bar(
        x=[p for p, _ in top10], y=[v for _, v in top10],
        marker_color="#2ecc71",
        text=[f"{v:,.0f}" for _, v in top10], textposition="outside",
    ), row=1, col=1)
    fig_topbot.add_trace(go.Bar(
        x=[p for p, _ in bot10], y=[v for _, v in bot10],
        marker_color="#e74c3c",
        text=[f"{v:,.0f}" for _, v in bot10], textposition="outside",
    ), row=1, col=2)
    fig_topbot.update_layout(height=500, showlegend=False, xaxis_tickangle=-45, xaxis2_tickangle=-45)

    # Figure 4: Per-product table heatmap
    days_set = sorted({d for prods in pp_pnl.values() for d in prods.keys()})
    z_data = []
    y_labels = []
    for g in GROUPS:
        members = [m for m in GROUPS[g] if m in pp_pnl]
        for m in members:
            row = [pp_pnl[m].get(d, 0) for d in days_set]
            z_data.append(row)
            y_labels.append(f"[{g}] {m}")
    fig_heatmap = go.Figure(go.Heatmap(
        z=z_data,
        x=[f"Day {d}" for d in days_set],
        y=y_labels,
        colorscale="RdYlGn", zmid=0,
        text=[[f"{v:,.0f}" for v in r] for r in z_data],
        texttemplate="%{text}",
    ))
    fig_heatmap.update_layout(
        title="Per-product per-day PnL heatmap",
        height=max(800, len(y_labels) * 18),
    )

    # Figure 5: Strategy mix
    from prosperity.config import get_round_config
    try:
        cfg = get_round_config(5, data.get("strategy", "best_v1610_v1600_drop_magenta"))
    except Exception:
        cfg = {}
    strat_count = defaultdict(list)
    for p, c in cfg.items():
        strat_count[c.strategy].append(p)
    strat_pnl = {}
    for s, prods in strat_count.items():
        strat_pnl[s] = sum(pp_total.get(p, 0) for p in prods)
    fig_strat = go.Figure(go.Bar(
        x=list(strat_pnl.keys()),
        y=list(strat_pnl.values()),
        text=[f"{v:,.0f} ({len(strat_count[s])})" for s, v in strat_pnl.items()],
        textposition="outside",
        marker_color="#3498db",
    ))
    fig_strat.update_layout(
        title="PnL by strategy class (with product count)",
        height=400, xaxis_tickangle=-20,
    )

    # Figure 6: Equity curve per day (chained)
    eq_per_day = extract_equity_per_day(data)
    fig_eq = go.Figure()
    cum = 0
    sorted_days = sorted(eq_per_day.keys(), key=lambda d: int(d) if isinstance(d, str) and d.isdigit() else d)
    for di, d in enumerate(sorted_days):
        eq = eq_per_day[d]
        if not eq:
            continue
        ts = []
        pnl = []
        for e in eq:
            if isinstance(e, list):
                t, v = e[0], e[1]
            else:
                t, v = e["timestamp"], e["equity"]
            ts.append(int(t) + di * 100_000)
            pnl.append(cum + float(v))
        fig_eq.add_trace(go.Scatter(
            x=ts, y=pnl, mode='lines', name=f'Day {d}',
            line=dict(width=1.5),
        ))
        if pnl:
            cum = pnl[-1]
    fig_eq.update_layout(
        title=f"Chained equity curve (3-day, total={total_pnl:,.0f})",
        xaxis_title="Timestamp", yaxis_title="Cumulative PnL",
        height=400,
    )

    # Figure 7: Per-product detail table with key metrics
    pp_summary = extract_per_product_summary(data)
    rows = []
    for prod in sorted(pp_summary.keys()):
        s = pp_summary[prod]
        if s["pnl"] == 0 and s["trades"] == 0:
            continue
        g = PRODUCT_GROUP.get(prod, "OTHER")
        rows.append([g, prod, s["pnl"], s["trades"], s["traded_volume"],
                     s["ending_position"], s["max_abs_position"],
                     f"{s['passive_adverse_rate']*100:.1f}%",
                     f"{s['fill_efficiency']*100:.2f}%"])
    rows.sort(key=lambda r: -r[2])
    fig_table = go.Figure(data=[go.Table(
        header=dict(values=['Group', 'Product', 'PnL', 'Trades', 'Volume',
                            'EndPos', 'MaxPos', 'AdvRate', 'FillEff'],
                    fill_color='#3b3a52', font=dict(color='white')),
        cells=dict(
            values=list(zip(*rows)),
            fill_color=[['#1e1e2e' if i % 2 == 0 else '#2a2a3a' for i in range(len(rows))]],
            font=dict(color='white'),
            format=[None, None, ',d', ',d', ',d', ',d', ',d', None, None],
        ),
    )])
    fig_table.update_layout(
        title="Per-product detail table (sorted by PnL)",
        height=max(500, len(rows) * 22),
    )

    # Figure 8: Inventory over time per product (top contributors only)
    top_products = sorted(pp_total.items(), key=lambda x: -abs(x[1]))[:20]
    top_product_names = [p for p, _ in top_products]
    pos_traces = extract_position_traces(data, products=top_product_names)
    fig_pos = make_subplots(
        rows=4, cols=5,
        subplot_titles=top_product_names,
        shared_xaxes=False, vertical_spacing=0.10, horizontal_spacing=0.04,
    )
    for idx, prod in enumerate(top_product_names):
        row = idx // 5 + 1
        col = idx % 5 + 1
        if prod not in pos_traces:
            continue
        for day, points in sorted(pos_traces[prod].items()):
            if not points:
                continue
            ts, positions = zip(*points)
            fig_pos.add_trace(
                go.Scatter(
                    x=list(ts), y=list(positions), mode='lines',
                    name=f"d{day}", line=dict(width=1),
                    showlegend=(idx == 0),
                ),
                row=row, col=col,
            )
        # Position limit lines (±10)
        fig_pos.add_hline(y=10, line=dict(color="#f38ba8", dash="dot", width=0.5),
                          row=row, col=col)
        fig_pos.add_hline(y=-10, line=dict(color="#f38ba8", dash="dot", width=0.5),
                          row=row, col=col)
        fig_pos.add_hline(y=0, line=dict(color="#bac2de", dash="dash", width=0.5),
                          row=row, col=col)
    fig_pos.update_layout(
        title="Inventory (position) over time — top 20 products by |PnL|",
        height=900, showlegend=True,
    )
    fig_pos.update_yaxes(range=[-12, 12])

    # Figure 9: Aggregate inventory stats per product (max abs, time at limit)
    inv_stats_rows = []
    pos_traces_all = extract_position_traces(data)
    for prod in sorted(pp_total.keys()):
        if pp_total.get(prod, 0) == 0:
            continue
        all_points = []
        for day_pts in pos_traces_all.get(prod, {}).values():
            all_points.extend(day_pts)
        if not all_points:
            continue
        positions = [p for _, p in all_points]
        max_abs = max(abs(p) for p in positions)
        time_at_max = sum(1 for p in positions if abs(p) >= 10) / max(len(positions), 1) * 100
        time_long = sum(1 for p in positions if p > 0) / max(len(positions), 1) * 100
        time_short = sum(1 for p in positions if p < 0) / max(len(positions), 1) * 100
        avg_abs = sum(abs(p) for p in positions) / max(len(positions), 1)
        g = PRODUCT_GROUP.get(prod, "OTHER")
        inv_stats_rows.append([g, prod, max_abs, f"{avg_abs:.1f}",
                               f"{time_at_max:.0f}%", f"{time_long:.0f}%",
                               f"{time_short:.0f}%"])
    inv_stats_rows.sort(key=lambda r: -float(r[3]))
    fig_inv_table = go.Figure(data=[go.Table(
        header=dict(values=['Group', 'Product', 'MaxAbs', 'AvgAbs',
                            '% at limit', '% long', '% short'],
                    fill_color='#3b3a52', font=dict(color='white')),
        cells=dict(
            values=list(zip(*inv_stats_rows)) if inv_stats_rows else [[]] * 7,
            fill_color=[['#1e1e2e' if i % 2 == 0 else '#2a2a3a'
                         for i in range(len(inv_stats_rows))]],
            font=dict(color='white'),
        ),
    )])
    fig_inv_table.update_layout(
        title="Inventory utilization per product",
        height=max(500, len(inv_stats_rows) * 22),
    )

    # Aggregate stats
    n_active = sum(1 for v in pp_total.values() if v != 0)
    n_positive = sum(1 for v in pp_total.values() if v > 0)
    n_negative = sum(1 for v in pp_total.values() if v < 0)
    n_zero = sum(1 for v in pp_total.values() if v == 0)

    # Compose HTML
    html_parts = [
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{title}</title>",
        f"<style>body{{font-family:Arial,sans-serif;background:#1e1e2e;color:#cdd6f4;padding:20px}}",
        f"h1,h2{{color:#89b4fa}}.summary{{background:#313244;padding:15px;border-radius:8px;margin:15px 0}}",
        f".kpi{{display:inline-block;margin:10px 20px;text-align:center}}.kpi .v{{font-size:1.6em;font-weight:bold;color:#a6e3a1}}",
        f".kpi .l{{font-size:0.85em;color:#bac2de}}</style></head><body>",
        f"<h1>{title}</h1>",
        f"<div class='summary'>",
        f"<div class='kpi'><div class='v'>{total_pnl:,.0f}</div><div class='l'>Total PnL</div></div>",
        f"<div class='kpi'><div class='v'>{n_active}</div><div class='l'>Active products</div></div>",
        f"<div class='kpi'><div class='v'>{n_positive}</div><div class='l'>Positive</div></div>",
        f"<div class='kpi'><div class='v' style='color:#f38ba8'>{n_negative}</div><div class='l'>Negative</div></div>",
        f"<div class='kpi'><div class='v' style='color:#bac2de'>{n_zero}</div><div class='l'>Zero</div></div>",
        f"</div>",
        f"<h2>1. Per-group PnL breakdown</h2>",
        fig_groups.to_html(include_plotlyjs="cdn", full_html=False),
        f"<h2>2. Strategy mix breakdown</h2>",
        fig_strat.to_html(include_plotlyjs=False, full_html=False),
        f"<h2>3. Top contributors / Worst</h2>",
        fig_topbot.to_html(include_plotlyjs=False, full_html=False),
        f"<h2>4. Per-product treemap</h2>",
        fig_treemap.to_html(include_plotlyjs=False, full_html=False),
        f"<h2>5. Per-product per-day heatmap</h2>",
        fig_heatmap.to_html(include_plotlyjs=False, full_html=False),
        f"<h2>6. Chained equity curve (3-day)</h2>",
        fig_eq.to_html(include_plotlyjs=False, full_html=False),
        f"<h2>7. Per-product detail table</h2>",
        fig_table.to_html(include_plotlyjs=False, full_html=False),
        f"<h2>8. Inventory (position) evolution — top 20 products</h2>",
        fig_pos.to_html(include_plotlyjs=False, full_html=False),
        f"<h2>9. Inventory utilization per product</h2>",
        fig_inv_table.to_html(include_plotlyjs=False, full_html=False),
        f"</body></html>",
    ]
    return "".join(html_parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True, help="Backtest JSON output")
    parser.add_argument("--out", required=True, help="Output HTML file")
    parser.add_argument("--title", default="R5 Backtest Dashboard")
    args = parser.parse_args()

    data = load_backtest_json(Path(args.json))
    html = build_html(data, title=args.title)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote {args.out} ({len(html):,} chars)")


if __name__ == "__main__":
    main()
