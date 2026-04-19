"""Scenario: what if adversary median reaches 2,500+?

Conditions required for median ≥ 2,500:
  - Less than 50% of field bids below 2,500
  - Need many teams bidding HIGH (V × 0.3+ shaded or more)

Realistic scenarios where this could happen:
  - "Competitive field" : < 20% no-bid, most teams do real analysis
  - "Claude + level-k spiral" : Claude cluster + anticipators push median up
  - "Aggressive top": top teams paranoid, bid 50-70% of V

This script:
  1. Compute the PROBA that median exceeds 2,500 under various field compositions
  2. EU analysis: our best bid under probability-weighted scenarios
  3. Break-even check for various hedging strategies

Usage:
    python research/round_2_MAF/23_high_median_scenario.py
"""
from __future__ import annotations
import random
import numpy as np

V_OURS = 11_194.0
N_TEAMS = 3065


def team_v_by_rank(rank: int, n: int) -> float:
    pct = rank / n
    if pct <= 0.05: return 15_000 - 2000 * (pct / 0.05)
    if pct <= 0.30: return 13_000 - 3000 * ((pct - 0.05) / 0.25)
    if pct <= 0.60: return 10_000 - 4500 * ((pct - 0.30) / 0.30)
    if pct <= 0.85: return max(0, 5_500 - 3500 * ((pct - 0.60) / 0.25))
    return max(0, 2_000 * (1 - (pct - 0.85) / 0.15))


def build_field(n, config, rng):
    """config: dict of fractions { 'no_bid', 'wiki', 'round', 'claude_173', 'shaded_low', 'shaded_high', 'aggressive' }"""
    bids = np.empty(n)
    frac_no_bid = config.get("no_bid", 0.50)
    frac_wiki   = config.get("wiki", 0.15)
    frac_round  = config.get("round", 0.10)
    frac_claude = config.get("claude_173", 0.0)
    frac_shade_lo = config.get("shaded_low", 0.0)  # shade 0.2-0.4
    frac_shade_hi = config.get("shaded_high", 0.10)  # shade 0.5-0.8
    frac_agg = config.get("aggressive", 0.05)  # V × 1.0-1.3

    for i in range(n):
        v_i = team_v_by_rank(i + 1, n)
        r = rng.random()
        c = frac_no_bid
        if r < c: bids[i] = 0.0; continue
        c += frac_wiki
        if r < c: bids[i] = 15.0; continue
        c += frac_round
        if r < c: bids[i] = rng.choice([50, 100, 500, 1000]); continue
        c += frac_claude
        if r < c: bids[i] = 2173.0; continue
        c += frac_shade_lo
        if r < c:
            bids[i] = v_i * rng.uniform(0.2, 0.4) if v_i > 0 else 0
            continue
        c += frac_shade_hi
        if r < c:
            bids[i] = v_i * rng.uniform(0.5, 0.8) if v_i > 0 else 0
            continue
        # aggressive
        bids[i] = v_i * rng.uniform(1.0, 1.3) if v_i > 0 else 0
    return bids


# ═══════════════════════════════════════════════════════════════════
# PART 1 — Under which configurations does median reach 2,500+?
# ═══════════════════════════════════════════════════════════════════

