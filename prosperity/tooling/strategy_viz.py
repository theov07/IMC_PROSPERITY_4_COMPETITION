"""Strategy visualization HTML report.

Generates a self-contained interactive HTML for post-hoc strategy analysis.
Works with the backtest JSON output (primary) and optionally an IMC log file.

Market price data and other-traders' fills are auto-loaded from the data/
directory using the round + day metadata embedded in the backtest JSON.

Charts per product:
  1. Price  — market bid/ask/mid · ±1σ/±2σ bands (from ZsMean+ZsStd features)
               · our submitted quotes (step lines) · our fills (★ taker / ● maker)
               · other traders' fills (coloured by trader)
  2. Z-score — rolling z-score (from feature_ticks) with ±1/±2 reference lines
  3. Position — our inventory over time
  4. PnL      — equity curve

Usage:
    # backtest JSON only (market data auto-loaded from data/)
    python -m prosperity.tooling.strategy_viz \\
        --backtest-json artifacts/backtest_results/round_4/hydro_mv_v1.json

    # with IMC log file (richer quote/feature data from live run)
    python -m prosperity.tooling.strategy_viz \\
        --backtest-json artifacts/backtest_results/round_4/hydro_mv_v1.json \\
        --log logs/round_4/tibo/hydro_mv_v1.log

    # single product
    python -m prosperity.tooling.strategy_viz \\
        --backtest-json artifacts/backtest_results/round_4/hydro_mv_v1.json \\
        --product HYDROGEL_PACK \\
        --out artifacts/viz/hydro_mv_v1.html
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

# ── Colour palette ─────────────────────────────────────────────────────────────

_TRADER_COLORS = [
    "#74c7ec", "#a6e3a1", "#fab387", "#cba6f7", "#f9e2af",
    "#89dceb", "#f2cdcd", "#b4befe", "#94e2d5", "#eba0ac",
    "#89b4fa", "#a6adc8",
]
_TRADER_COLORS_DARK = [
    "#1e6090", "#1a5c23", "#8a3e0a", "#4a1d7c", "#7a5800",
    "#0a6c7c", "#8c2a2a", "#1a2d7c", "#0a5c4a", "#7c1a2a",
    "#1a3c7c", "#3a3d5c",
]

# ── Utilities ──────────────────────────────────────────────────────────────────

def _jsid(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", str(name))


def _to_float(s) -> Optional[float]:
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def _to_int(s) -> Optional[int]:
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


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


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_backtest_json(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw


def _max_ts_in_price_csv(path: Path) -> int:
    max_ts = 0
    if not path.exists():
        return 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            ts = _to_int(row.get("timestamp", ""))
            if ts is not None:
                max_ts = max(max_ts, ts)
    return max_ts


def _load_market_prices(round_num: int, days: List[str], data_dir: Path) -> Dict[str, Any]:
    """Load market price CSVs and return per-product time series with multi-day offsets."""
    rows_by_prod: Dict[str, List[Tuple[int, Any, Any, Any]]] = defaultdict(list)
    ts_offset = 0
    for day in days:
        price_path = data_dir / f"prices_round_{round_num}_day_{day}.csv"
        if not price_path.exists():
            print(f"  Warning: {price_path} not found")
            continue
        max_ts = 0
        with open(price_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                prod = row.get("product", "").strip()
                ts   = _to_int(row.get("timestamp", ""))
                if ts is None or not prod:
                    continue
                max_ts = max(max_ts, ts)
                rows_by_prod[prod].append((
                    ts + ts_offset,
                    _to_float(row.get("bid_price_1", "")),
                    _to_float(row.get("ask_price_1", "")),
                    _to_float(row.get("mid_price", "")),
                ))
        ts_offset += max_ts + 100

    result: Dict[str, Any] = {}
    for prod, rows in rows_by_prod.items():
        rows.sort(key=lambda x: x[0])
        result[prod] = {
            "ts":   [r[0] for r in rows],
            "bid1": [r[1] for r in rows],
            "ask1": [r[2] for r in rows],
            "mid":  [r[3] for r in rows],
        }
    return result


def _load_market_trades(
    round_num: int, days: List[str], data_dir: Path,
) -> Tuple[List[Dict], List[int]]:
    """Load market trade CSVs. Returns (fills, ts_offsets)."""
    fills: List[Dict] = []
    ts_offset = 0
    offsets: List[int] = []
    for day in days:
        offsets.append(ts_offset)
        price_path = data_dir / f"prices_round_{round_num}_day_{day}.csv"
        trade_path = data_dir / f"trades_round_{round_num}_day_{day}.csv"
        day_max_ts = _max_ts_in_price_csv(price_path)
        if trade_path.exists():
            with open(trade_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f, delimiter=";"):
                    ts  = _to_int(row.get("timestamp", ""))
                    px  = _to_float(row.get("price", ""))
                    qty = _to_int(row.get("quantity", ""))
                    if ts is None or px is None or qty is None:
                        continue
                    fills.append({
                        "ts":     ts + ts_offset,
                        "buyer":  (row.get("buyer",  "") or "").strip() or "?",
                        "seller": (row.get("seller", "") or "").strip() or "?",
                        "symbol": (row.get("symbol", "") or row.get("product", "") or "").strip(),
                        "px": px, "qty": qty,
                    })
        ts_offset += day_max_ts + 100
    return sorted(fills, key=lambda x: x["ts"]), offsets


def _merge_backtest_fills(
    bt_days: List[Dict], round_num: int, days: List[str], data_dir: Path,
) -> List[Dict]:
    """Convert backtest fills into the same format as market trades, with day offsets."""
    ts_offsets: Dict[str, int] = {}
    ts_offset = 0
    for day in days:
        ts_offsets[str(day)] = ts_offset
        price_path = data_dir / f"prices_round_{round_num}_day_{day}.csv"
        ts_offsets[str(day)] = ts_offset
        ts_offset += _max_ts_in_price_csv(price_path) + 100

    our_fills: List[Dict] = []
    for day_data in bt_days:
        day = str(day_data.get("day", ""))
        offset = ts_offsets.get(day, 0)
        for f in day_data.get("fills", []):
            our_fills.append({
                "ts":         f["timestamp"] + offset,
                "symbol":     f["symbol"],
                "side":       f["side"],
                "price":      f["price"],
                "qty":        f["quantity"],
                "aggressive": f.get("aggressive", False),
                "gap_exploit": f.get("gap_exploit", False),
            })
    return sorted(our_fills, key=lambda x: x["ts"])


def _merge_quotes(bt_days: List[Dict], round_num: int, days: List[str], data_dir: Path) -> List[Dict]:
    """Convert backtest quotes with day offsets."""
    ts_offsets = _build_day_offsets(round_num, days, data_dir)
    result: List[Dict] = []
    for day_data in bt_days:
        offset = ts_offsets.get(str(day_data.get("day", "")), 0)
        for q in day_data.get("quotes", []):
            result.append({
                "ts":       q["timestamp"] + offset,
                "symbol":   q["symbol"],
                "bid":      q.get("bid"),
                "ask":      q.get("ask"),
                "bid_size": q.get("bid_size", 0),
                "ask_size": q.get("ask_size", 0),
            })
    return sorted(result, key=lambda x: x["ts"])


def _merge_features(bt_days: List[Dict], round_num: int, days: List[str], data_dir: Path) -> List[Dict]:
    """Convert backtest feature_ticks with day offsets."""
    ts_offsets = _build_day_offsets(round_num, days, data_dir)
    result: List[Dict] = []
    for day_data in bt_days:
        offset = ts_offsets.get(str(day_data.get("day", "")), 0)
        for ft in day_data.get("feature_ticks", []):
            result.append({
                **ft,
                "timestamp": ft["timestamp"] + offset,
            })
    return sorted(result, key=lambda x: x["timestamp"])


def _merge_equity(bt_days: List[Dict], round_num: int, days: List[str], data_dir: Path) -> Dict[str, List]:
    """Merge equity curves across days, per product."""
    ts_offsets = _build_day_offsets(round_num, days, data_dir)
    ts: List[int] = []
    pnl: List[float] = []
    pnl_carry = 0.0
    for day_data in bt_days:
        offset = ts_offsets.get(str(day_data.get("day", "")), 0)
        curve = day_data.get("equity_curve", [])
        if curve:
            for t, v in curve:
                ts.append(t + offset)
                pnl.append(v + pnl_carry)
            pnl_carry += day_data.get("pnl", 0.0)
    return {"ts": ts, "pnl": pnl}


def _build_day_offsets(round_num: int, days: List[str], data_dir: Path) -> Dict[str, int]:
    offsets: Dict[str, int] = {}
    ts_offset = 0
    for day in days:
        offsets[str(day)] = ts_offset
        price_path = data_dir / f"prices_round_{round_num}_day_{day}.csv"
        ts_offset += _max_ts_in_price_csv(price_path) + 100
    return offsets


# ── Optional: parse IMC log file ───────────────────────────────────────────────

def _parse_imclog(path: Path) -> Optional[Dict[str, Any]]:
    """Parse an official IMC .log JSON file.

    Returns dict with keys:
      market_prices  — same shape as _load_market_prices
      own_trades     — list of {ts, symbol, side, price, qty}
      quote_traces   — list of {timestamp, product, bid_price, ask_price, **extras}
      taker_fills    — list of {ts, product, side, price, qty, gap_exploit}
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  Warning: could not parse log {path}: {e}")
        return None

    # ── activitiesLog: market prices ──────────────────────────────────────
    activities_text = (
        raw.get("activitiesLog")
        or raw.get("activityLog")
        or raw.get("activities")
        or ""
    )
    rows_by_prod: Dict[str, List[Tuple]] = defaultdict(list)
    if activities_text:
        reader = csv.DictReader(
            activities_text.strip().splitlines(), delimiter=";"
        )
        for row in reader:
            prod = (row.get("product") or "").strip()
            ts   = _to_int(row.get("timestamp", ""))
            if not prod or ts is None:
                continue
            rows_by_prod[prod].append((
                ts,
                _to_float(row.get("bid_price_1", "")),
                _to_float(row.get("ask_price_1", "")),
                _to_float(row.get("mid_price", "")),
            ))
    market_prices: Dict[str, Any] = {}
    for prod, rows in rows_by_prod.items():
        rows.sort(key=lambda x: x[0])
        market_prices[prod] = {
            "ts":   [r[0] for r in rows],
            "bid1": [r[1] for r in rows],
            "ask1": [r[2] for r in rows],
            "mid":  [r[3] for r in rows],
        }

    # ── tradeHistory: own trades ──────────────────────────────────────────
    trade_text = (
        raw.get("tradeHistory")
        or raw.get("tradeLog")
        or ""
    )
    own_trades: List[Dict] = []
    if trade_text:
        reader = csv.DictReader(trade_text.strip().splitlines(), delimiter=";")
        for row in reader:
            ts    = _to_int(row.get("timestamp", ""))
            px    = _to_float(row.get("price", ""))
            qty   = _to_int(row.get("quantity", ""))
            buyer  = (row.get("buyer",  "") or "").strip()
            seller = (row.get("seller", "") or "").strip()
            sym    = (row.get("symbol", "") or row.get("product", "") or "").strip()
            if ts is None or px is None or qty is None:
                continue
            if buyer == "SUBMISSION":
                own_trades.append({"ts": ts, "symbol": sym, "side": "BUY",
                                   "price": px, "qty": qty})
            elif seller == "SUBMISSION":
                own_trades.append({"ts": ts, "symbol": sym, "side": "SELL",
                                   "price": px, "qty": qty})

    # ── lambdaLog: quote_trace + taker_fills ──────────────────────────────
    runtime_logs = raw.get("logs", [])
    quote_traces: List[Dict] = []
    taker_fills_log: List[Dict] = []

    decoder = json.JSONDecoder()
    for entry in runtime_logs:
        text = str(entry.get("lambdaLog", "") or "").strip()
        if not text:
            continue
        pos = 0
        while pos < len(text):
            while pos < len(text) and text[pos] in " \t\r\n":
                pos += 1
            if pos >= len(text):
                break
            try:
                obj, consumed = decoder.raw_decode(text, pos)
                pos += consumed
            except json.JSONDecodeError:
                nxt = text.find("{", pos + 1)
                if nxt == -1:
                    break
                pos = nxt
                continue
            if not isinstance(obj, dict):
                continue
            product = obj.get("product")
            if not product:
                continue
            trace = obj.get("trace")

            if trace == "taker_fills" or trace is None and "log" in obj:
                if trace == "taker_fills":
                    for entry_row in obj.get("log", []):
                        if len(entry_row) >= 4:
                            taker_fills_log.append({
                                "ts": entry_row[0], "product": product,
                                "side": entry_row[1], "price": entry_row[2],
                                "qty": entry_row[3],
                                "gap_exploit": len(entry_row) > 4 and entry_row[4] == 1,
                            })

            if trace == "quote_trace" or trace is None:
                columns = obj.get("columns")
                for tick in obj.get("log", []):
                    if not isinstance(columns, list) or len(tick) < 3:
                        continue
                    mapped = {str(col): (tick[i] if i < len(tick) else None)
                              for i, col in enumerate(columns)}
                    ts_val = _to_int(mapped.get("timestamp"))
                    bp     = mapped.get("bid_price")
                    ap     = mapped.get("ask_price")
                    if ts_val is None:
                        continue
                    row_data: Dict[str, Any] = {
                        "timestamp": ts_val,
                        "product":   product,
                        "bid_price": bp,
                        "ask_price": ap,
                    }
                    for k, v in mapped.items():
                        if k not in ("timestamp", "bid_price", "ask_price"):
                            row_data[k] = v
                    quote_traces.append(row_data)

    return {
        "market_prices": market_prices,
        "own_trades":    own_trades,
        "quote_traces":  quote_traces,
        "taker_fills":   taker_fills_log,
    }


