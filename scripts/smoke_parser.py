"""Exercise parse controls and presentation with disposable synthetic fixtures."""
import argparse
import ctypes
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from app import ReplayApp
from library import Store
from local_parser import ParseError, PARSER_VERSION
from test_local_parser import result
from smoke_ui import screenshot
from test_replays import write_replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--geometry", default="1540x920")
    parser.add_argument("--details-screenshot", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory, patch.object(socket, "create_connection", side_effect=AssertionError("network prohibited")):
        store = Store(Path(directory) / "fixture.sqlite3")
        for library in store.libraries():
            store.remove_library(library["id"])
        store.add_library(directory, "classic")
        for match_id in (901, 902, 903):
            write_replay(Path(directory) / f"{match_id}.dem", match_id=match_id, duration=1800)
        store.scan()
        # Supply synthetic teams independent of the summary fixture's player list.
        with store.connect() as db:
            import json
            for row in db.execute("SELECT path, metadata FROM files").fetchall():
                metadata = json.loads(row["metadata"])
                metadata["players"] = [{"account_id": 1, "name": "Alpha", "hero": "axe", "team": 2}, {"account_id": 2, "name": "Beta", "hero": "lich", "team": 3}, {"account_id": 3, "name": "Gamma", "team": None}]
                metadata["league_id"] = 42
                db.execute("UPDATE files SET metadata=? WHERE path=?", (json.dumps(metadata), row["path"]))
        store.pin(1, "Radiant nickname with a full tooltip")
        store.pin(2, "Dire player")
        store.pin(3, "Unknown team player")
        store.set_pref("hide_unknown", False)
        cached_match = next(match for match in store.catalog() if match["key"] == "903")
        store.save_full_parse(cached_match["copies"][0], PARSER_VERSION, result(duration=1800, winner=2, lobby_type=2, league_id=42))
        root = tk.Tk()
        app = ReplayApp(root, store)
        root.geometry(args.geometry)
        failures, stopped = [], []
        def slow_parse(path, progress):
            if path.stem == "902":
                raise ParseError("Recording ends before a final team score", "incomplete")
            for index in range(600):
                if app.local_parser.cancelled.wait(.05):
                    stopped.append(time.monotonic())
                    raise ParseError("Parsing stopped", "cancelled")
                progress({"event": "progress", "fraction": min(.9, index / 100)})
            raise AssertionError("Smoke should stop first")
        app.local_parser.parse_file = slow_parse

        def start():
            if app.busy:
                root.after(50, start)
                return
            try:
                assert "Radiant:" in app.match_values(app.catalog[0])[10]
                assert len(app.match_tree.body.find_withtag("pinned_team")) >= 2
                app.parse_button.invoke()
                root.after(500, capture)
            except Exception as exc:
                failures.append(exc)
                app.close()
        def capture():
            try:
                assert str(app.stop_parse_button["state"]) == "normal"
                assert app.busy
                assert app.parse_fraction.get() > 0
                app.parse_details()
                assert set(app.parse_window.tree.get_children()) == {"901", "902", "903"}
                app.parse_window.tree.selection_set("903")
                app.parse_window.show_selected()
                root.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
                detail_hwnd = ctypes.windll.user32.GetParent(app.parse_window.winfo_id()) or app.parse_window.winfo_id()
                done = threading.Event()
                def take():
                    try:
                        screenshot(hwnd, args.screenshot)
                        if args.details_screenshot:
                            screenshot(detail_hwnd, args.details_screenshot)
                    except Exception as exc:
                        failures.append(exc)
                    finally:
                        done.set()
                threading.Thread(target=take, daemon=True).start()
                def finish_capture():
                    if not done.is_set():
                        root.after(50, finish_capture)
                        return
                    app.stop_parse_button.invoke()
                    root.after(200, verify)
                root.after(50, finish_capture)
            except Exception as exc:
                failures.append(exc)
                app.close()
        def verify():
            try:
                assert stopped, "Stop must reach worker"
                assert not app.busy
                assert "stopped" in app.status.get()
                assert str(app.stop_parse_button["state"]) == "disabled"
                assert next(match for match in store.catalog() if match["key"] == "901")["parse_attempts"][0]["status"] == "cancelled"
                assert app.parse_progress.fraction < 1
                print("Parser UI smoke passed: team lines, cached/incomplete/live results, offline progress, Stop and retained attempts")
            except Exception as exc:
                failures.append(exc)
            app.close()
        root.after(600, start)
        root.after(30000, app.close)
        root.mainloop()
        if failures:
            raise failures[0]


if __name__ == "__main__":
    main()
