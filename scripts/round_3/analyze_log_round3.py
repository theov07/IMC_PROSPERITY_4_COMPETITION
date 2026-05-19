import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prosperity.tooling.r3_log_analysis import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli())
