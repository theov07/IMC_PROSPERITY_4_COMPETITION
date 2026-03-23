import argparse
import importlib
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from datamodel import Listing, Order, OrderDepth, Trade, TradingState, Observation
from vizualizer.data_loader import DataLoader


@dataclass
class FillResult:
    trade: Trade
    cash_delta: float


@dataclass
class BacktestSummary:
    pnl: float
    trades: List[Trade]
    positions: Dict[str, int]


class BacktestEngine:
    def __init__(self, data_dir: str, strategy_module: str):
        self.data_dir = data_dir
        self.strategy_module = strategy_module
        self.loader = DataLoader(data_dir)

    def _load_strategy(self):
        module = importlib.import_module(self.strategy_module)
        if not hasattr(module, "Trader"):
            raise ValueError(f"Strategy module {self.strategy_module} has no Trader class")
        return module.Trader()

    def _build_listings(self, products: List[str]) -> Dict[str, Listing]:
        return {p: Listing(symbol=p, product=p, denomination="XIRECS") for p in products}

    def _mid_price(self, order_depth: OrderDepth) -> float:
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else 0
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else 0
        if best_bid and best_ask:
            return (best_bid + best_ask) / 2
        return float(best_bid or best_ask or 0)

    def _simulate_fills(self, order_depth: OrderDepth, orders: List[Order], timestamp: int) -> List[FillResult]:
        fills: List[FillResult] = []
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        best_ask_qty = abs(order_depth.sell_orders[best_ask]) if best_ask is not None else 0
        best_bid_qty = order_depth.buy_orders[best_bid] if best_bid is not None else 0

        for order in orders:
            if order.quantity > 0 and best_ask is not None and order.price >= best_ask:
                fill_qty = min(order.quantity, best_ask_qty)
                if fill_qty > 0:
                    fills.append(
                        FillResult(
                            Trade(
                                symbol=order.symbol,
                                price=best_ask,
                                quantity=fill_qty,
                                buyer="SUBMISSION",
                                seller="",
                                timestamp=timestamp,
                            ),
                            cash_delta=-fill_qty * best_ask,
                        )
                    )
            elif order.quantity < 0 and best_bid is not None and order.price <= best_bid:
                fill_qty = min(abs(order.quantity), best_bid_qty)
                if fill_qty > 0:
                    fills.append(
                        FillResult(
                            Trade(
                                symbol=order.symbol,
                                price=best_bid,
                                quantity=fill_qty,
                                buyer="",
                                seller="SUBMISSION",
                                timestamp=timestamp,
                            ),
                            cash_delta=fill_qty * best_bid,
                        )
                    )

        return fills

    def run_day(self, price_file: str, trade_file: str) -> BacktestSummary:
        df_prices = self.loader.load_prices(price_file)
        history = self.loader.get_order_depths(df_prices)
        products = sorted(df_prices["product"].unique())
        listings = self._build_listings(products)

        market_trades = self.loader.load_trade_objects(trade_file)
        market_by_time = self.loader.group_trades_by_timestamp(market_trades)

        trader = self._load_strategy()
        trader_data = ""
        observations = Observation(plainValueObservations={}, conversionObservations={})

        positions: Dict[str, int] = {p: 0 for p in products}
        cash = 0.0
        own_trades: Dict[str, List[Trade]] = {p: [] for p in products}
        all_fills: List[Trade] = []

        for timestamp in sorted(history.keys()):
            order_depths = history[timestamp]
            state = TradingState(
                traderData=trader_data,
                timestamp=timestamp,
                listings=listings,
                order_depths=order_depths,
                own_trades=own_trades,
                market_trades=market_by_time.get(timestamp, {}),
                position=positions,
                observations=observations,
            )

            result, conversions, trader_data = trader.run(state)
            conversions = conversions or 0

            for product, orders in result.items():
                fills = self._simulate_fills(order_depths.get(product, OrderDepth()), orders, timestamp)
                for fill in fills:
                    all_fills.append(fill.trade)
                    positions[product] = positions.get(product, 0) + (fill.trade.quantity if fill.trade.buyer == "SUBMISSION" else -fill.trade.quantity)
                    cash += fill.cash_delta
                    own_trades.setdefault(product, []).append(fill.trade)

        # Mark-to-mid at end
        last_mid = 0.0
        for product in products:
            if history:
                last_ts = sorted(history.keys())[-1]
                od = history[last_ts].get(product)
                if od:
                    last_mid = self._mid_price(od)
                    cash += positions.get(product, 0) * last_mid

        return BacktestSummary(pnl=cash, trades=all_fills, positions=positions)


def find_days(data_dir: str) -> List[str]:
    days = []
    for file in os.listdir(data_dir):
        if file.startswith("prices_round_0_day_") and file.endswith(".csv"):
            day = file.replace("prices_round_0_day_", "").replace(".csv", "")
            days.append(day)
    return sorted(days)


def main():
    parser = argparse.ArgumentParser(description="Round 0 backtest framework")
    parser.add_argument("--strategy", required=True, help="Python module with Trader class (e.g., test_leo)")
    parser.add_argument("--its-days", nargs="*", help="In-sample days (e.g., -2)")
    parser.add_argument("--oots-days", nargs="*", help="Out-of-sample days (e.g., -1)")
    args = parser.parse_args()

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DATAS")
    engine = BacktestEngine(data_dir, args.strategy)

    all_days = find_days(data_dir)
    if not all_days:
        raise RuntimeError("No price files found in DATAS")

    its_days = args.its_days or all_days[: max(1, len(all_days) // 2)]
    oots_days = args.oots_days or [d for d in all_days if d not in its_days]

    print(f"ITS days: {its_days}")
    print(f"OOTS days: {oots_days}")

    def run_split(days: List[str], label: str):
        total_pnl = 0.0
        total_trades = 0
        last_positions: Dict[str, int] = {}

        for day in days:
            price_file = f"prices_round_0_day_{day}.csv"
            trade_file = f"trades_round_0_day_{day}.csv"
            summary = engine.run_day(price_file, trade_file)
            total_pnl += summary.pnl
            total_trades += len(summary.trades)
            last_positions = summary.positions
            print(f"{label} day {day}: pnl={summary.pnl:.2f}, trades={len(summary.trades)}")

        print(f"{label} TOTAL: pnl={total_pnl:.2f}, trades={total_trades}, positions={last_positions}")

    if its_days:
        run_split(its_days, "ITS")
    if oots_days:
        run_split(oots_days, "OOTS")


if __name__ == "__main__":
    main()
