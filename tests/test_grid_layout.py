from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from app import duration, sort_durations
from library import Store
from replay_grid import ReplayGrid, ROW_HEIGHT, clamp_column_width, resize_boundary


class LayoutLogicTests(unittest.TestCase):
    def test_resizable_boundary_hit_regions_and_width_limits(self):
        columns = ("match", "tracked", "notes", "league")
        widths = (100, 120, 200, 100)
        self.assertIsNone(resize_boundary(columns, widths, 100))
        self.assertEqual(resize_boundary(columns, widths, 215), "tracked")
        self.assertEqual(resize_boundary(columns, widths, 225), "tracked")
        self.assertIsNone(resize_boundary(columns, widths, 226))
        self.assertEqual(resize_boundary(columns, widths, 420), "notes")
        self.assertEqual(resize_boundary(columns, widths, 520), "league")
        self.assertEqual(clamp_column_width(1), 70)
        self.assertEqual(clamp_column_width(3000), 2000)
        for invalid in (True, "200", None, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                clamp_column_width(invalid)

    def test_duration_values_and_numeric_sort_unknown_last_in_both_directions(self):
        matches = [{"duration": 600}, {"duration": None}, {"duration": 90}, {"duration": 0}, {"duration": float("nan")}, {"duration": -1}]
        self.assertEqual(duration({"duration": 0}), "0:00")
        self.assertEqual(duration({"duration": 90.9}), "1:30")
        self.assertEqual(duration({"duration": 600}), "10:00")
        for value in (None, float("nan"), float("inf"), -1, True, "90"):
            self.assertEqual(duration({"duration": value}), "Unknown")
        self.assertEqual(sort_durations(matches)[:3], [matches[3], matches[2], matches[0]])
        self.assertEqual(sort_durations(matches, reverse=True)[:3], [matches[0], matches[2], matches[3]])
        self.assertEqual(sort_durations(matches)[3:], [matches[1], matches[4], matches[5]])
        self.assertEqual(sort_durations(matches, reverse=True)[3:], [matches[1], matches[4], matches[5]])


class GridInteractionTests(unittest.TestCase):
    def test_scrolled_drag_shared_widths_no_sort_selection_loss_and_restart(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.addCleanup(root.destroy)
        root.geometry("520x220")
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "layout.sqlite3")
            columns = ("match", "rating", "duration", "tracked", "notes", "league")
            grid = ReplayGrid(root, columns)
            grid.pack(fill="both", expand=True)
            sorted_columns = []
            for key, width in zip(columns, (100, 95, 78, 180, 240, 110)):
                grid.column(key, width=width)
                grid.heading(key, text=key.upper(), command=lambda column=key: sorted_columns.append(column))
            grid.insert("", "end", iid="A", values=("A", 4, "1:00", "Pinned A", "First note", "League"))
            grid.insert("", "end", iid="B", values=("B", 2, "2:00", "Pinned B", "Second note", "League"))
            grid.selection_set(["A", "B"], focus="B")
            grid.on_column_resize = lambda key, width: store.set_pref("column_widths", {column: grid.definitions[column]["width"] for column in ("tracked", "notes", "league") if column in grid.explicit_widths})
            root.update()

            def drag(key, delta):
                grid.xview("moveto", 1 if key == "league" else .4)
                root.update()
                self.assertGreater(grid.body.canvasx(0), 0)
                edge = sum(grid.widths()[:columns.index(key) + 1])
                x = min(grid.header.winfo_width() - 2, round(edge - grid.header.canvasx(0)))
                self.assertTrue(0 <= x < grid.header.winfo_width())
                absolute_x = grid.header.winfo_rootx() + x
                grid.header.event_generate("<Motion>", x=x, y=17)
                root.update()
                self.assertEqual(grid.header.cget("cursor"), "sb_h_double_arrow")
                grid.header.event_generate("<ButtonPress-1>", x=x, y=17, rootx=absolute_x)
                grid.header.event_generate("<B1-Motion>", x=x + delta, y=17, rootx=absolute_x + delta)
                grid.header.event_generate("<ButtonRelease-1>", x=x + delta, y=17, rootx=absolute_x + delta)
                root.update()
                self.assertEqual(grid.header.xview(), grid.body.xview())

            drag("tracked", 45)
            self.assertEqual(grid.definitions["tracked"]["width"], 225)
            drag("notes", -70)
            self.assertEqual(grid.definitions["notes"]["width"], 170)
            drag("league", 65)
            self.assertEqual(grid.definitions["league"]["width"], 175)
            self.assertEqual(sorted_columns, [])
            self.assertEqual(set(grid.selection()), {"A", "B"})
            self.assertEqual(grid.focus(), "B")
            grid.xview("moveto", 0)
            root.update()
            grid.header.event_generate("<ButtonPress-1>", x=50, y=17)
            grid.header.event_generate("<ButtonRelease-1>", x=50, y=17)
            root.update()
            self.assertEqual(sorted_columns, ["match"], "Ordinary header clicks must still sort")
            saved = store.get_pref("column_widths")
            self.assertEqual(saved, {"tracked": 225, "notes": 170, "league": 175})
            root.geometry("1100x220")
            root.update()
            self.assertEqual(grid.widths()[columns.index("notes")], 170, "Explicit shrink must override automatic fill")
            grid.destroy()
            restarted = ReplayGrid(root, columns)
            restarted.pack(fill="both", expand=True)
            restarted.restore_widths(Store(store.path).get_pref("column_widths"))
            root.update()
            self.assertEqual(restarted.widths()[columns.index("tracked")], 225)
            self.assertEqual(restarted.widths()[columns.index("notes")], 170)
            self.assertEqual(restarted.widths()[columns.index("league")], 175)

    def test_stars_only_same_value_clears_and_retains_multi_selection(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.addCleanup(root.destroy)
        root.geometry("360x180")
        grid = ReplayGrid(root, ("match", "rating"))
        grid.pack(fill="both", expand=True)
        grid.column("match", width=100)
        grid.column("rating", width=95)
        grid.insert("", "end", iid="A", values=("A", 4))
        grid.insert("", "end", iid="B", values=("B", 2))
        grid.selection_set(["A", "B"], focus="B")
        ratings = []
        def rate(key, value):
            ratings.append((key, value))
            grid.update_values(key, (key, value))
        grid.on_rating = rate
        root.update()
        x = 100 + 5 + 3 * 17 + 8
        grid.body.event_generate("<Button-1>", x=x, y=ROW_HEIGHT // 2)
        root.update()
        self.assertEqual(ratings[-1], ("A", 0))
        grid.body.event_generate("<Button-1>", x=x, y=ROW_HEIGHT // 2)
        root.update()
        self.assertEqual(ratings[-1], ("A", 4))
        self.assertEqual(set(grid.selection()), {"A", "B"})
        self.assertEqual(len(grid.body.find_withtag("rating_star")), 10)
        canvas_text = [grid.body.itemcget(item, "text") for item in grid.body.find_all() if grid.body.type(item) == "text"]
        self.assertNotIn("0", canvas_text)
        grid.rate_focused(0)
        self.assertEqual(ratings[-1], ("A", 0))


if __name__ == "__main__":
    unittest.main()
