"""Round 3 static data-and-strategy analysis — produces PNG plots.

Run:
    PYTHONPATH=. python -m prosperity.tooling.r3_analysis

Output: artifacts/analysis/round_3/ (8 PNG plots + a summary .txt)

Plots:
  1. spot_underlyings.png       — VELVETFRUIT + HYDROGEL + vol rolling over 3 days
  2. smile_snapshots.png        — smile at start/mid/end of each day (9 snapshots)
  3. iv_heatmap.png             — strike × time heatmap of implied vol
  4. bs_fair_vs_market.png      — BS fair value vs market mid per strike
  5. vol_realized_vs_implied.png— bar chart realized vol vs avg implied vol
  6. option_chain_greeks.png    — delta + vega across strikes at day-0 snapshot
  7. backtest_pos_pnl.png       — position + PnL per product over 3 days (r3_naive_champion)
  8. strategy_comparison.png    — cumulative PnL r3_naive_champion vs naive_base_round_3
"""
from __future__ import annotations

import glob
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from prosperity.options.black_scholes import call_price, call_delta, call_vega
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict


OUTDIR = Path("artifacts/analysis/round_3")
OUTDIR.mkdir(parents=True, exist_ok=True)

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
TICKS_PER_DAY = 10000
# TTE schedule per historical day (from wiki): day 0 = 8d, day 1 = 7d, day 2 = 6d
TTE_MAP = {0: 8.0, 1: 7.0, 2: 6.0}


def load_prices() -> pd.DataFrame:
    """Load all 3 days of prices into a single DataFrame with day_idx + TTE."""
    files = sorted(glob.glob("data/round_3/prices_round_3_day_*.csv"))
    dfs = []
    for f in files:
        day = int(Path(f).stem.split("_")[-1])
        df = pd.read_csv(f, sep=";")
        df["day_idx"] = day
        df["tte_d0"] = TTE_MAP.get(day, 5.0)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def compute_realized_vol(mid_series: pd.Series, window_ticks: int = 2000) -> pd.Series:
    """Rolling realized daily vol, sampled from log returns."""
    rets = np.log(mid_series.astype(float)).diff()
    # Annualize per-tick std → per-day = * sqrt(ticks_per_day)
    rv = rets.rolling(window_ticks, min_periods=200).std() * math.sqrt(TICKS_PER_DAY)
    return rv


# ── Plot 1: Spot underlyings + realized vol ───────────────────────────────────

