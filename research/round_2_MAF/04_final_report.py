"""Consolidated final report on MAF bid optimization.

Reads outputs from scripts 01-03 and produces a single report with:
  - Value V measurement from synthetic backtest
  - Adversary distribution under multiple scenarios
  - Optimal bid recommendation (robust + point estimate)
  - Downside/upside analysis
  - Final recommendation

Usage:
    python research/round_2_MAF/04_final_report.py --V 20000
"""
from __future__ import annotations
import argparse
import random
import numpy as np
from pathlib import Path
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class AdversaryModel:
    no_bid_fraction: float = 0.35
    wiki_copy_fraction: float = 0.25
    round_small_fraction: float = 0.15
    value_low_fraction: float = 0.10
    value_high_fraction: float = 0.10
    aggressive_fraction: float = 0.05

    def sample_bid(self, rng):
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


def sim_medians(model, n_teams=3000, n_sims=10000, seed=0):
    rng = random.Random(seed)
    return np.array([np.median([model.sample_bid(rng) for _ in range(n_teams)]) for _ in range(n_sims)])


def optimal_bid(V, medians, bid_range=(0, 50000), n_points=1000):
    bids = np.linspace(bid_range[0], bid_range[1], n_points)
    utils = np.array([np.mean(b > medians) * (V - b) for b in bids])
    best = np.argmax(utils)
    return bids[best], np.mean(bids[best] > medians), utils[best]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--V", type=float, default=20000, help="MAF value (finale XIRECs)")
    args = parser.parse_args()

    print("=" * 75)
    print("MAF BID OPTIMIZATION — CONSOLIDATED REPORT")
    print("=" * 75)
    print()

    print("━━━ Step 1: MAF value V (measured from synthetic +25% data) ━━━")
    print(f"  V ≈ {args.V:,.0f} finale XIRECs (to refine from script 02 results)")
    print()

    print("━━━ Step 2: Adversary bid distribution (estimated) ━━━")
    print("  Post-clarification from IMC FAQ:")
    print("    - Only teams with submitted trader.py count toward median")
    print("    - Missing bid() method → 0, negative bids → 0")
    print()
    print("  Base model (7 scenarios tested in 03b):")
    print("    35% no bid() method   → bid = 0")
    print("    25% wiki copy-paste   → bid = 15")
    print("    15% round small       → bid ∈ {50, 100, 200, 300, 500}")
    print("    10% value-anchored lo → bid ∈ [1k, 5k]")
    print("    10% value-anchored hi → bid ∈ [5k, 20k]")
    print("    5%  aggressive whales → bid ∈ [20k, 100k]")
    print()

    base_model = AdversaryModel()
    base_medians = sim_medians(base_model, n_sims=10000)
    print(f"  Simulated median: {base_medians.mean():.1f} ± {base_medians.std():.1f}")
    print()

    print("━━━ Step 3: Bid optimization (V = {:,.0f}) ━━━".format(args.V))
    best_bid, p_acc, util = optimal_bid(args.V, base_medians)
    print(f"  Base scenario optimal bid:   {best_bid:,.0f}")
    print(f"  P(accepted):                 {p_acc:.1%}")
    print(f"  Expected utility:            {util:,.0f} ({100*util/args.V:.1f}% of V)")
    print()

    print("━━━ Step 4: Sensitivity across scenarios ━━━")
    scenarios = {
        "Base":                      AdversaryModel(0.35, 0.25, 0.15, 0.10, 0.10, 0.05),
        "Many lazy (60% no bid)":    AdversaryModel(0.60, 0.15, 0.10, 0.07, 0.05, 0.03),
        "Few lazy (15% no bid)":     AdversaryModel(0.15, 0.30, 0.25, 0.15, 0.10, 0.05),
        "Wiki super sticky":         AdversaryModel(0.25, 0.40, 0.15, 0.10, 0.07, 0.03),
        "Serious teams dominate":    AdversaryModel(0.10, 0.15, 0.20, 0.25, 0.20, 0.10),
        "Value-anchored high":       AdversaryModel(0.20, 0.15, 0.15, 0.15, 0.25, 0.10),
    }
    print(f"  {'Scenario':<26} {'Median':>10} {'Optimal bid':>14} {'E[U]':>12}")
    print(f"  " + "-" * 64)
    all_bids = []
    for name, model in scenarios.items():
        m = sim_medians(model, n_sims=5000)
        bb, p, u = optimal_bid(args.V, m)
        all_bids.append(bb)
        print(f"  {name:<26} {m.mean():>10.1f} {bb:>14,.0f} {u:>12,.0f}")
    print()
    print(f"  Bid range across scenarios: {min(all_bids):,.0f} — {max(all_bids):,.0f}")
    print(f"  75th percentile (robust):   {np.percentile(all_bids, 75):,.0f}")
    print()

    print("━━━ Step 5: Final recommendation ━━━")
    robust_bid = np.percentile(all_bids, 75)
    print(f"  V assumed:                   {args.V:,.0f}")
    print(f"  Base-scenario optimal bid:   {best_bid:,.0f}")
    print(f"  Robust recommendation (p75): {robust_bid:,.0f}")
    print()
    print("  Decision matrix:")
    print(f"    Risk-taker (trust base model):     bid = {best_bid:,.0f}")
    print(f"    Balanced (robust across models):   bid = {robust_bid:,.0f}")
    print(f"    Ultra-safe (covers aggressive adv): bid = 3,000 — 5,000")
    print()
    print("━━━ Downside analysis ━━━")
    print("  First-price auction: if rejected, NO payment (downside = 0).")
    print("  If accepted, we pay OUR OWN bid. Max cost = our bid.")
    print("  Therefore bidding 1,500 has max loss 1,500 — cheap probe.")
    print()
    print("  Net expected gain by bid:")
    for b in [100, 500, 1000, 1500, 2000, 3000]:
        p, _ = np.mean(b > base_medians), 0
        p = float(np.mean(b > base_medians))
        ev = p * (args.V - b)
        print(f"    bid {b:>5,}: P(acc)={p:.1%}, E[gain]={ev:>+8,.0f}")
    print()

    print("=" * 75)
    print("FINAL VERDICT")
    print("=" * 75)
    print(f"  Recommended bid: {robust_bid:,.0f} XIRECs (finale units)")
    print(f"  Rationale: beats median under 75% of adversary scenarios,")
    print(f"             captures {100 * (args.V - robust_bid) / args.V:.0f}% of MAF value V if accepted,")
    print(f"             downside ≤ {robust_bid:,.0f} XIRECs if V turns out lower than estimated.")
    print("=" * 75)


if __name__ == "__main__":
    main()
