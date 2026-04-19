"""Core functions for Manual Round 2 — shared across scripts.

Cost function, pillar formulas, speed tournament mechanics, grid search.

All rigorously derived from the wiki spec:
  PnL = Research(x) × Scale(y) × Speed(rank) − Budget_Used
  Research(x) = 200_000 × ln(1+x) / ln(101)
  Scale(y)    = 7 × y / 100
  Speed(rank) = 0.9 − 0.8 × (rank-1) / (N-1)   [N = total submitters]
  Budget_Used = (x+y+z) / 100 × 50,000
"""
from __future__ import annotations
import math
from typing import Tuple
import numpy as np

BUDGET = 50_000

# ═══════════════════════════════════════════════════
# Pillar formulas
# ═══════════════════════════════════════════════════

def research(x: float) -> float:
    """Research reward for x% invested. Log, max 200k at 100%."""
    return 200_000 * math.log(1 + x) / math.log(101)


def scale(y: float) -> float:
    """Scale multiplier for y% invested. Linear, max 7 at 100%."""
    return 7.0 * y / 100.0


def speed_mult_from_rank(rank: int, n_total: int) -> float:
    """Speed multiplier. Linear between 0.9 (rank 1) and 0.1 (rank n_total).
    Ties share rank (handled upstream by compute_my_rank)."""
    if n_total <= 1:
        return 0.9
    return 0.9 - 0.8 * (rank - 1) / (n_total - 1)


def budget_used(x: int, y: int, z: int) -> float:
    return (x + y + z) / 100.0 * BUDGET


def pnl(x: int, y: int, z: int, speed_m: float) -> float:
    """Full cost function."""
    return research(x) * scale(y) * speed_m - budget_used(x, y, z)


# ═══════════════════════════════════════════════════
# Optimal (x, y) given a budget for x+y
# ═══════════════════════════════════════════════════

def best_xy_given_budget(B: int) -> Tuple[int, int, float]:
    """Grid search optimal (x, y) maximizing R(x)×S(y) with x+y = B."""
    if B <= 0:
        return (0, 0, 0.0)
    best = (0, 0, 0.0)
    for x in range(0, B + 1):
        y = B - x
        prod = research(x) * scale(y)
        if prod > best[2]:
            best = (x, y, prod)
    return best


# ═══════════════════════════════════════════════════
# Tournament rank computation (ties share rank, rank ∈ [1, N])
# ═══════════════════════════════════════════════════

def compute_rank(my_z: int, others_z: np.ndarray) -> int:
    """My rank in [1, N] where N = len(others_z)+1. Ties share rank."""
    all_z = np.concatenate([[my_z], others_z])
    # Rank formula per wiki: sort descending, ties share the smallest rank
    sorted_desc = np.sort(all_z)[::-1]
    my_rank = int(np.searchsorted(-sorted_desc, -my_z, side='left')) + 1
    return my_rank


def compute_pnl_vs_field(my_z: int, others_z: np.ndarray) -> dict:
    """Full computation: optimal (x,y) given 100-my_z budget, rank, m, PnL."""
    B_xy = 100 - my_z
    x, y, _ = best_xy_given_budget(B_xy)
    rank = compute_rank(my_z, others_z)
    n_total = len(others_z) + 1
    m = speed_mult_from_rank(rank, n_total)
    used = budget_used(x, y, my_z)
    p = research(x) * scale(y) * m - used
    return {
        "my_z": my_z, "x": x, "y": y, "rank": rank, "n_total": n_total,
        "m": m, "R": research(x), "S": scale(y),
        "RS": research(x) * scale(y),
        "used": used, "pnl": p,
    }


def find_best_response(others_z: np.ndarray) -> dict:
    best = None
    for z in range(0, 101):
        r = compute_pnl_vs_field(z, others_z)
        if best is None or r["pnl"] > best["pnl"]:
            best = r
    return best
