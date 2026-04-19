"""Estimate MAF gain in live IMC units.

Logic:
  - Live IMC samples ~80% of quotes from the true book each tick.
  - MAF gives +25% extra quotes → 80% × 1.25 = 100% (~ backtest conditions).
  - So:
        PnL_live(no MAF)  ≈ backtest on 80% subsampled data
        PnL_live(w/ MAF)  ≈ backtest on 100% full data
        uplift_ratio      = PnL(100%) / PnL(80%)
        MAF_gain_live     = LIVE_PNL × (uplift_ratio − 1)

  This converts the relative-% uplift measured in backtest into absolute
  finale-unit gain by anchoring on Leo's observed live PnL (≈12k total).

Usage:
    python research/round_2_MAF/06_estimate_maf_live_gain.py \
        --strategy champion_19april_am \
        --subsample-seeds 100,101,102 \
        --live-pnl-osm 4000 --live-pnl-ipr 8800
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
import shutil
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_backtest(strategy: str, data_parent: Path) -> dict:
    cmd = [
        sys.executable, "backtest.py",
        "--strategy", strategy,
        "--round", "2",
        "--days", "-1", "0", "1",
        "--execution-rule", "realistic",
        "--data-dir", str(data_parent),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8")
    if result.returncode != 0:
        print("ERROR:", result.stderr[-1500:])
        return {}
    out = result.stdout
    pnls = {}
    # Parse by walking lines; current-product state machine.
    current_product = None
    for line in out.splitlines():
        for product in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
            if product in line:
                current_product = product
        if "subtotal" in line and current_product is not None:
            # row like: "   └ subtotal         │          │  57,780 │   2166 │ ..."
            nums = re.findall(r"[-+]?[\d,]+\.?\d*", line)
            # first number (after header cols) is pnl
            for n in nums:
                try:
                    pnls[current_product] = float(n.replace(",", ""))
                    break
                except ValueError:
                    continue
            current_product = None  # consumed
    m = re.search(r"TOTAL.*?(\S+)\s*\│\s*\d+\s*│\s*\d+", out)
    if m:
        pnls["TOTAL"] = float(m.group(1).replace(",", ""))
    return pnls


def prep_synth_parent(source_dir: Path, tag: str) -> Path:
    parent = ROOT / f"_synth_parent_{tag}"
    round_dir = parent / "round_2"
    round_dir.mkdir(parents=True, exist_ok=True)
    for f in source_dir.glob("*.csv"):
        target = round_dir / f.name
        if target.exists():
            target.unlink()
        shutil.copy(f, target)
    return parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="champion_19april_am")
    parser.add_argument("--subsample-seeds", default="100,101,102")
    parser.add_argument("--p_keep", type=int, default=80, help="Subsample p_keep percentage (default 80)")
    parser.add_argument("--live-pnl-osm", type=float, default=4000,
                        help="Observed live PnL on OSMIUM (finale units), default 4000")
    parser.add_argument("--live-pnl-ipr", type=float, default=8800,
                        help="Observed live PnL on IPR (finale units), default 8800")
    args = parser.parse_args()

    seeds = [int(s) for s in args.subsample_seeds.split(",")]

    # --- 1) Baseline backtest at 100% (≈ live-with-MAF equivalent)
    print(f"\n━━━ Baseline 100% (≈ live WITH MAF) | strategy={args.strategy} ━━━")
    pnl_100 = run_backtest(args.strategy, ROOT / "data")
    print(f"  PnL_100%: OSM={pnl_100.get('ASH_COATED_OSMIUM',0):,.0f}  "
          f"IPR={pnl_100.get('INTARIAN_PEPPER_ROOT',0):,.0f}  "
          f"TOT={pnl_100.get('TOTAL',0):,.0f}")

    # --- 2) Subsampled runs at 80% (≈ live-without-MAF equivalent)
    sub_results = []
    for seed in seeds:
        src = ROOT / "data" / f"round_2_subsample_p{args.p_keep}_s{seed}"
        if not src.exists():
            print(f"WARN: {src} not found — run 05_subsample_80pct.py first")
            continue
        parent = prep_synth_parent(src, f"sub80_s{seed}")
        print(f"\n━━━ Subsampled 80% seed={seed} (≈ live no-MAF) ━━━")
        p = run_backtest(args.strategy, parent)
        print(f"  PnL_80%:  OSM={p.get('ASH_COATED_OSMIUM',0):,.0f}  "
              f"IPR={p.get('INTARIAN_PEPPER_ROOT',0):,.0f}  "
              f"TOT={p.get('TOTAL',0):,.0f}")
        sub_results.append((seed, p))
        shutil.rmtree(parent, ignore_errors=True)

    if not sub_results:
        print("No subsampled data. Abort.")
        return

    # --- 3) Compute uplift ratios per product
    print("\n" + "═" * 78)
    print("UPLIFT RATIOS — PnL(100%) / PnL(80%)")
    print("═" * 78)
    ratios_osm, ratios_ipr, ratios_tot = [], [], []
    print(f"{'Seed':<8} {'r_OSM':>10} {'r_IPR':>10} {'r_TOT':>10} "
          f"{'uplift_OSM%':>12} {'uplift_IPR%':>12} {'uplift_TOT%':>12}")
    print("-" * 78)
    for seed, p in sub_results:
        r_o = pnl_100.get("ASH_COATED_OSMIUM", 0) / max(1, p.get("ASH_COATED_OSMIUM", 1))
        r_i = pnl_100.get("INTARIAN_PEPPER_ROOT", 0) / max(1, p.get("INTARIAN_PEPPER_ROOT", 1))
        r_t = pnl_100.get("TOTAL", 0) / max(1, p.get("TOTAL", 1))
        ratios_osm.append(r_o); ratios_ipr.append(r_i); ratios_tot.append(r_t)
        print(f"{seed:<8} {r_o:>10.3f} {r_i:>10.3f} {r_t:>10.3f} "
              f"{(r_o-1)*100:>+11.2f}% {(r_i-1)*100:>+11.2f}% {(r_t-1)*100:>+11.2f}%")

    def ms(xs):
        return statistics.mean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)

    m_o, s_o = ms(ratios_osm)
    m_i, s_i = ms(ratios_ipr)
    m_t, s_t = ms(ratios_tot)
    print("-" * 78)
    print(f"{'MEAN':<8} {m_o:>10.3f} {m_i:>10.3f} {m_t:>10.3f} "
          f"{(m_o-1)*100:>+11.2f}% {(m_i-1)*100:>+11.2f}% {(m_t-1)*100:>+11.2f}%")
    print(f"{'STD':<8} {s_o:>10.3f} {s_i:>10.3f} {s_t:>10.3f}")

    # --- 4) Apply uplift to observed live PnL
    print("\n" + "═" * 78)
    print("MAF GAIN ESTIMATE IN LIVE FINALE UNITS")
    print("═" * 78)
    live_tot = args.live_pnl_osm + args.live_pnl_ipr
    print(f"Observed live baseline (no MAF assumed):")
    print(f"  OSM = {args.live_pnl_osm:>7,.0f}")
    print(f"  IPR = {args.live_pnl_ipr:>7,.0f}")
    print(f"  TOT = {live_tot:>7,.0f}")

    gain_osm = args.live_pnl_osm * (m_o - 1)
    gain_ipr = args.live_pnl_ipr * (m_i - 1)
    gain_tot = gain_osm + gain_ipr
    gain_osm_std = args.live_pnl_osm * s_o
    gain_ipr_std = args.live_pnl_ipr * s_i

    print(f"\nMAF extra PnL (live, estimated):")
    print(f"  OSM : {gain_osm:>+8,.0f}  ± {gain_osm_std:,.0f}  ({(m_o-1)*100:+.2f}% of live OSM)")
    print(f"  IPR : {gain_ipr:>+8,.0f}  ± {gain_ipr_std:,.0f}  ({(m_i-1)*100:+.2f}% of live IPR)")
    print(f"  TOT : {gain_tot:>+8,.0f}  ({100*gain_tot/live_tot:+.2f}% of live TOT)")

    print(f"\nInterpretation:")
    print(f"  → Rational max bid (ignoring adversary game): {max(0, gain_tot):,.0f} XIRECs")
    print(f"  → Under first-price auction, optimal bid < this (see script 03/04).")
    print("═" * 78)


if __name__ == "__main__":
    main()
