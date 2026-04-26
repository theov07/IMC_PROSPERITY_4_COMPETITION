"""Velvetfruit Extract + Vouchers — Round 3 Strategy Analysis

Run from repo root:
  python research/velvetfruit_options_analysis.py

Outputs:
  - Console: printed tables with FOR / AGAINST indicators per strategy
  - Plots:   artifacts/analysis/round_3/vev_*.png

Strategies evaluated:
  A. Passive MM on VELVETFRUIT_EXTRACT (baseline)
  B. Passive MM on options (current baseline, near-neutral)
  C. Long-vol delta-hedged (buy calls + short VELVETFRUIT hedge)
  D. Short-vol / sell calls + delta hedge (MM around theoretical fair)
  E. Smile arb (buy underpriced, sell overpriced strikes vega-neutral)
"""
from __future__ import annotations

import csv
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── path setup ─────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from prosperity.options.black_scholes import (
    call_delta, call_gamma, call_price, call_theta, call_vega,
)
from prosperity.options.implied_vol import call_implied_vol

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ── constants ──────────────────────────────────────────────────────────────────
DATA_DIR  = REPO_ROOT / "data" / "round_3"
OUT_DIR   = REPO_ROOT / "artifacts" / "analysis" / "round_3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STRIKES   = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMS  = [f"VEV_{k}" for k in STRIKES]
# TTE mapping: data day → time-to-expiry in days
TTE_MAP   = {0: 8.0, 1: 7.0, 2: 6.0}
# TTE at live submission (round 3 final):
TTE_LIVE  = 5.0
# Live slice: first 1000 ticks (ts 0 .. 99900 at step 100)
LIVE_TS_MAX = 99900
POS_LIMIT_VEV  = 300
POS_LIMIT_VELF = 200  # VELVETFRUIT_EXTRACT


# ── data loading ──────────────────────────────────────────────────────────────

def load_prices(day: int) -> Dict[str, List[Tuple[int, float, float, float]]]:
    """Return {product: [(ts, bid, ask, mid), ...]}."""
    path = DATA_DIR / f"prices_round_3_day_{day}.csv"
    result: Dict[str, List] = {}
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            prod = row["product"]
            ts   = int(row["timestamp"])
            mid  = float(row["mid_price"]) if row["mid_price"] else None
            b1   = row["bid_price_1"]
            a1   = row["ask_price_1"]
            bid  = float(b1) if b1 else None
            ask  = float(a1) if a1 else None
            if mid is None:
                continue
            result.setdefault(prod, []).append((ts, bid, ask, mid))
    return result


def load_trades(day: int) -> Dict[str, List[Tuple[int, float, int]]]:
    """Return {symbol: [(ts, price, qty), ...]}."""
    path = DATA_DIR / f"trades_round_3_day_{day}.csv"
    result: Dict[str, List] = {}
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            sym = row["symbol"]
            ts  = int(row["timestamp"])
            p   = float(row["price"])
            q   = int(row["quantity"])
            result.setdefault(sym, []).append((ts, p, q))
    return result


# ── statistics helpers ─────────────────────────────────────────────────────────

def returns(mids: List[float]) -> List[float]:
    return [math.log(mids[i] / mids[i - 1]) for i in range(1, len(mids)) if mids[i - 1] > 0]


def acf(series: List[float], lag: int) -> float:
    n = len(series)
    if n <= lag:
        return float("nan")
    mean = sum(series) / n
    var  = sum((x - mean) ** 2 for x in series) / n
    if var < 1e-14:
        return float("nan")
    cov = sum((series[i] - mean) * (series[i - lag] - mean) for i in range(lag, n)) / n
    return cov / var


def rolling_realized_vol(mids: List[float], window: int) -> List[float]:
    """Annualized daily vol over rolling window of log-returns."""
    rets = returns(mids)
    result = []
    for i in range(window - 1, len(rets)):
        chunk = rets[i - window + 1 : i + 1]
        mean  = sum(chunk) / len(chunk)
        var   = sum((x - mean) ** 2 for x in chunk) / max(len(chunk) - 1, 1)
        result.append(math.sqrt(var))  # per-tick vol (log-return std)
    return result


def ticks_to_daily_vol(tick_vol: float, ticks_per_day: int = 10000) -> float:
    """Convert per-tick log-return vol to per-day vol."""
    return tick_vol * math.sqrt(ticks_per_day)


