from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from app import ReplayApp, pinned_teams
from library import Store
from local_parser import LocalParser, ParseError, PARSER_VERSION
from parse_progress import ParseProgress, ParseProgressWindow, match_details
from replay_grid import ReplayGrid
from test_local_parser import result
from test_replays import write_replay


class ProgressTests(unittest.TestCase):
    def test_empty_sides_are_hidden_and_unknown_team_stays_explicit(self):
        self.assertEqual(pinned_teams({"players": []}, {1: "One"}), "")
        self.assertEqual(pinned_teams({"players": [{"account_id": 1, "team": 3}]}, {1: "One"}), "Dire: One")
        self.assertEqual(pinned_teams({"players": [{"account_id": 1}]}, {1: "One"}), "Unknown team: One")

    def test_outcomes_have_identity_path_and_cached_fields_and_stop_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "test.sqlite3")
            for library in store.libraries():
                store.remove_library(library["id"])
            store.add_library(directory, "classic")
            for match_id in (180, 181, 182):
                write_replay(Path(directory) / f"{match_id}.dem", match_id=match_id)
            store.scan()
            matches = sorted(store.catalog(), key=lambda match: match["key"])
            store.save_full_parse(matches[0]["copies"][0], PARSER_VERSION, result(duration=120))
            parser, model, events = LocalParser(), ParseProgress(), []
            model.start(matches)
            def update(event):
                events.append(event)
                model.update(event)
            def parse(path, progress):
                if path.stem == "181":
                    raise ParseError("No final state", "incomplete")
                parser.stop()
                raise ParseError("Stopped", "cancelled")
            with patch.object(parser, "parse_file", side_effect=parse):
                report = parser.parse_all(store, update, matches)
            model.finish(report)
            self.assertEqual([row["status"] for row in model.rows.values()], ["cached", "incomplete", "cancelled"])
            cached = next(event for event in events if event.get("status") == "cached")
            self.assertEqual((cached["key"], Path(cached["path"]).name), ("180", "180.dem"))
            self.assertEqual(model.rows["180"]["fields"]["duration"], 120)
            self.assertAlmostEqual(model.fraction, 2 / 3)
            self.assertIn("No final state", match_details(model.rows["181"]))
            history = ParseProgress()
            history.load_history(store.catalog())
            self.assertEqual(len(history.rows), 3)
            self.assertIn("39 : 24", match_details(history.rows["180"]))


class PresentationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.root.destroy)

    def test_lone_dire_color_winner_color_and_hero_separator(self):
        self.root.geometry("800x220")
        grid = ReplayGrid(self.root, ("radiant", "dire", "winner", "tracked"))
        grid.pack(fill="both", expand=True)
        for key, width in (("radiant", 158), ("dire", 140), ("winner", 75), ("tracked", 160)):
            grid.column(key, width=width)
        grid.insert("", "end", iid="A", values=("", "", "Radiant", "Dire: Only Dire"))
        grid.insert("", "end", iid="B", values=("", "", "Dire", ""))
        self.root.update()
        pinned = grid.body.find_withtag("pinned_team")
        self.assertEqual(len(pinned), 1)
        self.assertEqual(grid.body.itemcget(pinned[0], "fill"), "#ee9696")
        winners = grid.body.find_withtag("winner_text")
        self.assertEqual([grid.body.itemcget(item, "fill") for item in winners], ["#70d9a0", "#ee9696"])
        self.assertEqual(len(grid.body.find_withtag("hero_vs")), 2)

    def test_selected_scope_live_window_reopen_and_friendly_saved_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "test.sqlite3")
            for library in store.libraries():
                store.remove_library(library["id"])
            store.add_library(directory, "classic")
            for match_id in (180, 181, 182):
                write_replay(Path(directory) / f"{match_id}.dem", match_id=match_id)
            store.scan()
            store.set_pref("hide_unknown", False)
            with patch.object(ReplayApp, "scan"):
                app = ReplayApp(self.root, store)
                app.parse_selected()
                self.assertIn("Select one or more", app.status.get())
                app.match_tree.selection_set(["180", "182"])
                calls = []
                def parse(path, progress):
                    calls.append(path.stem)
                    progress({"fraction": .5})
                    time.sleep(.25)
                    return result(duration=1800, winner=3)
                with patch.object(app.local_parser, "parse_file", side_effect=parse):
                    app.parse_selected_button.invoke()
                    app.parse_details()
                    first_window = app.parse_window
                    deadline = time.monotonic() + 4
                    while app.busy and time.monotonic() < deadline:
                        self.root.update()
                        time.sleep(.01)
                    self.assertFalse(app.busy)
                self.assertEqual(set(calls), {"180", "182"})
                self.assertEqual(set(first_window.tree.get_children()), {"180", "182"})
                first_window.tree.selection_set("182")
                first_window.show_selected()
                self.assertIn("Game duration: 30:00", first_window.text.get("1.0", "end"))
                self.assertIn("Winner: Dire", first_window.text.get("1.0", "end"))
                self.assertNotIn('"schema_version"', first_window.text.get("1.0", "end"))
                first_window.destroy()
                app.parse_details()
                self.assertEqual(set(app.parse_window.tree.get_children()), {"180", "182"})
                history = ParseProgress()
                history.load_history(store.catalog())
                history_window = ParseProgressWindow(self.root, history, lambda: None)
                self.assertEqual(set(history_window.tree.get_children()), {"180", "182"})
                self.assertEqual(str(history_window.stop_button["state"]), "disabled")
                app.closed = True
