"""SVI (Stochastic Volatility Inspired) parameterization for the IV smile.

Standard form (Gatheral 2004):
    σ_BS²(k) · T = a + b · (ρ · (k - m) + sqrt((k - m)² + σ²))

where:
  k = log(K/F) ≈ log(K/S) for r=q=0  (log-moneyness)
  T = time to expiry in days (or any consistent unit)
  σ_BS = Black-Scholes implied vol per the same time unit as T
  a, b, ρ, m, σ_svi = SVI parameters (5 params)

Constraints (no calendar arbitrage):
  b ≥ 0
  -1 ≤ ρ ≤ 1
  σ_svi > 0
  a + b·σ_svi·sqrt(1-ρ²) ≥ 0   (no negative variance)

Compared to polynomial fit (degree 2):
  - SVI captures fat tails properly (ITM/OTM extremes)
  - Has horizontal asymptote at extreme moneyness (instead of curve diverging)
  - Better for trading: outliers vs SVI are more meaningful than vs polynomial

This is a single-expiry SVI. For multi-expiry use SSVI (not implemented).
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple


def svi_total_variance(k: float, a: float, b: float, rho: float, m: float, sigma: float) -> float:
    """SVI total variance σ²·T at log-moneyness k."""
    return a + b * (rho * (k - m) + math.sqrt((k - m) ** 2 + sigma ** 2))


def svi_iv(k: float, T: float, a: float, b: float, rho: float, m: float, sigma: float) -> float:
    """Convert SVI total variance to implied vol (per same time unit as T)."""
    if T <= 0.0:
        return 0.0
    w = svi_total_variance(k, a, b, rho, m, sigma)
    if w <= 0.0:
        return 0.0
    return math.sqrt(w / T)


def fit_svi(
    log_moneyness: Sequence[float],
    implied_vols: Sequence[float],
    T: float,
    *,
    n_iter: int = 200,
    learning_rate: float = 0.01,
) -> Optional[Tuple[float, float, float, float, float]]:
    """Fit SVI parameters (a, b, rho, m, sigma) by gradient descent on squared loss.

    Pure-python (no scipy) so it works in the IMC sandbox. Uses a basic Adam-like
    update rule. Initial guess from polynomial-2 fit of IV² vs k.

    Returns None if fit fails (insufficient data, NaN convergence).
    """
    n = len(log_moneyness)
    if n < 5 or len(implied_vols) != n or T <= 0.0:
        return None

    # Initial guess from polynomial fit of variance vs log-moneyness
    ks = list(log_moneyness)
    ws = [iv * iv * T for iv in implied_vols]   # total variance
    # Solve linear system for w = c0 + c1·k + c2·k² (degree 2)
    init = _polyfit_2(ks, ws)
    if init is None:
        return None
    c0, c1, c2 = init
    # Initial SVI params (heuristic): m at the minimum of the parabola
    m0 = -c1 / (2 * c2) if abs(c2) > 1e-12 else 0.0
    a0 = max(c0 - c1 * c1 / (4 * c2 + 1e-12), 1e-6)  # parabola minimum
    b0 = max(0.5 * abs(c2), 1e-4)
    rho0 = 0.0
    sigma0 = 0.1

    a, b, rho, m, sigma = a0, b0, rho0, m0, sigma0

    # Adam state
    state = {p: (0.0, 0.0) for p in "abrcs"}  # m1, m2
    beta1, beta2, eps = 0.9, 0.999, 1e-8

    def loss_grad(a, b, rho, m, sigma) -> Tuple[float, Tuple[float, float, float, float, float]]:
        loss = 0.0
        ga = gb = grho = gm = gs = 0.0
        for k, iv in zip(ks, implied_vols):
            target_w = iv * iv * T
            d = k - m
            r = math.sqrt(d * d + sigma * sigma)
            w = a + b * (rho * d + r)
            err = w - target_w
            loss += err * err
            # gradients
            ga += 2 * err
            gb += 2 * err * (rho * d + r)
            grho += 2 * err * b * d
            gm += 2 * err * b * (-rho - d / max(r, 1e-12))
            gs += 2 * err * b * sigma / max(r, 1e-12)
        return loss / n, (ga / n, gb / n, grho / n, gm / n, gs / n)

    for t in range(1, n_iter + 1):
        loss, (ga, gb, grho, gm, gs) = loss_grad(a, b, rho, m, sigma)
        # Adam updates
        for name, g in zip("abrcs", (ga, gb, grho, gm, gs)):
            m1, m2 = state[name]
            m1 = beta1 * m1 + (1 - beta1) * g
            m2 = beta2 * m2 + (1 - beta2) * g * g
            state[name] = (m1, m2)
            m1_hat = m1 / (1 - beta1 ** t)
            m2_hat = m2 / (1 - beta2 ** t)
            update = learning_rate * m1_hat / (math.sqrt(m2_hat) + eps)
            if name == "a":   a -= update
            elif name == "b": b -= update
            elif name == "r": rho -= update
            elif name == "c": m -= update
            elif name == "s": sigma -= update
        # Clamp constraints
        b = max(b, 1e-6)
        rho = max(-0.999, min(0.999, rho))
        sigma = max(sigma, 1e-3)
        # No-arb: a + b·σ·sqrt(1-ρ²) ≥ 0
        floor = -b * sigma * math.sqrt(max(0, 1 - rho * rho)) + 1e-6
        a = max(a, floor)

    if any(math.isnan(x) or math.isinf(x) for x in (a, b, rho, m, sigma)):
        return None
    return (a, b, rho, m, sigma)


def _polyfit_2(xs: Sequence[float], ys: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """Solve y = c0 + c1·x + c2·x² via normal equations."""
    n = len(xs)
    if n < 3:
        return None
    sx = sum(xs)
    sx2 = sum(x * x for x in xs)
    sx3 = sum(x ** 3 for x in xs)
    sx4 = sum(x ** 4 for x in xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2y = sum(x * x * y for x, y in zip(xs, ys))
    # 3×3 system
    M = [
        [float(n), sx, sx2],
        [sx, sx2, sx3],
        [sx2, sx3, sx4],
    ]
    Y = [sy, sxy, sx2y]
    return _solve_3x3(M, Y)


def _solve_3x3(M: List[List[float]], Y: List[float]) -> Optional[Tuple[float, float, float]]:
    """Solve 3×3 linear system by Gaussian elimination."""
    a = [row[:] + [y] for row, y in zip(M, Y)]
    for i in range(3):
        # Find pivot
        pivot = max(range(i, 3), key=lambda r: abs(a[r][i]))
        a[i], a[pivot] = a[pivot], a[i]
        if abs(a[i][i]) < 1e-12:
            return None
        for j in range(i + 1, 3):
            ratio = a[j][i] / a[i][i]
            for k in range(i, 4):
                a[j][k] -= ratio * a[i][k]
    # Back-substitution
    x = [0.0] * 3
    for i in range(2, -1, -1):
        s = a[i][3] - sum(a[i][j] * x[j] for j in range(i + 1, 3))
        x[i] = s / a[i][i]
    return tuple(x)


def svi_residuals(
    log_moneyness: Sequence[float],
    implied_vols: Sequence[float],
    T: float,
    params: Tuple[float, float, float, float, float],
) -> List[float]:
    """Per-strike IV residual: actual IV - SVI-fitted IV."""
    a, b, rho, m, sigma = params
    return [iv - svi_iv(k, T, a, b, rho, m, sigma) for k, iv in zip(log_moneyness, implied_vols)]


def svi_r2(
    log_moneyness: Sequence[float],
    implied_vols: Sequence[float],
    T: float,
    params: Tuple[float, float, float, float, float],
) -> float:
    """R² of SVI fit (in IV space, not variance space)."""
    a, b, rho, m, sigma = params
    fitted = [svi_iv(k, T, a, b, rho, m, sigma) for k in log_moneyness]
    mean_iv = sum(implied_vols) / max(len(implied_vols), 1)
    ss_tot = sum((iv - mean_iv) ** 2 for iv in implied_vols)
    ss_res = sum((iv - f) ** 2 for iv, f in zip(implied_vols, fitted))
    if ss_tot < 1e-12:
        return 0.0
    return 1.0 - ss_res / ss_tot
