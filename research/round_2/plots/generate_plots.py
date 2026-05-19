"""Generate insightful plots for Prosperity 4 Round 2 research.

Uses the leaderboard data from research/round_2/round_2_MAF/data/ to produce:
  1. PnL histogram — R1 Global top 600 + France 207
  2. CDF comparison — France vs World
  3. Rank vs PnL (scatter with our position highlighted)
  4. R2 backtest PnL distribution (simulated from aggregate stats)
  5. V distribution (MAF value per team ≈ 12% of PnL)
  6. Country breakdown top-600 (stacked bar)
  7. Speed allocation field by tier (for manual)
  8. Break-even bid visualization

Usage:
    python research/round_2/plots/generate_plots.py
"""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path
from collections import Counter

import matplotlib.pyplot as plt
import numpy as np
import matplotlib.patches as mpatches

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
MAF_DATA = ROOT / "round_2_MAF" / "data"

# Color palette
COLOR_WORLD = "#1f77b4"
COLOR_FRANCE = "#d62728"
COLOR_OURS = "#2ca02c"
COLOR_ACCENT = "#ff7f0e"
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.family": "DejaVu Sans",
    "font.size": 10,
})


def load_csv_pnl(path: Path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                p = float(r.get("pnl_finale", ""))
                rows.append({"rank": int(r["rank"]), "team": r["team_name"],
                             "country": r["country"], "pnl": p})
            except (ValueError, TypeError):
                continue
    return rows


def load_data():
    global_rows = load_csv_pnl(MAF_DATA / "leaderboard_r1_global_merged.csv")
    france_rows = load_csv_pnl(MAF_DATA / "leaderboard_r1_france.csv")
    with open(MAF_DATA / "r2_backtest_leaderboard_aggregate.json") as f:
        r2_agg = json.load(f)
    return global_rows, france_rows, r2_agg


# ═══════════════════════════════════════════════════════
# Plot 1: PnL Histograms — Global & France side by side
# ═══════════════════════════════════════════════════════

def plot_1_pnl_histograms(global_rows, france_rows):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    global_pnls = np.array([r["pnl"] for r in global_rows])
    france_pnls = np.array([r["pnl"] for r in france_rows])

    ax1.hist(global_pnls, bins=40, color=COLOR_WORLD, alpha=0.75, edgecolor="black")
    ax1.axvline(107674, color=COLOR_OURS, linestyle="--", linewidth=2,
                label=f"Notre team (rank 77)\n107,674")
    ax1.axvline(np.median(global_pnls), color=COLOR_ACCENT, linestyle=":",
                linewidth=2, label=f"Médiane = {np.median(global_pnls):,.0f}")
    ax1.set_title(f"R1 Global top 600 — Distribution PnL finale\n(min {min(global_pnls):,.0f} → max {max(global_pnls):,.0f})")
    ax1.set_xlabel("PnL finale (XIRECs)")
    ax1.set_ylabel("Nombre de teams")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2.hist(france_pnls, bins=30, color=COLOR_FRANCE, alpha=0.75, edgecolor="black")
    ax2.axvline(107674, color=COLOR_OURS, linestyle="--", linewidth=2,
                label=f"Notre team (rank 1 FR)\n107,674")
    ax2.axvline(np.median(france_pnls), color=COLOR_ACCENT, linestyle=":",
                linewidth=2, label=f"Médiane FR = {np.median(france_pnls):,.0f}")
    ax2.set_title(f"R1 France — Distribution PnL finale ({len(france_pnls)} teams)\n(min {min(france_pnls):,.0f} → max {max(france_pnls):,.0f})")
    ax2.set_xlabel("PnL finale (XIRECs)")
    ax2.set_ylabel("Nombre de teams")
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "01_pnl_histograms.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 01_pnl_histograms.png")


# ═══════════════════════════════════════════════════════
# Plot 2: CDF comparison France vs World
# ═══════════════════════════════════════════════════════

