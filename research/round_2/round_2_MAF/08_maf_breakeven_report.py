"""Final MAF break-even report.

Consolidates:
  1. LIVE PnL distribution per product from R2 live logs (script 07 output)
  2. BACKTEST uplift ratios 100% vs 80% subsample (script 06 output)
  3. → Expected extra PnL from MAF in live units, per product and total
  4. → Break-even bid (bid at which E[net gain] = 0)

Break-even logic:
  If we WIN the auction (top 50%), we pay our bid and gain MAF_extra_PnL.
  Break-even condition (ignoring acceptance probability for worst-case bound):
      bid_breakeven = E[MAF_extra_PnL]
  Any bid < breakeven → net positive if accepted.
  Any bid > breakeven → net negative if accepted.

Usage:
    python research/round_2/round_2_MAF/08_maf_breakeven_report.py \\
        --logs-json research/round_2/round_2_MAF/live_logs_summary.json \\
        --uplift-osm 1.488 --uplift-osm-std 0.025 \\
        --uplift-ipr 1.0004 --uplift-ipr-std 0.0004 \\
        --combined-only
"""
from __future__ import annotations
import argparse
import json
import math
import statistics
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs-json", default="research/round_2/round_2_MAF/live_logs_summary.json",
                    help="Path to JSON from script 07")
    ap.add_argument("--uplift-osm", type=float, default=1.488,
                    help="PnL(100%)/PnL(80%) ratio for OSMIUM from script 06")
    ap.add_argument("--uplift-osm-std", type=float, default=0.025)
    ap.add_argument("--uplift-ipr", type=float, default=1.0004,
                    help="PnL(100%)/PnL(80%) ratio for IPR from script 06")
    ap.add_argument("--uplift-ipr-std", type=float, default=0.0004)
    ap.add_argument("--combined-only", action="store_true",
                    help="Only consider runs with BOTH products > 0 (full-combined-champion runs)")
    ap.add_argument("--finale-scaling", type=float, default=8.9,
                    help="simu test → simu finale scaling factor (default 8.9, empirical from R1)")
    args = ap.parse_args()

    with open(args.logs_json, "r", encoding="utf-8") as f:
        logs = json.load(f)

    # Split runs by category
    combined = [r for r in logs if r.get("ASH_COATED_OSMIUM", 0) > 0 and r.get("INTARIAN_PEPPER_ROOT", 0) > 0]
    osm_only = [r for r in logs if r.get("ASH_COATED_OSMIUM", 0) > 0 and r.get("INTARIAN_PEPPER_ROOT", 0) == 0]
    ipr_only = [r for r in logs if r.get("ASH_COATED_OSMIUM", 0) == 0 and r.get("INTARIAN_PEPPER_ROOT", 0) > 0]

    def stats(xs):
        if not xs: return (0.0, 0.0, 0, 0)
        m = statistics.mean(xs)
        s = statistics.stdev(xs) if len(xs) > 1 else 0.0
        return (m, s, min(xs), max(xs))

    print("═" * 80)
    print("MAF BREAK-EVEN REPORT")
    print("═" * 80)
    print()
    print(f"Run categories parsed from logs:")
    print(f"  Combined (OSM+IPR): {len(combined)} run(s)")
    print(f"  OSM-only:           {len(osm_only)} run(s)")
    print(f"  IPR-only:           {len(ipr_only)} run(s)")
    print()

    # Choose OSM live distribution
    if args.combined_only or not osm_only:
        osm_runs = [r["ASH_COATED_OSMIUM"] for r in combined]
        osm_source = "combined runs"
    else:
        osm_runs = [r["ASH_COATED_OSMIUM"] for r in combined + osm_only]
        osm_source = "combined + OSM-only runs"

    if args.combined_only or not ipr_only:
        ipr_runs = [r["INTARIAN_PEPPER_ROOT"] for r in combined]
        ipr_source = "combined runs"
    else:
        ipr_runs = [r["INTARIAN_PEPPER_ROOT"] for r in combined + ipr_only]
        ipr_source = "combined + IPR-only runs"

    mo, so, lo_o, hi_o = stats(osm_runs)
    mi, si, lo_i, hi_i = stats(ipr_runs)
    mt = mo + mi
    # Total std: if we assume OSM/IPR independent within a run, total-per-run std is sqrt(so^2+si^2);
    # but cleaner: use observed totals from combined runs.
    combined_totals = [r["ASH_COATED_OSMIUM"] + r["INTARIAN_PEPPER_ROOT"] for r in combined]
    mt_obs, st_obs, lo_t, hi_t = stats(combined_totals) if combined_totals else (mt, 0.0, mt, mt)

    print("━━━ 1. LIVE PnL DISTRIBUTION (observed on IMC) ━━━")
    print(f"  OSM  ({osm_source}, n={len(osm_runs)}):")
    print(f"    mean = {mo:>7,.0f}   std = {so:>6,.0f}   range = [{lo_o:,.0f}, {hi_o:,.0f}]")
    print(f"  IPR  ({ipr_source}, n={len(ipr_runs)}):")
    print(f"    mean = {mi:>7,.0f}   std = {si:>6,.0f}   range = [{lo_i:,.0f}, {hi_i:,.0f}]")
    print(f"  TOTAL (observed combined runs, n={len(combined_totals)}):")
    print(f"    mean = {mt_obs:>7,.0f}   std = {st_obs:>6,.0f}   range = [{lo_t:,.0f}, {hi_t:,.0f}]")
    print()

    # MAF gain computation
    uo = args.uplift_osm
    ui = args.uplift_ipr
    gain_osm = mo * (uo - 1)
    gain_ipr = mi * (ui - 1)
    gain_tot = gain_osm + gain_ipr
    # Error propagation: Var[PnL × (u−1)] where PnL and u are independent:
    # = E[u−1]^2 * Var[PnL] + E[PnL]^2 * Var[u]
    var_osm_gain = (uo - 1) ** 2 * so ** 2 + mo ** 2 * args.uplift_osm_std ** 2
    var_ipr_gain = (ui - 1) ** 2 * si ** 2 + mi ** 2 * args.uplift_ipr_std ** 2
    std_osm_gain = math.sqrt(var_osm_gain)
    std_ipr_gain = math.sqrt(var_ipr_gain)
    std_tot_gain = math.sqrt(var_osm_gain + var_ipr_gain)  # independent products

    pct_osm = 100 * (uo - 1)
    pct_ipr = 100 * (ui - 1)
    pct_tot = 100 * gain_tot / mt_obs if mt_obs else 0.0

    print("━━━ 2. BACKTEST UPLIFT RATIOS (script 06) ━━━")
    print(f"  OSM uplift: ×{uo:.3f}  →  +{pct_osm:.2f}%   (std ratio ±{args.uplift_osm_std:.3f})")
    print(f"  IPR uplift: ×{ui:.4f}  →  +{pct_ipr:.3f}%  (std ratio ±{args.uplift_ipr_std:.4f})")
    print()

    print("━━━ 3. EXPECTED MAF GAIN (live XIRECs) ━━━")
    print(f"  OSM  : +{gain_osm:>6,.0f}  ± {std_osm_gain:,.0f}   (+{pct_osm:.2f}% of live OSM mean)")
    print(f"  IPR  : +{gain_ipr:>6,.0f}  ± {std_ipr_gain:,.0f}   (+{pct_ipr:.3f}% of live IPR mean)")
    print(f"  TOT  : +{gain_tot:>6,.0f}  ± {std_tot_gain:,.0f}   (+{pct_tot:.2f}% of live TOTAL mean)")
    print()

    # Break-even bid — CRITICAL: PnL live is in simu-test units, bid is paid in simu-finale units.
    # Scale by finale_scaling (≈ 8.9 empirically from R1: 12k test → 107k finale).
    scale = args.finale_scaling
    gain_tot_finale = gain_tot * scale
    std_tot_gain_finale = std_tot_gain * scale

    print("━━━ 4. BREAK-EVEN BID (E[net gain | accepted] = 0) ━━━")
    print(f"  ⚠ UNIT CONVERSION: live PnL is in simu-TEST units,")
    print(f"     but MAF bid is paid in simu-FINALE units → multiply by ×{scale}")
    print()
    print(f"  simu-test units:")
    print(f"    MAF gain = {gain_tot:,.0f} ± {std_tot_gain:,.0f} XIRECs_test")
    print()
    print(f"  simu-FINALE units (bid is paid here):")
    print(f"    Break-even bid  =  {gain_tot_finale:,.0f}  XIRECs_finale")
    print(f"    1σ band         =  [{gain_tot_finale - std_tot_gain_finale:,.0f} ,  {gain_tot_finale + std_tot_gain_finale:,.0f}]")
    print(f"    2σ band         =  [{gain_tot_finale - 2*std_tot_gain_finale:,.0f} ,  {gain_tot_finale + 2*std_tot_gain_finale:,.0f}]")
    print()
    print("  Interpretation (in finale XIRECs):")
    print(f"    bid < {gain_tot_finale:,.0f}   → net POSITIVE in expectation (if auction won)")
    print(f"    bid > {gain_tot_finale:,.0f}   → net NEGATIVE in expectation (if auction won)")
    print(f"    bid ≈ {max(0, gain_tot_finale - std_tot_gain_finale):,.0f}  → conservative (−1σ margin)")
    print()

    # Min / max bracket
    gain_min = lo_o * (uo - 1) + lo_i * (ui - 1)
    gain_max = hi_o * (uo - 1) + hi_i * (ui - 1)
    print("━━━ 5. SCENARIO BRACKET (using live min/max observed) ━━━")
    print(f"  Worst live PnL observed → MAF gain = {gain_min:>6,.0f} XIRECs")
    print(f"  Best live PnL observed  → MAF gain = {gain_max:>6,.0f} XIRECs")
    print()

    print("═" * 80)
    print(f"  FINAL ANSWER")
    print("═" * 80)
    print(f"  • With MAF, expected extra PnL (live simu-test) = +{gain_tot:,.0f} XIRECs_test   "
          f"(+{pct_tot:.1f}% of live total)")
    print(f"  • Break-even bid (simu-TEST units)    = {gain_tot:,.0f} XIRECs_test")
    print(f"  • Break-even bid (simu-FINALE units)  = {gain_tot_finale:,.0f} XIRECs_finale  ← BID IS PAID HERE")
    print(f"  • Conservative (−1σ, finale)          = {max(0, gain_tot_finale - std_tot_gain_finale):,.0f} XIRECs_finale")
    print(f"  • OSM contribution: {100*gain_osm/gain_tot if gain_tot else 0:.0f}% of MAF gain")
    print(f"  • IPR contribution: {100*gain_ipr/gain_tot if gain_tot else 0:.1f}% of MAF gain (quasi-nul)")
    print("═" * 80)


if __name__ == "__main__":
    main()
