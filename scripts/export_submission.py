"""Export a single-file Prosperity submission from the modular framework.

Inlines the actual strategy source files so the exported submission always
reflects the current modular codebase — no separate template to maintain.

Usage:
  python scripts/export_submission.py --member champion --round 0
  python scripts/export_submission.py --member leo --round 0 --output my_submission.py

When you add a new strategy:
  1. Create  prosperity/strategies/my_strategy.py  (the canonical source)
  2. Register it in  prosperity/strategies/__init__.py
  3. Add one line to STRATEGY_REGISTRY below (name → file + class name)
"""

import argparse
import ast
import sys
from pathlib import Path
from pprint import pformat
from textwrap import dedent
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prosperity.config import MEMBER_OVERRIDES, get_round_config


# ── Strategy registry ──────────────────────────────────────────────────────
# Maps strategy name → (source file relative to repo root, exported class name).
# Keep this in sync with prosperity/strategies/__init__.py.
STRATEGY_REGISTRY: dict[str, tuple[str, str]] = {
    "market_maker":       ("prosperity/strategies/market_maker.py",       "MarketMakerStrategy"),
    "naive_tight_mm":     ("prosperity/strategies/naive_tight_mm.py",     "NaiveTightMarketMakerStrategy"),
    "naive_tight_mm_v2":  ("prosperity/strategies/naive_tight_mm_v2.py",  "NaiveTightMarketMakerV2Strategy"),
    "naive_tight_mm_v3":  ("prosperity/strategies/naive_tight_mm_v3.py",  "NaiveTightMarketMakerV3Strategy"),
    "naive_tight_mm_v4":  ("prosperity/strategies/naive_tight_mm_v4.py",  "NaiveTightMarketMakerV4Strategy"),
    "naive_tight_mm_v5":  ("prosperity/strategies/naive_tight_mm_v5.py",  "NaiveTightMarketMakerV5Strategy"),
    "naive_tight_mm_v6":  ("prosperity/strategies/naive_tight_mm_v6.py",  "NaiveTightMarketMakerV6Strategy"),
    "naive_tight_mm_v7":  ("prosperity/strategies/naive_tight_mm_v7.py",  "NaiveTightMarketMakerV7Strategy"),
    "avellaneda_stoikov": ("prosperity/strategies/avellaneda_stoikov.py", "AvellanedaStoikovStrategy"),
    "stat_arb":           ("prosperity/strategies/stat_arb.py",           "StatArbStrategy"),
    "black_scholes":      ("prosperity/strategies/black_scholes.py",      "BlackScholesStrategy"),
    "conversion_arb":     ("prosperity/strategies/conversion_arb.py",     "ConversionArbStrategy"),
    "signal_trader":      ("prosperity/strategies/signal_trader.py",      "SignalTraderStrategy"),
}

# Core modules always inlined (order matters — later modules depend on earlier ones).
CORE_MODULES = [
    "prosperity/market.py",
    "prosperity/persistence.py",
    "prosperity/strategies/base.py",
]


# ── Source processing ──────────────────────────────────────────────────────

