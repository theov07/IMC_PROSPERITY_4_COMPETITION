"""Compact PRODUCTS dict by extracting common base + overrides."""
import re
import ast
from pathlib import Path

SRC = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION/prosperity/strategies/round_4/leo/r4_champion_FINAL.py")


def main():
    text = SRC.read_text(encoding="utf-8")
    before = len(text.encode())

    m = re.search(r"PRODUCTS\s*=\s*(\{[^\n]+\})", text, re.DOTALL)
    products = ast.literal_eval(m.group(1))

    # Find common params across VEV_x products (gamma_scalp_zgated + vev_option_mm_v3)
    vev_keys = [k for k in products if k.startswith("VEV_")]
    if not vev_keys:
        return

    # Build common base from first VEV
    first = products[vev_keys[0]]
    common = {}
    for key, val in first.items():
        # Only include if value matches across ALL vev products
        if all(other.get(key, object()) == val for other in (products[s] for s in vev_keys)):
            # And don't include strategy/strike (they differ)
            if key not in ("strategy", "strike"):
                common[key] = val

    # Build new PRODUCTS using {**_VB, **overrides}
    out_lines = []
    out_lines.append(f"_VB = {repr(common)}")
    out_lines.append("PRODUCTS = {")

    # Non-VEV products: keep as-is
    for sym in products:
        if sym.startswith("VEV_"):
            continue
        out_lines.append(f"    {sym!r}: {products[sym]!r},")

    # VEV products: use {**_VB, ...overrides}
    for sym in vev_keys:
        cfg = products[sym]
        overrides = {k: v for k, v in cfg.items() if k not in common or common.get(k) != v}
        # Only keep params NOT in common (strategy, strike, and any that differ)
        ov_only = {k: v for k, v in cfg.items() if cfg[k] != common.get(k, object())}
        # Use **
        out_lines.append(f"    {sym!r}: {{**_VB, {', '.join(f'{k!r}: {v!r}' for k, v in ov_only.items())}}},")

    out_lines.append("}")
    new_products_block = "\n".join(out_lines)

    # Replace
    new_text = text.replace("PRODUCTS = " + m.group(1), new_products_block)
    # Validate
    ast.parse(new_text)
    SRC.write_text(new_text, encoding="utf-8")

    after = len(new_text.encode())
    print(f"Before: {before:,} bytes")
    print(f"After:  {after:,} bytes  ({100*after/100000:.2f}%)")
    print(f"Saved:  {before - after:,} bytes ({100*(before-after)/before:.1f}%)")
    print(f"Common params extracted: {len(common)}")


if __name__ == "__main__":
    main()
