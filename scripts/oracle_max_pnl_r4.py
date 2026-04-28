"""Oracle backtester — compute realistic max PnL on R4 day 3 first 10%.

Uses perfect foresight (knows future prices). At each tick, looks N ticks ahead and:
  - If future_mid > current_ask → BUY at ask (taker)
  - If future_mid < current_bid → SELL at bid (taker)
  - Respects position limits and order book depth.

Pays the bid-ask spread on every fill. Realistic ceiling.
"""
from __future__ import annotations
import pandas as pd
from collections import defaultdict

DATA = "data/round_4/prices_round_4_day_3.csv"
TRADES_DATA = "data/round_4/trades_round_4_day_3.csv"
TICK_END = 99900  # first 10% of day 3

POSITION_LIMITS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    **{f"VEV_{k}": 300 for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
}

# Lookahead: how far to peek into the future
LOOKAHEAD_TICKS = 5
EDGE_THRESHOLD = 0.5  # only trade if expected gain >= 0.5 ticks


def main():
    df = pd.read_csv(DATA, sep=";")
    df = df[df["timestamp"] <= TICK_END].sort_values(["product", "timestamp"]).reset_index(drop=True)

    print(f"Loaded {len(df)} price rows for {df['product'].nunique()} products")

    # Per-product state
    positions = {p: 0 for p in POSITION_LIMITS}
    cash = 0.0
    pnl_per_prod = defaultdict(float)
    trades_count = defaultdict(int)
    realized_pnl = defaultdict(float)
    cost_basis = defaultdict(list)  # list of (qty, price) — FIFO

    products = df["product"].unique()

    print(f"\n{'Product':<22} {'Trades':>7} {'Gross':>10} {'Net':>10} {'Final pos':>10}")
    print("=" * 70)

    grand_total = 0.0
    for prod in products:
        if prod not in POSITION_LIMITS:
            continue
        limit = POSITION_LIMITS[prod]
        sub = df[df["product"] == prod].sort_values("timestamp").reset_index(drop=True)

        pos = 0
        cash_p = 0.0
        n_trades = 0
        gross_volume = 0.0

        for i in range(len(sub) - LOOKAHEAD_TICKS):
            row = sub.iloc[i]
            future = sub.iloc[i + LOOKAHEAD_TICKS]
            current_bid = row["bid_price_1"] if pd.notna(row["bid_price_1"]) else None
            current_ask = row["ask_price_1"] if pd.notna(row["ask_price_1"]) else None
            current_bid_vol = int(row["bid_volume_1"]) if pd.notna(row["bid_volume_1"]) else 0
            current_ask_vol = int(row["ask_volume_1"]) if pd.notna(row["ask_volume_1"]) else 0
            future_mid = future["mid_price"]

            if current_bid is None or current_ask is None or pd.isna(future_mid):
                continue

            # Decision: future_mid - current_ask = expected gain if we BUY
            # future_mid - current_bid = expected gain if we SELL (negative if going down)
            buy_edge = future_mid - current_ask  # we buy at ask, expect to sell at future_mid
            sell_edge = current_bid - future_mid  # we sell at bid, expect to buy back at future_mid

            if buy_edge >= EDGE_THRESHOLD and pos < limit:
                qty = min(current_ask_vol, limit - pos)
                if qty > 0:
                    pos += qty
                    cash_p -= qty * current_ask
                    n_trades += 1
                    gross_volume += abs(qty * current_ask)
            elif sell_edge >= EDGE_THRESHOLD and pos > -limit:
                qty = min(current_bid_vol, limit + pos)
                if qty > 0:
                    pos -= qty
                    cash_p += qty * current_bid
                    n_trades += 1
                    gross_volume += abs(qty * current_bid)

        # MTM at last mid
        last_mid = sub.iloc[-1]["mid_price"]
        net_pnl = cash_p + pos * last_mid
        grand_total += net_pnl
        print(f"{prod:<22} {n_trades:>7} {gross_volume:>10,.0f} {net_pnl:>+10,.0f} {pos:>+10}")

    print("=" * 70)
    print(f"{'GRAND TOTAL':<22} {'':>7} {'':>10} {grand_total:>+10,.0f}")
    print()
    print(f"Lookahead: {LOOKAHEAD_TICKS} ticks, Edge threshold: {EDGE_THRESHOLD} ticks")
    print(f"Realistic max PnL with perfect foresight: {grand_total:,.0f}")


if __name__ == "__main__":
    main()
