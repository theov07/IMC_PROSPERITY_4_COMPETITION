"""Nash equilibrium analysis for Manual Round 2 Speed tournament.

Two approaches:
  1. SYMMETRIC NASH: find z* such that if all N teams play z*, no team has
     incentive to deviate. Check stability against unilateral deviation.
  2. BEST-RESPONSE DYNAMICS: start from various initial allocations, iterate
     best response, see if/where it converges.

Formally, symmetric Nash z* satisfies:
     z* = argmax_z  PnL(z, others_all_at_z*)

The tricky part: with everyone at z*, they all tie at rank 1 → all m=0.9.
Deviation to z*+1: you rank 1 alone, others tied at rank 2.

Speed multiplier formula: m(rank) = 0.9 - 0.8 × (rank-1)/(N-1)
For N=3000, rank 2 still gives m ≈ 0.8997 (almost 0.9) → unilateral deviation
upward doesn't hurt others much.

Usage:
    python research/manual_round_2/10_nash_equilibrium.py
"""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("core", ROOT / "core.py")
core = importlib.util.module_from_spec(spec); sys.modules["core"] = core
spec.loader.exec_module(core)

spec_df = importlib.util.spec_from_file_location("df", ROOT / "07_data_driven_field.py")
dfmod = importlib.util.module_from_spec(spec_df); sys.modules["df"] = dfmod
spec_df.loader.exec_module(dfmod)


# ═══════════════════════════════════════════════════════════════════
# PART 1 — Symmetric Nash check: all at z*, deviations tested
# ═══════════════════════════════════════════════════════════════════

def test_symmetric_nash(z_star: int, n: int = 3065) -> dict:
    """All N teams play z_star. Test best response for one deviator."""
    # Non-deviator PnL: all tied rank 1, m=0.9
    bx, by, _ = core.best_xy_given_budget(100 - z_star)
    pnl_at_z = (core.research(bx) * core.scale(by) * 0.9
                - core.budget_used(bx, by, z_star))

    # Best response: what z maximizes PnL assuming others all play z_star?
    others = np.full(n - 1, z_star, dtype=int)
    best = core.find_best_response(others)

    is_nash = (best["my_z"] == z_star or best["pnl"] <= pnl_at_z + 1)
    return {
        "z_star": z_star,
        "symmetric_pnl": pnl_at_z,
        "best_response_z": best["my_z"],
        "best_response_pnl": best["pnl"],
        "profitable_deviation": best["pnl"] - pnl_at_z,
        "is_nash": is_nash,
        "xy_at_z_star": (bx, by),
    }


def part_1_symmetric_nash():
    print("═" * 82)
    print("PART 1 — SYMMETRIC NASH: is z* Nash if all N teams play z*?")
    print("═" * 82)
    print("""
  Setup: N=3,065 teams, tous jouent z_star.
  Tous tied rank 1, tous m=0.9.
  Question: a-t-on intérêt à dévier ?

  Deviation upward (z*+1): je rank 1 alone, autres rank 2 → m ≈ 0.9 pour tous
    (diff négligeable car N grand, m(rank 2) = 0.9 - 0.8/2999 = 0.8997)
    Coût: 500 XIRECs de budget, gain: ε → NON profitable

  Deviation downward (z*-1): je rank 2 seul, autres rank 1 → m=0.1 pour moi, 0.9 pour eux
    PERTE catastrophique → jamais profitable
""")

    print(f"  {'z*':>4}  {'(x, y)':>10}  {'PnL sym':>12}  {'best dev z':>12} "
          f"{'PnL dev':>12}  {'gain dev':>10}  {'Nash?':>8}")
    print("  " + "─" * 80)
    for z_star in [0, 5, 10, 20, 25, 30, 33, 40, 50, 60, 70, 80]:
        r = test_symmetric_nash(z_star)
        tag = "✓" if r["is_nash"] else "✗"
        print(f"  {z_star:>4}  {str(r['xy_at_z_star']):>10}  "
              f"{r['symmetric_pnl']:>+12,.0f}  {r['best_response_z']:>12} "
              f"{r['best_response_pnl']:>+12,.0f}  {r['profitable_deviation']:>+10,.0f}  "
              f"{tag:>8}")

    print()
    print("  CONCLUSION: tous les z* entre 0 et ~60 sont Nash (deviation upward")
    print("  n'apporte rien car m ≈ 0.9 reste). Équilibre MULTIPLE, coordination focale")
    print("  détermine lequel est sélectionné.")
    print()
    print("  PARETO-OPTIMAL Nash: z*=0 (PnL=618k pour tous). Fragile si coordination")
    print("  impossible (aucun mécanisme de communication).")


# ═══════════════════════════════════════════════════════════════════
# PART 2 — Best-response dynamics (Cournot-like iteration)
# ═══════════════════════════════════════════════════════════════════

