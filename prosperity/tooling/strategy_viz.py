"""Strategy visualization HTML report — v2 with v5 MM awareness.

Generates a self-contained interactive HTML for post-hoc strategy analysis.
Works with the backtest JSON output (primary) and optionally an IMC log file.

Auto-detects v5 mode (passive MM + AR taker) when DevSmooth is in feature_ticks,
showing a richer panel:
  1. Price  — market bid/ask/mid · FairValue · FairValue ± taker_edge (entry zone)
               · our submitted quotes (step lines) · taker fills (★) vs maker fills (●)
               · other traders' fills (coloured by trader)
  2. Deviation — DevSmooth over time with ±taker_edge threshold bands
  3. Position + Inventory Bias — position · bid_size · ask_size from quotes
  4. M14 Signal — Mark 14 step chart (+1/−1/0)
  5. PnL — equity curve

Non-v5 strategies show the original layout:
  1. Price + fills + σ bands (ZsMean/ZsStd)
  2. Z-score
  3. Position
  4. PnL

Usage:
    python -m prosperity.tooling.strategy_viz \\
        --backtest-json artifacts/backtest_results/round_4/hydro_mv_v5_best.json

    python -m prosperity.tooling.strategy_viz \\
        --backtest-json artifacts/backtest_results/round_4/hydro_mv_v5_best.json \\
        --ar-taker-edge 12 --product HYDROGEL_PACK
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
    return json.loads(path.read_text(encoding="utf-8"))


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
    rows_by_prod: Dict[str, List[Tuple]] = defaultdict(list)
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


def _build_day_offsets(round_num: int, days: List[str], data_dir: Path) -> Dict[str, int]:
    offsets: Dict[str, int] = {}
    ts_offset = 0
    for day in days:
        offsets[str(day)] = ts_offset
        price_path = data_dir / f"prices_round_{round_num}_day_{day}.csv"
        ts_offset += _max_ts_in_price_csv(price_path) + 100
    return offsets


def _merge_backtest_fills(
    bt_days: List[Dict], round_num: int, days: List[str], data_dir: Path,
) -> List[Dict]:
    ts_offsets = _build_day_offsets(round_num, days, data_dir)
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
                "aggressive": f.get("aggressive", True),
                "gap_exploit": f.get("gap_exploit", False),
            })
    return sorted(our_fills, key=lambda x: x["ts"])


def _merge_quotes(bt_days: List[Dict], round_num: int, days: List[str], data_dir: Path) -> List[Dict]:
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
    ts_offsets = _build_day_offsets(round_num, days, data_dir)
    result: List[Dict] = []
    for day_data in bt_days:
        offset = ts_offsets.get(str(day_data.get("day", "")), 0)
        for ft in day_data.get("feature_ticks", []):
            result.append({**ft, "timestamp": ft["timestamp"] + offset})
    return sorted(result, key=lambda x: x["timestamp"])


def _merge_equity(bt_days: List[Dict], round_num: int, days: List[str], data_dir: Path) -> Dict[str, List]:
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


# ── Feature extraction ────────────────────────────────────────────────────────

def _extract_v5_series(features: List[Dict], quotes: List[Dict], product: str) -> Dict[str, Any]:
    """Extract v5-specific time series from feature_ticks and quotes."""
    # From feature_ticks: FairValue, DevSmooth, M14Signal
    fv_ts, fv_vals, dev_ts, dev_vals, m14_ts, m14_vals = [], [], [], [], [], []
    for ft in features:
        if ft.get("symbol") != product:
            continue
        ts = ft["timestamp"]
        fv = _to_float(ft.get("FairValue"))
        dv = _to_float(ft.get("DevSmooth"))
        m14 = _to_float(ft.get("M14Signal"))
        if fv is not None:
            fv_ts.append(ts);  fv_vals.append(fv)
        if dv is not None:
            dev_ts.append(ts); dev_vals.append(dv)
        if m14 is not None:
            m14_ts.append(ts); m14_vals.append(m14)

    # From quotes: bid_size, ask_size (inventory bias) — subsample every 5th
    qts, q_bid_sz, q_ask_sz = [], [], []
    for i, q in enumerate(quotes):
        if q.get("symbol") != product:
            continue
        if i % 5 != 0:
            continue
        qts.append(q["ts"])
        q_bid_sz.append(q.get("bid_size", 0))
        q_ask_sz.append(q.get("ask_size", 0))

    return {
        "fv_ts":     fv_ts,    "fv":        fv_vals,
        "dev_ts":    dev_ts,   "dev":        dev_vals,
        "m14_ts":    m14_ts,   "m14":        m14_vals,
        "size_ts":   qts,      "bid_size":   q_bid_sz,  "ask_size":  q_ask_sz,
    }


def _sigma_bands_from_features(features: List[Dict], product: str) -> Dict[str, Any]:
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
        mean.append(mu); s1u.append(mu + sd); s1d.append(mu - sd)
        s2u.append(mu + 2 * sd); s2d.append(mu - 2 * sd)
        mid_smooth.append(ms); z_vals.append(zv)
    return {"ts": ts, "mean": mean, "s1u": s1u, "s1d": s1d,
            "s2u": s2u, "s2d": s2d, "mid_smooth": mid_smooth, "z": z_vals}


def _position_curve(
    our_fills: List[Dict], product: str, day_boundaries: Optional[List[int]] = None,
) -> Tuple[List[int], List[int]]:
    """Compute position over time, resetting to 0 at each day boundary."""
    events = sorted(
        [f for f in our_fills if f.get("symbol") == product],
        key=lambda x: x["ts"],
    )
    # Day reset timestamps: all offsets except the very first (position already 0)
    resets = sorted(b for b in (day_boundaries or []) if b > 0)
    ri = 0  # pointer into resets

    ts_list, pos_list = [], []
    pos = 0
    for f in events:
        ts = f["ts"]
        # Cross any day boundaries before this fill
        while ri < len(resets) and ts >= resets[ri]:
            if ts_list:                          # draw down to 0 at boundary
                ts_list.append(resets[ri] - 1)
                pos_list.append(pos)
            ts_list.append(resets[ri])           # reset point
            pos_list.append(0)
            pos = 0
            ri += 1
        sign = 1 if f.get("side") == "BUY" else -1
        pos += sign * f.get("qty", f.get("quantity", 0))
        ts_list.append(ts)
        pos_list.append(pos)
    return ts_list, pos_list


# ── Optional: parse IMC log file ───────────────────────────────────────────────

def _parse_imclog(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  Warning: could not parse log {path}: {e}")
        return None

    activities_text = (raw.get("activitiesLog") or raw.get("activityLog")
                       or raw.get("activities") or "")
    rows_by_prod: Dict[str, List[Tuple]] = defaultdict(list)
    if activities_text:
        for row in csv.DictReader(activities_text.strip().splitlines(), delimiter=";"):
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
            "ts":   [r[0] for r in rows], "bid1": [r[1] for r in rows],
            "ask1": [r[2] for r in rows], "mid":  [r[3] for r in rows],
        }

    trade_raw = raw.get("tradeHistory") or raw.get("tradeLog") or ""
    own_trades: List[Dict] = []
    # tradeHistory is either a CSV string or a list of dicts depending on IMC log version
    if isinstance(trade_raw, list):
        trade_rows = trade_raw
    elif isinstance(trade_raw, str) and trade_raw.strip():
        trade_rows = list(csv.DictReader(trade_raw.strip().splitlines(), delimiter=";"))
    else:
        trade_rows = []
    for row in trade_rows:
        ts     = _to_int(row.get("timestamp", ""))
        px     = _to_float(row.get("price", ""))
        qty    = _to_int(row.get("quantity", ""))
        buyer  = str(row.get("buyer",  "") or "").strip()
        seller = str(row.get("seller", "") or "").strip()
        sym    = str(row.get("symbol", "") or row.get("product", "") or "").strip()
        if ts is None or px is None or qty is None:
            continue
        if buyer == "SUBMISSION":
            own_trades.append({"ts": ts, "symbol": sym, "side": "BUY", "price": px, "qty": qty})
        elif seller == "SUBMISSION":
            own_trades.append({"ts": ts, "symbol": sym, "side": "SELL", "price": px, "qty": qty})

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
            if trace == "taker_fills":
                for entry_row in obj.get("log", []):
                    if len(entry_row) >= 4:
                        taker_fills_log.append({
                            "ts": entry_row[0], "product": product,
                            "side": entry_row[1], "price": entry_row[2], "qty": entry_row[3],
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
                    if ts_val is None:
                        continue
                    row_data: Dict[str, Any] = {
                        "timestamp": ts_val, "product": product,
                        "bid_price": mapped.get("bid_price"),
                        "ask_price": mapped.get("ask_price"),
                    }
                    for k, v in mapped.items():
                        if k not in ("timestamp", "bid_price", "ask_price"):
                            row_data[k] = v
                    quote_traces.append(row_data)

    return {
        "market_prices": market_prices, "own_trades": own_trades,
        "quote_traces": quote_traces, "taker_fills": taker_fills_log,
    }


# ── Plotly layout helper ───────────────────────────────────────────────────────

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


# ── Chart: Price + fills (v5 version) ─────────────────────────────────────────

def _price_chart_js_v5(
    product: str,
    market: Dict,
    our_fills: List[Dict],
    quotes: List[Dict],
    v5: Dict,          # output of _extract_v5_series
    market_trades: List[Dict],
    trader_index: Dict[str, int],
    taker_edge: float,
) -> str:
    safe = _jsid(product)
    step = 10
    ts_s  = market["ts"][::step]
    bid_s = market["bid1"][::step]
    ask_s = market["ask1"][::step]
    mid_s = market["mid"][::step]

    traces: List[str] = [
        f"""{{x:{_json_list(ts_s)},y:{_json_list(bid_s)},name:'Market Bid',mode:'lines',
      line:{{color:'#89b4fa',width:1}},opacity:0.6,hovertemplate:'Bid: %{{y}}<extra></extra>'}}""",
        f"""{{x:{_json_list(ts_s)},y:{_json_list(ask_s)},name:'Market Ask',mode:'lines',
      line:{{color:'#f38ba8',width:1}},opacity:0.6,hovertemplate:'Ask: %{{y}}<extra></extra>'}}""",
        f"""{{x:{_json_list(ts_s)},y:{_json_list(mid_s)},name:'Mid',mode:'lines',
      line:{{color:'#cdd6f4',width:1,opacity:0.4}},hovertemplate:'Mid: %{{y}}<extra></extra>'}}""",
    ]

    # AR fair value + entry threshold bands
    if v5["fv_ts"]:
        fv_ts  = _json_list(v5["fv_ts"])
        fv_v   = _json_list(v5["fv"])
        # Fair value ± taker_edge filled area (entry zone)
        fv_up  = _json_list([v + taker_edge for v in v5["fv"]])
        fv_dn  = _json_list([v - taker_edge for v in v5["fv"]])
        traces += [
            # upper band fill
            f"""{{x:{fv_ts},y:{fv_up},name:'+edge ({taker_edge})',mode:'lines',
          fill:'tonexty',fillcolor:'rgba(166,227,161,0.08)',
          line:{{color:'rgba(166,227,161,0.35)',width:1,dash:'dot'}},
          hovertemplate:'FV+edge: %{{y}}<extra></extra>'}}""",
            # lower band (plotted first so fill works between them)
            f"""{{x:{fv_ts},y:{fv_dn},name:'-edge ({taker_edge})',mode:'lines',
          fill:'tonexty',fillcolor:'rgba(243,139,168,0.08)',
          line:{{color:'rgba(243,139,168,0.35)',width:1,dash:'dot'}},
          hovertemplate:'FV-edge: %{{y}}<extra></extra>'}}""",
            # fair value itself
            f"""{{x:{fv_ts},y:{fv_v},name:'FairValue (AR)',mode:'lines',
          line:{{color:'#f9e2af',width:1.5}},
          hovertemplate:'FV: %{{y:.2f}}<extra></extra>'}}""",
        ]

    # Our submitted passive quotes (subsample every 5th for file size)
    q_prod = [q for q in quotes if q.get("symbol") == product]
    if q_prod:
        q_prod = q_prod[::5]
        q_ts  = [q["ts"]  for q in q_prod]
        q_bid = [q["bid"] for q in q_prod]
        q_ask = [q["ask"] for q in q_prod]
        traces += [
            f"""{{x:{json.dumps(q_ts)},y:{json.dumps(q_bid)},name:'Our Bid (passive)',
          mode:'lines',line:{{color:'#74c7ec',width:1.2,dash:'dot'}},
          hovertemplate:'Our Bid: %{{y}}<extra></extra>'}}""",
            f"""{{x:{json.dumps(q_ts)},y:{json.dumps(q_ask)},name:'Our Ask (passive)',
          mode:'lines',line:{{color:'#f38ba8',width:1.2,dash:'dot'}},
          hovertemplate:'Our Ask: %{{y}}<extra></extra>'}}""",
        ]

    # Our fills: taker (★ star) vs maker (● circle), split by side + type
    our_prod = [f for f in our_fills if f.get("symbol") == product]

    def _fill_trace(fills, color, marker_sym, name, size=11):
        if not fills:
            return None
        qtys = [f.get("qty", f.get("quantity", 0)) for f in fills]
        return (f"""{{x:{json.dumps([f['ts'] for f in fills])},
          y:{json.dumps([f['price'] for f in fills])},
          name:'{name}',mode:'markers',
          marker:{{symbol:'{marker_sym}',color:'{color}',size:{size},opacity:0.95,
                   line:{{color:'#1e1e2e',width:0.8}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{name}</b> qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")

    taker_buys  = [f for f in our_prod if f.get("side") == "BUY"  and f.get("aggressive", True)]
    taker_sells = [f for f in our_prod if f.get("side") == "SELL" and f.get("aggressive", True)]
    maker_buys  = [f for f in our_prod if f.get("side") == "BUY"  and not f.get("aggressive", True)]
    maker_sells = [f for f in our_prod if f.get("side") == "SELL" and not f.get("aggressive", True)]

    for fills, color, sym, name, sz in [
        (taker_buys,  "#a6e3a1", "star",         "TAKER BUY",  13),
        (taker_sells, "#f38ba8", "star",          "TAKER SELL", 13),
        (maker_buys,  "#74c7ec", "circle",        "MAKER BUY",   9),
        (maker_sells, "#eba0ac", "circle-open",   "MAKER SELL",  9),
    ]:
        t = _fill_trace(fills, color, sym, name, sz)
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
          x:{json.dumps([f['ts'] for f in buys])},y:{json.dumps([f['px'] for f in buys])},
          name:'{trader} buy',mode:'markers',
          marker:{{symbol:'square',color:'{bc}',size:6,opacity:0.7,
                   line:{{color:'#1e1e2e',width:0.4}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{trader}</b> BUY qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")
        if sells:
            qtys = [f["qty"] for f in sells]
            traces.append(f"""{{
          x:{json.dumps([f['ts'] for f in sells])},y:{json.dumps([f['px'] for f in sells])},
          name:'{trader} sell',mode:'markers',
          marker:{{symbol:'square-open',color:'{sc}',size:6,opacity:0.7,
                   line:{{color:'{sc}',width:1.2}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{trader}</b> SELL qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")

    traces_js = ",\n    ".join(traces)
    return f"""
  function plot_price_{safe}() {{
    var layout = Object.assign({{}}, {_layout_js()}, {{
      title: '{product} — Price + FairValue + Fills',
      legend: {{bgcolor:'rgba(0,0,0,0)',font:{{size:9}},x:1.01,xanchor:'left'}},
      yaxis: {{title:'price',gridcolor:'#313244'}},
      margin: {{t:36,b:44,l:65,r:200}},
    }});
    Plotly.newPlot('price_{safe}', [{traces_js}], layout, {{responsive:true}});
  }}"""


# ── Chart: AR Deviation with threshold bands (v5) ─────────────────────────────

def _deviation_chart_js(product: str, v5: Dict, taker_edge: float) -> str:
    safe = _jsid(product)
    if not v5["dev_ts"]:
        return f"""
  function plot_dev_{safe}() {{
    document.getElementById('dev_{safe}').innerHTML =
      '<p style="color:#6c7086;padding:1em">No DevSmooth available.</p>';
  }}"""

    dev_ts = _json_list(v5["dev_ts"])
    dev_v  = _json_list(v5["dev"])

    # Color each bar by whether it's beyond threshold
    ref_lines = f"""
      {{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:0,y1:0,
        line:{{color:'#cdd6f4',width:1}}}},
      {{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:{taker_edge},y1:{taker_edge},
        line:{{color:'#a6e3a1',width:1.5,dash:'dash'}}}},
      {{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:-{taker_edge},y1:-{taker_edge},
        line:{{color:'#f38ba8',width:1.5,dash:'dash'}}}},"""

    # M14 signal overlay (only if available)
    m14_trace = ""
    if v5["m14_ts"]:
        m14_ts = _json_list(v5["m14_ts"])
        m14_v  = _json_list([v * taker_edge * 0.8 for v in v5["m14"]])
        m14_trace = f""",{{
      x:{m14_ts},y:{m14_v},name:'M14 × edge',mode:'lines',
      line:{{color:'#cba6f7',width:1,dash:'dot'}},yaxis:'y',
      hovertemplate:'M14×edge: %{{y:.1f}}<extra></extra>'
    }}"""

    return f"""
  function plot_dev_{safe}() {{
    Plotly.newPlot('dev_{safe}', [{{
      x:{dev_ts},y:{dev_v},name:'DevSmooth',mode:'lines',fill:'tozeroy',
      fillcolor:'rgba(137,180,250,0.12)',
      line:{{color:'#89b4fa',width:1.5}},
      hovertemplate:'Dev: %{{y:.2f}}<extra></extra>'
    }}{m14_trace}],
    Object.assign({{}},{_layout_js()},{{
      title:'{product} — AR Deviation (threshold ±{taker_edge})',
      yaxis:{{title:'deviation (ticks)',gridcolor:'#313244',zeroline:false}},
      shapes:[{ref_lines}],
      margin:{{t:30,b:36,l:65,r:20}},
      annotations:[
        {{xref:'paper',yref:'y',x:0.01,y:{taker_edge},text:'BUY zone (-edge)',
          showarrow:false,font:{{color:'#a6e3a1',size:9}},xanchor:'left'}},
        {{xref:'paper',yref:'y',x:0.01,y:-{taker_edge},text:'SELL zone (+edge)',
          showarrow:false,font:{{color:'#f38ba8',size:9}},xanchor:'left'}},
      ]
    }}), {{responsive:true}});
  }}"""


# ── Chart: Position + Inventory Bias sizing ────────────────────────────────────

def _position_sizing_chart_js(
    product: str, our_fills: List[Dict], v5: Dict,
    day_boundaries: Optional[List[int]] = None,
) -> str:
    safe = _jsid(product)
    ts_list, pos_list = _position_curve(our_fills, product, day_boundaries)

    if not ts_list:
        return f"""
  function plot_pos_{safe}() {{
    document.getElementById('pos_{safe}').innerHTML =
      '<p style="color:#6c7086;padding:1em">No fills for {product}.</p>';
  }}"""

    pos_trace = f"""{{
      x:{json.dumps(ts_list)},y:{json.dumps(pos_list)},
      name:'Position',mode:'lines',fill:'tozeroy',
      fillcolor:'rgba(166,227,161,0.1)',
      line:{{color:'#a6e3a1',width:2}},yaxis:'y',
      hovertemplate:'pos: %{{y}}<extra></extra>'
    }}"""

    size_traces = ""
    if v5["size_ts"]:
        sz_ts = _json_list(v5["size_ts"])
        bsz   = _json_list(v5["bid_size"])
        asz   = _json_list(v5["ask_size"])
        size_traces = f""",{{
      x:{sz_ts},y:{bsz},name:'Bid size',mode:'lines',
      line:{{color:'#74c7ec',width:1,dash:'dot'}},yaxis:'y2',
      hovertemplate:'bid_sz: %{{y}}<extra></extra>'
    }},{{
      x:{sz_ts},y:{asz},name:'Ask size',mode:'lines',
      line:{{color:'#f38ba8',width:1,dash:'dot'}},yaxis:'y2',
      hovertemplate:'ask_sz: %{{y}}<extra></extra>'
    }}"""

    layout_extra = """
      yaxis2: {title:'quote size',overlaying:'y',side:'right',gridcolor:'#313244',
               showgrid:false,tickfont:{color:'#6c7086'}},"""

    return f"""
  function plot_pos_{safe}() {{
    Plotly.newPlot('pos_{safe}',[{pos_trace}{size_traces}],
    Object.assign({{}},{_layout_js(layout_extra)},{{
      title:'{product} — Position (left) + Quote Sizes / Inventory Bias (right)',
      yaxis:{{title:'units',gridcolor:'#313244',zeroline:true}},
      margin:{{t:30,b:36,l:65,r:65}},
    }}),{{responsive:true}});
  }}"""


# ── Chart: M14 Signal ─────────────────────────────────────────────────────────

def _m14_chart_js(product: str, v5: Dict) -> str:
    safe = _jsid(product)
    if not v5["m14_ts"]:
        return f"""
  function plot_m14_{safe}() {{
    document.getElementById('m14_{safe}').innerHTML =
      '<p style="color:#6c7086;padding:1em">No M14 signal data.</p>';
  }}"""

    m14_ts = _json_list(v5["m14_ts"])
    m14_v  = _json_list(v5["m14"])
    # Color: +1 green, -1 red, 0 grey
    colors = json.dumps([
        "#a6e3a1" if v == 1.0 else "#f38ba8" if v == -1.0 else "#6c7086"
        for v in v5["m14"]
    ])
    return f"""
  function plot_m14_{safe}() {{
    Plotly.newPlot('m14_{safe}',[{{
      x:{m14_ts},y:{m14_v},name:'M14 Signal',mode:'markers+lines',
      marker:{{color:{colors},size:5}},
      line:{{color:'#cba6f7',width:1}},
      hovertemplate:'M14: %{{y}}<extra></extra>'
    }}],
    Object.assign({{}},{_layout_js()},{{
      title:'{product} — Mark 14 Signal (+1=buy / −1=sell / 0=silent)',
      yaxis:{{title:'signal',gridcolor:'#313244',zeroline:true,
              tickvals:[-1,0,1],ticktext:['SELL','—','BUY'],range:[-1.5,1.5]}},
      shapes:[
        {{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:1,y1:1,
          line:{{color:'#a6e3a1',width:1,dash:'dot'}}}},
        {{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:-1,y1:-1,
          line:{{color:'#f38ba8',width:1,dash:'dot'}}}},
      ],
      margin:{{t:30,b:36,l:65,r:20}},
    }}),{{responsive:true}});
  }}"""


# ── Chart: PnL ────────────────────────────────────────────────────────────────

def _pnl_chart_js(equity: Dict, day_boundaries: Optional[List[int]] = None) -> str:
    if not equity["ts"]:
        return "function plot_pnl() {}"

    pnl_vals = equity["pnl"]

    # Drawdown: running peak − current (always ≤ 0)
    peak = 0.0
    dd_vals = []
    for p in pnl_vals:
        if p > peak:
            peak = p
        dd_vals.append(p - peak)

    # Vertical day-separator lines
    boundary_shapes = ""
    for b in (day_boundaries or [])[1:]:
        boundary_shapes += f"""
      {{type:'line',xref:'x',yref:'paper',x0:{b},x1:{b},y0:0,y1:1,
        line:{{color:'#45475a',width:1,dash:'dot'}}}},"""

    ts_js  = json.dumps(equity["ts"])
    pnl_js = _json_list(pnl_vals)
    dd_js  = _json_list(dd_vals)

    return f"""
  function plot_pnl() {{
    Plotly.newPlot('pnl_chart',[
      {{x:{ts_js},y:{pnl_js},name:'PnL',mode:'lines',fill:'tozeroy',
        fillcolor:'rgba(203,166,247,0.15)',
        line:{{color:'#cba6f7',width:2}},
        hovertemplate:'PnL: %{{y:,.0f}}<extra></extra>'}},
      {{x:{ts_js},y:{dd_js},name:'Drawdown',mode:'lines',fill:'tozeroy',
        fillcolor:'rgba(243,139,168,0.15)',
        line:{{color:'#f38ba8',width:1.5}},
        hovertemplate:'DD: %{{y:,.0f}}<extra></extra>'}}
    ], Object.assign({{}},{_layout_js()},{{
      title:'Portfolio Equity Curve + Drawdown',
      yaxis:{{title:'PnL / DD (SeaShells)',gridcolor:'#313244',zeroline:true}},
      shapes:[{boundary_shapes}],
      margin:{{t:30,b:36,l:75,r:20}},
    }}),{{responsive:true}});
  }}"""


# ── Original charts (non-v5 fallback) ─────────────────────────────────────────

def _price_chart_js_generic(
    product, market, our_fills, quotes, sigma_bands, market_trades, trader_index,
) -> str:
    safe = _jsid(product)
    step = 10
    ts_s  = market["ts"][::step]
    bid_s = market["bid1"][::step]
    ask_s = market["ask1"][::step]
    mid_s = market["mid"][::step]

    traces: List[str] = [
        f"""{{x:{_json_list(ts_s)},y:{_json_list(bid_s)},name:'Best Bid',mode:'lines',
      line:{{color:'#89b4fa',width:1.5}},hovertemplate:'Bid: %{{y}}<extra></extra>'}}""",
        f"""{{x:{_json_list(ts_s)},y:{_json_list(ask_s)},name:'Best Ask',mode:'lines',
      line:{{color:'#f38ba8',width:1.5}},hovertemplate:'Ask: %{{y}}<extra></extra>'}}""",
        f"""{{x:{_json_list(ts_s)},y:{_json_list(mid_s)},name:'Mid',mode:'lines',
      line:{{color:'#cdd6f4',width:1,opacity:0.5}},hovertemplate:'Mid: %{{y}}<extra></extra>'}}""",
    ]
    if sigma_bands["ts"]:
        zts = _json_list(sigma_bands["ts"])
        ms  = _json_list(sigma_bands["mid_smooth"])
        for y, nm, col, dash in [
            ("s2u", "+2σ", "#6c7086", "dot"), ("s2d", "-2σ", "#6c7086", "dot"),
            ("s1u", "+1σ", "#9399b2", "dash"), ("s1d", "-1σ", "#9399b2", "dash"),
            ("mean", "μ", "#a6adc8", "longdash"),
        ]:
            traces.append(f"""{{x:{zts},y:{_json_list(sigma_bands[y])},name:'{nm}',mode:'lines',
          line:{{color:'{col}',width:1,dash:'{dash}'}},hovertemplate:'{nm}: %{{y}}<extra></extra>'}}""")
        traces.append(f"""{{x:{zts},y:{ms},name:'MidSmooth',mode:'lines',
      line:{{color:'#f9e2af',width:1}},hovertemplate:'MidSmooth: %{{y}}<extra></extra>'}}""")

    q_prod = [q for q in quotes if q.get("symbol") == product]
    if q_prod:
        q_ts  = [q["ts"]  for q in q_prod]
        q_bid = [q["bid"] for q in q_prod]
        q_ask = [q["ask"] for q in q_prod]
        traces += [
            f"""{{x:{json.dumps(q_ts)},y:{json.dumps(q_bid)},name:'Our Bid',mode:'lines',
          line:{{color:'#74c7ec',width:1,dash:'dot'}},hovertemplate:'Our Bid: %{{y}}<extra></extra>'}}""",
            f"""{{x:{json.dumps(q_ts)},y:{json.dumps(q_ask)},name:'Our Ask',mode:'lines',
          line:{{color:'#f38ba8',width:1,dash:'dot'}},hovertemplate:'Our Ask: %{{y}}<extra></extra>'}}""",
        ]

    our_prod = [f for f in our_fills if f.get("symbol") == product]
    for fills, color, sym, nm in [
        ([f for f in our_prod if f.get("side") == "BUY"],  "#a6e3a1", "star", "OUR BUY"),
        ([f for f in our_prod if f.get("side") == "SELL"], "#f38ba8", "star", "OUR SELL"),
    ]:
        if fills:
            qtys = [f.get("qty", 0) for f in fills]
            traces.append(f"""{{x:{json.dumps([f['ts'] for f in fills])},
          y:{json.dumps([f['price'] for f in fills])},name:'{nm}',mode:'markers',
          marker:{{symbol:'{sym}',color:'{color}',size:11,opacity:0.95,
                   line:{{color:'#1e1e2e',width:0.8}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{nm}</b> qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")

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
            traces.append(f"""{{x:{json.dumps([f['ts'] for f in buys])},
          y:{json.dumps([f['px'] for f in buys])},name:'{trader} buy',mode:'markers',
          marker:{{symbol:'square',color:'{bc}',size:7,opacity:0.8,
                   line:{{color:'#1e1e2e',width:0.4}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{trader}</b> BUY qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")
        if sells:
            qtys = [f["qty"] for f in sells]
            traces.append(f"""{{x:{json.dumps([f['ts'] for f in sells])},
          y:{json.dumps([f['px'] for f in sells])},name:'{trader} sell',mode:'markers',
          marker:{{symbol:'square-open',color:'{sc}',size:7,opacity:0.8,
                   line:{{color:'{sc}',width:1.2}}}},
          customdata:{json.dumps(qtys)},
          hovertemplate:'<b>{trader}</b> SELL qty=%{{customdata}} @ %{{y}}<extra></extra>'}}""")

    traces_js = ",\n    ".join(traces)
    return f"""
  function plot_price_{safe}() {{
    Plotly.newPlot('price_{safe}', [{traces_js}],
    Object.assign({{}}, {_layout_js()}, {{
      title: '{product} — Price + Fills',
      legend: {{bgcolor:'rgba(0,0,0,0)',font:{{size:9}},x:1.01,xanchor:'left'}},
      yaxis: {{title:'price',gridcolor:'#313244'}},
      margin: {{t:36,b:44,l:65,r:200}},
    }}), {{responsive:true}});
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


def _position_chart_js_generic(
    product: str, our_fills: List[Dict], day_boundaries: Optional[List[int]] = None,
) -> str:
    safe = _jsid(product)
    ts_list, pos_list = _position_curve(our_fills, product, day_boundaries)
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


# ── CSS + JS ───────────────────────────────────────────────────────────────────

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
.chart-med   { height:260px; }
.chart-short { height:160px; }
.product-panel { display:none; }
.stat-row { display:flex; flex-wrap:wrap; gap:1.5em; margin:0.5em 0 1em; font-size:0.82em; }
.stat { color:#a6adc8; }
.stat b { color:#cdd6f4; }
.legend-row { display:flex; flex-wrap:wrap; gap:1.5em; font-size:0.78em; color:#6c7086; margin-bottom:0.5em; }
.legend-item { display:flex; align-items:center; gap:4px; }
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
    ['plot_price_','plot_dev_','plot_z_','plot_pos_','plot_m14_'].forEach(fn => {
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
    taker_edge: float = 12.0,
    day_boundaries: Optional[List[int]] = None,
) -> None:
    products = sorted(market_prices.keys())
    if product_filter:
        products = [p for p in products if p == product_filter]

    # Detect v5 mode: DevSmooth in feature_ticks
    is_v5 = any("DevSmooth" in ft for ft in features)
    print(f"  Mode: {'v5 (passive MM + AR taker)' if is_v5 else 'generic'}")

    all_traders = sorted({f["buyer"] for f in market_trades}
                         | {f["seller"] for f in market_trades}
                         - {"?", "SUBMISSION"})
    trader_index = {t: i for i, t in enumerate(all_traders)}

    total_pnl = bt.get("summary", {}).get("total_pnl", equity["pnl"][-1] if equity["pnl"] else 0)
    n_fills = len(our_fills)
    n_taker = sum(1 for f in our_fills if f.get("aggressive", True))
    n_maker = n_fills - n_taker
    strategy_name = bt.get("strategy", "")

    stats_html = f"""<div class="stat-row">
  <span class="stat">Strategy: <b>{strategy_name}</b></span>
  <span class="stat">Total PnL: <b>{total_pnl:,.0f}</b></span>
  <span class="stat">Fills: <b>{n_fills}</b> (taker: <b>{n_taker}</b> / maker: <b>{n_maker}</b>)</span>
  <span class="stat">Market participants: <b>{len(all_traders)}</b></span>
  {"<span class='stat'>AR taker edge: <b>±" + str(taker_edge) + " ticks</b></span>" if is_v5 else ""}
</div>"""

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

        prod_fills  = [f for f in our_fills if f.get("symbol") == prod]
        prod_quotes = [q for q in quotes   if q.get("symbol") == prod]
        prod_mkt    = market_prices.get(prod, {"ts": [], "bid1": [], "ask1": [], "mid": []})

        prod_pnl = 0.0
        for day_data in bt.get("days", []):
            prod_pnl += day_data.get("product_summaries", {}).get(prod, {}).get("pnl", 0.0)
        n_prod_taker = sum(1 for f in prod_fills if f.get("aggressive", True))
        n_prod_maker = len(prod_fills) - n_prod_taker

        if is_v5:
            v5 = _extract_v5_series(features, quotes, prod)

            # Build v5 panel HTML
            panels += f"""
<div id="prod_panel_{safe}" class="product-panel">
  <div class="stat-row">
    <span class="stat">Product PnL: <b>{prod_pnl:,.0f}</b></span>
    <span class="stat">Taker fills: <b>{n_prod_taker}</b></span>
    <span class="stat">Maker fills: <b>{n_prod_maker}</b></span>
  </div>
  <div class="legend-row">
    <span class="legend-item">★ green = TAKER BUY</span>
    <span class="legend-item">★ red = TAKER SELL</span>
    <span class="legend-item">● blue = MAKER BUY</span>
    <span class="legend-item">● pink = MAKER SELL</span>
    <span class="legend-item">■ = other trader</span>
    <span class="legend-item">yellow = AR FairValue</span>
    <span class="legend-item">green band = BUY entry zone (FV - {taker_edge})</span>
    <span class="legend-item">red band = SELL entry zone (FV + {taker_edge})</span>
  </div>
  <div class="chart-container"><div id="price_{safe}" class="chart-tall"></div></div>
  <div class="chart-container"><div id="dev_{safe}"   class="chart-med"></div></div>
  <div class="chart-container"><div id="pos_{safe}"   class="chart-med"></div></div>
  <div class="chart-container"><div id="m14_{safe}"   class="chart-short"></div></div>
</div>"""

            js_fns += _price_chart_js_v5(prod, prod_mkt, our_fills, prod_quotes,
                                          v5, market_trades, trader_index, taker_edge)
            js_fns += _deviation_chart_js(prod, v5, taker_edge)
            js_fns += _position_sizing_chart_js(prod, our_fills, v5, day_boundaries)
            js_fns += _m14_chart_js(prod, v5)

        else:
            sigma_bands = _sigma_bands_from_features(features, prod)
            panels += f"""
<div id="prod_panel_{safe}" class="product-panel">
  <div class="stat-row">
    <span class="stat">Product PnL: <b>{prod_pnl:,.0f}</b></span>
    <span class="stat">Fills: <b>{len(prod_fills)}</b></span>
  </div>
  <div class="chart-container"><div id="price_{safe}" class="chart-tall"></div></div>
  <div class="chart-container"><div id="z_{safe}"     class="chart-short"></div></div>
  <div class="chart-container"><div id="pos_{safe}"   class="chart-med"></div></div>
</div>"""
            js_fns += _price_chart_js_generic(prod, prod_mkt, our_fills, prod_quotes,
                                               sigma_bands, market_trades, trader_index)
            js_fns += _zscore_chart_js(prod, sigma_bands)
            js_fns += _position_chart_js_generic(prod, our_fills, day_boundaries)

    tab_bar += "</div>"
    js_fns  += _pnl_chart_js(equity, day_boundaries)

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
    parser.add_argument("--backtest-json", required=True)
    parser.add_argument("--log",           default=None)
    parser.add_argument("--product",       default=None)
    parser.add_argument("--out",           default=None)
    parser.add_argument("--data-dir",      default=None)
    parser.add_argument("--ar-taker-edge", type=float, default=12.0,
                        help="AR taker edge threshold to show on deviation chart (default 12.0)")
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
    print(f"  Products: {sorted(market_prices.keys())}, market trades: {len(market_trades)}")

    print("Processing backtest data ...")
    our_fills = _merge_backtest_fills(bt.get("days", []), round_num, days, data_dir / f"round_{round_num}")
    quotes    = _merge_quotes(bt.get("days", []), round_num, days, data_dir / f"round_{round_num}")
    features  = _merge_features(bt.get("days", []), round_num, days, data_dir / f"round_{round_num}")
    equity    = _merge_equity(bt.get("days", []), round_num, days, data_dir / f"round_{round_num}")
    print(f"  Fills: {len(our_fills)} ({sum(1 for f in our_fills if f.get('aggressive',True))} taker / "
          f"{sum(1 for f in our_fills if not f.get('aggressive',True))} maker), "
          f"quotes: {len(quotes)}, features: {len(features)}")

    if args.log:
        log_path = ROOT / args.log if not Path(args.log).is_absolute() else Path(args.log)
        print(f"Parsing IMC log {log_path} ...")
        log_data = _parse_imclog(log_path)
        if log_data:
            if log_data["market_prices"]:
                print(f"  Using market prices from log ({len(log_data['market_prices'])} products)")
                market_prices = log_data["market_prices"]
            if log_data["own_trades"]:
                print(f"  Using {len(log_data['own_trades'])} own trades from log")
                our_fills = [{"ts": t["ts"], "symbol": t["symbol"], "side": t["side"],
                               "price": t["price"], "qty": t["qty"],
                               "aggressive": False, "gap_exploit": False}
                             for t in log_data["own_trades"]]
            else:
                print("  No own trades in log — keeping backtest fills")
            if log_data["quote_traces"]:
                print(f"  Using {len(log_data['quote_traces'])} quote traces from log")
                quotes = [{"ts": q["timestamp"], "symbol": q["product"],
                           "bid": q.get("bid_price"), "ask": q.get("ask_price"),
                           "bid_size": q.get("bid_size", 0),
                           "ask_size": q.get("ask_size", 0)}
                          for q in log_data["quote_traces"]]
                features = []
                for q in log_data["quote_traces"]:
                    feat: Dict[str, Any] = {"timestamp": q["timestamp"], "symbol": q["product"]}
                    for k in ("FairValue", "DevSmooth", "M14Signal",
                              "ZsMean", "ZsStd", "MidSmooth", "Z"):
                        if k in q:
                            feat[k] = q[k]
                    features.append(feat)

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

    # Day boundaries: timestamp offset of each day's start (position resets here)
    ts_offsets     = _build_day_offsets(round_num, days, data_dir / f"round_{round_num}")
    day_boundaries = sorted(ts_offsets.values())

    print("Generating HTML ...")
    generate_html(
        bt=bt, market_prices=market_prices, market_trades=market_trades,
        our_fills=our_fills, quotes=quotes, features=features, equity=equity,
        output_path=out_path, title=title, product_filter=args.product,
        taker_edge=args.ar_taker_edge, day_boundaries=day_boundaries,
    )
    print("Done.")


if __name__ == "__main__":
    main()
