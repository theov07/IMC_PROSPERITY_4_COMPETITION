"""Analyze v4xxx BT outputs and compare per-day PnL."""
import re
import sys
from pathlib import Path

FILES = {
    "v3000_hybrid (baseline)": "artifacts/submissions/round_5/v3000_backtest_output.txt",
    "coloc": "/tmp/coloc_bt.txt",
    "v4000 (coloc params)": "/tmp/v4000_bt.txt",
    "v4100 (universal, all)": "/tmp/v4100_bt.txt",
    "v4200 (universal, conservative)": "/tmp/v4200_bt.txt",
    "v4300 (universal, medium)": "/tmp/v4300_bt.txt",
}


def parse_pnl(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        content = p.read_text(encoding="utf-8")
    except Exception:
        return None
    if not content:
        return None
    day_pnl = {2: 0, 3: 0, 4: 0}
    products_pnl = {}  # sym -> {2: x, 3: y, 4: z}
    cur_sym = None
    for line in content.splitlines():
        # detect product header: "PRODUCT_NAME" at start of line
        m = re.match(r"^\s+([A-Z][A-Z_0-9]+)\s+│\s*day (\d)\s*│\s*(-?[\d,]+)", line)
        if m:
            sym, d, pnl = m.group(1), int(m.group(2)), int(m.group(3).replace(",", ""))
            cur_sym = sym
            if d in day_pnl:
                day_pnl[d] += pnl
                products_pnl.setdefault(sym, {})[d] = pnl
            continue
        # continuation line "   │ day 3   │ ..."
        m = re.match(r"^\s+│\s*day (\d)\s*│\s*(-?[\d,]+)", line)
        if m and cur_sym:
            d, pnl = int(m.group(1)), int(m.group(2).replace(",", ""))
            if d in day_pnl:
                day_pnl[d] += pnl
                products_pnl.setdefault(cur_sym, {})[d] = pnl
    return day_pnl, products_pnl


def main():
    print(f"{'Variant':<35}  {'Day 2':>10}  {'Day 3':>10}  {'Day 4':>10}  {'Total':>10}")
    print("=" * 85)
    results = {}
    for label, path in FILES.items():
        r = parse_pnl(path)
        if r is None:
            print(f"{label:<35}  {'(running)':>10}")
            continue
        day_pnl, prods = r
        total = sum(day_pnl.values())
        results[label] = (day_pnl, prods, total)
        print(f"{label:<35}  {day_pnl[2]:>10,}  {day_pnl[3]:>10,}  {day_pnl[4]:>10,}  {total:>10,}")
    print()
    # Compare deltas vs v3000 on day 4 (live)
    if "v3000_hybrid (baseline)" in results:
        baseline = results["v3000_hybrid (baseline)"][0][4]
        print(f"\nDay-4 (LIVE) Δ vs v3000_hybrid baseline ({baseline:,}):")
        for label, (day_pnl, _, _) in results.items():
            if label == "v3000_hybrid (baseline)":
                continue
            delta = day_pnl[4] - baseline
            sign = "+" if delta > 0 else ""
            print(f"  {label:<35}  Δ Day-4 = {sign}{delta:,}")


if __name__ == "__main__":
    main()
