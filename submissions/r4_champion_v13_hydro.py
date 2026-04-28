"""Backtest wrapper for r4_champion_v13_hydro_round4_submission.py.

Loads Trader from the self-contained artifact file so the backtest engine can run it.
Position limits come from config.py "champion" → ROUND_4 fallback (200/300) which
matches the submission's embedded POSITION_LIMITS.
"""
import importlib.util
import pathlib
import sys

_path = pathlib.Path(__file__).parent.parent / "artifacts" / "submissions" / "round_4" / "r4_champion_v13_hydro_round4_submission.py"
_spec = importlib.util.spec_from_file_location("_r4_champ_v13_mod", _path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_r4_champ_v13_mod"] = _mod
_spec.loader.exec_module(_mod)

Trader = _mod.Trader
