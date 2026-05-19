"""Heterogeneous V analysis for MAF — we're top 1%, V ≈ 11,194.

KEY INSIGHT (Léo): the MAF value V is team-dependent.
  - Top teams (like us, rank 34/3065 in R2 backtest): V ≈ 11-15k finale
  - Median teams: V ≈ 5-8k
  - Bottom teams: V ≈ 0-3k (passive strats don't benefit from +25% flow)

Implication:
  - Our V advantage: we can RATIONALLY bid higher than median teams
  - Middle teams max rational bid ≈ 7k (their V)
  - Our break-even is 11,194 (vs their ~5-7k)
  - So we have ~4k of "budget" above typical rational bid

Question: given this asymmetry, how high can we bid safely?

Usage:
    python research/round_2/round_2_MAF/19_heterogeneous_V.py
"""
from __future__ import annotations
import math
import random
import numpy as np

V_FINALE_OURS = 11_194.0
N_TEAMS = 3065


def team_v_from_rank_percentile(rank_pct: float, v_top: float = 15_000) -> float:
    """Map a rank percentile (0=top, 100=bottom) to a V_finale.

    Based on R1 leaderboard data:
      top 5%  (pct 0-5)  → V ~14-15k (strong MM)
      top 30% (5-30)     → V ~10-14k
      middle (30-60)     → V ~6-10k
      lower (60-85)      → V ~3-6k (mixed passive)
      bottom (85-100)    → V ~0-3k (buy-hold, broken strats)
    """
    if rank_pct <= 5:   return v_top - rank_pct * 100          # 15000 → 14500
    if rank_pct <= 30:  return 14500 - (rank_pct - 5) * 100    # 14500 → 12000
    if rank_pct <= 60:  return 12000 - (rank_pct - 30) * 150   # 12000 → 7500
    if rank_pct <= 85:  return max(0, 7500 - (rank_pct - 60) * 180)  # 7500 → 3000
    return max(0, 3000 - (rank_pct - 85) * 200)                # 3000 → 0


def sample_heterogeneous_bids(n: int, rng_np: np.random.Generator,
                                rng_py: random.Random,
                                frac_no_bid=0.45, frac_wiki=0.15, frac_round=0.10,
                                shaded_lo=0.4, shaded_hi=0.8,
                                aggressive_lo=1.0, aggressive_hi=1.5) -> np.ndarray:
    """Build a heterogeneous bid distribution based on team V by rank percentile.

    Each team i has V_i dependent on its rank percentile.
    Archetype distribution over the field:
      - No bid:      frac_no_bid (bid=0)
      - Wiki:        frac_wiki (bid=15)
      - Round:       frac_round (small round number)
      - Shaded:      V_i × U(shaded_lo, shaded_hi)
      - Aggressive:  V_i × U(aggressive_lo, aggressive_hi)
    """
    bids = np.empty(n)
    for i in range(n):
        rank_pct = 100.0 * i / n  # assume teams indexed by rank
        v_i = team_v_from_rank_percentile(rank_pct)

        r = rng_py.random()
        c = frac_no_bid
        if r < c:
            bids[i] = 0.0
            continue
        c += frac_wiki
        if r < c:
            bids[i] = 15.0
            continue
        c += frac_round
        if r < c:
            bids[i] = float(rng_py.choice([10, 50, 100, 500, 1000, 5000]))
            continue
        # shaded vs aggressive (50-50 of rest)
        if rng_py.random() < 0.75:  # mostly shaded
            bids[i] = v_i * rng_py.uniform(shaded_lo, shaded_hi)
        else:
            bids[i] = v_i * rng_py.uniform(aggressive_lo, aggressive_hi)
    return bids


def best_response(field: np.ndarray, grid=None) -> tuple:
    if grid is None:
        grid = list(range(0, 2001, 100)) + list(range(2000, 6001, 200)) + \
               list(range(6000, 11195, 500)) + [11194]
    med = float(np.median(field))
    best_b, best_eu = 0, -1e18
    for b in grid:
        p_win = float(b > med)
        eu = p_win * (V_FINALE_OURS - b)
        if eu > best_eu:
            best_eu, best_b = eu, b
    return best_b, best_eu, med