# ── Feature helpers ────────────────────────────────────────────────────────────

def _sigma_bands_from_features(
    features: List[Dict], product: str,
) -> Dict[str, Any]:
    """Extract ±1σ/±2σ price bands from ZsMean + ZsStd in feature_ticks."""
    ts, mean, s1u, s1d, s2u, s2d, mid_smooth, z_vals = [], [], [], [], [], [], [], []
    for ft in features:
        if ft.get("symbol") != product:
            continue
        mu = _to_float(ft.get("ZsMean"))
        sd = _to_float(ft.get("ZsStd"))
        ms = _to_float(ft.get("MidSmooth"))
        zv = _to_float(ft.get("Z"))
        if mu is None or sd is None:
            continue
        ts.append(ft["timestamp"])
        mean.append(mu)
        s1u.append(mu + sd)
        s1d.append(mu - sd)
        s2u.append(mu + 2 * sd)
        s2d.append(mu - 2 * sd)
        mid_smooth.append(ms)
        z_vals.append(zv)
    return {"ts": ts, "mean": mean, "s1u": s1u, "s1d": s1d,
            "s2u": s2u, "s2d": s2d, "mid_smooth": mid_smooth, "z": z_vals}


def _position_curve(our_fills: List[Dict], product: str) -> Tuple[List[int], List[int]]:
    """Compute position over time from fills (sorted by ts)."""
    events = sorted(
        [f for f in our_fills if f.get("symbol") == product],
        key=lambda x: x["ts"],
    )
    ts_list, pos_list = [], []
    pos = 0
    for f in events:
        sign = 1 if f.get("side") == "BUY" else -1
        pos += sign * f.get("qty", f.get("quantity", 0))
        ts_list.append(f["ts"])
        pos_list.append(pos)
    return ts_list, pos_list


