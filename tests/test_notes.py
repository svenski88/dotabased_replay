from pathlib import Path
import sqlite3
import tempfile
import unittest

from library import Store, filter_matches, is_unknown, note_preview
from notes_import import import_notes, parse_notes


class NotesImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "matches.md"
        self.store = Store(self.root / "catalog.sqlite3")

    def test_bom_encodings_links_and_varied_separators(self):
        content = "Header is not a note\nhttps://www.dotabuff.com/matches/101 - Alpha, mid hero\nhttps://www.dotabuff.com/matches/102 ----- Beta - internal dashes retained\n[Replay](https://www.opendota.com/matches/103) — Gamma\nhttps://www.dotabuff.com/matches/104\n-- Section comment is not continuation\n"
        for encoding in ("utf-16", "utf-8-sig", "utf-8"):
            self.source.write_bytes(content.encode(encoding))
            entries = parse_notes(self.source)
            self.assertEqual([e["match_id"] for e in entries], ["101", "102", "103", "104"])
            self.assertEqual([e["note"] for e in entries], ["Alpha, mid hero", "Beta - internal dashes retained", "Gamma", ""])
            self.assertIn("-----", entries[1]["source_line"])

    def test_dry_run_nondestructive_apply_backup_and_repeat_idempotence(self):
        self.source.write_text("https://www.dotabuff.com/matches/101 -- New annotation\nhttps://www.dotabuff.com/matches/102 - Another annotation\nhttps://www.dotabuff.com/matches/103\n", encoding="utf-8")
        original = self.source.read_bytes()
        self.store.save_match("101", notes="My existing note")
        preview = import_notes(self.store, self.source)
        self.assertEqual((preview["links"], preview["changed"], preview["empty"]), (3, 2, 1))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT notes FROM matches WHERE id='101'").fetchone()[0], "My existing note")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM note_imports").fetchone()[0], 0)
        report = import_notes(self.store, self.source, apply=True)
        backup = Path(report["backup"])
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute("SELECT notes FROM matches WHERE id='101'").fetchone()[0], "My existing note")
        # sqlite connection context managers do not close: close the test reader too.
        db.close()
        renamed = backup.with_suffix(".moved")
        backup.rename(renamed)
        renamed.unlink()  # Windows fails here if the importer leaked its backup handles.
        with self.store.connect() as db:
            note = db.execute("SELECT notes FROM matches WHERE id='101'").fetchone()[0]
            self.assertTrue(note.startswith("My existing note\n\n[Imported from matches.md, line 1]\nNew annotation"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM note_imports").fetchone()[0], 2)
        second = import_notes(self.store, self.source, apply=True)
        self.assertEqual(second["changed"], 0)
        self.assertIsNone(second["backup"])
        self.assertEqual(second["already_imported"], 2)
        self.assertEqual(original, self.source.read_bytes())

    def test_duplicate_annotations_existing_text_and_changed_source(self):
        self.source.write_text("https://www.dotabuff.com/matches/101 - Same note\nhttps://www.dotabuff.com/matches/101 --- Same note\n", encoding="utf-8")
        self.store.save_match("101", notes="Same note")
        first = import_notes(self.store, self.source, apply=True)
        self.assertEqual(first["duplicates"], 1)
        self.assertEqual(first["already_present"], 1)
        self.assertEqual(first["changed"], 0)
        self.source.write_text("https://www.dotabuff.com/matches/101 - Same note\nhttps://www.dotabuff.com/matches/101 - New second note\n", encoding="utf-8")
        second = import_notes(self.store, self.source, apply=True)
        self.assertEqual(second["changed"], 1)
        with self.store.connect() as db:
            note = db.execute("SELECT notes FROM matches WHERE id='101'").fetchone()[0]
        self.assertEqual(note.count("Same note"), 1)
        self.assertIn("New second note", note)


class DisplayFilterTests(unittest.TestCase):
    def test_unknown_filter_allows_usable_duplicate_despite_one_bad_copy(self):
        usable = {"match_id": "101", "end_time": 1600000000, "players": [{"account_id": 42}], "errors": ["Other copy corrupt"]}
        unknown = [{"match_id": "102", "players": [], "errors": ["No summary"]}, {"players": []}, {"match_id": "103", "players": [{"account_id": 42}]}]
        self.assertFalse(is_unknown(usable))
        self.assertEqual(filter_matches([usable] + unknown, [], hide_unknown=True), [usable])
        self.assertEqual(len(filter_matches([usable] + unknown, [], hide_unknown=False)), 4)

    def test_first_line_and_literal_three_dot_truncation(self):
        self.assertEqual(note_preview("First line\nSecond line"), "First line")
        self.assertEqual(note_preview(""), "")
        self.assertEqual(note_preview("abcdefghijklmnop", limit=10), "abcdefg...")
        self.assertEqual(note_preview("x" * 80), "x" * 80)
        self.assertEqual(len(note_preview("x" * 81)), 80)


if __name__ == "__main__":
    unittest.main()
