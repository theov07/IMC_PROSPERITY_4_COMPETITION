"""Ablation study for tibo_velvet_v25 — feature importance per product.

Runs the full 3-day backtest for each ablation variant (one feature disabled
at a time). Collects all available metrics per product per day and saves them
to a JSON file for future visualization.

Usage:
    python scripts/ablation_v25.py
    python scripts/ablation_v25.py --days 1   # quick single-day run
    python scripts/ablation_v25.py --out artifacts/analysis/round_3/ablation_v25.json
"""
from __future__ import annotations

import argparse
import copy
import importlib
import json
import sys
import tempfile
import textwrap
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prosperity.config import MEMBER_OVERRIDES, ProductConfig, get_round_config
from prosperity.tooling.backtest import (
    BacktestEngine,
    TradeMatchingMode,
    _chain_equity_curves,
    aggregate_day_summaries,
)

# ── Constants ─────────────────────────────────────────────────────────────────
ROUND    = 3
MODE     = TradeMatchingMode("realistic")
DATA_DIR = str(ROOT / "data")

# ── Feature ablations ─────────────────────────────────────────────────────────
# Each ablation is a dict mapping product symbol → param overrides.
# Empty dict = baseline (no changes).
ABLATIONS: Dict[str, Dict[str, Dict[str, Any]]] = {
    # ── Baseline ──────────────────────────────────────────────────────────────
    "baseline": {},

    # ── VEVOptionMMV25 features (VEV_4000 / 5200 / 5300 / 5400) ─────────────

    # Disable z-score ask adaptation → pure passive wide ask on all 4 strikes
    "no_zscore_ask_5200_5300_5400": {
        "VEV_5200": {"zscore_exec_mode": "none"},
        "VEV_5300": {"zscore_exec_mode": "none"},
        "VEV_5400": {"zscore_exec_mode": "none"},
    },

    # Symmetric ask on 5200/5300 (ask_offset=1 like VEV_4000) — test whether
    # holding a wide ask (rarely sells) adds value vs freely selling both ways
    "symmetric_ask_5200_5300": {
        "VEV_5200": {"ask_offset_neutral": 1, "ask_offset_sell": 1},
        "VEV_5300": {"ask_offset_neutral": 1, "ask_offset_sell": 1},
    },

    # Allow crossing on VEV_5400 (remove prevent_crossing guard)
    "allow_crossing_5400": {
        "VEV_5400": {"prevent_crossing": False},
    },

    # ── GammaScalpV25 features (VEV_4500 / 5000 / 5100) ─────────────────────

    # Disable active taker — passive bid only, no "take when ask ≤ BS fair"
    "passive_only_4500_5000_5100": {
        "VEV_4500": {"edge_ticks": -999.0},
        "VEV_5000": {"edge_ticks": -999.0},
        "VEV_5100": {"edge_ticks": -999.0},
    },

    # Disable z-score skip gate — always accumulate, even when VELVETFRUIT is expensive
    "always_accumulate_4500_5000_5100": {
        "VEV_4500": {"skip_when_expensive": False},
        "VEV_5000": {"skip_when_expensive": False},
        "VEV_5100": {"skip_when_expensive": False},
    },

    # Enable "boost when cheap" — increase entry size when VELVETFRUIT z < -threshold
    "boost_when_cheap_4500_5000_5100": {
        "VEV_4500": {"boost_when_cheap": True, "entry_size_boost": 2.0},
        "VEV_5000": {"boost_when_cheap": True, "entry_size_boost": 2.0},
        "VEV_5100": {"boost_when_cheap": True, "entry_size_boost": 2.0},
    },

    # ── VelvetMMV25 features (VELVETFRUIT_EXTRACT) ────────────────────────────

    # Disable delta hedge — VELVETFRUIT quotes ignore VEV option delta exposure
    "no_delta_hedge": {
        "VELVETFRUIT_EXTRACT": {"use_delta_hedge": False},
    },
}


# ── Engine helpers ────────────────────────────────────────────────────────────

def _max_drawdown_full(equity_curve: list) -> tuple[float, float]:
    """Return (max_abs_drawdown, peak_at_max_drawdown)."""
    peak = None
    max_dd = 0.0
    peak_at_dd = 0.0
    for _, value in equity_curve:
        peak = value if peak is None else max(peak, value)
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
            peak_at_dd = peak
    return max_dd, peak_at_dd


def _build_ablation_config(base_member: str, overrides: Dict[str, Dict[str, Any]]) -> Dict:
    """Return an override dict (product → ProductConfig | None) suitable for
    MEMBER_OVERRIDES registration.  None entries explicitly exclude products
    that are in the ROUND_3 base but not in the v25 config.
    """
    from prosperity.config import ROUNDS
    resolved = copy.deepcopy(get_round_config(ROUND, base_member))

    # Apply param overrides
    for symbol, param_patch in overrides.items():
        if symbol not in resolved:
            continue
        pc = resolved[symbol]
        new_params = {**pc.params, **param_patch}
        resolved[symbol] = ProductConfig(
            symbol=pc.symbol,
            strategy=pc.strategy,
            position_limit=pc.position_limit,
            params=new_params,
        )

    # Any product in the base round that is NOT in the resolved v25 config
    # must be set to None so the ROUND_3 default doesn't leak through.
    base_products = set(ROUNDS.get(ROUND, {}).keys())
    for symbol in base_products:
        if symbol not in resolved:
            resolved[symbol] = None

    return resolved