def _extract(source: str) -> tuple[list[str], str]:
    """Parse *source* and return (external_import_lines, body_text).

    Strips from the body:
    - Module-level docstring
    - ``from __future__ import annotations`` (added once at the top of the output)
    - All ``from prosperity.X import ...`` and ``import prosperity.X`` lines
      (these modules are inlined; their symbols are already available)

    Collects for deduplication:
    - All other top-level import statements (stdlib, datamodel, typing, …)
    """
    tree = ast.parse(source)
    src_lines = source.splitlines(keepends=True)
    skip: set[int] = set()          # 1-indexed line numbers to remove from body
    external: list[str] = []

    # Skip module-level docstring.
    first = tree.body[0] if tree.body else None
    if (first and isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        for ln in range(first.lineno, first.end_lineno + 1):
            skip.add(ln)

    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue

        is_future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        is_internal = False
        if isinstance(node, ast.ImportFrom) and node.module:
            is_internal = node.module == "prosperity" or node.module.startswith("prosperity.")
        elif isinstance(node, ast.Import):
            is_internal = any(
                alias.name == "prosperity" or alias.name.startswith("prosperity.")
                for alias in node.names
            )

        # Always remove import lines from the body.
        for ln in range(node.lineno, node.end_lineno + 1):
            skip.add(ln)

        # Keep external imports for the top-level block.
        if not is_internal and not is_future:
            chunk = "".join(src_lines[node.lineno - 1 : node.end_lineno]).rstrip()
            external.append(chunk)

    body_lines = [line for i, line in enumerate(src_lines, 1) if i not in skip]
    body_text = "".join(body_lines).strip()
    return external, body_text


# ── Trader template (thin dispatch layer — not a strategy implementation) ──

_TRADER_CLASS = dedent("""\
    class Trader:
        def __init__(self):
            self.strategies = {}
            for symbol, cfg in PRODUCTS.items():
                strat_name = cfg["strategy"]
                params = {k: v for k, v in cfg.items() if k != "strategy"}
                cls = STRATEGY_CLASSES[strat_name]
                self.strategies[symbol] = cls(product=symbol, params=params)

        def bid(self) -> int:
            return 15

        def run(self, state: TradingState):
            saved = load_state(state.traderData)
            product_memories = saved.setdefault("products", {})
            result = {}
            total_conversions = 0
            for product, strategy in self.strategies.items():
                if product not in state.order_depths:
                    continue
                memory = product_memories.setdefault(product, {})
                orders, conversions = strategy.on_tick(state, memory)
                result[product] = orders
                total_conversions += conversions
            saved["last_timestamp"] = state.timestamp
            return result, total_conversions, dump_state(saved)
""")


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Export a single-file Prosperity submission")
    valid_members = sorted(MEMBER_OVERRIDES.keys())
    parser.add_argument("--member", default="champion", choices=valid_members)
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--output", default=None, help="Output file path")
    args = parser.parse_args()

    config = get_round_config(args.round, args.member)

    # Determine which strategy modules to inline.
    needed: set[str] = {pc.strategy for pc in config.values()}
    unknown = needed - set(STRATEGY_REGISTRY)
    if unknown:
        print(f"ERROR: strategies not in STRATEGY_REGISTRY: {sorted(unknown)}", file=sys.stderr)
        print(f"Add them to STRATEGY_REGISTRY in {__file__}", file=sys.stderr)
        return 1

    # Ordered list: core first, then one file per needed strategy (sorted for determinism).
    module_files = list(CORE_MODULES) + [STRATEGY_REGISTRY[n][0] for n in sorted(needed)]

    # Inline each module, collecting external imports along the way.
    all_ext_imports: list[str] = []
    seen_imports: set[str] = set()
    body_sections: list[str] = []

    for rel_path in module_files:
        source = (ROOT / rel_path).read_text(encoding="utf-8")
        ext_imports, body = _extract(source)

        for imp in ext_imports:
            if imp not in seen_imports:
                seen_imports.add(imp)
                all_ext_imports.append(imp)

        if body:
            rule = "─" * max(2, 78 - len(rel_path))
            body_sections.append(f"# ── {rel_path} {rule}\n\n{body}")

    # Embed config as a plain dict.
    products: dict = {}
    for symbol, pc in config.items():
        products[symbol] = {"strategy": pc.strategy, "position_limit": pc.position_limit, **pc.params}

    # Strategy class dispatch (only needed strategies).
    strat_entries = ", ".join(
        f'"{n}": {STRATEGY_REGISTRY[n][1]}' for n in sorted(needed)
    )
    strat_classes_line = f"STRATEGY_CLASSES = {{{strat_entries}}}"

    # Assemble output file.
    # `from __future__ import annotations` must be the very first statement.
    parts = [
        "from __future__ import annotations",
        "",
        "\n".join(sorted(all_ext_imports)),
        "",
        "\n\n\n".join(body_sections),
        "",
        "# ── Config " + "─" * 68,
        "",
        f"PRODUCTS = {pformat(products, width=100)}",
        "",
        strat_classes_line,
        "",
        "# ── Trader " + "─" * 68,
        "",
        _TRADER_CLASS,
    ]
    output = "\n".join(parts)

    output_path = Path(
        args.output or f"artifacts/submissions/{args.member}_round{args.round}_submission.py"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    print(f"Wrote {output_path} ({len(output):,} bytes)")
    print(f"Inlined : {', '.join(module_files)}")
    print(f"Strategies: {', '.join(sorted(needed))}")

    # Write the submissions/ wrapper so the backtester can import it directly.
    wrapper_path = ROOT / "submissions" / f"{args.member}.py"
    wrapper = dedent(f'''\
        """Backtester entrypoint — {args.member}."""

        from prosperity.strategies.trader import CURRENT_ROUND
        from prosperity.config import get_round_config
        from prosperity.persistence import dump_state, load_state
        from prosperity.strategies import build_strategy
        from prosperity.strategies.base import BaseStrategy

        from datamodel import Order, TradingState
        from typing import Dict, List


        class Trader:
            def __init__(self):
                config = get_round_config(CURRENT_ROUND, "{args.member}")
                self.strategies: Dict[str, BaseStrategy] = {{}}
                for symbol, pc in config.items():
                    merged = {{"position_limit": pc.position_limit, **pc.params}}
                    self.strategies[symbol] = build_strategy(pc.strategy, symbol, merged)

            def bid(self) -> int:
                return 15

            def run(self, state: TradingState):
                saved = load_state(state.traderData)
                mems = saved.setdefault("products", {{}})
                result: Dict[str, List[Order]] = {{}}
                features: Dict[str, Dict[str, float]] = {{}}
                convs = 0
                for product, strat in self.strategies.items():
                    if product not in state.order_depths:
                        continue
                    mem = mems.setdefault(product, {{}})
                    orders, c = strat.on_tick(state, mem)
                    result[product] = orders
                    convs += c
                    fp = strat.feature_prices(mem)
                    if fp:
                        features[product] = fp
                saved["last_timestamp"] = state.timestamp
                return result, convs, dump_state(saved), features
        ''')
    wrapper_path.write_text(wrapper, encoding="utf-8")
    print(f"Wrote {wrapper_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
