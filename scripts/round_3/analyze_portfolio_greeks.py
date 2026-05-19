"""Portfolio greeks diagnostic — reconstruct per-tick total delta/gamma/vega/theta
exposure for a backtest variant. Reveals when portfolio risk concentrates and
what's driving it.

Usage:
  python scripts/round_3/analyze_portfolio_greeks.py [variant_name]

Outputs:
  artifacts/analysis/round_3_option_velvet/greeks/
    portfolio_greeks_<variant>_day_X.png   (4-panel plot per day)
    portfolio_greeks_summary.csv           (per-day aggregates)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from prosperity.options.black_scholes import call_delta, call_gamma, call_theta, call_vega
from prosperity.options.implied_vol import call_implied_vol

ANA = ROOT / "artifacts" / "analysis" / "round_3"
DATA = ROOT / "data" / "round_3"
OUT = ROOT / "artifacts" / "analysis" / "round_3_option_velvet" / "greeks"
TTE_BY_DAY = {0: 8.0, 1: 7.0, 2: 6.0}


def reconstruct_per_strike_position(fills_per_strike: dict, day: int) -> dict:
    """Map strike → list of (timestamp, position) after each fill."""
    result = {}
    for strike, fills in fills_per_strike.items():
        fills_sorted = sorted(fills, key=lambda f: f["timestamp"])
        pos = 0
        series = []
        for f in fills_sorted:
            qty = f["quantity"] if f["side"] == "BUY" else -f["quantity"]
            pos += qty
            series.append((f["timestamp"], pos))
        result[strike] = series
    return result


def position_at_ts(series: list, ts: int) -> int:
    """Return position at given ts (last fill at or before ts)."""
    pos = 0
    for s_ts, s_pos in series:
        if s_ts > ts:
            break
        pos = s_pos
    return pos


def main():
    variant = sys.argv[1] if len(sys.argv) > 1 else "v38_drop_bad"
    json_path = ANA / f"r3_velvet_options_max3d_{variant}_3d.json"
    if not json_path.exists():
        print(f"Not found: {json_path}")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Analyzing portfolio greeks for {variant}...")

    with json_path.open() as fh:
        d = json.load(fh)

    summary_rows = []
    for day_idx, day_data in enumerate(d["days"]):
        day = day_data["day"]
        # Day might be string or int
        try: day_int = int(day)
        except: day_int = day_idx
        T0 = TTE_BY_DAY.get(day_int, TTE_BY_DAY[day_idx])
        day = day_int
        # Group fills by strike
        fills_per_strike = {}
        for f in day_data.get("fills", []):
            sym = f["symbol"]
            if not sym.startswith("VEV_"):
                continue
            try:
                K = int(sym.replace("VEV_", ""))
            except ValueError:
                continue
            fills_per_strike.setdefault(K, []).append(f)

        if not fills_per_strike:
            continue

        # Build position series per strike
        pos_series = reconstruct_per_strike_position(fills_per_strike, day)

        # Sample timestamps every 2000 ticks (50 samples per day)
        sample_ts = list(range(0, 999900, 20000))

        # Load underlying spot
        df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
        velvet = df[df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"]

        # Per-tick portfolio greeks
        ts_list, deltas, gammas, vegas, thetas = [], [], [], [], []
        for ts in sample_ts:
            S_arr = velvet[(velvet.index <= ts)]
            if S_arr.empty: continue
            S = S_arr.iloc[-1]
            T = max(0.01, T0 - ts / 1_000_000.0)

            d_total = g_total = v_total = t_total = 0.0
            for K, series in pos_series.items():
                pos = position_at_ts(series, ts)
                if pos == 0: continue
                # Get current option mid for IV
                df_K = df[(df["product"] == f"VEV_{K}") & (df["timestamp"] <= ts)]
                if df_K.empty: continue
                opt_mid = df_K.iloc[-1]["mid_price"]
                iv = call_implied_vol(opt_mid, S, K, T, sigma_init=0.0125)
                if iv is None or iv <= 0: continue
                d_total += pos * call_delta(S, K, T, iv)
                g_total += pos * call_gamma(S, K, T, iv)
                v_total += pos * call_vega(S, K, T, iv)
                t_total += pos * call_theta(S, K, T, iv)
            ts_list.append(ts)
            deltas.append(d_total)
            gammas.append(g_total)
            vegas.append(v_total)
            thetas.append(t_total)

        if not ts_list:
            continue

        # Plot 4-panel
        fig, axes = plt.subplots(2, 2, figsize=(14, 8))
        axes[0, 0].plot(ts_list, deltas, lw=1.2)
        axes[0, 0].set_title(f"Portfolio DELTA — Day {day}")
        axes[0, 0].axhline(0, color="r", lw=0.5, ls="--")
        axes[0, 0].grid(alpha=0.3)

        axes[0, 1].plot(ts_list, gammas, lw=1.2, color="green")
        axes[0, 1].set_title(f"Portfolio GAMMA — Day {day}")
        axes[0, 1].axhline(0, color="r", lw=0.5, ls="--")
        axes[0, 1].grid(alpha=0.3)

        axes[1, 0].plot(ts_list, vegas, lw=1.2, color="orange")
        axes[1, 0].set_title(f"Portfolio VEGA — Day {day}")
        axes[1, 0].axhline(0, color="r", lw=0.5, ls="--")
        axes[1, 0].grid(alpha=0.3)

        axes[1, 1].plot(ts_list, thetas, lw=1.2, color="purple")
        axes[1, 1].set_title(f"Portfolio THETA — Day {day}")
        axes[1, 1].axhline(0, color="r", lw=0.5, ls="--")
        axes[1, 1].grid(alpha=0.3)

        plt.suptitle(f"{variant} — Portfolio Greeks (Day {day})")
        plt.tight_layout()
        plt.savefig(OUT / f"portfolio_greeks_{variant}_day_{day}.png", dpi=110)
        plt.close(fig)

        # Aggregate stats
        avg_d = np.mean(deltas) if deltas else 0
        max_d = max(np.max(deltas), abs(np.min(deltas))) if deltas else 0
        avg_g = np.mean(gammas) if gammas else 0
        avg_v = np.mean(vegas) if vegas else 0
        avg_t = np.mean(thetas) if thetas else 0

        summary_rows.append({
            "variant": variant, "day": day,
            "avg_delta": round(avg_d, 1),
            "max_abs_delta": round(max_d, 1),
            "avg_gamma": round(avg_g, 4),
            "avg_vega": round(avg_v, 0),
            "avg_theta": round(avg_t, 1),
        })

    if summary_rows:
        df_summary = pd.DataFrame(summary_rows)
        print("\n", df_summary.to_string(index=False))
        out_csv = OUT / "portfolio_greeks_summary.csv"
        if out_csv.exists():
            existing = pd.read_csv(out_csv)
            df_summary = pd.concat([existing[existing["variant"] != variant], df_summary], ignore_index=True)
        df_summary.to_csv(out_csv, index=False)
        print(f"\n→ {out_csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
