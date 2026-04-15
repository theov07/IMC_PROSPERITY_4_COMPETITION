import unittest

from datamodel import Listing, Observation, Order, OrderDepth, Trade, TradingState
from prosperity.config import MEMBER_OVERRIDES
from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode, aggregate_day_summaries
from prosperity.tooling.grid_search import _apply_overrides

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
        self.assertIsNotNone(summary.robustness)
        self.assertGreaterEqual(summary.robustness.fill_efficiency, 0.0)
        self.assertGreaterEqual(summary.robustness.max_drawdown or 0.0, 0.0)
        self.assertIn("1", summary.robustness.markout_mean_by_horizon)
        self.assertIn("avg_quote_age_ticks", summary.robustness.quote_metrics)
        self.assertIn("inventory_drift", summary.robustness.pnl_attribution)
        self.assertEqual(len(summary.conversion_ticks), len(summary.equity_curve))
        for product_summary in summary.product_summaries.values():
            self.assertIsNotNone(product_summary.robustness)
            self.assertGreaterEqual(product_summary.robustness.avg_abs_position_ratio, 0.0)
            self.assertIn("one_sided_tick_ratio", product_summary.robustness.inventory_episode_metrics)
            self.assertIn("bid_fill_efficiency", product_summary.robustness.__dict__)

    def test_aggregate_day_summaries_exposes_robustness(self):
        engine = BacktestEngine("data", "champion")
        summary = engine.run_day("-2")
        aggregate = aggregate_day_summaries([summary])

        self.assertIn("robustness", aggregate)
        self.assertAlmostEqual(aggregate["total_pnl"], summary.pnl)
        self.assertGreaterEqual(aggregate["robustness"]["max_drawdown"], 0.0)
        self.assertIn("EMERALDS", aggregate["per_product_robustness"])
        self.assertIn("markout_mean_by_horizon", aggregate["robustness"])
        self.assertIn("quote_metrics", aggregate["per_product_robustness"]["EMERALDS"])


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


class GridSearchOverrideTests(unittest.TestCase):
    def test_apply_overrides_preserves_removed_products(self):
        patched = _apply_overrides(
            1,
            {"INTARIAN_PEPPER_ROOT": {"enable_selective_take": 1.0}},
            member="leo_reg_lin_round1_v5",
        )

        self.assertIn("ASH_COATED_OSMIUM", patched)
        self.assertIsNone(patched["ASH_COATED_OSMIUM"])
        self.assertIn("INTARIAN_PEPPER_ROOT", patched)
        self.assertEqual(patched["INTARIAN_PEPPER_ROOT"].params["enable_selective_take"], 1.0)

    def test_backtest_engine_position_limits_use_member_config(self):
        engine = BacktestEngine("data", "leo_reg_lin_round1_v5", round_num=1)
        limits = engine._get_position_limits()

        self.assertIn("INTARIAN_PEPPER_ROOT", limits)
        self.assertNotIn("ASH_COATED_OSMIUM", limits)


if __name__ == "__main__":
    unittest.main()
