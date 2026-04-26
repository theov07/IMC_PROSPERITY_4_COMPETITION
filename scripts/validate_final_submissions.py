"""Validate every submission in artifacts/submissions/round_3/_final/.

Each submission is loaded in its OWN python subprocess to avoid class-identity
collisions across self-contained inlined submissions (each redefines
BaseStrategy, BookSnapshot, etc.).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINAL_DIR = ROOT / "artifacts" / "submissions" / "round_3" / "_final"
LIMIT = 100_000

PROBE = r"""
import importlib.util, sys, traceback, json, time
spec = importlib.util.spec_from_file_location("submission_under_test", r"{path}")
mod = importlib.util.module_from_spec(spec)
sys.modules["submission_under_test"] = mod
try:
    spec.loader.exec_module(mod)
except Exception as e:
    print(json.dumps({{"ok": False, "stage": "import", "err": repr(e), "tb": traceback.format_exc()}}))
    sys.exit(0)
try:
    Trader = mod.Trader
    t = Trader()
except Exception as e:
    print(json.dumps({{"ok": False, "stage": "init", "err": repr(e), "tb": traceback.format_exc()}}))
    sys.exit(0)

# Build a minimal TradingState
TradingState = mod.TradingState
OrderDepth = mod.OrderDepth
Listing = mod.Listing if hasattr(mod, "Listing") else None
ods = {{}}
listings = {{}}
for sym, vals in [("HYDROGEL_PACK", (10018, 10020)),
                   ("VELVETFRUIT_EXTRACT", (1500, 1502)),
                   ("VEV_3950", (4500, 4520)),
                   ("VEV_4000", (4500, 4520)),
                   ("VEV_4050", (4500, 4520)),
                   ("VEV_4100", (4500, 4520)),
                   ("VEV_4150", (4500, 4520)),
                   ("VEV_4200", (4500, 4520)),
                   ("VEV_4300", (4500, 4520)),
                   ("VEV_4500", (4500, 4520)),
                   ("VEV_5000", (4500, 4520)),
                   ("VEV_5200", (4500, 4520))]:
    bid_p, ask_p = vals
    od = OrderDepth()
    od.buy_orders = {{bid_p: 25, bid_p - 1: 30}}
    od.sell_orders = {{ask_p: -25, ask_p + 1: -30}}
    ods[sym] = od

state = TradingState(
    traderData="",
    timestamp=500,
    listings=listings,
    order_depths=ods,
    own_trades={{}},
    market_trades={{}},
    position={{}},
    observations=mod.Observation({{}}, {{}}) if hasattr(mod, "Observation") else None,
)

try:
    t0 = time.perf_counter()
    out = t.run(state)
    dt_ms = (time.perf_counter() - t0) * 1000
    n_orders = sum(len(v) for v in out[0].values()) if isinstance(out, tuple) else 0
    print(json.dumps({{"ok": True, "n_orders": n_orders, "dt_ms": round(dt_ms, 2)}}))
except Exception as e:
    print(json.dumps({{"ok": False, "stage": "run", "err": repr(e), "tb": traceback.format_exc()}}))
"""


def main() -> int:
    files = sorted(FINAL_DIR.rglob("*_round3_submission.py"))
    if not files:
        print(f"[ERR] No submissions found under {FINAL_DIR}")
        return 1
    failures = 0
    print(f"Validating {len(files)} submissions in {FINAL_DIR}\n")
    print(f"{'FILE':<60} {'SIZE':>8} {'<100KB':>8} {'STATUS':<60}")
    print("-" * 140)
    for f in files:
        size = f.stat().st_size
        size_ok = size < LIMIT
        rel = f.relative_to(FINAL_DIR).as_posix()
        result = subprocess.run(
            [sys.executable, "-c", PROBE.format(path=str(f).replace("\\", "\\\\"))],
            capture_output=True, text=True, timeout=60,
        )
        line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        try:
            data = json.loads(line)
        except Exception:
            data = {"ok": False, "err": f"bad probe output: {line!r} stderr={result.stderr!r}"}
        if data.get("ok") and size_ok:
            status = f"OK  orders={data.get('n_orders', '?')}  dt={data.get('dt_ms', '?')}ms"
        else:
            failures += 1
            stage = data.get("stage", "?")
            err = data.get("err", "")[:80]
            status = f"FAIL [{stage}]: {err}"
        print(f"{rel:<60} {size:>8} {('OK' if size_ok else 'OVER'):>8} {status}")
    print()
    if failures:
        print(f"[FAILED] {failures}/{len(files)} submissions")
        return 1
    print(f"[OK] All {len(files)} submissions valid and under {LIMIT} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
