"""Counterparty analysis HTML report generator.

Reads prices and trades CSVs from official IMC data and writes a
self-contained HTML file with interactive Plotly charts showing each
counterparty's activity, PnL, and inventory.

Usage:
    # Single day
    python -m prosperity.tooling.counterparties_analysis \\
        --prices data/round_4/prices_round_4_day_1.csv \\
        --trades data/round_4/trades_round_4_day_1.csv \\
        --out artifacts/analysis/round_4/counterparties.html

    # Multi-day (days chained in timestamp order)
    python -m prosperity.tooling.counterparties_analysis \\
        --prices data/round_4/prices_round_4_day_{1,2,3}.csv \\
        --trades data/round_4/trades_round_4_day_{1,2,3}.csv \\
        --out artifacts/analysis/round_4/counterparties_all.html

    # Single product
    python -m prosperity.tooling.counterparties_analysis \\
        --prices data/round_4/prices_round_4_day_1.csv \\
        --trades data/round_4/trades_round_4_day_1.csv \\
        --product VELVETFRUIT_EXTRACT \\
        --out artifacts/analysis/round_4/velvet_counterparties.html
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.26.0.min.js"

# ── Visual palette (up to 12 traders) ────────────────────────────────────────

SHAPES = [
    "circle", "square", "diamond", "triangle-up", "cross",
    "star", "hexagram", "pentagon", "triangle-down", "bowtie",
    "asterisk", "hourglass",
]

# Light fills → buy markers
BUY_COLORS = [
    "#74c7ec",  # sky blue
    "#a6e3a1",  # green
    "#fab387",  # peach
    "#cba6f7",  # lavender
    "#f9e2af",  # yellow
    "#89dceb",  # cyan
    "#f2cdcd",  # flamingo
    "#b4befe",  # blue-purple
    "#94e2d5",  # teal
    "#eba0ac",  # rose
    "#89b4fa",  # cornflower
    "#a6adc8",  # subtext
]

# Dark fills → sell markers (same hue family, darker)
SELL_COLORS = [
    "#1e6090",  # dark blue
    "#1a5c23",  # dark green
    "#8a3e0a",  # dark orange
    "#4a1d7c",  # dark purple
    "#7a5800",  # dark yellow
    "#0a6c7c",  # dark cyan
    "#8c2a2a",  # dark flamingo
    "#1a2d7c",  # dark blue-purple
    "#0a5c4a",  # dark teal
    "#7c1a2a",  # dark rose
    "#1a3c7c",  # dark cornflower
    "#3a3d5c",  # dark subtext
]

# Colors for per-product lines in the trader detail section
PROD_COLORS = ["#74c7ec", "#a6e3a1", "#fab387", "#cba6f7", "#f9e2af", "#89dceb",
               "#f2cdcd", "#b4befe", "#94e2d5", "#eba0ac"]


# ── Utilities ─────────────────────────────────────────────────────────────────

def _jsid(name: str) -> str:
    """Make a name safe for use as a JS variable name / HTML id."""
    return re.sub(r"[^a-zA-Z0-9]", "_", str(name))


def _jsfloat(v) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "null"
    return str(round(v, 4))


def _fmt(v, digits: int = 0) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:,.{digits}f}"


def _to_float(s: str) -> Optional[float]:
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def _to_int(s: str) -> Optional[int]:
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_prices(paths: List[Path]) -> Tuple[List[str], Dict[str, Any]]:
    """Return (products_sorted, market_by_prod) from prices CSV(s).

    market_by_prod[product] = {
        "ts":    List[int],    # all timestamps (dense, for MTM interpolation)
        "bid1":  List[float|None],
        "ask1":  List[float|None],
        "mid":   List[float|None],
    }
    """
    rows_by_prod: Dict[str, List[Tuple[int, Any, Any, Any]]] = defaultdict(list)
    ts_offset = 0

    for path in paths:
        if not path.exists():
            print(f"  Warning: {path} not found")
            continue
        max_ts = 0
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                prod = row.get("product", "").strip()
                ts   = _to_int(row.get("timestamp", ""))
                if ts is None or not prod:
                    continue
                ts_g = ts + ts_offset
                max_ts = max(max_ts, ts)
                rows_by_prod[prod].append((
                    ts_g,
                    _to_float(row.get("bid_price_1", "")),
                    _to_float(row.get("ask_price_1", "")),
                    _to_float(row.get("mid_price", "")),
                ))
        ts_offset += max_ts + 100

    products = sorted(rows_by_prod.keys())
    market_by_prod: Dict[str, Any] = {}
    for prod in products:
        rows = sorted(rows_by_prod[prod], key=lambda x: x[0])
        market_by_prod[prod] = {
            "ts":   [r[0] for r in rows],
            "bid1": [r[1] for r in rows],
            "ask1": [r[2] for r in rows],
            "mid":  [r[3] for r in rows],
        }
    return products, market_by_prod


def _load_trades(paths: List[Path], ts_offsets: List[int]) -> List[Dict]:
    """Return list of fill dicts from trades CSV(s).

    Each fill: {ts, buyer, seller, symbol, price, qty}
    """
    fills: List[Dict] = []
    for path, ts_offset in zip(paths, ts_offsets):
        if not path.exists():
            print(f"  Warning: {path} not found")
            continue
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                ts  = _to_int(row.get("timestamp", ""))
                px  = _to_float(row.get("price", ""))
                qty = _to_int(row.get("quantity", ""))
                if ts is None or px is None or qty is None:
                    continue
                buyer  = (row.get("buyer",  "") or "").strip() or "SELF"
                seller = (row.get("seller", "") or "").strip() or "SELF"
                sym    = (row.get("symbol", "") or row.get("product", "") or "").strip()
                fills.append({
                    "ts": ts + ts_offset,
                    "buyer": buyer, "seller": seller,
                    "symbol": sym, "px": px, "qty": qty,
                })
    return sorted(fills, key=lambda x: x["ts"])


def _compute_ts_offsets(price_paths: List[Path]) -> List[int]:
    """Compute per-file timestamp offsets so multi-day timestamps don't collide."""
    offsets: List[int] = []
    offset = 0
    for path in price_paths:
        offsets.append(offset)
        if not path.exists():
            continue
        max_ts = 0
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                ts = _to_int(row.get("timestamp", ""))
                if ts is not None:
                    max_ts = max(max_ts, ts)
        offset += max_ts + 100
    return offsets