# ── Plotly layout ──────────────────────────────────────────────────────────────

def _layout_js(extra: str = "") -> str:
    return """{
        plot_bgcolor: '#1e1e2e', paper_bgcolor: '#1e1e2e',
        font: {color: '#cdd6f4', size: 11},
        legend: {bgcolor: 'rgba(0,0,0,0)', font: {size: 10}},
        xaxis: {gridcolor: '#313244', title: 'timestamp'},
        yaxis: {gridcolor: '#313244'},
        margin: {t: 36, b: 44, l: 65, r: 20},
        hovermode: 'x unified',
    """ + extra + "}"


# ── Chart JS functions ─────────────────────────────────────────────────────────

def _price_chart_js(
    product: str,
    market: Dict,         # {ts, bid1, ask1, mid}
    our_fills: List[Dict],
    quotes: List[Dict],
    sigma_bands: Dict,
    market_trades: List[Dict],
    trader_index: Dict[str, int],
) -> str:
    safe = _jsid(product)
    step = 10
    ts_s   = market["ts"][::step]
    bid_s  = market["bid1"][::step]
    ask_s  = market["ask1"][::step]
    mid_s  = market["mid"][::step]

    traces: List[str] = [
        f"""{{x:{_json_list(ts_s)},y:{_json_list(bid_s)},name:'Best Bid',mode:'lines',
      line:{{color:'#89b4fa',width:1.5}},hovertemplate:'Bid: %{{y}}<extra></extra>'}}""",
        f"""{{x:{_json_list(ts_s)},y:{_json_list(ask_s)},name:'Best Ask',mode:'lines',
      line:{{color:'#f38ba8',width:1.5}},hovertemplate:'Ask: %{{y}}<extra></extra>'}}""",
        f"""{{x:{_json_list(ts_s)},y:{_json_list(mid_s)},name:'Mid',mode:'lines',
      line:{{color:'#cdd6f4',width:1,opacity:0.5}},hovertemplate:'Mid: %{{y}}<extra></extra>'}}""",
    ]

    # σ bands
    if sigma_bands["ts"]:
        zts = _json_list(sigma_bands["ts"])
        ms  = _json_list(sigma_bands["mid_smooth"])
        traces += [
            f"""{{x:{zts},y:{_json_list(sigma_bands['s2u'])},name:'+2σ',mode:'lines',
          line:{{color:'#6c7086',width:1,dash:'dot'}},hovertemplate:'+2σ: %{{y}}<extra></extra>'}}""",
            f"""{{x:{zts},y:{_json_list(sigma_bands['s2d'])},name:'-2σ',mode:'lines',
          line:{{color:'#6c7086',width:1,dash:'dot'}},hovertemplate:'-2σ: %{{y}}<extra></extra>'}}""",
            f"""{{x:{zts},y:{_json_list(sigma_bands['s1u'])},name:'+1σ',mode:'lines',
          line:{{color:'#9399b2',width:1,dash:'dash'}},hovertemplate:'+1σ: %{{y}}<extra></extra>'}}""",
            f"""{{x:{zts},y:{_json_list(sigma_bands['s1d'])},name:'-1σ',mode:'lines',
          line:{{color:'#9399b2',width:1,dash:'dash'}},hovertemplate:'-1σ: %{{y}}<extra></extra>'}}""",
            f"""{{x:{zts},y:{_json_list(sigma_bands['mean'])},name:'Rolling μ',mode:'lines',
          line:{{color:'#a6adc8',width:1,dash:'longdash'}},hovertemplate:'μ: %{{y}}<extra></extra>'}}""",
            f"""{{x:{zts},y:{ms},name:'MidSmooth',mode:'lines',
          line:{{color:'#f9e2af',width:1}},hovertemplate:'MidSmooth: %{{y}}<extra></extra>'}}""",
        ]

    # Our submitted quotes as step lines
    q_prod = [q for q in quotes if q.get("symbol") == product]
    if q_prod:
        q_ts  = [q["ts"]  for q in q_prod]
        q_bid = [q["bid"] for q in q_prod]
        q_ask = [q["ask"] for q in q_prod]
        traces += [
            f"""{{x:{json.dumps(q_ts)},y:{json.dumps(q_bid)},name:'Our Bid',mode:'lines',
          line:{{color:'#74c7ec',width:1,dash:'dot'}},
          hovertemplate:'Our Bid: %{{y}}<extra></extra>'}}""",
            f"""{{x:{json.dumps(q_ts)},y:{json.dumps(q_ask)},name:'Our Ask',mode:'lines',
          line:{{color:'#f38ba8',width:1,dash:'dot'}},
          hovertemplate:'Our Ask: %{{y}}<extra></extra>'}}""",
        ]

    # Our fills — all shown as taker (star); backtest's aggressive flag is
    # unreliable for taker-only strategies (fill model artefact).
    our_prod   = [f for f in our_fills if f.get("symbol") == product]
    our_buys   = [f for f in our_prod if f.get("side") == "BUY"]
    our_sells  = [f for f in our_prod if f.get("side") == "SELL"]

    def _fill_trace(fills, color, symbol, name):
        if not fills:
            return None
        qtys = [f.get("qty", f.get("quantity", 0)) for f in fills]
        return (f"""{{x:{json.dumps([f['ts'] for f in fills])},
          y:{json.dumps([f['price'] for f in fills])},
          name:'{name}',mode:'markers',
          marker:{{symbol:'{symbol}',color:'{color}',size:11,opacity:0.95,
                   line:{{color:'#1e1e2e',width:0.8}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{name}</b> qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")

    for tr, col, sym, nm in [
        (our_buys,  "#a6e3a1", "star", "OUR BUY"),
        (our_sells, "#f38ba8", "star", "OUR SELL"),
    ]:
        t = _fill_trace(tr, col, sym, nm)
        if t:
            traces.append(t)

    # Other traders' fills
    mkt_prod = [f for f in market_trades if f.get("symbol") == product]
    all_traders = sorted({f["buyer"] for f in mkt_prod} | {f["seller"] for f in mkt_prod})
    all_traders = [t for t in all_traders if t not in ("?", "SUBMISSION")]
    for trader in all_traders:
        idx = trader_index.get(trader, 0)
        bc  = _TRADER_COLORS[idx % len(_TRADER_COLORS)]
        sc  = _TRADER_COLORS_DARK[idx % len(_TRADER_COLORS_DARK)]
        buys  = [f for f in mkt_prod if f["buyer"]  == trader]
        sells = [f for f in mkt_prod if f["seller"] == trader]
        if buys:
            qtys = [f["qty"] for f in buys]
            traces.append(f"""{{
          x:{json.dumps([f['ts'] for f in buys])},
          y:{json.dumps([f['px'] for f in buys])},
          name:'{trader} buy',mode:'markers',
          marker:{{symbol:'square',color:'{bc}',size:7,opacity:0.8,
                   line:{{color:'#1e1e2e',width:0.4}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{trader}</b> BUY qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")
        if sells:
            qtys = [f["qty"] for f in sells]
            traces.append(f"""{{
          x:{json.dumps([f['ts'] for f in sells])},
          y:{json.dumps([f['px'] for f in sells])},
          name:'{trader} sell',mode:'markers',
          marker:{{symbol:'square-open',color:'{sc}',size:7,opacity:0.8,
                   line:{{color:'{sc}',width:1.2}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{trader}</b> SELL qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")

    traces_js = ",\n    ".join(traces)
    return f"""
  function plot_price_{safe}() {{
    var layout = Object.assign({{}}, {_layout_js()}, {{
      title: '{product} — Price + Fills',
      legend: {{bgcolor:'rgba(0,0,0,0)',font:{{size:9}},x:1.01,xanchor:'left'}},
      yaxis: {{title:'price',gridcolor:'#313244'}},
      margin: {{t:36,b:44,l:65,r:200}},
    }});
    Plotly.newPlot('price_{safe}', [{traces_js}], layout, {{responsive:true}});
  }}"""


def _zscore_chart_js(product: str, sigma_bands: Dict) -> str:
    safe = _jsid(product)
    if not sigma_bands["ts"]:
        return f"""
  function plot_z_{safe}() {{
    document.getElementById('z_{safe}').innerHTML =
      '<p style="color:#6c7086;padding:1em">No z-score features available.</p>';
  }}"""
    ref_lines = """
      {type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:0,y1:0,line:{color:'#cdd6f4',width:1}},
      {type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:1,y1:1,line:{color:'#9399b2',width:1,dash:'dash'}},
      {type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:-1,y1:-1,line:{color:'#9399b2',width:1,dash:'dash'}},
      {type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:2,y1:2,line:{color:'#6c7086',width:1,dash:'dot'}},
      {type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:-2,y1:-2,line:{color:'#6c7086',width:1,dash:'dot'}},"""
    zts = _json_list(sigma_bands["ts"])
    zv  = _json_list(sigma_bands["z"])
    return f"""
  function plot_z_{safe}() {{
    Plotly.newPlot('z_{safe}', [{{
      x:{zts},y:{zv},name:'z-score',mode:'lines',
      line:{{color:'#cba6f7',width:1.5}},
      hovertemplate:'z: %{{y:.2f}}<extra></extra>'
    }}], Object.assign({{}},{_layout_js()},{{
      title:'{product} — Rolling Z-score',
      yaxis:{{title:'z-score',gridcolor:'#313244',zeroline:false}},
      shapes:[{ref_lines}],
      margin:{{t:30,b:36,l:55,r:20}},
    }}), {{responsive:true}});
  }}"""


def _position_chart_js(product: str, our_fills: List[Dict]) -> str:
    safe = _jsid(product)
    ts_list, pos_list = _position_curve(our_fills, product)
    if not ts_list:
        return f"""
  function plot_pos_{safe}() {{
    document.getElementById('pos_{safe}').innerHTML =
      '<p style="color:#6c7086;padding:1em">No fills for {product}.</p>';
  }}"""
    return f"""
  function plot_pos_{safe}() {{
    Plotly.newPlot('pos_{safe}',[{{
      x:{json.dumps(ts_list)},y:{json.dumps(pos_list)},
      name:'position',mode:'lines',fill:'tozeroy',
      line:{{color:'#a6e3a1',width:1.5}},
      hovertemplate:'pos: %{{y}}<extra></extra>'
    }}], Object.assign({{}},{_layout_js()},{{
      title:'{product} — Position',
      yaxis:{{title:'units',gridcolor:'#313244',zeroline:true}},
      margin:{{t:30,b:36,l:55,r:20}},
    }}),{{responsive:true}});
  }}"""


def _pnl_chart_js(equity: Dict) -> str:
    if not equity["ts"]:
        return "function plot_pnl() {}"
    return f"""
  function plot_pnl() {{
    Plotly.newPlot('pnl_chart',[{{
      x:{json.dumps(equity['ts'])},y:{_json_list(equity['pnl'])},
      name:'PnL',mode:'lines',fill:'tozeroy',
      line:{{color:'#cba6f7',width:2}},
      hovertemplate:'PnL: %{{y:,.0f}}<extra></extra>'
    }}], Object.assign({{}},{_layout_js()},{{
      title:'Portfolio Equity Curve',
      yaxis:{{title:'PnL (SeaShells)',gridcolor:'#313244',zeroline:true}},
      margin:{{t:30,b:36,l:75,r:20}},
    }}),{{responsive:true}});
  }}"""


# ── CSS + JS tabs ──────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'JetBrains Mono', monospace, sans-serif;
       background: #1e1e2e; color: #cdd6f4; }
h2 { color: #cba6f7; margin: 1em 0 0.5em; }
h3 { color: #89dceb; margin: 0.6em 0 0.3em; font-size: 1em; }
.container { max-width: 1800px; margin: 0 auto; padding: 1em 2em; }
.section { margin-bottom: 2.5em; }
.hint { color: #6c7086; font-size: 0.78em; margin-bottom: 0.6em; }
.tab-bar { display:flex; flex-wrap:wrap; gap:6px; margin:0.8em 0; }
.tab-btn {
  padding:5px 13px; border:1px solid #45475a; border-radius:6px;
  background:#313244; color:#cdd6f4; cursor:pointer; font-size:0.82em;
  transition:background 0.15s;
}
.tab-btn:hover { background:#45475a; }
.tab-btn.active { background:#45475a; border-color:#cba6f7; color:#cba6f7; font-weight:bold; }
.chart-container { margin-bottom:1em; border-radius:8px; overflow:hidden; }
.chart-tall  { height:520px; }
.chart-med   { height:220px; }
.chart-short { height:180px; }
.product-panel { display:none; }
.stat-row { display:flex; flex-wrap:wrap; gap:1.5em; margin:0.5em 0 1em; font-size:0.82em; }
.stat { color:#a6adc8; }
.stat b { color:#cdd6f4; }
"""

JS_TABS = """
function showProductPanel(safe) {
  document.querySelectorAll('.product-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.prod-tab-btn').forEach(b => b.classList.remove('active'));
  var panel = document.getElementById('prod_panel_' + safe);
  if (panel) panel.style.display = 'block';
  var btn = document.getElementById('prod_btn_' + safe);
  if (btn) btn.classList.add('active');
  if (panel && !panel.dataset.plotted) {
    ['plot_price_','plot_z_','plot_pos_'].forEach(fn => {
      var f = window[fn + safe]; if (f) f();
    });
    var pnl = window['plot_pnl']; if (pnl && !window['_pnl_plotted']) { pnl(); window['_pnl_plotted']=1; }
    panel.dataset.plotted = '1';
  }
}
"""


# ── HTML assembly ──────────────────────────────────────────────────────────────

def generate_html(
    bt: Dict,
    market_prices: Dict[str, Any],
    market_trades: List[Dict],
    our_fills: List[Dict],
    quotes: List[Dict],
    features: List[Dict],
    equity: Dict,
    output_path: Path,
    title: str = "",
    product_filter: Optional[str] = None,
) -> None:
    products = sorted(market_prices.keys())
    if product_filter:
        products = [p for p in products if p == product_filter]

    # Trader index for consistent colours
    all_traders = sorted({f["buyer"] for f in market_trades}
                         | {f["seller"] for f in market_trades}
                         - {"?", "SUBMISSION"})
    trader_index = {t: i for i, t in enumerate(all_traders)}

    # ── summary stats ─────────────────────────────────────────────────────────
    total_pnl = bt.get("summary", {}).get("total_pnl", equity["pnl"][-1] if equity["pnl"] else 0)
    n_fills = len(our_fills)
    strategy_name = bt.get("strategy", "")

    stats_html = f"""<div class="stat-row">
  <span class="stat">Strategy: <b>{strategy_name}</b></span>
  <span class="stat">Total PnL: <b>{total_pnl:,.0f}</b></span>
  <span class="stat">Our fills: <b>{n_fills}</b></span>
  <span class="stat">Market participants: <b>{len(all_traders)}</b></span>
</div>"""

    # ── product panels ────────────────────────────────────────────────────────
    tab_bar  = '<div class="tab-bar">'
    panels   = ""
    js_fns   = ""
    first_safe = ""

    for prod in products:
        safe = _jsid(prod)
        if not first_safe:
            first_safe = safe
        tab_bar += (
            f'<button class="prod-tab-btn tab-btn" id="prod_btn_{safe}"'
            f' onclick="showProductPanel(\'{safe}\')">{prod}</button>'
        )

        sigma_bands = _sigma_bands_from_features(features, prod)
        prod_fills  = [f for f in our_fills if f.get("symbol") == prod]
        prod_quotes = [q for q in quotes   if q.get("symbol") == prod]
        prod_mkt    = market_prices.get(prod, {"ts": [], "bid1": [], "ask1": [], "mid": []})

        # Stats for this product
        prod_pnl = 0.0
        for day_data in bt.get("days", []):
            prod_pnl += (day_data.get("product_summaries", {})
                         .get(prod, {}).get("pnl", 0.0))
        n_prod_fills = len(prod_fills)

        panels += f"""
<div id="prod_panel_{safe}" class="product-panel">
  <div class="stat-row">
    <span class="stat">Product PnL: <b>{prod_pnl:,.0f}</b></span>
    <span class="stat">Fills: <b>{n_prod_fills}</b></span>
  </div>
  <div class="chart-container"><div id="price_{safe}" class="chart-tall"></div></div>
  <div class="chart-container"><div id="z_{safe}"     class="chart-short"></div></div>
  <div class="chart-container"><div id="pos_{safe}"   class="chart-med"></div></div>
</div>"""

        js_fns += _price_chart_js(prod, prod_mkt, our_fills, prod_quotes,
                                   sigma_bands, market_trades, trader_index)
        js_fns += _zscore_chart_js(prod, sigma_bands)
        js_fns += _position_chart_js(prod, our_fills)

    tab_bar += "</div>"
    js_fns  += _pnl_chart_js(equity)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Strategy Viz — {title}</title>
  <script src="{_PLOTLY_CDN}"></script>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <h2 style="font-size:1.4em;margin-top:1em">Strategy Visualization — {title}</h2>
  {stats_html}

  <div class="section">
    <h2>Portfolio PnL</h2>
    <div class="chart-container"><div id="pnl_chart" class="chart-med"></div></div>
  </div>

  <div class="section">
    <h2>Per-product Analysis</h2>
    <p class="hint">
      ★ = our fill (buy green / sell red) &nbsp;|&nbsp;
      ■ = other trader buy &nbsp;|&nbsp; □ = other trader sell
    </p>
    {tab_bar}
    {panels}
  </div>
</div>
<script>
{JS_TABS}
{js_fns}
(function() {{
  if ('{first_safe}') showProductPanel('{first_safe}');
}})();
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path} ({output_path.stat().st_size:,} bytes)")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strategy visualization HTML (backtest JSON + optional IMC log)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--backtest-json", required=True,
                        help="Path to backtest JSON (from --json-out)")
    parser.add_argument("--log", default=None,
                        help="Path to IMC log file (optional, enriches data)")
    parser.add_argument("--product", default=None,
                        help="Filter to a single product symbol")
    parser.add_argument("--out", default=None,
                        help="Output HTML path (default: auto-derived)")
    parser.add_argument("--data-dir", default=None,
                        help="Root data directory (default: data/)")
    args = parser.parse_args()

    bt_path  = ROOT / args.backtest_json if not Path(args.backtest_json).is_absolute() else Path(args.backtest_json)
    data_dir = Path(args.data_dir) if args.data_dir else ROOT / "data"

    print("Loading backtest JSON ...")
    bt = _load_backtest_json(bt_path)
    round_num = int(bt.get("round", 0))
    days      = [str(d["day"]) for d in bt.get("days", [])]
    print(f"  Round {round_num}, days: {days}")

    print("Loading market data ...")
    market_prices = _load_market_prices(round_num, days, data_dir / f"round_{round_num}")
    market_trades, _ = _load_market_trades(round_num, days, data_dir / f"round_{round_num}")
    print(f"  Products: {sorted(market_prices.keys())}")
    print(f"  Market trades: {len(market_trades)}")

    print("Processing backtest data ...")
    our_fills = _merge_backtest_fills(bt.get("days", []), round_num, days,
                                      data_dir / f"round_{round_num}")
    quotes    = _merge_quotes(bt.get("days", []), round_num, days,
                              data_dir / f"round_{round_num}")
    features  = _merge_features(bt.get("days", []), round_num, days,
                                data_dir / f"round_{round_num}")
    equity    = _merge_equity(bt.get("days", []), round_num, days,
                              data_dir / f"round_{round_num}")
    print(f"  Our fills: {len(our_fills)}, quotes: {len(quotes)}, feature ticks: {len(features)}")

    # Optional: enrich from log file
    if args.log:
        log_path = ROOT / args.log if not Path(args.log).is_absolute() else Path(args.log)
        print(f"Parsing IMC log {log_path} ...")
        log_data = _parse_imclog(log_path)
        if log_data:
            if log_data["market_prices"]:
                print("  Using market prices from log")
                market_prices = log_data["market_prices"]
            if log_data["taker_fills"]:
                print(f"  Found {len(log_data['taker_fills'])} taker fill entries in log")
            if log_data["quote_traces"]:
                print(f"  Found {len(log_data['quote_traces'])} quote trace entries in log")
                # Override quotes + features with richer log data
                quotes = [{"ts": q["timestamp"], "symbol": q["product"],
                           "bid": q.get("bid_price"), "ask": q.get("ask_price"),
                           "bid_size": 0, "ask_size": 0}
                          for q in log_data["quote_traces"]]
                # Rebuild features from quote_traces (they contain all extras)
                features = []
                for q in log_data["quote_traces"]:
                    feat: Dict[str, Any] = {"timestamp": q["timestamp"], "symbol": q["product"]}
                    for k in ("zscore", "Z", "ZsMean", "ZsStd", "MidSmooth", "M14Signal",
                              "MvStateN", "GuardOn", "GuardDist", "GuardTrend"):
                        if k in q:
                            feat[k] = q[k]
                    # normalise key names from quote_trace extras
                    if "zscore" in q: feat["Z"]       = q["zscore"]
                    if "mid_smooth" in q: feat["MidSmooth"] = q["mid_smooth"]
                    features.append(feat)
            if log_data["own_trades"]:
                print(f"  Using {len(log_data['own_trades'])} own trades from log")
                our_fills = [{"ts": t["ts"], "symbol": t["symbol"], "side": t["side"],
                               "price": t["price"], "qty": t["qty"],
                               "aggressive": False, "gap_exploit": False}
                             for t in log_data["own_trades"]]

    if args.out:
        out_path = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    else:
        stem     = bt_path.stem
        prod_tag = f"_{args.product}" if args.product else ""
        out_path = ROOT / f"artifacts/viz/{stem}{prod_tag}.html"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    title_parts = []
    if args.product:
        title_parts.append(args.product)
    title_parts.append(bt.get("strategy", bt_path.stem))
    title = " | ".join(title_parts)

    print("Generating HTML ...")
    generate_html(
        bt=bt,
        market_prices=market_prices,
        market_trades=market_trades,
        our_fills=our_fills,
        quotes=quotes,
        features=features,
        equity=equity,
        output_path=out_path,
        title=title,
        product_filter=args.product,
    )
    print("Done.")


if __name__ == "__main__":
    main()
