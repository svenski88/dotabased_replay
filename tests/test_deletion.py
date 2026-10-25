from dataclasses import replace
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest

from deletion import DeletePlan, UnsafeDeletion, check_location, delete_files, make_delete_plan, unlink_verified
from library import Store, format_size
from replay_grid import rating_hit_test, selection_click
from test_replays import write_replay


class RatingMigrationTests(unittest.TestCase):
    def test_additive_legacy_migration_preserves_notes_clients_and_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            db = sqlite3.connect(path)
            db.executescript("CREATE TABLE matches(id TEXT PRIMARY KEY, notes TEXT DEFAULT '', client TEXT DEFAULT ''); INSERT INTO matches VALUES ('101','Keep my note','classic'); CREATE TABLE note_imports(source TEXT, fingerprint TEXT, match_id TEXT, note TEXT, source_line TEXT, line_number INTEGER, imported_at REAL, PRIMARY KEY(source,fingerprint)); INSERT INTO note_imports VALUES ('notes.md','hash','101','Imported note','Original source line',1,0);")
            db.close()
            store = Store(path)
            with store.connect() as db:
                self.assertEqual(tuple(db.execute("SELECT notes,client,rating FROM matches WHERE id='101'").fetchone()), ("Keep my note", "classic", 0))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM note_imports").fetchone()[0], 1)
            for rating in range(6):
                store.save_match("101", rating=rating)
            for value in (-1, 6, 2.5, True, "3"):
                with self.assertRaises(ValueError):
                    store.save_match("101", rating=value)
            with store.connect() as db:
                self.assertEqual(tuple(db.execute("SELECT notes,client,rating FROM matches WHERE id='101'").fetchone()), ("Keep my note", "classic", 5))

    def test_star_hit_regions_and_selection_transitions(self):
        self.assertIsNone(rating_hit_test(4))
        for value in range(1, 6):
            self.assertEqual(rating_hit_test(5 + (value - 1) * 17), value)
            self.assertEqual(rating_hit_test(5 + value * 17 - .01), value)
        self.assertIsNone(rating_hit_test(90))
        order = ["a", "b", "c", "d"]
        selected, anchor = selection_click(order, set(), None, "a")
        selected, anchor = selection_click(order, selected, anchor, "c", control=True)
        self.assertEqual(selected, {"a", "c"})
        selected, anchor = selection_click(order, selected, "a", "d", shift=True)
        self.assertEqual(selected, set(order))
        selected, _ = selection_click(order, selected, anchor, "b", control=True)
        self.assertEqual(selected, {"a", "c", "d"})


class DeleteFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root / "catalog.sqlite3")
        for library in self.store.libraries():
            self.store.remove_library(library["id"])
        self.first = self.root / "modern"
        self.second = self.root / "classic"
        self.first.mkdir()
        self.second.mkdir()
        self.store.add_library(self.first, "modern")
        self.store.add_library(self.second, "classic")
        self.paths = [self.first / "123.dem", self.second / "123.dem"]
        for path in self.paths:
            write_replay(path)
        self.store.scan()
        self.store.save_match("123", notes="Retain this", rating=4, client="classic")

    def test_copy_size_total_semantics_and_cancel_without_mutation(self):
        match = self.store.catalog()[0]
        self.assertEqual(match["total_size"], sum(path.stat().st_size for path in self.paths))
        self.assertEqual([copy["size"] for copy in match["copies"]], [path.stat().st_size for path in sorted(self.paths)])
        self.assertEqual(format_size(1024 * 1024), "1.0 MiB")
        plan = make_delete_plan(self.store, ["123"])
        self.assertEqual(len(plan.files), 2)
        self.assertEqual(plan.errors, ())
        report = delete_files(self.store, plan)
        self.assertTrue(report["cancelled"])
        self.assertTrue(all(path.is_file() for path in self.paths))
        self.assertEqual(len(self.store.catalog()[0]["copies"]), 2)

    def test_confirmed_exact_subset_then_last_copy_retains_notes_rating(self):
        plan = make_delete_plan(self.store, ["123"])
        one = plan.subset([str(self.paths[0])])
        report = delete_files(self.store, one, confirmed=True)
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["deleted"], [str(self.paths[0])])
        self.assertFalse(self.paths[0].exists())
        self.assertTrue(self.paths[1].exists())
        match = self.store.catalog()[0]
        self.assertEqual((len(match["copies"]), match["rating"], match["notes"]), (1, 4, "Retain this"))
        final = delete_files(self.store, make_delete_plan(self.store, ["123"]), confirmed=True)
        self.assertEqual(final["failed"], [])
        self.assertEqual(self.store.catalog(), [])
        with self.store.connect() as db:
            self.assertEqual(tuple(db.execute("SELECT notes,rating,client FROM matches WHERE id='123'").fetchone()), ("Retain this", 4, "classic"))

    def test_partial_permission_failure_only_hides_successful_copy(self):
        plan = make_delete_plan(self.store, ["123"])
        refused = plan.files[0].path
        def remove(target):
            if target.path == refused:
                raise PermissionError("Fixture permission failure")
            unlink_verified(target)
        report = delete_files(self.store, plan, confirmed=True, remove=remove)
        self.assertEqual(len(report["deleted"]), 1)
        self.assertEqual(len(report["failed"]), 1)
        self.assertEqual(report["failed"][0]["path"], refused)
        self.assertEqual([copy["path"] for copy in self.store.catalog()[0]["copies"]], [refused])

    def test_stale_plan_refuses_changed_or_replaced_file(self):
        plan = make_delete_plan(self.store, ["123"])
        target = plan.files[0]
        path = Path(target.path)
        path.write_bytes(path.read_bytes() + b"changed")
        report = delete_files(self.store, plan.subset([target.path]), confirmed=True)
        self.assertEqual(len(report["failed"]), 1)
        self.assertTrue(path.exists())
        self.assertEqual(len(self.store.catalog()[0]["copies"]), 2)
        self.assertTrue(make_delete_plan(self.store, ["123"]).errors)

    def test_replacement_with_identical_size_and_mtime_is_refused_by_identity(self):
        plan = make_delete_plan(self.store, ["123"])
        target = plan.files[0]
        path = Path(target.path)
        original = path.read_bytes()
        path.unlink()
        path.write_bytes(original)
        os.utime(path, ns=(target.mtime, target.mtime))
        self.assertNotEqual(path.stat().st_ino, target.identity[1])
        report = delete_files(self.store, plan.subset([target.path]), confirmed=True)
        self.assertEqual(len(report["failed"]), 1)
        self.assertTrue(path.is_file())

    def test_missing_copy_marked_absent_without_deleting_another_file(self):
        plan = make_delete_plan(self.store, ["123"])
        target = plan.files[0]
        Path(target.path).unlink()
        report = delete_files(self.store, plan.subset([target.path]), confirmed=True)
        self.assertEqual(report["missing"], [target.path])
        self.assertEqual(report["deleted"], [])
        self.assertEqual(len(self.store.catalog()[0]["copies"]), 1)

    def test_library_or_catalog_change_invalidates_snapshot(self):
        plan = make_delete_plan(self.store, ["123"])
        with self.store.connect() as db:
            db.execute("UPDATE files SET mtime=mtime+1 WHERE path=?", (plan.files[0].path,))
        report = delete_files(self.store, plan.subset([plan.files[0].path]), confirmed=True)
        self.assertEqual(len(report["failed"]), 1)
        self.assertTrue(Path(plan.files[0].path).exists())

    def test_outside_directory_and_wrong_extension_refused(self):
        with self.assertRaises(UnsafeDeletion):
            check_location(self.first, self.paths[1])
        other = self.first / "notes.md"
        other.write_text("keep", encoding="utf-8")
        with self.assertRaises(UnsafeDeletion):
            check_location(self.first, other)
        plan = make_delete_plan(self.store, ["123"])
        with self.assertRaises(UnsafeDeletion):
            plan.subset([str(other)])
        self.assertTrue(other.exists())

    def test_symlink_or_junction_component_refused(self):
        link = self.first / "linked"
        if os.name == "nt":
            import _winapi
            if not hasattr(_winapi, "CreateJunction"):
                self.skipTest("Junction creation unavailable")
            _winapi.CreateJunction(str(self.second), str(link))
        else:
            link.symlink_to(self.second, target_is_directory=True)
        with self.assertRaises(UnsafeDeletion):
            check_location(self.first, link / "123.dem")
        self.assertTrue(self.paths[1].exists())


if __name__ == "__main__":
    unittest.main()
