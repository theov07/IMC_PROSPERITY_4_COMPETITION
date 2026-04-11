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

    def test_parse_lambda_logs_supports_quote_first_and_reservation_formats(self):
        runtime_logs = [
            {
                "timestamp": 900,
                "sandboxLog": "",
                "lambdaLog": (
                    '{"product":"EMERALDS","chunk_end":900,"log":[[0,9993.5,9992,9995],'
                    '[100,9994.0,9993,9996]]}'
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

        self.assertEqual(tomatoes["bid_price"].tolist(), [5004, 5005])
        self.assertEqual(tomatoes["ask_price"].tolist(), [5009, 5010])
        self.assertTrue(tomatoes["reservation"].isna().all())


if __name__ == "__main__":
    unittest.main()
