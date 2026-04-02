"""Tests for prosperity.market — BookSnapshot from OrderDepth."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
from datamodel import OrderDepth
from prosperity.market import snapshot_from_order_depth


class TestBookSnapshot(unittest.TestCase):

    def _make_depth(self, buys, sells):
        od = OrderDepth()
        od.buy_orders = buys
        od.sell_orders = sells
        return od

    def test_basic_snapshot(self):
        od = self._make_depth({10: 5, 9: 3}, {12: -4, 13: -6})
        snap = snapshot_from_order_depth("TEST", od)
        self.assertEqual(snap.best_bid, 10)
        self.assertEqual(snap.best_ask, 12)
        self.assertEqual(snap.spread, 2)
        self.assertAlmostEqual(snap.mid_price, 11.0)

    def test_microprice(self):
        od = self._make_depth({10: 5}, {12: -10})
        snap = snapshot_from_order_depth("TEST", od)
        # microprice = (10*10 + 12*5) / (5 + 10) = 160/15 ≈ 10.667
        self.assertAlmostEqual(snap.microprice, 160.0 / 15.0, places=3)

    def test_imbalance(self):
        od = self._make_depth({10: 8}, {12: -2})
        snap = snapshot_from_order_depth("TEST", od)
        # imbalance = (8 - 2) / (8 + 2) = 0.6
        self.assertAlmostEqual(snap.imbalance, 0.6)

    def test_empty_book(self):
        od = self._make_depth({}, {})
        snap = snapshot_from_order_depth("TEST", od)
        self.assertIsNone(snap.best_bid)
        self.assertIsNone(snap.best_ask)
        self.assertIsNone(snap.mid_price)
        self.assertIsNone(snap.microprice)

    def test_one_side_only(self):
        od = self._make_depth({10: 5}, {})
        snap = snapshot_from_order_depth("TEST", od)
        self.assertEqual(snap.best_bid, 10)
        self.assertIsNone(snap.best_ask)
        self.assertIsNone(snap.mid_price)


class TestSortedLevels(unittest.TestCase):

    def test_bid_levels_sorted_desc(self):
        od = OrderDepth()
        od.buy_orders = {8: 3, 10: 5, 9: 4}
        od.sell_orders = {12: -2}
        snap = snapshot_from_order_depth("TEST", od)
        bid_prices = [p for p, v in snap.bid_levels]
        self.assertEqual(bid_prices, [10, 9, 8])

    def test_ask_levels_sorted_asc(self):
        od = OrderDepth()
        od.buy_orders = {10: 5}
        od.sell_orders = {14: -1, 12: -2, 13: -3}
        snap = snapshot_from_order_depth("TEST", od)
        ask_prices = [p for p, v in snap.ask_levels]
        self.assertEqual(ask_prices, [12, 13, 14])


if __name__ == "__main__":
    unittest.main()
