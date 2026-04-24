"""Nash equilibrium + Claude-coordination scenario for the MAF bid (STANDALONE).

Setup:
  V (break-even, our measured MAF value) = 11,194 finale XIRECs
  MAF auction: top 50% of bids accepted (strict > median), pay their own bid
  Our previous reco: bid = 2,173 (anti-focal markup on 2,000)

Key difference vs Manual Speed tournament:
  - Manual Speed has smooth rank → m function with N grand → tie with cluster OK
  - MAF has HARD cutoff at median → strict > needed → tie = LOSE

So in MAF:
  - If Claude-users cluster at 2,173 AND this cluster crosses median
    → tied bids at median LOSE the auction
  - Unilateral deviation to 2,174 (strict > cluster) guarantees a win

Usage:
    python research/round_2_MAF/18_nash_and_claude_scenario.py
"""
from __future__ import annotations
import random
import numpy as np

V_FINALE = 11_194.0   # Our measured V (break-even)
N_TEAMS = 3065

# Archetype wiki constants
WIKI_PRIMARY_BID = 15
WIKI_SECONDARY = [10, 15, 19, 20, 21, 34]
ROUND_NUMBERS = [10, 50, 100, 200, 500, 1000, 5000]


# ═══════════════════════════════════════════════════════════════════
# Minimal adversary model (self-contained from MAF scripts 11-17)
# ═══════════════════════════════════════════════════════════════════

def team_v_finale(pnl_test: float, threshold: float = 7000.0) -> float:
    """V_finale ≈ 0.122 × PnL_test × 8.9 if active MM, else 0."""
    if pnl_test < threshold:
        return 0.0
    v_test = 0.122 * pnl_test
    return min(15000.0, v_test * 8.9)


def generate_pnl_test(n: int, rng: np.random.Generator) -> np.ndarray:
    """Synthetic PnL_test ≈ R2 backtest aggregate stats."""
    import math
    median = 8546.0
    p25, p75 = 7285.0, 9023.0
    mu = math.log(median)
    sigma = math.log(p75/p25) / 1.349
    n_low = max(1, int(round(552 * n / 3065)))
    n_high = max(1, int(round(3 * n / 3065)))
    n_mid = n - n_low - n_high
    mid = rng.lognormal(mu, sigma, n_mid)
    mid = np.clip(mid, 4700, 11600)
    low = rng.uniform(-90_000, 4700, n_low)
    high = rng.uniform(11183, 11900, n_high)
    return np.concatenate([low, mid, high])


def sample_archetype_bid(pnl_test: float, rng: random.Random,
                          frac_no_bid=0.55, frac_wiki=0.15, frac_round=0.10,
                          frac_shaded=0.15, frac_agg=0.05):
    """Sample a bid given archetype."""
    r = rng.random()
    v_fin = team_v_finale(pnl_test)

    if r < frac_no_bid:
        return 0.0
    if r < frac_no_bid + frac_wiki:
        if rng.random() < 0.7:
            return float(WIKI_PRIMARY_BID)
        return float(rng.choice(WIKI_SECONDARY))
    if r < frac_no_bid + frac_wiki + frac_round:
        return float(rng.choice(ROUND_NUMBERS))
    if r < frac_no_bid + frac_wiki + frac_round + frac_shaded:
        base = v_fin if v_fin > 0 else 9000
        return base * rng.uniform(0.4, 0.8)
    # aggressive
    base = v_fin if v_fin > 0 else 9000
    return base * rng.uniform(1.0, 1.5)


def build_adversary_field(n: int, rng_np: np.random.Generator,
                           rng_py: random.Random, scenario="central") -> np.ndarray:
    """Build a field of n bids per scenario."""
    params = {
        "central":     (0.55, 0.15, 0.10, 0.15, 0.05),
        "lazy_eng":    (0.45, 0.20, 0.15, 0.15, 0.05),
        "pessimistic": (0.30, 0.10, 0.15, 0.35, 0.10),
        "wiki_sticky": (0.30, 0.40, 0.10, 0.15, 0.05),
    }[scenario]
    pnls = generate_pnl_test(n, rng_np)
    bids = np.empty(n)
    for i, p in enumerate(pnls):
        bids[i] = max(0.0, sample_archetype_bid(float(p), rng_py, *params))
    return bids


