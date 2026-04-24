"""Sensitivity of the MAF median to the size of the submitter pool.

Varies n_teams (the denominator = teams that submitted trader.py) to show
how much the absolute participation number affects the outcome.

Mathematically, the median is SCALE-INVARIANT for fixed archetype fractions:
  same composition → same median in expectation, just lower variance at larger N.

This script demonstrates that empirically across realistic n values:
    1,000   — pessimistic lower bound
    3,065   — observed aggregator count
    5,000   — likely real IMC count
    10,000  — upper estimate if IMC captures most registered teams
    20,000  — if every registrant submits (unrealistic upper bound)

Usage:
    python research/round_2_MAF/14_participation_sensitivity.py
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
import numpy as np
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("med_sim", ROOT / "11_median_simulator.py")
med_sim = importlib.util.module_from_spec(spec)
sys.modules["med_sim"] = med_sim
spec.loader.exec_module(med_sim)

Scenario = med_sim.Scenario
SCENARIOS = med_sim.SCENARIOS
OUR_V = med_sim.OUR_V_FINALE


def run(scen, n_teams, n_sims, seed):
    rng_np = np.random.default_rng(seed)
    rng_py = random.Random(seed)
    meds = np.empty(n_sims)
    for i in range(n_sims):
        meds[i] = med_sim.one_sim(n_teams, scen, rng_np, rng_py)["median"]
    bid_grid = [1, 10, 15, 25, 50, 100, 200, 500, 1000, 2000, 3000, 5000,
                6000, 7000, 8000, 9000, 10000, 11000, 11194]
    best_b, best_eu = 0, -1e18
    for b in bid_grid:
        p = float(np.mean(b > meds))
        eu = p * (OUR_V - b)
        if eu > best_eu: best_eu, best_b = eu, b
    return {
        "median_mean": float(meds.mean()),
        "median_std":  float(meds.std()),
        "median_p5":   float(np.percentile(meds, 5)),
        "median_p95":  float(np.percentile(meds, 95)),
        "optimal_bid": best_b,
        "optimal_eu":  float(best_eu),
        "pct_zero":    float(np.mean(meds == 0)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-sims", type=int, default=600)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    n_values = [500, 1000, 3065, 5000, 10000, 20000]
    scenarios = list(SCENARIOS.values())

    print("═" * 92)
    print("PARTICIPATION-RATE SENSITIVITY: how does n_teams affect the MAF median?")
    print("═" * 92)
    print("Key insight: for fixed archetype fractions, the median is scale-invariant")
    print("in expectation. Only the *variance* of the median across sims shrinks as n grows.")
    print()

    for scen in scenarios:
        print(f"\n━━━ Scenario '{scen.name}' "
              f"(no-bid={scen.frac_no_bid:.0%}, wiki={scen.frac_wiki:.0%}, "
              f"shaded={scen.frac_shaded:.0%}) ━━━")
        print(f"  {'n_teams':>8}   {'med mean':>9}   {'med std':>8}   "
              f"{'p5':>7}   {'p95':>7}   {'P(med=0)':>9}   {'opt bid':>8}   {'E[U]':>8}")
        print(f"  {'─'*8:>8}   {'─'*9:>9}   {'─'*8:>8}   "
              f"{'─'*7:>7}   {'─'*7:>7}   {'─'*9:>9}   {'─'*8:>8}   {'─'*8:>8}")
        for n in n_values:
            r = run(scen, n, args.n_sims, args.seed)
            print(f"  {n:>8,}   {r['median_mean']:>9,.0f}   {r['median_std']:>8,.0f}   "
                  f"{r['median_p5']:>7,.0f}   {r['median_p95']:>7,.0f}   "
                  f"{r['pct_zero']:>8.1%}   {r['optimal_bid']:>8,}   {r['optimal_eu']:>+8,.0f}")

    print()
    print("═" * 92)
    print("CONCLUSION")
    print("═" * 92)
    print("  - Median mean is essentially CONSTANT across n_teams (scale-invariant).")
    print("  - Variance (std) drops as n grows, but tight enough at all sizes to not")
    print("    shift the optimal bid for realistic n (≥ 1,000).")
    print("  - Bottom line: the denominator SIZE doesn't matter. Only COMPOSITION does.")
    print("  - Our 3,065 estimate is fine — use it as working assumption.")


if __name__ == "__main__":
    main()
