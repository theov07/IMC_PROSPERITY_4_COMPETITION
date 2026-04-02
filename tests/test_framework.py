import unittest

from datamodel import Listing, Observation, OrderDepth, TradingState
from prosperity.tooling.backtest import BacktestEngine

import main


class FrameworkSmokeTests(unittest.TestCase):
    def test_trader_returns_orders(self):
        trader = main.Trader()

        order_depth = OrderDepth()
        order_depth.buy_orders = {9999: 10, 9998: 8}
        order_depth.sell_orders = {10001: -9, 10002: -8}

        state = TradingState(
            traderData="",
            timestamp=0,
            listings={"EMERALDS": Listing("EMERALDS", "EMERALDS", "XIRECS")},
            order_depths={"EMERALDS": order_depth},
            own_trades={"EMERALDS": []},
            market_trades={"EMERALDS": []},
            position={"EMERALDS": 0},
            observations=Observation({}, {}),
        )

        orders, conversions, trader_data = trader.run(state)
        self.assertIn("EMERALDS", orders)
        self.assertEqual(conversions, 0)
        self.assertIsInstance(trader_data, str)

    def test_backtest_engine_runs_round_zero_day(self):
        engine = BacktestEngine("data", "champion")
        summary = engine.run_day("-2")
        self.assertIsInstance(summary.pnl, float)
        self.assertTrue(summary.product_summaries)


if __name__ == "__main__":
    unittest.main()
