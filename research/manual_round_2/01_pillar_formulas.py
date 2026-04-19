"""Pillar formulas for Manual Round 2 "Invest & Expand".

Verifies the 3 pillar formulas from the wiki against the in-game forecasts.

Setup:
  - Budget = 50,000 XIRECs
  - Allocate x%, y%, z% to Research, Scale, Speed (x+y+z ≤ 100, int)
  - Budget_Used = (x+y+z)/100 × 50,000

Formulas:
  - Research(x) = 200,000 × ln(1+x) / ln(1+100)    — logarithmic, max 200k at 100%
  - Scale(y)    = 7 × y / 100                       — linear, max 7 at 100%
  - Speed(z)    = rank-based, [0.1, 0.9] linear across ranks of all submitters

PnL = Research(x) × Scale(y) × Speed(rank) − Budget_Used

Game's "Research forecast" at x=40 shows 160,931. Let's verify:
  Research(40) = 200000 × ln(41) / ln(101) = 160,944 ≈ 160,931 ✓

Game's "Scale forecast" at y=25 shows ×1.8.
  Scale(25) = 7 × 0.25 = 1.75 ≈ 1.8 (rounded to 1 decimal) ✓

Usage:
    python research/manual_round_2/01_pillar_formulas.py
"""
from __future__ import annotations
import math


def research(x: float) -> float:
    """Research reward given x% invested (0-100)."""
    return 200_000 * math.log(1 + x) / math.log(1 + 100)


def scale(y: float) -> float:
    """Scale multiplier given y% invested (0-100)."""
    return 7.0 * y / 100.0


def speed_multiplier(rank: int, n_distinct_ranks: int) -> float:
    """Speed multiplier given rank (1 = best, N = worst).

    Linear between 0.9 (rank 1) and 0.1 (rank N).
    n_distinct_ranks = total number of rank positions across all submitters.
    """
    if n_distinct_ranks <= 1:
        return 0.9  # everyone ties → all top
    return 0.9 - 0.8 * (rank - 1) / (n_distinct_ranks - 1)


def budget_used(x: float, y: float, z: float) -> float:
    return (x + y + z) / 100.0 * 50_000


def pnl(x: float, y: float, z: float, speed_mult: float) -> float:
    return research(x) * scale(y) * speed_mult - budget_used(x, y, z)


def main():
    print("═" * 70)
    print("PILLAR FORMULAS — VERIFICATION")
    print("═" * 70)

    # Verify Research forecast at x=40
    r40 = research(40)
    print(f"\nResearch(40%) = {r40:,.2f}   (game shows 160,931 ≈ {r40:,.0f}) {'✓' if abs(r40-160931)<100 else '✗'}")

    # Verify Scale forecast at y=25
    s25 = scale(25)
    print(f"Scale(25%)    = ×{s25:.2f}        (game shows ×1.8)            {'✓' if abs(s25-1.75)<0.01 else '✗'}")

    # Speed examples from wiki
    print(f"\nSpeed rank examples:")
    print(f"  With 7 players [70,70,70,50,40,40,30] → ranks [1,1,1,4,5,5,7]")
    for rank in [1, 4, 5, 7]:
        print(f"    rank {rank}: speed_mult = {speed_multiplier(rank, 7):.3f}")
    print(f"  With 3 players [95,20,10] → ranks [1,2,3]")
    for rank in [1, 2, 3]:
        print(f"    rank {rank}: speed_mult = {speed_multiplier(rank, 3):.3f}")

    # Table of PnL outcomes for standard allocations
    print("\n" + "═" * 70)
    print("PnL OUTCOMES — varying speed rank and allocation")
    print("═" * 70)
    configs = [
        ("balanced", 40, 25, 35),
        ("research-heavy", 50, 30, 20),
        ("scale-heavy", 30, 50, 20),
        ("speed-heavy", 25, 25, 50),
        ("all-research", 100, 0, 0),
        ("full-coverage", 33, 33, 34),
    ]
    for mult in [0.1, 0.3, 0.5, 0.7, 0.9]:
        print(f"\nWith speed_mult = {mult:.1f}:")
        print(f"  {'Config':<18} {'x':>4} {'y':>4} {'z':>4}   {'Research':>10} {'Scale':>6}   {'PnL':>12}")
        for name, x, y, z in configs:
            p = pnl(x, y, z, mult)
            print(f"  {name:<18} {x:>4} {y:>4} {z:>4}   {research(x):>10,.0f} {scale(y):>6.2f}   {p:>+12,.0f}")


if __name__ == "__main__":
    main()
