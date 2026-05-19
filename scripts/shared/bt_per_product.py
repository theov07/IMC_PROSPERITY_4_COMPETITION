"""Run a backtest per product — isolates each product's contribution to the strategy.

Usage:
    python scripts/shared/bt_per_product.py --strategy best_v2640_carry_morning --round 5 --days 4

For each active product in the strategy's config, runs a single-product backtest
and prints PnL per product. Useful for:
- Identifying which products contribute most/least
- Debugging stale signals (products that should fire but don't)
- A/B testing single overlays in isolation

Note: products that depend on a partner (pair_skip, basket_skip, pebbles_arb)
will return DEGRADED results when run alone since their partner's mids are
missing from `state.order_depths`. Use --keep-partners to include partners.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def get_active_products(member: str, round_num: int) -> dict:
    """Return {product: strategy_name} for active (non-None) products in member's config."""
    sys.path.insert(0, str(ROOT))
    from prosperity.config import get_round_config
    cfg = get_round_config(round_num, member)
    return {sym: pc.strategy for sym, pc in cfg.items() if pc is not None}


def get_pair_partner(member: str, round_num: int, product: str) -> str | None:
    """Return the partner symbol for pair_skip / pair_skip_lag / coint_mm products."""
    sys.path.insert(0, str(ROOT))
    from prosperity.config import get_round_config
    cfg = get_round_config(round_num, member)
    pc = cfg.get(product)
    if not pc:
        return None
    p = pc.params
    return p.get("partner") or p.get("partner_product")


def run_single_product_backtest(
    member: str, round_num: int, days: list, product: str,
    keep_partners: bool = False, exec_rule: str = "realistic",
) -> int | None:
    """Run BT for one product, return its total PnL or None on failure."""
    products = [product]
    if keep_partners:
        partner = get_pair_partner(member, round_num, product)
        if partner and partner not in products:
            products.append(partner)

    cmd = [
        sys.executable, "backtest.py",
        "--strategy", member,
        "--round", str(round_num),
        "--days", *[str(d) for d in days],
        "--match-trades", exec_rule,
        "--products", *products,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                             cwd=str(ROOT), env={"PYTHONIOENCODING": "utf-8", **__import__("os").environ})
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0:
        print(f"  ERROR for {product}: {out.stderr[:200]}", file=sys.stderr)
        return None
    # Parse TOTAL line
    import re
    for line in out.stdout.split("\n"):
        m = re.search(r"TOTAL\s+│\s*\d+ day\(s\)\s*│\s*([-,\d]+)\s*│", line)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


def main():
    parser = argparse.ArgumentParser(description="Per-product backtest diagnostics")
    parser.add_argument("--strategy", required=True, help="Member config (e.g. best_v2640_carry_morning)")
    parser.add_argument("--round", type=int, default=5)
    parser.add_argument("--days", nargs="*", default=["4"])
    parser.add_argument("--match-trades", default="realistic",
                        choices=["queue", "all", "worse", "none", "realistic"])
    parser.add_argument("--keep-partners", action="store_true",
                        help="Also include the pair_skip/coint partner in each per-product run "
                             "(so the strategy has its full signal). Default OFF for cleanest isolation.")
    parser.add_argument("--filter-strategy", default=None,
                        help="Only run on products using this strategy (e.g. pair_skip_mm)")
    args = parser.parse_args()

    products = get_active_products(args.strategy, args.round)
    if args.filter_strategy:
        products = {p: s for p, s in products.items() if s == args.filter_strategy}
    print(f"Running per-product BT on {len(products)} products...")
    print(f"keep_partners={args.keep_partners}, days={args.days}, match-trades={args.match_trades}")
    print()

    results = []
    for product in sorted(products.keys()):
        strat = products[product]
        partner = get_pair_partner(args.strategy, args.round, product)
        print(f"  {product:<35} ({strat})...", end="", flush=True)
        pnl = run_single_product_backtest(
            args.strategy, args.round, args.days, product,
            keep_partners=args.keep_partners, exec_rule=args.match_trades,
        )
        if pnl is None:
            print(" FAILED")
        else:
            print(f" PnL={pnl:>+10,}")
        results.append({"product": product, "strategy": strat, "partner": partner, "pnl": pnl})

    # Summary table
    print()
    print(f"=== PER-PRODUCT PnL (sorted desc) ===")
    print(f"{'Product':<35} {'Strategy':<25} {'Partner':<25} {'PnL':>10}")
    print("-" * 100)
    valid = sorted([r for r in results if r["pnl"] is not None], key=lambda r: -r["pnl"])
    for r in valid:
        partner_str = r["partner"] or "-"
        print(f"{r['product']:<35} {r['strategy']:<25} {partner_str:<25} {r['pnl']:>+10,}")
    failed = [r for r in results if r["pnl"] is None]
    for r in failed:
        partner_str = r["partner"] or "-"
        print(f"{r['product']:<35} {r['strategy']:<25} {partner_str:<25} {'FAILED':>10}")

    total = sum(r["pnl"] for r in results if r["pnl"] is not None)
    print("-" * 100)
    print(f"{'SUM (per-product, with possible signal degradation)':<87} {total:>+10,}")

    # Optional: write to CSV
    out_path = ROOT / "artifacts" / "r5_compare" / f"{args.strategy}_per_product_pnl.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("product,strategy,partner,pnl\n")
        for r in results:
            partner_str = r["partner"] or ""
            pnl_str = str(r["pnl"]) if r["pnl"] is not None else ""
            f.write(f"{r['product']},{r['strategy']},{partner_str},{pnl_str}\n")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
