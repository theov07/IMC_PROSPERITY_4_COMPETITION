"""Drill into D3 last 5% crash: from +74k (tick 950k) to +20k (tick 999900) = -53k.

Identify:
  - Which products bleed in the last 5%
  - Position evolution per product
  - Mid price moves
  - Trade flow (taker vs maker on our side)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_JSON = ROOT / "artifacts" / "analysis" / "round_4" / "r4_velvet_options_only_3d.json"


def main():
    print(f"Loading baseline {BASELINE_JSON.name}...")
    with open(BASELINE_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    day3 = data["days"][2]
    fills = day3.get("fills", [])
    quotes = day3.get("quotes", [])
    feature_ticks = day3.get("feature_ticks", [])

    print(f"\nD3 has {len(fills):,} fills, {len(quotes):,} quotes, {len(feature_ticks):,} feature ticks")
    if fills:
        print(f"Fill[0] sample keys: {list(fills[0].keys()) if isinstance(fills[0], dict) else type(fills[0])}")
    if feature_ticks:
        ft0 = feature_ticks[0]
        print(f"Feature[0] sample keys: {list(ft0.keys()) if isinstance(ft0, dict) else type(ft0)}")

    # ========================
    # FILLS in the last 5% (tick >= 950000)
    # ========================
    print("\n" + "=" * 100)
    print("D3 LAST 5%: ALL FILLS BETWEEN tick 950,000 to 999,900 (the crash window)")
    print("=" * 100)

    last5 = [f for f in fills if isinstance(f, dict) and f.get("ts", f.get("timestamp", 0)) >= 950000]
    print(f"Total fills in last 5%: {len(last5)}")

    # Group by product
    by_product = {}
    for f in last5:
        sym = f.get("symbol", f.get("product", "?"))
        side = f.get("side", "?")  # BUY/SELL
        qty = f.get("quantity", f.get("qty", 0))
        price = f.get("price", 0)
        passive = f.get("passive", f.get("is_passive", None))
        by_product.setdefault(sym, []).append({"side": side, "qty": qty, "price": price, "passive": passive, "ts": f.get("ts", f.get("timestamp", 0))})

    for sym in sorted(by_product):
        flist = by_product[sym]
        n_buy = sum(1 for f in flist if f["side"] in ("BUY", "buy"))
        n_sell = sum(1 for f in flist if f["side"] in ("SELL", "sell"))
        qty_buy = sum(abs(f["qty"]) for f in flist if f["side"] in ("BUY", "buy"))
        qty_sell = sum(abs(f["qty"]) for f in flist if f["side"] in ("SELL", "sell"))
        n_passive = sum(1 for f in flist if f["passive"] in (True, "true", 1))
        n_aggressive = sum(1 for f in flist if f["passive"] in (False, "false", 0))
        print(
            f"{sym:>22s}: {len(flist):>4d} fills "
            f"({n_buy} buys / {n_sell} sells) "
            f"qty: BUY {qty_buy} / SELL {qty_sell} | "
            f"{n_passive} passive / {n_aggressive} aggressive"
        )

    # ========================
    # FEATURE TICKS — track position + mid in the crash window
    # ========================
    print("\n" + "=" * 100)
    print("D3 LAST 5%: POSITION + MID per product at each 1% checkpoint of crash window")
    print("=" * 100)

    # feature_ticks should have per-tick state. Sample at 950k, 960k, 970k, 980k, 990k, 999k
    if feature_ticks:
        # Try common keys
        sample = feature_ticks[0]
        print(f"Sample feature_tick keys: {list(sample.keys())}")
        if "ts" in sample:
            ts_key = "ts"
        elif "timestamp" in sample:
            ts_key = "timestamp"
        else:
            ts_key = None

        if ts_key:
            # Index by ts
            target_ts = [950000, 960000, 970000, 980000, 990000, 995000, 999000, 999900]
            samples = {}
            for ft in feature_ticks:
                t = ft.get(ts_key)
                if t in target_ts:
                    samples[t] = ft

            for t in target_ts:
                if t in samples:
                    ft = samples[t]
                    print(f"\n--- tick {t:,} ---")
                    # Print all numeric/string fields we have
                    for k, v in ft.items():
                        if isinstance(v, (int, float, str, bool)):
                            print(f"    {k}: {v}")
                        elif isinstance(v, dict):
                            print(f"    {k}: <dict with keys {list(v.keys())[:5]}...>")

    # ========================
    # EQUITY CURVE — exact crash moment (every 1% from 95-100)
    # ========================
    print("\n" + "=" * 100)
    print("D3 EQUITY CURVE — every 0.5% from tick 950k to 999.9k")
    print("=" * 100)
    ec = day3["equity_curve"]
    # Index by ts for quick lookup
    ec_by_ts = {row[0]: row[1] for row in ec}

    print(f"{'tick':>10s}  {'cum PnL':>12s}  {'delta from prev':>16s}")
    print("-" * 50)
    prev = None
    for t in range(950000, 1000000, 5000):
        # Find closest tick
        closest = min(ec_by_ts.keys(), key=lambda x: abs(x - t))
        if abs(closest - t) > 200:
            continue
        v = ec_by_ts[closest]
        delta = (v - prev) if prev is not None else 0
        print(f"{closest:>10,}  {v:>+12,.0f}  {delta:>+16,.0f}")
        prev = v


if __name__ == "__main__":
    main()