def spread_stats(data: List[Tuple[int, float, float, float]]) -> dict:
    spreads = [a - b for _, b, a, _ in data if b is not None and a is not None and a > b]
    if not spreads:
        return {"mean": None, "median": None, "pct_one_tick": None}
    spreads.sort()
    n = len(spreads)
    return {
        "mean":         sum(spreads) / n,
        "median":       spreads[n // 2],
        "pct_one_tick": sum(1 for s in spreads if s <= 1) / n,
    }


# ── option analytics ──────────────────────────────────────────────────────────

def compute_iv(market_mid: float, S: float, K: float, T: float) -> Optional[float]:
    """IV with sensible init and fallback for deep ITM."""
    if market_mid <= 0 or T <= 0:
        return None
    intrinsic = max(0.0, S - K)
    if market_mid <= intrinsic + 0.5:
        return None  # near intrinsic — IV not meaningful
    sigma_init = 0.02  # 2% daily vol as starting guess
    return call_implied_vol(market_mid, S, K, T, sigma_init=sigma_init)


def greeks_table(S: float, K: int, T: float, sigma: float) -> dict:
    return {
        "delta": call_delta(S, K, T, sigma),
        "gamma": call_gamma(S, K, T, sigma),
        "vega":  call_vega(S, K, T, sigma),
        "theta": call_theta(S, K, T, sigma),
        "price": call_price(S, K, T, sigma),
    }


def vega_theta_ratio(vega: float, theta: float) -> Optional[float]:
    if theta >= 0 or vega <= 0:
        return None
    return -vega / theta  # positive when theta is negative (time decay)


def breakeven_vol(S: float, K: int, T: float, market_mid: float) -> Optional[float]:
    """Vol at which BS price = market mid (i.e. the implied vol)."""
    return compute_iv(market_mid, S, K, T)


def gamma_pnl_vs_theta(
    S: float, K: int, T: float, sigma_iv: float, realized_vol_daily: float
) -> dict:
    """Expected P&L breakdown for a 1-unit long call delta-hedged for 1 tick.

    Uses: gamma income = 0.5 * gamma * S^2 * realized_var_per_tick
          theta cost   = |theta_per_tick|

    Returns dict with daily projections (scaled to 10k ticks / full day).
    """
    g     = call_gamma(S, K, T, sigma_iv)
    th    = call_theta(S, K, T, sigma_iv)  # per day
    # Per tick: theta_per_tick = theta / ticks_per_day
    # realized_var_per_tick = (realized_vol_daily / sqrt(ticks_per_day))^2
    ticks_per_day = 10000
    sigma_tick    = realized_vol_daily / math.sqrt(ticks_per_day)
    gamma_per_tick = 0.5 * g * (S * sigma_tick) ** 2
    theta_per_tick = th / ticks_per_day          # theta is negative
    net_per_tick   = gamma_per_tick + theta_per_tick  # theta negative, so subtracts
    return {
        "gamma_daily":  gamma_per_tick * ticks_per_day,
        "theta_daily":  theta_per_tick * ticks_per_day,  # negative
        "net_daily":    net_per_tick   * ticks_per_day,
        "gamma_tick":   gamma_per_tick,
        "theta_tick":   theta_per_tick,
    }


# ── main analysis ─────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("  VELVETFRUIT + VOUCHERS — Round 3 Strategy Analysis")
    print("=" * 70)

    # ── 1. Load all data ───────────────────────────────────────────────────────
    prices_by_day  = {d: load_prices(d)  for d in [0, 1, 2]}
    trades_by_day  = {d: load_trades(d)  for d in [0, 1, 2]}

    # ── 2. VELVETFRUIT price dynamics ──────────────────────────────────────────
    print("\n── 1. VELVETFRUIT_EXTRACT PRICE DYNAMICS ─────────────────────────")
    for day in [0, 1, 2]:
        data = prices_by_day[day].get("VELVETFRUIT_EXTRACT", [])
        mids  = [m for _, _, _, m in data]
        ticks = len(mids)
        if ticks < 2:
            continue

        # Full-day realized vol
        rets = returns(mids)
        tick_vol = (sum(r**2 for r in rets) / max(len(rets)-1, 1)) ** 0.5
        daily_vol_full = ticks_to_daily_vol(tick_vol)

        # Live-slice realized vol (first 1000 ticks)
        live_data = [(ts, b, a, m) for ts, b, a, m in data if ts <= LIVE_TS_MAX]
        live_mids = [m for _, _, _, m in live_data]
        live_rets = returns(live_mids)
        live_tick_vol = (sum(r**2 for r in live_rets) / max(len(live_rets)-1, 1)) ** 0.5
        live_daily_vol = ticks_to_daily_vol(live_tick_vol)

        # ACF on tick returns
        acf1   = acf(rets, 1)
        acf_50 = acf([sum(rets[i:i+50]) for i in range(0, len(rets)-50, 50)], 1)
        acf_500= acf([sum(rets[i:i+500]) for i in range(0, len(rets)-500, 500)], 1)

        # Spread
        sp = spread_stats(data)

        # Range
        lo, hi = min(mids), max(mids)

        print(f"\n  Day {day}:")
        print(f"    Price range    : {lo:.1f} – {hi:.1f}  (range {hi-lo:.1f} ticks)")
        print(f"    Realized vol   : {daily_vol_full*100:.3f}%/day  (full day)")
        print(f"    Live-slice vol : {live_daily_vol*100:.3f}%/day  (first 1000 ticks)")
        print(f"    ACF(1) tick    : {acf1:+.4f}   ← negative = bid/ask bounce")
        print(f"    ACF(1) 50-tick : {acf_50:+.4f}")
        print(f"    ACF(1) 500-tick: {acf_500:+.4f}   ← negative = mean-reverting")
        print(f"    Spread mean    : {sp['mean']:.2f} ticks  |  median {sp['median']:.0f}  |  "
              f"1-tick {sp['pct_one_tick']*100:.0f}%")

    # ── 3. Option spread + liquidity ───────────────────────────────────────────
    print("\n── 2. OPTION LIQUIDITY & SPREAD ──────────────────────────────────")
    for day in [0, 1, 2]:
        tte = TTE_MAP[day]
        trade_data = trades_by_day[day]
        print(f"\n  Day {day}  (TTE={tte:.0f}d):")
        header = f"    {'Strike':>6}  {'Bid-Ask':>8}  {'Market':>8}  "
        header += f"{'Spread%':>7}  {'Volume':>7}  {'Trades':>7}"
        print(header)
        print("    " + "-" * 56)
        for K in STRIKES:
            sym  = f"VEV_{K}"
            data = prices_by_day[day].get(sym, [])
            if not data:
                continue
            # Snapshot at t=0 (first tick)
            ts0, b0, a0, m0 = data[0]
            sp_abs = (a0 - b0) if (a0 and b0) else None
            sp_pct = (sp_abs / m0 * 100) if (sp_abs and m0 > 0) else None
            vol_trades = sum(q for _, _, q in trade_data.get(sym, []))
            n_trades   = len(trade_data.get(sym, []))
            sp_str  = f"{sp_abs:.0f}"    if sp_abs is not None else "N/A"
            sp_p    = f"{sp_pct:.1f}%"  if sp_pct is not None else "N/A"
            print(f"    K={K:>5}: spread {sp_str:>4} ticks ({sp_p:>6})  "
                  f"mid={m0:>7.1f}  vol={vol_trades:>5}  n={n_trades:>5}")

    # ── 4. IV smile analysis ───────────────────────────────────────────────────
    print("\n── 3. IMPLIED VOLATILITY SMILE ───────────────────────────────────")
    iv_by_day: Dict[int, Dict[int, float]] = {}  # day -> strike -> iv

    for day in [0, 1, 2]:
        tte = TTE_MAP[day]
        print(f"\n  Day {day}  (TTE={tte:.0f}d):")
        ivs = {}

        # Get VELVETFRUIT series for sync'd S
        velf_data = prices_by_day[day].get("VELVETFRUIT_EXTRACT", [])
        # Build ts→S map for fast lookup
        ts_to_S = {ts: m for ts, _, _, m in velf_data}

        for K in STRIKES:
            sym  = f"VEV_{K}"
            data = prices_by_day[day].get(sym, [])
            if not data:
                continue

            # Compute IV for every tick where we have a matching S
            iv_list = []
            for ts, bid, ask, mid in data:
                S = ts_to_S.get(ts)
                if S is None:
                    continue
                iv = compute_iv(mid, S, K, tte)
                if iv is not None:
                    iv_list.append(iv)

            if not iv_list:
                print(f"    K={K:>5}: IV not computable (near intrinsic or bad data)")
                continue

            iv_mean = sum(iv_list) / len(iv_list)
            iv_std  = (sum((x - iv_mean)**2 for x in iv_list) / max(len(iv_list)-1, 1)) ** 0.5
            ivs[K]  = iv_mean

            print(f"    K={K:>5}: IV = {iv_mean*100:6.3f}%/day  ± {iv_std*100:.3f}%  "
                  f"(n={len(iv_list):,})")

        iv_by_day[day] = ivs

    # ── 5. IV vs realized vol comparison ──────────────────────────────────────
    print("\n── 4. IV vs REALIZED VOL (long-vol / short-vol signal) ───────────")
    rv_by_day: Dict[int, float] = {}

    for day in [0, 1, 2]:
        data = prices_by_day[day].get("VELVETFRUIT_EXTRACT", [])
        mids = [m for _, _, _, m in data]
        rets = returns(mids)
        tick_vol     = (sum(r**2 for r in rets) / max(len(rets)-1, 1)) ** 0.5
        daily_vol    = ticks_to_daily_vol(tick_vol)
        rv_by_day[day] = daily_vol

    print(f"\n  {'Day':>4}  {'RV daily':>10}  {'ATM IV (5000)':>14}  "
          f"{'RV/IV ratio':>11}  {'Signal':>12}")
    print("  " + "-" * 62)
    for day in [0, 1, 2]:
        rv   = rv_by_day[day]
        ivs  = iv_by_day.get(day, {})
        iv_atm = ivs.get(5000)
        ratio  = rv / iv_atm if iv_atm else None
        if ratio is not None:
            signal = "LONG VOL ✓" if ratio > 1.2 else ("SHORT VOL ✓" if ratio < 0.8 else "NEUTRAL")
        else:
            signal = "N/A"
        iv_str = f"{iv_atm*100:.3f}%"  if iv_atm else "N/A"
        ra_str = f"{ratio:.2f}x"        if ratio  else "N/A"
        print(f"  {day:>4}  {rv*100:>9.3f}%  {iv_str:>14}  {ra_str:>11}  {signal:>12}")

    # ── 6. Greeks table (at live TTE=5 and day-2 avg S/IV) ───────────────────
    print("\n── 5. GREEKS AT TTE=5d (LIVE ROUND) ─────────────────────────────")
    # Use day-2 snapshot as best proxy for live
    day2_velf = prices_by_day[2].get("VELVETFRUIT_EXTRACT", [])
    S_live = sum(m for _, _, _, m in day2_velf[:100]) / max(len(day2_velf[:100]), 1)
    rv_live = rv_by_day[2]
    iv_day2 = iv_by_day.get(2, {})

    print(f"\n  S (day-2 avg first 100 ticks) = {S_live:.1f}")
    print(f"  Realized vol (day-2) = {rv_live*100:.3f}%/day")
    print(f"  TTE live = {TTE_LIVE}d")
    print()
    print(f"  {'K':>6}  {'IV':>8}  {'BS(RV)':>8}  {'Market':>8}  "
          f"{'Misprice':>9}  {'Delta':>7}  {'Gamma':>8}  "
          f"{'Vega':>7}  {'Theta':>7}  {'V/T ratio':>10}  {'Net/day':>9}")
    print("  " + "-" * 110)

    long_vol_candidates = []
    mm_candidates       = []

    for K in STRIKES:
        sym   = f"VEV_{K}"
        data2 = prices_by_day[2].get(sym, [])
        if not data2:
            continue

        # Market mid (first 100 tick average for stability)
        market_mid = sum(m for _, _, _, m in data2[:100]) / max(len(data2[:100]), 1)

        # Compute IV from market mid at TTE=5
        iv_from_market = iv_day2.get(K)  # from day-2 at TTE=6

        # Fallback: compute IV at TTE=5 from day2 market mid
        iv_live = compute_iv(market_mid, S_live, K, TTE_LIVE)
        sigma_use = iv_live or iv_from_market or rv_live

        bs_rv  = call_price(S_live, K, TTE_LIVE, rv_live)
        g      = greeks_table(S_live, K, TTE_LIVE, sigma_use)
        vt     = vega_theta_ratio(g["vega"], g["theta"])
        misprice = market_mid - bs_rv  # positive = option overpriced vs RV

        # Gamma PnL analysis
        gp = gamma_pnl_vs_theta(S_live, K, TTE_LIVE, sigma_use, rv_live)

        iv_str = f"{sigma_use*100:.2f}%" if sigma_use else "N/A"
        vt_str = f"{vt:.1f}" if vt else "N/A"
        print(
            f"  K={K:>5}: iv={iv_str:>7}  bs={bs_rv:>7.1f}  mkt={market_mid:>7.1f}  "
            f"mis={misprice:>+8.1f}  "
            f"d={g['delta']:>6.3f}  γ={g['gamma']:>7.4f}  "
            f"v={g['vega']:>6.1f}  θ={g['theta']:>6.1f}  "
            f"v/t={vt_str:>9}  net={gp['net_daily']:>+8.1f}"
        )

        # Classify candidates
        if gp["net_daily"] > 0 and g["delta"] < 0.95:
            long_vol_candidates.append((K, gp["net_daily"], g["delta"]))
        if abs(misprice) < 5 and g["delta"] < 0.95:
            mm_candidates.append((K, misprice))

    # ── 7. Delta-hedge capacity analysis ──────────────────────────────────────
    print("\n── 6. DELTA-HEDGE CAPACITY (calls only, short VELVETFRUIT) ───────")
    print(f"\n  VELVETFRUIT_EXTRACT position limit: {POS_LIMIT_VELF}")
    print(f"  VEV position limit per strike:       {POS_LIMIT_VEV}")
    print()
    print(f"  {'K':>6}  {'Delta':>7}  {'Max contracts':>14}  "
          f"{'VELF needed':>12}  {'Within limit?':>13}  {'Residual cap':>12}")
    print("  " + "-" * 78)

    for K in STRIKES:
        d = call_delta(S_live, K, TTE_LIVE, rv_live)
        max_contracts = min(POS_LIMIT_VEV, int(POS_LIMIT_VELF / max(d, 0.01)))
        velf_needed   = int(max_contracts * d)
        within = velf_needed <= POS_LIMIT_VELF
        residual_velf = POS_LIMIT_VELF - velf_needed
        print(f"  K={K:>5}: δ={d:>6.3f}  max_qty={max_contracts:>6}  "
              f"velf_short={velf_needed:>5}  {'YES' if within else 'NO':>13}  "
              f"residual={residual_velf:>5}")

    # ── 8. Smile deviation (arb signal) ───────────────────────────────────────
    print("\n── 7. SMILE DEVIATION FROM POLYNOMIAL FIT ────────────────────────")

    for day in [0, 1, 2]:
        ivs = iv_by_day.get(day, {})
        S_d = sum(m for _, _, _, m in prices_by_day[day].get("VELVETFRUIT_EXTRACT", [])[:100]) / 100.0

        valid = [(K, iv) for K, iv in ivs.items() if 4500 <= K <= 5500]
        if len(valid) < 3:
            continue

        # Fit quadratic in log-moneyness  x = log(K/S)
        xs = [math.log(K / S_d) for K, _ in valid]
        ys = [iv for _, iv in valid]
        n  = len(xs)
        # least-squares quadratic: y = a*x^2 + b*x + c
        A = [[xi**2, xi, 1.0] for xi in xs]
        # Normal equations (small system, solve directly)
        def mat_mult(A, B):
            n_, m_ = len(A), len(A[0])
            p_ = len(B[0])
            C = [[sum(A[i][k] * B[k][j] for k in range(m_)) for j in range(p_)] for i in range(n_)]
            return C
        def mat_vec(A, v):
            return [sum(A[i][j] * v[j] for j in range(len(v))) for i in range(len(A))]
        AT    = [[A[j][i] for j in range(n)] for i in range(3)]
        ATA   = mat_mult(AT, A)
        ATy   = mat_vec(AT, ys)
        # Solve 3x3 system via Cramer's rule
        def det3(M):
            a,b,c,d,e,f,g,h,i_ = M[0][0],M[0][1],M[0][2],M[1][0],M[1][1],M[1][2],M[2][0],M[2][1],M[2][2]
            return a*(e*i_ - f*h) - b*(d*i_ - f*g) + c*(d*h - e*g)
        def replace_col(M, v, col):
            R = [row[:] for row in M]
            for i in range(len(R)):
                R[i][col] = v[i]
            return R
        D  = det3(ATA)
        if abs(D) < 1e-20:
            continue
        pa = det3(replace_col(ATA, ATy, 0)) / D
        pb = det3(replace_col(ATA, ATy, 1)) / D
        pc = det3(replace_col(ATA, ATy, 2)) / D

        print(f"\n  Day {day}  (S≈{S_d:.1f}, fit: IV = {pa:.4f}·x² + {pb:.4f}·x + {pc:.4f})")
        print(f"  {'K':>6}  {'Market IV':>10}  {'Fitted IV':>10}  "
              f"{'Deviation':>10}  {'Signal':>16}")
        print("  " + "-" * 62)

        for K in STRIKES:
            iv_market = ivs.get(K)
            if iv_market is None:
                continue
            x_k = math.log(K / S_d)
            iv_fit = pa * x_k**2 + pb * x_k + pc
            dev   = iv_market - iv_fit
            dev_pct = dev / iv_fit * 100 if iv_fit > 0 else None
            if dev_pct is not None:
                signal = "BUY (cheap vol)" if dev_pct < -5 else \
                         ("SELL (rich vol)" if dev_pct > 5 else "NEUTRAL")
            else:
                signal = "N/A"
            dp_str = f"{dev_pct:+.1f}%" if dev_pct is not None else "N/A"
            print(f"  K={K:>5}: mkt={iv_market*100:>7.3f}%  fit={iv_fit*100:>7.3f}%  "
                  f"dev={dp_str:>9}  {signal:>16}")

    # ── 9. Strategy summary ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  STRATEGY INDICATORS SUMMARY")
    print("=" * 70)

    # Aggregate signals
    rv_avg    = sum(rv_by_day.values()) / 3
    iv_atm_avg = sum(iv_by_day[d].get(5000, 0.015) for d in [0,1,2]) / 3
    rv_iv_ratio = rv_avg / iv_atm_avg if iv_atm_avg > 0 else 1.0

    velf_day2 = prices_by_day[2].get("VELVETFRUIT_EXTRACT", [])
    sp2 = spread_stats(velf_day2)

    # Live-slice: how much does VELVETFRUIT actually move in first 1000 ticks?
    live_data2 = [(ts, b, a, m) for ts, b, a, m in velf_day2 if ts <= LIVE_TS_MAX]
    live_mids2 = [m for _, _, _, m in live_data2]
    live_rv    = ticks_to_daily_vol(
        (sum(r**2 for r in returns(live_mids2)) / max(len(returns(live_mids2))-1, 1)) ** 0.5
    )

    print(f"""
  Key numbers (averages across 3 days):
    VELVETFRUIT realized vol (full day) : {rv_avg*100:.3f}%/day
    VELVETFRUIT realized vol (live 1k)  : {live_rv*100:.3f}%/day  ← only first 1000 ticks matter for submission
    ATM IV (VEV_5000)                   : {iv_atm_avg*100:.3f}%/day
    RV/IV ratio                         : {rv_iv_ratio:.2f}x
    VELVETFRUIT spread (day-2)          : {sp2['mean']:.2f} ticks mean  |  {sp2['pct_one_tick']*100:.0f}% at 1-tick
""")

    strategies = [
        {
            "name": "A. Passive MM on VELVETFRUIT",
            "for":  [
                f"Tight spread: {sp2['mean']:.1f} ticks avg ({sp2['pct_one_tick']*100:.0f}% @ 1-tick) → easy to penny-improve",
                "ACF(1) tick <0 = bid/ask bounce → passive fills at ticked spread are profitable",
                "~15k/day in existing backtest (r3_naive_champion)",
                "No delta-hedge complexity, no options exposure",
            ],
            "against": [
                "Queue priority bottleneck: 50x gap backtest vs live (same problem as HYDROGEL)",
                "Low RV may mean few big moves to capture inventory turns",
            ],
            "verdict": "STRONG BASELINE — always include",
        },
        {
            "name": "B. Passive MM on options (current baseline)",
            "for":  [
                "Near-neutral PnL, no directional risk",
                "Captures bid/ask spread on options (spreads are 1-4 ticks, 1-5%)",
                "Oracle made 20k+ on VEV_5000 and VEV_5100 in live slice (primarily via MM volume)",
            ],
            "against": [
                "Adverse selection: informed traders know BS mispricing, you don't",
                "Near-neutral in backtest today (not contributing meaningful PnL)",
                "Need to MM all 10 strikes → traderData size pressure",
            ],
            "verdict": "KEEP but add BS-fair-aware pricing to tighten edge",
        },
        {
            "name": "C. Long-vol: buy calls + delta-hedge (short VELVETFRUIT)",
            "for":  [
                f"RV/IV ≈ {rv_iv_ratio:.2f}x → realized vol > implied vol = long-gamma income > theta cost",
                "Calls only (no puts needed): buy call, short VELVETFRUIT for delta hedge",
                "Best strikes: K=5000–5300 (high vega, meaningful gamma)",
                "Position limit allows: K=5300 (delta~0.4) → up to 200/0.4=500 but capped at 300",
            ],
            "against": [
                f"Live slice vol ({live_rv*100:.3f}%/day in first 1000 ticks) may be lower than full-day RV",
                "Theta bleeds every tick — if VELVETFRUIT is quiet in the live window, loss",
                "Calls only = long delta before hedging, need active rehedging per tick",
                "Delta-hedge consumes VELVETFRUIT sell capacity (limit 200 shared with MM hedge)",
                "Queue: hard to get option fills passively; aggressive fill is expensive",
            ],
            "verdict": "CONDITIONAL — profitable only if VELVETFRUIT moves in live slice; risky if quiet",
        },
        {
            "name": "D. Short-vol: sell calls (BS-fair aware MM skewed to sell side)",
            "for":  [
                "If options are consistently overpriced vs RV, selling collects premium",
                "Oracle ended SHORT VEV_5000–5200 in live slice and made the most PnL",
                "Theta works for you (collect premium as time passes)",
                "Don't need to delta-hedge if you only sell small size",
            ],
            "against": [
                f"RV/IV = {rv_iv_ratio:.2f}x → options are UNDERPRICED vs realized vol in theory",
                "Unlimited loss if VELVETFRUIT has a large move (naked short calls)",
                "Must delta-hedge or accept gap risk",
                "Deep ITM calls (K=4000, 4500) have delta≈1 — short call = short underlying, lots of risk",
            ],
            "verdict": "RISKY without hedge, but the oracle data suggests market SELLS calls profitably",
        },
        {
            "name": "E. Smile arb: long cheap strikes, short rich strikes",
            "for":  [
                "Pure vol structure play, direction-neutral",
                "Vega-neutral spread = no gamma/theta exposure",
            ],
            "against": [
                "Smile appears relatively stable and consistent — few persistent outliers",
                "Spread costs eat arb spread at small scale",
                "Complex to size correctly under position limits",
                "3 days of data is very little to identify reliable smile mispricings",
            ],
            "verdict": "LOW PRIORITY — not enough evidence of stable mispricing",
        },
    ]

    for s in strategies:
        print(f"\n  ── {s['name']}")
        print(f"     Verdict: {s['verdict']}")
        print("     FOR:")
        for f in s["for"]:
            print(f"       + {f}")
        print("     AGAINST:")
        for a in s["against"]:
            print(f"       - {a}")

    print("\n" + "=" * 70)
    print("  RECOMMENDED NEXT STEPS")
    print("=" * 70)
    print("""
  1. Always run Strategy A (VELVETFRUIT passive MM) — it's the proven baseline.

  2. Improve Option MM (B): instead of penny-improving around market mid,
     price around BS_fair(rolling_IV_avg) rather than book mid. This avoids
     being adversely selected on options that are repricing.

  3. Test a small Long-vol overlay (C): buy 10–20 units of K=5100 or K=5200
     (mid delta, high vega), delta-hedge tightly with VELVETFRUIT.
     Gate it behind a vol signal: only activate if rolling_IV < rolling_RV * 0.9.
     The risk is theta in quiet windows.

  4. Investigate why oracle ends SHORT options: run a tick-by-tick analysis of
     VEV_5000/5100/5200 option mid vs BS_fair over the day to see if options
     get expensive later in the day (after initial quiet). That would justify
     a SELL call overlay later in the session.

  5. Check live-slice ACF for VELVETFRUIT: if ACF is negative in first 1000 ticks,
     passive MM alone with tight spread will outperform complex option plays.
""")

    # ── 10. Plots ──────────────────────────────────────────────────────────────
    _plot_smile(iv_by_day, rv_by_day)
    _plot_velvetfruit_dynamics(prices_by_day, rv_by_day)
    _plot_option_spreads(prices_by_day)
    _plot_greeks_surface(S_live, TTE_LIVE, rv_live, iv_by_day.get(2, {}))
    print(f"\n  Plots saved to: {OUT_DIR}")


# ── plotting ───────────────────────────────────────────────────────────────────

def _plot_smile(
    iv_by_day: Dict[int, Dict[int, float]],
    rv_by_day: Dict[int, float],
) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    fig.suptitle("Implied Vol Smile vs Realized Vol — VELVETFRUIT Vouchers", fontsize=12)
    colors = ["steelblue", "darkorange", "seagreen"]
    for i, day in enumerate([0, 1, 2]):
        ax    = axes[i]
        ivs   = iv_by_day.get(day, {})
        rv    = rv_by_day.get(day, 0.015)
        ks    = sorted(ivs.keys())
        iv_vals = [ivs[k] * 100 for k in ks]
        ax.plot(ks, iv_vals, "o-", color=colors[i], label="Implied vol", linewidth=2, markersize=5)
        ax.axhline(rv * 100, color="crimson", linestyle="--", linewidth=1.5, label=f"Realized vol {rv*100:.2f}%")
        ax.set_title(f"Day {day}  (TTE={TTE_MAP[day]:.0f}d)")
        ax.set_xlabel("Strike K")
        ax.set_ylabel("Vol (%/day)" if i == 0 else "")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax.axvline(5250, color="gray", linestyle=":", alpha=0.6, label="S≈5250 (ATM)")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "vev_iv_smile.png", dpi=120)
    plt.close()


