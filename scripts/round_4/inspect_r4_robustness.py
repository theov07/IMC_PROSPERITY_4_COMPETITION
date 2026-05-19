"""Inspect robustness keys to find max drawdown."""
import json
from pathlib import Path

path = Path("artifacts/analysis/round_4/r4_v57_best_ratio_3d.json")
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

rob = data["summary"]["robustness"]
print("Top-level robustness keys:")
for k, v in rob.items():
    if isinstance(v, (int, float, str, bool)):
        print(f"  {k}: {v}")
    else:
        print(f"  {k}: <{type(v).__name__}>")

print("\nVELVETFRUIT_EXTRACT robustness sample:")
prob = data["summary"]["per_product_robustness"]["VELVETFRUIT_EXTRACT"]
for k, v in prob.items():
    if isinstance(v, (int, float, str, bool)):
        print(f"  {k}: {v}")
    else:
        print(f"  {k}: <{type(v).__name__}>")
