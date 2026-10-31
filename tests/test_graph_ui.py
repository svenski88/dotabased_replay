from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from app import ReplayApp
from library import Store
from local_parser import PARSER_VERSION
from graphs import derive_graph
from test_graphs import graph_fixture
from test_local_parser import result
from test_replays import write_replay


class GraphUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"ui.sqlite3")
        for lib in self.store.libraries():
            self.store.remove_library(lib["id"])
        self.store.add_library(self.temp.name, "modern")
        write_replay(Path(self.temp.name)/"180.dem", match_id=180)
        self.store.scan()
        self.store.set_pref("hide_unknown", False)
        graph = graph_fixture(lambda t: -.15 if 500 <= t < 720 else .01)
        class Model:
            def predict(self, rows):
                return [.65]*len(rows)
        derive_graph(graph, model=Model())
        graph["events"] = [{"kind": "hero_death", "time": 650, "tick": 20000,
                            "attacker": "npc_dota_hero_axe", "target": "npc_dota_hero_lich",
                            "attacker_team": 2, "target_team": 3, "source": "fixture"}]*5
        self.store.save_full_parse(self.store.catalog()[0]["copies"][0], PARSER_VERSION, {**result(), "graph": graph,
                                  "chat_complete": True, "chat": [{"tick": 1, "speaker": "Alpha", "channel": "All", "text": "gg", "time": 100}]})
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.cleanup_ui)
        with patch.object(ReplayApp, "scan"):
            self.app = ReplayApp(self.root, self.store)
        self.root.geometry("1100x720")
        self.app.match_tree.selection_set(["180"], focus="180")
        self.app.select_match()
        self.settle()
        self.app.graph_view.draw()

    def cleanup_ui(self):
        if self.root.winfo_exists():
            self.app.closed = True
            self.app.cancel_search_timer()
            self.app.local_parser.close()
            self.root.destroy()

    def settle(self):
        until = time.monotonic()+.25
        while time.monotonic() < until:
            self.root.update()
            time.sleep(.005)

    def assert_usable(self):
        view = self.app.graph_view
        self.assertTrue(view.winfo_ismapped())
        self.assertTrue(view.canvas.winfo_ismapped())
        self.assertTrue(view.readout.winfo_ismapped())
        self.assertGreaterEqual(view.canvas.winfo_height(), 85)
        self.assertGreaterEqual(view.canvas.winfo_width(), 200)
        self.assertLessEqual(view.winfo_rootx()+view.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
        self.assertTrue(self.app.match_tools.winfo_ismapped())
        self.assertGreaterEqual(self.app.match_tree.body.winfo_height(), 34)

    def test_minimum_size_panels_graph_and_persistence(self):
        self.assertFalse(self.app.accounts_panel.expanded)
        self.assertFalse(self.app.chat_panel.expanded)
        self.assert_usable()
        for panel in (self.app.accounts_panel, self.app.chat_panel):
            panel.toggle()
        self.settle()
        self.assert_usable()
        self.assertTrue(self.app.chat_text.winfo_ismapped())
        self.assertGreater(self.app.chat_text.winfo_height(), 300)
        self.assertIn("gg", self.app.chat_text.get("1.0", "end"))
        self.assertTrue(self.store.get_pref("accounts_panel_expanded"))
        self.assertTrue(self.store.get_pref("chat_panel_expanded"))
        self.app.detail_panes.sashpos(0, 70)
        self.app.save_detail_split()
        position = self.app.detail_panes.sashpos(0)
        self.root.update()
        self.assertEqual(self.app.detail_panes.sashpos(0), position)

    def test_completed_parse_is_reviewable_while_next_match_is_running(self):
        app = self.app
        write_replay(Path(self.temp.name)/"181.dem", match_id=181)
        self.store.scan()
        with self.store.connect() as db:
            db.execute("UPDATE full_parse SET version='old'")
        app.reload()
        app.match_tree.selection_set(["180"], focus="180")
        app.select_match()
        app.notes.insert("end", "pending annotation")
        entered_second, release = threading.Event(), threading.Event()

        def parse(path, progress):
            if path.stem == "181":
                entered_second.set()
                if not release.wait(10):
                    raise AssertionError("UI did not release the second parse")
            graph = graph_fixture(lambda t: .01)
            return {**result(match_id=path.stem, radiant_score=55, duration=1800), "graph": graph}

        with patch.object(app.local_parser, "parse_file", side_effect=parse), \
             patch.object(app.local_parser, "derive", side_effect=lambda graph: derive_graph(graph, model=None)):
            matches = sorted(app.catalog, key=lambda m: m["key"])
            app.start_parse(matches)
            try:
                deadline = time.monotonic()+8
                while time.monotonic() < deadline:
                    self.root.update()
                    if entered_second.is_set() and app.current_match().get("radiant_score") == 55:
                        break
                    time.sleep(.01)
                self.assertTrue(entered_second.is_set())
                self.assertTrue(app.busy)
                self.assertEqual(app.current_match()["radiant_score"], 55)
                self.assertIn("55", str(app.match_tree.rows["180"]["values"]))
                self.assertEqual(app.match_tree.focus(), "180")
                self.assertEqual(app.match_tree.selection(), ("180",))
                self.assertEqual(app.graph_view.graph["category"]["label"], "Close Game")
                self.assertIn("pending annotation", app.notes.get("1.0", "end"))
                self.assertIn("pending annotation", next(m for m in self.store.catalog() if m["key"] == "180")["notes"])
                app.match_tree.selection_set(["181"], focus="181")
                app.select_match()
                self.assertEqual(app.current_key, "181")
                self.assertTrue(app.busy)
            finally:
                release.set()
                deadline = time.monotonic()+8
                while app.busy and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
            self.assertFalse(app.busy)

    def test_hover_reuses_tooltip_and_position_only_events_skip_graph_redraw(self):
        view = self.app.graph_view
        _, _, top, bottom, _, _ = view.geometry_data
        event = SimpleNamespace(x=round(view.x(650)), y=round((top+bottom)/2),
                                x_root=500, y_root=500)
        view.hover(event)
        tooltip = view.tooltip
        event.x = round(view.x(900))
        view.hover(event)
        self.assertIs(view.tooltip, tooltip)
        from graph_view import clock
        self.assertIn(clock(view.sample_at_x(event.x)["time"]), tooltip.winfo_children()[0].cget("text"))
        view.canvas_size = (view.canvas.winfo_width(), view.canvas.winfo_height())
        with patch.object(view, "after", side_effect=AssertionError("movement needs no redraw")):
            view.schedule_draw(SimpleNamespace(width=view.canvas_size[0], height=view.canvas_size[1]))

    def test_hover_legend_category_and_filter_preserve_notes_and_cache_laziness(self):
        view = self.app.graph_view
        self.assertIn("Comeback", view.inspection.get())
        self.assertIn("Gold", view.inspection.get())
        self.assertEqual(sum(len(hit[-1]) for hit in view.marker_hits), 5)  # visible boxes plus overflow retain each event once
        view.visible["radiant_win_probability"].set(False)
        view.draw()
        self.assertFalse(view.visible["radiant_win_probability"].get())
        with patch.object(self.store, "graph_for_match", side_effect=AssertionError("same selection must remain cached")):
            self.app.render_matches()
        self.app.notes.insert("1.0", "keep my annotation")
        self.app.category_filter.set("Stomp")
        self.app.filter_changed()
        self.assertEqual(self.app.visible, [])
        self.assertEqual(self.store.catalog()[0]["notes"], "keep my annotation")
        self.app.category_filter.set("Comeback")
        self.app.filter_changed()
        self.assertEqual(len(self.app.visible), 1)

    def test_percent_hover_uses_combined_resources_and_shows_smoothed_values(self):
        view = self.app.graph_view
        _, _, top, bottom, _, _ = view.geometry_data
        x, y = round(view.x(650)), round((top+bottom)/2)
        event = SimpleNamespace(x=x, y=y, x_root=view.canvas.winfo_rootx()+x,
                                y_root=view.canvas.winfo_rooty()+y)
        view.hover(event)
        self.root.update_idletasks()
        text = view.tooltip.winfo_children()[0].cget("text")
        self.assertIn("-15.0%", text)
        self.assertIn("30-second median", text)
        self.assertIn("combined team resources", text)
        self.assertIn("-15.0%", view.inspection.get())
        from ui_helpers import monitor_bounds, tooltip_coordinates
        expected = tooltip_coordinates((event.x_root, event.y_root),
                                       (view.tooltip.winfo_reqwidth(), view.tooltip.winfo_reqheight()),
                                       monitor_bounds(view, (event.x_root, event.y_root)))
        self.root.update()
        self.assertAlmostEqual(view.tooltip.winfo_rootx(), expected[0], delta=2)
        self.assertAlmostEqual(view.tooltip.winfo_rooty(), expected[1], delta=2)
        view.leave()
        self.assertIsNone(view.tooltip)

    def test_events_stack_inside_columns_below_lines_until_the_center(self):
        view = self.app.graph_view
        graph = view.graph
        base = graph["events"][0]
        graph["events"] = [{**base, "time": 650+i*.01, "tick": i, "attacker_team": team}
                           for team in (2, 3) for i in range(20)]
        view.set_graph(graph)
        _, _, top, bottom, _, _ = view.geometry_data
        center = (top+bottom)/2
        hits = view.marker_hits
        self.assertEqual(sum(len(hit[-1]) for hit in hits), 40)
        self.assertTrue(hits)
        xs = {round(hit[0], 3) for hit in hits}
        self.assertEqual(len(xs), 1)
        for x1, y1, x2, y2, entries in hits:
            self.assertGreaterEqual(y1, top)
            self.assertLessEqual(y2, bottom)
            if entries[0]["attacker_team"] == 2:
                self.assertLess(y2, center)
            else:
                self.assertGreater(y1, center)
        order = list(view.canvas.find_all())
        self.assertLess(max(order.index(i) for i in view.canvas.find_withtag("events")),
                        min(order.index(i) for i in view.canvas.find_withtag("series")))
        top_hits = [hit for hit in hits if hit[-1][0]["attacker_team"] == 2]
        bottom_hits = [hit for hit in hits if hit[-1][0]["attacker_team"] == 3]
        self.assertEqual(len(top_hits), len(bottom_hits))
        self.assertGreaterEqual(max(hit[3] for hit in top_hits)+20, center)
        self.assertLessEqual(min(hit[1] for hit in bottom_hits)-20, center)

    def test_condensed_rows_keep_actions_and_watch_at_the_right_edge(self):
        app = self.app
        for button in (app.parse_button, app.parse_selected_button, app.parse_details_button,
                       app.enrich_button, app.enrich_next_button, app.delete_button, app.watch_button):
            text_width = int(self.root.tk.call("font", "measure", "TkDefaultFont", button.cget("text")))
            self.assertGreaterEqual(button.winfo_reqwidth(), text_width)
        self.assertEqual(app.search_entry.master, app.category_choice.master)
        self.assertEqual(app.parse_button.master, app.delete_button.master)
        self.assertEqual(app.parse_button.master, app.enrich_button.master)
        self.assertEqual(app.parse_button.master, app.enrich_next_button.master)
        self.assertEqual(app.copy_match_id_button.master, app.copy_choice.master)
        self.assertEqual(app.copy_choice.master, app.client_combo.master)
        self.assertEqual(app.copy_choice.master, app.match_tools.master)
        for button in app.link_buttons.values():
            self.assertEqual(button.master, app.copy_match_id_button.master)
            self.assertFalse(button.instate(["disabled"]))
        header = app.watch_button.master
        self.assertAlmostEqual(app.watch_button.winfo_rootx()+app.watch_button.winfo_width(),
                               header.winfo_rootx()+header.winfo_width(), delta=2)
        for panel in (app.accounts_panel, app.chat_panel):
            panel.toggle()
        self.settle()
        self.assert_usable()
        # Overflow is explicit and scrollable rather than hiding narrow-row actions.
        self.assertTrue(app.match_toolbar.scroll.winfo_ismapped())
        app.match_toolbar.canvas.xview_moveto(1)
        self.assertGreater(app.match_toolbar.canvas.xview()[0], 0)
        self.assertTrue(app.watch_button.winfo_ismapped())

    def test_right_click_copies_recorded_tick_for_the_hovered_sample(self):
        view = self.app.graph_view
        for sample in view.graph["samples"]:
            # Simulate a long pause in replay playback after game minute ten.
            sample["replay_tick"] = 5000 + sample["time"]*30 + (9000 if sample["time"] >= 600 else 0)
        event = SimpleNamespace(x=round(view.x(650)), y=30, x_root=500, y_root=300)
        hovered = view.sample_at_x(event.x)
        expected = f"demo_gototick {hovered['replay_tick']}"
        with patch.object(view.context_menu, "tk_popup") as popup, patch.object(view.context_menu, "grab_release"):
            view.show_context_menu(event)
        popup.assert_called_once_with(500, 300)
        self.assertEqual(view.context_menu.entrycget(0, "label"), f"Copy '{expected}' console command")
        # Menu selection captures its original location even if the graph changes.
        hovered["replay_tick"] += 99
        with patch.object(view, "clipboard_clear") as clear, patch.object(view, "clipboard_append") as append:
            view.context_menu.invoke(0)
        clear.assert_called_once()
        append.assert_called_once_with(expected)

    def test_legacy_graphs_explain_reparse_and_outside_plot_has_no_menu(self):
        view = self.app.graph_view
        event = SimpleNamespace(x=round(view.x(650)), y=30, x_root=500, y_root=300)
        with patch.object(view.context_menu, "tk_popup"), patch.object(view.context_menu, "grab_release"):
            view.show_context_menu(event)
        self.assertEqual(view.context_menu.entrycget(0, "state"), "disabled")
        self.assertIn("Parse Selected", view.context_menu.entrycget(0, "label"))
        with patch.object(view.context_menu, "tk_popup") as popup:
            view.show_context_menu(SimpleNamespace(x=0, x_root=0, y_root=0))
        popup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
