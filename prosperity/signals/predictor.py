"""Short-term price prediction using linear regression on microstructure features.

Features used:
  - Order book imbalance (bid_vol - ask_vol) / (bid_vol + ask_vol)
  - Microprice deviation from mid
  - Trade flow imbalance (recent buy volume - sell volume)
  - Lagged returns (1, 2, 5 ticks)
  - Spread

The model predicts the next-tick mid-price change using OLS (no external libs needed).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Trade

from prosperity.market import BookSnapshot


class LinearPredictor:
    """Online OLS predictor that updates incrementally."""

    def __init__(self, n_features: int, ridge_lambda: float = 1.0):
        self.n = n_features
        self.lam = ridge_lambda
        # XtX = n x n, XtY = n x 1 (stored as lists for stdlib-only)
        self._xtx: List[List[float]] = [[self.lam if i == j else 0.0 for j in range(n)] for i in range(n)]
        self._xty: List[float] = [0.0] * n
        self._weights: List[float] = [0.0] * n
        self._count = 0

    def update(self, features: List[float], target: float):
        """Add one observation and recompute weights."""
        n = self.n
        for i in range(n):
            self._xty[i] += features[i] * target
            for j in range(n):
                self._xtx[i][j] += features[i] * features[j]
        self._count += 1

        if self._count >= n + 2:
            self._solve()

    def _solve(self):
        """Solve (XtX) w = XtY via Cholesky-like fallback."""
        n = self.n
        # Simple Gaussian elimination
        A = [row[:] + [self._xty[i]] for i, row in enumerate(self._xtx)]
        for col in range(n):
            max_row = max(range(col, n), key=lambda r: abs(A[r][col]))
            A[col], A[max_row] = A[max_row], A[col]
            if abs(A[col][col]) < 1e-12:
                continue
            for row in range(col + 1, n):
                factor = A[row][col] / A[col][col]
                for j in range(col, n + 1):
                    A[row][j] -= factor * A[col][j]

        w = [0.0] * n
        for i in range(n - 1, -1, -1):
            if abs(A[i][i]) < 1e-12:
                continue
            w[i] = A[i][n]
            for j in range(i + 1, n):
                w[i] -= A[i][j] * w[j]
            w[i] /= A[i][i]

        self._weights = w

    def predict(self, features: List[float]) -> float:
        return sum(w * f for w, f in zip(self._weights, features))


class PricePredictor:
    """Wraps LinearPredictor with feature extraction from BookSnapshot + trades."""

    N_FEATURES = 7

    def __init__(self, ridge_lambda: float = 1.0):
        self.model = LinearPredictor(self.N_FEATURES, ridge_lambda)
        self._prev_mids: List[float] = []
        self._prev_features: List[float] | None = None

    def extract_features(
        self, book: BookSnapshot, recent_trades: List[Trade],
    ) -> List[float]:
        """Build feature vector from current book state and recent trades."""
        # 1. Book imbalance
        imbalance = book.imbalance if book.imbalance is not None else 0.0

        # 2. Microprice deviation from mid
        micro_dev = 0.0
        if book.microprice is not None and book.mid_price is not None:
            micro_dev = book.microprice - book.mid_price

        # 3. Trade flow imbalance
        buy_vol = 0
        sell_vol = 0
        for t in recent_trades:
            if t.buyer == "SUBMISSION" or (t.buyer and t.buyer != ""):
                buy_vol += t.quantity
            if t.seller == "SUBMISSION" or (t.seller and t.seller != ""):
                sell_vol += t.quantity
        total_flow = buy_vol + sell_vol
        trade_imb = (buy_vol - sell_vol) / total_flow if total_flow > 0 else 0.0

        # 4-6. Lagged returns
        mids = self._prev_mids
        current_mid = book.mid_price or 0.0
        ret_1 = (current_mid - mids[-1]) if len(mids) >= 1 else 0.0
        ret_2 = (current_mid - mids[-2]) if len(mids) >= 2 else 0.0
        ret_5 = (current_mid - mids[-5]) if len(mids) >= 5 else 0.0

        # 7. Spread
        spread = book.spread if book.spread is not None else 0.0

        return [imbalance, micro_dev, trade_imb, ret_1, ret_2, ret_5, spread]

    def on_tick(
        self, book: BookSnapshot, recent_trades: List[Trade],
    ) -> float:
        """Process one tick: update model with last prediction, return new prediction.

        Returns predicted mid-price CHANGE for next tick.
        """
        current_mid = book.mid_price
        if current_mid is None:
            return 0.0

        features = self.extract_features(book, recent_trades)

        # Train on previous tick's prediction vs actual
        if self._prev_features is not None and len(self._prev_mids) >= 1:
            prev_mid = self._prev_mids[-1]
            actual_change = current_mid - prev_mid
            self.model.update(self._prev_features, actual_change)

        prediction = self.model.predict(features)

        self._prev_features = features
        self._prev_mids.append(current_mid)
        if len(self._prev_mids) > 200:
            self._prev_mids[:] = self._prev_mids[-200:]

        return prediction