def _run_ablation(
    ablation_name: str,
    cfg: Dict,
    days: List[int],
) -> Dict[str, Any]:
    """Run backtest for one ablation config. Returns structured metrics dict."""

    # Register a unique member name so the submission wrapper can find the config.
    temp_member = f"_ablation_{ablation_name}"
    MEMBER_OVERRIDES[temp_member] = {ROUND: cfg}

    # Write a minimal submission wrapper to a temp file.
    wrapper_src = textwrap.dedent(f"""\
        from prosperity.config import get_round_config
        from prosperity.persistence import dump_state, load_state
        from prosperity.strategies import build_strategy
        from prosperity.strategies.base import BaseStrategy
        from datamodel import Order, TradingState
        from typing import Dict, List

        class Trader:
            def __init__(self):
                config = get_round_config({ROUND}, "{temp_member}")
                self.strategies = {{}}
                for symbol, pc in config.items():
                    merged = {{"position_limit": pc.position_limit, **pc.params}}
                    self.strategies[symbol] = build_strategy(pc.strategy, symbol, merged)

            def run(self, state: TradingState):
                saved = load_state(state.traderData)
                mems = saved.setdefault("products", {{}})
                shared = {{"timestamp": state.timestamp, "vev_total_delta": 0.0}}
                result: Dict[str, List[Order]] = {{}}
                convs = 0
                for product, strat in self.strategies.items():
                    if product not in state.order_depths:
                        continue
                    mem = mems.setdefault(product, {{}})
                    mem["_shared"] = shared
                    orders, c = strat.on_tick(state, mem)
                    result[product] = orders
                    convs += c
                for mem in mems.values():
                    if isinstance(mem, dict):
                        mem.pop("_shared", None)
                saved["last_timestamp"] = state.timestamp
                return result, convs, dump_state(saved), {{}}
    """)

    tmp_path = ROOT / "submissions" / f"{temp_member}.py"
    tmp_path.write_text(wrapper_src, encoding="utf-8")

    try:
        # Ensure the module is freshly loaded (not cached from a prior ablation).
        mod_name = f"submissions.{temp_member}"
        for k in list(sys.modules):
            if temp_member in k:
                del sys.modules[k]

        engine = BacktestEngine(DATA_DIR, temp_member, round_num=ROUND)
        day_summaries = [engine.run_day(d, mode=MODE) for d in days]
        aggregate = aggregate_day_summaries(day_summaries)

        # ── Per-product per-day metrics ────────────────────────────────────
        product_day_metrics: Dict[str, List[Dict]] = {}
        for s in day_summaries:
            for symbol, ps in s.product_summaries.items():
                if symbol not in product_day_metrics:
                    product_day_metrics[symbol] = []
                product_day_metrics[symbol].append({
                    "day":           s.day,
                    "pnl":           ps.pnl,
                    "trades":        ps.trades,
                    "traded_volume": ps.traded_volume,
                    "max_abs_pos":   ps.max_abs_position,
                    "end_pos":       ps.ending_position,
                    "make":          ps.robustness.passive_qty,
                    "take":          ps.robustness.aggressive_qty,
                    "avg_inv_ratio": ps.robustness.avg_abs_position_ratio,
                    "near_limit_ticks": ps.robustness.near_limit_tick_count,
                    "fill_efficiency": (
                        ps.robustness.passive_qty / ps.robustness.submitted_volume
                        if ps.robustness.submitted_volume > 0 else None
                    ),
                })

        # ── Per-day total metrics ──────────────────────────────────────────
        day_totals = []
        for s in day_summaries:
            dd_abs, peak = _max_drawdown_full(s.equity_curve)
            dd_pct = (dd_abs / peak * 100) if peak > 0 else None
            day_totals.append({
                "day":        s.day,
                "total_pnl":  s.pnl,
                "drawdown_abs": dd_abs,
                "drawdown_pct": dd_pct,
                "peak_equity":  peak,
            })

        # ── Overall totals ─────────────────────────────────────────────────
        chained = _chain_equity_curves(day_summaries)
        total_dd_abs, total_peak = _max_drawdown_full(chained)
        total_dd_pct = (total_dd_abs / total_peak * 100) if total_peak > 0 else None

        product_totals = {}
        for symbol, day_list in product_day_metrics.items():
            product_totals[symbol] = {
                "total_pnl":   sum(d["pnl"] for d in day_list),
                "total_trades": sum(d["trades"] for d in day_list),
                "total_volume": sum(d["traded_volume"] for d in day_list),
                "total_make":   sum(d["make"] for d in day_list),
                "total_take":   sum(d["take"] for d in day_list),
            }

        return {
            "ablation":       ablation_name,
            "total_pnl":      aggregate["total_pnl"],
            "drawdown_abs":   total_dd_abs,
            "drawdown_pct":   total_dd_pct,
            "peak_equity":    total_peak,
            "day_totals":     day_totals,
            "product_totals": product_totals,
            "product_day_metrics": product_day_metrics,
        }

    finally:
        tmp_path.unlink(missing_ok=True)
        MEMBER_OVERRIDES.pop(temp_member, None)
        for k in list(sys.modules):
            if temp_member in k:
                del sys.modules[k]