def part_1_when_median_2500():
    print("═" * 84)
    print("PART 1 — When does median reach 2,500+?")
    print("═" * 84)
    print("""
  Pour que médian = 2,500, il faut 50% du field bidant ≥ 2,500.
  Testons différentes compositions de field:
""")
    n = N_TEAMS

    configs = [
        # (label, fractions dict)
        ("Current default (central)", {"no_bid": 0.55, "wiki": 0.15, "round": 0.10, "shaded_high": 0.15, "aggressive": 0.05}),
        ("Pessimistic",               {"no_bid": 0.30, "wiki": 0.10, "round": 0.15, "shaded_high": 0.35, "aggressive": 0.10}),
        ("30% Claude @2173",          {"no_bid": 0.30, "wiki": 0.15, "round": 0.10, "claude_173": 0.30, "shaded_high": 0.10, "aggressive": 0.05}),
        ("50% Claude @2173",          {"no_bid": 0.20, "wiki": 0.10, "round": 0.10, "claude_173": 0.50, "shaded_high": 0.05, "aggressive": 0.05}),
        ("Competitive (15% no-bid)",  {"no_bid": 0.15, "wiki": 0.05, "round": 0.10, "shaded_high": 0.55, "aggressive": 0.15}),
        ("Serious tryhard",           {"no_bid": 0.10, "wiki": 0.05, "round": 0.05, "shaded_high": 0.60, "aggressive": 0.20}),
        ("Full rational (V×0.5)",     {"no_bid": 0.10, "wiki": 0.00, "round": 0.00, "shaded_low": 0.00, "shaded_high": 0.90, "aggressive": 0.00}),
    ]

    print(f"  {'Scenario':<30}  {'median':>8}  {'p25':>6}  {'p75':>6}  "
          f"{'proba med≥2500':>15}")
    print("  " + "─" * 75)

    for label, config in configs:
        medians = []
        for seed in range(50):
            rng = random.Random(seed)
            bids = build_field(n, config, rng)
            medians.append(float(np.median(bids)))

        avg_med = np.mean(medians)
        p25 = np.percentile(medians, 25)
        p75 = np.percentile(medians, 75)
        proba_high = np.mean([m >= 2500 for m in medians])
        print(f"  {label:<30}  {avg_med:>8,.0f}  {p25:>6,.0f}  {p75:>6,.0f}  "
              f"{proba_high:>14.0%}")

    print("""
  OBSERVATION:
    Médiane atteint 2,500+ SEULEMENT dans les scénarios très competitive:
    - "Competitive" (15% no-bid): médiane ~2,000-2,500 selon seed
    - "Serious tryhard" (10% no-bid): médiane ~3,000-5,000
    - "Full rational": médiane ~5,000-8,000

  Ces scénarios nécessitent que > 85% du field soit engagé sérieusement.
  Prosperity = compétition étudiante → ces scénarios semblent PEU probables.
""")


# ═══════════════════════════════════════════════════════════════════
# PART 2 — EU analysis under probability-weighted scenarios
# ═══════════════════════════════════════════════════════════════════

def part_2_probability_weighted_eu():
    print("═" * 84)
    print("PART 2 — Espérance d'utilité sous priors PROBA sur scénarios")
    print("═" * 84)
    print("""
  Assignons des probas subjectives à chaque scénario:
    P(current default, médiane ~0-500)      = 40%
    P(pessimistic, médiane ~500-1000)        = 20%
    P(30% Claude, médiane ~100-2173)         = 15%
    P(50% Claude, médiane ~2173)             = 10%
    P(competitive, médiane ~2000-3000)       = 10%
    P(serious tryhard, médiane ~3000-5000)   =  5%
""")

    n = N_TEAMS
    scenarios = {
        "default":    (0.40, {"no_bid": 0.55, "wiki": 0.15, "round": 0.10, "shaded_high": 0.15, "aggressive": 0.05}),
        "pessimistic":(0.20, {"no_bid": 0.30, "wiki": 0.10, "round": 0.15, "shaded_high": 0.35, "aggressive": 0.10}),
        "claude_30":  (0.15, {"no_bid": 0.30, "wiki": 0.15, "round": 0.10, "claude_173": 0.30, "shaded_high": 0.10, "aggressive": 0.05}),
        "claude_50":  (0.10, {"no_bid": 0.20, "wiki": 0.10, "round": 0.10, "claude_173": 0.50, "shaded_high": 0.05, "aggressive": 0.05}),
        "competitive":(0.10, {"no_bid": 0.15, "wiki": 0.05, "round": 0.10, "shaded_high": 0.55, "aggressive": 0.15}),
        "tryhard":    (0.05, {"no_bid": 0.10, "wiki": 0.05, "round": 0.05, "shaded_high": 0.60, "aggressive": 0.20}),
    }

    # Sample medians for each scenario
    medians_per_scen = {}
    for name, (prob, config) in scenarios.items():
        meds = []
        for seed in range(50):
            rng = random.Random(seed)
            bids = build_field(n, config, rng)
            meds.append(float(np.median(bids)))
        medians_per_scen[name] = meds

    # Our best bid grid
    bid_grid = [0, 100, 500, 1000, 2000, 2173, 2178, 2500, 3000, 5000, 7000, 10000]

    print(f"  {'Bid':>6}  " + "  ".join([f"{n_[:12]:>12}" for n_, _ in scenarios.items()]) + "  " + f"{'Weighted EU':>12}")
    print("  " + "─" * 110)

    for bid in bid_grid:
        row = f"  {bid:>6,}  "
        weighted = 0
        for name, (prob, _) in scenarios.items():
            meds = medians_per_scen[name]
            win_rate = np.mean([bid > m for m in meds])
            eu_if_win = V_OURS - bid
            eu = win_rate * eu_if_win
            row += f"{eu:>+12,.0f}  "
            weighted += prob * eu
        row += f"{weighted:>+12,.0f}"
        print(row)

    print()


