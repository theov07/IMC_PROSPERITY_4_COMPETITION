"""Tests for strategy modules — smoke tests that they produce valid orders."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
from datamodel import Listing, Observation, Order, OrderDepth, TradingState, Trade

from prosperity.strategies import build_strategy


def _make_state(product="TEST", buys=None, sells=None, position=0, market_trades=None):
    od = OrderDepth()
    od.buy_orders = buys or {100: 10, 99: 5}
    od.sell_orders = sells or {102: -10, 103: -5}

    return TradingState(
        traderData="",
        timestamp=1000,
        listings={product: Listing(symbol=product, product=product, denomination="XIRECS")},
        order_depths={product: od},
        own_trades={product: []},
        market_trades={product: market_trades or []},
        position={product: position},
        observations=Observation(plainValueObservations={}, conversionObservations={}),
    )


class TestMarketMakerStrategy(unittest.TestCase):

    def test_produces_orders(self):
        strat = build_strategy("market_maker", "TEST", {
            "position_limit": 50, "fair_mode": "microprice_ema",
            "ema_alpha": 0.15, "take_edge": 1.0, "quote_half_spread": 2,
            "inventory_aversion": 1.0, "max_inventory_bias_ticks": 3,
            "maker_size": 10, "join_best": True, "improve_ticks": 1,
        })
        state = _make_state()
        orders, conv = strat.on_tick(state, {})
        self.assertIsInstance(orders, list)
        self.assertEqual(conv, 0)
        self.assertTrue(len(orders) > 0)

    def test_respects_position_limit(self):
        strat = build_strategy("market_maker", "TEST", {
            "position_limit": 50, "fair_mode": "microprice_ema",
            "ema_alpha": 0.15, "take_edge": 1.0, "quote_half_spread": 2,
            "inventory_aversion": 1.0, "max_inventory_bias_ticks": 3,
            "maker_size": 10, "join_best": True, "improve_ticks": 1,
        })
        state = _make_state(position=50)  # at limit
        orders, _ = strat.on_tick(state, {})
        total_buy = sum(o.quantity for o in orders if o.quantity > 0)
        self.assertEqual(total_buy, 0)  # can't buy more


class TestNaiveTightMarketMaker(unittest.TestCase):

    def test_improves_inside_spread_when_possible(self):
        strat = build_strategy("naive_tight_mm", "TEST", {
            "position_limit": 50,
            "maker_size": 10,
            "tighten_ticks": 1,
        })
        state = _make_state(buys={100: 10}, sells={104: -10})
        orders, conv = strat.on_tick(state, {})
        self.assertEqual(conv, 0)
        bid_orders = [o for o in orders if o.quantity > 0]
        ask_orders = [o for o in orders if o.quantity < 0]
        self.assertTrue(any(o.price == 101 for o in bid_orders))
        self.assertTrue(any(o.price == 103 for o in ask_orders))

    def test_joins_best_when_spread_too_tight(self):
        strat = build_strategy("naive_tight_mm", "TEST", {
            "position_limit": 50,
            "maker_size": 10,
            "tighten_ticks": 1,
        })
        state = _make_state(buys={100: 10}, sells={101: -10})
        orders, _ = strat.on_tick(state, {})
        bid_orders = [o for o in orders if o.quantity > 0]
        ask_orders = [o for o in orders if o.quantity < 0]
        self.assertTrue(any(o.price == 100 for o in bid_orders))
        self.assertTrue(any(o.price == 101 for o in ask_orders))


class TestAvellanedaStoikov(unittest.TestCase):

    def test_produces_orders(self):
        strat = build_strategy("avellaneda_stoikov", "TEST", {
            "position_limit": 50, "gamma": 0.1, "kappa": 1.5,
            "sigma_window": 10, "sigma_default": 1.0, "sigma_floor": 0.5,
            "ts_increment": 100, "last_ts_value": 99900, "min_half_spread": 1.0,
            "maker_size": 8, "take_edge": 0.5,
        })
        state = _make_state()
        orders, conv = strat.on_tick(state, {})
        self.assertIsInstance(orders, list)
        self.assertEqual(conv, 0)

    def test_reservation_skews_with_inventory(self):
        params = {
            "position_limit": 50, "gamma": 0.5, "kappa": 1.5,
            "sigma_window": 10, "sigma_default": 2.0, "sigma_floor": 0.5,
            "ts_increment": 100, "last_ts_value": 99900, "min_half_spread": 1.0,
            "maker_size": 8, "take_edge": 0.5,
        }
        # Long position should skew reservation DOWN
        strat_long = build_strategy("avellaneda_stoikov", "TEST", params)
        mem_long = {}
        strat_long.on_tick(_make_state(position=30), mem_long)

        strat_flat = build_strategy("avellaneda_stoikov", "TEST", params)
        mem_flat = {}
        strat_flat.on_tick(_make_state(position=0), mem_flat)

        self.assertLess(mem_long.get("reservation", 0), mem_flat.get("reservation", 0))


class TestStatArb(unittest.TestCase):

    def test_no_orders_without_components(self):
        strat = build_strategy("stat_arb", "BASKET", {
            "position_limit": 50, "components": {"A": 2, "B": 1},
            "entry_z": 2.0, "exit_z": 0.5, "window": 10, "maker_size": 5,
        })
        # State has no component order depths
        state = _make_state(product="BASKET")
        orders, _ = strat.on_tick(state, {})
        self.assertEqual(len(orders), 0)


class TestBlackScholes(unittest.TestCase):

    def test_produces_orders_with_edge(self):
        strat = build_strategy("black_scholes", "OPTION", {
            "position_limit": 20, "underlying": "STOCK",
            "strike": 100, "risk_free_rate": 0.0,
            "total_ticks": 1000, "ticks_per_year": 2520000,
            "vol_window": 10, "vol_default": 0.3,
            "edge_threshold": 0.5, "maker_size": 5, "is_call": True,
        })
        # Build state with underlying
        od_option = OrderDepth()
        od_option.buy_orders = {5: 10}
        od_option.sell_orders = {7: -10}
        od_stock = OrderDepth()
        od_stock.buy_orders = {100: 20}
        od_stock.sell_orders = {101: -20}

        state = TradingState(
            traderData="",
            timestamp=1000,
            listings={
                "OPTION": Listing("OPTION", "OPTION", "XIRECS"),
                "STOCK": Listing("STOCK", "STOCK", "XIRECS"),
            },
            order_depths={"OPTION": od_option, "STOCK": od_stock},
            own_trades={"OPTION": [], "STOCK": []},
            market_trades={"OPTION": [], "STOCK": []},
            position={"OPTION": 0, "STOCK": 0},
            observations=Observation({}, {}),
        )
        orders, _ = strat.on_tick(state, {})
        self.assertIsInstance(orders, list)


class TestSignalTrader(unittest.TestCase):

    def test_follows_bot_signal(self):
        strat = build_strategy("signal_trader", "TEST", {
            "position_limit": 50, "tracked_bots": ["Olivia"],
            "signal_window": 5, "signal_strength": 1.0, "maker_size": 8,
        })
        trades = [
            Trade(symbol="TEST", price=101, quantity=5, buyer="Olivia", seller="Bot2", timestamp=999),
        ]
        state = _make_state(market_trades=trades)
        orders, _ = strat.on_tick(state, {})
        # Olivia bought → bullish signal → we should buy
        buy_orders = [o for o in orders if o.quantity > 0]
        self.assertTrue(len(buy_orders) > 0)


if __name__ == "__main__":
    unittest.main()
