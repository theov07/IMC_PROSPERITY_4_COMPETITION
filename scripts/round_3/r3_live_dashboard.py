"""HTML dashboard for R3 live result analysis.

Input: pair of live files passed with `--json` and `--log`
Output: artifacts/analysis/round_3/r3_live_dashboard.html

Includes:
  1. Equity curve over time (plotly)
  2. Per-product PnL trajectory
  3. Per-product mid + bid/ask + position over time
  4. Per-counterparty fill summary (table)
  5. Mark interaction matrix
  6. Counterparty-driven flow (when Mark X buys/sells, our position change)
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_HTML = ROOT / "artifacts" / "analysis" / "round_3" / "r3_live_dashboard.html"


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
    """Parse the activities CSV log."""
    if not activities_log_str:
        return {}
    lines = activities_log_str.strip().split("\n")
    if not lines:
        return {}
    # Skip header
    header = lines[0].split(";")
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
    """Parse the equity graph log (timestamp;value per line)."""
    if not graph_log_str:
        return []
    lines = graph_log_str.strip().split("\n")[1:]  # skip header
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
    parser = argparse.ArgumentParser(description="Build an HTML dashboard for an R3 live result.")
    parser.add_argument("--json", required=True, help="Path to the live result JSON file.")
    parser.add_argument("--log", required=True, help="Path to the companion .log file.")
    parser.add_argument("--out", default=str(DEFAULT_OUT_HTML), help="HTML output path.")
    args = parser.parse_args()

    json_file = Path(args.json)
    log_file = Path(args.log)
    out_html = Path(args.out)

    print("Loading R3 result files...")
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  Profit: {data['profit']:.0f}")
    print(f"  Status: {data['status']}, Round: {data['round']}")

    activities = parse_activities_log(data["activitiesLog"])
    graph = parse_graph_log(data["graphLog"])
    trades = parse_trade_history(log_file)
    print(f"  Activities rows: {len(activities)}")
    print(f"  Graph points: {len(graph)}")
    print(f"  Trades: {len(trades)}")

    # Group activities by product
    by_product = defaultdict(list)
    for r in activities:
        by_product[r["product"]].append(r)
    products = sorted(by_product.keys())
    print(f"  Products: {products}")

    # Per-product PnL trajectory
    pp_pnl = {p: [(r["ts"], r["pnl"]) for r in by_product[p]] for p in products}

    # Trades summary
    our_trades = [t for t in trades if t["buyer"] == "SUBMISSION" or t["seller"] == "SUBMISSION"]
    external_trades = [t for t in trades if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION"]
    print(f"  Our trades: {len(our_trades)}, External: {len(external_trades)}")

    # Per-counterparty per-product fills
    cp_per_prod = defaultdict(lambda: defaultdict(lambda: {"we_buy": 0, "we_sell": 0, "n_trades": 0}))
    for t in our_trades:
        sym = t["symbol"]
        qty = t["quantity"]
        if t["buyer"] == "SUBMISSION":
            cp = t["seller"]
            cp_per_prod[sym][cp]["we_buy"] += qty
        else:
            cp = t["buyer"]
            cp_per_prod[sym][cp]["we_sell"] += qty
        if t["buyer"] == "SUBMISSION":
            cp_per_prod[sym][t["seller"]]["n_trades"] += 1
        else:
            cp_per_prod[sym][t["buyer"]]["n_trades"] += 1

    # Mark interaction matrix
    mark_matrix = defaultdict(int)  # (buyer, seller) → qty
    for t in trades:
        if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION":
            mark_matrix[(t["buyer"], t["seller"])] += t["quantity"]

    # Build HTML
    print(f"\nWriting dashboard to {out_html}...")
    out_html.parent.mkdir(parents=True, exist_ok=True)

    # Plotly via CDN, no install needed
    plot_data = {}
    plot_data["equity_curve"] = graph
    plot_data["per_product_pnl"] = pp_pnl
    plot_data["per_product_mid"] = {
        p: [(r["ts"], r["mid"]) for r in by_product[p] if r["mid"] is not None]
        for p in products
    }
    plot_data["our_trade_count"] = len(our_trades)
    plot_data["external_trade_count"] = len(external_trades)
    plot_data["total_pnl"] = data["profit"]
    plot_data["positions"] = data.get("positions", [])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>R3 Live Dashboard — Profit ${data['profit']:.0f}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; margin: 20px; background: #fafafa; }}
.card {{ background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
h1 {{ color: #333; }} h2 {{ color: #555; border-bottom: 1px solid #ddd; padding-bottom: 8px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ padding: 6px 12px; text-align: right; border-bottom: 1px solid #eee; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ background: #f0f0f0; }}
.profit {{ color: #0a8043; font-weight: bold; }}
.loss {{ color: #c5221f; font-weight: bold; }}
.metric {{ display: inline-block; margin: 0 30px; padding: 12px; }}
.metric .v {{ font-size: 32px; font-weight: bold; color: #1a73e8; }}
.metric .l {{ font-size: 13px; color: #666; }}
</style>
</head>
<body>
<h1>R3 Live Result — D2 first 10%</h1>
<div class="card">
  <div class="metric"><div class="v profit">${data['profit']:,.0f}</div><div class="l">Total LIVE PnL</div></div>
  <div class="metric"><div class="v">{len(our_trades):,}</div><div class="l">Our trades</div></div>
  <div class="metric"><div class="v">{len(external_trades):,}</div><div class="l">External Mark↔Mark</div></div>
  <div class="metric"><div class="v">{len(products)}</div><div class="l">Products active</div></div>
</div>

<div class="card">
  <h2>Final Positions (end of preview)</h2>
  <table>
    <tr><th>Product</th><th>Quantity</th></tr>
    {''.join(f'<tr><td>{p["symbol"]}</td><td>{"+" if p["quantity"]>0 else ""}{p["quantity"]:,}</td></tr>' for p in data.get("positions", []))}
  </table>
</div>

<div class="card">
  <h2>Equity Curve (Total PnL over time)</h2>
  <div id="equity_chart" style="height:400px;"></div>
</div>

<div class="card">
  <h2>Per-Product PnL Trajectory</h2>
  <div id="per_prod_pnl_chart" style="height:500px;"></div>
</div>

<div class="card">
  <h2>Per-Product Mid Price</h2>
  <div id="per_prod_mid_chart" style="height:500px;"></div>
</div>

<div class="card">
  <h2>Counterparty Fills per Product (LIVE)</h2>
  <p style="color:#666;font-size:13px;">When we trade, who's on the other side?</p>
  {''.join(f'''
  <h3>{prod}</h3>
  <table>
    <tr><th>Counterparty</th><th>We bought from</th><th>We sold to</th><th>Net us (+ buy)</th><th>Trades</th></tr>
    {''.join(f"<tr><td>{cp}</td><td>{stats['we_buy']:,}</td><td>{stats['we_sell']:,}</td><td>{(stats['we_buy']-stats['we_sell']):+,}</td><td>{stats['n_trades']}</td></tr>" for cp, stats in sorted(cp_per_prod[prod].items(), key=lambda kv: -(kv[1]['we_buy']+kv[1]['we_sell'])))}
  </table>
  ''' for prod in sorted(cp_per_prod.keys()))}
</div>

<div class="card">
  <h2>Mark↔Mark Interaction Matrix (excluding us)</h2>
  <p style="color:#666;font-size:13px;">Who trades with whom (qty totals).</p>
  <table>
    <tr><th>Buyer</th><th>Seller</th><th>Total Qty</th></tr>
    {''.join(f'<tr><td>{b}</td><td>{s}</td><td>{q:,}</td></tr>' for (b,s), q in sorted(mark_matrix.items(), key=lambda kv: -kv[1])[:30])}
  </table>
</div>

<script>
// Equity curve
const equity_data = {json.dumps(graph)};
const eq_x = equity_data.map(p => p[0]);
const eq_y = equity_data.map(p => p[1]);
Plotly.newPlot('equity_chart', [{{
    x: eq_x, y: eq_y, type: 'scatter', mode: 'lines',
    line: {{color: '#1a73e8', width: 2}}, name: 'PnL'
}}], {{
    xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'PnL', tickformat: ',.0f'}},
    hovermode: 'x unified',
    shapes: [{{
        type: 'line', x0: 0, y0: 0, x1: eq_x[eq_x.length-1], y1: 0,
        line: {{color: 'gray', width: 1, dash: 'dot'}}
    }}]
}});

// Per-product PnL
const pp_data = {json.dumps(pp_pnl)};
const pp_traces = Object.keys(pp_data).map(p => ({{
    x: pp_data[p].map(d => d[0]),
    y: pp_data[p].map(d => d[1]),
    type: 'scatter', mode: 'lines', name: p
}}));
Plotly.newPlot('per_prod_pnl_chart', pp_traces, {{
    xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'PnL', tickformat: ',.0f'}},
    hovermode: 'x unified'
}});

// Per-product mid
const mid_data = {json.dumps({p: [(r["ts"], r["mid"]) for r in by_product[p] if r["mid"] is not None] for p in products})};
const mid_traces = Object.keys(mid_data).map(p => ({{
    x: mid_data[p].map(d => d[0]),
    y: mid_data[p].map(d => d[1]),
    type: 'scatter', mode: 'lines', name: p
}}));
Plotly.newPlot('per_prod_mid_chart', mid_traces, {{
    xaxis: {{title: 'Timestamp'}}, yaxis: {{title: 'Mid Price'}},
    hovermode: 'x unified'
}});
</script>
</body>
</html>
"""

    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {out_html.stat().st_size:,} bytes to {out_html}")


if __name__ == "__main__":
    main()
