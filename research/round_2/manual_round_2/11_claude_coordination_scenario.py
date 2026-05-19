"""Meta-scenario: what if many teams use Claude (or any frontier LLM) to decide?

Hypothesis: if frac_claude of the field consults Claude Opus 4.7 (or similar),
they all get a similar recommendation (say z_claude). This creates a MASSIVE
cluster at z_claude — much larger than any natural focal.

Questions:
  1. For varying frac_claude, what's the best response?
  2. If we KNOW Claude says z_claude, should we deviate to z_claude+1?
  3. Fixed-point: if everyone is "level-Claude-1" (beat Claude by 1),
     where does the spiral stop?

This is the strategic version of "Claude's output is the new focal point".

Usage:
    python research/round_2/manual_round_2/11_claude_coordination_scenario.py
"""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
spec_core = importlib.util.spec_from_file_location("core", ROOT / "core.py")
core = importlib.util.module_from_spec(spec_core); sys.modules["core"] = core
spec_core.loader.exec_module(core)

spec_df = importlib.util.spec_from_file_location("df", ROOT / "07_data_driven_field.py")
dfmod = importlib.util.module_from_spec(spec_df); sys.modules["df"] = dfmod
spec_df.loader.exec_module(dfmod)


def build_mixed_field(n_teams: int, frac_claude: float, z_claude: int,
                      rng: np.random.Generator) -> np.ndarray:
    """frac_claude of teams at z_claude, rest from data-driven distribution."""
    n_claude = int(n_teams * frac_claude)
    n_rest = n_teams - n_claude
    claude_part = np.full(n_claude, z_claude, dtype=int)
    rest = dfmod.build_field(n_rest, rng)
    return np.concatenate([claude_part, rest])


def part_1_scan_frac_claude():
    print("═" * 82)
    print("PART 1 — Best response vs varying Claude-adoption fraction")
    print("═" * 82)
    print(f"  Hypothesis: Claude recommends z=53 (notre reco)")
    print(f"  How does our best response shift as more teams follow Claude?")
    print()

    n_teams = 3065
    z_claude = 53
    rng = np.random.default_rng(42)

    print(f"  {'frac_claude':>12}  {'n_claude':>8}  {'field median':>13}  "
          f"{'best z':>7}  {'rank':>10}  {'m':>5}  {'PnL':>12}")
    print("  " + "─" * 78)
    for frac in [0.00, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.70, 1.00]:
        rng2 = np.random.default_rng(42)
        field = build_mixed_field(n_teams, frac, z_claude, rng2)
        best = core.find_best_response(field)
        print(f"  {frac:>11.0%}   {int(n_teams*frac):>8,}  {int(np.median(field)):>13}  "
              f"{best['my_z']:>7}  {best['rank']:>4}/{best['n_total']:<4}  "
              f"{best['m']:>5.2f}  {best['pnl']:>+12,.0f}")


def part_2_spiral_anticipation():
    print("\n" + "═" * 82)
    print("PART 2 — META-spiral: what if everyone anticipates Claude's reco?")
    print("═" * 82)
    print("""
  Naive: Claude says z=53, we play z=53. But if others also use Claude and
  ANTICIPATE that Claude-users cluster at 53, they might bid z=54 to strictly
  outrank them.

  Iterated reasoning:
    L-Claude-0: play Claude's answer = 53
    L-Claude-1: knowing others play 53, play 54
    L-Claude-2: knowing others play 54, play 55
    ...

  When does this spiral stop?
""")
    n_teams = 3065
    rng = np.random.default_rng(42)

    # Start with all at z=53 (Claude users)
    # Each level k+1 = best response if others are at z_k
    print(f"  Assuming 30% of teams are Claude-users, cluster at z_k at level k:")
    print(f"  {'Level':>6}  {'z_k (cluster)':>15}  {'our best resp':>15}  "
          f"{'rank':>10}  {'PnL':>12}")

    z_k = 53
    for k in range(8):
        rng2 = np.random.default_rng(42 + k)
        field = build_mixed_field(n_teams, 0.30, z_k, rng2)
        best = core.find_best_response(field)
        print(f"  {k:>6}  {z_k:>15}  {best['my_z']:>15}  "
              f"{best['rank']:>4}/{best['n_total']:<4}  {best['pnl']:>+12,.0f}")
        if best["my_z"] <= z_k:
            print(f"  → SPIRAL STOPS at z_k={z_k}: no more profit to deviate")
            break
        z_k = best["my_z"]


