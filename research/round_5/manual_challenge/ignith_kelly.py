"""Manual challenge — Ignith / Ashflow Alpha portfolio optimization.

Round 5 manual:
  - Budget = 1,000,000
  - 9 tradable goods (Ignith)
  - Fee per good: (volume_pct/100)^2 * budget = 100 * vol^2

Inputs needed: Ashflow Alpha news/views per good (we'll plug in when data arrives).
Goal: maximize expected_pnl - fees.

Math:
  expected_pnl = sum_i (alpha_i * vol_i)
  fees         = sum_i (vol_i / 100)^2 * 1e6
               = sum_i vol_i^2 * 100

  Optimization (no constraints): d/dvol_i [alpha_i*vol_i - 100*vol_i^2] = 0
                                  alpha_i - 200*vol_i = 0
                                  vol_i = alpha_i / 200

  But sum(vol_i) <= 100 (can't allocate >100% of budget).

This script:
  1. Computes optimal allocation given alpha vector
  2. Plots fee curve vs profit curve per good
  3. Outputs JSON-ready submission grid

Note: vol_i is the % of budget allocated to good i.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts" / "analysis" / "round_5"
OUT.mkdir(parents=True, exist_ok=True)


def optimal_unconstrained(alphas: dict) -> dict:
    """Optimal vol per good if no budget constraint: vol_i = alpha_i / 200."""
    return {k: max(0.0, v / 200.0) for k, v in alphas.items()}


def optimal_with_budget(alphas: dict, max_budget_pct: float = 100.0) -> dict:
    """Constrained optimization: max sum(alpha_i * vol_i) - 100 * vol_i^2
    subject to sum(vol_i) <= max_budget_pct.

    Lagrangian: L = sum(alpha_i*vol_i - 100*vol_i^2) - lambda*(sum(vol_i) - max)
    KKT:        alpha_i - 200*vol_i - lambda = 0  =>  vol_i = (alpha_i - lambda) / 200
                Also: vol_i >= 0, sum(vol_i) <= max
    Iterate: find lambda such that sum of clamped(alpha_i - lambda)/200 = max.
    """
    items = list(alphas.items())
    if not items:
        return {}
    # Initial: lambda = 0 (unconstrained solution)
    def total_for(lam):
        return sum(max(0.0, (a - lam) / 200.0) for _, a in items)
    if total_for(0) <= max_budget_pct:
        return {k: max(0.0, a / 200.0) for k, a in items}
    # Binary search lambda in [0, max(alphas)]
    lo, hi = 0.0, max(a for _, a in items)
    for _ in range(50):
        mid = (lo + hi) / 2
        if total_for(mid) > max_budget_pct:
            lo = mid
        else:
            hi = mid
    lam = (lo + hi) / 2
    return {k: max(0.0, (a - lam) / 200.0) for k, a in items}


def compute_pnl(alphas: dict, vols: dict) -> dict:
    """Returns dict with profit, fees, net per good + total."""
    out = {}
    total_profit = 0
    total_fees = 0
    for k in alphas:
        v = vols.get(k, 0)
        a = alphas[k]
        profit = a * v
        fee = 100 * v * v
        net = profit - fee
        out[k] = dict(alpha=a, vol_pct=v, profit=profit, fee=fee, net=net)
        total_profit += profit
        total_fees += fee
    out["__total"] = dict(profit=total_profit, fees=total_fees, net=total_profit - total_fees)
    return out


def example():
    """Example with hypothetical alphas."""
    # Alphas in PnL points per 1% of budget (e.g., alpha=50 means 1% allocation = 50 PnL)
    # When data arrives, replace with actual estimates from Ashflow Alpha
    alphas = {
        "GoodA": 100,  # high conviction
        "GoodB": 80,
        "GoodC": 60,
        "GoodD": 40,
        "GoodE": 20,
        "GoodF": 0,
        "GoodG": -20,  # negative alpha (short)
        "GoodH": -50,
        "GoodI": -100,
    }
    vols = optimal_with_budget(alphas, max_budget_pct=100)
    pnl = compute_pnl(alphas, vols)
    print("Example (replace with real alphas):")
    for k in alphas:
        d = pnl[k]
        print(f"  {k}: alpha={d['alpha']:>5}  vol={d['vol_pct']:>6.2f}%  net={d['net']:>10,.0f}")
    print(f"  TOTAL: net={pnl['__total']['net']:,.0f}  budget_used={sum(vols.values()):.1f}%")


if __name__ == "__main__":
    example()
