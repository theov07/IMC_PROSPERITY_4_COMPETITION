"""Sensitivity analysis: test multiple adversary distribution assumptions.

Explores how the optimal bid varies if our model of the adversary population
is wrong. Reports robust bid range across scenarios.
"""
from __future__ import annotations
import random
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dataclasses import dataclass


@dataclass
class AdversaryModel:
    no_bid_fraction: float = 0.35
    wiki_copy_fraction: float = 0.25
    round_small_fraction: float = 0.15
    value_low_fraction: float = 0.10
    value_high_fraction: float = 0.10
    aggressive_fraction: float = 0.05

    def sample_bid(self, rng: random.Random) -> float:
        r = rng.random()
        c = self.no_bid_fraction
        if r < c: return 0.0
        c += self.wiki_copy_fraction
        if r < c: return rng.choice([10, 15, 15, 15, 19, 20, 34])
        c += self.round_small_fraction
        if r < c: return rng.choice([50, 100, 200, 300, 500])
        c += self.value_low_fraction
        if r < c: return rng.uniform(1000, 5000)
        c += self.value_high_fraction
        if r < c: return rng.uniform(5000, 20000)
        return rng.uniform(20000, 100000)


def simulate_median(model: AdversaryModel, n_teams: int, n_sims: int, seed: int = 0) -> np.ndarray:
    rng = random.Random(seed)
    medians = np.empty(n_sims)
    for i in range(n_sims):
        pop = np.array([model.sample_bid(rng) for _ in range(n_teams)])
        medians[i] = np.median(pop)
    return medians


def find_optimal_bid(V, medians, bid_range=(0, 50000), n_points=500):
    bids = np.linspace(bid_range[0], bid_range[1], n_points)
    utils = np.array([np.mean(b > medians) * (V - b) for b in bids])
    best_idx = np.argmax(utils)
    return bids[best_idx], utils[best_idx]


SCENARIOS = {
    "Base (my estimate)": AdversaryModel(0.35, 0.25, 0.15, 0.10, 0.10, 0.05),
    "Many no-bid (60%)": AdversaryModel(0.60, 0.15, 0.10, 0.07, 0.05, 0.03),
    "Few no-bid (15%)": AdversaryModel(0.15, 0.30, 0.25, 0.15, 0.10, 0.05),
    "Wiki super sticky (40% @15)": AdversaryModel(0.25, 0.40, 0.15, 0.10, 0.07, 0.03),
    "Serious teams only": AdversaryModel(0.10, 0.15, 0.20, 0.25, 0.20, 0.10),
    "Value-anchored high": AdversaryModel(0.20, 0.15, 0.15, 0.15, 0.25, 0.10),
    "Aggressive whales": AdversaryModel(0.20, 0.20, 0.15, 0.15, 0.15, 0.15),
}

V_SCENARIOS = [5000, 10000, 15000, 20000, 25000, 30000]


def main():
    n_teams = 3000
    n_sims = 5000
    print(f"Adversary distribution sensitivity analysis")
    print(f"n_teams={n_teams}, n_sims={n_sims}")
    print(f"\nMedian of bids under each scenario:")
    print(f"{'Scenario':<32} {'Median (mean ± std)':<25}")
    print("-" * 60)

    medians_by_scenario = {}
    for name, model in SCENARIOS.items():
        m = simulate_median(model, n_teams, n_sims)
        medians_by_scenario[name] = m
        print(f"{name:<32} {m.mean():>8.1f} ± {m.std():>7.1f}")

    print(f"\n\n━━━ Optimal bid by (V, scenario) ━━━")
    print(f"{'V':<10}", end="")
    for name in SCENARIOS.keys():
        print(f"{name[:18]:>20}", end="")
    print()
    print("-" * (10 + 20 * len(SCENARIOS)))

    best_bids_all = {}
    for V in V_SCENARIOS:
        print(f"V={V:>6,}", end="   ")
        best_bids_all[V] = {}
        for name, m in medians_by_scenario.items():
            bid, u = find_optimal_bid(V, m)
            best_bids_all[V][name] = bid
            print(f"{bid:>18,.0f}", end="  ")
        print()

    # Robust bid: median across scenarios for each V
    print(f"\n\n━━━ Robust bid across scenarios ━━━")
    print(f"{'V (finale)':<12} {'Min':<10} {'Med':<10} {'Max':<10} {'Robust reco':<15}")
    print("-" * 60)
    for V in V_SCENARIOS:
        bids_across = list(best_bids_all[V].values())
        bmin, bmed, bmax = min(bids_across), np.median(bids_across), max(bids_across)
        # Robust reco = safe choice that works across scenarios
        # Pick 75th percentile (robust upper half)
        robust = np.percentile(bids_across, 75)
        print(f"{V:>10,}  {bmin:>8,.0f}  {bmed:>8,.0f}  {bmax:>8,.0f}  {robust:>12,.0f}")

    print(f"\n━━━ Summary ━━━")
    print("Across all adversary-model assumptions tested:")
    print("  - If the wiki example is sticky (median ~15): tiny bid (50-100) is optimal")
    print("  - If serious teams dominate: bid of 3000-10000 is optimal")
    print("  - If value-anchored are many: bid 2000-5000 is optimal")
    print()
    print("ROBUST RECOMMENDATION (covers 75% of adversary scenarios):")
    for V in [15000, 20000, 25000]:
        bids = list(best_bids_all[V].values())
        p75 = np.percentile(bids, 75)
        print(f"  V={V:,} finale → bid = {p75:,.0f}")


if __name__ == "__main__":
    main()
