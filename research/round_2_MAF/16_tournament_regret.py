"""Tournament-aware bid optimization: MINIMIZE RELATIVE RANKING LOSS.

Problem: if top teams bid high and win MAF but WE don't, we fall behind by V
         in the global ranking — this is NOT captured by pure EV analysis.

Framing:
  Consider K competitors likely ranked close to us. For each:
    - If we lose auction AND they win  → we fall behind by V (−V relative)
    - If we win auction AND they lose  → we gain V relative (+V)
    - If both win or both lose          → zero relative change (maybe − bid diff)

  Our goal: maximize RELATIVE PnL vs competitors, not absolute EV.

Model assumption: top K competitors are "sophisticated" — they measure their
own V (~11k like us), do level-k reasoning, and bid in the same region.

We explore: what bid MINIMIZES expected ranking loss vs top competitors?

Usage:
    python research/round_2_MAF/16_tournament_regret.py --scenario central_eng
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
from pathlib import Path
import numpy as np
import random

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("med_sim", ROOT / "11_median_simulator.py")
med_sim = importlib.util.module_from_spec(spec)
sys.modules["med_sim"] = med_sim
spec.loader.exec_module(med_sim)

V_FINALE = med_sim.OUR_V_FINALE
SCENARIOS = med_sim.SCENARIOS


def simulate_medians_with_top_competitors(scen, n_total, n_sims, top_strategy_dist,
                                            rng_np, rng_py):
    """Simulate medians, return also the distribution of top-competitor bids.

    top_strategy_dist: dict mapping bid_level → fraction of top competitors bidding that.
    Example: {500: 0.2, 2000: 0.3, 5000: 0.3, 8000: 0.15, 11000: 0.05}
    """
    medians = np.empty(n_sims)
    # Sample the top competitor bid once per sim (they all draw independently)
    n_top = 100   # top 100 competitors we care about for ranking
    top_bid_levels = list(top_strategy_dist.keys())
    top_bid_weights = list(top_strategy_dist.values())
    top_bids_per_sim = np.empty((n_sims, n_top))

    for i in range(n_sims):
        res = med_sim.one_sim(n_total, scen, rng_np, rng_py)
        medians[i] = res["median"]
        # Sample each of our n_top competitors' bid
        choices = rng_py.choices(top_bid_levels, weights=top_bid_weights, k=n_top)
        top_bids_per_sim[i, :] = choices
    return medians, top_bids_per_sim


def analyze_bid_vs_tournament(bid_ours, medians, top_bids_per_sim):
    """For a given OUR bid, compute relative-PnL vs top-K competitors.

    For each sim and each top competitor:
      our_win = 1 if bid_ours > median else 0
      their_win = 1 if their_bid > median else 0
      our_net = our_win × (V − bid_ours)
      their_net = their_win × (V − their_bid)
      relative = our_net − their_net

    Report mean relative vs top-K competitors averaged over sims.
    """
    n_sims, n_top = top_bids_per_sim.shape
    our_wins = bid_ours > medians  # (n_sims,)
    our_net = our_wins * (V_FINALE - bid_ours)  # (n_sims,)

    their_wins = top_bids_per_sim > medians[:, None]  # (n_sims, n_top)
    their_net = their_wins * (V_FINALE - top_bids_per_sim)  # (n_sims, n_top)

    relative = our_net[:, None] - their_net  # (n_sims, n_top)
    # Mean relative per sim (avg over competitors)
    mean_relative_per_sim = relative.mean(axis=1)
    # Grand mean
    return {
        "our_win_rate": float(our_wins.mean()),
        "our_ev": float(our_net.mean()),
        "mean_relative_vs_top": float(mean_relative_per_sim.mean()),
        "std_relative_vs_top": float(mean_relative_per_sim.std()),
        "worst_case_relative": float(np.percentile(mean_relative_per_sim, 5)),
        "best_case_relative": float(np.percentile(mean_relative_per_sim, 95)),
        # Frequency of "we lose while top competitor wins"
        "pct_we_lose_they_win": float(np.mean(~our_wins[:, None] & their_wins)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="central_eng",
                    choices=["all"] + list(SCENARIOS.keys()))
    ap.add_argument("--n-sims", type=int, default=300)
    ap.add_argument("--n-teams", type=int, default=3065)
    args = ap.parse_args()

    # Model the top competitors' bid distribution:
    # They are sophisticated, V ~ ours, they've done some analysis.
    # Assume a mix: some lazy-rational (low bids), most medium, some aggressive.
    top_strategy = {
        100:    0.10,   # think field is zombie-heavy, bid small
        500:    0.20,   # matched our initial naive optimal
        2000:   0.25,   # moderate shade
        5000:   0.25,   # aggressive shade
        8000:   0.15,   # close to V
        11000:  0.05,   # bid full V (paranoid)
    }
    print("═" * 82)
    print("TOURNAMENT-AWARE BID OPTIMIZATION")
    print("═" * 82)
    print(f"  V_ours = {V_FINALE:,.0f} finale")
    print(f"  Assumed top-100 competitor bid distribution:")
    for b, w in top_strategy.items():
        print(f"    {w:.0%} bid {b:,}")
    print()

    scenarios = list(SCENARIOS.values()) if args.scenario == "all" else [SCENARIOS[args.scenario]]

    for scen in scenarios:
        rng_np = np.random.default_rng(42)
        rng_py = random.Random(42)
        medians, top_bids = simulate_medians_with_top_competitors(
            scen, args.n_teams, args.n_sims, top_strategy, rng_np, rng_py)

        print("━" * 82)
        print(f"Scenario: {scen.name} (no-bid={scen.frac_no_bid:.0%}, "
              f"wiki={scen.frac_wiki:.0%}, shaded+agg={scen.frac_shaded+scen.frac_aggressive:.0%})")
        print(f"  Median (mean across sims): {medians.mean():,.0f}")
        print("━" * 82)

        bid_grid = [0, 50, 150, 500, 1000, 2000, 3000, 5000, 7000, 8000, 10000, 11000]
        print(f"  {'our bid':>8}  {'P(win)':>8}  {'E[U abs]':>10}  "
              f"{'Rel vs top':>11}  {'Worst rel':>10}  {'%lose/theirWin':>15}")
        print(f"  {'─'*8:>8}  {'─'*8:>8}  {'─'*10:>10}  "
              f"{'─'*11:>11}  {'─'*10:>10}  {'─'*15:>15}")
        for b in bid_grid:
            r = analyze_bid_vs_tournament(b, medians, top_bids)
            print(f"  {b:>8,}  {r['our_win_rate']:>7.1%}  "
                  f"{r['our_ev']:>+10,.0f}  {r['mean_relative_vs_top']:>+11,.0f}  "
                  f"{r['worst_case_relative']:>+10,.0f}  {r['pct_we_lose_they_win']:>14.1%}")

        # Find bid maximizing RELATIVE (not absolute EV)
        best_rel_bid, best_rel = 0, -1e18
        for b in bid_grid:
            r = analyze_bid_vs_tournament(b, medians, top_bids)
            if r['mean_relative_vs_top'] > best_rel:
                best_rel = r['mean_relative_vs_top']; best_rel_bid = b
        print(f"\n  → Bid maximizing RELATIVE standing: {best_rel_bid:,} "
              f"(mean relative vs top = {best_rel:+,.0f} finale)")


if __name__ == "__main__":
    main()
