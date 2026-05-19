"""Quick inspection of one R4 backtest JSON's top-level schema."""
import json
from pathlib import Path

path = Path("artifacts/analysis/round_4/r4_v57_best_ratio_3d.json")
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("Top-level keys:", list(data.keys()) if isinstance(data, dict) else type(data))


def inspect(obj, depth=0, max_depth=3, max_items=8):
    if depth >= max_depth:
        return
    if isinstance(obj, dict):
        for i, (k, v) in enumerate(obj.items()):
            if i >= max_items:
                print("  " * depth + f"... +{len(obj) - max_items} more keys")
                break
            if isinstance(v, (dict, list)):
                preview = f"<{type(v).__name__} len={len(v)}>"
            else:
                preview = repr(v)[:80]
            print("  " * depth + f"{k!r}: {preview}")
            if isinstance(v, dict):
                inspect(v, depth + 1, max_depth, max_items)
            elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                print("  " * (depth + 1) + f"[0] sample:")
                inspect(v[0], depth + 2, max_depth, max_items)


inspect(data)
