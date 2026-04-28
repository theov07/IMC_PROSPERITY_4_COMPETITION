"""HTML dashboard v2 — comprehensive price + trade evolution per asset.

Enhancements over v1:
  - Each product gets its own price chart with bid/ask shading + mid line
  - Trade markers overlaid on price (green = our buys, red = our sells, gray = Mark↔Mark)
  - Volume bars per product
  - Spread evolution
  - Position evolution
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

LOG_DIR = Path("C:/Users/LéoRENAULT/Downloads/result_round_3")
LOG_FILE = LOG_DIR / "486239.log"
JSON_FILE = LOG_DIR / "486239.json"
OUT_HTML = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION/artifacts/analysis/round_3/r3_live_dashboard_v2.html")


def parse_trade_history(log_path: Path):
    with open(log_path, "r", encoding="utf-8") as f:
        raw = f.read()
    start = raw.find('"tradeHistory":[')
    if start < 0:
        return []
    start += len('"tradeHistory":')
    depth = 0
    for i, ch in enumerate(raw[start:]):
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:start + i + 1])
    return []


def parse_activities_log(activities_log_str):
    if not activities_log_str:
        return []
    lines = activities_log_str.strip().split("\n")
    if not lines:
        return []
    rows = []
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) < 17:
            continue
        try:
            row = {
                "day": int(parts[0]),
                "ts": int(parts[1]),
                "product": parts[2],
                "bid_p1": float(parts[3]) if parts[3] else None,
                "bid_v1": int(parts[4]) if parts[4] else 0,
                "ask_p1": float(parts[9]) if parts[9] else None,
                "ask_v1": int(parts[10]) if parts[10] else 0,
                "mid": float(parts[15]) if parts[15] else None,
                "pnl": float(parts[16]) if parts[16] else 0.0,
            }
            rows.append(row)
        except Exception:
            continue
    return rows


def parse_graph_log(graph_log_str):
    if not graph_log_str:
        return []
    lines = graph_log_str.strip().split("\n")[1:]
    out = []
    for line in lines:
        parts = line.split(";")
        if len(parts) >= 2:
            try:
                out.append((int(parts[0]), float(parts[1])))
            except Exception:
                continue
    return out


def main():
    print("Loading R3 result files...")
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  Profit: {data['profit']:.0f}")

    activities = parse_activities_log(data["activitiesLog"])
    graph = parse_graph_log(data["graphLog"])
    trades = parse_trade_history(LOG_FILE)
    print(f"  Activities rows: {len(activities)}")
    print(f"  Trades: {len(trades)}")

    # Group activities by product (keep mid + bid + ask + volume)
    by_product = defaultdict(list)
    for r in activities:
        by_product[r["product"]].append(r)
    products = sorted(by_product.keys())

    # Sample down for speed (every 100 ts = every tick)
    def downsample(rows, step=10):
        return [r for i, r in enumerate(rows) if i % step == 0]

    # Per-product time series for plotting
    pp_data = {}
    for p in products:
        rows = by_product[p]
        # downsample to keep HTML small
        rows_ds = downsample(rows, step=5)
        pp_data[p] = {
            "ts": [r["ts"] for r in rows_ds],
            "mid": [r["mid"] for r in rows_ds],
            "bid": [r["bid_p1"] for r in rows_ds],
            "ask": [r["ask_p1"] for r in rows_ds],
            "spread": [(r["ask_p1"] - r["bid_p1"]) if r["bid_p1"] and r["ask_p1"] else None for r in rows_ds],
            "vol": [r["bid_v1"] + r["ask_v1"] for r in rows_ds],
            "pnl": [r["pnl"] for r in rows_ds],
        }

    # Trades grouped by product
    trades_by_prod = defaultdict(list)
    for t in trades:
        trades_by_prod[t["symbol"]].append(t)

    # Position trajectory per product (cumulative from our trades)
    pp_position = {}
    for p in products:
        pos = 0
        traj = []
        ts_to_pos = {}
        for t in sorted(trades_by_prod[p], key=lambda x: x["timestamp"]):
            if t["buyer"] == "SUBMISSION":
                pos += t["quantity"]
            elif t["seller"] == "SUBMISSION":
                pos -= t["quantity"]
            ts_to_pos[t["timestamp"]] = pos
        # Fill in via piecewise constant
        for r in by_product[p]:
            ts = r["ts"]
            # Find latest pos update <= ts
            relevant = [k for k in ts_to_pos if k <= ts]
            cur_pos = ts_to_pos[max(relevant)] if relevant else 0
            traj.append((ts, cur_pos))
        traj_ds = traj[::5]  # downsample
        pp_position[p] = {
            "ts": [t for t, _ in traj_ds],
            "pos": [v for _, v in traj_ds],
        }

    # Trade markers per product
    pp_trade_markers = {}
    for p in products:
        our_buys = [(t["timestamp"], t["price"]) for t in trades_by_prod[p] if t["buyer"] == "SUBMISSION"]
        our_sells = [(t["timestamp"], t["price"]) for t in trades_by_prod[p] if t["seller"] == "SUBMISSION"]
        external = [(t["timestamp"], t["price"]) for t in trades_by_prod[p]
                    if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION"]
        pp_trade_markers[p] = {
            "buys": {"ts": [t for t, _ in our_buys], "p": [p_ for _, p_ in our_buys]},
            "sells": {"ts": [t for t, _ in our_sells], "p": [p_ for _, p_ in our_sells]},
            "external": {"ts": [t for t, _ in external], "p": [p_ for _, p_ in external]},
        }

    # Counterparty per-product
    cp_per_prod = defaultdict(lambda: defaultdict(lambda: {"we_buy": 0, "we_sell": 0, "n_trades": 0}))
    for t in trades:
        if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION":
            continue
        sym = t["symbol"]
        qty = t["quantity"]
        if t["buyer"] == "SUBMISSION":
            cp = t["seller"]
            cp_per_prod[sym][cp]["we_buy"] += qty
        else:
            cp = t["buyer"]
            cp_per_prod[sym][cp]["we_sell"] += qty
        cp_per_prod[sym][cp]["n_trades"] += 1

    print(f"  Building HTML...")
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)

    # ── Build HTML ────────────────────────────────────────────────────
    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>R3 Live Dashboard v2 — Profit ${data['profit']:.0f}</title>
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
.product-grid {{ display: grid; grid-template-columns: 1fr; gap: 0; }}
.chart {{ height: 380px; }}
.subchart {{ height: 200px; }}
nav {{ position: sticky; top: 0; background: rgba(255,255,255,0.95); padding: 10px; border-bottom: 1px solid #ddd; z-index: 100; margin: -20px -20px 20px -20px; }}
nav a {{ color: #1a73e8; margin-right: 14px; text-decoration: none; font-size: 13px; }}
nav a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<nav>
  <strong>R3 Live Dashboard v2</strong> &nbsp;|&nbsp;
  <a href="#summary">Summary</a>
  <a href="#equity">Equity Curve</a>
  <a href="#prices">Asset Prices</a>
  <a href="#counterparties">Counterparties</a>
</nav>

<h1 id="summary">R3 Live Result — Day 2 first 10%</h1>
<div class="card">
  <div class="metric"><div class="v profit">${data['profit']:,.0f}</div><div class="l">Total Live PnL</div></div>
  <div class="metric"><div class="v">{sum(1 for t in trades if t["buyer"] == "SUBMISSION" or t["seller"] == "SUBMISSION"):,}</div><div class="l">Our Trades</div></div>
  <div class="metric"><div class="v">{sum(1 for t in trades if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION"):,}</div><div class="l">Mark↔Mark</div></div>
  <div class="metric"><div class="v">{len(products)}</div><div class="l">Products</div></div>
</div>

<div class="card">
  <h2>Final Positions</h2>
  <table>
    <tr><th>Product</th><th>Quantity</th></tr>
    {''.join(f'<tr><td>{p["symbol"]}</td><td>{"+" if p["quantity"]>0 else ""}{p["quantity"]:,}</td></tr>' for p in data.get("positions", []))}
  </table>
</div>

<div class="card" id="equity">
  <h2>Equity Curve (Total PnL)</h2>
  <div id="equity_chart" class="chart"></div>
</div>

<h2 id="prices" style="margin: 28px 16px 16px 16px;">Asset Price Evolution</h2>
""")

    # Per-product price chart sections
    for p in products:
        chart_id = "chart_" + p.replace(" ", "_")
        html_parts.append(f"""
<div class="card">
  <h3>{p}</h3>
  <div id="{chart_id}_price" class="chart"></div>
  <div id="{chart_id}_pos" class="subchart"></div>
  <div id="{chart_id}_pnl" class="subchart"></div>
</div>""")

    # Counterparty section
    html_parts.append('<div class="card" id="counterparties"><h2>Counterparty Fills per Product</h2>')
    for prod in sorted(cp_per_prod.keys()):
        cps = cp_per_prod[prod]
        html_parts.append(f"<h3>{prod}</h3><table>")
        html_parts.append("<tr><th>Counterparty</th><th>We Bought</th><th>We Sold</th><th>Net (+ buy)</th><th>Trades</th></tr>")
        for cp, stats in sorted(cps.items(), key=lambda kv: -(kv[1]["we_buy"] + kv[1]["we_sell"])):
            html_parts.append(f"<tr><td>{cp}</td><td>{stats['we_buy']:,}</td><td>{stats['we_sell']:,}</td><td>{(stats['we_buy']-stats['we_sell']):+,}</td><td>{stats['n_trades']}</td></tr>")
        html_parts.append("</table>")
    html_parts.append("</div>")

    # Plotly script
    html_parts.append(f"""
<script>
// Equity curve
const equity = {json.dumps(graph)};
Plotly.newPlot('equity_chart', [{{
    x: equity.map(d => d[0]), y: equity.map(d => d[1]),
    type: 'scatter', mode: 'lines',
    line: {{color: '#1a73e8', width: 2}}, name: 'Total PnL',
    fill: 'tozeroy', fillcolor: 'rgba(26,115,232,0.1)'
}}], {{
    xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'PnL', tickformat: ',.0f'}},
    hovermode: 'x unified', margin: {{t: 20}}
}});

// Per-product charts
const pp_data = {json.dumps(pp_data)};
const pp_pos = {json.dumps(pp_position)};
const pp_marks = {json.dumps(pp_trade_markers)};

Object.keys(pp_data).forEach(p => {{
    const chart_id = "chart_" + p.replace(/ /g, "_");
    const d = pp_data[p];
    const pos = pp_pos[p];
    const m = pp_marks[p];

    // PRICE CHART: bid/ask area + mid line + trade markers
    const traces = [
        {{
            x: d.ts, y: d.bid, name: 'Bid', mode: 'lines',
            line: {{color: '#0a8043', width: 1}}, opacity: 0.6
        }},
        {{
            x: d.ts, y: d.ask, name: 'Ask', mode: 'lines',
            line: {{color: '#c5221f', width: 1}}, opacity: 0.6,
            fill: 'tonexty', fillcolor: 'rgba(150,150,150,0.1)'
        }},
        {{
            x: d.ts, y: d.mid, name: 'Mid', mode: 'lines',
            line: {{color: '#1a73e8', width: 2}}
        }},
        {{
            x: m.buys.ts, y: m.buys.p, name: 'Our BUY',
            mode: 'markers', marker: {{color: '#0a8043', size: 8, symbol: 'triangle-up'}},
            type: 'scatter'
        }},
        {{
            x: m.sells.ts, y: m.sells.p, name: 'Our SELL',
            mode: 'markers', marker: {{color: '#c5221f', size: 8, symbol: 'triangle-down'}},
            type: 'scatter'
        }},
        {{
            x: m.external.ts, y: m.external.p, name: 'Mark↔Mark',
            mode: 'markers', marker: {{color: 'rgba(150,150,150,0.5)', size: 5, symbol: 'circle'}},
            type: 'scatter'
        }}
    ];
    Plotly.newPlot(chart_id + '_price', traces, {{
        title: p + ' — Price + Trades',
        xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'Price'}},
        hovermode: 'x unified', margin: {{t: 30}}, showlegend: true
    }});

    // POSITION CHART
    Plotly.newPlot(chart_id + '_pos', [{{
        x: pos.ts, y: pos.pos, type: 'scatter', mode: 'lines',
        line: {{color: '#9c27b0', width: 1.5}}, name: 'Position',
        fill: 'tozeroy', fillcolor: 'rgba(156,39,176,0.1)'
    }}], {{
        title: 'Position', height: 180,
        xaxis: {{title: ''}}, yaxis: {{title: 'qty'}},
        hovermode: 'x unified', margin: {{t: 25, b: 30}}
    }});

    // PNL CHART
    Plotly.newPlot(chart_id + '_pnl', [{{
        x: d.ts, y: d.pnl, type: 'scatter', mode: 'lines',
        line: {{color: '#ff6d00', width: 1.5}}, name: 'PnL',
        fill: 'tozeroy', fillcolor: 'rgba(255,109,0,0.1)'
    }}], {{
        title: 'PnL', height: 180,
        xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'PnL'}},
        hovermode: 'x unified', margin: {{t: 25, b: 30}}
    }});
}});
</script>
</body>
</html>
""")

    final_html = "".join(html_parts)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(final_html)
    print(f"Wrote {OUT_HTML.stat().st_size:,} bytes to {OUT_HTML}")


if __name__ == "__main__":
    main()
