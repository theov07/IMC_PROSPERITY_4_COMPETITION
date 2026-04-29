"""Per-product breakdown : best_v10 vs carry overlays.

Identifies which specific products benefit from carry, which don't,
and which would benefit from being kept naive_mm.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION")
COMP = ROOT / "artifacts" / "r5_compare"


def parse(filepath: Path) -> dict:
    if not filepath.exists():
        return {}
    with open(filepath, encoding='utf-8', errors='replace') as f:
        txt = f.read()
    out = {}
    cur = None
    for line in txt.splitlines():
        m = re.match(r'\s+([A-Z][A-Z0-9_]+)\s+\│\s*day\s+\d', line)
        if m: cur = m.group(1)
        if 'subtotal' in line and cur:
            parts = re.split(r'[│|]', line)
            if len(parts) > 2:
                pm = re.search(r'([-]?[\d,]+)', parts[2])
                if pm:
                    out[cur] = int(pm.group(1).replace(',',''))
            cur = None
    return out


def main():
    # Compare available variants
    variants_to_check = [
        "best_v10", "best_v1010_carry", "best_v1020_full_carry",
        "best_v3000_carry_flipped", "best_v4000_adaptive_flipped",
        "best_v2000_carry_snack", "best_v5000_audit_carry",
        "best_v6000_superalgo", "best_v7000_superalgo_slow", "best_v8000_superalgo_fast",
        "best_v9000_topdown",
    ]
    data = {}
    for v in variants_to_check:
        d = parse(COMP / f"{v}.txt")
        if d:
            data[v] = d

    if "best_v10" not in data:
        print("Missing best_v10 baseline")
        return

    print(f"{'variant':<35} {'total':>10} {'delta_v10':>10}")
    print("-" * 60)
    base = sum(data["best_v10"].values())
    for v, d in data.items():
        total = sum(d.values())
        delta = total - base
        print(f"{v:<35} {total:>10,} {delta:>+10,}")

    # Per-product detail for top 3 carry variants
    print("\n\n=== Per-product diff vs v10 (top 5 helpers + top 5 hurters) ===")
    for v in ["best_v1010_carry", "best_v1020_full_carry", "best_v6000_superalgo",
              "best_v5000_audit_carry"]:
        if v not in data: continue
        diffs = []
        all_p = set(data["best_v10"].keys()) | set(data[v].keys())
        for p in all_p:
            a = data["best_v10"].get(p, 0)
            b = data[v].get(p, 0)
            if a != b:
                diffs.append((p, a, b, b - a))
        diffs.sort(key=lambda x: x[3], reverse=True)
        print(f"\n{v}:")
        print(f"  HELPERS: {[(p,d) for p,_,_,d in diffs[:5]]}")
        print(f"  HURTERS: {[(p,d) for p,_,_,d in diffs[-5:]]}")


if __name__ == "__main__":
    main()
