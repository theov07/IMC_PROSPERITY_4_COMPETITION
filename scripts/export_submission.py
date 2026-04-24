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
import contextlib
import importlib.util
import io
import sys
import time
import traceback
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
    "naive_tight_mm":     ("prosperity/strategies/round_1/naive_tight_mm.py",     "NaiveTightMarketMakerStrategy"),
    "naive_tight_mm_v2":  ("prosperity/strategies/naive_tight_mm_v2.py",  "NaiveTightMarketMakerV2Strategy"),
    "naive_tight_mm_v3":  ("prosperity/strategies/naive_tight_mm_v3.py",  "NaiveTightMarketMakerV3Strategy"),
    "naive_tight_mm_v4":  ("prosperity/strategies/naive_tight_mm_v4.py",  "NaiveTightMarketMakerV4Strategy"),
    "naive_tight_mm_v5":  ("prosperity/strategies/naive_tight_mm_v5.py",  "NaiveTightMarketMakerV5Strategy"),
    "naive_tight_mm_v6":  ("prosperity/strategies/naive_tight_mm_v6.py",  "NaiveTightMarketMakerV6Strategy"),
    "naive_tight_mm_v7":  ("prosperity/strategies/naive_tight_mm_v7.py",  "NaiveTightMarketMakerV7Strategy"),
    "naive_tight_mm_v8":  ("prosperity/strategies/naive_tight_mm_v8.py",  "NaiveTightMarketMakerV8Strategy"),
    "naive_tight_mm_v9":  ("prosperity/strategies/naive_tight_mm_v9.py",  "NaiveTightMarketMakerV9Strategy"),
    "round1_regression_top_book": ("prosperity/strategies/round_1/regression_top_book.py", "Round1RegressionTopBookStrategy"),
    "round1_regression_mm_v3": ("prosperity/strategies/round_1/regression_mm_v3.py", "Round1RegressionMMV3Strategy"),
    "round1_regression_mm_v4": ("prosperity/strategies/round_1/regression_mm_v4.py", "Round1RegressionMMV4Strategy"),
    "round1_regression_mm_v5": ("prosperity/strategies/round_1/regression_mm_v5.py", "Round1RegressionMMV5Strategy"),
    "leo_fusion_a": ("prosperity/strategies/round_1/leo_fusion_a.py", "LeoFusionAStrategy"),
    "leo_fusion_b": ("prosperity/strategies/round_1/leo_fusion_b.py", "LeoFusionBStrategy"),
    "leo_fusion_b_v3": ("prosperity/strategies/round_1/leo_fusion_b_v3.py", "LeoFusionBV3Strategy"),
    "leo_fusion_b_v8": ("prosperity/strategies/round_1/leo_fusion_b_v8.py", "LeoFusionBV8Strategy"),
    "leo_fusion_b_v10": ("prosperity/strategies/round_1/leo_fusion_b_v10.py", "LeoFusionBV10Strategy"),
    "leo_fusion_b_gap": ("prosperity/strategies/round_1/leo_fusion_b_gap.py", "LeoFusionBGapStrategy"),
    "leo_fusion_b_scout": ("prosperity/strategies/round_1/leo_fusion_b_scout.py", "LeoFusionBScoutStrategy"),
    "osmium_mr_artifact": ("prosperity/strategies/round_1/osmium_mr_artifact.py", "OsmiumMeanRevStrategy"),
    "osmium_mr_v2": ("prosperity/strategies/round_1/osmium_mr_v2.py", "OsmiumMeanRevV2Strategy"),
    "leo_fusion_c": ("prosperity/strategies/round_1/leo_fusion_c.py", "LeoFusionCStrategy"),
    "leo_fusion_d": ("prosperity/strategies/round_1/leo_fusion_d.py", "LeoFusionDStrategy"),
    "naive_tight_mm_v10": ("prosperity/strategies/naive_tight_mm_v10.py", "NaiveTightMarketMakerV10Strategy"),
    "naive_tight_mm_v11": ("prosperity/strategies/naive_tight_mm_v11.py", "NaiveTightMarketMakerV11Strategy"),
    "naive_tight_mm_v12": ("prosperity/strategies/naive_tight_mm_v12.py", "NaiveTightMarketMakerV12Strategy"),
    "naive_tight_mm_v14": ("prosperity/strategies/naive_tight_mm_v14.py", "NaiveTightMarketMakerV14Strategy"),
    "naive_tight_mm_v15": ("prosperity/strategies/naive_tight_mm_v15.py", "NaiveTightMarketMakerV15Strategy"),
    "naive_tight_mm_v16": ("prosperity/strategies/naive_tight_mm_v16.py", "NaiveTightMarketMakerV16Strategy"),
    "naive_tight_mm_v17": ("prosperity/strategies/naive_tight_mm_v17.py", "NaiveTightMarketMakerV17Strategy"),
    "naive_tight_mm_v23": ("prosperity/strategies/naive_tight_mm_v23.py", "NaiveTightMarketMakerV23Strategy"),
    "naive_tight_mm_v24": ("prosperity/strategies/naive_tight_mm_v24.py", "NaiveTightMarketMakerV24Strategy"),
    "trend_carry_mm_v25": ("prosperity/strategies/naive_tight_mm_v25.py", "TrendCarryMMV25Strategy"),
    "trend_carry_mm_v26": ("prosperity/strategies/naive_tight_mm_v26.py", "TrendCarryMMV26Strategy"),
    "trend_carry_mm_v34": ("prosperity/strategies/naive_tight_mm_v34.py", "TrendCarryMMV34Strategy"),
    "trend_carry_mm_v37": ("prosperity/strategies/naive_tight_mm_v37.py", "TrendCarryMMV37Strategy"),
    "trend_carry_mm_v38": ("prosperity/strategies/naive_tight_mm_v38.py", "TrendCarryMMV38Strategy"),
    "trend_carry_mm_v41": ("prosperity/strategies/naive_tight_mm_v41.py", "TrendCarryMMV41Strategy"),
    "trend_biased_mm_v18": ("prosperity/strategies/naive_tight_mm_v18.py", "TrendBiasedMMV18Strategy"),
    "book_following_trend_mm_v19": ("prosperity/strategies/naive_tight_mm_v19.py", "BookFollowingTrendMMV19Strategy"),
    "book_following_trend_mm_v20": ("prosperity/strategies/naive_tight_mm_v20.py", "BookFollowingTrendMMV20Strategy"),
    "book_following_trend_mm_v21": ("prosperity/strategies/naive_tight_mm_v21.py", "BookFollowingTrendMMV21Strategy"),
    "avellaneda_stoikov": ("prosperity/strategies/avellaneda_stoikov.py", "AvellanedaStoikovStrategy"),
    "stat_arb":           ("prosperity/strategies/stat_arb.py",           "StatArbStrategy"),
    "black_scholes":      ("prosperity/strategies/black_scholes.py",      "BlackScholesStrategy"),
    "conversion_arb":     ("prosperity/strategies/conversion_arb.py",     "ConversionArbStrategy"),
    "signal_trader":      ("prosperity/strategies/signal_trader.py",      "SignalTraderStrategy"),
    "mm_first":           ("prosperity/strategies/metal_winner/mm_first.py",           "MMFirstStrategy"),
    "mm_first_v2":        ("prosperity/strategies/metal_winner/mm_first_v2.py",        "MMFirstStrategy"),
    "mm_first_v3":        ("prosperity/strategies/round_2/tibo/mm_first_v3.py",        "MMFirstStrategy"),
    "mm_first_v4_combo":  ("prosperity/strategies/round_2/leo/mm_first_v4_combo.py",   "MMFirstV4ComboStrategy"),
    "theo_best_clean_generalized":    ("prosperity/strategies/round_2/theo/theo_best_clean_generalized.py", "TheoBestCleanGeneralizedStrategy"),
    "theo_best_clean_generalized_v2": ("prosperity/strategies/round_2/theo/theo_best_clean_generalized.py", "TheoBestCleanGeneralizedV2Strategy"),
    "theo_best_clean_generalized_v3": ("prosperity/strategies/round_2/theo/theo_best_clean_generalized.py", "TheoBestCleanGeneralizedV3Strategy"),
    "theo_best_clean_generalized_v4": ("prosperity/strategies/round_2/theo/theo_best_clean_generalized.py", "TheoBestCleanGeneralizedV4Strategy"),
    "mean_reversion":     ("prosperity/strategies/round_1/mean_reversion.py",          "MeanReversionStrategy"),
    "zscore":             ("prosperity/strategies/metal_winner/zscore.py",             "ZScoreStrategy"),
    "buy_and_hold":       ("prosperity/strategies/base/buy_and_hold.py",       "BuyAndHoldStrategy"),
    "trend_carry_window": ("prosperity/strategies/round_1/trend_carry_window.py", "TrendCarryWindowStrategy"),
    "trend_carry_window_v2": ("prosperity/strategies/trend_carry_window_v2.py", "TrendCarryWindowV2Strategy"),
    "osmium_mr":          ("prosperity/strategies/osmium_mr.py",          "OsmiumMeanRevStrategy"),
    "theo_best_generalized": ("prosperity/strategies/round_1/theo_best_generalized.py", "TheoGeneralizedStrategy"),
    "theo_root_ask_gap_generalised": (
        "prosperity/strategies/round_2/theo/theo_root_ask_gap_generalised.py",
        "TheoRootAskGapGeneralisedStrategy",
    ),
    "osmium_modulaire":   ("prosperity/strategies/round_2/leo/osmium_modulaire.py", "OsmiumModulaireStrategy"),
    "pepper_modulaire":   ("prosperity/strategies/round_2/leo/pepper_modulaire.py", "PepperModulaireStrategy"),
    "ask_exploit_modulaire": ("prosperity/strategies/round_2/theo/ask_exploit_modulaire.py", "AskExploitModulaireStrategy"),
    "aco_mm_modulaire":   ("prosperity/strategies/round_2/leo/aco_mm_modulaire.py", "AcoMMModulaireStrategy"),
    # ── Round 3 ──
    "option_mm_bs":       ("prosperity/strategies/round_3/option_mm_bs.py", "OptionMMBSStrategy"),
    "theo_r3_vol_arb_v1": ("prosperity/strategies/round_3/theo/theo_r3_vol_arb_v1.py", "TheoR3VolArbV1Strategy"),
}

