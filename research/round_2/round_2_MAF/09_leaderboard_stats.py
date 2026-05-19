"""Analyze R1 leaderboard PnL distribution → infer V distribution for the field.

Inputs:
  data/leaderboard_r1_global_top100.csv (top 100 worldwide)
  data/leaderboard_r1_france.csv        (~208 French teams)

Key assumption (empirical from our champion):
    V (MAF value, finale XIRECs) ≈ 0.12 × team_PnL_finale
    (we measured V≈11,194 and our live finale PnL ≈ 93,500 with 12.4% uplift)

Rough extrapolation: the French queue distribution is a plausible proxy for
the full world distribution below the top 100.

Usage:
    python research/round_2/round_2_MAF/09_leaderboard_stats.py
"""
from __future__ import annotations
import argparse
from pathlib import Path
import csv
import statistics

ROOT = Path(__file__).resolve().parent


def load_csv(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                r["pnl_finale"] = float(r["pnl_finale"]) if r.get("pnl_finale") else None
                r["rank"] = int(r["rank"])
            except Exception:
                r["pnl_finale"] = None
            if r["pnl_finale"] is not None:
                rows.append(r)
    return rows


def pct(xs, p):
    xs_sorted = sorted(xs)
    k = (len(xs_sorted) - 1) * p / 100.0
    f = int(k); c = min(f + 1, len(xs_sorted) - 1)
    if f == c: return xs_sorted[f]
    return xs_sorted[f] + (k - f) * (xs_sorted[c] - xs_sorted[f])


def summarize(label, pnl):
    print(f"\n=== {label} (n={len(pnl)}) ===")
    print(f"  mean  = {statistics.mean(pnl):>10,.0f}")
    print(f"  std   = {statistics.stdev(pnl):>10,.0f}")
    print(f"  min   = {min(pnl):>10,.0f}")
    print(f"  p10   = {pct(pnl,10):>10,.0f}")
    print(f"  p25   = {pct(pnl,25):>10,.0f}")
    print(f"  p50   = {pct(pnl,50):>10,.0f}")
    print(f"  p75   = {pct(pnl,75):>10,.0f}")
    print(f"  p90   = {pct(pnl,90):>10,.0f}")
    print(f"  max   = {max(pnl):>10,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v-ratio", type=float, default=0.12,
                    help="V per team ≈ v_ratio × pnl_finale (default 0.12 empirical)")
    ap.add_argument("--n-world-active", type=int, default=3000,
                    help="Estimated # world active teams with trader.py submitted")
    args = ap.parse_args()

    global_top = load_csv(ROOT / "data" / "leaderboard_r1_global_top100.csv")
    france = load_csv(ROOT / "data" / "leaderboard_r1_france.csv")

    print("═" * 70)
    print("R1 LEADERBOARD — PnL distribution (finale XIRECs)")
    print("═" * 70)

    summarize("GLOBAL top 100", [r["pnl_finale"] for r in global_top])
    summarize("FRANCE full", [r["pnl_finale"] for r in france])

    # V distribution
    print("\n" + "═" * 70)
    print(f"V distribution (MAF value per team, v_ratio={args.v_ratio:.0%})")
    print("═" * 70)
    v_global = [r["pnl_finale"] * args.v_ratio for r in global_top]
    v_france = [r["pnl_finale"] * args.v_ratio for r in france]
    summarize("V — Global top 100", v_global)
    summarize("V — France full", v_france)

    # Heuristic: extrapolate world distribution
    print("\n" + "═" * 70)
    print("EXTRAPOLATED WORLD DISTRIBUTION (heuristic)")
    print("═" * 70)
    print(f"Assumption: top 100 = known distribution, rank 101+ follows shape similar")
    print(f"to France queue (scale to {args.n_world_active} active world teams).")

    # Build world distribution: top100 real, then France shape rescaled for
    # the remaining (n_world_active − 100) positions
    remaining = args.n_world_active - 100
    fr_pnl = sorted([r["pnl_finale"] for r in france], reverse=True)
    # Scale France rank-percentile to cover remaining world positions
    world_tail = []
    if remaining > 0 and fr_pnl:
        for i in range(remaining):
            idx = int(i / remaining * len(fr_pnl))
            idx = min(idx, len(fr_pnl) - 1)
            world_tail.append(fr_pnl[idx])
    world_pnl = [r["pnl_finale"] for r in global_top] + world_tail
    summarize(f"World PnL distribution (n={args.n_world_active}, extrapolated)", world_pnl)

    world_V = [p * args.v_ratio for p in world_pnl]
    summarize(f"World V distribution (n={args.n_world_active}, extrapolated)", world_V)

    # Key quantities for adversary model
    med_pnl = pct(world_pnl, 50)
    med_v = med_pnl * args.v_ratio
    print("\n" + "═" * 70)
    print("KEY STATS FOR ADVERSARY BID MODEL")
    print("═" * 70)
    print(f"Median world team PnL (finale): {med_pnl:,.0f}")
    print(f"Median world team V (finale):   {med_v:,.0f}  ← median 'rational' bid ceiling")
    print(f"Top-100 threshold:              {global_top[-1]['pnl_finale']:,.0f}")
    print(f"Our team PnL finale (leo):      ~107,674 (rank ~77 world / 1 FR)")
    print(f"Our team V (measured):          ~11,194 (≈ {11194/107674*100:.1f}% of PnL)")
    print()
    print("→ Most teams have LOWER V than us, so they should bid LOWER than 11,194")
    print("→ Rational bidders below median PnL have V < ~{:,.0f}".format(med_v))


if __name__ == "__main__":
    main()
