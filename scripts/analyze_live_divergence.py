"""Compare two live IMC submissions to understand fill divergence.

Looks at fills from tradeHistory in .log files and identifies WHERE and WHY
two runs diverge despite (supposedly) identical strategy logic.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def load_log(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def my_fills(trade_history: list) -> list:
    """Extract SUBMISSION fills as (ts, sym, side, price, qty)."""
    out = []
    for t in trade_history:
        ts = t["timestamp"]
        sym = t["symbol"]
        price = t["price"]
        qty = t["quantity"]
        if t["buyer"] == "SUBMISSION":
            out.append((ts, sym, "BUY", price, qty))
        elif t["seller"] == "SUBMISSION":
            out.append((ts, sym, "SELL", price, qty))
    return sorted(out)


def diverge_analysis(path_a: str, path_b: str, name_a: str = "A", name_b: str = "B"):
    da = load_log(Path(path_a))
    db = load_log(Path(path_b))

    fa = my_fills(da.get("tradeHistory", []))
    fb = my_fills(db.get("tradeHistory", []))

    print(f"=== {name_a} vs {name_b} fill comparison ===")
    print(f"{name_a}: {len(fa)} fills")
    print(f"{name_b}: {len(fb)} fills")
    print()

    # Find first divergence point
    set_a = set(fa)
    set_b = set(fb)
    common = set_a & set_b
    print(f"Identical fills: {len(common)}")
    print(f"{name_a} only: {len(set_a - common)}")
    print(f"{name_b} only: {len(set_b - common)}")
    print()

    # Find first timestamp where they diverge
    ts_a = sorted({f[0] for f in fa})
    ts_b = sorted({f[0] for f in fb})

    # Per-symbol divergence
    sym_a = defaultdict(int)
    sym_b = defaultdict(int)
    for ts, sym, side, p, q in set_a - common:
        sym_a[(sym, side)] += q
    for ts, sym, side, p, q in set_b - common:
        sym_b[(sym, side)] += q

    print(f"=== Per-symbol divergence (only in one run) ===")
    print(f"{'Symbol':<32} {'Side':<5} {f'{name_a} qty':>10} {f'{name_b} qty':>10} {'Δ':>6}")
    all_keys = sorted(set(sym_a) | set(sym_b))
    for k in all_keys:
        a = sym_a.get(k, 0)
        b = sym_b.get(k, 0)
        if a != b:
            print(f"{k[0]:<32} {k[1]:<5} {a:>10} {b:>10} {b-a:>+6}")

    # Find divergence boundaries (windows of consecutive different fills)
    print(f"\n=== Divergence WINDOWS (first 5) ===")
    diverge_ts_a = sorted([f[0] for f in set_a - common])
    diverge_ts_b = sorted([f[0] for f in set_b - common])
    print(f"{name_a} only timestamps: {diverge_ts_a[:10]}")
    print(f"{name_b} only timestamps: {diverge_ts_b[:10]}")

    # First divergence point
    if diverge_ts_a or diverge_ts_b:
        first_diverge = min(diverge_ts_a + diverge_ts_b)
        print(f"\nFirst divergence at ts={first_diverge}")

    return fa, fb


def per_symbol_pnl(path: str, mid_at_99900: dict) -> dict:
    """Compute final PnL per symbol from fills + mark-to-market."""
    d = load_log(Path(path))
    pnl = {}
    pos = defaultdict(int)
    cash = defaultdict(float)
    for t in d.get("tradeHistory", []):
        sym = t["symbol"]
        if t["buyer"] == "SUBMISSION":
            pos[sym] += t["quantity"]
            cash[sym] -= t["quantity"] * t["price"]
        elif t["seller"] == "SUBMISSION":
            pos[sym] -= t["quantity"]
            cash[sym] += t["quantity"] * t["price"]
    for sym in set(pos) | set(cash):
        pnl[sym] = cash[sym] + pos[sym] * mid_at_99900.get(sym, 0)
    return pnl


def get_mids_at_ts(path: str, target_ts: int) -> dict:
    """Get mids from activitiesLog at a specific timestamp."""
    d = load_log(Path(path))
    al = d.get("activitiesLog", "")
    out = {}
    for line in al.strip().split("\n")[1:]:
        parts = line.split(";")
        if len(parts) < 16:
            continue
        if int(parts[1]) == target_ts and parts[15]:
            out[parts[2]] = float(parts[15])
    return out


if __name__ == "__main__":
    a = "C:/Users/LéoRENAULT/Downloads/log_v2090/563187.log"
    b = "C:/Users/LéoRENAULT/Downloads/best_log/564793.log"

    fa, fb = diverge_analysis(a, b, "v2090", "v2640")

    # Compare PnL per symbol
    mids = get_mids_at_ts(a, 99900)
    pnl_a = per_symbol_pnl(a, mids)
    pnl_b = per_symbol_pnl(b, mids)

    print(f"\n=== Per-symbol PnL diff (v2640 - v2090) ===")
    diffs = []
    for s in sorted(set(pnl_a) | set(pnl_b)):
        d = pnl_b.get(s, 0) - pnl_a.get(s, 0)
        if abs(d) > 100:
            diffs.append((s, pnl_a.get(s, 0), pnl_b.get(s, 0), d))
    diffs.sort(key=lambda x: -abs(x[3]))
    for s, a_p, b_p, d in diffs[:25]:
        print(f"{s:<35} v2090={a_p:>+8.0f}  v2640={b_p:>+8.0f}  Δ={d:>+8.0f}")
