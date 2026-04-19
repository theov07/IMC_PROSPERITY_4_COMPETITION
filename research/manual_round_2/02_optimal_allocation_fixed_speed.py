"""Find optimal (x, y, z) allocation given a FIXED speed multiplier.

Approach: grid search over all integer (x, y, z) with x + y + z ≤ 100.
For each speed multiplier m ∈ [0.1, 0.9], find the argmax PnL.

Key insight: PnL = Research(x) × Scale(y) × m − Budget_Used
            Budget_Used = (x+y+z)/100 × 50,000

Since Scale is linear in y and Research is log-concave in x, the optimum
is interior or at a boundary. With z acting only through m (and Budget_Used),
the decision for z is: "invest just enough to secure your target m".

For this script, we assume m is EXOGENOUS (set by adversary behavior) and
find the best (x, y, z). The game-theoretic choice of z is in script 03.

Usage:
    python research/manual_round_2/02_optimal_allocation_fixed_speed.py
"""
from __future__ import annotations
import math
from typing import Tuple

BUDGET = 50_000


def research(x: float) -> float:
    return 200_000 * math.log(1 + x) / math.log(101)


def scale(y: float) -> float:
    return 7.0 * y / 100.0


def pnl(x: int, y: int, z: int, m: float) -> float:
    used = (x + y + z) / 100.0 * BUDGET
    return research(x) * scale(y) * m - used


def grid_search_best(m: float) -> Tuple[int, int, int, float]:
    best = (-1, -1, -1, -1e18)
    for x in range(0, 101):
        for y in range(0, 101 - x):
            for z in range(0, 101 - x - y + 1):
                p = pnl(x, y, z, m)
                if p > best[3]:
                    best = (x, y, z, p)
    return best


def main():
    print("═" * 78)
    print("OPTIMAL ALLOCATION vs FIXED SPEED MULTIPLIER (grid search, int %)")
    print("═" * 78)
    print(f"{'m':>5}  {'x (R)':>6} {'y (S)':>6} {'z (Sp)':>7}  "
          f"{'Research':>10} {'Scale':>6}  {'Used':>8}  {'PnL':>14}")
    print("─" * 78)

    results = []
    for m in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        x, y, z, p = grid_search_best(m)
        results.append((m, x, y, z, p))
        used = (x+y+z)/100 * BUDGET
        print(f"{m:>5.1f}  {x:>6} {y:>6} {z:>7}  "
              f"{research(x):>10,.0f} {scale(y):>6.2f}  {used:>8,.0f}  {p:>+14,.0f}")

    # Interesting question: does optimal always put z at minimum?
    print("\n" + "═" * 78)
    print("KEY OBSERVATIONS")
    print("═" * 78)

    # Check if optimal z is always 0
    all_z = [r[3] for r in results]
    if all(z == 0 for z in all_z):
        print("  → Optimal z is ALWAYS 0 when speed multiplier is exogenous!")
        print("    (Speed contributes only via m, not via z investment).")
        print("    This means: if you can secure m=X without investing in speed,")
        print("                put ALL your budget into research + scale.")
    else:
        print(f"  → Optimal z varies: {sorted(set(all_z))}")

    # Research-Scale split at each m
    print("\n  Research:Scale ratio at optimum:")
    for m, x, y, z, p in results:
        if x + y > 0:
            pct_x = 100 * x / (x + y)
            print(f"    m={m:.1f}: x={x:>3} y={y:>3} z={z:>3} "
                  f"→ Research {pct_x:>5.1f}% / Scale {100-pct_x:>5.1f}%")

    # Sanity: the optimum when m is exogenous favors Scale
    print("\n  Note: when m is exogenous, corner solutions may dominate.")
    print("  Real decision depends on expected m via the Speed tournament (script 03).")

    # Show sensitivity: how much does PnL change if we deviate from optimal x?
    print("\n" + "═" * 78)
    print("SENSITIVITY: PnL vs x (holding y, z at their optimum) for m=0.5")
    print("═" * 78)
    m_check = 0.5
    _, y_opt, z_opt, _ = grid_search_best(m_check)
    print(f"  (y={y_opt}, z={z_opt} fixed)")
    print(f"  {'x':>4}   {'PnL':>12}   {'diff vs opt':>12}")
    best_p = max(pnl(x, y_opt, z_opt, m_check) for x in range(0, 101 - y_opt - z_opt + 1))
    for x in range(0, 101 - y_opt - z_opt + 1, 5):
        p = pnl(x, y_opt, z_opt, m_check)
        print(f"  {x:>4}   {p:>+12,.0f}   {p - best_p:>+12,.0f}")


if __name__ == "__main__":
    main()
