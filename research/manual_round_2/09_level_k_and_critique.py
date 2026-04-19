"""Level-k reasoning for Speed tournament + critique of (40, 25, 35).

Two contributions:
  1. CRITIQUE of the starting allocation (40, 25, 35) — show WHY suboptimal
  2. LEVEL-K reasoning: if others run our analysis and converge on z*, focal
     shifts → need to iterate

Level-k logic for Speed (like we did for MAF):
  L0: naive players ignore Speed, pick round number (35 UI default or 30 or 50)
  L1: plays best response to L0 distribution (= our script 08 result, z=40-50)
  L2: knowing L1 converges on 50, expect cluster there → match 50 or go 51+
  L3: if L2 goes 51+, expect cluster at 51 → go 52+ → spiral...

Key insight: spiral bounded by Research × Scale collapse. Above z=55 or so,
PnL starts dropping even if m→0.9. So spiral self-limits.

Usage:
    python research/manual_round_2/09_level_k_and_critique.py
"""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
spec_core = importlib.util.spec_from_file_location("core", ROOT / "core.py")
core = importlib.util.module_from_spec(spec_core); sys.modules["core"] = core
spec_core.loader.exec_module(core)

spec_df = importlib.util.spec_from_file_location("data_field", ROOT / "07_data_driven_field.py")
df = importlib.util.module_from_spec(spec_df); sys.modules["data_field"] = df
spec_df.loader.exec_module(df)


def pnl_detail(x, y, z, m):
    R, S = core.research(x), core.scale(y)
    return {
        "R": R, "S": S, "m": m, "RS": R*S,
        "gross": R * S * m,
        "used": core.budget_used(x, y, z),
        "pnl": R * S * m - core.budget_used(x, y, z),
    }


# ═══════════════════════════════════════════════════════════════════════
# PART 1 — CRITIQUE of (40, 25, 35)
# ═══════════════════════════════════════════════════════════════════════

