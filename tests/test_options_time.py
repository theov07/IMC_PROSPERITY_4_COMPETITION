import json
import unittest

from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)


class OptionTimeTests(unittest.TestCase):
    def test_legacy_tick_config_resolves_raw_timestamp_units(self):
        params = {"ticks_per_day": 10000, "ts_increment": 100}

        self.assertEqual(timestamp_units_per_day_from_params(params), 1_000_000.0)

    def test_tte_uses_raw_timestamp_units(self):
        tte = time_to_expiry_days(999900, 5.0, timestamp_units_per_day=1_000_000)

        self.assertAlmostEqual(tte, 4.0001, places=4)

    def test_historical_backtest_day_overrides_live_tte(self):
        trader_data = json.dumps({"_backtest": {"round": 3, "day": 1}})
        tte = resolve_initial_tte_days(trader_data, 5.0, {0: 8.0, 1: 7.0, 2: 6.0})

        self.assertEqual(tte, 7.0)


if __name__ == "__main__":
    unittest.main()
