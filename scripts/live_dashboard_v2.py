"""HTML dashboard for any LIVE log (IMC submission JSON).

Plots PER PRODUCT:
  - mid_price + bid_1 + ask_1 (top-of-book)
  - "fair value" = EMA(mid, half_life=10) — proxy for v9's _smooth_mid
  - our BUY/SELL trades (markers)
  - position trajectory below

Usage:
  python scripts/live_dashboard_v2.py \\
      --log "C:/Users/LeoRENAULT/Downloads/log_v9/517024.json" \\
      --out artifacts/analysis/round_4/live_v9_dashboard.html
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True, help="Path to LIVE log JSON")
    ap.add_argument("--out", required=True, help="HTML output path")
    ap.add_argument("--title", default=None, help="Optional dashboard title")
    args = ap.parse_args()

    log_path = Path(args.log)
    out_html = Path(args.out)
    print(f"Loading {log_path.stat().st_size/1e6:.1f} MB JSON...")
    with open(log_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    profit = d.get("profit", 0)
    title = args.title or f"R4 LIVE — PnL ${profit:+,.0f} ({log_path.stem})"

    # Parse activitiesLog: per (product, ts) -> bid/ask/mid
    rows = []
    lines = d.get("activitiesLog", "").strip().split("\n")
    if not lines:
        print("ERROR: empty activitiesLog")
        return
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) < 17:
            continue
        try:
            rows.append({
                "ts": int(parts[1]),
                "product": parts[2],
                "bid_p": float(parts[3]) if parts[3] else None,
                "bid_v": int(parts[4]) if parts[4] else 0,
                "ask_p": float(parts[9]) if parts[9] else None,
                "ask_v": int(parts[10]) if parts[10] else 0,
                "mid": float(parts[15]) if parts[15] else None,
                "pnl": float(parts[16]) if parts[16] else 0.0,
            })
        except Exception:
            continue
    print(f"  Activities rows: {len(rows):,}")

    # Compute equity curve (sum of all per-product PnL per tick)
    pnl_at_ts = defaultdict(float)
    for r in rows:
        pnl_at_ts[r["ts"]] += r["pnl"]
    equity = sorted(pnl_at_ts.items())
    cumul = 0.0
    equity_running = []
    for ts, p in equity:
        cumul += p
        equity_running.append((ts, p))  # p IS already cumulative in the IMC format

    # Use direct PnL value at each ts (not cumulative diff)
    # IMC's profit_and_loss column is per-tick total
    equity_running = [(ts, sum(r["pnl"] for r in rows if r["ts"] == ts)) for ts, _ in equity]
    # Re-do simpler: total_pnl per ts is sum of last per-product pnl observed
    total_at_ts = {}
    last_pnl = {}
    for r in rows:
        last_pnl[r["product"]] = r["pnl"]
        total_at_ts[r["ts"]] = sum(last_pnl.values())
    equity_running = sorted(total_at_ts.items())

    # Per-product: collect time series + compute EMA fair value
    per_product = {}  # product -> {ts, mid, bid, ask, fair, vol}
    for prod in sorted(set(r["product"] for r in rows)):
        prod_rows = sorted([r for r in rows if r["product"] == prod], key=lambda x: x["ts"])
        ts_arr = [r["ts"] for r in prod_rows]
        mid_arr = [r["mid"] for r in prod_rows]
        bid_arr = [r["bid_p"] for r in prod_rows]
        ask_arr = [r["ask_p"] for r in prod_rows]
        # EMA fair value: half_life ≈ 10 ticks (matches v9 _smooth_mid default)
        alpha = 1 - 0.5 ** (1 / 10)
        fair_arr = []
        ema = mid_arr[0] if mid_arr and mid_arr[0] is not None else 0.0
        for m in mid_arr:
            if m is None:
                fair_arr.append(ema)
            else:
                ema = alpha * m + (1 - alpha) * ema
                fair_arr.append(ema)
        per_product[prod] = {
            "ts": ts_arr, "mid": mid_arr, "bid": bid_arr, "ask": ask_arr, "fair": fair_arr,
        }

    # Parse tradeHistory (our trades)
    raw_log_path = log_path.with_suffix(".log")
    our_buys = defaultdict(list)
    our_sells = defaultdict(list)
    if raw_log_path.exists():
        with open(raw_log_path, "r", encoding="utf-8") as f:
            raw = f.read()
        start = raw.find('"tradeHistory":[')
        if start >= 0:
            start += len('"tradeHistory":')
            depth = 0
            end = start
            for i, ch in enumerate(raw[start:]):
                if ch == '[':
                    depth += 1
                elif ch == ']':
                    depth -= 1
                    if depth == 0:
                        end = start + i + 1
                        break
            try:
                trades = json.loads(raw[start:end])
                for t in trades:
                    sym = t.get("symbol", "")
                    ts = t.get("timestamp", 0)
                    p = t.get("price", 0)
                    q = t.get("quantity", 0)
                    if t.get("buyer") == "SUBMISSION":
                        our_buys[sym].append((ts, p, q))
                    elif t.get("seller") == "SUBMISSION":
                        our_sells[sym].append((ts, p, q))
                print(f"  Our trades parsed: {sum(len(v) for v in our_buys.values()) + sum(len(v) for v in our_sells.values())}")
            except Exception as e:
                print(f"  Trade parse error: {e}")

    # Compute per-product position trajectory
    per_product_pos = {}
    for prod in per_product.keys():
        events = []
        for ts, p, q in our_buys.get(prod, []):
            events.append((ts, +q))
        for ts, p, q in our_sells.get(prod, []):
            events.append((ts, -q))
        events.sort()
        cur = 0
        ts_arr, pos_arr = [], []
        for ts, dq in events:
            cur += dq
            ts_arr.append(ts)
            pos_arr.append(cur)
        per_product_pos[prod] = {"ts": ts_arr, "pos": pos_arr}

    # Per-product final PnL
    pp_pnl = {prod: (last_pnl.get(prod, 0)) for prod in per_product.keys()}

    print(f"  Building HTML for {len(per_product)} products...")
    out_html.parent.mkdir(parents=True, exist_ok=True)

    relevant = sorted(per_product.keys(), key=lambda p: -abs(pp_pnl.get(p, 0)))

    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
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
.profit {{ color: #0a8043; font-weight: bold; }}
.loss {{ color: #c5221f; font-weight: bold; }}
.metric {{ display: inline-block; margin-right: 30px; padding: 8px 0; }}
.metric .v {{ font-size: 28px; font-weight: bold; color: #1a73e8; }}
.metric .l {{ font-size: 12px; color: #666; text-transform: uppercase; }}
.chart {{ height: 380px; }}
.subchart {{ height: 180px; }}
nav {{ position: sticky; top: 0; background: rgba(255,255,255,0.95); padding: 10px; border-bottom: 1px solid #ddd; z-index: 100; margin: -20px -20px 20px -20px; }}
nav a {{ color: #1a73e8; margin-right: 14px; text-decoration: none; font-size: 13px; }}
</style>
</head>
<body>
<nav><strong>{title}</strong> &nbsp;|&nbsp; <a href="#equity">Equity</a> &nbsp;|&nbsp; <a href="#products">Products</a></nav>

<h1>{title}</h1>
<div class="card">
  <div class="metric"><div class="v profit">${profit:+,.0f}</div><div class="l">Total PnL</div></div>
  <div class="metric"><div class="v">{len(per_product)}</div><div class="l">Products</div></div>
  <div class="metric"><div class="v">{sum(len(v) for v in our_buys.values())}</div><div class="l">Our buys</div></div>
  <div class="metric"><div class="v">{sum(len(v) for v in our_sells.values())}</div><div class="l">Our sells</div></div>
</div>

<div class="card" id="equity">
  <h2>Equity Curve</h2>
  <div id="equity_chart" class="chart"></div>
</div>

<div class="card">
  <h2>Per-product summary</h2>
  <table>
    <tr><th>Product</th><th>Final PnL</th><th>Our buys</th><th>Our sells</th><th>End position</th></tr>
""")
    for prod in relevant:
        nb = sum(q for _, _, q in our_buys.get(prod, []))
        ns = sum(q for _, _, q in our_sells.get(prod, []))
        pos_data = per_product_pos.get(prod, {"pos": []})
        end_pos = pos_data["pos"][-1] if pos_data.get("pos") else 0
        pnl_class = "profit" if pp_pnl.get(prod, 0) >= 0 else "loss"
        parts.append(f'<tr><td>{prod}</td><td class="{pnl_class}">{pp_pnl.get(prod, 0):+,.0f}</td><td>{nb}</td><td>{ns}</td><td>{end_pos:+d}</td></tr>')

    parts.append('  </table>\n</div>\n\n<h2 id="products" style="margin: 28px 16px 16px 16px;">Per-Product: bid/ask/mid + fair value + our trades + position</h2>\n')

    for prod in relevant:
        chart_id = "chart_" + prod.replace(" ", "_")
        parts.append(f"""
<div class="card">
  <h3>{prod} — final PnL: ${pp_pnl.get(prod, 0):+,.0f}</h3>
  <div id="{chart_id}_price" class="chart"></div>
  <div id="{chart_id}_pos" class="subchart"></div>
</div>""")

    parts.append("\n<script>\n")
    parts.append(f"const equity = {json.dumps(equity_running)};\n")
    parts.append("""
Plotly.newPlot('equity_chart', [{
    x: equity.map(d => d[0]), y: equity.map(d => d[1]),
    type: 'scatter', mode: 'lines',
    line: {color: '#1a73e8', width: 2}, name: 'PnL',
    fill: 'tozeroy', fillcolor: 'rgba(26,115,232,0.1)'
}], {
    xaxis: {title: 'Timestamp'}, yaxis: {title: 'PnL', tickformat: ',.0f'},
    hovermode: 'x unified', margin: {t: 20}
});

""")

    parts.append(f"const pp = {json.dumps(per_product)};\n")
    parts.append(f"const pp_pos = {json.dumps(per_product_pos)};\n")
    # Buys/sells as plain dicts of lists
    bs = {p: {"buys": our_buys[p], "sells": our_sells[p]} for p in our_buys.keys() | our_sells.keys()}
    parts.append(f"const trades = {json.dumps(bs)};\n")

    parts.append("""
Object.keys(pp).forEach(p => {
    const chart_id = "chart_" + p.replace(/ /g, "_");
    const d = pp[p];
    const t = trades[p] || {buys: [], sells: []};
    const pos = pp_pos[p] || {ts: [], pos: []};
    Plotly.newPlot(chart_id + '_price', [
        {x: d.ts, y: d.bid, name: 'bid_1', mode: 'lines', line: {color: 'rgba(10,128,67,0.4)', width: 1, dash: 'dot'}},
        {x: d.ts, y: d.ask, name: 'ask_1', mode: 'lines', line: {color: 'rgba(197,34,31,0.4)', width: 1, dash: 'dot'}},
        {x: d.ts, y: d.mid, name: 'mid', mode: 'lines', line: {color: '#666', width: 1}},
        {x: d.ts, y: d.fair, name: 'fair (EMA)', mode: 'lines', line: {color: '#1a73e8', width: 2}},
        {x: t.buys.map(x => x[0]), y: t.buys.map(x => x[1]), name: 'Our BUY', mode: 'markers', marker: {color: '#0a8043', size: 7, symbol: 'triangle-up'}},
        {x: t.sells.map(x => x[0]), y: t.sells.map(x => x[1]), name: 'Our SELL', mode: 'markers', marker: {color: '#c5221f', size: 7, symbol: 'triangle-down'}}
    ], {
        title: p + ' — Order book + fair value + our trades',
        xaxis: {title: 'Timestamp'}, yaxis: {title: 'Price'},
        hovermode: 'x unified', margin: {t: 30}, showlegend: true
    });
    Plotly.newPlot(chart_id + '_pos', [{
        x: pos.ts, y: pos.pos, type: 'scatter', mode: 'lines',
        line: {color: '#9c27b0', width: 1.5}, name: 'Position',
        fill: 'tozeroy', fillcolor: 'rgba(156,39,176,0.1)'
    }], {
        title: 'Position',
        xaxis: {title: 'Timestamp'}, yaxis: {title: 'qty'},
        hovermode: 'x unified', margin: {t: 25, b: 30}
    });
});
</script>
</body>
</html>
""")

    with open(out_html, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print(f"Wrote {out_html.stat().st_size:,} bytes to {out_html}")


if __name__ == "__main__":
    main()
