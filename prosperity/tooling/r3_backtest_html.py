"""Round-3 backtest HTML report generator.

Reads the JSON output from `backtest.py --json-out` (and optionally the prices
CSVs for market bid/ask and Greek computation) and writes a self-contained HTML
file with interactive Plotly charts.

Usage:
    python -m prosperity.tooling.r3_backtest_html \\
        --json artifacts/analysis/round_3/tibo_velvet_v25_round3.json \\
        --prices-dir data/round_3 \\
        --out artifacts/analysis/round_3/tibo_velvet_v25_report.html

    # without prices CSV (summary table + fills/quotes/equity only)
    python -m prosperity.tooling.r3_backtest_html \\
        --json artifacts/analysis/round_3/tibo_velvet_v25_round3.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import pandas as pd
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from prosperity.options.black_scholes import (
    call_delta, call_gamma, call_price, call_theta, call_vega,
)
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict

# ── Option universe ───────────────────────────────────────────────────────────
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
OPTION_SYMS = [f"VEV_{k}" for k in STRIKES]
UNDERLYING = "VELVETFRUIT_EXTRACT"
TTE_BY_DAY = {0: 8.0, 1: 7.0, 2: 6.0}
TS_PER_DAY = 1_000_000
SIGMA_PRIOR = 0.0125

PRODUCT_COLORS = {
    "VELVETFRUIT_EXTRACT": "#1f77b4",
    "VEV_4000": "#ff7f0e", "VEV_4500": "#2ca02c", "VEV_5000": "#d62728",
    "VEV_5100": "#9467bd", "VEV_5200": "#8c564b", "VEV_5300": "#e377c2",
    "VEV_5400": "#7f7f7f", "VEV_5500": "#bcbd22", "VEV_6000": "#17becf",
    "VEV_6500": "#aec7e8",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _opt_strike(sym: str) -> int | None:
    if sym.startswith("VEV_"):
        try:
            return int(sym[4:])
        except ValueError:
            pass
    return None


def _tte(ts: int, day: int) -> float:
    return max(0.001, TTE_BY_DAY.get(day, 5.0) - ts / TS_PER_DAY)


def _fmt(v, digits=0):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:,.{digits}f}"


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_prices(prices_dir: Path, day: int) -> "pd.DataFrame | None":
    if not _HAS_NUMPY:
        return None
    path = prices_dir / f"prices_round_3_day_{day}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, delimiter=";")
    df.columns = [c.strip() for c in df.columns]
    for col in ["bid_price_1", "ask_price_1", "mid_price", "timestamp"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _build_series(json_days: list[dict], prices_dir: Path | None) -> dict:
    """Merge JSON data + prices CSVs into per-symbol time series dicts."""
    out: dict[str, Any] = {
        "equity_curve": [],          # [[ts_global, pnl], ...]
        "products": {},              # sym → {ts, bid1, ask1, mid, our_bid, our_ask, fills, ...}
    }

    ts_offset = 0
    all_fills_global: list[dict] = []

    for day_data in json_days:
        day = day_data["day"]
        prices_df = _load_prices(prices_dir, day) if prices_dir else None

        # ── Equity curve ──────────────────────────────────────────────────────
        for ts, pnl in day_data.get("equity_curve", []):
            out["equity_curve"].append([ts + ts_offset, pnl])

        # ── Fills ─────────────────────────────────────────────────────────────
        for f in day_data.get("fills", []):
            all_fills_global.append({**f, "ts_global": f["timestamp"] + ts_offset, "day": day})

        # ── Quotes (our MM bid/ask, subsampled every 10 ticks) ────────────────
        quotes_by_sym: dict[str, list] = {}
        _quote_tick_count: dict[str, int] = {}
        for q in day_data.get("quotes", []):
            sym = q["symbol"]
            _quote_tick_count[sym] = _quote_tick_count.get(sym, 0) + 1
            if _quote_tick_count[sym] % 10 != 0:
                continue
            if sym not in quotes_by_sym:
                quotes_by_sym[sym] = []
            quotes_by_sym[sym].append({
                "ts": q["timestamp"] + ts_offset,
                "bid": q.get("bid"), "ask": q.get("ask"),
                "bid_size": q.get("bid_size", 0), "ask_size": q.get("ask_size", 0),
            })

        # ── Feature ticks (greeks, z-score, fair_iv, MidSmooth) ──────────────
        features_by_sym: dict[str, list] = {}
        for ft in day_data.get("feature_ticks", []):
            sym = ft["symbol"]
            if sym not in features_by_sym:
                features_by_sym[sym] = []
            features_by_sym[sym].append({**ft, "ts": ft["timestamp"] + ts_offset})

        # ── Market prices from CSV (subsampled every 10 ticks for HTML size) ──
        market_by_sym: dict[str, dict] = {}
        if prices_df is not None:
            for sym, grp in prices_df.groupby("product"):
                grp_s = grp.iloc[::10].reset_index(drop=True)  # every 10 ticks
                market_by_sym[sym] = {
                    "ts":   (grp_s["timestamp"] + ts_offset).tolist(),
                    "bid1": grp_s["bid_price_1"].tolist(),
                    "ask1": grp_s["ask_price_1"].tolist(),
                    "mid":  grp_s["mid_price"].tolist(),
                }

        # ── Underlying spot series (for Greek computation) ────────────────────
        spot_ts: list[int] = []
        spot_vals: list[float] = []
        if UNDERLYING in market_by_sym:
            spot_ts  = market_by_sym[UNDERLYING]["ts"]
            spot_vals = [
                (b + a) / 2 if (b and a and not math.isnan(b) and not math.isnan(a)) else None
                for b, a in zip(
                    market_by_sym[UNDERLYING]["bid1"],
                    market_by_sym[UNDERLYING]["ask1"],
                )
            ]

        # Fast spot lookup by timestamp
        spot_map: dict[int, float] = {}
        for ts, sv in zip(spot_ts, spot_vals):
            if sv is not None:
                spot_map[ts - ts_offset] = sv  # raw timestamp key

        # ── Per-product assembly ───────────────────────────────────────────────
        all_syms = set(quotes_by_sym) | set(features_by_sym) | set(market_by_sym)
        for sym in all_syms:
            if sym not in out["products"]:
                out["products"][sym] = {
                    "market": [], "quotes": [], "features": [],
                    "greeks": [], "smile_fair": [],
                }
            pd_out = out["products"][sym]
            pd_out["market"].extend(market_by_sym.get(sym, {}).get("ts") and [
                {"ts": t, "bid1": b, "ask1": a, "mid": m}
                for t, b, a, m in zip(
                    market_by_sym[sym]["ts"],
                    market_by_sym[sym]["bid1"],
                    market_by_sym[sym]["ask1"],
                    market_by_sym[sym]["mid"],
                )
            ] or [])
            pd_out["quotes"].extend(quotes_by_sym.get(sym, []))
            pd_out["features"].extend(features_by_sym.get(sym, []))

            # Compute per-tick Greeks for option products
            K = _opt_strike(sym)
            if K is not None and market_by_sym.get(sym):
                sym_mkt = market_by_sym[sym]
                for raw_ts, mid in zip(
                    [t - ts_offset for t in sym_mkt["ts"]],
                    sym_mkt["mid"],
                ):
                    if mid is None or (isinstance(mid, float) and math.isnan(mid)):
                        continue
                    S = spot_map.get(raw_ts)
                    if S is None or S <= 0:
                        continue
                    T = _tte(raw_ts, day)
                    try:
                        iv = call_implied_vol(mid, S, float(K), T, sigma_init=SIGMA_PRIOR)
                        sigma = iv if (iv and 0.001 < iv < 5.0) else SIGMA_PRIOR
                        pd_out["greeks"].append({
                            "ts":    raw_ts + ts_offset,
                            "delta": call_delta(S, float(K), T, sigma),
                            "gamma": call_gamma(S, float(K), T, sigma),
                            "vega":  call_vega(S, float(K), T, sigma),
                            "theta": call_theta(S, float(K), T, sigma),
                            "iv":    sigma,
                            "fair":  call_price(S, float(K), T, sigma),
                        })
                    except Exception:
                        pass

        # ── Smile fair value (cross-strike smile fit per tick, subsampled) ────
        if prices_df is not None and spot_map:
            opt_mids: dict[int, dict[int, float]] = {}  # raw_ts → {K: mid}
            for sym in OPTION_SYMS:
                K = _opt_strike(sym)
                if K is None or sym not in market_by_sym:
                    continue
                for raw_ts, mid in zip(
                    [t - ts_offset for t in market_by_sym[sym]["ts"]],
                    market_by_sym[sym]["mid"],
                ):
                    if mid and isinstance(mid, float) and not math.isnan(mid) and mid > 0:
                        opt_mids.setdefault(raw_ts, {})[K] = mid

            # Subsample every 50 ticks for performance
            sampled_ts = sorted(opt_mids.keys())[::50]
            for raw_ts in sampled_ts:
                S = spot_map.get(raw_ts)
                if S is None or S <= 0:
                    continue
                T = _tte(raw_ts, day)
                km = opt_mids[raw_ts]
                ivs: dict[int, float] = {}
                for K_val, mid in km.items():
                    intrinsic = max(0.0, S - K_val)
                    if mid <= intrinsic + 1.0:
                        continue
                    iv = call_implied_vol(mid, S, float(K_val), T, sigma_init=SIGMA_PRIOR)
                    if iv and 0.001 < iv < 5.0:
                        ivs[K_val] = iv
                if len(ivs) < 3:
                    continue
                coeffs = fit_smile_poly(list(ivs.keys()), list(ivs.values()), S, T)
                if coeffs is None:
                    continue
                for sym in OPTION_SYMS:
                    K_val = _opt_strike(sym)
                    if K_val is None:
                        continue
                    try:
                        smile_iv = smile_predict(float(K_val), coeffs, S, T)
                        fair = call_price(S, float(K_val), T, smile_iv)
                        if sym not in out["products"]:
                            out["products"][sym] = {"market": [], "quotes": [], "features": [], "greeks": [], "smile_fair": []}
                        out["products"][sym]["smile_fair"].append({
                            "ts": raw_ts + ts_offset, "smile_iv": smile_iv, "fair": fair,
                        })
                    except Exception:
                        pass

        # advance ts_offset
        max_ts = 0
        for ec in day_data.get("equity_curve", []):
            if ec[0] > max_ts:
                max_ts = ec[0]
        ts_offset += max_ts + 100

    # Attach fills to products
    for f in all_fills_global:
        sym = f["symbol"]
        if sym in out["products"]:
            out["products"][sym].setdefault("fills", []).append(f)
        else:
            out["products"][sym] = {"market": [], "quotes": [], "features": [], "greeks": [], "smile_fair": [], "fills": [f]}

    # Compute per-product cumulative inventory from fills
    for sym, pd_out in out["products"].items():
        fills = sorted(pd_out.get("fills", []), key=lambda x: x["ts_global"])
        inv = []
        pos = 0
        for f in fills:
            sign = 1 if f["side"] == "BUY" else -1
            pos += sign * f["quantity"]
            inv.append({"ts": f["ts_global"], "position": pos})
        pd_out["inventory"] = inv

    # Per-product MTM PnL: cash from fills + position × market mid at each market tick.
    # Realized-only would be permanently negative for accumulation strategies (long calls
    # never sold intraday). MTM shows the true economic PnL including open positions.
    for sym, pd_out in out["products"].items():
        fills = sorted(pd_out.get("fills", []), key=lambda x: x["ts_global"])
        mkt   = sorted(pd_out.get("market", []), key=lambda x: x["ts"])

        # Build cash timeline from fills
        cash_events: list[tuple[int, float]] = []
        cash = 0.0
        pos  = 0
        for f in fills:
            sign  = 1 if f["side"] == "BUY" else -1
            cash -= sign * f["quantity"] * f["price"]
            pos  += sign * f["quantity"]
            cash_events.append((f["ts_global"], cash, pos))

        if not mkt:
            # No market data: fallback to realized cash only
            pd_out["pnl_curve"] = [{"ts": ts, "mtm_pnl": c, "realized": c, "position": p}
                                    for ts, c, p in cash_events]
            continue

        # Merge: at each market tick, interpolate cash + position, compute MTM PnL
        pnl_curve: list[dict] = []
        c_idx = 0
        cash_cur, pos_cur = 0.0, 0
        for m in mkt:
            ts  = m["ts"]
            mid = m.get("mid")
            if mid is None or (isinstance(mid, float) and math.isnan(mid)):
                continue
            # Advance cash/position up to this timestamp
            while c_idx < len(cash_events) and cash_events[c_idx][0] <= ts:
                _, cash_cur, pos_cur = cash_events[c_idx]
                c_idx += 1
            mtm = cash_cur + pos_cur * mid
            pnl_curve.append({"ts": ts, "mtm_pnl": mtm, "realized": cash_cur, "position": pos_cur})

        pd_out["pnl_curve"] = pnl_curve

    # Compute portfolio-level underlying spread
    if UNDERLYING in out["products"]:
        mkt = out["products"][UNDERLYING]["market"]
        out["underlying_spread"] = [
            {"ts": r["ts"], "spread": r["ask1"] - r["bid1"]}
            for r in mkt
            if r.get("bid1") and r.get("ask1")
            and not math.isnan(r["bid1"]) and not math.isnan(r["ask1"])
        ]
    else:
        out["underlying_spread"] = []

    return out


# ── Portfolio Greeks ──────────────────────────────────────────────────────────

def _portfolio_greeks(series: dict, json_days: list[dict]) -> list[dict]:
    """Compute portfolio-level Greeks per global timestamp."""
    if not _HAS_NUMPY:
        return []

    # Build position per symbol per global timestamp (from fills)
    pos_by_sym: dict[str, dict[int, int]] = {}
    for sym, pd_out in series["products"].items():
        fills = sorted(pd_out.get("fills", []), key=lambda x: x["ts_global"])
        pos = 0
        last_ts = -1
        pos_map: dict[int, int] = {}
        for f in fills:
            sign = 1 if f["side"] == "BUY" else -1
            pos += sign * f["quantity"]
            pos_map[f["ts_global"]] = pos
            last_ts = f["ts_global"]
        pos_by_sym[sym] = pos_map

    def _get_pos(sym: str, ts: int) -> int:
        pm = pos_by_sym.get(sym, {})
        if not pm:
            return 0
        last = 0
        for t, p in sorted(pm.items()):
            if t <= ts:
                last = p
            else:
                break
        return last

    # Collect all timestamps from equity_curve
    ts_list = [ec[0] for ec in series["equity_curve"]][::50]  # subsample
    ts_offset = 0
    day_ts_map: dict[int, int] = {}
    for day_data in json_days:
        day = day_data["day"]
        for ec in day_data.get("equity_curve", []):
            raw_ts = ec[0]
            day_ts_map[raw_ts + ts_offset] = day
        max_ec = max((ec[0] for ec in day_data.get("equity_curve", [])), default=0)
        ts_offset += max_ec + 100

    portfolio: list[dict] = []
    for ts in ts_list:
        day = day_ts_map.get(ts, 0)
        row: dict = {"ts": ts, "delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}

        # VELVETFRUIT: delta = 1 per unit
        velvet_pos = _get_pos(UNDERLYING, ts)
        row["delta"] += velvet_pos

        # Options: delta, gamma, vega, theta via BS
        spot_mkt = series["products"].get(UNDERLYING, {}).get("market", [])
        S = None
        for m in reversed(spot_mkt):
            if m["ts"] <= ts and m.get("mid") and not math.isnan(m.get("mid", float("nan"))):
                S = m["mid"]
                break
        if S is None:
            continue

        # Estimate raw timestamp from global ts and day offset
        raw_ts_approx = ts % TS_PER_DAY
        T = _tte(raw_ts_approx, day)

        for sym in OPTION_SYMS:
            K = _opt_strike(sym)
            if K is None:
                continue
            pos = _get_pos(sym, ts)
            if pos == 0:
                continue
            try:
                sigma = SIGMA_PRIOR
                row["delta"] += pos * call_delta(S, float(K), T, sigma)
                row["gamma"] += pos * call_gamma(S, float(K), T, sigma)
                row["vega"]  += pos * call_vega(S, float(K), T, sigma)
                row["theta"] += pos * call_theta(S, float(K), T, sigma)
            except Exception:
                pass

        portfolio.append(row)
    return portfolio


# ── HTML generation ───────────────────────────────────────────────────────────

def _js_array(values: list, key: str | None = None) -> str:
    if key:
        return "[" + ",".join(
            "null" if (v is None or (isinstance(v, float) and not math.isfinite(v))) else str(round(v, 6))
            for item in values for v in [item.get(key)]
        ) + "]"
    return "[" + ",".join(
        "null" if (v is None or (isinstance(v, float) and not math.isfinite(v))) else str(round(v, 6))
        for v in values
    ) + "]"


def _js_ts(items: list, key: str = "ts") -> str:
    return "[" + ",".join(str(int(item[key])) for item in items) + "]"


_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.26.0.min.js"


def _summary_table_html(json_data: dict) -> str:
    """Big summary table: all products × all days + totals."""
    days = [d["day"] for d in json_data["days"]]
    products_seen: list[str] = []
    for d in json_data["days"]:
        for sym in d["product_summaries"]:
            if sym not in products_seen:
                products_seen.append(sym)

    def _ps(day_data: dict, sym: str) -> dict:
        return day_data["product_summaries"].get(sym, {})

    rows_html = []
    for sym in products_seen:
        color = PRODUCT_COLORS.get(sym, "#555")
        for i, d in enumerate(json_data["days"]):
            ps = _ps(d, sym)
            if not ps:
                continue
            rob = ps.get("robustness", {})
            pnl = ps.get("pnl", 0)
            pnl_cls = "pos" if pnl > 0 else ("neg" if pnl < 0 else "")
            rows_html.append(f"""
        <tr class="{'product-first' if i==0 else 'product-rest'}">
          <td style="border-left:4px solid {color}">{'<b>'+sym+'</b>' if i==0 else ''}</td>
          <td>Day {d['day']}</td>
          <td class="{pnl_cls}">{_fmt(pnl)}</td>
          <td>{_fmt(ps.get('trades'))}</td>
          <td>{_fmt(ps.get('traded_volume'))}</td>
          <td>{_fmt(ps.get('max_abs_position'))}</td>
          <td>{_fmt(ps.get('ending_position'))}</td>
          <td>{_fmt(rob.get('passive_qty'))}</td>
          <td>{_fmt(rob.get('aggressive_qty'))}</td>
          <td>{_fmt(rob.get('avg_abs_position_ratio'), 3)}</td>
        </tr>""")

    # Totals row
    total_pnl = json_data["summary"]["total_pnl"]
    tp_cls = "pos" if total_pnl > 0 else "neg"
    rob_total = json_data["summary"]["robustness"]
    dd = rob_total.get("max_drawdown")
    dd_str = _fmt(dd)

    return f"""
