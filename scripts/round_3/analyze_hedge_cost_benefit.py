"""Hedge cost/benefit analysis — last year's team rejected hedging because:
  - Hedging cost: 40k/day (spread + adverse selection on VELVET)
  - Potential loss without hedge: 16k/day
  - → unhedged is 24k/day better

Apply same calculation to our 3-day backtests. Per variant compute:
  - velvet_spread_cost = -(spread_capture_velvet)  if negative, else 0
  - velvet_take_cost   = -(take_edge_velvet)       if negative, else 0
  - velvet_realised_loss = velvet_pnl  (realized + MTM at end of day)
  - option_directional_pnl = inventory_drift (option drift contribution)
  - DD reduction vs no-hedge baseline (v11)

Output: artifacts/analysis/round_3_option_velvet/hedge_cost_benefit.csv
        plus a console table.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "artifacts" / "analysis" / "round_3"
ARTRES = ROOT / "artifacts" / "backtest_results" / "round_3" / "options_research"
OUT = ROOT / "artifacts" / "analysis" / "round_3_option_velvet"

VARIANTS = [
    ("v11_optimal (no hedge)",        ART / "r3_velvet_options_max3d_v11_optimal_3d.json"),
    ("v12_dh_passive (no taker)",     ART / "r3_velvet_options_max3d_v12_dh_passive_3d.json"),
    ("v13_dh_lowfreq (rare taker)",   ART / "r3_velvet_options_max3d_v13_dh_lowfreq_3d.json"),
    ("v14_dh_default (full hedger)",  ART / "r3_velvet_options_max3d_v14_dh_default_3d.json"),
    ("v20_z_skip_strict (z-gate)",    ART / "r3_velvet_options_max3d_v20_z_skip_strict_3d.json"),
    ("v24_r2velvet_zskip (R2+zskip)", ART / "r3_velvet_options_max3d_v24_r2velvet_zskip_3d.json"),
    ("v12_r2velvet (R2 anchor MM)",   ARTRES / "r3_velvet_options_max3d_v12_r2velvet_3d.json"),
]

BASELINE = "v11_optimal (no hedge)"


def load(p: Path) -> dict:
    return json.loads(p.read_text())


def main():
    rows = []
    baseline = None
    for label, path in VARIANTS:
        if not path.exists():
            print(f"missing: {label}")
            continue
        d = load(path)
        summ = d["summary"]
        rb = summ["robustness"]
        attr = rb["pnl_attribution"]

        velvet_pnl = summ["per_product_pnl"].get("VELVETFRUIT_EXTRACT", 0)
        velvet_trades = summ["per_product_trades"].get("VELVETFRUIT_EXTRACT", 0)
        total_pnl = summ["total_pnl"]
        max_dd = rb["max_drawdown"]

        row = dict(
            variant=label,
            total_pnl=int(total_pnl),
            max_dd=int(max_dd),
            pnl_dd_ratio=round(total_pnl / max(abs(max_dd), 1), 3),
            velvet_pnl=int(velvet_pnl),
            velvet_trades=int(velvet_trades),
            inventory_drift=int(attr.get("inventory_drift", 0)),
            spread_capture=int(attr.get("spread_capture", 0)),
            take_edge=int(attr.get("take_edge", 0)),
            make_edge=int(attr.get("make_edge", 0)),
            agg_adverse=int(attr.get("aggressive_adverse_selection_1", 0)),
            pas_adverse=int(attr.get("passive_adverse_selection_1", 0)),
        )
        rows.append(row)
        if label == BASELINE:
            baseline = row

    if not rows or baseline is None:
        print("No data")
        return 1

    print(f"\n{'Variant':<35} {'PnL':>9} {'DD':>9} {'Ratio':>6} {'VELVET':>8} {'V_trd':>6} {'inv_drift':>10} {'spread':>8} {'take':>8}")
    print("-" * 115)
    for r in rows:
        print(f"{r['variant']:<35} {r['total_pnl']:>9,} {r['max_dd']:>9,} {r['pnl_dd_ratio']:>6.2f} {r['velvet_pnl']:>8,} {r['velvet_trades']:>6,} {r['inventory_drift']:>10,} {r['spread_capture']:>8,} {r['take_edge']:>8,}")

    # Cost-benefit calculation for hedger variants
    print(f"\n{'='*60}")
    print("HEDGER COST/BENEFIT vs v11 baseline (per-3-day-backtest)")
    print(f"{'='*60}")
    print(f"{'Variant':<35} {'PnL Δ':>9} {'DD Δ':>9} {'Ratio Δ':>8} {'verdict':<20}")
    print("-" * 95)
    for r in rows:
        if r['variant'] == BASELINE: continue
        pnl_delta = r['total_pnl'] - baseline['total_pnl']
        dd_delta = r['max_dd'] - baseline['max_dd']  # less negative = better
        ratio_delta = r['pnl_dd_ratio'] - baseline['pnl_dd_ratio']
        if pnl_delta < 0 and dd_delta > 0:
            verdict = "WORSE: PnL -, DD worse"
        elif pnl_delta < 0 and dd_delta < 0:
            verdict = "TRADE: PnL -, DD better"
        elif pnl_delta > 0 and dd_delta < 0:
            verdict = "WIN: PnL +, DD better"
        elif pnl_delta > 0 and dd_delta > 0:
            verdict = "WIN: PnL +, DD worse"
        else:
            verdict = "neutral"
        print(f"{r['variant']:<35} {pnl_delta:>+9,} {dd_delta:>+9,} {ratio_delta:>+8.3f} {verdict:<20}")

    # Per-day cost/benefit for hedger variants only
    print(f"\n{'='*60}")
    print("PER-DAY HEDGE COST vs DIRECTIONAL RISK (last year's team analysis)")
    print(f"{'='*60}")
    for r in rows:
        if "dh_" not in r['variant']: continue
        pnl_loss_per_day = (baseline['total_pnl'] - r['total_pnl']) / 3.0
        dd_saved_per_day = (abs(baseline['max_dd']) - abs(r['max_dd'])) / 3.0
        print(f"{r['variant']:<35}")
        print(f"  Hedge cost (PnL lost):     {pnl_loss_per_day:>10,.0f}/day")
        print(f"  DD reduction (gain):       {dd_saved_per_day:>10,.0f}/day")
        if dd_saved_per_day > 0:
            ratio = pnl_loss_per_day / dd_saved_per_day
            print(f"  Cost/benefit ratio:        {ratio:>10.2f}  (>1 = hedge not worth it)")
        else:
            print(f"  No DD benefit, hedge IS A LOSS without compensation")
        print()

    # Final verdict summary
    print(f"{'='*60}")
    print("V24 (R2 VELVET + Z-GATE) — best risk-adjusted")
    print(f"{'='*60}")
    v24 = next((r for r in rows if "v24" in r['variant']), None)
    if v24:
        print(f"PnL +{v24['total_pnl']:,}  DD {v24['max_dd']:,}  Ratio {v24['pnl_dd_ratio']:.2f}")
        print(f"Z-gate replaces explicit delta hedge as the risk-control mechanism")
        print(f"(skip option entries when VELVET overbought instead of hedging post-fact)")

    OUT.mkdir(exist_ok=True, parents=True)
    csv_path = OUT / "hedge_cost_benefit.csv"
    with csv_path.open("w") as f:
        cols = list(rows[0].keys())
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(r[c]) for c in cols) + "\n")
    print(f"\n→ CSV written: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