def plot_2_cdf(global_rows, france_rows):
    fig, ax = plt.subplots(figsize=(10, 6))
    g = np.sort([r["pnl"] for r in global_rows])
    f = np.sort([r["pnl"] for r in france_rows])

    ax.plot(g, np.arange(1, len(g)+1) / len(g) * 100,
            color=COLOR_WORLD, linewidth=2, label=f"R1 Global top 600 (n={len(g)})")
    ax.plot(f, np.arange(1, len(f)+1) / len(f) * 100,
            color=COLOR_FRANCE, linewidth=2, label=f"R1 France (n={len(f)})")

    # Notre position
    ax.axvline(107674, color=COLOR_OURS, linestyle="--", linewidth=2,
               label="Notre PnL (107,674)")
    ax.scatter([107674], [np.searchsorted(g, 107674)/len(g)*100],
               color=COLOR_WORLD, s=120, edgecolor="black", zorder=5)
    ax.scatter([107674], [np.searchsorted(f, 107674)/len(f)*100],
               color=COLOR_FRANCE, s=120, edgecolor="black", zorder=5)

    ax.set_xlabel("PnL finale (XIRECs)")
    ax.set_ylabel("Percentile cumulative (%)")
    ax.set_title("CDF des PnL — R1 Global vs France\n(Notre team : top 1% global, top 0.5% France)")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(50000, 130000)

    plt.tight_layout()
    plt.savefig(OUT / "02_cdf_comparison.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 02_cdf_comparison.png")


# ═══════════════════════════════════════════════════════
# Plot 3: Rank vs PnL scatter with our position
# ═══════════════════════════════════════════════════════

def plot_3_rank_vs_pnl(global_rows, france_rows):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Global
    g_ranks = [r["rank"] for r in global_rows]
    g_pnls = [r["pnl"] for r in global_rows]
    ax1.scatter(g_ranks, g_pnls, s=15, color=COLOR_WORLD, alpha=0.6)
    ax1.scatter([77], [107674], s=200, color=COLOR_OURS, zorder=5,
                edgecolor="black", label="Nous (rank 77)")
    ax1.axhline(107674, color=COLOR_OURS, linestyle=":", alpha=0.5)
    ax1.set_xlabel("Rank (global)")
    ax1.set_ylabel("PnL finale (XIRECs)")
    ax1.set_title("R1 Global — Rank vs PnL (top 600)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # France
    f_ranks = [r["rank"] for r in france_rows]
    f_pnls = [r["pnl"] for r in france_rows]
    ax2.scatter(f_ranks, f_pnls, s=25, color=COLOR_FRANCE, alpha=0.7)
    ax2.scatter([1], [107674], s=250, color=COLOR_OURS, zorder=5,
                edgecolor="black", label="Nous (rank 1 FR)")
    ax2.axhline(107674, color=COLOR_OURS, linestyle=":", alpha=0.5)
    ax2.set_xlabel("Rank (France)")
    ax2.set_ylabel("PnL finale (XIRECs)")
    ax2.set_title("R1 France — Rank vs PnL (207 teams)")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "03_rank_vs_pnl.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 03_rank_vs_pnl.png")


# ═══════════════════════════════════════════════════════
# Plot 4: R2 backtest leaderboard — synthetic from aggregate
# ═══════════════════════════════════════════════════════

def plot_4_r2_distribution(r2_agg):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Reconstruct approximate distribution from stats
    n = r2_agg["n_entries_total"]
    median = r2_agg["median_pnl"]
    p25, p75 = r2_agg["p25_pnl"], r2_agg["p75_pnl"]
    field_floor = r2_agg["field_floor"]
    field_ceiling = r2_agg["field_ceiling"]
    low_out = r2_agg["outliers_low"]
    low_worst = r2_agg["outliers_low_worst"]
    high_out = r2_agg["outliers_high"]

    # Log-normal fit for middle
    mu = math.log(median)
    sigma = math.log(p75 / p25) / 1.349
    n_mid = n - low_out - high_out
    rng = np.random.default_rng(42)
    mid = np.clip(rng.lognormal(mu, sigma, n_mid), field_floor, field_ceiling)
    low = rng.uniform(low_worst, field_floor, low_out)
    high = rng.uniform(field_ceiling, field_ceiling + 300, high_out)
    field = np.concatenate([low, mid, high])

    # Histogram
    ax1.hist(field[field > 0], bins=60, color="#9467bd", alpha=0.75, edgecolor="black")
    ax1.axvline(10300, color=COLOR_OURS, linestyle="--", linewidth=2,
                label="Notre PnL R2 (~10,300, rank 34)")
    ax1.axvline(median, color=COLOR_ACCENT, linestyle=":", linewidth=2,
                label=f"Médiane = {median:,.0f}")
    ax1.set_xlabel("PnL test (XIRECs)")
    ax1.set_ylabel("Nombre de teams")
    ax1.set_title(f"R2 Backtest leaderboard — distribution\n(n={n:,}, 96% profitable)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Zoomed view incluant outliers bas
    ax2.hist(field, bins=80, color="#9467bd", alpha=0.75, edgecolor="black")
    ax2.axvline(0, color="black", linestyle="-", linewidth=1, alpha=0.5)
    ax2.axvline(10300, color=COLOR_OURS, linestyle="--", linewidth=2,
                label="Notre PnL")
    ax2.set_xlabel("PnL test (XIRECs)")
    ax2.set_ylabel("Nombre de teams")
    ax2.set_title("R2 Backtest — vue complète (incluant 552 outliers négatifs)")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "04_r2_distribution.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 04_r2_distribution.png")