def critique_404025():
    print("═" * 82)
    print("PART 1 — Pourquoi (Research=40, Scale=25, Speed=35) est SUBOPTIMAL")
    print("═" * 82)

    # Base numbers
    x, y, z = 40, 25, 35
    n_teams = 3065
    rng = np.random.default_rng(42)
    field = df.build_field(n_teams, rng)
    rank = core.compute_rank(z, field)
    m = core.speed_mult_from_rank(rank, n_teams + 1)
    d = pnl_detail(x, y, z, m)

    print(f"\n  Configuration initiale: x={x}%, y={y}%, z={z}%")
    print(f"  Budget used: {d['used']:,.0f} XIRECs (100%)")
    print(f"  Research({x}) = {d['R']:,.0f}")
    print(f"  Scale({y})    = ×{d['S']:.2f}")
    print(f"  Rank vs data-driven field: {rank}/{n_teams+1}  "
          f"({100*rank/(n_teams+1):.1f}% from top)")
    print(f"  Speed multiplier: ×{m:.2f}")
    print(f"  → PnL = Research × Scale × Speed − Budget = "
          f"{d['R']:,.0f} × {d['S']:.2f} × {m:.2f} − {d['used']:,.0f}")
    print(f"         = {d['gross']:,.0f} − {d['used']:,.0f}")
    print(f"         = {d['pnl']:+,.0f}")

    # Compare to our reco
    x2, y2, z2 = 13, 37, 50
    rank2 = core.compute_rank(z2, field)
    m2 = core.speed_mult_from_rank(rank2, n_teams + 1)
    d2 = pnl_detail(x2, y2, z2, m2)
    print(f"\n  Notre reco: x={x2}%, y={y2}%, z={z2}%  →  PnL = {d2['pnl']:+,.0f}")
    print(f"  Écart: {d2['pnl'] - d['pnl']:+,.0f} XIRECs ({100*(d2['pnl']-d['pnl'])/max(1,d['pnl']):.0f}% better)")

    print()
    print("  ─────────────────────────────────────────────────────────────")
    print("  RAISONS du suboptimum de (40, 25, 35):")
    print("  ─────────────────────────────────────────────────────────────")

    # 1. Research ratio too high
    # Find best y at x fixed=40
    best_y_at_40 = 0
    best_pnl_x40 = -1e18
    for y_try in range(0, 101-40+1):
        z_try = 100 - 40 - y_try
        if z_try < 0: continue
        rank_try = core.compute_rank(z_try, field)
        m_try = core.speed_mult_from_rank(rank_try, n_teams + 1)
        p = core.research(40) * core.scale(y_try) * m_try - core.budget_used(40, y_try, z_try)
        if p > best_pnl_x40:
            best_pnl_x40 = p; best_y_at_40 = y_try

    print(f"\n  (1) Research à 40% est trop élevé (saturation log)")
    print(f"      Research(40) = 160,931 ; Research(20) = 134,866 ; Research(13) = 114,366")
    print(f"      Les 50% suivants (20%→40%) n'ajoutent que ~26k sur 160k = +19%")
    print(f"      Alors que Scale est LINÉAIRE: doubler y DOUBLE son effet (0→7)")

    # 2. Scale too low
    print(f"\n  (2) Scale à 25% est trop bas (laisse du marginal linéaire)")
    print(f"      Scale(25) = 1.75  →  Scale(37) = 2.59  →  Scale(50) = 3.50  →  Scale(77) = 5.39")
    print(f"      Chaque +1% Scale ajoute 0.07 de multiplicateur (pure linéaire)")

    # 3. Speed 35 is below median (field median=40)
    print(f"\n  (3) Speed à 35% est SOUS la médiane du field (median=40)")
    print(f"      → rank {rank}/{n_teams+1} = {100*rank/(n_teams+1):.1f}% from top  →  m=×{m:.2f}")
    print(f"      Si on pousse à z=50 → rank {rank2}/{n_teams+1} = {100*rank2/(n_teams+1):.1f}%  →  m=×{m2:.2f}")
    print(f"      C'est un saut de m: +{m2-m:.2f} (= +{(m2/m-1)*100:.0f}% gross PnL sur R×S)")

    # 4. Ratio R/S not optimal for the budget left
    print(f"\n  (4) Ratio Research:Scale = 40:25 = 1.6  →  BEAUCOUP trop haut")
    print(f"      Optimum analytique: R/S ≈ 0.35 à budget plein (23:77)")
    print(f"      Optimum à B_xy=50 (quand z=50): R/S ≈ 0.35 aussi → 13:37")

    print()
    print("  ─────────────────────────────────────────────────────────────")
    print("  DÉCOMPOSITION du gap +80k → +171k:")
    print("  ─────────────────────────────────────────────────────────────")

    # Gap decomposition
    # Stage 1: keep z=35, switch to optimal (x, y) with x+y=65
    b_x, b_y, _ = core.best_xy_given_budget(65)
    rank_s1 = core.compute_rank(35, field)
    m_s1 = core.speed_mult_from_rank(rank_s1, n_teams + 1)
    p_s1 = core.research(b_x) * core.scale(b_y) * m_s1 - core.budget_used(b_x, b_y, 35)
    print(f"    Step 1 (optim R/S à z=35): (x={b_x}, y={b_y}, z=35) → PnL = {p_s1:+,.0f}  (+{p_s1-d['pnl']:,.0f})")

    # Stage 2: now also optimize z
    b2_x, b2_y, _ = core.best_xy_given_budget(50)
    rank_s2 = core.compute_rank(50, field)
    m_s2 = core.speed_mult_from_rank(rank_s2, n_teams + 1)
    p_s2 = core.research(b2_x) * core.scale(b2_y) * m_s2 - core.budget_used(b2_x, b2_y, 50)
    print(f"    Step 2 (+pousse z à 50):   (x={b2_x}, y={b2_y}, z=50) → PnL = {p_s2:+,.0f}  (+{p_s2-p_s1:,.0f})")
    print(f"\n    Total gain: +80k  →  +171k  =  +91k de gain (+113%)")


# ═══════════════════════════════════════════════════════════════════════
# PART 2 — LEVEL-K reasoning
# ═══════════════════════════════════════════════════════════════════════

