"""Monte Carlo simulator of the MAF median across adversary scenarios.

Approach:
  1. Generate synthetic field of N=3,065 teams matching the R2 backtest
     leaderboard aggregate stats (median=8546, p25=7285, p75=9023, etc.).
  2. Assign each team a V (MAF value) via thresholded-linear proxy:
         V_test = 0.122 × PnL_test  if PnL_test > threshold else 0
  3. Assign each team an archetype per scenario fractions:
         A. No bid()         → bid = 0
         B. Wiki copy-paste  → bid = 15 (exact, from wiki example)
         C. Round-number     → uniform from {10, 50, 100, 500, 1000, 5000}
         D. V-aware shaded   → bid = V_finale × U(0.4, 0.8)
         E. Aggressive       → bid = V_finale × U(1.0, 1.5)
  4. Compute median → determine P(win | bid=X) for our team across many sims.
  5. Compute optimal bid = argmax EV = P(accept) × (V_ours − bid).

All bids in simu-FINALE units.

Usage:
    python research/round_2_MAF/11_median_simulator.py --scenario central --n-sims 2000
    python research/round_2_MAF/11_median_simulator.py --scenario pessimistic
    python research/round_2_MAF/11_median_simulator.py --scenario optimistic
    python research/round_2_MAF/11_median_simulator.py --scenario competitive
"""
from __future__ import annotations
import argparse
import json
import random
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# Our team (from measurement)
OUR_V_FINALE = 11194.0   # break-even in finale XIRECs
FINALE_SCALING = 8.9

# V proxy params (empirical)
V_RATIO = 0.122                   # V_test = 0.122 × PnL_test for active MM teams
V_THRESHOLD_TEST = 7000.0         # below this PnL, team is passive → V ≈ 0
V_CAP_FINALE = 15000.0            # cap V at 15k finale (no team realistically exceeds)

# Wiki example bids (observed in the R2 wiki doc)
WIKI_PRIMARY_BID = 15
WIKI_SECONDARY = [10, 15, 19, 20, 21, 34]
ROUND_NUMBERS = [10, 50, 100, 200, 500, 1000, 5000]


@dataclass
class Scenario:
    name: str
    # Archetype fractions (sum to 1.0) — applied ONLY to teams that submitted trader.py
    # (teams without trader.py are EXCLUDED from the median denominator per IMC FAQ).
    # IMPORTANT: the absolute denominator size does NOT affect the median — only the
    # composition of the submitter pool matters. We model 3,065 (observed lower bound
    # from the aggregator) but results scale invariantly with n.
    frac_no_bid: float
    frac_wiki: float
    frac_round: float
    frac_shaded: float
    frac_aggressive: float
    # Wiki sub-behavior
    prob_wiki_exact_15: float = 0.7   # fraction of wiki-copy that use exactly 15 (vs pick from secondary)
    # V model threshold (test units): below this, team is passive → V=0
    v_threshold_test: float = V_THRESHOLD_TEST
    # Shading ranges
    shaded_lo: float = 0.4
    shaded_hi: float = 0.8
    aggressive_lo: float = 1.0
    aggressive_hi: float = 1.5


# RECALIBRATED scenarios — the 3,065 teams in the denominator are all engaged
# (96% profitable, actively submitted functional trader.py). Therefore the
# fraction of them who *skip* implementing bid() is LOWER than the raw "zombies"
# fraction in the overall registrant pool.
#
# frac_not_submitted = 85% (20k registered → 3065 with trader.py) — INFO ONLY,
# these teams are NOT in the median denominator (IMC rule).
SCENARIOS = {
    # Field of engaged teams — most bother implementing bid()
    "tryhard":        Scenario("tryhard",        0.10, 0.05, 0.05, 0.60, 0.20),  # serious field
    "rational_heavy": Scenario("rational_heavy", 0.20, 0.10, 0.10, 0.45, 0.15),  # pro pool
    "central_eng":    Scenario("central_eng",    0.30, 0.15, 0.15, 0.30, 0.10),  # realistic middle
    "lazy_eng":       Scenario("lazy_eng",       0.45, 0.20, 0.15, 0.15, 0.05),  # engaged but lazy on MAF
    "wiki_sticky":    Scenario("wiki_sticky",    0.30, 0.40, 0.10, 0.15, 0.05),  # wiki=15 dominant
}


# ══════════════════════════════════════════════════════════════════════
# Synthetic team field matching R2 backtest leaderboard stats
# ══════════════════════════════════════════════════════════════════════

