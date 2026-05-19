"""Strip unused (opt-in, no-op in champion_19april_am) helpers from an exported submission.

Removes the following methods from MMFirstV4ComboStrategy (they're all opt-in
via params that default to no-op in v4_F5):

  _compute_base_mid, _probe_quotes, _probe_tick0, _apply_momentum_follower,
  _apply_toxic_flow, _apply_jump_filter, _taker_cooldown_active,
  _update_taker_cooldown, _microprice_size_tilt, _apply_spread_widening,
  _apply_spread_zscore_skew, _apply_fill_rate_toxicity, _asym_passive_skew,
  _apply_eod_flatten, _zscore_taker_adjust, _zscore_price_skew

AND their call sites in compute_orders (we replace call-lines with no-op
equivalents that keep variables defined).
"""
from __future__ import annotations
import ast
import re
import sys
from pathlib import Path


DEAD_METHODS = [
    "_compute_base_mid",
    "_probe_quotes",
    "_probe_tick0",
    "_apply_momentum_follower",
    "_apply_toxic_flow",
    "_apply_jump_filter",
    "_taker_cooldown_active",
    "_update_taker_cooldown",
    "_microprice_size_tilt",
    "_apply_spread_widening",
    "_apply_spread_zscore_skew",
    "_apply_fill_rate_toxicity",
    "_asym_passive_skew",
    "_apply_eod_flatten",
    "_zscore_taker_adjust",
    "_zscore_price_skew",
]


def strip_methods_from_class(source: str, method_names: list[str]) -> str:
    """Parse source with AST, find each method by name inside any class, and remove it."""
    tree = ast.parse(source)
    remove_ranges: list[tuple[int, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in method_names:
                    remove_ranges.append((item.lineno, item.end_lineno))

    lines = source.splitlines(keepends=True)
    # Delete in descending order
    for start, end in sorted(remove_ranges, reverse=True):
        del lines[start - 1:end]
    return "".join(lines)


def replace_call_sites(source: str) -> str:
    """Replace calls to removed helpers in compute_orders with no-op equivalents."""
    # Each call produced certain outputs that the orchestrator uses.
    # Replace them with identity assignments to keep the code valid.

    replacements = [
        # base_mid = self._compute_base_mid(mid, book)
        (r"base_mid = self\._compute_base_mid\(mid, book\)",
         "base_mid = mid"),
        # various passthrough helpers that return (bid, ask) unchanged
        (r"bid_price, ask_price = self\._asym_passive_skew\(bid_price, ask_price, eff_position, book\)",
         "pass"),
        (r"bid_price, ask_price = self\._apply_spread_widening\(bid_price, ask_price, book, memory\)",
         "pass"),
        (r"bid_price, ask_price = self\._apply_spread_zscore_skew\(bid_price, ask_price, book, memory\)",
         "pass"),
        # sizes passthrough
        (r"bid_size, ask_size = self\._apply_toxic_flow\(state, memory, bid_size, ask_size\)",
         "pass"),
        (r"bid_size, ask_size = self\._apply_jump_filter\(book, memory, bid_size, ask_size\)",
         "pass"),
        (r"bid_size, ask_size = self\._apply_fill_rate_toxicity\(state, memory, bid_size, ask_size\)",
         "pass"),
        (r"bid_size, ask_size = self\._microprice_size_tilt\(book, mid, bid_size, ask_size\)",
         "pass"),
        # probe / momentum helpers return empty orders
        (r"probe_orders, buy_cap, sell_cap = self\._probe_quotes\([^)]+\)",
         "probe_orders = []"),
        (r"probe_t0_orders, buy_cap, sell_cap = self\._probe_tick0\([^)]+\)",
         "probe_t0_orders = []"),
        (r"momentum_orders, buy_cap, sell_cap = self\._apply_momentum_follower\([^)]+\)",
         "momentum_orders = []"),
        # taker cooldown: no-op both checks
        (r"buy_blocked, sell_blocked = self\._taker_cooldown_active\(state, memory\)",
         "buy_blocked = sell_blocked = False"),
        (r"self\._update_taker_cooldown\(state, memory, taker_buy_px, taker_sell_px\)",
         "pass"),
        # eod_flatten returns None -> kept call but strip it
        (r"eod_orders = self\._apply_eod_flatten\(state, order_depth, position\)\s*\n\s*if eod_orders is not None:\s*\n\s*return eod_orders, 0",
         "pass  # eod_flatten stripped"),
        # inventory_bias calls _apply_inventory_bias but also passes through eff_position
        # NOT removed since inventory_aversion_gamma=0.0015 IS set in v4_F5 → active
        # Skip
    ]

    for pattern, replacement in replacements:
        source = re.sub(pattern, replacement, source, flags=re.MULTILINE)
    return source


def main():
    if len(sys.argv) != 2:
        print("Usage: python _strip_dead_helpers.py <path_to_submission.py>")
        sys.exit(1)
    p = Path(sys.argv[1])
    src = p.read_text(encoding="utf-8")
    before = len(src.encode("utf-8"))

    # Strip methods
    src = strip_methods_from_class(src, DEAD_METHODS)
    # Replace call sites
    src = replace_call_sites(src)
    # Validate
    ast.parse(src)

    after = len(src.encode("utf-8"))
    out = p.with_stem(p.stem + "_stripped")
    out.write_text(src, encoding="utf-8")
    print(f"{p.name}: {before:,} -> {after:,} bytes ({100*(before-after)/before:.1f}% reduction)")
    print(f"Written: {out}")


if __name__ == "__main__":
    main()
