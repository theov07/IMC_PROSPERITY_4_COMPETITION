"""Backtester wrapper for test_theo standalone submission."""

import sys
import importlib.util

# Load the standalone submission file directly
_spec = importlib.util.spec_from_file_location(
    "test_theo_submission",
    "artifacts/submissions/round_1/theo/test_theo_round1_submission.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod  # register before exec so dataclass works
_spec.loader.exec_module(_mod)

Trader = _mod.Trader