# ═══════════════════════════════════════════════════════
# Plot 5: V distribution (MAF value per team)
# ═══════════════════════════════════════════════════════

def plot_5_v_distribution(global_rows, france_rows):
    fig, ax = plt.subplots(figsize=(12, 6))

    g_v = np.array([r["pnl"] * 0.12 for r in global_rows])
    f_v = np.array([r["pnl"] * 0.12 for r in france_rows])

    ax.hist(g_v, bins=40, color=COLOR_WORLD, alpha=0.6, edgecolor="black",
            label=f"V Global top 600 (mean {g_v.mean():,.0f})")
    ax.hist(f_v, bins=30, color=COLOR_FRANCE, alpha=0.6, edgecolor="black",
            label=f"V France (mean {f_v.mean():,.0f})")

    ax.axvline(11194, color=COLOR_OURS, linestyle="--", linewidth=2.5,
               label="V ≈ 11,194 (notre mesure)")
    ax.axvline(2173, color="darkgreen", linestyle=":", linewidth=2.5,
               label="Bid MAF retenu = 2,173")

    ax.set_xlabel("V (MAF value ≈ 12% × PnL), XIRECs finale")
    ax.set_ylabel("Nombre de teams")
    ax.set_title("Distribution de V parmi les top teams\n(V ≈ 12% du PnL finale, break-even = 11,194)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "05_v_distribution.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 05_v_distribution.png")


# ═══════════════════════════════════════════════════════
# Plot 6: Country breakdown top 600
# ═══════════════════════════════════════════════════════

def plot_6_country_breakdown(global_rows):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    # Top 100 by country
    top100 = global_rows[:100]
    counts_top100 = Counter(r["country"] for r in top100)
    countries = sorted(counts_top100.keys(), key=lambda k: -counts_top100[k])[:12]
    n_countries = [counts_top100[c] for c in countries]

    ax1.barh(countries, n_countries, color=COLOR_WORLD, alpha=0.85, edgecolor="black")
    for i, v in enumerate(n_countries):
        ax1.text(v + 0.2, i, str(v), va="center", fontsize=9)
    ax1.set_xlabel("Nombre de teams")
    ax1.set_title("R1 Global — Top 100 par pays\n(au-delà de 12 pays = others)")
    ax1.invert_yaxis()
    ax1.grid(True, alpha=0.3, axis="x")

    # Top 600 by country
    counts_top600 = Counter(r["country"] for r in global_rows)
    countries_all = sorted(counts_top600.keys(), key=lambda k: -counts_top600[k])[:15]
    n_countries_all = [counts_top600[c] for c in countries_all]
    colors = plt.cm.tab20(np.linspace(0, 1, len(countries_all)))

    ax2.barh(countries_all, n_countries_all, color=colors, edgecolor="black")
    for i, v in enumerate(n_countries_all):
        ax2.text(v + 0.5, i, str(v), va="center", fontsize=9)
    ax2.set_xlabel("Nombre de teams")
    ax2.set_title("R1 Global — Top 600 par pays\n(on voit la France 4e)")
    ax2.invert_yaxis()
    ax2.grid(True, alpha=0.3, axis="x")

    plt.tight_layout()
    plt.savefig(OUT / "06_country_breakdown.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 06_country_breakdown.png")


# ═══════════════════════════════════════════════════════
# Plot 7: Pillars PnL landscape (manual)
# ═══════════════════════════════════════════════════════

def plot_7_pillars_landscape():
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(16, 5))

    xs = np.arange(0, 101)

    # Research
    R = 200_000 * np.log(1 + xs) / np.log(101)
    ax1.plot(xs, R, color=COLOR_WORLD, linewidth=2.5)
    ax1.fill_between(xs, 0, R, color=COLOR_WORLD, alpha=0.2)
    ax1.axvline(12, color=COLOR_OURS, linestyle="--", label=f"x=12%, R={R[12]:,.0f}")
    ax1.axhline(R[12], color=COLOR_OURS, linestyle=":")
    ax1.set_xlabel("Research % investi")
    ax1.set_ylabel("Research score")
    ax1.set_title("Research(x) — log concave\n(max 200k à 100%)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Scale
    S = 7 * xs / 100
    ax2.plot(xs, S, color=COLOR_FRANCE, linewidth=2.5)
    ax2.fill_between(xs, 0, S, color=COLOR_FRANCE, alpha=0.2)
    ax2.axvline(35, color=COLOR_OURS, linestyle="--", label=f"y=35%, S=×{S[35]:.2f}")
    ax2.axhline(S[35], color=COLOR_OURS, linestyle=":")
    ax2.set_xlabel("Scale % investi")
    ax2.set_ylabel("Scale multiplier")
    ax2.set_title("Scale(y) — linéaire\n(max ×7 à 100%)")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # Speed (function of rank)
    # Speed multiplier for a z given our field
    zs = np.arange(0, 101)
    # Approx m(z) using median assumption of field at 40
    # If we're above median (z > 40), m > 0.5
    # Simple heuristic based on our field analysis
    field_median = 40
    field_p25, field_p75 = 30, 50
    def m_estimate(z):
        # sigmoid-like mapping from z to m based on field distribution
        if z < field_p25: return 0.1 + 0.1 * z / field_p25
        if z < field_median: return 0.2 + 0.3 * (z - field_p25) / (field_median - field_p25)
        if z < field_p75: return 0.5 + 0.2 * (z - field_median) / (field_p75 - field_median)
        return min(0.9, 0.7 + 0.2 * (z - field_p75) / 20)
    ms = [m_estimate(z) for z in zs]
    ax3.plot(zs, ms, color="#9467bd", linewidth=2.5)
    ax3.fill_between(zs, 0.1, ms, color="#9467bd", alpha=0.2)
    ax3.axvline(53, color=COLOR_OURS, linestyle="--", label=f"z=53%, m≈{m_estimate(53):.2f}")
    ax3.axhline(m_estimate(53), color=COLOR_OURS, linestyle=":")
    ax3.set_xlabel("Speed % investi")
    ax3.set_ylabel("Speed multiplier (estimé)")
    ax3.set_title("Speed(z) — rank-based ∈ [0.1, 0.9]\n(estimation vs field empirique)")
    ax3.set_ylim(0, 1)
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "07_pillars_landscape.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 07_pillars_landscape.png")