def best_response_bid(field: np.ndarray, grid=None) -> tuple:
    if grid is None:
        grid = [0, 1, 10, 15, 25, 50, 100, 200, 500, 1000, 1500, 2000, 2173, 2200,
                2500, 3000, 5000, 7000, 8000, 10000, 11000, 11194]
    med = float(np.median(field))
    best_b, best_eu = 0, -1e18
    for b in grid:
        p_win = float(b > med)  # strict >
        eu = p_win * (V_FINALE - b)
        if eu > best_eu:
            best_eu, best_b = eu, b
    return best_b, best_eu, med


# ═══════════════════════════════════════════════════════════════════
# PART 1 — Symmetric Nash for MAF
# ═══════════════════════════════════════════════════════════════════

def part_1_nash_symmetric():
    print("═" * 82)
    print("PART 1 — SYMMETRIC NASH for MAF auction")
    print("═" * 82)
    print("""
  Setup: tous les N teams bid b_star.
    - Median = b_star → "bids > b_star" est vide → personne ne gagne → PnL = 0
  Unilateral deviation à b_star + 1:
    - Seul au-dessus → strict > median → gagne
    - EV = V − (b_star + 1)
  Nash: best dev ≤ 0 → nécessite b_star ≥ V − 1 = 11,193
""")

    print(f"  {'b_star':>10}  {'all-at PnL':>12}  {'dev bid':>10} {'dev PnL':>10}  {'Nash?':>7}")
    print("  " + "─" * 65)
    for b_star in [0, 100, 500, 1000, 2000, 2173, 5000, 10000, 11193, 11194, 11500]:
        dev = b_star + 1
        dev_pnl = V_FINALE - dev
        is_nash = dev_pnl <= 0
        tag = "✓" if is_nash else "✗"
        print(f"  {b_star:>10,}  {0:>+12,}  {dev:>10,} {dev_pnl:>+10,.0f}  {tag:>7}")

    print("""
  CONCLUSION:
    - Unique symmetric Nash (en EV absolu) = bid = V − 1 = 11,193
    - À ce point, la déviation à 11,194 donne EV = 0 (zéro gain net)
    - Field REAL non homogène → cette analyse ne suffit pas
""")


# ═══════════════════════════════════════════════════════════════════
# PART 2 — Best-response dynamics (starting from various fields)
# ═══════════════════════════════════════════════════════════════════

def part_2_bestresp_dynamics():
    print("═" * 82)
    print("PART 2 — BEST-RESPONSE DYNAMICS from various adversary fields")
    print("═" * 82)

    for scen in ["central", "lazy_eng", "pessimistic", "wiki_sticky"]:
        rng_np = np.random.default_rng(42)
        rng_py = random.Random(42)
        field = build_adversary_field(N_TEAMS, rng_np, rng_py, scen)

        print(f"\n  Scenario '{scen}': initial median = {np.median(field):,.0f}")
        print(f"  {'Iter':>5}  {'median':>8}  {'best bid':>10}  {'EU':>10}")

        for it in range(8):
            best_b, eu, med = best_response_bid(field)
            print(f"  {it:>5}  {med:>8,.0f}  {best_b:>10,}  {eu:>+10,.0f}")
            # 15% of field updates to best response
            idx = rng_py.sample(range(len(field)), int(0.15 * len(field)))
            for i in idx:
                field[i] = best_b
            if best_b >= V_FINALE - 10:
                print(f"  → SPIRAL reached break-even, stop")
                break


# ═══════════════════════════════════════════════════════════════════
# PART 3 — Claude-coordination scenario
# ═══════════════════════════════════════════════════════════════════

