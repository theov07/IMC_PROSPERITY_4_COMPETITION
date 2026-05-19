"""Inspect days[].product_summaries to find per-day per-product DD."""
import json
from pathlib import Path

path = Path("artifacts/analysis/round_4/r4_v57_best_ratio_3d.json")
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

day0 = data["days"][0]
print("Day 0 top-level keys:", list(day0.keys()))
print(f"\nDay 0 PnL: {day0['pnl']}")

ps = day0["product_summaries"]
print(f"\nProduct summaries keys: {list(ps.keys())}")
print("\nVELVETFRUIT_EXTRACT day 0 summary:")
for k, v in ps["VELVETFRUIT_EXTRACT"].items():
    if isinstance(v, (int, float, str, bool, type(None))):
        print(f"  {k}: {v}")
    else:
        print(f"  {k}: <{type(v).__name__}>")