<div class="section" id="summary-section">
  <h2>Summary — All Products × All Days</h2>
  <p style="color:#888;font-size:0.85em">Max drawdown (chained): <b>{dd_str}</b></p>
  <table class="summary-table">
    <thead>
      <tr>
        <th>Product</th><th>Day</th><th>PnL</th><th>Trades</th>
        <th>Volume</th><th>Max pos</th><th>End pos</th>
        <th>Make</th><th>Take</th><th>Avg inv</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows_html)}
      <tr class="total-row">
        <td colspan="2"><b>TOTAL</b></td>
        <td class="{tp_cls}"><b>{_fmt(total_pnl)}</b></td>
        <td>{_fmt(rob_total.get('passive_trades',0) + rob_total.get('aggressive_trades',0))}</td>
        <td>{_fmt(rob_total.get('traded_volume'))}</td>
        <td>—</td><td>—</td>
        <td>{_fmt(rob_total.get('passive_qty'))}</td>
        <td>{_fmt(rob_total.get('aggressive_qty'))}</td>
        <td>{_fmt(rob_total.get('avg_abs_position_ratio'), 3)}</td>
      </tr>
    </tbody>
  </table>
</div>"""


def _product_charts_js(sym: str, pd_out: dict, portfolio_greeks: list[dict],
                        equity_curve: list, json_data: dict) -> str:
    """Generate the Plotly chart definitions for one product."""
    color = PRODUCT_COLORS.get(sym, "#1f77b4")
    K = _opt_strike(sym)
    is_option = K is not None

    mkt    = pd_out.get("market", [])
    quotes = pd_out.get("quotes", [])
    fills  = pd_out.get("fills", [])
    greeks = pd_out.get("greeks", [])
    smile  = pd_out.get("smile_fair", [])
    inv    = pd_out.get("inventory", [])
    pnl_c  = pd_out.get("pnl_curve", [])
    feats  = pd_out.get("features", [])

    # ── Fills split ────────────────────────────────────────────────────────
    buy_fills  = [f for f in fills if f["side"] == "BUY"]
    sell_fills = [f for f in fills if f["side"] == "SELL"]

    # ── Feature data ───────────────────────────────────────────────────────
    feat_ts    = [f["ts"] for f in feats]
    z_vals     = [f.get("z_velvet") or f.get("velvet_z") for f in feats]
    fair_iv_v  = [f.get("fair_iv") for f in feats]
    mode_vals  = [f.get("mode") for f in feats]
    mid_smooth = [f.get("MidSmooth") for f in feats]

    # ── Realized vol (20-tick rolling stdev of returns from market mid) ────
    rv_ts: list[int] = []
    rv_vals: list[float | None] = []
    if mkt and len(mkt) > 20:
        buf: list[float] = []
        for m in mkt:
            mid = m.get("mid")
            if mid and not math.isnan(mid):
                buf.append(mid)
            if len(buf) >= 2:
                rets = [buf[i] / buf[i-1] - 1 for i in range(max(1, len(buf)-20), len(buf))]
                if len(rets) >= 2:
                    mean_r = sum(rets) / len(rets)
                    var = sum((r - mean_r)**2 for r in rets) / (len(rets) - 1)
                    rv_ts.append(m["ts"])
                    rv_vals.append(var**0.5)

    # ── IV from computed greeks ────────────────────────────────────────────
    iv_ts   = [g["ts"] for g in greeks]
    iv_vals = [g.get("iv") for g in greeks]

    # ── Portfolio greeks vs product greeks ─────────────────────────────────
    pg_ts    = [g["ts"] for g in portfolio_greeks]
    pg_delta = [g["delta"] for g in portfolio_greeks]
    pg_gamma = [g["gamma"] for g in portfolio_greeks]
    pg_vega  = [g["vega"]  for g in portfolio_greeks]
    pg_theta = [g["theta"] for g in portfolio_greeks]

    prod_delta = [g["delta"] for g in greeks] if is_option else (
        [1.0 * (inv[0]["position"] if inv else 0)] * len(pg_ts))
    prod_gamma = [g["gamma"] for g in greeks]
    prod_vega  = [g["vega"]  for g in greeks]
    prod_theta = [g["theta"] for g in greeks]

    # ── Portfolio equity curve ─────────────────────────────────────────────
    eq_ts  = [ec[0] for ec in equity_curve]
    eq_pnl = [ec[1] for ec in equity_curve]

    # Build JS variable prefix
    vp = f"c_{sym.replace('-', '_').replace('.', '_')}"

    lines: list[str] = [f"""
    // ── {sym} ────────────────────────────────────────────────────────────

    var {vp}_mkt_ts    = {json.dumps([m['ts'] for m in mkt])};
    var {vp}_mkt_bid1  = {json.dumps([m.get('bid1') for m in mkt])};
    var {vp}_mkt_ask1  = {json.dumps([m.get('ask1') for m in mkt])};
    var {vp}_mkt_mid   = {json.dumps([m.get('mid') for m in mkt])};

    var {vp}_q_ts  = {json.dumps([q['ts'] for q in quotes])};
    var {vp}_q_bid = {json.dumps([q.get('bid') for q in quotes])};
    var {vp}_q_ask = {json.dumps([q.get('ask') for q in quotes])};

    var {vp}_buy_ts  = {json.dumps([f['ts_global'] for f in buy_fills])};
    var {vp}_buy_px  = {json.dumps([f['price'] for f in buy_fills])};
    var {vp}_sell_ts = {json.dumps([f['ts_global'] for f in sell_fills])};
    var {vp}_sell_px = {json.dumps([f['price'] for f in sell_fills])};

    var {vp}_smile_ts   = {json.dumps([s['ts'] for s in smile])};
    var {vp}_smile_fair = {json.dumps([s.get('fair') for s in smile])};

    var {vp}_inv_ts  = {json.dumps([i['ts'] for i in inv])};
    var {vp}_inv_pos = {json.dumps([i['position'] for i in inv])};

    var {vp}_rv_ts  = {json.dumps(rv_ts)};
    var {vp}_rv_val = {json.dumps(rv_vals)};
    var {vp}_iv_ts  = {json.dumps(iv_ts)};
    var {vp}_iv_val = {json.dumps(iv_vals)};

    var {vp}_greek_ts    = {json.dumps([g['ts'] for g in greeks])};
    var {vp}_prod_delta  = {json.dumps(prod_delta[:len(greeks)] if is_option else [])};
    var {vp}_prod_gamma  = {json.dumps(prod_gamma)};
    var {vp}_prod_vega   = {json.dumps(prod_vega)};
    var {vp}_prod_theta  = {json.dumps(prod_theta)};

    var {vp}_pg_ts    = {json.dumps(pg_ts)};
    var {vp}_pg_delta = {json.dumps(pg_delta)};
    var {vp}_pg_gamma = {json.dumps(pg_gamma)};
    var {vp}_pg_vega  = {json.dumps(pg_vega)};
    var {vp}_pg_theta = {json.dumps(pg_theta)};

    var {vp}_feat_ts    = {json.dumps(feat_ts)};
    var {vp}_z_vals     = {json.dumps(z_vals)};
    var {vp}_mode_vals  = {json.dumps(mode_vals)};
    var {vp}_midsmooth  = {json.dumps(mid_smooth)};

    var {vp}_pnl_ts   = {json.dumps([p['ts'] for p in pnl_c])};
    var {vp}_pnl_mtm  = {json.dumps([p.get('mtm_pnl') for p in pnl_c])};
    var {vp}_pnl_real = {json.dumps([p.get('realized') for p in pnl_c])};
    var {vp}_eq_ts    = {json.dumps(eq_ts)};
    var {vp}_eq_pnl   = {json.dumps(eq_pnl)};

    var {vp}_spread_ts  = {json.dumps([s['ts'] for s in pd_out.get('..spread', [])])};
    var {vp}_spread_val = {json.dumps([s.get('spread') for s in pd_out.get('..spread', [])])};
    """]  # end data definitions

    lines.append(f"""
    function plot_{vp}() {{

      var color = '{color}';
      var layout_base = {{
        plot_bgcolor: '#1e1e2e', paper_bgcolor: '#1e1e2e',
        font: {{color: '#cdd6f4', size: 11}},
        legend: {{bgcolor: 'rgba(0,0,0,0)', font: {{size: 10}}}},
        xaxis: {{gridcolor: '#313244', title: 'timestamp'}},
        yaxis: {{gridcolor: '#313244'}},
        margin: {{t: 30, b: 40, l: 60, r: 20}},
        hovermode: 'x unified',
      }};

      // ── 1. Price chart ───────────────────────────────────────────────────
      var traces_price = [
        {{x:{vp}_mkt_ts, y:{vp}_mkt_bid1, name:'Mkt bid', line:{{color:'#89b4fa',width:1}}, mode:'lines'}},
        {{x:{vp}_mkt_ts, y:{vp}_mkt_ask1, name:'Mkt ask', line:{{color:'#f38ba8',width:1}}, mode:'lines'}},
        {{x:{vp}_q_ts,   y:{vp}_q_bid,   name:'Our bid', line:{{color:'#74c7ec',width:1.5,dash:'dot'}}, mode:'lines'}},
        {{x:{vp}_q_ts,   y:{vp}_q_ask,   name:'Our ask', line:{{color:'#fab387',width:1.5,dash:'dot'}}, mode:'lines'}},
        {{x:{vp}_smile_ts, y:{vp}_smile_fair, name:'Smile fair', line:{{color:'#a6e3a1',width:2}}, mode:'lines'}},
        {{x:{vp}_midsmooth, y:{vp}_midsmooth, name:'Mid smooth', line:{{color:'#cba6f7',width:1.5}}, mode:'lines', visible: {'true' if sym == UNDERLYING else "'legendonly'"}}},
        {{x:{vp}_buy_ts,  y:{vp}_buy_px,  name:'Buy fill',  mode:'markers',
          marker:{{symbol:'triangle-up', color:'#a6e3a1', size:8}}}},
        {{x:{vp}_sell_ts, y:{vp}_sell_px, name:'Sell fill', mode:'markers',
          marker:{{symbol:'triangle-down', color:'#f38ba8', size:8}}}},
      ];
      Plotly.newPlot('{vp}_price', traces_price,
        Object.assign({{}}, layout_base, {{title: '{sym} — Price + Quotes + Fills',
          yaxis: {{title: 'price', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 2. Inventory ─────────────────────────────────────────────────────
      Plotly.newPlot('{vp}_inv', [
        {{x:{vp}_inv_ts, y:{vp}_inv_pos, name:'Position', fill:'tozeroy',
          line:{{color:color, width:2}}, mode:'lines'}}
      ], Object.assign({{}}, layout_base, {{title:'{sym} — Inventory',
        yaxis:{{title:'units', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 3. Vol (RV vs IV) ─────────────────────────────────────────────────
      Plotly.newPlot('{vp}_vol', [
        {{x:{vp}_rv_ts, y:{vp}_rv_val, name:'Realized vol (20-tick)', line:{{color:'#f38ba8',width:1.5}}, mode:'lines'}},
        {{x:{vp}_iv_ts, y:{vp}_iv_val, name:'Implied vol (BS)', line:{{color:'#a6e3a1',width:1.5}}, mode:'lines'}},
      ], Object.assign({{}}, layout_base, {{title:'{sym} — Vol: RV vs IV',
        yaxis:{{title:'daily vol', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 4. Delta ─────────────────────────────────────────────────────────
      Plotly.newPlot('{vp}_delta', [
        {{x:{vp}_greek_ts, y:{vp}_prod_delta, name:'{sym} delta', line:{{color:color,width:2}}, mode:'lines'}},
        {{x:{vp}_pg_ts, y:{vp}_pg_delta, name:'Portfolio delta', line:{{color:'#cba6f7',width:1.5,dash:'dash'}}, mode:'lines'}},
      ], Object.assign({{}}, layout_base, {{title:'{sym} — Delta (product + portfolio)',
        yaxis:{{title:'Δ units', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 5. Underlying spread (cost of delta hedge) ────────────────────────
      var uspread_sym = '{UNDERLYING}';
      Plotly.newPlot('{vp}_spread', [
        {{x:{vp}_mkt_ts, y:{vp}_mkt_ask1.map((a,i) => (a&&{vp}_mkt_bid1[i]) ? a - {vp}_mkt_bid1[i] : null),
          name:'{UNDERLYING} spread', fill:'tozeroy', line:{{color:'#fab387',width:1}}, mode:'lines'}},
      ], Object.assign({{}}, layout_base, {{title:'{UNDERLYING} spread — cost of delta hedge',
        yaxis:{{title:'bid-ask spread', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 6. Vega ──────────────────────────────────────────────────────────
      Plotly.newPlot('{vp}_vega', [
        {{x:{vp}_greek_ts, y:{vp}_prod_vega, name:'{sym} vega', line:{{color:color,width:2}}, mode:'lines'}},
        {{x:{vp}_pg_ts, y:{vp}_pg_vega, name:'Portfolio vega', line:{{color:'#cba6f7',width:1.5,dash:'dash'}}, mode:'lines'}},
      ], Object.assign({{}}, layout_base, {{title:'{sym} — Vega (product + portfolio)',
        yaxis:{{title:'vega', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 7. Gamma ─────────────────────────────────────────────────────────
      Plotly.newPlot('{vp}_gamma', [
        {{x:{vp}_greek_ts, y:{vp}_prod_gamma, name:'{sym} gamma', line:{{color:color,width:2}}, mode:'lines'}},
        {{x:{vp}_pg_ts, y:{vp}_pg_gamma, name:'Portfolio gamma', line:{{color:'#cba6f7',width:1.5,dash:'dash'}}, mode:'lines'}},
      ], Object.assign({{}}, layout_base, {{title:'{sym} — Gamma (product + portfolio)',
        yaxis:{{title:'γ', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 8. Theta ─────────────────────────────────────────────────────────
      Plotly.newPlot('{vp}_theta', [
        {{x:{vp}_greek_ts, y:{vp}_prod_theta, name:'{sym} theta', line:{{color:color,width:2}}, mode:'lines'}},
        {{x:{vp}_pg_ts, y:{vp}_pg_theta, name:'Portfolio theta', line:{{color:'#cba6f7',width:1.5,dash:'dash'}}, mode:'lines'}},
      ], Object.assign({{}}, layout_base, {{title:'{sym} — Theta (product + portfolio)',
        yaxis:{{title:'θ /tick', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 9. Z-score ───────────────────────────────────────────────────────
      Plotly.newPlot('{vp}_zscore', [
        {{x:{vp}_feat_ts, y:{vp}_z_vals, name:'z-score VELVET', line:{{color:'#89dceb',width:1.5}}, mode:'lines'}},
        {{x:{vp}_feat_ts, y:{vp}_mode_vals, name:'mode (1=acc,0=unwind,-1=skip)', line:{{color:'#f9e2af',width:1,dash:'dot'}}, mode:'lines', yaxis:'y2'}},
      ], Object.assign({{}}, layout_base, {{title:'{sym} — Z-score signal + mode',
        yaxis:{{title:'z', gridcolor:'#313244'}},
        yaxis2:{{title:'mode', overlaying:'y', side:'right', gridcolor:'#313244'}}}}), {{responsive:true}});

      // ── 10. PnL ──────────────────────────────────────────────────────────
      // MTM PnL = cash from fills + position × current mid  (the correct P&L)
      // Realized = cash from fills only (negative for accumulation strategies — ignore)
      Plotly.newPlot('{vp}_pnl', [
        {{x:{vp}_pnl_ts, y:{vp}_pnl_mtm,  name:'{sym} MTM PnL (cash + pos×mid)', line:{{color:color,width:2}}, mode:'lines'}},
        {{x:{vp}_pnl_ts, y:{vp}_pnl_real, name:'{sym} realized only (cash)', line:{{color:'#7f849c',width:1,dash:'dot'}}, mode:'lines'}},
        {{x:{vp}_eq_ts,  y:{vp}_eq_pnl,   name:'Portfolio equity', line:{{color:'#cba6f7',width:1.5,dash:'dash'}}, mode:'lines'}},
      ], Object.assign({{}}, layout_base, {{title:'{sym} — MTM PnL + Portfolio equity',
        yaxis:{{title:'PnL', gridcolor:'#313244'}}}}), {{responsive:true}});
    }}
    """)

    return "\n".join(lines)


def _product_panel_html(sym: str) -> str:
    vp = f"c_{sym.replace('-', '_').replace('.', '_')}"
    div_ids = ["price", "inv", "vol", "delta", "spread", "vega", "gamma", "theta", "zscore", "pnl"]
    chart_labels = [
        "Price + Quotes + Fills", "Inventory", "Vol (RV vs IV)",
        "Delta", "VELVETFRUIT Spread", "Vega", "Gamma", "Theta",
        "Z-score + Mode", "PnL",
    ]
    divs = "".join(
        f'<div class="chart-container"><div id="{vp}_{did}" class="chart"></div></div>\n'
        for did in div_ids
    )
    return f"""
<div id="panel_{vp}" class="product-panel" style="display:none">
  <h3 style="color:{PRODUCT_COLORS.get(sym,'#cdd6f4')}">{sym}</h3>
  {divs}
</div>"""


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'JetBrains Mono', monospace, sans-serif; background: #1e1e2e; color: #cdd6f4; }
h2 { color: #cba6f7; margin: 1em 0 0.5em; }
h3 { color: #89dceb; margin: 0.5em 0; }
.container { max-width: 1600px; margin: 0 auto; padding: 1em 2em; }
.section { margin-bottom: 2em; }
.summary-table { width: 100%; border-collapse: collapse; font-size: 0.82em; }
.summary-table th { background: #313244; padding: 6px 10px; text-align: right; color: #cba6f7; }
.summary-table th:first-child, .summary-table th:nth-child(2) { text-align: left; }
.summary-table td { padding: 5px 10px; border-bottom: 1px solid #313244; text-align: right; }
.summary-table td:first-child, .summary-table td:nth-child(2) { text-align: left; }
.product-first td { border-top: 2px solid #45475a; }
.total-row td { background: #313244; font-weight: bold; border-top: 2px solid #cba6f7; }
.pos { color: #a6e3a1; }
.neg { color: #f38ba8; }
.tab-bar { display: flex; flex-wrap: wrap; gap: 6px; margin: 1em 0; }
.tab-btn {
  padding: 6px 14px; border: 1px solid #45475a; border-radius: 6px;
  background: #313244; color: #cdd6f4; cursor: pointer; font-size: 0.82em;
  transition: background 0.2s;
}
.tab-btn:hover { background: #45475a; }
.tab-btn.active { background: #7f849c; border-color: #cba6f7; color: #cba6f7; font-weight: bold; }
.chart-container { margin-bottom: 1em; border-radius: 8px; overflow: hidden; }
.chart { height: 320px; }
"""

JS_TABS = """
function showPanel(sym) {
  document.querySelectorAll('.product-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  var vp = 'c_' + sym.replace(/-/g,'_').replace(/\\./g,'_');
  var panel = document.getElementById('panel_' + vp);
  if (panel) { panel.style.display = 'block'; }
  var btn = document.getElementById('btn_' + vp);
  if (btn) { btn.classList.add('active'); }
  // Lazy-init: call plot function if not already drawn
  var plotFn = window['plot_' + vp];
  if (plotFn && !panel.dataset.plotted) {
    plotFn();
    panel.dataset.plotted = '1';
  }
}
"""


def generate_html(json_data: dict, series: dict, portfolio_greeks: list[dict],
                  output_path: Path, strategy_name: str = "") -> None:
    # Only show products that were actually traded (have fills) or are the underlying
    active = {sym for sym, pd_out in series["products"].items() if pd_out.get("fills")}
    active.add(UNDERLYING)
    products = [p for p in [UNDERLYING] + OPTION_SYMS if p in active and p in series["products"]]
    for sym in series["products"]:
        if sym not in products and sym in active:
            products.append(sym)

    # Summary table
    summary_html = _summary_table_html(json_data)

    # Tab bar
    tab_bar = '<div class="tab-bar">'
    for sym in products:
        vp = f"c_{sym.replace('-', '_').replace('.', '_')}"
        col = PRODUCT_COLORS.get(sym, "#cdd6f4")
        tab_bar += f'<button class="tab-btn" id="btn_{vp}" onclick="showPanel(\'{sym}\')" style="border-color:{col}">{sym}</button>'
    tab_bar += "</div>"

    # Product panels HTML
    panels_html = "\n".join(_product_panel_html(sym) for sym in products)

    # JS data + chart functions
    js_charts = "\n".join(
        _product_charts_js(sym, series["products"][sym], portfolio_greeks,
                           series["equity_curve"], json_data)
        for sym in products
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Backtest Report — {strategy_name}</title>
  <script src="{_PLOTLY_CDN}"></script>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <h2 style="font-size:1.4em;margin-top:1em">Backtest Report — {strategy_name}</h2>

  {summary_html}

  <div class="section" id="product-section">
    <h2>Per-Product Charts</h2>
    {tab_bar}
    <div id="product-panels">
      {panels_html}
    </div>
  </div>
</div>

<script>
{JS_TABS}

{js_charts}

// Auto-open first product
(function() {{
  var first = document.querySelector('.tab-btn');
  if (first) first.click();
}})();
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path} ({output_path.stat().st_size:,} bytes)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate backtest HTML report")
    parser.add_argument("--json",   required=True, help="Backtest JSON from --json-out")
    parser.add_argument("--prices-dir", default=None,
                        help="Dir with prices_round_3_day_N.csv files (optional, enables market quotes + Greeks)")
    parser.add_argument("--out", default=None, help="Output HTML path")
    args = parser.parse_args()

    json_path = ROOT / args.json if not Path(args.json).is_absolute() else Path(args.json)
    json_data = json.loads(json_path.read_text(encoding="utf-8"))

    prices_dir = Path(args.prices_dir) if args.prices_dir else None
    if prices_dir and not prices_dir.is_absolute():
        prices_dir = ROOT / prices_dir

    strategy_name = json_data.get("strategy", json_path.stem)

    print(f"Processing {strategy_name} ({len(json_data['days'])} day(s)) ...")
    series = _build_series(json_data["days"], prices_dir)

    print("Computing portfolio Greeks ...")
    portfolio_greeks = _portfolio_greeks(series, json_data["days"])

    if args.out:
        out_path = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    else:
        out_path = json_path.with_suffix(".html")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    generate_html(json_data, series, portfolio_greeks, out_path, strategy_name)


if __name__ == "__main__":
    main()
