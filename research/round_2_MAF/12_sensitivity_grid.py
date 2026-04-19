"""Sensitivity grid analysis for MAF median.

Scans key unknowns:
  - frac_no_bid ∈ [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
  - frac_wiki   ∈ [0.05, 0.10, 0.20, 0.30, 0.40]
  - shading multiplier (shaded bidders aggressiveness) ∈ [0.4, 0.6, 0.8]
  - v_threshold_test ∈ [5000, 7000, 9000]

For each combination: run Monte Carlo, compute median, optimal bid.

Outputs:
  - Main table: optimal bid vs (frac_no_bid × frac_wiki)
  - Robust bid: p75 of optimal across scenarios
  - Breakeven warning: if optimal > 11,194 (our V)

Usage:
    python research/round_2_MAF/12_sensitivity_grid.py --n-sims 500
"""
from __future__ import annotations
import argparse
import json
import numpy as np
import random
from pathlib import Path

# Reuse the simulator logic (imported here for DRY)
import importlib.util
import sys
ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("med_sim", ROOT / "11_median_simulator.py")
med_sim = importlib.util.module_from_spec(spec)
sys.modules["med_sim"] = med_sim
spec.loader.exec_module(med_sim)

Scenario = med_sim.Scenario
OUR_V_FINALE = med_sim.OUR_V_FINALE


