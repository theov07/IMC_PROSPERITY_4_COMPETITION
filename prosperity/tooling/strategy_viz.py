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


def _feature_value(row: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = _to_float(row.get(key))
        if value is not None:
            return value
    return None


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
    """Extract v5/v6/v7-specific time series from feature_ticks and quotes."""
    (fv_ts, fv_vals, dev_ts, dev_vals, m14_ts, m14_vals,
     anc_ts, anc_vals, mom_ts, mom_vals,
     guard_ts, guard_vals, tsell_ts, tsell_vals, tbuy_ts, tbuy_vals,
     fsz_ts, f_bid_sz, f_ask_sz,
     fmid_ts, fmid_vals, alim_ts, alim_vals) = ([] for _ in range(23))

    for ft in features:
        if ft.get("symbol") != product:
            continue
        ts = ft["timestamp"]
        fv   = _to_float(ft.get("FairValue"))
        dv   = _to_float(ft.get("DevSmooth"))
        m14  = _to_float(ft.get("M14Signal"))
        anc  = _to_float(ft.get("Anchor"))
        mom  = _to_float(ft.get("ar_mom"))
        grd  = _to_float(ft.get("guard"))
        ts_  = _to_float(ft.get("taker_sell"))
        tb_  = _to_float(ft.get("taker_buy"))
        # v6 uses bid_size/ask_size; v7 uses mm_bid_qty/mm_ask_qty
        bsz  = _to_float(ft.get("bid_size") if ft.get("bid_size") is not None else ft.get("mm_bid_qty"))
        asz  = _to_float(ft.get("ask_size") if ft.get("ask_size") is not None else ft.get("mm_ask_qty"))
        fmid = _to_float(ft.get("fast_mid"))          # v7: reactive EWMA fair value for MM
        alim = _to_float(ft.get("anchor_limit"))      # v7: AR taker position boundary
        if fv   is not None: fv_ts.append(ts);     fv_vals.append(fv)
        if dv   is not None: dev_ts.append(ts);    dev_vals.append(dv)
        if m14  is not None: m14_ts.append(ts);    m14_vals.append(m14)
        if anc  is not None: anc_ts.append(ts);    anc_vals.append(anc)
        if mom  is not None: mom_ts.append(ts);    mom_vals.append(mom)
        if grd  is not None: guard_ts.append(ts);  guard_vals.append(grd)
        if ts_  is not None: tsell_ts.append(ts);  tsell_vals.append(ts_)
        if tb_  is not None: tbuy_ts.append(ts);   tbuy_vals.append(tb_)
        if bsz  is not None and asz is not None:
            fsz_ts.append(ts); f_bid_sz.append(bsz); f_ask_sz.append(asz)
        if fmid is not None: fmid_ts.append(ts);   fmid_vals.append(fmid)
        if alim is not None: alim_ts.append(ts);   alim_vals.append(alim)

    # sizes: prefer quote-trace from features; fall back to quotes buffer
    if not fsz_ts:
        for i, q in enumerate(quotes):
            if q.get("symbol") != product or i % 5 != 0:
                continue
            fsz_ts.append(q["ts"])
            f_bid_sz.append(q.get("bid_size", 0))
            f_ask_sz.append(q.get("ask_size", 0))

    return {
        "fv_ts":      fv_ts,    "fv":         fv_vals,
        "dev_ts":     dev_ts,   "dev":         dev_vals,
        "m14_ts":     m14_ts,   "m14":         m14_vals,
        "anc_ts":     anc_ts,   "anc":         anc_vals,
        "mom_ts":     mom_ts,   "mom":         mom_vals,
        "guard_ts":   guard_ts, "guard":       guard_vals,
        "tsell_ts":   tsell_ts, "tsell":       tsell_vals,
        "tbuy_ts":    tbuy_ts,  "tbuy":        tbuy_vals,
        "size_ts":    fsz_ts,   "bid_size":    f_bid_sz,  "ask_size": f_ask_sz,
        "fmid_ts":    fmid_ts,  "fmid":        fmid_vals,
        "alim_ts":    alim_ts,  "alim":        alim_vals,
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


# ── IMC log mode: load everything from an uploaded submission log ──────────────

def _parse_activities(activities_text: str) -> Tuple[Dict[str, Any], Dict, Dict[str, Dict]]:
    """Parse activitiesLog CSV → market_prices, total equity, per-product equity."""
    rows_by_prod: Dict[str, List[Tuple]] = defaultdict(list)
    pnl_by_ts: Dict[int, float] = {}
    pnl_by_prod_ts: Dict[str, Dict[int, float]] = defaultdict(dict)

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
        pnl = _to_float(row.get("profit_and_loss", ""))
        if pnl is not None:
            pnl_by_ts[ts] = pnl_by_ts.get(ts, 0.0) + pnl
            pnl_by_prod_ts[prod][ts] = pnl

    market_prices: Dict[str, Any] = {}
    for prod, rows in rows_by_prod.items():
        rows.sort(key=lambda x: x[0])
        market_prices[prod] = {
            "ts":   [r[0] for r in rows], "bid1": [r[1] for r in rows],
            "ask1": [r[2] for r in rows], "mid":  [r[3] for r in rows],
        }

    ts_sorted = sorted(pnl_by_ts)
    equity = {"ts": ts_sorted, "pnl": [pnl_by_ts[t] for t in ts_sorted]}

    per_product_equity: Dict[str, Dict] = {}
    for prod, pm in pnl_by_prod_ts.items():
        ts_p = sorted(pm)
        per_product_equity[prod] = {"ts": ts_p, "pnl": [pm[t] for t in ts_p]}

    return market_prices, equity, per_product_equity


def _parse_trade_history(trade_raw) -> Tuple[List[Dict], List[Dict]]:
    """Parse tradeHistory → (our_fills, market_trades)."""
    if isinstance(trade_raw, list):
        rows = trade_raw
    elif isinstance(trade_raw, str) and trade_raw.strip():
        rows = list(csv.DictReader(trade_raw.strip().splitlines(), delimiter=";"))
    else:
        rows = []

    our_fills: List[Dict] = []
    market_trades: List[Dict] = []
    for row in rows:
        ts     = _to_int(row.get("timestamp", "") if isinstance(row, dict) else row.get("timestamp", ""))
        px     = _to_float(row.get("price", ""))
        qty    = _to_int(row.get("quantity", ""))
        buyer  = str(row.get("buyer",  "") or "").strip()
        seller = str(row.get("seller", "") or "").strip()
        sym    = str(row.get("symbol", "") or row.get("product", "") or "").strip()
        if ts is None or px is None or qty is None:
            continue
        if buyer == "SUBMISSION":
            our_fills.append({"ts": ts, "symbol": sym, "side": "BUY",  "price": px, "qty": qty, "aggressive": True})
        elif seller == "SUBMISSION":
            our_fills.append({"ts": ts, "symbol": sym, "side": "SELL", "price": px, "qty": qty, "aggressive": True})
        else:
            market_trades.append({"ts": ts, "buyer": buyer, "seller": seller, "symbol": sym, "px": px, "qty": qty})

    return our_fills, market_trades


def _parse_lambdalog_entries(runtime_logs: list, default_product: str = "") -> List[Dict]:
    """Parse lambdaLog entries from IMC logs.

    Handles two formats:
    1. Staggered block format (blk=A/B/C) produced by v5's diag_enabled logging
    2. Buffered quote_trace / taker_fills format produced by log_quote_snapshot

    default_product: fallback product name for blk entries that lack a "product" field
    (happens when uploaded before the product field was added to the logging code).
    """
    features: List[Dict] = []
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

            product = obj.get("product", "") or default_product
            blk = obj.get("blk")

            # ── Staggered block format (v5 diag_enabled) ──────────────────────
            if blk == "A":
                ts = _to_int(obj.get("ts"))
                if ts is not None and product:
                    features.append({
                        "timestamp": ts, "symbol": product,
                        "FairValue": _to_float(obj.get("fv")),
                        "DevSmooth": _to_float(obj.get("dev")),
                        "Position":  _to_float(obj.get("pos")),
                        "Guard":     _to_float(obj.get("guard")),
                    })
            elif blk == "C":
                ts = _to_int(obj.get("ts"))
                if ts is not None and product:
                    features.append({
                        "timestamp": ts, "symbol": product,
                        "M14Signal": _to_float(obj.get("m14_signal")),
                    })

            # ── Buffered quote_trace format (log_quote_snapshot) ───────────────
            elif not product:
                continue
            else:
                trace = obj.get("trace")
                columns = obj.get("columns")
                if trace == "quote_trace" or (trace is None and columns):
                    _META = {"timestamp", "bid_price", "ask_price",
                             "trace", "columns", "chunk_end", "product"}
                    for tick in obj.get("log", []):
                        if not isinstance(columns, list) or len(tick) < 3:
                            continue
                        mapped = {str(col): (tick[i] if i < len(tick) else None)
                                  for i, col in enumerate(columns)}
                        ts_val = _to_int(mapped.get("timestamp"))
                        if ts_val is None:
                            continue
                        feat: Dict[str, Any] = {"timestamp": ts_val, "symbol": product}
                        # Dynamically extract every non-metadata column
                        for k, v in mapped.items():
                            if k not in _META and v is not None:
                                fv = _to_float(v)
                                if fv is not None:
                                    feat[k] = fv
                        features.append(feat)

    return features


def _load_from_imclog(path: Path) -> Dict[str, Any]:
    """Load ALL visualizer data from a single IMC log file (.log or .json).

    Accepts both the .log format (has tradeHistory + activitiesLog + lambdaLog)
    and the .json format (has activitiesLog + graphLog but NO tradeHistory).
    When a .json file is loaded, automatically looks for a companion .log file
    in the same directory to recover the trade history.

    Returns the same data shape as the backtest pipeline so generate_html()
    works identically for both modes.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  Error reading log: {e}")
        sys.exit(1)

    activities_text = (raw.get("activitiesLog") or raw.get("activityLog") or "")
    market_prices, equity, per_product_equity = _parse_activities(activities_text)

    trade_raw = raw.get("tradeHistory") or raw.get("tradeLog") or []
    runtime_logs = raw.get("logs", [])

    # .json files have no tradeHistory — try companion .log file for trade data
    if not trade_raw and path.suffix == ".json":
        companion = path.with_suffix(".log")
        if companion.exists():
            print(f"  Auto-loading trade history from companion {companion.name} ...")
            try:
                companion_raw = json.loads(companion.read_text(encoding="utf-8"))
                trade_raw = companion_raw.get("tradeHistory") or companion_raw.get("tradeLog") or []
                # Also use lambdaLog from the .log if the .json lacks it
                if not runtime_logs:
                    runtime_logs = companion_raw.get("logs", [])
            except Exception as e:
                print(f"  Warning: could not read companion .log file: {e}")
        else:
            print(f"  ⚠  No tradeHistory in .json and no companion {companion.name} found — market trades will be empty")

    our_fills, market_trades = _parse_trade_history(trade_raw)

    # Infer primary product from our fills so old logs (without "product" in blk
    # dicts) still get their feature entries attributed to the right symbol.
    _syms = [f["symbol"] for f in our_fills if f.get("symbol")]
    primary_product = max(set(_syms), key=_syms.count) if _syms else ""
    features = _parse_lambdalog_entries(runtime_logs, default_product=primary_product)

    strategy_name = raw.get("submissionId", path.stem)[:32]
    n_feat = len([
        f for f in features
        if _feature_value(f, "FairValue", "fair_value") is not None
        or _feature_value(f, "DevSmooth", "deviation") is not None
    ])
    n_m14  = len([f for f in features if _feature_value(f, "M14Signal", "m14_signal") is not None])
    print(f"  Products: {sorted(market_prices.keys())}")
    print(f"  Own fills: {len(our_fills)}, market trades: {len(market_trades)}")
    print(f"  Features: {n_feat} A-blocks (FairValue/DevSmooth), {n_m14} C-blocks (M14Signal)")
    if n_feat == 0:
        print("  ⚠  No FairValue/DevSmooth in lambdaLog — v5 chart will show price/fills only")

    return {
        "market_prices":        market_prices,
        "market_trades":        market_trades,
        "our_fills":            our_fills,
        "quotes":               [],          # passive quote prices not logged in live
        "features":             features,
        "equity":               equity,
        "per_product_equity":   per_product_equity,
        "strategy_name":        strategy_name,
        "day_boundaries":       [],          # single-day live run — no resets
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

    # Anchor — shows where the dynamic anchor is tracking (v6+)
    if v5.get("anc_ts"):
        anc_ts = _json_list(v5["anc_ts"])
        anc_v  = _json_list(v5["anc"])
        traces.append(f"""{{x:{anc_ts},y:{anc_v},name:'Anchor (slow)',mode:'lines',
          line:{{color:'#fab387',width:1.2,dash:'dash'}},opacity:0.8,
          hovertemplate:'Anchor: %{{y:.2f}}<extra></extra>'}}""")

    # FastMid — v7 reactive EWMA used as MM fair value (tracks price closely)
    if v5.get("fmid_ts"):
        fmid_ts = _json_list(v5["fmid_ts"])
        fmid_v  = _json_list(v5["fmid"])
        traces.append(f"""{{x:{fmid_ts},y:{fmid_v},name:'FastMid (MM ref)',mode:'lines',
          line:{{color:'#a6e3a1',width:1.2,dash:'dash'}},opacity:0.85,
          hovertemplate:'FastMid: %{{y:.2f}}<extra></extra>'}}""")

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
      x:{sz_ts},y:{bsz},name:'Bid size (MM)',mode:'lines',
      line:{{color:'#74c7ec',width:1,dash:'dot'}},yaxis:'y2',
      hovertemplate:'bid_sz: %{{y}}<extra></extra>'
    }},{{
      x:{sz_ts},y:{asz},name:'Ask size (MM)',mode:'lines',
      line:{{color:'#f38ba8',width:1,dash:'dot'}},yaxis:'y2',
      hovertemplate:'ask_sz: %{{y}}<extra></extra>'
    }}"""

    # v7: anchor_limit reference lines — show the AR taker position boundary
    anchor_shapes = ""
    if v5.get("alim_ts") and v5["alim_ts"]:
        alim = v5["alim"][0]  # static per session
        anchor_shapes = f"""
        {{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:{alim},y1:{alim},
          line:{{color:'#fab387',width:1,dash:'dot'}}}},
        {{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:-{alim},y1:-{alim},
          line:{{color:'#fab387',width:1,dash:'dot'}}}},"""
        anchor_annot = f"""
        {{xref:'paper',yref:'y',x:0.99,y:{alim},text:'anchor +{int(alim)}u',
          showarrow:false,font:{{color:'#fab387',size:9}},xanchor:'right'}},
        {{xref:'paper',yref:'y',x:0.99,y:-{alim},text:'anchor -{int(alim)}u',
          showarrow:false,font:{{color:'#fab387',size:9}},xanchor:'right'}},"""
    else:
        anchor_annot = ""

    layout_extra = """
      yaxis2: {title:'quote size',overlaying:'y',side:'right',gridcolor:'#313244',
               showgrid:false,tickfont:{color:'#6c7086'}},"""

    return f"""
  function plot_pos_{safe}() {{
    Plotly.newPlot('pos_{safe}',[{pos_trace}{size_traces}],
    Object.assign({{}},{_layout_js(layout_extra)},{{
      title:'{product} — Position (left) + MM Quote Sizes (right)',
      yaxis:{{title:'units',gridcolor:'#313244',zeroline:true}},
      margin:{{t:30,b:36,l:65,r:65}},
      shapes:[{anchor_shapes}],
      annotations:[{anchor_annot}],
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


def _adaptive_regime_chart_js(product: str, v5: Dict) -> str:
    safe = _jsid(product)
    has_conf = bool(v5.get("conf_ts"))
    has_drift = bool(v5.get("drift_ts"))
    if not has_conf and not has_drift:
        return f"""
  function plot_regime_{safe}() {{
    document.getElementById('regime_{safe}').innerHTML =
      '<p style="color:#6c7086;padding:1em">No adaptive fair diagnostics for this strategy.</p>';
  }}"""

    traces: List[str] = []
    if has_conf:
        traces.append(f"""{{
      x:{_json_list(v5["conf_ts"])},y:{_json_list(v5["conf"])},
      name:'Anchor confidence',mode:'lines',
      line:{{color:'#94e2d5',width:1.8}},yaxis:'y',
      hovertemplate:'confidence: %{{y:.3f}}<extra></extra>'
    }}""")
    if has_drift:
        traces.append(f"""{{
      x:{_json_list(v5["drift_ts"])},y:{_json_list(v5["drift"])},
      name:'Anchor drift EWMA',mode:'lines',
      line:{{color:'#f9e2af',width:1.2,dash:'dot'}},yaxis:'y2',
      hovertemplate:'drift: %{{y:.2f}}<extra></extra>'
    }}""")

    traces_js = ",\n    ".join(traces)
    layout_extra = """
      yaxis2: {title:'drift (ticks)',overlaying:'y',side:'right',
               gridcolor:'#313244',showgrid:false,tickfont:{color:'#6c7086'}},"""
    return f"""
  function plot_regime_{safe}() {{
    Plotly.newPlot('regime_{safe}',[{traces_js}],
    Object.assign({{}},{_layout_js(layout_extra)},{{
      title:'{product} — Adaptive Fair Regime',
      yaxis:{{title:'anchor confidence',range:[0,1.05],gridcolor:'#313244',zeroline:false}},
      margin:{{t:30,b:36,l:65,r:70}},
    }}),{{responsive:true}});
  }}"""


# ── Chart: AR Momentum + Taker Activity (v6) ─────────────────────────────────

def _ar_momentum_chart_js(product: str, v5: Dict) -> str:
    """AR momentum + per-tick taker sell/buy bar chart.

    ar_mom positive → fair_value pulled DOWN → dev grows → taker sells fire.
    This chart makes it visually obvious when takers fire and why.
    """
    safe = _jsid(product)
    has_mom   = bool(v5.get("mom_ts"))
    has_taker = bool(v5.get("tsell_ts") or v5.get("tbuy_ts"))
    if not has_mom and not has_taker:
        return f"""
  function plot_mom_{safe}() {{
    document.getElementById('mom_{safe}').innerHTML =
      '<p style="color:#6c7086;padding:1em">No AR momentum / taker data (v6+ logging required).</p>';
  }}"""

    traces = []
    if has_mom:
        mom_ts = _json_list(v5["mom_ts"])
        mom_v  = _json_list(v5["mom"])
        # Guard state as background shading: guard=0 → taker blocked (red tint)
        guard_shapes = ""
        if v5.get("guard_ts"):
            # Build contiguous blocked regions
            pairs = sorted(zip(v5["guard_ts"], v5["guard"]))
            in_block = False
            start_ts = 0
            for ts, g in pairs:
                if g == 0 and not in_block:
                    in_block = True; start_ts = ts
                elif g != 0 and in_block:
                    in_block = False
                    guard_shapes += f"""{{type:'rect',xref:'x',yref:'paper',
                      x0:{start_ts},x1:{ts},y0:0,y1:1,
                      fillcolor:'rgba(243,139,168,0.08)',line:{{width:0}}}},"""
            if in_block:
                guard_shapes += f"""{{type:'rect',xref:'x',yref:'paper',
                  x0:{start_ts},x1:{pairs[-1][0]},y0:0,y1:1,
                  fillcolor:'rgba(243,139,168,0.08)',line:{{width:0}}}},"""

        traces.append(f"""{{
      x:{mom_ts},y:{mom_v},name:'AR momentum',mode:'lines',fill:'tozeroy',
      fillcolor:'rgba(249,226,175,0.15)',
      line:{{color:'#f9e2af',width:1.5}},
      hovertemplate:'ar_mom: %{{y:.4f}}<extra></extra>'
    }}""")

    if has_taker:
        if v5.get("tsell_ts"):
            traces.append(f"""{{
      x:{_json_list(v5["tsell_ts"])},y:{_json_list([-v for v in v5["tsell"]])},
      name:'Taker SELL (neg)',mode:'markers+lines',
      marker:{{color:'#f38ba8',size:5,symbol:'triangle-down'}},
      line:{{color:'#f38ba8',width:1}},
      hovertemplate:'sell qty: %{{text}}<extra></extra>',
      text:{_json_list(v5["tsell"])}
    }}""")
        if v5.get("tbuy_ts"):
            traces.append(f"""{{
      x:{_json_list(v5["tbuy_ts"])},y:{_json_list(v5["tbuy"])},
      name:'Taker BUY',mode:'markers+lines',
      marker:{{color:'#a6e3a1',size:5,symbol:'triangle-up'}},
      line:{{color:'#a6e3a1',width:1}},
      hovertemplate:'buy qty: %{{y}}<extra></extra>'
    }}""")

    guard_shapes_js = guard_shapes if has_mom and v5.get("guard_ts") else ""
    traces_js = ",\n    ".join(traces)
    return f"""
  function plot_mom_{safe}() {{
    Plotly.newPlot('mom_{safe}',[{traces_js}],
    Object.assign({{}},{_layout_js()},{{
      title:'{product} — AR Momentum (yellow) + Taker Activity (red shading = guard blocked)',
      yaxis:{{title:'momentum / qty',gridcolor:'#313244',zeroline:true}},
      shapes:[{guard_shapes_js}],
      margin:{{t:30,b:36,l:65,r:20}},
    }}),{{responsive:true}});
  }}"""


# ── Per-product equity from fills (backtest mode) ─────────────────────────────

def _compute_product_equity_from_fills(
    our_fills: List[Dict],
    market_prices: Dict[str, Any],
    products: List[str],
) -> Dict[str, Dict]:
    """Reconstruct per-product PnL curve from fills + mid prices.

    PnL = -cost_basis + position × mid  (realized + unrealized, matches IMC formula).
    Used in backtest mode where activitiesLog is not available.
    """
    per_product: Dict[str, Dict] = {}
    for product in products:
        prod_fills = sorted(
            [f for f in our_fills if f.get("symbol") == product],
            key=lambda x: x["ts"],
        )
        mid_ts   = market_prices.get(product, {}).get("ts",  [])
        mid_vals = market_prices.get(product, {}).get("mid", [])
        if not mid_ts:
            continue

        position   = 0
        cost_basis = 0.0
        fi         = 0
        ts_list:  List[int]   = []
        pnl_list: List[float] = []

        for i, ts in enumerate(mid_ts):
            mid = mid_vals[i]
            if mid is None:
                continue
            while fi < len(prod_fills) and prod_fills[fi]["ts"] <= ts:
                f   = prod_fills[fi]
                qty = f.get("qty", f.get("quantity", 0))
                px  = f["price"]
                if f["side"] == "BUY":
                    cost_basis += px * qty
                    position   += qty
                else:
                    cost_basis -= px * qty
                    position   -= qty
                fi += 1
            ts_list.append(ts)
            pnl_list.append(-cost_basis + position * mid)

        if ts_list:
            # subsample: keep at most 1 000 points (pure visualisation)
            step = max(1, len(ts_list) // 1000)
            per_product[product] = {
                "ts":  ts_list[::step],
                "pnl": pnl_list[::step],
            }
    return per_product


# ── Chart: PnL ────────────────────────────────────────────────────────────────

def _pnl_chart_js(
    equity: Dict,
    per_product_equity: Dict[str, Dict],
    day_boundaries: Optional[List[int]] = None,
) -> str:
    if not equity["ts"]:
        return "function plot_pnl() {} function pnlSelect(k) {}"

    def _build_dd(pnl_vals: List[float]) -> List[float]:
        peak = 0.0
        dd: List[float] = []
        for p in pnl_vals:
            if p > peak:
                peak = p
            dd.append(p - peak)
        return dd

    # Vertical day-separator shapes
    boundary_shapes = ""
    for b in (day_boundaries or [])[1:]:
        boundary_shapes += f"""
      {{type:'line',xref:'x',yref:'paper',x0:{b},x1:{b},y0:0,y1:1,
        line:{{color:'#45475a',width:1,dash:'dot'}}}},"""

    # Build JS data object: one entry per view (all + each product)
    entries: List[str] = []

    all_dd = _build_dd(equity["pnl"])
    entries.append(
        f"  all: {{ts:{json.dumps(equity['ts'])},"
        f"pnl:{_json_list(equity['pnl'])},"
        f"dd:{_json_list(all_dd)},"
        f"label:'Portfolio'}}"
    )

    for prod, eq in per_product_equity.items():
        if not eq.get("ts"):
            continue
        p_dd = _build_dd(eq["pnl"])
        entries.append(
            f"  {_jsid(prod)}: {{ts:{json.dumps(eq['ts'])},"
            f"pnl:{_json_list(eq['pnl'])},"
            f"dd:{_json_list(p_dd)},"
            f"label:{json.dumps(prod)}}}"
        )

    data_js = "{\n" + ",\n".join(entries) + "\n}"
    layout_extra = "yaxis:{title:'PnL / DD (SeaShells)',gridcolor:'#313244',zeroline:true},"
    layout_extra += f"shapes:[{boundary_shapes}],margin:{{t:30,b:36,l:75,r:20}},"

    return f"""
  var _pnl_data = {data_js};
  var _pnl_layout = Object.assign({{}},{_layout_js()},{{{layout_extra}}});

  function plot_pnl() {{ pnlSelect('all'); }}

  function pnlSelect(key) {{
    var d = _pnl_data[key]; if (!d) return;
    document.querySelectorAll('.pnl-filter-btn').forEach(function(b) {{
      b.classList.toggle('active', b.dataset.key === key);
    }});
    Plotly.react('pnl_chart', [
      {{x:d.ts,y:d.pnl,name:'PnL',mode:'lines',fill:'tozeroy',
        fillcolor:'rgba(203,166,247,0.15)',
        line:{{color:'#cba6f7',width:2}},
        hovertemplate:'PnL: %{{y:,.0f}}<extra></extra>'}},
      {{x:d.ts,y:d.dd,name:'Drawdown',mode:'lines',fill:'tozeroy',
        fillcolor:'rgba(243,139,168,0.15)',
        line:{{color:'#f38ba8',width:1.5}},
        hovertemplate:'DD: %{{y:,.0f}}<extra></extra>'}}
    ], Object.assign({{}}, _pnl_layout, {{title: d.label + ' — Equity + Drawdown'}}),
    {{responsive:true}});
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
    ['plot_price_','plot_dev_','plot_mom_','plot_z_','plot_pos_','plot_m14_'].forEach(fn => {
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
    per_product_equity: Optional[Dict[str, Dict]] = None,
    title: str = "",
    product_filter: Optional[str] = None,
    taker_edge: float = 12.0,
    day_boundaries: Optional[List[int]] = None,
) -> None:
    products = sorted(market_prices.keys())
    if product_filter:
        products = [p for p in products if p == product_filter]

    # Per-product equity: use provided dict (IMC log mode) or compute from fills
    if per_product_equity is None:
        per_product_equity = _compute_product_equity_from_fills(
            our_fills, market_prices, products,
        )
    # Filter to displayed products only
    ppe = {p: v for p, v in per_product_equity.items() if p in products}

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
        # Fall back to last point of per-product equity curve if bt days unavailable
        if prod_pnl == 0.0 and prod in ppe and ppe[prod].get("pnl"):
            prod_pnl = ppe[prod]["pnl"][-1]
        n_prod_taker = sum(1 for f in prod_fills if f.get("aggressive", True))
        n_prod_maker = len(prod_fills) - n_prod_taker

        if is_v5:
            v5 = _extract_v5_series(features, quotes, prod)

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
    <span class="legend-item">yellow = AR FairValue (slow)</span>
    <span class="legend-item">orange dashed = Anchor (v6/v7 slow)</span>
    <span class="legend-item">green dashed = FastMid (v7 MM reference)</span>
    <span class="legend-item">orange dotted = anchor_limit ± (v7 AR taker boundary)</span>
    <span class="legend-item">green band = BUY entry zone (FV - {taker_edge})</span>
    <span class="legend-item">red band = SELL entry zone (FV + {taker_edge})</span>
  </div>
  <div class="chart-container"><div id="price_{safe}" class="chart-tall"></div></div>
  <div class="chart-container"><div id="dev_{safe}"   class="chart-med"></div></div>
  <div class="chart-container"><div id="mom_{safe}"   class="chart-med"></div></div>
  <div class="chart-container"><div id="pos_{safe}"   class="chart-med"></div></div>
  <div class="chart-container"><div id="regime_{safe}" class="chart-med"></div></div>
  <div class="chart-container"><div id="m14_{safe}"   class="chart-short"></div></div>
</div>"""

            js_fns += _price_chart_js_v5(prod, prod_mkt, our_fills, prod_quotes,
                                          v5, market_trades, trader_index, taker_edge)
            js_fns += _deviation_chart_js(prod, v5, taker_edge)
            js_fns += _ar_momentum_chart_js(prod, v5)
            js_fns += _position_sizing_chart_js(prod, our_fills, v5, day_boundaries)
            js_fns += _adaptive_regime_chart_js(prod, v5)
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

    # PnL filter bar: All + one button per product that has equity data
    pnl_filter_bar = '<div class="tab-bar">'
    pnl_filter_bar += '<button class="pnl-filter-btn tab-btn active" data-key="all" onclick="pnlSelect(\'all\')">All</button>'
    for prod in products:
        if prod in ppe:
            safe_key = _jsid(prod)
            pnl_filter_bar += (
                f'<button class="pnl-filter-btn tab-btn" data-key="{safe_key}"'
                f' onclick="pnlSelect(\'{safe_key}\')">{prod}</button>'
            )
    pnl_filter_bar += "</div>"

    js_fns += _pnl_chart_js(equity, ppe, day_boundaries)

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
    <h2>PnL</h2>
    {pnl_filter_bar}
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
        description=(
            "Strategy visualization HTML.\n\n"
            "Mode A — backtest analysis:\n"
            "  python -m prosperity.tooling.strategy_viz --backtest-json artifacts/backtest_results/round_4/hydro_mv_v5_best.json\n\n"
            "Mode B — live IMC log analysis:\n"
            "  python -m prosperity.tooling.strategy_viz --log logs/round_4/tibo/hydro_mv_v5.log\n"
            "  python -m prosperity.tooling.strategy_viz --log logs/round_4/tibo/hydro_mv_v5.json\n\n"
            "Both .log and .json IMC files are accepted. When a .json is passed, the tool\n"
            "automatically loads trade history from the sibling .log file (same name, .log ext).\n"
            "The two modes are mutually exclusive. --log uses ONLY live data; no backtest\n"
            "features are mixed in."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backtest-json", help="Path to backtest result JSON")
    group.add_argument("--log",           help="Path to IMC submission log (.log or .json file). "
                                               "When passing a .json file that lacks tradeHistory, "
                                               "the tool auto-loads the companion .log file from "
                                               "the same directory.")
    parser.add_argument("--product",       default=None)
    parser.add_argument("--out",           default=None)
    parser.add_argument("--data-dir",      default=None)
    parser.add_argument("--ar-taker-edge", type=float, default=12.0,
                        help="AR taker edge threshold shown on deviation chart (default 12.0)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else ROOT / "data"

    # ── Mode B: live IMC log ────────────────────────────────────────────────────
    if args.log:
        log_path = ROOT / args.log if not Path(args.log).is_absolute() else Path(args.log)
        print(f"[Mode: IMC log] Loading {log_path} ...")
        d = _load_from_imclog(log_path)

        stem    = log_path.stem
        title   = (args.product + " | " if args.product else "") + d["strategy_name"]
        if args.out:
            out_path = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
        else:
            prod_tag = f"_{args.product}" if args.product else ""
            out_path = ROOT / f"artifacts/viz/{stem}{prod_tag}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        print("Generating HTML ...")
        generate_html(
            bt={"strategy": d["strategy_name"], "days": [], "summary": {}},
            market_prices=d["market_prices"],
            market_trades=d["market_trades"],
            our_fills=d["our_fills"],
            quotes=d["quotes"],
            features=d["features"],
            equity=d["equity"],
            per_product_equity=d["per_product_equity"],
            output_path=out_path,
            title=title,
            product_filter=args.product,
            taker_edge=args.ar_taker_edge,
            day_boundaries=d["day_boundaries"],
        )
        print("Done.")
        return

    # ── Mode A: backtest JSON ───────────────────────────────────────────────────
    bt_path = ROOT / args.backtest_json if not Path(args.backtest_json).is_absolute() else Path(args.backtest_json)
    print(f"[Mode: backtest] Loading {bt_path} ...")
    bt        = _load_backtest_json(bt_path)
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
