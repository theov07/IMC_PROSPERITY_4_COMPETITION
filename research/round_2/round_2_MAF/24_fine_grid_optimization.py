"""Fine-grid optimization of MAF bid under probability-weighted scenarios.

No more round-number guessing. Grid at +10 increments across [0, V].
Find the TRUE optimum under various prior probabilities.

Process:
  1. Simulate field medians under 6 scenarios (base, pessimistic, claude, competitive, tryhard, full_rational)
  2. For each bid b ∈ [0, 11_194, step=10], compute EU(b) under a prior mix
  3. Sweep priors: P(high-median) ∈ [5%, 50%]
  4. Report TRUE argmax bid at each prior

Usage:
    python research/round_2/round_2_MAF/24_fine_grid_optimization.py
"""
from __future__ import annotations
import random
import numpy as np

V_OURS = 11_194.0
N_TEAMS = 3065


def team_v_by_rank(rank: int, n: int) -> float:
    pct = rank / n
    if pct <= 0.05: return 15_000 - 2000 * (pct / 0.05)
    if pct <= 0.30: return 13_000 - 3000 * ((pct - 0.05) / 0.25)
    if pct <= 0.60: return 10_000 - 4500 * ((pct - 0.30) / 0.30)
    if pct <= 0.85: return max(0, 5_500 - 3500 * ((pct - 0.60) / 0.25))
    return max(0, 2_000 * (1 - (pct - 0.85) / 0.15))


def build_field(n, config, rng):
    bids = np.empty(n)
    fnb = config.get("no_bid", 0.55)
    fw  = config.get("wiki", 0.15)
    fr  = config.get("round", 0.10)
    fcl = config.get("claude_173", 0.0)
    fs  = config.get("shaded_high", 0.15)
    fa  = config.get("aggressive", 0.05)
    for i in range(n):
        v_i = team_v_by_rank(i + 1, n)
        r = rng.random()
        c = fnb
        if r < c: bids[i] = 0.0; continue
        c += fw
        if r < c: bids[i] = 15.0; continue
        c += fr
        if r < c: bids[i] = rng.choice([50, 100, 500, 1000]); continue
        c += fcl
        if r < c: bids[i] = 2173.0; continue
        c += fs
        if r < c:
            bids[i] = v_i * rng.uniform(0.5, 0.8) if v_i > 0 else 0
            continue
        bids[i] = v_i * rng.uniform(1.0, 1.3) if v_i > 0 else 0
    return bids


SCENARIOS = {
    "base":        {"no_bid": 0.55, "wiki": 0.15, "round": 0.10, "shaded_high": 0.15, "aggressive": 0.05},
    "pessimistic": {"no_bid": 0.30, "wiki": 0.10, "round": 0.15, "shaded_high": 0.35, "aggressive": 0.10},
    "claude_30":   {"no_bid": 0.30, "wiki": 0.15, "round": 0.10, "claude_173": 0.30, "shaded_high": 0.10, "aggressive": 0.05},
    "competitive": {"no_bid": 0.15, "wiki": 0.05, "round": 0.10, "shaded_high": 0.55, "aggressive": 0.15},
    "tryhard":     {"no_bid": 0.10, "wiki": 0.05, "round": 0.05, "shaded_high": 0.60, "aggressive": 0.20},
}


def simulate_medians(scenario_key, n_sims=100):
    config = SCENARIOS[scenario_key]
    medians = []
    for seed in range(n_sims):
        rng = random.Random(seed)
        bids = build_field(N_TEAMS, config, rng)
        medians.append(float(np.median(bids)))
    return np.array(medians)


def eu_for_bid(bid: float, medians: np.ndarray) -> float:
    p_win = float(np.mean(bid > medians))
    return p_win * (V_OURS - bid)


def optimal_bid_grid_fine(medians_per_scen: dict, priors: dict,
                            grid_step: int = 25) -> tuple:
    """Fine-grid search of optimal bid under prior-weighted EU."""
    grid = list(range(0, int(V_OURS) + 1, grid_step))
    best_bid, best_eu = 0, -1e18
    all_eus = {}
    for bid in grid:
        weighted_eu = 0
        per_scen = {}
        for scen, meds in medians_per_scen.items():
            eu = eu_for_bid(bid, meds)
            per_scen[scen] = eu
            weighted_eu += priors[scen] * eu
        all_eus[bid] = (weighted_eu, per_scen)
        if weighted_eu > best_eu:
            best_eu, best_bid = weighted_eu, bid
    return best_bid, best_eu, all_eus