def _plot_velvetfruit_dynamics(
    prices_by_day: Dict[int, Dict],
    rv_by_day: Dict[int, float],
) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    fig.suptitle("VELVETFRUIT_EXTRACT Price Dynamics", fontsize=12)
    for i, day in enumerate([0, 1, 2]):
        data  = prices_by_day[day].get("VELVETFRUIT_EXTRACT", [])
        tss   = [ts for ts, _, _, _ in data]
        mids  = [m  for _, _, _, m  in data]
        rets  = returns(mids)

        # Price path
        ax = axes[0][i]
        ax.plot(tss, mids, linewidth=0.7, color="steelblue")
        ax.set_title(f"Day {day} — mid price (RV={rv_by_day[day]*100:.2f}%/day)")
        ax.set_xlabel("Timestamp")
        ax.set_ylabel("Price" if i == 0 else "")
        ax.axvline(LIVE_TS_MAX, color="red", linestyle="--", alpha=0.6, label="Live cutoff")
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

        # Rolling vol
        ax2 = axes[1][i]
        win = 500
        rvs = rolling_realized_vol(mids, win)
        rvs_daily = [ticks_to_daily_vol(v) * 100 for v in rvs]
        ax2.plot(tss[win:], rvs_daily, linewidth=0.8, color="darkorange", label=f"Rolling {win}-tick RV")
        ax2.set_title(f"Day {day} — rolling {win}-tick realized vol")
        ax2.set_xlabel("Timestamp")
        ax2.set_ylabel("Vol (%/day)" if i == 0 else "")
        ax2.axvline(LIVE_TS_MAX, color="red", linestyle="--", alpha=0.6)
        ax2.legend(fontsize=7)
        ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT_DIR / "vev_velvetfruit_dynamics.png", dpi=120)
    plt.close()


