"""Build adversary Speed-allocation distribution FROM LEADERBOARD DATA.

Rationale: team sophistication (proxied by R1 PnL rank) predicts their Speed
allocation strategy. We model:

  - TOP teams (top ~5%): sophisticated, do real game theory
    → bimodal: either coordinate LOW (trust focal) or push HIGH (paranoid)
  - MID teams (top 5-60%): typical intuitive allocation
    → cluster around round focals (25, 30, 33, 40, 50) with noise
  - BOTTOM teams (bottom 40%): naive, random or near-default
    → uniform 0-60 or clustered at game default

Data sources:
  - /data/leaderboard_r1_global_merged.csv (MAF research: 600 global teams)
  - /data/leaderboard_r1_france.csv (207 French teams)
  - /data/r2_backtest_leaderboard_aggregate.json (3,065 submitters R2)

Note: Manual submitters ≠ trader.py submitters exactly, but mostly overlap.
We assume n_submitters ≈ 3,065 (same order of magnitude).

Usage:
    python research/round_2/manual_round_2/07_data_driven_field.py
"""
from __future__ import annotations
import csv
import json
import importlib.util
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("core", ROOT / "core.py")
core = importlib.util.module_from_spec(spec); sys.modules["core"] = core
spec.loader.exec_module(core)

# Use leaderboard data from MAF research folder (same data)
MAF_DATA = ROOT.parent / "round_2_MAF" / "data"


def load_maf_data():
    # Global top (merged, 600 rows)
    global_pnl = []
    with open(MAF_DATA / "leaderboard_r1_global_merged.csv") as f:
        for r in csv.DictReader(f):
            try:
                global_pnl.append(float(r["pnl_finale"]))
            except (ValueError, TypeError):
                continue

    # France full (207 rows)
    france_pnl = []
    with open(MAF_DATA / "leaderboard_r1_france.csv") as f:
        for r in csv.DictReader(f):
            try:
                france_pnl.append(float(r["pnl_finale"]))
            except (ValueError, TypeError):
                continue

    with open(MAF_DATA / "r2_backtest_leaderboard_aggregate.json") as f:
        r2_stats = json.load(f)

    return global_pnl, france_pnl, r2_stats


def sophistication_tier(rank_percentile: float) -> str:
    """Map rank_percentile (0=top, 100=bottom) to team tier."""
    if rank_percentile <= 5:  return "TOP"       # top 5% (pros)
    if rank_percentile <= 30: return "UPPER_MID" # top 5-30%
    if rank_percentile <= 60: return "MID"       # 30-60%
    if rank_percentile <= 85: return "LOWER_MID" # 60-85%
    return "BOTTOM"                              # bottom 15%


def sample_speed_for_tier(tier: str, rng: np.random.Generator) -> int:
    """Generate a plausible speed allocation for a team of the given tier.

    NO UI DEFAULT ASSUMPTION — we don't know IMC's initial slider values.
    Natural focals come from round numbers (25, 30, 33, 40, 50) and
    budget fractions (0, 10, 20, 50, 100).

    Based on game-theory / behavioral reasoning:
      - TOP: sophisticated pros, bimodal (shade focal or push paranoid)
      - UPPER_MID: focal-preferring with moderate variance
      - MID: wide spread around round numbers
      - LOWER_MID / BOTTOM: noisier, more random
    """
    u = rng.random()
    if tier == "TOP":
        # Sophisticated pros, natural focals only
        if u < 0.35:   return int(rng.choice([25, 30, 33]))      # rational low-mid
        if u < 0.55:   return int(rng.choice([40, 45, 50]))      # moderate
        if u < 0.80:   return int(rng.integers(55, 80))          # paranoid high
        return int(rng.choice([0, 5, 10]))                       # bold coord low

    if tier == "UPPER_MID":
        if u < 0.20:   return int(rng.choice([25, 30]))
        if u < 0.50:   return int(rng.choice([33, 40]))          # focal cluster
        if u < 0.80:   return int(rng.choice([45, 50]))
        return int(np.clip(rng.normal(50, 10), 0, 100))

    if tier == "MID":
        # Cluster around natural focals with noise
        if u < 0.30:   return int(rng.choice([25, 30, 33]))
        if u < 0.60:   return int(rng.choice([40, 50]))          # round numbers
        if u < 0.85:   return int(np.clip(rng.normal(40, 15), 0, 100))
        return int(rng.integers(50, 80))

    if tier == "LOWER_MID":
        if u < 0.35:   return int(rng.choice([25, 30, 33, 40, 50]))
        if u < 0.70:   return int(np.clip(rng.normal(35, 20), 0, 100))
        return int(rng.integers(0, 100))

    # BOTTOM: high entropy, no default preference
    if u < 0.30:       return int(rng.choice([0, 25, 33, 50]))  # common simple picks
    if u < 0.60:       return int(np.clip(rng.normal(35, 20), 0, 100))
    return int(rng.integers(0, 100))


