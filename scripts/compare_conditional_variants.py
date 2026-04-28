"""Compare conditional risk-management variants vs baseline (no overfit-time mechanism).

Variants:
  - baseline (no risk management)
  - trend_only       — block BUYs when EMA-down trend on VELVET (threshold=0.5)
  - trend_aggressive — same but threshold=0.3
  - stoploss_v1      — flatten product on 30k drawdown from peak
  - stoploss_tight   — flatten on 15k drawdown
  - dhedge_v1        — full delta hedge VELVET to options
  - dhedge_partial   — 50% delta hedge
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / "artifacts" / "analysis" / "round_4"

VARIANTS = [
    ("baseline", "r4_velvet_options_only_3d.json"),
    ("trend_only", "r4_velvet_trend_only_3d.json"),
    ("trend_aggressive", "r4_velvet_trend_aggressive_3d.json"),
    ("stoploss_v1 (30k)", "r4_velvet_stoploss_v1_3d.json"),
    ("stoploss_tight (15k)", "r4_velvet_stoploss_tight_3d.json"),
    ("dhedge_v1 (full)", "r4_velvet_dhedge_v1_3d.json"),
    ("dhedge_partial (50%)", "r4_velvet_dhedge_partial_3d.json"),
]


def load(name, fname):
    path = ANALYSIS_DIR / fname
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    days = d["days"]
    return {
        "name": name,
        "total_pnl": d["summary"]["total_pnl"],
        "max_dd": d["summary"]["robustness"]["max_drawdown"],
        "ratio": d["summary"]["total_pnl"] / d["summary"]["robustness"]["max_drawdown"],
        "daily_pnls": [day["pnl"] for day in days],
        "per_product_pnl": d["summary"]["per_product_pnl"],
        "per_day_per_product": {
            f"D{day['day']}": {sym: stats["pnl"] for sym, stats in day["product_summaries"].items()}
            for day in days
        },
    }


def main():
    results = []
    for name, fname in VARIANTS:
        r = load(name, fname)
        if r is None:
            print(f"MISSING: {fname}")
            continue
        results.append(r)

    if not results:
        return

    base = results[0]

    print("=" * 110)
    print("CONDITIONAL RISK-MGMT VARIANTS vs BASELINE (3-day backtest, realistic fill, HYDROGEL OFF)")
    print("=" * 110)
    print(f"{'Variant':>22s}  {'PnL_3d':>10s}  {'vs base':>9s}  {'DD':>8s}  {'Ratio':>6s}  {'D1':>8s}  {'D2':>8s}  {'D3':>8s}")
    print("-" * 110)
    for r in results:
        delta_pnl = r["total_pnl"] - base["total_pnl"]
        d1, d2, d3 = r["daily_pnls"]
        flag = "  base" if r is base else ("  WIN!" if delta_pnl > 1000 else ("  LOSE" if delta_pnl < -1000 else "  ~~"))
        print(
            f"{r['name']:>22s}  "
            f"{r['total_pnl']:>+10,.0f}  "
            f"{delta_pnl:>+9,.0f}  "
            f"{r['max_dd']:>8,.0f}  "
            f"{r['ratio']:>6.2f}  "
            f"{d1:>+8,.0f}  {d2:>+8,.0f}  {d3:>+8,.0f}{flag}"
        )

    # D3 detail
    print("\n" + "=" * 110)
    print("D3 BREAKDOWN — most informative (the day that crashed in baseline)")
    print("=" * 110)
    print(f"{'Variant':>22s}  {'D3 PnL':>10s}  {'vs base':>9s}  per-product D3 PnL")
    print("-" * 110)
    base_d3_pnl = base["daily_pnls"][2]
    for r in results:
        d3_pnl = r["daily_pnls"][2]
        delta = d3_pnl - base_d3_pnl
        # Top 3 products by abs PnL on D3
        d3_prods = sorted(r["per_day_per_product"]["D3"].items(), key=lambda kv: -abs(kv[1]))[:6]
        prods_str = ", ".join(f"{sym.replace('VELVETFRUIT_EXTRACT', 'VELVET').replace('VEV_', '')}={pnl:+,.0f}" for sym, pnl in d3_prods if pnl != 0)
        print(f"{r['name']:>22s}  {d3_pnl:>+10,.0f}  {delta:>+9,.0f}  {prods_str}")


if __name__ == "__main__":
    main()