def generate_field_pnl_test(n: int, rng: np.random.Generator) -> np.ndarray:
    """Generate n synthetic PnL_test values matching R2 aggregate stats:
       n=3065, median=8546, p25=7285, p75=9023, 96% profitable,
       552 low outliers (worst -90k), 3 high outliers (best ~11.9k)."""
    # Build 3 segments, scaling outlier counts proportionally to n (baseline n=3065)
    n_low = max(1, int(round(552 * n / 3065)))
    n_high = max(1, int(round(3 * n / 3065)))
    n_mid = n - n_low - n_high
    if n_mid <= 0:
        n_mid = max(1, n - 2)
        n_low = max(0, n - n_mid - 1)
        n_high = 1

    # Middle segment: log-normal fit from p25=7285, p50=8546, p75=9023
    # For log-normal: mu = log(median); sigma = log(p75/p25) / (2*0.6745)
    import math
    median = 8546.0
    p25 = 7285.0
    p75 = 9023.0
    mu = math.log(median)
    sigma = math.log(p75 / p25) / (2 * 0.6745)
    mid = rng.lognormal(mu, sigma, size=n_mid)
    # Clip to avoid absurd tails
    mid = np.clip(mid, 4700, 11600)

    # Low outliers: uniform between -90k and field floor 4700
    low = rng.uniform(-90_000, 4700, size=n_low)

    # High outliers: uniform between 11183 and 11900
    high = rng.uniform(11183, 11900, size=n_high)

    return np.concatenate([low, mid, high])


def team_v_test(pnl_test: float, threshold: float) -> float:
    """Proxy: V_test = V_RATIO × PnL_test if above threshold, else 0."""
    if pnl_test < threshold:
        return 0.0
    return V_RATIO * pnl_test


def team_v_finale(pnl_test: float, threshold: float) -> float:
    return min(V_CAP_FINALE, team_v_test(pnl_test, threshold) * FINALE_SCALING)


# ══════════════════════════════════════════════════════════════════════
# Archetype bid sampling
# ══════════════════════════════════════════════════════════════════════

def sample_bid(archetype: str, v_finale: float, rng: random.Random, scen: Scenario) -> float:
    """Sample bid (finale XIRECs) for a team of given archetype and V."""
    if archetype == "A":  # No bid()
        return 0.0
    if archetype == "B":  # Wiki copy
        if rng.random() < scen.prob_wiki_exact_15:
            return WIKI_PRIMARY_BID
        return float(rng.choice(WIKI_SECONDARY))
    if archetype == "C":  # Round number lazy
        return float(rng.choice(ROUND_NUMBERS))
    if archetype == "D":  # V-aware shaded
        if v_finale <= 0:
            # Team without real V but still decides to shade: shade relative to median-team V ~ 9k
            return max(0.0, 9000 * rng.uniform(scen.shaded_lo, scen.shaded_hi))
        return v_finale * rng.uniform(scen.shaded_lo, scen.shaded_hi)
    if archetype == "E":  # Aggressive
        base = v_finale if v_finale > 0 else 9000
        return base * rng.uniform(scen.aggressive_lo, scen.aggressive_hi)
    raise ValueError(archetype)


def assign_archetype(rng: random.Random, scen: Scenario) -> str:
    r = rng.random()
    cum = scen.frac_no_bid
    if r < cum: return "A"
    cum += scen.frac_wiki
    if r < cum: return "B"
    cum += scen.frac_round
    if r < cum: return "C"
    cum += scen.frac_shaded
    if r < cum: return "D"
    return "E"


# ══════════════════════════════════════════════════════════════════════
# Single simulation: generate field + bids → return median
# ══════════════════════════════════════════════════════════════════════

def one_sim(n_teams: int, scen: Scenario, rng_np: np.random.Generator,
            rng_py: random.Random) -> dict:
    pnls = generate_field_pnl_test(n_teams, rng_np)
    bids = np.empty(n_teams, dtype=float)
    for i, pnl in enumerate(pnls):
        v_fin = team_v_finale(float(pnl), scen.v_threshold_test)
        arch = assign_archetype(rng_py, scen)
        bids[i] = max(0.0, sample_bid(arch, v_fin, rng_py, scen))
    med = float(np.median(bids))
    return {
        "median": med,
        "p25": float(np.percentile(bids, 25)),
        "p75": float(np.percentile(bids, 75)),
        "p90": float(np.percentile(bids, 90)),
        "p95": float(np.percentile(bids, 95)),
        "p99": float(np.percentile(bids, 99)),
        "mean": float(np.mean(bids)),
        "n_nonzero": int(np.sum(bids > 0)),
    }


# ══════════════════════════════════════════════════════════════════════
# Multi-sim + optimal bid
# ══════════════════════════════════════════════════════════════════════