def part_3_everyone_on_claude():
    print("\n" + "═" * 82)
    print("PART 3 — Extreme case: 100% of teams use Claude and agree on z=53")
    print("═" * 82)
    print("""
  If LITERALLY everyone plays z=53, they all tie rank 1 → m=0.9 for all.
  Deviation to z=54 (our case): rank 1 alone, others rank 2 (m ≈ 0.8997).
""")
    n = 3065
    # All at 53
    rng = np.random.default_rng(42)
    others = np.full(n - 1, 53, dtype=int)

    # Nos choices
    print(f"  {'our z':>6}  {'rank':>10}  {'m':>5}  {'x':>3} {'y':>3}  {'R×S':>10}  {'PnL':>12}  {'Δ vs 53':>10}")

    base_r = core.compute_pnl_vs_field(53, others)
    for z in [50, 52, 53, 54, 55, 60, 70]:
        r = core.compute_pnl_vs_field(z, others)
        delta = r["pnl"] - base_r["pnl"]
        marker = " ← Claude"if z == 53 else ""
        print(f"  {z:>6}  {r['rank']:>4}/{r['n_total']:<4}  {r['m']:>5.3f}  "
              f"{r['x']:>3} {r['y']:>3}  {r['RS']:>10,.0f}  {r['pnl']:>+12,.0f}  "
              f"{delta:>+10,.0f}{marker}")

    print()
    print("  → Si tout le monde agree sur z=53, DÉVIER à 54 te donne +1 rank (négligeable m)")
    print("  → Mais cela te coûte 500 XIRECs. Best response: RESTER à 53 (match cluster)")


def part_4_claude_not_perfectly_coordinated():
    print("\n" + "═" * 82)
    print("PART 4 — Claude is not consistent: users get slightly different answers")
    print("═" * 82)
    print("""
  Realistically, Claude's answer varies with user's wording:
    - "what z should I pick?" → 53
    - "what's optimal given my level-k concern?" → 55
    - "conservative estimate?" → 50
    - "aggressive but safe?" → 60

  So Claude-users cluster NEAR z=53 but not exactly at it.
""")
    n_teams = 3065
    rng = np.random.default_rng(42)

    # Model Claude-users as Normal(53, σ=3), others as data-driven
    for sigma_claude in [0, 1, 2, 3, 5]:
        rng2 = np.random.default_rng(42)
        n_claude = int(n_teams * 0.30)
        claude = np.clip(rng2.normal(53, sigma_claude, n_claude), 0, 100).astype(int)
        rest = dfmod.build_field(n_teams - n_claude, rng2)
        field = np.concatenate([claude, rest])
        best = core.find_best_response(field)
        print(f"  σ_Claude={sigma_claude}: field median={int(np.median(field))}, "
              f"best z={best['my_z']}, rank={best['rank']}/{best['n_total']}, "
              f"PnL={best['pnl']:+,.0f}")

    print()
    print("  → Plus Claude est consistent (σ→0), plus le cluster est rigide")
    print("  → Plus Claude varie (σ↑), plus il dilue dans la noise du field")


def part_5_strategic_response_to_claude_fact():
    print("\n" + "═" * 82)
    print("PART 5 — RECOMMANDATION stratégique si tu sais que Claude est utilisé")
    print("═" * 82)
    print("""
  Stratégie A — Match Claude (coord focal):
    Play z=53, tie with ~30% of field → safe m, PnL solid

  Stratégie B — Beat Claude by 1 (anti-focal):
    Play z=54, beat the ~30% cluster → rank jump, PnL slightly better

  Stratégie C — Anticipate beat-by-1 (level 2):
    Play z=55, beat the beat-by-1 strategists

  Stratégie D — Mid-stop (level 3+):
    Play z=56-58, hedge against all levels

  Numerical comparison:
""")
    n_teams = 3065
    rng = np.random.default_rng(42)
    # 30% at z=53, 70% data-driven
    field = build_mixed_field(n_teams, 0.30, 53, rng)

    print(f"  {'strategy':>20}  {'z':>3}  {'rank':>10}  {'m':>5}  {'PnL':>12}")
    for name, z in [("A: Match Claude", 53),
                     ("B: Beat by 1", 54),
                     ("C: Anticipate L2", 55),
                     ("D: Hedged L3", 57),
                     ("E: Paranoid L4", 60)]:
        r = core.compute_pnl_vs_field(z, field)
        print(f"  {name:>20}  {z:>3}  {r['rank']:>4}/{r['n_total']:<4}  "
              f"{r['m']:>5.2f}  {r['pnl']:>+12,.0f}")

    print()
    # Compute best overall under different assumptions
    for frac_c in [0.05, 0.10, 0.20, 0.30, 0.50]:
        rng2 = np.random.default_rng(42)
        f2 = build_mixed_field(n_teams, frac_c, 53, rng2)
        b2 = core.find_best_response(f2)
        print(f"  If frac_claude={int(frac_c*100)}%: best z = {b2['my_z']}, "
              f"PnL = {b2['pnl']:+,.0f}")


if __name__ == "__main__":
    part_1_scan_frac_claude()
    part_2_spiral_anticipation()
    part_3_everyone_on_claude()
    part_4_claude_not_perfectly_coordinated()
    part_5_strategic_response_to_claude_fact()
