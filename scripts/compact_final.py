"""Aggressive compaction of r4_champion_FINAL.py.

1. Strip all # comments (line comments + inline)
2. Drop unused params per product
3. Validate AST + write
"""
import re
import ast
import sys
from pathlib import Path

SRC = Path("C:/Users/LéoRENAULT/Documents/projet/prosperity/IMC_PROSPERITY_4_COMPETITION/prosperity/strategies/round_4/leo/r4_champion_FINAL.py")


def strip_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        in_str = False
        quote = None
        new_line = ""
        i = 0
        while i < len(line):
            ch = line[i]
            if in_str:
                if ch == "\\":
                    # escape next char
                    new_line += ch
                    if i + 1 < len(line):
                        new_line += line[i + 1]
                        i += 1
                elif ch == quote:
                    in_str = False
                    new_line += ch
                else:
                    new_line += ch
            else:
                if ch in ('"', "'"):
                    in_str = True
                    quote = ch
                    new_line += ch
                elif ch == "#":
                    break
                else:
                    new_line += ch
            i += 1
        new_line = new_line.rstrip()
        if new_line:
            out.append(new_line)
    return "\n".join(out)


def drop_unused_params(text: str) -> tuple[str, int]:
    m = re.search(r"PRODUCTS\s*=\s*(\{[^\n]+\})", text, re.DOTALL)
    if not m:
        return text, 0
    products = ast.literal_eval(m.group(1))
    saved = 0
    for sym, cfg in products.items():
        # Drop zscore_* if zscore_exec_mode is "none" or absent
        if cfg.get("zscore_exec_mode", "none") == "none":
            for k in list(cfg.keys()):
                if k.startswith("zscore_") and k != "zscore_exec_mode":
                    saved += len(repr(k)) + len(repr(cfg[k])) + 4
                    cfg.pop(k)
        # Drop guard_* if strategy != r3_guarded_anchor_mm
        if cfg.get("strategy", "") != "r3_guarded_anchor_mm":
            for k in list(cfg.keys()):
                if k.startswith("guard_"):
                    saved += len(repr(k)) + len(repr(cfg[k])) + 4
                    cfg.pop(k)
        # Drop tte_days_initial, timestamp_units_per_day for non-option strategies
        if cfg.get("strategy", "") not in ("gamma_scalp_zgated", "vev_option_mm_v3", "option_mm_bs"):
            for k in ("tte_days_initial", "timestamp_units_per_day"):
                if k in cfg:
                    saved += len(repr(k)) + len(repr(cfg[k])) + 4
                    cfg.pop(k)
    return text.replace(m.group(1), repr(products)), saved


def main():
    text = SRC.read_text(encoding="utf-8")
    before = len(text.encode())
    text = strip_comments(text)
    text, saved_params = drop_unused_params(text)
    # Validate
    ast.parse(text)
    SRC.write_text(text, encoding="utf-8")
    after = len(text.encode())
    print(f"Before: {before:,} bytes")
    print(f"After:  {after:,} bytes  ({100*after/100000:.2f}% of 100KB)")
    print(f"Saved:  {before - after:,} bytes ({100*(before-after)/before:.1f}%)")


if __name__ == "__main__":
    main()