# ── Analysis ──────────────────────────────────────────────────────────────────

def _mid_at(ts_list: List[int], val_list: List[Optional[float]], ts: int) -> Optional[float]:
    """Return most recent mid price at or before `ts`."""
    if not ts_list:
        return None
    idx = bisect.bisect_right(ts_list, ts) - 1
    if idx < 0:
        return None
    # Walk back to find a non-None value
    while idx >= 0:
        v = val_list[idx]
        if v is not None:
            return v
        idx -= 1
    return None


def _build_data(
    products: List[str],
    market_by_prod: Dict[str, Any],
    all_fills: List[Dict],
    product_filter: Optional[str],
) -> Dict[str, Any]:
    """Build the complete analysis data structure."""

    if product_filter:
        products = [p for p in products if p == product_filter]
        market_by_prod = {k: v for k, v in market_by_prod.items() if k == product_filter}
        all_fills = [f for f in all_fills if f["symbol"] == product_filter]

    # Discover all named traders
    all_names: set = set()
    for f in all_fills:
        all_names.add(f["buyer"])
        all_names.add(f["seller"])
    all_names.discard("SELF")
    traders = sorted(all_names)
    if any(f["buyer"] == "SELF" or f["seller"] == "SELF" for f in all_fills):
        traders = ["SELF"] + traders

    # Precompute dense mid ts/val per product (for MTM)
    mid_ts_by_prod: Dict[str, List[int]] = {}
    mid_val_by_prod: Dict[str, List[Optional[float]]] = {}
    for prod in products:
        mkt = market_by_prod[prod]
        mid_ts_by_prod[prod]  = mkt["ts"]
        mid_val_by_prod[prod] = mkt["mid"]

    # Per-trader fills
    trader_fills: Dict[str, List[Dict]] = {t: [] for t in traders}
    for f in all_fills:
        for side, name in [("BUY", f["buyer"]), ("SELL", f["seller"])]:
            if name in trader_fills:
                trader_fills[name].append({
                    "ts": f["ts"], "px": f["px"], "qty": f["qty"],
                    "side": side, "prod": f["symbol"],
                })

    # Per-trader analytics
    trader_analytics: Dict[str, Dict] = {}

    for trader in traders:
        fills = sorted(trader_fills[trader], key=lambda x: x["ts"])
        prods_traded = sorted({f["prod"] for f in fills if f["prod"] in products})

        # PnL + inventory curves per product
        prod_pnl: Dict[str, List[Dict]] = {}
        for prod in prods_traded:
            pfills = sorted([f for f in fills if f["prod"] == prod], key=lambda x: x["ts"])
            tl = mid_ts_by_prod.get(prod, [])
            vl = mid_val_by_prod.get(prod, [])

            curve: List[Dict] = []
            cash, pos, fi = 0.0, 0, 0

            # Subsample: every 10 market ticks to keep HTML light
            for i, (ts, mid) in enumerate(zip(tl, vl)):
                # Advance fills up to this timestamp
                while fi < len(pfills) and pfills[fi]["ts"] <= ts:
                    f = pfills[fi]
                    sign = 1 if f["side"] == "BUY" else -1
                    cash -= sign * f["px"] * f["qty"]
                    pos  += sign * f["qty"]
                    fi   += 1
                if i % 10 == 0 and mid is not None:
                    curve.append({
                        "ts":       int(ts),
                        "mtm":      cash + pos * mid,
                        "realized": cash,
                        "pos":      pos,
                    })
            prod_pnl[prod] = curve

        total_trades = len(fills)
        buy_trades   = sum(1 for f in fills if f["side"] == "BUY")
        total_vol    = sum(f["qty"] for f in fills)
        final_mtm    = sum(c[-1]["mtm"] if c else 0.0 for c in prod_pnl.values())

        pos_samples = [abs(r["pos"]) for c in prod_pnl.values() for r in c]
        avg_abs_pos = sum(pos_samples) / len(pos_samples) if pos_samples else 0.0

        trader_analytics[trader] = {
            "total_trades": total_trades,
            "buy_trades":   buy_trades,
            "sell_trades":  total_trades - buy_trades,
            "total_vol":    total_vol,
            "final_mtm":    final_mtm,
            "avg_abs_pos":  avg_abs_pos,
            "prod_pnl":     prod_pnl,
            "fills":        fills,
        }

    return {
        "products":         products,
        "market_by_prod":   market_by_prod,
        "traders":          traders,
        "trader_analytics": trader_analytics,
    }