def plot_spot_underlyings(df: pd.DataFrame):
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    colors = {"VELVETFRUIT_EXTRACT": "#C0392B", "HYDROGEL_PACK": "#2874A6"}
    for p in ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK"]:
        sub = df[df["product"] == p].sort_values(["day_idx", "timestamp"]).reset_index(drop=True)
        t = np.arange(len(sub))
        mid = sub["mid_price"].astype(float)
        rv = compute_realized_vol(mid, 2000)
        axes[0].plot(t, mid, color=colors[p], label=p, lw=0.6)
        axes[1].plot(t, rv * 100, color=colors[p], label=p, lw=0.7)
    # Day boundaries
    for i in range(1, 3):
        axes[0].axvline(i * TICKS_PER_DAY, color="gray", ls="--", alpha=0.4)
        axes[1].axvline(i * TICKS_PER_DAY, color="gray", ls="--", alpha=0.4)
    axes[0].set_title("Underlyings: VELVETFRUIT_EXTRACT & HYDROGEL_PACK (3 days)")
    axes[0].set_ylabel("Mid price")
    axes[0].legend(loc="upper left")
    axes[0].grid(True, alpha=0.3)
    axes[1].set_title("Realized daily vol (rolling 2000-tick window)")
    axes[1].set_xlabel("Tick (concat 3 days)")
    axes[1].set_ylabel("Daily vol (%)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="upper left")
    plt.tight_layout()
    plt.savefig(OUTDIR / "01_spot_underlyings.png", dpi=110)
    plt.close()
    print("  [OK] 01_spot_underlyings.png")


# ── Plot 2: Smile at 9 snapshots ──────────────────────────────────────────────

def plot_smile_snapshots(df: pd.DataFrame):
    fig, axes = plt.subplots(3, 3, figsize=(13, 10), sharex=True, sharey=True)
    for row, day in enumerate([0, 1, 2]):
        day_df = df[df["day_idx"] == day]
        tte = TTE_MAP[day]
        for col, frac in enumerate([0.01, 0.5, 0.99]):
            ax = axes[row, col]
            tick_idx = int(frac * (TICKS_PER_DAY - 1))
            ts = tick_idx * 100  # timestamps are in steps of 100
            snap = day_df[day_df["timestamp"] == ts].set_index("product")["mid_price"]
            S = snap.get("VELVETFRUIT_EXTRACT")
            if S is None or pd.isna(S):
                continue
            xs, ys = [], []
            for K in STRIKES:
                sym = f"VEV_{K}"
                mid = snap.get(sym)
                if pd.isna(mid):
                    continue
                iv = call_implied_vol(float(mid), float(S), K, tte)
                if iv is None or iv <= 0.005 or iv > 0.1:
                    continue
                xs.append(K)
                ys.append(iv * 100)
            ax.plot(xs, ys, "o-", color="#1B4F72", lw=1.5)
            ax.axvline(S, color="red", ls="--", alpha=0.5, label=f"S={S:.0f}")
            ax.set_title(f"Day {day}, ts={ts}  (TTE={tte}d)", fontsize=9)
            ax.grid(True, alpha=0.3)
            if col == 0:
                ax.set_ylabel("IV (% daily)")
            if row == 2:
                ax.set_xlabel("Strike K")
            ax.legend(fontsize=7, loc="upper left")
    fig.suptitle("Volatility smile — 3 days × 3 snapshots (start, mid, end)", fontsize=13)
    plt.tight_layout()
    plt.savefig(OUTDIR / "02_smile_snapshots.png", dpi=110)
    plt.close()
    print("  [OK] 02_smile_snapshots.png")


# ── Plot 3: IV heatmap strike × time ──────────────────────────────────────────

def plot_iv_heatmap(df: pd.DataFrame):
    # Coarse sampling: every 200 ticks → 150 snapshots across 3 days
    step = 200
    snapshots = sorted(df["timestamp"].unique())[::step // 100]
    iv_matrix = np.full((len(STRIKES), len(snapshots) * 3), np.nan)
    col = 0
    for day in [0, 1, 2]:
        day_df = df[df["day_idx"] == day]
        tte = TTE_MAP[day]
        day_snapshots = sorted(day_df["timestamp"].unique())[::step // 100]
        for ts in day_snapshots:
            row = day_df[day_df["timestamp"] == ts].set_index("product")["mid_price"]
            S = row.get("VELVETFRUIT_EXTRACT")
            if S is None or pd.isna(S):
                col += 1
                continue
            for i, K in enumerate(STRIKES):
                mid = row.get(f"VEV_{K}")
                if pd.isna(mid):
                    continue
                iv = call_implied_vol(float(mid), float(S), K, tte)
                if iv is not None and 0.005 <= iv <= 0.1:
                    iv_matrix[i, col] = iv * 100
            col += 1

    fig, ax = plt.subplots(figsize=(13, 5))
    im = ax.imshow(iv_matrix, aspect="auto", cmap="viridis", origin="lower",
                   extent=[0, col, 0, len(STRIKES)])
    ax.set_yticks(np.arange(len(STRIKES)) + 0.5)
    ax.set_yticklabels(STRIKES)
    ax.set_xlabel("Snapshot (3 days concat, every 200 ticks)")
    ax.set_ylabel("Strike K")
    ax.set_title("Implied vol heatmap (strike × time)")
    # Day boundaries
    for i in range(1, 3):
        ax.axvline(i * (col // 3), color="white", ls="--", alpha=0.7)
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("IV (% daily)")
    plt.tight_layout()
    plt.savefig(OUTDIR / "03_iv_heatmap.png", dpi=110)
    plt.close()
    print("  [OK] 03_iv_heatmap.png")


# ── Plot 4: BS fair vs market mid ─────────────────────────────────────────────

def plot_bs_fair_vs_market(df: pd.DataFrame):
    fig, axes = plt.subplots(2, 5, figsize=(15, 7), sharex=False)
    axes_flat = axes.flatten()
    for idx, K in enumerate(STRIKES):
        ax = axes_flat[idx]
        sym = f"VEV_{K}"
        # Build per-day series
        for day in [0, 1, 2]:
            sub = df[df["day_idx"] == day].copy()
            spot = sub[sub["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"]
            opt = sub[sub["product"] == sym].set_index("timestamp")["mid_price"]
            tte = TTE_MAP[day]
            merged = pd.DataFrame({"S": spot, "mkt": opt}).dropna()
            if len(merged) == 0:
                continue
            # Compute BS fair using the aggregate implied vol from all strikes at each ts
            # (simple: use the mid-strike IV as a fair proxy)
            fairs = []
            for ts, r in merged.iterrows():
                # Build smile from all strikes at this ts
                row_all = df[(df["day_idx"] == day) & (df["timestamp"] == ts)].set_index("product")["mid_price"]
                ks, ivs = [], []
                for K2 in STRIKES:
                    m = row_all.get(f"VEV_{K2}")
                    if pd.isna(m):
                        continue
                    iv = call_implied_vol(float(m), float(r["S"]), K2, tte)
                    if iv is not None and 0.005 <= iv <= 0.1:
                        ks.append(K2)
                        ivs.append(iv)
                if len(ks) >= 3:
                    coeffs = fit_smile_poly(ks, ivs, r["S"], tte, degree=2)
                    if coeffs:
                        sigma = smile_predict(K, coeffs, r["S"], tte)
                        sigma = max(0.005, min(0.1, sigma))
                        fairs.append(call_price(r["S"], K, tte, sigma))
                        continue
                fairs.append(np.nan)
            merged["fair"] = fairs
            t = np.arange(len(merged)) + day * TICKS_PER_DAY
            ax.plot(t, merged["mkt"].values, color="#2874A6", lw=0.5, label="Market" if day == 0 else None)
            ax.plot(t, merged["fair"].values, color="#C0392B", lw=0.5, label="BS fair (smile)" if day == 0 else None)
        ax.set_title(f"K={K}", fontsize=9)
        ax.grid(True, alpha=0.3)
        if idx == 0:
            ax.legend(fontsize=7)
    fig.suptitle("BS fair value (smile-interpolated) vs Market mid — per strike, 3 days", fontsize=12)
    plt.tight_layout()
    plt.savefig(OUTDIR / "04_bs_fair_vs_market.png", dpi=110)
    plt.close()
    print("  [OK] 04_bs_fair_vs_market.png")


# ── Plot 5: Realized vs Implied vol bar chart ─────────────────────────────────

def plot_vol_realized_vs_implied(df: pd.DataFrame):
    rv_velvet = np.log(df[df["product"] == "VELVETFRUIT_EXTRACT"]["mid_price"].astype(float)).diff().std() * math.sqrt(TICKS_PER_DAY)
    rv_hydro = np.log(df[df["product"] == "HYDROGEL_PACK"]["mid_price"].astype(float)).diff().std() * math.sqrt(TICKS_PER_DAY)

    # Average implied vol per strike across all days
    iv_per_strike = {K: [] for K in STRIKES}
    for day in [0, 1, 2]:
        day_df = df[df["day_idx"] == day]
        tte = TTE_MAP[day]
        # Sample every 500 ticks
        for ts in range(0, TICKS_PER_DAY * 100, 5000):
            row = day_df[day_df["timestamp"] == ts].set_index("product")["mid_price"]
            S = row.get("VELVETFRUIT_EXTRACT")
            if S is None or pd.isna(S):
                continue
            for K in STRIKES:
                mid = row.get(f"VEV_{K}")
                if pd.isna(mid):
                    continue
                iv = call_implied_vol(float(mid), float(S), K, tte)
                if iv is not None and 0.005 <= iv <= 0.1:
                    iv_per_strike[K].append(iv)
    iv_avg = {K: (np.mean(v) if v else np.nan) for K, v in iv_per_strike.items()}

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax0 = axes[0]
    ax0.bar(["VELVETFRUIT\nrealized", "HYDROGEL\nrealized"], [rv_velvet * 100, rv_hydro * 100],
            color=["#C0392B", "#2874A6"])
    ax0.set_ylabel("Daily vol (%)")
    ax0.set_title("Realized daily vol (underlyings, 3 days)")
    ax0.grid(True, alpha=0.3, axis="y")
    for i, v in enumerate([rv_velvet, rv_hydro]):
        ax0.text(i, v * 100 + 0.05, f"{v*100:.2f}%", ha="center", fontsize=10)

    ax1 = axes[1]
    strikes = list(iv_avg.keys())
    vals = [iv_avg[K] * 100 if not np.isnan(iv_avg[K]) else 0 for K in strikes]
    ax1.bar([str(K) for K in strikes], vals, color="#8E44AD")
    ax1.axhline(rv_velvet * 100, color="red", ls="--", lw=2, label=f"VELVET realized={rv_velvet*100:.2f}%")
    ax1.set_xlabel("Strike")
    ax1.set_ylabel("Avg implied vol (% daily)")
    ax1.set_title("Implied vol per strike vs realized vol")
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(OUTDIR / "05_vol_realized_vs_implied.png", dpi=110)
    plt.close()
    print(f"  [OK] 05_vol_realized_vs_implied.png  (RV_velvet={rv_velvet:.4f}, RV_hydro={rv_hydro:.4f})")


# ── Plot 6: Greeks across strikes at a snapshot ───────────────────────────────

def plot_option_chain_greeks(df: pd.DataFrame):
    day_df = df[df["day_idx"] == 0]
    ts = 0
    row = day_df[day_df["timestamp"] == ts].set_index("product")["mid_price"]
    S = float(row["VELVETFRUIT_EXTRACT"])
    tte = TTE_MAP[0]

    deltas, vegas, prices, fairs, ivs = [], [], [], [], []
    valid_strikes = []
    for K in STRIKES:
        mid = row.get(f"VEV_{K}")
        if pd.isna(mid):
            continue
        iv = call_implied_vol(float(mid), S, K, tte)
        if iv is None:
            continue
        valid_strikes.append(K)
        ivs.append(iv)
        deltas.append(call_delta(S, K, tte, iv))
        vegas.append(call_vega(S, K, tte, iv))
        prices.append(float(mid))
        fairs.append(call_price(S, K, tte, iv))

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    axes[0, 0].plot(valid_strikes, prices, "o-", color="#1B4F72", lw=2, label="Market mid")
    axes[0, 0].axvline(S, color="red", ls="--", alpha=0.4, label=f"S={S:.0f}")
    axes[0, 0].set_title(f"Option chain prices (day 0, ts=0, TTE={tte}d)")
    axes[0, 0].set_xlabel("Strike K")
    axes[0, 0].set_ylabel("Call price")
    axes[0, 0].legend()
    axes[0, 0].grid(True, alpha=0.3)

    axes[0, 1].plot(valid_strikes, [d for d in deltas], "o-", color="#B9770E", lw=2)
    axes[0, 1].axvline(S, color="red", ls="--", alpha=0.4)
    axes[0, 1].set_title("Delta (dC/dS)")
    axes[0, 1].set_xlabel("Strike K")
    axes[0, 1].set_ylabel("Delta")
    axes[0, 1].grid(True, alpha=0.3)

    axes[1, 0].plot(valid_strikes, vegas, "o-", color="#6C3483", lw=2)
    axes[1, 0].axvline(S, color="red", ls="--", alpha=0.4)
    axes[1, 0].set_title("Vega (dC/dσ)")
    axes[1, 0].set_xlabel("Strike K")
    axes[1, 0].set_ylabel("Vega")
    axes[1, 0].grid(True, alpha=0.3)

    axes[1, 1].plot(valid_strikes, [iv * 100 for iv in ivs], "o-", color="#D35400", lw=2)
    axes[1, 1].axvline(S, color="red", ls="--", alpha=0.4)
    axes[1, 1].set_title("Implied vol per strike (smile shape)")
    axes[1, 1].set_xlabel("Strike K")
    axes[1, 1].set_ylabel("IV (% daily)")
    axes[1, 1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUTDIR / "06_option_chain_greeks.png", dpi=110)
    plt.close()
    print("  [OK] 06_option_chain_greeks.png")


# ── Plot 7: Backtest position + PnL (runs backtest & parses JSON) ─────────────

def run_backtest(member: str, force: bool = False) -> Optional[Path]:
    """Run backtest with JSON output. Returns path to JSON or None on failure.

    Skips re-running if JSON already exists (unless force=True).
    """
    out_json = OUTDIR / f"backtest_{member}.json"
    if out_json.exists() and not force:
        print(f"  [skip] {member} JSON already exists ({out_json.stat().st_size // 1024} KB)")
        return out_json
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        sys.executable, "backtest.py",
        "--strategy", member,
        "--round", "3",
        "--days", "0", "1", "2",
        "--match-trades", "realistic",
        "--json-out", str(out_json),
    ]
    try:
        print(f"  [run]  {member}...", flush=True)
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True, timeout=900)
        return out_json if out_json.exists() else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [ERR] backtest {member}: {e}")
        return None


def plot_backtest_pos_pnl(json_path: Path):
    """From fills[] reconstruct position and realized PnL per product over 3 days."""
    with open(json_path, "r") as f:
        data = json.load(f)
    days_data = data.get("days", [])

    # Accumulate per-product series across all days
    prod_pos: Dict[str, List[Tuple[int, int]]] = {}
    prod_pnl: Dict[str, List[Tuple[int, float]]] = {}
    day_offset = 0
    for day_info in days_data:
        day_idx = day_info.get("day", 0)
        fills = day_info.get("fills", [])
        # Ensure each product has at least one entry at start of day
        positions: Dict[str, int] = {}
        pnls: Dict[str, float] = {}
        for f in sorted(fills, key=lambda x: x["timestamp"]):
            sym = f["symbol"]
            qty = f["quantity"] if f["side"] == "BUY" else -f["quantity"]
            positions[sym] = positions.get(sym, 0) + qty
            # Cash PnL: SELL adds price*qty, BUY subtracts price*qty (mark-to-market added later)
            pnls[sym] = pnls.get(sym, 0.0) - f["price"] * qty
            abs_ts = day_offset + f["timestamp"]
            prod_pos.setdefault(sym, []).append((abs_ts, positions[sym]))
            prod_pnl.setdefault(sym, []).append((abs_ts, pnls[sym]))
        day_offset += TICKS_PER_DAY * 100  # 1 day = 10000 ticks × 100 ts_increment

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    palette = plt.cm.tab20.colors
    for i, product in enumerate(sorted(prod_pos.keys())):
        pos_series = prod_pos[product]
        pnl_series = prod_pnl[product]
        if not pos_series:
            continue
        pos_t = [t for t, v in pos_series]
        pos_v = [v for t, v in pos_series]
        pnl_t = [t for t, v in pnl_series]
        pnl_v = [v for t, v in pnl_series]
        axes[0].plot(pos_t, pos_v, color=palette[i % len(palette)], label=product, lw=0.5)
        axes[1].plot(pnl_t, pnl_v, color=palette[i % len(palette)], label=product, lw=0.7)
    # Day boundaries
    for i in range(1, 3):
        axes[0].axvline(i * TICKS_PER_DAY * 100, color="gray", ls="--", alpha=0.4)
        axes[1].axvline(i * TICKS_PER_DAY * 100, color="gray", ls="--", alpha=0.4)
    axes[0].set_title("Position per product (r3_naive_champion, 3 days realistic)")
    axes[0].set_ylabel("Position (units)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=7, ncol=4, loc="upper left")
    axes[0].axhline(0, color="black", lw=0.5)
    axes[1].set_title("Realized cash PnL per product (before mark-to-market)")
    axes[1].set_xlabel("Timestamp (3 days concat)")
    axes[1].set_ylabel("Cumulative cash PnL")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(fontsize=7, ncol=4, loc="upper left")
    axes[1].axhline(0, color="black", lw=0.5)
    plt.tight_layout()
    plt.savefig(OUTDIR / "07_backtest_pos_pnl.png", dpi=110)
    plt.close()
    print("  [OK] 07_backtest_pos_pnl.png")


# ── Plot 8: Strategy comparison ───────────────────────────────────────────────

def plot_strategy_comparison(paths: Dict[str, Path]):
    """Cumulative equity curve across all products, per strategy, over 3 days."""
    fig, ax = plt.subplots(figsize=(13, 6))
    for name, p in paths.items():
        if p is None or not Path(p).exists():
            continue
        with open(p, "r") as f:
            data = json.load(f)
        # Concat equity_curve across 3 days — add day offset
        ts_list: List[int] = []
        pnl_list: List[float] = []
        day_offset = 0
        cum_offset = 0.0
        for day_info in data.get("days", []):
            ec = day_info.get("equity_curve", [])
            if not ec:
                continue
            day_last = 0.0
            for ts, v in ec:
                ts_list.append(ts + day_offset)
                pnl_list.append(cum_offset + v)
                day_last = v
            day_offset += TICKS_PER_DAY * 100
            cum_offset += day_last
        total = data.get("summary", {}).get("total_pnl", 0)
        ax.plot(ts_list, pnl_list, lw=1.5, label=f"{name}  (total={total:,.0f})")
    # Day boundaries
    for i in range(1, 3):
        ax.axvline(i * TICKS_PER_DAY * 100, color="gray", ls="--", alpha=0.4)
    ax.set_title("Cumulative PnL — strategy comparison on Round 3 data (3 days realistic)")
    ax.set_xlabel("Timestamp (3 days concat)")
    ax.set_ylabel("Cumulative PnL")
    ax.grid(True, alpha=0.3)
    ax.axhline(0, color="black", lw=0.5)
    ax.legend(fontsize=10, loc="upper left")
    plt.tight_layout()
    plt.savefig(OUTDIR / "08_strategy_comparison.png", dpi=110)
    plt.close()
    print("  [OK] 08_strategy_comparison.png")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Output directory: {OUTDIR.resolve()}\n")
    print("[step 1] Loading R3 price data...")
    df = load_prices()
    print(f"  Loaded {len(df)} rows across {df['day_idx'].nunique()} days, {df['product'].nunique()} products\n")

    print("[step 2] Data-exploration plots (skipping existing ones)...")
    skip_data = bool(os.environ.get("R3_SKIP_DATA_PLOTS"))
    if not skip_data:
        plot_spot_underlyings(df)
        plot_smile_snapshots(df)
        plot_iv_heatmap(df)
        plot_vol_realized_vs_implied(df)
        plot_option_chain_greeks(df)
        plot_bs_fair_vs_market(df)

    print("\n[step 3] Ensuring backtest JSONs exist for strategy plots...")
    p_champion = run_backtest("r3_naive_champion")
    p_base = run_backtest("naive_base_round_3")

    print("\n[step 4] Strategy plots...")
    if p_champion:
        plot_backtest_pos_pnl(p_champion)
    paths = {
        "r3_naive_champion": p_champion,
        "naive_base_round_3": p_base,
    }
    if any(v for v in paths.values() if v):
        plot_strategy_comparison(paths)

    print(f"\nAll plots written to {OUTDIR.resolve()}")


if __name__ == "__main__":
    main()
