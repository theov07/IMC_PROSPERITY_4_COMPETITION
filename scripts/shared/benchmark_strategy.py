import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datamodel import TradingState
from prosperity.tooling.backtest import BacktestEngine


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Trader.run latency against historical snapshots")
    parser.add_argument("--strategy", required=True, help="Strategy alias/module, e.g. champion or main")
    parser.add_argument("--round", type=int, default=0, help="Round number to benchmark")
    parser.add_argument("--day", default="-2", help="Round day to replay for timing")
    parser.add_argument("--data-dir", default="data", help="Data root or per-round directory containing price and trade CSVs")
    args = parser.parse_args()

    engine = BacktestEngine(args.data_dir, args.strategy)
    prices_df = engine.loader.load_prices(f"prices_round_{args.round}_day_{args.day}.csv")
    order_history = engine.loader.order_depth_history(prices_df)
    products = sorted(prices_df["product"].unique())
    listings = engine.loader.build_listings(products)
    observations = engine.loader.empty_observation()
    trader = engine._load_trader()

    positions = {product: 0 for product in products}
    own_trades = {product: [] for product in products}
    trader_data = ""
    timings_ms: list[float] = []

    for timestamp in sorted(order_history.keys()):
        state = TradingState(
            traderData=trader_data,
            timestamp=timestamp,
            listings=listings,
            order_depths=order_history[timestamp],
            own_trades=own_trades,
            market_trades={},
            position=positions,
            observations=observations,
        )

        start = time.perf_counter()
        _, _, trader_data = trader.run(state)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings_ms.append(elapsed_ms)

    mean_ms = statistics.fmean(timings_ms) if timings_ms else 0.0
    median_ms = statistics.median(timings_ms) if timings_ms else 0.0
    p95_ms = percentile(timings_ms, 0.95)
    max_ms = max(timings_ms) if timings_ms else 0.0

    print(f"strategy={args.strategy} round={args.round} day={args.day}")
    print(f"ticks={len(timings_ms)} mean_ms={mean_ms:.3f} median_ms={median_ms:.3f} p95_ms={p95_ms:.3f} max_ms={max_ms:.3f}")
    print("constraint_reference=Prosperity wiki says each run should return within 900ms and average <=100ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
