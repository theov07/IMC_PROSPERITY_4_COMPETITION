"""HTML dashboard for v5 BACKTEST 3-day result on VELVET + options.

Same format as r3_live_dashboard_v2 but reads from our backtest JSON.

Source: artifacts/analysis/round_4/r4_velvet_v4_M49_w08_postslim_3d.json
Output: artifacts/analysis/round_4/v5_backtest_dashboard.html
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
JSON_PATH = ROOT / "artifacts" / "analysis" / "round_4" / "r4_velvet_v4_M49_w08_postslim_3d.json"
OUT_HTML = ROOT / "artifacts" / "analysis" / "round_4" / "v5_backtest_dashboard.html"


def main():
    print(f"Loading backtest JSON ({JSON_PATH.stat().st_size/1e6:.1f} MB)...")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        d = json.load(f)
    print(f"  Total PnL: {d['summary']['total_pnl']:.0f}")
    print(f"  DD: {d['summary']['robustness']['max_drawdown']:.0f}")

    days = d["days"]
    products = sorted(d["summary"]["per_product_pnl"].keys())
    relevant = [p for p in products if d["summary"]["per_product_pnl"].get(p, 0) != 0]

    # ---- Equity curve concatenated across 3 days ----
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

    # ---- Per-product per-tick data ----
    # Use feature_ticks (has mid + bid/ask) and fills
    pp_data = {}
    pp_pos = {}
    pp_marks = {}
    for prod in relevant:
        all_features = []
        all_pos = []
        all_buy = []
        all_sell = []
        for di, day in enumerate(days):
            offset = di * 1_000_000
            features = day.get("feature_ticks", [])
            day_features = [f for f in features if f.get("symbol") == prod]
            # Per-tick mid (try MidSmooth or fall back)
            for f in day_features:
                ts_g = offset + f.get("timestamp", 0)
                mid = f.get("MidSmooth")
                all_features.append((ts_g, mid))
            # Position evolution from product_summaries (per-day final)
            ps = day.get("product_summaries", {}).get(prod, {})
            # Use fills to reconstruct position trajectory
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

        # Downsample features (keep every 5th to keep HTML small)
        ds_features = all_features[::5]
        ds_pos = all_pos[::3] if len(all_pos) > 200 else all_pos

        pp_data[prod] = {
            "ts": [t for t, _ in ds_features],
            "mid": [m for _, m in ds_features],
        }
        pp_pos[prod] = {
            "ts": [t for t, _ in ds_pos],
            "pos": [p for _, p in ds_pos],
        }
        pp_marks[prod] = {
            "buys": {"ts": [t for t, _ in all_buy], "p": [p for _, p in all_buy]},
            "sells": {"ts": [t for t, _ in all_sell], "p": [p for _, p in all_sell]},
        }

    # ---- Per-product per-day PnL bars ----
    per_day_per_prod = {}
    for prod in relevant:
        per_day_per_prod[prod] = []
        for day in days:
            ps = day.get("product_summaries", {}).get(prod, {})
            per_day_per_prod[prod].append({
                "day": day.get("day"),
                "pnl": ps.get("pnl", 0),
                "max_pos": ps.get("max_abs_position", 0),
                "trades": ps.get("trades", 0),
            })

    print(f"  Building HTML for {len(relevant)} products...")
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)

    html_parts = []
    pnl_total = d["summary"]["total_pnl"]
    dd = d["summary"]["robustness"]["max_drawdown"]
    ratio = pnl_total / dd if dd else 0

    html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>R4 v5 Backtest Dashboard — PnL ${pnl_total:,.0f}</title>
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
.day-bar {{ display: flex; gap: 4px; height: 30px; margin-top: 4px; }}
.day-bar .day {{ flex: 1; padding: 4px 6px; font-size: 11px; color: white; border-radius: 4px; text-align: center; }}
</style>
</head>
<body>
<nav>
  <strong>R4 v5 Backtest Dashboard (3 days)</strong> &nbsp;|&nbsp;
  <a href="#summary">Summary</a>
  <a href="#equity">Equity</a>
  <a href="#per_day">Per-day</a>
  <a href="#products">Products</a>
</nav>

<h1 id="summary">R4 v5 BACKTEST — VELVET + Options (3-day)</h1>
<div class="card">
  <div class="metric"><div class="v profit">${pnl_total:,.0f}</div><div class="l">Total PnL (3 days)</div></div>
  <div class="metric"><div class="v loss">${dd:,.0f}</div><div class="l">Max DD</div></div>
  <div class="metric"><div class="v">{ratio:.2f}</div><div class="l">PnL / DD ratio</div></div>
  <div class="metric"><div class="v">{len(relevant)}</div><div class="l">Active products</div></div>
</div>

<div class="card" id="per_day">
  <h2>Per-day PnL summary</h2>
  <table>
    <tr><th>Day</th><th>PnL</th><th>vs prev</th></tr>
    {''.join(f'<tr><td>D{day["day"]}</td><td class="{"profit" if day["pnl"]>=0 else "loss"}">{day["pnl"]:+,.0f}</td><td></td></tr>' for day in days)}
  </table>
</div>

<div class="card">
  <h2>Per-product 3-day PnL</h2>
  <table>
    <tr><th>Product</th><th>D1</th><th>D2</th><th>D3</th><th>Total</th><th>Worst day</th><th>Max position</th></tr>
""")

    for prod in relevant:
        days_data = per_day_per_prod[prod]
        d1, d2, d3 = days_data[0]['pnl'], days_data[1]['pnl'], days_data[2]['pnl']
        total = d1 + d2 + d3
        worst = min(d1, d2, d3)
        max_pos = max(day['max_pos'] for day in days_data)
        worst_str = f'{worst:+,.0f}' if worst < 0 else '<span style="color:#888">(no loss)</span>'
        html_parts.append(f'''<tr>
<td>{prod}</td>
<td class="{"profit" if d1>=0 else "loss"}">{d1:+,.0f}</td>
<td class="{"profit" if d2>=0 else "loss"}">{d2:+,.0f}</td>
<td class="{"profit" if d3>=0 else "loss"}">{d3:+,.0f}</td>
<td><strong>{total:+,.0f}</strong></td>
<td>{worst_str}</td>
<td>{max_pos}</td>
</tr>''')

    html_parts.append("""
  </table>
</div>

<div class="card" id="equity">
  <h2>Equity Curve (Total PnL across 3 days)</h2>
  <p style="color:#666;font-size:13px;">Vertical lines = day boundaries (D1 ends at ts 1M, D2 at 2M, D3 at 3M).</p>
  <div id="equity_chart" class="chart"></div>
</div>

<h2 id="products" style="margin: 28px 16px 16px 16px;">Per-Product Price + Trades + Position</h2>
""")

    for prod in relevant:
        chart_id = "chart_" + prod.replace(" ", "_")
        html_parts.append(f"""
<div class="card">
  <h3>{prod} — total PnL: ${sum(d['pnl'] for d in per_day_per_prod[prod]):+,.0f}</h3>
  <div id="{chart_id}_price" class="chart"></div>
  <div id="{chart_id}_pos" class="subchart"></div>
</div>""")

    # Plotly script
    html_parts.append(f"""
<script>
const equity = {json.dumps(equity_concat)};
const day_bounds = [1000000, 2000000];

Plotly.newPlot('equity_chart', [{{
    x: equity.map(d => d[0]), y: equity.map(d => d[1]),
    type: 'scatter', mode: 'lines',
    line: {{color: '#1a73e8', width: 2}}, name: 'Cumulative PnL',
    fill: 'tozeroy', fillcolor: 'rgba(26,115,232,0.1)'
}}], {{
    xaxis: {{title: 'Timestamp (ts)'}}, yaxis: {{title: 'PnL', tickformat: ',.0f'}},
    hovermode: 'x unified', margin: {{t: 20}},
    shapes: day_bounds.map(b => ({{
        type: 'line', x0: b, x1: b, y0: 0, y1: 1, yref: 'paper',
        line: {{color: 'gray', dash: 'dash', width: 1}}
    }})),
    annotations: [
        {{x: 500000, y: 1, yref: 'paper', text: 'D1', showarrow: false, yshift: 10}},
        {{x: 1500000, y: 1, yref: 'paper', text: 'D2', showarrow: false, yshift: 10}},
        {{x: 2500000, y: 1, yref: 'paper', text: 'D3', showarrow: false, yshift: 10}}
    ]
}});

const pp_data = {json.dumps(pp_data)};
const pp_pos = {json.dumps(pp_pos)};
const pp_marks = {json.dumps(pp_marks)};

Object.keys(pp_data).forEach(p => {{
    const chart_id = "chart_" + p.replace(/ /g, "_");
    const d = pp_data[p];
    const pos = pp_pos[p];
    const m = pp_marks[p];

    const traces = [
        {{
            x: d.ts, y: d.mid, name: 'Mid (smooth)', mode: 'lines',
            line: {{color: '#1a73e8', width: 2}}
        }},
        {{
            x: m.buys.ts, y: m.buys.p, name: 'Our BUY',
            mode: 'markers', marker: {{color: 'rgba(10,128,67,0.5)', size: 5, symbol: 'triangle-up'}}
        }},
        {{
            x: m.sells.ts, y: m.sells.p, name: 'Our SELL',
            mode: 'markers', marker: {{color: 'rgba(197,34,31,0.5)', size: 5, symbol: 'triangle-down'}}
        }}
    ];
    Plotly.newPlot(chart_id + '_price', traces, {{
        title: p + ' — Mid + Our trades',
        xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'Price'}},
        hovermode: 'x unified', margin: {{t: 30}}, showlegend: true,
        shapes: day_bounds.map(b => ({{
            type: 'line', x0: b, x1: b, y0: 0, y1: 1, yref: 'paper',
            line: {{color: 'gray', dash: 'dash', width: 1}}
        }}))
    }});

    Plotly.newPlot(chart_id + '_pos', [{{
        x: pos.ts, y: pos.pos, type: 'scatter', mode: 'lines',
        line: {{color: '#9c27b0', width: 1.5}}, name: 'Position',
        fill: 'tozeroy', fillcolor: 'rgba(156,39,176,0.1)'
    }}], {{
        title: 'Position',
        xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'qty'}},
        hovermode: 'x unified', margin: {{t: 25, b: 30}},
        shapes: day_bounds.map(b => ({{
            type: 'line', x0: b, x1: b, y0: 0, y1: 1, yref: 'paper',
            line: {{color: 'gray', dash: 'dash', width: 1}}
        }}))
    }});
}});
</script>
</body>
</html>
""")

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))
    print(f"Wrote {OUT_HTML.stat().st_size:,} bytes to {OUT_HTML}")


if __name__ == "__main__":
    main()
