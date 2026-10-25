import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app import pinned_teams
from library import Store
from local_parser import LocalParser, ParseError, PARSER_VERSION, validate_result


def result(**fields):
    return dict(event="result", schema_version=1, helper_version=PARSER_VERSION, complete=True, final_state=6,
                fields={"radiant_score": 39, "dire_score": 24, **fields}, provenance={"radiant_score": "team kills", "dire_score": "team kills"})


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "test.sqlite3")
        with self.store.connect() as db:
            db.execute("DELETE FROM libraries")
        self.store.add_library(str(self.root), "classic")

    def catalog(self, names=("180.dem",)):
        for name in names:
            (self.root / name).write_bytes(b"synthetic invalid replay")
        self.store.scan()
        return self.store.catalog()

    def test_cancel_before_worker_start_never_erased(self):
        self.catalog()
        parser = LocalParser()
        parser.reset()
        parser.stop()
        with patch.object(parser, "parse_file", side_effect=AssertionError("must not start")):
            report = parser.parse_all(self.store)
        self.assertTrue(report["cancelled"])
        self.assertEqual(report["completed"], 0)

    def test_cache_stat_change_failure_continue_duplicate_fallback_and_metadata(self):
        matches = self.catalog(("180.dem", "180_1.dem", "181.dem"))
        self.store.save_match("180", notes="preserved", rating=4)
        self.store.cache("matches/180", {"radiant_score": 0, "dire_score": 0, "players": [{"kills": 5}], "start_time": 1440000000}, 100)
        before = next(m for m in self.store.catalog() if m["key"] == "180")
        self.assertIsNone(before["radiant_score"])
        parser = LocalParser()
        def parse(path, progress):
            if path.name == "180.dem":
                raise ParseError("synthetic bad copy")
            return result(duration=1800, league_id=0, players=[])
        with patch.object(socket, "create_connection", side_effect=AssertionError("offline")), patch.object(parser, "parse_file", side_effect=parse) as call:
            report = parser.parse_all(self.store)
            self.assertEqual(report["completed"], 2)
            self.assertEqual(call.call_count, 3)
            call.reset_mock()
            self.assertEqual(parser.parse_all(self.store)["cached"], 2)
            call.assert_not_called()
            changed = self.root / "180_1.dem"
            changed.write_bytes(b"changed replay")
            report = parser.parse_all(self.store, matches=matches)
            self.assertEqual(report["failed"], 1)
        after = next(m for m in self.store.catalog() if m["key"] == "180")
        self.assertEqual((after["radiant_score"], after["dire_score"]), (39, 24))
        self.assertEqual((after["notes"], after["rating"], after["start_time"]), ("preserved", 4, 1440000000))
        self.assertEqual(self.store.cached("matches/180")["data"]["radiant_score"], 0)
        self.assertNotIn("score_notice", after)

    def test_recovered_identity_groups_before_notes_api_and_conflicts_are_rejected(self):
        matches = self.catalog(("unknown.dem", "180.dem"))
        unknown = next(m for m in matches if not m.get("match_id"))
        self.store.save_match("180", notes="linked by recovered identity", rating=5)
        recovered = result(match_id="180", players=[{"account_id": 4, "name": "recorded player", "team": 2}], end_time=1440000000, league_id=42)
        self.store.save_full_parse(unknown["copies"][0], PARSER_VERSION, recovered)
        merged = self.store.catalog()
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["copies"]), 2)
        self.assertEqual(merged[0]["notes"], "linked by recovered identity")
        self.assertEqual(merged[0]["league_id"], 42)
        self.assertEqual(merged[0]["players"][0]["name"], "recorded player")
        known_copy = next(c for c in merged[0]["copies"] if Path(c["path"]).name == "180.dem")
        self.store.save_full_parse(known_copy, PARSER_VERSION, result(match_id="999"))
        merged = self.store.catalog()[0]
        self.assertEqual(merged["match_id"], "180")
        self.assertTrue(any("conflicts" in error for error in merged["errors"]))

    def test_default_batch_refreshes_catalog_and_invalidates_changed_success(self):
        match = self.catalog()[0]
        self.store.save_full_parse(match["copies"][0], PARSER_VERSION, result())
        (self.root / "180.dem").write_bytes(b"changed to incomplete replay")
        (self.root / "181.dem").write_bytes(b"new incomplete replay")
        parser = LocalParser()
        with patch.object(parser, "parse_file", side_effect=ParseError("no post-game", "incomplete")) as call:
            report = parser.parse_all(self.store)
        self.assertEqual((report["total"], report["cached"], report["failed"]), (2, 0, 2))
        self.assertEqual(call.call_count, 2)
        refreshed = self.store.catalog()
        self.assertTrue(all(m["radiant_score"] is None for m in refreshed))
        self.assertEqual(next(m for m in refreshed if m["key"] == "180")["copies"][0]["size"], len(b"changed to incomplete replay"))

    def test_incremental_commit_survives_stop_and_restart_and_timeout_continues(self):
        matches = self.catalog(("180.dem", "181.dem", "182.dem"))
        parser = LocalParser()
        calls = []
        def interrupted(path, progress):
            calls.append(path.name)
            if len(calls) == 2:
                parser.stop()
                raise ParseError("stopped", "cancelled")
            return result()
        with patch.object(parser, "parse_file", side_effect=interrupted):
            report = parser.parse_all(self.store, matches=matches)
        self.assertEqual(report["completed"], 1)
        self.assertTrue(report["cancelled"])
        self.assertEqual(sum(m["local_complete"] for m in self.store.catalog()), 1)
        parser.reset()
        def resumed(path, progress):
            if path.name == calls[1]:
                raise ParseError("test timeout", "timeout")
            return result()
        with patch.object(parser, "parse_file", side_effect=resumed):
            report = parser.parse_all(self.store, matches=matches)
        self.assertEqual((report["cached"], report["completed"], report["failed"]), (1, 1, 1))
        statuses = [a["status"] for m in self.store.catalog() for a in m["parse_attempts"]]
        self.assertEqual(statuses, ["timeout"])

    def test_quiet_helper_stop_and_timeout_cleanup_and_bad_protocol(self):
        import sys
        original = subprocess.Popen
        parser = LocalParser(timeout=.15)
        def quiet(*args, **kwargs):
            return original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        with patch("local_parser.subprocess.Popen", side_effect=quiet):
            with self.assertRaises(ParseError) as caught:
                parser.parse_file("unused")
            self.assertEqual(caught.exception.status, "timeout")
            self.assertIsNone(parser.process)
            parser.timeout = 600
            timer = threading.Timer(.1, parser.stop)
            timer.start()
            started = time.monotonic()
            with self.assertRaises(ParseError) as caught:
                parser.parse_file("unused")
            timer.join()
            self.assertEqual(caught.exception.status, "cancelled")
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNone(parser.process)
        parser.reset()
        with patch("local_parser.subprocess.Popen", side_effect=lambda *a, **kw: original([sys.executable, "-c", "print('[]')"], **kw)):
            with self.assertRaisesRegex(ParseError, "non-object"):
                parser.parse_file("unused")

    def test_validation_and_team_grouping(self):
        self.assertEqual(validate_result(result())["fields"]["dire_score"], 24)
        with self.assertRaises(ParseError):
            validate_result(result(lobby_type=-1))
        value = pinned_teams({"players": [{"account_id": 1, "team": 2}, {"account_id": 2, "team": 3}, {"account_id": 3}]}, {1: "Long Radiant nickname", 2: "Dire name", 3: "Unknown name"})
        self.assertEqual(value, "Radiant: Long Radiant nickname\nDire: Dire name\nUnknown team: Unknown name")


if __name__ == "__main__":
    unittest.main()