# ═══════════════════════════════════════════════════════════════════
# PART 3 — Sensitivity: if we put MORE weight on competitive scenarios
# ═══════════════════════════════════════════════════════════════════

def part_3_pessimistic_priors():
    print("═" * 84)
    print("PART 3 — What if Léo croit plus au scénario competitive?")
    print("═" * 84)
    print("""
  Testons 3 priors différents sur la probabilité du 'competitive field':
    - Optimist: proba competitive = 15%
    - Central:  proba competitive = 30%
    - Pessimist: proba competitive = 50%
""")

    n = N_TEAMS
    # Base field (non-competitive)
    base_config = {"no_bid": 0.55, "wiki": 0.15, "round": 0.10, "shaded_high": 0.15, "aggressive": 0.05}
    comp_config = {"no_bid": 0.15, "wiki": 0.05, "round": 0.10, "shaded_high": 0.55, "aggressive": 0.15}
    tryhard_config = {"no_bid": 0.10, "wiki": 0.05, "round": 0.05, "shaded_high": 0.60, "aggressive": 0.20}

    for comp_weight in [0.15, 0.30, 0.50]:
        base_weight = 1 - comp_weight
        tryhard_weight = comp_weight * 0.3  # 30% of competitive is tryhard
        comp_weight_adj = comp_weight - tryhard_weight

        meds_base = [float(np.median(build_field(n, base_config, random.Random(s)))) for s in range(50)]
        meds_comp = [float(np.median(build_field(n, comp_config, random.Random(s)))) for s in range(50)]
        meds_tryhard = [float(np.median(build_field(n, tryhard_config, random.Random(s)))) for s in range(50)]

        print(f"\n  Proba competitive = {comp_weight:.0%}: (base={base_weight:.0%}, "
              f"comp={comp_weight_adj:.0%}, tryhard={tryhard_weight:.0%})")
        print(f"  {'Bid':>6}  {'base':>10}  {'comp':>10}  {'tryhard':>10}  {'Weighted EU':>12}")

        bid_grid = [2000, 2173, 2500, 3000, 5000, 7000, 9000]
        for bid in bid_grid:
            win_base = np.mean([bid > m for m in meds_base])
            win_comp = np.mean([bid > m for m in meds_comp])
            win_tryhard = np.mean([bid > m for m in meds_tryhard])

            eu_base = win_base * (V_OURS - bid)
            eu_comp = win_comp * (V_OURS - bid)
            eu_tryhard = win_tryhard * (V_OURS - bid)

            weighted = (base_weight * eu_base
                      + comp_weight_adj * eu_comp
                      + tryhard_weight * eu_tryhard)
            print(f"  {bid:>6,}  {eu_base:>+10,.0f}  {eu_comp:>+10,.0f}  "
                  f"{eu_tryhard:>+10,.0f}  {weighted:>+12,.0f}")


# ═══════════════════════════════════════════════════════════════════
# PART 4 — Break-even analysis: when does hedging pay off?
# ═══════════════════════════════════════════════════════════════════

