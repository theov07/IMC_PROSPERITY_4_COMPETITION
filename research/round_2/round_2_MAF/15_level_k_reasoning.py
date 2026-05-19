"""Cognitive Hierarchy / Level-k reasoning for MAF bid.

Problem: if OTHER teams also run our optimization and bid the level-1 optimal
         (e.g. 500), the median shifts → our bid becomes suboptimal.

Model (Camerer-Ho-Chong cognitive hierarchy):
  - Level 0 rationals: bid their V (no shading, no strategic thought)
  - Level 1 rationals: bid optimal assuming everyone else is L0
  - Level 2 rationals: bid optimal assuming everyone else is L0 + L1 mix
  - Level k rationals: bid optimal vs L0 + ... + L_{k-1} mix

Distribution of levels among rationals: Poisson(λ), typical λ ∈ [1, 2].

We iterate:
  1. Start at level 0: rationals bid V (full valuation)
  2. Compute resulting median + optimal bid for L1
  3. Add L1 bidders to the field with Poisson weight
  4. Recompute median + optimal bid for L2
  5. ...iterate until convergence (optimal stops moving)

Output:
  - Bid at each level (convergence sequence)
  - Final mixed-level distribution
  - Our best-response bid integrating all levels
  - Recommendation by λ (sophistication parameter)

Usage:
    python research/round_2/round_2_MAF/15_level_k_reasoning.py --scenario central_eng --lambda 1.5
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
import math
from pathlib import Path
import numpy as np
import random

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("med_sim", ROOT / "11_median_simulator.py")
med_sim = importlib.util.module_from_spec(spec)
sys.modules["med_sim"] = med_sim
spec.loader.exec_module(med_sim)

V_FINALE = med_sim.OUR_V_FINALE  # 11,194
SCENARIOS = med_sim.SCENARIOS


def poisson_weights(lam: float, max_k: int):
    """P(level=k) under truncated Poisson, normalized to sum=1."""
    raw = [math.exp(-lam) * lam**k / math.factorial(k) for k in range(max_k + 1)]
    s = sum(raw)
    return [w / s for w in raw]


def sample_v_for_rationals(n: int, rng_np: np.random.Generator,
                            threshold: float = 7000.0) -> np.ndarray:
    """V distribution for the 'rational' subset: they are competent teams, so
    their PnL distribution is shifted upward. Sample from top-half of field.
    Returns V_finale per rational."""
    # Use top-half of the R2 field distribution
    pnls = med_sim.generate_field_pnl_test(n * 3, rng_np)
    pnls = pnls[pnls > threshold]  # active MM only
    pnls = pnls[:n] if len(pnls) >= n else np.pad(pnls, (0, n - len(pnls)), constant_values=10300)
    return np.array([med_sim.team_v_finale(float(p), threshold) for p in pnls])


def build_non_rational_bids(scen, n_total: int, rng_py: random.Random) -> np.ndarray:
    """Generate the fixed-archetype (non-rational) bids: no-bid, wiki, round."""
    frac_fixed = scen.frac_no_bid + scen.frac_wiki + scen.frac_round
    n_fixed = int(n_total * frac_fixed / (frac_fixed + scen.frac_shaded + scen.frac_aggressive))
    # Redistribute within the fixed part
    n_nobid = int(scen.frac_no_bid / frac_fixed * n_fixed)
    n_wiki  = int(scen.frac_wiki   / frac_fixed * n_fixed)
    n_round = n_fixed - n_nobid - n_wiki
    bids = np.concatenate([
        np.zeros(n_nobid),
        np.array([15 if rng_py.random() < scen.prob_wiki_exact_15
                  else rng_py.choice(med_sim.WIKI_SECONDARY)
                  for _ in range(n_wiki)]),
        np.array([rng_py.choice(med_sim.ROUND_NUMBERS) for _ in range(n_round)]),
    ])
    return bids, n_fixed


def iterate_levels(scen, n_total=3065, max_level=6, n_sims=80, lam=1.5, seed=42):
    """Run level-k iteration and track the optimal bid at each level."""
    n_rational = n_total - int(n_total * (scen.frac_no_bid + scen.frac_wiki + scen.frac_round))

    rng_np = np.random.default_rng(seed)
    rng_py = random.Random(seed)

    # Level 0: rationals bid their V (naive — full valuation)
    # Level k+1: rationals bid optimal given levels 0..k currently in the field

    # Build Poisson weights for level distribution among rationals
    weights = poisson_weights(lam, max_level)

    bid_sequence = []
    for k in range(max_level + 1):
        # Build the field as it would be if rationals are at levels 0..k
        # with conditional Poisson weights (truncated at k)
        cond = weights[:k+1]
        s = sum(cond); cond = [w/s for w in cond]

        # Monte Carlo
        medians = np.empty(n_sims)
        for sim in range(n_sims):
            nr_bids, _ = build_non_rational_bids(scen, n_total, rng_py)

            # Rationals: sample their V, then assign a level per Poisson weights
            vs = sample_v_for_rationals(n_rational, rng_np)
            levels = rng_py.choices(range(k+1), weights=cond, k=n_rational)

            r_bids = np.empty(n_rational)
            for i, (v, lv) in enumerate(zip(vs, levels)):
                if lv == 0:
                    # L0: bid full V (naive)
                    r_bids[i] = v
                else:
                    # L_lv: bid = b_{lv-1} (the optimal from previous level)
                    r_bids[i] = bid_sequence[lv - 1] if lv - 1 < len(bid_sequence) else v

            all_bids = np.concatenate([nr_bids, r_bids])
            medians[sim] = float(np.median(all_bids))

        # Find optimal bid for level k+1 (our response)
        bid_grid = [1, 10, 15, 25, 50, 100, 150, 200, 300, 500, 750, 1000,
                    1500, 2000, 3000, 5000, 7000, 8000, 10000, 11000, 11194]
        best_b, best_eu, best_p = 0, -1e18, 0
        for b in bid_grid:
            p = float(np.mean(b > medians))
            eu = p * (V_FINALE - b)
            if eu > best_eu:
                best_eu, best_b, best_p = eu, b, p
        bid_sequence.append(best_b)
        med_mean = float(medians.mean())
        print(f"  Level {k+1}: assume field has L0..L{k} rationals (Poisson truncated weights)")
        print(f"           → median = {med_mean:,.0f}   "
              f"→ optimal bid = {best_b:,}   P(win)={best_p:.1%}   E[U]={best_eu:+,.0f}")

    return bid_sequence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="all",
                    choices=["all"] + list(SCENARIOS.keys()))
    ap.add_argument("--lambda", dest="lam", type=float, default=1.5,
                    help="Poisson parameter for cognitive-level distribution (typical 1-2)")
    ap.add_argument("--max-level", type=int, default=5)
    ap.add_argument("--n-sims", type=int, default=80)
    ap.add_argument("--n-teams", type=int, default=3065)
    args = ap.parse_args()

    scenarios = list(SCENARIOS.values()) if args.scenario == "all" else [SCENARIOS[args.scenario]]

    print("═" * 84)
    print("LEVEL-K / COGNITIVE HIERARCHY MODEL")
    print("═" * 84)
    print(f"  V_ours = {V_FINALE:,.0f} finale   λ(Poisson) = {args.lam}   n_teams = {args.n_teams}")
    print("  Assumption: rationals' level of sophistication follows Poisson(λ).")
    print("  Typical distribution with λ=1.5:")
    ws = poisson_weights(args.lam, args.max_level)
    for k, w in enumerate(ws):
        print(f"    P(level={k}) = {w:.1%}")
    print()

    for scen in scenarios:
        print("━" * 84)
        print(f"Scenario: {scen.name}")
        print(f"  Composition: no-bid={scen.frac_no_bid:.0%}  wiki={scen.frac_wiki:.0%}  "
              f"round={scen.frac_round:.0%}  shaded+agg={scen.frac_shaded+scen.frac_aggressive:.0%}")
        print("━" * 84)
        seq = iterate_levels(scen, n_total=args.n_teams, max_level=args.max_level,
                             n_sims=args.n_sims, lam=args.lam)
        print(f"\n  Bid sequence across levels: {seq}")
        # Convergence check
        if len(seq) >= 3 and seq[-1] == seq[-2]:
            print(f"  ⇒ CONVERGED at bid = {seq[-1]:,}")
        else:
            print(f"  ⇒ Non-monotone or still drifting; final = {seq[-1]:,}")

    # Summary
    print()
    print("═" * 84)
    print("GAME-THEORETIC RECOMMENDATION (level-k aware)")
    print("═" * 84)
    print("  If you think ~20% of rationals do L2+ reasoning (λ≈1.5):")
    print("    → optimal bid shifts UPWARD vs level-1 naive.")
    print("  If λ > 2 (highly strategic field):")
    print("    → shifts further up; prepare for bid escalation.")


if __name__ == "__main__":
    main()
