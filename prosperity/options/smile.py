"""Volatility smile fitting across strikes (single expiry).

Uses polynomial regression in log-moneyness space:
    m = ln(K/F)     where F = forward price ≈ S * e^((r-q)*T)
    sigma(m) = a0 + a1*m + a2*m^2    (default degree 2 = classic smile shape)

Fit is minimum-variance over observed (m, sigma_implied) pairs. Returns the
coefficients as a list [a0, a1, a2, ...]. Use `smile_predict(m, coeffs)` to
interpolate/extrapolate a sigma at any moneyness.

No numpy — pure Python for sandbox. Uses normal equations with small matrix
inverse (2x2 or 3x3).
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple, Optional


def _solve_normal_eqs(X_cols: List[List[float]], y: List[float]) -> Optional[List[float]]:
    """Ordinary least squares: solve (X^T X) beta = X^T y for small matrices.

    X_cols is a list of columns (each column is a list of same length n).
    Returns beta as list[float] or None if singular.
    """
    n = len(y)
    d = len(X_cols)
    if n < d:
        return None
    # Build X^T X (d x d) and X^T y (d)
    XtX = [[0.0] * d for _ in range(d)]
    Xty = [0.0] * d
    for i in range(d):
        for j in range(d):
            s = 0.0
            for k in range(n):
                s += X_cols[i][k] * X_cols[j][k]
            XtX[i][j] = s
        s = 0.0
        for k in range(n):
            s += X_cols[i][k] * y[k]
        Xty[i] = s
    # Solve d x d via Gauss-Jordan
    M = [row[:] + [Xty[i]] for i, row in enumerate(XtX)]  # augmented
    for i in range(d):
        # Partial pivot
        max_row = i
        for r in range(i + 1, d):
            if abs(M[r][i]) > abs(M[max_row][i]):
                max_row = r
        M[i], M[max_row] = M[max_row], M[i]
        if abs(M[i][i]) < 1e-12:
            return None
        pivot = M[i][i]
        for c in range(d + 1):
            M[i][c] /= pivot
        for r in range(d):
            if r != i:
                factor = M[r][i]
                for c in range(d + 1):
                    M[r][c] -= factor * M[i][c]
    return [M[i][d] for i in range(d)]


# ── Smile fit ─────────────────────────────────────────────────────────────────

def fit_smile_poly(
    strikes: Sequence[float],
    vols: Sequence[float],
    S: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    *,
    degree: int = 2,
    min_points: int = 3,
) -> Optional[List[float]]:
    """Fit polynomial smile sigma(m) = sum(a_i * m^i) where m = ln(K/F).

    Args:
        strikes: iterable of strike prices
        vols:    iterable of matching implied vols (skip None values)
        S, T, r, q: BS inputs to compute forward F = S * e^((r-q)*T)
        degree: polynomial degree (2 = quadratic smile, default)
        min_points: require at least this many valid (K, vol) pairs

    Returns:
        list of coefficients [a0, a1, ..., a_degree], or None if fit failed.
    """
    F = S * math.exp((r - q) * T)
    ms: List[float] = []
    sigs: List[float] = []
    for K, v in zip(strikes, vols):
        if v is None or v <= 0.0 or K <= 0.0:
            continue
        ms.append(math.log(K / F))
        sigs.append(float(v))
    if len(ms) < max(min_points, degree + 1):
        return None
    # Build design matrix columns [1, m, m^2, ...]
    cols: List[List[float]] = []
    for d in range(degree + 1):
        cols.append([m ** d for m in ms])
    return _solve_normal_eqs(cols, sigs)


def smile_predict(
    K: float,
    coeffs: Sequence[float],
    S: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
) -> float:
    """Evaluate smile sigma at strike K using fitted polynomial."""
    F = S * math.exp((r - q) * T)
    m = math.log(K / F)
    sig = 0.0
    for i, a in enumerate(coeffs):
        sig += a * (m ** i)
    return max(1e-5, sig)


def average_vol(vols: Sequence[Optional[float]]) -> Optional[float]:
    """Robust average of a list of implied vols (ignore None/invalid)."""
    valid = [v for v in vols if v is not None and v > 0.0]
    if not valid:
        return None
    return sum(valid) / len(valid)