# Core modules always inlined (order matters — later modules depend on earlier ones).
CORE_MODULES = [
    "prosperity/market.py",
    "prosperity/persistence.py",
    "prosperity/strategies/base/base.py",
]

# Optional per-strategy file deps (paths inlined BEFORE the strategy file).
STRATEGY_FILE_DEPS: dict[str, list[str]] = {
    "option_mm_bs": [
        "prosperity/options/time.py",
        "prosperity/options/black_scholes.py",
        "prosperity/options/implied_vol.py",
        "prosperity/options/smile.py",
    ],
    "theo_r3_vol_arb_v1": [
        "prosperity/options/time.py",
        "prosperity/options/black_scholes.py",
        "prosperity/options/implied_vol.py",
        "prosperity/options/smile.py",
    ],
}

# Extra strategy-module dependencies (inlined before the strategy file that needs them).
STRATEGY_DEPS: dict[str, list[str]] = {
    "leo_fusion_a": ["round1_regression_mm_v5"],
    "leo_fusion_b": ["round1_regression_mm_v5"],
    "leo_fusion_b_v3": ["round1_regression_mm_v5"],
    "leo_fusion_b_v8": ["round1_regression_mm_v5"],
    "leo_fusion_b_v10": ["round1_regression_mm_v5"],
    "leo_fusion_b_gap": ["round1_regression_mm_v5", "leo_fusion_b"],
    "leo_fusion_b_scout": ["round1_regression_mm_v5", "leo_fusion_b", "leo_fusion_b_gap"],
    "leo_fusion_c": ["round1_regression_mm_v5"],
    "leo_fusion_d": ["round1_regression_mm_v5"],
    "osmium_mr": ["naive_tight_mm_v10"],
    "osmium_mr_v2": ["naive_tight_mm_v10", "osmium_mr_artifact"],
    "theo_best_generalized": ["round1_regression_mm_v5"],
    "pepper_modulaire":      ["round1_regression_mm_v5"],
    "ask_exploit_modulaire": ["round1_regression_mm_v5"],
}

