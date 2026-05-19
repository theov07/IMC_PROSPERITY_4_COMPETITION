"""Final consolidated recommendation for MAF bid.

Integrates:
  - V_ours = 11,194 finale (from scripts 05-08)
  - Adversary median simulation (script 11) across 5 scenarios
  - Sensitivity grid (script 12) across 28 combinations

Outputs:
  - Decision narrative per scenario
  - Final bid recommendation with reasoning
  - Sanity checks and caveats

Usage:
    python research/round_2/round_2_MAF/13_final_recommendation.py
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent

# Load prior outputs
scenarios_file = ROOT / "median_sim_results.json"
sensitivity_file = ROOT / "sensitivity_grid_results.json"

scenarios = json.load(open(scenarios_file)) if scenarios_file.exists() else []
sens = json.load(open(sensitivity_file)) if sensitivity_file.exists() else []

V_OURS = 11194.0


def main():
    print("═" * 82)
    print("  MAF BID — FINAL CONSOLIDATED RECOMMENDATION")
    print("═" * 82)
    print()
    print(f"  Break-even V (our measured MAF gain, finale XIRECs):  {V_OURS:,.0f}")
    print(f"  ⇒ Bids > {V_OURS:,.0f} are EV-negative even if auction is won.")
    print()

    # ──────────────────────────────────────────────────
    # Step 1 — Scenario narratives
    # ──────────────────────────────────────────────────
    print("━" * 82)
    print("STEP 1 — FIELD SCENARIOS (Monte Carlo median + optimal bid)")
    print("━" * 82)
    print(f"{'Scenario':<14} {'Description':<38} {'Med adv':>8} {'Bid opt':>9} {'E[U]':>9}")
    print("─" * 82)
    narratives = {
        "central":     "55% no-bid, 15% wiki=15, 30% aware",
        "pessimistic": "30% no-bid, 10% wiki, field SERIOUS",
        "optimistic":  "75% no-bid (mostly zombies)",
        "competitive": "15% no-bid, 70%+ rational bidders",
        "wiki_heavy":  "40% no-bid, 40% wiki copy=15",
    }
    for r in scenarios:
        name = r["scenario"]
        desc = narratives.get(name, "")
        print(f"{name:<14} {desc:<38} "
              f"{r['median_mean']:>8,.0f} {r['optimal_bid']:>9,} {r['optimal_eu']:>+9,.0f}")
    print()

    # ──────────────────────────────────────────────────
    # Step 2 — Sensitivity grid key findings
    # ──────────────────────────────────────────────────
    print("━" * 82)
    print("STEP 2 — SENSITIVITY: optimal bid vs (frac_no_bid × frac_wiki)")
    print("━" * 82)
    # Reconstruct table
    grid_no_bid = sorted({r["frac_no_bid"] for r in sens if "frac_no_bid" in r and r.get("v_threshold") == 7000
                          and r.get("shaded_lo") == 0.5})
    grid_wiki   = sorted({r["frac_wiki"]   for r in sens if "frac_no_bid" in r and r.get("v_threshold") == 7000
                          and r.get("shaded_lo") == 0.5})
    # Main grid entries only
    grid_main = [r for r in sens if r.get("v_threshold") == 7000 and r.get("shaded_lo") == 0.5]

    print(f"  {'frac_no_bid':<14}", "".join([f"{fw:>9.0%}" for fw in grid_wiki]))
    for fnb in grid_no_bid:
        row = f"  nb={fnb:.0%}".ljust(14)
        for fw in grid_wiki:
            match = [r for r in grid_main if abs(r["frac_no_bid"]-fnb)<1e-6 and abs(r["frac_wiki"]-fw)<1e-6]
            if match:
                row += f"{match[0]['optimal_bid']:>9,}"
            else:
                row += f"{'–':>9}"
        print(row)
    print()
    print("  KEY FINDING: if frac_no_bid ≥ 60% → bid 1 suffices (median=0)")
    print("               if frac_no_bid ≤ 30% → bid >1,000 to stay competitive")
    print()

    # ──────────────────────────────────────────────────
    # Step 3 — Robust bid aggregation
    # ──────────────────────────────────────────────────
    all_optimals = [r["optimal_bid"] for r in grid_main]
    print("━" * 82)
    print("STEP 3 — ROBUST BID (distribution across sensitivity cells)")
    print("━" * 82)
    q = {p: int(np.percentile(all_optimals, p)) for p in [10, 25, 50, 75, 90]}
    print(f"  p10 (only if v. confident zombie-heavy):  {q[10]:>6,}")
    print(f"  p25                                        {q[25]:>6,}")
    print(f"  p50 (median optimal)                       {q[50]:>6,}")
    print(f"  p75 (robust, beats 75% of scenarios)       {q[75]:>6,}")
    print(f"  p90 (safe, beats 90% of scenarios)         {q[90]:>6,}")
    print()

    # ──────────────────────────────────────────────────
    # Step 4 — Expected utility per bid, ensemble over all scenarios
    # ──────────────────────────────────────────────────
    print("━" * 82)
    print("STEP 4 — ENSEMBLE E[U] PER BID (average across main scenarios)")
    print("━" * 82)
    print(f"  {'bid':>8}   " + " ".join([f"{s['scenario']:>12}" for s in scenarios]) + "    ENSEMBLE")
    bid_grid = [1, 15, 25, 50, 100, 500, 1000, 2000, 5000, 7000, 8000, 10000, 11000]
    ensemble = {}
    for b in bid_grid:
        evs_str = ""
        evs_vals = []
        for s in scenarios:
            u = s["utils"].get(str(b), None)
            if u is None:
                evs_str += f"{'–':>12}"
                continue
            evs_str += f"{u:>+12,.0f}"
            evs_vals.append(u)
        avg = sum(evs_vals) / len(evs_vals) if evs_vals else 0
        ensemble[b] = avg
        print(f"  {b:>8,}   {evs_str}  {avg:>+10,.0f}")

    best_ens = max(ensemble, key=ensemble.get)
    print()
    print(f"  → Best bid under UNIFORM prior over scenarios: {best_ens:,} "
          f"(ensemble E[U] = +{ensemble[best_ens]:,.0f})")
    print()

    # ──────────────────────────────────────────────────
    # Step 5 — Final verdict
    # ──────────────────────────────────────────────────
    print("═" * 82)
    print("  FINAL VERDICT")
    print("═" * 82)
    print()
    print("  RECOMMENDED BID RANGES:")
    print("  ──────────────────────")
    print("   Ultra-aggressive (trust zombie-heavy field):     bid = 1 — 50")
    print("   Expected-value optimal (uniform prior):          bid = {:,}".format(best_ens))
    print("   Robust p75 (covers most scenarios):              bid = {:,}".format(q[75]))
    print("   Safe p90 (covers 90% of scenarios):              bid = {:,}".format(q[90]))
    print("   Ultra-safe (if field very serious):              bid = 5,000 — 7,000")
    print()
    print("  BREAK-EVEN WARNING:")
    print(f"    Never bid > {V_OURS:,.0f} (our V). Bid above = EV-negative.")
    print()
    print("  DECISION FACTORS:")
    print("    - If you trust that ≥60% of teams don't implement bid(): aim bid 1-100")
    print("    - If you think field is professional (≤30% zombie): aim bid 2,000-7,000")
    print("    - Middle ground (40-50% zombie): aim bid 100-1,000")
    print()
    print("  ⚠ The single biggest uncertainty is `frac_no_bid`.")
    print("    Every 10% shift in this assumption moves the optimal bid by ~5-10×.")
    print("═" * 82)


if __name__ == "__main__":
    main()
