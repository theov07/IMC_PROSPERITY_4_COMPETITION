"""Simulate pair_skip(COTTON-NYLON) on the live data and check what orders we'd post.

Tests whether our strategy decisions are deterministic given identical mids,
which they should be.
"""

import json
import math
from collections import defaultdict


def online_z(value: float, buf: list, window: int) -> float:
    buf.append(value)
    if len(buf) > window:
        buf[:] = buf[-window:]
    if len(buf) < 30:
        return 0.0
    n = len(buf)
    mu = sum(buf) / n
    var = sum((x - mu) ** 2 for x in buf) / max(n - 1, 1)
    std = math.sqrt(var)
    if std < 1e-9:
        return 0.0
    return (value - mu) / std


def simulate(log_path: str, target_sym: str, partner_sym: str,
             pair_thresh: float = 1.25, z_window: int = 300,
             tighten: int = 1, hard_pause: int = 9, size: int = 5):
    with open(log_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    al = data["activitiesLog"]
    rows_by_ts = defaultdict(dict)
    for line in al.strip().split("\n")[1:]:
        parts = line.split(";")
        if len(parts) < 16:
            continue
        ts = int(parts[1])
        prod = parts[2]
        if prod not in (target_sym, partner_sym):
            continue
        try:
            bb = float(parts[3]) if parts[3] else None
            ba = float(parts[9]) if parts[9] else None
            mid = float(parts[15]) if parts[15] else None
        except ValueError:
            continue
        rows_by_ts[ts][prod] = (bb, ba, mid)

    z_self_buf = []
    z_partner_buf = []
    decisions = []  # (ts, post_bid, post_ask, pair_z, bid_p, ask_p)

    for ts in sorted(rows_by_ts.keys()):
        d = rows_by_ts[ts]
        if target_sym not in d or partner_sym not in d:
            continue
        bb, ba, mid = d[target_sym]
        _, _, partner_mid = d[partner_sym]
        if bb is None or ba is None or mid is None or partner_mid is None:
            continue
        spread = ba - bb
        bid_p = bb + tighten if spread >= 2 else bb
        ask_p = ba - tighten if spread >= 2 else ba

        zp = online_z(mid, z_self_buf, z_window)
        zq = online_z(partner_mid, z_partner_buf, z_window)
        partner_sign = -1.0
        pair_z = zp - partner_sign * zq

        post_bid = True
        post_ask = True
        if pair_z > pair_thresh:
            post_bid = False
        elif pair_z < -pair_thresh:
            post_ask = False

        decisions.append((ts, post_bid, post_ask, pair_z, bid_p, ask_p))

    return decisions


if __name__ == "__main__":
    paths = {
        "v2090": "C:/Users/LéoRENAULT/Downloads/log_v2090/563187.log",
        "v2640": "C:/Users/LéoRENAULT/Downloads/best_log/564793.log",
    }

    decisions = {}
    for name, p in paths.items():
        decisions[name] = simulate(p, "SLEEP_POD_COTTON", "SLEEP_POD_NYLON")

    print(f"v2090 decisions: {len(decisions['v2090'])}")
    print(f"v2640 decisions: {len(decisions['v2640'])}")

    # Compare decisions
    diff_count = 0
    for d90, d64 in zip(decisions["v2090"], decisions["v2640"]):
        if d90 != d64:
            diff_count += 1
            if diff_count <= 5:
                print(f"DIFF at ts={d90[0]}: v2090={d90[1:]}, v2640={d64[1:]}")
    print(f"Total decision differences: {diff_count}")

    # Did pair_skip skip BID at ts=32400?
    for d in decisions["v2090"]:
        if d[0] == 32400:
            print(f"\nv2090 @ ts=32400: post_bid={d[1]}, pair_z={d[3]:.3f}")
    for d in decisions["v2640"]:
        if d[0] == 32400:
            print(f"v2640 @ ts=32400: post_bid={d[1]}, pair_z={d[3]:.3f}")
