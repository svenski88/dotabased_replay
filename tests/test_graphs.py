import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from graphs import (CLASSIFIER_VERSION, FEATURES, GraphCancelled, Micro19, classify, derive_graph,
                    feature_row, model_identity, needs_derivation, validate_sample)
from library import Store, filter_matches
from local_parser import LocalParser, PARSER_VERSION, ParseError
from test_local_parser import result
from test_replays import write_replay


def graph_fixture(advantage=lambda t: 0, duration=1800, winner=2):
    samples = []
    for t in range(duration):
        adv = advantage(t)
        r, d = 50000*(1+adv), 50000*(1-adv)
        samples.append({"time": t, "observed_time": t+.01, "radiant_net_worth": r, "dire_net_worth": d,
                        "net_worth_difference": r-d, "radiant_xp": r*2, "dire_xp": d*2,
                        "xp_difference": (r-d)*2, "player_net_worth": [r/5]*5+[d/5]*5,
                        "towers_dead_R": 0, "towers_dead_D": 0, "rax_dead_R": 0, "rax_dead_D": 0})
    return {"schema_version": 1, "complete": True, "duration": duration, "winner": winner,
            "extractor_version": PARSER_VERSION, "samples": samples, "events": []}


class CategoryTests(unittest.TestCase):
    def test_comeback_supersedes_oscillating_close_ending_and_records_interval(self):
        graph = graph_fixture(lambda t: -.15 if 500 <= t < 720 else .01)
        category = classify(graph)
        self.assertEqual(category["label"], "Comeback")
        self.assertEqual(category["basis"], "Gold")
        self.assertGreaterEqual(category["details"]["deficit_end"]-category["details"]["deficit_start"], 120)
        self.assertGreaterEqual(category["details"]["maximum_deficit_second"], 500)
        self.assertAlmostEqual(category["details"]["resource_deficit_max"], 15000)
        graph["winner"] = 3
        self.assertEqual(classify(graph)["label"], "Close Game")

    def test_large_short_swings_can_finish_close_and_final_minute_is_excluded(self):
        graph = graph_fixture(lambda t: .22*(-1 if (t//55)%2 else 1) if t < 1500 else .0 if t < 1740 else .7)
        category = classify(graph)
        self.assertEqual(category["label"], "Close Game")
        self.assertGreaterEqual(category["details"]["ending_neutral_fraction"], .6)

    def test_early_stomp_and_brief_dip_but_not_long_dip(self):
        self.assertEqual(classify(graph_fixture(lambda t: .1))["label"], "Stomp")
        self.assertEqual(classify(graph_fixture(lambda t: .04 if 900 <= t < 930 else .1))["label"], "Stomp")
        self.assertEqual(classify(graph_fixture(lambda t: .04 if 900 <= t < 1000 else .1))["label"], "Other")
        self.assertEqual(classify(graph_fixture(lambda t: -.04 if 900 <= t < 960 else .1))["label"], "Other")

    def test_late_dominance_is_other_and_winner_deficit_is_nonnegative(self):
        category = classify(graph_fixture(lambda t: .15 if t >= 700 else .01))
        self.assertEqual(category["label"], "Other")
        self.assertEqual(category["details"]["winner_max_deficit"], 0)

    def test_gold_primary_and_xp_fallback(self):
        graph = graph_fixture(lambda t: .1)
        for sample in graph["samples"]:
            sample.update(radiant_xp=20000, dire_xp=80000, xp_difference=-60000)
        self.assertEqual(classify(graph)["label"], "Stomp")
        for sample in graph["samples"]:
            sample.update(radiant_net_worth=None, dire_net_worth=None, net_worth_difference=None)
        category = classify(graph)
        self.assertEqual((category["label"], category["basis"]), ("Comeback", "XP fallback"))

    def test_unknown_outcome_gaps_and_missing_ending_are_insufficient(self):
        graph = graph_fixture()
        graph["winner"] = None
        self.assertEqual(classify(graph)["label"], "Insufficient data")
        graph["winner"] = 2
        graph["samples"] = graph["samples"][:1450] + graph["samples"][1540:]
        # Exactly 6% of the evaluation interval is missing in both resources.
        self.assertEqual(classify(graph)["label"], "Insufficient data")
        short = graph_fixture(duration=400)
        self.assertEqual(classify(short)["label"], "Insufficient data")

    def test_gap_breaks_sustained_deficit_and_model_never_affects_category(self):
        graph = graph_fixture(lambda t: -.15 if 500 <= t < 680 else 0)
        graph["samples"] = [s for s in graph["samples"] if s["time"] != 590]
        for s in graph["samples"]:
            s["radiant_win_probability"] = 1
        self.assertEqual(classify(graph)["label"], "Close Game")


class ModelTests(unittest.TestCase):
    def test_feature_contract_exact_order_signs_and_no_imputation(self):
        sample = graph_fixture(duration=1)["samples"][0]
        sample.update(towers_dead_R=2, towers_dead_D=5, rax_dead_R=1, rax_dead_D=3)
        row = feature_row(sample)
        self.assertEqual(len(row), len(FEATURES))
        self.assertEqual(row[-6:], [2, 5, 3, 1, 3, 2])
        sample["player_net_worth"][0] = None
        self.assertIsNone(feature_row(sample))
        sample["player_net_worth"][0] = 0
        self.assertIsNone(feature_row(sample))
        sample["player_net_worth"][0] = 10000
        sample["rax_dead_R"] = 7
        self.assertIsNone(feature_row(sample))

    def test_scoring_failure_keeps_category_and_extraction(self):
        graph = graph_fixture(lambda t: .1)
        class Broken:
            def predict(self, rows):
                raise RuntimeError("fixture inference unavailable")
        derive_graph(graph, model=Broken())
        self.assertEqual(graph["category"]["label"], "Stomp")
        self.assertEqual(graph["prediction"]["status"], "error")
        self.assertEqual(len(graph["samples"]), 1800)
        self.assertTrue(all("radiant_win_probability" not in s for s in graph["samples"]))

    def test_cancellation_between_batches_and_no_outcome_features(self):
        graph = graph_fixture()
        calls = []
        class Model:
            def predict(self, rows):
                calls.append(rows)
                return [.25]*len(rows)
        with self.assertRaises(GraphCancelled):
            derive_graph(graph, cancelled=lambda: bool(calls), model=Model())
        self.assertEqual(len(calls[0][0]), 19)
        self.assertEqual(len(calls[0]), 600)

    def test_lightgbm_reference_prediction(self):
        try:
            model = Micro19()
        except ImportError:
            self.skipTest("Install requirements-runtime.txt for native inference parity")
        # Independent golden outputs obtained from the original source artifact.
        rows = [[10000]*10+[50000,50000,0,0,0,0,0,0,0],
                [12000,8000,15000,6000,9000,7000,11000,8000,5000,9000,50000,40000,10000,2,5,3,1,3,2]]
        expected = [0.5222032224852916, 0.8698741070856804]
        for actual, reference in zip(model.predict(rows), expected):
            self.assertAlmostEqual(actual, reference, places=12)

    def test_stop_during_last_inference_batch_discards_result(self):
        stopped = []
        class Model:
            def predict(self, rows):
                stopped.append(True)
                return [.5]*len(rows)
        with self.assertRaises(GraphCancelled):
            derive_graph(graph_fixture(duration=400), cancelled=lambda: bool(stopped), model=Model())



class GraphStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "fixture.sqlite3")
        for library in self.store.libraries():
            self.store.remove_library(library["id"])
        self.store.add_library(self.root, "modern")
        self.path = self.root / "180.dem"
        write_replay(self.path, match_id=180)
        self.store.scan()
        self.copy = self.store.catalog()[0]["copies"][0]

    def save(self, graph=None):
        graph = graph or graph_fixture()
        graph.update(category=classify(graph), model_version=model_identity(), classifier_version=CLASSIFIER_VERSION)
        self.store.save_full_parse(self.copy, PARSER_VERSION, {**result(), "graph": graph})
        return graph

    def test_compressed_lazy_storage_preserves_annotations_and_filters(self):
        self.store.save_match("180", notes="keep note", rating=4)
        self.save()
        with self.store.connect() as db:
            self.assertNotIn('"samples"', db.execute("SELECT data FROM full_parse").fetchone()[0])
            row = db.execute("SELECT summary,payload FROM replay_graphs").fetchone()
            self.assertNotIn('"samples"', row[0])
            self.assertIsInstance(row[1], bytes)
        with patch("library.zlib.decompress", side_effect=AssertionError("catalog must stay lazy")):
            match = self.store.catalog()[0]
            self.assertEqual(match["category"], "Close Game")
            self.assertEqual((match["notes"], match["rating"]), ("keep note", 4))
            self.assertEqual(len(filter_matches([match], [], search="keep", category="Close Game")), 1)
            self.assertEqual(filter_matches([match], [], category="Stomp"), [])
        self.assertEqual(len(self.store.graph_for_match(match)["samples"]), 1800)

    def test_changed_stat_hides_graph_and_valid_duplicate_falls_back(self):
        self.save()
        duplicate = self.root / "180_1.dem"
        write_replay(duplicate, match_id=180)
        self.store.scan()
        match = self.store.catalog()[0]
        other = next(c for c in match["copies"] if c["path"] != self.copy["path"])
        self.store.save_full_parse(other, PARSER_VERSION, {**result(), "graph": self.store.graph_cached(self.copy)})
        self.path.write_bytes(b"changed recording")
        self.store.scan()
        match = self.store.catalog()[0]
        self.assertEqual(match["category"], "Close Game")
        self.assertIsNotNone(self.store.graph_for_match(match, self.copy["path"]))
        duplicate.write_bytes(b"also changed")
        self.store.scan()
        self.assertTrue(all(m["category"] == "Not parsed" for m in self.store.catalog()))

    def test_current_duplicate_graph_precedes_preferred_older_copy(self):
        self.save()
        duplicate = self.root / "180_1.dem"
        write_replay(duplicate, match_id=180)
        self.store.scan()
        other = next(c for c in self.store.catalog()[0]["copies"] if c["path"] != self.copy["path"])
        old = graph_fixture(lambda t: .1)
        old["category"] = classify(old)
        old["extractor_version"] = "old-helper"
        self.store.save_full_parse(other, "old-helper", {**result(), "graph": old})
        match = self.store.catalog()[0]
        self.assertEqual(match["category"], "Close Game")
        self.assertEqual(self.store.graph_for_match(match, other["path"])["category"]["label"], "Close Game")

    def test_model_and_classifier_versions_trigger_derivation_without_native_parse(self):
        graph = self.save()
        graph["model_version"] = "old-model"
        self.store.save_graph(self.copy, PARSER_VERSION, graph)
        runner = LocalParser()
        with patch.object(runner, "parse_file", side_effect=AssertionError("must not parse replay")), \
             patch.object(runner, "derive", side_effect=lambda g: g.update(model_version=model_identity(), classifier_version=CLASSIFIER_VERSION)) as derive:
            report = runner.parse_all(self.store, matches=self.store.catalog())
        self.assertEqual(report["cached"], 1)
        derive.assert_called_once()

    def test_cached_rescore_rechecks_physical_file_before_commit(self):
        graph = self.save()
        graph["model_version"] = "old-model"
        self.store.save_graph(self.copy, PARSER_VERSION, graph)
        runner = LocalParser()
        with patch.object(runner, "parse_file", side_effect=AssertionError("must not parse")), \
             patch.object(runner, "derive", side_effect=lambda g: self.path.write_bytes(b"changed during cached rescore")):
            report = runner.parse_all(self.store, matches=self.store.catalog())
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["cached"], 0)
        self.assertEqual(self.store.graph_cached(self.copy)["model_version"], "old-model")

    def test_missing_declared_graph_forces_refresh(self):
        self.store.save_full_parse(self.copy, PARSER_VERSION, {**result(), "graph_schema_version": 1})
        runner = LocalParser()
        with patch.object(runner, "parse_file", return_value=result()) as parse:
            report = runner.parse_all(self.store, matches=self.store.catalog())
        parse.assert_called_once()
        self.assertEqual(report["completed"], 1)

    def test_replay_change_during_scoring_does_not_commit(self):
        runner = LocalParser()
        with patch.object(runner, "parse_file", return_value={**result(), "graph": graph_fixture()}), \
             patch.object(runner, "derive", side_effect=lambda graph: self.path.write_bytes(b"replacement during scoring")):
            report = runner.parse_all(self.store, matches=self.store.catalog())
        self.assertEqual(report["failed"], 1)
        self.assertIsNone(self.store.full_cached(self.copy, PARSER_VERSION))

    def test_bounded_protocol_stream_and_completion(self):
        graph = graph_fixture(duration=400)
        entries = [{"event": "graph_sample", "entry": s} for s in graph["samples"]]
        final = {**result(), "graph_schema_version": 1, "graph_complete": True,
                 "graph_sample_count": 400, "graph_event_count": 0}
        fixture = self.root / "protocol.jsonl"
        original = subprocess.Popen
        script = "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())"
        def parse(records):
            fixture.write_text("\n".join(json.dumps(r) for r in records)+"\n", encoding="utf-8")
            with patch("local_parser.subprocess.Popen", side_effect=lambda *a, **kw: original([sys.executable, "-c", script, str(fixture)], **kw)):
                return LocalParser().parse_file("unused")
        self.assertGreater(sum(len(json.dumps(e)) for e in entries), 131072)
        self.assertEqual(len(parse(entries+[final])["graph"]["samples"]), 400)
        with self.assertRaisesRegex(ParseError, "incomplete"):
            parse(entries[:-1]+[final])
        with self.assertRaisesRegex(ParseError, "strictly ordered"):
            parse(entries[:1]*2+[final])
        bad = copy.deepcopy(entries[0])
        bad["entry"]["radiant_xp"] = float("nan")
        with self.assertRaisesRegex(ParseError, "Invalid graph"):
            parse([bad, final])


if __name__ == "__main__":
    unittest.main()
