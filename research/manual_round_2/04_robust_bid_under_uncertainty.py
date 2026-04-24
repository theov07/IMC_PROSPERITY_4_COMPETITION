"""Find robust allocation (x, y, z) under UNCERTAINTY about adversary z distribution.

We don't know the true distribution. We hedge across a mixture of plausible ones.

Adversary scenarios (subjective priors):
  - "all_low_coord"    (15%): everyone coordinated low (z=0-10), common in casual teams
  - "mostly_low"       (25%): exp(15), most teams under-invest
  - "bimodal"          (15%): two clusters (lazy + paranoid)
  - "normal_30"        (25%): middle focal around 30%
  - "uniform_0_100"    (10%): completely random field
  - "competitive_heavy"(10%): N(50, 15), serious teams push high

For each candidate z ∈ [0, 100], compute expected PnL across scenarios.
Recommend the z that maximizes the prior-weighted EU.

Usage:
    python research/manual_round_2/04_robust_bid_under_uncertainty.py
"""
from __future__ import annotations
import numpy as np
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("speed_mod", ROOT / "03_speed_tournament.py")
sp = importlib.util.module_from_spec(spec); sys.modules["speed_mod"] = sp
spec.loader.exec_module(sp)


def build_scenarios(n_others: int, rng: np.random.Generator):
    return {
        "all_low_coord":     (0.15, rng.integers(0, 11, n_others)),
        "mostly_low":        (0.25, np.clip(rng.exponential(15, n_others), 0, 100).astype(int)),
        "bimodal":           (0.15, np.concatenate([
                                        rng.integers(0, 15, n_others // 2),
                                        rng.integers(60, 85, n_others - n_others//2)])),
        "normal_30":         (0.25, np.clip(rng.normal(30, 10, n_others), 0, 100).astype(int)),
        "uniform_0_100":     (0.10, rng.integers(0, 101, n_others)),
        "competitive_heavy": (0.10, np.clip(rng.normal(50, 15, n_others), 0, 100).astype(int)),
    }


def compute_all_pnls(scenario_dists, z_grid):
    """Return {z: {scenario_name: pnl}}."""
    out = {z: {} for z in z_grid}
    for name, (prob, others) in scenario_dists.items():
        for z in z_grid:
            res = sp.compute_pnl(z, others)
            out[z][name] = res["pnl"]
    return out


def main():
    n_others = 2000
    rng = np.random.default_rng(42)
    scen_dists = build_scenarios(n_others, rng)

    print("═" * 85)
    print("ROBUST ALLOCATION: expected PnL under prior-weighted scenario mix")
    print("═" * 85)
    print("Adversary distribution priors:")
    for name, (p, _) in scen_dists.items():
        print(f"  {p:.0%} {name}")
    print()

    z_grid = list(range(0, 101, 1))
    all_pnls = compute_all_pnls(scen_dists, z_grid)

    # Prior-weighted EU per z
    ensemble = {}
    for z in z_grid:
        ev = sum(prob * all_pnls[z][name] for name, (prob, _) in scen_dists.items())
        ensemble[z] = ev

    best_z = max(ensemble, key=ensemble.get)
    best_ev = ensemble[best_z]

    # Show all z values with their ensemble + scenario breakdown
    print(f"{'z':>4}  " + "  ".join([f"{name[:9]:>10}" for name in scen_dists.keys()]) + "  " + f"{'ENSEMBLE':>10}")
    print("─" * 85)
    for z in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 100]:
        row = f"{z:>4}  "
        for name in scen_dists.keys():
            row += f"{all_pnls[z][name]:>+10,.0f}  "
        row += f"{ensemble[z]:>+10,.0f}"
        marker = "  ← BEST" if z == best_z else ""
        print(row + marker)

    print(f"\nEnsemble-optimal z = {best_z}  (weighted E[PnL] = {best_ev:+,.0f})")

    # Print the best response details
    res = sp.compute_pnl(best_z, scen_dists["normal_30"][1])  # use normal_30 for rank detail
    print(f"\nAllocation at z={best_z}:")
    print(f"  x = {res['x']}%    Research = {res['R']:,.0f}")
    print(f"  y = {res['y']}%    Scale    = ×{res['S']:.2f}")
    print(f"  z = {best_z}%    Speed (vs normal_30) = ×{res['m']:.2f}")
    print(f"  Budget used = {(res['x']+res['y']+best_z)}%  ({(res['x']+res['y']+best_z)*500:,} XIRECs)")

    # Show robustness: worst-case across scenarios
    worst_case_at_best = min(all_pnls[best_z].values())
    best_case_at_best = max(all_pnls[best_z].values())
    print(f"\nRobustness at z={best_z}:")
    print(f"  Best-case scenario   = {best_case_at_best:+,.0f}")
    print(f"  Worst-case scenario  = {worst_case_at_best:+,.0f}")

    # Show minimax z (maximize worst-case)
    minimax = {z: min(all_pnls[z].values()) for z in z_grid}
    best_minimax_z = max(minimax, key=minimax.get)
    print(f"\nMINIMAX z (maximizes worst-case): z = {best_minimax_z}  "
          f"worst-case PnL = {minimax[best_minimax_z]:+,.0f}")


if __name__ == "__main__":
    main()
