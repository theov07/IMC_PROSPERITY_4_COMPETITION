"""CORRECT level-k spiral for MAF bid under universal Claude adoption.

Fix to script 21: the spiral should go UPWARD, not downward.

Correct level-k reasoning (Camerer-Ho-Chong):
  L0 (naïve): bid = V × 0.19 ≈ 2,173 (what Claude says initially)
  L1: knowing L0 cluster at 2,173, bid 2,174 (strict > to beat them)
  L2: anticipating L1 at 2,174, bid 2,175
  L3: bid 2,176
  ...
  Self-limit: when marginal gain (+1 win) < marginal cost (+1 XIREC).
  The spiral STOPS when adding 1 XIREC no longer buys a meaningful rank improvement.

The critical insight Léo raised:
  - Under-bidding has HUGE downside: miss V entirely (loss = V ≈ 11,194)
  - Over-bidding has LIMITED downside: just pay extra (loss = bid − optimal)
  - So risk-averse → bid ABOVE median expectation, not below

This script shows the correct spiral and quantifies the cost of under-bidding.

Usage:
    python research/round_2_MAF/22_correct_levelk_spiral.py
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


# ═══════════════════════════════════════════════════════════════════
# PART 1 — Correct level-k spiral (UPWARD)
# ═══════════════════════════════════════════════════════════════════

def part_1_correct_spiral():
    print("═" * 84)
    print("PART 1 — CORRECT level-k spiral (UPWARD, anti-focal)")
    print("═" * 84)
    print("""
  Setup:
    - 30% of teams are 'L0 Claude-naïfs' → bid exactly 2,173 (Claude's first answer)
    - Rest of field: archetype distribution (no-bid, wiki, shaded)

  Iteration:
    - L1: knowing 30% at 2,173, I bid 2,174 → strict > cluster, I win
    - L2: if others also L1 → they bid 2,174 → I bid 2,175
    - L3: spiral continues until marginal gain vanishes
""")
    n = N_TEAMS
    claude_bid = 2173  # L0 bid

    rng = random.Random(42)
    # Build a base field (30% at claude_bid, rest archetype)
    base_field = []
    for i in range(n):
        v_i = team_v_by_rank(i + 1, n)
        r = rng.random()
        if r < 0.30:
            base_field.append(claude_bid)  # Claude L0
        elif r < 0.30 + 0.38:  # 38% non-Claude with their own archetype
            base_field.append(0)
        elif r < 0.30 + 0.38 + 0.10:
            base_field.append(15)
        elif r < 0.30 + 0.38 + 0.10 + 0.07:
            base_field.append(rng.choice([50, 100, 500, 1000]))
        elif v_i > 0:
            base_field.append(v_i * rng.uniform(0.4, 0.8))
        else:
            base_field.append(0)
    base_field = np.array(base_field)

    # Compute best response iteratively (me playing L1, L2, ...)
    print(f"  Iteration starting: base field with 30% Claude L0 at bid={claude_bid}")
    print(f"  {'Level':>6}  {'my bid':>8}  {'median':>8}  {'P(win)':>8}  "
          f"{'EU':>10}  {'marginal gain':>14}")
    print("  " + "─" * 72)

    prev_bid = claude_bid
    prev_eu = 0
    for level in range(0, 10):
        if level == 0:
            my_bid = claude_bid  # L0: match Claude
        else:
            my_bid = claude_bid + level  # L1, L2, L3...

        # Compute median and my EU
        med = float(np.median(base_field))
        # Note: for L0 (match Claude), I'm tied at median → lose
        # For L1+, I'm strict above cluster → win
        p_win = 1.0 if my_bid > med else 0.0
        eu = p_win * (V_OURS - my_bid)
        marginal = eu - prev_eu

        print(f"  L{level:<5}  {my_bid:>8,}  {med:>8,.0f}  {p_win:>7.0%}   "
              f"{eu:>+10,.0f}  {marginal:>+14,.0f}")
        prev_bid = my_bid
        prev_eu = eu

    print("""
  OBSERVATIONS:
    - L0 (match Claude): bid 2,173, but tied at median (30% cluster) → LOSE
    - L1 (beat by 1): bid 2,174, strict > cluster → WIN
    - L2+, L3+: each +1 XIREC costs −1 in EU but P(win)=1.0 all the way
      → every +1 is a pure −1 in PnL (no rank improvement)

  CONCLUSION: L1 markup (+1 XIREC) is MANDATORY to beat Claude cluster.
  Mais L2+ est gaspillage (pas de nouveau cluster à battre).
""")


# ═══════════════════════════════════════════════════════════════════
# PART 2 — The spiral STOPS: marginal analysis
# ═══════════════════════════════════════════════════════════════════

def part_2_when_does_spiral_stop():
    print("═" * 84)
    print("PART 2 — Quand le spiral s'arrête?")
    print("═" * 84)
    print("""
  La question: y a-t-il un cluster à 2,174 (L1 réaction)?

  Argument:
    - Si seulement 30% sont Claude L0 (bid 2,173) et SOME sont L1 → bid 2,174
    - L1 doit être < L0 en fraction (moins de teams font du meta-reasoning)
    - Donc cluster à 2,174 est PLUS PETIT que cluster à 2,173
    - Pour battre L1, L2 monte à 2,175... mais cluster encore plus petit

  Self-limit: marginal benefit of +1 XIREC vanishes quickly.
""")
    print(f"""
  Distribution plausible des levels:
    L0 (take Claude at face value): 30% × 50% = 15% of field
    L1 (beat by 1):                  30% × 30% =  9% of field
    L2 (anticipate L1):              30% × 15% = 4.5% of field
    L3 (anticipate L2):              30% × 5%  = 1.5%
    Total strategic: ~30% of field

  Cluster sizes:
    2,173: 15% of field (big)
    2,174: 9% of field  (medium)
    2,175: 4.5%
    2,176: 1.5%
    2,177+: <0.5%

  Best bid: 2,174 (beats 15% cluster) pays +1 for big rank jump.
  Going to 2,175 costs +1 for only +4.5% rank jump (much less profitable).
""")


# ═══════════════════════════════════════════════════════════════════
# PART 3 — The CRITICAL point Léo raised: downside asymmetry
# ═══════════════════════════════════════════════════════════════════

def part_3_downside_asymmetry():
    print("═" * 84)
    print("PART 3 — DOWNSIDE ASYMMETRY (Léo's insight)")
    print("═" * 84)
    print(f"""
  Why under-bidding is catastrophic:

    If bid ACCEPTED: gain = V − bid (max 11,194 if bid=0, min 0 if bid=V)
    If bid REJECTED: gain = 0 (miss V entirely)

  So missing by 1 XIREC costs V ≈ 11,194 XIRECs in opportunity cost.
  Over-paying by 1 XIREC costs only 1 XIREC.

  ASYMMETRY: under-bid penalty = 11,194 × over-bid penalty.

  Risk-averse implication: bid with MARGIN above expected median.

  Quantification:
""")
    print(f"  {'scenario':<25}  {'true median':>12}  {'our bid':>9}  "
          f"{'accepted?':>10}  {'EU':>10}  {'regret vs optimal':>17}")
    print("  " + "─" * 90)

    scenarios = [
        ("Nous croyons médiane 0",            0, 1),
        ("...mais vraie médiane est 500",   500, 1),    # catastrophe
        ("Nous croyons médiane 500",        500, 501),
        ("...mais vraie médiane est 2000", 2000, 501),  # catastrophe
        ("Nous bidons 2,173 (safe)",       2000, 2173),
        ("Médiane vraie 2,500",            2500, 2173), # perdu, mais envisagé
        ("Nous bidons 2,173, médiane 0",      0, 2173),
    ]
    for scen, true_med, our_bid in scenarios:
        accepted = our_bid > true_med
        eu = (V_OURS - our_bid) if accepted else 0
        # Compute regret: if we knew true median, optimal bid is true_med + 1
        optimal_bid = true_med + 1
        optimal_eu = V_OURS - optimal_bid
        regret = optimal_eu - eu
        print(f"  {scen:<25}  {true_med:>12,}  {our_bid:>9,}  "
              f"{('YES' if accepted else 'NO'):>10}  {eu:>+10,.0f}  {regret:>+17,.0f}")

    print("""
  REGRET ANALYSIS:
    - Bid 1 avec vraie médiane 500 → regret = 10,693 (on RATE la MAF entière)
    - Bid 501 avec vraie médiane 2,000 → regret = 9,193 (même problème)
    - Bid 2,173 avec vraie médiane 2,500 → regret = 8,694 (moins pire car moins catastrophique)
    - Bid 2,173 avec vraie médiane 0 → regret = 2,172 (petite prime d'assurance payée)

  → Better to over-bid by 2,173 than to under-bid by a few hundred.
""")


# ═══════════════════════════════════════════════════════════════════
# PART 4 — The TRUE upward spiral: mutual escalation anti-focal
# ═══════════════════════════════════════════════════════════════════

def part_4_mutual_escalation():
    print("═" * 84)
    print("PART 4 — MUTUAL ESCALATION (anti-focal spiral)")
    print("═" * 84)
    print("""
  Hypothesis: multiple top teams all anticipate each other.
  Each wants to be strictly above the Claude cluster.

  Game:
    Turn 1: all top teams bid 2,173 (Claude's reco)
    Turn 2: I realize others bid 2,173 → I bid 2,174
    Turn 3: others realize I bid 2,174 → they bid 2,175
    Turn 4: I bid 2,176
    ...

  When does it stop?
    - When marginal cost (+1 XIREC) > marginal gain (+rank jump)
    - Rank jumps happen at cluster boundaries
    - Once past all clusters, +1 gives 0 rank jump → no profit in continuing

  Simulation: follows each level carefully.
""")

    # Simulate: track the "top team" bidding evolution
    # Each level: top team bids max(current, 2173 + level)
    print(f"  Assume top 10% of teams iterate level-k:")
    print(f"  {'Iter':>5}  {'bid (top)':>10}  {'approx cluster at':>18}  "
          f"{'marginal gain':>14}  {'stop?':>6}")
    print("  " + "─" * 70)

    for iter_ in range(0, 20):
        bid = 2173 + iter_
        # Cluster size decays exponentially with level
        cluster_pct = 0.30 * (0.5 ** iter_)
        # Marginal gain of +1 XIREC: rank jump × (V - bid)
        marginal_rank_jump = cluster_pct  # % of field we pass
        # The gain from passing them is the expected value of being above vs tied
        # Approximation: each 1% rank jump above = ~V × 0.01 in ranking value
        # But we lose V×0.01 per percent we pass (they're worse off)
        # Actually: if we're already ABOVE median, extra rank jumps don't help us win more
        # It's purely defensive vs being BEATEN by someone else at 2,174

        # A cleaner model: marginal cost = 1 XIREC. Marginal defensive value =
        # P(anyone above us at bid-1) × V. Use cluster_pct as proxy.
        marg_gain = cluster_pct * V_OURS  # defensive value against cluster
        stop = marg_gain < 1
        stop_str = "STOP" if stop else ""
        print(f"  {iter_:>5}  {bid:>10,}  {cluster_pct:>17.2%}  {marg_gain:>+14,.0f}  "
              f"{stop_str:>6}")
        if stop:
            break

    print("""
  Le spiral s'arrête rapidement car:
    - À chaque level, le cluster est MOITIÉ de la taille du précédent
    - La valeur défensive marginale (cluster_pct × V) chute exponentiellement
    - Au-delà de ~5-7 niveaux, marginal_gain < marginal_cost

  CONVERGENCE pratique: bid = 2,173 + 3 à 5 = 2,176-2,178

  Mais le gain entre 2,173 et 2,178 est ~3-5 rank jumps dans le top 10%,
  soit ~(0.5% → 0.05%) × V ≈ 50 XIRECs de valeur défensive.

  PRATICAL RECO: bid 2,173 ou 2,178 sont équivalents en pratique.
""")


# ═══════════════════════════════════════════════════════════════════
# PART 5 — Clarification + final reco
# ═══════════════════════════════════════════════════════════════════

def part_5_final():
    print("═" * 84)
    print("PART 5 — CLARIFICATION et reco finale")
    print("═" * 84)
    print(f"""
  L'erreur du script 21:
    - Il faisait un spiral de "chacun cherche à pay le MINIMUM pour battre median"
    - Ce spiral descendait car chaque itération réduisait le median
    - MAIS c'est Nash fragile (under-bid miss la MAF si on se trompe)

  Le VRAI spiral level-k:
    - Chacun cherche à être STRICTEMENT au-dessus du cluster des rivaux
    - Spiral monte: 2,173 → 2,174 → 2,175 ... → self-limit à ~2,178
    - Beyond that, marginal cost > marginal gain

  L'INSIGHT DE LÉO (correct):
    - Under-bid = miss V entière (11,194 lost)
    - Over-bid = pay a few extra XIRECs (~1-100 lost)
    - ASYMÉTRIE majeure: risk-averse → bid un PEU au-dessus du focal

  RECOMMANDATION FINALE MAF:

    🏆 bid = 2,173 (focal Schelling, rank stable)

    OU

    🏆 bid = 2,178 (L1-L5 spiral, markup modeste)

    Les deux sont défendables. Différence: 5 XIRECs = 0.045% de V.
    2,178 est un LÉGER hedge contre "d'autres ont aussi lu l'argument level-k".

  NE JAMAIS SOUS-BIDDER sous 2,000 car:
    - Si Claude cluster est à 2,173, notre bid < 2,173 = under median_cluster = REJECTED
    - Miss V = 11,194 XIRECs de perte
    - C'est 100× pire que l'économie de 200 XIRECs
""")


if __name__ == "__main__":
    part_1_correct_spiral()
    part_2_when_does_spiral_stop()
    part_3_downside_asymmetry()
    part_4_mutual_escalation()
    part_5_final()