def best_response_dynamics(initial_field: np.ndarray, n_iter: int = 30,
                             fraction_updating: float = 0.1,
                             rng: np.random.Generator = None) -> list:
    """Iterate best response: at each step, a fraction of teams updates to their BR."""
    if rng is None: rng = np.random.default_rng(42)
    field = initial_field.copy()
    trajectory = [field.copy()]
    for t in range(n_iter):
        n = len(field)
        # Update a random fraction to best response
        idx_update = rng.choice(n, size=int(n * fraction_updating), replace=False)
        for i in idx_update:
            others = np.delete(field, i)
            br = core.find_best_response(others)
            field[i] = br["my_z"]
        trajectory.append(field.copy())
    return trajectory


def part_2_best_response_dynamics():
    print("\n" + "═" * 82)
    print("PART 2 — BEST-RESPONSE DYNAMICS (Cournot-type iteration)")
    print("═" * 82)
    print("""
  Start from various initial conditions, let teams best-respond iteratively
  (10% update per round). See where it converges.
""")

    rng = np.random.default_rng(42)
    n_teams = 500  # smaller for computation speed

    initial_conditions = {
        "all_zero": np.zeros(n_teams, dtype=int),
        "all_fifty": np.full(n_teams, 50, dtype=int),
        "uniform_0_100": rng.integers(0, 101, n_teams),
        "normal_30": np.clip(rng.normal(30, 10, n_teams), 0, 100).astype(int),
        "data_driven": dfmod.build_field(n_teams, rng),
    }

    print(f"  Starting with N={n_teams} teams, 10% update per round, 15 rounds")
    print()
    for name, init in initial_conditions.items():
        rng2 = np.random.default_rng(42)
        traj = best_response_dynamics(init, n_iter=15, fraction_updating=0.10, rng=rng2)
        # Stats over time
        print(f"  Initial '{name}': mean={init.mean():.1f} median={np.median(init):.0f}")
        for t in [0, 3, 5, 10, 15]:
            if t < len(traj):
                f = traj[t]
                print(f"    iter {t:>3}: mean={f.mean():>5.1f}  median={np.median(f):>3.0f}  "
                      f"p25={np.percentile(f,25):>3.0f}  p75={np.percentile(f,75):>3.0f}  "
                      f"top-10%={np.percentile(f, 90):>3.0f}")
        print()


# ═══════════════════════════════════════════════════════════════════
# PART 3 — Mixed-strategy Nash via fictitious play approximation
# ═══════════════════════════════════════════════════════════════════

def fictitious_play(n_teams: int = 500, n_iter: int = 50,
                     rng: np.random.Generator = None) -> tuple:
    """Fictitious play: each team plays best response to EMPIRICAL history of opponents."""
    if rng is None: rng = np.random.default_rng(42)
    # Initialize: all random
    field = rng.integers(0, 101, n_teams)
    # Track history: each team's avg z over time (for empirical expectation)
    history = [field.copy()]
    for t in range(n_iter):
        # Empirical distribution from history average
        empirical = np.mean(history, axis=0).astype(int)
        # Each team plays BR to empirical (subset to save compute)
        n_update = min(50, n_teams)
        idx = rng.choice(n_teams, size=n_update, replace=False)
        for i in idx:
            others_emp = np.delete(empirical, i)
            br = core.find_best_response(others_emp)
            field[i] = br["my_z"]
        history.append(field.copy())
    return field, history


def part_3_fictitious_play():
    print("═" * 82)
    print("PART 3 — FICTITIOUS PLAY (approximate Nash search)")
    print("═" * 82)
    print("""
  Each team plays best response to empirical history of others' plays.
  If it converges → approximate mixed Nash.
""")
    rng = np.random.default_rng(42)
    final, history = fictitious_play(n_teams=300, n_iter=30, rng=rng)

    print(f"  Final (after 30 iter): mean={final.mean():.1f}  median={np.median(final):.0f}")
    print(f"  p25={np.percentile(final, 25):.0f}  p75={np.percentile(final, 75):.0f}")
    print()

    # Show which values are most common
    from collections import Counter
    c = Counter(final)
    top_values = sorted(c.items(), key=lambda x: -x[1])[:10]
    print(f"  Top 10 most-played z values:")
    for v, count in top_values:
        print(f"    z={v:>3}: {count} teams ({100*count/len(final):.1f}%)")

    # Compute mean best response to the final distribution
    best = core.find_best_response(final)
    print(f"\n  Best response to final distribution: z={best['my_z']}, PnL={best['pnl']:+,.0f}")
    if best["my_z"] == int(round(final.mean())) or abs(best["my_z"] - np.median(final)) < 3:
        print(f"  → Fictitious play CONVERGED: best response ≈ empirical median")


if __name__ == "__main__":
    part_1_symmetric_nash()
    part_2_best_response_dynamics()
    part_3_fictitious_play()
