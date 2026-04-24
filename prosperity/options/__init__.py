"""Options pricing utilities — Black-Scholes, implied vol, smile fitting.

All functions are pure (no state), so they're trivially embeddable in a
Trader.run() hot path. Units: time T in DAYS, vol sigma is per-DAY (daily vol).
Risk-free rate r=0 by default (prosperity assumption). No dividends.

Usage:
    from prosperity.options.black_scholes import call_price, call_delta, call_vega
    from prosperity.options.implied_vol import call_implied_vol
    from prosperity.options.smile import fit_smile_poly, smile_predict
"""

from prosperity.options.black_scholes import (
    call_price,
    call_delta,
    call_gamma,
    call_vega,
    call_theta,
    put_price,
    put_delta,
)
from prosperity.options.implied_vol import call_implied_vol, put_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict, average_vol

__all__ = [
    "call_price",
    "call_delta",
    "call_gamma",
    "call_vega",
    "call_theta",
    "put_price",
    "put_delta",
    "call_implied_vol",
    "put_implied_vol",
    "fit_smile_poly",
    "smile_predict",
    "average_vol",
]