def part_4_breakeven_hedge():
    print("\n" + "═" * 84)
    print("PART 4 — BREAK-EVEN: when does hedging (higher bid) pay off?")
    print("═" * 84)
    print("""
  Si on bid 5,000 au lieu de 2,173:
    - Coût additionnel si on gagne de toute façon: 2,827 XIRECs
    - Gain si 5,000 est ACCEPTÉ mais 2,173 ne l'aurait pas été: 6,194 (V-5000)

  Break-even: Si P(2,173 rate) × 6,194 > 2,827 × P(2,173 gagne)
  i.e. P(median > 2,173) × 6,194 > 2,827 × P(median < 2,173)
  P(high) × 6,194 > 2,827 × P(low)
  P(high) / P(low) > 2,827 / 6,194 = 0.456
  P(high) > 0.31 (approx)

  → Si proba(median > 2,173) > 31%, alors hedger à 5,000 est profitable.

  Let's check various bids:
""")

    n = N_TEAMS
    # Assume some "high median" scenarios
    base_config = {"no_bid": 0.55, "wiki": 0.15, "round": 0.10, "shaded_high": 0.15, "aggressive": 0.05}
    comp_config = {"no_bid": 0.15, "wiki": 0.05, "round": 0.10, "shaded_high": 0.55, "aggressive": 0.15}

    for p_high in [0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.70]:
        p_low = 1 - p_high
        meds_low = [float(np.median(build_field(n, base_config, random.Random(s)))) for s in range(30)]
        meds_high = [float(np.median(build_field(n, comp_config, random.Random(s)))) for s in range(30)]

        print(f"\n  P(high-median scenario) = {p_high:.0%}:")
        print(f"  {'Bid':>6}  {'EU':>10}")
        for bid in [2173, 3000, 5000, 7000, 9000]:
            win_low = np.mean([bid > m for m in meds_low])
            win_high = np.mean([bid > m for m in meds_high])
            eu_low = win_low * (V_OURS - bid)
            eu_high = win_high * (V_OURS - bid)
            total_eu = p_low * eu_low + p_high * eu_high
            print(f"  {bid:>6,}  {total_eu:>+10,.0f}")


# ═══════════════════════════════════════════════════════════════════
# PART 5 — Verdict on the question
# ═══════════════════════════════════════════════════════════════════

def part_5_verdict():
    print("\n" + "═" * 84)
    print("PART 5 — RÉPONSE À TA QUESTION: 'médiane peut-elle aller à 2,500?'")
    print("═" * 84)
    print(f"""
  OUI, mais sous conditions strictes:
    - Proba conditionnelle: ~10-20% selon les hypothèses
    - Require: field tryhard, moins de 20% no-bid

  CONTEXTE Prosperity:
    - 3,065 trader.py submitters (field déjà filtré vs registered)
    - 96% profitable → field engagé
    - MAIS majorité sont des étudiants → complexity MAF mal comprise

  RÉALISTE PROBA médian > 2,500:
    - 15-20% selon mon estimate pondéré
    - Dans ce 15-20%, notre 2,173 rate la MAF
    - Perte: 11,194 × 0.15-0.20 = 1,679-2,239 XIRECs attendue

  HEDGING:
    - Bid 5,000 protège contre médiane 2,000-4,999 → +6,194 si ce cas arrive
    - Coût si cas "normal": 2,827 de plus que 2,173
    - Break-even: P(hedging pays off) > 31%

  VERDICT:
    - Si tu estimes P(competitive field) ≥ 30% → bid 5,000 est optimal
    - Si tu estimes P(competitive field) < 30% → bid 2,173 reste optimal
    - Zone d'incertitude: bid 3,000 est un compromis

  Mon estimate personnel: P(competitive) ≈ 20% → 2,173 reste légèrement optimal
  Mais 3,000 est defendable si tu penses 30% de risque scenario competitive.
""")


if __name__ == "__main__":
    part_1_when_median_2500()
    part_2_probability_weighted_eu()
    part_3_pessimistic_priors()
    part_4_breakeven_hedge()
    part_5_verdict()
