"""Per-asset PnL + DD analysis for backtest results.

Reconstructs per-product equity curve from fills + price data, computes:
  - Per-product realized PnL
  - Per-product max drawdown (absolute + as % of peak)
  - Per-product turnover and capital deployed
  - Risk-adjusted metrics: PnL/DD per product

Output: artifacts/analysis/round_3_option_velvet/per_asset_dd.csv + console table.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ANA = ROOT / "artifacts" / "analysis" / "round_3"
OUT = ROOT / "artifacts" / "analysis" / "round_3_option_velvet"
DATA = ROOT / "data" / "round_3"

VARIANTS = [
    ("v24", "r3_velvet_options_max3d_v24_r2velvet_zskip_3d.json"),
    ("v32 (IV gate)", "r3_velvet_options_max3d_v32_iv_gate_3d.json"),
    ("v33 (per-strike z)", "r3_velvet_options_max3d_v33_per_strike_z_3d.json"),
    ("v34 (combo)", "r3_velvet_options_max3d_v34_combined_3d.json"),
    ("v35 (4500 z=1.0)", "r3_velvet_options_max3d_v35_per_strike_z_rev_3d.json"),
]


def reconstruct_pnl_series(fills, price_data):
    """Given fills (list of {ts, side, price, qty}) and price_data {ts→mid},
    return per-tick (timestamp, realized_pnl, mtm_pnl, total_pnl, position).
    """
    # Sort fills by timestamp
    fills = sorted(fills, key=lambda f: f["timestamp"])

    # Position + cash tracking
    position = 0
    cash = 0.0
    series = []

    fill_idx = 0
    for ts, mid in price_data:
        # Apply all fills at or before this ts
        while fill_idx < len(fills) and fills[fill_idx]["timestamp"] <= ts:
            f = fills[fill_idx]
            qty_signed = f["quantity"] if f["side"] == "BUY" else -f["quantity"]
            cash -= qty_signed * f["price"]
            position += qty_signed
            fill_idx += 1
        mtm = position * mid
        total = cash + mtm
        series.append((ts, total, position, cash, mtm))
    return series


def per_asset_dd_for_variant(json_path: Path) -> pd.DataFrame:
    """Compute per-asset DD across all 3 days for a backtest variant."""
    with json_path.open() as fh:
        d = json.load(fh)

    # Collect per-asset fills across all days, compute PnL time series
    assets = set()
    for day in d["days"]:
        for f in day.get("fills", []):
            assets.add(f["symbol"])

    rows = []
    for asset in sorted(assets):
        # Concat fills across days, but offset each day's ts by day_idx*1M for continuity
        all_fills = []
        all_prices = []
        for day_idx, day in enumerate(d["days"]):
            day_fills = [f for f in day.get("fills", []) if f["symbol"] == asset]
            for f in day_fills:
                all_fills.append({**f, "timestamp": f["timestamp"] + day_idx * 10_000_000})

            # Load price data for this asset on this day
            try:
                df = pd.read_csv(DATA / f"prices_round_3_day_{day['day']}.csv", sep=";")
                sub = df[df["product"] == asset].sort_values("timestamp")
                for _, r in sub.iterrows():
                    all_prices.append((int(r.timestamp) + day_idx * 10_000_000, r.mid_price))
            except Exception:
                continue

        if not all_fills or not all_prices:
            continue

        series = reconstruct_pnl_series(all_fills, all_prices)
        if not series:
            continue

        pnls = [t[1] for t in series]
        positions = [t[2] for t in series]

        peak = pnls[0]
        max_dd = 0.0
        peak_at_dd = 0.0
        for p in pnls:
            if p > peak:
                peak = p
            dd = peak - p
            if dd > max_dd:
                max_dd = dd
                peak_at_dd = peak

        final_pnl = pnls[-1]
        max_pos = max(abs(p) for p in positions) if positions else 0
        # Capital proxy: max_pos × avg price
        avg_price = sum(p[1] for p in all_prices) / len(all_prices)
        capital_proxy = max_pos * avg_price

        # Risk metrics
        pnl_per_dd = final_pnl / max_dd if max_dd > 0 else float("inf")
        dd_pct_of_capital = max_dd / capital_proxy * 100 if capital_proxy > 0 else 0
        pnl_pct_of_capital = final_pnl / capital_proxy * 100 if capital_proxy > 0 else 0

        rows.append({
            "asset": asset,
            "final_pnl": round(final_pnl, 0),
            "max_dd": round(max_dd, 0),
            "pnl_per_dd": round(pnl_per_dd, 2) if max_dd > 0 else None,
            "max_pos": max_pos,
            "capital_proxy": round(capital_proxy, 0),
            "dd_pct_capital": round(dd_pct_of_capital, 2),
            "pnl_pct_capital": round(pnl_pct_of_capital, 2),
        })
    return pd.DataFrame(rows).sort_values("final_pnl", ascending=False)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    all_dfs = {}
    for label, fname in VARIANTS:
        path = ANA / fname
        if not path.exists():
            print(f"missing: {label}")
            continue
        print(f"\n{'='*100}")
        print(f"=== {label} per-asset breakdown ===")
        print(f"{'='*100}")
        df = per_asset_dd_for_variant(path)
        print(df.to_string(index=False))
        all_dfs[label] = df
        df.to_csv(OUT / f"per_asset_dd_{label.replace(' ','_').replace('(','').replace(')','').replace('/','-')}.csv", index=False)

    # Aggregate cross-variant comparison: per-asset DD comparison
    print("\n" + "="*100)
    print("CROSS-VARIANT COMPARISON — per-asset PnL and DD")
    print("="*100)
    assets = sorted(set().union(*[set(df["asset"].tolist()) for df in all_dfs.values()]))
    for asset in assets:
        print(f"\n--- {asset} ---")
        print(f"{'Variant':<25} {'PnL':>10} {'maxDD':>10} {'PnL/DD':>8} {'DD%cap':>8} {'PnL%cap':>9}")
        for label, df in all_dfs.items():
            row = df[df["asset"] == asset]
            if row.empty:
                continue
            r = row.iloc[0]
            ratio = r["pnl_per_dd"] if r["pnl_per_dd"] is not None else float("inf")
            print(f"{label:<25} {r['final_pnl']:>10,.0f} {r['max_dd']:>10,.0f} "
                  f"{ratio:>8.2f} {r['dd_pct_capital']:>7.2f}% {r['pnl_pct_capital']:>8.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
