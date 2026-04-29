"""ETF / basket fair value computation for R5.

Each "ETF" = a fixed linear combination of products. We track the live mid
of each member, compute the basket fair value (e.g. equal-weight mean,
or PCA-PC1 weighted), and the deviation of any single member from this
fair value. If the deviation is mean-reverting (verified offline), we
can MM around the equilibrium.

Pre-computed weight schemes (from research/structure_analysis/pca_analysis.py):
  - SNACKPACK_PC1: long RASP, short STRAW+PIST  (60% var)
  - SNACKPACK_PC2: long VAN, short CHOC          (35% var)
  - PEBBLES_PC1:  XL vs (XS+S+M+L)               (top loadings)

Equal-weight group ETFs: just mean of all members (z-scored).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from prosperity.baskets.groups import GROUPS

# Pre-computed PCA portfolios (loadings from pca_per_group_summary.csv)
# Use these as fixed basket weights that capture the structural factor.
PCA_PORTFOLIOS: Dict[str, Dict[str, float]] = {
    "SNACKPACK_PC1": {
        "SNACKPACK_RASPBERRY": +0.652,
        "SNACKPACK_STRAWBERRY": -0.626,
        "SNACKPACK_PISTACHIO": -0.427,
        "SNACKPACK_VANILLA": -0.013,
        "SNACKPACK_CHOCOLATE": +0.007,
    },
    "SNACKPACK_PC2": {
        "SNACKPACK_VANILLA": +0.693,
        "SNACKPACK_CHOCOLATE": -0.721,
        "SNACKPACK_PISTACHIO": -0.006,
        "SNACKPACK_STRAWBERRY": -0.010,
        "SNACKPACK_RASPBERRY": +0.008,
    },
    # PEBBLES PC1 (from per-group): typically XL +heavy vs XS/S/M/L
    "PEBBLES_PC1": {
        "PEBBLES_XL": +0.78,
        "PEBBLES_XS": +0.47,
        "PEBBLES_S": +0.27,
        "PEBBLES_M": +0.22,
        "PEBBLES_L": +0.21,
    },
}


class GroupETF:
    """Equal-weight basket of a single group, with running fair value
    and deviation tracking.

    Use as fair value = mean of group mids. Deviation_i = mid_i - fair_value.
    If group has flat mean (TRANSLATOR/PEBBLES), deviation = pure tracking error.
    """

    def __init__(self, group: str):
        self.group = group
        self.members: List[str] = list(GROUPS[group])

    def fair_value(self, mids: Dict[str, float]) -> Optional[float]:
        valid = [mids[m] for m in self.members if m in mids and mids[m] is not None]
        if not valid:
            return None
        return sum(valid) / len(valid)

    def deviations(self, mids: Dict[str, float]) -> Dict[str, float]:
        fv = self.fair_value(mids)
        if fv is None:
            return {}
        return {m: mids[m] - fv for m in self.members if m in mids and mids[m] is not None}


class PCAPortfolio:
    """Linear combination ETF defined by pre-computed PCA loadings.

    fair_price = sum(w_i * mid_i)  - the "synthetic price" of this portfolio.
    """

    def __init__(self, name: str):
        self.name = name
        self.weights: Dict[str, float] = PCA_PORTFOLIOS[name]

    def synthetic_price(self, mids: Dict[str, float]) -> Optional[float]:
        s = 0.0
        n = 0
        for p, w in self.weights.items():
            m = mids.get(p)
            if m is None:
                return None
            s += w * m
            n += 1
        return s if n else None
