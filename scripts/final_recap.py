"""Final recap: per-product per-day PnL for our best strategies on R4 backtest 3-day."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / "artifacts" / "analysis" / "round_4"

VARIANTS = [
    ("BASELINE r4_velvet_options_only", "r4_velvet_options_only_3d.json"),
    ("v1 fade_mark49", "r4_velvet_cp_bias_fade_mark49_3d.json"),
    ("v2 fade_49_14", "r4_velvet_fade_49_14_3d.json"),
    ("v3 combo_obi_fade", "r4_velvet_combo_obi_fade_3d.json"),
    ("v4 combo_w01_w02", "r4_velvet_combo_obi_fade_w01_w02_3d.json"),
    ("★ v5 (M49=-0.8) UPLOAD", "r4_velvet_v4_M49_w08_3d.json"),
]


def fmt(v, w=10):
    if v is None:
        return f"{'n/a':>{w}s}"
    return f"{v:>+{w},.0f}"


def per_product_max_dd_proxy(d, product):
    """Approximate per-product DD from per-day PnL min (worst day)."""
    days = d["days"]
    daily_pnls = []
    for day in days:
        ps = day["product_summaries"].get(product, {})
        daily_pnls.append(ps.get("pnl", 0))
    return min(daily_pnls) if daily_pnls else 0


def main():
    results = []
    for name, fname in VARIANTS:
        path = ANALYSIS_DIR / fname
        if not path.exists():
            print(f"MISSING: {fname}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        results.append((name, d))

    # ── 1. PnL TOTAL TABLE ─────────────────────────────────
    print("=" * 110)
    print("RÉCAP — PnL TOTAL et DD PAR JOUR")
    print("=" * 110)
    print(f"{'Variant':>32s}  {'PnL_3d':>10s}  {'DD':>8s}  {'Ratio':>6s}  {'D1':>10s}  {'D2':>10s}  {'D3':>10s}")
    print("-" * 110)
    for name, d in results:
        days = d["days"]
        pnl = d["summary"]["total_pnl"]
        dd = d["summary"]["robustness"]["max_drawdown"]
        ratio = pnl / dd if dd else 0
        daily = [day["pnl"] for day in days]
        print(f"{name:>32s}  {pnl:>+10,.0f}  {dd:>8,.0f}  {ratio:>6.2f}  {daily[0]:>+10,.0f}  {daily[1]:>+10,.0f}  {daily[2]:>+10,.0f}")

    # ── 2. PnL PAR PRODUIT (3-day total) ───────────────────
    print("\n" + "=" * 130)
    print("PnL PAR PRODUIT (3-day total, par variant)")
    print("=" * 130)
    products = sorted(results[0][1]["summary"]["per_product_pnl"].keys())
    relevant = [p for p in products if any(
        r[1]["summary"]["per_product_pnl"].get(p, 0) for r in results
    )]
    header = f"{'Product':>22s}" + "".join(f"{n[:18]:>20s}" for n, _ in results)
    print(header)
    print("-" * 130)
    for prod in relevant:
        row = f"{prod:>22s}"
        for _, d in results:
            v = d["summary"]["per_product_pnl"].get(prod, 0)
            row += f"{v:>+20,.0f}"
        print(row)
    # Total row
    print("-" * 130)
    row = f"{'TOTAL':>22s}"
    for _, d in results:
        row += f"{d['summary']['total_pnl']:>+20,.0f}"
    print(row)

    # ── 3. PnL PAR PRODUIT PAR JOUR pour CHAMPION v5 ───────
    print("\n" + "=" * 110)
    print("DÉTAIL PRODUIT × JOUR pour CHAMPION v5 (UPLOAD)")
    print("=" * 110)
    champion = results[-1]  # last = v5
    name, d = champion
    print(f"  {name}")
    print(f"  Total: PnL {d['summary']['total_pnl']:>+10,.0f} / DD {d['summary']['robustness']['max_drawdown']:>8,.0f} / Ratio {d['summary']['total_pnl']/d['summary']['robustness']['max_drawdown']:.2f}\n")
    print(f"  {'Product':>22s}  {'D1':>12s}  {'D2':>12s}  {'D3':>12s}  {'Total':>12s}  {'Worst day':>12s}")
    print("-" * 100)
    for prod in relevant:
        d1 = d["days"][0]["product_summaries"].get(prod, {}).get("pnl", 0)
        d2 = d["days"][1]["product_summaries"].get(prod, {}).get("pnl", 0)
        d3 = d["days"][2]["product_summaries"].get(prod, {}).get("pnl", 0)
        tot = d1 + d2 + d3
        worst = min(d1, d2, d3)
        worst_str = f"{worst:>+12,.0f}" if worst < 0 else f"{'(no loss)':>12s}"
        print(f"  {prod:>22s}  {d1:>+12,.0f}  {d2:>+12,.0f}  {d3:>+12,.0f}  {tot:>+12,.0f}  {worst_str}")

    # ── 4. COMPARAISON BASELINE vs v5 par produit ──────────
    print("\n" + "=" * 110)
    print("COMPARAISON BASELINE vs v5 — DELTA PAR PRODUIT (où v5 gagne le plus)")
    print("=" * 110)
    base = results[0][1]
    v5 = results[-1][1]
    print(f"  {'Product':>22s}  {'Baseline':>12s}  {'v5':>12s}  {'Delta':>12s}  {'D1d':>10s}  {'D2d':>10s}  {'D3d':>10s}")
    print("-" * 110)
    deltas = []
    for prod in relevant:
        b_total = base["summary"]["per_product_pnl"].get(prod, 0)
        v_total = v5["summary"]["per_product_pnl"].get(prod, 0)
        delta = v_total - b_total
        d1d = v5["days"][0]["product_summaries"].get(prod, {}).get("pnl", 0) - base["days"][0]["product_summaries"].get(prod, {}).get("pnl", 0)
        d2d = v5["days"][1]["product_summaries"].get(prod, {}).get("pnl", 0) - base["days"][1]["product_summaries"].get(prod, {}).get("pnl", 0)
        d3d = v5["days"][2]["product_summaries"].get(prod, {}).get("pnl", 0) - base["days"][2]["product_summaries"].get(prod, {}).get("pnl", 0)
        deltas.append((prod, delta, d1d, d2d, d3d))
    deltas.sort(key=lambda x: -x[1])
    for prod, delta, d1d, d2d, d3d in deltas:
        b = base["summary"]["per_product_pnl"].get(prod, 0)
        v = v5["summary"]["per_product_pnl"].get(prod, 0)
        print(f"  {prod:>22s}  {b:>+12,.0f}  {v:>+12,.0f}  {delta:>+12,.0f}  {d1d:>+10,.0f}  {d2d:>+10,.0f}  {d3d:>+10,.0f}")


if __name__ == "__main__":
    main()
