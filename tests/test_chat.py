import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import ReplayApp
from chat import chat_lines
from library import Store
from local_parser import LocalParser, PARSER_VERSION, ParseError
from search import SearchIndex, compile_terms, query_terms
from test_local_parser import result


def entry(text="gg", **values):
    return {"tick": 120, "speaker": "Игрок", "channel": "All", "text": text, **values}


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def store(self):
        store = Store(self.root / "test.sqlite3")
        for library in store.libraries():
            store.remove_library(library["id"])
        store.add_library(str(self.root), "modern")
        (self.root / "180.dem").write_bytes(b"synthetic replay")
        store.scan()
        return store

    def parse_records(self, records):
        # A real child process exercises line framing beyond the old 128 KiB
        # result limit, without needing a replay, Dota client or network access.
        fixture = self.root / "protocol.jsonl"
        fixture.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        original = subprocess.Popen
        script = "import pathlib,sys; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())"
        with patch("local_parser.subprocess.Popen", side_effect=lambda *args, **kwargs: original([sys.executable, "-c", script, str(fixture)], **kwargs)):
            return LocalParser().parse_file("unused")

    def test_streamed_large_log_and_protocol_validation(self):
        entries = [entry("你好" * 200, tick=index) for index in range(300)]
        records = [{"event": "chat", "entry": value} for value in entries]
        finished = {**result(), "chat_complete": True, "chat_count": len(entries)}
        self.assertGreater(len(json.dumps(entries)), 131072)
        self.assertEqual(self.parse_records(records + [finished])["chat"], entries)
        with self.assertRaisesRegex(ParseError, "incomplete"):
            self.parse_records(records[:1] + [finished])
        with self.assertRaisesRegex(ParseError, "Invalid chat tick"):
            self.parse_records([{"event": "chat", "entry": entry(tick=-1)}, finished])
        with self.assertRaisesRegex(ParseError, "Invalid chat time"):
            self.parse_records([{"event": "chat", "entry": entry(time=float("nan"))}, finished])
        with patch("local_parser.MAX_CHAT_BYTES", 1), self.assertRaisesRegex(ParseError, "safety limit"):
            self.parse_records(records[:1] + [finished])

    def test_cache_upgrade_duplicates_changed_files_notes_and_search(self):
        store = self.store()
        match = store.catalog()[0]
        copy = match["copies"][0]
        store.save_match("180", notes="keep my note", rating=4)
        store.save_full_parse(copy, "1.0.0+manta1.5.2", result())
        self.assertIn("not been parsed", chat_lines(store.catalog()[0]))
        before = store.catalog()[0]
        self.assertFalse(SearchIndex([before]).matches(before, compile_terms(query_terms("secrettranscriptword"))))
        self.assertIsNone(store.full_cached(copy, PARSER_VERSION))
        parsed = {**result(), "chat_complete": True, "chat_count": 1, "chat": [entry("SecretTranscriptWord late comeback")]}
        store.save_full_parse(copy, PARSER_VERSION, parsed)
        duplicate = self.root / "180_1.dem"
        duplicate.write_bytes(b"second synthetic replay")
        store.scan()
        second_copy = next(value for value in store.catalog()[0]["copies"] if value["path"] != copy["path"])
        # Even a newer metadata-only result must not erase a recovered transcript.
        store.save_full_parse(second_copy, PARSER_VERSION, result())
        restored = store.catalog()[0]
        self.assertEqual(restored["chat"], parsed["chat"])
        self.assertEqual((restored["notes"], restored["rating"]), ("keep my note", 4))
        index = SearchIndex([restored])
        for query in ("secrettranscriptword", '"late comeback"', 'secrettranscriptword "keep my note"', 'Игрок late'):
            self.assertTrue(index.matches(restored, compile_terms(query_terms(query))), query)
        self.assertFalse(index.matches(restored, compile_terms(query_terms("secrettranscriptword missingword"))))
        self.assertEqual(store.full_cached(copy, PARSER_VERSION)["chat"], parsed["chat"])
        Path(copy["path"]).write_bytes(b"changed recording with another size")
        store.scan()
        self.assertNotIn("chat", store.catalog()[0])

    def test_empty_unparsed_clock_and_tick_presentation(self):
        self.assertIn("not been parsed", chat_lines({}))
        self.assertIn("No chat messages", chat_lines({"chat_complete": True, "chat": []}))
        rendered = chat_lines({"chat_complete": True, "chat": [entry(time=-12.8), entry(time=125), entry(speaker="")]})
        self.assertIn("[-00:12] [All] Игрок: gg", rendered)
        self.assertIn("[02:05]", rendered)
        self.assertIn("[Tick 120] [All] Unknown player", rendered)

    def test_ui_scroll_clear_and_note_isolation(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(root.destroy)
        with patch.object(ReplayApp, "scan"):
            store = self.store()
            app = ReplayApp(root, store)
            self.addCleanup(lambda: setattr(app, "closed", True))
            match = store.catalog()[0]
            app.current_key = match["key"]
            app.catalog = [match]
            match.update(chat_complete=True, chat=[entry(f"Message {index}") for index in range(100)], notes="My own note")
            app.show_match(match)
            root.update()
            self.assertEqual(str(app.chat_text["state"]), "disabled")
            self.assertIn("Message 0", app.chat_text.get("1.0", "end"))
            self.assertLess(app.chat_text.yview()[1], 1)
            app.chat_text.yview_moveto(1)
            root.update()
            self.assertGreater(app.chat_text.yview()[0], 0)
            self.assertEqual(app.notes.get("1.0", "end-1c"), "My own note")
            app.show_match(match)
            root.update()
            self.assertEqual(app.chat_text.yview()[0], 0)
            app.clear_match()
            self.assertEqual(app.chat_text.get("1.0", "end-1c"), "")


if __name__ == "__main__":
    unittest.main()
