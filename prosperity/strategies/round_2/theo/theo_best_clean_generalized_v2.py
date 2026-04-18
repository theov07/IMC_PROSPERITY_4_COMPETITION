"""Theo round-2 clean generalized v2.

This version keeps the v1 logic intact and expresses the winning startup-build
tuning through the round-2 config override only.
"""

from __future__ import annotations

from prosperity.strategies.round_2.theo.theo_best_clean_generalized import (
    TheoBestCleanGeneralizedStrategy,
)


class TheoBestCleanGeneralizedV2Strategy(TheoBestCleanGeneralizedStrategy):
    """V2: same logic as v1, with tuned startup-build parameters from search."""

    pass