# ═══════════════════════════════════════════════════════
# Plot 8: Break-even bid visualization (MAF)
# ═══════════════════════════════════════════════════════

def plot_8_breakeven_bid():
    fig, ax = plt.subplots(figsize=(12, 6))
    bids = np.linspace(0, 15000, 500)

    # E[U] vs bid for each scenario (simplified)
    scenarios_median = {
        "optimistic (med=0)": 0,
        "central (med=0)": 0,
        "wiki_sticky (med=15)": 15,
        "pessimistic (med=594)": 594,
        "competitive (med=5102)": 5102,
    }
    V = 11194
    colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#d62728", "#9467bd"]

    for (name, med), color in zip(scenarios_median.items(), colors):
        eu = np.where(bids > med, V - bids, 0)
        ax.plot(bids, eu, label=name, linewidth=2, color=color)

    # Mark our chosen bid
    ax.axvline(2173, color="black", linestyle="--", linewidth=2.5, alpha=0.7)
    ax.text(2300, 9500, "Notre bid\n= 2,173", fontsize=10, color="black", weight="bold")
    ax.axvline(V, color="red", linestyle=":", linewidth=2, alpha=0.7)
    ax.text(V + 100, 500, f"Break-even\n= {V:,}", fontsize=10, color="red", weight="bold")

    ax.set_xlabel("Bid (XIRECs finale)")
    ax.set_ylabel("E[Utility] si auction gagnée (V − bid)")
    ax.set_title("MAF — E[U] par scénario vs bid\n(V = 11,194, break-even visible)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0, 15000)
    ax.set_ylim(-500, V + 500)

    plt.tight_layout()
    plt.savefig(OUT / "08_maf_breakeven_eu.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 08_maf_breakeven_eu.png")


# ═══════════════════════════════════════════════════════
# Plot 9: Speed tournament PnL landscape (Manual)
# ═══════════════════════════════════════════════════════

def plot_9_speed_tournament():
    """Plot PnL vs z using data-driven field."""
    import sys
    from pathlib import Path
    mr2 = ROOT / "manual_round_2"
    import importlib.util
    spec = importlib.util.spec_from_file_location("core", mr2 / "core.py")
    core = importlib.util.module_from_spec(spec); sys.modules["core"] = core
    spec.loader.exec_module(core)
    spec2 = importlib.util.spec_from_file_location("df", mr2 / "07_data_driven_field.py")
    dfmod = importlib.util.module_from_spec(spec2); sys.modules["df"] = dfmod
    spec2.loader.exec_module(dfmod)

    rng = np.random.default_rng(42)
    field = dfmod.build_field(3065, rng)

    zs = np.arange(0, 101)
    pnls = []
    ms = []
    ranks = []
    for z in zs:
        r = core.compute_pnl_vs_field(z, field)
        pnls.append(r["pnl"])
        ms.append(r["m"])
        ranks.append(r["rank"])
    pnls = np.array(pnls)
    ms = np.array(ms)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    ax1.plot(zs, pnls, color=COLOR_WORLD, linewidth=2.5)
    ax1.fill_between(zs, 0, pnls, where=pnls>0, color=COLOR_WORLD, alpha=0.2)
    ax1.fill_between(zs, 0, pnls, where=pnls<=0, color="red", alpha=0.2)
    best_z = int(np.argmax(pnls))
    ax1.scatter([best_z], [pnls[best_z]], color=COLOR_OURS, s=200, zorder=5,
                edgecolor="black", label=f"Optimum z={best_z}, PnL={pnls[best_z]:,.0f}")
    ax1.axvline(53, color="black", linestyle="--", linewidth=1.5, alpha=0.5,
                label="Reco (z=53)")
    ax1.set_xlabel("Speed % (z)")
    ax1.set_ylabel("PnL finale")
    ax1.set_title(f"Manual — PnL landscape vs z\n(field data-driven n=3,065)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Speed multiplier vs z
    ax2.plot(zs, ms, color="#9467bd", linewidth=2.5)
    ax2.fill_between(zs, 0.1, ms, color="#9467bd", alpha=0.2)
    ax2.scatter([best_z], [ms[best_z]], color=COLOR_OURS, s=150, zorder=5,
                edgecolor="black")
    ax2.axhline(0.5, color="black", linestyle=":", alpha=0.5, label="m=0.5 (middle rank)")
    ax2.axhline(0.9, color="red", linestyle=":", alpha=0.5, label="m=0.9 (top rank)")
    ax2.set_xlabel("Speed % (z)")
    ax2.set_ylabel("Speed multiplier")
    ax2.set_title("Speed multiplier m(rank) vs z")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "09_speed_tournament.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ 09_speed_tournament.png")


def main():
    print("Generating plots...")
    global_rows, france_rows, r2_agg = load_data()
    print(f"Loaded: {len(global_rows)} global, {len(france_rows)} France")
    print()

    plot_1_pnl_histograms(global_rows, france_rows)
    plot_2_cdf(global_rows, france_rows)
    plot_3_rank_vs_pnl(global_rows, france_rows)
    plot_4_r2_distribution(r2_agg)
    plot_5_v_distribution(global_rows, france_rows)
    plot_6_country_breakdown(global_rows)
    plot_7_pillars_landscape()
    plot_8_breakeven_bid()
    plot_9_speed_tournament()

    print(f"\nAll plots saved to: {OUT}")


if __name__ == "__main__":
    main()