def run_scenario(scen: Scenario, n_sims: int, n_teams: int, seed: int):
    rng_np = np.random.default_rng(seed)
    rng_py = random.Random(seed)

    medians, p75s, p95s, means = [], [], [], []
    for _ in range(n_sims):
        res = one_sim(n_teams, scen, rng_np, rng_py)
        medians.append(res["median"])
        p75s.append(res["p75"])
        p95s.append(res["p95"])
        means.append(res["mean"])

    medians = np.array(medians)
    p95s = np.array(p95s)

    print(f"\n━━━ Scenario '{scen.name}' ━━━")
    print(f"  Denominator = teams that submitted trader.py (n={n_teams}, scale-invariant).")
    print(f"  Composition of the submitter pool:")
    print(f"    no-bid={scen.frac_no_bid:.0%}  wiki={scen.frac_wiki:.0%}  "
          f"round={scen.frac_round:.0%}  shaded={scen.frac_shaded:.0%}  agg={scen.frac_aggressive:.0%}")
    print(f"  Median distribution across {n_sims} sims:")
    print(f"    mean    = {medians.mean():>8,.0f}")
    print(f"    std     = {medians.std():>8,.0f}")
    print(f"    p5/p95  = {np.percentile(medians,5):>8,.0f} / {np.percentile(medians,95):>8,.0f}")
    print(f"    min/max = {medians.min():>8,.0f} / {medians.max():>8,.0f}")
    print(f"    {np.mean(medians == 0)*100:.1f}% of sims have median = 0")
    print(f"  Field bid p95 (aggressive tail): mean = {p95s.mean():,.0f}")

    # P(win | bid=X) : bid strictly greater than median wins
    print(f"\n  P(WIN | bid=X) and expected utility (V={OUR_V_FINALE:,.0f} finale):")
    print(f"    {'bid':>8}   {'P(win)':>8}   {'E[payoff]':>10}   {'E[U]':>9}")
    print(f"    {'─'*8:>8}   {'─'*8:>8}   {'─'*10:>10}   {'─'*9:>9}")
    utils = {}
    for bid in [1, 10, 15, 50, 100, 500, 1000, 2000, 3000, 5000, 7000, 8000,
                9000, 10000, 11000, 11194, 12000, 13000, 15000]:
        p_win = float(np.mean(bid > medians))
        ev = p_win * (OUR_V_FINALE - bid)
        utils[bid] = ev
        print(f"    {bid:>8,}   {p_win:>7.1%}   "
              f"{'+'+format(OUR_V_FINALE-bid,',.0f') if OUR_V_FINALE-bid>=0 else format(OUR_V_FINALE-bid,',.0f'):>10}   "
              f"{ev:>+9,.0f}")

    # Optimal
    best_bid = max(utils, key=utils.get)
    p_win_best = float(np.mean(best_bid > medians))
    print(f"\n  Optimal bid:  {best_bid:,}  (P(win)={p_win_best:.1%}, E[U]=+{utils[best_bid]:,.0f})")

    return {
        "scenario": scen.name,
        "median_mean": float(medians.mean()),
        "median_std": float(medians.std()),
        "median_p5": float(np.percentile(medians, 5)),
        "median_p95": float(np.percentile(medians, 95)),
        "pct_zero_median": float(np.mean(medians == 0)),
        "utils": {str(k): float(v) for k, v in utils.items()},
        "optimal_bid": int(best_bid),
        "optimal_p_win": float(p_win_best),
        "optimal_eu": float(utils[best_bid]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="all",
                    choices=["all", "tryhard", "rational_heavy", "central_eng",
                             "lazy_eng", "wiki_sticky"])
    ap.add_argument("--n-sims", type=int, default=1500)
    ap.add_argument("--n-teams", type=int, default=3065)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--save-json", type=str, default=None)
    args = ap.parse_args()

    if args.scenario == "all":
        scenarios = list(SCENARIOS.values())
    else:
        scenarios = [SCENARIOS[args.scenario]]

    print("═" * 78)
    print("MAF MEDIAN SIMULATOR")
    print(f"n_teams={args.n_teams}  n_sims={args.n_sims}  "
          f"V_ours={OUR_V_FINALE:,.0f} finale")
    print("═" * 78)

    results = []
    for sc in scenarios:
        r = run_scenario(sc, args.n_sims, args.n_teams, args.seed)
        results.append(r)

    # Summary table
    print("\n" + "═" * 78)
    print("SUMMARY ACROSS SCENARIOS")
    print("═" * 78)
    print(f"{'Scenario':<14} {'Med mean':>10} {'Med p95':>10} {'P(med=0)':>9} "
          f"{'Optim bid':>10} {'P(win)':>8} {'E[U]':>9}")
    print("─" * 78)
    for r in results:
        print(f"{r['scenario']:<14} {r['median_mean']:>10,.0f} {r['median_p95']:>10,.0f} "
              f"{r['pct_zero_median']:>8.0%} {r['optimal_bid']:>10,} "
              f"{r['optimal_p_win']:>7.1%} {r['optimal_eu']:>+9,.0f}")
    print("═" * 78)

    if args.save_json:
        with open(args.save_json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved to {args.save_json}")


if __name__ == "__main__":
    main()
