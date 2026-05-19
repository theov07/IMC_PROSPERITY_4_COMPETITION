"""Default local entrypoint for the framework.

This mirrors the classic IMC-style ``main.py`` expected by some tests and
older tooling, while delegating to the maintained modular trader dispatcher.
"""

from submissions.champion import Trader
