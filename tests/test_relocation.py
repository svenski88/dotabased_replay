"""External folder moves recover caches without parsing or touching replays."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from library import Store
from local_parser import PARSER_VERSION
from test_graphs import graph_fixture
from test_local_parser import result
from test_replays import write_replay


class RelocationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.old, self.new = self.root / "old-storage", self.root / "new-storage"
        self.old.mkdir()
        self.new.mkdir()
        self.store = Store(self.root / "library.sqlite3")
        for library in self.store.libraries():
            self.store.remove_library(library["id"])
        self.store.add_library(self.old, "modern")
        self.source = self.old / "123.dem"
        write_replay(self.source)
        self.store.scan()
        self.copy = self.store.catalog()[0]["copies"][0]
        self.graph = graph_fixture(duration=10)
        self.store.save_full_parse(self.copy, PARSER_VERSION, {**result(match_id="123"), "graph": self.graph})
        self.store.save_match("123", notes="keep", rating=5, client="classic")

    def move(self):
        destination = self.new / self.source.name
        shutil.copy2(self.source, destination)
        self.source.unlink()
        for library in self.store.libraries():
            self.store.remove_library(library["id"])
        self.store.add_library(self.new, "modern")
        return destination

    def test_manual_move_recovers_metadata_graph_and_annotations_idempotently(self):
        destination = self.move()
        self.assertEqual(self.store.scan()["recovered"], 1)
        match = self.store.catalog()[0]
        self.assertTrue(match["local_complete"])
        self.assertEqual(match["radiant_score"], 39)
        self.assertEqual((match["notes"], match["rating"], match["client_override"]), ("keep", 5, "classic"))
        self.assertEqual(self.store.graph_for_match(match), self.graph)
        self.assertEqual(self.store.scan()["recovered"], 0)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM full_parse").fetchone()[0], 2)
        self.assertEqual(destination.stat().st_mtime_ns, self.copy["mtime"])

    def test_already_scanned_new_location_recovers_from_equivalent_old_copies(self):
        # In-app migrations retain both the download and old storage caches.
        duplicate = {**self.copy, "path": str(self.old / "download-copy.dem")}
        self.store.save_full_parse(duplicate, PARSER_VERSION, {**result(match_id="123"), "graph": self.graph})
        self.move()
        with self.store.connect() as db:
            db.execute("DELETE FROM full_parse WHERE path=?", (self.copy["path"],))
        self.store.scan()
        destination = self.store.catalog()[0]["copies"][0]
        with self.store.connect() as db:
            db.execute("DELETE FROM full_parse WHERE path=?", (destination["path"],))
            db.execute("DELETE FROM replay_graphs WHERE path=?", (destination["path"],))
        # Add a second equivalent candidate again to exercise duplicate resolution.
        self.store.save_full_parse(self.copy, PARSER_VERSION, {**result(match_id="123"), "graph": self.graph})
        report = self.store.scan()
        self.assertEqual((report["cached"], report["recovered"]), (1, 1))
        self.assertEqual(self.store.graph_for_match(self.store.catalog()[0]), self.graph)

    def test_changed_stats_wrong_identity_and_unknown_identity_are_not_reused(self):
        destination = self.move()
        os.utime(destination, ns=(self.copy["mtime"] + 1000000, self.copy["mtime"] + 1000000))
        self.assertEqual(self.store.scan()["recovered"], 0)
        os.utime(destination, ns=(self.copy["mtime"], self.copy["mtime"]))
        self.store.save_full_parse(self.copy, PARSER_VERSION, result(match_id="999"))
        self.assertEqual(self.store.scan()["recovered"], 0)
        self.assertFalse(self.store.catalog()[0]["local_complete"])
        with self.store.connect() as db:
            db.execute("DELETE FROM full_parse")
        unknown = {**self.copy, "path": str(self.old / "unknown.dem")}
        self.store.save_full_parse(unknown, PARSER_VERSION, result())
        self.assertEqual(self.store.scan()["recovered"], 0)

    def test_older_cache_without_recorded_id_can_use_matching_numeric_filename(self):
        self.store.save_full_parse(self.copy, PARSER_VERSION, {**result(), "graph": self.graph})
        self.move()
        self.assertEqual(self.store.scan()["recovered"], 1)
        self.assertEqual(self.store.graph_for_match(self.store.catalog()[0]), self.graph)

    def test_conflicting_metadata_versions_and_graphs_are_refused(self):
        duplicate = {**self.copy, "path": str(self.old / "duplicate.dem")}
        self.move()
        for version, fields, graph in (
                (PARSER_VERSION, {"match_id": "123", "duration": 900}, self.graph),
                ("older-parser", {"match_id": "123"}, self.graph),
                (PARSER_VERSION, {"match_id": "123"}, {**self.graph, "winner": 3})):
            self.store.save_full_parse(duplicate, version, {**result(**fields), "graph": graph})
            self.assertEqual(self.store.scan()["recovered"], 0)
            self.assertFalse(self.store.catalog()[0]["local_complete"])

    def test_existing_success_preserved_and_parser_version_not_upgraded(self):
        self.store.save_full_parse(self.copy, "old-version", {**result(match_id="123"), "graph": self.graph})
        self.move()
        self.assertEqual(self.store.scan()["recovered"], 1)
        destination = self.store.catalog()[0]["copies"][0]
        self.assertIsNone(self.store.full_cached(destination, PARSER_VERSION))
        self.assertIsNotNone(self.store.full_cached(destination, "old-version"))
        self.store.save_full_parse(destination, PARSER_VERSION, result(match_id="123", duration=800))
        self.assertEqual(self.store.scan()["recovered"], 0)
        self.assertEqual(self.store.catalog()[0]["duration"], 800)
