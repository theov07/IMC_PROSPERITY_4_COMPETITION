"""Generate 80% subsampled R2 data (approximates live IMC book visibility).

Rationale (Leo's insight):
  Live IMC samples ~80% of quotes from the true order book at each tick.
  Our backtest uses 100% (the full logged book). So backtest PnL is from 100% conditions.
  MAF gives +25% extra quotes → 80% × 1.25 = 100% ≈ backtest conditions.

  Therefore:
    PnL(live no-MAF)  ≈ PnL at 80% book
    PnL(live w/ MAF)  ≈ PnL at 100% book (= our backtest baseline)
    MAF uplift ratio  = PnL(100%) / PnL(80%)
    MAF extra in live = Live_PnL × (ratio − 1)

This script produces an "80%" synthetic dataset by binomial-thinning volumes
(each unit of volume kept with p=0.8). This preserves distribution shape
(wiki: "quotes fit perfectly in the distribution"), just thinner.

Usage:
    python research/round_2/round_2_MAF/05_subsample_80pct.py --seed 100 --n_seeds 3 --p_keep 0.8
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "round_2"
OUT_BASE = ROOT / "data"

PRODUCTS = ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]
DAYS = [-1, 0, 1]


def thin_volumes(df: pd.DataFrame, p_keep: float, rng: np.random.Generator) -> pd.DataFrame:
    """Binomial-thin each volume cell. Preserves prices; reduces vols by ~(1-p_keep)."""
    out = df.copy()
    for side in ("bid", "ask"):
        for i in (1, 2, 3):
            col = f"{side}_volume_{i}"
            if col not in out.columns:
                continue
            vals = out[col].values
            new_vals = np.empty_like(vals, dtype=object)
            for k, v in enumerate(vals):
                if pd.isna(v):
                    new_vals[k] = v
                else:
                    v_int = int(v)
                    if v_int <= 0:
                        new_vals[k] = v_int
                    else:
                        kept = int(rng.binomial(v_int, p_keep))
                        new_vals[k] = kept
            out[col] = new_vals

    # If a level's volume became 0, null the price too (level dropped entirely)
    for side in ("bid", "ask"):
        for i in (1, 2, 3):
            vcol, pcol = f"{side}_volume_{i}", f"{side}_price_{i}"
            if vcol in out.columns and pcol in out.columns:
                mask = (out[vcol] == 0)
                out.loc[mask, pcol] = np.nan
                out.loc[mask, vcol] = np.nan
    return out


def thin_trades(df: pd.DataFrame, p_keep: float, rng: np.random.Generator) -> pd.DataFrame:
    """Thin trades: each trade dropped with prob (1-p_keep), volume binomial-thinned."""
    if df.empty:
        return df
    out = df.copy()
    keep_mask = rng.random(len(out)) < p_keep
    out = out[keep_mask].copy()
    # Thin remaining trade volumes
    vols = out["quantity"].values
    new_vols = np.array([rng.binomial(int(v), p_keep) if v > 0 else 0 for v in vols])
    out["quantity"] = new_vols
    out = out[out["quantity"] > 0]
    return out


def process_day(day: int, seed: int, p_keep: float) -> tuple:
    rng = np.random.default_rng(seed * 10000 + (day + 10) * 1000)
    prices_path = DATA_DIR / f"prices_round_2_day_{day}.csv"
    trades_path = DATA_DIR / f"trades_round_2_day_{day}.csv"
    if not prices_path.exists():
        return None, None
    df_prices = pd.read_csv(prices_path, sep=";")
    df_trades = pd.read_csv(trades_path, sep=";") if trades_path.exists() else pd.DataFrame()

    thinned_prices = []
    for product in PRODUCTS:
        df_p = df_prices[df_prices["product"] == product].copy()
        thinned_prices.append(thin_volumes(df_p, p_keep, rng))
    df_prices_out = pd.concat(thinned_prices).sort_values(["timestamp", "product"]).reset_index(drop=True)

    df_trades_out = thin_trades(df_trades, p_keep, rng) if not df_trades.empty else df_trades
    return df_prices_out, df_trades_out


def orig_volume(day: int) -> int:
    path = DATA_DIR / f"prices_round_2_day_{day}.csv"
    if not path.exists():
        return 0
    df = pd.read_csv(path, sep=";")
    total = 0
    for side in ("bid", "ask"):
        for i in (1, 2, 3):
            col = f"{side}_volume_{i}"
            if col in df.columns:
                total += int(df[col].fillna(0).sum())
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--n_seeds", type=int, default=3)
    parser.add_argument("--p_keep", type=float, default=0.8,
                        help="Probability each volume unit / trade is kept (default 0.8)")
    args = parser.parse_args()

    for s in range(args.n_seeds):
        seed = args.seed + s
        out_dir = OUT_BASE / f"round_2_subsample_p{int(args.p_keep*100)}_s{seed}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Seed {seed} → {out_dir} ===")

        for day in DAYS:
            df_p, df_t = process_day(day, seed, args.p_keep)
            if df_p is None:
                continue
            df_p.to_csv(out_dir / f"prices_round_2_day_{day}.csv", sep=";", index=False)
            if df_t is not None and not df_t.empty:
                df_t.to_csv(out_dir / f"trades_round_2_day_{day}.csv", sep=";", index=False)

            orig = orig_volume(day)
            new_vol = 0
            for side in ("bid", "ask"):
                for i in (1, 2, 3):
                    col = f"{side}_volume_{i}"
                    if col in df_p.columns:
                        new_vol += int(df_p[col].fillna(0).sum())
            ratio = new_vol / orig if orig else 0
            print(f"  day {day}: orig vol={orig:,} → thinned vol={new_vol:,} (ratio={ratio:.3f}, target={args.p_keep})")


if __name__ == "__main__":
    main()