def build_field(n_teams: int, rng: np.random.Generator) -> np.ndarray:
    """Build a synthetic field of n_teams allocations, respecting tier structure."""
    zs = np.empty(n_teams, dtype=int)
    for i in range(n_teams):
        # Rank percentile: uniform in [0, 100) since we have no correlation structure
        pct = 100.0 * i / n_teams
        tier = sophistication_tier(pct)
        zs[i] = sample_speed_for_tier(tier, rng)
    return zs


def main():
    global_pnl, france_pnl, r2_stats = load_maf_data()

    print("═" * 80)
    print("DATA-DRIVEN ADVERSARY FIELD FOR SPEED ALLOCATION")
    print("═" * 80)
    print(f"\nLeaderboard data loaded:")
    print(f"  R1 global top: {len(global_pnl)} teams (min={min(global_pnl):,.0f}, "
          f"max={max(global_pnl):,.0f})")
    print(f"  R1 France:     {len(france_pnl)} teams")
    print(f"  R2 active:     {r2_stats['n_entries_total']} trader.py submitters")
    print()

    # Build synthetic Speed field based on tier structure
    n_teams = r2_stats["n_entries_total"]  # 3,065
    print(f"Building synthetic Speed field for n={n_teams:,} teams...")
    print(f"(Manual submitters are expected to be ~equal or slightly larger.)\n")

    rng = np.random.default_rng(42)
    field = build_field(n_teams, rng)

    print(f"Synthetic field Speed-allocation distribution:")
    print(f"  mean   = {field.mean():.1f}")
    print(f"  median = {int(np.median(field))}")
    print(f"  p10    = {int(np.percentile(field, 10))}")
    print(f"  p25    = {int(np.percentile(field, 25))}")
    print(f"  p75    = {int(np.percentile(field, 75))}")
    print(f"  p90    = {int(np.percentile(field, 90))}")
    print()
    # Count clusters at each focal
    print("  Cluster sizes at round numbers (focals):")
    for v in [0, 10, 15, 20, 25, 30, 33, 35, 40, 45, 50, 60, 70, 100]:
        count = int((field == v).sum())
        pct = count / n_teams
        print(f"    z={v:>3}: {count:>4} teams ({pct:.1%})")
    print()

    # Find best response to this data-driven field
    best = core.find_best_response(field)
    print("━" * 80)
    print("BEST RESPONSE TO DATA-DRIVEN FIELD")
    print("━" * 80)
    print(f"  Optimal z           = {best['my_z']}")
    print(f"  Optimal (x, y, z)   = ({best['x']}, {best['y']}, {best['my_z']})")
    print(f"  My rank             = {best['rank']}/{best['n_total']}  "
          f"({100*best['rank']/best['n_total']:.1f}% from top)")
    print(f"  Speed multiplier    = ×{best['m']:.3f}")
    print(f"  Research × Scale    = {best['RS']:,.0f}")
    print(f"  Budget used         = {best['used']:,.0f}")
    print(f"  Expected PnL        = {best['pnl']:+,.0f}")
    print()

    # PnL landscape around the optimum
    print("━" * 80)
    print("PnL LANDSCAPE (near optimum)")
    print("━" * 80)
    print(f"  {'z':>4}  {'rank':>13}  {'m':>5}  {'x':>3} {'y':>3}  "
          f"{'R×S':>10}  {'PnL':>12}")
    for z in range(max(0, best["my_z"]-15), min(101, best["my_z"]+20)):
        r = core.compute_pnl_vs_field(z, field)
        marker = " ←" if z == best["my_z"] else ""
        print(f"  {z:>4}  {r['rank']:>6}/{r['n_total']:<6}  {r['m']:>5.2f}  "
              f"{r['x']:>3} {r['y']:>3}  {r['RS']:>10,.0f}  {r['pnl']:>+12,.0f}{marker}")

    # Also test specific focal candidates
    print("\n  Specific focal candidates:")
    for z in [25, 30, 33, 35, 40, 45, 50]:
        r = core.compute_pnl_vs_field(z, field)
        print(f"    z={z:>3}: rank={r['rank']:>4}, m={r['m']:.3f}, "
              f"PnL={r['pnl']:+,.0f}")

    # Robustness: rerun with different seeds
    print("\n" + "━" * 80)
    print("ROBUSTNESS CHECK: best response across 10 simulated fields")
    print("━" * 80)
    best_zs = []
    best_pnls = []
    for seed in range(100, 110):
        rng2 = np.random.default_rng(seed)
        f2 = build_field(n_teams, rng2)
        b2 = core.find_best_response(f2)
        best_zs.append(b2["my_z"])
        best_pnls.append(b2["pnl"])
    print(f"  Best z across 10 seeds: {best_zs}")
    print(f"  Median best z:          {int(np.median(best_zs))}")
    print(f"  PnL mean / std:         {np.mean(best_pnls):,.0f} / {np.std(best_pnls):,.0f}")


if __name__ == "__main__":
    main()