def main():
    print("═" * 84)
    print("FINE-GRID OPTIMIZATION — Find TRUE optimal bid (step=25 XIRECs)")
    print("═" * 84)

    # 1. Simulate medians for each scenario
    print("\nSimulating medians per scenario (n_sims=100 each)...")
    medians_per_scen = {}
    for scen in SCENARIOS:
        meds = simulate_medians(scen, n_sims=100)
        medians_per_scen[scen] = meds
        print(f"  {scen:<15}: median avg = {meds.mean():>7,.0f}  "
              f"(p25={np.percentile(meds,25):>6,.0f}, p75={np.percentile(meds,75):>6,.0f})")

    # 2. Multiple priors tested
    priors_list = [
        ("Optimistic (field casual)",       {"base": 0.70, "pessimistic": 0.15, "claude_30": 0.10, "competitive": 0.04, "tryhard": 0.01}),
        ("Central",                         {"base": 0.40, "pessimistic": 0.20, "claude_30": 0.20, "competitive": 0.15, "tryhard": 0.05}),
        ("Pessimistic (field engaged)",     {"base": 0.25, "pessimistic": 0.25, "claude_30": 0.15, "competitive": 0.25, "tryhard": 0.10}),
        ("Very pessimistic",                {"base": 0.15, "pessimistic": 0.20, "claude_30": 0.15, "competitive": 0.30, "tryhard": 0.20}),
    ]

    print("\n" + "═" * 84)
    print("OPTIMAL BID PAR PRIOR (grid step=25)")
    print("═" * 84)

    for label, priors in priors_list:
        assert abs(sum(priors.values()) - 1.0) < 0.001, f"Priors sum = {sum(priors.values())}"
        best_bid, best_eu, all_eus = optimal_bid_grid_fine(medians_per_scen, priors, grid_step=25)

        print(f"\n  Prior: {label}")
        print(f"    Priors: {priors}")
        print(f"    → TRUE optimal bid = {best_bid}  (weighted EU = {best_eu:+,.0f})")

        # Show top 10 bids near optimum
        sorted_bids = sorted(all_eus.keys(), key=lambda b: -all_eus[b][0])[:10]
        print(f"    Top 10 bids by weighted EU:")
        for b in sorted_bids:
            eu, per_scen = all_eus[b]
            scen_str = " ".join([f"{s[:4]}={per_scen[s]:>+7,.0f}" for s in SCENARIOS])
            print(f"      bid={b:>6,}  EU={eu:+,.0f}  |  {scen_str}")

    # 3. Fine-scan around the interesting zone
    print("\n" + "═" * 84)
    print("FINE SCAN zone 1,500-4,000 (step=50) — Central prior")
    print("═" * 84)
    central_priors = priors_list[1][1]
    grid_fine = list(range(1500, 4001, 50))
    print(f"  {'bid':>6}  {'weighted EU':>12}  {'EU base':>8}  {'EU pess':>8}  "
          f"{'EU claude':>10}  {'EU comp':>8}  {'EU try':>8}")

    for bid in grid_fine:
        per_scen = {s: eu_for_bid(bid, medians_per_scen[s]) for s in SCENARIOS}
        weighted = sum(central_priors[s] * per_scen[s] for s in SCENARIOS)
        marker = " ← optimal" if bid in [2100, 2125, 2150, 2175, 2200, 2250, 2300, 2500, 2750, 3000] else ""
        print(f"  {bid:>6,}  {weighted:>+12,.0f}  {per_scen['base']:>+8,.0f}  "
              f"{per_scen['pessimistic']:>+8,.0f}  {per_scen['claude_30']:>+10,.0f}  "
              f"{per_scen['competitive']:>+8,.0f}  {per_scen['tryhard']:>+8,.0f}")

    # 4. Summary: consolidated recommendation
    print("\n" + "═" * 84)
    print("RÉSUMÉ — TRUE optima selon priors")
    print("═" * 84)
    print(f"  {'Prior':<40}  {'Optimal bid':>12}  {'Weighted EU':>12}")
    for label, priors in priors_list:
        best_bid, best_eu, _ = optimal_bid_grid_fine(medians_per_scen, priors, grid_step=25)
        print(f"  {label:<40}  {best_bid:>12,}  {best_eu:>+12,.0f}")

    print("""
  → Le vrai optimal n'est PAS un nombre rond, c'est une valeur concrète
    selon où se situe le EU maximum dans la grille fine.

  Note: grid step=25 pour précision. Step=1 possible mais coût compute,
  et le plateau est plat dans la zone ~2,100-2,300.
""")


if __name__ == "__main__":
    main()
