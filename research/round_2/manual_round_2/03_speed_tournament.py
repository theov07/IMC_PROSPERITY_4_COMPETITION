"""Model Speed as a RANK-BASED tournament.

Setup:
  - Each team allocates z% to Speed
  - Rank across all submitters determines multiplier m ∈ [0.1, 0.9]
  - Given my z and the distribution of others' z, compute my m
  - Compute my PnL given optimal (x, y) with x+y = 100-z

Key tradeoff:
  - More z → better rank, higher m, BUT less budget for Research+Scale
  - If I invest z=0 and others invest ≥1, I rank last → m = 0.1 (catastrophic)
  - If I invest z=50, I secure high m but R×S shrinks

Finds: best response z given an adversary z distribution.

Usage:
    python research/round_2/manual_round_2/03_speed_tournament.py
"""
from __future__ import annotations
import math
from typing import List, Tuple
import numpy as np

BUDGET = 50_000


def research(x: float) -> float:
    return 200_000 * math.log(1 + x) / math.log(101)


def scale(y: float) -> float:
    return 7.0 * y / 100.0


def best_xy_given_budget(B: int) -> Tuple[int, int, float]:
    """Given total budget B (in %) for x+y, find optimal (x, y) maximizing R(x)×S(y)."""
    if B <= 0:
        return (0, 0, 0.0)
    best = (0, 0, 0.0)
    for x in range(0, B + 1):
        y = B - x
        prod = research(x) * scale(y)
        if prod > best[2]:
            best = (x, y, prod)
    return best


def speed_mult_from_rank(rank: int, n_ranks: int) -> float:
    """Linear between 0.9 (rank 1) and 0.1 (rank n_ranks). If n_ranks=1, all tied → 0.9."""
    if n_ranks <= 1:
        return 0.9
    return 0.9 - 0.8 * (rank - 1) / (n_ranks - 1)


def compute_my_rank(my_z: int, others_z: np.ndarray) -> Tuple[int, int]:
    """Return (my_rank, n_distinct_ranks)."""
    all_z = np.concatenate([[my_z], others_z])
    sorted_desc = np.sort(all_z)[::-1]
    # Distinct values
    uniq, counts = np.unique(-sorted_desc, return_counts=True)  # unique in desc order
    uniq = -uniq
    # Build rank map: first distinct value → rank 1, next → rank 1+counts[0], etc.
    rank_map = {}
    cumulative = 0
    for v, c in zip(uniq, counts):
        rank_map[v] = cumulative + 1
        cumulative += c
    my_rank = rank_map[my_z]
    n_total = len(all_z)  # use total players as "n_ranks" per wiki example (rank 7 for 7 players)
    return my_rank, n_total


def compute_pnl(my_z: int, others_z: np.ndarray, verbose: bool = False) -> dict:
    """Compute my PnL given my z, others' z, optimal (x,y) derived from budget left."""
    B_xy = 100 - my_z
    x, y, _ = best_xy_given_budget(B_xy)
    rank, n_total = compute_my_rank(my_z, others_z)
    m = speed_mult_from_rank(rank, n_total)
    R = research(x)
    S = scale(y)
    used = (x + y + my_z) / 100.0 * BUDGET
    pnl = R * S * m - used
    if verbose:
        print(f"    z={my_z:3d} → x={x:3d}, y={y:3d}  rank={rank}/{n_total}  m={m:.3f}  "
              f"R×S={R*S:,.0f}  PnL={pnl:+,.0f}")
    return {"my_z": my_z, "x": x, "y": y, "rank": rank, "m": m,
            "R": R, "S": S, "used": used, "pnl": pnl}


def find_best_response(others_z: np.ndarray) -> dict:
    """Find my best z given others' z distribution."""
    best = None
    for z in range(0, 101):
        res = compute_pnl(z, others_z)
        if best is None or res["pnl"] > best["pnl"]:
            best = res
    return best


def main():
    print("═" * 80)
    print("SPEED AS RANK-BASED TOURNAMENT — BEST RESPONSE ANALYSIS")
    print("═" * 80)

    # Explore: given N competitors with various z distributions, what's my best response?
    n_others = 2000
    rng = np.random.default_rng(42)

    scenarios = {
        "all_zero":           np.zeros(n_others, dtype=int),
        "all_ten":            np.full(n_others, 10, dtype=int),
        "all_thirty":         np.full(n_others, 30, dtype=int),
        "all_fifty":          np.full(n_others, 50, dtype=int),
        "uniform_0_50":       rng.integers(0, 51, size=n_others),
        "uniform_0_100":      rng.integers(0, 101, size=n_others),
        "normal_30_std10":    np.clip(rng.normal(30, 10, n_others), 0, 100).astype(int),
        "bimodal":            np.concatenate([
                                 rng.integers(0, 15, n_others//2),
                                 rng.integers(60, 85, n_others//2)]),
        "mostly_low":         np.clip(rng.exponential(15, n_others), 0, 100).astype(int),
        "competitive_heavy":  np.clip(rng.normal(50, 15, n_others), 0, 100).astype(int),
    }

    print(f"\n{'Scenario':<22} {'med z':>6} {'best z':>7} {'my rank':>10} {'m':>5} "
          f"{'x':>3} {'y':>3} {'PnL':>12}")
    print("─" * 80)
    for name, others in scenarios.items():
        res = find_best_response(others)
        print(f"{name:<22} {int(np.median(others)):>6} {res['my_z']:>7} "
              f"{res['rank']:>5}/{len(others)+1:<4} {res['m']:>5.2f} "
              f"{res['x']:>3} {res['y']:>3} {res['pnl']:>+12,.0f}")

    # Detailed look at 'normal_30_std10' — realistic adversary
    print("\n" + "═" * 80)
    print("DETAIL: best response to N(μ=30, σ=10) adversary distribution")
    print("═" * 80)
    others = scenarios["normal_30_std10"]
    print(f"  Adversary distribution stats: mean={others.mean():.1f}, "
          f"median={int(np.median(others))}, p25={int(np.percentile(others,25))}, "
          f"p75={int(np.percentile(others,75))}")
    print(f"  {'my z':>5}  {'rank':>12}  {'m':>5}  "
          f"{'x':>3} {'y':>3}  {'R×S':>10}  {'PnL':>12}")
    for z in [0, 10, 20, 25, 30, 31, 35, 40, 45, 50, 60, 70, 80, 100]:
        r = compute_pnl(z, others)
        print(f"  {z:>5}  {r['rank']:>6}/{len(others)+1:<5}  {r['m']:>5.2f}  "
              f"{r['x']:>3} {r['y']:>3}  {r['R']*r['S']:>10,.0f}  {r['pnl']:>+12,.0f}")


if __name__ == "__main__":
    main()