# ── HTML / CSS / JS ───────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'JetBrains Mono', monospace, sans-serif;
       background: #1e1e2e; color: #cdd6f4; }
h2 { color: #cba6f7; margin: 1em 0 0.5em; }
h3 { color: #89dceb; margin: 0.6em 0 0.3em; font-size: 1em; }
.container { max-width: 1600px; margin: 0 auto; padding: 1em 2em; }
.section { margin-bottom: 2.5em; }
.hint { color: #6c7086; font-size: 0.78em; margin-bottom: 0.6em; }

/* Summary table */
.summary-table { width: 100%; border-collapse: collapse; font-size: 0.82em; }
.summary-table th {
  background: #313244; padding: 6px 10px;
  text-align: right; color: #cba6f7; white-space: nowrap;
}
.summary-table th:first-child { text-align: left; }
.summary-table td {
  padding: 5px 10px; border-bottom: 1px solid #313244;
  text-align: right; cursor: pointer;
}
.summary-table td:first-child { text-align: left; }
.summary-table tr:hover td { background: #2a2a3e; }
.pos { color: #a6e3a1; }
.neg { color: #f38ba8; }
.trader-dot {
  display: inline-block; width: 11px; height: 11px;
  border-radius: 50%; margin-right: 7px; vertical-align: middle;
}

/* Tabs */
.tab-bar { display: flex; flex-wrap: wrap; gap: 6px; margin: 0.8em 0; }
.tab-btn {
  padding: 5px 13px; border: 1px solid #45475a; border-radius: 6px;
  background: #313244; color: #cdd6f4; cursor: pointer; font-size: 0.82em;
  transition: background 0.15s;
}
.tab-btn:hover  { background: #45475a; }
.tab-btn.active {
  background: #45475a; border-color: #cba6f7;
  color: #cba6f7; font-weight: bold;
}

/* Charts */
.chart-container { margin-bottom: 1em; border-radius: 8px; overflow: hidden; }
.chart      { height: 360px; }
.chart-tall { height: 500px; }
.product-panel { display: none; }
.trader-panel  { display: none; }

/* Legend key in description */
.legend-keys { display: flex; flex-wrap: wrap; gap: 12px; margin: 0.4em 0 0.8em; font-size: 0.78em; }
.legend-key  { display: flex; align-items: center; gap: 5px; color: #a6adc8; }
"""

JS_TABS = """
function showProductPanel(safe) {
  document.querySelectorAll('.product-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.prod-tab-btn').forEach(b => b.classList.remove('active'));
  var panel = document.getElementById('prod_panel_' + safe);
  if (panel) { panel.style.display = 'block'; }
  var btn = document.getElementById('prod_btn_' + safe);
  if (btn) { btn.classList.add('active'); }
  var fn = window['plot_prod_' + safe];
  if (fn && panel && !panel.dataset.plotted) { fn(); panel.dataset.plotted = '1'; }
}

function showTraderPanel(safe) {
  document.querySelectorAll('.trader-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.trader-tab-btn').forEach(b => b.classList.remove('active'));
  var panel = document.getElementById('trader_panel_' + safe);
  if (panel) { panel.style.display = 'block'; }
  var btn = document.getElementById('trader_btn_' + safe);
  if (btn) { btn.classList.add('active'); }
  var fn = window['plot_trader_' + safe];
  if (fn && panel && !panel.dataset.plotted) { fn(); panel.dataset.plotted = '1'; }
}

function jumpToTrader(safe) {
  showTraderPanel(safe);
  var el = document.getElementById('trader-detail-section');
  if (el) { setTimeout(function() { el.scrollIntoView({behavior:'smooth'}); }, 50); }
}
"""


def _layout_js() -> str:
    return """{
        plot_bgcolor: '#1e1e2e', paper_bgcolor: '#1e1e2e',
        font: {color: '#cdd6f4', size: 11},
        legend: {bgcolor: 'rgba(0,0,0,0)', font: {size: 10}},
        xaxis: {gridcolor: '#313244', title: 'timestamp'},
        yaxis: {gridcolor: '#313244'},
        margin: {t: 36, b: 44, l: 65, r: 20},
        hovermode: 'x unified',
    }"""


def _json_list(values: list) -> str:
    parts = []
    for v in values:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            parts.append("null")
        elif isinstance(v, float):
            parts.append(str(round(v, 4)))
        else:
            parts.append(str(v))
    return "[" + ",".join(parts) + "]"


# ── Summary table ─────────────────────────────────────────────────────────────

def _summary_html(data: Dict[str, Any]) -> str:
    traders   = data["traders"]
    analytics = data["trader_analytics"]

    rows = []
    for i, trader in enumerate(traders):
        a      = analytics[trader]
        safe   = _jsid(trader)
        color  = BUY_COLORS[i % len(BUY_COLORS)]
        pnl    = a["final_mtm"]
        pnl_cls = "pos" if pnl > 0 else ("neg" if pnl < 0 else "")
        prods  = ", ".join(sorted(a["prod_pnl"].keys())) or "—"
        rows.append(f"""      <tr onclick="jumpToTrader('{safe}')">
        <td><span class="trader-dot" style="background:{color}"></span>{trader}</td>
        <td>{a['total_trades']}</td>
        <td>{a['buy_trades']}</td>
        <td>{a['sell_trades']}</td>
        <td>{a['total_vol']:,}</td>
        <td class="{pnl_cls}">{_fmt(pnl)}</td>
        <td>{_fmt(a['avg_abs_pos'], 1)}</td>
        <td style="font-size:0.75em;color:#6c7086">{prods}</td>
      </tr>""")

    return f"""<div class="section" id="summary-section">
  <h2>Counterparty Summary</h2>
  <p class="hint">Click a row to jump to that trader's PnL &amp; inventory charts.</p>
  <table class="summary-table">
    <thead>
      <tr>
        <th style="text-align:left">Trader</th>
        <th>Trades</th><th>Buys</th><th>Sells</th>
        <th>Volume</th><th>MTM PnL</th><th>Avg |Pos|</th>
        <th style="text-align:left">Products traded</th>
      </tr>
    </thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>
</div>"""


# ── Price + trades chart per product ──────────────────────────────────────────

def _price_chart_js(prod: str, mkt: Dict, traders: List[str],
                    trader_analytics: Dict[str, Dict]) -> str:
    """JS function that plots market bid/ask + all traders' fills for one product."""
    safe = _jsid(prod)

    # Subsample market data every 10 ticks
    ts_s   = mkt["ts"][::10]
    bid_s  = mkt["bid1"][::10]
    ask_s  = mkt["ask1"][::10]

    traces: List[str] = [
        f"""{{
      x:{_json_list(ts_s)}, y:{_json_list(bid_s)},
      name:'Best Bid', mode:'lines',
      line:{{color:'#89b4fa',width:1.5}},
      hovertemplate:'<b>Bid</b>: %{{y}}<extra></extra>'
    }}""",
        f"""{{
      x:{_json_list(ts_s)}, y:{_json_list(ask_s)},
      name:'Best Ask', mode:'lines',
      line:{{color:'#f38ba8',width:1.5}},
      hovertemplate:'<b>Ask</b>: %{{y}}<extra></extra>'
    }}""",
    ]

    for i, trader in enumerate(traders):
        fills = [f for f in trader_analytics[trader]["fills"] if f["prod"] == prod]
        if not fills:
            continue

        shape    = SHAPES[i % len(SHAPES)]
        buy_col  = BUY_COLORS[i  % len(BUY_COLORS)]
        sell_col = SELL_COLORS[i % len(SELL_COLORS)]

        buys  = [f for f in fills if f["side"] == "BUY"]
        sells = [f for f in fills if f["side"] == "SELL"]

        if buys:
            bts  = [f["ts"] for f in buys]
            bpx  = [f["px"] for f in buys]
            bqty = [f["qty"] for f in buys]
            traces.append(f"""{{
      x:{json.dumps(bts)}, y:{json.dumps(bpx)},
      name:'{trader} buy', mode:'markers',
      marker:{{symbol:'{shape}', color:'{buy_col}', size:9, opacity:0.9,
               line:{{color:'#1e1e2e',width:0.5}}}},
      customdata:{json.dumps(bqty)},
      hovertemplate:'<b>{trader}</b> BUY qty=%{{customdata}} @ %{{y}}<extra></extra>'
    }}""")

        if sells:
            sts  = [f["ts"] for f in sells]
            spx  = [f["px"] for f in sells]
            sqty = [f["qty"] for f in sells]
            traces.append(f"""{{
      x:{json.dumps(sts)}, y:{json.dumps(spx)},
      name:'{trader} sell', mode:'markers',
      marker:{{symbol:'{shape}', color:'{sell_col}', size:9, opacity:0.9,
               line:{{color:'#cdd6f4',width:0.8}}}},
      customdata:{json.dumps(sqty)},
      hovertemplate:'<b>{trader}</b> SELL qty=%{{customdata}} @ %{{y}}<extra></extra>'
    }}""")

    traces_js = ",\n    ".join(traces)

    return f"""
  function plot_prod_{safe}() {{
    var layout = Object.assign({{}}, {_layout_js()}, {{
      title: '{prod} — Market Price + Counterparty Trades',
      legend: {{bgcolor:'rgba(0,0,0,0)', font:{{size:9}}, x:1.01, xanchor:'left'}},
      yaxis:  {{title:'price', gridcolor:'#313244'}},
      margin: {{t:36, b:44, l:65, r:180}},
    }});
    Plotly.newPlot('prod_{safe}_chart', [
    {traces_js}
    ], layout, {{responsive:true}});
  }}"""


# ── Trader detail: PnL + inventory charts ─────────────────────────────────────

def _trader_detail_js(trader: str, analytics: Dict, products: List[str]) -> str:
    safe    = _jsid(trader)
    prod_pnl = analytics["prod_pnl"]

    pnl_traces: List[str] = []
    inv_traces: List[str] = []

    for pi, prod in enumerate(products):
        if prod not in prod_pnl or not prod_pnl[prod]:
            continue
        curve    = prod_pnl[prod]
        pc       = PROD_COLORS[pi % len(PROD_COLORS)]
        dark_pc  = SELL_COLORS[pi % len(SELL_COLORS)]
        prod_safe = _jsid(prod)

        ts_j   = json.dumps([r["ts"]       for r in curve])
        mtm_j  = json.dumps([round(r["mtm"],      2) for r in curve])
        real_j = json.dumps([round(r["realized"],  2) for r in curve])
        pos_j  = json.dumps([r["pos"]       for r in curve])

        pnl_traces.append(f"""{{
      x:{ts_j}, y:{mtm_j},
      name:'{prod} MTM PnL', mode:'lines',
      line:{{color:'{pc}', width:2}},
      hovertemplate:'{prod} MTM: %{{y:,.0f}}<extra></extra>'
    }}""")
        pnl_traces.append(f"""{{
      x:{ts_j}, y:{real_j},
      name:'{prod} Cash flow', mode:'lines',
      line:{{color:'{dark_pc}', width:1.2, dash:'dot'}},
      hovertemplate:'{prod} Cash flow: %{{y:,.0f}}<extra></extra>'
    }}""")
        inv_traces.append(f"""{{
      x:{ts_j}, y:{pos_j},
      name:'{prod}', mode:'lines', fill:'tozeroy',
      line:{{color:'{pc}', width:1.5}},
      hovertemplate:'{prod} pos: %{{y}}<extra></extra>'
    }}""")

    if not pnl_traces:
        return f"""
  function plot_trader_{safe}() {{
    // No data for {trader}
    document.getElementById('trader_{safe}_pnl').innerHTML =
      '<p style="color:#6c7086;padding:1em">No trade data for {trader}.</p>';
  }}"""

    pnl_js = ",\n    ".join(pnl_traces)
    inv_js = ",\n    ".join(inv_traces)

    return f"""
  function plot_trader_{safe}() {{
    var lb = {_layout_js()};
    Plotly.newPlot('trader_{safe}_pnl', [
    {pnl_js}
    ], Object.assign({{}}, lb, {{
      title: '{trader} — MTM PnL + Realized PnL',
      yaxis: {{title:'PnL (SeaShells)', gridcolor:'#313244'}},
    }}), {{responsive:true}});
    Plotly.newPlot('trader_{safe}_inv', [
    {inv_js}
    ], Object.assign({{}}, lb, {{
      title: '{trader} — Inventory (position per product)',
      yaxis: {{title:'units', gridcolor:'#313244'}},
    }}), {{responsive:true}});
  }}"""


# ── Per-trader product PnL summary table ──────────────────────────────────────

def _trader_pnl_table_html(trader: str, analytics: Dict, products: List[str]) -> str:
    """Small table: one row per product traded, showing final MTM PnL / cash flow / position."""
    prod_pnl = analytics["prod_pnl"]
    rows: List[str] = []
    total_mtm  = 0.0
    total_cash = 0.0

    for prod in products:
        if prod not in prod_pnl or not prod_pnl[prod]:
            continue
        last = prod_pnl[prod][-1]
        mtm  = last["mtm"]
        cash = last["realized"]   # pure cash from trades, no MTM
        pos  = last["pos"]
        total_mtm  += mtm
        total_cash += cash

        mtm_cls  = "pos" if mtm  > 0 else ("neg" if mtm  < 0 else "")
        cash_cls = "pos" if cash > 0 else ("neg" if cash < 0 else "")
        pos_cls  = "pos" if pos  > 0 else ("neg" if pos  < 0 else "")
        rows.append(
            f'      <tr>'
            f'<td style="text-align:left">{prod}</td>'
            f'<td class="{mtm_cls}">{_fmt(mtm)}</td>'
            f'<td class="{cash_cls}">{_fmt(cash)}</td>'
            f'<td class="{pos_cls}">{pos:,}</td>'
            f'</tr>'
        )

    if not rows:
        return ""

    tmtm_cls  = "pos" if total_mtm  > 0 else ("neg" if total_mtm  < 0 else "")
    tcash_cls = "pos" if total_cash > 0 else ("neg" if total_cash < 0 else "")
    total_row = (
        f'      <tr style="border-top:2px solid #cba6f7;font-weight:bold">'
        f'<td style="text-align:left">Total</td>'
        f'<td class="{tmtm_cls}">{_fmt(total_mtm)}</td>'
        f'<td class="{tcash_cls}">{_fmt(total_cash)}</td>'
        f'<td>—</td>'
        f'</tr>'
    )

    return (
        '<table class="summary-table" style="font-size:0.78em;margin:0.5em 0 1em">'
        '<thead><tr>'
        '<th style="text-align:left">Product</th>'
        '<th>MTM PnL</th>'
        '<th>Cash flow (no MTM)</th>'
        '<th>Final position</th>'
        '</tr></thead>'
        '<tbody>'
        + "\n".join(rows)
        + "\n" + total_row
        + '</tbody></table>'
    )


# ── Assemble HTML ─────────────────────────────────────────────────────────────

def generate_html(data: Dict[str, Any], output_path: Path, title: str = "") -> None:
    products         = data["products"]
    traders          = data["traders"]
    analytics        = data["trader_analytics"]
    market_by_prod   = data["market_by_prod"]

    # ── Summary table ────────────────────────────────────────────────────────
    summary_html = _summary_html(data)

    # ── Legend key (shape × color explanation) ───────────────────────────────
    legend_keys = ""
    for i, trader in enumerate(traders):
        shape    = SHAPES[i % len(SHAPES)]
        buy_col  = BUY_COLORS[i % len(BUY_COLORS)]
        sell_col = SELL_COLORS[i % len(SELL_COLORS)]
        legend_keys += (
            f'<span class="legend-key">'
            f'<svg width="14" height="14"><circle cx="7" cy="7" r="5" fill="{buy_col}"/></svg>'
            f'<svg width="14" height="14"><circle cx="7" cy="7" r="5" fill="{sell_col}"/></svg>'
            f'{trader}</span>'
        )

    # ── Product price charts ─────────────────────────────────────────────────
    prod_tab_bar = '<div class="tab-bar">'
    prod_panels  = ""
    for prod in products:
        safe = _jsid(prod)
        prod_tab_bar += (
            f'<button class="prod-tab-btn tab-btn" id="prod_btn_{safe}"'
            f' onclick="showProductPanel(\'{safe}\')">{prod}</button>'
        )
        prod_panels += f"""
<div id="prod_panel_{safe}" class="product-panel">
  <div class="chart-container">
    <div id="prod_{safe}_chart" class="chart chart-tall"></div>
  </div>
</div>"""
    prod_tab_bar += "</div>"

    # ── Trader detail panels ─────────────────────────────────────────────────
    trader_tab_bar = '<div class="tab-bar">'
    trader_panels  = ""
    for i, trader in enumerate(traders):
        safe  = _jsid(trader)
        color = BUY_COLORS[i % len(BUY_COLORS)]
        trader_tab_bar += (
            f'<button class="trader-tab-btn tab-btn" id="trader_btn_{safe}"'
            f' onclick="showTraderPanel(\'{safe}\')"'
            f' style="border-color:{color}">{trader}</button>'
        )
        pnl_table = _trader_pnl_table_html(trader, analytics[trader], products)
        trader_panels += f"""
<div id="trader_panel_{safe}" class="trader-panel">
  <h3 style="color:{color}">{trader}</h3>
  {pnl_table}
  <div class="chart-container"><div id="trader_{safe}_pnl" class="chart"></div></div>
  <div class="chart-container"><div id="trader_{safe}_inv" class="chart"></div></div>
</div>"""
    trader_tab_bar += "</div>"

    # ── JS chart functions ───────────────────────────────────────────────────
    js_prod_fns = "\n".join(
        _price_chart_js(prod, market_by_prod[prod], traders, analytics)
        for prod in products
        if prod in market_by_prod
    )
    js_trader_fns = "\n".join(
        _trader_detail_js(trader, analytics[trader], products)
        for trader in traders
    )

    first_prod_safe   = _jsid(products[0])   if products else ""
    first_trader_safe = _jsid(traders[0])    if traders  else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Counterparty Analysis — {title}</title>
  <script src="{_PLOTLY_CDN}"></script>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <h2 style="font-size:1.4em;margin-top:1em">Counterparty Analysis — {title}</h2>

  {summary_html}

  <div class="section" id="market-section">
    <h2>Market Price + Counterparty Trades</h2>
    <p class="hint">
      Each trader has a unique marker shape.
      <b style="color:#89b4fa">Light fill = buy</b> &nbsp;|&nbsp;
      <b style="color:#f38ba8">Dark fill = sell</b>.
      Hover for trader name, side, quantity, and price.
    </p>
    <div class="legend-keys">{legend_keys}</div>
    {prod_tab_bar}
    <div id="prod-panels">{prod_panels}</div>
  </div>

  <div class="section" id="trader-detail-section">
    <h2>Trader Detail — PnL &amp; Inventory</h2>
    <p class="hint">
      <b>MTM PnL</b> = cash from trades + position × current mid price (solid line).
      <b>Cash flow</b> = raw cash from fills only, no MTM adjustment (dotted line).
      Net buyers show negative cash flow; net sellers show positive.
    </p>
    {trader_tab_bar}
    <div id="trader-panels">{trader_panels}</div>
  </div>

</div>

<script>
{JS_TABS}

{js_prod_fns}

{js_trader_fns}

(function() {{
  if ('{first_prod_safe}')   showProductPanel('{first_prod_safe}');
  if ('{first_trader_safe}') showTraderPanel('{first_trader_safe}');
}})();
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path} ({output_path.stat().st_size:,} bytes)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Counterparty analysis HTML report (Round 4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--prices", nargs="+", required=True,
                        help="Prices CSV file(s), one per day in chronological order")
    parser.add_argument("--trades", nargs="+", required=True,
                        help="Trades CSV file(s), matching the prices files")
    parser.add_argument("--product", default=None,
                        help="Filter to a single product symbol (default: all)")
    parser.add_argument("--out", default=None,
                        help="Output HTML path (default: auto-derived from first prices file)")
    args = parser.parse_args()

    price_paths = [ROOT / p if not Path(p).is_absolute() else Path(p) for p in args.prices]
    trade_paths = [ROOT / t if not Path(t).is_absolute() else Path(t) for t in args.trades]

    if len(price_paths) != len(trade_paths):
        print("ERROR: --prices and --trades must have the same number of files")
        sys.exit(1)

    print("Computing timestamp offsets ...")
    ts_offsets = _compute_ts_offsets(price_paths)

    print("Loading prices ...")
    products, market_by_prod = _load_prices(price_paths)
    print(f"  Products: {products}")

    print("Loading trades ...")
    all_fills = _load_trades(trade_paths, ts_offsets)
    print(f"  {len(all_fills)} fill records")

    print("Building analysis ...")
    data = _build_data(products, market_by_prod, all_fills, args.product)
    print(f"  Traders: {data['traders']}")

    if args.out:
        out_path = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    else:
        stem = price_paths[0].stem.replace("prices_", "")
        prod_tag = f"_{args.product}" if args.product else ""
        out_path = ROOT / f"artifacts/analysis/round_4/{stem}{prod_tag}_counterparties.html"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    title_parts = []
    if args.product:
        title_parts.append(args.product)
    title_parts += [p.stem for p in price_paths]
    title = " | ".join(title_parts)

    print("Generating HTML ...")
    generate_html(data, out_path, title)
    print("Done.")


if __name__ == "__main__":
    main()