def evaluate_scenario(frac_no_bid, frac_wiki, shaded_lo, shaded_hi,
                      v_threshold, n_sims=500, n_teams=3065, seed=42):
    # Fractions of remaining after no_bid and wiki
    remaining = 1.0 - frac_no_bid - frac_wiki
    # Split remaining into round/shaded/aggressive: 20% / 65% / 15%
    frac_round = remaining * 0.20
    frac_shaded = remaining * 0.65
    frac_agg = remaining * 0.15

    scen = Scenario(
        name=f"nb{frac_no_bid:.0%}_wk{frac_wiki:.0%}_sh{shaded_lo}-{shaded_hi}_vt{v_threshold}",
        frac_no_bid=frac_no_bid, frac_wiki=frac_wiki,
        frac_round=frac_round, frac_shaded=frac_shaded, frac_aggressive=frac_agg,
        v_threshold_test=v_threshold,
        shaded_lo=shaded_lo, shaded_hi=shaded_hi,
    )

    rng_np = np.random.default_rng(seed)
    rng_py = random.Random(seed)
    medians = np.empty(n_sims)
    for i in range(n_sims):
        r = med_sim.one_sim(n_teams, scen, rng_np, rng_py)
        medians[i] = r["median"]

    # Evaluate fine grid of bids
    bid_grid = [1, 10, 15, 25, 50, 100, 200, 500, 1000, 1500, 2000, 3000,
                4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 11194]
    best_bid, best_eu = 0, -1e18
    for b in bid_grid:
        p = float(np.mean(b > medians))
        eu = p * (OUR_V_FINALE - b)
        if eu > best_eu:
            best_eu = eu; best_bid = b
    return {
        "frac_no_bid": frac_no_bid,
        "frac_wiki": frac_wiki,
        "shaded_lo": shaded_lo,
        "shaded_hi": shaded_hi,
        "v_threshold": v_threshold,
        "median_mean": float(medians.mean()),
        "median_p95": float(np.percentile(medians, 95)),
        "pct_zero_median": float(np.mean(medians == 0)),
        "optimal_bid": best_bid,
        "optimal_eu": float(best_eu),
        "p_win_at_optimal": float(np.mean(best_bid > medians)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-sims", type=int, default=500)
    ap.add_argument("--n-teams", type=int, default=3065)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--save-json", type=str,
                    default="research/round_2_MAF/sensitivity_grid_results.json")
    args = ap.parse_args()

    # Main grid: frac_no_bid × frac_wiki
    grid_no_bid = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
    grid_wiki   = [0.05, 0.10, 0.20, 0.30]

    # Fixed "central" other params
    shaded = (0.5, 0.7)
    threshold = 7000

    print("═" * 86)
    print("SENSITIVITY GRID: OPTIMAL BID (finale XIRECs)")
    print("═" * 86)
    print(f"Fixed: shaded∈[{shaded[0]},{shaded[1]}], v_threshold_test={threshold}, "
          f"V_ours={OUR_V_FINALE:,.0f}")
    print(f"Rows = frac_no_bid ({grid_no_bid[0]:.0%}→{grid_no_bid[-1]:.0%})")
    print(f"Cols = frac_wiki   ({grid_wiki[0]:.0%}→{grid_wiki[-1]:.0%})")
    print()

    results = []
    header = "  " + "frac_no_bid \\ wiki".ljust(20)
    for fw in grid_wiki:
        header += f"{fw:>9.0%}"
    header += f"{'median avg':>14}"
    print(header)
    print("  " + "─" * (20 + 9 * len(grid_wiki) + 14))

    all_optimals = []
    for fnb in grid_no_bid:
        row_vals = []
        median_avg = 0
        for fw in grid_wiki:
            res = evaluate_scenario(fnb, fw, shaded[0], shaded[1], threshold,
                                     n_sims=args.n_sims, n_teams=args.n_teams, seed=args.seed)
            results.append(res)
            row_vals.append(res["optimal_bid"])
            median_avg += res["median_mean"]
            all_optimals.append(res["optimal_bid"])
        median_avg /= len(grid_wiki)
        row = f"  frac_no_bid={fnb:.0%}".ljust(22)
        for v in row_vals:
            row += f"{v:>9,}"
        row += f"{median_avg:>14,.0f}"
        print(row)

    # Additional stratified grids
    print("\n" + "═" * 86)
    print("SHADING SENSITIVITY (frac_no_bid=50%, frac_wiki=15% fixed)")
    print("═" * 86)
    print(f"  {'shaded range':<20} {'median mean':>12} {'optimal bid':>12} {'P(win)':>8} {'E[U]':>9}")
    for sh_lo, sh_hi, label in [
        (0.3, 0.5, "[0.3, 0.5] shy"),
        (0.5, 0.7, "[0.5, 0.7] bal"),
        (0.7, 0.9, "[0.7, 0.9] bold"),
        (0.9, 1.1, "[0.9, 1.1] full")
    ]:
        r = evaluate_scenario(0.50, 0.15, sh_lo, sh_hi, threshold,
                              n_sims=args.n_sims, n_teams=args.n_teams, seed=args.seed)
        results.append(r)
        print(f"  {label:<20} {r['median_mean']:>12,.0f} {r['optimal_bid']:>12,} "
              f"{r['p_win_at_optimal']:>7.1%} {r['optimal_eu']:>+9,.0f}")

    # V threshold sensitivity
    print("\n" + "═" * 86)
    print("V-THRESHOLD SENSITIVITY (frac_no_bid=50%, frac_wiki=15%)")
    print("═" * 86)
    print(f"  {'threshold':<15} {'median mean':>12} {'optimal bid':>12} {'P(win)':>8} {'E[U]':>9}")
    for vt in [5000, 7000, 9000, 10000]:
        r = evaluate_scenario(0.50, 0.15, 0.5, 0.7, vt,
                              n_sims=args.n_sims, n_teams=args.n_teams, seed=args.seed)
        results.append(r)
        print(f"  v_thresh={vt:<6} {r['median_mean']:>12,.0f} {r['optimal_bid']:>12,} "
              f"{r['p_win_at_optimal']:>7.1%} {r['optimal_eu']:>+9,.0f}")

    # Robust bid
    all_optimals_arr = np.array(all_optimals)
    print("\n" + "═" * 86)
    print("ROBUST BID RECOMMENDATION (across main grid)")
    print("═" * 86)
    print(f"  min optimal          = {int(all_optimals_arr.min()):>8,}")
    print(f"  median optimal       = {int(np.median(all_optimals_arr)):>8,}")
    print(f"  p75 optimal (robust) = {int(np.percentile(all_optimals_arr, 75)):>8,}")
    print(f"  p90 optimal (safe)   = {int(np.percentile(all_optimals_arr, 90)):>8,}")
    print(f"  max optimal          = {int(all_optimals_arr.max()):>8,}")
    print()
    print(f"  Break-even constraint: {OUR_V_FINALE:,.0f} finale")
    print(f"  → Bids above break-even lose money even if accepted.")

    # Save
    with open(args.save_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {args.save_json}")


if __name__ == "__main__":
    main()
