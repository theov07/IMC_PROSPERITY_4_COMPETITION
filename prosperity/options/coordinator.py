"""Per-tick shared cache for option strategies.

Purpose: amortize expensive cross-product computations (smile fit, underlying
mid, portfolio greeks) across the 10 VEV_xxxx strategies that run within the
same tick. Each Trader.run() visits products sequentially, but all share the
same `datamodel.TradingState`. By keying the cache on `(tick_id, key)` we
compute once and reuse.

Design rationale:
  - The dispatcher gives each strategy its own `memory` dict, so
    `memory["_shared"]` is per-product, NOT shared across products.
  - A module-level singleton sidesteps this cleanly in the single-threaded
    Prosperity sandbox. We tag cached entries with the current timestamp so
    stale entries from a previous tick are never served.
  - Cache grows bounded (one entry per key per tick) and is implicitly evicted
    by timestamp invalidation.

Public API:
  get_smile(state, *, strikes, underlying, sigma_floor, sigma_cap, prior_vol)
      → list of smile coefficients or None. Caches per tick.
  get_spot(state, *, underlying)
      → mid price of the underlying. Caches per tick.
  publish_position(product, position)
      → record this strategy's current position (used by hedger).
  get_positions()
      → dict of {product: position} for the current tick.
  reset_if_new_tick(ts)
      → clears tick-scoped caches when ts advances. Called automatically.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from datamodel import TradingState

from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly


# ── Module-level state (safe in Prosperity single-threaded sandbox) ───────────

_STATE: Dict[str, Any] = {
    "ts": None,          # int — timestamp of current tick
    "smile": None,       # List[float] or None — last computed smile coeffs
    "spot": {},          # dict: underlying_symbol -> float mid
    "positions": {},     # dict: product -> int position (published by strategies)
}


def _ensure_current_tick(ts: int) -> None:
    """Clear per-tick caches if the timestamp has advanced."""
    if _STATE["ts"] != ts:
        _STATE["ts"] = ts
        _STATE["smile"] = None
        _STATE["spot"] = {}
        _STATE["positions"] = {}


# ── Spot ──────────────────────────────────────────────────────────────────────

def get_spot(state: TradingState, *, underlying: str) -> Optional[float]:
    """Return mid-price of the underlying, caching the result for this tick."""
    ts = int(state.timestamp)
    _ensure_current_tick(ts)
    cached = _STATE["spot"].get(underlying)
    if cached is not None:
        return cached
    od = state.order_depths.get(underlying)
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    bb = max(od.buy_orders.keys())
    ba = min(od.sell_orders.keys())
    spot = 0.5 * (bb + ba)
    _STATE["spot"][underlying] = spot
    return spot


# ── Smile ─────────────────────────────────────────────────────────────────────

def get_smile(
    state: TradingState,
    *,
    strikes: List[int],
    strike_prefix: str,
    S: float,
    T: float,
    sigma_floor: float,
    sigma_cap: float,
    prior_vol: float,
    degree: int = 2,
) -> Optional[List[float]]:
    """Return smile coefficients fitted across all strikes at this tick.

    Fits once per tick. Subsequent calls in the same tick return the cached
    result regardless of which strike asked.

    Args:
        state: current TradingState (for order_depths)
        strikes: iterable of strike prices to consider
        strike_prefix: e.g. "VEV_" so "VEV_5000" resolves from strike 5000
        S, T: spot + time to expiry for BS
        sigma_floor/sigma_cap: IV bounds for validity
        prior_vol: initial guess for IV solver
        degree: polynomial degree in log-moneyness (default 2)
    """
    ts = int(state.timestamp)
    _ensure_current_tick(ts)
    if _STATE["smile"] is not None:
        return _STATE["smile"]

    valid_strikes: List[float] = []
    valid_vols: List[float] = []
    for K in strikes:
        sym = f"{strike_prefix}{K}"
        od = state.order_depths.get(sym)
        if not od or not od.buy_orders or not od.sell_orders:
            continue
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        mid = 0.5 * (bb + ba)
        iv = call_implied_vol(mid, S, float(K), T, sigma_init=prior_vol)
        if iv is not None and sigma_floor <= iv <= sigma_cap:
            valid_strikes.append(float(K))
            valid_vols.append(iv)

    coeffs: Optional[List[float]] = None
    if len(valid_strikes) >= 3:
        coeffs = fit_smile_poly(valid_strikes, valid_vols, S, T, degree=degree)

    _STATE["smile"] = coeffs
    return coeffs


# ── Position registry (used by delta hedger) ──────────────────────────────────

def publish_position(ts: int, product: str, position: int) -> None:
    """Record current position for `product`. Called by each strategy per tick."""
    _ensure_current_tick(ts)
    _STATE["positions"][product] = int(position)


def get_positions(ts: int) -> Dict[str, int]:
    """Return snapshot of published positions for the given tick (dict copy)."""
    _ensure_current_tick(ts)
    return dict(_STATE["positions"])


# ── Debug / introspection ─────────────────────────────────────────────────────

def snapshot() -> Dict[str, Any]:
    """Return a shallow copy of current state (debug / testing)."""
    return {
        "ts": _STATE["ts"],
        "smile_present": _STATE["smile"] is not None,
        "spot_keys": list(_STATE["spot"].keys()),
        "positions": dict(_STATE["positions"]),
    }


def reset() -> None:
    """Clear all state. Intended for tests / between backtest runs."""
    _STATE["ts"] = None
    _STATE["smile"] = None
    _STATE["spot"] = {}
    _STATE["positions"] = {}
