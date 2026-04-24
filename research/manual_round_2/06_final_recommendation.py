"""Final consolidated recommendation for Manual Round 2 "Invest & Expand".

Integrates:
  - Pillar formulas (script 01)
  - Optimal (x,y) given exogenous m (script 02) → x:y ratio ≈ 23:77 at B=100
  - Speed tournament dynamics (script 03) → best z depends on field
  - Robust allocation under prior mix (script 04) → ensemble z ≈ 30
  - Focal point matching (script 05) → z=33 best response to realistic clusters

Decision framework:
  1. With x+y+z=100 forced (full budget), given z, optimal (x, y) with x+y=100-z
     has x/y ratio that varies from 23:77 at z=0 to smaller x/(x+y) at high z.
  2. The critical choice is z, because Speed is rank-based.
  3. Matching a focal cluster (z at round number) lets us tie at that rank
     and share its m — usually the best strategy.

Usage:
    python research/manual_round_2/06_final_recommendation.py
"""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("speed_mod", ROOT / "03_speed_tournament.py")
sp = importlib.util.module_from_spec(spec); sys.modules["speed_mod"] = sp
spec.loader.exec_module(sp)


def main():
    print("═" * 80)
    print("MANUAL ROUND 2 — FINAL ALLOCATION RECOMMENDATION")
    print("═" * 80)

    print("""
CONTEXT
───────
  Budget: 50,000 XIRECs. Allocate (x, y, z) to (Research, Scale, Speed).
  PnL = Research(x) × Scale(y) × Speed(rank) − Budget_Used
  Research = 200,000 × ln(1+x)/ln(101) — logarithmic
  Scale    = 7 × y/100 — linear
  Speed    = rank-based [0.1, 0.9] linear

  If we tie at rank 1, m = 0.9. If bottom rank, m = 0.1.

KEY FINDING 1 — given m, optimal R/S ratio is 23:77 at full budget
───────────────────────────────────────────────────────────────────
  With x+y=100, optimal is x=23, y=77 (corner-ish solution).
  Research saturates fast (log), Scale is linear → Scale gets more.
  At lower budgets (higher z), x/(x+y) drops slightly but stays ~25%.

KEY FINDING 2 — Speed is the DOMINANT DECISION
───────────────────────────────────────────────
  With m=0.9, max PnL ≈ 618k. With m=0.1, max PnL ≈ 24k.
  → 25× difference based purely on Speed rank.
  → Investing too little in z = catastrophic.
  → Investing too much in z = waste budget on R×S.

KEY FINDING 3 — focal points DOMINATE the strategy
──────────────────────────────────────────────────
  Round numbers (25, 30, 33, 40, 50) are natural clusters.
  Matching the biggest cluster lets us SHARE rank → same m at lower cost.
  Going 1% above a cluster: same rank, wasted budget.
  Going 1% below a cluster: drop rank, catastrophic.
""")

    # ─────────────────────────────────────────────────
    # Scenario summary from scripts 03-05
    # ─────────────────────────────────────────────────
    print("─" * 80)
    print("SCENARIO SUMMARY — best response under each adversary model")
    print("─" * 80)
    print(f"  {'Scenario':<28} {'Best z':>7} {'best (x, y, z)':>18} {'PnL':>12}")
    print(f"  {'─'*28:<28} {'─'*7:>7} {'─'*18:>18} {'─'*12:>12}")

    rng = np.random.default_rng(42)
    n_others = 2000
    scenarios = {
        "All_coord_at_0":       np.zeros(n_others, dtype=int),
        "Mostly_low (exp~15)":  np.clip(rng.exponential(15, n_others), 0, 100).astype(int),
        "Normal(30, σ=10)":     np.clip(rng.normal(30, 10, n_others), 0, 100).astype(int),
        "Normal(50, σ=15)":     np.clip(rng.normal(50, 15, n_others), 0, 100).astype(int),
        "Uniform(0, 100)":      rng.integers(0, 101, n_others),
        "Focal 33 (18% cluster)":  np.concatenate([
            np.full(int(0.18 * n_others), 33, dtype=int),
            np.clip(rng.normal(30, 15, int(0.82 * n_others)), 0, 100).astype(int)]),
        "Focal 50 (20% cluster)": np.concatenate([
            np.full(int(0.20 * n_others), 50, dtype=int),
            np.clip(rng.normal(30, 15, int(0.80 * n_others)), 0, 100).astype(int)]),
    }
    for name, others in scenarios.items():
        best_z, best_pnl = 0, -1e18
        for z in range(0, 101):
            p = sp.compute_pnl(z, others)["pnl"]
            if p > best_pnl: best_pnl, best_z = p, z
        r = sp.compute_pnl(best_z, others)
        print(f"  {name:<28} {best_z:>7} {f'({r[chr(120)]},{r[chr(121)]},{best_z})':>18} {best_pnl:>+12,.0f}")

    # ─────────────────────────────────────────────────
    # Ensemble optimum under mix
    # ─────────────────────────────────────────────────
    priors = {
        "Mostly_low (exp~15)":      0.25,
        "Normal(30, σ=10)":         0.30,
        "Focal 33 (18% cluster)":   0.20,
        "Focal 50 (20% cluster)":   0.10,
        "Normal(50, σ=15)":         0.10,
        "Uniform(0, 100)":          0.05,
    }
    ensemble = {}
    for z in range(0, 101):
        ev = 0
        for name, prob in priors.items():
            p = sp.compute_pnl(z, scenarios[name])["pnl"]
            ev += prob * p
        ensemble[z] = ev
    best_z_ens = max(ensemble, key=ensemble.get)

    print("\n" + "─" * 80)
    print("ENSEMBLE-OPTIMAL z (weighted by subjective scenario probabilities)")
    print("─" * 80)
    print(f"  Priors:  25% Mostly_low · 30% Normal(30) · 20% Focal33 · 10% Focal50 · ")
    print(f"            10% Normal(50) · 5% Uniform")
    print(f"\n  Best z (ensemble):           {best_z_ens}")
    print(f"  Expected PnL at best z:      {ensemble[best_z_ens]:+,.0f}")

    # Top 10 z values by ensemble
    sorted_ens = sorted(ensemble.items(), key=lambda kv: -kv[1])[:10]
    print(f"\n  Top 10 z values by ensemble E[PnL]:")
    for z, ev in sorted_ens:
        r = sp.compute_pnl(z, scenarios["Focal 33 (18% cluster)"])
        print(f"    z={z:>3}  E[PnL]={ev:>+11,.0f}  (xy=({r['x']},{r['y']}))")

    # ─────────────────────────────────────────────────
    # FINAL RECOMMENDATION
    # ─────────────────────────────────────────────────
    print("\n" + "═" * 80)
    print("  🏆 FINAL RECOMMENDATION")
    print("═" * 80)
    r = sp.compute_pnl(best_z_ens, scenarios["Focal 33 (18% cluster)"])
    print(f"""
  RESEARCH  = {r['x']}%    ({r['x']*500:>6,} XIRECs)  → reward  {r['R']:>8,.0f}
  SCALE     = {r['y']}%    ({r['y']*500:>6,} XIRECs)  → mult   ×{r['S']:.2f}
  SPEED     = {best_z_ens}%    ({best_z_ens*500:>6,} XIRECs)  → mult   ~×0.5-0.7 (depends on rank)
  ────────────────────────────────
  TOTAL     = {r['x']+r['y']+best_z_ens}%   ({(r['x']+r['y']+best_z_ens)*500:>6,} XIRECs used)

  Expected PnL (ensemble):  {ensemble[best_z_ens]:+,.0f}

  RATIONALE:
    - z={best_z_ens} is the ensemble-optimal under subjective priors
    - Matches the likely focal at z=33 (biggest cluster) OR very near it
    - Capture good m while preserving budget for Research × Scale
    - Robust across most plausible adversary distributions
""")

    # Alternatives
    print("  ALTERNATIVES:")
    print("    - Defensive (if field competitive, z ≈ 50): (x=13, y=37, z=50), PnL ~216k")
    print("    - Aggressive (if field coordinates low): (x=21, y=69, z=10), PnL ~532k")
    print("    - Focal-match 40: (x=15, y=45, z=40), PnL ~215k (robust to noise)")


if __name__ == "__main__":
    main()
