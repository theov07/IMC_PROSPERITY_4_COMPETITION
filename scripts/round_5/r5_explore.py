"""R5 data exploration — find patterns, mid-price profiles, group correlations."""
from __future__ import annotations

import numpy as np
import pandas as pd
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "round_5"

GROUPS = {
    "Galaxy_Sounds": ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                      "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                      "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "Sleep_Pods": ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                   "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "Microchips": ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                   "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "Pebbles": ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "Robots": ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
               "ROBOT_LAUNDRY", "ROBOT_IRONING"],
    "UV_Visors": ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                  "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "Translators": ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                    "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                    "TRANSLATOR_VOID_BLUE"],
    "Panels": ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "Oxygen_Shakes": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                      "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC"],
    "Snack_Packs": ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                    "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
}


def main():
    print("=" * 100)
    print("ROUND 5 — DATA EXPLORATION")
    print("=" * 100)
    # Load all 3 days prices
    dfs = []
    for d in [2, 3, 4]:
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    prices = pd.concat(dfs, ignore_index=True)
    prices["mid"] = (prices["bid_price_1"].fillna(0) + prices["ask_price_1"].fillna(0)) / 2

    print(f"\nTotal rows: {len(prices):,}")
    print(f"Days: {sorted(prices['day'].unique())}")
    print(f"Products: {len(prices['product'].unique())}")
    print()

    # Per-product stats
    print("=" * 100)
    print("PER-PRODUCT MID PRICE STATS (3-day)")
    print("=" * 100)
    print(f"{'Group':<14s}  {'Product':<35s}  {'Start':>9s}  {'End':>9s}  {'Drift':>8s}  {'%':>6s}  {'Min':>9s}  {'Max':>9s}  {'Std':>7s}")
    print("-" * 110)
    for group, prods in GROUPS.items():
        for p in prods:
            sub = prices[prices["product"] == p].sort_values(["day", "timestamp"])
            sub = sub[sub["mid"] > 0]
            if len(sub) == 0:
                print(f"{group:<14s}  {p:<35s}  NO DATA")
                continue
            s, e = sub.iloc[0]["mid"], sub.iloc[-1]["mid"]
            mn, mx = sub["mid"].min(), sub["mid"].max()
            std = sub["mid"].std()
            drift = e - s
            pct = drift / s * 100 if s else 0
            print(f"{group:<14s}  {p:<35s}  {s:>9.2f}  {e:>9.2f}  {drift:>+8.2f}  {pct:>+6.2f}%  {mn:>9.2f}  {mx:>9.2f}  {std:>7.2f}")
        print()

    # Within-group correlations (5 products each)
    print("=" * 100)
    print("WITHIN-GROUP MID PRICE CORRELATIONS (3-day, day 2)")
    print("Looks for groups where products move together (high corr) — possible spreads / pairs")
    print("=" * 100)

    pivot = prices[prices["day"] == 2].pivot_table(
        index="timestamp", columns="product", values="mid", aggfunc="first"
    )
    for group, prods in GROUPS.items():
        avail = [p for p in prods if p in pivot.columns]
        if len(avail) < 2:
            continue
        corr = pivot[avail].corr()
        # Print average of off-diagonal
        n = len(avail)
        off_diag = (corr.values.sum() - n) / (n * n - n)
        print(f"\n{group} (avg off-diag corr: {off_diag:.3f})")
        # Print full corr matrix
        print(corr.round(3).to_string())


if __name__ == "__main__":
    main()