def level_k_analysis():
    print("\n" + "═" * 82)
    print("PART 2 — LEVEL-K / SECOND-TOUR REASONING")
    print("═" * 82)
    print("""
  Problème: si d'autres teams font aussi notre analyse data-driven et
  convergent sur z=50, alors 50 devient un GROS focal → la médiane monte.

  Modèle level-k (cognitive hierarchy, Camerer-Ho-Chong):
    L0: naïf, pick round number au hasard (25, 30, 33, 40, 50)
    L1: best response à L0 distribution (notre script 08 = z ≈ 50)
    L2: knowing L1 converges at 50 → expects cluster there → z ≥ 51
    L3: knowing L2 goes 51 → z ≥ 52 → spiral

  Self-limiting: au-delà d'un seuil, Research×Scale s'effondre et le spiral
  devient contre-productif.
""")

    n_teams = 3065
    rng = np.random.default_rng(42)
    base_field = df.build_field(n_teams, rng)

    # Compute best response at each level
    # Level 1: play against base field
    b1 = core.find_best_response(base_field)
    z_L1 = b1["my_z"]
    print(f"  Level 1 (vs data-driven base field):  best z = {z_L1}  "
          f"PnL = {b1['pnl']:+,.0f}")

    # Level 2: assume some fraction of field plays z_L1 (clusters with us)
    # New field = base field with fraction_LK shifted to z_L1
    # We vary fraction of strategic (L1+) players in field
    for frac_strategic in [0.05, 0.10, 0.20, 0.30]:
        # Replace frac_strategic of the field with z_L1
        n_strategic = int(n_teams * frac_strategic)
        new_field = base_field.copy()
        # Random indices to replace
        idx = rng.choice(n_teams, size=n_strategic, replace=False)
        new_field[idx] = z_L1
        b2 = core.find_best_response(new_field)
        z_L2 = b2["my_z"]
        print(f"  Level 2 (with {int(frac_strategic*100)}% strategic at z={z_L1}): "
              f"best z = {z_L2}  PnL = {b2['pnl']:+,.0f}")

    # Level 3: nested - assume both L1 and L2 clusters exist
    print(f"\n  Level 3 (with mix L1={z_L1}@15% and L2_shifted@5%):")
    new_field = base_field.copy()
    # 15% at L1 value
    idx_l1 = rng.choice(n_teams, size=int(n_teams * 0.15), replace=False)
    new_field[idx_l1] = z_L1
    # 5% at L2 value (z_L1 + 1 or 2 based on typical L2 response)
    remaining = np.setdiff1d(np.arange(n_teams), idx_l1)
    idx_l2 = rng.choice(remaining, size=int(n_teams * 0.05), replace=False)
    new_field[idx_l2] = z_L1 + 1
    b3 = core.find_best_response(new_field)
    print(f"    best z = {b3['my_z']}  PnL = {b3['pnl']:+,.0f}")

    # Self-limiting: show landscape
    print(f"\n  Self-limiting analysis (what PnL at each z if everyone else also pushes):")
    print(f"    {'z':>4}  {'rank (shifted field)':>22}  {'m':>5}  {'R×S':>10}  {'PnL':>10}")
    # Field where top 20% is shifted to their L1+ responses
    shifted_field = base_field.copy()
    top20 = int(n_teams * 0.20)
    idx_top = rng.choice(n_teams, size=top20, replace=False)
    shifted_field[idx_top] = z_L1 + 2  # shift top teams slightly higher

    for z in [40, 45, 48, 50, 51, 52, 55, 60]:
        rank = core.compute_rank(z, shifted_field)
        m = core.speed_mult_from_rank(rank, n_teams + 1)
        bx, by, _ = core.best_xy_given_budget(100 - z)
        p = core.research(bx) * core.scale(by) * m - core.budget_used(bx, by, z)
        print(f"    {z:>4}  {rank:>6}/{n_teams+1:<5}         {m:>5.2f}  "
              f"{core.research(bx)*core.scale(by):>10,.0f}  {p:>+10,.0f}")


# ═══════════════════════════════════════════════════════════════════════
# PART 3 — SYNTHESIS & final recommendation with second-tour adjustment
# ═══════════════════════════════════════════════════════════════════════

def synthesis():
    print("\n" + "═" * 82)
    print("PART 3 — SYNTHÈSE & recommandation intégrant le second tour")
    print("═" * 82)
    print("""
  Le second tour pousse vers un léger markup sur z=50:
    - Si 10-20% du field converge sur 50 (stratèges like us) → focal 50
    - Pour BATTRE ce focal et rank strictement au-dessus: z=51
    - Coût marginal: 500 XIRECs (1% budget) = 0.29% de la V
    - Gain potentiel: battre ~10-20% du field (~300-600 teams)

  Markup analogue à celui du MAF (2173 vs 2000):
    z = 50 → 51 (markup +1%, prime ou non-round pour éviter sous-cluster)

  Cependant: le gain marginal à z=51 vs z=50 est négligeable car:
    - m improvement très faible (rank stays similar)
    - cost +500 non compensé

  VERDICT: z=50 reste défendable. Le markup à 51 est une option "belt-and-suspenders"
  mais pas essentielle vu la platitude du plateau PnL.
""")


if __name__ == "__main__":
    critique_404025()
    level_k_analysis()
    synthesis()
