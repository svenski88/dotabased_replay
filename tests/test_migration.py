from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from library import Store
from migration import make_plan, migrate, publish_copy, save_rule
from test_replays import write_replay


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source, self.storage = self.root / "downloads", self.root / "storage"
        self.source.mkdir()
        self.storage.mkdir()
        self.store = Store(self.root / "test.sqlite3")
        for library in self.store.libraries():
            self.store.remove_library(library["id"])
        self.store.add_library(self.source, "modern")
        self.rule = {"client": "modern", "source": str(self.source), "storage": str(self.storage), "before": "2025-01-01"}

    def replay(self, name="123.dem", modified="2024-06-01"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_replay(path)
        timestamp = datetime.fromisoformat(modified).timestamp()
        os.utime(path, (timestamp, timestamp))
        self.store.scan()
        return path

    def test_rule_persists_and_cutoff_is_strict_local_midnight(self):
        old = self.replay()
        self.replay("new.dem", "2025-01-01")
        self.replay("later.dem", "2025-02-01")
        save_rule(self.store, self.rule)
        reloaded = Store(self.store.path)
        self.assertEqual(reloaded.get_pref("migration_rules")["modern"], self.rule)
        plan = make_plan(reloaded, self.rule)
        self.assertEqual([entry.source.path for entry in plan.files], [str(old)])
        self.assertTrue(old.exists())
        self.assertEqual(list(self.storage.iterdir()), [])
        self.assertTrue(migrate(self.store, plan)["cancelled"])
        self.assertTrue(old.exists())

    def test_move_preserves_cache_annotations_and_nested_paths(self):
        source = self.replay("nested/123.dem")
        match = self.store.catalog()[0]
        copy = match["copies"][0]
        self.store.save_match("123", notes="my note", client="classic", rating=4)
        with self.store.connect() as db:
            db.execute("INSERT INTO full_parse VALUES (?,?,?,?,?,?)", (str(source), copy["size"], copy["mtime"], "v1", json.dumps({"complete": True, "schema_version": 1, "fields": {}}), 1))
            db.execute("INSERT INTO replay_graphs VALUES (?,?,?,?,?,?,?)", (str(source), copy["size"], copy["mtime"], "graph-v1", "{}", b"graph", 1))
            db.execute("INSERT INTO parse_attempts VALUES (?,?,?,?,?,?,?)", (str(source), copy["size"], copy["mtime"], "v1", "complete", "", 1))
        result = migrate(self.store, make_plan(self.store, self.rule), confirmed=True)
        self.assertEqual(result["failed"], [])
        self.assertFalse(source.exists())
        destination = self.storage / "nested/123.dem"
        self.assertEqual(destination.stat().st_mtime_ns, copy["mtime"])
        self.store.scan()
        match = self.store.catalog()[0]
        self.assertEqual((match["notes"], match["rating"], match["client_override"]), ("my note", 4, "classic"))
        self.assertEqual(match["copies"][0]["path"], str(destination))
        self.assertEqual(match["copies"][0]["client"], "modern")
        with self.store.connect() as db:
            for table in ("full_parse", "replay_graphs", "parse_attempts"):
                cached = db.execute(f"SELECT * FROM {table} WHERE path=?", (str(destination),)).fetchone()
                self.assertEqual((cached["size"], cached["mtime"]), (copy["size"], copy["mtime"]))

    def test_unknown_match_notes_rating_override_and_provenance_follow_path(self):
        source = self.source / "unknown.dem"
        source.write_bytes(b"unknown replay")
        os.utime(source, (0, 0))
        self.store.scan()
        old_key = "file:" + str(source)
        self.store.save_match(old_key, notes="unknown note", rating=3, client="classic")
        with self.store.connect() as db:
            db.execute("INSERT INTO note_imports VALUES (?,?,?,?,?,?,?)", ("fixture", "hash", old_key, "note", "line", 1, 0))
        result = migrate(self.store, make_plan(self.store, self.rule), confirmed=True)
        self.assertEqual(result["failed"], [])
        match = self.store.catalog()[0]
        new_key = "file:" + str(self.storage / "unknown.dem")
        self.assertEqual((match["key"], match["notes"], match["rating"], match["client_override"]), (new_key, "unknown note", 3, "classic"))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT match_id FROM note_imports").fetchone()[0], new_key)

    def test_existing_destination_and_late_collision_never_overwrite(self):
        source = self.replay()
        destination = self.storage / source.name
        plan = make_plan(self.store, self.rule)
        destination.write_bytes(b"keep")
        refused = make_plan(self.store, self.rule)
        self.assertFalse(refused.files)
        self.assertEqual(len(refused.errors), 1)
        result = migrate(self.store, plan, confirmed=True)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(destination.read_bytes(), b"keep")
        self.assertTrue(source.exists())

    def test_changed_source_is_refused(self):
        source = self.replay()
        plan = make_plan(self.store, self.rule)
        source.write_bytes(b"changed")
        result = migrate(self.store, plan, confirmed=True)
        self.assertEqual(len(result["failed"]), 1)
        self.assertTrue(source.exists())
        self.assertFalse((self.storage / source.name).exists())

    def test_storage_disappearing_after_publish_keeps_source(self):
        source = self.replay()
        def publish_then_remove(*args):
            publish_copy(*args)
            Path(args[1].destination).unlink()
        with patch("migration.publish_copy", side_effect=publish_then_remove):
            result = migrate(self.store, make_plan(self.store, self.rule), confirmed=True)
        self.assertEqual(len(result["failed"]), 1)
        self.assertTrue(source.exists())

    def test_database_failure_and_removal_failure_retain_recoverable_copy(self):
        source = self.replay()
        with patch("migration.publish_copy", side_effect=ValueError("fixture database error")):
            result = migrate(self.store, make_plan(self.store, self.rule), confirmed=True)
        self.assertTrue(source.exists())
        self.assertTrue((self.storage / source.name).exists())
        self.assertEqual(len(result["failed"]), 1)
        # A retained verified copy is discovered by a later scan; it is never overwritten.
        self.store.scan()
        self.assertEqual(len(self.store.catalog()[0]["copies"]), 2)

    def test_source_removal_failure_keeps_both_catalog_copies(self):
        source = self.replay()
        with patch("migration.unlink_verified", side_effect=PermissionError("fixture locked")):
            result = migrate(self.store, make_plan(self.store, self.rule), confirmed=True)
        self.assertTrue(source.exists())
        self.assertEqual(len(result["copied"]), 1)
        self.assertEqual(len(self.store.catalog()[0]["copies"]), 2)

    def test_cancel_between_files(self):
        self.replay()
        self.replay("124.dem")
        plan = make_plan(self.store, self.rule)
        checks = iter((False, True))
        result = migrate(self.store, plan, confirmed=True, cancelled=lambda: next(checks))
        self.assertTrue(result["cancelled"])
        self.assertEqual(len(result["moved"]), 1)

    def test_overlap_wrong_client_and_reparse_folders_refused(self):
        self.replay()
        for storage in (self.source, self.root):
            with self.assertRaises(ValueError):
                make_plan(self.store, {**self.rule, "storage": str(storage)})
        self.store.add_library(self.storage, "classic")
        with self.assertRaises(ValueError):
            make_plan(self.store, self.rule)
        with self.assertRaises(ValueError):
            make_plan(self.store, {**self.rule, "source": ""})
        with self.assertRaises(ValueError):
            make_plan(self.store, {**self.rule, "storage": "   "})
        with self.assertRaises(ValueError):
            make_plan(self.store, {**self.rule, "before": "2025-02-30"})
        self.store.remove_library(next(item["id"] for item in self.store.libraries() if item["path"] == str(self.storage)))
        original = Path.lstat
        def reparse(path):
            if path == self.storage:
                return SimpleNamespace(st_mode=original(path).st_mode, st_file_attributes=0x400)
            return original(path)
        with patch.object(Path, "lstat", reparse), self.assertRaises(ValueError):
            make_plan(self.store, self.rule)