def main():
    print("═" * 84)
    print("HETEROGENEOUS V ANALYSIS — we're top 1%, V=11,194")
    print("═" * 84)
    print("""
  Unlike the simple archetype model where all rationals share the same V,
  here V varies by team rank:

    rank  0-5%   → V ≈ 14,500 (top teams, strong MM)
    rank  5-30%  → V ≈ 12,000
    rank 30-60%  → V ≈ 10,000-7,500
    rank 60-85%  → V ≈ 7,500-3,000
    rank 85-100% → V ≈ 3,000-0

  Average V in the field ≈ 7,500 (median team).
  Our V = 11,194 (top ~1%).
""")

    # Scenario scan
    print("─" * 84)
    print("SCENARIO GRID: best response given heterogeneous V + adversary archetypes")
    print("─" * 84)

    scenarios = [
        ("naive field",     0.65, 0.20, 0.10),
        ("central",         0.45, 0.15, 0.10),
        ("pessimistic",     0.30, 0.10, 0.15),
        ("competitive",     0.15, 0.05, 0.10),
    ]

    print(f"  {'scenario':<18}  {'field median':>13}  {'mean bid':>10}  "
          f"{'p75 bid':>9}  {'p95 bid':>9}  {'best resp':>10}  {'EU':>10}")
    print("  " + "─" * 82)

    for name, fnb, fwiki, fround in scenarios:
        meds, best_bs, eus = [], [], []
        means, p75s, p95s = [], [], []
        for seed in range(30):
            rng_np = np.random.default_rng(seed)
            rng_py = random.Random(seed)
            field = sample_heterogeneous_bids(
                N_TEAMS, rng_np, rng_py,
                frac_no_bid=fnb, frac_wiki=fwiki, frac_round=fround,
                shaded_lo=0.4, shaded_hi=0.8,
                aggressive_lo=1.0, aggressive_hi=1.5)
            meds.append(float(np.median(field)))
            means.append(float(np.mean(field)))
            p75s.append(float(np.percentile(field, 75)))
            p95s.append(float(np.percentile(field, 95)))
            b, eu, _ = best_response(field)
            best_bs.append(b); eus.append(eu)

        modal_b = max(set(best_bs), key=best_bs.count)
        print(f"  {name:<18}  {np.mean(meds):>13,.0f}  {np.mean(means):>10,.0f}  "
              f"{np.mean(p75s):>9,.0f}  {np.mean(p95s):>9,.0f}  "
              f"{modal_b:>10,}  {np.mean(eus):>+10,.0f}")

    # Key comparison: what do we gain from "V advantage"?
    print("\n" + "─" * 84)
    print("V-ADVANTAGE QUANTIFIED: how much can we exploit being top 1%?")
    print("─" * 84)
    print("""
  Imagine a 'top team' (V=14,500) vs a 'median team' (V=7,500) facing
  the same adversary. Max bid each can profitably make:
""")

    rng_np = np.random.default_rng(42)
    rng_py = random.Random(42)
    scen_name = "central"
    field = sample_heterogeneous_bids(N_TEAMS, rng_np, rng_py,
                                        frac_no_bid=0.45, frac_wiki=0.15, frac_round=0.10)
    med = float(np.median(field))

    print(f"  Adversary scenario: '{scen_name}', median = {med:,.0f}")
    print()
    print(f"  {'team V':>10}  {'max rational bid':>17}  {'best bid vs field':>18}  "
          f"{'EU at best':>11}")
    for v_team, label in [(3000, "bottom V"), (7500, "median V"), (11194, "our V (top 1%)"),
                            (14500, "absolute top V")]:
        grid = list(range(0, int(v_team) + 100, 50))
        best_b, best_eu = 0, -1e18
        for b in grid:
            p_win = float(b > med)
            eu = p_win * (v_team - b)
            if eu > best_eu:
                best_eu, best_b = eu, b
        print(f"  {v_team:>10,}  {v_team - 1:>17,}  {best_b:>18,}  "
              f"{best_eu:>+11,.0f}   ← {label}")

    print()
    print("  INSIGHT:")
    print("    - Median team (V=7,500) is CAPPED at bid < 7,500 (break-even)")
    print("    - Notre V=11,194 nous permet de bid jusqu'à 11,193 rationnellement")
    print("    - Si adversary median is ~100-500, we can bid 100-500 safely")
    print("    - But if adversaries (esp. top teams) bid their V×shade, the")
    print("      competitive distribution could push median to 3-5k → we still")
    print("      have room to win (V=11k vs median=5k)")

    # Part: if many top teams bid near their V, where does median go?
    print("\n" + "─" * 84)
    print("WHAT IF TOP 5% BID NEAR THEIR V? (aggressive top segment)")
    print("─" * 84)

    print(f"  {'top5% shade':>12}  {'median bid':>11}  {'best resp':>10}  "
          f"{'EU':>10}  {'comment':>35}")
    for shade_top in [0.5, 0.7, 0.9, 1.0, 1.2]:
        # Custom simulation: top 5% shade aggressively
        rng_np = np.random.default_rng(42)
        rng_py = random.Random(42)
        bids = np.empty(N_TEAMS)
        for i in range(N_TEAMS):
            pct = 100.0 * i / N_TEAMS
            v_i = team_v_from_rank_percentile(pct)
            r = rng_py.random()
            if pct <= 5:  # top 5% — always bid their V × shade_top
                bids[i] = v_i * shade_top
            elif r < 0.45:
                bids[i] = 0.0
            elif r < 0.60:
                bids[i] = 15.0
            elif r < 0.70:
                bids[i] = rng_py.choice([50, 100, 500, 1000])
            else:
                bids[i] = v_i * rng_py.uniform(0.4, 0.8)

        med_val = float(np.median(bids))
        b, eu, _ = best_response(bids)
        if shade_top >= 1.0:
            comment = f"top bid > V — irrational (EV-neg if win)"
        else:
            comment = f"top teams bid {shade_top:.0%} of V"
        print(f"  {shade_top:>12.0%}  {med_val:>11,.0f}  {b:>10,}  {eu:>+10,.0f}  "
              f"{comment:>35}")

    print()
    print("  CONCLUSION: tant que top-5% shadent (< 1.0 × V), médian bids restent")
    print("  autour de 0-100. Notre 2,173 reste strict above. OPTIMAL DOMINANT.")

    # Final synthesis
    print("\n" + "═" * 84)
    print("VERDICT: our V advantage doesn't change the recommendation much")
    print("═" * 84)
    print("""
  Raison:
    1. Même avec field competitive (top 5% bid 90% of V), median bids ≈ 2-3k
    2. Notre V (11,194) permet de bid jusqu'à 11,193 rationnellement
    3. MAIS la médiane reste largement sous ça → pas besoin de bid haut
    4. Notre avantage V est utile UNIQUEMENT si la médiane bids monte à 5-8k
       → ça n'arrive que si > 50% du field bid rationnellement (très improbable)

  IMPLICATION:
    - Notre reco 2,173 (ou 2,200 contre Claude-coord) EXPLOITE DÉJÀ notre V advantage
    - On capture (V − bid) = 11,194 − 2,173 = 9,021 si on gagne
    - Médian team (V=7,500) devrait bid max 7,500 → peut capter 5k max au même bid
    - → Notre gain ABSOLU est supérieur au leur, MÊME en bidant le même 2,173

  EN RELATIF (vs median team bidding same 2,173):
    - Us: EU = 11,194 − 2,173 = +9,021
    - Median team: EU = 7,500 − 2,173 = +5,327
    - We're +3,694 ahead per auction win (V-advantage captured)

  → Notre V-advantage se matérialise automatiquement dans le spread V − bid.
    Pas besoin de bidder plus haut pour l'exploiter.
""")


if __name__ == "__main__":
    main()
