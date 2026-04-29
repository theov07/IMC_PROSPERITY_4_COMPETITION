"""Pick R5 final champion among v1614 family.

Reads `artifacts/r5_compare/<member>.txt` for each candidate, parses TOTAL line,
prints ranking, and emits `artifacts/r5_compare/.champion.txt`.
"""

from __future__ import annotations

import re
from pathlib import Path

CANDIDATES = [
    "best_v1611_drop_mint",
    "best_v1614_rectangle_pair",
    "best_v1620_v1614_drop_mint",
    "best_v1630_laundry_pair",
    "best_v1640_vac_pair",
    "best_v1650_both_robot_pairs",
    "best_v1660_super",
    "best_v1700_chip_pair",
    "best_v1710_circle_pair",
    "best_v1720_oval_only",
    "best_v1730_circle_oval",
    "best_v1740_circle_oval_partner",
    "best_v1750_symmetric_circle_oval",
    "best_v1760_oval_triangle_added",
    "best_v1770_circle_square",
    "best_v1780_panel_pair",
    "best_v1790_pistachio_vanilla",
    "best_v1800_eclipse_void",
    "best_v1810_astro_void",
    "best_v1820_morning_choco",
    "best_v1830_red_amber",
    "best_v1840_orange_yellow",
    "best_v1850_uv_combo",
    "best_v1860_with_astro",
    "best_v1870_red_yellow",
    "best_v1880_dark_planetary",
    "best_v1890_winds_planetary",
    "best_v1900_blackholes_planetary",
    "best_v1910_all_winners",
    "best_v1920_tighter_thresh",
    "best_v1930_size8",
    "best_v1940_triangle_square",
    "best_v1950_suede_nylon",
    "best_v1960_suede_poly",
    "best_v1970_morning_evening",
    "best_v1980_pebbles_l_pair",
    "best_v1990_garlic_choco",
    "best_v2000_vac_naive",
    "best_v2010_cotton_nylon",
    "best_v2020_poly_nylon",
    "best_v2030_suede_cotton_nylon",
    "best_v2040_three_sleep_pods",
    "best_v2050_cotton_only_v1910",
    "best_v2060_revive_lamb",
    "best_v2070_revive_pebbles_m",
    "best_v2080_revive_magenta",
    "best_v2090_revive_space_gray",
    "best_v2100_with_astro",
    "best_v2110_space_eclipse",
    "best_v2120_mist_void",
    "best_v2130_ironing_dishes",
    "best_v2140_mopping_dishes",
    "best_v2150_evening_choco",
    "best_v2160_astro_eclipse",
]

ROOT = Path(__file__).resolve().parents[1]
COMPARE = ROOT / "artifacts" / "r5_compare"


def _parse_total(path: Path) -> tuple[int | None, str | None]:
    if not path.is_file():
        return None, "missing"
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"TOTAL\s+│\s*3 day\(s\)\s*│\s*([-0-9,]+)\s*│", text)
    if not m:
        return None, "running"
    pnl = int(m.group(1).replace(",", ""))
    dd = re.search(r"TOTAL \(chained equity\)\s+([0-9,]+)\s+([\d.]+%)", text)
    dd_str = f"{dd.group(1)} ({dd.group(2)})" if dd else "n/a"
    return pnl, dd_str


def main():
    results = []
    for name in CANDIDATES:
        pnl, info = _parse_total(COMPARE / f"{name}.txt")
        results.append((name, pnl, info))

    # Sort by PnL desc (None last)
    results.sort(key=lambda x: x[1] if x[1] is not None else -10**9, reverse=True)

    print(f"{'#':>2}  {'Member':<35} {'PnL':>10}  Drawdown")
    print("-" * 75)
    baseline_pnl = next((p for n, p, _ in results if n == "best_v1611_drop_mint" and p is not None), None)
    for i, (name, pnl, info) in enumerate(results, 1):
        if pnl is None:
            print(f"{i:>2}  {name:<37} {'PEND':>10}  ({info})")
        else:
            delta = ""
            if baseline_pnl is not None and name != "best_v1611_drop_mint":
                d = pnl - baseline_pnl
                delta = f" ({d:+,} vs v1611)"
            print(f"{i:>2}  {name:<37} {pnl:>10,}  {info}{delta}")

    finished = [r for r in results if r[1] is not None]
    if finished:
        champ = max(finished, key=lambda x: x[1])
        print()
        print(f"CHAMPION: {champ[0]} = {champ[1]:,} PnL  (DD={champ[2]})")
        (COMPARE / ".champion.txt").write_text(f"{champ[0]}\t{champ[1]}\t{champ[2]}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
