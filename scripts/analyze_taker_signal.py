"""Analyze: what if we only take when conditions are perfect?

From fill_conditions_v2 analysis:
  - Aggressive fills happen when spread=5-6 (vs baseline 16), |dev|=5, imb=+0.4
  - Edge per aggressive fill is +7 ticks, markout +5

Question: can we improve total PnL by being MORE selective on takers?
This script looks at the relationship between take_edge and profitability.
"""
import numpy as np
import pandas as pd

DATA = [
    ("data/round_1/prices_round_1_day_-2.csv", "-2"),
    ("data/round_1/prices_round_1_day_-1.csv", "-1"),
    ("data/round_1/prices_round_1_day_0.csv", "0"),
]
PRODUCT = "ASH_COATED_OSMIUM"
ANCHOR = 10000.0


def main():
    for path, day in DATA:
        df = pd.read_csv(path, sep=";")
        df.columns = [c.strip() for c in df.columns]
        p = df[df["product"] == PRODUCT].copy().sort_values("timestamp").reset_index(drop=True)

        mid = p["mid_price"].dropna().values.astype(float)
        bid1 = p["bid_price_1"].values.astype(float)
        ask1 = p["ask_price_1"].values.astype(float)
        bid_vol1 = p["bid_volume_1"].values.astype(float)
        ask_vol1 = p["ask_volume_1"].values.astype(float)

        n = len(mid)
        spread = ask1 - bid1
        dev = mid - ANCHOR
        imb = (bid_vol1 - ask_vol1) / (bid_vol1 + ask_vol1 + 1e-9)

        # AR(1) returns
        ret = np.diff(mid)

        print(f"\n=== Day {day} ({n} ticks) ===")

        # For each tick, compute the "ideal taker" signal:
        # Buy when: dev < -X (below anchor) AND next return > 0
        # Sell when: dev > +X (above anchor) AND next return < 0
        print(f"\n  Taker selectivity analysis:")
        print(f"  {'dev_thr':>8} {'buy_n':>6} {'buy_edge':>10} {'sell_n':>6} {'sell_edge':>10} {'total_pnl':>10}")

        for dev_thr in [0, 1, 2, 3, 4, 5, 6, 8, 10]:
            # Buy signals: dev < -dev_thr, take at ask
            buy_mask = dev[:-1] < -dev_thr
            buy_fwd = ret[buy_mask]  # return after buying
            buy_n = len(buy_fwd)
            buy_edge = buy_fwd.mean() if buy_n > 0 else 0

            # Sell signals: dev > dev_thr, take at bid
            sell_mask = dev[:-1] > dev_thr
            sell_fwd = -ret[sell_mask]  # negative return = profit for seller
            sell_n = len(sell_fwd)
            sell_edge = sell_fwd.mean() if sell_n > 0 else 0

            # Approximate PnL (1 unit per signal)
            total_pnl = buy_fwd.sum() + (-ret[sell_mask]).sum() if sell_n > 0 else buy_fwd.sum()

            print(f"  {dev_thr:>8} {buy_n:>6} {buy_edge:>+10.3f} {sell_n:>6} {sell_edge:>+10.3f} {total_pnl:>+10.1f}")

        # Now add spread filter
        print(f"\n  + Spread filter (spread <= X):")
        print(f"  {'spread_max':>10} {'dev_thr':>8} {'buy_n':>6} {'buy_edge':>10} {'sell_n':>6} {'sell_edge':>10} {'total_pnl':>10}")
        for spread_max in [6, 8, 10, 14, 20]:
            for dev_thr in [0, 2, 4]:
                s_mask = spread[:-1] <= spread_max
                buy_mask = (dev[:-1] < -dev_thr) & s_mask
                sell_mask = (dev[:-1] > dev_thr) & s_mask

                buy_fwd = ret[buy_mask]
                sell_fwd = -ret[sell_mask]
                buy_n = len(buy_fwd)
                sell_n = len(sell_fwd)
                buy_edge = buy_fwd.mean() if buy_n > 0 else 0
                sell_edge = sell_fwd.mean() if sell_n > 0 else 0
                total_pnl = buy_fwd.sum() + sell_fwd.sum()
                print(f"  {spread_max:>10} {dev_thr:>8} {buy_n:>6} {buy_edge:>+10.3f} {sell_n:>6} {sell_edge:>+10.3f} {total_pnl:>+10.1f}")

        # Multi-tick holding period analysis
        print(f"\n  Holding period analysis (dev_thr=3):")
        print(f"  {'hold_ticks':>11} {'buy_n':>6} {'buy_edge':>10} {'sell_n':>6} {'sell_edge':>10} {'total_pnl':>10}")
        dev_thr = 3
        for hold in [1, 2, 3, 5, 10, 20, 50]:
            buy_mask = np.where(dev[:-hold] < -dev_thr)[0]
            sell_mask = np.where(dev[:-hold] > dev_thr)[0]
            buy_mask = buy_mask[buy_mask + hold < n]
            sell_mask = sell_mask[sell_mask + hold < n]

            buy_fwd = mid[buy_mask + hold] - mid[buy_mask]
            sell_fwd = mid[sell_mask] - mid[sell_mask + hold]

            buy_n = len(buy_fwd)
            sell_n = len(sell_fwd)
            buy_edge = buy_fwd.mean() if buy_n > 0 else 0
            sell_edge = sell_fwd.mean() if sell_n > 0 else 0
            total_pnl = buy_fwd.sum() + sell_fwd.sum()
            print(f"  {hold:>11} {buy_n:>6} {buy_edge:>+10.3f} {sell_n:>6} {sell_edge:>+10.3f} {total_pnl:>+10.1f}")


main()
