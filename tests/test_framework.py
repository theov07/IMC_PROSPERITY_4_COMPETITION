import unittest

from datamodel import Listing, Observation, Order, OrderDepth, Trade, TradingState
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode

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


class PassiveFillRuleTests(unittest.TestCase):
    def test_queue_rule_join_requires_trades_beyond_displayed_queue(self):
        order_depth = OrderDepth()
        order_depth.buy_orders = {100: 10}
        order_depth.sell_orders = {102: -10}

        fills = BacktestEngine._simulate_fills(
            order_depth=order_depth,
            orders=[Order("EMERALDS", 100, 5)],
            current_market_trades=[Trade("EMERALDS", 100, 7, timestamp=0)],
            timestamp=0,
            mode=TradeMatchingMode.queue,
        )

        self.assertEqual(sum(fill.quantity for fill in fills), 0)

    def test_queue_rule_join_fills_after_displayed_queue_is_cleared(self):
        order_depth = OrderDepth()
        order_depth.buy_orders = {100: 10}
        order_depth.sell_orders = {102: -10}

        fills = BacktestEngine._simulate_fills(
            order_depth=order_depth,
            orders=[Order("EMERALDS", 100, 5)],
            current_market_trades=[Trade("EMERALDS", 100, 12, timestamp=0)],
            timestamp=0,
            mode=TradeMatchingMode.queue,
        )

        self.assertEqual(sum(fill.quantity for fill in fills), 2)

    def test_queue_rule_improved_price_has_no_queue_ahead(self):
        order_depth = OrderDepth()
        order_depth.buy_orders = {100: 10}
        order_depth.sell_orders = {102: -10}

        fills = BacktestEngine._simulate_fills(
            order_depth=order_depth,
            orders=[Order("EMERALDS", 101, 4)],
            current_market_trades=[Trade("EMERALDS", 101, 3, timestamp=0)],
            timestamp=0,
            mode=TradeMatchingMode.queue,
        )

        self.assertEqual(sum(fill.quantity for fill in fills), 3)

    def test_queue_rule_trade_through_price_completes_remaining_quantity(self):
        order_depth = OrderDepth()
        order_depth.buy_orders = {100: 10}
        order_depth.sell_orders = {102: -10}

        fills = BacktestEngine._simulate_fills(
            order_depth=order_depth,
            orders=[Order("EMERALDS", 100, 5)],
            current_market_trades=[
                Trade("EMERALDS", 100, 10, timestamp=0),
                Trade("EMERALDS", 99, 1, timestamp=0),
            ],
            timestamp=0,
            mode=TradeMatchingMode.queue,
        )

        self.assertEqual(sum(fill.quantity for fill in fills), 5)


if __name__ == "__main__":
    unittest.main()
