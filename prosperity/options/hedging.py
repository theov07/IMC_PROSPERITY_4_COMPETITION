"""Option portfolio hedging — pure functions.

Computes portfolio greeks from a set of option positions and recommends a
hedge trade in the underlying to reach a target exposure (typically
delta-neutral, target_delta=0).

Units: consistent with black_scholes.py — T in days, sigma per-day, r=0.

Public API:
  portfolio_greeks(positions, S, T, sigma_fn) → dict {delta, gamma, vega}
  recommend_delta_hedge(current_pos, portfolio_delta, target_delta=0.0,
                        pos_limit=None, trade_step=1) → int (signed qty)

Signed convention:
  positive qty = BUY underlying
  negative qty = SELL underlying
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from prosperity.options.black_scholes import call_delta, call_gamma, call_vega


# ── Portfolio greeks ──────────────────────────────────────────────────────────

def portfolio_greeks(
    positions: List[Tuple[float, int]],
    S: float,
    T: float,
    sigma_fn: Callable[[float], float],
) -> Dict[str, float]:
    """Compute aggregated delta / gamma / vega across a set of call option positions.

    Args:
        positions: list of (strike, signed_quantity) tuples.
        S: spot price of the underlying.
        T: time to expiry in days.
        sigma_fn: callable strike -> sigma. Typically `lambda K: smile_predict(...)`.

    Returns:
        dict with keys "delta", "gamma", "vega" (floats, per-unit sigma).
    """
    total_delta = 0.0
    total_gamma = 0.0
    total_vega = 0.0
    for K, qty in positions:
        if qty == 0:
            continue
        sigma = max(1e-6, float(sigma_fn(float(K))))
        total_delta += qty * call_delta(S, K, T, sigma)
        total_gamma += qty * call_gamma(S, K, T, sigma)
        total_vega += qty * call_vega(S, K, T, sigma)
    return {"delta": total_delta, "gamma": total_gamma, "vega": total_vega}


# ── Delta hedge recommendation ────────────────────────────────────────────────

def recommend_delta_hedge(
    *,
    current_underlying_pos: int,
    option_portfolio_delta: float,
    target_delta: float = 0.0,
    position_limit: Optional[int] = None,
    max_trade_size: Optional[int] = None,
) -> int:
    """Return signed quantity of underlying to trade to reach target_delta.

    Logic:
        Since underlying delta = 1 per unit, net_delta = option_delta + underlying_pos.
        To reach net_delta = target_delta, we need:
            new_underlying_pos = target_delta - option_delta
            trade_qty = new_underlying_pos - current_underlying_pos

    Args:
        current_underlying_pos: current position in the underlying.
        option_portfolio_delta: aggregated option delta (from portfolio_greeks).
        target_delta: net portfolio delta we want (default 0 = delta-neutral).
        position_limit: optional max abs position on underlying (clamps).
        max_trade_size: optional max abs qty per trade (throttles hedge speed).

    Returns:
        signed int — buy (> 0), sell (< 0), or 0.
    """
    target_underlying = target_delta - option_portfolio_delta
    trade_qty = int(round(target_underlying - current_underlying_pos))

    if max_trade_size is not None and max_trade_size > 0:
        if trade_qty > max_trade_size:
            trade_qty = max_trade_size
        elif trade_qty < -max_trade_size:
            trade_qty = -max_trade_size

    if position_limit is not None:
        new_pos = current_underlying_pos + trade_qty
        if new_pos > position_limit:
            trade_qty = position_limit - current_underlying_pos
        elif new_pos < -position_limit:
            trade_qty = -position_limit - current_underlying_pos

    return int(trade_qty)


# ── Vega hedge (buy/sell ATM option to offset portfolio vega) ─────────────────

def recommend_vega_hedge(
    *,
    portfolio_vega: float,
    atm_vega: float,
    current_atm_option_pos: int,
    target_vega: float = 0.0,
    position_limit: Optional[int] = None,
    max_trade_size: Optional[int] = None,
) -> int:
    """Return signed qty of an ATM option to trade to reach target_vega.

    Vega_i per unit = atm_vega. Trade qty = (target_vega - portfolio_vega) / atm_vega.
    """
    if atm_vega <= 0:
        return 0
    target_additional_pos = (target_vega - portfolio_vega) / atm_vega
    trade_qty = int(round(target_additional_pos))

    if max_trade_size is not None and max_trade_size > 0:
        if trade_qty > max_trade_size:
            trade_qty = max_trade_size
        elif trade_qty < -max_trade_size:
            trade_qty = -max_trade_size

    if position_limit is not None:
        new_pos = current_atm_option_pos + trade_qty
        if new_pos > position_limit:
            trade_qty = position_limit - current_atm_option_pos
        elif new_pos < -position_limit:
            trade_qty = -position_limit - current_atm_option_pos

    return int(trade_qty)
