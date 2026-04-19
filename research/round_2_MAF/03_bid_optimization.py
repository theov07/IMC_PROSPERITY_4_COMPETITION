"""Model adversary bid distribution + compute optimal bid.

Given the MAF value V (from script 02) and an adversary distribution model,
compute the optimal bid b* that maximizes expected net gain:

  E[U(b)] = P(b > median | dist) × (V − b)

where `median` is over submitted bids, and P(b > median) is the probability
our bid exceeds the median of the submitted adversary pool.

Adversary distribution (post-clarification from IMC FAQ):
  - Only teams with a trader.py are counted (others ignored)
  - Teams without bid() method → counted as 0
  - Negative bids → treated as 0
  - ~2000-3000 active submitting teams

Distribution model (estimated from first principles):
  - 35% submit without bid() method → bid = 0
  - 25% copy wiki example → bid = 15
  - 15% round numbers small → bid ∈ {50, 100, 200, 500}
  - 10% value-anchored low → bid ∈ [1000, 5000]
  - 10% value-anchored high → bid ∈ [5000, 20000]
  - 5% aggressive → bid ∈ [20000, 100000]

Usage:
    python research/round_2_MAF/03_bid_optimization.py --V 20000
    python research/round_2_MAF/03_bid_optimization.py --V 20000 --n_teams 3000 --n_sims 10000
"""
from __future__ import annotations
import argparse
import random
from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass
class AdversaryModel:
    """Mixture model of adversary bid distribution."""
    no_bid_fraction: float = 0.35      # submit without bid() method
    wiki_copy_fraction: float = 0.25   # bid 15
    round_small_fraction: float = 0.15  # round numbers 50-500
    value_low_fraction: float = 0.10   # 1k-5k
    value_high_fraction: float = 0.10  # 5k-20k
    aggressive_fraction: float = 0.05  # 20k-100k

    def sample_bid(self, rng: random.Random) -> float:
        r = rng.random()
        c = 0.0
        c += self.no_bid_fraction
        if r < c:
            return 0.0
        c += self.wiki_copy_fraction
        if r < c:
            # Tiny spread around 15 (some also 10, 19, 20, 34 from wiki example)
            return rng.choice([10, 15, 15, 15, 19, 20, 34])
        c += self.round_small_fraction
        if r < c:
            return rng.choice([50, 100, 200, 300, 500])
        c += self.value_low_fraction
        if r < c:
            return rng.uniform(1000, 5000)
        c += self.value_high_fraction
        if r < c:
            return rng.uniform(5000, 20000)
        return rng.uniform(20000, 100000)

    def sample_population(self, n: int, rng: random.Random) -> np.ndarray:
        return np.array([self.sample_bid(rng) for _ in range(n)])


def simulate_median(model: AdversaryModel, n_teams: int, n_sims: int, seed: int = 0) -> np.ndarray:
    """Return array of simulated medians over n_sims runs with n_teams each."""
    rng = random.Random(seed)
    medians = np.empty(n_sims)
    for i in range(n_sims):
        pop = model.sample_population(n_teams, rng)
        medians[i] = np.median(pop)
    return medians


def expected_utility(bid: float, V: float, medians: np.ndarray) -> tuple[float, float]:
    """Compute E[U(b)] = P(b > median) × (V − b).

    Returns (accept_prob, expected_utility).
    """
    accept_prob = np.mean(bid > medians)
    utility = accept_prob * (V - bid)
    return accept_prob, utility


def find_optimal_bid(V: float, medians: np.ndarray,
                     bid_range: tuple[float, float] = (0, 50000),
                     n_points: int = 500) -> tuple[float, float, float]:
    """Grid-search optimal bid in [lo, hi]. Returns (best_bid, accept_prob, utility)."""
    bids = np.linspace(bid_range[0], bid_range[1], n_points)
    utils = np.array([expected_utility(b, V, medians)[1] for b in bids])
    best_idx = np.argmax(utils)
    best_bid = bids[best_idx]
    accept_prob, util = expected_utility(best_bid, V, medians)
    return best_bid, accept_prob, util


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--V", type=float, default=20000,
                        help="MAF value V in simu finale XIRECs")
    parser.add_argument("--n_teams", type=int, default=3000)
    parser.add_argument("--n_sims", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    model = AdversaryModel()

    print(f"Simulating {args.n_sims} populations of {args.n_teams} adversary bids each...")
    medians = simulate_median(model, args.n_teams, args.n_sims, args.seed)

    print(f"\n━━━ Adversary median distribution ━━━")
    print(f"  mean:   {medians.mean():.1f}")
    print(f"  std:    {medians.std():.1f}")
    print(f"  p5:     {np.percentile(medians, 5):.1f}")
    print(f"  p50:    {np.percentile(medians, 50):.1f}")
    print(f"  p95:    {np.percentile(medians, 95):.1f}")

    print(f"\n━━━ Bid acceptance probabilities (V = {args.V:,.0f}) ━━━")
    print(f"{'Bid':>10} {'P(accepted)':>15} {'V − bid':>12} {'E[U]':>12}")
    print("-" * 55)
    for bid in [0, 15, 50, 100, 200, 500, 800, 1000, 1500, 2000, 3000, 5000, 10000, 20000]:
        p, u = expected_utility(bid, args.V, medians)
        print(f"{bid:>10,} {p:>15.3f} {args.V - bid:>12,.0f} {u:>12,.0f}")

    # Optimal bid
    print("\n━━━ Optimal bid (grid search) ━━━")
    best_bid, best_p, best_u = find_optimal_bid(args.V, medians, bid_range=(0, args.V * 0.5), n_points=500)
    print(f"  Optimal bid:      {best_bid:,.0f}")
    print(f"  P(accepted):      {best_p:.3f}")
    print(f"  Expected utility: {best_u:,.0f}")
    print(f"  Utility as % of V: {100 * best_u / args.V:.1f}%")

    # Sensitivity on V
    print("\n━━━ Sensitivity of optimal bid to V ━━━")
    print(f"{'V':>12} {'Best bid':>12} {'P(acc)':>10} {'E[U]':>12}")
    print("-" * 50)
    for V in [5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000]:
        bb, bp, bu = find_optimal_bid(V, medians, bid_range=(0, V * 0.5), n_points=500)
        print(f"{V:>12,} {bb:>12,.0f} {bp:>10.3f} {bu:>12,.0f}")

    # Risk analysis: downside of common bid choices
    print("\n━━━ Risk analysis: P(reject) and worst-case loss ━━━")
    print("(Reject = we bid and lose; keep full V but don't get MAF)")
    print(f"{'Bid':>10} {'P(accept)':>12} {'P(reject)':>12} {'Cost if reject':>15}")
    print("-" * 55)
    for bid in [0, 500, 1000, 1500, 2000, 3000, 5000]:
        p_acc, _ = expected_utility(bid, args.V, medians)
        p_rej = 1 - p_acc
        print(f"{bid:>10,} {p_acc:>12.3f} {p_rej:>12.3f} {'—  (no cost)':>15}")
    print()
    print("Note: Losing the auction costs nothing (no payment). Only accepted bids pay.")
    print("Therefore downside is capped: max loss = bid if V = 0 (unlikely).")


if __name__ == "__main__":
    main()
