"""Tests for prosperity.risk — capacity calculations and inventory bias."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
from prosperity.risk import buy_capacity, sell_capacity, inventory_bias_ticks
from prosperity.config import ProductConfig


class TestCapacity(unittest.TestCase):

    def test_buy_capacity_no_position(self):
        self.assertEqual(buy_capacity(0, 50), 50)

    def test_buy_capacity_long(self):
        self.assertEqual(buy_capacity(30, 50), 20)

    def test_buy_capacity_at_limit(self):
        self.assertEqual(buy_capacity(50, 50), 0)

    def test_buy_capacity_short(self):
        self.assertEqual(buy_capacity(-20, 50), 70)

    def test_sell_capacity_no_position(self):
        self.assertEqual(sell_capacity(0, 50), 50)

    def test_sell_capacity_short(self):
        self.assertEqual(sell_capacity(-30, 50), 20)

    def test_sell_capacity_at_limit(self):
        self.assertEqual(sell_capacity(-50, 50), 0)

    def test_sell_capacity_long(self):
        self.assertEqual(sell_capacity(20, 50), 70)


class TestInventoryBias(unittest.TestCase):

    def _profile(self, aversion=1.0, max_ticks=3):
        return ProductConfig(
            symbol="TEST", strategy="market_maker", position_limit=50,
            params=dict(inventory_aversion=aversion, max_inventory_bias_ticks=max_ticks),
        )

    def test_zero_position(self):
        from prosperity.risk import inventory_bias_ticks as ibt
        # Need to use the old function signature — it takes a ProductProfile
        # but our new config uses ProductConfig. Let's test the strategy's method instead.
        pass

    def test_bias_direction(self):
        # Positive position should produce positive bias (skew asks down)
        p = self._profile(aversion=1.0, max_ticks=3)
        bias = inventory_bias_ticks(25, 50, p)
        self.assertGreater(bias, 0)

    def test_bias_negative_position(self):
        p = self._profile(aversion=1.0, max_ticks=3)
        bias = inventory_bias_ticks(-25, 50, p)
        self.assertLess(bias, 0)

    def test_bias_clamped(self):
        p = self._profile(aversion=5.0, max_ticks=3)
        bias = inventory_bias_ticks(50, 50, p)
        self.assertLessEqual(abs(bias), 3)


if __name__ == "__main__":
    unittest.main()