def _plot_option_spreads(prices_by_day: Dict[int, Dict]) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("Option Bid-Ask Spreads by Strike — Round 3", fontsize=12)
    for i, day in enumerate([0, 1, 2]):
        ax = axes[i]
        ks, sps_abs, sps_pct, mids = [], [], [], []
        for K in STRIKES:
            data = prices_by_day[day].get(f"VEV_{K}", [])
            if not data:
                continue
            spreads = [a - b for _, b, a, _ in data if b and a and a > b]
            mid_vals = [m for _, _, _, m in data]
            if not spreads or not mid_vals:
                continue
            sp_mean  = sum(spreads) / len(spreads)
            mid_mean = sum(mid_vals) / len(mid_vals)
            ks.append(K)
            sps_abs.append(sp_mean)
            sps_pct.append(sp_mean / mid_mean * 100 if mid_mean > 0 else 0)
            mids.append(mid_mean)
        ax.bar([str(k) for k in ks], sps_pct, color="steelblue", alpha=0.7)
        ax.set_title(f"Day {day} — spread (% of mid)")
        ax.set_xlabel("Strike")
        ax.set_ylabel("Spread % of mid" if i == 0 else "")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "vev_option_spreads.png", dpi=120)
    plt.close()


def _plot_greeks_surface(
    S: float, T: float, rv: float, iv_day2: Dict[int, float]
) -> None:
    fig = plt.figure(figsize=(14, 8))
    fig.suptitle(f"Greeks at TTE={T}d, S={S:.0f} — using realized vol {rv*100:.2f}%", fontsize=11)
    gs = gridspec.GridSpec(2, 3, figure=fig)

    greek_names = ["delta", "gamma", "vega", "theta"]
    greek_labels = ["Delta (dC/dS)", "Gamma (d²C/dS²)", "Vega (dC/dσ)", "Theta (dC/dt)"]
    positions = [(0, 0), (0, 1), (0, 2), (1, 0)]

    ks_plot = [k for k in STRIKES if 4500 <= k <= 6000]
    for (r_, c_), gname, glabel in zip(positions, greek_names, greek_labels):
        ax = fig.add_subplot(gs[r_, c_])
        vals_rv = [greeks_table(S, K, T, rv)[gname] for K in ks_plot]
        ax.plot(ks_plot, vals_rv, "o-", color="steelblue", label=f"σ=RV({rv*100:.2f}%)", linewidth=2)

        # Also plot at market IV if available
        if iv_day2:
            vals_iv = []
            for K in ks_plot:
                iv = iv_day2.get(K, rv)
                vals_iv.append(greeks_table(S, K, T, iv)[gname])
            ax.plot(ks_plot, vals_iv, "s--", color="darkorange", label="σ=market IV", linewidth=1.5)

        ax.set_title(glabel, fontsize=9)
        ax.set_xlabel("Strike K", fontsize=8)
        ax.axvline(S, color="gray", linestyle=":", alpha=0.6)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    # Net daily P&L for long-vol (gamma - theta) per unit
    ax_net = fig.add_subplot(gs[1, 1])
    net_vals = []
    for K in ks_plot:
        gp = gamma_pnl_vs_theta(S, K, T, call_delta(S, K, T, rv), rv)  # use rv as sigma
        net_vals.append(gp["net_daily"])
    colors_net = ["green" if v > 0 else "red" for v in net_vals]
    ax_net.bar(ks_plot, net_vals, color=colors_net, alpha=0.7)
    ax_net.axhline(0, color="black", linewidth=0.8)
    ax_net.set_title("Long-vol net daily P&L (gamma - theta)", fontsize=9)
    ax_net.set_xlabel("Strike K", fontsize=8)
    ax_net.set_ylabel("P&L per unit per day", fontsize=8)
    ax_net.grid(alpha=0.3, axis="y")

    # Delta hedge cost (VELVETFRUIT units needed per option)
    ax_dh = fig.add_subplot(gs[1, 2])
    deltas = [call_delta(S, K, T, rv) for K in ks_plot]
    max_qty = [min(POS_LIMIT_VEV, int(POS_LIMIT_VELF / max(d, 0.01))) for d in deltas]
    ax_dh.bar(ks_plot, max_qty, color="steelblue", alpha=0.7)
    ax_dh.set_title("Max long-vol size (delta-hedge within VELF limit=200)", fontsize=9)
    ax_dh.set_xlabel("Strike K", fontsize=8)
    ax_dh.set_ylabel("Max contracts", fontsize=8)
    ax_dh.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(OUT_DIR / "vev_greeks_surface.png", dpi=120)
    plt.close()


if __name__ == "__main__":
    main()