def build_field_with_claude(n: int, frac_claude: float, bid_claude: float,
                              rng_np, rng_py, scen="central") -> np.ndarray:
    n_claude = int(n * frac_claude)
    rest = build_adversary_field(n - n_claude, rng_np, rng_py, scen)
    claude = np.full(n_claude, bid_claude)
    return np.concatenate([claude, rest])


def part_3_claude_coordination():
    print("\n" + "═" * 82)
    print("PART 3 — CLAUDE-COORDINATION: si frac_claude teams bid 2,173")
    print("═" * 82)
    print(f"""
  Claude suggère bid = 2,173 (anti-focal markup sur 2,000).
  Si frac_claude des teams suivent → cluster à 2,173.

  Question: where does the median fall?
    - Si median < 2,173 : Claude's 2,173 WINS (strict >)
    - Si median ≈ 2,173 : cluster tied at median → LOSES
    - Si median > 2,173 : médian dépasse le cluster → cluster loses
""")

    print(f"  {'frac_claude':>12}  {'scenario':<13}  {'median':>8}  "
          f"{'2,173 wins?':>12}  {'best resp':>10}  {'EU best':>10}")
    print("  " + "─" * 80)
    for frac in [0.00, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70]:
        for scen in ["central", "lazy_eng", "pessimistic"]:
            meds, best_bs, best_eus = [], [], []
            for seed in range(30):
                rng_np = np.random.default_rng(seed)
                rng_py = random.Random(seed)
                field = build_field_with_claude(N_TEAMS, frac, 2173, rng_np, rng_py, scen)
                m = float(np.median(field))
                meds.append(m)
                b, eu, _ = best_response_bid(field)
                best_bs.append(b); best_eus.append(eu)

            avg_med = np.mean(meds)
            modal_b = max(set(best_bs), key=best_bs.count)
            avg_eu = np.mean(best_eus)
            tie_2173 = (avg_med < 2173)
            print(f"  {frac:>11.0%}   {scen:<13}  {avg_med:>8,.0f}  "
                  f"{('YES' if tie_2173 else 'NO'):>12}  {modal_b:>10,}  "
                  f"{avg_eu:>+10,.0f}")


# ═══════════════════════════════════════════════════════════════════
# PART 4 — Strategic synthesis
# ═══════════════════════════════════════════════════════════════════

def part_4_synthesis():
    print("\n" + "═" * 82)
    print("PART 4 — SYNTHÈSE")
    print("═" * 82)
    print("""
  DIFFÉRENCE FONDAMENTALE vs Manual Speed:

    Manual Speed (rank-based):
      m(rank 2) ≈ m(rank 1) quand N grand → tie avec cluster Claude OK
      → bid = Claude's reco (z=53) stable

    MAF auction (strict > median):
      bid = median → LOSE (pas de >)
      → must be strictly above cluster to win

  CONSÉQUENCE pour le bid MAF:

    Si frac_claude faible (< 20%) :
      Claude cluster à 2,173 ne domine pas la distribution
      Median reste bas (0 - 600 selon scénario)
      Bid 2,173 reste strict au-dessus → on gagne
      → Keep 2,173

    Si frac_claude élevé (≥ 30%) et scenario central:
      Cluster à 2,173 peut crosser la médiane
      Notre 2,173 tie au median → LOSE
      Need to bid 2,174 (ou plus pour marge)
      → Consider 2,200 or 2,500

    Si scenario pessimistic (field plus competitive):
      Median was already ~594 without Claude
      Even with Claude cluster, median probably stays < 2,173
      → 2,173 OK

  RECOMMANDATION:
    - Default: bid = 2,173 (safe si frac_claude modéré + scénarios stables dominants)
    - Hedge contre Claude-coordination massive: bid = 2,200 (+27 XIRECs cost)
    - Hedge + insurance level-k: bid = 2,500 (+327 cost = 0.16% of live total)

  VERDICT: 2,173 reste le central, avec option 2,200-2,500 si tu crois à
  une adoption massive de Claude (≥ 30% du field).
""")


if __name__ == "__main__":
    part_1_nash_symmetric()
    part_2_bestresp_dynamics()
    part_3_claude_coordination()
    part_4_synthesis()
