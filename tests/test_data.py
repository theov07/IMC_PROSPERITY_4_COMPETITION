import tempfile
import unittest
from pathlib import Path

from prosperity.tooling.data import MarketDataLoader


class MarketDataLoaderPathTests(unittest.TestCase):
    def test_load_prices_resolves_nested_round_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            round_dir = root / "round_1"
            round_dir.mkdir()
            prices_path = round_dir / "prices_round_1_day_-2.csv"
            prices_path.write_text(
                "day;timestamp;product;bid_price_1;bid_volume_1;ask_price_1;ask_volume_1\n"
                "-2;0;AMETHYSTS;9999;10;10001;10\n",
                encoding="utf-8",
            )

            loader = MarketDataLoader(root)
            prices_df = loader.load_prices("prices_round_1_day_-2.csv")

            self.assertEqual(len(prices_df), 1)
            self.assertEqual(prices_df.iloc[0]["product"], "AMETHYSTS")

    def test_available_days_reads_nested_round_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            round_dir = root / "round_0"
            round_dir.mkdir()
            (round_dir / "prices_round_0_day_-2.csv").write_text("day;timestamp;product\n", encoding="utf-8")
            (round_dir / "prices_round_0_day_-1.csv").write_text("day;timestamp;product\n", encoding="utf-8")

            loader = MarketDataLoader(root)

            self.assertEqual(loader.available_days(0), ["-1", "-2"])


if __name__ == "__main__":
    unittest.main()
