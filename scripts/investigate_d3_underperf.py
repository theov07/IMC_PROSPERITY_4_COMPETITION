"""Investigate why D3 PnL on baseline is 3.4x lower than D1/D2.

D1 = +68,920
D2 = +68,340
D3 = +20,452 (-71% vs D1/D2)

Hypotheses to test:
  1. Lower traded volume on D3 (less flow → less spread captured)
  2. Higher adverse selection on D3 (passive fills toxic)
  3. Different mid price dynamics (regime change, larger jumps)
  4. Position limit hit too early (stuck inventory)
  5. Specific product underperforms (VELVET vs options)
  6. Equity curve drawdown on D3 (one bad event)
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
BASELINE_JSON = ROOT / "artifacts" / "analysis" / "round_4" / "r4_velvet_options_only_3d.json"


def fmt(v, w=10, d=0):
    if v is None:
        return f"{'n/a':>{w}s}"
    if isinstance(v, float):
        return f"{v:>{w},.{d}f}"
    return f"{v:>{w},}"


def main():
    print(f"Loading baseline {BASELINE_JSON.name} ({BASELINE_JSON.stat().st_size/1e6:.1f}MB)...")
    with open(BASELINE_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    days = data["days"]
    assert len(days) == 3

    # ===== Per-day robustness comparison =====
    print("\n" + "=" * 100)
    print("PER-DAY ROBUSTNESS METRICS (baseline = r4_velvet_options_only)")
    print("=" * 100)

    rob_keys = [
        ("total_pnl", "PnL", 0),
        ("traded_volume", "TradedVol", 0),
        ("aggressive_qty", "AggQty", 0),
        ("passive_qty", "PassQty", 0),
        ("aggressive_trades", "AggTrades", 0),
        ("passive_trades", "PassTrades", 0),
        ("submitted_volume", "SubmVol", 0),
        ("fill_efficiency", "FillEff", 4),
        ("aggressive_share", "AggShare", 3),
        ("passive_adverse_rate", "AdvRate", 3),
        ("passive_post_fill_edge", "PostFillEdge", 3),
        ("avg_abs_position_ratio", "AvgPosRatio", 3),
        ("near_limit_tick_ratio", "NearLimitRatio", 3),
        ("max_drawdown", "MaxDD", 0),
        ("buy_filled_qty", "BuyFilled", 0),
        ("sell_filled_qty", "SellFilled", 0),
        ("bid_fill_efficiency", "BidFillEff", 4),
        ("ask_fill_efficiency", "AskFillEff", 4),
    ]

    print(f"{'Metric':>20s}  {'D1':>14s}  {'D2':>14s}  {'D3':>14s}  {'D3/D1':>8s}  {'D3-D1':>14s}")
    print("-" * 100)
    for key, label, decimals in rob_keys:
        vals = []
        for day in days:
            if key == "total_pnl":
                vals.append(day["pnl"])
            else:
                vals.append(day["robustness"].get(key))

        if all(v is None for v in vals):
            continue
        # ratio D3/D1
        ratio = (vals[2] / vals[0]) if vals[0] not in (None, 0) else None
        diff = (vals[2] - vals[0]) if (vals[2] is not None and vals[0] is not None) else None
        print(
            f"{label:>20s}  "
            f"{fmt(vals[0], 14, decimals)}  "
            f"{fmt(vals[1], 14, decimals)}  "
            f"{fmt(vals[2], 14, decimals)}  "
            f"{(f'{ratio:.2f}x' if ratio is not None else 'n/a'):>8s}  "
            f"{fmt(diff, 14, decimals)}"
        )

    # ===== Per-product per-day PnL =====
    print("\n" + "=" * 100)
    print("PER-PRODUCT PER-DAY PnL")
    print("=" * 100)
    prods = list(days[0]["product_summaries"].keys())
    relevant = [p for p in prods if any(days[i]["product_summaries"][p]["pnl"] for i in range(3))]
    print(f"{'Product':>22s}  {'D1':>10s}  {'D2':>10s}  {'D3':>10s}  {'D3-D1':>10s}  {'D3 share':>10s}")
    print("-" * 100)
    for p in relevant:
        vals = [days[i]["product_summaries"][p]["pnl"] for i in range(3)]
        diff = vals[2] - vals[0]
        share = vals[2] / sum(v for v in vals if v != 0) * 100 if sum(vals) else 0
        print(
            f"{p:>22s}  "
            f"{fmt(vals[0], 10)}  {fmt(vals[1], 10)}  {fmt(vals[2], 10)}  "
            f"{fmt(diff, 10)}  {fmt(share, 10, 1)}"
        )

    # ===== Per-product trade count per day =====
    print("\n" + "=" * 100)
    print("PER-PRODUCT TRADE COUNT PER DAY (volume = how often we got filled)")
    print("=" * 100)
    print(f"{'Product':>22s}  {'D1 trd':>8s}  {'D2 trd':>8s}  {'D3 trd':>8s}  {'D1 vol':>10s}  {'D2 vol':>10s}  {'D3 vol':>10s}")
    print("-" * 100)
    for p in relevant:
        td = [days[i]["product_summaries"][p].get("trades", 0) for i in range(3)]
        tv = [days[i]["product_summaries"][p].get("traded_volume", 0) for i in range(3)]
        print(
            f"{p:>22s}  "
            f"{fmt(td[0], 8)}  {fmt(td[1], 8)}  {fmt(td[2], 8)}  "
            f"{fmt(tv[0], 10)}  {fmt(tv[1], 10)}  {fmt(tv[2], 10)}"
        )

    # ===== Per-product max position per day =====
    print("\n" + "=" * 100)
    print("PER-PRODUCT MAX |POSITION| PER DAY (proxy for inventory pressure)")
    print("=" * 100)
    print(f"{'Product':>22s}  {'D1 maxpos':>10s}  {'D2 maxpos':>10s}  {'D3 maxpos':>10s}")
    print("-" * 100)
    for p in relevant:
        vals = [days[i]["product_summaries"][p].get("max_abs_position", 0) for i in range(3)]
        print(f"{p:>22s}  {fmt(vals[0], 10)}  {fmt(vals[1], 10)}  {fmt(vals[2], 10)}")

    # ===== Equity curve per day — find drawdowns =====
    print("\n" + "=" * 100)
    print("EQUITY CURVE PROFILE PER DAY (PnL trajectory; format: [ts, pnl])")
    print("=" * 100)
    for i, label in enumerate(["D1", "D2", "D3"]):
        ec = days[i].get("equity_curve", [])
        if not ec:
            continue
        # ec is list of [ts, pnl]
        pnls = [row[1] for row in ec]
        max_pnl = max(pnls)
        end_pnl = pnls[-1]
        min_pnl = min(pnls)
        # checkpoints at 0/10/25/50/75/99% of the day
        cps = [pnls[int(len(pnls) * f)] for f in (0.10, 0.25, 0.50, 0.75, 0.99)]
        # max drawdown intra-day
        peak = pnls[0]
        max_dd = 0
        for v in pnls:
            if v > peak:
                peak = v
            max_dd = max(max_dd, peak - v)
        print(
            f"{label}: max={max_pnl:>+10,.0f}  min={min_pnl:>+10,.0f}  end={end_pnl:>+10,.0f}  "
            f"intraday_DD={max_dd:>10,.0f}"
        )
        print(
            f"     checkpoints (10/25/50/75/99%): "
            + " | ".join(f"{c:>+8,.0f}" for c in cps)
        )

    # ===== D3 specific: when does PnL turn negative? =====
    print("\n" + "=" * 100)
    print("D3 EQUITY CURVE — every 5% checkpoint to find the bleeding window")
    print("=" * 100)
    ec3 = days[2]["equity_curve"]
    pnls3 = [row[1] for row in ec3]
    n = len(pnls3)
    print(f"{'tick %':>8s}  {'tick':>10s}  {'cum PnL':>12s}  {'delta vs prev':>14s}")
    print("-" * 60)
    prev = 0
    for pct in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]:
        idx = min(int(n * pct / 100), n - 1)
        ts = ec3[idx][0]
        v = pnls3[idx]
        delta = v - prev
        print(f"{pct:>7d}%  {ts:>10,}  {v:>+12,.0f}  {delta:>+14,.0f}")
        prev = v

    # ===== Per-product per-day passive adverse rate =====
    print("\n" + "=" * 100)
    print("PER-PRODUCT PER-DAY PASSIVE ADVERSE RATE (% of passive fills that went against us)")
    print("=" * 100)
    print(f"{'Product':>22s}  {'D1':>8s}  {'D2':>8s}  {'D3':>8s}  {'D3-D1':>8s}")
    print("-" * 100)
    for p in relevant:
        vals = []
        for i in range(3):
            ps = days[i]["product_summaries"][p].get("robustness", {})
            vals.append(ps.get("passive_adverse_rate"))
        v_str = lambda v: f"{v*100:>6.1f}%" if v is not None else "n/a"
        diff = (vals[2] - vals[0]) * 100 if (vals[2] is not None and vals[0] is not None) else None
        print(
            f"{p:>22s}  {v_str(vals[0]):>8s}  {v_str(vals[1]):>8s}  {v_str(vals[2]):>8s}  "
            f"{(f'{diff:+.1f}pp' if diff is not None else 'n/a'):>8s}"
        )

    # ===== Per-product per-day post-fill edge (markout proxy) =====
    print("\n" + "=" * 100)
    print("PER-PRODUCT PER-DAY PASSIVE POST-FILL EDGE (markout in ticks; >0 = good)")
    print("=" * 100)
    print(f"{'Product':>22s}  {'D1':>10s}  {'D2':>10s}  {'D3':>10s}  {'D3-D1':>10s}")
    print("-" * 100)
    for p in relevant:
        vals = []
        for i in range(3):
            ps = days[i]["product_summaries"][p].get("robustness", {})
            vals.append(ps.get("passive_post_fill_edge"))
        v_str = lambda v: f"{v:+.2f}" if v is not None else "n/a"
        diff = (vals[2] - vals[0]) if (vals[2] is not None and vals[0] is not None) else None
        print(
            f"{p:>22s}  {v_str(vals[0]):>10s}  {v_str(vals[1]):>10s}  {v_str(vals[2]):>10s}  "
            f"{(f'{diff:+.2f}' if diff is not None else 'n/a'):>10s}"
        )


if __name__ == "__main__":
    main()