# Params useful for local analysis/backtests but pointless in the live upload.
EXPORT_PARAM_DROP = {
    "historical_tte_by_day",
}


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

        # Keep external imports for the top-level block (skip IMC-forbidden ones).
        if not is_internal and not is_future:
            chunk = "".join(src_lines[node.lineno - 1 : node.end_lineno]).rstrip()
            if chunk not in {"import os"}:
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
            shared = {"timestamp": state.timestamp}
            result = {}
            total_conversions = 0
            for product, strategy in self.strategies.items():
                if product not in state.order_depths:
                    continue
                memory = product_memories.setdefault(product, {})
                memory["_shared"] = shared
                orders, conversions = strategy.on_tick(state, memory)
                result[product] = orders
                total_conversions += conversions
            for memory in product_memories.values():
                if isinstance(memory, dict):
                    memory.pop("_shared", None)
            saved["last_timestamp"] = state.timestamp
            return result, total_conversions, dump_state(saved)
""")


# ── Validation ────────────────────────────────────────────────────────────

# Imports banned by the IMC sandbox
_BANNED_IMPORTS = {"os", "sys", "subprocess", "socket", "pathlib", "shutil",
                   "importlib", "ctypes", "multiprocessing", "threading"}

# Hard time limit per tick (ms) — IMC cuts at 900ms, we warn well before
_WARN_MS = 100
_HARD_MS = 900
_BENCH_TICKS = 200  # number of ticks used for the runtime benchmark


def _build_test_state(products: dict, timestamp: int = 0, trader_data: str = ""):
    """Build a minimal but realistic TradingState for validation."""
    from datamodel import Listing, OrderDepth, TradingState

    order_depths = {}
    listings = {}
    for symbol in products:
        od = OrderDepth()
        od.buy_orders  = {9992: 15, 9990: 30}  if "EMERALD" in symbol else {5000: 10, 4999: 20}
        od.sell_orders = {10008: -15, 10010: -30} if "EMERALD" in symbol else {5013: -10, 5014: -20}
        order_depths[symbol] = od
        listings[symbol] = Listing(symbol, symbol, "XIRECS")

    return TradingState(
        traderData=trader_data,
        timestamp=timestamp,
        listings=listings,
        order_depths=order_depths,
        own_trades={},
        market_trades={},
        position={},
        observations=None,
    )


def _validate(output_path: Path, products: dict) -> bool:
    """Run all pre-flight checks on the exported file. Returns True if all pass."""
    source = output_path.read_text(encoding="utf-8")
    ok = True

    print("\n-- Validation --------------------------------------------------")

    # 1. Syntax check
    try:
        ast.parse(source)
        print("  [OK] Syntax valid")
    except SyntaxError as e:
        print(f"  [FAIL] Syntax error: {e}")
        return False  # no point continuing

    # 2. Banned imports
    tree = ast.parse(source)
    banned_found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _BANNED_IMPORTS:
                    banned_found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in _BANNED_IMPORTS:
                    banned_found.append(node.module)
    if banned_found:
        print(f"  [FAIL] Banned imports found: {banned_found}")
        ok = False
    else:
        print("  [OK] No banned imports")

    # 3. Load module and instantiate Trader
    try:
        mod_name = f"_submission_validate_{output_path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, output_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        trader = mod.Trader()
        print("  [OK] Trader.__init__() succeeded")
    except Exception:
        print("  [FAIL] Trader.__init__() crashed:")
        traceback.print_exc(limit=5)
        return False

    # 4. Functional test — one tick (stdout suppressed: strategies print trace JSON)
    try:
        state = _build_test_state(products, timestamp=0)
        with contextlib.redirect_stdout(io.StringIO()):
            result = trader.run(state)
        if not isinstance(result, tuple) or len(result) < 3:
            raise ValueError(f"run() must return (orders, conversions, traderData), got: {result!r}")
        orders_dict, _, _ = result[0], result[1], result[2]
        total_orders = sum(len(v) for v in orders_dict.values())
        print(f"  [OK] run() tick 0: {total_orders} order(s) across {list(orders_dict.keys())}")
    except Exception:
        print("  [FAIL] run() crashed on tick 0:")
        traceback.print_exc(limit=5)
        return False

    # 5. Runtime benchmark over _BENCH_TICKS ticks (stdout suppressed)
    try:
        trader_data = result[2]
        durations = []
        for i in range(_BENCH_TICKS):
            state = _build_test_state(products, timestamp=i * 100, trader_data=trader_data)
            t0 = time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):
                out = trader.run(state)
            durations.append((time.perf_counter() - t0) * 1000)
            trader_data = out[2]

        avg_ms  = sum(durations) / len(durations)
        max_ms  = max(durations)
        p99_ms  = sorted(durations)[int(len(durations) * 0.99)]

        status = "OK" if avg_ms < _WARN_MS else ("WARN" if avg_ms < _HARD_MS else "FAIL")
        print(f"  [{status}] Runtime over {_BENCH_TICKS} ticks — "
              f"avg={avg_ms:.2f}ms  p99={p99_ms:.2f}ms  max={max_ms:.2f}ms  "
              f"(limit={_HARD_MS}ms)")
        if status == "FAIL":
            ok = False
    except Exception:
        print("  [FAIL] Runtime benchmark crashed:")
        traceback.print_exc(limit=5)
        ok = False

    print("----------------------------------------------------------------")
    print(f"  {'ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED — review before uploading'}")
    print("----------------------------------------------------------------\n")
    return ok


# ── Main ----------------------------------------------------------------───

def main() -> int:
    parser = argparse.ArgumentParser(description="Export a single-file Prosperity submission")
    valid_members = sorted(MEMBER_OVERRIDES.keys())
    parser.add_argument("--member", default="champion", choices=valid_members)
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument(
        "--product",
        nargs="*",
        metavar="SYMBOL",
        help="Only include these product(s), e.g. --product ASH_COATED_OSMIUM",
    )
    args = parser.parse_args()

    config = get_round_config(args.round, args.member)
    if args.product:
        unknown_products = set(args.product) - set(config)
        if unknown_products:
            print(f"ERROR: unknown product(s): {sorted(unknown_products)}", file=sys.stderr)
            print(f"Available: {sorted(config.keys())}", file=sys.stderr)
            return 1
        config = {k: v for k, v in config.items() if k in args.product}

    # Determine which strategy modules to inline.
    needed: set[str] = {pc.strategy for pc in config.values()}
    unknown = needed - set(STRATEGY_REGISTRY)
    if unknown:
        print(f"ERROR: strategies not in STRATEGY_REGISTRY: {sorted(unknown)}", file=sys.stderr)
        print(f"Add them to STRATEGY_REGISTRY in {__file__}", file=sys.stderr)
        return 1

    # Resolve dependencies: prepend each needed strategy's deps.
    resolved: list[str] = []
    for n in sorted(needed):
        for dep in STRATEGY_DEPS.get(n, []):
            if dep not in resolved:
                resolved.append(dep)
        if n not in resolved:
            resolved.append(n)
    unknown_dep = set(resolved) - set(STRATEGY_REGISTRY)
    if unknown_dep:
        print(f"ERROR: STRATEGY_DEPS references unknown: {sorted(unknown_dep)}", file=sys.stderr)
        return 1

    # Ordered list: core first, then per-strategy file deps, then the strategy file itself.
    module_files = list(CORE_MODULES)
    for n in resolved:
        for file_dep in STRATEGY_FILE_DEPS.get(n, []):
            if file_dep not in module_files:
                module_files.append(file_dep)
        module_files.append(STRATEGY_REGISTRY[n][0])

    # Inline each module, collecting external imports along the way.
    all_ext_imports: list[str] = []
    seen_imports: set[str] = set()
    body_sections: list[str] = []

    for rel_path in module_files:
        source = (ROOT / rel_path).read_text(encoding="utf-8")
        ext_imports, body = _extract(source)
        # Replace env-var checks with False: os never imported in the submission,
        # and live IMC never sets this var anyway (the if-blocks still execute).
        body = body.replace('os.environ.get("INTERNAL_BACKTEST")', "False")

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
        params = {k: v for k, v in pc.params.items() if k not in EXPORT_PARAM_DROP}
        if "timestamp_units_per_day" in params:
            params.pop("ticks_per_day", None)
        products[symbol] = {"strategy": pc.strategy, "position_limit": pc.position_limit, **params}

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

    if args.output:
        output_path = Path(args.output)
    else:
        team = next((t for t in ("leo", "theo", "tibo") if t in args.member.lower()), None)
        round_dir = f"round_{args.round}"
        if team is not None:
            default_output = f"artifacts/submissions/{round_dir}/{team}/{args.member}_round{args.round}_submission.py"
        else:
            default_output = f"artifacts/submissions/{round_dir}/{args.member}_round{args.round}_submission.py"
        output_path = Path(default_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    print(f"Wrote {output_path} ({len(output):,} bytes)")
    print(f"Inlined : {', '.join(module_files)}")
    print(f"Strategies: {', '.join(sorted(needed))}")

    _validate(output_path, products)

    # Write the submissions/ wrapper so the backtester can import it directly.
    wrapper_path = ROOT / "submissions" / f"{args.member}.py"
    wrapper = dedent(f'''\
        """Backtester entrypoint — {args.member}."""

        from prosperity.config import get_round_config
        from prosperity.persistence import dump_state, load_state
        from prosperity.strategies import build_strategy
        from prosperity.strategies.base import BaseStrategy

        from datamodel import Order, TradingState
        from typing import Dict, List


        class Trader:
            def __init__(self):
                config = get_round_config({args.round}, "{args.member}")
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
