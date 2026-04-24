"""Measure ΔPnL of having +25% extra volume (the MAF value V).

Runs the backtest on:
  - Normal R2 data (baseline, what we get without MAF)
  - Each synthetic enriched dataset (what we'd get WITH MAF)

Computes ΔPnL = PnL(enriched) − PnL(baseline) per seed + averaged.
Decomposes by product.

Also scales to "simu finale" units (×10) to compare against bid cost.

Usage:
    python research/round_2_MAF/02_measure_delta_pnl.py \\
        --strategy champion_19april_am \\
        --seeds 42,43,44
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_backtest(strategy: str, data_dir: Path) -> dict:
    """Run backtest with a specific data directory. Returns {OSM: pnl, IPR: pnl, TOTAL: pnl}."""
    cmd = [
        sys.executable, "backtest.py",
        "--strategy", strategy,
        "--round", "2",
        "--days", "-1", "0", "1",
        "--execution-rule", "realistic",
        "--data-dir", str(data_dir),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8")
    if result.returncode != 0:
        print(f"ERROR: backtest failed with data_dir={data_dir}")
        print(result.stderr[-2000:])
        return {}

    out = result.stdout
    pnls = {}
    for product in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
        # Match "  product | subtotal | PNL | ..."
        m = re.search(rf"{product}.*?└ subtotal.*?(\S+)\s*\│\s*\d+", out, re.DOTALL)
        if m:
            pnl_str = m.group(1).replace(",", "")
            try:
                pnls[product] = float(pnl_str)
            except ValueError:
                pnls[product] = 0.0
    total_match = re.search(r"TOTAL.*?(\S+)\s*\│\s*\d+\s*│\s*\d+", out)
    if total_match:
        pnls["TOTAL"] = float(total_match.group(1).replace(",", ""))
    return pnls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="champion_19april_am")
    parser.add_argument("--seeds", default="42,43,44", help="Comma-separated list of seeds")
    parser.add_argument("--scaling-factor", type=float, default=10.0,
                        help="simu test → simu finale scaling (default 10)")
    args = parser.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]

    # 1. Baseline: normal R2 data
    print(f"\n━━━ Running baseline (no MAF) on strategy={args.strategy} ━━━")
    baseline = run_backtest(args.strategy, ROOT / "data")
    print(f"Baseline PnL: {baseline}")

    # 2. Enriched: each synthetic seed
    enriched_results = []
    for seed in seeds:
        # The backtester expects data-dir with "round_2/" subfolder structure
        # We need to create a temp structure where round_2/ points to our synthetic files
        # Simple approach: put synthetic data in data/round_2_synthetic_sXX and point --data-dir there
        synth_parent = ROOT / f"_synth_parent_s{seed}"
        synth_round = synth_parent / "round_2"
        synth_round.mkdir(parents=True, exist_ok=True)
        # Symlink the files
        source_dir = ROOT / "data" / f"round_2_synthetic_s{seed}"
        if not source_dir.exists():
            print(f"WARN: {source_dir} not found, skipping seed {seed}")
            continue
        import shutil
        for f in source_dir.glob("*.csv"):
            target = synth_round / f.name
            if target.exists():
                target.unlink()
            shutil.copy(f, target)

        print(f"\n━━━ Running enriched seed={seed} ━━━")
        enriched = run_backtest(args.strategy, synth_parent)
        print(f"Seed {seed} PnL: {enriched}")
        enriched_results.append((seed, enriched))

        # Cleanup temp parent
        shutil.rmtree(synth_parent, ignore_errors=True)

    # 3. Compute deltas
    print("\n" + "═" * 70)
    print(f"RESULTS: strategy={args.strategy}, {len(enriched_results)} seeds")
    print("═" * 70)
    print(f"{'Seed':<8} {'OSM ΔPnL':>12} {'IPR ΔPnL':>12} {'Total ΔPnL':>12} {'Scaled finale':>15}")
    print("-" * 70)

    osm_deltas, ipr_deltas, total_deltas = [], [], []
    for seed, enr in enriched_results:
        d_osm = enr.get("ASH_COATED_OSMIUM", 0) - baseline.get("ASH_COATED_OSMIUM", 0)
        d_ipr = enr.get("INTARIAN_PEPPER_ROOT", 0) - baseline.get("INTARIAN_PEPPER_ROOT", 0)
        d_tot = enr.get("TOTAL", 0) - baseline.get("TOTAL", 0)
        osm_deltas.append(d_osm); ipr_deltas.append(d_ipr); total_deltas.append(d_tot)
        scaled = d_tot * args.scaling_factor
        print(f"{seed:<8} {d_osm:>+12,.0f} {d_ipr:>+12,.0f} {d_tot:>+12,.0f} {scaled:>+15,.0f}")

    if total_deltas:
        import statistics
        mean_delta = statistics.mean(total_deltas)
        std_delta = statistics.stdev(total_deltas) if len(total_deltas) > 1 else 0
        print("-" * 70)
        print(f"{'Mean':<8} {statistics.mean(osm_deltas):>+12,.0f} {statistics.mean(ipr_deltas):>+12,.0f} {mean_delta:>+12,.0f} {mean_delta * args.scaling_factor:>+15,.0f}")
        print(f"{'Std':<8} {'':<12} {'':<12} {std_delta:>+12,.0f}")
        print()
        print(f"V (MAF value, simu test units):   {mean_delta:+,.0f} ± {std_delta:,.0f}")
        print(f"V scaled to simu finale (×{args.scaling_factor:.0f}): {mean_delta * args.scaling_factor:+,.0f} ± {std_delta * args.scaling_factor:,.0f}")
        print()
        print("Interpretation:")
        print(f"  The MAF gives us an expected {mean_delta * args.scaling_factor:+,.0f} finale XIRECs of extra PnL.")
        print(f"  A rational max bid (ignoring adversary dynamics) = {max(0, mean_delta * args.scaling_factor):,.0f}.")
        print(f"  Under first-price game theory, optimal bid is much lower (see script 03).")


if __name__ == "__main__":
    main()
