import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
import pandas as pd

from prosperity.tooling.logs import _parse_lambda_logs, load_official_log
from prosperity.tooling.reconcile import discover_backtest_json, reconcile_backtest_to_official


ACTIVITIES = (
    "day;timestamp;product;bid_price_1;bid_volume_1;ask_price_1;ask_volume_1;profit_and_loss\n"
    "-1;0;EMERALDS;9999;10;10001;10;0.0\n"
)

GRAPH = (
    "timestamp;value\n"
    "0;12.5\n"
)


class TestOfficialLogLoading(unittest.TestCase):

    def test_loads_json_and_auto_merges_companion_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "43130.json"
            log_path = root / "43130.log"

            json_payload = {
                "round": "0",
                "status": "FINISHED",
                "profit": 123.5,
                "activitiesLog": ACTIVITIES,
                "graphLog": GRAPH,
                "positions": [{"symbol": "EMERALDS", "quantity": 3}],
            }
            log_payload = {
                "submissionId": "abc-123",
                "activitiesLog": ACTIVITIES,
                "tradeHistory": [
                    {
                        "timestamp": 0,
                        "buyer": "SUBMISSION",
                        "seller": "",
                        "symbol": "EMERALDS",
                        "currency": "XIRECS",
                        "price": 10000.0,
                        "quantity": 4,
                    }
                ],
                "logs": [{"timestamp": 0, "sandboxLog": "", "lambdaLog": ""}],
            }

            json_path.write_text(json.dumps(json_payload), encoding="utf-8")
            log_path.write_text(json.dumps(log_payload), encoding="utf-8")

            official = load_official_log(json_path)

            self.assertEqual(official.submission_id, "abc-123")
            self.assertEqual(official.profit, 123.5)
            self.assertEqual(official.status, "FINISHED")
            self.assertEqual(len(official.activities), 1)
            self.assertEqual(len(official.trades), 1)
            self.assertEqual(len(official.graph), 1)
            self.assertEqual(len(official.positions), 1)
            self.assertEqual(len(official.runtime_logs), 1)
            self.assertEqual({path.suffix for path in official.loaded_paths}, {".json", ".log"})
            self.assertEqual(official.analysis_group, root.name)

    def test_loads_log_and_auto_merges_companion_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "43130.json"
            log_path = root / "43130.log"

            json_path.write_text(
                json.dumps(
                    {
                        "round": "0",
                        "status": "FINISHED",
                        "profit": 77.0,
                        "activitiesLog": ACTIVITIES,
                        "graphLog": GRAPH,
                    }
                ),
                encoding="utf-8",
            )
            log_path.write_text(
                json.dumps(
                    {
                        "submissionId": "from-log",
                        "activitiesLog": ACTIVITIES,
                        "tradeHistory": [],
                        "logs": [],
                    }
                ),
                encoding="utf-8",
            )

            official = load_official_log(log_path)

            self.assertEqual(official.submission_id, "from-log")
            self.assertEqual(official.profit, 77.0)
            self.assertEqual(official.status, "FINISHED")
            self.assertFalse(official.activities.empty)

    def test_loads_single_file_without_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "solo.json"
            json_path.write_text(
                json.dumps(
                    {
                        "round": "0",
                        "status": "FINISHED",
                        "profit": 10.0,
                        "activitiesLog": ACTIVITIES,
                        "graphLog": GRAPH,
                    }
                ),
                encoding="utf-8",
            )

            official = load_official_log(json_path)

            self.assertEqual(official.profit, 10.0)
            self.assertIsNone(official.companion_path)
            self.assertEqual(len(official.loaded_paths), 1)

    def test_prefers_meaningful_parent_folder_for_analysis_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "leo_round0_naive"
            root.mkdir(parents=True, exist_ok=True)
            json_path = root / "43130.json"
            log_path = root / "43130.log"
            py_path = root / "43130.py"

            json_path.write_text(
                json.dumps(
                    {
                        "round": "0",
                        "status": "FINISHED",
                        "profit": 10.0,
                        "activitiesLog": ACTIVITIES,
                    }
                ),
                encoding="utf-8",
            )
            log_path.write_text(
                json.dumps(
                    {
                        "submissionId": "sub-1",
                        "activitiesLog": ACTIVITIES,
                        "tradeHistory": [],
                    }
                ),
                encoding="utf-8",
            )
            py_path.write_text("class Trader:\n    pass\n", encoding="utf-8")

            official = load_official_log(json_path)

            self.assertEqual(official.analysis_group, "leo_round0_naive")
            self.assertIsNotNone(official.submission_source_path)

    def test_parse_lambda_logs_supports_columns_and_legacy_formats(self):
        runtime_logs = [
            {
                "timestamp": 900,
                "sandboxLog": "",
                "lambdaLog": (
                    '{"product":"EMERALDS","trace":"quote_trace","chunk_end":900,'
                    '"columns":["timestamp","reservation","bid_price","ask_price","tighten","skew"],'
                    '"log":[[0,9993.5,9992,9995,1,-2],[100,9994.0,9993,9996,0,1]]}'
                    '{"product":"TOMATOES","chunk_end":900,"log":[[0,5004,5009,4,0],'
                    '[100,5005,5010,3,0]]}'
                ),
            }
        ]

        parsed = _parse_lambda_logs(pd.DataFrame(runtime_logs))

        self.assertEqual(len(parsed), 4)

        emeralds = parsed[parsed["product"] == "EMERALDS"].sort_values("timestamp")
        tomatoes = parsed[parsed["product"] == "TOMATOES"].sort_values("timestamp")

        self.assertEqual(emeralds["bid_price"].tolist(), [9992, 9993])
        self.assertEqual(emeralds["ask_price"].tolist(), [9995, 9996])
        self.assertEqual(emeralds["reservation"].tolist(), [9993.5, 9994.0])
        self.assertEqual(emeralds["tighten"].tolist(), [1, 0])
        self.assertEqual(emeralds["skew"].tolist(), [-2, 1])

        self.assertEqual(tomatoes["bid_price"].tolist(), [5004, 5005])
        self.assertEqual(tomatoes["ask_price"].tolist(), [5009, 5010])
        self.assertTrue(tomatoes["reservation"].isna().all())

    def test_reconcile_backtest_to_official_compares_product_level_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "43130.json"
            log_path = root / "43130.log"

            activities = (
                "day;timestamp;product;bid_price_1;bid_volume_1;ask_price_1;ask_volume_1;profit_and_loss\n"
                "-1;0;EMERALDS;9999;10;10001;10;12.0\n"
                "-1;0;TOMATOES;4999;10;5001;10;8.0\n"
            )

            json_path.write_text(
                json.dumps(
                    {
                        "round": "0",
                        "status": "FINISHED",
                        "profit": 20.0,
                        "activitiesLog": activities,
                        "graphLog": GRAPH,
                        "positions": [
                            {"symbol": "EMERALDS", "quantity": 1},
                            {"symbol": "TOMATOES", "quantity": -2},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            log_path.write_text(
                json.dumps(
                    {
                        "submissionId": "reconcile-1",
                        "activitiesLog": activities,
                        "tradeHistory": [
                            {
                                "timestamp": 0,
                                "buyer": "SUBMISSION",
                                "seller": "",
                                "symbol": "EMERALDS",
                                "currency": "XIRECS",
                                "price": 10000.0,
                                "quantity": 2,
                            },
                            {
                                "timestamp": 100,
                                "buyer": "",
                                "seller": "SUBMISSION",
                                "symbol": "TOMATOES",
                                "currency": "XIRECS",
                                "price": 5002.0,
                                "quantity": 3,
                            },
                        ],
                        "logs": [],
                    }
                ),
                encoding="utf-8",
            )

            official = load_official_log(json_path)
            backtest = {
                "strategy": "champion",
                "round": 0,
                "execution_rule": "realistic",
                "days": [
                    {
                        "day": "-1",
                        "pnl": 25.0,
                        "fills": [
                            {
                                "timestamp": 0,
                                "symbol": "EMERALDS",
                                "side": "BUY",
                                "price": 10000,
                                "quantity": 3,
                                "aggressive": False,
                            },
                            {
                                "timestamp": 100,
                                "symbol": "TOMATOES",
                                "side": "SELL",
                                "price": 5001,
                                "quantity": 1,
                                "aggressive": False,
                            },
                        ],
                        "product_summaries": {
                            "EMERALDS": {
                                "symbol": "EMERALDS",
                                "pnl": 15.0,
                                "ending_position": 3,
                                "trades": 1,
                                "traded_volume": 3,
                                "turnover": 30000.0,
                                "max_abs_position": 3,
                            },
                            "TOMATOES": {
                                "symbol": "TOMATOES",
                                "pnl": 10.0,
                                "ending_position": -1,
                                "trades": 1,
                                "traded_volume": 1,
                                "turnover": 5001.0,
                                "max_abs_position": 1,
                            },
                        },
                        "equity_curve": [],
                        "quotes": [],
                        "feature_ticks": [],
                    }
                ],
            }

            report = reconcile_backtest_to_official(backtest, official)

            self.assertEqual(report["backtest"]["execution_rule"], "realistic")
            self.assertEqual(report["official"]["submission_id"], "reconcile-1")
            self.assertAlmostEqual(report["delta"]["total_pnl"], 5.0)
            self.assertAlmostEqual(report["per_product"]["EMERALDS"]["delta"]["pnl"], 3.0)
            self.assertEqual(report["per_product"]["EMERALDS"]["delta"]["trade_count"], 0)
            self.assertEqual(report["per_product"]["EMERALDS"]["delta"]["ending_position"], 2)
            self.assertEqual(report["per_product"]["TOMATOES"]["delta"]["sell_qty"], -2)

    def test_discover_backtest_json_matches_strategy_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs" / "leo_round0_naiveV8"
            log_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir = root / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            json_path = log_dir / "84616.json"
            log_path = log_dir / "84616.log"
            py_path = log_dir / "84616.py"
            bt_v8_path = artifacts_dir / "backtest_leo_naive_v8.json"
            bt_v7_path = artifacts_dir / "backtest_leo_naive_v7.json"

            json_path.write_text(
                json.dumps(
                    {
                        "round": "0",
                        "status": "FINISHED",
                        "profit": 10.0,
                        "activitiesLog": ACTIVITIES,
                        "graphLog": GRAPH,
                    }
                ),
                encoding="utf-8",
            )
            log_path.write_text(
                json.dumps(
                    {
                        "submissionId": "sub-v8",
                        "activitiesLog": ACTIVITIES,
                        "tradeHistory": [],
                        "logs": [],
                    }
                ),
                encoding="utf-8",
            )
            py_path.write_text(
                "PRODUCTS = {'EMERALDS': {'strategy': 'naive_tight_mm_v8'}}\n",
                encoding="utf-8",
            )

            for path, strategy in ((bt_v8_path, "leo_naive_v8"), (bt_v7_path, "leo_naive_v7")):
                path.write_text(
                    json.dumps(
                        {
                            "strategy": strategy,
                            "round": 0,
                            "days": [{"day": "-1", "pnl": 0.0, "fills": [], "product_summaries": {}, "equity_curve": []}],
                        }
                    ),
                    encoding="utf-8",
                )

            official = load_official_log(json_path)
            discovered = discover_backtest_json(official, search_root=root)

            self.assertEqual(discovered, bt_v8_path)


if __name__ == "__main__":
    unittest.main()