# ── Summary printing ──────────────────────────────────────────────────────────

PRODUCTS_ORDER = [
    "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400",
]

def _short(name: str) -> str:
    return (name.replace("VELVETFRUIT_EXTRACT", "VELVET")
                .replace("VEV_", "V")
                .replace("_", " "))


def _print_pnl_table(results: List[Dict]) -> None:
    """Print per-product total PnL for each ablation + delta vs baseline."""
    baseline = next(r for r in results if r["ablation"] == "baseline")

    # Header
    products = [p for p in PRODUCTS_ORDER
                if p in baseline.get("product_totals", {})]
    col_w = max(len(_short(p)) for p in products)
    abl_w = max(len(r["ablation"]) for r in results)

    header = f"{'Ablation':<{abl_w}}  {'Total':>9}  {'DD%':>6}" + "".join(
        f"  {_short(p):>{col_w}}" for p in products
    )
    print("\n" + "─" * len(header))
    print(header)
    print("─" * len(header))

    for r in results:
        base_total = baseline["total_pnl"]
        delta = r["total_pnl"] - base_total
        delta_str = (f"+{delta:,.0f}" if delta >= 0 else f"{delta:,.0f}") if r["ablation"] != "baseline" else "     —"
        dd_str = f"{r['drawdown_pct']:.1f}%" if r["drawdown_pct"] is not None else "  n/a"

        product_cols = ""
        for p in products:
            pt = r.get("product_totals", {}).get(p, {})
            pnl = pt.get("total_pnl", 0)
            base_pnl = baseline.get("product_totals", {}).get(p, {}).get("total_pnl", 0)
            d = pnl - base_pnl
            cell = f"{pnl:,.0f}" if r["ablation"] == "baseline" else f"{d:+,.0f}"
            product_cols += f"  {cell:>{col_w}}"

        print(f"{r['ablation']:<{abl_w}}  {r['total_pnl']:>9,.0f}  {dd_str:>6}  {delta_str:>8}{product_cols}")

    print("─" * len(header))
    print("  Δ columns show change vs baseline for each product.")
    print()


def _print_day_breakdown(results: List[Dict]) -> None:
    """Print per-day total PnL + drawdown for each ablation."""
    days = sorted({d["day"] for r in results for d in r["day_totals"]})
    abl_w = max(len(r["ablation"]) for r in results)

    header = f"{'Ablation':<{abl_w}}" + "".join(
        f"  D{d} PnL  D{d} DD%" for d in days
    ) + "  Total"
    print("─" * len(header))
    print(header)
    print("─" * len(header))

    for r in results:
        day_map = {d["day"]: d for d in r["day_totals"]}
        row = f"{r['ablation']:<{abl_w}}"
        for d in days:
            dm = day_map.get(d, {})
            pnl = dm.get("total_pnl", 0)
            ddp = dm.get("drawdown_pct")
            dd_str = f"{ddp:.0f}%" if ddp is not None else " n/a"
            row += f"  {pnl:>7,.0f}  {dd_str:>5}"
        row += f"  {r['total_pnl']:>9,.0f}"
        print(row)

    print("─" * len(header))
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ablation study for tibo_velvet_v25")
    parser.add_argument("--days", nargs="*", type=int, default=[0, 1, 2])
    parser.add_argument("--out", default="artifacts/analysis/round_3/v25_ablation.json")
    parser.add_argument("--ablations", nargs="*", default=None,
                        help="Subset of ablation names to run (default: all)")
    args = parser.parse_args()

    days = sorted(args.days)
    ablation_names = args.ablations or list(ABLATIONS.keys())
    if "baseline" not in ablation_names:
        ablation_names = ["baseline"] + ablation_names

    print(f"Running {len(ablation_names)} ablation(s) on days {days} ...")
    print()

    results = []
    for name in ablation_names:
        overrides = ABLATIONS[name]
        cfg = _build_ablation_config("tibo_velvet_v25", overrides)
        affected = list(overrides.keys()) or ["all products"]
        print(f"  [{name}] affects: {', '.join(affected)} ...")
        r = _run_ablation(name, cfg, days)
        results.append(r)
        print(f"    → total PnL: {r['total_pnl']:,.0f}  DD: {r['drawdown_pct']:.1f}%")

    print()
    print("═" * 80)
    print("  PnL TABLE  (absolute for baseline, delta Δ vs baseline for others)")
    print("═" * 80)
    _print_pnl_table(results)

    print("═" * 80)
    print("  PER-DAY BREAKDOWN")
    print("═" * 80)
    _print_day_breakdown(results)

    # Save full structured output for future visualization
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Full metrics saved to {out_path}")


if __name__ == "__main__":
    main()
