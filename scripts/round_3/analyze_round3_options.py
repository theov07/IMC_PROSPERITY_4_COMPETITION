"""Comprehensive analysis suite for Round 3 options + VELVET.

Outputs to artifacts/analysis/round_3_option_velvet/:
  smiles/        — daily volatility smile snapshots (poly fit + SVI fit overlaid)
  iv_timeseries/ — per-strike IV time series, IV residual time series
  outliers/      — IV residual histograms, top outlier events
  vega/          — vega per-strike, gamma per-strike, exposure analysis
  svi/           — SVI fit parameters per day, fit comparison vs polynomial
  velvet/        — VELVET path, return distribution, realized vol
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

from prosperity.options.black_scholes import call_delta, call_gamma, call_price, call_vega
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.svi import fit_svi, svi_iv, svi_r2, svi_residuals

OUT = ROOT / "artifacts" / "analysis" / "round_3_option_velvet"
DATA = ROOT / "data" / "round_3"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
DAYS = [0, 1, 2]
TTE_BY_DAY = {0: 8.0, 1: 7.0, 2: 6.0}   # days remaining at session start
TICKS_PER_DAY = 10000
TS_INCREMENT = 100


# ─── Data loading ────────────────────────────────────────────────────────────

def load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
    return df


def get_velvet(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp").sort_index()


def get_strike(df: pd.DataFrame, K: int) -> pd.DataFrame:
    return df[df["product"] == f"VEV_{K}"].set_index("timestamp").sort_index()


def compute_iv_for_strike(df_strike: pd.DataFrame, df_velvet: pd.DataFrame, K: int, T0: float) -> pd.DataFrame:
    """Compute per-tick IV for a strike (annualized)."""
    aligned = df_strike[["mid_price"]].rename(columns={"mid_price": "opt_mid"}).join(
        df_velvet[["mid_price"]].rename(columns={"mid_price": "spot"}),
        how="inner",
    )
    rows = []
    for ts, row in aligned.iterrows():
        # TTE in days at this ts
        T = max(0.01, T0 - ts / 1_000_000.0)
        iv_per_day = call_implied_vol(row.opt_mid, row.spot, K, T, sigma_init=0.0125)
        if iv_per_day is None or iv_per_day <= 0:
            continue
        iv_ann = iv_per_day * math.sqrt(252.0)
        rows.append((ts, T, row.spot, row.opt_mid, iv_per_day, iv_ann,
                     math.log(K / row.spot) / math.sqrt(T)))
    return pd.DataFrame(rows, columns=["timestamp", "T", "spot", "opt_mid", "iv_day", "iv_ann", "moneyness"]).set_index("timestamp")


# ─── Plot helpers ────────────────────────────────────────────────────────────

def plot_smile_with_fits(day: int, all_iv: dict, T_avg: float, out_path: Path):
    """One smile plot per day with polynomial degree 2 fit + SVI fit."""
    fig, ax = plt.subplots(figsize=(12, 7))
    all_m, all_iv_flat = [], []
    color_map = plt.cm.tab10
    for i, K in enumerate(STRIKES):
        if K not in all_iv: continue
        df = all_iv[K]
        if df.empty: continue
        ax.scatter(df.moneyness, df.iv_ann, s=4, alpha=0.4, label=f"K={K}", color=color_map(i % 10))
        all_m.extend(df.moneyness.tolist())
        all_iv_flat.extend(df.iv_ann.tolist())

    if len(all_m) < 5:
        plt.close(fig); return

    # Polynomial fit
    coeffs = np.polyfit(all_m, all_iv_flat, deg=2)
    m_grid = np.linspace(min(all_m), max(all_m), 200)
    poly_fit = np.polyval(coeffs, m_grid)
    ax.plot(m_grid, poly_fit, "k-", lw=2,
            label=f"poly2 fit: {coeffs[0]:.3f}m² + {coeffs[1]:.3f}m + {coeffs[2]:.3f}")

    # SVI fit (in per-day vol)
    iv_day = [iv / math.sqrt(252.0) for iv in all_iv_flat]
    svi_params = fit_svi(all_m, iv_day, T_avg)
    if svi_params:
        svi_grid = [svi_iv(k, T_avg, *svi_params) * math.sqrt(252.0) for k in m_grid]
        r2 = svi_r2(all_m, iv_day, T_avg, svi_params)
        a, b, rho, mu, sig = svi_params
        ax.plot(m_grid, svi_grid, "r--", lw=2,
                label=f"SVI fit: a={a:.3f} b={b:.3f} ρ={rho:.2f} m={mu:.2f} σ={sig:.2f} (R²={r2:.4f})")

    # Polynomial R²
    poly_r2 = 1 - np.sum((np.array(all_iv_flat) - np.polyval(coeffs, all_m)) ** 2) / np.sum((np.array(all_iv_flat) - np.mean(all_iv_flat)) ** 2)
    ax.set_title(f"Volatility smile — Day {day} (poly2 R²={poly_r2:.4f})")
    ax.set_xlabel("moneyness  m = log(K/S) / √T")
    ax.set_ylabel("implied vol (annualized)")
    ax.legend(loc="upper center", ncol=4, fontsize=8)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_iv_timeseries_per_strike(all_iv: dict, day: int, out_dir: Path):
    """Time series of IV per strike."""
    fig, axes = plt.subplots(3, 3, figsize=(15, 9))
    axes = axes.flatten()
    plot_strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000]
    for ax, K in zip(axes, plot_strikes):
        if K not in all_iv: continue
        df = all_iv[K]
        if df.empty: continue
        ax.plot(df.index, df.iv_ann, lw=0.6, alpha=0.8)
        ax.set_title(f"VEV_{K} — IV(annual)")
        ax.set_ylim(0, max(0.5, df.iv_ann.quantile(0.99) * 1.1))
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=7)
    plt.suptitle(f"IV time series — Day {day}")
    plt.tight_layout()
    plt.savefig(out_dir / f"iv_timeseries_day_{day}.png", dpi=110)
    plt.close(fig)


def plot_iv_residuals(all_iv: dict, day: int, T_avg: float, out_dir: Path):
    """For each tick, fit smile and compute residual = iv - fitted_iv. Plot per-strike."""
    # Aggregate timestamps where ALL strikes have data
    all_timestamps = sorted(set.intersection(*(set(df.index) for df in all_iv.values() if not df.empty)))
    if len(all_timestamps) < 100:
        return None

    residual_rows = []
    for ts in all_timestamps:
        ks, ivs_day = [], []
        for K in STRIKES:
            if K not in all_iv: continue
            df = all_iv[K]
            if ts not in df.index: continue
            row = df.loc[ts]
            ks.append(row.moneyness)
            ivs_day.append(row.iv_day)
        if len(ks) < 6: continue
        # Fit polynomial degree 2
        coeffs = np.polyfit(ks, ivs_day, deg=2)
        for K, k, iv in zip(STRIKES, ks, ivs_day):
            fitted = np.polyval(coeffs, k)
            residual_rows.append((ts, K, iv - fitted))
    if not residual_rows: return None
    rdf = pd.DataFrame(residual_rows, columns=["timestamp", "K", "residual_iv_day"])

    # Histogram per strike
    fig, axes = plt.subplots(3, 3, figsize=(15, 9))
    axes = axes.flatten()
    plot_strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000]
    for ax, K in zip(axes, plot_strikes):
        sub = rdf[rdf.K == K]
        if sub.empty: continue
        ax.hist(sub.residual_iv_day * 1e4, bins=50, alpha=0.7)  # bps
        m = sub.residual_iv_day.mean() * 1e4
        s = sub.residual_iv_day.std() * 1e4
        ax.axvline(m, color="r", lw=1, label=f"mean={m:.1f}bp")
        ax.axvline(m + 2*s, color="orange", lw=1, ls="--", label=f"+2σ={m+2*s:.1f}bp")
        ax.axvline(m - 2*s, color="orange", lw=1, ls="--", label=f"-2σ={m-2*s:.1f}bp")
        ax.set_title(f"VEV_{K} IV residual (bps)")
        ax.legend(fontsize=7); ax.grid(alpha=0.3); ax.tick_params(labelsize=7)
    plt.suptitle(f"IV residuals (vs polynomial fit) — Day {day}")
    plt.tight_layout()
    plt.savefig(out_dir / f"iv_residual_hist_day_{day}.png", dpi=110)
    plt.close(fig)
    return rdf


def plot_vega_gamma(all_iv: dict, day: int, out_dir: Path):
    """Per-strike average vega + gamma + delta."""
    rows = []
    for K in STRIKES:
        if K not in all_iv: continue
        df = all_iv[K]
        if df.empty: continue
        spots = df["spot"].values
        Ts = df["T"].values
        ivs = df["iv_day"].values
        ws_v = [call_vega(float(s), K, float(t), float(iv)) for s, t, iv in zip(spots, Ts, ivs)]
        ws_g = [call_gamma(float(s), K, float(t), float(iv)) for s, t, iv in zip(spots, Ts, ivs)]
        ws_d = [call_delta(float(s), K, float(t), float(iv)) for s, t, iv in zip(spots, Ts, ivs)]
        if ws_v:
            rows.append((K, np.mean(ws_v), np.mean(ws_g), np.mean(ws_d)))
    gdf = pd.DataFrame(rows, columns=["K", "avg_vega", "avg_gamma", "avg_delta"])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, col, title in zip(axes, ["avg_vega", "avg_gamma", "avg_delta"],
                                ["Vega", "Gamma", "Delta"]):
        ax.bar(gdf.K.astype(str), gdf[col])
        ax.set_title(f"avg {title} per strike (Day {day})")
        ax.grid(alpha=0.3); ax.tick_params(axis='x', rotation=45)
    plt.tight_layout()
    plt.savefig(out_dir / f"vega_gamma_delta_day_{day}.png", dpi=110)
    plt.close(fig)
    return gdf


def plot_velvet_path(day: int, df_velvet: pd.DataFrame, out_dir: Path):
    """VELVET mid + return distribution + realized vol."""
    if df_velvet.empty: return
    rets = df_velvet.mid_price.pct_change().dropna()
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    axes[0].plot(df_velvet.index, df_velvet.mid_price, lw=0.5)
    axes[0].set_title(f"VELVET mid — Day {day}")
    axes[0].grid(alpha=0.3)
    axes[1].hist(rets * 1e4, bins=80, alpha=0.7)
    axes[1].set_title(f"per-tick returns (bps)  σ={rets.std()*1e4:.2f}bp")
    axes[1].grid(alpha=0.3)
    # Rolling realized vol (1000-tick window, annualized)
    rolling_vol_ann = rets.rolling(1000).std() * math.sqrt(252.0 * TICKS_PER_DAY)
    axes[2].plot(df_velvet.index[1:], rolling_vol_ann)
    axes[2].axhline(rets.std() * math.sqrt(252.0 * TICKS_PER_DAY), color="r", lw=1, ls="--",
                    label=f"day total {rets.std()*math.sqrt(252.0*TICKS_PER_DAY):.3f}")
    axes[2].set_title(f"Rolling 1000-tick realized vol (annual)")
    axes[2].legend(); axes[2].grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / f"velvet_path_day_{day}.png", dpi=110)
    plt.close(fig)
    return rets.std() * math.sqrt(252.0 * TICKS_PER_DAY)


# ─── Outlier event detection ────────────────────────────────────────────────

def detect_outlier_events(rdf: pd.DataFrame, day: int, out_dir: Path):
    """Find ticks where a strike's IV residual spikes beyond ±2σ.
    Output a CSV of such events per strike with subsequent residual evolution."""
    if rdf is None or rdf.empty: return
    events = []
    for K in STRIKES:
        sub = rdf[rdf.K == K].sort_values("timestamp").reset_index(drop=True)
        if sub.empty: continue
        m = sub.residual_iv_day.mean()
        s = sub.residual_iv_day.std()
        thr = 2 * s
        sub["z"] = (sub.residual_iv_day - m) / s
        # Detect crossings of |z| > 2
        outliers = sub[sub.z.abs() > 2.0].copy()
        for _, row in outliers.iterrows():
            events.append({
                "day": day, "K": K, "timestamp": int(row.timestamp),
                "residual_bp": round(row.residual_iv_day * 1e4, 1),
                "z": round(row.z, 2),
                "direction": "rich" if row.residual_iv_day > 0 else "cheap",
            })
    if events:
        edf = pd.DataFrame(events).sort_values(["day", "timestamp", "K"])
        edf.to_csv(out_dir / f"outlier_events_day_{day}.csv", index=False)
        return edf
    return None


def plot_iv_residual_timeseries(rdf: pd.DataFrame, day: int, out_dir: Path):
    """For each strike, plot IV residual time series with ±2σ bands."""
    if rdf is None or rdf.empty: return
    fig, axes = plt.subplots(3, 3, figsize=(15, 9))
    axes = axes.flatten()
    plot_strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000]
    for ax, K in zip(axes, plot_strikes):
        sub = rdf[rdf.K == K].sort_values("timestamp")
        if sub.empty: continue
        m = sub.residual_iv_day.mean()
        s = sub.residual_iv_day.std()
        ax.plot(sub.timestamp, sub.residual_iv_day * 1e4, lw=0.5)
        ax.axhline(m * 1e4, color="r", lw=0.8)
        ax.axhline((m + 2*s) * 1e4, color="orange", lw=0.8, ls="--")
        ax.axhline((m - 2*s) * 1e4, color="orange", lw=0.8, ls="--")
        ax.set_title(f"VEV_{K}  resid bp  σ={s*1e4:.2f}")
        ax.grid(alpha=0.3); ax.tick_params(labelsize=7)
    plt.suptitle(f"IV residual time series + ±2σ bands — Day {day}")
    plt.tight_layout()
    plt.savefig(out_dir / f"iv_residual_timeseries_day_{day}.png", dpi=110)
    plt.close(fig)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"Output → {OUT}")
    summary = {"days": []}

    for day in DAYS:
        print(f"\n=== Day {day} ===")
        df = load_day(day)
        df_velvet = get_velvet(df)
        T0 = TTE_BY_DAY[day]

        all_iv = {}
        for K in STRIKES:
            df_K = get_strike(df, K)
            if df_K.empty:
                print(f"  K={K}: no data")
                continue
            iv_df = compute_iv_for_strike(df_K, df_velvet, K, T0)
            print(f"  K={K}: {len(iv_df)} IV samples; mean IV={iv_df.iv_ann.mean():.3f} ann")
            all_iv[K] = iv_df

        # Smile snapshot
        T_avg = T0 - 0.5  # mid-day
        plot_smile_with_fits(day, all_iv, T_avg, OUT / "smiles" / f"smile_day_{day}.png")
        # IV timeseries
        plot_iv_timeseries_per_strike(all_iv, day, OUT / "iv_timeseries")
        # IV residuals
        rdf = plot_iv_residuals(all_iv, day, T_avg, OUT / "outliers")
        plot_iv_residual_timeseries(rdf, day, OUT / "outliers")
        # Outlier events CSV
        outlier_events = detect_outlier_events(rdf, day, OUT / "outliers")
        # Vega/gamma/delta
        gdf = plot_vega_gamma(all_iv, day, OUT / "vega")
        # VELVET path
        realized_vol = plot_velvet_path(day, df_velvet, OUT / "velvet")

        # Day summary
        day_summary = {
            "day": day,
            "T0_days": T0,
            "velvet_realized_vol_ann": float(realized_vol) if realized_vol else None,
            "n_strikes": len(all_iv),
            "n_outlier_events": int(len(outlier_events)) if outlier_events is not None else 0,
            "iv_per_strike_ann_mean": {K: float(df.iv_ann.mean()) for K, df in all_iv.items()},
        }
        if gdf is not None:
            day_summary["greeks_per_strike"] = gdf.set_index("K").to_dict("index")
        summary["days"].append(day_summary)

    with (OUT / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n✓ All analyses written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
