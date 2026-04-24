"""Analyze R2 active field — the actual denominator for MAF median.

Data source: 3,065 de-duplicated trader.py submissions from the open-source
IMC R2 backtest leaderboard aggregator (see data/r2_backtest_leaderboard_aggregate.json).

Key insight: this is the REAL denominator for the MAF median (n=3065),
not our earlier guess of 3000. Teams without trader.py are ignored by IMC.

Converts:
    - PnL distribution (simu-test units) → V distribution (V = v_ratio × PnL)
    - PnL finale units (× 8.9 scaling)
    - Identifies where our team sits (rank 34, 98.9%)

Usage:
    python research/round_2_MAF/10_r2_field_analysis.py
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def lognormal_fit(median: float, p25: float, p75: float):
    """Fit a log-normal from median + IQR. Returns (mu, sigma) of log."""
    mu = math.log(median)
    # IQR for log-normal: exp(mu + 0.6745 sigma) - exp(mu - 0.6745 sigma)
    # Easier: use log(p75/p25) = 2 × 0.6745 × sigma → sigma = log(p75/p25) / 1.349
    sigma = math.log(p75 / p25) / 1.349
    return mu, sigma


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v-ratio", type=float, default=0.122,
                    help="V per team ≈ v_ratio × PnL_test (default 12.2% from our measurement)")
    ap.add_argument("--finale-scaling", type=float, default=8.9)
    args = ap.parse_args()

    with open(DATA / "r2_backtest_leaderboard_aggregate.json") as f:
        agg = json.load(f)

    n = agg["n_entries_total"]
    med = agg["median_pnl"]
    mean = agg["mean_pnl"]
    p25 = agg["p25_pnl"]
    p75 = agg["p75_pnl"]
    std = agg["pnl_std_dev"]
    top10 = agg["top_10_cutoff_pnl"]
    pct_profit = agg["pct_profitable"]
    low_outliers = agg["outliers_low"]
    scale = args.finale_scaling
    vr = args.v_ratio

    print("═" * 78)
    print("R2 ACTIVE FIELD ANALYSIS")
    print("═" * 78)
    print(f"Source: {agg['source']}")
    print(f"Unit: {agg['unit']}  (×{scale} for finale)")
    print()
    print(f"Total submitted trader.py:      n = {n:,}")
    print(f"  → This IS the MAF denominator (teams without trader.py excluded by IMC)")
    print()

    print("━━━ PnL distribution (simu-test units) ━━━")
    print(f"  % profitable     = {pct_profit:.1f}%")
    print(f"  mean             = {mean:,.0f}")
    print(f"  median           = {med:,.0f}")
    print(f"  p25 / p75        = {p25:,.0f} / {p75:,.0f}")
    print(f"  std              = {std:,.0f}")
    print(f"  top-10 cutoff    = {top10:,.0f}  (99.7%-ile)")
    print(f"  low outliers     = {low_outliers} (worst -90k)")
    print()

    print(f"━━━ PnL distribution (finale units ×{scale}) ━━━")
    print(f"  median           = {med*scale:,.0f}")
    print(f"  p25 / p75        = {p25*scale:,.0f} / {p75*scale:,.0f}")
    print(f"  top-10 cutoff    = {top10*scale:,.0f}")
    print()

    # V proxy linear model
    print(f"━━━ V distribution (linear proxy V = {vr:.1%} × PnL) ━━━")
    print(f"  median V (test)      = {med*vr:,.0f}  |  finale = {med*vr*scale:,.0f}")
    print(f"  p25 V (finale)       = {p25*vr*scale:,.0f}")
    print(f"  p75 V (finale)       = {p75*vr*scale:,.0f}")
    print(f"  top-10 V (finale)    = {top10*vr*scale:,.0f}")
    print(f"  our V (measured)     = 11,194 finale   (rank 34, ~top 1%)")
    print()

    # Critical ratio: what fraction of field has V higher than us?
    # From aggregate, we know our PnL ~10,300 → rank 34
    # Teams above us have PnL >= ~10,300 → V_test >= ~1,257
    n_above_us = int(n * (100 - 98.9) / 100)
    print(f"━━━ Teams with V comparable or higher than ours (top 1%) ━━━")
    print(f"  ~{n_above_us} teams (rank ≤ 34) have PnL ≥ ours → V ≥ ~11,194 finale")
    print(f"  These are the 'strong rationals' who could theoretically outbid us")
    print()

    # V non-linear: weak teams probably have V ≈ 0 (buy-hold doesn't benefit from MAF)
    # Let's compute with a thresholded V model: V = max(0, vr × (PnL − PnL_threshold))
    print("━━━ Alternative V model (thresholded, more realistic) ━━━")
    for threshold_pct in [0, 25, 50, 75]:
        if threshold_pct == 0: thresh = 0
        elif threshold_pct == 25: thresh = p25
        elif threshold_pct == 50: thresh = med
        else: thresh = p75
        # Approx mean V: sum over bins (using median/p25/p75/top10 as proxies)
        reprs = [(0.25, (p25+0)/2), (0.25, (med+p25)/2), (0.25, (p75+med)/2),
                 (0.20, (top10+p75)/2), (0.05, top10*1.1)]
        ev = sum(w * max(0, vr * (x - thresh)) for w, x in reprs)
        print(f"  threshold=p{threshold_pct:2d} ({thresh:>5,.0f}): E[V_test] = {ev:,.0f}   "
              f"E[V_finale] = {ev*scale:,.0f}")
    print()

    print("━━━ Key numbers for adversary model ━━━")
    print(f"  Denominator (n)                = {n:,}")
    print(f"  Median team V_finale (linear)  = {med*vr*scale:,.0f}")
    print(f"  Our V_finale                   = 11,194")
    print(f"  Teams w/ V ≥ ours              = ~{n_above_us} (top 1%)")
    print(f"  Teams w/ V ≥ half ours (5,6k)  = ~{int(n*0.10):,} (top 10%)")
    print(f"  Teams w/ V ≈ 0 (PnL ≤ 0)       = ~{low_outliers} + some near-zero profitables")


if __name__ == "__main__":
    main()
