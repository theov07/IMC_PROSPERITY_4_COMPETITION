"""Analyze the 4 alpha live probe logs to find hidden interactions.

Probes:
  EXTREME: 5 phases (DARK / TIGHT / MEGA_BID / MEGA_ASK / NORMAL)
  SIZE:    5 phases (size 1, 5, 30, 100, 200)
  SHADOW:  2 phases (queue 2nd, then below-best)
  ON_OFF:  alternating 50t ON / 50t OFF

Per probe, breaks down per-phase fills + Mark↔Mark patterns.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = {
    "EXTREME": ROOT / "logs" / "round_4" / "probe_extreme.log",
    "SIZE":    ROOT / "logs" / "round_4" / "probe_size.log",
    "SHADOW":  ROOT / "logs" / "round_4" / "probe_shadow.log",
    "ON_OFF":  ROOT / "logs" / "round_4" / "probe_on_off.log",
}
JSONS = {k: path.with_suffix(".json") for k, path in LOGS.items()}


def parse_trades(log_path):
    with open(log_path, "r", encoding="utf-8") as f:
        raw = f.read()
    start = raw.find('"tradeHistory":[')
    if start < 0:
        return []
    start += len('"tradeHistory":')
    depth = 0
    for i, ch in enumerate(raw[start:]):
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:start + i + 1])
    return []


def phase_for(probe, intra_tick):
    """Map probe + tick → phase name."""
    if probe == "EXTREME":
        if intra_tick < 200:
            return "P1_DARK"
        if intra_tick < 400:
            return "P2_TIGHT_MM"
        if intra_tick < 600:
            return "P3_MEGA_BID"
        if intra_tick < 800:
            return "P4_MEGA_ASK"
        return "P5_NORMAL_MM"
    elif probe == "SIZE":
        if intra_tick < 200:
            return "P1_size1"
        if intra_tick < 400:
            return "P2_size5"
        if intra_tick < 600:
            return "P3_size30"
        if intra_tick < 800:
            return "P4_size100"
        return "P5_size200"
    elif probe == "SHADOW":
        return "P1_AT_BEST" if intra_tick < 500 else "P2_BELOW_BEST"
    elif probe == "ON_OFF":
        cycle = intra_tick // 50
        return "ON" if cycle % 2 == 0 else "OFF"
    return "?"


def main():
    summary_table = []

    for probe_name, log_path in LOGS.items():
        json_path = JSONS[probe_name]
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        profit = data["profit"]
        trades = parse_trades(log_path)
        our_trades = [t for t in trades if t["buyer"] == "SUBMISSION" or t["seller"] == "SUBMISSION"]
        ext_trades = [t for t in trades if t["buyer"] != "SUBMISSION" and t["seller"] != "SUBMISSION"]

        print("\n" + "=" * 110)
        print(f"PROBE: {probe_name}  |  PnL: {profit:+,.0f}  |  Trades: {len(trades)} ({len(our_trades)} us, {len(ext_trades)} Mark↔Mark)")
        print("=" * 110)

        # Per-phase per-counterparty fills
        per_phase_us = defaultdict(lambda: defaultdict(lambda: {"buy": 0, "sell": 0}))
        per_phase_ext = defaultdict(lambda: defaultdict(lambda: {"buy": 0, "sell": 0}))

        for t in trades:
            if t["symbol"] != "VELVETFRUIT_EXTRACT":
                continue
            ts = t["timestamp"]
            intra_tick = ts // 100
            phase = phase_for(probe_name, intra_tick)
            qty = t["quantity"]

            # Our trade
            if t["buyer"] == "SUBMISSION":
                cp = t["seller"]
                per_phase_us[phase][cp]["sell"] += qty  # they sold to us
            elif t["seller"] == "SUBMISSION":
                cp = t["buyer"]
                per_phase_us[phase][cp]["buy"] += qty  # they bought from us
            else:
                # External Mark ↔ Mark
                if t["buyer"]:
                    per_phase_ext[phase][t["buyer"]]["buy"] += qty
                if t["seller"]:
                    per_phase_ext[phase][t["seller"]]["sell"] += qty

        # Print: per phase, who filled us and who Mark↔Mark
        all_phases = sorted(set(list(per_phase_us.keys()) + list(per_phase_ext.keys())))
        for phase in all_phases:
            print(f"\n  --- {phase} ---")
            us = per_phase_us[phase]
            ext = per_phase_ext[phase]
            us_trades_count = sum(s["buy"] + s["sell"] for s in us.values())
            ext_trades_count = sum(s["buy"] + s["sell"] for s in ext.values())
            print(f"    Total in phase: {us_trades_count + ext_trades_count} contracts ({us_trades_count} with us, {ext_trades_count} Mark↔Mark)")
            print(f"    {'CP':>10s}  {'WITH_US_buy':>12s}  {'WITH_US_sell':>12s}  {'EXT_buy':>10s}  {'EXT_sell':>10s}")
            all_marks = set(list(us.keys()) + list(ext.keys()))
            for cp in sorted(all_marks):
                u = us.get(cp, {"buy": 0, "sell": 0})
                e = ext.get(cp, {"buy": 0, "sell": 0})
                if u["buy"] + u["sell"] + e["buy"] + e["sell"] == 0:
                    continue
                print(f"    {cp:>10s}  {u['buy']:>12d}  {u['sell']:>12d}  {e['buy']:>10d}  {e['sell']:>10d}")

        summary_table.append((probe_name, profit, len(our_trades), len(ext_trades)))

    print("\n" + "=" * 110)
    print("SUMMARY")
    print("=" * 110)
    print(f"{'Probe':>12s}  {'PnL':>10s}  {'our_trades':>11s}  {'mark_mark':>11s}")
    for n, pnl, u, e in summary_table:
        print(f"{n:>12s}  {pnl:>+10,.0f}  {u:>11d}  {e:>11d}")


if __name__ == "__main__":
    main()
