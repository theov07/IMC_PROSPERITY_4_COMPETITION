"""Focal-point analysis: if many teams cluster at round numbers (25, 30, 33, 40, 50),
we can MATCH that cluster and tie at rank 1, getting m=0.9 while keeping budget for R×S.

Key insight: in a rank-based tournament with TIES sharing rank,
  - If N/2 players cluster at z* and I match z*, I tie at rank 1 with them → m=0.9
  - If I go slightly above (z*+1), they drop to rank 2 (m=0.1), but I'm alone at 1
    → I spent more for same m, they suffer
  - If I go slightly below, I'm at bottom → m=0.1, catastrophic

Given the rank-based structure, FOCAL MATCHING is often the best strategy.

This script tests: given a focal cluster at each round number, what's my best response?

Usage:
    python research/round_2/manual_round_2/05_focal_point_matching.py
"""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("speed_mod", ROOT / "03_speed_tournament.py")
sp = importlib.util.module_from_spec(spec); sys.modules["speed_mod"] = sp
spec.loader.exec_module(sp)


def build_focal_scenario(focal: int, focal_frac: float, n_others: int,
                          rng: np.random.Generator, noise_sigma: int = 8):
    """Scenario: focal_frac of players cluster exactly at 'focal',
       the rest follow a noisy distribution around 30."""
    n_focal = int(n_others * focal_frac)
    n_rest = n_others - n_focal
    focal_bids = np.full(n_focal, focal, dtype=int)
    rest = np.clip(rng.normal(30, noise_sigma, n_rest), 0, 100).astype(int)
    return np.concatenate([focal_bids, rest])


def main():
    rng = np.random.default_rng(42)
    n_others = 2000

    print("═" * 90)
    print("FOCAL-POINT MATCHING: can we exploit clusters at round numbers?")
    print("═" * 90)

    focals_to_test = [20, 25, 30, 33, 40, 50]
    focal_fractions = [0.20, 0.30, 0.40]

    print(f"\n{'focal':>6} {'f_frac':>7}  {'z=focal-1':>10} {'z=focal':>10} "
          f"{'z=focal+1':>11}  {'best z':>7} {'best PnL':>11}")
    print("─" * 90)
    for focal in focals_to_test:
        for ff in focal_fractions:
            others = build_focal_scenario(focal, ff, n_others, rng)
            # Compare PnL at focal-1, focal, focal+1
            pnl_below = sp.compute_pnl(max(0, focal-1), others)["pnl"]
            pnl_match = sp.compute_pnl(focal, others)["pnl"]
            pnl_above = sp.compute_pnl(focal+1, others)["pnl"]
            # Find true best z
            best_z, best_pnl = 0, -1e18
            for z in range(0, 101):
                p = sp.compute_pnl(z, others)["pnl"]
                if p > best_pnl: best_pnl, best_z = p, z
            print(f"{focal:>6} {ff:>7.0%}  {pnl_below:>+10,.0f} {pnl_match:>+10,.0f} "
                  f"{pnl_above:>+11,.0f}  {best_z:>7} {best_pnl:>+11,.0f}")

    # Try a more realistic mix: several focal points AND noise
    print("\n" + "═" * 90)
    print("REALISTIC MIX: multiple focal clusters + noise")
    print("═" * 90)
    realistic_mix = {
        0:  0.08,   # naive 'invest nothing'
        10: 0.05,   # low commitment
        20: 0.07,
        25: 0.15,   # strong focal
        30: 0.12,
        33: 0.18,   # strongest focal ('one-third')
        40: 0.10,
        50: 0.10,   # 'half budget'
        60: 0.05,
        70: 0.05,
        100: 0.05,  # 'YOLO all speed'
    }
    # Build synthetic field
    print("  Field composition:")
    for z, f in realistic_mix.items():
        print(f"    {f:.0%} at z={z}")
    print()

    all_z = []
    for z, f in realistic_mix.items():
        all_z.extend([z] * int(f * n_others))
    # Pad to n_others
    while len(all_z) < n_others:
        all_z.append(30)
    others = np.array(all_z[:n_others])

    # Evaluate each candidate
    print(f"  {'my z':>5}  {'rank':>13}  {'m':>5}  "
          f"{'x':>3} {'y':>3}  {'R×S':>10}  {'PnL':>12}")
    for z in [0, 10, 20, 25, 30, 31, 33, 34, 40, 50, 70]:
        r = sp.compute_pnl(z, others)
        marker = " ← focal" if z in realistic_mix else ""
        print(f"  {z:>5}  {r['rank']:>6}/{len(others)+1:<6}  {r['m']:>5.2f}  "
              f"{r['x']:>3} {r['y']:>3}  {r['R']*r['S']:>10,.0f}  {r['pnl']:>+12,.0f}{marker}")

    # Best response
    best_z, best_pnl = 0, -1e18
    for z in range(0, 101):
        p = sp.compute_pnl(z, others)["pnl"]
        if p > best_pnl: best_pnl, best_z = p, z
    print(f"\n  Best response: z = {best_z}  PnL = {best_pnl:+,.0f}")

    # ---- Show the full landscape to visualize
    print("\n" + "═" * 90)
    print("FULL LANDSCAPE (realistic mix): PnL vs z")
    print("═" * 90)
    print(f"  {'z':>4}  {'PnL':>12}  {'z':>4}  {'PnL':>12}  {'z':>4}  {'PnL':>12}")
    rows = []
    for z in range(0, 101):
        p = sp.compute_pnl(z, others)["pnl"]
        rows.append((z, p))
    # 3 columns
    for i in range(0, len(rows) // 3 + 1):
        parts = []
        for col in range(3):
            idx = i + col * ((len(rows) + 2) // 3)
            if idx < len(rows):
                z, p = rows[idx]
                parts.append(f"{z:>4}  {p:>+12,.0f}")
        if parts:
            print("  " + "  ".join(parts))

if __name__ == "__main__":
    main()
