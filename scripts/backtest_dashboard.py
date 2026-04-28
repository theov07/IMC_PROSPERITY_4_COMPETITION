"""Generic HTML dashboard for any backtest JSON.

Usage:
  python scripts/backtest_dashboard.py \\
      --json artifacts/backtest_cache/round_4/v9_M22cond_z15_w04_3d.json \\
      --out  artifacts/analysis/round_4/v9_dashboard.html \\
      --title "v9 M22cond_z15_w04"

Generic version of v5_backtest_dashboard.py — title and source/output are CLI args.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="Backtest JSON path")
    ap.add_argument("--out", required=True, help="HTML output path")
    ap.add_argument("--title", default="Backtest Dashboard", help="Dashboard title")
    args = ap.parse_args()

    json_path = Path(args.json)
    out_html = Path(args.out)
    title = args.title

    print(f"Loading {json_path.stat().st_size/1e6:.1f} MB JSON...")
    with open(json_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    print(f"  Total PnL: {d['summary']['total_pnl']:.0f}")
    print(f"  DD: {d['summary']['robustness']['max_drawdown']:.0f}")

    days = d["days"]
    products = sorted(d["summary"]["per_product_pnl"].keys())
    relevant = [p for p in products if d["summary"]["per_product_pnl"].get(p, 0) != 0]

    # Equity curve concatenated across days
    equity_concat = []
    cumul_pnl = 0
    for di, day in enumerate(days):
        ec = day.get("equity_curve", [])
        for ts, pnl in ec:
            global_ts = di * 1_000_000 + ts
            equity_concat.append((global_ts, cumul_pnl + pnl))
        if ec:
            cumul_pnl += ec[-1][1]
    print(f"  Equity points: {len(equity_concat)}")

    # Per-product per-tick data
    pp_data, pp_pos, pp_marks = {}, {}, {}
    for prod in relevant:
        all_features, all_pos, all_buy, all_sell = [], [], [], []
        for di, day in enumerate(days):
            offset = di * 1_000_000
            features = day.get("feature_ticks", [])
            day_features = [f for f in features if f.get("symbol") == prod]
            for f in day_features:
                ts_g = offset + f.get("timestamp", 0)
                mid = f.get("MidSmooth")
                all_features.append((ts_g, mid))
            day_fills = [fl for fl in day.get("fills", []) if fl.get("symbol") == prod]
            cumul = 0
            for fl in sorted(day_fills, key=lambda x: x.get("timestamp", 0)):
                ts_g = offset + fl.get("timestamp", 0)
                qty = fl.get("quantity", 0)
                side = fl.get("side", "BUY")
                if side == "BUY":
                    cumul += qty
                    all_buy.append((ts_g, fl.get("price", 0)))
                else:
                    cumul -= qty
                    all_sell.append((ts_g, fl.get("price", 0)))
                all_pos.append((ts_g, cumul))

        ds_features = all_features[::5]
        ds_pos = all_pos[::3] if len(all_pos) > 200 else all_pos
        pp_data[prod] = {"ts": [t for t, _ in ds_features], "mid": [m for _, m in ds_features]}
        pp_pos[prod] = {"ts": [t for t, _ in ds_pos], "pos": [p for _, p in ds_pos]}
        pp_marks[prod] = {
            "buys": {"ts": [t for t, _ in all_buy], "p": [p for _, p in all_buy]},
            "sells": {"ts": [t for t, _ in all_sell], "p": [p for _, p in all_sell]},
        }

    # Per-product per-day PnL
    per_day_per_prod = {}
    for prod in relevant:
        per_day_per_prod[prod] = []
        for day in days:
            ps = day.get("product_summaries", {}).get(prod, {})
            per_day_per_prod[prod].append({
                "day": day.get("day"), "pnl": ps.get("pnl", 0),
                "max_pos": ps.get("max_abs_position", 0),
                "trades": ps.get("trades", 0),
                "end_pos": ps.get("end_position", 0),
            })

    print(f"  Building HTML for {len(relevant)} products...")
    out_html.parent.mkdir(parents=True, exist_ok=True)

    pnl_total = d["summary"]["total_pnl"]
    dd = d["summary"]["robustness"]["max_drawdown"]
    ratio = pnl_total / dd if dd else 0
    n_days = len(days)

    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title} — PnL ${pnl_total:,.0f}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; margin: 20px; background: #f5f5f7; color: #222; }}
.card {{ background: white; padding: 18px; margin: 16px 0; border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); }}
h1 {{ color: #111; margin: 0 0 8px 0; }}
h2 {{ color: #1a73e8; border-bottom: 2px solid #e0e0e0; padding-bottom: 6px; margin-top: 0; }}
h3 {{ color: #444; margin: 16px 0 4px 0; font-size: 16px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ padding: 6px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ background: #fafafa; color: #555; font-weight: 600; }}
.profit {{ color: #0a8043; font-weight: bold; }}
.loss {{ color: #c5221f; font-weight: bold; }}
.metric {{ display: inline-block; margin-right: 30px; padding: 8px 0; }}
.metric .v {{ font-size: 28px; font-weight: bold; color: #1a73e8; }}
.metric .l {{ font-size: 12px; color: #666; text-transform: uppercase; }}
.chart {{ height: 380px; }}
.subchart {{ height: 200px; }}
nav {{ position: sticky; top: 0; background: rgba(255,255,255,0.95); padding: 10px; border-bottom: 1px solid #ddd; z-index: 100; margin: -20px -20px 20px -20px; }}
nav a {{ color: #1a73e8; margin-right: 14px; text-decoration: none; font-size: 13px; }}
nav a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<nav>
  <strong>{title} ({n_days} days)</strong> &nbsp;|&nbsp;
  <a href="#summary">Summary</a>
  <a href="#equity">Equity</a>
  <a href="#per_day">Per-day</a>
  <a href="#products">Products</a>
</nav>

<h1 id="summary">{title}</h1>
<div class="card">
  <div class="metric"><div class="v profit">${pnl_total:,.0f}</div><div class="l">Total PnL ({n_days} days)</div></div>
  <div class="metric"><div class="v loss">${dd:,.0f}</div><div class="l">Max DD</div></div>
  <div class="metric"><div class="v">{ratio:.2f}</div><div class="l">PnL / DD ratio</div></div>
  <div class="metric"><div class="v">{len(relevant)}</div><div class="l">Active products</div></div>
</div>

<div class="card" id="per_day">
  <h2>Per-day PnL summary</h2>
  <table>
    <tr><th>Day</th><th>PnL</th></tr>
    {''.join(f'<tr><td>D{day["day"]}</td><td class="{"profit" if day.get("pnl",0)>=0 else "loss"}">{day.get("pnl",0):+,.0f}</td></tr>' for day in days)}
  </table>
</div>

<div class="card">
  <h2>Per-product per-day PnL</h2>
  <table>
    <tr><th>Product</th>{''.join(f'<th>D{day["day"]}</th>' for day in days)}<th>Total</th><th>Worst day</th><th>End pos D{n_days}</th><th>Max |pos|</th></tr>
""")

    for prod in relevant:
        days_data = per_day_per_prod[prod]
        pnls = [dd_['pnl'] for dd_ in days_data]
        total = sum(pnls)
        worst = min(pnls) if pnls else 0
        max_pos = max((dd_['max_pos'] for dd_ in days_data), default=0)
        end_pos = days_data[-1]['end_pos'] if days_data else 0
        worst_str = f'{worst:+,.0f}' if worst < 0 else '<span style="color:#888">(no loss)</span>'
        cells = ''.join(f'<td class="{"profit" if p>=0 else "loss"}">{p:+,.0f}</td>' for p in pnls)
        parts.append(f'''<tr>
<td>{prod}</td>
{cells}
<td><strong>{total:+,.0f}</strong></td>
<td>{worst_str}</td>
<td>{end_pos:+d}</td>
<td>{max_pos}</td>
</tr>''')

    parts.append("""
  </table>
</div>

<div class="card" id="equity">
  <h2>Equity Curve (cumulative PnL across days)</h2>
  <p style="color:#666;font-size:13px;">Vertical lines = day boundaries.</p>
  <div id="equity_chart" class="chart"></div>
</div>

<h2 id="products" style="margin: 28px 16px 16px 16px;">Per-Product Price + Trades + Position</h2>
""")

    for prod in relevant:
        chart_id = "chart_" + prod.replace(" ", "_")
        days_data = per_day_per_prod[prod]
        prod_total = sum(dd_['pnl'] for dd_ in days_data)
        parts.append(f"""
<div class="card">
  <h3>{prod} — total PnL: ${prod_total:+,.0f}  |  end pos D{n_days}: {days_data[-1]['end_pos']:+d}</h3>
  <div id="{chart_id}_price" class="chart"></div>
  <div id="{chart_id}_pos" class="subchart"></div>
</div>""")

    day_bounds_js = json.dumps([i * 1_000_000 for i in range(1, n_days)])
    annotations_js = []
    for i in range(n_days):
        annotations_js.append(f'{{x: {i * 1_000_000 + 500_000}, y: 1, yref: "paper", text: "D{i+1}", showarrow: false, yshift: 10}}')

    parts.append(f"""
<script>
const equity = {json.dumps(equity_concat)};
const day_bounds = {day_bounds_js};

Plotly.newPlot('equity_chart', [{{
    x: equity.map(d => d[0]), y: equity.map(d => d[1]),
    type: 'scatter', mode: 'lines',
    line: {{color: '#1a73e8', width: 2}}, name: 'Cumulative PnL',
    fill: 'tozeroy', fillcolor: 'rgba(26,115,232,0.1)'
}}], {{
    xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'PnL', tickformat: ',.0f'}},
    hovermode: 'x unified', margin: {{t: 20}},
    shapes: day_bounds.map(b => ({{
        type: 'line', x0: b, x1: b, y0: 0, y1: 1, yref: 'paper',
        line: {{color: 'gray', dash: 'dash', width: 1}}
    }})),
    annotations: [{', '.join(annotations_js)}]
}});

const pp_data = {json.dumps(pp_data)};
const pp_pos = {json.dumps(pp_pos)};
const pp_marks = {json.dumps(pp_marks)};

Object.keys(pp_data).forEach(p => {{
    const chart_id = "chart_" + p.replace(/ /g, "_");
    const d = pp_data[p];
    const pos = pp_pos[p];
    const m = pp_marks[p];
    Plotly.newPlot(chart_id + '_price', [
        {{x: d.ts, y: d.mid, name: 'Mid (smooth)', mode: 'lines', line: {{color: '#1a73e8', width: 2}}}},
        {{x: m.buys.ts, y: m.buys.p, name: 'Our BUY', mode: 'markers', marker: {{color: 'rgba(10,128,67,0.5)', size: 5, symbol: 'triangle-up'}}}},
        {{x: m.sells.ts, y: m.sells.p, name: 'Our SELL', mode: 'markers', marker: {{color: 'rgba(197,34,31,0.5)', size: 5, symbol: 'triangle-down'}}}}
    ], {{
        title: p + ' — Mid + Our trades',
        xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'Price'}},
        hovermode: 'x unified', margin: {{t: 30}},
        shapes: day_bounds.map(b => ({{type: 'line', x0: b, x1: b, y0: 0, y1: 1, yref: 'paper', line: {{color: 'gray', dash: 'dash', width: 1}}}}))
    }});
    Plotly.newPlot(chart_id + '_pos', [{{
        x: pos.ts, y: pos.pos, type: 'scatter', mode: 'lines',
        line: {{color: '#9c27b0', width: 1.5}}, name: 'Position',
        fill: 'tozeroy', fillcolor: 'rgba(156,39,176,0.1)'
    }}], {{
        title: 'Position',
        xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'qty'}},
        hovermode: 'x unified', margin: {{t: 25, b: 30}},
        shapes: day_bounds.map(b => ({{type: 'line', x0: b, x1: b, y0: 0, y1: 1, yref: 'paper', line: {{color: 'gray', dash: 'dash', width: 1}}}}))
    }});
}});
</script>
</body>
</html>
""")

    with open(out_html, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print(f"Wrote {out_html.stat().st_size:,} bytes to {out_html}")


if __name__ == "__main__":
    main()
