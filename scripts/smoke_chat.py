"""Validate chat panes and search using synthetic replays and a disposable DB."""
import argparse
import ctypes
from pathlib import Path
import socket
import sys
import tempfile
import threading
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from app import ReplayApp
from library import Store
from local_parser import PARSER_VERSION
from smoke_ui import screenshot
from test_local_parser import result
from test_replays import write_replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--geometry", default="1540x920")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory, patch.object(ReplayApp, "scan"), patch.object(socket, "create_connection", side_effect=AssertionError("network prohibited")):
        store = Store(Path(directory) / "chat.sqlite3")
        for library in store.libraries():
            store.remove_library(library["id"])
        store.add_library(directory, "modern")
        store.set_pref("hide_unknown", False)
        write_replay(Path(directory) / "901.dem", match_id=901, duration=1800)
        store.scan()
        match = store.catalog()[0]
        transcript = [{"tick": 100 + index, "time": index * 42 - 15, "speaker": "Alpha" if index % 2 == 0 else "Beta", "channel": "All", "text": "Good luck, have fun!" if index == 0 else "Let's defend the tower and turn this game around." if index % 2 else "Nice fight, well played!"} for index in range(80)]
        store.save_full_parse(match["copies"][0], PARSER_VERSION, {**result(duration=1800, winner=2, players=[{"account_id": 1, "name": "Alpha", "hero": "axe", "team": 2}, {"account_id": 2, "name": "Beta", "hero": "lich", "team": 3}]), "chat_complete": True, "chat_count": len(transcript), "chat": transcript})
        store.save_match("901", notes="Late comeback after a long defence.")
        root = tk.Tk()
        app = ReplayApp(root, store)
        root.geometry(args.geometry)
        failures, captured = [], threading.Event()

        def exercise():
            try:
                app.search.set('"defend the tower" comeback')
                app.render_matches()
                assert app.match_tree.get_children() == ("901",)
                match = app.catalog[0]
                app.current_key = match["key"]
                app.show_match(match)
                root.update_idletasks()
                assert str(app.chat_text["state"]) == "disabled"
                assert app.chat_text.winfo_width() > 150
                assert app.chat_text.yview()[1] < 1
                app.chat_text.yview_moveto(1)
                root.update_idletasks()
                assert app.chat_text.yview()[0] > 0
                app.show_match(match)
                assert "Late comeback" in app.notes.get("1.0", "end")
                root.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
                def capture():
                    try:
                        screenshot(hwnd, args.screenshot)
                    except Exception as exc:
                        failures.append(exc)
                    finally:
                        captured.set()
                threading.Thread(target=capture, daemon=True).start()
                finish()
            except Exception as exc:
                failures.append(exc)
                app.close()

        def finish():
            if not captured.is_set():
                root.after(50, finish)
                return
            app.clear_match()
            assert app.chat_text.get("1.0", "end-1c") == ""
            print("Chat UI smoke passed: searchable cached transcript, scroll, note isolation, clear and screenshot")
            app.close()

        root.after(500, exercise)
        root.after(30000, app.close)
        root.mainloop()
        if failures:
            raise failures[0]


if __name__ == "__main__":
    main()
