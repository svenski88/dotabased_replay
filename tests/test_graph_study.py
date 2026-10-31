"""Synthetic regression checks for bounded sampling and unknown graph data."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "study_graphs", Path(__file__).resolve().parents[1] / "scripts/study_graphs.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


class GraphStudyTests(unittest.TestCase):
    def test_sample_bound_dedup_eras_and_missing_footer(self):
        catalog = []
        for era in ("classic", "modern"):
            for i in range(5):
                catalog.append({"end_time": i + 1, "players": [True], "errors": [],
                                "copies": [{"path": f"{era}-{i}.dem", "client": era, "size": 2000000}]})
        catalog.append({"errors": ["No complete file-info footer"],
                        "copies": [{"path": "partial.dem", "client": "modern", "size": 2000000}]})
        result = study.select_samples(catalog)
        self.assertEqual(len(result), 6)
        self.assertEqual(len({s["path"] for s in result}), 6)
        self.assertEqual([s["path"] for s in result[:2]], ["classic-0.dem", "classic-4.dem"])
        self.assertEqual(result[-1]["path"], "partial.dem")
        self.assertEqual(study.select_samples([]), [])

    def test_missing_values_are_unknown_and_gaps_remain_visible(self):
        data = {"samples": [{"time": 0, "radiant_net_worth": 0, "dire_net_worth": 0,
                             "net_worth_difference": 0},
                            {"time": 50, "radiant_net_worth": 500}],
                "events": [{"kind": "roshan", "time": None}]}
        result = study.summarize(data)
        self.assertEqual(result["coverage"]["net_worth"]["valid_samples"], 1)
        self.assertEqual(result["coverage"]["xp"]["valid_samples"], 0)
        self.assertEqual(result["largest_sample_gap_seconds"], 50)
        self.assertEqual(result["untimed_events"], 1)
        self.assertIsNone(result["shape_features"]["winner_largest_deficit_fraction"])

    def test_winner_relative_deficit_uses_verified_winner(self):
        data = {"winner": 2, "samples": [
            {"time": 600, "radiant_net_worth": 40, "dire_net_worth": 60, "net_worth_difference": -20},
            {"time": 601, "radiant_net_worth": 60, "dire_net_worth": 40, "net_worth_difference": 20}]}
        self.assertEqual(study.summarize(data)["shape_features"]["winner_largest_deficit_fraction"], .2)
        del data["winner"]
        self.assertIsNone(study.summarize(data)["shape_features"]["winner_largest_deficit_fraction"])


if __name__ == "__main__":
    unittest.main()
